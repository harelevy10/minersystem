"""
Volatility Contraction Pattern (VCP) Detection

The VCP is Minervini's primary base pattern. It consists of a series of price
contractions that progressively tighten in both price range and volume.

Pattern anatomy:
  - Stock forms a base after an uptrend
  - Base has 2-4 "contractions" (pullbacks from a local high)
  - Each contraction is smaller than the previous (e.g., 25%→15%→8%→4%)
  - Volume dries up as the contractions narrow
  - The final contraction forms the "pivot" (entry point)
  - Breakout occurs on expanding volume

Detection algorithm:
  1. Find the base (recent high-volume consolidation period)
  2. Identify swing highs and swing lows within the base
  3. Measure each contraction depth
  4. Verify contractions are shrinking
  5. Verify volume is drying up in each contraction
  6. Locate the pivot (most recent contraction high)
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from config import VCP, VOLUME


@dataclass
class Contraction:
    """A single price contraction within a VCP base."""
    high: float
    low: float
    high_date: str
    low_date: str
    depth_pct: float          # (high - low) / high
    avg_volume_during: float  # average volume during this contraction
    volume_percentile: float  # vs 50-day average volume


@dataclass
class VCPResult:
    """Result of VCP pattern detection."""
    detected: bool = False
    num_contractions: int = 0
    contractions: list = field(default_factory=list)
    base_start: Optional[str] = None
    base_end: Optional[str] = None
    base_length_days: int = 0
    pivot_price: float = 0.0          # Entry price (breakout point)
    stop_price: float = 0.0           # Suggested stop (below last low)
    current_price: float = 0.0
    pct_from_pivot: float = 0.0       # How far current price is from pivot
    near_pivot: bool = False          # Within 5% of pivot
    volume_drying_up: bool = False    # Volume contracting in base
    pattern_quality: float = 0.0     # 0-100 score
    tight_area: bool = False          # Final contraction very tight (<= 10%)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "vcp_detected": self.detected,
            "vcp_contractions": self.num_contractions,
            "vcp_base_length_days": self.base_length_days,
            "vcp_pivot_price": round(self.pivot_price, 2),
            "vcp_stop_price": round(self.stop_price, 2),
            "vcp_pct_from_pivot": round(self.pct_from_pivot * 100, 1),
            "vcp_near_pivot": self.near_pivot,
            "vcp_volume_drying": self.volume_drying_up,
            "vcp_pattern_quality": round(self.pattern_quality, 1),
            "vcp_tight_area": self.tight_area,
            "vcp_notes": self.notes,
        }


class VCPDetector:
    """
    Detects Volatility Contraction Patterns in price/volume data.
    """

    def __init__(self, cfg: dict = None, vol_cfg: dict = None):
        self.cfg = cfg or VCP
        self.vol_cfg = vol_cfg or VOLUME

    def detect(self, df: pd.DataFrame) -> VCPResult:
        """
        Main entry point — detect VCP in a stock's price history.

        Args:
            df: OHLCV DataFrame (daily, sorted ascending)

        Returns:
            VCPResult
        """
        result = VCPResult()
        if df is None or len(df) < 40:
            result.notes = "Insufficient data"
            return result

        df = df.copy().sort_index()
        close = df["Close"].values
        high = df["High"].values
        low = df["Low"].values
        volume = df["Volume"].values
        dates = df.index.astype(str).tolist()

        current_price = float(close[-1])
        result.current_price = current_price

        # ── Step 1: Define the base lookback window ───────────────────────
        lookback = min(self.cfg["base_lookback_days"], len(df) - 1)
        base_slice = slice(-lookback, None)

        base_close = close[base_slice]
        base_high = high[base_slice]
        base_low = low[base_slice]
        base_vol = volume[base_slice]
        base_dates = dates[-lookback:]

        # ── Step 2: Confirm we're in a base (price near recent high) ──────
        base_peak = float(np.max(base_high))
        base_trough = float(np.min(base_low))
        total_base_depth = (base_peak - base_trough) / base_peak

        # The base should not be too deep (> 50% is a stage 3/4 decline)
        if total_base_depth > 0.50:
            result.notes = f"Base too deep ({total_base_depth:.0%}) — likely not a valid base"
            return result

        # ── Step 3: Find swing highs and lows ────────────────────────────
        swing_highs, swing_lows = self._find_swing_points(
            base_close, base_high, base_low, window=5
        )

        if len(swing_highs) < self.cfg["min_contractions"]:
            result.notes = f"Only {len(swing_highs)} swing high(s) found — need {self.cfg['min_contractions']}+"
            return result

        # ── Step 4: Build contractions ────────────────────────────────────
        contractions = self._build_contractions(
            swing_highs, swing_lows, base_close, base_high, base_low,
            base_vol, base_dates
        )

        if len(contractions) < self.cfg["min_contractions"]:
            result.notes = f"Only {len(contractions)} valid contraction(s)"
            return result

        # ── Step 5: Verify contractions are shrinking ─────────────────────
        depths = [c.depth_pct for c in contractions]
        shrinking = all(
            depths[i] <= depths[i-1] * (1 + 0.15)  # allow 15% tolerance
            for i in range(1, len(depths))
        )

        strictly_shrinking = all(
            depths[i] < depths[i-1]
            for i in range(1, len(depths))
        )

        if not shrinking:
            result.notes = "Contractions not shrinking — not a valid VCP"
            return result

        # ── Step 6: Check volume drying up ────────────────────────────────
        vol_drying = self._check_volume_drying(contractions, base_vol)

        # ── Step 7: First contraction depth check ────────────────────────
        if depths[0] > self.cfg["max_first_contraction_pct"]:
            result.notes = (f"First contraction too deep ({depths[0]:.0%}) — "
                           f"max {self.cfg['max_first_contraction_pct']:.0%}")
            return result

        # ── Step 8: Last contraction (pivot area) ────────────────────────
        last_contraction = contractions[-1]
        tight_area = last_contraction.depth_pct <= self.cfg["max_last_contraction_pct"]

        pivot_price = last_contraction.high
        stop_price = last_contraction.low * 0.99  # 1% below the pivot low

        pct_from_pivot = (pivot_price - current_price) / pivot_price
        near_pivot = abs(pct_from_pivot) <= self.cfg["pivot_proximity_pct"]

        # ── Step 9: Compute pattern quality score ─────────────────────────
        quality = self._compute_quality(
            contractions=contractions,
            strictly_shrinking=strictly_shrinking,
            vol_drying=vol_drying,
            tight_area=tight_area,
            near_pivot=near_pivot,
            total_base_depth=total_base_depth,
        )

        # ── Populate result ───────────────────────────────────────────────
        result.detected = True
        result.num_contractions = len(contractions)
        result.contractions = [
            {
                "depth_pct": round(c.depth_pct * 100, 1),
                "high": round(c.high, 2),
                "low": round(c.low, 2),
            }
            for c in contractions
        ]
        result.base_start = base_dates[0]
        result.base_end = base_dates[-1]
        result.base_length_days = lookback
        result.pivot_price = pivot_price
        result.stop_price = stop_price
        result.pct_from_pivot = pct_from_pivot
        result.near_pivot = near_pivot
        result.volume_drying_up = vol_drying
        result.tight_area = tight_area
        result.pattern_quality = quality

        # Build notes
        depth_str = " → ".join(f"{d:.0%}" for d in depths)
        result.notes = (f"VCP: {len(contractions)}T | Contractions: {depth_str} | "
                       f"Pivot: ${pivot_price:.2f} | Stop: ${stop_price:.2f}")

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Swing Point Detection
    # ─────────────────────────────────────────────────────────────────────────

    def _find_swing_points(self, close: np.ndarray, high: np.ndarray,
                           low: np.ndarray, window: int = 5):
        """
        Find swing highs and lows using a rolling window approach.
        A swing high is a point where high[i] is the max in window[i-w:i+w].
        A swing low is a point where low[i] is the min in window[i-w:i+w].
        """
        n = len(close)
        swing_highs = []  # list of (index, price)
        swing_lows = []   # list of (index, price)

        for i in range(window, n - window):
            left = slice(i - window, i)
            right = slice(i + 1, i + window + 1)

            # Swing high
            if (high[i] >= np.max(high[left]) and
                    high[i] >= np.max(high[right])):
                swing_highs.append((i, float(high[i])))

            # Swing low
            if (low[i] <= np.min(low[left]) and
                    low[i] <= np.min(low[right])):
                swing_lows.append((i, float(low[i])))

        return swing_highs, swing_lows

    # ─────────────────────────────────────────────────────────────────────────
    # Contraction Building
    # ─────────────────────────────────────────────────────────────────────────

    def _build_contractions(self, swing_highs, swing_lows, close, high, low,
                            volume, dates) -> list[Contraction]:
        """
        Build a list of Contraction objects from swing highs and lows.
        Each contraction = from a swing high down to the next swing low.
        """
        contractions = []
        max_c = self.cfg["max_contractions"]

        # Pair each swing high with the subsequent swing low
        for sh_idx, sh_price in swing_highs[-max_c:]:
            # Find the first swing low AFTER this swing high
            subsequent_lows = [(idx, p) for idx, p in swing_lows if idx > sh_idx]
            if not subsequent_lows:
                continue
            sl_idx, sl_price = subsequent_lows[0]

            depth = (sh_price - sl_price) / sh_price
            if depth <= 0.01:  # Skip trivial moves
                continue

            # Average volume during this contraction
            vol_during = volume[sh_idx:sl_idx + 1]
            avg_vol = float(np.mean(vol_during)) if len(vol_during) > 0 else 0.0

            # Volume percentile vs entire base
            vol_pct = float(np.sum(volume <= avg_vol)) / len(volume) if len(volume) > 0 else 0.5

            c = Contraction(
                high=sh_price,
                low=sl_price,
                high_date=dates[min(sh_idx, len(dates) - 1)],
                low_date=dates[min(sl_idx, len(dates) - 1)],
                depth_pct=depth,
                avg_volume_during=avg_vol,
                volume_percentile=vol_pct,
            )
            contractions.append(c)

        return contractions

    # ─────────────────────────────────────────────────────────────────────────
    # Volume Analysis
    # ─────────────────────────────────────────────────────────────────────────

    def _check_volume_drying(self, contractions: list[Contraction],
                              base_vol: np.ndarray) -> bool:
        """
        Check if volume is drying up across contractions.
        Volume should be declining in successive contractions.
        """
        if len(contractions) < 2:
            return False

        vols = [c.avg_volume_during for c in contractions]
        # Volume should be declining (or at least not increasing) in successive contractions
        drying = all(vols[i] <= vols[i-1] * 1.1 for i in range(1, len(vols)))

        # Final contraction volume should be below the 40th percentile
        threshold = self.cfg["volume_dry_up_percentile"]
        final_vol_pct = contractions[-1].volume_percentile
        very_dry = final_vol_pct <= threshold

        return drying or very_dry

    # ─────────────────────────────────────────────────────────────────────────
    # Quality Scoring
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_quality(self, contractions, strictly_shrinking, vol_drying,
                         tight_area, near_pivot, total_base_depth) -> float:
        """
        Score VCP quality from 0-100.
        Higher = better pattern quality.
        """
        score = 50.0  # base score for having a valid VCP

        # Number of contractions (2-4 is ideal)
        n = len(contractions)
        if n == 2:
            score += 5
        elif n == 3:
            score += 10
        elif n >= 4:
            score += 8

        # Strictly shrinking contractions
        if strictly_shrinking:
            score += 15

        # Volume drying up
        if vol_drying:
            score += 15

        # Tight final area
        if tight_area:
            score += 10
            last_depth = contractions[-1].depth_pct
            if last_depth <= 0.05:  # extra bonus for very tight (<5%)
                score += 5

        # Near the pivot entry point
        if near_pivot:
            score += 10

        # Reasonable total base depth (shallower is better)
        if total_base_depth <= 0.20:
            score += 5
        elif total_base_depth <= 0.30:
            score += 3

        return min(100.0, score)
