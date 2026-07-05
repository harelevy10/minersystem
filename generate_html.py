#!/usr/bin/env python3
"""
Standalone HTML Report Generator
================================
Runs the Minervini SEPA screener (or O'Neil CAN SLIM) and writes a single,
self-contained interactive HTML file you can open in any browser — no Claude,
no Streamlit, no server needed.

Usage:
    python3 generate_html.py                      # Screen S&P 500, open report
    python3 generate_html.py --universe nasdaq100
    python3 generate_html.py --tickers NVDA AAPL MSFT
    python3 generate_html.py --method oneil
    python3 generate_html.py --no-open            # Don't auto-open browser
    python3 generate_html.py --from-csv           # Skip screening, build from latest CSV

The HTML is saved to output/report.html (and a timestamped copy).
"""

import os
import sys
import json
import time
import glob
import csv
import argparse
import webbrowser
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg


# ─────────────────────────────────────────────────────────────────────────────
# Config / screening
# ─────────────────────────────────────────────────────────────────────────────

def build_config(args) -> dict:
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
    config["TREND_TEMPLATE"]["rs_rating_min"] = args.min_rs
    return config


def run_screen(args):
    """Run the screener and return (passed, all_results, meta)."""
    from screener.universe import get_universe

    config = build_config(args)

    if args.tickers:
        tickers = [t.upper().strip() for t in args.tickers]
        universe_name = "custom"
    else:
        universe_name = args.universe
        print(f"  Loading {universe_name.upper()} universe...")
        tickers = get_universe(universe_name, cfg.UNIVERSE["custom_file"])

    if not tickers:
        print("  [ERROR] No tickers to screen.")
        sys.exit(1)

    print(f"  Screening {len(tickers)} tickers with method='{args.method}'...")

    market = None
    if args.method == "oneil":
        from screener.oneil_screener import CANSLIMScreener
        config["CAN_SLIM"] = dict(cfg.CAN_SLIM)
        config["BASE_PATTERNS"] = dict(cfg.BASE_PATTERNS)
        config["CAN_SLIM_SCORING"] = dict(cfg.CAN_SLIM_SCORING)
        screener = CANSLIMScreener(config)
        start = time.time()
        passed, all_results, market = screener.run(tickers, verbose=True)
    else:
        from screener.screener import MinerviniScreener
        screener = MinerviniScreener(config)
        start = time.time()
        passed, all_results = screener.run(tickers, verbose=True)

    shorts = []
    if args.method != "oneil":
        shorts = [r for r in all_results if r.get("technical", {}).get("passes_short_trend_template")]
        shorts.sort(key=lambda r: r.get("technical", {}).get("rs_rating", 99))

    elapsed = time.time() - start
    meta = {
        "method": args.method,
        "universe": universe_name,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "screened": len([r for r in all_results if r.get("technical") or r.get("canslim")]),
        "passed": len(passed),
        "elapsed": round(elapsed, 1),
        "market": (market.status if market else None),
        "market_uptrend": (market.confirmed_uptrend if market else None),
    }
    return passed, all_results, meta, shorts


def load_from_csv():
    """Build results from the most recent CSV in output/ (no live screening)."""
    files = sorted(glob.glob("output/minervini_screener_*.csv"))
    if not files:
        print("  [ERROR] No CSV found in output/. Run a screen first.")
        sys.exit(1)
    path = files[-1]
    print(f"  Building from {path}")

    def coerce(v):
        if v in ("", "None", "nan"):
            return None
        if v in ("True", "TRUE"):
            return True
        if v in ("False", "FALSE"):
            return False
        try:
            return float(v) if ("." in v or "e" in v.lower()) else int(v)
        except (ValueError, TypeError):
            return v

    passed = []
    with open(path) as f:
        for row in csv.DictReader(f):
            row = {k: coerce(v) for k, v in row.items()}
            passed.append(_flat_to_nested(row))

    meta = {
        "method": "minervini",
        "universe": "(from CSV)",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "screened": len(passed),
        "passed": len(passed),
        "elapsed": 0,
        "market": None,
        "market_uptrend": None,
        "source": os.path.basename(path),
    }
    return passed, passed, meta


