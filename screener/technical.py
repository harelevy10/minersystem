"""
Technical Analysis — Minervini Trend Template & Stage 2 Analysis

Implements all 8 criteria of the Minervini Trend Template plus:
- Relative Strength (RS) Rating calculation
- Stage analysis
- Volume accumulation/distribution score
- RS Line trend
"""

import numpy as np
import pandas as pd
from typing import Optional
from dataclasses import dataclass, field

from config import TREND_TEMPLATE, RS_CALCULATION, VOLUME, RISK, SHORT_TREND_TEMPLATE


@dataclass
class TrendTemplateResult:
    """Result of the Trend Template evaluation."""
    # Individual criterion pass/fail
    c1_price_above_sma150: bool = False   # Price > 150-day SMA
    c2_price_above_sma200: bool = False   # Price > 200-day SMA
    c3_sma150_above_sma200: bool = False  # 150 SMA > 200 SMA
    c4_sma200_trending_up: bool = False   # 200 SMA trending up ≥ 1 month
    c5_sma50_above_sma150: bool = False   # 50 SMA > 150 SMA
    c6_sma50_above_sma200: bool = False   # 50 SMA > 200 SMA
    c7_price_above_sma50: bool = False    # Price > 50 SMA
    c8_above_52wk_low: bool = False       # Price ≥ 125% of 52-week low
    c9_near_52wk_high: bool = False       # Price within 25% of 52-week high
    c10_rs_rating: bool = False           # RS Rating ≥ 70

    # Short (inverse) Trend Template — Stage 4 breakdown candidate
    s1_price_below_sma150: bool = False
    s2_price_below_sma200: bool = False
    s3_sma150_below_sma200: bool = False
    s4_sma200_trending_down: bool = False
    s5_sma50_below_sma150: bool = False
    s6_sma50_below_sma200: bool = False
    s7_price_below_sma50: bool = False
    s8_near_52wk_low: bool = False        # within 25% of 52-week low
    s9_far_from_52wk_high: bool = False   # ≥25% below 52-week high
    s10_rs_weak: bool = False             # RS Rating ≤ 30

    # Computed values
    current_price: float = 0.0
    sma_50: float = 0.0
    sma_150: float = 0.0
    sma_200: float = 0.0
    sma_200_slope: float = 0.0
    week_52_high: float = 0.0
    week_52_low: float = 0.0
    pct_from_52wk_high: float = 0.0
    pct_above_52wk_low: float = 0.0
    rs_rating: float = 0.0
    rs_line_trending_up: bool = False
    stage: int = 0

    # Accumulation/Distribution
    acc_dist_ratio: float = 0.0
    volume_trend: str = "neutral"        # "accumulation", "distribution", "neutral"

    @property
    def passes_all(self) -> bool:
        return all([
            self.c1_price_above_sma150,
            self.c2_price_above_sma200,
            self.c3_sma150_above_sma200,
            self.c4_sma200_trending_up,
            self.c5_sma50_above_sma150,
            self.c6_sma50_above_sma200,
            self.c7_price_above_sma50,
            self.c8_above_52wk_low,
            self.c9_near_52wk_high,
            self.c10_rs_rating,
        ])

    @property
    def criteria_passed(self) -> int:
        return sum([
            self.c1_price_above_sma150,
            self.c2_price_above_sma200,
            self.c3_sma150_above_sma200,
            self.c4_sma200_trending_up,
            self.c5_sma50_above_sma150,
            self.c6_sma50_above_sma200,
            self.c7_price_above_sma50,
            self.c8_above_52wk_low,
            self.c9_near_52wk_high,
            self.c10_rs_rating,
        ])

    @property
    def passes_short_all(self) -> bool:
        return all([
            self.s1_price_below_sma150,
            self.s2_price_below_sma200,
            self.s3_sma150_below_sma200,
            self.s4_sma200_trending_down,
            self.s5_sma50_below_sma150,
            self.s6_sma50_below_sma200,
            self.s7_price_below_sma50,
            self.s8_near_52wk_low,
            self.s9_far_from_52wk_high,
            self.s10_rs_weak,
        ])

    @property
    def short_criteria_passed(self) -> int:
        return sum([
            self.s1_price_below_sma150,
            self.s2_price_below_sma200,
            self.s3_sma150_below_sma200,
            self.s4_sma200_trending_down,
            self.s5_sma50_below_sma150,
            self.s6_sma50_below_sma200,
            self.s7_price_below_sma50,
            self.s8_near_52wk_low,
            self.s9_far_from_52wk_high,
            self.s10_rs_weak,
        ])

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "current_price": round(self.current_price, 2),
            "sma_50": round(self.sma_50, 2),
            "sma_150": round(self.sma_150, 2),
            "sma_200": round(self.sma_200, 2),
            "week_52_high": round(self.week_52_high, 2),
            "week_52_low": round(self.week_52_low, 2),
            "pct_from_52wk_high": round(self.pct_from_52wk_high * 100, 1),
            "pct_above_52wk_low": round(self.pct_above_52wk_low * 100, 1),
            "rs_rating": round(self.rs_rating, 1),
            "rs_line_trending_up": self.rs_line_trending_up,
            "volume_trend": self.volume_trend,
            "acc_dist_ratio": round(self.acc_dist_ratio, 2),
            "criteria_passed": f"{self.criteria_passed}/10",
            "passes_trend_template": self.passes_all,
            # Individual criteria
            "c1_price_above_sma150": self.c1_price_above_sma150,
            "c2_price_above_sma200": self.c2_price_above_sma200,
            "c3_sma150_above_sma200": self.c3_sma150_above_sma200,
            "c4_sma200_trending_up": self.c4_sma200_trending_up,
            "c5_sma50_above_sma150": self.c5_sma50_above_sma150,
            "c6_sma50_above_sma200": self.c6_sma50_above_sma200,
            "c7_price_above_sma50": self.c7_price_above_sma50,
            "c8_above_52wk_low": self.c8_above_52wk_low,
            "c9_near_52wk_high": self.c9_near_52wk_high,
            "c10_rs_rating": self.c10_rs_rating,
            # Short (inverse) Trend Template
            "short_criteria_passed": f"{self.short_criteria_passed}/10",
            "passes_short_trend_template": self.passes_short_all,
            "s1_price_below_sma150": self.s1_price_below_sma150,
            "s2_price_below_sma200": self.s2_price_below_sma200,
            "s3_sma150_below_sma200": self.s3_sma150_below_sma200,
            "s4_sma200_trending_down": self.s4_sma200_trending_down,
            "s5_sma50_below_sma150": self.s5_sma50_below_sma150,
            "s6_sma50_below_sma200": self.s6_sma50_below_sma200,
            "s7_price_below_sma50": self.s7_price_below_sma50,
            "s8_near_52wk_low": self.s8_near_52wk_low,
            "s9_far_from_52wk_high": self.s9_far_from_52wk_high,
            "s10_rs_weak": self.s10_rs_weak,
        }


