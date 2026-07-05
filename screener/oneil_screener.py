"""
CAN SLIM (William O'Neil / IBD) Screener Orchestrator
=====================================================
Mirror of MinerviniScreener but runs O'Neil's CAN SLIM methodology.

Pipeline:
    1. Fetch price history (reuses DataFetcher + cache)
    2. Assess general market direction (M) — run once on SPY/QQQ
    3. Compute universe-relative RS ratings
    4. Run technical pre-screen (reuses Minervini's TechnicalAnalyzer for RS/stage)
    5. Fetch fundamentals for surviving tickers
    6. Evaluate CAN SLIM criteria per stock
    7. Detect base patterns (Cup & Handle / Flat Base / Double Bottom)
    8. Score and sort
"""

import logging

import pandas as pd
from tqdm import tqdm

from screener.data_fetcher import DataFetcher
from screener.technical import TechnicalAnalyzer, compute_rs_ratings
from screener.oneil import (
    CANSLIMAnalyzer, BasePatternDetector,
    assess_market_direction, MarketDirection,
)

logger = logging.getLogger(__name__)


class CANSLIMScreener:
    """Runs the full CAN SLIM screen on a universe of tickers."""

    def __init__(self, config: dict):
        self.config = config
        uni_cfg = config.get("UNIVERSE", {})
        canslim_cfg = config.get("CAN_SLIM", {})

        self.data_fetcher = DataFetcher(
            cache_dir=uni_cfg.get("cache_dir", "cache/"),
            cache_ttl_hours=uni_cfg.get("cache_ttl_hours", 4),
            api_delay=uni_cfg.get("api_delay", 0.1),
            max_workers=uni_cfg.get("max_workers", 10),
        )
        self.tech_analyzer = TechnicalAnalyzer(
            cfg_trend=config.get("TREND_TEMPLATE"),
            cfg_rs=config.get("RS_CALCULATION"),
            cfg_volume=config.get("VOLUME"),
        )
        self.canslim = CANSLIMAnalyzer(cfg=canslim_cfg)
        self.base_detector = BasePatternDetector(cfg=config.get("BASE_PATTERNS"))
        self.scoring_weights = config.get("CAN_SLIM_SCORING", {})
        self.min_price = canslim_cfg.get("min_price", 15.0)
        self.min_market_cap = canslim_cfg.get("min_market_cap", 300_000_000)
        self.min_avg_volume = canslim_cfg.get("min_avg_volume", 400_000)

    def run(self, tickers: list[str], verbose: bool = True
            ) -> tuple[list[dict], list[dict], MarketDirection]:
        """
        Returns:
            passed_results  — stocks passing CAN SLIM
            all_results     — every ticker analyzed (for stats)
            market          — MarketDirection assessment (global)
        """
        if verbose:
            print(f"\n  Fetching price data for {len(tickers)} stocks...")

        # ── Phase 1: price data ──────────────────────────────────────────────
        with tqdm(total=len(tickers), desc="  Price data", unit="stock",
                  disable=not verbose) as pbar:
            price_data = self.data_fetcher.batch_fetch_prices(
                tickers, period="2y", progress_callback=pbar.update
            )

        # ── Phase 2: Market direction (M) — SPY + QQQ ────────────────────────
        spy = self.data_fetcher.get_benchmark_history("SPY", period="2y")
        qqq = self.data_fetcher.get_benchmark_history("QQQ", period="2y")
        market = assess_market_direction(spy, qqq)

        if verbose:
            print(f"  Market direction: {market.status.upper()} "
                  f"(distribution days: {market.distribution_days_last_25})")

        # ── Phase 3: RS ratings ──────────────────────────────────────────────
        if verbose:
            print(f"  Computing RS ratings for {len(price_data)} stocks...")
        rs_ratings = compute_rs_ratings(price_data)

        # ── Phase 4: technical pre-screen (L + N use tech outputs) ───────────
        if verbose:
            print("  Running technical analysis...")

        tech_results = {}
        survivors = []
        all_raw = list(rs_ratings.values())
        l_rs_min = self.canslim.cfg["l_rs_rating_min"]

        for ticker, df in price_data.items():
            if df is None or len(df) < 50:
                continue
            price = float(df["Close"].iloc[-1])
            if price < self.min_price:
                continue

            tech = self.tech_analyzer.analyze(
                ticker=ticker, df=df, benchmark_df=spy, all_rs_scores=all_raw
            )
            if ticker in rs_ratings:
                tech.rs_rating = rs_ratings[ticker]
                tech.c10_rs_rating = tech.rs_rating >= l_rs_min

            tech_results[ticker] = tech

            # Gate to fundamentals: must have RS >= 70 AND near 52wk high or Stage 2
            near_high = tech.pct_from_52wk_high <= 0.20
            if tech.rs_rating >= 70 and (near_high or tech.stage == 2):
                survivors.append(ticker)

        if verbose:
            print(f"  Technical pre-screen passed: {len(survivors)} stocks")

        # ── Phase 5: fundamentals ────────────────────────────────────────────
        if verbose:
            print(f"  Fetching fundamentals for {len(survivors)} stocks...")

        with tqdm(total=len(survivors), desc="  Fundamentals", unit="stock",
                  disable=not verbose) as pbar:
            fund_data = self.data_fetcher.batch_fetch_fundamentals(
                survivors, progress_callback=pbar.update
            )

        # ── Phase 6: evaluate CAN SLIM + base patterns ───────────────────────
        if verbose:
            print("  Evaluating CAN SLIM criteria and base patterns...")

        passed_results, all_results = [], []

        for ticker in survivors:
            tech = tech_results[ticker]
            info = fund_data.get(ticker, {})
            df = price_data.get(ticker)

            # Liquidity gate
            market_cap = info.get("marketCap") or 0
            avg_vol = info.get("averageVolume") or 0
            if market_cap < self.min_market_cap or avg_vol < self.min_avg_volume:
                continue

            canslim_result = self.canslim.analyze(
                ticker=ticker, df=df, info=info,
                tech_result=tech, market=market,
            )
            base = self.base_detector.detect(df)
            score = self._compute_score(canslim_result, base, tech)

            result = {
                "ticker":   ticker,
                "score":    score,
                "sector":   info.get("sector") or "",
                "industry": info.get("industry") or "",
                "technical":   tech.to_dict(),
                "canslim":     canslim_result.to_dict(),
                "base":        base.to_dict(),
            }
            all_results.append(result)

            if canslim_result.passes_all:
                passed_results.append(result)

        passed_results.sort(key=lambda r: r.get("score", 0), reverse=True)
        return passed_results, all_results, market

    def _compute_score(self, cs, base, tech) -> float:
        """Composite 0-100 score for ranking CAN SLIM candidates."""
        w = self.scoring_weights
        score = 0.0

        score += (cs.rs_rating / 99.0) * 100 * w.get("rs_rating", 0.25)

        if cs.eps_growth_current_qtr is not None:
            score += min(100, cs.eps_growth_current_qtr * 100) * w.get("eps_growth", 0.20)

        if cs.sales_growth is not None:
            score += min(100, max(0, cs.sales_growth * 100)) * w.get("sales_growth", 0.10)

        if cs.annual_eps_growth_3yr:
            avg_annual = sum(cs.annual_eps_growth_3yr) / len(cs.annual_eps_growth_3yr)
            score += min(100, avg_annual * 100) * w.get("annual_eps", 0.10)

        if base.detected:
            score += base.quality_score * w.get("base_quality", 0.20)

        if cs.institutional_ownership is not None:
            # Sweet spot around 50-70%
            inst_score = max(0, 100 - abs(cs.institutional_ownership - 0.60) * 200)
            score += inst_score * w.get("institutional", 0.05)

        vol_score = min(100, max(0, (cs.acc_dist_ratio - 0.5) * 100))
        score += vol_score * w.get("volume_trend", 0.10)

        return round(min(100, max(0, score)), 1)
