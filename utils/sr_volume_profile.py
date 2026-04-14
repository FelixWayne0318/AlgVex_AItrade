"""
v4.0: S/R Volume Profile Calculator (Confirmation Layer)

Range Uniform Distribution volume profile using execution layer bars (24h lookback).
Independent data source from detection layer (1D/4H swing points).
v18.2: Migrated from 15M to 30M bars (48 bars = 24h).

Produces VPOC (Volume Point of Control), VAH (Value Area High), VAL (Value Area Low).

Reference: CME Market Profile, SHS (2021) — VPOC 90% reaction rate (WIG20)
"""

import logging
from typing import Dict, List, Optional, Any

from utils.sr_types import SRCandidate, SRLevel, SRSourceType


logger = logging.getLogger(__name__)


def calculate_volume_profile(
    bars: List[Dict[str, Any]],
    current_price: float,
    value_area_pct: int = 70,
    min_bins: int = 30,
    max_bins: int = 80,
) -> List[SRCandidate]:
    """
    Calculate Volume Profile using Range Uniform Distribution.

    Algorithm: For each bar, distribute its volume proportionally across price bins
    based on the overlap between the bar's H-L range and each bin's range.
    This avoids the close-only bias of simple volume profiling.

    Parameters
    ----------
    bars : List[Dict]
        Execution layer bars (30M: ~48 bars = 24h). Each must have 'high', 'low', 'close', 'volume'.
    current_price : float
        Current market price.
    value_area_pct : int
        Value Area percentage (standard: 70%).
    min_bins : int
        Minimum number of price bins.
    max_bins : int
        Maximum number of price bins.

    Returns
    -------
    List[SRCandidate]
        VPOC, VAH, VAL candidates.
    """
    if not bars or len(bars) < 10:
        return []

    try:
        # Collect all highs and lows to determine price range
        highs = [float(b.get('high', 0)) for b in bars if float(b.get('high', 0)) > 0]
        lows = [float(b.get('low', 0)) for b in bars if float(b.get('low', 0)) > 0]

        if not highs or not lows:
            return []

        price_high = max(highs)
        price_low = min(lows)
        price_range = price_high - price_low

        if price_range <= 0:
            return []

        # Determine number of bins
        num_bins = max(min_bins, min(max_bins, int(price_range / (current_price * 0.001))))
        bin_size = price_range / num_bins

        # Create bins
        bin_edges = [price_low + i * bin_size for i in range(num_bins + 1)]
        vol_bins = [0.0] * num_bins

        # Distribute volume using Range Uniform Distribution
        for bar in bars:
            high = float(bar.get('high', 0))
            low = float(bar.get('low', 0))
            volume = float(bar.get('volume', 0))

            if high <= 0 or low <= 0 or volume <= 0:
                continue

            bar_range = high - low

            for j in range(num_bins):
                b_low = bin_edges[j]
                b_high = bin_edges[j + 1]

                # Check overlap
                if low <= b_high and high >= b_low:
                    if bar_range > 0:
                        overlap = (min(high, b_high) - max(low, b_low)) / bar_range
                    else:
                        overlap = 1.0  # Doji bar
                    vol_bins[j] += volume * max(0, overlap)

        total_volume = sum(vol_bins)
        if total_volume <= 0:
            return []

        # Find VPOC (bin with highest volume)
        vpoc_idx = vol_bins.index(max(vol_bins))
        vpoc_price = (bin_edges[vpoc_idx] + bin_edges[vpoc_idx + 1]) / 2

        # Calculate Value Area (VAH, VAL)
        # Sort bins by volume (descending), accumulate until value_area_pct reached
        sorted_bins = sorted(range(num_bins), key=lambda i: vol_bins[i], reverse=True)
        va_volume_target = total_volume * (value_area_pct / 100.0)
        va_volume = 0.0
        va_bins = set()

        for idx in sorted_bins:
            va_bins.add(idx)
            va_volume += vol_bins[idx]
            if va_volume >= va_volume_target:
                break

        # VAH = highest price in value area, VAL = lowest price in value area
        va_indices = sorted(va_bins)
        vah_price = bin_edges[va_indices[-1] + 1]  # Upper edge of highest VA bin
        val_price = bin_edges[va_indices[0]]  # Lower edge of lowest VA bin

        # Build candidates
        candidates = []

        # VPOC — most traded price level
        vpoc_side = 'support' if vpoc_price < current_price else 'resistance'
        candidates.append(SRCandidate(
            price=round(vpoc_price, 2),
            source='VP_VPOC',
            weight=1.3,
            side=vpoc_side,
            extra={'total_bins': num_bins, 'vpoc_volume_pct': (vol_bins[vpoc_idx] / total_volume) * 100},
            level=SRLevel.INTERMEDIATE,
            source_type=SRSourceType.STRUCTURAL,
            timeframe="30m_vp",
        ))

        # VAH — upper edge of value area (resistance)
        if vah_price > current_price:
            candidates.append(SRCandidate(
                price=round(vah_price, 2),
                source='VP_VAH',
                weight=1.0,
                side='resistance',
                level=SRLevel.INTERMEDIATE,
                source_type=SRSourceType.STRUCTURAL,
                timeframe="30m_vp",
            ))

        # VAL — lower edge of value area (support)
        if val_price < current_price:
            candidates.append(SRCandidate(
                price=round(val_price, 2),
                source='VP_VAL',
                weight=1.0,
                side='support',
                level=SRLevel.INTERMEDIATE,
                source_type=SRSourceType.STRUCTURAL,
                timeframe="30m_vp",
            ))

        return candidates

    except Exception as e:
        logger.warning(f"Volume Profile calculation failed: {e}")
        return []
