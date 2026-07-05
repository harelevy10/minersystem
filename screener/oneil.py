"""
William O'Neil / IBD — CAN SLIM Analyzer
=========================================
Implements the 7 CAN SLIM criteria from "How to Make Money in Stocks":

  C — Current quarterly EPS growth (≥ 25% YoY, acceleration preferred)
  A — Annual EPS growth (≥ 25% each of last 3 years) + ROE ≥ 17%
  N — New: price near 52-week high / new product / breakout from sound base
  S — Supply & Demand: small float preferred, volume surge on up days
  L — Leader (not laggard): RS Rating ≥ 80
  I — Institutional sponsorship: rising, but not over-owned
  M — Market direction: general market (SPY/QQQ) in confirmed uptrend

Plus base pattern detection: Cup & Handle, Flat Base, Double Bottom.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Market Direction — M in CAN SLIM (run once per screen, not per stock)
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class MarketDirection:
    status: str = "unknown"           # "uptrend" | "correction" | "downtrend" | "unknown"
    spy_above_sma50: bool = False
    spy_above_sma200: bool = False
    spy_sma50_above_sma200: bool = False
    qqq_above_sma50: bool = False
    qqq_above_sma200: bool = False
    distribution_days_last_25: int = 0   # days with >0.2% drop on rising volume
    confirmed_uptrend: bool = False

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "confirmed_uptrend": self.confirmed_uptrend,
            "spy_above_sma50": self.spy_above_sma50,
            "spy_above_sma200": self.spy_above_sma200,
            "spy_sma50_above_sma200": self.spy_sma50_above_sma200,
            "qqq_above_sma50": self.qqq_above_sma50,
            "qqq_above_sma200": self.qqq_above_sma200,
            "distribution_days_last_25": self.distribution_days_last_25,
        }


def assess_market_direction(
    spy_df: Optional[pd.DataFrame],
    qqq_df: Optional[pd.DataFrame] = None,
    cfg: Optional[dict] = None,
) -> MarketDirection:
    """
    Determine whether the general market is in a confirmed uptrend.
    O'Neil: never buy in a bear market — wait for a follow-through day and
    confirmed uptrend on the major indices.
    """
    md = MarketDirection()

    def _analyse(df: pd.DataFrame) -> tuple[bool, bool, bool]:
        close = df["Close"]
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        price = float(close.iloc[-1])
        return (
            price > float(sma50) if not pd.isna(sma50) else False,
            price > float(sma200) if not pd.isna(sma200) else False,
            float(sma50) > float(sma200) if not (pd.isna(sma50) or pd.isna(sma200)) else False,
        )

    if spy_df is not None and len(spy_df) >= 200:
        md.spy_above_sma50, md.spy_above_sma200, md.spy_sma50_above_sma200 = _analyse(spy_df)
        md.distribution_days_last_25 = _count_distribution_days(spy_df, lookback=25)

    if qqq_df is not None and len(qqq_df) >= 200:
        md.qqq_above_sma50, md.qqq_above_sma200, _ = _analyse(qqq_df)

    uptrend = (md.spy_above_sma50 and md.spy_above_sma200 and
               md.spy_sma50_above_sma200 and md.distribution_days_last_25 <= 5)

    md.confirmed_uptrend = uptrend
    if uptrend:
        md.status = "uptrend"
    elif md.spy_above_sma200:
        md.status = "correction"
    else:
        md.status = "downtrend"

    return md


def _count_distribution_days(df: pd.DataFrame, lookback: int = 25) -> int:
    """A distribution day = index drops >0.2% on higher volume than prior day."""
    if len(df) < lookback + 2:
        return 0
    recent = df.iloc[-lookback - 1:]
    close_chg = recent["Close"].pct_change()
    vol_chg = recent["Volume"].diff()
    dist = ((close_chg < -0.002) & (vol_chg > 0)).sum()
    return int(dist)


# ═════════════════════════════════════════════════════════════════════════════
# Base Pattern Detection — Cup & Handle, Flat Base, Double Bottom
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class BasePattern:
    detected: bool = False
    pattern: str = "none"             # "cup_handle" | "flat_base" | "double_bottom" | "none"
    pivot_price: float = 0.0           # buy point (breakout trigger)
    stop_price: float = 0.0            # O'Neil: 7-8% below pivot
    base_depth_pct: float = 0.0        # how deep the base correction was
    base_length_weeks: int = 0
    pct_from_pivot: float = 0.0        # current price distance from pivot (%)
    near_pivot: bool = False           # within 5% of pivot
    quality_score: float = 0.0         # 0-100 base quality

    def to_dict(self) -> dict:
        return {
            "base_detected":       self.detected,
            "base_pattern":        self.pattern,
            "base_pivot_price":    round(self.pivot_price, 2),
            "base_stop_price":     round(self.stop_price, 2),
            "base_depth_pct":      round(self.base_depth_pct * 100, 1),
            "base_length_weeks":   self.base_length_weeks,
            "base_pct_from_pivot": round(self.pct_from_pivot, 2),
            "base_near_pivot":     self.near_pivot,
            "base_quality_score":  round(self.quality_score, 1),
        }


class BasePatternDetector:
    """Detects O'Neil base patterns."""

    def __init__(self, cfg: dict = None):
        from config import BASE_PATTERNS
        self.cfg = cfg or BASE_PATTERNS

    def detect(self, df: pd.DataFrame) -> BasePattern:
        if df is None or len(df) < 50:
            return BasePattern()

        # Try patterns in order of preference — Cup & Handle is the gold standard
        for detector in (self._detect_cup_handle, self._detect_flat_base,
                          self._detect_double_bottom):
            pattern = detector(df)
            if pattern.detected:
                pattern.near_pivot = (
                    0 <= pattern.pct_from_pivot <= self.cfg["pivot_proximity_pct"] * 100
                )
                return pattern
        return BasePattern()

    # ── Cup & Handle ─────────────────────────────────────────────────────────
    def _detect_cup_handle(self, df: pd.DataFrame) -> BasePattern:
        """
        Cup & Handle: 12-35% correction forming a U, followed by a shallow
        handle that pulls back no more than ~15% in the upper half of the cup.
        """
        cfg = self.cfg
        min_days = cfg["cup_min_weeks"] * 5
        max_days = cfg["cup_max_weeks"] * 5
        close = df["Close"]
        high = df["High"]

        if len(close) < min_days + cfg["handle_min_days"]:
            return BasePattern()

        # Search for a cup in the last N days (scan window)
        window = min(max_days + cfg["handle_max_days"], len(close))
        recent = df.iloc[-window:]
        recent_close = recent["Close"]
        recent_high = recent["High"]

        # Left lip = max in first half of window
        half = len(recent) // 2
        left_section = recent_high.iloc[:half]
        if left_section.empty:
            return BasePattern()
        left_lip_idx = left_section.idxmax()
        try:
            left_lip_pos = recent.index.get_loc(left_lip_idx)
        except KeyError:
            return BasePattern()
        left_lip_price = float(recent_high.loc[left_lip_idx])

        # Cup bottom = lowest low after the left lip
        after_lip = recent.iloc[left_lip_pos + 1:]
        if len(after_lip) < cfg["handle_min_days"] + 10:
            return BasePattern()
        cup_low_idx = after_lip["Low"].idxmin()
        cup_low_price = float(after_lip["Low"].loc[cup_low_idx])

        depth = (left_lip_price - cup_low_price) / left_lip_price
        if depth < cfg["cup_min_depth_pct"] or depth > cfg["cup_max_depth_pct"]:
            return BasePattern()

        # Right lip = max close between cup low and current
        try:
            cup_low_pos = after_lip.index.get_loc(cup_low_idx)
        except KeyError:
            return BasePattern()
        after_cup = after_lip.iloc[cup_low_pos + 1:]
        if len(after_cup) < cfg["handle_min_days"]:
            return BasePattern()

        right_lip_price = float(after_cup["High"].max())
        # Right lip should approximate left lip (within 5%)
        if abs(right_lip_price - left_lip_price) / left_lip_price > 0.08:
            return BasePattern()

        # Handle forms after right lip — pullback in upper half of cup
        right_lip_idx = after_cup["High"].idxmax()
        try:
            right_lip_pos = after_cup.index.get_loc(right_lip_idx)
        except KeyError:
            return BasePattern()
        handle_section = after_cup.iloc[right_lip_pos + 1:]
        if len(handle_section) < cfg["handle_min_days"]:
            return BasePattern()

        handle_low = float(handle_section["Low"].min())
        handle_pullback = (right_lip_price - handle_low) / right_lip_price
        if handle_pullback > cfg["handle_max_depth_pct"]:
            return BasePattern()

        # Handle must be in upper half of cup
        cup_mid = (left_lip_price + cup_low_price) / 2
        if cfg["handle_upper_half"] and handle_low < cup_mid:
            return BasePattern()

        # Pivot = handle high + 10 cents (O'Neil's rule)
        pivot = float(handle_section["High"].max()) + 0.10
        current_price = float(close.iloc[-1])
        pct_from_pivot = (current_price - pivot) / pivot * 100

        base_days = left_lip_pos  # approximation
        base_weeks = max(cfg["cup_min_weeks"], int((len(recent) - base_days) / 5))

        quality = _base_quality_score(
            depth=depth, handle_pullback=handle_pullback,
            ideal_depth=0.20, ideal_handle=0.08, base_weeks=base_weeks
        )

        return BasePattern(
            detected=True,
            pattern="cup_handle",
            pivot_price=pivot,
            stop_price=pivot * 0.93,  # 7% stop
            base_depth_pct=depth,
            base_length_weeks=base_weeks,
            pct_from_pivot=pct_from_pivot,
            quality_score=quality,
        )

    # ── Flat Base ────────────────────────────────────────────────────────────
    def _detect_flat_base(self, df: pd.DataFrame) -> BasePattern:
        """
        Flat Base: 5+ weeks of sideways action within a tight range (<15%).
        Typically forms after an initial run-up — a consolidation base.
        """
        cfg = self.cfg
        min_days = cfg["flat_min_weeks"] * 5
        if len(df) < min_days + 10:
            return BasePattern()

        window = df.iloc[-min_days - 10:]
        hi = float(window["High"].max())
        lo = float(window["Low"].min())
        if hi <= 0:
            return BasePattern()

        range_pct = (hi - lo) / hi
        if range_pct > cfg["flat_max_range_pct"]:
            return BasePattern()

        # Must be consolidating after advance — price still near the high
        current_price = float(df["Close"].iloc[-1])
        if current_price < lo or current_price > hi * 1.02:
            return BasePattern()

        pivot = hi + 0.10
        pct_from_pivot = (current_price - pivot) / pivot * 100
        weeks = min_days // 5

        quality = _base_quality_score(
            depth=range_pct, handle_pullback=0, ideal_depth=0.08,
            ideal_handle=0, base_weeks=weeks
        )

        return BasePattern(
            detected=True,
            pattern="flat_base",
            pivot_price=pivot,
            stop_price=pivot * 0.93,
            base_depth_pct=range_pct,
            base_length_weeks=weeks,
            pct_from_pivot=pct_from_pivot,
            quality_score=quality,
        )

    # ── Double Bottom ────────────────────────────────────────────────────────
    def _detect_double_bottom(self, df: pd.DataFrame) -> BasePattern:
        """
        Double Bottom: two distinct lows, second undercutting the first slightly,
        separated by a middle peak. Pivot = middle peak high.
        """
        cfg = self.cfg
        min_days = cfg["db_min_weeks"] * 5
        if len(df) < min_days + 10:
            return BasePattern()

        window = df.iloc[-min_days - 20:]
        low_series = window["Low"]

        # First bottom = min in first third
        third = len(window) // 3
        first_bot_idx = low_series.iloc[:third].idxmin()
        first_bot_price = float(low_series.loc[first_bot_idx])
        try:
            first_pos = window.index.get_loc(first_bot_idx)
        except KeyError:
            return BasePattern()

        # Middle peak = max between first and last third
        middle = window.iloc[first_pos + 1: 2 * third]
        if middle.empty:
            return BasePattern()
        mid_peak_price = float(middle["High"].max())

        # Second bottom = min in last third
        last_third = window.iloc[2 * third:]
        if last_third.empty:
            return BasePattern()
        second_bot_price = float(last_third["Low"].min())

        diff = abs(second_bot_price - first_bot_price) / first_bot_price
        if diff > cfg["db_max_second_bottom_diff"]:
            return BasePattern()

        # Validate W shape: middle peak must be notably above both bottoms
        if mid_peak_price <= first_bot_price * 1.05:
            return BasePattern()

        pivot = mid_peak_price + 0.10
        current_price = float(df["Close"].iloc[-1])
        pct_from_pivot = (current_price - pivot) / pivot * 100
        weeks = min_days // 5

        depth = (mid_peak_price - min(first_bot_price, second_bot_price)) / mid_peak_price
        quality = _base_quality_score(
            depth=depth, handle_pullback=0, ideal_depth=0.20,
            ideal_handle=0, base_weeks=weeks
        )

        return BasePattern(
            detected=True,
            pattern="double_bottom",
            pivot_price=pivot,
            stop_price=pivot * 0.93,
            base_depth_pct=depth,
            base_length_weeks=weeks,
            pct_from_pivot=pct_from_pivot,
            quality_score=quality,
        )