class TechnicalAnalyzer:
    """
    Performs all technical analysis required by the Minervini SEPA system.
    """

    def __init__(self, cfg_trend: dict = None, cfg_rs: dict = None,
                 cfg_volume: dict = None, cfg_short: dict = None):
        self.cfg = cfg_trend or TREND_TEMPLATE
        self.rs_cfg = cfg_rs or RS_CALCULATION
        self.vol_cfg = cfg_volume or VOLUME
        self.short_cfg = cfg_short or SHORT_TREND_TEMPLATE

    # ─────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────────────

    def analyze(self, ticker: str, df: pd.DataFrame,
                benchmark_df: Optional[pd.DataFrame] = None,
                all_rs_scores: Optional[list] = None) -> TrendTemplateResult:
        """
        Run the full Minervini Trend Template analysis on a stock.

        Args:
            ticker: Ticker symbol (for logging)
            df: OHLCV DataFrame (daily, index=Date)
            benchmark_df: SPY price history for RS calculation
            all_rs_scores: Pre-computed raw RS scores for all stocks (for percentile ranking)

        Returns:
            TrendTemplateResult with all criteria evaluated
        """
        result = TrendTemplateResult()

        if df is None or len(df) < self.cfg["sma_200"] + 5:
            return result

        df = df.copy().sort_index()
        close = df["Close"]
        volume = df["Volume"]

        # ── Moving averages ──────────────────────────────────────────────────
        sma_50 = close.rolling(self.cfg["sma_50"]).mean()
        sma_150 = close.rolling(self.cfg["sma_150"]).mean()
        sma_200 = close.rolling(self.cfg["sma_200"]).mean()

        current_price = float(close.iloc[-1])
        cur_sma50 = float(sma_50.iloc[-1])
        cur_sma150 = float(sma_150.iloc[-1])
        cur_sma200 = float(sma_200.iloc[-1])

        if any(np.isnan([current_price, cur_sma50, cur_sma150, cur_sma200])):
            return result

        result.current_price = current_price
        result.sma_50 = cur_sma50
        result.sma_150 = cur_sma150
        result.sma_200 = cur_sma200

        # ── 52-week high / low ───────────────────────────────────────────────
        days_252 = min(252, len(close))
        high_52 = float(close.iloc[-days_252:].max())
        low_52 = float(close.iloc[-days_252:].min())
        result.week_52_high = high_52
        result.week_52_low = low_52
        result.pct_from_52wk_high = (high_52 - current_price) / high_52 if high_52 > 0 else 1.0
        result.pct_above_52wk_low = (current_price - low_52) / low_52 if low_52 > 0 else 0.0

        # ── Trend Template Criteria ──────────────────────────────────────────
        # C1: Price > 150-day SMA
        result.c1_price_above_sma150 = current_price > cur_sma150

        # C2: Price > 200-day SMA
        result.c2_price_above_sma200 = current_price > cur_sma200

        # C3: 150-day SMA > 200-day SMA
        result.c3_sma150_above_sma200 = cur_sma150 > cur_sma200

        # C4: 200-day SMA trending up for at least 1 month (20 trading days)
        trend_days = self.cfg["sma_200_trend_days"]
        if len(sma_200.dropna()) >= trend_days + 1:
            sma200_prev = float(sma_200.dropna().iloc[-trend_days - 1])
            result.sma_200_slope = (cur_sma200 - sma200_prev) / sma200_prev
            result.c4_sma200_trending_up = cur_sma200 > sma200_prev
            result.s4_sma200_trending_down = cur_sma200 < sma200_prev
        else:
            result.c4_sma200_trending_up = False
            result.s4_sma200_trending_down = False

        # C5: 50-day SMA > 150-day SMA
        result.c5_sma50_above_sma150 = cur_sma50 > cur_sma150

        # C6: 50-day SMA > 200-day SMA
        result.c6_sma50_above_sma200 = cur_sma50 > cur_sma200

        # C7: Price > 50-day SMA
        result.c7_price_above_sma50 = current_price > cur_sma50

        # C8: Price at least 25% above 52-week low
        result.c8_above_52wk_low = result.pct_above_52wk_low >= self.cfg["pct_above_52wk_low"]

        # C9: Price within 25% of 52-week high
        result.c9_near_52wk_high = result.pct_from_52wk_high <= self.cfg["pct_from_52wk_high"]

        # ── Short (inverse) Trend Template — mirrors C1-C9 for Stage 4 breakdowns ──
        result.s1_price_below_sma150 = current_price < cur_sma150
        result.s2_price_below_sma200 = current_price < cur_sma200
        result.s3_sma150_below_sma200 = cur_sma150 < cur_sma200
        result.s5_sma50_below_sma150 = cur_sma50 < cur_sma150
        result.s6_sma50_below_sma200 = cur_sma50 < cur_sma200
        result.s7_price_below_sma50 = current_price < cur_sma50
        result.s8_near_52wk_low = result.pct_above_52wk_low <= self.cfg["pct_above_52wk_low"]
        result.s9_far_from_52wk_high = result.pct_from_52wk_high >= self.cfg["pct_from_52wk_high"]

        # ── Relative Strength Rating ─────────────────────────────────────────
        raw_rs = self._compute_raw_rs_score(close)
        result.rs_rating = raw_rs  # Will be percentile-ranked later if all_rs_scores provided

        if all_rs_scores is not None and len(all_rs_scores) > 0:
            result.rs_rating = _percentile_rank(raw_rs, all_rs_scores)

        result.c10_rs_rating = result.rs_rating >= self.cfg["rs_rating_min"]
        result.s10_rs_weak = result.rs_rating <= self.short_cfg["rs_rating_max"]

        # ── RS Line Trend (price relative to SPY) ───────────────────────────
        if benchmark_df is not None and not benchmark_df.empty:
            result.rs_line_trending_up = self._rs_line_trending(close, benchmark_df["Close"])

        # ── Accumulation / Distribution ─────────────────────────────────────
        result.acc_dist_ratio, result.volume_trend = self._acc_dist_score(
            close, volume, self.vol_cfg["acc_dist_lookback"]
        )

        # ── Stage Determination ──────────────────────────────────────────────
        result.stage = self._determine_stage(
            current_price, cur_sma50, cur_sma150, cur_sma200,
            sma_200.dropna()
        )

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # RS Rating
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_raw_rs_score(self, close: pd.Series) -> float:
        """
        Compute Minervini's weighted RS score (proxy for IBD RS Rating).
        Weights: Q4=40%, Q3=20%, Q2=20%, Q1=20%
        Each quarter is the % price change over that 63-day period.
        """
        n = len(close)
        if n < 252:
            return 0.0

        w = self.rs_cfg
        q4 = _pct_change(close, 0, 63)    # most recent quarter
        q3 = _pct_change(close, 63, 126)
        q2 = _pct_change(close, 126, 189)
        q1 = _pct_change(close, 189, 252)

        if any(v is None for v in [q4, q3, q2, q1]):
            return 0.0

        return (q4 * w["q4_weight"] + q3 * w["q3_weight"] +
                q2 * w["q2_weight"] + q1 * w["q1_weight"])

    def _rs_line_trending(self, stock_close: pd.Series,
                          bench_close: pd.Series) -> bool:
        """
        Check if the RS Line (stock / benchmark) is trending up.
        RS Line trending up = stock outperforming benchmark.
        """
        trend_days = self.rs_cfg["rs_line_trend_days"]
        try:
            # Align on common dates
            combined = pd.concat([stock_close, bench_close], axis=1,
                                  join="inner")
            if len(combined) < trend_days + 1:
                return False
            rs_line = combined.iloc[:, 0] / combined.iloc[:, 1]
            rs_sma = rs_line.rolling(trend_days).mean()
            return float(rs_line.iloc[-1]) > float(rs_sma.iloc[-1])
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Accumulation / Distribution
    # ─────────────────────────────────────────────────────────────────────────

    def _acc_dist_score(self, close: pd.Series, volume: pd.Series,
                        lookback: int = 25) -> tuple[float, str]:
        """
        Compare total volume on up-days vs down-days over 'lookback' days.
        Ratio > 1 = accumulation, < 1 = distribution.
        """
        if len(close) < lookback + 1:
            return 1.0, "neutral"

        recent_close = close.iloc[-lookback:]
        recent_vol = volume.iloc[-lookback:]

        changes = recent_close.diff()
        up_vol = float(recent_vol[changes > 0].sum())
        down_vol = float(recent_vol[changes < 0].sum())

        if down_vol == 0:
            ratio = 2.0
        else:
            ratio = up_vol / down_vol

        if ratio >= 1.3:
            trend = "accumulation"
        elif ratio <= 0.7:
            trend = "distribution"
        else:
            trend = "neutral"

        return round(ratio, 2), trend

    # ─────────────────────────────────────────────────────────────────────────
    # Stage Analysis
    # ─────────────────────────────────────────────────────────────────────────

    def _determine_stage(self, price: float, sma50: float, sma150: float,
                         sma200: float, sma200_series: pd.Series) -> int:
        """
        Determine Minervini / Weinstein stage:
        Stage 1: Basing (flat, below or at MAs)
        Stage 2: Advancing (price and MAs in bullish alignment)
        Stage 3: Topping (price weakening relative to MAs)
        Stage 4: Declining (price below all MAs, MAs declining)
        """
        # Check if 200 SMA is trending up
        sma200_up = (len(sma200_series) >= 20 and
                     float(sma200_series.iloc[-1]) > float(sma200_series.iloc[-20]))

        # Stage 2: Full bullish alignment
        if (price > sma50 > sma150 > sma200 and sma200_up):
            return 2

        # Stage 4: Full bearish alignment
        if (price < sma50 < sma150 < sma200 and not sma200_up):
            return 4

        # Stage 3: Price weakening but MAs still ascending
        if (price < sma50 and sma50 > sma150 and sma200_up):
            return 3

        # Stage 3/4 transition
        if (price < sma50 and price < sma150 and sma200_up):
            return 3

        # Stage 1: Basing / Stage 2 early
        if (sma200_up and price > sma200):
            return 1  # Potentially Stage 1/2 transition — not confirmed Stage 2

        return 4  # Default to Stage 4 if unclear


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def _pct_change(close: pd.Series, start_offset: int, end_offset: int) -> Optional[float]:
    """Calculate % price change between two historical offsets from the end."""
    n = len(close)
    try:
        end_price = float(close.iloc[-(start_offset + 1)])
        start_price = float(close.iloc[-(end_offset)])
        if start_price <= 0:
            return None
        return (end_price - start_price) / start_price
    except (IndexError, ZeroDivisionError):
        return None


