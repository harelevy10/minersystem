"""
Report Generator
Formats and outputs screener results to console and CSV files.
"""

import os
import csv
import json
from datetime import datetime
from typing import Optional

from tabulate import tabulate
from colorama import init, Fore, Style

init(autoreset=True)  # Colorama init


# ─────────────────────────────────────────────────────────────────────────────
# Color helpers
# ─────────────────────────────────────────────────────────────────────────────

def green(s): return f"{Fore.GREEN}{s}{Style.RESET_ALL}"
def red(s):   return f"{Fore.RED}{s}{Style.RESET_ALL}"
def yellow(s): return f"{Fore.YELLOW}{s}{Style.RESET_ALL}"
def cyan(s):  return f"{Fore.CYAN}{s}{Style.RESET_ALL}"
def bold(s):  return f"{Style.BRIGHT}{s}{Style.RESET_ALL}"
def dim(s):   return f"{Style.DIM}{s}{Style.RESET_ALL}"


def check(passed: bool) -> str:
    return green("✓") if passed else red("✗")


def fmt_pct(v, decimals=1) -> str:
    if v is None:
        return dim("N/A")
    return f"{v:+.{decimals}f}%"


def fmt_price(v) -> str:
    if v is None or v == 0:
        return dim("N/A")
    return f"${v:,.2f}"


def fmt_num(v, suffix="") -> str:
    if v is None:
        return dim("N/A")
    if v >= 1e9:
        return f"{v/1e9:.1f}B{suffix}"
    if v >= 1e6:
        return f"{v/1e6:.1f}M{suffix}"
    if v >= 1e3:
        return f"{v/1e3:.1f}K{suffix}"
    return f"{v:.0f}{suffix}"


def fmt_rating(v) -> str:
    if v is None:
        return dim("N/A")
    v = float(v)
    if v >= 90:
        return green(f"{v:.0f}")
    if v >= 70:
        return yellow(f"{v:.0f}")
    return red(f"{v:.0f}")


# ─────────────────────────────────────────────────────────────────────────────
# Console Report
# ─────────────────────────────────────────────────────────────────────────────

def print_banner(universe: str, total_screened: int, total_passed: int,
                 elapsed_secs: float):
    """Print the screener run summary banner."""
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print()
    print(bold("═" * 72))
    print(bold(f"  MINERVINI SEPA STOCK SCREENER  │  {date_str}"))
    print(bold("═" * 72))
    print(f"  Universe  : {cyan(universe.upper())}")
    print(f"  Screened  : {total_screened} stocks")
    print(f"  Passed    : {green(str(total_passed))} stocks")
    print(f"  Runtime   : {elapsed_secs:.1f}s")
    print(bold("═" * 72))
    print()


def print_results_table(results: list[dict], max_rows: int = 50,
                        show_all_criteria: bool = False):
    """
    Print a formatted results table to console.

    Args:
        results: List of result dicts (from screener)
        max_rows: Maximum rows to show
        show_all_criteria: If True, show individual criterion pass/fail
    """
    if not results:
        print(yellow("  No stocks passed all criteria."))
        return

    results = results[:max_rows]

    # ── Summary table ─────────────────────────────────────────────────────
    headers = [
        "#", "Ticker", "Price", "RS", "Stage",
        "EPS%", "Sales%", "ROE%",
        "VCP", "Pivot", "Stop",
        "Tech", "Fund", "Score"
    ]

    rows = []
    for i, r in enumerate(results, 1):
        t = r.get("technical", {})
        f = r.get("fundamental", {})
        v = r.get("vcp", {})

        vcp_str = green(f"✓ {v.get('vcp_contractions', 0)}T") if v.get("vcp_detected") else dim("—")
        pivot = fmt_price(v.get("vcp_pivot_price")) if v.get("vcp_detected") else dim("—")
        stop = fmt_price(v.get("vcp_stop_price")) if v.get("vcp_detected") else dim("—")

        tech_pass = t.get("passes_trend_template", False)
        fund_pass = f.get("passes_mandatory_fundamentals", False)

        score = r.get("score", 0)
        score_str = (green if score >= 75 else yellow if score >= 50 else dim)(f"{score:.0f}")

        rows.append([
            bold(str(i)),
            bold(cyan(r.get("ticker", ""))),
            fmt_price(t.get("current_price")),
            fmt_rating(t.get("rs_rating")),
            _stage_str(t.get("stage", 0)),
            fmt_pct(f.get("eps_growth_current_qtr_pct")),
            fmt_pct(f.get("sales_growth_current_qtr_pct")),
            fmt_pct(f.get("roe_pct")),
            vcp_str,
            pivot,
            stop,
            check(tech_pass),
            check(fund_pass),
            score_str,
        ])

    print(tabulate(rows, headers=headers, tablefmt="simple",
                   colalign=("right", "left", "right", "right", "center",
                             "right", "right", "right",
                             "center", "right", "right",
                             "center", "center", "right")))
    print()

    # ── Per-stock detailed breakdown ─────────────────────────────────────
    if show_all_criteria and results:
        print(bold("─" * 72))
        print(bold("  DETAILED CRITERIA BREAKDOWN"))
        print(bold("─" * 72))
        for r in results[:10]:  # Only first 10 in detail
            _print_stock_detail(r)


