#!/usr/bin/env python3
"""
Minervini SEPA Daily Stock Screener
====================================
Screens stocks using Mark Minervini's Specific Entry Point Analysis (SEPA)
methodology from "Trade Like a Stock Market Wizard" and
"Think & Trade Like a Champion".

Usage:
    python main.py                          # Screen S&P 500
    python main.py --universe nasdaq100     # Screen NASDAQ 100
    python main.py --universe russell2000   # Screen Russell 2000
    python main.py --universe custom        # Screen tickers from universe/custom.txt
    python main.py --tickers AAPL MSFT NVDA # Screen specific tickers
    python main.py --universe sp500 --min-rs 80  # Tighter RS filter
    python main.py --clear-cache            # Clear cached data and re-fetch
    python main.py --no-fundamentals        # Skip fundamental analysis (faster)
    python main.py --detail                 # Show detailed breakdown per stock
"""

import sys
import time
import argparse
import logging
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
from screener.universe import get_universe
from screener.screener import MinerviniScreener
from screener.report import (
    print_banner, print_results_table, print_summary_stats,
    save_csv, save_json
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Minervini SEPA Daily Stock Screener",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--method", "-m",
        choices=["minervini", "oneil"],
        default="minervini",
        help="Screening methodology: 'minervini' (SEPA) or 'oneil' (CAN SLIM / IBD)"
    )
    parser.add_argument(
        "--universe", "-u",
        default=cfg.UNIVERSE["default_universe"],
        choices=["sp500", "nasdaq100", "russell2000", "custom"],
        help="Stock universe to screen (default: %(default)s)"
    )
    parser.add_argument(
        "--tickers", "-t",
        nargs="+",
        help="Screen specific tickers (overrides --universe)"
    )
    parser.add_argument(
        "--min-rs",
        type=float,
        default=cfg.TREND_TEMPLATE["rs_rating_min"],
        help="Minimum RS Rating required (default: %(default)s)"
    )
    parser.add_argument(
        "--min-eps",
        type=float,
        default=cfg.FUNDAMENTALS["eps_growth_current_qtr_min"] * 100,
        help="Minimum quarterly EPS growth %% (default: %(default)s)"
    )
    parser.add_argument(
        "--min-sales",
        type=float,
        default=cfg.FUNDAMENTALS["sales_growth_min"] * 100,
        help="Minimum quarterly sales growth %% (default: %(default)s)"
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=cfg.RISK["min_price"],
        help="Minimum stock price (default: $%(default)s)"
    )
    parser.add_argument(
        "--sort-by",
        choices=["rs_rating", "score", "eps_growth", "vcp_quality"],
        default=cfg.OUTPUT["sort_by"],
        help="Sort results by this field (default: %(default)s)"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=cfg.OUTPUT["max_results"],
        help="Max results to display (default: %(default)s)"
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        default=cfg.OUTPUT["show_all_criteria"],
        help="Show detailed criteria breakdown per stock"
    )
    parser.add_argument(
        "--no-fundamentals",
        action="store_true",
        help="Skip fundamental analysis (technical only, much faster)"
    )
    parser.add_argument(
        "--no-vcp",
        action="store_true",
        help="Skip VCP pattern detection"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save results to CSV"
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear all cached data before running"
    )
    parser.add_argument(
        "--output-dir",
        default=cfg.OUTPUT["output_dir"],
        help="Directory for output files (default: %(default)s)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=True,
        help="Verbose output (default: True)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output"
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: %(default)s)"
    )
    return parser.parse_args()


def build_config(args) -> dict:
    """Build config dict with CLI overrides applied."""
    # Deep copy base config
    config = {
        "TREND_TEMPLATE": dict(cfg.TREND_TEMPLATE),
        "FUNDAMENTALS": dict(cfg.FUNDAMENTALS),
        "RS_CALCULATION": dict(cfg.RS_CALCULATION),
        "VCP": dict(cfg.VCP),
        "VOLUME": dict(cfg.VOLUME),
        "RISK": dict(cfg.RISK),
        "UNIVERSE": dict(cfg.UNIVERSE),
        "OUTPUT": dict(cfg.OUTPUT),
        "SCORING": dict(cfg.SCORING),
    }

    # Apply CLI overrides
    config["TREND_TEMPLATE"]["rs_rating_min"] = args.min_rs
    config["FUNDAMENTALS"]["eps_growth_current_qtr_min"] = args.min_eps / 100
    config["FUNDAMENTALS"]["sales_growth_min"] = args.min_sales / 100
    config["RISK"]["min_price"] = args.min_price
    config["OUTPUT"]["sort_by"] = args.sort_by
    config["OUTPUT"]["max_results"] = args.top
    config["OUTPUT"]["output_dir"] = args.output_dir

    return config