def _base_quality_score(
    depth: float, handle_pullback: float,
    ideal_depth: float, ideal_handle: float, base_weeks: int
) -> float:
    """Heuristic 0-100 score: closer to ideal depth + longer base = higher."""
    depth_score = max(0, 100 - abs(depth - ideal_depth) * 300)
    handle_score = (max(0, 100 - abs(handle_pullback - ideal_handle) * 400)
                     if ideal_handle else 50)
    length_score = min(100, base_weeks * 6)
    return round((depth_score * 0.5 + handle_score * 0.3 + length_score * 0.2), 1)


# ═════════════════════════════════════════════════════════════════════════════
# CAN SLIM Criteria Evaluator
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class CANSLIMResult:
    """Per-stock CAN SLIM evaluation (M is global, injected by orchestrator)."""
    # Computed values
    eps_growth_current_qtr: Optional[float] = None
    eps_growth_prior_qtr: Optional[float] = None
    eps_acceleration: Optional[bool] = None
    annual_eps_growth_3yr: list = field(default_factory=list)
    consecutive_eps_growth_years: int = 0
    roe: Optional[float] = None
    sales_growth: Optional[float] = None

    pct_from_52wk_high: float = 0.0
    rs_rating: float = 0.0
    rs_line_trending_up: bool = False
    float_shares: Optional[float] = None
    volume_surge: bool = False
    acc_dist_ratio: float = 0.0
    institutional_ownership: Optional[float] = None

    market_direction: str = "unknown"

    # Criteria (letter-by-letter)
    c_current_eps: bool = False
    a_annual_eps: bool = False
    n_new_high: bool = False
    s_supply_demand: bool = False
    l_leader: bool = False
    i_institutional: bool = False
    m_market_ok: bool = False

    @property
    def passes_all(self) -> bool:
        return all([self.c_current_eps, self.a_annual_eps, self.n_new_high,
                    self.s_supply_demand, self.l_leader, self.i_institutional,
                    self.m_market_ok])

    @property
    def letters_passed(self) -> str:
        """Returns e.g. 'C-A-N---L-I---' for a stock that failed S and M."""
        return "-".join([
            "C" if self.c_current_eps else " ",
            "A" if self.a_annual_eps else " ",
            "N" if self.n_new_high else " ",
            "S" if self.s_supply_demand else " ",
            "L" if self.l_leader else " ",
            "I" if self.i_institutional else " ",
            "M" if self.m_market_ok else " ",
        ])

    @property
    def criteria_passed(self) -> int:
        return sum([self.c_current_eps, self.a_annual_eps, self.n_new_high,
                    self.s_supply_demand, self.l_leader, self.i_institutional,
                    self.m_market_ok])

    def to_dict(self) -> dict:
        def pct(v): return round(v * 100, 1) if v is not None else None
        return {
            "eps_growth_current_qtr_pct": pct(self.eps_growth_current_qtr),
            "eps_growth_prior_qtr_pct":   pct(self.eps_growth_prior_qtr),
            "eps_acceleration":            self.eps_acceleration,
            "consecutive_eps_growth_years": self.consecutive_eps_growth_years,
            "roe_pct":                     pct(self.roe),
            "sales_growth_pct":            pct(self.sales_growth),
            "pct_from_52wk_high":          round(self.pct_from_52wk_high * 100, 1),
            "rs_rating":                   round(self.rs_rating, 1),
            "rs_line_trending_up":         self.rs_line_trending_up,
            "float_shares_M":              round(self.float_shares / 1e6, 1) if self.float_shares else None,
            "volume_surge":                self.volume_surge,
            "acc_dist_ratio":              round(self.acc_dist_ratio, 2),
            "institutional_ownership_pct": pct(self.institutional_ownership),
            "market_direction":            self.market_direction,
            "c_current_eps":     self.c_current_eps,
            "a_annual_eps":      self.a_annual_eps,
            "n_new_high":        self.n_new_high,
            "s_supply_demand":   self.s_supply_demand,
            "l_leader":          self.l_leader,
            "i_institutional":   self.i_institutional,
            "m_market_ok":       self.m_market_ok,
            "canslim_letters":   self.letters_passed,
            "canslim_passed":    f"{self.criteria_passed}/7",
            "passes_canslim":    self.passes_all,
        }


