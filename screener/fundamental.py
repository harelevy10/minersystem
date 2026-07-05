"""
Fundamental Analysis — Minervini SEPA Criteria

Implements Minervini's fundamental requirements from
"Trade Like a Stock Market Wizard":
- EPS growth (quarterly and annual)
- EPS acceleration
- Sales/Revenue growth
- Return on Equity (ROE)
- Pre-tax profit margins
- Institutional sponsorship
- Minimum liquidity requirements
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FundamentalResult:
    """Result of fundamental analysis for a single stock."""

    # EPS
    eps_growth_current_qtr: Optional[float] = None     # YoY %
    eps_growth_prior_qtr: Optional[float] = None       # YoY % (quarter before)
    eps_acceleration: Optional[bool] = None            # current > prior
    eps_annual_growth_3yr: Optional[list] = None       # list of 3 annual growth rates
    eps_consecutive_growth_years: int = 0

    # Revenue / Sales
    sales_growth_current_qtr: Optional[float] = None   # YoY %
    sales_growth_prior_qtr: Optional[float] = None
    sales_acceleration: Optional[bool] = None

    # Profitability
    roe: Optional[float] = None
    pretax_margin: Optional[float] = None
    net_margin: Optional[float] = None

    # Liquidity
    market_cap: Optional[float] = None
    avg_volume: Optional[float] = None
    float_shares: Optional[float] = None

    # Institutional
    institutional_holders: Optional[int] = None
    institutional_ownership_pct: Optional[float] = None

    # Criterion pass/fail
    c_eps_growth: bool = False
    c_eps_acceleration: bool = False
    c_annual_eps: bool = False
    c_sales_growth: bool = False
    c_roe: bool = False
    c_margin: bool = False
    c_market_cap: bool = False
    c_volume: bool = False
    c_institutional: bool = False

    @property
    def passes_mandatory(self) -> bool:
        """Must pass EPS growth, sales growth, market cap, and volume."""
        return all([
            self.c_eps_growth,
            self.c_sales_growth,
            self.c_market_cap,
            self.c_volume,
        ])

    @property
    def passes_all(self) -> bool:
        return all([
            self.c_eps_growth,
            self.c_eps_acceleration,
            self.c_annual_eps,
            self.c_sales_growth,
            self.c_roe,
            self.c_margin,
            self.c_market_cap,
            self.c_volume,
        ])

    @property
    def criteria_passed(self) -> int:
        return sum([
            self.c_eps_growth,
            self.c_eps_acceleration,
            self.c_annual_eps,
            self.c_sales_growth,
            self.c_roe,
            self.c_margin,
            self.c_market_cap,
            self.c_volume,
            self.c_institutional,
        ])

    def to_dict(self) -> dict:
        def fmt_pct(v):
            return round(v * 100, 1) if v is not None else None

        return {
            "eps_growth_current_qtr_pct": fmt_pct(self.eps_growth_current_qtr),
            "eps_growth_prior_qtr_pct": fmt_pct(self.eps_growth_prior_qtr),
            "eps_acceleration": self.eps_acceleration,
            "eps_consecutive_growth_years": self.eps_consecutive_growth_years,
            "sales_growth_current_qtr_pct": fmt_pct(self.sales_growth_current_qtr),
            "sales_acceleration": self.sales_acceleration,
            "roe_pct": fmt_pct(self.roe),
            "pretax_margin_pct": fmt_pct(self.pretax_margin),
            "net_margin_pct": fmt_pct(self.net_margin),
            "market_cap_M": round(self.market_cap / 1e6, 0) if self.market_cap else None,
            "avg_volume_K": round(self.avg_volume / 1e3, 0) if self.avg_volume else None,
            "institutional_holders": self.institutional_holders,
            "institutional_ownership_pct": fmt_pct(self.institutional_ownership_pct),
            # Criteria
            "c_eps_growth": self.c_eps_growth,
            "c_eps_acceleration": self.c_eps_acceleration,
            "c_annual_eps": self.c_annual_eps,
            "c_sales_growth": self.c_sales_growth,
            "c_roe": self.c_roe,
            "c_margin": self.c_margin,
            "c_market_cap": self.c_market_cap,
            "c_volume": self.c_volume,
            "c_institutional": self.c_institutional,
            "fundamental_criteria_passed": f"{self.criteria_passed}/9",
            "passes_mandatory_fundamentals": self.passes_mandatory,
        }


class FundamentalAnalyzer:
    """
    Evaluates a stock against Minervini's fundamental criteria.
    """

    def __init__(self, cfg: dict = None):
        from config import FUNDAMENTALS
        self.cfg = cfg or FUNDAMENTALS

    def analyze(self, ticker: str, info: dict) -> FundamentalResult:
        """
        Analyze fundamental data from yfinance info dict.

        Args:
            ticker: Ticker symbol
            info: yfinance Ticker.info dict (+ parsed financials)

        Returns:
            FundamentalResult
        """
        result = FundamentalResult()

        if not info:
            return result

        # ── Market Cap & Volume ───────────────────────────────────────────────
        result.market_cap = _safe_float(info.get("marketCap"))
        result.avg_volume = _safe_float(info.get("averageVolume"))
        result.float_shares = _safe_float(info.get("floatShares"))

        result.c_market_cap = (
            result.market_cap is not None and
            result.market_cap >= self.cfg["market_cap_min"]
        )
        result.c_volume = (
            result.avg_volume is not None and
            result.avg_volume >= self.cfg["avg_volume_min"]
        )

        # ── EPS Growth ───────────────────────────────────────────────────────
        result.eps_growth_current_qtr = self._get_eps_growth_current_qtr(info)
        result.eps_growth_prior_qtr = self._get_eps_growth_prior_qtr(info)

        if result.eps_growth_current_qtr is not None:
            result.c_eps_growth = (
                result.eps_growth_current_qtr >= self.cfg["eps_growth_current_qtr_min"]
            )

        # EPS Acceleration: current quarter growth > prior quarter growth
        if (result.eps_growth_current_qtr is not None and
                result.eps_growth_prior_qtr is not None):
            result.eps_acceleration = (
                result.eps_growth_current_qtr > result.eps_growth_prior_qtr
            )
            result.c_eps_acceleration = result.eps_acceleration
        elif result.eps_growth_current_qtr is not None:
            # If we only have one quarter, treat as neutral
            result.eps_acceleration = None
            result.c_eps_acceleration = True  # don't penalize missing data

        # ── Annual EPS Growth ────────────────────────────────────────────────
        annual_eps_growth = self._get_annual_eps_growth(info)
        result.eps_annual_growth_3yr = annual_eps_growth

        if annual_eps_growth:
            consecutive = 0
            for g in annual_eps_growth:
                if g >= self.cfg["eps_annual_growth_min"]:
                    consecutive += 1
                else:
                    break
            result.eps_consecutive_growth_years = consecutive
            result.c_annual_eps = consecutive >= self.cfg["eps_consecutive_years"]
        else:
            # If no annual data, don't block the screen — just flag as unknown
            result.c_annual_eps = True

        # ── Sales / Revenue Growth ───────────────────────────────────────────
        result.sales_growth_current_qtr = self._get_sales_growth(info)
        result.sales_growth_prior_qtr = self._get_prior_sales_growth(info)

        if result.sales_growth_current_qtr is not None:
            result.c_sales_growth = (
                result.sales_growth_current_qtr >= self.cfg["sales_growth_min"]
            )
            if result.sales_growth_prior_qtr is not None:
                result.sales_acceleration = (
                    result.sales_growth_current_qtr > result.sales_growth_prior_qtr
                )

        # ── Return on Equity ─────────────────────────────────────────────────
        result.roe = _safe_float(info.get("returnOnEquity"))
        if result.roe is not None:
            result.c_roe = result.roe >= self.cfg["roe_min"]
        else:
            result.c_roe = True  # Unknown — don't penalize

        # ── Profit Margins ───────────────────────────────────────────────────
        # yfinance provides grossMargins, operatingMargins, profitMargins (net)
        # Minervini looks at pre-tax margins; we use operating margin as proxy
        result.pretax_margin = _safe_float(
            info.get("operatingMargins") or info.get("ebitdaMargins")
        )
        result.net_margin = _safe_float(info.get("profitMargins"))

        if result.pretax_margin is not None:
            result.c_margin = result.pretax_margin >= self.cfg["pretax_margin_min"]
        else:
            result.c_margin = True  # Unknown — don't penalize

        # ── Institutional Sponsorship ─────────────────────────────────────────
        result.institutional_holders = _safe_int(info.get("institutionsCount") or
                                                  info.get("heldPercentInstitutions"))
        # yfinance gives heldPercentInstitutions as a decimal
        result.institutional_ownership_pct = _safe_float(info.get("heldPercentInstitutions"))

        # Use ownership % as a proxy if holder count is unavailable
        if result.institutional_ownership_pct is not None:
            result.c_institutional = result.institutional_ownership_pct >= 0.05  # 5%+
        else:
            result.c_institutional = True

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # EPS Extraction Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_eps_growth_current_qtr(self, info: dict) -> Optional[float]:
        """
        Get most recent quarter EPS growth (YoY).
        Tries multiple yfinance fields.
        """
        # Direct yfinance field
        growth = _safe_float(info.get("earningsGrowth") or
                             info.get("earningsQuarterlyGrowth"))
        if growth is not None:
            return growth

        # Try to compute from earnings history
        eh = info.get("earnings_history")
        if eh:
            try:
                return self._compute_eps_growth_from_history(eh, quarter=0)
            except Exception:
                pass
        return None

    def _get_eps_growth_prior_qtr(self, info: dict) -> Optional[float]:
        """Get prior quarter EPS growth (YoY)."""
        eh = info.get("earnings_history")
        if eh:
            try:
                return self._compute_eps_growth_from_history(eh, quarter=1)
            except Exception:
                pass
        return None

    def _compute_eps_growth_from_history(self, eh: dict, quarter: int) -> Optional[float]:
        """
        Compute YoY EPS growth for a specific quarter offset.
        earnings_history is a dict-of-dicts from yfinance.
        """
        import pandas as pd
        df = pd.DataFrame(eh).T
        if "epsActual" not in df.columns or "epsDifference" not in df.columns:
            return None

        df = df.dropna(subset=["epsActual"]).sort_index(ascending=False)
        if len(df) < quarter + 5:
            return None

        current_eps = float(df["epsActual"].iloc[quarter])
        prior_eps = float(df["epsActual"].iloc[quarter + 4])  # 4 quarters back = YoY

        if prior_eps == 0:
            return None
        # Handle negative base
        if prior_eps < 0 and current_eps > 0:
            return 1.0  # Turnaround — treat as 100% growth
        if prior_eps < 0:
            return None

        return (current_eps - prior_eps) / abs(prior_eps)

    def _get_annual_eps_growth(self, info: dict) -> list:
        """
        Get list of annual EPS growth rates (most recent first).
        Returns up to 3 years of growth rates.
        """
        # yfinance earningsHistory doesn't have annual directly
        # Use annualEarnings if available (older API) or compute from quarterly
        try:
            eh = info.get("earnings_history")
            if eh:
                import pandas as pd
                df = pd.DataFrame(eh).T
                if "epsActual" in df.columns:
                    df = df.dropna(subset=["epsActual"]).sort_index(ascending=False)
                    annual_eps = []
                    # Sum 4 quarters per year
                    for i in range(0, min(16, len(df) - 4), 4):
                        current_yr = float(df["epsActual"].iloc[i:i+4].sum())
                        prior_yr = float(df["epsActual"].iloc[i+4:i+8].sum())
                        if prior_yr <= 0 or len(df) < i + 8:
                            break
                        growth = (current_yr - prior_yr) / abs(prior_yr)
                        annual_eps.append(growth)
                    return annual_eps[:3]
        except Exception:
            pass
        return []

    # ─────────────────────────────────────────────────────────────────────────
    # Revenue Growth Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_sales_growth(self, info: dict) -> Optional[float]:
        """Get most recent quarter revenue growth (YoY)."""
        growth = _safe_float(info.get("revenueGrowth"))
        if growth is not None:
            return growth

        rev = info.get("quarterly_revenue", [])
        if len(rev) >= 5:
            current = rev[0]
            prior = rev[4]
            if prior and prior > 0 and current:
                return (current - prior) / prior
        return None

    def _get_prior_sales_growth(self, info: dict) -> Optional[float]:
        """Get prior quarter revenue growth (YoY)."""
        rev = info.get("quarterly_revenue", [])
        if len(rev) >= 6:
            current = rev[1]
            prior = rev[5]
            if prior and prior > 0 and current:
                return (current - prior) / prior
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        import math
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None