def _percentile_rank(value: float, all_values: list) -> float:
    """Return the percentile rank of 'value' within 'all_values' (0-99 scale)."""
    if not all_values:
        return 50.0
    arr = np.array(all_values)
    pct = float(np.sum(arr <= value)) / len(arr) * 99
    return round(pct, 1)


def compute_rs_ratings(price_data: dict[str, pd.DataFrame]) -> dict[str, float]:
    """
    Compute RS ratings for all stocks, percentile-ranked against each other.
    This is the proper way to compute RS Rating (relative to all stocks in universe).

    Args:
        price_data: dict of ticker -> OHLCV DataFrame

    Returns:
        dict of ticker -> RS Rating (0-99)
    """
    analyzer = TechnicalAnalyzer()
    raw_scores = {}

    for ticker, df in price_data.items():
        if df is not None and len(df) >= 252:
            raw = analyzer._compute_raw_rs_score(df["Close"])
            raw_scores[ticker] = raw

    if not raw_scores:
        return {}

    all_raw = list(raw_scores.values())
    rs_ratings = {
        ticker: _percentile_rank(score, all_raw)
        for ticker, score in raw_scores.items()
    }
    return rs_ratings


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Compute Average True Range (ATR) as a volatility measure."""
    if len(df) < period + 1:
        return 0.0
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])
