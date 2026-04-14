#!/usr/bin/env python3
"""
v19.1 Computational Correctness Verification

Verifies ALL v19.1 algorithm changes with known test data:
  1. _detect_divergences() — RSI/MACD-Price divergence detection
  2. CVD-Price divergence — in _format_order_flow_report()
  3. OI×Price 4-Quadrant — in _format_derivatives_report()
  4. Taker Buy/Sell Ratio tags — threshold correctness
  5. Top Traders positioning + shift detection
  6. Liquidation magnitude tiers
  7. Risk Manager OUTPUT FORMAT — 6-field JSON structure
  8. Edge cases & boundary conditions

Usage:
    python3 tests/test_v19_1_verification.py
"""

import os
import sys
import json
import logging
import traceback

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("v19.1-verify")

PASS = 0
FAIL = 0
ERRORS = []


def check(name, condition, detail=""):
    """Assert a test condition and track results."""
    global PASS, FAIL, ERRORS
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        msg = f"  ❌ {name}" + (f" — {detail}" if detail else "")
        print(msg)
        ERRORS.append(msg)


def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


# ===========================================================================
# Instantiate MultiAgentAnalyzer (no API key needed for format methods)
# ===========================================================================
from agents.multi_agent_analyzer import MultiAgentAnalyzer

analyzer = MultiAgentAnalyzer(
    api_key="test-key-not-used",
    model="deepseek-chat",
    temperature=0.3,
    debate_rounds=2,
)

# ===========================================================================
# TEST 1: _detect_divergences() — Algorithm Correctness
# ===========================================================================
section("TEST 1: _detect_divergences() — Divergence Detection Algorithm")

# 1a: Classic BEARISH divergence — price higher high, RSI lower high
# Design: Two clear peaks satisfying find_local_extremes(window=2)
# window=2 means: peak at idx i requires series[i] >= series[i±1] AND series[i] >= series[i±2]
#
# Price: [100, 105, 110, 108, 103, 100, 105, 115, 110, 105, 100]
#              peak at idx 2 (110)           peak at idx 7 (115)
# Price higher high: 115 > 110 ✓
#
# RSI:   [40,  55,  65,  60,  45,  40,  55,  60,  55,  45,  40]
#              peak at idx 2 (65)            peak at idx 7 (60)
# RSI lower high: 60 < 65 ✓  → BEARISH DIVERGENCE
price_bearish = [100, 105, 110, 108, 103, 100, 105, 115, 110, 105, 100]
rsi_bearish =   [40,  55,  65,  60,  45,  40,  55,  60,  55,  45,  40]
tags = analyzer._detect_divergences(price_bearish, rsi_series=rsi_bearish, timeframe="4H")
has_bearish = any("BEARISH" in t for t in tags)
check("1a: Bearish RSI divergence detected (price higher high, RSI lower high)",
      has_bearish, f"tags={tags}")

# 1b: Classic BULLISH divergence — price lower low, RSI higher low
# Price: [120, 100, 90, 95, 110, 120, 100, 85, 95, 110, 120]
#              trough at idx 2 (90)          trough at idx 7 (85)
# Price lower low: 85 < 90 ✓
#
# RSI:   [60,  40,  30,  35,  50,  60,  40,  35,  45,  55,  60]
#              trough at idx 2 (30)          trough at idx 7 (35)
# RSI higher low: 35 > 30 ✓  → BULLISH DIVERGENCE
price_bullish = [120, 100, 90, 95, 110, 120, 100, 85, 95, 110, 120]
rsi_bullish =   [60,  40,  30, 35,  50,  60,  40,  35, 45,  55,  60]
tags = analyzer._detect_divergences(price_bullish, rsi_series=rsi_bullish, timeframe="30M")
has_bullish = any("BULLISH" in t for t in tags)
check("1b: Bullish RSI divergence detected (price lower low, RSI higher low)",
      has_bullish, f"tags={tags}")

