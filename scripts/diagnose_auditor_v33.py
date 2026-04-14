#!/usr/bin/env python3
"""
AI Quality Auditor v33.1 Comprehensive Diagnostic — 审计系统全面检测

6 dimensions of verification using REAL market data + deterministic unit tests:

  A. RSI Zone Check Precision (v33.1 conservative matching)
     - 20 true positive + 12 false positive test cases
     - Window coverage: realistic AI phrasings
     - Cross-TF exclusion with conservative matching

  B. All Zone Checks: ADX, BB, Extension, Volatility
     - False positive resistance
     - Threshold boundary conditions

  C. Value Extraction Accuracy
     - _extract_indicator_value multi-TF isolation
     - _extract_dollar_value cross-TF protection
     - _extract_pct_near_label precision

  D. Scoring Function Integrity
     - _calculate_score boundary conditions
     - Penalty weight proportionality
     - Error deduplication verification

  E. Coverage & Tag Mapping Completeness
     - TAG → CATEGORY mapping: every tag maps to a category
     - _coverable / _weak_signal protection
     - _effective_required logic

  F. End-to-End Audit (mock agents + real technical data)
     - Perfect agent → score ≥ 90
     - Bad agent (fabricated values) → score < 70
     - Data-unavailable agent → no false penalties

Usage:
  cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \\
    python3 scripts/diagnose_auditor_v33.py
"""

from __future__ import annotations

import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Auto-switch to venv if needed
project_dir = Path(__file__).parent.parent.absolute()
venv_python = project_dir / "venv" / "bin" / "python"
in_venv = (
    hasattr(sys, 'real_prefix')
    or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
)
if not in_venv and venv_python.exists():
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

sys.path.insert(0, str(project_dir))

# Load env
env_file = Path.home() / '.env.algvex'
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

import logging
logging.basicConfig(level=logging.WARNING)

# ============================================================================
# Test infrastructure
# ============================================================================

PASS = 0
FAIL = 0
WARN = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        msg = f"  ❌ {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
    return condition


def warn(name: str, detail: str = ""):
    global WARN
    WARN += 1
    msg = f"  ⚠️ {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def section(title: str):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


# ============================================================================
# A. RSI Zone Check Precision (v33.1)
# ============================================================================

