"""
Stock Universe Loader
Fetches ticker lists for S&P 500, NASDAQ 100, Russell 2000, or custom lists.
"""

import os
import requests
import pandas as pd
from io import StringIO


def get_sp500() -> list[str]:
    """Fetch current S&P 500 constituents from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        return sorted(tickers)
    except Exception as e:
        print(f"  [!] Failed to fetch S&P 500 from Wikipedia: {e}")
        return _sp500_fallback()


def get_nasdaq100() -> list[str]:
    """Fetch current NASDAQ-100 constituents from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        # Find the table that has a "Ticker" or "Symbol" column
        for df in tables:
            cols = [c.lower() for c in df.columns]
            if "ticker" in cols or "symbol" in cols:
                col = "Ticker" if "Ticker" in df.columns else "Symbol"
                tickers = df[col].str.replace(".", "-", regex=False).tolist()
                return sorted([t for t in tickers if isinstance(t, str) and len(t) <= 5])
        raise ValueError("No suitable table found")
    except Exception as e:
        print(f"  [!] Failed to fetch NASDAQ-100 from Wikipedia: {e}")
        return _nasdaq100_fallback()


def get_russell2000() -> list[str]:
    """
    Fetch Russell 2000 constituents.
    Uses iShares IWM holdings as a proxy (free, reliable).
    Falls back to a curated small-cap list if unavailable.
    """
    url = (
        "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/"
        "1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        # The CSV has metadata rows before the actual data
        lines = resp.text.splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith("Ticker"))
        df = pd.read_csv(StringIO("\n".join(lines[start:])))
        tickers = df["Ticker"].dropna().tolist()
        return sorted([t.strip() for t in tickers if isinstance(t, str) and 1 <= len(t) <= 5])
    except Exception as e:
        print(f"  [!] Failed to fetch Russell 2000 holdings: {e}")
        print("      Using S&P 500 as fallback.")
        return get_sp500()


def get_custom(filepath: str) -> list[str]:
    """
    Load tickers from a custom file.
    Supports one ticker per line, or comma-separated on one line.
    Lines starting with '#' are treated as comments.
    """
    if not os.path.exists(filepath):
        print(f"  [!] Custom ticker file not found: {filepath}")
        return []
    tickers = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Support comma-separated or space-separated
            for t in line.replace(",", " ").split():
                t = t.strip().upper()
                if t:
                    tickers.append(t)
    return sorted(set(tickers))


def get_universe(name: str, custom_file: str = "universe/custom.txt") -> list[str]:
    """
    Return the requested stock universe as a list of tickers.

    Args:
        name: One of "sp500", "nasdaq100", "russell2000", "custom"
        custom_file: Path to custom ticker file (only used when name="custom")

    Returns:
        Sorted list of ticker symbols
    """
    name = name.lower().strip()
    loaders = {
        "sp500": get_sp500,
        "nasdaq100": get_nasdaq100,
        "russell2000": get_russell2000,
    }
    if name in loaders:
        return loaders[name]()
    elif name == "custom":
        return get_custom(custom_file)
    else:
        print(f"  [!] Unknown universe '{name}'. Defaulting to S&P 500.")
        return get_sp500()


# ─────────────────────────────────────────────────────────────────────────────
# Fallback lists (in case web fetches fail)
# ─────────────────────────────────────────────────────────────────────────────

def _sp500_fallback() -> list[str]:
    """A representative sample of S&P 500 tickers as fallback."""
    return [
        "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "BRK-B",
        "UNH", "JPM", "V", "XOM", "JNJ", "PG", "MA", "LLY", "AVGO", "HD",
        "CVX", "MRK", "ABBV", "PEP", "COST", "ADBE", "CRM", "TMO", "WMT",
        "BAC", "ACN", "NFLX", "AMD", "TXN", "QCOM", "DHR", "NEE", "LIN",
        "PM", "ORCL", "MDT", "HON", "UPS", "AMGN", "SCHW", "INTU", "INTC",
        "IBM", "CAT", "GS", "BLK", "SPGI", "AXP", "DE", "GILD", "ELV",
        "LOW", "ADI", "ISRG", "REGN", "MMC", "ZTS", "VRTX", "CI", "TJX",
        "MU", "NOW", "PLD", "CB", "SO", "DUK", "SYK", "BSX", "LRCX", "ETN",
        "AON", "KLAC", "MELI", "PANW", "SNPS", "CDNS", "MCO", "APD", "FIS",
        "MPC", "PSX", "VLO", "OXY", "COP", "SLB", "EOG", "PXD", "MOS",
        "CF", "NUE", "STLD", "FCX", "X", "AA", "CLF", "ATI",
    ]


def _nasdaq100_fallback() -> list[str]:
    """A representative sample of NASDAQ-100 tickers as fallback."""
    return [
        "AAPL", "MSFT", "AMZN", "NVDA", "META", "TSLA", "GOOGL", "GOOG",
        "AVGO", "ADBE", "COST", "PEP", "CSCO", "NFLX", "CMCSA", "TMUS",
        "INTC", "AMD", "QCOM", "TXN", "AMAT", "LRCX", "MRVL", "KLAC",
        "SNPS", "CDNS", "MELI", "ASML", "INTU", "ISRG", "REGN", "VRTX",
        "GILD", "AMGN", "MDLZ", "SBUX", "ATVI", "ADP", "PANW", "FTNT",
        "CRWD", "ZS", "DDOG", "SNOW", "MDB", "NET", "OKTA", "ZM", "TEAM",
        "WDAY", "NOW", "VEEV", "PAYC", "COUP", "HUBS", "BILL", "ABNB",
        "DASH", "RBLX", "RIVN", "LCID", "NIO", "XPEV", "LI",
    ]
