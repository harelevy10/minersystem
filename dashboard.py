"""
Minervini SEPA Stock Screener — Web Dashboard
Run with: streamlit run dashboard.py
"""

import sys
import os
import time
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config as cfg
from screener.universe import get_universe
from screener.screener import MinerviniScreener

# ─────────────────────────────────────────────────────────────────────────────
# Watchlist persistence
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_DIR  = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(_PROJECT_DIR, "watchlist.json")
HISTORY_DIR    = os.path.join(_PROJECT_DIR, "output", "scan_history")
os.makedirs(HISTORY_DIR, exist_ok=True)


def _load_watchlist() -> dict:
    """Returns {ticker: {added_date, added_price, notes}}"""
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_watchlist(wl: dict):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(wl, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Scan history persistence
# ─────────────────────────────────────────────────────────────────────────────

def _hist_save(passed: list, universe: str, n_screened: int) -> str:
    """Persist a scan run to disk. Returns the saved filepath."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    ts = datetime.now()
    fname = ts.strftime("scan_%Y-%m-%d_%H-%M-%S.json")
    payload = {
        "timestamp": ts.isoformat(),
        "date":      ts.strftime("%Y-%m-%d"),
        "universe":  universe,
        "n_screened": n_screened,
        "n_passed":  len(passed),
        "results":   passed,
    }
    fpath = os.path.join(HISTORY_DIR, fname)
    with open(fpath, "w") as fh:
        json.dump(payload, fh)
    return fpath


def _hist_list() -> list:
    """Return [(filepath, meta_dict), …] sorted newest-first."""
    if not os.path.exists(HISTORY_DIR):
        return []
    files = sorted(
        [f for f in os.listdir(HISTORY_DIR) if f.endswith(".json")],
        reverse=True,
    )
    out = []
    for fname in files:
        fpath = os.path.join(HISTORY_DIR, fname)
        try:
            with open(fpath) as fh:
                d = json.load(fh)
            ts_str = d.get("timestamp", "")
            time_part = ts_str[11:16] if len(ts_str) > 10 else ""
            out.append((fpath, {
                "timestamp":  ts_str,
                "date":       d.get("date", ""),
                "universe":   d.get("universe", ""),
                "n_screened": d.get("n_screened", 0),
                "n_passed":   d.get("n_passed", 0),
                "label": (
                    f"{d.get('date','')}  {time_part}"
                    f"  ·  {d.get('universe','').upper()}"
                    f"  ·  {d.get('n_passed',0)} stocks found"
                ),
            }))
        except Exception:
            pass
    return out


def _hist_load(filepath: str) -> dict:
    with open(filepath) as fh:
        return json.load(fh)


def _hist_compare(scan_a: dict, scan_b: dict) -> dict:
    """
    Compare scan_a (baseline/older) vs scan_b (newer).
    Returns { new, dropped, improved, degraded, unchanged }.
    """
    def _idx(scan):
        return {r["ticker"]: r for r in scan.get("results", []) if r.get("ticker")}

    idx_a = _idx(scan_a)
    idx_b = _idx(scan_b)
    set_a, set_b = set(idx_a), set(idx_b)

    new     = [idx_b[t] for t in sorted(set_b - set_a)]
    dropped = [idx_a[t] for t in sorted(set_a - set_b)]

    improved, degraded, unchanged = [], [], []
    for t in sorted(set_a & set_b):
        ra, rb = idx_a[t], idx_b[t]
        rs_a    = ra.get("technical", {}).get("rs_rating", 0) or 0
        rs_b    = rb.get("technical", {}).get("rs_rating", 0) or 0
        score_a = ra.get("score", 0) or 0
        score_b = rb.get("score", 0) or 0
        rb["_delta"] = {"rs": rs_b - rs_a, "score": score_b - score_a,
                        "rs_a": rs_a, "score_a": score_a}
        if rs_b > rs_a + 2 or score_b > score_a + 3:
            improved.append(rb)
        elif rs_b < rs_a - 2 or score_b < score_a - 3:
            degraded.append(rb)
        else:
            unchanged.append(rb)

    return dict(new=new, dropped=dropped, improved=improved,
                degraded=degraded, unchanged=unchanged)


def _wl_add(ticker: str, price=None, snapshot=None):
    wl = st.session_state.watchlist
    if ticker not in wl:
        wl[ticker] = {
            "added_date": datetime.now().strftime("%Y-%m-%d"),
            "added_price": round(price, 2) if price else None,
            "notes": "",
            "snapshot": snapshot or {},   # RS, score, pivot, stop, status, vcp_pct at add time
        }
        st.session_state.watchlist = wl
        _save_watchlist(wl)


def _wl_remove(ticker: str):
    wl = st.session_state.watchlist
    wl.pop(ticker, None)
    wl_data = st.session_state.get("watchlist_data", {})
    wl_data.pop(ticker, None)
    st.session_state.watchlist = wl
    st.session_state.watchlist_data = wl_data
    _save_watchlist(wl)

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Minervini SEPA Screener",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
  /* ── Global & fonts ───────────────────────────────────────────────────── */
  html, body, [class*="css"] { font-family: "Inter", "Segoe UI", sans-serif; }

  /* Custom scrollbar */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: #0d0f1a; }
  ::-webkit-scrollbar-thumb { background: #2d3748; border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: #4a5568; }

  /* ── Header ──────────────────────────────────────────────────────────── */
  .main-header {
    background: linear-gradient(135deg, #0d0f1a 0%, #16213e 60%, #1a1a2e 100%);
    padding: 1.2rem 2rem;
    border-radius: 14px;
    margin-bottom: 1.2rem;
    border: 1px solid rgba(233,69,96,0.4);
    box-shadow: 0 0 32px rgba(233,69,96,0.08), inset 0 1px 0 rgba(255,255,255,0.04);
  }
  .main-header h1 {
    color: #ffffff;
    font-size: 1.65rem;
    font-weight: 700;
    margin: 0;
    letter-spacing: 0.5px;
  }
  .main-header p { color: #718096; margin: 0.25rem 0 0; font-size: 0.85rem; }

  /* ── Tabs ─────────────────────────────────────────────────────────────── */
  button[data-baseweb="tab"] {
    font-size: 0.9rem !important;
    font-weight: 600 !important;
    padding: 0.55rem 1.2rem !important;
    transition: color 0.15s;
  }
  button[data-baseweb="tab"][aria-selected="true"] {
    color: #63b3ed !important;
    border-bottom-color: #63b3ed !important;
  }

  /* ── Sidebar ──────────────────────────────────────────────────────────── */
  section[data-testid="stSidebar"] {
    background: #080a14;
    border-right: 1px solid #1a1f35;
  }
  section[data-testid="stSidebar"] .stMarkdown hr { border-color: #1e2535; }

  /* ── Streamlit metric overrides ───────────────────────────────────────── */
  [data-testid="stMetric"] {
    background: #111521;
    border: 1px solid #1e2535;
    border-radius: 10px;
    padding: 0.7rem 1rem;
    transition: border-color 0.2s;
  }
  [data-testid="stMetric"]:hover { border-color: #2d3f6a; }
  [data-testid="stMetricLabel"] { font-size: 0.7rem !important; color: #4a5568 !important; letter-spacing: 1px; text-transform: uppercase; }
  [data-testid="stMetricValue"] { font-size: 1.55rem !important; font-weight: 700 !important; color: #e2e8f0 !important; }
  [data-testid="stMetricDelta"] { font-size: 0.78rem !important; }

  /* ── Expander ─────────────────────────────────────────────────────────── */
  [data-testid="stExpander"] {
    border: 1px solid #1e2535 !important;
    border-radius: 10px !important;
    background: #0e111d !important;
    margin-bottom: 0.5rem;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  [data-testid="stExpander"]:hover {
    border-color: #2d3f6a !important;
    box-shadow: 0 2px 16px rgba(99,179,237,0.05);
  }
  [data-testid="stExpander"] summary {
    font-weight: 600 !important;
    font-size: 0.9rem !important;
  }

  /* ── Buttons ─────────────────────────────────────────────────────────── */
  .stButton > button {
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: all 0.15s !important;
    border: 1px solid #2d3748 !important;
  }
  .stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
  }
  .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #2b6cb0, #1a365d) !important;
    border-color: #3182ce !important;
    box-shadow: 0 0 16px rgba(49,130,206,0.25) !important;
  }
  .stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #3182ce, #2b6cb0) !important;
    box-shadow: 0 0 24px rgba(49,130,206,0.4) !important;
  }

  /* ── Near pivot alert ─────────────────────────────────────────────────── */
  .pivot-alert {
    background: linear-gradient(135deg, #1a2644 0%, #0e111d 100%);
    border: 1px solid rgba(66,153,225,0.35);
    border-left: 3px solid #4299e1;
    border-radius: 10px;
    padding: 0.85rem 1.1rem;
    margin-bottom: 0.5rem;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .pivot-alert:hover {
    border-color: rgba(66,153,225,0.7);
    box-shadow: 0 2px 20px rgba(66,153,225,0.1);
  }
  .pivot-alert .ticker { color: #63b3ed; font-weight: 700; font-size: 1.05rem; }
  .pivot-alert .detail { color: #718096; font-size: 0.82rem; line-height: 1.6; margin-top: 0.2rem; }

  /* ── Trading Plan Cards ───────────────────────────────────────────────── */
  .tp-card {
    background: #0e111d;
    border: 1px solid #1e2535;
    border-radius: 10px;
    padding: 0.85rem 1.1rem;
    margin-bottom: 0.55rem;
    transition: box-shadow 0.2s, border-color 0.2s;
  }
  .tp-card:hover { box-shadow: 0 2px 16px rgba(0,0,0,0.3); }
  .tp-entry { border-left: 3px solid #48bb78; }
  .tp-entry:hover { border-color: #48bb78; box-shadow: 0 2px 20px rgba(72,187,120,0.08); }
  .tp-stop  { border-left: 3px solid #fc8181; }
  .tp-stop:hover  { border-color: #fc8181; box-shadow: 0 2px 20px rgba(252,129,129,0.08); }
  .tp-target{ border-left: 3px solid #63b3ed; }
  .tp-target:hover{ border-color: #63b3ed; box-shadow: 0 2px 20px rgba(99,179,237,0.08); }
  .tp-size  { border-left: 3px solid #b794f4; }
  .tp-size:hover  { border-color: #b794f4; box-shadow: 0 2px 20px rgba(183,148,244,0.08); }

  .tp-label {
    color: #4a5568;
    font-size: 0.66rem;
    text-transform: uppercase;
    letter-spacing: 1.8px;
    margin-bottom: 0.25rem;
  }
  .tp-value { color: #e2e8f0; font-size: 1.2rem; font-weight: 700; line-height: 1.2; }
  .tp-sub   { color: #718096; font-size: 0.76rem; margin-top: 0.2rem; line-height: 1.5; }

  /* Badges */
  .tp-badge-buy  { background:rgba(39,103,73,0.8); color:#9ae6b4; border-radius:5px; padding:3px 9px; font-size:0.72rem; font-weight:700; letter-spacing:0.5px; }
  .tp-badge-wait { background:rgba(116,66,16,0.8); color:#fbd38d; border-radius:5px; padding:3px 9px; font-size:0.72rem; font-weight:700; }
  .tp-badge-rr-good { background:rgba(45,63,122,0.8); color:#90cdf4; border-radius:5px; padding:3px 9px; font-size:0.72rem; font-weight:700; }

  /* ── Thesis box ────────────────────────────────────────────────────────── */
  .thesis-box {
    background: #0a0d18;
    border: 1px solid #1e2535;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    color: #a0aec0;
    font-size: 0.83rem;
    line-height: 1.75;
    margin-top: 0.6rem;
  }
  .thesis-box b { color: #e2e8f0; }
  .thesis-box p { margin: 0 0 0.4rem; }

  /* ── Dataframe ────────────────────────────────────────────────────────── */
  [data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }

  /* ── Progress bar (score column) ─────────────────────────────────────── */
  [data-testid="stDataFrameProgressColumn"] > div { border-radius: 3px !important; }

  /* ── Spinner ─────────────────────────────────────────────────────────── */
  [data-testid="stSpinner"] { color: #63b3ed !important; }

  /* ── Alerts / info ────────────────────────────────────────────────────── */
  [data-testid="stAlert"] { border-radius: 10px !important; }

  /* ── Hide Streamlit chrome ────────────────────────────────────────────── */
  #MainMenu { visibility: hidden; }
  footer     { visibility: hidden; }
  header     { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — Controls
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Screener Settings")
    st.markdown("---")

    st.markdown("**Universe**")
    universe = st.selectbox(
        "Stock Universe",
        options=["sp500", "nasdaq100", "russell2000", "custom"],
        format_func=lambda x: {
            "sp500": "S&P 500 (~503 stocks)",
            "nasdaq100": "NASDAQ-100",
            "russell2000": "Russell 2000",
            "custom": "Custom (universe/custom.txt)",
        }[x],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("**Trend Template**")

    min_rs = st.slider("Min RS Rating", 50, 99, int(cfg.TREND_TEMPLATE["rs_rating_min"]),
                       help="IBD-style RS Rating — 70+ is Minervini's floor, 80+ is ideal")
    pct_from_high = st.slider("Max % from 52wk High", 5, 40,
                               int(cfg.TREND_TEMPLATE["pct_from_52wk_high"] * 100),
                               help="Stock must be within this % of its 52-week high")
    pct_above_low = st.slider("Min % above 52wk Low", 10, 50,
                               int(cfg.TREND_TEMPLATE["pct_above_52wk_low"] * 100),
                               help="Stock must be at least this % above its 52-week low")

    st.markdown("---")
    st.markdown("**Fundamentals**")

    min_eps = st.slider("Min EPS Growth % (curr qtr)", 0, 100,
                        int(cfg.FUNDAMENTALS["eps_growth_current_qtr_min"] * 100),
                        help="Year-over-year EPS growth for the most recent quarter")
    min_sales = st.slider("Min Sales Growth %", 0, 60,
                          int(cfg.FUNDAMENTALS["sales_growth_min"] * 100),
                          help="Year-over-year revenue growth for the most recent quarter")
    min_roe = st.slider("Min ROE %", 0, 50,
                        int(cfg.FUNDAMENTALS["roe_min"] * 100),
                        help="Return on Equity — Minervini's minimum is 17%")

    st.markdown("---")
    st.markdown("**Filters**")
    min_price = st.number_input("Min Price ($)", value=float(cfg.RISK["min_price"]),
                                min_value=1.0, max_value=100.0, step=5.0)
    min_mktcap = st.number_input("Min Market Cap ($M)", value=300, min_value=0, step=100)
    require_vcp = st.checkbox("Require VCP Pattern", value=False,
                              help="Only show stocks with a confirmed VCP base")
    near_pivot_only = st.checkbox("Near Pivot Only (≤5%)", value=False,
                                  help="Only show stocks within 5% of their pivot entry point")

    st.markdown("---")
    st.markdown("**Position Sizing**")
    portfolio_size = st.number_input(
        "Portfolio Size ($)",
        value=100_000,
        min_value=1_000,
        max_value=10_000_000,
        step=10_000,
        help="Used to calculate position size based on Minervini's 1% risk rule",
    )
    risk_per_trade_pct = st.slider(
        "Risk Per Trade (%)",
        min_value=0.5, max_value=3.0, value=1.0, step=0.25,
        help="Max % of portfolio to risk on a single trade (Minervini recommends 1%)",
    )

    st.markdown("---")
    clear_cache = st.checkbox("Clear Cache (fresh data)", value=False)

    run_btn = st.button("🚀 Run Screener", use_container_width=True, type="primary")

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(f"""
<div class="main-header">
  <h1>📈 Minervini SEPA Stock Screener</h1>
  <p>Specific Entry Point Analysis &nbsp;·&nbsp; Stage 2 Trend Template &nbsp;·&nbsp;
     VCP Pattern Detection &nbsp;·&nbsp; {datetime.now().strftime("%B %d, %Y")}</p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────

if "results" not in st.session_state:
    st.session_state.results = None
if "all_results" not in st.session_state:
    st.session_state.all_results = None
if "last_run" not in st.session_state:
    st.session_state.last_run = None
if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = None
if "portfolio_size" not in st.session_state:
    st.session_state.portfolio_size = 100_000
if "risk_per_trade_pct" not in st.session_state:
    st.session_state.risk_per_trade_pct = 1.0
if "watchlist" not in st.session_state:
    st.session_state.watchlist = _load_watchlist()
if "watchlist_data" not in st.session_state:
    st.session_state.watchlist_data = {}
if "wl_refresh_requested" not in st.session_state:
    st.session_state.wl_refresh_requested = False
# CAN SLIM (O'Neil) state
if "canslim_results" not in st.session_state:
    st.session_state.canslim_results = None
if "canslim_all_results" not in st.session_state:
    st.session_state.canslim_all_results = None
if "canslim_market" not in st.session_state:
    st.session_state.canslim_market = None
if "canslim_last_run" not in st.session_state:
    st.session_state.canslim_last_run = None

# ─────────────────────────────────────────────────────────────────────────────
# Run screener
# ─────────────────────────────────────────────────────────────────────────────

if run_btn:
    # Build config with UI overrides
    run_config = {
        "TREND_TEMPLATE": {
            **cfg.TREND_TEMPLATE,
            "rs_rating_min": min_rs,
            "pct_from_52wk_high": pct_from_high / 100,
            "pct_above_52wk_low": pct_above_low / 100,
        },
        "FUNDAMENTALS": {
            **cfg.FUNDAMENTALS,
            "eps_growth_current_qtr_min": min_eps / 100,
            "sales_growth_min": min_sales / 100,
            "roe_min": min_roe / 100,
            "market_cap_min": min_mktcap * 1_000_000,
        },
        "RS_CALCULATION": cfg.RS_CALCULATION,
        "VCP": cfg.VCP,
        "VOLUME": cfg.VOLUME,
        "RISK": {**cfg.RISK, "min_price": min_price},
        "UNIVERSE": cfg.UNIVERSE,
        "OUTPUT": cfg.OUTPUT,
        "SCORING": cfg.SCORING,
    }

    screener = MinerviniScreener(run_config)

    if clear_cache:
        screener.data_fetcher.clear_cache()

    with st.spinner(f"Loading {universe.upper()} universe..."):
        tickers = get_universe(universe, cfg.UNIVERSE["custom_file"])

    progress_bar = st.progress(0, text=f"Fetching data for {len(tickers)} stocks...")

    # Patch data_fetcher to update progress bar
    total = len(tickers)
    fetched = [0]

    original_callback = None

    def progress_update():
        fetched[0] += 1
        pct = min(fetched[0] / total, 1.0)
        progress_bar.progress(pct, text=f"Fetching price data... {fetched[0]}/{total}")

    # Temporarily monkey-patch to get progress
    orig_batch = screener.data_fetcher.batch_fetch_prices

    def patched_batch(ticks, period="2y", progress_callback=None):
        return orig_batch(ticks, period=period, progress_callback=progress_update)

    screener.data_fetcher.batch_fetch_prices = patched_batch

    t0 = time.time()
    with st.spinner("Running SEPA analysis..."):
        passed, all_results = screener.run(tickers, verbose=False)
    elapsed = time.time() - t0

    progress_bar.empty()

    # Apply post-filters
    if require_vcp:
        passed = [r for r in passed if r.get("vcp", {}).get("vcp_detected")]
    if near_pivot_only:
        passed = [r for r in passed if r.get("vcp", {}).get("vcp_near_pivot")]

    n_screened = len([r for r in all_results if r.get("technical")])
    st.session_state.results = passed
    st.session_state.all_results = all_results
    st.session_state.last_run = {
        "universe":  universe,
        "elapsed":   elapsed,
        "total":     n_screened,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    # Persist scan to history
    try:
        _hist_save(passed, universe, n_screened)
    except Exception:
        pass
    st.session_state.selected_ticker = None
    st.session_state.portfolio_size = portfolio_size
    st.session_state.risk_per_trade_pct = risk_per_trade_pct
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Helper rendering functions  (defined here so they're available below)
# ─────────────────────────────────────────────────────────────────────────────

def _build_results_df(results: list[dict], portfolio_size: float = 100_000,
                      risk_pct: float = 0.01) -> pd.DataFrame:
    rows = []
    for r in results:
        t = r.get("technical", {})
        f = r.get("fundamental", {})
        v = r.get("vcp", {})
        stage_map = {1: "1-Base", 2: "2-Bull", 3: "3-Top", 4: "4-Bear"}
        stage = stage_map.get(t.get("stage", 0), "?")
        vcp_str = f"✓ {v.get('vcp_contractions',0)}T" if v.get("vcp_detected") else "—"

        plan = _build_trading_plan(r, portfolio_size, risk_pct)
        raw_status = plan["status"]
        if "BUY ZONE" in raw_status:
            status_display = "✅ BUY ZONE"
            status_order = 0
        elif "WAIT" in raw_status:
            pct_away = raw_status.split("—")[1].strip() if "—" in raw_status else ""
            status_display = f"⏳ WAIT {pct_away}"
            status_order = 1
        else:
            pct_ext = raw_status.split("—")[1].strip() if "—" in raw_status else ""
            status_display = f"⚠ EXT {pct_ext}"
            status_order = 2

        upside_pct = round((plan["target_1"] - plan["pivot"]) / plan["pivot"] * 100, 1) if plan["pivot"] > 0 else 0

        rows.append({
            "_status_order": status_order,
            "_risk_dollar": plan["risk_per_share"],
            "_risk_pct": plan["risk_pct_entry"],
            "_upside": upside_pct,
            "Status": status_display,
            "Ticker": r.get("ticker", ""),
            "Sector": r.get("sector", ""),
            "Price": t.get("current_price"),
            "Pivot": plan["pivot"],
            "Risk$/sh": plan["risk_per_share"],
            "Risk%": plan["risk_pct_entry"],
            "Upside%": upside_pct,
            "Score": float(r.get("score", 0)),
            "RS": t.get("rs_rating"),
            "EPS%": f.get("eps_growth_current_qtr_pct"),
            "Sales%": f.get("sales_growth_current_qtr_pct"),
            "Stage": stage,
            "VCP": vcp_str,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(
            ["_status_order", "_risk_dollar", "_risk_pct", "_upside"],
            ascending=[True, True, True, False],
        ).reset_index(drop=True)
    df = df.drop(columns=["_status_order", "_risk_dollar", "_risk_pct", "_upside"])
    return df


def _build_trading_plan(r: dict, portfolio_size: float = 100_000,
                        risk_pct: float = 0.01) -> dict:
    """
    Compute a complete Minervini trading plan for a stock.
    Returns a dict with all entry/exit/sizing parameters.
    """
    t = r.get("technical", {})
    v = r.get("vcp", {})
    f = r.get("fundamental", {})

    price = t.get("current_price", 0) or 0
    sma50 = t.get("sma_50", 0) or 0

    # ── Entry ────────────────────────────────────────────────────────────────
    if v.get("vcp_detected") and v.get("vcp_pivot_price", 0):
        pivot = float(v["vcp_pivot_price"])
        stop_raw = float(v.get("vcp_stop_price", pivot * 0.92))
    else:
        # No VCP: use 52-week high as pivot, 50-day SMA as stop guide
        pivot = float(t.get("week_52_high", price * 1.02))
        stop_raw = float(sma50 * 0.99) if sma50 > 0 else price * 0.92

    buy_zone_high = round(pivot * 1.05, 2)      # Don't chase more than 5% above pivot
    in_buy_zone = pivot <= price <= buy_zone_high
    above_pivot = price > buy_zone_high

    # ── Stop Loss ────────────────────────────────────────────────────────────
    # Use the more conservative of: VCP low or 8% below pivot
    stop_8pct = round(pivot * 0.92, 2)
    stop_loss = round(max(stop_raw, stop_8pct * 0.995), 2)  # slightly below 8%
    # Also note the 50-day SMA as a "soft stop" / trailing stop reference
    trailing_stop = round(sma50 * 0.99, 2) if sma50 > 0 else None

    risk_per_share = round(pivot - stop_loss, 2)
    risk_pct_entry = round((pivot - stop_loss) / pivot * 100, 1) if pivot > 0 else 0

    # ── Profit Targets (Minervini: minimum 3:1 R:R) ──────────────────────────
    rr_3to1 = round(pivot + (risk_per_share * 3), 2)   # 3:1 minimum
    target_20pct = round(pivot * 1.20, 2)               # 20% gain — first trim
    target_40pct = round(pivot * 1.40, 2)               # 40% gain — second trim

    # Use whichever is more conservative as T1
    target_1 = max(rr_3to1, target_20pct)
    target_2 = round(pivot * 1.40, 2)

    rr_ratio = round((target_1 - pivot) / risk_per_share, 1) if risk_per_share > 0 else 0

    # ── Position Sizing (1% risk rule) ───────────────────────────────────────
    max_risk_dollars = portfolio_size * risk_pct
    shares = int(max_risk_dollars / risk_per_share) if risk_per_share > 0 else 0
    position_value = round(shares * pivot, 2)
    position_pct_portfolio = round(position_value / portfolio_size * 100, 1) if portfolio_size > 0 else 0

    # ── Trade Status ─────────────────────────────────────────────────────────
    if in_buy_zone:
        status = "BUY ZONE"
    elif price < pivot:
        pct_away = round((pivot - price) / pivot * 100, 1)
        status = f"WAIT — {pct_away:.1f}% below pivot"
    else:
        pct_extended = round((price - buy_zone_high) / buy_zone_high * 100, 1)
        status = f"EXTENDED — {pct_extended:.1f}% past buy zone"

    # ── Trade Thesis ─────────────────────────────────────────────────────────
    eps = f.get("eps_growth_current_qtr_pct")
    sales = f.get("sales_growth_current_qtr_pct")
    roe = f.get("roe_pct")
    rs = t.get("rs_rating", 0)
    stage = t.get("stage", 0)
    vol_trend = t.get("volume_trend", "neutral")
    vcp_n = v.get("vcp_contractions", 0)
    vcp_quality = v.get("vcp_pattern_quality", 0)
    acc_ratio = t.get("acc_dist_ratio", 1.0)
    pct_from_high = t.get("pct_from_52wk_high", 0)

    thesis_parts = [
        f"<b>Stage {stage} uptrend</b> confirmed — price above rising 50/150/200-day SMAs in proper alignment.",
    ]
    if eps is not None:
        accel = " (accelerating)" if f.get("c_eps_acceleration") else ""
        thesis_parts.append(f"<b>EPS growth {eps:+.0f}%</b> YoY{accel} — {'well above' if eps >= 40 else 'above'} Minervini's 20% minimum.")
    if sales is not None:
        thesis_parts.append(f"<b>Revenue growth {sales:+.0f}%</b> YoY — {'strong acceleration' if f.get('sales_acceleration') else 'solid growth'}.")
    if roe is not None:
        thesis_parts.append(f"<b>ROE {roe:.0f}%</b> — {'well above' if roe >= 25 else 'above'} the 17% threshold, indicating efficient capital use.")
    thesis_parts.append(f"<b>RS Rating {rs:.0f}</b> — outperforming {rs:.0f}% of all stocks over the past 12 months.")
    if v.get("vcp_detected"):
        thesis_parts.append(
            f"<b>VCP base ({vcp_n} contractions, quality {vcp_quality:.0f}/100)</b> — "
            f"progressively tighter price action with volume drying up, "
            f"{'very tight' if vcp_quality >= 85 else 'valid'} pivot at ${pivot:.2f}."
        )
    if vol_trend == "accumulation":
        thesis_parts.append(f"<b>Accumulation confirmed</b> — up-day volume exceeds down-day volume (A/D ratio {acc_ratio:.2f}x).")
    thesis_parts.append(
        f"<b>Risk/Reward = {rr_ratio:.1f}:1</b> — "
        f"risking ${risk_per_share:.2f}/share ({risk_pct_entry}%) for a potential gain to ${target_1:.2f} (+{round((target_1-pivot)/pivot*100):.0f}%)."
    )

    # Exit triggers
    exit_triggers = [
        f"Close below ${stop_loss:.2f} (stop loss — {risk_pct_entry}% risk)",
        f"Close below 50-day SMA (${sma50:.2f}) on heavy volume" if sma50 > 0 else None,
        "Weekly reversal on climactic volume (distribution top signal)",
        f"Price reaches ${target_1:.2f} — trim 1/3 position, raise stop to breakeven",
        f"Price reaches ${target_2:.2f} — trim another 1/3, trail remaining with 50-day SMA",
    ]
    exit_triggers = [e for e in exit_triggers if e]

    return {
        "pivot": pivot,
        "buy_zone_high": buy_zone_high,
        "in_buy_zone": in_buy_zone,
        "above_pivot": above_pivot,
        "status": status,
        "stop_loss": stop_loss,
        "trailing_stop": trailing_stop,
        "risk_per_share": risk_per_share,
        "risk_pct_entry": risk_pct_entry,
        "target_1": target_1,
        "target_2": target_2,
        "rr_ratio": rr_ratio,
        "shares": shares,
        "position_value": position_value,
        "position_pct_portfolio": position_pct_portfolio,
        "max_risk_dollars": round(max_risk_dollars, 2),
        "thesis_html": " ".join(f"<p style='margin:0 0 0.4rem'>• {p}</p>" for p in thesis_parts),
        "exit_triggers": exit_triggers,
    }


def _render_stock_detail(r: dict, portfolio_size: float = 100_000, risk_pct: float = 0.01, key_suffix: str = ""):
    t = r.get("technical", {})
    f = r.get("fundamental", {})
    v = r.get("vcp", {})
    ticker = r.get("ticker", "")
    price = t.get("current_price", 0) or 0

    plan = _build_trading_plan(r, portfolio_size, risk_pct)

    tab1, tab2, tab3 = st.tabs(["📋 Trading Plan", "✅ Criteria", "📖 Thesis"])

    # ── Tab 1: Trading Plan ──────────────────────────────────────────────────
    with tab1:
        hdr_col, btn_col = st.columns([3, 1])
        with hdr_col:
            st.markdown(f"**{ticker}** &nbsp; ${price:.2f} &nbsp; RS {t.get('rs_rating',0):.0f} &nbsp; Score {r.get('score',0):.0f}/100")
        with btn_col:
            in_wl = ticker in st.session_state.watchlist
            _wl_key = f"wl_btn_{ticker}{key_suffix}"
            if in_wl:
                if st.button("✅ Watching", key=_wl_key, help="Remove from watchlist"):
                    _wl_remove(ticker)
                    st.rerun()
            else:
                if st.button("⭐ Watch", key=_wl_key, help="Add to watchlist"):
                    v_snap = r.get("vcp", {})
                    f_snap = r.get("fundamental", {})
                    snap = {
                        "rs":       t.get("rs_rating", 0),
                        "score":    r.get("score", 0),
                        "pivot":    plan["pivot"],
                        "stop":     plan["stop_loss"],
                        "status":   plan["status"],
                        "vcp_pct":  v_snap.get("vcp_pct_from_pivot"),
                        "eps":      f_snap.get("eps_growth_current_qtr_pct"),
                        "sales":    f_snap.get("sales_growth_current_qtr_pct"),
                    }
                    _wl_add(ticker, price, snapshot=snap)
                    st.rerun()

        # Status badge
        s = plan["status"]
        if "BUY ZONE" in s:
            badge = '<span class="tp-badge-buy">✓ IN BUY ZONE</span>'
        elif "WAIT" in s:
            badge = f'<span class="tp-badge-wait">⏳ {s}</span>'
        else:
            badge = f'<span style="background:#4a1942;color:#fbb6ce;border-radius:4px;padding:2px 8px;font-size:0.72rem;font-weight:700;">⚠ {s}</span>'
        st.markdown(badge, unsafe_allow_html=True)
        st.markdown("")

        # Entry / Stop / Target cards in 2-col grid
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"""
            <div class="tp-card tp-entry">
              <div class="tp-label">Entry — Buy Point</div>
              <div class="tp-value">${plan['pivot']:.2f}</div>
              <div class="tp-sub">Buy zone: ${plan['pivot']:.2f} – ${plan['buy_zone_high']:.2f}<br>
              Do NOT buy more than 5% above pivot</div>
            </div>
            <div class="tp-card tp-stop">
              <div class="tp-label">Stop Loss</div>
              <div class="tp-value">${plan['stop_loss']:.2f}</div>
              <div class="tp-sub">Risk: ${plan['risk_per_share']:.2f}/share ({plan['risk_pct_entry']}%)<br>
              Below last VCP low · Max 8% below entry</div>
            </div>
            """, unsafe_allow_html=True)
        with col_b:
            st.markdown(f"""
            <div class="tp-card tp-target">
              <div class="tp-label">Target 1 — Trim 1/3</div>
              <div class="tp-value">${plan['target_1']:.2f}</div>
              <div class="tp-sub">+{round((plan['target_1']-plan['pivot'])/plan['pivot']*100):.0f}% from entry &nbsp;·&nbsp;
              <span class="tp-badge-rr-good">R:R {plan['rr_ratio']:.1f}:1</span></div>
            </div>
            <div class="tp-card tp-target">
              <div class="tp-label">Target 2 — Trim 1/3 more</div>
              <div class="tp-value">${plan['target_2']:.2f}</div>
              <div class="tp-sub">+{round((plan['target_2']-plan['pivot'])/plan['pivot']*100):.0f}% from entry &nbsp;·&nbsp;
              Trail remainder with 50-day SMA</div>
            </div>
            """, unsafe_allow_html=True)

        # Position sizing
        st.markdown(f"""
        <div class="tp-card tp-size">
          <div class="tp-label">Position Size (1% Risk Rule)</div>
          <div class="tp-value">{plan['shares']:,} shares &nbsp; <span style="color:#a0aec0;font-size:0.9rem;">(${plan['position_value']:,.0f})</span></div>
          <div class="tp-sub">
            Max risk: ${plan['max_risk_dollars']:,.0f} &nbsp;·&nbsp;
            {plan['position_pct_portfolio']:.1f}% of ${portfolio_size:,.0f} portfolio &nbsp;·&nbsp;
            Entry @ ${plan['pivot']:.2f} × {plan['shares']:,} shares
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Trailing stop
        if plan["trailing_stop"]:
            st.markdown(f"""
            <div class="tp-card" style="border-left:4px solid #ecc94b">
              <div class="tp-label">Trailing Stop (after breakout)</div>
              <div class="tp-value">${plan['trailing_stop']:.2f}</div>
              <div class="tp-sub">1% below 50-day SMA — move up weekly as stock advances.<br>
              Exit immediately on a close below 50-day on heavy volume.</div>
            </div>
            """, unsafe_allow_html=True)

        # Exit triggers checklist
        st.markdown("**Exit Triggers**")
        for trigger in plan["exit_triggers"]:
            st.markdown(f"→ {trigger}")

    # ── Tab 2: SEPA Criteria ─────────────────────────────────────────────────
    with tab2:
        st.markdown("**Trend Template**")
        for label, key in [
            ("Price > 150 SMA", "c1_price_above_sma150"),
            ("Price > 200 SMA", "c2_price_above_sma200"),
            ("150 SMA > 200 SMA", "c3_sma150_above_sma200"),
            ("200 SMA trending up", "c4_sma200_trending_up"),
            ("50 SMA > 150 SMA", "c5_sma50_above_sma150"),
            ("50 SMA > 200 SMA", "c6_sma50_above_sma200"),
            ("Price > 50 SMA", "c7_price_above_sma50"),
            ("≥25% above 52wk low", "c8_above_52wk_low"),
            ("Within 25% of 52wk high", "c9_near_52wk_high"),
            (f"RS ≥ 70  ({t.get('rs_rating',0):.0f})", "c10_rs_rating"),
        ]:
            st.markdown(f"{'✅' if t.get(key) else '❌'} {label}")

        st.markdown("**Fundamentals**")
        for label, key in [
            (f"EPS Growth {f.get('eps_growth_current_qtr_pct','N/A')}%", "c_eps_growth"),
            ("EPS Acceleration", "c_eps_acceleration"),
            (f"Sales Growth {f.get('sales_growth_current_qtr_pct','N/A')}%", "c_sales_growth"),
            (f"ROE {f.get('roe_pct','N/A')}%", "c_roe"),
            (f"Operating Margin {f.get('pretax_margin_pct','N/A')}%", "c_margin"),
            ("Market Cap & Volume", "c_market_cap"),
        ]:
            st.markdown(f"{'✅' if f.get(key) else '❌'} {label}")

        vol_color = {"accumulation": "🟢", "distribution": "🔴", "neutral": "🟡"}
        vt = t.get("volume_trend", "neutral")
        st.markdown(f"\n{vol_color.get(vt,'⚪')} Volume: **{vt.title()}** (A/D {t.get('acc_dist_ratio',0):.2f}x)")

    # ── Tab 3: Trade Thesis ──────────────────────────────────────────────────
    with tab3:
        st.markdown(f"""<div class="thesis-box">{plan['thesis_html']}</div>""",
                    unsafe_allow_html=True)
        if v.get("vcp_detected"):
            st.caption(v.get("vcp_notes", ""))


def _render_charts(results: list[dict], all_results: list[dict]):
    st.markdown("### 📊 Analytics")
    col1, col2, col3 = st.columns(3)
    with col1:
        rs_vals = [r["technical"].get("rs_rating", 0) for r in all_results if r.get("technical")]
        passed_rs = [r["technical"].get("rs_rating", 0) for r in results if r.get("technical")]
        fig = go.Figure()
        fig.add_trace(go.Histogram(x=rs_vals, nbinsx=20, name="All", marker_color="#4a5568", opacity=0.6))
        fig.add_trace(go.Histogram(x=passed_rs, nbinsx=20, name="Passed", marker_color="#48bb78", opacity=0.9))
        fig.update_layout(title="RS Rating Distribution", barmode="overlay",
            paper_bgcolor="#1e2130", plot_bgcolor="#1e2130", font_color="#a0aec0",
            title_font_color="#e2e8f0", margin=dict(l=10, r=10, t=40, b=10), height=280,
            legend=dict(bgcolor="#1e2130"))
        fig.update_xaxes(gridcolor="#2d3748")
        fig.update_yaxes(gridcolor="#2d3748")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        stage_counts = {}
        stage_labels = {1: "Stage 1 — Base", 2: "Stage 2 — Bull", 3: "Stage 3 — Top", 4: "Stage 4 — Bear", 0: "Unknown"}
        for r in all_results:
            label = stage_labels.get(r.get("technical", {}).get("stage", 0), "Unknown")
            stage_counts[label] = stage_counts.get(label, 0) + 1
        fig2 = go.Figure(go.Pie(labels=list(stage_counts.keys()), values=list(stage_counts.values()),
            hole=0.45, marker_colors=["#ecc94b", "#48bb78", "#ed8936", "#fc8181", "#718096"]))
        fig2.update_layout(title="Stage Breakdown (Full Universe)", paper_bgcolor="#1e2130",
            font_color="#a0aec0", title_font_color="#e2e8f0",
            margin=dict(l=10, r=10, t=40, b=10), height=280, legend=dict(bgcolor="#1e2130"))
        st.plotly_chart(fig2, use_container_width=True)
    with col3:
        eps_list, sales_list, rs_list, tickers_list, scores_list = [], [], [], [], []
        for r in results:
            f = r.get("fundamental", {})
            t = r.get("technical", {})
            eps = f.get("eps_growth_current_qtr_pct")
            sales = f.get("sales_growth_current_qtr_pct")
            if eps is not None and sales is not None:
                eps_list.append(float(eps)); sales_list.append(float(sales))
                rs_list.append(float(t.get("rs_rating", 50)))
                tickers_list.append(r.get("ticker", ""))
                scores_list.append(float(r.get("score", 0)))
        if eps_list:
            fig3 = go.Figure(go.Scatter(x=sales_list, y=eps_list, mode="markers+text",
                text=tickers_list, textposition="top center",
                marker=dict(size=[s / 8 for s in scores_list], color=rs_list,
                    colorscale="Viridis", showscale=True,
                    colorbar=dict(title="RS", thickness=10), line=dict(color="#2d3748", width=1)),
                hovertemplate="<b>%{text}</b><br>Sales: %{x:.1f}%<br>EPS: %{y:.1f}%<extra></extra>"))
            fig3.add_hline(y=20, line_dash="dot", line_color="#718096", opacity=0.5)
            fig3.add_vline(x=20, line_dash="dot", line_color="#718096", opacity=0.5)
            fig3.update_layout(title="EPS vs Sales Growth (passed)", xaxis_title="Sales Growth %",
                yaxis_title="EPS Growth %", paper_bgcolor="#1e2130", plot_bgcolor="#1e2130",
                font_color="#a0aec0", title_font_color="#e2e8f0",
                margin=dict(l=10, r=10, t=40, b=10), height=280)
            fig3.update_xaxes(gridcolor="#2d3748")
            fig3.update_yaxes(gridcolor="#2d3748")
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No fundamental data available for chart.")
    if results:
        top_n = min(15, len(results))
        top = sorted(results, key=lambda r: r.get("score", 0), reverse=True)[:top_n]
        fig4 = go.Figure(go.Bar(
            x=[r.get("score", 0) for r in reversed(top)],
            y=[r.get("ticker", "") for r in reversed(top)],
            orientation="h",
            marker=dict(color=[r.get("score", 0) for r in reversed(top)],
                colorscale=[[0, "#4a5568"], [0.5, "#ecc94b"], [1, "#48bb78"]], showscale=False),
            text=[f"{r.get('score',0):.0f}" for r in reversed(top)], textposition="outside",
            hovertemplate="<b>%{y}</b>: %{x:.0f}<extra></extra>"))
        fig4.update_layout(title=f"Top {top_n} Stocks by Composite Score", xaxis_title="Score (0–100)",
            paper_bgcolor="#1e2130", plot_bgcolor="#1e2130", font_color="#a0aec0",
            title_font_color="#e2e8f0", margin=dict(l=80, r=60, t=40, b=30),
            height=max(250, top_n * 28))
        fig4.update_xaxes(gridcolor="#2d3748", range=[0, 110])
        fig4.update_yaxes(gridcolor="#2d3748")
        st.plotly_chart(fig4, use_container_width=True)


def _show_near_misses(all_results):
    """
    When no stock passes ALL criteria, show the closest candidates in the SAME
    rich, selectable table + full detail panel used for passing stocks — so the
    user can still click any stock and see its complete trading plan.
    """
    st.markdown("### 🔎 Near Misses — Closest to Passing")
    st.caption("No stock passed every criterion, so here are the strongest candidates. "
               "Click any row to see its full breakdown — or relax the filters in the sidebar.")

    # Rank by # of Trend Template criteria passed, then composite score.
    candidates = []
    for r in all_results:
        t = r.get("technical", {})
        if not t:
            continue
        try:
            passed = int(str(t.get("criteria_passed", "0/10")).split("/")[0])
        except Exception:
            passed = 0
        candidates.append((passed, float(r.get("score", 0) or 0), r))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    near = [r for _, _, r in candidates[:40]]

    if not near:
        st.info("No analyzable results to display.")
        return

    _pf = st.session_state.get("portfolio_size", 100_000)
    _rp = st.session_state.get("risk_per_trade_pct", 1.0) / 100

    df_near = _build_results_df(near, _pf, _rp)
    # Add the criteria-passed column so it's clear why these didn't fully pass.
    crit_map = {r.get("ticker"): r.get("technical", {}).get("criteria_passed", "?") for r in near}
    if not df_near.empty:
        df_near.insert(2, "Criteria", df_near["Ticker"].map(crit_map))
        # Near-miss stocks haven't had fundamentals fetched (that only runs for
        # full Trend-Template passers), so Sector/EPS%/Sales%/VCP are empty here.
        # Drop any column that has no data so the table doesn't look broken.
        for col in ["Sector", "EPS%", "Sales%", "VCP"]:
            if col in df_near.columns:
                series = df_near[col]
                is_empty = series.isna().all() or (series.astype(str).str.strip().isin(["", "—", "None"]).all())
                if is_empty:
                    df_near = df_near.drop(columns=[col])

    tbl_col, det_col = st.columns([3, 2])
    with tbl_col:
        df_tickers = df_near["Ticker"].tolist()
        ticker_to_result = {r["ticker"]: r for r in near}
        near_ordered = [ticker_to_result[tk] for tk in df_tickers if tk in ticker_to_result]

        event = st.dataframe(
            df_near,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="near_miss_table",
            column_config={
                "Status":   st.column_config.TextColumn("Status",   width=140),
                "Ticker":   st.column_config.TextColumn("Ticker",   width=70),
                "Criteria": st.column_config.TextColumn("Trend ✓",  width=70,
                              help="Trend Template criteria passed (out of 10)"),
                "Sector":   st.column_config.TextColumn("Sector",   width=130),
                "Price":    st.column_config.NumberColumn("Price",   format="$%.2f"),
                "Pivot":    st.column_config.NumberColumn("Pivot",   format="$%.2f"),
                "Risk$/sh": st.column_config.NumberColumn("Risk$/sh",format="$%.2f"),
                "Risk%":    st.column_config.NumberColumn("Risk%",   format="%.1f%%"),
                "Upside%":  st.column_config.NumberColumn("Upside%", format="+%.1f%%"),
                "Score":    st.column_config.ProgressColumn("Score", min_value=0, max_value=100, width=90),
                "RS":       st.column_config.NumberColumn("RS",      format="%d", width=55),
                "EPS%":     st.column_config.NumberColumn("EPS%",    format="%.1f%%"),
                "Sales%":   st.column_config.NumberColumn("Sales%",  format="%.1f%%"),
                "Stage":    st.column_config.TextColumn("Stage",     width=75),
                "VCP":      st.column_config.TextColumn("VCP",       width=65),
            },
            height=500,
        )
        sel_rows = event.selection.rows if event.selection else []
        if sel_rows and sel_rows[0] < len(near_ordered):
            st.session_state.selected_ticker = near_ordered[sel_rows[0]]["ticker"]

    with det_col:
        sel = st.session_state.selected_ticker
        r_sel = next((x for x in near if x["ticker"] == sel), None)
        if r_sel:
            _render_stock_detail(r_sel, _pf, _rp, key_suffix="_nearmiss")
        else:
            st.info("👆 Click a row to see the full breakdown for that stock.")


def _make_journey_html(plan: dict, added_price, current_price: float) -> str:
    """Render an HTML price-journey bar: STOP → [added] → NOW → PIVOT → T1."""
    stop  = plan["stop_loss"]
    pivot = plan["pivot"]
    t1    = plan["target_1"]
    span  = t1 - stop
    if span <= 0 or current_price <= 0:
        return ""

    def _p(price):
        return max(2.0, min(97.0, (price - stop) / span * 100))

    curr_p  = _p(current_price)
    pivot_p = _p(pivot)

    # Color: green past pivot, amber above added, red below
    if current_price >= pivot:
        curr_col = "#48bb78"
    elif added_price and current_price > added_price:
        curr_col = "#ecc94b"
    else:
        curr_col = "#fc8181"

    # Added marker + label
    added_marker = added_label = ""
    if added_price and added_price > 0:
        ap = _p(added_price)
        added_marker = (
            f'<div style="position:absolute;left:{ap:.1f}%;top:50%;'
            f'transform:translate(-50%,-50%);width:9px;height:9px;'
            f'background:#ecc94b;border-radius:50%;border:2px solid #0e111d;'
            f'opacity:0.9;" title="Added: ${added_price:.2f}"></div>'
        )
        added_label = (
            f'<span style="position:absolute;left:{ap:.1f}%;'
            f'transform:translateX(-50%);text-align:center;color:#ecc94b;">'
            f'ADDED<br>${added_price:.0f}</span>'
        )

    return f"""
<div style="margin:1.1rem 0 2rem;">
  <div style="height:8px;background:#1a1f35;border-radius:4px;position:relative;overflow:visible;">
    <div style="position:absolute;left:0;width:{curr_p:.1f}%;height:100%;
      background:linear-gradient(90deg,#742a2a80,{curr_col}90);border-radius:4px;"></div>
    <div style="position:absolute;left:{pivot_p:.1f}%;top:-4px;bottom:-4px;
      width:2px;background:#63b3ed;border-radius:1px;opacity:0.9;" title="Pivot ${pivot:.2f}"></div>
    {added_marker}
    <div style="position:absolute;left:{curr_p:.1f}%;top:50%;
      transform:translate(-50%,-50%);width:13px;height:13px;
      background:{curr_col};border-radius:50%;border:2px solid #0e111d;
      box-shadow:0 0 9px {curr_col}cc;"></div>
  </div>
  <div style="position:relative;margin-top:10px;height:34px;font-size:0.63rem;
              color:#4a5568;line-height:1.35;white-space:nowrap;">
    <span style="position:absolute;left:0;transform:translateX(-50%);
      text-align:center;color:#fc8181;">STOP<br>${stop:.0f}</span>
    {added_label}
    <span style="position:absolute;left:{pivot_p:.1f}%;transform:translateX(-50%);
      text-align:center;color:#63b3ed;">PIVOT<br>${pivot:.0f}</span>
    <span style="position:absolute;left:{curr_p:.1f}%;transform:translateX(-50%);
      text-align:center;color:{curr_col};font-weight:700;">NOW<br>${current_price:.0f}</span>
    <span style="position:absolute;right:0;transform:translateX(50%);
      text-align:center;color:#68d391;">T1<br>${t1:.0f}</span>
  </div>
</div>"""


def _make_progress_html(snap: dict, rs: float, score: float, v: dict, raw_status: str) -> str:
    """Build a 'then vs now' comparison table from the add-time snapshot."""
    if not snap:
        return ""

    rows = []

    def _row(label, before, after, delta_val, higher_is_better=True):
        good = delta_val > 0 if higher_is_better else delta_val < 0
        bad  = delta_val < 0 if higher_is_better else delta_val > 0
        col  = "#48bb78" if good else ("#fc8181" if bad else "#a0aec0")
        arrow = "↑" if delta_val > 0 else ("↓" if delta_val < 0 else "→")
        change_html = f'<span style="color:{col}">{arrow} {abs(delta_val):.1f}</span>'
        rows.append((label, before, after, change_html))

    added_rs = snap.get("rs")
    if added_rs is not None:
        _row("RS Rating", f"{added_rs:.0f}", f"{rs:.0f}", rs - added_rs)

    added_score = snap.get("score")
    if added_score is not None:
        _row("Score", f"{added_score:.0f}/100", f"{score:.0f}/100", score - added_score)

    added_vcp_pct = snap.get("vcp_pct")
    curr_vcp_pct  = v.get("vcp_pct_from_pivot")
    if added_vcp_pct is not None and curr_vcp_pct is not None:
        delta = curr_vcp_pct - added_vcp_pct
        suffix = " (tightening ✓)" if delta < 0 else " (widening)"
        good = delta < 0
        col  = "#48bb78" if good else "#fc8181"
        arrow = "↓" if delta < 0 else "↑"
        rows.append((
            "% from Pivot",
            f"{added_vcp_pct:.1f}%",
            f"{curr_vcp_pct:.1f}%",
            f'<span style="color:{col}">{arrow} {abs(delta):.1f}%{suffix}</span>',
        ))

    # Status change
    added_status = snap.get("status", "")
    if added_status and added_status != raw_status:
        improved = "BUY ZONE" in raw_status and "BUY ZONE" not in added_status
        degraded = ("FAILED" in raw_status or "EXTENDED" in raw_status) and "BUY ZONE" in added_status
        col = "#48bb78" if improved else ("#fc8181" if degraded else "#a0aec0")
        verdict = "↑ Improved!" if improved else ("↓ Degraded" if degraded else "→ Changed")
        rows.append((
            "Status",
            added_status[:18],
            raw_status[:18],
            f'<span style="color:{col};font-weight:700;">{verdict}</span>',
        ))

    if not rows:
        return ""

    table_rows = "".join(
        f'<tr>'
        f'<td style="color:#4a5568;font-size:0.72rem;padding:3px 10px 3px 0;white-space:nowrap;">{lbl}</td>'
        f'<td style="color:#718096;font-size:0.72rem;padding:3px 8px;font-family:monospace;opacity:0.7;">{bef}</td>'
        f'<td style="color:#4a5568;font-size:0.72rem;padding:3px 4px;">→</td>'
        f'<td style="color:#e2e8f0;font-size:0.72rem;padding:3px 8px;font-family:monospace;">{aft}</td>'
        f'<td style="font-size:0.73rem;padding:3px 0;">{chg}</td>'
        f'</tr>'
        for lbl, bef, aft, chg in rows
    )
    return f"""
<div style="background:#0a0d18;border:1px solid #1e2535;border-radius:8px;
            padding:0.7rem 1rem;margin:0.8rem 0 0.4rem;">
  <div style="font-size:0.62rem;color:#4a5568;text-transform:uppercase;
              letter-spacing:1.5px;margin-bottom:0.5rem;">📊 Progress since added</div>
  <table style="border-collapse:collapse;width:100%;">{table_rows}</table>
</div>"""


def _render_watchlist_card(ticker: str, meta: dict, r,
                           portfolio_size: float, risk_pct: float):
    """Render one watchlist stock card."""
    added_date = meta.get("added_date", "")
    added_price = meta.get("added_price")
    notes = meta.get("notes", "")

    if r:
        t = r.get("technical", {})
        f = r.get("fundamental", {})
        v = r.get("vcp", {})
        price = t.get("current_price", 0) or 0
        rs = t.get("rs_rating", 0) or 0
        score = r.get("score", 0) or 0
        passes_tt = t.get("passes_trend_template", False)
        stage = t.get("stage", 0)
        plan = _build_trading_plan(r, portfolio_size, risk_pct)
        raw_status = plan["status"]

        # Price change since added
        price_delta_html = ""
        if added_price and price:
            chg = (price - added_price) / added_price * 100
            color = "#48bb78" if chg >= 0 else "#fc8181"
            sign = "+" if chg >= 0 else ""
            price_delta_html = f'<span style="color:{color};font-size:0.82rem;"> ({sign}{chg:.1f}% since added)</span>'

        # Health indicator
        if not passes_tt:
            health_color, health_icon, health_label = "#fc8181", "🔴", "Trend Template FAILED — setup broken"
        elif "BUY ZONE" in raw_status:
            health_color, health_icon, health_label = "#48bb78", "🟢", "In buy zone — actionable now"
        elif v.get("vcp_detected"):
            pct = v.get("vcp_pct_from_pivot", 0) or 0
            if pct < 3:
                health_color, health_icon, health_label = "#68d391", "🟢", f"Very close to pivot ({pct:.1f}% away)"
            elif pct < 8:
                health_color, health_icon, health_label = "#ecc94b", "🟡", f"Approaching pivot ({pct:.1f}% away)"
            else:
                health_color, health_icon, health_label = "#a0aec0", "⚪", f"Basing — {pct:.1f}% from pivot"
        else:
            health_color, health_icon, health_label = "#a0aec0", "⚪", "Stage 2 uptrend — no VCP yet"

        # Status badge
        if "BUY ZONE" in raw_status:
            status_badge = '<span style="background:#276749;color:#9ae6b4;border-radius:4px;padding:2px 7px;font-size:0.72rem;font-weight:700;">✅ BUY ZONE</span>'
        elif "WAIT" in raw_status:
            away = raw_status.split("—")[1].strip() if "—" in raw_status else raw_status
            status_badge = f'<span style="background:#744210;color:#fbd38d;border-radius:4px;padding:2px 7px;font-size:0.72rem;font-weight:700;">⏳ WAIT {away}</span>'
        elif "EXTENDED" in raw_status:
            ext = raw_status.split("—")[1].strip() if "—" in raw_status else raw_status
            status_badge = f'<span style="background:#4a1942;color:#fbb6ce;border-radius:4px;padding:2px 7px;font-size:0.72rem;font-weight:700;">⚠ EXT {ext}</span>'
        else:
            status_badge = f'<span style="background:#742a2a;color:#feb2b2;border-radius:4px;padding:2px 7px;font-size:0.72rem;font-weight:700;">❌ FAILED</span>'

        tt_badge = (
            '<span style="background:#276749;color:#9ae6b4;border-radius:4px;padding:2px 7px;font-size:0.72rem;font-weight:600;">TT ✓</span>'
            if passes_tt else
            '<span style="background:#742a2a;color:#feb2b2;border-radius:4px;padding:2px 7px;font-size:0.72rem;font-weight:600;">TT ✗</span>'
        )
        vcp_badge = (
            f'<span style="background:#2d3f7a;color:#90cdf4;border-radius:4px;padding:2px 7px;font-size:0.72rem;font-weight:600;">VCP ✓ {v.get("vcp_contractions",0)}T</span>'
            if v.get("vcp_detected") else ""
        )
        eps = f.get("eps_growth_current_qtr_pct")
        sales = f.get("sales_growth_current_qtr_pct")

        price_chg = f"  ({((price-added_price)/added_price*100):+.1f}%)" if added_price and price else ""
        auto_expand = "BUY ZONE" in raw_status or (v.get("vcp_detected") and (v.get("vcp_pct_from_pivot") or 99) < 5)
        with st.expander(
            f"{health_icon}  **{ticker}** &nbsp; ${price:.2f}{price_chg}  ·  RS {rs:.0f}  ·  Score {score:.0f}  ·  {raw_status}",
            expanded=auto_expand,
        ):
            # Top row: metrics + remove button
            m1, m2, m3, m4, m5, rem_col = st.columns([2, 2, 2, 2, 2, 1])
            with m1:
                st.metric("Price", f"${price:.2f}",
                          delta=f"{((price-added_price)/added_price*100):+.1f}% vs entry" if added_price else None)
            with m2:
                st.metric("RS Rating", f"{rs:.0f}")
            with m3:
                st.metric("Score", f"{score:.0f}/100")
            with m4:
                ep = f"{eps:+.0f}%" if eps is not None else "N/A"
                st.metric("EPS Growth", ep)
            with m5:
                sp = f"{sales:+.0f}%" if sales is not None else "N/A"
                st.metric("Sales Growth", sp)
            with rem_col:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑 Remove", key=f"wl_rem_{ticker}"):
                    _wl_remove(ticker)
                    st.rerun()

            # Status bar
            st.markdown(
                f'{status_badge} &nbsp; {tt_badge} &nbsp; {vcp_badge} &nbsp; '
                f'<span style="color:{health_color};font-size:0.82rem;">{health_label}</span>',
                unsafe_allow_html=True,
            )

            # ── Price journey bar ─────────────────────────────────────────────
            st.markdown(
                _make_journey_html(plan, added_price, price),
                unsafe_allow_html=True,
            )

            # ── Progress since added ──────────────────────────────────────────
            snap = meta.get("snapshot", {})
            days_held = (datetime.now() - datetime.strptime(added_date, "%Y-%m-%d")).days if added_date else 0
            snap_html = _make_progress_html(snap, rs, score, v, raw_status)
            if snap_html:
                st.markdown(snap_html, unsafe_allow_html=True)
            else:
                st.caption(f"⏱ {days_held}d on watchlist · Added {added_date}" +
                           (f" at ${added_price:.2f}" if added_price else ""))

            st.markdown("")

            # ── Trading plan quick view ───────────────────────────────────────
            pc1, pc2, pc3, pc4 = st.columns(4)
            with pc1:
                st.markdown(f"""<div class="tp-card tp-entry">
                  <div class="tp-label">Pivot / Buy Zone</div>
                  <div class="tp-value">${plan['pivot']:.2f}</div>
                  <div class="tp-sub">Up to ${plan['buy_zone_high']:.2f}</div>
                </div>""", unsafe_allow_html=True)
            with pc2:
                st.markdown(f"""<div class="tp-card tp-stop">
                  <div class="tp-label">Stop Loss</div>
                  <div class="tp-value">${plan['stop_loss']:.2f}</div>
                  <div class="tp-sub">Risk {plan['risk_pct_entry']}% · ${plan['risk_per_share']:.2f}/sh</div>
                </div>""", unsafe_allow_html=True)
            with pc3:
                st.markdown(f"""<div class="tp-card tp-target">
                  <div class="tp-label">Target 1</div>
                  <div class="tp-value">${plan['target_1']:.2f}</div>
                  <div class="tp-sub">+{round((plan['target_1']-plan['pivot'])/plan['pivot']*100):.0f}% · R:R {plan['rr_ratio']:.1f}:1</div>
                </div>""", unsafe_allow_html=True)
            with pc4:
                st.markdown(f"""<div class="tp-card tp-target">
                  <div class="tp-label">Target 2</div>
                  <div class="tp-value">${plan['target_2']:.2f}</div>
                  <div class="tp-sub">+{round((plan['target_2']-plan['pivot'])/plan['pivot']*100):.0f}% from pivot</div>
                </div>""", unsafe_allow_html=True)

            # ── Notes + footer ────────────────────────────────────────────────
            new_notes = st.text_input(
                "Notes", value=notes, placeholder="e.g. Waiting for volume dry-up on week 3...",
                key=f"wl_notes_{ticker}", label_visibility="collapsed",
            )
            if new_notes != notes:
                wl = st.session_state.watchlist
                wl[ticker]["notes"] = new_notes
                st.session_state.watchlist = wl
                _save_watchlist(wl)

            st.caption(
                f"⏱ {days_held}d on watchlist · Added {added_date}"
                + (f" at ${added_price:.2f}" if added_price else "")
            )

    else:
        # No data yet
        with st.expander(f"⚪  **{ticker}**  · Added {added_date} · No data yet — click Refresh", expanded=False):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.info("Click **🔄 Refresh Analysis** to fetch current data for this stock.")
            with c2:
                if st.button("🗑 Remove", key=f"wl_rem_{ticker}"):
                    _wl_remove(ticker)
                    st.rerun()


def _render_watchlist_tab():
    wl = st.session_state.watchlist
    wl_data = st.session_state.get("watchlist_data", {})
    _pf = st.session_state.get("portfolio_size", 100_000)
    _rp = st.session_state.get("risk_per_trade_pct", 1.0) / 100

    # ── Header ───────────────────────────────────────────────────────────────
    hcol, addcol, refcol = st.columns([3, 2, 1])
    with hcol:
        st.markdown(f"### ⭐ Watchlist ({len(wl)} stocks)")
    with addcol:
        new_tk = st.text_input("Add ticker manually", placeholder="e.g. NVDA",
                               key="wl_manual_input", label_visibility="collapsed")
        if st.button("➕ Add ticker", key="wl_manual_add") and new_tk.strip():
            _wl_add(new_tk.strip().upper())
            st.rerun()
    with refcol:
        refresh = st.button("🔄 Refresh Analysis", key="wl_refresh_btn", use_container_width=True,
                            disabled=len(wl) == 0)

    if refresh and wl:
        tickers = list(wl.keys())
        # Run with very lenient config so all stocks get full analysis
        lenient = {
            "TREND_TEMPLATE": {**cfg.TREND_TEMPLATE, "rs_rating_min": 0,
                               "pct_from_52wk_high": 1.0, "pct_above_52wk_low": 0.0},
            "FUNDAMENTALS": {**cfg.FUNDAMENTALS,
                             "eps_growth_current_qtr_min": -99,
                             "sales_growth_min": -99,
                             "roe_min": -99},
            "RS_CALCULATION": cfg.RS_CALCULATION,
            "VCP": cfg.VCP,
            "VOLUME": cfg.VOLUME,
            "RISK": {**cfg.RISK, "min_price": 0, "min_avg_volume": 0},
            "UNIVERSE": cfg.UNIVERSE,
            "OUTPUT": cfg.OUTPUT,
            "SCORING": cfg.SCORING,
        }
        screener = MinerviniScreener(lenient)
        with st.spinner(f"Fetching data for {len(tickers)} watchlist stocks..."):
            _, all_res = screener.run(tickers, verbose=False)
        # Update added_price for newly added stocks (no price yet)
        wl_updated = st.session_state.watchlist
        for res in all_res:
            tk = res.get("ticker")
            if tk and tk in wl_updated:
                if not wl_updated[tk].get("added_price"):
                    price = res.get("technical", {}).get("current_price")
                    if price:
                        wl_updated[tk]["added_price"] = round(price, 2)
        st.session_state.watchlist = wl_updated
        _save_watchlist(wl_updated)
        # Merge sector/industry into watchlist results (lenient run may skip fundamentals)
        for res in all_res:
            if not res.get("sector"):
                res["sector"] = ""
        st.session_state.watchlist_data = {r["ticker"]: r for r in all_res if r.get("ticker")}
        st.rerun()

    if not wl:
        st.info("Your watchlist is empty.\n\n"
                "- **Add manually** using the input above\n"
                "- **Add from screener** — run the screener, click a row, and press **⭐ Watch** in the trading plan panel")
        return

    # ── Sort watchlist: BUY ZONE first, then WAIT, then EXTENDED, then no data ──
    def _wl_sort_key(ticker):
        r = wl_data.get(ticker)
        if not r:
            return (9, 0)
        t = r.get("technical", {})
        if not t.get("passes_trend_template"):
            return (3, 0)
        plan = _build_trading_plan(r, _pf, _rp)
        s = plan["status"]
        if "BUY ZONE" in s:
            return (0, 0)
        elif "WAIT" in s:
            pct = v.get("vcp_pct_from_pivot", 99) if (v := r.get("vcp", {})) else 99
            return (1, pct)
        return (2, 0)

    sorted_tickers = sorted(wl.keys(), key=_wl_sort_key)

    # ── Summary row ──────────────────────────────────────────────────────────
    if wl_data:
        buy_zone = sum(1 for tk in wl if wl_data.get(tk) and
                       "BUY ZONE" in _build_trading_plan(wl_data[tk], _pf, _rp)["status"])
        failed_tt = sum(1 for tk in wl if wl_data.get(tk) and
                        not wl_data[tk].get("technical", {}).get("passes_trend_template"))
        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.metric("Watching", len(wl))
        sm2.metric("In Buy Zone", buy_zone)
        sm3.metric("Setup Failed", failed_tt)
        sm4.metric("No Data", len(wl) - len(wl_data))
        st.markdown("---")

    # ── Cards ────────────────────────────────────────────────────────────────
    for ticker in sorted_tickers:
        meta = wl[ticker]
        r = wl_data.get(ticker)
        _render_watchlist_card(ticker, meta, r, _pf, _rp)


# ─────────────────────────────────────────────────────────────────────────────
# History tab
# ─────────────────────────────────────────────────────────────────────────────

def _hist_results_table(results: list, key_suffix: str = ""):
    """Render a compact results dataframe for history / compare views."""
    _pf = st.session_state.get("portfolio_size", 100_000)
    _rp = st.session_state.get("risk_per_trade_pct", 1.0) / 100
    if not results:
        st.info("No results in this group.")
        return
    df = _build_results_df(results, _pf, _rp)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ticker":   st.column_config.TextColumn("Ticker",   width=70),
            "Sector":   st.column_config.TextColumn("Sector",   width=130),
            "Price":    st.column_config.NumberColumn("Price",   format="$%.2f", width=80),
            "RS":       st.column_config.NumberColumn("RS",      width=55),
            "Score":    st.column_config.ProgressColumn("Score", min_value=0, max_value=100, width=90),
            "Status":   st.column_config.TextColumn("Status",   width=130),
            "Risk$/sh": st.column_config.NumberColumn("Risk$/sh",format="$%.2f", width=80),
            "Risk%":    st.column_config.NumberColumn("Risk%",   format="%.1f%%", width=65),
            "Upside%":  st.column_config.NumberColumn("Upside%", format="%.0f%%", width=75),
        },
        key=f"hist_df_{key_suffix}",
    )


def _hist_delta_table(results: list, key_suffix: str = ""):
    """Show improved/degraded results with delta columns."""
    if not results:
        st.info("None.")
        return
    rows = []
    for r in results:
        t = r.get("technical", {})
        d = r.get("_delta", {})
        rows.append({
            "Ticker":     r.get("ticker", ""),
            "Price":      t.get("current_price", 0) or 0,
            "RS Now":     t.get("rs_rating", 0) or 0,
            "RS Before":  d.get("rs_a", 0),
            "ΔRS":        d.get("rs", 0),
            "Score Now":  r.get("score", 0) or 0,
            "Score Before": d.get("score_a", 0),
            "ΔScore":     d.get("score", 0),
        })
    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ticker":       st.column_config.TextColumn(width=70),
            "Price":        st.column_config.NumberColumn(format="$%.2f", width=80),
            "RS Now":       st.column_config.NumberColumn(width=70),
            "RS Before":    st.column_config.NumberColumn(width=80),
            "ΔRS":          st.column_config.NumberColumn(width=55),
            "Score Now":    st.column_config.ProgressColumn(min_value=0, max_value=100, width=90),
            "Score Before": st.column_config.NumberColumn(width=90),
            "ΔScore":       st.column_config.NumberColumn(width=65),
        },
        key=f"hist_delta_{key_suffix}",
    )


def _render_history_tab():
    scans = _hist_list()

    st.markdown("### 📅 Scan History")

    if not scans:
        st.info(
            "No scan history yet.\n\n"
            "Run your first scan — it will be saved automatically and appear here."
        )
        return

    # ── Mode picker ───────────────────────────────────────────────────────────
    mode = st.radio(
        "Mode", ["Browse a scan", "Compare two scans"],
        horizontal=True, key="hist_mode", label_visibility="collapsed",
    )

    labels = [m["label"] for _, m in scans]

    # ─────────────────────────────────────────────────────────────────────────
    if mode == "Browse a scan":
        sel = st.selectbox("Select scan", range(len(labels)),
                           format_func=lambda i: labels[i], key="hist_browse_sel")
        fpath, meta = scans[sel]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Date", meta["date"])
        c2.metric("Time", meta["timestamp"][11:16] if len(meta["timestamp"]) > 10 else "")
        c3.metric("Universe", meta["universe"].upper())
        c4.metric("Passed", meta["n_passed"],
                  delta=f"of {meta['n_screened']} screened" if meta["n_screened"] else None)

        st.markdown("---")
        data    = _hist_load(fpath)
        results = data.get("results", [])
        if not results:
            st.warning("No stocks passed this scan.")
            return

        _hist_results_table(results, key_suffix="browse")

        # Add-to-watchlist buttons
        _pf = st.session_state.get("portfolio_size", 100_000)
        _rp = st.session_state.get("risk_per_trade_pct", 1.0) / 100
        st.markdown("---")
        st.markdown("**Add a stock from this scan to your watchlist:**")
        ticker_options = [r.get("ticker", "") for r in results]
        wl_col1, wl_col2 = st.columns([3, 1])
        with wl_col1:
            chosen = st.selectbox("Ticker", ticker_options, key="hist_add_sel")
        with wl_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("⭐ Add to Watchlist", key="hist_add_btn"):
                r_chosen = next((r for r in results if r.get("ticker") == chosen), None)
                if r_chosen:
                    price = r_chosen.get("technical", {}).get("current_price")
                    plan  = _build_trading_plan(r_chosen, _pf, _rp)
                    snap  = {
                        "rs":      r_chosen.get("technical", {}).get("rs_rating", 0),
                        "score":   r_chosen.get("score", 0),
                        "pivot":   plan["pivot"],
                        "stop":    plan["stop_loss"],
                        "status":  plan["status"],
                        "vcp_pct": r_chosen.get("vcp", {}).get("vcp_pct_from_pivot"),
                    }
                    _wl_add(chosen, price, snapshot=snap)
                    st.success(f"{chosen} added to watchlist!")
                    st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    else:  # Compare two scans
        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown(
                '<div style="background:#1a2644;border:1px solid #2d4a8a;border-radius:8px;'
                'padding:0.5rem 1rem;margin-bottom:0.5rem;font-size:0.8rem;color:#90cdf4;">'
                '📌 Baseline (older scan)</div>', unsafe_allow_html=True)
            sel_a = st.selectbox(
                "Baseline scan", range(len(labels)),
                index=min(1, len(scans) - 1),
                format_func=lambda i: labels[i], key="hist_cmp_a",
                label_visibility="collapsed",
            )
        with cc2:
            st.markdown(
                '<div style="background:#1a3a2a;border:1px solid #2d7a4a;border-radius:8px;'
                'padding:0.5rem 1rem;margin-bottom:0.5rem;font-size:0.8rem;color:#9ae6b4;">'
                '✨ Comparison (newer scan)</div>', unsafe_allow_html=True)
            sel_b = st.selectbox(
                "Newer scan", range(len(labels)),
                index=0,
                format_func=lambda i: labels[i], key="hist_cmp_b",
                label_visibility="collapsed",
            )

        if sel_a == sel_b:
            st.warning("Select two **different** scans to compare.")
            return

        # Guarantee A is older, B is newer (lower index = newer in sorted list)
        older_idx = max(sel_a, sel_b)
        newer_idx = min(sel_a, sel_b)
        path_a, meta_a = scans[older_idx]
        path_b, meta_b = scans[newer_idx]
        scan_a = _hist_load(path_a)
        scan_b = _hist_load(path_b)
        diff   = _hist_compare(scan_a, scan_b)

        # ── Summary cards ──────────────────────────────────────────────────
        st.markdown("---")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("📌 Baseline", f"{meta_a['n_passed']} stocks", meta_a["date"])
        m2.metric("✨ Current",  f"{meta_b['n_passed']} stocks", meta_b["date"])
        m3.metric("🆕 New",      len(diff["new"]),
                  delta=f"+{len(diff['new'])}" if diff["new"] else None)
        m4.metric("❌ Dropped",  len(diff["dropped"]),
                  delta=f"-{len(diff['dropped'])}" if diff["dropped"] else None,
                  delta_color="inverse")
        m5.metric("📈 Improved / 📉 Degraded",
                  f"{len(diff['improved'])} / {len(diff['degraded'])}")

        st.markdown("---")

        # ── New stocks ─────────────────────────────────────────────────────
        with st.expander(
            f"🆕 New Setups — appeared in {meta_b['date']} scan, not in {meta_a['date']}  ({len(diff['new'])})",
            expanded=bool(diff["new"]),
        ):
            if diff["new"]:
                st.caption("These stocks passed the screener for the first time in the newer scan.")
                _hist_results_table(diff["new"], key_suffix="new")
            else:
                st.info("No new stocks — same set as baseline.")

        # ── Dropped stocks ─────────────────────────────────────────────────
        with st.expander(
            f"❌ Dropped Out — were in {meta_a['date']}, gone from {meta_b['date']}  ({len(diff['dropped'])})",
            expanded=bool(diff["dropped"]),
        ):
            if diff["dropped"]:
                st.caption("These setups broke between the two scans — trend template or criteria no longer met.")
                _hist_results_table(diff["dropped"], key_suffix="dropped")
            else:
                st.info("No stocks dropped — all baseline stocks still passing.")

        # ── Improved ───────────────────────────────────────────────────────
        with st.expander(
            f"📈 Improved — RS or Score rising  ({len(diff['improved'])})",
            expanded=False,
        ):
            if diff["improved"]:
                st.caption("RS increased >2pts or Score increased >3pts — setup getting stronger.")
                _hist_delta_table(diff["improved"], key_suffix="imp")
            else:
                st.info("No significant improvements.")

        # ── Degraded ───────────────────────────────────────────────────────
        with st.expander(
            f"📉 Degraded — RS or Score declining  ({len(diff['degraded'])})",
            expanded=False,
        ):
            if diff["degraded"]:
                st.caption("RS fell >2pts or Score fell >3pts — watch these carefully.")
                _hist_delta_table(diff["degraded"], key_suffix="deg")
            else:
                st.info("No significant degradation.")

        # ── Unchanged ──────────────────────────────────────────────────────
        with st.expander(
            f"↔ Unchanged — holding steady  ({len(diff['unchanged'])})",
            expanded=False,
        ):
            _hist_results_table(diff["unchanged"], key_suffix="unch")


# ─────────────────────────────────────────────────────────────────────────────
# Results display
# ─────────────────────────────────────────────────────────────────────────────

_wl_badge = f" ({len(st.session_state.watchlist)})" if st.session_state.watchlist else ""
_hist_badge = f" ({len(_hist_list())})" if _hist_list() else ""
_canslim_badge = (f" ({len(st.session_state.canslim_results)})"
                   if st.session_state.canslim_results else "")
tab_screener, tab_canslim, tab_analyze, tab_watchlist, tab_history = st.tabs([
    "🔍 Minervini (SEPA)",
    f"🎯 CAN SLIM (O'Neil){_canslim_badge}",
    "🔎 Analyze Ticker",
    f"⭐ Watchlist{_wl_badge}",
    f"📅 History{_hist_badge}",
])

# ── Screener tab ──────────────────────────────────────────────────────────────
with tab_screener:
    if st.session_state.results is not None:
        results = st.session_state.results
        all_results = st.session_state.all_results
        meta = st.session_state.last_run

        # Summary metrics
        tech_pass = sum(1 for r in all_results if r.get("technical", {}).get("passes_trend_template"))
        vcp_count = sum(1 for r in results if r.get("vcp", {}).get("vcp_detected"))
        near_pivot_count = sum(1 for r in results if r.get("vcp", {}).get("vcp_near_pivot"))

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            st.metric("Screened", meta["total"], help="Total stocks analyzed")
        with c2:
            st.metric("Trend Template ✓", tech_pass)
        with c3:
            st.metric("All Criteria ✓", len(results))
        with c4:
            st.metric("VCP Patterns", vcp_count)
        with c5:
            st.metric("Near Pivot", near_pivot_count, help="Within 5% of pivot entry")
        with c6:
            st.metric("Runtime", f"{meta['elapsed']:.1f}s")

        if not results:
            st.info("ℹ️ No stock passed **all** criteria — but strong candidates are listed below. "
                    "Loosen the sidebar filters (e.g. lower Min RS or EPS growth) to surface full passes.")
            _show_near_misses(all_results)
        else:
            # Near Pivot alert strip
            near_pivot = [r for r in results if r.get("vcp", {}).get("vcp_near_pivot")]
            if near_pivot:
                st.markdown("### ⭐ Near Pivot — Ready to Break Out")
                cols = st.columns(min(len(near_pivot), 4))
                for i, r in enumerate(near_pivot[:4]):
                    t = r["technical"]
                    v = r["vcp"]
                    f = r["fundamental"]
                    with cols[i]:
                        st.markdown(f"""
                        <div class="pivot-alert">
                          <div class="ticker">{r['ticker']}</div>
                          <div class="detail">
                            RS {t['rs_rating']:.0f} &nbsp;|&nbsp; Score {r['score']:.0f}<br>
                            Pivot ${v['vcp_pivot_price']:.2f} &nbsp;|&nbsp; Stop ${v['vcp_stop_price']:.2f}<br>
                            {v['vcp_pct_from_pivot']:.1f}% from pivot<br>
                            EPS {f.get('eps_growth_current_qtr_pct','N/A')}%
                            &nbsp;|&nbsp; Sales {f.get('sales_growth_current_qtr_pct','N/A')}%
                          </div>
                        </div>
                        """, unsafe_allow_html=True)
                st.markdown("")

            # Main Results Table
            st.markdown("### 📋 Screener Results")
            _pf_tbl = st.session_state.get("portfolio_size", 100_000)
            _rp_tbl = st.session_state.get("risk_per_trade_pct", 1.0) / 100
            df_display = _build_results_df(results, _pf_tbl, _rp_tbl)

            ticker_col, detail_col = st.columns([3, 2])
            with ticker_col:
                df_tickers = df_display["Ticker"].tolist()
                ticker_to_result = {r["ticker"]: r for r in results}
                results_ordered = [ticker_to_result[tk] for tk in df_tickers if tk in ticker_to_result]

                event = st.dataframe(
                    df_display,
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    column_config={
                        "Status":   st.column_config.TextColumn("Status",   width=150),
                        "Ticker":   st.column_config.TextColumn("Ticker",   width=75),
                        "Sector":   st.column_config.TextColumn("Sector",   width=140),
                        "Price":    st.column_config.NumberColumn("Price",   format="$%.2f"),
                        "Pivot":    st.column_config.NumberColumn("Pivot",   format="$%.2f"),
                        "Risk$/sh": st.column_config.NumberColumn("Risk$/sh",format="$%.2f"),
                        "Risk%":    st.column_config.NumberColumn("Risk%",   format="%.1f%%"),
                        "Upside%":  st.column_config.NumberColumn("Upside%", format="+%.1f%%"),
                        "Score":    st.column_config.ProgressColumn("Score", min_value=0, max_value=100, width=90),
                        "RS":       st.column_config.NumberColumn("RS",      format="%d", width=55),
                        "EPS%":     st.column_config.NumberColumn("EPS%",    format="%.1f%%"),
                        "Sales%":   st.column_config.NumberColumn("Sales%",  format="%.1f%%"),
                        "Stage":    st.column_config.TextColumn("Stage",     width=75),
                        "VCP":      st.column_config.TextColumn("VCP",       width=65),
                    },
                    height=500,
                )
                selected_rows = event.selection.rows if event.selection else []
                if selected_rows:
                    idx = selected_rows[0]
                    if idx < len(results_ordered):
                        st.session_state.selected_ticker = results_ordered[idx]["ticker"]

            with detail_col:
                sel = st.session_state.selected_ticker
                _pf = st.session_state.get("portfolio_size", 100_000)
                _rp = st.session_state.get("risk_per_trade_pct", 1.0) / 100
                if sel:
                    r_sel = next((x for x in results if x["ticker"] == sel), None)
                    if r_sel:
                        _render_stock_detail(r_sel, _pf, _rp, key_suffix="_detail")
                else:
                    st.info("👆 Click a row to see the full trading plan for that stock.")

            # Charts
            st.markdown("---")
            _render_charts(results, all_results)

            # All Trading Plans
            st.markdown("---")
            st.markdown("### 📝 All Trading Plans")
            _pf2 = st.session_state.get("portfolio_size", 100_000)
            _rp2 = st.session_state.get("risk_per_trade_pct", 1.0) / 100
            for r_plan in results:
                plan = _build_trading_plan(r_plan, _pf2, _rp2)
                t_p = r_plan.get("technical", {})
                ticker_p = r_plan.get("ticker", "")
                status = plan["status"]
                status_icon = "✅" if "BUY ZONE" in status else ("⏳" if "WAIT" in status else "⚠️")
                with st.expander(
                    f"{status_icon}  **{ticker_p}** &nbsp; ${t_p.get('current_price',0):.2f} "
                    f"&nbsp; RS {t_p.get('rs_rating',0):.0f} &nbsp; Score {r_plan.get('score',0):.0f} "
                    f"&nbsp;·&nbsp; {status}",
                    expanded=False,
                ):
                    _render_stock_detail(r_plan, _pf2, _rp2, key_suffix="_exp")

            # Export
            st.markdown("---")
            col_exp1, _ = st.columns([1, 4])
            with col_exp1:
                csv_data = df_display.to_csv(index=False).encode()
                st.download_button(
                    "⬇️ Download CSV",
                    data=csv_data,
                    file_name=f"minervini_{meta['universe']}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                )

    else:
        # Welcome screen
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("""
            **📐 Trend Template**
            The 10-criterion Stage 2 filter ensures every stock is in a confirmed uptrend:
            price above all SMAs (50/150/200), 200 SMA rising, RS ≥ 70, within 25% of 52-week high.
            """)
        with col2:
            st.markdown("""
            **📊 VCP Pattern**
            Volatility Contraction Pattern detection identifies stocks forming tight bases
            with 2–4 progressively shrinking contractions and drying-up volume — Minervini's
            primary entry setup.
            """)
        with col3:
            st.markdown("""
            **💰 Fundamentals**
            Filters for the growth characteristics Minervini demands: EPS acceleration,
            sales growth, 3-year earnings track record, ROE ≥ 17%, and institutional sponsorship.
            """)
        st.markdown("")
        st.info("👈 Configure your settings in the sidebar and click **Run Screener** to begin.")

# ── CAN SLIM (O'Neil / IBD) tab ──────────────────────────────────────────────
with tab_canslim:
    from screener.oneil_screener import CANSLIMScreener

    st.markdown("### 🎯 CAN SLIM Screener — William O'Neil (IBD)")
    st.caption(
        "Seven criteria from *How to Make Money in Stocks*: "
        "**C**urrent EPS · **A**nnual EPS · **N**ew highs · "
        "**S**upply/Demand · **L**eader (RS≥80) · **I**nstitutional · **M**arket direction."
    )

    # ── Controls ─────────────────────────────────────────────────────────────
    ctl1, ctl2, ctl3, ctl4 = st.columns([2, 1.5, 1.5, 1.5])
    with ctl1:
        cs_universe = st.selectbox(
            "Universe",
            options=["sp500", "nasdaq100", "russell2000", "custom"],
            key="cs_universe",
            format_func=lambda x: {
                "sp500":      "S&P 500",
                "nasdaq100":  "NASDAQ-100",
                "russell2000":"Russell 2000",
                "custom":     "Custom",
            }[x],
        )
    with ctl2:
        cs_min_rs = st.slider("Min RS (L)", 70, 99,
                               int(cfg.CAN_SLIM["l_rs_rating_min"]), key="cs_min_rs")
    with ctl3:
        cs_min_eps = st.slider("Min EPS growth % (C)", 10, 100,
                                int(cfg.CAN_SLIM["c_eps_growth_min"] * 100), key="cs_min_eps")
    with ctl4:
        cs_require_base = st.checkbox("Require base pattern", value=False,
                                        key="cs_require_base",
                                        help="Only show stocks with detected Cup/Flat/DB base")

    cs_clear = st.checkbox("Clear cache (fresh data)", value=False, key="cs_clear")
    cs_run = st.button("🎯 Run CAN SLIM Screen", type="primary", use_container_width=True,
                        key="cs_run_btn")

    # ── Execute run ──────────────────────────────────────────────────────────
    if cs_run:
        cs_config = {
            "TREND_TEMPLATE":    cfg.TREND_TEMPLATE,
            "FUNDAMENTALS":      cfg.FUNDAMENTALS,
            "RS_CALCULATION":    cfg.RS_CALCULATION,
            "VOLUME":            cfg.VOLUME,
            "UNIVERSE":          cfg.UNIVERSE,
            "CAN_SLIM":          {**cfg.CAN_SLIM,
                                    "l_rs_rating_min":  cs_min_rs,
                                    "c_eps_growth_min": cs_min_eps / 100},
            "BASE_PATTERNS":     cfg.BASE_PATTERNS,
            "CAN_SLIM_SCORING":  cfg.CAN_SLIM_SCORING,
        }
        cs_screener = CANSLIMScreener(cs_config)
        if cs_clear:
            cs_screener.data_fetcher.clear_cache()

        with st.spinner(f"Loading {cs_universe.upper()} universe..."):
            cs_tickers = get_universe(cs_universe, cfg.UNIVERSE["custom_file"])

        cs_bar = st.progress(0, text=f"Fetching data for {len(cs_tickers)} stocks...")
        cs_fetched = [0]
        def _cs_progress():
            cs_fetched[0] += 1
            cs_bar.progress(min(cs_fetched[0] / max(len(cs_tickers), 1), 1.0),
                             text=f"Fetching price data... {cs_fetched[0]}/{len(cs_tickers)}")

        _orig_cs = cs_screener.data_fetcher.batch_fetch_prices
        cs_screener.data_fetcher.batch_fetch_prices = (
            lambda ticks, period="2y", progress_callback=None:
            _orig_cs(ticks, period=period, progress_callback=_cs_progress)
        )

        t0 = time.time()
        with st.spinner("Evaluating CAN SLIM criteria..."):
            cs_passed, cs_all, cs_market = cs_screener.run(cs_tickers, verbose=False)
        cs_elapsed = time.time() - t0
        cs_bar.empty()

        if cs_require_base:
            cs_passed = [r for r in cs_passed if r.get("base", {}).get("base_detected")]

        st.session_state.canslim_results = cs_passed
        st.session_state.canslim_all_results = cs_all
        st.session_state.canslim_market = cs_market.to_dict()
        st.session_state.canslim_last_run = {
            "universe": cs_universe,
            "total":    len(cs_all),
            "elapsed":  cs_elapsed,
            "ts":       datetime.now().isoformat(),
        }
        st.rerun()

    # ── Display results ──────────────────────────────────────────────────────
    cs_res = st.session_state.canslim_results
    cs_mkt = st.session_state.canslim_market
    cs_meta = st.session_state.canslim_last_run

    if cs_res is None:
        st.info("👆 Pick a universe and click **Run CAN SLIM Screen** to begin.")
    else:
        # Market direction banner (the M in CAN SLIM — gates all buys per O'Neil)
        mkt_status = (cs_mkt or {}).get("status", "unknown")
        mkt_color = {
            "uptrend":    "#10b981",
            "correction": "#f59e0b",
            "downtrend":  "#ef4444",
            "unknown":    "#6b7280",
        }.get(mkt_status, "#6b7280")
        mkt_emoji = {"uptrend":"🟢","correction":"🟡","downtrend":"🔴","unknown":"⚪"}.get(mkt_status,"⚪")
        st.markdown(
            f"""<div style='background:linear-gradient(135deg,#0e111d,#151a2a);
                            border:1px solid {mkt_color};
                            border-left:4px solid {mkt_color};
                            padding:0.8rem 1rem; border-radius:10px; margin-bottom:1rem;'>
                  <span style='color:{mkt_color}; font-weight:700; font-size:1rem;'>
                    {mkt_emoji} Market Direction (M): {mkt_status.upper()}
                  </span>
                  <span style='color:#94a3b8; margin-left:1rem; font-size:0.85rem;'>
                    SPY &gt; 50SMA: {'✓' if (cs_mkt or {}).get('spy_above_sma50') else '✗'} &nbsp;·&nbsp;
                    SPY &gt; 200SMA: {'✓' if (cs_mkt or {}).get('spy_above_sma200') else '✗'} &nbsp;·&nbsp;
                    Distribution days (last 25): {(cs_mkt or {}).get('distribution_days_last_25', 0)}
                  </span>
                </div>""",
            unsafe_allow_html=True,
        )
        if mkt_status != "uptrend":
            st.warning("⚠️ O'Neil's rule: avoid new buys when the general market is not in a confirmed uptrend.")

        # Summary metrics
        tech_pass = sum(1 for r in (st.session_state.canslim_all_results or [])
                          if r.get("canslim", {}).get("canslim_passed", "0/7").startswith(("5","6","7")))
        base_count = sum(1 for r in cs_res if r.get("base", {}).get("base_detected"))
        near_pivot = sum(1 for r in cs_res if r.get("base", {}).get("base_near_pivot"))

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Screened",      cs_meta["total"])
        m2.metric("CAN SLIM ✓",   len(cs_res))
        m3.metric("Near-pass (5-7)", tech_pass)
        m4.metric("With Base",    base_count)
        m5.metric("Runtime",      f"{cs_meta['elapsed']:.1f}s")

        if not cs_res:
            st.warning("No stocks passed all 7 CAN SLIM criteria. Showing top near-misses below.")
            near = sorted(
                st.session_state.canslim_all_results or [],
                key=lambda r: int(r.get("canslim", {}).get("canslim_passed", "0/7").split("/")[0]),
                reverse=True,
            )[:15]
            cs_display = near
        else:
            cs_display = cs_res

        # Build DataFrame for display
        rows = []
        for r in cs_display:
            cs = r.get("canslim", {})
            b = r.get("base", {})
            t = r.get("technical", {})
            rows.append({
                "Ticker":    r["ticker"],
                "Score":     r.get("score", 0),
                "CANSLIM":   cs.get("canslim_letters", ""),
                "Pass":      cs.get("canslim_passed", ""),
                "RS":        cs.get("rs_rating", 0),
                "Price":     t.get("current_price", 0),
                "% from Hi": cs.get("pct_from_52wk_high", 0),
                "EPS%":      cs.get("eps_growth_current_qtr_pct"),
                "Sales%":    cs.get("sales_growth_pct"),
                "ROE%":      cs.get("roe_pct"),
                "Inst%":     cs.get("institutional_ownership_pct"),
                "Base":      b.get("base_pattern", "none"),
                "Pivot":     b.get("base_pivot_price", 0),
                "Stop":      b.get("base_stop_price", 0),
                "% Pivot":   b.get("base_pct_from_pivot", 0),
                "Sector":    r.get("sector", ""),
            })

        df_cs = pd.DataFrame(rows)
        st.markdown("### 📋 Results")
        st.dataframe(
            df_cs,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score":     st.column_config.ProgressColumn("Score", min_value=0, max_value=100, width=80),
                "CANSLIM":   st.column_config.TextColumn("Letters", width=110,
                               help="Which of C-A-N-S-L-I-M this stock passes"),
                "Price":     st.column_config.NumberColumn("Price",     format="$%.2f"),
                "Pivot":     st.column_config.NumberColumn("Pivot",     format="$%.2f"),
                "Stop":      st.column_config.NumberColumn("Stop",      format="$%.2f"),
                "% from Hi": st.column_config.NumberColumn("% from Hi", format="%.1f%%"),
                "% Pivot":   st.column_config.NumberColumn("% Pivot",   format="%+.1f%%"),
                "EPS%":      st.column_config.NumberColumn("EPS%",      format="%.1f%%"),
                "Sales%":    st.column_config.NumberColumn("Sales%",    format="%.1f%%"),
                "ROE%":      st.column_config.NumberColumn("ROE%",      format="%.1f%%"),
                "Inst%":     st.column_config.NumberColumn("Inst%",     format="%.1f%%"),
                "RS":        st.column_config.NumberColumn("RS",        format="%d", width=55),
            },
            height=560,
        )

        # Near-pivot spotlight
        near_pivot_rows = [r for r in cs_res if r.get("base", {}).get("base_near_pivot")]
        if near_pivot_rows:
            st.markdown("### ⭐ Near Pivot — Base Breakout Candidates")
            cols = st.columns(min(len(near_pivot_rows), 4))
            for i, r in enumerate(near_pivot_rows[:4]):
                b = r["base"]; cs = r["canslim"]; t = r["technical"]
                with cols[i]:
                    st.markdown(
                        f"""<div class="pivot-alert">
                              <div class="ticker">{r['ticker']}</div>
                              <div class="detail">
                                {b['base_pattern'].replace('_', ' ').title()} &nbsp;|&nbsp; Score {r['score']:.0f}<br>
                                Pivot ${b['base_pivot_price']:.2f} &nbsp;|&nbsp; Stop ${b['base_stop_price']:.2f}<br>
                                {b['base_pct_from_pivot']:+.1f}% from pivot<br>
                                RS {cs['rs_rating']:.0f} &nbsp;|&nbsp; EPS {cs.get('eps_growth_current_qtr_pct', 'N/A')}%
                              </div>
                            </div>""",
                        unsafe_allow_html=True,
                    )


# ── Analyze single ticker tab ─────────────────────────────────────────────────
with tab_analyze:
    from analyze import run_analysis

    st.markdown("### 🔎 Analyze a Single Ticker")
    st.caption("Enter any symbol — get the full **Minervini SEPA** *and* **O'Neil CAN SLIM** "
               "breakdown, every criterion pass/fail (runs even if it fails the screens). "
               "RS is percentile-ranked vs the S&P 500.")

    ac1, ac2 = st.columns([3, 1])
    with ac1:
        az_ticker = st.text_input("Symbol", placeholder="e.g. NVDA", key="az_ticker",
                                  label_visibility="collapsed")
    with ac2:
        az_run = st.button("🔎 Analyze", type="primary", use_container_width=True, key="az_run")

    if az_run and az_ticker.strip():
        with st.spinner(f"Analyzing {az_ticker.upper().strip()} (computing RS vs S&P 500)..."):
            st.session_state.az_result = run_analysis(az_ticker)

    az_res = st.session_state.get("az_result")
    if az_res and "error" in az_res:
        st.error(az_res["error"])
    elif az_res:
        cs = az_res["canslim"]; base = az_res["base"]; mkt = az_res["market"]
        price = float(az_res["df"]["Close"].iloc[-1])
        st.markdown(f"## {az_res['ticker']} — ${price:.2f}")

        col_m, col_o = st.columns(2)
        with col_m:
            st.markdown("### 🔍 Minervini SEPA")
            _render_stock_detail(az_res["minervini"], key_suffix="_analyze")
        with col_o:
            st.markdown("### 🎯 O'Neil CAN SLIM")
            letters = cs.get("canslim_letters", "")
            st.markdown(f"**[{letters}]** — {cs.get('canslim_passed','?')}  ·  RS {cs.get('rs_rating',0):.0f}")
            for label, key in [
                (f"C — Current EPS growth  {cs.get('eps_growth_current_qtr_pct','N/A')}%", "c_current_eps"),
                (f"A — Annual EPS growth  ({cs.get('consecutive_eps_growth_years',0)} yrs, ROE {cs.get('roe_pct','N/A')}%)", "a_annual_eps"),
                (f"N — New high  ({cs.get('pct_from_52wk_high',0):.1f}% from 52wk high)", "n_new_high"),
                (f"S — Supply/Demand  (A/D {cs.get('acc_dist_ratio',0):.2f}x)", "s_supply_demand"),
                (f"L — Leader  (RS {cs.get('rs_rating',0):.0f})", "l_leader"),
                (f"I — Institutional  ({cs.get('institutional_ownership_pct','N/A')}%)", "i_institutional"),
                (f"M — Market direction  ({mkt.status})", "m_market_ok"),
            ]:
                st.markdown(f"{'✅' if cs.get(key) else '❌'} {label}")

            st.markdown("**Base Pattern**")
            if base.get("base_detected"):
                st.markdown(
                    f"🟢 {base['base_pattern'].replace('_',' ').title()} — "
                    f"{base['base_length_weeks']}w, depth {base['base_depth_pct']}%  ·  "
                    f"Pivot ${base['base_pivot_price']:.2f} · Stop ${base['base_stop_price']:.2f} · "
                    f"{base['base_pct_from_pivot']:+.1f}% away")
            else:
                st.markdown("⚪ No base pattern detected")

            if not mkt.confirmed_uptrend:
                st.warning("⚠️ Market not in confirmed uptrend — O'Neil rule: avoid new buys.")
    else:
        st.info("👆 Enter a symbol and click **Analyze**.")


# ── Watchlist tab ─────────────────────────────────────────────────────────────
with tab_watchlist:
    _render_watchlist_tab()

# ── History tab ───────────────────────────────────────────────────────────────
with tab_history:
    _render_history_tab()