def print_short_candidates(all_results: list[dict], max_rows: int = 20):
    """Print stocks that pass the inverse (short) Trend Template — Stage 4 breakdowns."""
    shorts = [r for r in all_results if r.get("technical", {}).get("passes_short_trend_template")]
    if not shorts:
        return
    shorts.sort(key=lambda r: r.get("technical", {}).get("rs_rating", 99))

    print(bold(f"  SHORT CANDIDATES ({len(shorts)} in confirmed Stage 4 downtrend)"))
    print(f"  {'─'*72}")
    headers = ["#", "Ticker", "Price", "RS", "50 SMA", "150 SMA", "% From High", "Vol Trend"]
    rows = []
    for i, r in enumerate(shorts[:max_rows], 1):
        t = r.get("technical", {})
        rows.append([
            i, r.get("ticker", ""),
            fmt_price(t.get("current_price")),
            fmt_rating(t.get("rs_rating")),
            fmt_price(t.get("sma_50")),
            fmt_price(t.get("sma_150")),
            f"-{t.get('pct_from_52wk_high', 0):.1f}%",
            _vol_trend_str(t.get("volume_trend")),
        ])
    print(tabulate(rows, headers=headers, tablefmt="simple",
                   colalign=("right", "left", "right", "right", "right", "right", "right", "left")))
    print()


def _stage_str(stage: int) -> str:
    stage_colors = {1: yellow, 2: green, 3: yellow, 4: red}
    fn = stage_colors.get(stage, dim)
    labels = {1: "1-Base", 2: "2-Bull", 3: "3-Top", 4: "4-Bear", 0: "?"}
    return fn(labels.get(stage, "?"))


def _print_stock_detail(r: dict):
    t = r.get("technical", {})
    f = r.get("fundamental", {})
    v = r.get("vcp", {})

    ticker = r.get("ticker", "")
    print(f"\n  {bold(cyan(ticker))} — {fmt_price(t.get('current_price'))}  "
          f"RS: {fmt_rating(t.get('rs_rating'))}  "
          f"Stage: {_stage_str(t.get('stage', 0))}")

    print(f"  {'─'*60}")

    # Trend Template
    print(f"  {bold('TREND TEMPLATE')}")
    criteria = [
        (f"C1  Price > 150 SMA  (${t.get('sma_150', 0):.2f})", t.get("c1_price_above_sma150")),
        (f"C2  Price > 200 SMA  (${t.get('sma_200', 0):.2f})", t.get("c2_price_above_sma200")),
        ("C3  150 SMA > 200 SMA", t.get("c3_sma150_above_sma200")),
        ("C4  200 SMA trending up ≥ 1 month", t.get("c4_sma200_trending_up")),
        ("C5  50 SMA > 150 SMA", t.get("c5_sma50_above_sma150")),
        ("C6  50 SMA > 200 SMA", t.get("c6_sma50_above_sma200")),
        (f"C7  Price > 50 SMA  (${t.get('sma_50', 0):.2f})", t.get("c7_price_above_sma50")),
        (f"C8  ≥25% above 52wk low  ({t.get('pct_above_52wk_low', 0):.1f}%)", t.get("c8_above_52wk_low")),
        (f"C9  Within 25% of 52wk high  ({t.get('pct_from_52wk_high', 0):.1f}% from high)", t.get("c9_near_52wk_high")),
        (f"C10 RS Rating ≥ 70  ({t.get('rs_rating', 0):.0f})", t.get("c10_rs_rating")),
    ]
    for label, passed in criteria:
        print(f"      {check(passed)}  {label}")

    print(f"\n  {bold('FUNDAMENTALS')}")
    fund_criteria = [
        (f"EPS Growth (curr qtr)  ({f.get('eps_growth_current_qtr_pct', 'N/A')}%)", f.get("c_eps_growth")),
        (f"EPS Acceleration", f.get("c_eps_acceleration")),
        (f"3yr Annual EPS Growth  ({f.get('eps_consecutive_growth_years', 0)} consec. years)", f.get("c_annual_eps")),
        (f"Sales Growth  ({f.get('sales_growth_current_qtr_pct', 'N/A')}%)", f.get("c_sales_growth")),
        (f"ROE  ({f.get('roe_pct', 'N/A')}%)", f.get("c_roe")),
        (f"Operating Margin  ({f.get('pretax_margin_pct', 'N/A')}%)", f.get("c_margin")),
        (f"Market Cap  ({fmt_num(f.get('market_cap_M', 0) * 1e6 if f.get('market_cap_M') else 0)})", f.get("c_market_cap")),
        (f"Avg Volume  ({fmt_num(f.get('avg_volume_K', 0) * 1e3 if f.get('avg_volume_K') else 0)})", f.get("c_volume")),
    ]
    for label, passed in fund_criteria:
        if passed is None:
            passed = False
        print(f"      {check(passed)}  {label}")

    print(f"\n  {bold('VCP PATTERN')}")
    if v.get("vcp_detected"):
        print(f"      {green('✓')}  VCP Detected — {v.get('vcp_contractions')} contractions")
        print(f"         Pivot: {fmt_price(v.get('vcp_pivot_price'))}  "
              f"Stop: {fmt_price(v.get('vcp_stop_price'))}")
        print(f"         From pivot: {v.get('vcp_pct_from_pivot', 0):.1f}%  "
              f"Quality: {v.get('vcp_pattern_quality', 0):.0f}/100")
        print(f"         {dim(v.get('vcp_notes', ''))}")
    else:
        print(f"      {dim('—')}  No VCP detected  {dim(v.get('vcp_notes', ''))}")

    print(f"\n  Volume Trend: {_vol_trend_str(t.get('volume_trend'))}  "
          f"Acc/Dist Ratio: {t.get('acc_dist_ratio', 0):.2f}")
    print(f"  RS Line Trending Up: {check(t.get('rs_line_trending_up', False))}")
    print(f"  Score: {bold(str(round(r.get('score', 0))))}/100")


