#!/usr/bin/env python3
"""Headless daily scan for the web app / cron.

Runs the Minervini SEPA screener and writes one history JSON per day in the
exact schema the dashboard's History tab reads (_hist_load / _hist_compare).
Same-day re-runs overwrite. No console formatting, no interactivity.

    python3 daily_scan.py [universe]     # default: sp500
"""
import json
import os
import sys
from datetime import datetime

import config as cfg
from screener.universe import get_universe
from screener.screener import MinerviniScreener

HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "output", "scan_history")


def main(universe: str = "sp500") -> str:
    config = {k: dict(getattr(cfg, k)) for k in (
        "TREND_TEMPLATE", "FUNDAMENTALS", "RS_CALCULATION", "VCP",
        "VOLUME", "RISK", "UNIVERSE", "OUTPUT", "SCORING")}

    tickers = get_universe(universe, cfg.UNIVERSE["custom_file"])
    if not tickers:
        sys.exit(f"No tickers for universe '{universe}'")

    passed, all_results = MinerviniScreener(config).run(tickers, verbose=False)
    n_screened = len([r for r in all_results if r.get("technical")])

    def _tech(r, key):
        return r.get("technical", {}).get(key)

    os.makedirs(HISTORY_DIR, exist_ok=True)
    ts = datetime.now()
    fpath = os.path.join(HISTORY_DIR, ts.strftime("scan_%Y-%m-%d.json"))
    with open(fpath, "w") as fh:
        json.dump({
            "timestamp": ts.isoformat(),
            "date": ts.strftime("%Y-%m-%d"),
            "universe": universe,
            "n_screened": n_screened,
            "n_passed": len(passed),
            "results": passed,
            # the hosted dashboard can't re-screen (Yahoo blocks Streamlit
            # Cloud IPs), so persist what it would otherwise recompute
            "n_trend_pass": sum(1 for r in all_results
                                if _tech(r, "passes_trend_template")),
            "shorts": [r for r in all_results
                       if _tech(r, "passes_short_trend_template")],
        }, fh)

    print(f"{ts:%Y-%m-%d}: {len(passed)} passed / {n_screened} screened -> {fpath}")
    return fpath


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sp500")