def _flat_to_nested(row: dict) -> dict:
    """Rebuild the nested {technical, fundamental, vcp} shape from a flat CSV row."""
    tech_keys = {
        "stage", "current_price", "sma_50", "sma_150", "sma_200", "week_52_high",
        "week_52_low", "pct_from_52wk_high", "pct_above_52wk_low", "rs_rating",
        "rs_line_trending_up", "volume_trend", "acc_dist_ratio", "criteria_passed",
        "passes_trend_template", "c1_price_above_sma150", "c2_price_above_sma200",
        "c3_sma150_above_sma200", "c4_sma200_trending_up", "c5_sma50_above_sma150",
        "c6_sma50_above_sma200", "c7_price_above_sma50", "c8_above_52wk_low",
        "c9_near_52wk_high", "c10_rs_rating",
    }
    nested = {"ticker": row.get("ticker"), "score": row.get("score") or 0,
              "technical": {}, "fundamental": {}, "vcp": {}}
    for k, v in row.items():
        if k in ("ticker", "score"):
            continue
        if k in tech_keys:
            nested["technical"][k] = v
        elif k.startswith("vcp_"):
            nested["vcp"][k] = v
        else:
            nested["fundamental"][k] = v
    return nested


# ─────────────────────────────────────────────────────────────────────────────
# HTML generation
# ─────────────────────────────────────────────────────────────────────────────

def make_safe(results):
    """Make results JSON-serializable (drop unserializable values)."""
    return json.loads(json.dumps(results, default=str))


def write_html(passed, meta, shorts=None, out_dir="output"):
    os.makedirs(out_dir, exist_ok=True)
    payload = json.dumps(
        {"meta": meta, "results": make_safe(passed), "shorts": make_safe(shorts or [])},
        ensure_ascii=False,
    )
    html = HTML_TEMPLATE.replace("/*__DATA__*/", payload)

    main_path = os.path.join(out_dir, "report.html")
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(html)

    # timestamped archive copy
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    with open(os.path.join(out_dir, f"report_{stamp}.html"), "w", encoding="utf-8") as f:
        f.write(html)

    return os.path.abspath(main_path)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Minervini SEPA Screener — Report</title>