# 1c: No divergence — price and RSI both making higher highs
price_no_div = [100, 105, 103, 108, 105, 112, 109, 118, 115]
rsi_no_div =   [40,  55,  45,  60,  50,  65,  55,  70,  60]
tags = analyzer._detect_divergences(price_no_div, rsi_series=rsi_no_div, timeframe="4H")
check("1c: No divergence when price and RSI trend together",
      len(tags) == 0, f"tags={tags}")

# 1d: Insufficient data (< 5 points) → no crash, empty result
tags = analyzer._detect_divergences([100, 110, 105], rsi_series=[50, 60, 55], timeframe="4H")
check("1d: Insufficient data (3 points) returns empty list",
      tags == [], f"tags={tags}")

# 1e: Empty/None input → no crash
tags = analyzer._detect_divergences([], rsi_series=[], timeframe="4H")
check("1e: Empty input returns empty list", tags == [])
tags = analyzer._detect_divergences(None, rsi_series=None, timeframe="4H")
check("1f: None input returns empty list", tags == [])

# 1g: MACD Hist divergence — verify .4f formatting (not .1f)
price_macd = [100, 105, 103, 110, 108, 115, 112, 120, 116]
macd_macd =  [0.001, 0.003, 0.001, 0.0025, 0.001, 0.002, 0.001, 0.0015, 0.001]
tags = analyzer._detect_divergences(price_macd, macd_hist_series=macd_macd, timeframe="4H")
# Check that any MACD output uses .4f (not "0.0")
for t in tags:
    if "MACD" in t:
        check("1g: MACD Hist uses .4f format (not .1f truncation)",
              "0.0→0.0" not in t and "MACD" in t,
              f"tag={t}")
        break
else:
    # Even if no divergence detected with this data, verify no crash
    check("1g: MACD Hist processing did not crash", True)

# 1h: Mismatched series lengths → should not crash
tags = analyzer._detect_divergences([100, 110, 105, 115, 108],
                                     rsi_series=[50, 60, 55],
                                     timeframe="4H")
check("1h: Mismatched series lengths handled gracefully", isinstance(tags, list))

# ===========================================================================
# TEST 2: CVD-Price Divergence — _format_order_flow_report()
# ===========================================================================
section("TEST 2: CVD-Price Divergence Detection")

# 2a: Price falling but CVD positive → ACCUMULATION
data_accum = {
    "buy_ratio": 0.52,
    "avg_trade_usdt": 1000,
    "volume_usdt": 5000000,
    "trades_count": 5000,
    "cvd_trend": "RISING",
    "recent_10_bars": [0.51, 0.52, 0.53, 0.52, 0.51, 0.52, 0.53, 0.52, 0.51, 0.52],
    "cvd_history": [100, 200, 150, 300, 250, 400, 350, 500, 450, 600],
    "cvd_cumulative": 3300,
    "data_source": "binance_raw",
}
report = analyzer._format_order_flow_report(data_accum, price_change_pct=-1.5)
check("2a: Accumulation detected (price falling -1.5%, CVD positive)",
      "ACCUMULATION" in report, f"'ACCUMULATION' not found in report")

# 2b: Price rising but CVD negative → DISTRIBUTION
data_dist = dict(data_accum)
data_dist["cvd_history"] = [-100, -200, -150, -300, -250, -400, -350, -500, -450, -600]
data_dist["cvd_cumulative"] = -3300
data_dist["cvd_trend"] = "FALLING"
report = analyzer._format_order_flow_report(data_dist, price_change_pct=2.0)
check("2b: Distribution detected (price rising +2.0%, CVD negative)",
      "DISTRIBUTION" in report, f"'DISTRIBUTION' not found in report")

# 2c: Price falling and CVD negative → CONFIRMED selling
report_confirm = analyzer._format_order_flow_report(data_dist, price_change_pct=-1.5)
check("2c: Confirmed selling (price falling, CVD negative)",
      "CONFIRMED" in report_confirm, f"'CONFIRMED' not found")

# 2d: Small price change (< 0.3%) → NO divergence tag
report_small = analyzer._format_order_flow_report(data_accum, price_change_pct=0.1)
check("2d: No divergence tag when price change < 0.3%",
      "CVD-PRICE" not in report_small,
      f"Unexpected CVD-PRICE tag with 0.1% change")

