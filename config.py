"""
Minervini SEPA (Specific Entry Point Analysis) System Configuration
All thresholds and parameters based on Mark Minervini's published criteria
from "Trade Like a Stock Market Wizard" and "Think & Trade Like a Champion"
"""

# ─────────────────────────────────────────────────────────────────────────────
# TREND TEMPLATE  (Stage 2 Qualification)
# A stock must pass ALL 8 criteria to be in a valid Stage 2 uptrend
# ─────────────────────────────────────────────────────────────────────────────
TREND_TEMPLATE = {
    # 1. Price must be above both the 150-day and 200-day SMAs
    "sma_150": 150,
    "sma_200": 200,
    "sma_50": 50,

    # 2. 150-day SMA must be above the 200-day SMA
    # (enforced in code, no threshold needed)

    # 3. 200-day SMA must be trending UP — measured over this many trading days
    "sma_200_trend_days": 20,          # ~1 month; Minervini prefers 4-5 months

    # 4. 50-day SMA must be above both 150-day and 200-day SMAs
    # (enforced in code)

    # 5. Price must be above the 50-day SMA
    # (enforced in code)

    # 6. Price must be at least this % above its 52-week low
    "pct_above_52wk_low": 0.25,        # 25%

    # 7. Price must be within this % of its 52-week high
    #    i.e., price >= (1 - threshold) * 52wk_high
    "pct_from_52wk_high": 0.25,        # within 25% of 52-week high

    # 8. Relative Strength rating minimum (IBD-style, 0-99 percentile)
    "rs_rating_min": 70,               # Minervini prefers 80+; 70 is the floor
}

# ─────────────────────────────────────────────────────────────────────────────
# SHORT TREND TEMPLATE  (Stage 4 breakdown candidates)
# Mirror image of TREND_TEMPLATE: price below all SMAs, MAs declining,
# near 52wk low, weak RS. Reuses TREND_TEMPLATE's SMA windows and % thresholds.
# ─────────────────────────────────────────────────────────────────────────────
SHORT_TREND_TEMPLATE = {
    "rs_rating_max": 30,                # RS Rating <= 30 marks a laggard
}

# ─────────────────────────────────────────────────────────────────────────────
# FUNDAMENTAL CRITERIA
# ─────────────────────────────────────────────────────────────────────────────
FUNDAMENTALS = {
    # Current quarter EPS growth (year-over-year) — minimum threshold
    "eps_growth_current_qtr_min": 0.20,    # 20% minimum; ideally 40%+
    "eps_growth_current_qtr_ideal": 0.40,  # 40%+ is the ideal

    # Annual EPS growth — minimum for each of the past 3 years
    "eps_annual_growth_min": 0.20,         # 20% per year

    # Number of consecutive years of annual EPS growth required
    "eps_consecutive_years": 3,

    # EPS acceleration: current quarter growth must be >= prior quarter growth
    # (enforced in code as a boolean check)
    "eps_acceleration_required": True,

    # Revenue / Sales growth — most recent quarter year-over-year
    "sales_growth_min": 0.20,             # 20% minimum

    # Return on Equity minimum
    "roe_min": 0.17,                      # 17%

    # Pre-tax profit margin minimum
    "pretax_margin_min": 0.12,            # 12% (lower threshold for growth stocks)

    # Institutional sponsorship — at least this many institutions holding
    "institutional_holders_min": 10,

    # Minimum market cap (USD) — avoids illiquid micro-caps
    "market_cap_min": 300_000_000,        # $300M

    # Minimum average daily volume (shares)
    "avg_volume_min": 500_000,            # 500K shares/day
}

# ─────────────────────────────────────────────────────────────────────────────
# RELATIVE STRENGTH CALCULATION
# Minervini uses IBD's RS Rating (1-99 scale, percentile vs all stocks)
# We calculate a proxy using weighted 12-month price performance
# ─────────────────────────────────────────────────────────────────────────────
RS_CALCULATION = {
    # Weights for each quarter (most recent gets highest weight)
    # Q4 = most recent quarter, Q1 = oldest quarter
    "q4_weight": 0.40,
    "q3_weight": 0.20,
    "q2_weight": 0.20,
    "q1_weight": 0.20,

    # Lookback period for RS line trend (days)
    "rs_line_trend_days": 50,

    # Benchmark ticker for RS line
    "benchmark": "SPY",
}