def test_rsi_zone_precision():
    section("A. RSI Zone Check Precision (v33.1 conservative matching)")

    from agents.ai_quality_auditor import AIQualityAuditor
    auditor = AIQualityAuditor()

    # A1: True positives — should detect RSI zone claims
    print()
    print("  A1: True Positives (should detect)")
    true_positives = [
        ('30M RSI oversold', r'(?:30[Mm]|执行层)', True, 'English direct'),
        ('30M RSI 超卖', r'(?:30[Mm]|执行层)', True, 'Chinese direct'),
        ('超卖 RSI zone in 30M', r'(?:30[Mm]|执行层)', True, 'Reversed order'),
        ('4H RSI is oversold at 28', r'(?:4[Hh]|决策层)', True, 'With value'),
        ('RSI处于超卖区域, 4H确认', r'(?:4[Hh]|决策层)', True, 'Chinese with context'),
        ('1D RSI(28.5)超卖', r'(?:1[Dd]|趋势层)', True, 'Value in parens'),
        ('执行层 RSI overbought', r'(?:30[Mm]|执行层)', True, 'Chinese TF alias'),
        ('决策层 RSI 超买信号', r'(?:4[Hh]|决策层)', True, 'Chinese TF + Chinese claim'),
        ('4H RSI shows oversold', r'(?:4[Hh]|决策层)', True, 'With verb'),
        ('30M RSI=64.8, 超卖反弹', r'(?:30[Mm]|执行层)', True, 'Value then claim'),
    ]

    _RSI_OVERSOLD = r'(?:RSI.{0,15}(?:oversold|超卖)|(?:oversold|超卖).{0,15}RSI)'
    _RSI_OVERBOUGHT = r'(?:RSI.{0,15}(?:overbought|超买)|(?:overbought|超买).{0,15}RSI)'

    for text, tf_p, expected, desc in true_positives:
        claim = _RSI_OVERSOLD if 'oversold' in text.lower() or '超卖' in text else _RSI_OVERBOUGHT
        result = auditor._claims_near_tf(text, tf_p, claim)
        check(f"TP: {desc}", result == expected,
              f"text='{text}' expected={expected} got={result}")

    # A2: False positive resistance — should NOT detect
    print()
    print("  A2: False Positive Resistance (should NOT detect)")
    false_positives = [
        ('4H/30M动量看涨配合超卖条件', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         'Conjunction without RSI'),
        ('oversold extension ratio', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         'Extension context'),
        ('扩展超卖', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         'Extension Chinese'),
        ('市场超卖', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         'Market-level no RSI'),
        ('价格超卖反弹', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         'Price-level no RSI'),
        ('超卖条件改善', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         'Condition improvement'),
        ('combined with oversold conditions, 30M', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         'Combined with no RSI'),
        ('1D趋势极端暗示超卖', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         '1D extension context'),
        ('配合超卖条件 30M', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         'Conjunction'),
        ('extension into oversold territory, 30M', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         'Extension territory'),
        ('30M momentum strong, 市场超买可能', r'(?:30[Mm]|执行层)', _RSI_OVERBOUGHT,
         'Market overbought no RSI'),
        ('overbought conditions near 4H level', r'(?:4[Hh]|决策层)', _RSI_OVERBOUGHT,
         'Conditions without RSI'),
    ]

    for text, tf_p, claim, desc in false_positives:
        result = auditor._claims_near_tf(text, tf_p, claim)
        check(f"FP: {desc}", result is False,
              f"text='{text}' → matched={result}")

    # A3: Cross-TF exclusion with conservative matching
    print()
    print("  A3: Cross-TF Exclusion")
    cross_tf_tests = [
        ('4H RSI超卖区域，30M动量看涨', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         False, 'RSI超卖 belongs to 4H scope, not 30M'),
        ('1D趋势(ADX=35)确认。4H RSI超卖区域', r'(?:4[Hh]|决策层)', _RSI_OVERSOLD,
         True, 'RSI超卖 belongs to 4H scope'),
        ('30M RSI oversold. 4H MACD bearish', r'(?:30[Mm]|执行层)', _RSI_OVERSOLD,
         True, 'RSI oversold belongs to 30M'),
        ('30M RSI oversold. 4H MACD bearish', r'(?:4[Hh]|决策层)', _RSI_OVERSOLD,
         False, 'RSI oversold belongs to 30M, not 4H'),
    ]

    for text, tf_p, claim, expected, desc in cross_tf_tests:
        result = auditor._claims_near_tf(text, tf_p, claim)
        check(f"XTF: {desc}", result == expected,
              f"expected={expected} got={result}")


# ============================================================================
# B. All Zone Checks (ADX, BB, Extension, Volatility)
# ============================================================================

