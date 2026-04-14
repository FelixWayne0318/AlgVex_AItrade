"""
v4.0: S/R Swing Point Detector (Detection Layer)

Multi-timeframe swing detection with volume-weighted scoring.
Extracts Williams Fractal swing highs/lows from OHLCV bars,
applies Spitsin (2025) percentile-based continuous volume weighting.

Reference: Spitsin et al. (2025) Contemporary Mathematics 6(6)
  - Without volume confirmation: P = 0.70
  - With volume confirmation:    P = 0.81-0.88

Usage:
    detector = SwingDetector(left_bars=5, right_bars=5, max_age=100)
    candidates = detector.detect(bars_data, current_price, timeframe="4h",
                                  base_weight=1.5, level=SRLevel.INTERMEDIATE)
"""

import logging
from typing import Dict, List, Optional, Any

from utils.sr_types import SRCandidate, SRLevel, SRSourceType


logger = logging.getLogger(__name__)


def _volume_weight_factor(bar_volume: float, all_volumes: List[float]) -> float:
    """
    Percentile-based continuous volume scaling (Spitsin 2025 spirit).

    Advantages:
    - Continuous function, not binary
    - Percentile naturally normalizes across 1D/4H/30M
    - No new parameters (30%/70% ≈ ±0.5 std dev)
    - Low-volume swings not discarded (floor 0.3)

    Parameters
    ----------
    bar_volume : float
        Volume of the swing bar.
    all_volumes : List[float]
        All bar volumes in the lookback window.

    Returns
    -------
    float
        Volume weight factor [0.3, 1.0].
    """
    if not all_volumes or bar_volume <= 0:
        return 0.5  # No data → neutral

    # Percentile rank
    rank = sum(1 for v in all_volumes if v <= bar_volume) / len(all_volumes)

    # Three-tier continuous weighting
    if rank >= 0.7:       # Top 30% high volume
        return 1.0
    elif rank >= 0.3:     # Middle 40% (30th-70th percentile)
        return 0.5 + (rank - 0.3) * 1.25   # 0.5 → 1.0 linear
    else:                 # Bottom 30% low volume
        return 0.3        # Floor


def detect_swing_points(
    bars_data: List[Dict[str, Any]],
    current_price: float,
    timeframe: str = "15m",
    base_weight: float = 0.8,
    level: str = SRLevel.MINOR,
    left_bars: int = 5,
    right_bars: int = 5,
    max_age: int = 100,
    volume_weighting: bool = True,
) -> List[SRCandidate]:
    """
    Detect swing highs/lows using Williams Fractal with volume weighting.

    Parameters
    ----------
    bars_data : List[Dict]
        OHLCV bars. Each must have 'high', 'low', 'close', and optionally 'volume'.
    current_price : float
        Current market price for support/resistance classification.
    timeframe : str
        Timeframe label for same-source weight capping ("1d", "4h", "30m").
    base_weight : float
        Base weight for candidates (1D=2.0, 4H=1.5, 30M=0.8).
    level : str
        SRLevel for candidates (1D=MAJOR, 4H=INTERMEDIATE, 30M=MINOR).
    left_bars : int
        Number of bars to the left for fractal detection.
    right_bars : int
        Number of bars to the right for fractal detection.
    max_age : int
        Maximum lookback bars.
    volume_weighting : bool
        Enable Spitsin (2025) percentile volume weighting.

    Returns
    -------
    List[SRCandidate]
        Detected swing point candidates with volume-adjusted weights.
    """
    candidates = []
    if not bars_data:
        return candidates

    # Limit to max_age bars
    bars = bars_data[-max_age:] if len(bars_data) > max_age else bars_data
    n = len(bars)
    min_bars_needed = left_bars + 1 + right_bars

    if n < min_bars_needed:
        return candidates

    # Pre-collect all volumes for percentile calculation
    all_volumes = []
    if volume_weighting:
        all_volumes = [
            float(b.get('volume', 0))
            for b in bars
            if float(b.get('volume', 0)) > 0
        ]

    for i in range(left_bars, n - right_bars):
        bar = bars[i]
        bar_high = float(bar.get('high', 0))
        bar_low = float(bar.get('low', 0))
        bar_volume = float(bar.get('volume', 0))

        if bar_high <= 0 or bar_low <= 0:
            continue

        # Check swing high: bar[i].high >= all bars in [i-left, i+right]
        is_swing_high = True
        for j in range(i - left_bars, i + right_bars + 1):
            if j == i:
                continue
            if float(bars[j].get('high', 0)) > bar_high:
                is_swing_high = False
                break

        # Check swing low: bar[i].low <= all bars in [i-left, i+right]
        is_swing_low = True
        for j in range(i - left_bars, i + right_bars + 1):
            if j == i:
                continue
            if float(bars[j].get('low', 0)) < bar_low:
                is_swing_low = False
                break

        if not is_swing_high and not is_swing_low:
            continue

        # Age weighting: more recent swings are more relevant
        bars_ago = n - 1 - i
        age_factor = max(0.5, 1.0 - (bars_ago / max_age) * 0.5)

        # Volume weighting: Spitsin (2025) percentile continuous scaling
        vol_factor = 1.0
        if volume_weighting and all_volumes:
            vol_factor = _volume_weight_factor(bar_volume, all_volumes)

        # Final weight = base × age × volume
        final_weight = base_weight * age_factor * vol_factor

        if is_swing_high:
            # S/R Flip: broken resistance becomes support
            if bar_high >= current_price:
                side = 'resistance'
            else:
                side = 'support'
            candidates.append(SRCandidate(
                price=bar_high,
                source=f"Swing_High_{timeframe.upper()}",
                weight=final_weight,
                side=side,
                extra={
                    'bar_index': i,
                    'bars_ago': bars_ago,
                    'age_factor': age_factor,
                    'vol_factor': vol_factor,
                    'volume': bar_volume,
                },
                level=level,
                source_type=SRSourceType.STRUCTURAL,
                timeframe=timeframe,
            ))

        if is_swing_low:
            # S/R Flip: broken support becomes resistance
            if bar_low <= current_price:
                side = 'support'
            else:
                side = 'resistance'
            candidates.append(SRCandidate(
                price=bar_low,
                source=f"Swing_Low_{timeframe.upper()}",
                weight=final_weight,
                side=side,
                extra={
                    'bar_index': i,
                    'bars_ago': bars_ago,
                    'age_factor': age_factor,
                    'vol_factor': vol_factor,
                    'volume': bar_volume,
                },
                level=level,
                source_type=SRSourceType.STRUCTURAL,
                timeframe=timeframe,
            ))

    logger.debug(
        f"Swing detection ({timeframe}): found {len(candidates)} points from {n} bars"
        + (f" (vol_weighted)" if volume_weighting else "")
    )
    return candidates