# ─────────────────────────────────────────────────────────────────────────────
# VOLATILITY CONTRACTION PATTERN (VCP)
# The VCP is Minervini's primary base pattern — a series of progressively
# tighter price contractions with declining volume
# ─────────────────────────────────────────────────────────────────────────────
VCP = {
    # Minimum number of contractions to confirm a VCP
    "min_contractions": 2,

    # Maximum number of contractions (typically 2-4)
    "max_contractions": 4,

    # Each contraction must be smaller than the previous by at least this ratio
    # e.g., 0.5 means next contraction <= 50% of previous contraction depth
    "contraction_shrink_ratio": 0.50,

    # Max depth of the first (widest) contraction from high to low
    "max_first_contraction_pct": 0.40,    # 40% max depth

    # Max depth of the last (tightest) contraction — the pivot area
    "max_last_contraction_pct": 0.10,     # 10% tight

    # Volume on contraction lows should be below this percentile of recent volume
    "volume_dry_up_percentile": 0.40,     # below 40th percentile = "drying up"

    # Lookback window for VCP base detection (trading days)
    "base_lookback_days": 60,             # ~3 months

    # Maximum base length
    "max_base_days": 250,                 # ~1 year

    # Price proximity to pivot for a "near pivot" alert
    "pivot_proximity_pct": 0.05,          # within 5% of pivot high
}

# ─────────────────────────────────────────────────────────────────────────────
# VOLUME ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
VOLUME = {
    # Breakout volume must be at least this multiple of the 50-day avg volume
    "breakout_volume_multiplier": 1.40,   # 40% above average

    # Volume moving average periods
    "vol_ma_short": 10,
    "vol_ma_long": 50,

    # Accumulation/Distribution: up-day volume vs down-day volume ratio
    # over the past N days
    "acc_dist_lookback": 25,
    "acc_dist_ratio_min": 1.0,            # up-day vol >= down-day vol

    # Tight weeks: weeks where weekly range < this % of weekly close
    "tight_week_range_pct": 0.015,        # 1.5%
}

# ─────────────────────────────────────────────────────────────────────────────
# PRICE / RISK MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────
RISK = {
    # Minimum stock price (avoid sub-$10 stocks which can be volatile/illiquid)
    "min_price": 10.0,

    # Stop-loss guidance: percentage below pivot/buy point
    "stop_loss_pct": 0.07,               # 7-8% below entry

    # Risk/Reward minimum: expected gain vs risk
    "min_risk_reward": 3.0,              # 3:1 minimum

    # Position sizing: max risk per trade as % of portfolio
    "max_risk_per_trade": 0.01,          # 1% of portfolio
}

# ─────────────────────────────────────────────────────────────────────────────
# SCREENING UNIVERSE OPTIONS
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSE = {
    # Available universes: "sp500", "nasdaq100", "russell2000", "custom"
    "default_universe": "sp500",

    # For custom universe, provide a list of tickers in universe/custom.txt
    "custom_file": "universe/custom.txt",

    # Cache price data locally (reduces API calls on re-runs)
    "cache_data": True,
    "cache_dir": "cache/",
    "cache_ttl_hours": 4,               # refresh cache after 4 hours

    # Max workers for parallel data fetching
    "max_workers": 10,

    # Delay between API calls (seconds) to avoid rate limiting
    "api_delay": 0.1,
}

# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
OUTPUT = {
    "output_dir": "output/",
    "save_csv": True,
    "save_json": False,
    "show_all_criteria": True,           # show pass/fail for each criterion
    "max_results": 50,                   # max stocks to display in console
    "sort_by": "rs_rating",             # sort results by this field
    "sort_ascending": False,
}