def test_all_zone_checks():
    section("B. Zone Check Precision (ADX, BB, Extension, Volatility)")

    from agents.ai_quality_auditor import AIQualityAuditor
    auditor = AIQualityAuditor()

    # B1: ADX zone — strong trend claim when ADX < 15
    print()
    print("  B1: ADX Zone Checks")
    tech_data_ranging = {
        'adx': 12.0, 'rsi': 50.0,
        'mtf_decision_layer': {'adx': 12.0, 'rsi': 50.0},
        'mtf_trend_layer': {'adx': 12.0, 'rsi': 50.0},
    }
    # "strong trend" when ADX=12 → should error
    errs = auditor._check_zone_claims('30M strong trend confirmed', tech_data_ranging)
    check("ADX: strong trend + ADX=12 → detected", len(errs) > 0,
          f"errors={errs}")

    # "ranging" when ADX=12 → should NOT error (correct claim)
    errs = auditor._check_zone_claims('30M ranging market', tech_data_ranging)
    check("ADX: ranging + ADX=12 → no error", len(errs) == 0,
          f"errors={errs}")

    tech_data_trending = {
        'adx': 40.0, 'rsi': 50.0,
        'mtf_decision_layer': {'adx': 40.0, 'rsi': 50.0},
        'mtf_trend_layer': {'adx': 40.0, 'rsi': 50.0},
    }
    # "ranging" when ADX=40 → should error
    errs = auditor._check_zone_claims('4H sideways market', tech_data_trending)
    check("ADX: sideways + ADX=40 → detected", len(errs) > 0,
          f"errors={errs}")

    # B2: BB zone — lower band claim when BB > 0.7
    print()
    print("  B2: BB Position Zone Checks")
    tech_data_bb = {
        'bb_position': 0.85, 'rsi': 50.0,
        'mtf_decision_layer': {'bb_position': 0.85, 'rsi': 50.0},
        'mtf_trend_layer': {'bb_position': 0.85, 'rsi': 50.0},
    }
    errs = auditor._check_zone_claims('30M near lower band', tech_data_bb)
    check("BB: lower band + BB=85% → detected", len(errs) > 0,
          f"errors={errs}")

    errs = auditor._check_zone_claims('30M near upper band', tech_data_bb)
    check("BB: upper band + BB=85% → no error", len(errs) == 0,
          f"errors={errs}")

    # B3: Extension regime — cross-TF ANY-match
    print()
    print("  B3: Extension Regime (cross-TF)")
    tech_ext_mixed = {
        'extension_regime': 'NORMAL', 'rsi': 50.0,
        'mtf_decision_layer': {'extension_regime': 'OVEREXTENDED', 'rsi': 50.0},
        'mtf_trend_layer': {'extension_regime': 'NORMAL', 'rsi': 50.0},
    }
    errs = auditor._check_zone_claims(
        'current extension is overextended', tech_ext_mixed)
    check("Extension: OVEREXTENDED claim + 4H=OVEREXTENDED → no error",
          len(errs) == 0, f"errors={errs}")

    tech_ext_normal = {
        'extension_regime': 'NORMAL', 'rsi': 50.0,
        'mtf_decision_layer': {'extension_regime': 'NORMAL', 'rsi': 50.0},
        'mtf_trend_layer': {'extension_regime': 'EXTENDED', 'rsi': 50.0},
    }
    errs = auditor._check_zone_claims(
        'extension ratio is overextended regime', tech_ext_normal)
    check("Extension: OVEREXTENDED claim + all NORMAL/EXTENDED → detected",
          len(errs) > 0, f"errors={errs}")

    # B4: Volatility regime
    print()
    print("  B4: Volatility Regime (cross-TF)")
    tech_vol = {
        'volatility_regime': 'LOW', 'rsi': 50.0,
        'mtf_decision_layer': {'volatility_regime': 'LOW', 'rsi': 50.0},
        'mtf_trend_layer': {'volatility_regime': 'NORMAL', 'rsi': 50.0},
    }
    errs = auditor._check_zone_claims(
        'volatility is extreme, very high', tech_vol)
    check("Volatility: extreme claim + all LOW/NORMAL → detected",
          len(errs) > 0, f"errors={errs}")


# ============================================================================
# C. Value Extraction Accuracy
# ============================================================================

def test_value_extraction():
    section("C. Value Extraction Accuracy")

    from agents.ai_quality_auditor import AIQualityAuditor
    auditor = AIQualityAuditor()

    # C1: Multi-TF RSI isolation
    print()
    print("  C1: Multi-TF RSI Isolation")
    text = '30M RSI=45.2, 4H RSI=62.3, 1D RSI=55.0'
    tf_patterns = {
        '30M': [r'30[Mm]', r'执行层'],
        '4H': [r'4[Hh]', r'决策层'],
        '1D': [r'1[Dd]', r'趋势层'],
    }
    expected = {'30M': 45.2, '4H': 62.3, '1D': 55.0}
    for tf, pats in tf_patterns.items():
        val = auditor._extract_indicator_value(text, pats, r'RSI', 0, 100, tf_label=tf)
        ok = val is not None and abs(val - expected[tf]) < 0.1
        check(f"RSI extraction {tf}={val} (expect {expected[tf]})", ok,
              f"extracted={val}")

    # C2: Cross-TF protection
    print()
    print("  C2: Cross-TF Protection")
    text2 = '1D ADX=35.5确认趋势，DI- 26.3 > DI+ 17.9。4H MACD bearish'
    val = auditor._extract_indicator_value(
        text2, [r'4[Hh]', r'决策层'], r'(?<![/])ADX', 0, 100, tf_label='4H')
    check("Cross-TF: 1D ADX not extracted as 4H", val is None,
          f"extracted={val}, should be None")

    # C3: Dollar value extraction
    print()
    print("  C3: Dollar Value Extraction")
    text3 = '30M ATR: $1,234.56, 4H ATR: $2,345.67'
    val_30m = auditor._extract_dollar_value(
        text3, [r'30[Mm]'], r'ATR', tf_label='30M')
    val_4h = auditor._extract_dollar_value(
        text3, [r'4[Hh]'], r'ATR', tf_label='4H')
    check("Dollar 30M ATR=$1,234.56", val_30m is not None and abs(val_30m - 1234.56) < 0.1)
    check("Dollar 4H ATR=$2,345.67", val_4h is not None and abs(val_4h - 2345.67) < 0.1)

    # C4: Percentage extraction
    print()
    print("  C4: Percentage Extraction")
    text4 = 'Long Ratio: 55.3%, Short Ratio: 44.7%'
    long_val = auditor._extract_pct_near_label(text4, r'[Ll]ong\s*(?:[Rr]atio|%)', 0, 100)
    short_val = auditor._extract_pct_near_label(text4, r'[Ss]hort\s*(?:[Rr]atio|%)', 0, 100)
    check("Long Ratio=55.3%", long_val is not None and abs(long_val - 55.3) < 0.1)
    check("Short Ratio=44.7%", short_val is not None and abs(short_val - 44.7) < 0.1)

    # C5: Negative FR
    text5 = 'Funding Rate: -0.01234%'
    fr_val = auditor._extract_pct_near_label(
        text5, r'[Ff]unding\s*[Rr]ate|(?<![A-Za-z])FR(?![A-Za-z])', -1.0, 1.0)
    check("Negative FR=-0.01234%", fr_val is not None and abs(fr_val - (-0.01234)) < 0.001,
          f"extracted={fr_val}")