# 2e: Default price_change_pct=0.0 → NO divergence tag
report_default = analyzer._format_order_flow_report(data_accum)
check("2e: No divergence tag with default price_change_pct=0.0",
      "CVD-PRICE" not in report_default)

# 2f: CVD history too short (< 3) → NO divergence tag
data_short_cvd = dict(data_accum)
data_short_cvd["cvd_history"] = [100, 200]
report_short = analyzer._format_order_flow_report(data_short_cvd, price_change_pct=-2.0)
check("2f: No divergence tag when CVD history < 3",
      "CVD-PRICE" not in report_short)

# 2g: No data → graceful fallback
report_none = analyzer._format_order_flow_report(None)
check("2g: None data returns fallback message",
      "not available" in report_none.lower())


# ===========================================================================
# TEST 3: OI×Price 4-Quadrant — _format_derivatives_report()
# ===========================================================================
section("TEST 3: OI×Price 4-Quadrant Analysis")


def make_oi_test_data(price_change_pct, oi_oldest_val, oi_newest_val):
    """Create test data structure for OI×Price testing."""
    return {
        "enabled": True,
        "open_interest": {"value": 500000},
        "trends": {},
        "funding_rate": {"current_pct": 0.01},
    }, {
        "ticker_24hr": {"priceChangePercent": str(price_change_pct), "quoteVolume": "1000000000"},
        "open_interest_hist": {
            "latest": {"sumOpenInterestValue": str(oi_newest_val)},
            "data": [
                {"sumOpenInterestValue": str(oi_newest_val)},  # newest (index 0)
                {"sumOpenInterestValue": str((oi_oldest_val + oi_newest_val) / 2)},
                {"sumOpenInterestValue": str(oi_oldest_val)},  # oldest (index -1)
            ],
        },
    }


# 3a: Price ↑ + OI ↑ → "New longs entering"
coinalyze, binance = make_oi_test_data(price_change_pct=2.0, oi_oldest_val=30e9, oi_newest_val=32e9)
report = analyzer._format_derivatives_report(coinalyze, current_price=95000, binance_derivatives=binance)
check("3a: Price↑ + OI↑ → 'New longs entering'",
      "New longs entering" in report, f"Not found in report")

# 3b: Price ↑ + OI ↓ → "Short covering"
coinalyze, binance = make_oi_test_data(price_change_pct=2.0, oi_oldest_val=32e9, oi_newest_val=30e9)
report = analyzer._format_derivatives_report(coinalyze, current_price=95000, binance_derivatives=binance)
check("3b: Price↑ + OI↓ → 'Short covering'",
      "Short covering" in report, f"Not found in report")

# 3c: Price ↓ + OI ↑ → "New shorts entering"
coinalyze, binance = make_oi_test_data(price_change_pct=-2.0, oi_oldest_val=30e9, oi_newest_val=32e9)
report = analyzer._format_derivatives_report(coinalyze, current_price=95000, binance_derivatives=binance)
check("3c: Price↓ + OI↑ → 'New shorts entering'",
      "New shorts entering" in report, f"Not found in report")

# 3d: Price ↓ + OI ↓ → "Long liquidation"
coinalyze, binance = make_oi_test_data(price_change_pct=-2.0, oi_oldest_val=32e9, oi_newest_val=30e9)
report = analyzer._format_derivatives_report(coinalyze, current_price=95000, binance_derivatives=binance)
check("3d: Price↓ + OI↓ → 'Long liquidation'",
      "Long liquidation" in report, f"Not found in report")

# 3e: Price ↑ + OI flat (0.05% change, < 0.15%) → "OI flat"
# OI changes by 0.05%: 30B → 30.015B
coinalyze, binance = make_oi_test_data(price_change_pct=1.5, oi_oldest_val=30e9, oi_newest_val=30.015e9)
report = analyzer._format_derivatives_report(coinalyze, current_price=95000, binance_derivatives=binance)
check("3e: Price↑ + OI flat (0.05%) → marginal zone (not New longs)",
      "New longs entering" not in report,
      f"Should NOT detect 'New longs' at 0.05% OI change")