<style>
  :root{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2330; --border:#2d333b;
    --text:#e6edf3; --muted:#8b949e; --green:#2ea043; --green2:#3fb950;
    --red:#f85149; --yellow:#d29922; --cyan:#39c5cf; --accent:#58a6ff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    font-size:14px;line-height:1.5}
  header{padding:20px 28px;border-bottom:1px solid var(--border);
    background:linear-gradient(180deg,#161b22,#0d1117)}
  h1{margin:0;font-size:20px;letter-spacing:.3px}
  h1 .tag{color:var(--accent)}
  .sub{color:var(--muted);font-size:13px;margin-top:4px}
  .stats{display:flex;flex-wrap:wrap;gap:12px;padding:18px 28px}
  .stat{background:var(--panel);border:1px solid var(--border);border-radius:10px;
    padding:12px 18px;min-width:120px}
  .stat .n{font-size:24px;font-weight:700}
  .stat .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
  .stat.green .n{color:var(--green2)} .stat.cyan .n{color:var(--cyan)} .stat.red .n{color:var(--red)}
  .shorts-hdr{color:var(--red);text-transform:uppercase;font-size:13px;letter-spacing:.5px;margin:22px 0 10px}
  .controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:0 28px 14px}
  .controls input,.controls select{background:var(--panel);color:var(--text);
    border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:13px}
  .controls input{min-width:220px}
  .chk{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:13px;cursor:pointer}
  .wrap{padding:0 28px 40px}
  table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
  th,td{padding:9px 10px;text-align:right;border-bottom:1px solid var(--border);white-space:nowrap}
  th{position:sticky;top:0;background:var(--panel2);color:var(--muted);font-size:12px;
    text-transform:uppercase;letter-spacing:.4px;cursor:pointer;user-select:none;z-index:2}
  th.l,td.l{text-align:left}
  th.c,td.c{text-align:center}
  th:hover{color:var(--text)}
  tbody tr{cursor:pointer}
  tbody tr:hover{background:var(--panel)}
  .tick{font-weight:700;color:var(--cyan)}
  .pos{color:var(--green2)} .neg{color:var(--red)} .mut{color:var(--muted)}
  .pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:12px;font-weight:600}
  .pill.s2{background:rgba(63,185,80,.15);color:var(--green2)}
  .pill.s1,.pill.s3{background:rgba(210,153,34,.15);color:var(--yellow)}
  .pill.s4{background:rgba(248,81,73,.15);color:var(--red)}
  .pill.s0{background:rgba(139,148,158,.15);color:var(--muted)}
  .ok{color:var(--green2);font-weight:700} .no{color:var(--red);font-weight:700}
  .rs{font-weight:700}
  .vcp-yes{color:var(--green2);font-weight:600} .vcp-no{color:var(--muted)}
  .score-bar{display:inline-block;width:46px;height:8px;background:var(--border);
    border-radius:5px;overflow:hidden;vertical-align:middle;margin-right:6px}
  .score-bar i{display:block;height:100%;background:linear-gradient(90deg,#d29922,#3fb950)}
  /* detail modal */
  .overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;
    align-items:flex-start;justify-content:center;padding:40px 16px;overflow:auto;z-index:10}
  .overlay.on{display:flex}
  .modal{background:var(--panel);border:1px solid var(--border);border-radius:14px;
    width:min(820px,100%);padding:24px 28px}
  .modal h2{margin:0 0 2px;font-size:22px}
  .modal h2 .px{color:var(--muted);font-weight:400;font-size:16px;margin-left:8px}
  .close{float:right;cursor:pointer;color:var(--muted);font-size:22px;line-height:1}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:18px}
  .sec h3{font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:var(--accent);
    border-bottom:1px solid var(--border);padding-bottom:6px;margin:0 0 8px}
  .crit{display:flex;justify-content:space-between;gap:10px;padding:3px 0}
  .crit .lbl{color:var(--text)}
  .crit .v{color:var(--muted);font-size:12px}
  .vcpbox{margin-top:18px;background:var(--panel2);border:1px solid var(--border);
    border-radius:10px;padding:14px 18px}
  .empty{padding:60px;text-align:center;color:var(--muted)}
  footer{padding:18px 28px;color:var(--muted);font-size:12px;border-top:1px solid var(--border)}
  @media (max-width:680px){.grid2{grid-template-columns:1fr}.controls input{min-width:140px}}
</style>
</head>
<body>
<header>
  <h1>Minervini <span class="tag">SEPA</span> Screener</h1>
  <div class="sub" id="sub"></div>
</header>

<div class="stats" id="stats"></div>

<div class="controls">
  <input id="search" type="search" placeholder="Filter ticker…" autocomplete="off">
  <select id="sortsel">
    <option value="score">Sort: Score</option>
    <option value="rs">Sort: RS Rating</option>
    <option value="eps">Sort: EPS Growth</option>
    <option value="price">Sort: Price</option>
  </select>
  <label class="chk"><input type="checkbox" id="vcponly"> VCP only</label>
  <label class="chk"><input type="checkbox" id="pivotonly"> Near pivot (≤5%)</label>
  <span class="mut" id="count"></span>
</div>

<div class="wrap">
  <table id="tbl">
    <thead><tr>
      <th class="l" data-k="ticker">Ticker</th>
      <th data-k="price">Price</th>
      <th data-k="rs">RS</th>
      <th class="c" data-k="stage">Stage</th>
      <th data-k="eps">EPS %</th>
      <th data-k="sales">Sales %</th>
      <th data-k="roe">ROE %</th>
      <th class="c" data-k="vcp">VCP</th>
      <th data-k="pivot">Pivot</th>
      <th data-k="stop">Stop</th>
      <th class="c" data-k="tech">Tech</th>
      <th class="c" data-k="fund">Fund</th>
      <th data-k="score">Score</th>
    </tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <div class="empty" id="empty" style="display:none">No stocks match the current filters.</div>
</div>

<div class="wrap" id="shortsWrap" style="display:none">
  <h3 class="shorts-hdr">🔻 Short Candidates — confirmed Stage 4 downtrend</h3>
  <table id="shortsTbl">
    <thead><tr>
      <th class="l">Ticker</th><th>Price</th><th>RS</th><th class="c">Stage</th>
      <th>50 SMA</th><th>150 SMA</th><th>% From High</th><th class="l">Vol Trend</th>
    </tr></thead>
    <tbody id="shortsRows"></tbody>
  </table>
</div>

<div class="overlay" id="overlay"><div class="modal" id="modal"></div></div>

<footer>Generated locally from cached/live data via yfinance. Educational use only — not investment advice.</footer>

<script>
const DATA = /*__DATA__*/;
const meta = DATA.meta, ALL = DATA.results || [], SHORTS = DATA.shorts || [];

// ---------- helpers ----------
const num = v => (v===null||v===undefined||v===""||isNaN(v))?null:Number(v);
const money = v => { v=num(v); return v===null?'<span class="mut">—</span>':'$'+v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); };
const pct = v => { v=num(v); if(v===null) return '<span class="mut">—</span>';
  const c=v>=0?'pos':'neg'; return `<span class="${c}">${v>=0?'+':''}${v.toFixed(1)}%</span>`; };
