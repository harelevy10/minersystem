"""
Data Fetcher
Handles all yfinance API calls with caching, error handling, and rate limiting.
"""

import os
import time
import json
import hashlib
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class DataFetcher:
    """
    Fetches and caches stock price history and fundamental data from yfinance.
    """

    def __init__(self, cache_dir: str = "cache/", cache_ttl_hours: int = 4,
                 api_delay: float = 0.1, max_workers: int = 10):
        self.cache_dir = cache_dir
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.api_delay = api_delay
        self.max_workers = max_workers
        os.makedirs(cache_dir, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Price History
    # ─────────────────────────────────────────────────────────────────────────

    def get_price_history(self, ticker: str, period: str = "2y") -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV daily price history for a ticker.
        Returns a DataFrame with columns: Open, High, Low, Close, Volume, Adj Close
        """
        cache_key = f"price_{ticker}_{period}"
        cached = self._load_cache(cache_key)
        if cached is not None:
            return cached

        try:
            time.sleep(self.api_delay)
            t = yf.Ticker(ticker)
            df = t.history(period=period, auto_adjust=True)
            if df is None or df.empty or len(df) < 50:
                return None
            df.index = pd.to_datetime(df.index).tz_localize(None)
            self._save_cache(cache_key, df)
            return df
        except Exception as e:
            logger.debug(f"Price fetch failed for {ticker}: {e}")
            return None

    def get_benchmark_history(self, ticker: str = "SPY", period: str = "2y") -> Optional[pd.DataFrame]:
        """Fetch benchmark (SPY) price history."""
        return self.get_price_history(ticker, period)

    # ─────────────────────────────────────────────────────────────────────────
    # Fundamental Data
    # ─────────────────────────────────────────────────────────────────────────

    def get_fundamentals(self, ticker: str) -> dict:
        """
        Fetch fundamental data for a ticker.
        Returns a dict with all available financial metrics.
        """
        cache_key = f"fundamentals_{ticker}"
        cached = self._load_cache(cache_key, as_dataframe=False)
        if cached is not None:
            return cached

        try:
            time.sleep(self.api_delay)
            t = yf.Ticker(ticker)
            info = t.info or {}
            financials = self._parse_financials(t, info)
            result = {**info, **financials}
            self._save_cache(cache_key, result, as_dataframe=False)
            return result
        except Exception as e:
            logger.debug(f"Fundamentals fetch failed for {ticker}: {e}")
            return {}

    def _parse_financials(self, ticker_obj: yf.Ticker, info: dict) -> dict:
        """Parse income statement and quarterly earnings data."""
        result = {}

        try:
            # Quarterly earnings history
            earnings_hist = ticker_obj.earnings_history
            if earnings_hist is not None and not earnings_hist.empty:
                result["earnings_history"] = earnings_hist.to_dict()
        except Exception:
            pass

        try:
            # Quarterly financials
            qf = ticker_obj.quarterly_financials
            if qf is not None and not qf.empty:
                result["quarterly_revenue"] = self._extract_quarterly_revenue(qf)
        except Exception:
            pass

        try:
            # Annual financials
            af = ticker_obj.financials
            if af is not None and not af.empty:
                result["annual_revenue"] = self._extract_annual_revenue(af)
        except Exception:
            pass

        try:
            # Quarterly income statement
            qi = ticker_obj.quarterly_income_stmt
            if qi is not None and not qi.empty:
                result["quarterly_income"] = self._extract_quarterly_income(qi)
        except Exception:
            pass

        return result

    def _extract_quarterly_revenue(self, qf: pd.DataFrame) -> list:
        """Extract the last 4 quarterly revenue figures."""
        try:
            if "Total Revenue" in qf.index:
                rev = qf.loc["Total Revenue"].dropna()
                return [float(v) for v in rev.values[:4]]
        except Exception:
            pass
        return []

    def _extract_annual_revenue(self, af: pd.DataFrame) -> list:
        """Extract the last 4 annual revenue figures."""
        try:
            if "Total Revenue" in af.index:
                rev = af.loc["Total Revenue"].dropna()
                return [float(v) for v in rev.values[:4]]
        except Exception:
            pass
        return []

    def _extract_quarterly_income(self, qi: pd.DataFrame) -> list:
        """Extract last 4 quarters of operating income / pre-tax income."""
        try:
            for row_name in ["Pretax Income", "Operating Income", "Net Income"]:
                if row_name in qi.index:
                    inc = qi.loc[row_name].dropna()
                    return [float(v) for v in inc.values[:4]]
        except Exception:
            pass
        return []

    # ─────────────────────────────────────────────────────────────────────────
    # Batch Fetching
    # ─────────────────────────────────────────────────────────────────────────

    def batch_fetch_prices(self, tickers: list[str], period: str = "2y",
                           progress_callback=None) -> dict[str, pd.DataFrame]:
        """
        Fetch price history for multiple tickers in parallel.
        Returns a dict mapping ticker -> DataFrame.
        """
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.get_price_history, t, period): t
                for t in tickers
            }
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    df = future.result()
                    if df is not None:
                        results[ticker] = df
                except Exception as e:
                    logger.debug(f"Batch price fetch error for {ticker}: {e}")
                if progress_callback:
                    progress_callback()
        return results

    def batch_fetch_fundamentals(self, tickers: list[str],
                                 progress_callback=None) -> dict[str, dict]:
        """
        Fetch fundamentals for multiple tickers in parallel.
        Returns a dict mapping ticker -> fundamentals dict.
        """
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.get_fundamentals, t): t
                for t in tickers
            }
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    data = future.result()
                    results[ticker] = data
                except Exception as e:
                    logger.debug(f"Batch fundamentals error for {ticker}: {e}")
                if progress_callback:
                    progress_callback()
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Cache Management
    # ─────────────────────────────────────────────────────────────────────────

    def _cache_path(self, key: str, as_dataframe: bool = True) -> str:
        h = hashlib.md5(key.encode()).hexdigest()
        ext = "parquet" if as_dataframe else "json"
        return os.path.join(self.cache_dir, f"{h}.{ext}")

    def _is_cache_fresh(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        return datetime.now() - mtime < self.cache_ttl

    def _load_cache(self, key: str, as_dataframe: bool = True):
        path = self._cache_path(key, as_dataframe)
        if not self._is_cache_fresh(path):
            return None
        try:
            if as_dataframe:
                return pd.read_parquet(path)
            else:
                with open(path) as f:
                    return json.load(f)
        except Exception:
            return None

    def _save_cache(self, key: str, data, as_dataframe: bool = True):
        path = self._cache_path(key, as_dataframe)
        try:
            if as_dataframe:
                data.to_parquet(path)
            else:
                with open(path, "w") as f:
                    # Convert non-serializable objects to strings
                    json.dump(_make_serializable(data), f)
        except Exception as e:
            logger.debug(f"Cache save failed for {key}: {e}")

    def clear_cache(self):
        """Delete all cached files."""
        for f in os.listdir(self.cache_dir):
            try:
                os.remove(os.path.join(self.cache_dir, f))
            except Exception:
                pass
        print(f"Cache cleared: {self.cache_dir}")


def _make_serializable(obj):
    """Recursively convert non-JSON-serializable objects."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_serializable(i) for i in obj]
    elif isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64)):
        return float(obj) if not np.isnan(obj) else None
    elif isinstance(obj, np.ndarray):
        return [_make_serializable(i) for i in obj.tolist()]
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif isinstance(obj, float) and np.isnan(obj):
        return None
    else:
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)