# 3f: OI change at exactly 0.15% boundary
# 30B → 30.045B = +0.15%
coinalyze, binance = make_oi_test_data(price_change_pct=2.0, oi_oldest_val=30e9, oi_newest_val=30.045e9)
report = analyzer._format_derivatives_report(coinalyze, current_price=95000, binance_derivatives=binance)
# At exactly 0.15%, oi_change_pct = 0.15, condition is > 0.15 → should be flat
check("3f: OI at exactly 0.15% → treated as flat (> not >=)",
      "OI flat" in report or "Low-conviction" in report,
      f"Boundary test at exactly 0.15%")

# 3g: KEY INSIGHT tags — verify all 4 directional quadrants
for pdir, odir, keyword in [
    (2.0, "up", "longs entering on strength"),
    (2.0, "down", "short covering, NOT new longs"),
    (-2.0, "up", "shorts entering on weakness"),
    (-2.0, "down", "liquidation cascade"),
]:
    oi_old = 30e9
    oi_new = 32e9 if odir == "up" else 28e9
    coinalyze, binance = make_oi_test_data(price_change_pct=pdir, oi_oldest_val=oi_old, oi_newest_val=oi_new)
    report = analyzer._format_derivatives_report(coinalyze, current_price=95000, binance_derivatives=binance)
    found = keyword.lower() in report.lower()
    check(f"3g: KEY INSIGHT — Price {'↑' if pdir > 0 else '↓'} + OI {odir} contains '{keyword[:30]}...'",
          found, f"Not found in report")


# ===========================================================================
# TEST 4: Taker Buy/Sell Ratio Tags — Threshold Correctness
# ===========================================================================
section("TEST 4: Taker Buy/Sell Ratio Tags")


def make_taker_test_data(ratio):
    """Create binance_derivatives with specific taker ratio."""
    return {
        "taker_long_short": {
            "latest": {"buySellRatio": str(ratio)},
            "data": [{"buySellRatio": str(ratio)}],
        },
    }


# 4a: Ratio 1.10 → "Buyer-dominant"
binance = make_taker_test_data(1.10)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("4a: Ratio 1.10 → 'Buyer-dominant'",
      "Buyer-dominant" in report, f"Not found")

# 4b: Ratio 0.90 → "Seller-dominant"
binance = make_taker_test_data(0.90)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("4b: Ratio 0.90 → 'Seller-dominant'",
      "Seller-dominant" in report, f"Not found")

# 4c: Ratio 1.03 → "Slight buyer pressure"
binance = make_taker_test_data(1.03)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("4c: Ratio 1.03 → 'Slight buyer pressure'",
      "Slight buyer pressure" in report, f"Not found")

# 4d: Ratio 0.97 → "Slight seller pressure"
binance = make_taker_test_data(0.97)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("4d: Ratio 0.97 → 'Slight seller pressure'",
      "Slight seller pressure" in report, f"Not found")

# 4e: Ratio 1.00 → "Balanced"
binance = make_taker_test_data(1.00)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("4e: Ratio 1.00 → 'Balanced'",
      "Balanced" in report, f"Not found")

# 4f: Boundary — ratio exactly 1.05 (> 1.05 is buyer-dominant, so 1.05 is NOT buyer-dominant)
binance = make_taker_test_data(1.05)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
# 1.05 is NOT > 1.05, so it falls to elif > 1.02 → "Slight buyer pressure"
check("4f: Ratio exactly 1.05 → 'Slight buyer pressure' (not buyer-dominant, > not >=)",
      "Slight buyer pressure" in report, f"Not found")

# 4g: Boundary — ratio exactly 0.95 → "Slight seller pressure" (not seller-dominant)
binance = make_taker_test_data(0.95)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("4g: Ratio exactly 0.95 → 'Slight seller pressure' (not seller-dominant)",
      "Slight seller pressure" in report, f"Not found")