def main():
    args = parse_args()
    verbose = args.verbose and not args.quiet

    # ── Logging setup ────────────────────────────────────────────────────────
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # ── Build config with overrides ──────────────────────────────────────────
    config = build_config(args)

    # ── Determine ticker universe ────────────────────────────────────────────
    if args.tickers:
        tickers = [t.upper().strip() for t in args.tickers]
        universe_name = "custom"
        if verbose:
            print(f"\n  Screening {len(tickers)} specific tickers: {', '.join(tickers)}")
    else:
        universe_name = args.universe
        if verbose:
            print(f"\n  Loading {universe_name.upper()} universe...")
        tickers = get_universe(universe_name, cfg.UNIVERSE["custom_file"])
        if verbose:
            print(f"  {len(tickers)} tickers loaded.")

    if not tickers:
        print("  [ERROR] No tickers to screen. Exiting.")
        sys.exit(1)

    # ── Initialize screener ──────────────────────────────────────────────────
    if args.method == "oneil":
        from screener.oneil_screener import CANSLIMScreener
        config["CAN_SLIM"] = dict(cfg.CAN_SLIM)
        config["BASE_PATTERNS"] = dict(cfg.BASE_PATTERNS)
        config["CAN_SLIM_SCORING"] = dict(cfg.CAN_SLIM_SCORING)
        screener = CANSLIMScreener(config)
    else:
        screener = MinerviniScreener(config)

    # ── Clear cache if requested ─────────────────────────────────────────────
    if args.clear_cache:
        screener.data_fetcher.clear_cache()

    # ── Run the screener ─────────────────────────────────────────────────────
    start_time = time.time()
    if args.method == "oneil":
        passed_results, all_results, market = screener.run(tickers, verbose=verbose)
        if verbose:
            print(f"\n  === Market Direction (M): {market.status.upper()} ===")
            if not market.confirmed_uptrend:
                print("  ⚠  Market NOT in confirmed uptrend — O'Neil rule: avoid new buys.")
    else:
        passed_results, all_results = screener.run(tickers, verbose=verbose)
    elapsed = time.time() - start_time

    # ── Print results ────────────────────────────────────────────────────────
    print_banner(
        universe=universe_name,
        total_screened=len([r for r in all_results if r.get("technical")]),
        total_passed=len(passed_results),
        elapsed_secs=elapsed,
    )

    if args.method == "oneil":
        _print_canslim_results(passed_results, all_results, max_rows=args.top)
    else:
        print_summary_stats(passed_results, all_results)
        if passed_results:
            print_results_table(
                passed_results,
                max_rows=args.top,
                show_all_criteria=args.detail,
            )
        else:
            _print_top_near_misses(all_results, n=10)

    # ── Save output ──────────────────────────────────────────────────────────
    if not args.no_save and passed_results:
        csv_path = save_csv(passed_results, args.output_dir)
        if verbose:
            print(f"  Results saved: {csv_path}")

    # ── Print near-pivot watchlist ────────────────────────────────────────────
    near_pivot = [r for r in passed_results if r.get("vcp", {}).get("vcp_near_pivot")]
    if near_pivot:
        print(f"\n  {'─'*60}")
        print(f"  NEAR PIVOT WATCHLIST ({len(near_pivot)} stocks within 5% of pivot)")
        print(f"  {'─'*60}")
        for r in near_pivot:
            t = r.get("technical", {})
            v = r.get("vcp", {})
            ticker = r.get("ticker", "")
            price = t.get("current_price", 0)
            pivot = v.get("vcp_pivot_price", 0)
            pct_away = v.get("vcp_pct_from_pivot", 0)
            rs = t.get("rs_rating", 0)
            print(f"  ★  {ticker:<6} | Price: ${price:.2f} | Pivot: ${pivot:.2f} | "
                  f"{pct_away:.1f}% from pivot | RS: {rs:.0f}")
        print()

    return 0 if passed_results else 1