class CANSLIMAnalyzer:
    """Evaluates a stock against the 7 CAN SLIM criteria."""

    def __init__(self, cfg: dict = None):
        from config import CAN_SLIM
        self.cfg = cfg or CAN_SLIM

    def analyze(
        self,
        ticker: str,
        df: pd.DataFrame,
        info: dict,
        tech_result,              # TrendTemplateResult — reuses RS + 52w + acc/dist
        market: MarketDirection,
    ) -> CANSLIMResult:
        r = CANSLIMResult()
        cfg = self.cfg

        # ── M (global, same for every stock in the run) ──────────────────────
        r.market_direction = market.status
        r.m_market_ok = market.confirmed_uptrend

        # ── RS + price-action pulled from tech_result ────────────────────────
        r.rs_rating = tech_result.rs_rating
        r.rs_line_trending_up = tech_result.rs_line_trending_up
        r.pct_from_52wk_high = tech_result.pct_from_52wk_high
        r.acc_dist_ratio = tech_result.acc_dist_ratio

        # ── C: Current quarterly EPS growth ──────────────────────────────────
        r.eps_growth_current_qtr = _safe_float(
            info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
        )
        r.eps_growth_prior_qtr = _eps_growth_from_history(info, quarter=1)
        if r.eps_growth_current_qtr is None:
            r.eps_growth_current_qtr = _eps_growth_from_history(info, quarter=0)

        if r.eps_growth_current_qtr is not None:
            passes_growth = r.eps_growth_current_qtr >= cfg["c_eps_growth_min"]
            if cfg["c_eps_acceleration"] and r.eps_growth_prior_qtr is not None:
                r.eps_acceleration = r.eps_growth_current_qtr > r.eps_growth_prior_qtr
                r.c_current_eps = passes_growth and r.eps_acceleration
            else:
                r.c_current_eps = passes_growth

        # ── A: Annual EPS growth 3 years + ROE ───────────────────────────────
        r.annual_eps_growth_3yr = _annual_eps_growth(info)
        if r.annual_eps_growth_3yr:
            consecutive = 0
            for g in r.annual_eps_growth_3yr:
                if g >= cfg["a_annual_eps_growth_min"]:
                    consecutive += 1
                else:
                    break
            r.consecutive_eps_growth_years = consecutive

        r.roe = _safe_float(info.get("returnOnEquity"))
        roe_ok = r.roe is None or r.roe >= cfg["a_roe_min"]
        eps_years_ok = (r.consecutive_eps_growth_years >= cfg["a_consecutive_years"]
                         if r.annual_eps_growth_3yr else True)  # unknown → don't block
        r.a_annual_eps = eps_years_ok and roe_ok

        # ── N: Near 52-week high (breakout-ready) ────────────────────────────
        r.n_new_high = r.pct_from_52wk_high <= cfg["n_pct_from_52wk_high"]

        # ── S: Supply & Demand ───────────────────────────────────────────────
        r.float_shares = _safe_float(info.get("floatShares"))
        r.volume_surge = _volume_surge(df, mult=cfg["s_volume_surge_mult"])
        # Float is a preference, not a hard gate — O'Neil favors <50M but large-caps qualify
        float_ok = r.float_shares is None or r.float_shares <= cfg["s_float_max"] * 20
        acc_ok = r.acc_dist_ratio >= cfg["s_acc_dist_ratio_min"]
        # S passes if acc/dist strong OR recent volume surge (either is demand)
        r.s_supply_demand = float_ok and (acc_ok or r.volume_surge)

        # ── L: Leader (RS >= 80) ─────────────────────────────────────────────
        r.sales_growth = _safe_float(info.get("revenueGrowth"))
        rs_ok = r.rs_rating >= cfg["l_rs_rating_min"]
        rs_line_ok = r.rs_line_trending_up if cfg["l_rs_line_trending_up"] else True
        r.l_leader = rs_ok and rs_line_ok

        # ── I: Institutional sponsorship ─────────────────────────────────────
        r.institutional_ownership = _safe_float(info.get("heldPercentInstitutions"))
        if r.institutional_ownership is not None:
            r.i_institutional = (
                cfg["i_inst_ownership_min"] <= r.institutional_ownership
                <= cfg["i_inst_ownership_max"]
            )
        else:
            r.i_institutional = True  # unknown — don't penalize

        return r


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