const big = v => { v=num(v); if(v===null) return '—';
  if(v>=1e9)return (v/1e9).toFixed(1)+'B'; if(v>=1e6)return (v/1e6).toFixed(1)+'M';
  if(v>=1e3)return (v/1e3).toFixed(1)+'K'; return v.toFixed(0); };
const truthy = v => v===true||v==="True"||v==="TRUE"||v===1;
const STAGE={1:['1 · Base','s1'],2:['2 · Bull','s2'],3:['3 · Top','s3'],4:['4 · Bear','s4'],0:['?','s0']};

function row2view(r){
  const t=r.technical||{}, f=r.fundamental||{}, v=r.vcp||{};
  return {
    ref:r, ticker:r.ticker||'',
    price:num(t.current_price),
    rs:num(t.rs_rating),
    stage:num(t.stage)||0,
    eps:num(f.eps_growth_current_qtr_pct),
    sales:num(f.sales_growth_current_qtr_pct),
    roe:num(f.roe_pct),
    vcp:truthy(v.vcp_detected),
    contractions:num(v.vcp_contractions),
    pivot:truthy(v.vcp_detected)?num(v.vcp_pivot_price):null,
    stop:truthy(v.vcp_detected)?num(v.vcp_stop_price):null,
    pctpiv:num(v.vcp_pct_from_pivot),
    nearpiv:truthy(v.vcp_near_pivot),
    tech:truthy(t.passes_trend_template),
    fund:truthy(f.passes_mandatory_fundamentals),
    score:num(r.score)||0,
  };
}
const VIEWS = ALL.map(row2view);

// ---------- header / stats ----------
document.getElementById('sub').textContent =
  `${(meta.method||'minervini').toUpperCase()} · ${String(meta.universe||'').toUpperCase()} · generated ${meta.generated}`
  + (meta.source?` · source ${meta.source}`:'');