# ─────────────────────────────────────────────────────────────────────────────
# CAN SLIM — William O'Neil / IBD methodology
# From "How to Make Money in Stocks" (O'Neil). 7 letters = 7 criteria.
# Stricter than Minervini on RS (80+ required) and emphasizes base patterns.
# ─────────────────────────────────────────────────────────────────────────────
CAN_SLIM = {
    # C — Current quarterly EPS growth (YoY). O'Neil: 25% min, prefer 40-100%+
    "c_eps_growth_min":        0.25,
    "c_eps_growth_ideal":      0.40,
    "c_eps_acceleration":      True,    # require current qtr > prior qtr

    # A — Annual EPS growth (each of last 3 years). O'Neil: 25% min annual.
    "a_annual_eps_growth_min": 0.25,
    "a_consecutive_years":     3,
    "a_roe_min":               0.17,    # 17% ROE (O'Neil's threshold)

    # N — New: price within X% of 52-week high (or breaking out of base)
    "n_pct_from_52wk_high":    0.15,    # within 15% of new high

    # S — Supply & Demand
    "s_float_max":             50_000_000,      # prefer < 50M float shares
    "s_volume_surge_mult":     1.50,            # breakout vol ≥ 1.5× avg
    "s_acc_dist_ratio_min":    1.10,            # up-day vol / down-day vol

    # L — Leader (not laggard). RS Rating ≥ 80 is O'Neil's floor.
    "l_rs_rating_min":         80,
    "l_rs_line_trending_up":   True,

    # I — Institutional sponsorship
    "i_inst_ownership_min":    0.10,    # at least 10% held by institutions
    "i_inst_ownership_max":    0.95,    # avoid over-owned (sponsorship peak)

    # M — Market direction (general market must be in confirmed uptrend)
    "m_benchmarks":            ["SPY", "QQQ"],
    "m_require_above_sma50":   True,
    "m_require_above_sma200":  True,
    "m_require_sma50_gt_200":  True,

    # Minimum price & liquidity (O'Neil avoids <$15 stocks and low-volume)
    "min_price":               15.0,
    "min_avg_volume":          400_000,
    "min_market_cap":          300_000_000,
}

# ─────────────────────────────────────────────────────────────────────────────
# BASE PATTERNS (O'Neil): Cup & Handle, Flat Base, Double Bottom
# ─────────────────────────────────────────────────────────────────────────────
BASE_PATTERNS = {
    # Cup & Handle
    "cup_min_depth_pct":       0.12,    # 12% minimum correction
    "cup_max_depth_pct":       0.35,    # 35% maximum (deeper = fails)
    "cup_min_weeks":           7,       # 7-week min cup formation
    "cup_max_weeks":           65,      # ~15 months max
    "handle_max_depth_pct":    0.15,    # handle < 15% pullback
    "handle_min_days":         5,
    "handle_max_days":         25,
    "handle_upper_half":       True,    # handle must form in upper half of cup

    # Flat Base
    "flat_min_weeks":          5,
    "flat_max_range_pct":      0.15,    # <15% total range

    # Double Bottom
    "db_min_weeks":            7,
    "db_max_second_bottom_diff": 0.04,  # 2nd bottom within 4% of 1st

    # Pivot proximity alert
    "pivot_proximity_pct":     0.05,
}

# ─────────────────────────────────────────────────────────────────────────────
# CAN SLIM SCORING WEIGHTS
# ─────────────────────────────────────────────────────────────────────────────
CAN_SLIM_SCORING = {
    "rs_rating":     0.25,
    "eps_growth":    0.20,
    "sales_growth":  0.10,
    "annual_eps":    0.10,
    "base_quality":  0.20,
    "institutional": 0.05,
    "volume_trend":  0.10,
}

# ─────────────────────────────────────────────────────────────────────────────
# SCORING WEIGHTS
# Used to rank stocks that pass all mandatory criteria
# ─────────────────────────────────────────────────────────────────────────────
SCORING = {
    "rs_rating": 0.30,                  # 30% weight on RS Rating
    "eps_growth": 0.20,                 # 20% weight on EPS growth
    "sales_growth": 0.15,               # 15% weight on sales growth
    "vcp_quality": 0.20,                # 20% weight on VCP pattern quality
    "volume_trend": 0.15,               # 15% weight on volume accumulation
}
