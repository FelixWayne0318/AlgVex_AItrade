"""
AI Quality Auditor — validates AI agent outputs against expected data coverage,
SIGNAL_CONFIDENCE_MATRIX compliance, and MTF responsibility fulfillment.

Runs post-hoc after each multi-agent analysis cycle. Results are logged and
surfaced via Telegram heartbeat and diagnostic reports.

v24.0: Initial implementation.
v24.1: Complete implementation of all 6 validation dimensions:
  1. AI data coverage rate (per agent, per category)
  2. SIGNAL_CONFIDENCE_MATRIX usage audit (SKIP signal detection)
  3. MTF responsibility fulfillment (positive + violation checks)
  4. Per-Agent data citation tracking (stored text + matched patterns)
  5. Production-level AI quality metrics (score + regime + flags)
  6. User-facing quality report (heartbeat summary + to_dict)
v26.0: Full data citation verification (expanded from DI-only):
  - Value accuracy: RSI/ADX/DI±/BB Position/Volume Ratio across 3 TFs
  - Price values: ATR/SMA200 dollar-formatted verification (% tolerance)
  - Comparison claims: MACD vs Signal, Price vs SMA200, SMA20 vs SMA50, MACD histogram sign
  - Zone claims: RSI oversold/overbought, ADX trending/ranging, Extension regime,
    Volatility Regime, BB Position zone
  - Non-technical data: Sentiment ratios, Funding Rate, Buy Ratio, OBI, S/R prices
  - Audit scope expanded to all 5 agents (added entry_timing + risk)
v27.0 compatibility:
  - Tag-based data coverage: REASON_TAGS mapped to data categories via _TAG_TO_CATEGORIES
  - Citation/zone/comparison checks run ONLY on summary text, not on tag names
  - Prevents false positives from tag substrings (e.g. TREND_1D_BULLISH + MACD_BEARISH_CROSS)
v29.1: Combined tag + text coverage for structured output:
  - In v27.0+ structured mode, agents output focused tag sets (~5 evidence + ~5 risk_flags)
    but their reasoning field (max 500 chars) often references data categories not mapped
    to any tag (e.g. "Order flow: Taker buy ratio 0.71", "4H momentum confirms").
  - Coverage now combines BOTH tag-based (_TAG_TO_CATEGORIES) and text-based
    (_DATA_CATEGORY_MARKERS regex) detection. Tags take priority; text supplements.
  - Fixes false negatives where agents analyzed data categories but didn't use a
    corresponding tag (e.g., mentioning "4H" in reasoning without RSI_CARDWELL tag).
v29.3: Weak-signal tag filtering for coverable-category audit:
  - Tags representing neutral/negligible signals (FR_FAVORABLE_SHORT at FR=0.003%,
    SENTIMENT_CROWDED_LONG at ratio=0.61) should not force a category to be "required".
  - _WEAK_SIGNAL_TAGS defines tags that are valid but carry minimal trading value.
  - When a category is covered ONLY by weak-signal tags, it is excluded from _coverable
    and not penalized as MISSING_DATA. Strong tags always override.
  - Fixes false penalties where AI correctly ignored negligible signals (e.g., FR 0.003%
    is technically "longs pay shorts" but irrelevant to trading decisions).
v29.4: Reasoning truncation fix + neutral data acknowledgment:
  - _validate_agent_output() saves _raw_reasoning before 500-char truncation.
    Auditor uses pre-truncation reasoning for text-based coverage detection,
    fixing false MISSING_DATA when data references appear beyond char 500.
  - debate_history_text now includes reasoning field (using _raw_reasoning).
  - Neutral data acknowledgment: AI prompts instruct agents to select neutral
    tags (FR_IGNORED, SENTIMENT_NEUTRAL, OBI_BALANCED) for non-actionable data.
    Auditor tracks neutral_acknowledged (AI confirmed analysis) vs.
    unconfirmed_neutral (AI selected no tag — unclear if data was analyzed).
    UNCONFIRMED_NEUTRAL flag is informational (no score penalty), distinguishing
    "analyzed but neutral" from "not analyzed at all".
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from agents.analysis_context import AnalysisContext
from agents.prompt_constants import (
    _SIGNAL_ANNOTATIONS, _get_multiplier,
    BULLISH_EVIDENCE_TAGS, BEARISH_EVIDENCE_TAGS,  # v34.0: logic-level checks
)

logger = logging.getLogger(__name__)

# ============================================================================
# Tags that represent neutral/edge-case signals — AI is NOT expected to cite them.
# When these are the ONLY tags covering a data category, that category should NOT
# be required (the AI correctly ignores signals with no trading value).
#
# Examples:
#   - FR_FAVORABLE_SHORT at FR=0.003% is technically "longs pay shorts" but
#     the cost is negligible — AI correctly ignores it.
#   - SENTIMENT_CROWDED_LONG at long_ratio=0.61 barely exceeds 0.60 threshold —
#     not a meaningful crowding signal.
#   - FR_IGNORED means FR is near zero — no cost/benefit to cite.
#   - SENTIMENT_NEUTRAL means sentiment is balanced — nothing to flag.
#   - FR_TREND_RISING/FALLING: direction-only without magnitude (meaningful only
#     when combined with FR_ADVERSE/FR_EXTREME).
#   - OBI_BALANCED means orderbook has no directional pressure — nothing to cite.
# ============================================================================
_WEAK_SIGNAL_TAGS: Set[str] = {
    'FR_IGNORED',            # FR ≈ 0%, no cost/benefit
    'FR_FAVORABLE_LONG',     # FR < -0.001%, negligible
    'FR_FAVORABLE_SHORT',    # FR > 0.001%, negligible
    'FR_TREND_RISING',       # Direction-only, no magnitude
    'FR_TREND_FALLING',      # Direction-only, no magnitude
    'SENTIMENT_NEUTRAL',     # Balanced sentiment, nothing to flag
    'SENTIMENT_CROWDED_LONG',   # Threshold 0.60 is very low, edge case
    'SENTIMENT_CROWDED_SHORT',  # Threshold 0.60 is very low, edge case
    'OBI_BALANCED',          # |OBI| ≤ 0.2, neutral orderbook pressure
}

# ============================================================================
# Constants — data categories expected per agent role
# ============================================================================

# Text section markers that map to the 13 data categories.
# Each marker list is OR-matched: any hit = category referenced.
# v29.6: Broadened to reduce false MISSING_DATA. Each category includes:
# (1) specific technical terms, (2) category name itself, (3) common LLM
# phrasings. Tag-based coverage (_TAG_TO_CATEGORIES) is primary; these text
# patterns are SUPPLEMENTARY fallback for categories not yet covered by tags.
_DATA_CATEGORY_MARKERS: Dict[str, List[str]] = {
    'technical_30m': [r'30[Mm]', r'执行层', r'BB\b', r'Bollinger', r'execution\s*layer',
                      r'30[Mm].{0,20}MACD', r'MACD.{0,20}30[Mm]',
                      r'30[Mm].{0,20}OBV', r'OBV.{0,20}30[Mm]'],
    'sentiment': [r'[Ll]ong/?[Ss]hort\s*[Rr]atio', r'多空比', r'[Ss]entiment', r'[Cc]rowded'],
    'price': [r'[Pp]rice', r'价格', r'\$[\d,]+'],
    'order_flow': [r'CVD', r'[Bb]uy\s*[Rr]atio', r'[Oo]rder\s*[Ff]low', r'[Tt]aker.{0,15}[Bb]uy',
                   r'[Tt]aker.{0,15}[Ss]ell', r'[Aa]ccumulation', r'[Dd]istribution', r'[Aa]bsorption'],
    'derivatives': [r'[Ff]unding\s*[Rr]ate', r'(?<![A-Za-z])FR(?![A-Za-z])',
                    r'[Oo]pen\s*[Ii]nterest', r'(?<![A-Za-z])OI(?![A-Za-z])',
                    r'[Pp]remium', r'[Dd]erivativ', r'[Ll]iquidat(?:ion|ed)',
                    r'资金费率', r'持仓量'],
    'binance_derivatives': [r'[Tt]op\s*[Tt]raders?', r'[Tt]aker\s*[Rr]atio',
                            r'[Bb]inance\s*[Dd]erivativ'],
    'orderbook': [r'(?<![A-Za-z])OBI(?![A-Za-z])', r'[Oo]rder\s*[Bb]ook', r'[Dd]epth',
                  r'[Pp]ressure\s*[Gg]radient', r'[Bb]id.{0,10}[Aa]sk', r'订单簿'],
    'mtf_4h': [r'4[Hh]', r'决策层', r'[Mm]omentum\s*layer', r'[Mm]omentum\s*(?:4|four)',
               r'4[Hh].{0,20}MACD', r'MACD.{0,20}4[Hh]',
               r'4[Hh].{0,20}OBV', r'OBV.{0,20}4[Hh]',
               r'4[Hh].{0,20}[Vv]olume', r'[Vv]olume.{0,20}4[Hh]'],
    'mtf_1d': [r'1[Dd]', r'趋势层', r'SMA\s*200', r'[Tt]rend\s*layer', r'[Dd]aily',
               r'1[Dd].{0,20}MACD', r'MACD.{0,20}1[Dd]',
               r'1[Dd].{0,20}OBV', r'OBV.{0,20}1[Dd]',
               r'1[Dd].{0,20}[Vv]olume', r'[Vv]olume.{0,20}1[Dd]',
               r'1[Dd].{0,20}(?:BB|Bollinger)', r'(?:BB|Bollinger).{0,20}1[Dd]'],
    'sr_zones': [r'[Ss]upport', r'[Rr]esistance', r'S/?R\s*[Zz]one', r'\bS1\b', r'\bR1\b',
                 r'支撑', r'阻力'],
    'extension_ratio': [r'[Ee]xtension\s*[Rr]atio', r'ATR.{0,20}[Ee]xtension',
                        r'[Oo]ver\s*[Ee]xtended', r'[Ee]xtension.{0,20}ATR'],
    'volatility_regime': [r'[Vv]olatility\s*[Rr]egime', r'[Vv]ol.{0,20}[Pp]ercentile',
                          r'\bVol\s*(LOW|HIGH|EXTREME)\b', r'[Vv]olatility\s*(LOW|HIGH|EXTREME)',
                          r'[Vv]olatility\s+(?:is\s+)?(?:low|normal|high|extreme)'],
    'position_context': [r'[Ll]iquidation\s*[Bb]uffer', r'[Pp]osition\s*[Ss]ize',
                         r'[Ll]everage', r'[Ee]quity'],
}

# v27.0: Map REASON_TAGS to data categories for tag-based data coverage.
# When agents output structured tags instead of free text, we use this mapping
# to determine which data sources they referenced.
# v29.0: Changed to List[str] — one tag can cover multiple data categories.
# Fixes: 4H-specific tags (RSI_CARDWELL, MACD_*_CROSS, MACD_HISTOGRAM) were
# wrongly mapped only to technical_30m; DI_*_CROSS only to mtf_1d; VOLUME_*
# only to technical_30m. Tags now map to all timeframes they actually reference.
_TAG_TO_CATEGORIES: Dict[str, List[str]] = {
    # technical_30m + mtf_4h (generated from EITHER 30M OR 4H data)
    'RSI_OVERSOLD': ['technical_30m', 'mtf_4h'], 'RSI_OVERBOUGHT': ['technical_30m', 'mtf_4h'],
    'BB_LOWER_ZONE': ['technical_30m', 'mtf_4h'], 'BB_UPPER_ZONE': ['technical_30m', 'mtf_4h'],
    # BB_SQUEEZE/EXPANSION: always-valid judgment tags (no deterministic data check).
    # NOT mapped to technical_30m — they must not inflate coverage when no 30M data is cited.
    # Agents citing only BB_SQUEEZE/EXPANSION do not demonstrate 30M data usage.
    'RSI_BEARISH_DIV_30M': ['technical_30m'], 'RSI_BULLISH_DIV_30M': ['technical_30m'],
    'MACD_BEARISH_DIV_30M': ['technical_30m'], 'MACD_BULLISH_DIV_30M': ['technical_30m'],
    'OBV_BEARISH_DIV_30M': ['technical_30m'], 'OBV_BULLISH_DIV_30M': ['technical_30m'],
    'EARLY_ENTRY': ['technical_30m'], 'LATE_ENTRY': ['technical_30m'],
    'LOW_VOLUME_ENTRY': ['technical_30m'],
    'SMA_BULLISH_CROSS_30M': ['technical_30m'], 'SMA_BEARISH_CROSS_30M': ['technical_30m'],
    'SMA_BULLISH_CROSS_4H': ['mtf_4h'], 'SMA_BEARISH_CROSS_4H': ['mtf_4h'],
    'EMA_BULLISH_CROSS_4H': ['mtf_4h'], 'EMA_BEARISH_CROSS_4H': ['mtf_4h'],
    'MACD_1D_BULLISH': ['mtf_1d'], 'MACD_1D_BEARISH': ['mtf_1d'],
    # 4H indicators — generated from 4H RSI/MACD/DI, cover mtf_4h
    # MACD_*_CROSS: generated from macd_4h OR macd_30m → covers both TFs
    'MACD_BEARISH_CROSS': ['technical_30m', 'mtf_4h'],
    'MACD_BULLISH_CROSS': ['technical_30m', 'mtf_4h'],
    # MACD_HISTOGRAM_*: generated from 4H histogram trend, also applicable to 30M
    'MACD_HISTOGRAM_CONTRACTING': ['technical_30m', 'mtf_4h'],
    'MACD_HISTOGRAM_EXPANDING': ['technical_30m', 'mtf_4h'],
    # RSI_CARDWELL_*: generated from rsi_4h ONLY (Cardwell range analysis)
    'RSI_CARDWELL_BULL': ['mtf_4h'], 'RSI_CARDWELL_BEAR': ['mtf_4h'],
    # VOLUME_*: generated from vol_ratio_30m OR vol_ratio_4h → covers both TFs
    'VOLUME_SURGE': ['technical_30m', 'mtf_4h'],
    'VOLUME_DRY': ['technical_30m', 'mtf_4h'],
    # sentiment
    'SENTIMENT_CROWDED_LONG': ['sentiment'], 'SENTIMENT_CROWDED_SHORT': ['sentiment'],
    'SENTIMENT_EXTREME': ['sentiment'], 'SENTIMENT_NEUTRAL': ['sentiment'],
    # order_flow
    'CVD_POSITIVE': ['order_flow'], 'CVD_NEGATIVE': ['order_flow'],
    'CVD_ACCUMULATION': ['order_flow'], 'CVD_DISTRIBUTION': ['order_flow'],
    'CVD_ABSORPTION_BUY': ['order_flow'], 'CVD_ABSORPTION_SELL': ['order_flow'],
    'BUY_RATIO_HIGH': ['order_flow'], 'BUY_RATIO_LOW': ['order_flow'],
    # derivatives
    'FR_FAVORABLE_LONG': ['derivatives'], 'FR_FAVORABLE_SHORT': ['derivatives'],
    'FR_ADVERSE_LONG': ['derivatives'], 'FR_ADVERSE_SHORT': ['derivatives'],
    'FR_EXTREME': ['derivatives'], 'FR_IGNORED': ['derivatives'],
    'FR_TREND_RISING': ['derivatives'], 'FR_TREND_FALLING': ['derivatives'],
    'PREMIUM_POSITIVE': ['derivatives'], 'PREMIUM_NEGATIVE': ['derivatives'],
    'OI_LONG_OPENING': ['derivatives'], 'OI_SHORT_OPENING': ['derivatives'],
    'OI_LONG_CLOSING': ['derivatives'], 'OI_SHORT_CLOSING': ['derivatives'],
    'LIQUIDATION_CASCADE_LONG': ['derivatives'], 'LIQUIDATION_CASCADE_SHORT': ['derivatives'],
    # binance_derivatives
    'TOP_TRADERS_LONG_BIAS': ['binance_derivatives'], 'TOP_TRADERS_SHORT_BIAS': ['binance_derivatives'],
    'TAKER_BUY_DOMINANT': ['binance_derivatives'], 'TAKER_SELL_DOMINANT': ['binance_derivatives'],
    # orderbook
    'OBI_BUY_PRESSURE': ['orderbook'], 'OBI_SELL_PRESSURE': ['orderbook'], 'OBI_BALANCED': ['orderbook'],
    'OBI_SHIFTING_BULLISH': ['orderbook'], 'OBI_SHIFTING_BEARISH': ['orderbook'],
    'SLIPPAGE_HIGH': ['orderbook'], 'LIQUIDITY_THIN': ['orderbook'],
    # mtf_4h (4H divergences + composite momentum)
    'RSI_BEARISH_DIV_4H': ['mtf_4h'], 'RSI_BULLISH_DIV_4H': ['mtf_4h'],
    'MACD_BEARISH_DIV_4H': ['mtf_4h'], 'MACD_BULLISH_DIV_4H': ['mtf_4h'],
    'OBV_BEARISH_DIV_4H': ['mtf_4h'], 'OBV_BULLISH_DIV_4H': ['mtf_4h'],
    'MOMENTUM_4H_BULLISH': ['mtf_4h'], 'MOMENTUM_4H_BEARISH': ['mtf_4h'],
    # WEAK_TREND_ADX_LOW: generated from adx_1d < 25 (1D data)
    'WEAK_TREND_ADX_LOW': ['mtf_1d'],
    # mtf_1d
    'TREND_1D_BULLISH': ['mtf_1d'], 'TREND_1D_BEARISH': ['mtf_1d'], 'TREND_1D_NEUTRAL': ['mtf_1d'],
    'STRONG_TREND_ADX40': ['mtf_1d'], 'TREND_ALIGNED': ['mtf_1d'],
    # DI_*_CROSS: generated from 1D OR 4H (OR 30M for bearish) → covers both TFs
    'DI_BULLISH_CROSS': ['mtf_1d', 'mtf_4h'],
    'DI_BEARISH_CROSS': ['mtf_1d', 'mtf_4h'],
    'TREND_EXHAUSTION': ['mtf_1d'],
    # sr_zones
    'NEAR_STRONG_SUPPORT': ['sr_zones'], 'NEAR_STRONG_RESISTANCE': ['sr_zones'],
    'SR_BREAKOUT_POTENTIAL': ['sr_zones'], 'SR_REJECTION': ['sr_zones'],
    'SR_TRAPPED': ['sr_zones'], 'SR_CLEAR_SPACE': ['sr_zones'],
    # extension_ratio (multi-timeframe v29.2)
    'EXTENSION_NORMAL': ['extension_ratio'],
    'EXTENSION_EXTREME': ['extension_ratio'], 'EXTENSION_OVEREXTENDED': ['extension_ratio'],
    'EXTENSION_4H_OVEREXTENDED': ['extension_ratio', 'mtf_4h'], 'EXTENSION_4H_EXTREME': ['extension_ratio', 'mtf_4h'],
    'EXTENSION_1D_OVEREXTENDED': ['extension_ratio', 'mtf_1d'], 'EXTENSION_1D_EXTREME': ['extension_ratio', 'mtf_1d'],
    'OVEREXTENDED_ENTRY': ['extension_ratio'],
    # volatility_regime (multi-timeframe v29.2)
    'VOL_EXTREME': ['volatility_regime'], 'VOL_HIGH': ['volatility_regime'], 'VOL_LOW': ['volatility_regime'],
    'VOL_4H_HIGH': ['volatility_regime', 'mtf_4h'], 'VOL_4H_EXTREME': ['volatility_regime', 'mtf_4h'], 'VOL_4H_LOW': ['volatility_regime', 'mtf_4h'],
    'VOL_1D_HIGH': ['volatility_regime', 'mtf_1d'], 'VOL_1D_EXTREME': ['volatility_regime', 'mtf_1d'], 'VOL_1D_LOW': ['volatility_regime', 'mtf_1d'],
    # price
    'DIVERGENCE_CONFIRMED': ['price'],
    # position context — LIQUIDATION_BUFFER from account/position data, not price
    'LIQUIDATION_BUFFER_CRITICAL': ['position_context'], 'LIQUIDATION_BUFFER_LOW': ['position_context'],
    'SL_TOO_TIGHT': ['price'], 'SL_TOO_WIDE': ['price'], 'TP_TOO_GREEDY': ['price'],
    'WRONG_DIRECTION': ['price'],
}

# Minimum data categories each agent MUST reference.
_AGENT_REQUIRED_CATEGORIES: Dict[str, Set[str]] = {
    'bull': {'mtf_1d', 'mtf_4h', 'technical_30m', 'order_flow', 'derivatives', 'sr_zones', 'sentiment'},
    'bear': {'mtf_1d', 'mtf_4h', 'technical_30m', 'order_flow', 'derivatives', 'sr_zones', 'sentiment'},
    'judge': {'mtf_1d', 'mtf_4h', 'technical_30m', 'order_flow', 'derivatives', 'sentiment'},
    # v31.5: removed order_flow — ET prompt only guides 4 dimensions
    # (MTF alignment, 30M timing, counter-trend risk, extension/volatility)
    'entry_timing': {'technical_30m', 'mtf_4h', 'mtf_1d'},
    # position_context: state-dependent (only relevant with open position),
    # covered by text-based _DATA_CATEGORY_MARKERS detection when applicable
    # v31.5: removed orderbook/binance_derivatives — Risk prompt only guides
    # volatility/FR/liquidation/S&R; audit should match prompt design
    'risk': {'derivatives', 'extension_ratio', 'volatility_regime'},
}

# Map from _SIGNAL_ANNOTATIONS keys to text detection patterns.
# Used by SKIP signal audit to detect if an agent cited a SKIP-tier signal.
# v30.5: Use tempered greedy token _NO_TF to prevent cross-TF matching.
# "1D bearish trend...4H MACD" would falsely match "1D.*MACD" with unbounded .*.
# The tempered greedy token stops at any TF label boundary.
_NO_TF = r'(?:(?!(?:30[Mm]|4[Hh]|1[Dd]|执行层|决策层|趋势层)).)'
_SIGNAL_KEY_PATTERNS: Dict[str, List[str]] = {
    '1d_sma200': [rf'1[Dd]{_NO_TF}{{0,30}}?SMA\s*200', rf'SMA\s*200{_NO_TF}{{0,30}}?1[Dd]'],
    '1d_adx_di': [rf'1[Dd]{_NO_TF}{{0,30}}?(?:ADX|DI[\+\-])', rf'(?:ADX|DI[\+\-]){_NO_TF}{{0,30}}?1[Dd]'],
    '1d_macd': [rf'1[Dd]{_NO_TF}{{0,30}}?MACD'],
    '1d_macd_h': [rf'1[Dd]{_NO_TF}{{0,30}}?MACD{_NO_TF}{{0,20}}?[Hh]ist(?:ogram)?',
                  rf'1[Dd]{_NO_TF}{{0,30}}?(?:MACD{_NO_TF}{{0,10}}?)?直方图'],
    '1d_rsi': [rf'1[Dd]{_NO_TF}{{0,30}}?RSI'],
    '4h_rsi': [rf'4[Hh]{_NO_TF}{{0,30}}?RSI'],
    '4h_macd': [rf'4[Hh]{_NO_TF}{{0,30}}?MACD'],
    '4h_macd_h': [rf'4[Hh]{_NO_TF}{{0,30}}?MACD{_NO_TF}{{0,20}}?[Hh]ist(?:ogram)?',
                  rf'4[Hh]{_NO_TF}{{0,30}}?(?:MACD{_NO_TF}{{0,10}}?)?直方图'],
    '4h_adx_di': [rf'4[Hh]{_NO_TF}{{0,30}}?(?:ADX|DI[\+\-])'],
    '4h_bb': [rf'4[Hh]{_NO_TF}{{0,30}}?(?:BB|Bollinger)'],
    '4h_sma': [rf'4[Hh]{_NO_TF}{{0,30}}?SMA\s*(?:cross|交叉|20|50)'],
    '30m_rsi': [rf'30[Mm]{_NO_TF}{{0,30}}?RSI'],
    '30m_macd': [rf'30[Mm]{_NO_TF}{{0,30}}?MACD'],
    '30m_macd_h': [rf'30[Mm]{_NO_TF}{{0,30}}?MACD{_NO_TF}{{0,20}}?[Hh]ist(?:ogram)?',
                   rf'30[Mm]{_NO_TF}{{0,30}}?(?:MACD{_NO_TF}{{0,10}}?)?直方图'],
    '30m_adx': [rf'30[Mm]{_NO_TF}{{0,30}}?ADX'],
    '30m_bb': [rf'30[Mm]{_NO_TF}{{0,30}}?(?:BB|Bollinger)'],
    '30m_sma': [rf'30[Mm]{_NO_TF}{{0,30}}?SMA'],
    '30m_volume': [rf'30[Mm]{_NO_TF}{{0,30}}?[Vv]olume'],
    # v36.1: OBV citation detection (all 3 TFs)
    '30m_obv': [rf'30[Mm]{_NO_TF}{{0,30}}?OBV'],
    '4h_obv': [rf'4[Hh]{_NO_TF}{{0,30}}?OBV'],
    '1d_obv': [rf'1[Dd]{_NO_TF}{{0,30}}?OBV'],
    # v36.1: Missing 1D BB / 1D Volume / 4H Volume patterns
    '1d_bb': [rf'1[Dd]{_NO_TF}{{0,30}}?(?:BB|Bollinger)'],
    '1d_volume': [rf'1[Dd]{_NO_TF}{{0,30}}?[Vv]olume'],
    '4h_volume': [rf'4[Hh]{_NO_TF}{{0,30}}?[Vv]olume'],
}

# Confluence layer keywords for verifying Judge output.
_CONFLUENCE_DIRECTION_KEYWORDS: Dict[str, List[str]] = {
    'BULLISH': [r'\bBULLISH\b', r'看多', r'上涨', r'多头'],
    'BEARISH': [r'\bBEARISH\b', r'看空', r'下跌', r'空头'],
    'NEUTRAL': [r'\bNEUTRAL\b', r'中性', r'无趋势', r'无方向'],
}


def _get_skip_signals_for_regime(adx_1d: float) -> Set[str]:
    """Return set of annotation keys that are SKIP in the given regime."""
    skip: Set[str] = set()
    for key in _SIGNAL_ANNOTATIONS:
        _, m, tier = _get_multiplier(key, adx_1d)
        if tier == 'skip':
            skip.add(key)
    return skip


# ============================================================================
# Constants — data citation verification (v26.0)
# ============================================================================

# Indicators to verify value accuracy across all timeframes.
# (display_name, data_key, indicator_regex, abs_tolerance, valid_min, valid_max, scale_factor)
# scale_factor: multiply actual value before comparing to cited value.
# BB Position stored as 0-1, displayed as 0-100%; Volume Ratio is 1:1.
_VALUE_VERIFY_INDICATORS: list = [
    ('RSI', 'rsi', r'RSI', 3.0, 0, 100, 1.0),
    ('ADX', 'adx', r'(?<![/])ADX', 3.0, 0, 100, 1.0),
    ('DI+', 'di_plus', r'DI\+', 2.0, 0, 100, 1.0),
    ('DI-', 'di_minus', r'DI[\-−]', 2.0, 0, 100, 1.0),
    ('BB Position', 'bb_position', r'BB\s*(?:Position|Pos)', 5.0, 0, 100, 100.0),
    ('Volume Ratio', 'volume_ratio', r'Volume\s*Ratio', 0.3, 0, 50, 1.0),
    # v30.3: Extension Ratio value verification.
    # (Price-SMA)/ATR, reported as "Extension Ratio (SMA20): ±X.XX ATR".
    # Range ~ -10 to +10, tolerance 0.5 ATR. Covers 30M + 4H (both use SMA20).
    # 1D uses SMA200 key → gracefully skipped (None).
    ('Extension Ratio', 'extension_ratio_sma_20',
     r'[Ee]xtension\s*[Rr]atio(?:\s*\(SMA\s*20\))?', 0.5, -15, 15, 1.0),
    # v31.0: ATR% (ATR/Price*100) value verification.
    # Bounded percentage, typically 0.5%-10% for crypto.
    # Tolerance 0.5% accounts for rounding. scale=100 converts 0-1 to 0-100%.
    ('ATR%', 'atr_pct', r'ATR\s*%', 0.5, 0, 30, 100.0),
]

# Dollar-formatted price indicators — uses percentage tolerance.
# (display_name, data_key, label_regex, pct_tolerance)
_PRICE_VERIFY_INDICATORS: list = [
    ('ATR', 'atr', r'ATR', 5.0),
    ('SMA 200', 'sma_200', r'SMA\s*200', 0.5),
]

# v31.1: MACD-family indicators — uses percentage tolerance with minimum
# absolute threshold.  MACD values scale with asset price (no fixed bounds)
# so absolute tolerance is inappropriate.  When |actual| < min_abs the check
# is skipped because near-zero values make percentage comparison unstable.
# (display_name, data_key, indicator_regex, pct_tolerance, min_abs_threshold)
_MACD_VERIFY_INDICATORS: list = [
    # MACD line: plain "MACD" is safe — the extraction patterns' delimiter
    # class [:\s=at] rejects "MACD Histogram" and "MACD Signal" because
    # 'H' and 'S' are not in [:\s=at], so no negative lookahead needed.
    ('MACD',           'macd',           r'MACD',                  15.0, 1e-6),
    ('MACD Signal',    'macd_signal',    r'MACD\s*Signal',         15.0, 1e-6),
    ('MACD Histogram', 'macd_histogram', r'MACD\s*Hist(?:ogram)?', 20.0, 1e-6),
]

# Timeframe regex patterns for proximity matching in agent text.
_TF_CITE_PATTERNS: Dict[str, List[str]] = {
    '30M': [r'30[Mm]', r'执行层'],
    '4H': [r'4[Hh]', r'决策层'],
    '1D': [r'1[Dd]', r'趋势层'],
}


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class AgentAuditResult:
    """Audit result for a single agent."""
    agent_role: str
    # Per-category coverage: {category_name: True/False}
    data_coverage: Dict[str, bool] = field(default_factory=dict)
    # Which required categories are missing
    missing_categories: List[str] = field(default_factory=list)
    # v29.4: Categories where AI selected a neutral/weak tag, confirming it
    # analyzed the data but found it non-actionable. Distinguishes "analyzed
    # but neutral" from "not analyzed at all".
    neutral_acknowledged: List[str] = field(default_factory=list)
    # v29.4: Weak-signal categories that were NOT in _required and AI did NOT
    # select any neutral tag — unclear if AI analyzed the data.
    unconfirmed_neutral: List[str] = field(default_factory=list)
    # Fraction of required categories covered (0.0-1.0)
    coverage_rate: float = 0.0
    # SKIP-tier signals the agent cited as evidence
    skip_signal_violations: List[str] = field(default_factory=list)
    # MTF violations (30M for direction, missing 30M for entry_timing, etc.)
    mtf_violations: List[str] = field(default_factory=list)
    # Per-category citation detail: {category: [matched_pattern, ...]}
    citations: Dict[str, List[str]] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)


@dataclass
class ConfluenceAuditResult:
    """Audit result for Judge's confluence assessment."""
    layers_declared: Dict[str, str] = field(default_factory=dict)
    aligned_layers_declared: int = 0
    aligned_layers_actual: int = 0
    alignment_mismatch: bool = False
    confidence_declared: str = ''
    confidence_expected: str = ''
    confidence_mismatch: bool = False
    flags: List[str] = field(default_factory=list)