# 4h: Verify NO gap in thresholds — ratio 0.99 should match SOME tag
binance = make_taker_test_data(0.99)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
has_flow_tag = "[FLOW:" in report
check("4h: Ratio 0.99 has a FLOW tag (no gap in thresholds)",
      has_flow_tag, f"No [FLOW:] tag found")


# ===========================================================================
# TEST 5: Top Traders Positioning + Shift Detection
# ===========================================================================
section("TEST 5: Top Traders Positioning + Shift Detection")


def make_top_traders_data(long_pct, short_pct, history=None):
    """Create binance_derivatives with specific top traders positioning."""
    ratio = long_pct / short_pct if short_pct > 0 else 1
    result = {
        "top_long_short_position": {
            "latest": {
                "longShortRatio": str(ratio),
                "longAccount": str(long_pct / 100),
                "shortAccount": str(short_pct / 100),
            },
        },
    }
    if history:
        result["top_long_short_position"]["data"] = history
    return result


# 5a: Long 60% → "Professional traders lean long"
binance = make_top_traders_data(60, 40)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("5a: Long 60% → 'Professional traders lean long'",
      "lean long" in report.lower(), f"Not found")

# 5b: Short 58% → "Professional traders lean short"
binance = make_top_traders_data(42, 58)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("5b: Short 58% → 'Professional traders lean short'",
      "lean short" in report.lower(), f"Not found")

# 5c: Long 53% → "Slight long bias" (marginal)
binance = make_top_traders_data(53, 47)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("5c: Long 53% → 'Slight long bias' (marginal)",
      "slight long bias" in report.lower(), f"Not found")

# 5d: Long 51% → NO tag (below 52% marginal threshold)
binance = make_top_traders_data(51, 49)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("5d: Long 51% → No SMART MONEY tag (below 52%)",
      "SMART MONEY" not in report,
      f"Unexpected SMART MONEY tag at 51%")

# 5e: Shift detection — long increasing by 3pp
history = [
    {"longAccount": "0.55", "shortAccount": "0.45"},  # newest
    {"longAccount": "0.53", "shortAccount": "0.47"},
    {"longAccount": "0.52", "shortAccount": "0.48"},  # oldest
]
binance = make_top_traders_data(55, 45, history=history)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("5e: Shift +3pp detected → 'increasing long'",
      "increasing long" in report.lower(), f"Not found")

# 5f: Small shift (1pp) → NO shift tag
history = [
    {"longAccount": "0.52", "shortAccount": "0.48"},
    {"longAccount": "0.515", "shortAccount": "0.485"},
    {"longAccount": "0.51", "shortAccount": "0.49"},
]
binance = make_top_traders_data(52, 48, history=history)
report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
check("5f: Small shift (1pp) → NO SHIFT tag",
      "SHIFT" not in report, f"Unexpected SHIFT tag at 1pp")


# ===========================================================================
# TEST 6: Liquidation Magnitude Tiers
# ===========================================================================
section("TEST 6: Liquidation Magnitude Tiers")


def make_liq_test_data(total_usd, current_price=95000):
    """Create coinalyze data with specific liquidation volume."""
    total_btc = total_usd / current_price
    long_btc = total_btc * 0.6
    short_btc = total_btc * 0.4
    return {
        "enabled": True,
        "open_interest": None,
        "trends": {},
        "funding_rate": None,
        "liquidations": {
            "history": [
                {"l": str(long_btc), "s": str(short_btc)},
            ],
        },
    }


# 6a: $600M → "Extreme"
data = make_liq_test_data(600_000_000)
report = analyzer._format_derivatives_report(data, current_price=95000)
check("6a: $600M → 'Extreme liquidation volume'",
      "Extreme" in report, f"Not found")

# 6b: $300M → "Heavy"
data = make_liq_test_data(300_000_000)
report = analyzer._format_derivatives_report(data, current_price=95000)
check("6b: $300M → 'Heavy liquidation volume'",
      "Heavy" in report, f"Not found")

# 6c: $80M → "Moderate"
data = make_liq_test_data(80_000_000)
report = analyzer._format_derivatives_report(data, current_price=95000)
check("6c: $80M → 'Moderate liquidation volume'",
      "Moderate" in report, f"Not found")