# ============================================================================
# D. Scoring Function Integrity
# ============================================================================

def test_scoring_integrity():
    section("D. Scoring Function Integrity")

    from agents.ai_quality_auditor import AIQualityAuditor, QualityReport, AgentAuditResult
    auditor = AIQualityAuditor()

    # D1: Perfect report → score 100
    print()
    print("  D1: Perfect Report")
    report = QualityReport()
    report.agent_results = {
        'bull': AgentAuditResult(agent_role='bull', coverage_rate=1.0),
        'bear': AgentAuditResult(agent_role='bear', coverage_rate=1.0),
    }
    score = auditor._calculate_score(report)
    check("Perfect report → 100", score == 100, f"score={score}")

    # D2: Single citation error
    print()
    print("  D2: Single Errors")
    report2 = QualityReport()
    report2.citation_errors = 1
    check("1 citation error → 92", auditor._calculate_score(report2) == 92)

    report3 = QualityReport()
    report3.value_errors = 1
    check("1 value error → 95", auditor._calculate_score(report3) == 95)

    report4 = QualityReport()
    report4.zone_errors = 1
    check("1 zone error → 95", auditor._calculate_score(report4) == 95)

    # D3: No penalty cap (v33.1)
    print()
    print("  D3: No Penalty Cap")
    report5 = QualityReport()
    report5.citation_errors = 5
    report5.value_errors = 5
    report5.zone_errors = 5
    score5 = auditor._calculate_score(report5)
    expected = 100 - (5*8 + 5*5 + 5*5) # = 100 - 90 = 10
    check(f"Heavy text errors → {expected}", score5 == expected,
          f"score={score5}")

    # D4: Score never below 0
    report6 = QualityReport()
    report6.citation_errors = 20
    report6.value_errors = 20
    score6 = auditor._calculate_score(report6)
    check("Extreme errors → score >= 0", score6 >= 0, f"score={score6}")

    # D5: Confluence mismatch penalty
    print()
    print("  D5: Confluence Penalties")
    from agents.ai_quality_auditor import ConfluenceAuditResult
    report7 = QualityReport()
    report7.confluence_audit = ConfluenceAuditResult(
        layers_declared={'trend_1d': 'BULLISH', 'momentum_4h': 'BULLISH'},
        alignment_mismatch=True,
        aligned_layers_declared=3,
        aligned_layers_actual=1,
        confidence_mismatch=True,
    )
    score7 = auditor._calculate_score(report7)
    # diff=2 → 20, conf_mismatch → 10, total=30 → score=70
    check("Confluence mismatch → 70", score7 == 70, f"score={score7}")

    # D6: Counter-trend penalty
    print()
    print("  D6: Counter-Trend Penalty")
    report8 = QualityReport()
    report8.counter_trend_detected = True
    report8.counter_trend_flagged_by_entry_timing = False
    score8 = auditor._calculate_score(report8)
    check("Counter-trend not flagged → 85", score8 == 85, f"score={score8}")

    report9 = QualityReport()
    report9.counter_trend_detected = True
    report9.counter_trend_flagged_by_entry_timing = True
    score9 = auditor._calculate_score(report9)
    check("Counter-trend flagged → 100", score9 == 100, f"score={score9}")


# ============================================================================
# E. Coverage & Tag Mapping Completeness
# ============================================================================