@dataclass
class QualityReport:
    """Complete quality audit report for one analysis cycle."""
    timestamp: float = 0.0
    adx_1d: float = 30.0
    regime: str = 'WEAK_TREND'
    agent_results: Dict[str, AgentAuditResult] = field(default_factory=dict)
    confluence_audit: Optional[ConfluenceAuditResult] = None
    counter_trend_detected: bool = False
    counter_trend_flagged_by_entry_timing: bool = False
    # v25.0: comparison direction errors (DI reversal, MACD crossover, Price/SMA200, etc.)
    citation_errors: int = 0
    # v26.0: fabricated/inaccurate numerical values
    value_errors: int = 0
    # v26.0: qualitative zone misclassification (RSI oversold/overbought, ADX trend, etc.)
    zone_errors: int = 0
    # v34.0: phantom citations (AI cites unavailable data sources)
    phantom_citations: int = 0
    # v34.0: narrative misread (AI uses contradictory adjectives for indicator values)
    narrative_misreads: int = 0
    # v34.0: logic-level coherence checks
    reason_signal_conflict: int = 0     # penalty value (0/8/12)
    confidence_risk_conflict: int = 0   # penalty value (0/6)
    overall_score: int = 100
    flags: List[str] = field(default_factory=list)

    def to_summary(self) -> str:
        """One-line summary for logging/heartbeat."""
        parts = [f"AI Quality: {self.overall_score}/100"]
        if self.flags:
            parts.append(f"flags={len(self.flags)}")
        for role, result in self.agent_results.items():
            if result.missing_categories:
                parts.append(f"{role}:miss={','.join(result.missing_categories)}")
        if self.confluence_audit and self.confluence_audit.alignment_mismatch:
            parts.append("confluence:MISMATCH")
        if self.value_errors:
            parts.append(f"value_errs={self.value_errors}")
        if self.zone_errors:
            parts.append(f"zone_errs={self.zone_errors}")
        if self.phantom_citations:
            parts.append(f"phantom={self.phantom_citations}")
        if self.narrative_misreads:
            parts.append(f"narrative={self.narrative_misreads}")
        if self.reason_signal_conflict > 0:
            parts.append(f"reason_sig={self.reason_signal_conflict}")
        if self.confidence_risk_conflict > 0:
            parts.append(f"conf_risk={self.confidence_risk_conflict}")
        return ' | '.join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Serializable dict for diagnostic export / Web API."""
        d: Dict[str, Any] = {
            'timestamp': self.timestamp,
            'adx_1d': self.adx_1d,
            'regime': self.regime,
            'overall_score': self.overall_score,
            'flags': self.flags,
            'agents': {},
        }
        for role, r in self.agent_results.items():
            agent_dict: Dict[str, Any] = {
                'coverage_rate': round(r.coverage_rate, 2),
                'data_coverage': r.data_coverage,
                'missing_categories': r.missing_categories,
                'citations': {k: v for k, v in r.citations.items() if v},
                'skip_violations': r.skip_signal_violations,
                'mtf_violations': r.mtf_violations,
                'flags': r.flags,
            }
            # v29.4: Include neutral acknowledgment tracking
            if r.neutral_acknowledged:
                agent_dict['neutral_acknowledged'] = r.neutral_acknowledged
            if r.unconfirmed_neutral:
                agent_dict['unconfirmed_neutral'] = r.unconfirmed_neutral
            d['agents'][role] = agent_dict
        if self.confluence_audit:
            ca = self.confluence_audit
            d['confluence'] = {
                'layers_declared': ca.layers_declared,
                'aligned_declared': ca.aligned_layers_declared,
                'aligned_actual': ca.aligned_layers_actual,
                'alignment_mismatch': ca.alignment_mismatch,
                'confidence_declared': ca.confidence_declared,
                'confidence_expected': ca.confidence_expected,
                'confidence_mismatch': ca.confidence_mismatch,
                'flags': ca.flags,
            }
        d['citation_errors'] = self.citation_errors
        d['value_errors'] = self.value_errors
        d['zone_errors'] = self.zone_errors
        d['phantom_citations'] = self.phantom_citations
        d['narrative_misreads'] = self.narrative_misreads
        d['reason_signal_conflict'] = self.reason_signal_conflict
        d['confidence_risk_conflict'] = self.confidence_risk_conflict
        d['counter_trend'] = {
            'detected': self.counter_trend_detected,
            'flagged_by_entry_timing': self.counter_trend_flagged_by_entry_timing,
        }
        return d


# ============================================================================
# AIQualityAuditor
# ============================================================================

class AIQualityAuditor:
    """
    Post-hoc auditor for multi-agent AI analysis outputs.

    Called after each analysis cycle with the raw agent outputs. Produces a
    QualityReport with per-agent data coverage, SKIP signal violations, MTF
    responsibility checks, and confluence accuracy verification.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"{__name__}.AIQualityAuditor")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def audit(self, ctx: AnalysisContext) -> QualityReport:
        """Run full quality audit on one analysis cycle's outputs.

        v30.0: AnalysisContext is the sole data carrier. Ground truth for
        citation verification comes from ctx.features (= what agents saw).
        Falls back to ctx.raw_data when features are unavailable.
        """
        features = ctx.features or {}

        # Build ground truth from features (primary) or raw_data (fallback)
        if features:
            gt_tech = self._features_to_tf_data(features)
            gt_nontech = self._features_to_nontech(features)
        else:
            rd = ctx.raw_data or {}
            gt_tech = rd.get('technical') or {}
            gt_nontech = {
                'sentiment': rd.get('sentiment'),
                'order_flow': rd.get('order_flow'),
                'derivatives': rd.get('derivatives'),
                'orderbook': rd.get('orderbook'),
                'sr_zones': rd.get('sr_zones'),
            }

        # Read all agent outputs from ctx (single source)
        adx_1d = features.get('adx_1d', 30.0) if features else 30.0
        bull_text = ctx.debate_bull_text
        bear_text = ctx.debate_bear_text
        judge_decision = ctx.judge_output
        entry_timing_result = ctx.et_output
        risk_result = ctx.risk_output
        bull_structured = ctx.bull_output
        bear_structured = ctx.bear_output
        valid_tags = ctx.valid_tags
        report = QualityReport(
            timestamp=time.time(),
            adx_1d=adx_1d,
            regime=self._classify_regime(adx_1d),
        )

        # v27.0: Extract tags for tag-based data coverage
        _bull_tags = None
        _bear_tags = None
        if bull_structured:
            _bull_tags = (bull_structured.get('evidence', [])
                          + bull_structured.get('risk_flags', []))
        if bear_structured:
            _bear_tags = (bear_structured.get('evidence', [])
                          + bear_structured.get('risk_flags', []))

        # Judge/Risk/ET tags from structured dicts
        _judge_tags = None
        _risk_tags = None
        _et_tags = None
        if judge_decision:
            _judge_tags = (judge_decision.get('decisive_reasons', [])
                           + judge_decision.get('acknowledged_risks', []))
        if entry_timing_result and entry_timing_result.get('timing_verdict') != 'N/A':
            _et_tags = entry_timing_result.get('decisive_reasons', [])
        if risk_result:
            _risk_tags = risk_result.get('risk_factors', [])
            if isinstance(_risk_tags, str):
                _risk_tags = None  # Not a list, fall back to text

        # Dynamic requirement adjustment: only require categories that have
        # market-condition tags available. Memory/lesson tags (always-valid)
        # should not count as covering a data category.
        # v29.3: Weak-signal tags (FR_FAVORABLE_SHORT at FR=0.003%, SENTIMENT_CROWDED_LONG
        # at ratio=0.61, etc.) should not make a category "required" when they are the
        # ONLY tags covering it — AI correctly ignores negligible signals.
        _coverable: Optional[Set[str]] = None
        if valid_tags is not None:
            from agents.tag_validator import _ALWAYS_VALID
            _coverable = set()
            _weak_only: Set[str] = set()  # Categories covered ONLY by weak tags
            for tag in valid_tags:
                if tag in _ALWAYS_VALID:
                    continue  # Memory tags don't count for coverage
                cats = _TAG_TO_CATEGORIES.get(tag, [])
                is_weak = tag in _WEAK_SIGNAL_TAGS
                for cat in cats:
                    if is_weak:
                        if cat not in _coverable:
                            _weak_only.add(cat)
                    else:
                        _coverable.add(cat)
                        _weak_only.discard(cat)  # Strong tag overrides
            # weak_only categories are NOT added to _coverable —
            # AI is not penalized for ignoring negligible signals

        # 0. v34.1: Data availability pre-check
        # v34.2: Map _avail_* flags to audit data categories so _effective_required()
        # excludes categories whose source data is genuinely missing. This prevents
        # penalizing agents for not citing data they never received.
        _AVAIL_TO_CATEGORIES: Dict[str, List[str]] = {
            '_avail_order_flow': ['order_flow'],
            '_avail_derivatives': ['derivatives'],
            '_avail_binance_derivatives': ['binance_derivatives'],
            '_avail_orderbook': ['orderbook'],
            '_avail_mtf_4h': ['mtf_4h'],
            '_avail_mtf_1d': ['mtf_1d'],
            '_avail_account': ['position_context'],
            '_avail_sr_zones': ['sr_zones'],
            '_avail_sentiment': ['sentiment'],
        }
        _avail_flags = {k: v for k, v in features.items() if k.startswith('_avail_')}
        _unavailable = [k.replace('_avail_', '') for k, v in _avail_flags.items() if not v]
        _unavailable_categories: Set[str] = set()
        for flag_key, is_avail in _avail_flags.items():
            if not is_avail:
                for cat in _AVAIL_TO_CATEGORIES.get(flag_key, []):
                    _unavailable_categories.add(cat)
        if _unavailable:
            report.flags.append(f'DATA_UNAVAILABLE: {", ".join(_unavailable)}')

        def _effective_required(role: str) -> Optional[Set[str]]:
            """Return required categories intersected with coverable set,
            excluding categories whose source data is unavailable."""
            base = _AGENT_REQUIRED_CATEGORIES.get(role, set())
            # v34.2: Remove categories with genuinely missing source data
            adjusted = base - _unavailable_categories
            if _coverable is None:
                return adjusted if adjusted != base else None
            trimmed = adjusted & _coverable
            return trimmed if trimmed != base else None

        # 1. Per-agent data coverage + per-agent citation tracking
        # v29.1: Include structured reasoning in text for coverage regex.
        # v29.4: Prefer _raw_reasoning (pre-truncation) over truncated reasoning.
        # The 500-char reasoning limit causes data references (e.g., "Funding rate
        # 0.003% is normal") to be cut off, creating false MISSING_DATA flags.
        _bull_coverage_text = bull_text
        if bull_structured:
            _reasoning = bull_structured.get('_raw_reasoning') or bull_structured.get('reasoning', '')
            if _reasoning:
                _bull_coverage_text = _reasoning + ' ' + bull_text
        _bear_coverage_text = bear_text
        if bear_structured:
            _reasoning = bear_structured.get('_raw_reasoning') or bear_structured.get('reasoning', '')
            if _reasoning:
                _bear_coverage_text = _reasoning + ' ' + bear_text

        # v29.4: Pass weak_only categories so _audit_agent can track neutral
        # acknowledgment vs. unconfirmed (AI didn't select neutral tag either).
        _weak_cats = _weak_only if (_coverable is not None) else set()
        report.agent_results['bull'] = self._audit_agent(
            'bull', _bull_coverage_text, adx_1d,
            required_override=_effective_required('bull'), tags=_bull_tags,
            weak_only_categories=_weak_cats)
        report.agent_results['bear'] = self._audit_agent(
            'bear', _bear_coverage_text, adx_1d,
            required_override=_effective_required('bear'), tags=_bear_tags,
            weak_only_categories=_weak_cats)

        judge_text = self._extract_judge_text(judge_decision) if judge_decision else ''
        report.agent_results['judge'] = self._audit_agent(
            'judge', judge_text, adx_1d,
            required_override=_effective_required('judge'), tags=_judge_tags)

        _et_text = ''
        if entry_timing_result and entry_timing_result.get('timing_verdict') != 'N/A':
            # v29.1: Include reasoning field for richer coverage detection
            # v30.4: Use _raw_* (pre-truncation) versions consistent with
            # bull/bear/judge/risk to prevent false errors from truncated text.
            _et_reason = (entry_timing_result.get('_raw_reason')
                          or entry_timing_result.get('reason', ''))
            _et_reasoning = (entry_timing_result.get('_raw_reasoning')
                             or entry_timing_result.get('reasoning', ''))
            _et_text = f"{_et_reasoning} {_et_reason}".strip()
            report.agent_results['entry_timing'] = self._audit_agent(
                'entry_timing', _et_text, adx_1d,
                required_override=_effective_required('entry_timing'),
                tags=_et_tags,
            )

        _risk_text = ''
        if risk_result:
            # v29.1: Include reasoning field for richer coverage detection
            # v30.4: Use _raw_* (pre-truncation) versions consistent with
            # citation check path (line 647) to prevent truncation mismatches.
            _risk_reasoning = (risk_result.get('_raw_reasoning')
                               or risk_result.get('reasoning', ''))
            _risk_text = (
                _risk_reasoning + ' '
                + (risk_result.get('_raw_reason') or risk_result.get('reason', '')) + ' '
                + str(risk_result.get('risk_factors', ''))
            )
            # Judge already decided HOLD → Risk is passthrough, relax all.
            # Otherwise, apply coverable-category trimming.
            risk_received_hold = (
                judge_decision
                and judge_decision.get('decision', '') == 'HOLD'
            )
            report.agent_results['risk'] = self._audit_agent(
                'risk', _risk_text, adx_1d,
                required_override=(set() if risk_received_hold
                                   else _effective_required('risk')),
                tags=_risk_tags,
            )

        # 2. Confluence accuracy (Judge-specific)
        if judge_decision:
            report.confluence_audit = self._audit_confluence(judge_decision)

        # 3. Data citation accuracy (v25.0 DI + v26.0 full data)
        # v27.0: Use ONLY summary/reason text for citation checks.
        # REASON_TAG names contain timeframe substrings (e.g. TREND_1D_BULLISH)
        # that cause false positives when regex-matched against indicator checks.
        # v29.5: Prefer _raw_* (pre-truncation) over truncated text to prevent
        # false citation errors from auditing text that was cut at max_length.
        _bull_check_text = (bull_structured.get('_raw_summary') or bull_structured.get('summary', '')) if bull_structured else bull_text
        _bear_check_text = (bear_structured.get('_raw_summary') or bear_structured.get('summary', '')) if bear_structured else bear_text
        _judge_check_text = ''
        if judge_decision:
            _judge_check_text = judge_decision.get('_raw_rationale') or judge_decision.get('rationale', '') or judge_text
        _risk_check_text = (risk_result.get('_raw_reason') or risk_result.get('reason', '')) if risk_result else _risk_text

        # v33.0: Deduplicate text-based errors across agents.
        # Downstream agents (Risk, Entry Timing) quote upstream summaries
        # (Bull/Bear) in their reason fields.  Without deduplication, the
        # same "超卖" in Bull's summary and Risk's reason (which quotes Bull)
        # generates zone_error ×2 = 10 points for one AI output choice.
        # Dedup key = error message content (role-independent).
        _seen_errors: set = set()

        for _role, _text in [
            ('bull', _bull_check_text), ('bear', _bear_check_text),
            ('judge', _judge_check_text),
            ('entry_timing', _et_text), ('risk', _risk_check_text),
        ]:
            if not _text:
                continue

            if gt_tech:
                # v25.0: DI comparison direction errors
                _di_errs = self._audit_di_citations(_text, gt_tech)
                for e in _di_errs:
                    if e not in _seen_errors:
                        _seen_errors.add(e)
                        report.citation_errors += 1
                        report.flags.append(f'CITATION_ERROR({_role}): {e}')

                # v26.0: MACD/SMA200/SMA cross/histogram comparison errors
                _cmp_errs = self._check_comparison_claims(_text, gt_tech)
                for e in _cmp_errs:
                    if e not in _seen_errors:
                        _seen_errors.add(e)
                        report.citation_errors += 1
                        report.flags.append(f'CITATION_ERROR({_role}): {e}')

                # v26.0: Numerical value accuracy errors (RSI/ADX/DI/BB/Volume)
                _val_errs = self._check_value_accuracy(_text, gt_tech)
                for e in _val_errs:
                    if e not in _seen_errors:
                        _seen_errors.add(e)
                        report.value_errors += 1
                        report.flags.append(f'VALUE_ERROR({_role}): {e}')

                # v26.0: Dollar-formatted price value errors (ATR/SMA200)
                _price_errs = self._check_price_values(_text, gt_tech)
                for e in _price_errs:
                    if e not in _seen_errors:
                        _seen_errors.add(e)
                        report.value_errors += 1
                        report.flags.append(f'VALUE_ERROR({_role}): {e}')

                # v31.1: MACD-family value errors (MACD/Signal/Histogram)
                _macd_errs = self._check_macd_values(_text, gt_tech)
                for e in _macd_errs:
                    if e not in _seen_errors:
                        _seen_errors.add(e)
                        report.value_errors += 1
                        report.flags.append(f'VALUE_ERROR({_role}): {e}')

                # v26.0: Zone/regime claim errors
                _zone_errs = self._check_zone_claims(_text, gt_tech)
                for e in _zone_errs:
                    if e not in _seen_errors:
                        _seen_errors.add(e)
                        report.zone_errors += 1
                        report.flags.append(f'ZONE_ERROR({_role}): {e}')

            # v26.0: Non-technical data source citation verification
            _nt_errs = self._check_nontech_claims(
                _text,
                gt_nontech.get('sentiment'),
                gt_nontech.get('order_flow'),
                gt_nontech.get('derivatives'),
                gt_nontech.get('orderbook'),
                gt_nontech.get('sr_zones'),
            )
            for e in _nt_errs:
                if e not in _seen_errors:
                    _seen_errors.add(e)
                    report.value_errors += 1
                    report.flags.append(f'VALUE_ERROR({_role}): {e}')

        # 3b. v34.0: Phantom citation detection (AI citing unavailable data)
        for _role, _text in [
            ('bull', _bull_check_text), ('bear', _bear_check_text),
            ('judge', _judge_check_text),
            ('entry_timing', _et_text), ('risk', _risk_check_text),
        ]:
            if not _text:
                continue
            _phantom_errs = self._check_phantom_citations(
                _text,
                gt_nontech.get('sentiment'),
                gt_nontech.get('order_flow'),
                gt_nontech.get('derivatives'),
                gt_nontech.get('orderbook'),
            )
            for e in _phantom_errs:
                if e not in _seen_errors:
                    _seen_errors.add(e)
                    report.phantom_citations += 1
                    report.flags.append(f'PHANTOM_CITATION({_role}): {e}')

        # 3c. v34.0: Narrative misread detection (contradictory adjective for value)
        # v36.1: Also check reasoning text — narrative misread patterns
        # (RSI+adjective) are safe for reasoning because \b word boundaries
        # on 'bullish' prevent false positives from REASON_TAG names
        # (e.g. MOMENTUM_4H_BULLISH won't match \bbullish\b due to _BULLISH_)
        _bull_reasoning = ''
        if bull_structured:
            _bull_reasoning = bull_structured.get('_raw_reasoning') or bull_structured.get('reasoning', '')
        _bear_reasoning = ''
        if bear_structured:
            _bear_reasoning = bear_structured.get('_raw_reasoning') or bear_structured.get('reasoning', '')
        _judge_reasoning = ''
        if judge_decision:
            _judge_reasoning = judge_decision.get('_raw_reasoning') or judge_decision.get('reasoning', '')

        for _role, _text in [
            ('bull', _bull_check_text), ('bear', _bear_check_text),
            ('judge', _judge_check_text),
            ('bull', _bull_reasoning), ('bear', _bear_reasoning),
            ('judge', _judge_reasoning),
        ]:
            if not _text or not gt_tech:
                continue
            _narr_errs = self._check_narrative_misread(_text, gt_tech)
            for e in _narr_errs:
                if e not in _seen_errors:
                    _seen_errors.add(e)
                    report.narrative_misreads += 1
                    report.flags.append(f'NARRATIVE_MISREAD({_role}): {e}')

        # 3d. v34.0: Contradictory data omission (informational)
        _scores = ctx.scores
        for _role, _text in [('bull', _bull_check_text), ('bear', _bear_check_text)]:
            if not _text:
                continue
            _omit_flags = self._check_contradictory_omission(
                _role, _text, _scores)
            for f in _omit_flags:
                report.flags.append(f'CONTRADICTORY_OMISSION: {f}')

        # ── v34.0: Logic-level coherence checks ──

        # 3e. Reason-Signal Alignment (decisive_reasons vs decision)
        if judge_decision and judge_decision.get('decision', '') in ('LONG', 'SHORT'):
            _rsa_penalty, _rsa_flag = self._check_reason_signal_alignment(
                judge_decision.get('decision', ''),
                judge_decision.get('decisive_reasons', []))
            if _rsa_penalty > 0:
                report.reason_signal_conflict = _rsa_penalty
                report.flags.append(f'REASON_SIGNAL_CONFLICT: {_rsa_flag}')

        # 3f. Signal-Score Divergence (informational, no penalty)
        if judge_decision and _scores and judge_decision.get('decision', '') in ('LONG', 'SHORT'):
            _ssd_flag = self._check_signal_score_divergence(
                _scores.get('net', ''), judge_decision.get('decision', ''))
            if _ssd_flag:
                report.flags.append(f'SIGNAL_SCORE_DIVERGENCE: {_ssd_flag}')

        # 3g. Confidence-Risk Coherence
        if judge_decision and _scores:
            _risk_env = _scores.get('risk_env', {})
            _crc_penalty, _crc_flag = self._check_confidence_risk_coherence(
                judge_decision.get('confidence', ''),
                _risk_env.get('score', 0),
                _risk_env.get('level', 'LOW'))
            if _crc_penalty > 0:
                report.confidence_risk_conflict = _crc_penalty
                report.flags.append(f'CONFIDENCE_RISK_CONFLICT: {_crc_flag}')

        # 3h. Debate Conviction Spread (informational)
        if ctx.bull_output is not None and ctx.bear_output is not None:
            _bull_conv = ctx.bull_output.get('conviction', 0.5)
            _bear_conv = ctx.bear_output.get('conviction', 0.5)
            _dq_flag = self._check_debate_quality(_bull_conv, _bear_conv)
            if _dq_flag:
                report.flags.append(f'DEBATE_CONVERGENCE: {_dq_flag}')

        # 3i. Decisive Reasons Diversity (informational)
        if judge_decision and judge_decision.get('decisive_reasons'):
            _rd_flag = self._check_reason_diversity(
                judge_decision.get('decisive_reasons', []))
            if _rd_flag:
                report.flags.append(f'SINGLE_DIMENSION_DECISION: {_rd_flag}')

        # 3j. Shallow Round 2 Detection (informational, v34.1)
        if ctx.bull_output is not None and ctx.bear_output is not None:
            _sr2_flag = self._check_debate_shallow_round2(
                ctx.bull_output, ctx.bear_output)
            if _sr2_flag:
                report.flags.append(f'DEBATE_SHALLOW_R2: {_sr2_flag}')

        # 4. Counter-trend detection
        if judge_decision and gt_tech:
            ct = self._check_counter_trend(judge_decision, gt_tech)
            report.counter_trend_detected = ct
            if ct and entry_timing_result:
                ctr = entry_timing_result.get('counter_trend_risk', 'NONE')
                report.counter_trend_flagged_by_entry_timing = ctr in ('HIGH', 'MODERATE', 'LOW')
                if not report.counter_trend_flagged_by_entry_timing:
                    report.flags.append(
                        'COUNTER_TREND_NOT_FLAGGED: Entry Timing did not flag counter-trend risk')

        # 5. Calculate overall score
        report.overall_score = self._calculate_score(report)

        # 6. Collect all flags from sub-results into report.flags
        for role, result in report.agent_results.items():
            for f in result.flags:
                report.flags.append(f"{role}: {f}")
        if report.confluence_audit:
            for f in report.confluence_audit.flags:
                report.flags.append(f"confluence: {f}")

        return report

    # ------------------------------------------------------------------
    # Internal: unified per-agent audit
    # ------------------------------------------------------------------

    def _audit_agent(
        self, role: str, text: str, adx_1d: float,
        required_override: Optional[Set[str]] = None,
        tags: Optional[List[str]] = None,
        weak_only_categories: Optional[Set[str]] = None,
    ) -> AgentAuditResult:
        """Full audit of a single agent: coverage + citations + SKIP + MTF.

        v27.0: When `tags` is provided (structured output mode), data coverage
        is primarily determined by mapping REASON_TAGS to data categories.
        v29.1: Text-based regex coverage now SUPPLEMENTS tag coverage. Tags
        take priority; text fills gaps for categories not mapped to any tag.
        v29.4: weak_only_categories tracks categories covered only by weak/neutral
        tags. If AI selected a weak tag for such a category, it's recorded as
        neutral_acknowledged (AI analyzed but found non-actionable). If AI didn't
        select any tag, it's recorded as unconfirmed_neutral.
        """
        result = AgentAuditResult(agent_role=role)
        required = (required_override if required_override is not None
                     else _AGENT_REQUIRED_CATEGORIES.get(role, set()))
        if not text and not tags:
            result.flags.append('EMPTY_OUTPUT')
            result.missing_categories = list(required)
            return result

        # --- Data coverage ---
        covered_categories: Set[str] = set()

        if tags:
            # v27.0 tag-based coverage: map REASON_TAGS to data categories
            # v29.0: multi-category support — one tag can cover multiple categories
            for tag in tags:
                cats = _TAG_TO_CATEGORIES.get(tag, [])
                for cat in cats:
                    covered_categories.add(cat)
                    result.citations.setdefault(cat, []).append(tag)

        # v29.1: ALWAYS also check reasoning/summary text for coverage.
        # In structured mode (v27.0+), agents output focused tag sets but their
        # reasoning field (max 500 chars) often references additional data
        # categories (e.g. "Order flow: Taker buy ratio 0.71") that don't map
        # to a specific tag. Combining both sources prevents false negatives.
        if text:
            for category, patterns in _DATA_CATEGORY_MARKERS.items():
                if category in covered_categories:
                    continue  # Already covered by tags, skip regex
                for p in patterns:
                    m = re.search(p, text, re.IGNORECASE)
                    if m:
                        covered_categories.add(category)
                        result.citations.setdefault(category, []).append(
                            f"text:{m.group(0)}")
                        break  # One match per category is enough

        for category in _DATA_CATEGORY_MARKERS:
            result.data_coverage[category] = category in covered_categories

        # Missing required categories
        for cat in sorted(required):
            if not result.data_coverage.get(cat, False):
                result.missing_categories.append(cat)

        # v32.1 fix: empty set() means "no categories required" (e.g. Risk
        # Manager skipped for HOLD signal). `if required` is falsy for set(),
        # incorrectly falling back to all markers. Use `is not None` instead.
        total = len(required) if required is not None else len(_DATA_CATEGORY_MARKERS)
        covered = total - len(result.missing_categories)
        # total=0 means no categories required (e.g. Risk Manager skipped) → 100%
        result.coverage_rate = covered / total if total > 0 else 1.0

        if result.missing_categories:
            result.flags.append(f"MISSING_DATA: {', '.join(result.missing_categories)}")

        # v29.4: Track neutral data acknowledgment for weak-signal categories.
        # These categories were excluded from _required (AI not penalized for ignoring),
        # but we track whether AI acknowledged them via neutral tags.
        if weak_only_categories:
            for cat in sorted(weak_only_categories):
                if cat in covered_categories:
                    # AI selected a neutral/weak tag → confirmed it analyzed the data
                    result.neutral_acknowledged.append(cat)
                else:
                    # AI didn't select any tag → unclear if data was analyzed
                    result.unconfirmed_neutral.append(cat)
            if result.unconfirmed_neutral:
                result.flags.append(
                    f"UNCONFIRMED_NEUTRAL: {', '.join(result.unconfirmed_neutral)}")

        # --- SKIP signal violations ---
        self._check_skip_signal_usage(result, text, adx_1d)

        # --- MTF responsibility ---
        self._check_mtf_responsibility(result, text, role, adx_1d)

        return result

    # ------------------------------------------------------------------
    # Internal: SKIP signal detection
    # ------------------------------------------------------------------

    def _check_skip_signal_usage(
        self, result: AgentAuditResult, text: str, adx_1d: float,
    ) -> None:
        """
        Check if agent cited SKIP-tier signals as evidence.

        Uses _SIGNAL_KEY_PATTERNS to detect mentions of specific indicators
        per timeframe, then cross-references with _SIGNAL_ANNOTATIONS to
        determine if that signal is SKIP in the current regime.
        """
        skip_signals = _get_skip_signals_for_regime(adx_1d)
        if not skip_signals:
            return

        for sig_key in skip_signals:
            patterns = _SIGNAL_KEY_PATTERNS.get(sig_key)
            if not patterns:
                continue
            for p in patterns:
                m = re.search(p, text, re.IGNORECASE)
                if m:
                    _, multiplier, tier = _get_multiplier(sig_key, adx_1d)
                    violation = (
                        f"{sig_key} (×{multiplier:.1f} {tier.upper()}) "
                        f"cited: \"{m.group(0)}\""
                    )
                    result.skip_signal_violations.append(violation)
                    result.flags.append(f"SKIP_SIGNAL: {sig_key} used in {result.agent_role}")
                    break  # One match per signal key is enough

    # ------------------------------------------------------------------
    # Internal: MTF responsibility
    # ------------------------------------------------------------------

    def _check_mtf_responsibility(
        self, result: AgentAuditResult, text: str,
        role: str, adx_1d: float,
    ) -> None:
        """Verify agent evaluates correct timeframes per its role.

        v29.6: Root-cause fix — use TAG-BASED structural analysis in structured
        mode (v27.0+) instead of fragile text regex. Tags are deterministic;
        regex cannot reliably distinguish "direction claim" from "technical
        observation" in natural language.

        Tag-based MTF check: If agent's tags reference ONLY 30M data categories
        (technical_30m) without any higher-TF categories (mtf_1d, mtf_4h), the
        agent is basing direction on 30M alone — a genuine MTF violation.
        If higher TF tags are present, 30M tags are supplementary context, not
        the directional basis.
        """
        if role in ('bull', 'bear'):
            # ADX>=25: Bull/Bear should NOT base direction on 30M
            if adx_1d >= 25:
                # v29.6: Tag-based structural check (primary, deterministic).
                # Check if agent referenced higher-TF data via tags.
                tag_categories = set()
                if result.citations:
                    for cat in result.citations:
                        tag_categories.add(cat)

                has_higher_tf = tag_categories & {'mtf_1d', 'mtf_4h'}
                has_30m = 'technical_30m' in tag_categories

                if has_30m and not has_higher_tf:
                    # Agent cited ONLY 30M data, no 1D/4H — genuine MTF violation
                    result.mtf_violations.append(
                        '30M_DIRECTION: Direction based solely on 30M data '
                        '(no 1D/4H tags cited)')
                    result.flags.append(
                        'MTF_VIOLATION: 30M used for direction in ADX>=25')

        elif role == 'entry_timing':
            # Entry Timing MUST evaluate 30M execution layer
            # v27.0: Also check tag-based coverage — structured output may not
            # mention "30M" in reason text but covers technical_30m via tags
            # (e.g. RSI_CARDWELL_BEAR, BB_LOWER_ZONE map to technical_30m).
            has_30m_text = bool(re.search(r'30[Mm]|执行层|execution', text, re.IGNORECASE))
            has_30m_tag = result.data_coverage.get('technical_30m', False)
            if not has_30m_text and not has_30m_tag:
                result.mtf_violations.append(
                    'MISSING_30M: Entry Timing did not evaluate 30M execution layer')
                result.flags.append('MTF_VIOLATION: 30M not evaluated by Entry Timing')

        elif role == 'risk':
            # Risk Manager should NOT re-judge direction (v4.14)
            direction_judgment = re.search(
                r'(?:应该|should)\s*(?:做多|做空|LONG|SHORT|开多|开空)',
                text, re.IGNORECASE,
            )
            if direction_judgment:
                result.mtf_violations.append(
                    'DIRECTION_OVERRIDE: Risk Manager attempted to judge direction')
                result.flags.append('MTF_VIOLATION: Risk Manager judged direction')

    # ------------------------------------------------------------------
    # Internal: confluence verification
    # ------------------------------------------------------------------

    def _audit_confluence(self, judge_decision: Dict[str, Any]) -> ConfluenceAuditResult:
        """Verify Judge's confluence alignment accuracy."""
        result = ConfluenceAuditResult()

        confluence = judge_decision.get('confluence', {})
        if not confluence:
            result.flags.append('NO_CONFLUENCE: Judge output missing confluence field')
            return result

        # Use original Judge decision before Entry Timing override.
        # When Entry Timing REJECTs, it changes decision to HOLD but the
        # Judge's confluence layers still describe the original signal direction.
        direction_signal = judge_decision.get(
            '_timing_original_signal', judge_decision.get('decision', 'HOLD')
        )
        aligned_count = 0

        if direction_signal in ('LONG', 'SHORT'):
            # Directional signal: verify each layer's direction matches
            for layer_key in ('trend_1d', 'momentum_4h', 'levels_30m', 'derivatives'):
                layer_text = str(confluence.get(layer_key, ''))
                result.layers_declared[layer_key] = layer_text

                layer_dir = self._extract_direction(layer_text)
                if layer_dir:
                    expected_dir = 'BULLISH' if direction_signal == 'LONG' else 'BEARISH'
                    if layer_dir == expected_dir:
                        aligned_count += 1

            result.aligned_layers_declared = int(confluence.get('aligned_layers', 0))
            result.aligned_layers_actual = aligned_count
        else:
            # HOLD: no directional alignment to verify — accept declared count.
            # The Judge's aligned_layers in a HOLD context indicates how many
            # layers agreed with the winning_side, but without a directional
            # signal the auditor cannot cross-validate layer directions.
            for layer_key in ('trend_1d', 'momentum_4h', 'levels_30m', 'derivatives'):
                result.layers_declared[layer_key] = str(confluence.get(layer_key, ''))
            declared = int(confluence.get('aligned_layers', 0))
            result.aligned_layers_declared = declared
            result.aligned_layers_actual = declared

        if result.aligned_layers_declared != result.aligned_layers_actual:
            result.alignment_mismatch = True
            result.flags.append(
                f'ALIGNMENT_MISMATCH: declared={result.aligned_layers_declared} '
                f'actual={result.aligned_layers_actual}')

        # Use original Judge confidence before Entry Timing override
        result.confidence_declared = judge_decision.get(
            '_timing_original_confidence', judge_decision.get('confidence', 'LOW')
        )
        result.confidence_expected = self._expected_confidence(result.aligned_layers_actual)

        if result.confidence_declared != result.confidence_expected:
            if not self._confidence_within_tolerance(
                result.confidence_declared, result.confidence_expected
            ):
                result.confidence_mismatch = True
                result.flags.append(
                    f'CONFIDENCE_MISMATCH: declared={result.confidence_declared} '
                    f'expected={result.confidence_expected} '
                    f'(from {result.aligned_layers_actual} aligned layers)')

        return result

    # ------------------------------------------------------------------
    # Internal: DI citation accuracy check (v25.0)
    # ------------------------------------------------------------------

    def _audit_di_citations(
        self, text: str, technical_data: Optional[Dict[str, Any]],
    ) -> List[str]:
        """Detect DI+/DI- comparison reversal errors in any agent text.

        Returns list of error descriptions (empty if no errors).
        Checks all 3 timeframes (30M, 4H, 1D).

        v31.0: Rewritten with tolerance-based value matching. Previous
        approach required exact 1-decimal formatting (e.g. "23.4") which
        missed rounded citations like "DI+ 23 < DI- 18". Now extracts
        any numeric value near DI+/DI- comparison operators and validates
        within ±2.0 tolerance against ground truth before checking
        comparison direction.
        """
        if not text or not technical_data:
            return []

        errors: List[str] = []
        _timeframes = [
            ('30M', technical_data),
            ('4H', technical_data.get('mtf_decision_layer', {})),
            ('1D', technical_data.get('mtf_trend_layer', {})),
        ]

        # Pattern: "DI+(X) < DI-(Y)" or "DI+ X < DI- Y" or "DI+:X < DI-:Y"
        # Captures cited values and comparison operator
        _di_plus_cmp_minus = re.compile(
            r'DI\+\s*[\(:]?\s*([\d]+\.?\d*)\s*[\)]?\s*([<>])\s*'
            r'DI[\-−]\s*[\(:]?\s*([\d]+\.?\d*)',
            re.IGNORECASE,
        )
        # Reverse order: "DI-(Y) > DI+(X)"
        _di_minus_cmp_plus = re.compile(
            r'DI[\-−]\s*[\(:]?\s*([\d]+\.?\d*)\s*[\)]?\s*([<>])\s*'
            r'DI\+\s*[\(:]?\s*([\d]+\.?\d*)',
            re.IGNORECASE,
        )

        _DI_TOLERANCE = 2.0  # Accept cited values within ±2.0 of actual

        for tf_label, tf_data in _timeframes:
            if not tf_data or not isinstance(tf_data, dict):
                continue
            raw_plus = tf_data.get('di_plus')
            raw_minus = tf_data.get('di_minus')
            if raw_plus is None or raw_minus is None:
                continue
            di_plus = float(raw_plus)
            di_minus = float(raw_minus)
            if abs(di_plus - di_minus) < 0.05:
                continue  # Too close to call — skip

            actual_dir = 'BULLISH' if di_plus > di_minus else 'BEARISH'

            # Check "DI+(X) <> DI-(Y)" patterns
            for m in _di_plus_cmp_minus.finditer(text):
                try:
                    cited_plus = float(m.group(1))
                    op = m.group(2)
                    cited_minus = float(m.group(3))
                except (ValueError, IndexError):
                    continue
                # Verify cited values are close to actual (anchors to this TF)
                if (abs(cited_plus - di_plus) > _DI_TOLERANCE
                        or abs(cited_minus - di_minus) > _DI_TOLERANCE):
                    continue
                # Check comparison direction
                if op == '<' and di_plus > di_minus:
                    errors.append(
                        f'{tf_label}: DI+={di_plus:.1f}>{di_minus:.1f}={actual_dir} '
                        f'but agent claimed DI+({cited_plus:.0f}) < DI-({cited_minus:.0f})')
                    break
                elif op == '>' and di_plus < di_minus:
                    errors.append(
                        f'{tf_label}: DI+={di_plus:.1f}<{di_minus:.1f}={actual_dir} '
                        f'but agent claimed DI+({cited_plus:.0f}) > DI-({cited_minus:.0f})')
                    break

            # Check "DI-(Y) <> DI+(X)" patterns (reverse order)
            for m in _di_minus_cmp_plus.finditer(text):
                try:
                    cited_minus = float(m.group(1))
                    op = m.group(2)
                    cited_plus = float(m.group(3))
                except (ValueError, IndexError):
                    continue
                if (abs(cited_plus - di_plus) > _DI_TOLERANCE
                        or abs(cited_minus - di_minus) > _DI_TOLERANCE):
                    continue
                # Note: operator direction is reversed (DI- op DI+)
                if op == '>' and di_plus > di_minus:
                    errors.append(
                        f'{tf_label}: DI+={di_plus:.1f}>{di_minus:.1f}={actual_dir} '
                        f'but agent claimed DI-({cited_minus:.0f}) > DI+({cited_plus:.0f})')
                    break
                elif op == '<' and di_plus < di_minus:
                    errors.append(
                        f'{tf_label}: DI+={di_plus:.1f}<{di_minus:.1f}={actual_dir} '
                        f'but agent claimed DI-({cited_minus:.0f}) < DI+({cited_plus:.0f})')
                    break

        return errors

    # ------------------------------------------------------------------
    # Internal: value accuracy check (v26.0)
    # ------------------------------------------------------------------

    def _check_value_accuracy(
        self, text: str, technical_data: Dict[str, Any],
    ) -> List[str]:
        """Check cited numerical values against actual data across all timeframes.

        Detects value fabrication: AI cites a number that doesn't match reality.
        Uses per-indicator absolute tolerance to account for rounding.
        """
        if not text or not technical_data:
            return []

        errors: List[str] = []

        timeframes = [
            ('30M', technical_data),
            ('4H', technical_data.get('mtf_decision_layer') or {}),
            ('1D', technical_data.get('mtf_trend_layer') or {}),
        ]

        for tf_label, tf_data in timeframes:
            if not tf_data or not isinstance(tf_data, dict):
                continue
            tf_regexes = _TF_CITE_PATTERNS.get(tf_label, [])

            for ind_name, data_key, ind_regex, tolerance, v_min, v_max, scale in _VALUE_VERIFY_INDICATORS:
                actual_raw = tf_data.get(data_key)
                if actual_raw is None:
                    continue
                try:
                    actual = float(actual_raw) * scale
                except (ValueError, TypeError):
                    continue
                if actual == 0:
                    continue  # Likely uninitialized

                cited = self._extract_indicator_value(
                    text, tf_regexes, ind_regex, v_min, v_max,
                    tf_label=tf_label,
                )
                if cited is not None and abs(cited - actual) > tolerance:
                    errors.append(
                        f'{tf_label} {ind_name}: actual={actual:.1f}, '
                        f'cited={cited:.1f} (off by {abs(cited - actual):.1f})')

        return errors

    # Per-TF "other TF" patterns for Pattern 3 post-validation (v29.5).
    # When Pattern 3 matches "ADX=36.8 ... 4H", check that no OTHER TF label
    # appears within 20 chars before the indicator — if it does, the value
    # belongs to that other TF, not the one we're trying to match.
    # Fixes false positive: "1D趋势(ADX=36.8)和4H动量" → 36.8 is 1D, not 4H.
    _PATTERN3_OTHER_TF: Dict[str, str] = {
        '30M': r'(?:4[Hh]|1[Dd]|决策层|趋势层)',
        '4H':  r'(?:30[Mm]|1[Dd]|执行层|趋势层)',
        '1D':  r'(?:30[Mm]|4[Hh]|执行层|决策层)',
    }

    def _extract_indicator_value(
        self, text: str, tf_regexes: List[str],
        ind_regex: str, v_min: float, v_max: float,
        tf_label: str = '',
    ) -> Optional[float]:
        """Extract the numerical value an agent cited for indicator@timeframe.

        Three pattern strategies (ordered by specificity):
        1. "RSI(4H): 45.1" — indicator + parenthetical tf + value
        2. "4H RSI: 45.1"  — tf context then indicator then value
        3. "RSI: 45.1 ... 4H" — indicator + value then tf nearby
           v29.5: Post-validates that no OTHER TF label precedes the indicator
           within 20 chars, preventing cross-TF value attribution in compact text
           like "1D趋势(ADX=36.8)和4H动量".

        Returns first valid extracted value, or None if not found.
        """
        # Negative lookahead rejects numbers followed by letters (e.g. "30M")
        # v31.0: Optional negative sign for indicators like Extension Ratio
        # that can be negative (e.g. "-2.5 ATR").
        # v31.1: Optional +/- sign — MACD Histogram uses "+0.0004" format.
        number_pat = r'([+\-]?[\d]+\.?\d*)(?![A-Za-z])'

        # Tempered greedy token: advance char-by-char but stop at any TF mention.
        # Prevents cross-matching like "1D RSI=62. 4H ADX: 35" → 1D ADX.
        _no_other_tf = r'(?:(?!(?:30[Mm]|4[Hh]|1[Dd]|执行层|决策层|趋势层)).)'

        # v29.5: Other-TF pattern for Pattern 3 post-validation
        _other_tf_pat = self._PATTERN3_OTHER_TF.get(tf_label, '')

        for tf_p in tf_regexes:
            patterns = [
                # "RSI(4H): 45.1" or "RSI (4H) at 45.1"
                rf'{ind_regex}\s*[\(]?\s*{tf_p}\s*[\)]?\s*[:\s=at]*\s*{number_pat}',
                # "4H RSI: 45.1" — TF then indicator (no other TF in between)
                rf'{tf_p}{_no_other_tf}{{0,20}}?{ind_regex}\s*[:\s=at]*\s*{number_pat}',
                # "RSI: 45.1 (4H)" — value before tf mention (tight window)
                # v26.1: Added _no_other_tf guard to prevent cross-TF matching
                # e.g. "1D ADX=48.6) 与 4H" was incorrectly extracting 48.6 as 4H ADX
                rf'{ind_regex}\s*[:\s=at]*\s*{number_pat}{_no_other_tf}{{0,8}}?{tf_p}',
            ]

            for pat_idx, pattern in enumerate(patterns):
                m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if m:
                    # v29.5→v30.5: Pattern 3 post-validation — reject if another TF
                    # label precedes the indicator within 50 chars (value belongs to
                    # that TF). Widened from 20→50 chars to cover Chinese text where
                    # TF label and indicator value can be 30+ chars apart, e.g.:
                    # "1D ADX=35.5(>25)确认下跌趋势，DI- 26.3 > DI+ 17.9。4H"
                    # Here "DI+ 17.9" is 34 chars from "1D", old 20-char window missed it.
                    if pat_idx == 2 and _other_tf_pat:
                        pre_window = text[max(0, m.start() - 50):m.start()]
                        if re.search(_other_tf_pat, pre_window):
                            continue  # Value belongs to a different TF
                    try:
                        val = float(m.group(1))
                        if v_min <= val <= v_max:
                            return val
                    except (ValueError, IndexError):
                        continue

        return None

    # ------------------------------------------------------------------
    # Internal: dollar-formatted price value check (v26.0)
    # ------------------------------------------------------------------

    def _check_price_values(
        self, text: str, technical_data: Dict[str, Any],
    ) -> List[str]:
        """Check dollar-formatted price values (ATR, SMA200) across timeframes.

        Uses percentage tolerance instead of absolute tolerance because
        these values scale with price level.
        """
        if not text or not technical_data:
            return []

        errors: List[str] = []
        # ATR: 30M primary, 4H/1D if available
        # SMA200: 1D only
        tf_sources = [
            ('30M', technical_data),
            ('4H', technical_data.get('mtf_decision_layer') or {}),
            ('1D', technical_data.get('mtf_trend_layer') or {}),
        ]

        for tf_label, tf_data in tf_sources:
            if not tf_data or not isinstance(tf_data, dict):
                continue
            tf_regexes = _TF_CITE_PATTERNS.get(tf_label, [])

            for ind_name, data_key, label_regex, pct_tol in _PRICE_VERIFY_INDICATORS:
                actual_raw = tf_data.get(data_key)
                if actual_raw is None:
                    continue
                try:
                    actual = float(actual_raw)
                except (ValueError, TypeError):
                    continue
                if actual <= 0:
                    continue

                cited = self._extract_dollar_value(text, tf_regexes, label_regex,
                                                    tf_label=tf_label)
                if cited is not None and cited > 0:
                    pct_diff = abs(cited - actual) / actual * 100
                    if pct_diff > pct_tol:
                        errors.append(
                            f'{tf_label} {ind_name}: actual=${actual:,.2f}, '
                            f'cited=${cited:,.2f} (off by {pct_diff:.1f}%)')

        return errors

    # ------------------------------------------------------------------
    # Internal: MACD-family value check (v31.1)
    # ------------------------------------------------------------------

    def _check_macd_values(
        self, text: str, technical_data: Dict[str, Any],
    ) -> List[str]:
        """Check MACD / Signal / Histogram cited values across all timeframes.

        v31.1: MACD values have no natural bounds and scale with asset price,
        so we use percentage tolerance instead of absolute tolerance.
        When |actual| is near zero (< min_abs_threshold), the comparison is
        skipped because percentage difference becomes unstable.
        """
        if not text or not technical_data:
            return []

        errors: List[str] = []

        tf_sources = [
            ('30M', technical_data),
            ('4H', technical_data.get('mtf_decision_layer') or {}),
            ('1D', technical_data.get('mtf_trend_layer') or {}),
        ]

        for tf_label, tf_data in tf_sources:
            if not tf_data or not isinstance(tf_data, dict):
                continue
            tf_regexes = _TF_CITE_PATTERNS.get(tf_label, [])

            for ind_name, data_key, ind_regex, pct_tol, min_abs in _MACD_VERIFY_INDICATORS:
                actual_raw = tf_data.get(data_key)
                if actual_raw is None:
                    continue
                try:
                    actual = float(actual_raw)
                except (ValueError, TypeError):
                    continue

                # Skip near-zero values — percentage comparison is unstable
                if abs(actual) < min_abs:
                    continue

                # MACD can be negative; use wide extraction bounds
                cited = self._extract_indicator_value(
                    text, tf_regexes, ind_regex,
                    v_min=-1e9, v_max=1e9,
                    tf_label=tf_label,
                )
                if cited is None:
                    continue

                # Skip if cited is also near zero
                if abs(cited) < min_abs:
                    continue

                pct_diff = abs(cited - actual) / abs(actual) * 100
                if pct_diff > pct_tol:
                    errors.append(
                        f'{tf_label} {ind_name}: actual={actual:.4f}, '
                        f'cited={cited:.4f} (off by {pct_diff:.1f}%)')

        return errors

    def _extract_dollar_value(
        self, text: str, tf_regexes: List[str], label_regex: str,
        tf_label: str = '',
    ) -> Optional[float]:
        """Extract a dollar-formatted value near a label and timeframe mention.

        Handles formats: "$94,800", "$94,800.00", "$1,234.56"
        v30.5: Added Pattern 3 cross-TF post-validation (same as _extract_indicator_value).
        """
        dollar_pat = r'\$\s*([\d,]+(?:\.\d+)?)'
        # Tempered greedy: no other TF mention between matched TF and indicator
        _no_tf = r'(?:(?!(?:30[Mm]|4[Hh]|1[Dd]|执行层|决策层|趋势层)).)'
        _other_tf_pat = self._PATTERN3_OTHER_TF.get(tf_label, '')

        for tf_p in tf_regexes:
            patterns = [
                # "ATR(30M): $1,234.56" or "ATR (30M) = $1,234.56"
                rf'{label_regex}\s*[\(]?\s*{tf_p}\s*[\)]?\s*[:\s=]*\s*{dollar_pat}',
                # "30M ... ATR: $1,234.56" (no other TF in between)
                rf'{tf_p}{_no_tf}{{0,30}}?{label_regex}\s*[:\s=]*\s*{dollar_pat}',
                # "ATR: $1,234.56 (30M)" (tight reverse window, no other TF in between)
                rf'{label_regex}\s*[:\s=]*\s*{dollar_pat}{_no_tf}{{0,8}}?{tf_p}',
            ]

            for pat_idx, pattern in enumerate(patterns):
                m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if m:
                    # v30.5: Pattern 3 post-validation (same as _extract_indicator_value)
                    if pat_idx == 2 and _other_tf_pat:
                        pre_window = text[max(0, m.start() - 50):m.start()]
                        if re.search(_other_tf_pat, pre_window):
                            continue  # Value belongs to a different TF
                    try:
                        val = float(m.group(1).replace(',', ''))
                        if val > 0:
                            return val
                    except (ValueError, IndexError):
                        continue

        return None

    # ------------------------------------------------------------------
    # Internal: comparison direction claims (v26.0)
    # ------------------------------------------------------------------

    def _check_comparison_claims(
        self, text: str, technical_data: Dict[str, Any],
    ) -> List[str]:
        """Check directional comparison claims against actual data.

        v26.0 checks:
        - MACD vs Signal crossover direction (per TF)
        - Price vs SMA200 position (above/below)
        - SMA20 vs SMA50 golden/death cross (per TF)
        - MACD Histogram positive/negative (per TF)
        v31.3 checks:
        - DI+/DI- crossover direction text claims (per TF)
        - EMA 12/26 crossover direction text claims (per TF)
        """
        if not text or not technical_data:
            return []

        errors: List[str] = []

        timeframes = [
            ('30M', technical_data),
            ('4H', technical_data.get('mtf_decision_layer') or {}),
            ('1D', technical_data.get('mtf_trend_layer') or {}),
        ]
        # v31.0: Include Chinese TF aliases for comparison claim detection
        # in mixed-language text (e.g. "决策层 MACD 死叉").
        tf_aliases = {
            '30M': r'(?:30[Mm]|执行层)', '4H': r'(?:4[Hh]|决策层)', '1D': r'(?:1[Dd]|趋势层)',
        }

        for tf_label, tf_data in timeframes:
            if not tf_data or not isinstance(tf_data, dict):
                continue
            tf_p = tf_aliases[tf_label]

            # -- MACD vs Signal direction --
            # v30.5: Use _claims_near_tf for cross-TF exclusion instead of
            # raw regex window. Previous ±100 char window caused false errors
            # when "1D bearish trend ... 4H MACD bearish cross" attributed
            # the 4H MACD claim to 1D timeframe.
            macd_raw = tf_data.get('macd')
            signal_raw = tf_data.get('macd_signal')
            if macd_raw is not None and signal_raw is not None:
                try:
                    macd_val = float(macd_raw)
                    signal_val = float(signal_raw)
                except (ValueError, TypeError):
                    macd_val, signal_val = 0, 0

                if abs(macd_val - signal_val) >= 0.0001:
                    actual_bullish = macd_val > signal_val
                    # v31.2: dual-order patterns — detect both "MACD bearish cross"
                    # and "Signal crossed below MACD" / "信号线下穿MACD" phrasings
                    bearish_claim = (
                        self._claims_near_tf(
                            text, tf_p,
                            r'MACD.{0,20}(?:bearish|死叉|空头).{0,10}(?:cross|交叉|signal)',
                        ) or self._claims_near_tf(
                            text, tf_p,
                            r'(?:[Ss]ignal|信号线?).{0,10}(?:cross(?:ed)?\s*(?:below|under)|下穿).{0,10}MACD',
                        )
                    )
                    bullish_claim = (
                        self._claims_near_tf(
                            text, tf_p,
                            r'MACD.{0,20}(?:bullish|金叉|多头).{0,10}(?:cross|交叉|signal)',
                        ) or self._claims_near_tf(
                            text, tf_p,
                            r'(?:[Ss]ignal|信号线?).{0,10}(?:cross(?:ed)?\s*(?:above|over)|上穿).{0,10}MACD',
                        )
                    )
                    if actual_bullish and bearish_claim:
                        errors.append(
                            f'{tf_label} MACD: {macd_val:.4f}>{signal_val:.4f}=BULLISH '
                            f'but agent claimed bearish crossover')
                    elif not actual_bullish and bullish_claim:
                        errors.append(
                            f'{tf_label} MACD: {macd_val:.4f}<{signal_val:.4f}=BEARISH '
                            f'but agent claimed bullish crossover')

            # -- MACD Histogram positive/negative (v26.0) --
            hist_raw = tf_data.get('macd_histogram')
            if hist_raw is None and macd_raw is not None and signal_raw is not None:
                try:
                    hist_raw = float(macd_raw) - float(signal_raw)
                except (ValueError, TypeError):
                    hist_raw = None
            if hist_raw is not None:
                try:
                    hist_val = float(hist_raw)
                except (ValueError, TypeError):
                    hist_val = 0
                if abs(hist_val) >= 0.0001:
                    hist_positive = hist_val > 0
                    # v31.2: expanded patterns — also detect Chinese "直方图"
                    if hist_positive and self._claims_near_tf(
                        text, tf_p,
                        r'(?:histogram|hist|直方图).{0,15}(?:negative|下降|空头|bearish)',
                    ):
                        errors.append(
                            f'{tf_label} MACD Histogram: {hist_val:.4f}>0 (positive) '
                            f'but agent claimed negative')
                    elif not hist_positive and self._claims_near_tf(
                        text, tf_p,
                        r'(?:histogram|hist|直方图).{0,15}(?:positive|上升|多头|bullish)',
                    ):
                        errors.append(
                            f'{tf_label} MACD Histogram: {hist_val:.4f}<0 (negative) '
                            f'but agent claimed positive')

            # -- DI+/DI- crossover direction (v31.3) --
            # Complements _audit_di_citations() which checks numerical comparisons
            # (e.g. "DI+ 23 > DI- 18"). This checks textual crossover claims
            # (e.g. "DI bullish cross", "DI+ crossed above DI-", "DI+上穿DI-").
            di_plus_raw = tf_data.get('di_plus')
            di_minus_raw = tf_data.get('di_minus')
            if di_plus_raw is not None and di_minus_raw is not None:
                try:
                    di_plus_v = float(di_plus_raw)
                    di_minus_v = float(di_minus_raw)
                except (ValueError, TypeError):
                    di_plus_v, di_minus_v = 0, 0
                if abs(di_plus_v - di_minus_v) >= 0.5:
                    di_bullish = di_plus_v > di_minus_v
                    # Bearish DI cross claims
                    di_bearish_claim = (
                        self._claims_near_tf(
                            text, tf_p,
                            r'DI.{0,15}(?:bearish|死叉|空头).{0,10}(?:cross|交叉)',
                        ) or self._claims_near_tf(
                            text, tf_p,
                            r'DI[\-−]\s*(?:cross(?:ed|ing)?\s*(?:above|over)|上穿|领先)\s*(?:the\s+)?DI\+',
                        )
                    )
                    # Bullish DI cross claims
                    di_bullish_claim = (
                        self._claims_near_tf(
                            text, tf_p,
                            r'DI.{0,15}(?:bullish|金叉|多头).{0,10}(?:cross|交叉)',
                        ) or self._claims_near_tf(
                            text, tf_p,
                            r'DI\+\s*(?:cross(?:ed|ing)?\s*(?:above|over)|上穿|领先)\s*(?:the\s+)?DI[\-−]',
                        )
                    )
                    if di_bullish and di_bearish_claim:
                        errors.append(
                            f'{tf_label} DI: DI+={di_plus_v:.1f}>DI-={di_minus_v:.1f}=BULLISH '
                            f'but agent claimed bearish DI cross')
                    elif not di_bullish and di_bullish_claim:
                        errors.append(
                            f'{tf_label} DI: DI+={di_plus_v:.1f}<DI-={di_minus_v:.1f}=BEARISH '
                            f'but agent claimed bullish DI cross')

            # -- SMA20 vs SMA50 golden/death cross (v26.0) --
            sma20_raw = tf_data.get('sma_20')
            sma50_raw = tf_data.get('sma_50')
            if sma20_raw is not None and sma50_raw is not None:
                try:
                    sma20 = float(sma20_raw)
                    sma50 = float(sma50_raw)
                except (ValueError, TypeError):
                    sma20, sma50 = 0, 0
                if sma20 > 0 and sma50 > 0 and abs(sma20 - sma50) / sma50 > 0.001:
                    golden = sma20 > sma50  # SMA20 above SMA50
                    if golden and self._claims_near_tf(
                        text, tf_p,
                        r'(?:SMA\s*20|SMA20).{0,20}(?:death\s*cross|死叉|below\s*SMA\s*50)',
                    ):
                        errors.append(
                            f'{tf_label} SMA20=${sma20:,.0f} > SMA50=${sma50:,.0f} '
                            f'but agent claimed death cross')
                    elif not golden and self._claims_near_tf(
                        text, tf_p,
                        r'(?:SMA\s*20|SMA20).{0,20}(?:golden\s*cross|金叉|above\s*SMA\s*50)',
                    ):
                        errors.append(
                            f'{tf_label} SMA20=${sma20:,.0f} < SMA50=${sma50:,.0f} '
                            f'but agent claimed golden cross')

            # -- EMA 12/26 crossover direction (v31.3) --
            # v29.2 introduced EMA_BULLISH/BEARISH_CROSS_4H tags, but agents
            # may also describe EMA crosses in reasoning text without using
            # the tag. This validates textual EMA crossover claims.
            ema12_raw = tf_data.get('ema_12')
            ema26_raw = tf_data.get('ema_26')
            if ema12_raw is not None and ema26_raw is not None:
                try:
                    ema12 = float(ema12_raw)
                    ema26 = float(ema26_raw)
                except (ValueError, TypeError):
                    ema12, ema26 = 0, 0
                if ema12 > 0 and ema26 > 0 and abs(ema12 - ema26) / ema26 > 0.001:
                    ema_bullish = ema12 > ema26
                    if ema_bullish and self._claims_near_tf(
                        text, tf_p,
                        r'EMA.{0,15}(?:bearish|death|死叉|空头).{0,10}(?:cross|交叉)',
                    ):
                        errors.append(
                            f'{tf_label} EMA12=${ema12:,.0f} > EMA26=${ema26:,.0f} '
                            f'but agent claimed bearish EMA cross')
                    elif not ema_bullish and self._claims_near_tf(
                        text, tf_p,
                        r'EMA.{0,15}(?:bullish|golden|金叉|多头).{0,10}(?:cross|交叉)',
                    ):
                        errors.append(
                            f'{tf_label} EMA12=${ema12:,.0f} < EMA26=${ema26:,.0f} '
                            f'but agent claimed bullish EMA cross')

        # -- Price vs SMA200 --
        # v31.7: Use _claims_near_tf with 1D scope to prevent matching
        # conditional/hypothetical text like "if price falls below SMA 200".
        # All other comparison checks already use _claims_near_tf for scoping.
        price = technical_data.get('price', 0)
        mtf_1d = technical_data.get('mtf_trend_layer') or {}
        sma200_raw = mtf_1d.get('sma_200')
        tf_1d_p = r'(?:1[Dd]|趋势层|SMA\s*200)'  # SMA200 is inherently 1D
        if price and sma200_raw:
            try:
                p = float(price)
                s = float(sma200_raw)
            except (ValueError, TypeError):
                p, s = 0, 0
            if s > 0 and abs(p - s) / s > 0.005:  # >0.5% apart
                above = p > s
                if above and self._claims_near_tf(
                    text, tf_1d_p,
                    r'(?:below|under|beneath|低于)\s*(?:the\s+)?SMA\s*200',
                ):
                    errors.append(
                        f'Price ${p:,.0f} ABOVE SMA200 ${s:,.0f} '
                        f'but agent claimed below')
                elif not above and self._claims_near_tf(
                    text, tf_1d_p,
                    r'(?:above|over|高于)\s*(?:the\s+)?SMA\s*200',
                ):
                    errors.append(
                        f'Price ${p:,.0f} BELOW SMA200 ${s:,.0f} '
                        f'but agent claimed above')

        return errors

    # ------------------------------------------------------------------
    # Internal: zone / regime claim checks (v26.0)
    # ------------------------------------------------------------------

    def _check_zone_claims(
        self, text: str, technical_data: Dict[str, Any],
    ) -> List[str]:
        """Check qualitative zone claims against actual values.

        v26.0 checks:
        - RSI oversold/overbought (conservative threshold: 50)
        - ADX strong trend vs ranging (thresholds: 15 and 35)
        - Extension regime (NORMAL vs OVEREXTENDED/EXTREME)
        - Volatility Regime (LOW/HIGH/EXTREME mismatch)
        - BB Position zone (overbought/oversold at bands)
        """
        if not text or not technical_data:
            return []

        errors: List[str] = []

        timeframes = [
            ('30M', technical_data),
            ('4H', technical_data.get('mtf_decision_layer') or {}),
            ('1D', technical_data.get('mtf_trend_layer') or {}),
        ]
        # v31.0: Include Chinese TF aliases to detect zone claims in
        # Chinese-only text (e.g. "决策层 RSI 超买"). Without these,
        # claims using Chinese TF labels bypass all zone verification.
        tf_aliases = {
            '30M': r'(?:30[Mm]|执行层)', '4H': r'(?:4[Hh]|决策层)', '1D': r'(?:1[Dd]|趋势层)',
        }

        for tf_label, tf_data in timeframes:
            if not tf_data or not isinstance(tf_data, dict):
                continue
            tf_p = tf_aliases[tf_label]

            # -- RSI zone claims --
            # v33.1: Conservative matching — require RSI indicator context.
            # Root cause: bare "oversold/超卖" matches extension ratio context,
            # compound Chinese clauses, and other non-RSI usage.  Previous
            # approach (exclude conjunctions/extension via regex) was
            # whack-a-mole — incomplete exclusion list, false negatives
            # when RSI genuinely appears near a conjunction.
            #
            # Fix: Only match when "oversold/超卖" appears within 15 chars
            # of "RSI" (either order).  This is high-precision because:
            #   - "RSI oversold" / "RSI 超卖" / "超卖 RSI" → matched
            #   - "RSI(64.8)处于超卖" (distance=8) → matched
            #   - "RSI at 64.8 in oversold" (distance=12) → matched
            #   - "oversold extension" / "配合超卖条件" → NOT matched (no RSI)
            #   - Eliminates entire class of false positives without exclusions
            #   Window=15 covers all realistic AI phrasings with zero FP risk.
            _RSI_OVERSOLD = (
                r'(?:RSI.{0,15}(?:oversold|超卖)'
                r'|(?:oversold|超卖).{0,15}RSI)'
            )
            _RSI_OVERBOUGHT = (
                r'(?:RSI.{0,15}(?:overbought|超买)'
                r'|(?:overbought|超买).{0,15}RSI)'
            )
            rsi_raw = tf_data.get('rsi')
            if rsi_raw is not None:
                try:
                    rsi = float(rsi_raw)
                except (ValueError, TypeError):
                    rsi = None
                if rsi is not None:
                    # "oversold" when RSI > 50 is clearly wrong
                    if rsi > 50 and self._claims_near_tf(
                        text, tf_p, _RSI_OVERSOLD,
                    ):
                        errors.append(
                            f'{tf_label} RSI={rsi:.1f} but agent claimed oversold')
                    # "overbought" when RSI < 50 is clearly wrong
                    elif rsi < 50 and self._claims_near_tf(
                        text, tf_p, _RSI_OVERBOUGHT,
                    ):
                        errors.append(
                            f'{tf_label} RSI={rsi:.1f} but agent claimed overbought')

            # -- ADX trend strength claims --
            adx_raw = tf_data.get('adx')
            if adx_raw is not None:
                try:
                    adx = float(adx_raw)
                except (ValueError, TypeError):
                    adx = None
                if adx is not None:
                    # "strong trend" when ADX < 15 is wrong
                    if adx < 15 and self._claims_near_tf(
                        text, tf_p,
                        r'(?:strong\s*trend|强趋势|trending\s*strongly)',
                    ):
                        errors.append(
                            f'{tf_label} ADX={adx:.1f} but agent claimed strong trend')
                    # "ranging/no trend" when ADX > 35 is wrong
                    elif adx > 35 and self._claims_near_tf(
                        text, tf_p,
                        r'(?:ranging|no\s*trend|无趋势|sideways|横盘)',
                    ):
                        errors.append(
                            f'{tf_label} ADX={adx:.1f} but agent claimed ranging/no trend')

            # -- BB Position zone (v26.0) --
            bb_raw = tf_data.get('bb_position')
            if bb_raw is not None:
                try:
                    bb = float(bb_raw)
                except (ValueError, TypeError):
                    bb = None
                if bb is not None:
                    # "near lower band / oversold" when BB > 0.7 is wrong
                    if bb > 0.7 and self._claims_near_tf(
                        text, tf_p,
                        r'(?:lower\s*band|near\s*lower|BB\s*(?:oversold|超卖))',
                    ):
                        errors.append(
                            f'{tf_label} BB Position={bb*100:.0f}% (upper half) '
                            f'but agent claimed near lower band')
                    # "near upper band / overbought" when BB < 0.3 is wrong
                    elif bb < 0.3 and self._claims_near_tf(
                        text, tf_p,
                        r'(?:upper\s*band|near\s*upper|BB\s*(?:overbought|超买))',
                    ):
                        errors.append(
                            f'{tf_label} BB Position={bb*100:.0f}% (lower half) '
                            f'but agent claimed near upper band')

        # -- Extension regime claims (TF-aware, v31.6) --
        # v26.1: Use assertion-style patterns to detect agent claiming a wrong regime.
        # v31.6: Collect regimes from all 3 TFs. Agent text often omits TF qualifier,
        # so "any TF matches" strategy prevents false positives when TFs diverge.
        _all_ext_regimes = {technical_data.get('extension_regime', '')}
        for _mtf_key in ('mtf_decision_layer', 'mtf_trend_layer'):
            _mtf = technical_data.get(_mtf_key) or {}
            _er = _mtf.get('extension_regime', '')
            if _er:
                _all_ext_regimes.add(_er)
        _all_ext_regimes.discard('')
        _ext_claim_normal = (
            r'(?:extension\s*(?:ratio\s*)?(?:is|=|→)\s*(?:normal|healthy)'
            r'|(?:regime|状态)\s*[:\s=]*\s*(?:normal|正常)'
            r'|(?:当前|current).{0,30}extension.{0,10}(?:normal|正常))'
        )
        _ext_claim_overextended = (
            r'(?:extension\s*(?:ratio\s*)?(?:is|=|→)\s*(?:overextended|EXTREME)'
            r'|(?:regime|状态)\s*[:\s=]*\s*(?:overextended|EXTREME)'
            r'|(?:当前|current).{0,30}(?:overextended|过度延伸|EXTREME))'
        )
        if _all_ext_regimes:
            # Only flag if NO TF supports the claimed regime
            if (_all_ext_regimes <= {'NORMAL', 'EXTENDED'}) and re.search(
                _ext_claim_overextended, text, re.IGNORECASE,
            ):
                errors.append(
                    f'Extension regimes={_all_ext_regimes} but agent claimed overextended/extreme')
            elif (_all_ext_regimes <= {'EXTREME', 'OVEREXTENDED'}) and re.search(
                _ext_claim_normal, text, re.IGNORECASE,
            ):
                errors.append(
                    f'Extension regimes={_all_ext_regimes} but agent claimed normal extension')

        # -- Volatility Regime claims (TF-aware, v31.6) --
        # v31.0: Symmetric checks — all clearly contradictory combinations covered.
        # v31.6: Collect regimes from all 3 TFs (same "any TF matches" strategy).
        _all_vol_regimes = {technical_data.get('volatility_regime', '')}
        for _mtf_key in ('mtf_decision_layer', 'mtf_trend_layer'):
            _mtf = technical_data.get(_mtf_key) or {}
            _vr = _mtf.get('volatility_regime', '')
            if _vr:
                _all_vol_regimes.add(_vr)
        _all_vol_regimes.discard('')
        _vol_claim_low = r'(?:volatility|波动)\s*(?:is\s+)?(?:low|calm|低|平静)'
        _vol_claim_extreme = r'(?:volatility|波动)\s*(?:is\s+)?(?:extreme|very\s*high|极高|EXTREME)'
        if _all_vol_regimes:
            if (_all_vol_regimes <= {'LOW', 'NORMAL'}) and re.search(
                _vol_claim_extreme, text, re.IGNORECASE,
            ):
                errors.append(
                    f'Volatility regimes={_all_vol_regimes} but agent claimed extreme volatility')
            elif (_all_vol_regimes <= {'EXTREME', 'HIGH'}) and re.search(
                _vol_claim_low, text, re.IGNORECASE,
            ):
                errors.append(
                    f'Volatility regimes={_all_vol_regimes} but agent claimed low volatility')

        return errors

    # All TF patterns for cross-TF exclusion in proximity checks.
    _ALL_TF_PATTERNS = [r'30[Mm]', r'4[Hh]', r'1[Dd]', r'执行层', r'决策层', r'趋势层']

    @staticmethod
    def _claims_near_tf(
        text: str, tf_regex: str, claim_regex: str, window: int = 80,
        exclude_before: 'Optional[str]' = None,
        exclude_after: 'Optional[str]' = None,
        exclude_window: int = 30,
    ) -> bool:
        """Check if a qualitative claim appears near a timeframe mention.

        v26.1: Cross-TF exclusion — if a *different* TF mention appears between
        the target TF and the claim match, the claim likely refers to the other TF.
        Window reduced from 120 to 80 chars to minimize false positives from
        multi-timeframe discussions in the same paragraph.

        v31.5: Nearest-TF-wins — if any other TF mention in the full text is
        closer to the claim than the target TF, the claim is attributed to that
        closer TF and rejected.  Fixes false positives from cross-sentence
        patterns like ``"4H ... MACD bearish cross). 30M ..."`` where the claim
        belongs to the preceding TF but falls within the target TF's window.

        v33.0: Context-aware exclusion — after a candidate match passes all
        cross-TF checks, optionally check if ``exclude_before`` / ``exclude_after``
        patterns appear within ``exclude_window`` chars of the **specific** match.
        This is targeted (per-match), not global, preventing the false-negative
        issue of blanket text-level exclusions.

        Parameters
        ----------
        exclude_before : optional regex
            If this pattern matches within *exclude_window* chars BEFORE the
            specific claim match, skip the match.  E.g. ``r'(?:extension|扩展|
            配合|加上|叠加)'`` excludes claims preceded by extension context or
            compound conjunctions.
        exclude_after : optional regex
            If this pattern matches within *exclude_window* chars AFTER the
            specific claim match, skip the match.  E.g. ``r'(?:extension|扩展)'``
            excludes "oversold ... extension" forward context.
        exclude_window : int
            Character window for context exclusion (default 30).
        """
        # Build set of "other TF" patterns (everything except the target TF)
        other_tfs = [p for p in AIQualityAuditor._ALL_TF_PATTERNS
                     if not re.fullmatch(tf_regex, p.replace(r'[Mm]', 'M').replace(r'[Hh]', 'H').replace(r'[Dd]', 'D'), re.IGNORECASE)]

        for m in re.finditer(tf_regex, text, re.IGNORECASE):
            w_start = max(0, m.start() - window)
            w_end = min(len(text), m.end() + window)
            window_text = text[w_start:w_end]
            tf_pos_in_window = m.start() - w_start

            # v33.0: Iterate ALL claim matches in the window (not just the
            # first).  re.search only returns the first match — if that match
            # is excluded by scope/context checks, subsequent valid matches
            # in the same window would be missed.
            for claim_match in re.finditer(
                claim_regex, window_text, re.IGNORECASE,
            ):
                # Check if another TF mention sits between the target TF
                # and the claim.  If so, the claim likely belongs to the
                # other TF — skip this match.
                claim_pos_in_window = claim_match.start()
                between_start = min(tf_pos_in_window, claim_pos_in_window)
                between_end = max(
                    tf_pos_in_window + m.end() - m.start(),
                    claim_pos_in_window + claim_match.end()
                    - claim_match.start(),
                )
                between_text = window_text[between_start:between_end]

                has_other_tf = False
                for other_p in other_tfs:
                    if re.search(other_p, between_text, re.IGNORECASE):
                        has_other_tf = True
                        break
                if has_other_tf:
                    continue  # Claim belongs to a different TF

                # v31.5: Scope-based attribution — when the claim appears
                # BEFORE the target TF in the text (left side of window),
                # it likely belongs to whichever TF mention most recently
                # precedes it.  E.g. in "4H ... MACD bearish cross). 30M
                # ..." the claim is in 4H's scope even though it's only 3
                # chars from "30M".
                claim_abs_start = w_start + claim_match.start()
                claim_abs_end = w_start + claim_match.end()

                if claim_abs_start < m.start():
                    nearest_pre_end = -1
                    nearest_pre_is_target = False

                    for t_m in re.finditer(
                        tf_regex, text[:claim_abs_start], re.IGNORECASE,
                    ):
                        if t_m.end() > nearest_pre_end:
                            nearest_pre_end = t_m.end()
                            nearest_pre_is_target = True

                    for other_p in other_tfs:
                        for o_m in re.finditer(
                            other_p, text[:claim_abs_start], re.IGNORECASE,
                        ):
                            if o_m.end() > nearest_pre_end:
                                nearest_pre_end = o_m.end()
                                nearest_pre_is_target = False

                    if nearest_pre_end >= 0 and not nearest_pre_is_target:
                        continue  # Claim belongs to a preceding TF's scope

                # v33.0: Context-aware exclusion — check patterns in
                # the GAP between the TF mention and the claim, not an
                # arbitrary char window.  This prevents false exclusion
                # from unrelated contexts (e.g. "1D扩展...30M RSI oversold"
                # — "扩展" is in 1D's gap, not 30M's gap).
                if exclude_before or exclude_after:
                    if claim_abs_start >= m.end():
                        # Claim is after TF → gap = TF_end .. claim_start
                        gap_text = text[m.end():claim_abs_start]
                    elif claim_abs_end <= m.start():
                        # Claim is before TF → gap = claim_end .. TF_start
                        gap_text = text[claim_abs_end:m.start()]
                    else:
                        gap_text = ''  # Overlapping / adjacent

                    if exclude_before and gap_text:
                        if re.search(
                            exclude_before, gap_text, re.IGNORECASE,
                        ):
                            continue  # Exclusion context in TF→claim gap
                    if exclude_after:
                        post_end = min(
                            len(text), claim_abs_end + exclude_window,
                        )
                        post_text = text[claim_abs_end:post_end]
                        if re.search(
                            exclude_after, post_text, re.IGNORECASE,
                        ):
                            continue  # Claim followed by exclusion context

                return True
        return False

    # ------------------------------------------------------------------
    # Internal: non-technical data citation check (v26.0)
    # ------------------------------------------------------------------

    def _check_nontech_claims(
        self,
        text: str,
        sentiment_data: Optional[Dict[str, Any]],
        order_flow_data: Optional[Dict[str, Any]],
        derivatives_data: Optional[Dict[str, Any]],
        orderbook_data: Optional[Dict[str, Any]],
        sr_zones_data: Optional[Dict[str, Any]],
    ) -> List[str]:
        """Check AI citations of non-technical data against actual values.

        Covers: Sentiment L/S ratios, Funding Rate, Buy Ratio, OBI, S/R prices.
        """
        if not text:
            return []

        errors: List[str] = []

        # -- Sentiment: Long Ratio and Short Ratio --
        if sentiment_data and not sentiment_data.get('degraded'):
            long_r = sentiment_data.get('positive_ratio')
            short_r = sentiment_data.get('negative_ratio')
            if long_r is not None:
                try:
                    actual_long_pct = float(long_r) * 100
                except (ValueError, TypeError):
                    actual_long_pct = None
                if actual_long_pct is not None and actual_long_pct > 0:
                    cited = self._extract_pct_near_label(
                        text, r'[Ll]ong\s*(?:[Rr]atio|%)', 0, 100)
                    if cited is not None and abs(cited - actual_long_pct) > 3.0:
                        errors.append(
                            f'Sentiment Long Ratio: actual={actual_long_pct:.1f}%, '
                            f'cited={cited:.1f}% (off by {abs(cited - actual_long_pct):.1f}%)')
            if short_r is not None:
                try:
                    actual_short_pct = float(short_r) * 100
                except (ValueError, TypeError):
                    actual_short_pct = None
                if actual_short_pct is not None and actual_short_pct > 0:
                    cited = self._extract_pct_near_label(
                        text, r'[Ss]hort\s*(?:[Rr]atio|%)', 0, 100)
                    if cited is not None and abs(cited - actual_short_pct) > 3.0:
                        errors.append(
                            f'Sentiment Short Ratio: actual={actual_short_pct:.1f}%, '
                            f'cited={cited:.1f}% (off by {abs(cited - actual_short_pct):.1f}%)')

        # -- Derivatives: Funding Rate --
        if derivatives_data:
            fr_dict = derivatives_data.get('funding_rate') or {}
            if isinstance(fr_dict, dict):
                # current_pct / settled_pct already in percentage form (e.g. 0.01234 = 0.01234%)
                fr_raw = fr_dict.get('current_pct') or fr_dict.get('settled_pct')
                if fr_raw is None and fr_dict.get('value') is not None:
                    # Fallback: raw decimal value → convert to %
                    try:
                        fr_raw = float(fr_dict['value']) * 100
                    except (ValueError, TypeError):
                        fr_raw = None
                try:
                    actual_fr_pct = float(fr_raw) if fr_raw is not None else None
                except (ValueError, TypeError):
                    actual_fr_pct = None
                if actual_fr_pct is not None:
                    cited_fr = self._extract_pct_near_label(
                        text, r'[Ff]unding\s*[Rr]ate|(?<![A-Za-z])FR(?![A-Za-z])',
                        -1.0, 1.0,
                    )
                    if cited_fr is not None and abs(cited_fr - actual_fr_pct) > 0.005:
                        errors.append(
                            f'Funding Rate: actual={actual_fr_pct:.5f}%, '
                            f'cited={cited_fr:.5f}% (off by {abs(cited_fr - actual_fr_pct):.5f}%)')

        # -- Order Flow: Buy Ratio --
        if order_flow_data:
            buy_r = order_flow_data.get('buy_ratio')
            if buy_r is not None:
                try:
                    actual_buy_pct = float(buy_r) * 100
                except (ValueError, TypeError):
                    actual_buy_pct = None
                if actual_buy_pct is not None and actual_buy_pct > 0:
                    cited = self._extract_pct_near_label(
                        text, r'[Bb]uy\s*[Rr]atio', 0, 100)
                    if cited is not None and abs(cited - actual_buy_pct) > 3.0:
                        errors.append(
                            f'Buy Ratio: actual={actual_buy_pct:.1f}%, '
                            f'cited={cited:.1f}% (off by {abs(cited - actual_buy_pct):.1f}%)')

        # -- Orderbook: OBI (Order Book Imbalance) --
        # v26.1: Check against ALL OBI variants (simple, weighted, adaptive).
        # Agents may cite any variant; flagging only against weighted caused
        # false positives when agents cited simple OBI.
        if orderbook_data:
            obi_dict = orderbook_data.get('obi') or {}
            obi_variants: list = []
            if isinstance(obi_dict, dict):
                for key in ('simple', 'weighted', 'adaptive'):
                    v = obi_dict.get(key)
                    if v is not None:
                        try:
                            obi_variants.append(float(v))
                        except (ValueError, TypeError):
                            logger.debug(f"OBI value parse skipped: {v!r}")
            elif obi_dict is not None:
                try:
                    obi_variants.append(float(obi_dict))
                except (ValueError, TypeError):
                    logger.debug(f"OBI value parse skipped: {obi_dict!r}")
            if obi_variants:
                m = re.search(
                    r'(?<![A-Za-z])OBI(?![A-Za-z])\s*[:\s=]*\s*([-+]?[\d]+\.?\d*)',
                    text, re.IGNORECASE,
                )
                if m:
                    try:
                        cited_obi = float(m.group(1))
                        # Accept if cited value is within tolerance of ANY variant
                        min_diff = min(abs(cited_obi - v) for v in obi_variants)
                        if min_diff > 0.05:
                            best_match = min(obi_variants, key=lambda v: abs(cited_obi - v))
                            errors.append(
                                f'OBI: actual={best_match:.2f}, '
                                f'cited={cited_obi:.2f} (off by {min_diff:.2f})')
                    except (ValueError, IndexError):
                        logger.debug("OBI citation comparison skipped")

        # -- S/R Zones: Support and Resistance prices --
        # v26.1: Extract ALL dollar values near S/R labels, accept if ANY matches.
        # Previous approach took only the first match, which could be a BB Upper
        # or other non-S/R price mentioned near "resistance" in the same paragraph.
        if sr_zones_data:
            for zone_type in ('nearest_support', 'nearest_resistance'):
                zone = sr_zones_data.get(zone_type)
                if zone:
                    actual_price = getattr(zone, 'price_center', None)
                    if actual_price is not None:
                        try:
                            actual_p = float(actual_price)
                        except (ValueError, TypeError):
                            continue
                        if actual_p <= 0:
                            continue
                        label = 'Support' if 'support' in zone_type else 'Resistance'
                        label_re = r'[Ss]upport|S1|支撑' if 'support' in zone_type else r'[Rr]esistance|R1|阻力'
                        all_cited = self._extract_all_dollars_near_label(text, label_re)
                        if all_cited:
                            # Accept if ANY cited value is within 1% of actual
                            min_diff = min(
                                abs(c - actual_p) / actual_p * 100 for c in all_cited
                            )
                            if min_diff > 1.0:
                                closest = min(all_cited, key=lambda c: abs(c - actual_p))
                                errors.append(
                                    f'{label}: actual=${actual_p:,.0f}, '
                                    f'cited=${closest:,.0f} (off by {min_diff:.1f}%)')

        return errors

    # ------------------------------------------------------------------
    # v34.0: Phantom citation detection
    # ------------------------------------------------------------------

    def _check_phantom_citations(
        self,
        text: str,
        sentiment_data: Optional[Dict[str, Any]],
        order_flow_data: Optional[Dict[str, Any]],
        derivatives_data: Optional[Dict[str, Any]],
        orderbook_data: Optional[Dict[str, Any]],
    ) -> List[str]:
        """Detect AI citing specific values from data sources that were unavailable.

        v34.0: When a data source is None or degraded, the AI should NOT cite
        specific numerical values from it. If it does, the values are fabricated.
        """
        if not text:
            return []

        errors: List[str] = []

        # Sentiment unavailable but AI cites L/S ratio with specific %
        _sentiment_unavailable = (
            not sentiment_data
            or sentiment_data.get('degraded')
        )
        if _sentiment_unavailable:
            cited_long = self._extract_pct_near_label(
                text, r'[Ll]ong\s*(?:[Rr]atio|%)', 0, 100)
            cited_short = self._extract_pct_near_label(
                text, r'[Ss]hort\s*(?:[Rr]atio|%)', 0, 100)
            if cited_long is not None:
                errors.append(
                    f'Phantom: Sentiment unavailable but AI cited '
                    f'Long Ratio={cited_long:.1f}%')
            if cited_short is not None:
                errors.append(
                    f'Phantom: Sentiment unavailable but AI cited '
                    f'Short Ratio={cited_short:.1f}%')

        # Derivatives unavailable but AI cites specific FR %
        if not derivatives_data:
            cited_fr = self._extract_pct_near_label(
                text, r'[Ff]unding\s*[Rr]ate|(?<![A-Za-z])FR(?![A-Za-z])',
                -1.0, 1.0,
            )
            if cited_fr is not None:
                errors.append(
                    f'Phantom: Derivatives unavailable but AI cited '
                    f'FR={cited_fr:.5f}%')

        # Order flow unavailable but AI cites specific Buy Ratio %
        if not order_flow_data:
            cited_br = self._extract_pct_near_label(
                text, r'[Bb]uy\s*[Rr]atio', 0, 100)
            if cited_br is not None:
                errors.append(
                    f'Phantom: Order flow unavailable but AI cited '
                    f'Buy Ratio={cited_br:.1f}%')

        # Orderbook unavailable but AI cites specific OBI value
        if not orderbook_data:
            m = re.search(
                r'(?<![A-Za-z])OBI(?![A-Za-z])\s*[:\s=]*\s*([-+]?[\d]+\.?\d*)',
                text, re.IGNORECASE,
            )
            if m:
                try:
                    cited_obi = float(m.group(1))
                    errors.append(
                        f'Phantom: Orderbook unavailable but AI cited '
                        f'OBI={cited_obi:.2f}')
                except (ValueError, IndexError):
                    pass

        return errors

    # ------------------------------------------------------------------
    # v34.0: Narrative misread detection
    # ------------------------------------------------------------------

    def _check_narrative_misread(
        self,
        text: str,
        gt_tech: Dict[str, Any],
    ) -> List[str]:
        """Detect AI using contradictory adjectives for indicator values.

        v34.0: Catches cases where AI correctly cites a number but misinterprets
        its meaning, e.g. "RSI 62 indicates momentum exhaustion" (62 is strong
        momentum, not exhaustion).

        Conservative: only checks clear-cut cases with wide margin. Avoids
        penalizing borderline interpretations (RSI 45-55 is ambiguous).
        """
        if not text:
            return []

        errors: List[str] = []
        # TF aliases matching _check_comparison_claims convention
        _tf_aliases = {
            '30M': r'(?:30[Mm]|执行层)',
            '4H': r'(?:4[Hh]|决策层)',
            '1D': r'(?:1[Dd]|趋势层)',
        }
        _TF_MAP = {
            None: '30M',
            'mtf_decision_layer': '4H',
            'mtf_trend_layer': '1D',
        }

        for tf_key, tf_label in _TF_MAP.items():
            tf_data = gt_tech.get(tf_key, gt_tech) if tf_key else gt_tech
            if not isinstance(tf_data, dict):
                continue

            rsi_raw = tf_data.get('rsi')
            if rsi_raw is None:
                continue
            try:
                rsi = float(rsi_raw)
            except (ValueError, TypeError):
                continue

            # Only check clear-cut ranges: RSI > 60 is bullish, < 40 is bearish.
            # 40-60 is ambiguous — skip to avoid false positives.
            if 40 <= rsi <= 60:
                continue

            tf_p = _tf_aliases[tf_label]

            # Check for RSI + contradictory adjectives using _claims_near_tf
            if rsi > 60:
                # RSI > 60 is strong/bullish — contradicted by weakness/exhaustion
                _weak_patterns = [
                    rf'RSI.{{0,30}}(?:衰竭|exhausti|weaken|弱|fading|bearish\s*diverge)',
                    rf'(?:衰竭|exhausti|weaken|弱势|fading).{{0,20}}RSI',
                ]
                for pat in _weak_patterns:
                    if self._claims_near_tf(text, tf_p, pat):
                        errors.append(
                            f'{tf_label} RSI={rsi:.1f} (bullish) but AI describes '
                            f'weakness/exhaustion')
                        break
            elif rsi < 40:
                # RSI < 40 is weak/bearish — contradicted by strength claims
                # v36.1: \b word boundaries on 'bullish' in keyword-before-RSI
                # pattern to prevent false positives from REASON_TAG names
                # (e.g. MOMENTUM_4H_BULLISH → \bBULLISH\b won't match _BULLISH_)
                _strong_patterns = [
                    rf'RSI.{{0,30}}(?:强|strong\s*momentum|bullish\s*signal|强势)',
                    rf'(?:强势|strong\s*momentum|\bbullish\b).{{0,20}}RSI',
                ]
                for pat in _strong_patterns:
                    if self._claims_near_tf(text, tf_p, pat):
                        errors.append(
                            f'{tf_label} RSI={rsi:.1f} (bearish) but AI describes '
                            f'strong/bullish momentum')
                        break

        return errors

    # ------------------------------------------------------------------
    # v34.0: Contradictory data omission detection (informational flag)
    # ------------------------------------------------------------------

    def _check_contradictory_omission(
        self,
        role: str,
        text: str,
        scores: Optional[Dict[str, Any]],
    ) -> List[str]:
        """Detect when an agent omits data from a dimension that contradicts its role.

        v34.0: Uses precomputed dimensional scores to identify when Bull ignores
        bearish dimensions or Bear ignores bullish dimensions. Purely informational
        flag — low penalty weight because selective emphasis is partly legitimate
        for advocate roles.

        Only flags when:
        1. A dimension has a CLEAR directional score (BULLISH/BEARISH, not NEUTRAL)
        2. The score contradicts the agent's role
        3. The agent's text has NO mention of the relevant data category
        """
        if not scores or not text or role not in ('bull', 'bear'):
            return []

        flags: List[str] = []

        # Dimension → data categories that should be mentioned if score is strong
        _DIMENSION_CATEGORIES = {
            'order_flow': (['order_flow'], r'CVD|[Bb]uy\s*[Rr]atio|[Oo]rder\s*[Ff]low|[Tt]aker'),
            'momentum': (['mtf_4h', 'technical_30m'], r'RSI|MACD|[Mm]omentum'),
            'risk_env': (['derivatives'], r'[Ff]unding|FR|[Ll]iquidat'),
        }

        for dim, (categories, text_pattern) in _DIMENSION_CATEGORIES.items():
            dim_score = scores.get(dim)
            if not isinstance(dim_score, dict):
                continue

            direction = dim_score.get('direction', 'NEUTRAL')
            if direction == 'NEUTRAL':
                continue

            # Bull should mention bearish dimensions, Bear should mention bullish
            contradicts_role = (
                (role == 'bull' and direction == 'BEARISH')
                or (role == 'bear' and direction == 'BULLISH')
            )
            if not contradicts_role:
                continue

            # Check if agent mentions the relevant data at all
            if not re.search(text_pattern, text, re.IGNORECASE):
                flags.append(
                    f'{role}: {dim} score={direction} but agent does not '
                    f'address this contradictory evidence')

        return flags

    @staticmethod
    def _extract_pct_near_label(
        text: str, label_regex: str, v_min: float, v_max: float,
    ) -> Optional[float]:
        """Extract a percentage value near a label mention.

        Handles: "55.3%", "0.01234%", "-0.01234%", etc.
        """
        # v31.0: Capture optional negative sign to avoid false VALUE_ERROR
        # on negative Funding Rate values (e.g. "FR: -0.01234%").
        pattern = rf'(?:{label_regex}).{{0,30}}?(-?[\d]+\.?\d*)%'
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                val = float(m.group(1))
                if v_min <= val <= v_max:
                    return val
            except (ValueError, IndexError):
                logger.debug(f"Regex value extraction skipped for pattern match: {m.group(0)!r}")
        return None

    @staticmethod
    def _extract_dollar_near_label(text: str, label_regex: str) -> Optional[float]:
        """Extract a dollar value near a label mention."""
        pattern = rf'(?:{label_regex}).{{0,30}}?\$\s*([\d,]+(?:\.\d+)?)'
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                return float(m.group(1).replace(',', ''))
            except (ValueError, IndexError):
                logger.debug(f"Dollar extraction skipped for: {m.group(0)!r}")
        return None

    @staticmethod
    def _extract_all_dollars_near_label(text: str, label_regex: str) -> List[float]:
        """Extract ALL dollar values near a label mention (v26.1).

        Returns list of all found dollar values within 30 chars of the label.
        Used for S/R checks where agents may cite both the S/R zone and
        secondary targets (like BB upper) near the same label.
        """
        pattern = rf'(?:{label_regex}).{{0,30}}?\$\s*([\d,]+(?:\.\d+)?)'
        values: List[float] = []
        for m in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            try:
                val = float(m.group(1).replace(',', ''))
                if val > 0:
                    values.append(val)
            except (ValueError, IndexError):
                continue
        return values

    @staticmethod
    def _extract_direction(layer_text: str) -> Optional[str]:
        """Extract BULLISH/BEARISH/NEUTRAL from a confluence layer string.

        Priority 1: Explicit English tags (BULLISH/BEARISH/NEUTRAL).
        Priority 2: Chinese keyword fallback.

        English tags are checked first to avoid false positives where Chinese
        keywords appear in opposing context — e.g. "多头R/R极度不利" contains
        "多头" (bullish keyword) but the layer is actually BEARISH.
        """
        # Priority 1: Explicit English direction tags
        for direction in ('BULLISH', 'BEARISH', 'NEUTRAL'):
            if re.search(rf'\b{direction}\b', layer_text):
                return direction
        # Priority 2: Chinese keywords (fallback when no English tag present)
        for direction, patterns in _CONFLUENCE_DIRECTION_KEYWORDS.items():
            for p in patterns:
                if re.search(p, layer_text):
                    return direction
        return None

    @staticmethod
    def _expected_confidence(aligned_layers: int) -> str:
        """Map aligned_layers count to expected confidence per Judge rules."""
        if aligned_layers >= 3:
            return 'HIGH'
        elif aligned_layers >= 2:
            return 'MEDIUM'
        return 'LOW'

    @staticmethod
    def _confidence_within_tolerance(declared: str, expected: str) -> bool:
        """Allow one-level downgrade tolerance (Entry Timing or 30M cap)."""
        rank = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}
        d = rank.get(declared, 1)
        e = rank.get(expected, 1)
        return d >= e - 1

    # ------------------------------------------------------------------
    # Internal: counter-trend detection
    # ------------------------------------------------------------------

    @staticmethod
    def _check_counter_trend(
        judge_decision: Dict[str, Any],
        technical_data: Dict[str, Any],
    ) -> bool:
        """Detect if Judge's signal is counter-trend vs 1D direction.

        v31.7: Use _timing_original_signal when available. After Entry Timing
        REJECTs, decision is overwritten to 'HOLD', which would always return
        False and skip counter-trend validation entirely. The original signal
        is preserved in _timing_original_signal for exactly this purpose.
        """
        decision = judge_decision.get(
            '_timing_original_signal', judge_decision.get('decision', 'HOLD')
        )
        if decision not in ('LONG', 'SHORT'):
            return False

        mtf_trend = technical_data.get('mtf_trend_layer', {})
        if not mtf_trend:
            return False

        try:
            di_plus = float(mtf_trend.get('di_plus', 0) or 0)
            di_minus = float(mtf_trend.get('di_minus', 0) or 0)
        except (ValueError, TypeError):
            return False

        if di_plus == 0 and di_minus == 0:
            return False

        is_1d_bullish = di_plus > di_minus
        if decision == 'LONG' and not is_1d_bullish:
            return True
        if decision == 'SHORT' and is_1d_bullish:
            return True
        return False

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_regime(adx_1d: float) -> str:
        """Classify market regime from 1D ADX."""
        if adx_1d >= 40:
            return 'STRONG_TREND'
        elif adx_1d >= 25:
            return 'WEAK_TREND'
        return 'RANGING'

    @staticmethod
    def _extract_judge_text(judge_decision: Dict[str, Any]) -> str:
        """Extract searchable text from Judge's structured output.

        v31.7: Include _raw_reasoning (pre-truncation chain-of-thought) for
        coverage detection parity with Bull/Bear/ET/Risk, which all include
        _raw_reasoning in their coverage text. Without this, Judge's reasoning
        field (up to 1500 chars of data analysis) was invisible to coverage
        regex, causing false MISSING_DATA flags.
        """
        parts: List[str] = []
        # v31.7: Include reasoning (prefer pre-truncation _raw_reasoning)
        _reasoning = (judge_decision.get('_raw_reasoning')
                      or judge_decision.get('reasoning', ''))
        if _reasoning:
            parts.append(str(_reasoning))
        # v29.5: Prefer _raw_rationale (pre-truncation)
        _rationale = (judge_decision.get('_raw_rationale')
                      or judge_decision.get('rationale', ''))
        if _rationale:
            parts.append(str(_rationale))
        for action in judge_decision.get('strategic_actions', []):
            parts.append(str(action))
        for risk in judge_decision.get('acknowledged_risks', []):
            parts.append(str(risk))
        confluence = judge_decision.get('confluence', {})
        for layer_key in ('trend_1d', 'momentum_4h', 'levels_30m', 'derivatives'):
            # Include layer key as context — the Judge's structured output
            # confirms which data was analyzed, even if the text doesn't
            # repeat the timeframe label (e.g. levels_30m text may not say "30M").
            layer_val = str(confluence.get(layer_key, ''))
            parts.append(f'{layer_key}: {layer_val}')
        return ' '.join(parts)

    # ------------------------------------------------------------------
    # v30.0: Ground truth construction from features
    # ------------------------------------------------------------------

    @staticmethod
    def _features_to_tf_data(features: Dict[str, Any]) -> Dict[str, Any]:
        """Build nested TF-indexed ground truth from flat features dict.

        Produces the same nested structure as ``technical_data`` (30M at
        top-level, 4H in ``mtf_decision_layer``, 1D in ``mtf_trend_layer``)
        so existing verification methods work unchanged.

        Ground truth comes from features (= what agents saw), not from raw
        pipeline input.
        """
        _TF_SUFFIXES = {
            '30m': None,
            '4h': 'mtf_decision_layer',
            '1d': 'mtf_trend_layer',
        }
        _INDICATOR_BASES = [
            'rsi', 'adx', 'di_plus', 'di_minus', 'bb_position',
            'volume_ratio', 'macd_histogram', 'macd_signal', 'macd',
            'sma_20', 'sma_50', 'sma_200', 'atr', 'atr_pct',
            'bb_upper', 'bb_lower', 'ema_12', 'ema_26',
            'extension_ratio', 'extension_regime',
            'volatility_regime', 'volatility_percentile',
        ]

        # v31.7: Enum defaults that should NOT enter ground truth.
        # extract_features() returns "NONE" when data is missing — this is NOT a
        # real regime value and would pollute zone check sets (e.g. adding "NONE"
        # to _all_ext_regimes prevents subset checks from detecting mismatches).
        _ENUM_BASES = {'extension_regime', 'volatility_regime'}
        _ENUM_SKIP = {'NONE', 'N/A', ''}

        result: Dict[str, Any] = {}
        tf_4h: Dict[str, Any] = {}
        tf_1d: Dict[str, Any] = {}

        for base in _INDICATOR_BASES:
            for suffix, target_key in _TF_SUFFIXES.items():
                feat_key = f'{base}_{suffix}'
                val = features.get(feat_key)
                if val is None:
                    continue
                # v31.7: Skip enum defaults that represent missing data
                if base in _ENUM_BASES and str(val).upper() in _ENUM_SKIP:
                    continue
                if target_key is None:
                    result[base] = val
                elif target_key == 'mtf_decision_layer':
                    tf_4h[base] = val
                else:
                    tf_1d[base] = val

        # Top-level keys that don't follow {base}_{tf} suffix convention
        # v31.0: price and market_regime remain unsuffixed in feature dict
        for key in ('price', 'market_regime'):
            val = features.get(key)
            if val is not None:
                result[key] = val

        # v31.0: Alias extension_ratio → extension_ratio_sma_20/200 for
        # _VALUE_VERIFY_INDICATORS compatibility. Features path produces
        # 'extension_ratio' key but raw-data path uses 'extension_ratio_sma_20'
        # (30M/4H) and 'extension_ratio_sma_200' (1D). Set both so value
        # verification works regardless of data source.
        for container, sma_key in [
            (result, 'extension_ratio_sma_20'),
            (tf_4h, 'extension_ratio_sma_20'),
            (tf_1d, 'extension_ratio_sma_200'),
        ]:
            if 'extension_ratio' in container and sma_key not in container:
                container[sma_key] = container['extension_ratio']

        if tf_4h:
            result['mtf_decision_layer'] = tf_4h
        if tf_1d:
            result['mtf_trend_layer'] = tf_1d

        return result

    @staticmethod
    def _features_to_nontech(features: Dict[str, Any]) -> Dict[str, Any]:
        """Build non-technical ground truth dicts from features.

        Returns dict with keys: sentiment, derivatives, order_flow, orderbook,
        sr_zones.  Structure matches what ``_check_nontech_claims()`` expects.
        """
        from types import SimpleNamespace

        result: Dict[str, Any] = {}

        # Sentiment (v34.3: now uses _avail_sentiment flag)
        lr = features.get('long_ratio')
        sr = features.get('short_ratio')
        if lr is not None or sr is not None:
            result['sentiment'] = {
                'positive_ratio': lr,
                'negative_ratio': sr,
                'degraded': features.get('sentiment_degraded', False),
            }

        # Derivatives (funding rate)
        # v34.2: Respect _avail_derivatives flag — if data source was
        # unavailable, default feature values are artifacts, not real data.
        if features.get('_avail_derivatives', True):
            fr = features.get('funding_rate_pct')
            if fr is not None:
                result['derivatives'] = {
                    'funding_rate': {'current_pct': fr},
                }

        # Order flow
        if features.get('_avail_order_flow', True):
            br = features.get('buy_ratio_30m')
            if br is not None:
                result['order_flow'] = {'buy_ratio': br}

        # Orderbook
        if features.get('_avail_orderbook', True):
            obi = features.get('obi_weighted')
            if obi is not None:
                result['orderbook'] = {'obi': {'weighted': obi}}

        # S/R zones — use SimpleNamespace for .price_center attribute access
        sp = features.get('nearest_support_price')
        rp = features.get('nearest_resist_price')
        if sp is not None or rp is not None:
            sr_dict: Dict[str, Any] = {}
            if sp is not None:
                sr_dict['nearest_support'] = SimpleNamespace(price_center=sp)
            if rp is not None:
                sr_dict['nearest_resistance'] = SimpleNamespace(price_center=rp)
            result['sr_zones'] = sr_dict

        return result

    # ------------------------------------------------------------------
    # v34.0: Logic-level coherence checks (5 new checks)
    # ------------------------------------------------------------------

    # Debate conviction spread threshold for echo chamber detection
    _DEBATE_CONVERGENCE_THRESHOLD = 0.15

    # Regex for _scores['net'] format from compute_scores_from_features()
    # v40.0: Support both LEAN_ and TRANSITIONING_ net labels
    _NET_DIRECTION_RE = re.compile(r'(?:LEAN|TRANSITIONING)_(BULLISH|BEARISH)_(\d+)of(\d+)')

    @staticmethod
    def _check_reason_signal_alignment(
        decision: str,
        decisive_reasons: List[str],
    ) -> tuple:
        """Check if Judge's decisive_reasons tags align with its decision.

        Returns (penalty, flag_text). HOLD/CLOSE/REDUCE exempt.
        Need >= 2 directional tags (after excluding weak signals).
        """
        if decision not in ('LONG', 'SHORT'):
            return (0, '')

        # Filter out weak signals before directional count
        strong_reasons = [t for t in decisive_reasons if t not in _WEAK_SIGNAL_TAGS]

        # Count directional tags
        bullish = sum(1 for t in strong_reasons if t in BULLISH_EVIDENCE_TAGS)
        bearish = sum(1 for t in strong_reasons if t in BEARISH_EVIDENCE_TAGS)
        total_directional = bullish + bearish

        # Need >= 2 directional tags for meaningful sample
        if total_directional < 2:
            return (0, '')

        # Calculate conflict ratio
        if decision == 'LONG':
            conflict_ratio = bearish / total_directional
        else:  # SHORT
            conflict_ratio = bullish / total_directional

        # Penalty thresholds
        if conflict_ratio >= 0.75:
            penalty = 12
        elif conflict_ratio >= 0.50:
            penalty = 8
        else:
            return (0, '')

        flag = (f"decision={decision} conflict_ratio={conflict_ratio:.2f} "
                f"({bearish if decision == 'LONG' else bullish} opposing / "
                f"{total_directional} directional) penalty={penalty}")
        return (penalty, flag)

    @staticmethod
    def _check_signal_score_divergence(
        scores_net: str,
        judge_decision: str,
    ) -> Optional[str]:
        """Flag when Judge decision diverges from _scores['net'] consensus.

        Informational only — no penalty. Logged for correlation analysis.
        Returns flag text or None.
        """
        if judge_decision not in ('LONG', 'SHORT'):
            return None

        m = AIQualityAuditor._NET_DIRECTION_RE.match(scores_net)
        if not m:
            return None

        net_direction = m.group(1)  # BULLISH or BEARISH
        if net_direction == 'BULLISH' and judge_decision == 'SHORT':
            return f"net={scores_net} decision={judge_decision}"
        if net_direction == 'BEARISH' and judge_decision == 'LONG':
            return f"net={scores_net} decision={judge_decision}"

        return None

    @staticmethod
    def _check_confidence_risk_coherence(
        judge_confidence: str,
        risk_env_score: int,
        risk_env_level: str,
    ) -> tuple:
        """Check if Judge confidence is appropriate given risk environment.

        Only penalizes overconfidence in danger (HIGH+HIGH).
        Never penalizes conservative caution (asymmetric by design).
        """
        if judge_confidence == 'HIGH' and risk_env_level == 'HIGH':
            flag = f"confidence={judge_confidence} risk_env={risk_env_level}({risk_env_score}) penalty=6"
            return (6, flag)
        return (0, '')

    @staticmethod
    def _check_debate_quality(
        bull_conviction: float,
        bear_conviction: float,
    ) -> Optional[str]:
        """Flag when Bull and Bear conviction spread is suspiciously low.

        Informational only — no penalty. Low spread suggests echo chamber /
        shallow debate where neither side found compelling counter-arguments.
        Returns flag text or None.
        """
        spread = abs(bull_conviction - bear_conviction)
        if spread < AIQualityAuditor._DEBATE_CONVERGENCE_THRESHOLD:
            return (f"bull={bull_conviction:.2f} bear={bear_conviction:.2f} "
                    f"spread={spread:.2f}")
        return None

    @staticmethod
    def _check_reason_diversity(
        decisive_reasons: List[str],
    ) -> Optional[str]:
        """Flag when all decisive_reasons map to the same data category.

        Informational only — no penalty. Single-dimension dependency makes
        the decision fragile.
        """
        if len(decisive_reasons) < 2:
            return None

        # Collect all categories covered by decisive_reasons
        categories_seen: Set[str] = set()
        mapped_count = 0
        for tag in decisive_reasons:
            cats = _TAG_TO_CATEGORIES.get(tag)
            if cats:
                categories_seen.update(cats)
                mapped_count += 1

        # Need >= 2 mapped tags
        if mapped_count < 2:
            return None

        # Single category = fixation
        if len(categories_seen) == 1:
            single_cat = next(iter(categories_seen))
            return f"{mapped_count}/{len(decisive_reasons)} tags from {single_cat}"

        return None

    # Threshold for R1→R2 evidence overlap indicating shallow debate
    _SHALLOW_DEBATE_OVERLAP_THRESHOLD = 0.85

    @staticmethod
    def _check_debate_shallow_round2(
        bull_output: Dict[str, Any],
        bear_output: Dict[str, Any],
    ) -> Optional[str]:
        """Flag when R2 outputs show no meaningful evolution from R1.

        Detects shallow debate where agents repeat their R1 arguments
        without engaging with the opponent's counter-arguments.
        Informational only — no penalty.

        Metrics (pre-computed in multi_agent_analyzer._run_structured_debate):
          _r1_r2_evidence_overlap: Jaccard similarity of R1/R2 evidence tags
          _r1_r2_evidence_new:     Count of new tags introduced in R2
          _r1_r2_conviction_delta: |R2_conviction - R1_conviction|

        A shallow debate has:
          - High overlap (>= 0.85): R2 tags are ~identical to R1
          - Zero new evidence: no new tags introduced
          - Low conviction change: agent didn't update beliefs
        Both agents must show stagnation for the flag to trigger.
        Returns flag text or None.
        """
        stagnant_agents = []
        for label, output in [("Bull", bull_output), ("Bear", bear_output)]:
            overlap = output.get("_r1_r2_evidence_overlap")
            new_ev = output.get("_r1_r2_evidence_new")
            conv_delta = output.get("_r1_r2_conviction_delta")
            # Skip if metrics not available (e.g. text fallback path)
            if overlap is None or new_ev is None or conv_delta is None:
                return None
            if (overlap >= AIQualityAuditor._SHALLOW_DEBATE_OVERLAP_THRESHOLD
                    and new_ev == 0
                    and conv_delta < 0.05):
                stagnant_agents.append(label)

        if len(stagnant_agents) == 2:
            bull_overlap = bull_output.get("_r1_r2_evidence_overlap", 0)
            bear_overlap = bear_output.get("_r1_r2_evidence_overlap", 0)
            return (
                f"both agents stagnant: "
                f"Bull overlap={bull_overlap:.2f} new=0 "
                f"Bear overlap={bear_overlap:.2f} new=0"
            )
        return None

    # v30.3: Tiered penalty weights for missing data categories.
    # Critical categories (directional anchors) incur heavier penalties than
    # auxiliary data sources. Applied per-agent in _calculate_score().
    _CATEGORY_PENALTY: Dict[str, int] = {
        'mtf_1d': 12,           # 1D trend is the directional anchor — missing = near-blind
        'mtf_4h': 10,           # 4H decision layer — core momentum source
        'technical_30m': 8,     # Execution layer — entry timing depends on it
        'order_flow': 5,        # Supporting: CVD/taker/buy ratio
        'derivatives': 5,      # Supporting: FR/OI/liquidations
        'sentiment': 3,         # Auxiliary: global L/S ratio
        'sr_zones': 3,          # Auxiliary: support/resistance context
        'orderbook': 5,         # Supporting: OBI/depth
        'extension_ratio': 5,   # Risk: ATR extension regime
        'volatility_regime': 5, # Risk: ATR% percentile
        'binance_derivatives': 3,  # Auxiliary: top traders/taker ratio
        'position_context': 3,  # State-dependent: liquidation buffer
        'price': 3,             # Basic: dollar values
    }

    # v30.3: Tiered MTF violation penalties by severity.
    _MTF_VIOLATION_PENALTY: Dict[str, int] = {
        'DIRECTION_OVERRIDE': 15,  # Risk Manager re-judging direction = architecture violation
        '30M_DIRECTION': 10,       # Bull/Bear basing direction on 30M alone
        'MISSING_30M': 8,          # Entry Timing not evaluating execution layer
    }

    # v33.1: Removed _MAX_TEXT_PENALTY cap.  With conservative matching
    # (indicator-anchored regexes), text-based false positives are rare.
    # The cap masked REAL errors (8 fabricated citations → still 75 🟡).

    def _calculate_score(self, report: QualityReport) -> int:
        """Calculate 0-100 quality score from audit results.

        v30.3: Tiered weights — critical data categories and severe MTF
        violations incur heavier penalties than auxiliary gaps.
        """
        penalty = 0

        # Per-agent coverage penalties (v30.3: category-aware weights)
        for role, result in report.agent_results.items():
            for cat in result.missing_categories:
                penalty += self._CATEGORY_PENALTY.get(cat, 5)
            if 'EMPTY_OUTPUT' in str(result.flags):
                penalty += 10
            # v30.3: MTF violation severity-aware penalties
            for violation in result.mtf_violations:
                matched = False
                for key, weight in self._MTF_VIOLATION_PENALTY.items():
                    if key in violation:
                        penalty += weight
                        matched = True
                        break
                if not matched:
                    penalty += 8  # Default for unknown violations
            penalty += len(result.skip_signal_violations) * 3

        # Confluence accuracy penalties
        if report.confluence_audit:
            ca = report.confluence_audit
            if ca.alignment_mismatch:
                diff = abs(ca.aligned_layers_declared - ca.aligned_layers_actual)
                penalty += diff * 10
            if ca.confidence_mismatch:
                penalty += 10
            if not ca.layers_declared:
                penalty += 15

        # Text-based citation/value/zone penalties.
        # v33.1: No cap — conservative matching (indicator-anchored regexes)
        # ensures low false positive rate.  Real errors should penalize fully.
        penalty += report.citation_errors * 8   # Directional reversals
        penalty += report.value_errors * 5      # Number accuracy
        penalty += report.zone_errors * 5       # Zone mismatches
        penalty += report.phantom_citations * 8  # Fabricated data from unavailable source
        penalty += report.narrative_misreads * 4  # Contradictory adjective for indicator value
        # CONTRADICTORY_OMISSION is informational only — no score penalty.
        # Selective emphasis is partly legitimate for advocate roles (Bull/Bear).

        # Counter-trend penalty
        if report.counter_trend_detected and not report.counter_trend_flagged_by_entry_timing:
            penalty += 15

        # v34.0: Logic-level coherence penalties
        penalty += report.reason_signal_conflict      # 0 / 8 / 12
        penalty += report.confidence_risk_conflict     # 0 / 6
        # signal_score_divergence, debate_convergence, single_dimension_decision
        # are informational only — NO penalty

        return max(0, 100 - penalty)