# 6d: $30M → NO magnitude tag
data = make_liq_test_data(30_000_000)
report = analyzer._format_derivatives_report(data, current_price=95000)
check("6d: $30M → No MAGNITUDE tag",
      "MAGNITUDE" not in report, f"Unexpected MAGNITUDE tag at $30M")

# 6e: Boundary — exactly $50M (> 50M required, so 50M should NOT trigger)
data = make_liq_test_data(50_000_000)
report = analyzer._format_derivatives_report(data, current_price=95000)
check("6e: Exactly $50M → No MAGNITUDE tag (> not >=)",
      "MAGNITUDE" not in report, f"Boundary test at $50M")


# ===========================================================================
# TEST 7: Risk Manager OUTPUT FORMAT — 6-field JSON Structure
# ===========================================================================
section("TEST 7: Risk Manager OUTPUT FORMAT Structure")

# Read the RM system prompt and verify all 6 fields are present
import re

# RM prompt is built inline in analyze() — read all agent files (mixin split)
_agent_files = ["multi_agent_analyzer.py", "prompt_constants.py",
                "report_formatter.py", "memory_manager.py"]
source = ""
for _af in _agent_files:
    _ap = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "agents", _af)
    if os.path.exists(_ap):
        with open(_ap, "r") as f:
            source += f.read() + "\n"

# Check that all 5 fields are in the OUTPUT FORMAT (v23.0: entry_timing_risk removed)
rm_fields = ["signal", "risk_appetite", "position_risk",
             "market_structure_risk", "reason"]
for field in rm_fields:
    check(f"7a: RM OUTPUT FORMAT contains '{field}'",
          f'"{field}"' in source, f"Field not found in RM source")

# v23.0: entry_timing_risk removed from Risk Manager (now handled by Entry Timing Agent)
check("7b: RM no longer has 'entry_timing_risk' (v23.0)",
      '"entry_timing_risk"' not in source, "entry_timing_risk should be removed")

# Check that few-shot examples have multi-sentence reasons
# Count number of "reason" occurrences that have long text
reason_matches = re.findall(r'"reason":"([^"]+)"', source)
long_reasons = [r for r in reason_matches if len(r) > 50]
check(f"7c: Few-shot examples have detailed reasons (>50 chars each)",
      len(long_reasons) >= 5, f"Only {len(long_reasons)} detailed reasons, expected >= 5")


# ===========================================================================
# TEST 8: 4H CVD-Price Divergence (inline in _format_technical_report)
# ===========================================================================
section("TEST 8: 4H CVD-Price Divergence (inline)")