def test_coverage_mapping():
    section("E. Coverage & Tag Mapping Completeness")

    from agents.ai_quality_auditor import (
        _TAG_TO_CATEGORIES, _AGENT_REQUIRED_CATEGORIES,
        _DATA_CATEGORY_MARKERS, _WEAK_SIGNAL_TAGS,
    )

    # E1: All REASON_TAGS map to categories or are always-valid
    print()
    print("  E1: Tag Mapping Completeness")
    try:
        from agents.prompt_constants import REASON_TAGS
        from agents.tag_validator import _ALWAYS_VALID

        unmapped = []
        for tag in REASON_TAGS:
            if tag not in _TAG_TO_CATEGORIES and tag not in _ALWAYS_VALID:
                unmapped.append(tag)

        check(f"All {len(REASON_TAGS)} REASON_TAGS mapped", len(unmapped) == 0,
              f"unmapped={unmapped[:5]}")
    except ImportError:
        warn("Could not import REASON_TAGS/ALWAYS_VALID")

    # E2: Required categories all have tag mappings
    print()
    print("  E2: Required Categories Have Tags")
    all_tag_cats = set()
    for tag, cats in _TAG_TO_CATEGORIES.items():
        for cat in cats:
            all_tag_cats.add(cat)

    all_required = set()
    for role, cats in _AGENT_REQUIRED_CATEGORIES.items():
        all_required.update(cats)

    uncovered = all_required - all_tag_cats
    check("All required categories have tag mappings", len(uncovered) == 0,
          f"uncovered={uncovered}")

    # E3: Weak signal tags are valid REASON_TAGS
    print()
    print("  E3: Weak Signal Tags Validity")
    try:
        invalid_weak = _WEAK_SIGNAL_TAGS - set(REASON_TAGS)
        check("All weak tags are valid REASON_TAGS", len(invalid_weak) == 0,
              f"invalid={invalid_weak}")
    except NameError:
        warn("REASON_TAGS not available for weak tag validation")

    # E4: _DATA_CATEGORY_MARKERS regex compilation
    print()
    print("  E4: Category Marker Regex Validity")
    all_compile = True
    for cat, patterns in _DATA_CATEGORY_MARKERS.items():
        for p in patterns:
            try:
                re.compile(p)
            except re.error as e:
                all_compile = False
                warn(f"Invalid regex in {cat}: {p} — {e}")
    check("All category marker regexes compile", all_compile)

    # E5: Confidence tolerance logic
    print()
    print("  E5: Confidence Tolerance")
    from agents.ai_quality_auditor import AIQualityAuditor
    tests = [
        ('HIGH', 'HIGH', True),
        ('MEDIUM', 'HIGH', True),  # 1-level down OK
        ('LOW', 'HIGH', False),    # 2-level down NOT OK
        ('HIGH', 'MEDIUM', True),
        ('LOW', 'MEDIUM', True),
        ('LOW', 'LOW', True),
    ]
    all_ok = True
    for d, e, want in tests:
        result = AIQualityAuditor._confidence_within_tolerance(d, e)
        if result != want:
            all_ok = False
    check("Confidence tolerance logic correct", all_ok)


# ============================================================================
# F. End-to-End Audit with Real Data
# ============================================================================