def _print_short_detail(r: dict):
    """Print the inverse (short) Trend Template breakdown for a single stock."""
    t = r.get("technical", {})
    print(f"\n  {bold('SHORT TREND TEMPLATE')}  ({t.get('short_criteria_passed', '0/10')})")
    criteria = [
        (f"S1  Price < 150 SMA  (${t.get('sma_150', 0):.2f})", t.get("s1_price_below_sma150")),
        (f"S2  Price < 200 SMA  (${t.get('sma_200', 0):.2f})", t.get("s2_price_below_sma200")),
        ("S3  150 SMA < 200 SMA", t.get("s3_sma150_below_sma200")),
        ("S4  200 SMA trending down ≥ 1 month", t.get("s4_sma200_trending_down")),
        ("S5  50 SMA < 150 SMA", t.get("s5_sma50_below_sma150")),
        ("S6  50 SMA < 200 SMA", t.get("s6_sma50_below_sma200")),
        (f"S7  Price < 50 SMA  (${t.get('sma_50', 0):.2f})", t.get("s7_price_below_sma50")),
        (f"S8  Within 25% of 52wk low  ({t.get('pct_above_52wk_low', 0):.1f}% above low)", t.get("s8_near_52wk_low")),
        (f"S9  ≥25% below 52wk high  ({t.get('pct_from_52wk_high', 0):.1f}% off)", t.get("s9_far_from_52wk_high")),
        (f"S10 RS Rating ≤ 30  ({t.get('rs_rating', 0):.0f})", t.get("s10_rs_weak")),
    ]
    for label, passed in criteria:
        print(f"      {check(passed)}  {label}")
    verdict = green("SHORT CANDIDATE") if t.get("passes_short_trend_template") else dim("not a short candidate")
    print(f"\n  Verdict: {verdict}")


def _vol_trend_str(trend: str) -> str:
    if trend == "accumulation":
        return green("Accumulation")
    if trend == "distribution":
        return red("Distribution")
    return yellow("Neutral")


# ─────────────────────────────────────────────────────────────────────────────
# File Output
# ─────────────────────────────────────────────────────────────────────────────

def save_csv(results: list[dict], output_dir: str = "output/") -> str:
    """Save screener results to a CSV file."""
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filepath = os.path.join(output_dir, f"minervini_screener_{date_str}.csv")

    if not results:
        return filepath

    # Flatten nested dicts for CSV
    flat_rows = []
    for r in results:
        row = {"ticker": r.get("ticker"), "score": r.get("score")}
        row.update(r.get("technical", {}))
        row.update(r.get("fundamental", {}))
        row.update(r.get("vcp", {}))
        flat_rows.append(row)

    fieldnames = list(flat_rows[0].keys())
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_rows)

    return filepath


def save_json(results: list[dict], output_dir: str = "output/") -> str:
    """Save screener results to a JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filepath = os.path.join(output_dir, f"minervini_screener_{date_str}.json")

    with open(filepath, "w") as f:
        json.dump(results, f, indent=2, default=str)

    return filepath


def print_summary_stats(results: list[dict], all_results: list[dict]):
    """Print summary statistics about the screening run."""
    if not all_results:
        return

    tech_pass = sum(1 for r in all_results if r.get("technical", {}).get("passes_trend_template"))
    fund_pass = sum(1 for r in all_results if r.get("fundamental", {}).get("passes_mandatory_fundamentals"))
    vcp_pass = sum(1 for r in all_results if r.get("vcp", {}).get("vcp_detected"))
    full_pass = len(results)
    near_pivot = sum(1 for r in results if r.get("vcp", {}).get("vcp_near_pivot"))

    print(bold("  SCREENING SUMMARY"))
    print(f"  Total screened        : {len(all_results)}")
    print(f"  Pass Trend Template   : {green(str(tech_pass))}")
    print(f"  Pass Fundamentals     : {green(str(fund_pass))}")
    print(f"  VCP Patterns Found    : {green(str(vcp_pass))}")
    print(f"  Pass All Criteria     : {green(bold(str(full_pass)))}")
    print(f"  Near Pivot (≤5%)      : {cyan(str(near_pivot))}")
    print()