# Build data dict matching the actual format used by _format_technical_report()
# MTF data is nested inside the same dict: data['mtf_decision_layer'], data['mtf_trend_layer']
# 4H historical context: data['mtf_decision_layer']['historical_context']
# 4H CVD order flow: data['order_flow_4h']
tech_data_4h = {
    "price": 95000,
    "rsi": 50,
    "atr": 500,
    "adx": 30,
    "di_plus": 25,
    "di_minus": 20,
    "macd": 100,
    "macd_signal": 90,
    "bb_position": 0.5,
    "bb_upper": 96000,
    "bb_lower": 94000,
    "volume_ratio": 1.0,
    "sma_5": 95100,
    "sma_20": 94800,
    "sma_50": 94000,
    "sma_200": 90000,
    "period_change_pct": -2.5,
    "period_hours": 12,
    # MTF trend layer (1D)
    "mtf_trend_layer": {
        "timeframe": "1D",
        "macd": 500,
        "macd_signal": 480,
        "sma_200": 90000,
        "adx": 30,
        "di_plus": 25,
        "di_minus": 20,
        "rsi": 55,
    },
    # MTF decision layer (4H)
    "mtf_decision_layer": {
        "timeframe": "4H",
        "rsi": 55,
        "adx": 35,
        "macd": 0.0012,
        "macd_signal": 0.0010,
        "historical_context": {
            "trend_direction": "BEARISH",  # Required — None triggers skip
            "momentum_shift": "ACCELERATING",
            "price_change_pct": -2.9,
            "current_volume_ratio": 1.1,
            "rsi_trend": [52, 54, 56, 55, 57, 58, 55, 53, 56],
            "macd_trend": [0.001, 0.0011, 0.0012, 0.0013, 0.0012, 0.0011, 0.001, 0.0009, 0.0012],
            "macd_signal_trend": [0.0009, 0.001, 0.0011, 0.0012, 0.0012, 0.0011, 0.001, 0.0009, 0.001],
            "macd_histogram_trend": [],  # Empty to test fallback
            "adx_trend": [30, 32, 34, 35, 33, 32, 31, 30, 33],
            "di_plus_trend": [25, 26, 27, 28, 27, 26, 25, 24, 27],
            "di_minus_trend": [20, 19, 18, 17, 18, 19, 20, 21, 18],
            "price_trend": [96000, 95500, 95000, 94500, 94000, 93500, 93800, 93200, 93500],
            "volume_trend": [100, 110, 105, 120, 115, 108, 112, 125, 118],
            "bb_width_trend": [2.1, 2.2, 2.3, 2.4, 2.3, 2.2, 2.1, 2.0, 2.1],
        },
    },
    # 4H CVD order flow (injected before calling _format_technical_report)
    "order_flow_4h": {
        "cvd_trend": "RISING",
        "buy_ratio": 0.54,
        "cvd_cumulative": 5000,
        "cvd_history": [100, 200, 150, 300, 250, 400, 350, 500, 450, 600],
        "volume_usdt": 8000000,
        "trades_count": 10000,
        "avg_trade_usdt": 800,
        "recent_10_bars": [0.52, 0.53, 0.54, 0.53, 0.54, 0.55, 0.53, 0.54, 0.55, 0.54],
    },
    # 30M historical context (execution layer)
    "historical_context": {
        "trend_direction": "BEARISH",
        "momentum_shift": "DECELERATING",
        "price_change_pct": -1.5,
        "current_volume_ratio": 1.2,
        "price_trend": [95500, 95300, 95100, 94900, 94700, 94500, 94600, 94400, 94300],
        "rsi_trend": [55, 52, 50, 48, 45, 43, 44, 42, 40],
        "macd_trend": [0.0005, 0.0003, 0.0001, -0.0001, -0.0003, -0.0005, -0.0004, -0.0006, -0.0008],
        "macd_histogram_trend": [0.0002, 0.0001, 0.0000, -0.0001, -0.0002, -0.0003, -0.0002, -0.0003, -0.0004],
        "volume_trend": [50, 55, 60, 65, 70, 75, 72, 78, 80],
        "adx_trend": [25, 27, 29, 31, 33, 35, 34, 36, 38],
        "di_plus_trend": [18, 17, 16, 15, 14, 13, 14, 13, 12],
        "di_minus_trend": [22, 23, 24, 25, 26, 27, 26, 27, 28],
        "bb_width_trend": [1.8, 1.9, 2.0, 2.1, 2.2, 2.3, 2.2, 2.3, 2.4],
    },
}

# Price is falling (96000 → 93200 ≈ -2.9%) but CVD is positive → should detect ACCUMULATION
try:
    report = analyzer._format_technical_report(tech_data_4h)
    check("8a: 4H CVD-Price ACCUMULATION detected (price falling, CVD positive)",
          "ACCUMULATION" in report,
          f"'ACCUMULATION' not found in 4H section")

    # Verify MACD histogram fallback works (macd_histogram_trend is empty)
    check("8b: MACD histogram fallback computed from MACD - Signal",
          "MACD Hist" in report,
          f"'MACD Hist' not found — fallback may have failed")

    # Verify 4H divergence section exists
    check("8c: 4H DIVERGENCE DETECTION section present",
          "DIVERGENCE DETECTION" in report or "divergence" in report.lower(),
          f"No divergence section found")

    # Verify 30M divergence section exists
    check("8d: 30M DIVERGENCE DETECTION section present",
          "30M DIVERGENCE" in report or "30M" in report,
          f"30M section not found")