def _print_top_near_misses(all_results: list[dict], n: int = 10):
    """Print the top stocks that came closest to passing all criteria."""
    from screener.report import yellow, dim, bold, cyan
    # Sort by criteria_passed count
    candidates = []
    for r in all_results:
        t = r.get("technical", {})
        f = r.get("fundamental", {})
        tech_passed = t.get("criteria_passed", "0/10")
        try:
            passed_count = int(str(tech_passed).split("/")[0])
        except Exception:
            passed_count = 0
        candidates.append((passed_count, r.get("ticker", ""), r))

    candidates.sort(reverse=True)

    print(yellow("  No stocks passed all criteria. Top near-misses:"))
    print(f"  {'─'*60}")
    for _, ticker, r in candidates[:n]:
        t = r.get("technical", {})
        print(f"  {cyan(ticker):<10} Trend Template: {t.get('criteria_passed','?')} | "
              f"RS: {t.get('rs_rating', 0):.0f} | "
              f"Stage: {t.get('stage', '?')} | "
              f"Price: ${t.get('current_price', 0):.2f}")
    print()


def _print_canslim_results(passed: list[dict], all_results: list[dict], max_rows: int = 50):
    """Simple console table for CAN SLIM results."""
    from screener.report import green, yellow, cyan, bold, dim

    if not passed:
        print(yellow("\n  No stocks passed all 7 CAN SLIM criteria. Top near-misses:"))
        near = sorted(
            all_results,
            key=lambda r: int(r.get("canslim", {}).get("canslim_passed", "0/7").split("/")[0]),
            reverse=True,
        )[:10]
        print(f"  {'─'*90}")
        for r in near:
            cs = r.get("canslim", {})
            b = r.get("base", {})
            print(f"  {cyan(r['ticker']):<10} [{cs.get('canslim_letters','')}] "
                  f"{cs.get('canslim_passed','?')}  RS:{cs.get('rs_rating',0):>3.0f}  "
                  f"EPS:{str(cs.get('eps_growth_current_qtr_pct','?')):>7}%  "
                  f"base:{b.get('base_pattern','none')}")
        print()
        return

    print(green(f"\n  {len(passed)} stocks passed all 7 CAN SLIM criteria:"))
    print(f"  {'─'*108}")
    hdr = (f"  {'Ticker':<7} {'Score':>6} {'RS':>4} {'EPS%':>7} {'Sales%':>7} "
           f"{'Base':<14} {'Pivot':>8} {'%Piv':>7} {'Letters':<16} Sector")
    print(bold(hdr))
    print(f"  {'─'*108}")
    for r in passed[:max_rows]:
        cs = r.get("canslim", {})
        b = r.get("base", {})
        print(f"  {r['ticker']:<7} {r.get('score',0):>6.1f} "
              f"{cs.get('rs_rating',0):>4.0f} "
              f"{str(cs.get('eps_growth_current_qtr_pct','?')):>7} "
              f"{str(cs.get('sales_growth_pct','?')):>7} "
              f"{b.get('base_pattern','none'):<14} "
              f"${b.get('base_pivot_price',0):>7.2f} "
              f"{b.get('base_pct_from_pivot',0):>+6.1f}% "
              f"{cs.get('canslim_letters',''):<16} "
              f"{dim(r.get('sector','')[:25])}")
    print()

    near_pivot = [r for r in passed if r.get("base", {}).get("base_near_pivot")]
    if near_pivot:
        print(f"  {'─'*60}")
        print(bold(f"  ⭐ NEAR PIVOT — BREAKOUT CANDIDATES ({len(near_pivot)})"))
        print(f"  {'─'*60}")
        for r in near_pivot:
            b = r["base"]
            print(f"  {r['ticker']:<7} {b['base_pattern']:<14} "
                  f"pivot ${b['base_pivot_price']:.2f}  "
                  f"stop ${b['base_stop_price']:.2f}  "
                  f"{b['base_pct_from_pivot']:+.1f}% away")
        print()


if __name__ == "__main__":
    sys.exit(main())