def _volume_surge(df: pd.DataFrame, mult: float = 1.5, lookback: int = 10) -> bool:
    """True if any of the last N days had volume ≥ mult × 50-day avg on an up day."""
    if df is None or len(df) < 55:
        return False
    avg_vol = df["Volume"].iloc[-50:].mean()
    if avg_vol <= 0:
        return False
    recent = df.iloc[-lookback:]
    up_days = recent["Close"] > recent["Close"].shift(1)
    surge = (recent["Volume"] >= avg_vol * mult) & up_days
    return bool(surge.any())


def _eps_growth_from_history(info: dict, quarter: int = 0) -> Optional[float]:
    """Compute YoY EPS growth from earnings_history dict (quarter=0 = most recent)."""
    eh = info.get("earnings_history")
    if not eh:
        return None
    try:
        df = pd.DataFrame(eh).T
        if "epsActual" not in df.columns:
            return None
        df = df.dropna(subset=["epsActual"]).sort_index(ascending=False)
        if len(df) < quarter + 5:
            return None
        cur = float(df["epsActual"].iloc[quarter])
        prior = float(df["epsActual"].iloc[quarter + 4])
        if prior == 0:
            return None
        if prior < 0 and cur > 0:
            return 1.0
        if prior < 0:
            return None
        return (cur - prior) / abs(prior)
    except Exception:
        return None


def _annual_eps_growth(info: dict) -> list:
    """Extract up to 3 years of annual EPS growth (most recent first)."""
    eh = info.get("earnings_history")
    if not eh:
        return []
    try:
        df = pd.DataFrame(eh).T
        if "epsActual" not in df.columns:
            return []
        df = df.dropna(subset=["epsActual"]).sort_index(ascending=False)
        out = []
        for i in range(0, min(16, len(df) - 4), 4):
            cur_yr = float(df["epsActual"].iloc[i:i + 4].sum())
            prior_yr = float(df["epsActual"].iloc[i + 4:i + 8].sum())
            if prior_yr <= 0 or len(df) < i + 8:
                break
            out.append((cur_yr - prior_yr) / abs(prior_yr))
        return out[:3]
    except Exception:
        return []


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        import math
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None