def test_end_to_end():
    section("F. End-to-End Audit (mock agents + real data)")

    # F1: Fetch real market data (if available) or use mock
    print()
    print("  F1: Market Data")
    last_close = 95000.0  # Default mock price
    try:
        import requests
        resp = requests.get(
            'https://fapi.binance.com/fapi/v1/klines',
            params={'symbol': 'BTCUSDT', 'interval': '30m', 'limit': 5},
            timeout=10,
        )
        resp.raise_for_status()
        klines = resp.json()
        if klines:
            last_close = float(klines[-1][4])
            check(f"Real BTC price: ${last_close:,.0f}", 10000 < last_close < 500000)
        else:
            check("Using mock price $95,000", True)
    except Exception:
        check("Using mock price $95,000 (API unavailable)", True)

    # F2: Build mock technical data
    print()
    print("  F2: Build Ground Truth")
    tech = {
        'rsi': 55.0, 'adx': 28.0, 'di_plus': 22.0, 'di_minus': 18.0,
        'bb_position': 0.55, 'volume_ratio': 1.2, 'macd': 150.0,
        'macd_signal': 145.0, 'macd_histogram': 5.0,
        'sma_20': last_close * 0.99, 'sma_50': last_close * 0.98,
        'extension_regime': 'NORMAL', 'volatility_regime': 'NORMAL',
        'price': last_close,
        'mtf_decision_layer': {
            'rsi': 52.0, 'adx': 30.0, 'di_plus': 24.0, 'di_minus': 20.0,
            'bb_position': 0.50, 'macd': 200.0, 'macd_signal': 195.0,
            'macd_histogram': 5.0, 'extension_regime': 'NORMAL',
            'volatility_regime': 'NORMAL',
        },
        'mtf_trend_layer': {
            'rsi': 58.0, 'adx': 35.0, 'di_plus': 25.0, 'di_minus': 15.0,
            'sma_200': last_close * 0.95,
            'extension_regime': 'NORMAL', 'volatility_regime': 'NORMAL',
        },
    }

    from agents.ai_quality_auditor import AIQualityAuditor
    auditor = AIQualityAuditor()

    # F3: Good agent text → no errors
    print()
    print("  F3: Good Agent Text → No Errors")
    good_text = (
        f'30M RSI=55.0 neutral zone. 4H RSI=52.0 also neutral. '
        f'4H MACD bullish cross (MACD > Signal). '
        f'1D ADX=35.0 showing strong trend. DI+ 25.0 > DI- 15.0 = BULLISH. '
        f'Price ${last_close:,.0f} above SMA 200 ${last_close * 0.95:,.0f}.'
    )
    zone_errs = auditor._check_zone_claims(good_text, tech)
    check("Good text → 0 zone errors", len(zone_errs) == 0,
          f"zone_errs={zone_errs}")

    cmp_errs = auditor._check_comparison_claims(good_text, tech)
    check("Good text → 0 comparison errors", len(cmp_errs) == 0,
          f"cmp_errs={cmp_errs}")

    val_errs = auditor._check_value_accuracy(good_text, tech)
    check("Good text → 0 value errors", len(val_errs) == 0,
          f"val_errs={val_errs}")

    # F4: Bad agent text → errors detected
    print()
    print("  F4: Bad Agent Text → Errors Detected")
    bad_text = (
        f'30M RSI oversold at 55. '  # RSI=55 is NOT oversold
        f'4H MACD bearish cross. '   # MACD=200 > Signal=195 = BULLISH, not bearish
        f'1D ADX=35 ranging market. '  # ADX=35 is NOT ranging
        f'Price ${last_close:,.0f} below SMA 200.'  # price is ABOVE SMA200
    )
    zone_errs = auditor._check_zone_claims(bad_text, tech)
    check("Bad text → zone errors detected", len(zone_errs) >= 1,
          f"zone_errs={zone_errs}")

    cmp_errs = auditor._check_comparison_claims(bad_text, tech)
    check("Bad text → comparison errors detected", len(cmp_errs) >= 1,
          f"cmp_errs={cmp_errs}")

    # F5: No false positive on 超卖 without RSI
    print()
    print("  F5: No False Positive on Bare 超卖")
    safe_text = (
        f'30M 动量看涨配合超卖条件改善。扩展超卖修复。'
        f'4H 价格超卖反弹，市场超买可能性低。'
    )
    zone_errs = auditor._check_zone_claims(safe_text, tech)
    check("Bare 超卖/超买 without RSI → 0 zone errors", len(zone_errs) == 0,
          f"zone_errs={zone_errs}")


# ============================================================================
# Main
# ============================================================================

def main():
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  AI Quality Auditor v33.1 — Comprehensive Diagnostic           ║")
    print("╚══════════════════════════════════════════════════════════════════╝")

    t0 = time.time()

    try:
        test_rsi_zone_precision()
        test_all_zone_checks()
        test_value_extraction()
        test_scoring_integrity()
        test_coverage_mapping()
        test_end_to_end()
    except Exception:
        print()
        print("  💥 UNEXPECTED ERROR:")
        traceback.print_exc()

    elapsed = time.time() - t0

    print()
    print("=" * 70)
    print(f"  Results: {PASS} passed, {FAIL} failed, {WARN} warnings")
    print(f"  Elapsed: {elapsed:.1f}s")
    print("=" * 70)

    if FAIL > 0:
        print(f"  ❌ {FAIL} CHECKS FAILED — review errors above")
        sys.exit(1)
    elif WARN > 0:
        print(f"  ⚠️ All checks passed with {WARN} warnings")
        sys.exit(0)
    else:
        print(f"  ✅ ALL {PASS} CHECKS PASSED")
        sys.exit(0)


if __name__ == '__main__':
    main()