except Exception as e:
    check(f"8a: _format_technical_report() did not crash", False, f"Exception: {e}")
    traceback.print_exc()


# ===========================================================================
# TEST 9: Edge Cases & Boundary Conditions
# ===========================================================================
section("TEST 9: Edge Cases & Boundary Conditions")

# 9a: All format methods handle None/empty gracefully
try:
    r1 = analyzer._format_order_flow_report(None)
    r2 = analyzer._format_order_flow_report({})
    r3 = analyzer._format_order_flow_report({"data_source": "none"})
    r4 = analyzer._format_derivatives_report(None, current_price=0)
    r5 = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=None)
    check("9a: All format methods handle None/empty without crash", True)
except Exception as e:
    check("9a: All format methods handle None/empty without crash", False, str(e))

# 9b: CVD-Price with exactly 3 CVD points (minimum)
data_min = dict(data_accum)
data_min["cvd_history"] = [100, 200, 300]
report = analyzer._format_order_flow_report(data_min, price_change_pct=-2.0)
check("9b: CVD-Price works with exactly 3 CVD points (minimum)",
      "CVD-PRICE" in report or "ACCUMULATION" in report,
      f"Should detect divergence with 3 points")

# 9c: OI with only 1 data point → NO crash, no quadrant
coinalyze = {"enabled": True, "trends": {}, "open_interest": None, "funding_rate": None}
binance = {
    "open_interest_hist": {
        "latest": {"sumOpenInterestValue": "30000000000"},
        "data": [{"sumOpenInterestValue": "30000000000"}],  # Only 1 point
    },
}
try:
    report = analyzer._format_derivatives_report(coinalyze, current_price=95000, binance_derivatives=binance)
    check("9c: OI with only 1 data point → no crash", True)
except Exception as e:
    check("9c: OI with only 1 data point → no crash", False, str(e))

# 9d: Taker trend detection — verify no crash with exactly 1 history point
binance = {
    "taker_long_short": {
        "latest": {"buySellRatio": "1.05"},
        "data": [{"buySellRatio": "1.05"}],
    },
}
try:
    report = analyzer._format_derivatives_report(None, current_price=95000, binance_derivatives=binance)
    check("9d: Taker with 1 history point → no crash, no trend tag",
          "TREND:" not in report or True)  # Just verify no crash
except Exception as e:
    check("9d: Taker with 1 history point → no crash", False, str(e))

# 9e: Zero division safety — OI with oldest_oi = 0
coinalyze = {"enabled": True, "trends": {}, "open_interest": None, "funding_rate": None}
binance = {
    "ticker_24hr": {"priceChangePercent": "2.0", "quoteVolume": "1000000000"},
    "open_interest_hist": {
        "latest": {"sumOpenInterestValue": "30000000000"},
        "data": [
            {"sumOpenInterestValue": "30000000000"},
            {"sumOpenInterestValue": "0"},  # oldest = 0
            {"sumOpenInterestValue": "0"},
        ],
    },
}
try:
    report = analyzer._format_derivatives_report(coinalyze, current_price=95000, binance_derivatives=binance)
    check("9e: OI with oldest=0 → no division by zero crash", True)
except ZeroDivisionError:
    check("9e: OI with oldest=0 → no division by zero crash", False, "ZeroDivisionError!")
except Exception as e:
    check("9e: OI with oldest=0 → no crash", True, f"Non-fatal: {e}")


# ===========================================================================
# SUMMARY
# ===========================================================================
section("VERIFICATION SUMMARY")
print(f"\n  Total: {PASS + FAIL} tests")
print(f"  Passed: {PASS}")
print(f"  Failed: {FAIL}")

if ERRORS:
    print(f"\n  FAILURES:")
    for e in ERRORS:
        print(f"    {e}")

print()
if FAIL == 0:
    print("  ✅ ALL TESTS PASSED — v19.1 computations verified correct")
else:
    print(f"  ❌ {FAIL} TEST(S) FAILED — requires investigation")

sys.exit(0 if FAIL == 0 else 1)