const nearN = VIEWS.filter(v=>v.nearpiv).length;
const vcpN  = VIEWS.filter(v=>v.vcp).length;
const stats=[
  ['Passed', meta.passed, 'green'], ['Screened', meta.screened, ''],
  ['VCP patterns', vcpN, 'cyan'], ['Near pivot', nearN, 'cyan'],
  ['Runtime', (meta.elapsed||0)+'s', ''],
];
if(meta.market) stats.push(['Market', meta.market, meta.market_uptrend?'green':'']);
if(SHORTS.length) stats.push(['Short candidates', SHORTS.length, 'red']);
document.getElementById('stats').innerHTML = stats.map(([l,n,c])=>
  `<div class="stat ${c}"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');

// ---------- short candidates ----------
if(SHORTS.length){
  document.getElementById('shortsWrap').style.display='block';
  document.getElementById('shortsRows').innerHTML = SHORTS.map(r=>{
    const t=r.technical||{};
    const st=STAGE[num(t.stage)||0]||STAGE[0];
    return `<tr>
      <td class="l"><span class="tick">${r.ticker}</span></td>
      <td>${money(num(t.current_price))}</td>
      <td class="rs neg">${(num(t.rs_rating)||0).toFixed(0)}</td>
      <td class="c"><span class="pill ${st[1]}">${st[0]}</span></td>
      <td>${money(num(t.sma_50))}</td>
      <td>${money(num(t.sma_150))}</td>
      <td>-${(num(t.pct_from_52wk_high)||0).toFixed(1)}%</td>
      <td class="l">${t.volume_trend||''}</td>
    </tr>`;
  }).join('');
}

// ---------- table render ----------
let sortKey='score', sortDir=-1;
function render(){
  const q=document.getElementById('search').value.trim().toUpperCase();
  const vcponly=document.getElementById('vcponly').checked;
  const pivotonly=document.getElementById('pivotonly').checked;
  let rows=VIEWS.filter(v=>
    (!q||v.ticker.toUpperCase().includes(q)) &&
    (!vcponly||v.vcp) && (!pivotonly||v.nearpiv));
  rows.sort((a,b)=>{
    let x=a[sortKey], y=b[sortKey];
    if(typeof x==='string'){x=x||'';y=y||'';return sortDir*x.localeCompare(y);}
    x=(x===null||x===undefined)?-1e15:x; y=(y===null||y===undefined)?-1e15:y;
    return sortDir*(x-y);
  });
  document.getElementById('count').textContent = `${rows.length} shown`;
  document.getElementById('empty').style.display = rows.length?'none':'block';
  document.getElementById('rows').innerHTML = rows.map((v,i)=>{
    const st=STAGE[v.stage]||STAGE[0];
    const rsCls = v.rs>=90?'pos':v.rs>=70?'':'neg';
    return `<tr data-i="${VIEWS.indexOf(v)}">
      <td class="l"><span class="tick">${v.ticker}</span></td>
      <td>${money(v.price)}</td>
      <td class="rs ${rsCls}">${v.rs!==null?v.rs.toFixed(0):'—'}</td>
      <td class="c"><span class="pill ${st[1]}">${st[0]}</span></td>
      <td>${pct(v.eps)}</td>
      <td>${pct(v.sales)}</td>
      <td>${pct(v.roe)}</td>
      <td class="c">${v.vcp?`<span class="vcp-yes">✓ ${v.contractions||''}T</span>`:'<span class="vcp-no">—</span>'}</td>
      <td>${v.pivot!==null?money(v.pivot):'<span class="mut">—</span>'}</td>
      <td>${v.stop!==null?money(v.stop):'<span class="mut">—</span>'}</td>
      <td class="c">${v.tech?'<span class="ok">✓</span>':'<span class="no">✗</span>'}</td>
      <td class="c">${v.fund?'<span class="ok">✓</span>':'<span class="no">✗</span>'}</td>
      <td><span class="score-bar"><i style="width:${Math.max(0,Math.min(100,v.score))}%"></i></span>${v.score.toFixed(0)}</td>
    </tr>`;}).join('');
}

// sort by header
document.querySelectorAll('th[data-k]').forEach(th=>{
  th.onclick=()=>{const k=th.dataset.k;
    if(k===sortKey)sortDir*=-1; else{sortKey=k;sortDir=(k==='ticker')?1:-1;}
    document.getElementById('sortsel').value=['score','rs','eps','price'].includes(k)?k:'score';
    render();};
});
document.getElementById('sortsel').onchange=e=>{sortKey=e.target.value;sortDir=-1;render();};
['search','vcponly','pivotonly'].forEach(id=>
  document.getElementById(id).addEventListener('input',render));

// ---------- detail modal ----------
function crit(label, passed, extra){
  const mark = passed===true?'<span class="ok">✓</span>':passed===false?'<span class="no">✗</span>':'<span class="mut">·</span>';
  return `<div class="crit"><span class="lbl">${mark} ${label}</span><span class="v">${extra||''}</span></div>`;
}
function openDetail(i){
  const r=VIEWS[i].ref, t=r.technical||{}, f=r.fundamental||{}, v=r.vcp||{};
  const st=STAGE[num(t.stage)||0]||STAGE[0];
  const tt=[
    ['Price > 150 SMA',t.c1_price_above_sma150,money(t.sma_150)],
    ['Price > 200 SMA',t.c2_price_above_sma200,money(t.sma_200)],
    ['150 SMA > 200 SMA',t.c3_sma150_above_sma200,''],
    ['200 SMA trending up',t.c4_sma200_trending_up,''],
    ['50 SMA > 150 SMA',t.c5_sma50_above_sma150,''],
    ['50 SMA > 200 SMA',t.c6_sma50_above_sma200,''],
    ['Price > 50 SMA',t.c7_price_above_sma50,money(t.sma_50)],
    ['≥25% above 52wk low',t.c8_above_52wk_low,(num(t.pct_above_52wk_low)||0).toFixed(0)+'%'],
    ['Within 25% of 52wk high',t.c9_near_52wk_high,(num(t.pct_from_52wk_high)||0).toFixed(0)+'% off'],
    ['RS Rating ≥ 70',t.c10_rs_rating,(num(t.rs_rating)||0).toFixed(0)],
  ];
  const fc=[
    ['EPS growth (qtr)',f.c_eps_growth,(f.eps_growth_current_qtr_pct??'?')+'%'],
    ['EPS acceleration',f.c_eps_acceleration,''],
    ['3yr annual EPS',f.c_annual_eps,(f.eps_consecutive_growth_years||0)+' yrs'],
    ['Sales growth',f.c_sales_growth,(f.sales_growth_current_qtr_pct??'?')+'%'],
    ['ROE ≥ 17%',f.c_roe,(f.roe_pct??'?')+'%'],
    ['Operating margin',f.c_margin,(f.pretax_margin_pct??'?')+'%'],
    ['Market cap',f.c_market_cap,big(num(f.market_cap_M)*1e6)],
    ['Avg volume',f.c_volume,big(num(f.avg_volume_K)*1e3)],
  ];
  let vcpHtml;
  if(truthy(v.vcp_detected)){
    vcpHtml=`<div class="vcpbox"><b class="vcp-yes">✓ VCP — ${v.vcp_contractions} contractions</b><br>
      Pivot ${money(v.vcp_pivot_price)} · Stop ${money(v.vcp_stop_price)} ·
      ${(num(v.vcp_pct_from_pivot)||0).toFixed(1)}% from pivot ·
      Quality ${(num(v.vcp_pattern_quality)||0).toFixed(0)}/100</div>`;
  } else {
    vcpHtml=`<div class="vcpbox"><span class="mut">No VCP pattern detected.</span></div>`;
  }
  document.getElementById('modal').innerHTML=`
    <span class="close" onclick="closeDetail()">×</span>
    <h2><span class="tick">${r.ticker}</span><span class="px">${money(t.current_price)} ·
      RS ${(num(t.rs_rating)||0).toFixed(0)} · <span class="pill ${st[1]}">${st[0]}</span> ·
      Score ${(num(r.score)||0).toFixed(0)}/100</span></h2>
    <div class="grid2">
      <div class="sec"><h3>Trend Template</h3>${tt.map(c=>crit(c[0],truthy(c[1]),c[2])).join('')}</div>
      <div class="sec"><h3>Fundamentals</h3>${fc.map(c=>crit(c[0],truthy(c[1]),c[2])).join('')}</div>
    </div>${vcpHtml}`;
  document.getElementById('overlay').classList.add('on');
}
function closeDetail(){document.getElementById('overlay').classList.remove('on');}
document.getElementById('rows').addEventListener('click',e=>{
  const tr=e.target.closest('tr'); if(tr)openDetail(+tr.dataset.i);});
document.getElementById('overlay').addEventListener('click',e=>{
  if(e.target.id==='overlay')closeDetail();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDetail();});

render();
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Generate a standalone HTML screener report")
    p.add_argument("--method", "-m", choices=["minervini", "oneil"], default="minervini")
    p.add_argument("--universe", "-u", default=cfg.UNIVERSE["default_universe"],
                   choices=["sp500", "nasdaq100", "russell2000", "custom"])
    p.add_argument("--tickers", "-t", nargs="+")
    p.add_argument("--min-rs", type=float, default=cfg.TREND_TEMPLATE["rs_rating_min"])
    p.add_argument("--from-csv", action="store_true",
                   help="Skip screening; build report from the latest output CSV")
    p.add_argument("--no-open", action="store_true", help="Do not auto-open the browser")
    return p.parse_args()


def main():
    args = parse_args()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if args.from_csv:
        passed, all_results, meta = load_from_csv()
        shorts = []
    else:
        passed, all_results, meta, shorts = run_screen(args)

    path = write_html(passed, meta, shorts=shorts)
    print(f"\n  ✓ HTML report written: {path}")
    print(f"    {meta['passed']} stocks passed / {meta['screened']} screened")

    if not args.no_open:
        webbrowser.open("file://" + path)
        print("    Opening in your browser…")


if __name__ == "__main__":
    main()
