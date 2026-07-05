#!/usr/bin/env python3
"""
Single-Ticker Analyzer
======================
Enter one stock symbol, get the full Minervini SEPA *and* O'Neil CAN SLIM
breakdown for it — every criterion, pass or fail (unlike the screeners, which
only show fundamentals for stocks that clear the technical gate).

Usage:
    python3 analyze.py NVDA
    python3 analyze.py            # prompts for a ticker

RS Rating is percentile-ranked against the S&P 500 (uses the cached price data
from your daily screen, so it's fast once the cache is warm).
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
from screener.universe import get_universe
from screener.data_fetcher import DataFetcher
from screener.technical import TechnicalAnalyzer, compute_rs_ratings
from screener.fundamental import FundamentalAnalyzer
from screener.vcp import VCPDetector
from screener.oneil import CANSLIMAnalyzer, BasePatternDetector, assess_market_direction
from screener import report


def run_analysis(ticker: str, fetcher: DataFetcher = None) -> dict:
    """
    Analyze one ticker against both methodologies, unconditionally.
    Returns {"ticker", "minervini", "canslim", "base", "market", "df"} or
    {"error": "..."} if data is missing. Used by both the CLI and the dashboard.
    """
    ticker = ticker.upper().strip()
    fetcher = fetcher or DataFetcher(
        cache_dir=cfg.UNIVERSE["cache_dir"],
        cache_ttl_hours=cfg.UNIVERSE["cache_ttl_hours"],
        api_delay=cfg.UNIVERSE.get("api_delay", 0.1),
        max_workers=cfg.UNIVERSE.get("max_workers", 10),
    )

    df = fetcher.get_price_history(ticker, period="2y")
    if df is None or len(df) < 50:
        return {"error": f"No usable price data for {ticker} (need ≥50 days)."}

    spy = fetcher.get_benchmark_history("SPY", period="2y")
    qqq = fetcher.get_benchmark_history("QQQ", period="2y")
    info = fetcher.get_fundamentals(ticker)

    # ── RS percentile vs S&P 500 (cached) ────────────────────────────────────
    universe = get_universe("sp500", cfg.UNIVERSE["custom_file"])
    price_data = fetcher.batch_fetch_prices(universe, period="2y")
    price_data[ticker] = df
    rs_ratings = compute_rs_ratings(price_data)
    rs_rating = rs_ratings.get(ticker, 0)

    # ── Technical (shared by both methodologies) ─────────────────────────────
    tech = TechnicalAnalyzer(
        cfg_trend=cfg.TREND_TEMPLATE, cfg_rs=cfg.RS_CALCULATION, cfg_volume=cfg.VOLUME,
    ).analyze(ticker, df, benchmark_df=spy, all_rs_scores=list(rs_ratings.values()))
    tech.rs_rating = rs_rating
    tech.c10_rs_rating = rs_rating >= cfg.TREND_TEMPLATE["rs_rating_min"]
    tech.s10_rs_weak = rs_rating <= cfg.SHORT_TREND_TEMPLATE["rs_rating_max"]

    # ── Minervini: fundamentals + VCP (run unconditionally) ──────────────────
    fund = FundamentalAnalyzer(cfg=cfg.FUNDAMENTALS).analyze(ticker, info)
    vcp = VCPDetector(cfg=cfg.VCP, vol_cfg=cfg.VOLUME).detect(df)
    minervini = {
        "ticker": ticker, "score": 0,
        "sector": info.get("sector") or "", "industry": info.get("industry") or "",
        "technical": tech.to_dict(), "fundamental": fund.to_dict(),
        "vcp": vcp.to_dict() if vcp else {},
    }

    # ── O'Neil: CAN SLIM + base pattern (run unconditionally) ────────────────
    market = assess_market_direction(spy, qqq)
    canslim = CANSLIMAnalyzer(cfg=cfg.CAN_SLIM).analyze(
        ticker=ticker, df=df, info=info, tech_result=tech, market=market)
    base = BasePatternDetector(cfg=cfg.BASE_PATTERNS).detect(df)

    return {
        "ticker": ticker, "minervini": minervini,
        "canslim": canslim.to_dict(), "base": base.to_dict(),
        "market": market, "df": df,
    }


def analyze(ticker: str):
    print(f"  Analyzing {ticker.upper().strip()} (computing RS vs S&P 500)...")
    res = run_analysis(ticker)
    if "error" in res:
        print(f"\n  [ERROR] {res['error']}")
        return 1
    t = res["ticker"]
    print(f"\n{'='*64}\n  MINERVINI SEPA — {t}\n{'='*64}")
    report._print_stock_detail(res["minervini"])
    report._print_short_detail(res["minervini"])
    print(f"\n{'='*64}\n  O'NEIL CAN SLIM — {t}\n{'='*64}")
    _print_canslim_detail(t, res["df"], res["canslim"], res["base"], res["market"])
    return 0


def _print_canslim_detail(ticker, df, cs, base, market):
    from screener.report import check, bold, cyan, dim, green, red, fmt_price
    price = float(df["Close"].iloc[-1])
    print(f"\n  {bold(cyan(ticker))} — {fmt_price(price)}  RS: {cs.get('rs_rating', 0):.0f}  "
          f"[{cs.get('canslim_letters', '')}]  {cs.get('canslim_passed', '?')}")
    print(f"  {'─'*60}")
    rows = [
        (f"C  Current quarterly EPS growth  ({cs.get('eps_growth_current_qtr_pct', 'N/A')}%)", cs.get("c_current_eps")),
        (f"A  Annual EPS growth  ({cs.get('consecutive_eps_growth_years', 0)} consec. yrs, ROE {cs.get('roe_pct', 'N/A')}%)", cs.get("a_annual_eps")),
        (f"N  New high / new highs  ({cs.get('pct_from_52wk_high', 0):.1f}% from 52wk high)", cs.get("n_new_high")),
        (f"S  Supply & demand  (acc/dist {cs.get('acc_dist_ratio', 0):.2f}, float {cs.get('float_shares_M', 'N/A')}M)", cs.get("s_supply_demand")),
        (f"L  Leader  (RS {cs.get('rs_rating', 0):.0f}, RS line up: {cs.get('rs_line_trending_up')})", cs.get("l_leader")),
        (f"I  Institutional sponsorship  ({cs.get('institutional_ownership_pct', 'N/A')}%)", cs.get("i_institutional")),
        (f"M  Market direction  ({market.status})", cs.get("m_market_ok")),
    ]
    for label, passed in rows:
        print(f"      {check(bool(passed))}  {label}")

    print(f"\n  {bold('BASE PATTERN')}")
    if base.get("base_detected"):
        print(f"      {green('✓')}  {base['base_pattern']} — {base['base_length_weeks']} weeks, "
              f"depth {base['base_depth_pct']}%")
        print(f"         Pivot: {fmt_price(base['base_pivot_price'])}  "
              f"Stop: {fmt_price(base['base_stop_price'])}  "
              f"{base['base_pct_from_pivot']:+.1f}% away  "
              f"Quality: {base['base_quality_score']:.0f}/100")
    else:
        print(f"      {dim('—')}  No base pattern detected")
    if not market.confirmed_uptrend:
        print("\n  " + red("⚠  Market NOT in confirmed uptrend — O'Neil rule: avoid new buys."))
    print()


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else input("Enter a stock symbol: ")
    sys.exit(analyze(t))
