"""
Main Screener Orchestration
Ties together data fetching, technical analysis, fundamental analysis,
VCP detection, and scoring into a single run.
"""

import logging
from typing import Optional

import pandas as pd
from tqdm import tqdm

from screener.data_fetcher import DataFetcher
from screener.technical import TechnicalAnalyzer, compute_rs_ratings, compute_atr
from screener.fundamental import FundamentalAnalyzer
from screener.vcp import VCPDetector

logger = logging.getLogger(__name__)


class MinerviniScreener:
    """
    Runs the full Minervini SEPA screening process on a universe of stocks.
    """

    def __init__(self, config: dict):
        self.config = config
        uni_cfg = config.get("UNIVERSE", {})
        out_cfg = config.get("OUTPUT", {})
        score_cfg = config.get("SCORING", {})
        risk_cfg = config.get("RISK", {})

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
        self.fund_analyzer = FundamentalAnalyzer(cfg=config.get("FUNDAMENTALS"))
        self.vcp_detector = VCPDetector(
            cfg=config.get("VCP"),
            vol_cfg=config.get("VOLUME"),
        )
        self.scoring_weights = score_cfg
        self.min_price = risk_cfg.get("min_price", 10.0)
        self.sort_by = out_cfg.get("sort_by", "rs_rating")
        self.sort_asc = out_cfg.get("sort_ascending", False)

    def run(self, tickers: list[str], verbose: bool = True) -> tuple[list[dict], list[dict]]:
        """
        Run the screener on a list of tickers.

        Returns:
            (passed_results, all_results)
            - passed_results: stocks that passed all mandatory criteria
            - all_results: all stocks with their analysis (for statistics)
        """
        if verbose:
            print(f"\n  Fetching price data for {len(tickers)} stocks...")

        # ── Phase 1: Fetch all price data ────────────────────────────────
        with tqdm(total=len(tickers), desc="  Price data", unit="stock",
                  disable=not verbose) as pbar:
            price_data = self.data_fetcher.batch_fetch_prices(
                tickers, period="2y",
                progress_callback=pbar.update
            )

        # ── Phase 2: Fetch benchmark (SPY) ───────────────────────────────
        benchmark_df = self.data_fetcher.get_benchmark_history("SPY", period="2y")

        # ── Phase 3: Compute RS Ratings (universe-relative percentile) ───
        if verbose:
            print(f"  Computing RS ratings for {len(price_data)} stocks...")
        rs_ratings = compute_rs_ratings(price_data)

        # ── Phase 4: Technical screening (fast, no additional API calls) ─
        if verbose:
            print("  Running technical analysis...")

        tech_pass_tickers = []
        all_tech_results = {}

        for ticker, df in price_data.items():
            if df is None or len(df) < 50:
                continue
            current_price = float(df["Close"].iloc[-1])
            if current_price < self.min_price:
                continue

            # Inject pre-computed RS rating
            raw_rs_scores = list(rs_ratings.values())
            tech_result = self.tech_analyzer.analyze(
                ticker=ticker,
                df=df,
                benchmark_df=benchmark_df,
                all_rs_scores=raw_rs_scores,
            )
            # Override with percentile-ranked RS rating
            if ticker in rs_ratings:
                tech_result.rs_rating = rs_ratings[ticker]
                tech_result.c10_rs_rating = (
                    tech_result.rs_rating >= self.config["TREND_TEMPLATE"]["rs_rating_min"]
                )

            all_tech_results[ticker] = tech_result

            if tech_result.passes_all:
                tech_pass_tickers.append(ticker)

        if verbose:
            print(f"  Trend Template passed: {len(tech_pass_tickers)} stocks")

        # ── Phase 5: Fundamental analysis (only for tech-passing stocks) ─
        if verbose:
            print(f"  Fetching fundamentals for {len(tech_pass_tickers)} stocks...")

        with tqdm(total=len(tech_pass_tickers), desc="  Fundamentals", unit="stock",
                  disable=not verbose) as pbar:
            fund_data = self.data_fetcher.batch_fetch_fundamentals(
                tech_pass_tickers,
                progress_callback=pbar.update
            )

        # ── Phase 6: Apply fundamental filters + VCP detection ───────────
        all_results = []
        passed_results = []

        if verbose:
            print("  Applying fundamental filters and VCP detection...")

        for ticker in tech_pass_tickers:
            tech_result = all_tech_results[ticker]
            fund_info = fund_data.get(ticker, {})
            df = price_data.get(ticker)

            # Fundamental analysis
            fund_result = self.fund_analyzer.analyze(ticker, fund_info)

            # VCP detection
            vcp_result = self.vcp_detector.detect(df) if df is not None else None

            # Scoring
            score = self._compute_score(tech_result, fund_result, vcp_result)

            result = {
                "ticker":   ticker,
                "score":    score,
                "sector":   fund_info.get("sector") or "",
                "industry": fund_info.get("industry") or "",
                "technical":   tech_result.to_dict(),
                "fundamental": fund_result.to_dict(),
                "vcp":         vcp_result.to_dict() if vcp_result else {},
            }

            all_results.append(result)

            if fund_result.passes_mandatory:
                passed_results.append(result)

        # Also include non-tech-passing stocks in all_results for statistics
        for ticker, tech_result in all_tech_results.items():
            if ticker not in tech_pass_tickers:
                all_results.append({
                    "ticker": ticker,
                    "score": 0,
                    "technical": tech_result.to_dict(),
                    "fundamental": {},
                    "vcp": {},
                })

        # ── Phase 7: Sort results ─────────────────────────────────────────
        passed_results = self._sort_results(passed_results)

        return passed_results, all_results

    def _compute_score(self, tech, fund, vcp) -> float:
        """
        Compute a composite score (0-100) for ranking.
        """
        w = self.scoring_weights
        score = 0.0

        # RS Rating (0-99 → 0-100)
        rs = tech.rs_rating if tech.rs_rating else 0
        score += (rs / 99.0) * 100 * w.get("rs_rating", 0.30)

        # EPS growth
        eps_g = fund.eps_growth_current_qtr
        if eps_g is not None:
            eps_score = min(100, max(0, eps_g * 100))  # 100% growth → score 100
            score += eps_score * w.get("eps_growth", 0.20)

        # Sales growth
        sales_g = fund.sales_growth_current_qtr
        if sales_g is not None:
            sales_score = min(100, max(0, sales_g * 100))
            score += sales_score * w.get("sales_growth", 0.15)

        # VCP quality
        if vcp and vcp.detected:
            score += vcp.pattern_quality * w.get("vcp_quality", 0.20)

        # Volume accumulation
        acc_ratio = tech.acc_dist_ratio
        vol_score = min(100, max(0, (acc_ratio - 0.5) * 100))
        score += vol_score * w.get("volume_trend", 0.15)

        return round(min(100, max(0, score)), 1)

    def _sort_results(self, results: list[dict]) -> list[dict]:
        """Sort results by the configured sort field."""
        sort_field = self.sort_by

        def get_sort_key(r):
            if sort_field == "rs_rating":
                return r.get("technical", {}).get("rs_rating", 0)
            if sort_field == "score":
                return r.get("score", 0)
            if sort_field == "eps_growth":
                return r.get("fundamental", {}).get("eps_growth_current_qtr_pct", 0) or 0
            if sort_field == "vcp_quality":
                return r.get("vcp", {}).get("vcp_pattern_quality", 0) or 0
            return r.get("score", 0)

        return sorted(results, key=get_sort_key, reverse=not self.sort_asc)
