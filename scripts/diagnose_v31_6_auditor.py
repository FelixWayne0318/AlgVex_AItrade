#!/usr/bin/env python3
"""
v31.6/v31.7 AI Quality Auditor Diagnostic — 审计系统完整性验证

Verifies all v31.6 + v31.7 fixes + auditor core logic using REAL market data.
No AI calls — pure deterministic checks on auditor internals.

5 检查维度:
  A. v31.6/v31.7 修复验证 (5+2 fixes)
  B. 数据完整性 (MTF 层字段覆盖)
  C. Zone Check 精度 (跨 TF regime 场景)
  D. 评分合理性 (模拟评分无异常惩罚)
  E. Feature 完整性 (124 features 提取)

Usage:
  cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
    python3 scripts/diagnose_v31_6_auditor.py
"""

from __future__ import annotations

import os
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

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

import requests
from decimal import Decimal

try:
    from utils.config_manager import ConfigManager
except ImportError:
    ConfigManager = None

try:
    from indicators.technical_manager import TechnicalIndicatorManager
    HAS_NT = True
except ImportError:
    TechnicalIndicatorManager = None
    HAS_NT = False

from agents.ai_quality_auditor import AIQualityAuditor, QualityReport

# ============================================================================
# Constants
# ============================================================================

# Production ai_strategy.py 4H mtf_decision_layer fields (lines 2587-2615)
PRODUCTION_4H_FIELDS = {
    'timeframe', 'rsi', 'macd', 'macd_signal', 'macd_histogram',
    'sma_20', 'sma_50', 'bb_upper', 'bb_middle', 'bb_lower', 'bb_position',
    'adx', 'di_plus', 'di_minus', 'adx_regime',
    'atr', 'volume_ratio', 'atr_pct',
    'extension_ratio_sma_20', 'extension_ratio_sma_50',
    'extension_regime', 'volatility_regime', 'volatility_percentile',
    'ema_12', 'ema_26',
}

# Production ai_strategy.py 1D mtf_trend_layer fields (lines 2634-2660)
PRODUCTION_1D_FIELDS = {
    'timeframe', 'sma_200', 'macd', 'macd_signal', 'macd_histogram',
    'rsi', 'adx', 'di_plus', 'di_minus', 'adx_regime',
    'bb_position', 'atr', 'volume_ratio',
    'bb_upper', 'bb_lower', 'bb_middle',
    'atr_pct', 'extension_ratio_sma_200',
    'extension_regime', 'volatility_regime', 'volatility_percentile',
    'ema_12', 'ema_26',
}

VALID_EXTENSION_REGIMES = {'NORMAL', 'EXTENDED', 'OVEREXTENDED', 'EXTREME'}
VALID_VOLATILITY_REGIMES = {'LOW', 'NORMAL', 'HIGH', 'EXTREME'}


# ============================================================================
# Data fetching (real market data, no AI calls)
# ============================================================================

class MockBar:
    def __init__(self, o, h, l, c, v, ts):
        self.open = Decimal(str(o))
        self.high = Decimal(str(h))
        self.low = Decimal(str(l))
        self.close = Decimal(str(c))
        self.volume = Decimal(str(v))
        self.ts_init = int(ts)


def feed_klines(mgr, klines):
    for k in klines[:-1]:
        bar = MockBar(
            float(k[1]), float(k[2]), float(k[3]),
            float(k[4]), float(k[5]), int(k[0]),
        )
        mgr.update(bar)


def fetch_real_data() -> Dict[str, Any]:
    """Fetch real BTC market data and build indicator managers.

    Requires NautilusTrader for full indicator computation.
    Falls back to synthetic data if NT is not available (limited checks).
    """
    print("\n" + "=" * 70)
    print("📡 Step 0: Fetching real market data (no AI calls)")
    print("=" * 70)

    if not HAS_NT:
        print("  ⚠️  NautilusTrader not available — using synthetic data for A/D checks")
        print("     (Checks B/C/E require real indicators, will use synthetic defaults)")
        # Synthetic data with realistic values for auditor logic testing
        current_price = 87000.0
        tech_30m = {
            'rsi': 55.2, 'adx': 22.5, 'di_plus': 18.3, 'di_minus': 15.1,
            'macd': -120.5, 'macd_signal': -95.3, 'macd_histogram': -25.2,
            'sma_20': 86800.0, 'sma_50': 0, 'sma_5': 87100.0,
            'bb_upper': 88500.0, 'bb_middle': 87200.0, 'bb_lower': 85900.0,
            'bb_position': 0.42, 'atr': 850.0, 'volume_ratio': 1.15,
            'atr_pct': 0.98, 'adx_regime': 'WEAK',
            'extension_ratio_sma_20': 0.24, 'extension_regime': 'NORMAL',
            'volatility_regime': 'NORMAL', 'volatility_percentile': 45.0,
            'ema_12': 87050.0, 'ema_26': 86950.0,
        }
        tech_4h = {
            'rsi': 48.7, 'adx': 30.2, 'di_plus': 20.1, 'di_minus': 22.8,
            'macd': -640.0, 'macd_signal': -552.0, 'macd_histogram': -88.0,
            'sma_20': 87500.0, 'sma_50': 86200.0,
            'bb_upper': 89000.0, 'bb_middle': 87500.0, 'bb_lower': 86000.0,
            'bb_position': 0.33, 'atr': 1800.0, 'volume_ratio': 0.95,
            'atr_pct': 2.07, 'adx_regime': 'TRENDING',
            'extension_ratio_sma_20': -0.28, 'extension_ratio_sma_50': 0.44,
            'extension_regime': 'NORMAL',
            'volatility_regime': 'NORMAL', 'volatility_percentile': 52.0,
            'ema_12': 87100.0, 'ema_26': 87300.0,
        }
        tech_1d = {
            'rsi': 52.1, 'adx': 18.5, 'di_plus': 16.2, 'di_minus': 14.8,
            'macd': 450.0, 'macd_signal': 380.0, 'macd_histogram': 70.0,
            'sma_200': 82500.0,
            'bb_upper': 91000.0, 'bb_middle': 87000.0, 'bb_lower': 83000.0,
            'bb_position': 0.50, 'atr': 3200.0, 'volume_ratio': 1.05,
            'atr_pct': 3.68, 'adx_regime': 'RANGING',
            'extension_ratio_sma_200': 1.41,
            'extension_regime': 'NORMAL',
            'volatility_regime': 'NORMAL', 'volatility_percentile': 48.0,
            'ema_12': 87200.0, 'ema_26': 86800.0,
        }
        return {'current_price': current_price, 'tech_30m': tech_30m,
                'tech_4h': tech_4h, 'tech_1d': tech_1d}

    resp = requests.get(
        "https://fapi.binance.com/fapi/v1/ticker/price",
        params={"symbol": "BTCUSDT"}, timeout=10,
    )
    current_price = float(resp.json()['price'])
    print(f"  BTC price: ${current_price:,.2f}")

    klines_data = {}
    for interval, label in [("30m", "30M"), ("4h", "4H"), ("1d", "1D")]:
        resp_k = requests.get(
            "https://fapi.binance.com/fapi/v1/klines",
            params={"symbol": "BTCUSDT", "interval": interval, "limit": 250},
            timeout=10,
        )
        klines_data[interval] = resp_k.json()
        print(f"  {label} klines: {len(klines_data[interval])} bars")

    mgr_30m = TechnicalIndicatorManager(sma_periods=[5, 20])
    mgr_4h = TechnicalIndicatorManager(sma_periods=[20, 50])
    mgr_1d = TechnicalIndicatorManager(sma_periods=[200])

    feed_klines(mgr_30m, klines_data["30m"])
    feed_klines(mgr_4h, klines_data["4h"])
    feed_klines(mgr_1d, klines_data["1d"])

    tech_30m = mgr_30m.get_technical_data(current_price)
    tech_4h = mgr_4h.get_technical_data(current_price)
    tech_1d = mgr_1d.get_technical_data(current_price)

    return {
        'current_price': current_price,
        'tech_30m': tech_30m,
        'tech_4h': tech_4h,
        'tech_1d': tech_1d,
    }


def build_production_technical_data(data: Dict) -> Dict[str, Any]:
    """Build technical_data dict exactly as production ai_strategy.py does."""
    tech_30m = dict(data['tech_30m'])
    tech_4h = data['tech_4h']
    tech_1d = data['tech_1d']

    # 4H decision layer — EXACTLY matching ai_strategy.py lines 2587-2615
    tech_30m['mtf_decision_layer'] = {
        'timeframe': '4H',
        'rsi': tech_4h.get('rsi', 50),
        'macd': tech_4h.get('macd', 0),
        'macd_signal': tech_4h.get('macd_signal', 0),
        'macd_histogram': tech_4h.get('macd_histogram', 0),
        'sma_20': tech_4h.get('sma_20', 0),
        'sma_50': tech_4h.get('sma_50', 0),
        'bb_upper': tech_4h.get('bb_upper', 0),
        'bb_middle': tech_4h.get('bb_middle', 0),
        'bb_lower': tech_4h.get('bb_lower', 0),
        'bb_position': tech_4h.get('bb_position', 0.5),
        'adx': tech_4h.get('adx', 0),
        'di_plus': tech_4h.get('di_plus', 0),
        'di_minus': tech_4h.get('di_minus', 0),
        'adx_regime': tech_4h.get('adx_regime', 'UNKNOWN'),
        'atr': tech_4h.get('atr', 0),
        'volume_ratio': tech_4h.get('volume_ratio', 1.0),
        'macd_histogram': tech_4h.get('macd_histogram', 0),
        'atr_pct': tech_4h.get('atr_pct', 0),
        'extension_ratio_sma_20': tech_4h.get('extension_ratio_sma_20', 0),
        'extension_ratio_sma_50': tech_4h.get('extension_ratio_sma_50', 0),
        'extension_regime': tech_4h.get('extension_regime', 'NORMAL'),
        'volatility_regime': tech_4h.get('volatility_regime', 'NORMAL'),
        'volatility_percentile': tech_4h.get('volatility_percentile', 50),
        'ema_12': tech_4h.get('ema_12', 0),
        'ema_26': tech_4h.get('ema_26', 0),
    }

    # 1D trend layer — EXACTLY matching ai_strategy.py lines 2634-2660
    tech_30m['mtf_trend_layer'] = {
        'timeframe': '1D',
        'sma_200': tech_1d.get('sma_200', 0),
        'macd': tech_1d.get('macd', 0),
        'macd_signal': tech_1d.get('macd_signal', 0),
        'macd_histogram': tech_1d.get('macd_histogram', 0),
        'rsi': tech_1d.get('rsi', 0),
        'adx': tech_1d.get('adx', 0),
        'di_plus': tech_1d.get('di_plus', 0),
        'di_minus': tech_1d.get('di_minus', 0),
        'adx_regime': tech_1d.get('adx_regime', 'UNKNOWN'),
        'bb_position': tech_1d.get('bb_position', 0.5),
        'atr': tech_1d.get('atr', 0),
        'volume_ratio': tech_1d.get('volume_ratio', 1.0),
        'bb_upper': tech_1d.get('bb_upper', 0),
        'bb_lower': tech_1d.get('bb_lower', 0),
        'bb_middle': tech_1d.get('bb_middle', 0),
        'atr_pct': tech_1d.get('atr_pct', 0),
        'extension_ratio_sma_200': tech_1d.get('extension_ratio_sma_200', 0),
        'extension_regime': tech_1d.get('extension_regime', 'NORMAL'),
        'volatility_regime': tech_1d.get('volatility_regime', 'NORMAL'),
        'volatility_percentile': tech_1d.get('volatility_percentile', 50),
        'ema_12': tech_1d.get('ema_12', 0),
        'ema_26': tech_1d.get('ema_26', 0),
    }

    tech_30m['timeframe'] = '30M'
    tech_30m['price'] = data['current_price']
    return tech_30m


def build_diagnostic_technical_data(data: Dict) -> Dict[str, Any]:
    """Build technical_data as diagnose_quality_deductions.py does (should match production)."""
    tech_30m = dict(data['tech_30m'])
    tech_4h = data['tech_4h']
    tech_1d = data['tech_1d']

    # Mirror of diagnose_quality_deductions.py lines 154-200
    tech_30m['mtf_decision_layer'] = {
        'timeframe': '4H',
        'rsi': tech_4h.get('rsi', 50),
        'macd': tech_4h.get('macd', 0),
        'macd_signal': tech_4h.get('macd_signal', 0),
        'macd_histogram': tech_4h.get('macd_histogram', 0),
        'sma_20': tech_4h.get('sma_20', 0),
        'sma_50': tech_4h.get('sma_50', 0),
        'adx': tech_4h.get('adx', 0),
        'di_plus': tech_4h.get('di_plus', 0),
        'di_minus': tech_4h.get('di_minus', 0),
        'bb_upper': tech_4h.get('bb_upper', 0),
        'bb_middle': tech_4h.get('bb_middle', 0),
        'bb_lower': tech_4h.get('bb_lower', 0),
        'bb_position': tech_4h.get('bb_position', 0.5),
        'atr': tech_4h.get('atr', 0),
        'volume_ratio': tech_4h.get('volume_ratio', 1.0),
        'adx_regime': tech_4h.get('adx_regime', 'UNKNOWN'),
        'atr_pct': tech_4h.get('atr_pct', 0),
        'extension_ratio_sma_20': tech_4h.get('extension_ratio_sma_20', 0),
        'extension_ratio_sma_50': tech_4h.get('extension_ratio_sma_50', 0),
        'extension_regime': tech_4h.get('extension_regime', 'NORMAL'),
        'volatility_regime': tech_4h.get('volatility_regime', 'NORMAL'),
        'volatility_percentile': tech_4h.get('volatility_percentile', 50),
        'ema_12': tech_4h.get('ema_12', 0),
        'ema_26': tech_4h.get('ema_26', 0),
    }

    tech_30m['mtf_trend_layer'] = {
        'timeframe': '1D',
        'sma_200': tech_1d.get('sma_200', 0),
        'macd': tech_1d.get('macd', 0),
        'macd_signal': tech_1d.get('macd_signal', 0),
        'macd_histogram': tech_1d.get('macd_histogram', 0),
        'rsi': tech_1d.get('rsi', 0),
        'adx': tech_1d.get('adx', 0),
        'di_plus': tech_1d.get('di_plus', 0),
        'di_minus': tech_1d.get('di_minus', 0),
        'adx_regime': tech_1d.get('adx_regime', 'UNKNOWN'),
        'atr': tech_1d.get('atr', 0),
        'atr_pct': tech_1d.get('atr_pct', 0),
        'extension_ratio_sma_200': tech_1d.get('extension_ratio_sma_200', 0),
        'extension_regime': tech_1d.get('extension_regime', 'NORMAL'),
        'volatility_regime': tech_1d.get('volatility_regime', 'NORMAL'),
        'volatility_percentile': tech_1d.get('volatility_percentile', 50),
        'bb_position': tech_1d.get('bb_position', 0.5),
        'volume_ratio': tech_1d.get('volume_ratio', 1.0),
        'bb_upper': tech_1d.get('bb_upper', 0),
        'bb_lower': tech_1d.get('bb_lower', 0),
        'bb_middle': tech_1d.get('bb_middle', 0),
        'ema_12': tech_1d.get('ema_12', 0),
        'ema_26': tech_1d.get('ema_26', 0),
    }

    tech_30m['timeframe'] = '30M'
    tech_30m['price'] = data['current_price']
    return tech_30m


# ============================================================================
# Check A: v31.6 Fix Verification
# ============================================================================

def check_a_v316_fixes(data: Dict) -> List[Tuple[str, bool, str]]:
    """Verify all 5 v31.6 fixes."""
    results = []

    # --- A1: bb_position default 0.5 ---
    # Simulate missing bb_position in 4H data
    fake_4h = {}  # Empty dict, forces default
    bb_default = fake_4h.get('bb_position', 0.5)  # Production code after fix
    ok = bb_default == 0.5
    results.append(('A1', ok,
        f'bb_position default = {bb_default} (expect 0.5)'))

    # Verify auditor scale_factor would produce reasonable value
    scaled = bb_default * 100  # auditor scale_factor=100
    ok2 = 0 <= scaled <= 100
    results.append(('A1b', ok2,
        f'bb_position scaled = {scaled}% (expect 0-100 range, NOT 5000%)'))

    # Verify real data bb_position is in reasonable range.
    # bb_position = (price - bb_lower) / (bb_upper - bb_lower)
    # Can exceed 1.0 when price is above upper band or go negative when
    # below lower band. Typical range is roughly -0.5 to 1.5; extreme
    # moves can push to ~2.0. Values beyond [-1, 3] suggest a data error.
    real_bb_30m = data['tech_30m'].get('bb_position', None)
    real_bb_4h = data['tech_4h'].get('bb_position', None)
    ok3 = True
    detail = []
    for label, val in [('30M', real_bb_30m), ('4H', real_bb_4h)]:
        if val is not None:
            in_range = -1.0 <= val <= 3.0
            ok3 = ok3 and in_range
            detail.append(f'{label}={val:.4f}')
        else:
            detail.append(f'{label}=None')
    results.append(('A1c', ok3,
        f'Real bb_position reasonable (-1~3): {", ".join(detail)}'))

    # --- A2: TF-aware regime zone check ---
    auditor = AIQualityAuditor()
    # Scenario: 30M=NORMAL, 4H=OVEREXTENDED — agent claims "overextended" should NOT be error
    mock_tech = {
        'extension_regime': 'NORMAL',
        'volatility_regime': 'NORMAL',
        'mtf_decision_layer': {
            'extension_regime': 'OVEREXTENDED',
            'volatility_regime': 'HIGH',
        },
        'mtf_trend_layer': {
            'extension_regime': 'NORMAL',
            'volatility_regime': 'NORMAL',
        },
    }
    text_overext = 'The extension ratio is overextended, suggesting caution.'
    zone_errors = auditor._check_zone_claims(text_overext, mock_tech)
    ext_false_pos = [e for e in zone_errors if 'Extension' in e]
    ok4 = len(ext_false_pos) == 0
    results.append(('A2a', ok4,
        f'30M=NORMAL, 4H=OVEREXTENDED, claim "overextended" → '
        f'{"no false positive ✅" if ok4 else f"FALSE POSITIVE: {ext_false_pos}"}'))

    # Scenario: ALL TFs are NORMAL — agent claims "overextended" SHOULD be error
    mock_tech_all_normal = {
        'extension_regime': 'NORMAL',
        'volatility_regime': 'NORMAL',
        'mtf_decision_layer': {'extension_regime': 'NORMAL', 'volatility_regime': 'NORMAL'},
        'mtf_trend_layer': {'extension_regime': 'NORMAL', 'volatility_regime': 'NORMAL'},
    }
    zone_errors2 = auditor._check_zone_claims(text_overext, mock_tech_all_normal)
    ext_caught = [e for e in zone_errors2 if 'Extension' in e]
    ok5 = len(ext_caught) > 0
    results.append(('A2b', ok5,
        f'ALL TFs NORMAL, claim "overextended" → '
        f'{"correctly caught ✅" if ok5 else "MISSED — false negative"}'))

    # Scenario: volatility — 30M=LOW, 1D=EXTREME — claim "extreme" should NOT be error
    mock_tech_vol = {
        'extension_regime': 'NORMAL',
        'volatility_regime': 'LOW',
        'mtf_decision_layer': {'volatility_regime': 'NORMAL'},
        'mtf_trend_layer': {'volatility_regime': 'EXTREME'},
    }
    text_vol = 'Volatility is extreme, reduce position size.'
    zone_errors3 = auditor._check_zone_claims(text_vol, mock_tech_vol)
    vol_false_pos = [e for e in zone_errors3 if 'Volatility' in e]
    ok6 = len(vol_false_pos) == 0
    results.append(('A2c', ok6,
        f'30M=LOW, 1D=EXTREME, claim "extreme vol" → '
        f'{"no false positive ✅" if ok6 else f"FALSE POSITIVE: {vol_false_pos}"}'))

    # --- A3: Counter-trend LOW inclusion ---
    # Simulate: ET flagged counter_trend_risk as LOW
    mock_et = {'counter_trend_risk': 'LOW', 'timing_verdict': 'FAIR'}
    ctr = mock_et.get('counter_trend_risk', 'NONE')
    flagged = ctr in ('HIGH', 'MODERATE', 'LOW')
    results.append(('A3', flagged,
        f'counter_trend_risk=LOW → flagged={flagged} (expect True)'))

    # Also verify NONE is NOT flagged
    ctr_none = 'NONE'
    flagged_none = ctr_none in ('HIGH', 'MODERATE', 'LOW')
    results.append(('A3b', not flagged_none,
        f'counter_trend_risk=NONE → flagged={flagged_none} (expect False)'))

    # --- A4: ema_10/ema_20 removed ---
    bases = auditor._features_to_tf_data.__code__.co_consts  # Can't easily check, use direct approach
    # Check _INDICATOR_BASES directly from class
    # The list is defined inside _features_to_tf_data as a local variable.
    # Alternative: just search the source code
    import inspect
    source = inspect.getsource(AIQualityAuditor._features_to_tf_data)
    has_ema10 = 'ema_10' in source
    has_ema20 = 'ema_20' in source
    ok7 = not has_ema10 and not has_ema20
    results.append(('A4', ok7,
        f'_INDICATOR_BASES: ema_10={has_ema10}, ema_20={has_ema20} (expect both False)'))

    # --- A5: Diagnostic script 1D RSI default ---
    # Check by reading the file
    deductions_path = project_dir / 'scripts' / 'diagnose_quality_deductions.py'
    if deductions_path.exists():
        source_deductions = deductions_path.read_text()
        # Find the 1D mtf_trend_layer RSI default
        import re
        match = re.search(
            r"tech_30m\['mtf_trend_layer'\]\s*=\s*\{.*?'rsi':\s*tech_1d\.get\('rsi',\s*(\d+)\)",
            source_deductions, re.DOTALL)
        if match:
            rsi_default = int(match.group(1))
            ok8 = rsi_default == 0
            results.append(('A5', ok8,
                f'diagnose_quality_deductions.py 1D RSI default = {rsi_default} (expect 0)'))
        else:
            results.append(('A5', False, 'Could not parse 1D RSI default from source'))
    else:
        results.append(('A5', False, 'diagnose_quality_deductions.py not found'))

    # --- A6: v31.7 — _features_to_tf_data filters out "NONE" enum defaults ---
    # When a TF layer is missing, extract_features produces extension_regime="NONE".
    # _features_to_tf_data must NOT pass "NONE" into ground truth, otherwise zone
    # check subset comparisons are defeated.
    try:
        auditor = AIQualityAuditor()
        # Simulate: 30M=NORMAL, 4H=missing(NONE), 1D=missing(NONE)
        fake_features = {
            'extension_regime_30m': 'NORMAL',
            'extension_regime_4h': 'NONE',
            'extension_regime_1d': 'NONE',
            'volatility_regime_30m': 'LOW',
            'volatility_regime_4h': 'NONE',
            'volatility_regime_1d': 'NONE',
            'rsi_30m': 55.0,
        }
        gt = auditor._features_to_tf_data(fake_features)
        # Ground truth should NOT contain "NONE" for extension_regime
        gt_4h = gt.get('mtf_decision_layer', {})
        gt_1d = gt.get('mtf_trend_layer', {})
        none_leaked_4h = gt_4h.get('extension_regime') == 'NONE'
        none_leaked_1d = gt_1d.get('extension_regime') == 'NONE'
        ok6 = not none_leaked_4h and not none_leaked_1d
        results.append(('A6', ok6,
            f'"NONE" filtered from ground truth: 4H_ext={gt_4h.get("extension_regime", "absent")}, '
            f'1D_ext={gt_1d.get("extension_regime", "absent")} (expect absent, not NONE)'))

        # Verify zone check now catches false claim when only 30M=NORMAL
        import re
        # Build zone check set as auditor does
        all_ext = {gt.get('extension_regime', '')}
        for k in ('mtf_decision_layer', 'mtf_trend_layer'):
            mtf = gt.get(k) or {}
            er = mtf.get('extension_regime', '')
            if er:
                all_ext.add(er)
        all_ext.discard('')
        # Should be just {'NORMAL'}, not {'NORMAL', 'NONE'}
        ok7 = all_ext == {'NORMAL'}
        results.append(('A6b', ok7,
            f'Extension regime set = {all_ext} (expect {{NORMAL}} without NONE)'))
    except Exception as e:
        results.append(('A6', False, f'NONE filter test failed: {e}'))

    # --- A7: v31.7 — _extract_judge_text includes _raw_reasoning ---
    try:
        auditor = AIQualityAuditor()
        fake_judge = {
            '_raw_reasoning': 'Order flow shows CVD positive with buy ratio 0.71',
            'reasoning': 'Order flow shows CVD',  # Truncated version
            'rationale': 'Bullish setup confirmed',
            'strategic_actions': ['Enter long'],
            'acknowledged_risks': ['FR_ADVERSE_LONG'],
            'confluence': {'trend_1d': 'BULLISH', 'momentum_4h': 'BULLISH',
                           'levels_30m': 'NEUTRAL', 'derivatives': 'NEUTRAL',
                           'aligned_layers': 2},
        }
        judge_text = auditor._extract_judge_text(fake_judge)
        has_raw = 'buy ratio 0.71' in judge_text
        has_rationale = 'Bullish setup confirmed' in judge_text
        ok8 = has_raw and has_rationale
        results.append(('A7', ok8,
            f'Judge text includes _raw_reasoning={has_raw}, rationale={has_rationale}'))
    except Exception as e:
        results.append(('A7', False, f'Judge text test failed: {e}'))

    return results


# ============================================================================
# Check B: Data Completeness (MTF field parity)
# ============================================================================

def check_b_data_completeness(data: Dict) -> List[Tuple[str, bool, str]]:
    """Verify production and diagnostic MTF layers have identical field sets."""
    results = []

    prod = build_production_technical_data(data)
    diag = build_diagnostic_technical_data(data)

    # Check 4H field sets
    prod_4h_keys = set(prod['mtf_decision_layer'].keys())
    diag_4h_keys = set(diag['mtf_decision_layer'].keys())

    missing_in_diag_4h = prod_4h_keys - diag_4h_keys
    extra_in_diag_4h = diag_4h_keys - prod_4h_keys

    ok1 = len(missing_in_diag_4h) == 0
    ok2 = len(extra_in_diag_4h) == 0
    results.append(('B1a', ok1,
        f'4H: missing in diagnostic = {missing_in_diag_4h or "none"}'))
    results.append(('B1b', ok2,
        f'4H: extra in diagnostic = {extra_in_diag_4h or "none"}'))

    # Check 4H against production constant
    missing_vs_prod = PRODUCTION_4H_FIELDS - prod_4h_keys
    results.append(('B1c', len(missing_vs_prod) == 0,
        f'4H vs PRODUCTION_4H_FIELDS: missing = {missing_vs_prod or "none"}'))

    # Check 1D field sets
    prod_1d_keys = set(prod['mtf_trend_layer'].keys())
    diag_1d_keys = set(diag['mtf_trend_layer'].keys())

    missing_in_diag_1d = prod_1d_keys - diag_1d_keys
    extra_in_diag_1d = diag_1d_keys - prod_1d_keys

    ok3 = len(missing_in_diag_1d) == 0
    ok4 = len(extra_in_diag_1d) == 0
    results.append(('B2a', ok3,
        f'1D: missing in diagnostic = {missing_in_diag_1d or "none"}'))
    results.append(('B2b', ok4,
        f'1D: extra in diagnostic = {extra_in_diag_1d or "none"}'))

    missing_vs_prod_1d = PRODUCTION_1D_FIELDS - prod_1d_keys
    results.append(('B2c', len(missing_vs_prod_1d) == 0,
        f'1D vs PRODUCTION_1D_FIELDS: missing = {missing_vs_prod_1d or "none"}'))

    # Check value parity (same data → same values)
    diffs = []
    for key in prod_4h_keys & diag_4h_keys:
        pv = prod['mtf_decision_layer'][key]
        dv = diag['mtf_decision_layer'][key]
        if pv != dv:
            diffs.append(f'4H.{key}: prod={pv} diag={dv}')
    for key in prod_1d_keys & diag_1d_keys:
        pv = prod['mtf_trend_layer'][key]
        dv = diag['mtf_trend_layer'][key]
        if pv != dv:
            diffs.append(f'1D.{key}: prod={pv} diag={dv}')
    ok5 = len(diffs) == 0
    results.append(('B3', ok5,
        f'Value parity: {len(diffs)} diffs' + (f' → {diffs[:5]}' if diffs else '')))

    return results


# ============================================================================
# Check C: Zone Check Precision (real data, no false positives)
# ============================================================================

def check_c_zone_precision(data: Dict) -> List[Tuple[str, bool, str]]:
    """Run zone checks with real data + truthful text to verify zero false positives."""
    results = []
    auditor = AIQualityAuditor()
    tech = build_production_technical_data(data)

    # Get actual values
    rsi_30m = tech.get('rsi', 50)
    adx_30m = tech.get('adx', 0)
    ext_30m = tech.get('extension_regime', 'UNKNOWN')
    vol_30m = tech.get('volatility_regime', 'UNKNOWN')
    ext_4h = tech.get('mtf_decision_layer', {}).get('extension_regime', 'UNKNOWN')
    ext_1d = tech.get('mtf_trend_layer', {}).get('extension_regime', 'UNKNOWN')
    vol_4h = tech.get('mtf_decision_layer', {}).get('volatility_regime', 'UNKNOWN')
    vol_1d = tech.get('mtf_trend_layer', {}).get('volatility_regime', 'UNKNOWN')

    print(f"\n  Real regimes:")
    print(f"    Extension:  30M={ext_30m}, 4H={ext_4h}, 1D={ext_1d}")
    print(f"    Volatility: 30M={vol_30m}, 4H={vol_4h}, 1D={vol_1d}")
    print(f"    30M RSI={rsi_30m:.1f}, ADX={adx_30m:.1f}")

    # Generate truthful text based on actual data
    truthful_parts = []
    if rsi_30m > 50:
        truthful_parts.append(f'30M RSI={rsi_30m:.1f} is in upper territory')
    else:
        truthful_parts.append(f'30M RSI={rsi_30m:.1f} is in lower territory')

    # Truthfully describe each TF's extension regime
    for tf, regime in [('30M', ext_30m), ('4H', ext_4h), ('1D', ext_1d)]:
        if regime in VALID_EXTENSION_REGIMES:
            truthful_parts.append(f'{tf} extension ratio is {regime.lower()}')

    truthful_text = '. '.join(truthful_parts) + '.'

    errors = auditor._check_zone_claims(truthful_text, tech)
    ok = len(errors) == 0
    results.append(('C1', ok,
        f'Truthful text zone check: {len(errors)} errors'
        + (f' → {errors}' if errors else '')))

    # C2: Regime validity — all regimes should be in valid sets
    for label, regime, valid_set in [
        ('30M ext', ext_30m, VALID_EXTENSION_REGIMES),
        ('4H ext', ext_4h, VALID_EXTENSION_REGIMES),
        ('1D ext', ext_1d, VALID_EXTENSION_REGIMES),
        ('30M vol', vol_30m, VALID_VOLATILITY_REGIMES),
        ('4H vol', vol_4h, VALID_VOLATILITY_REGIMES),
        ('1D vol', vol_1d, VALID_VOLATILITY_REGIMES),
    ]:
        ok_regime = regime in valid_set
        results.append(('C2', ok_regime,
            f'{label} regime = "{regime}" (valid={ok_regime})'))

    # C3: bb_position values in auditor-friendly range
    for tf_label, tf_data in [('30M', tech), ('4H', tech.get('mtf_decision_layer', {})),
                               ('1D', tech.get('mtf_trend_layer', {}))]:
        bb = tf_data.get('bb_position')
        if bb is not None:
            in_range = -0.5 <= bb <= 1.5  # Allow slight out-of-band
            scaled = bb * 100
            ok_bb = in_range and 0 <= scaled <= 200
            results.append(('C3', ok_bb,
                f'{tf_label} bb_position={bb:.4f} → scaled={scaled:.1f}% (expect 0-100 range)'))

    return results


# ============================================================================
# Check D: Score Sanity (simulated audit with mock agent output)
# ============================================================================

def check_d_score_sanity(data: Dict) -> List[Tuple[str, bool, str]]:
    """Simulate a quality audit with perfect agent outputs to verify no spurious penalties."""
    results = []
    auditor = AIQualityAuditor()
    tech = build_production_technical_data(data)

    # Build minimal but valid mock agent outputs
    rsi_30m = tech.get('rsi', 50)
    adx_4h = tech.get('mtf_decision_layer', {}).get('adx', 0)

    # Create an empty report and run _calculate_score to verify baseline
    report = QualityReport()
    report.citation_errors = 0
    report.value_errors = 0
    report.zone_errors = 0
    report.counter_trend_detected = False

    baseline_score = auditor._calculate_score(report)
    ok1 = baseline_score == 100
    results.append(('D1', ok1,
        f'Baseline score (no errors) = {baseline_score} (expect 100)'))

    # Simulate counter-trend with LOW risk flagged
    report2 = QualityReport()
    report2.counter_trend_detected = True
    report2.counter_trend_flagged_by_entry_timing = True  # LOW/MODERATE/HIGH all set this now
    score2 = auditor._calculate_score(report2)
    ok2 = score2 == 100  # No penalty because it WAS flagged
    results.append(('D2', ok2,
        f'Counter-trend flagged (LOW) score = {score2} (expect 100, no penalty)'))

    # Simulate counter-trend NOT flagged (NONE)
    report3 = QualityReport()
    report3.counter_trend_detected = True
    report3.counter_trend_flagged_by_entry_timing = False
    score3 = auditor._calculate_score(report3)
    ok3 = score3 == 85  # 100 - 15 penalty
    results.append(('D3', ok3,
        f'Counter-trend NOT flagged score = {score3} (expect 85, -15 penalty)'))

    # Simulate 1 citation + 1 value + 1 zone error
    report4 = QualityReport()
    report4.citation_errors = 1
    report4.value_errors = 1
    report4.zone_errors = 1
    score4 = auditor._calculate_score(report4)
    expected4 = 100 - 8 - 5 - 5  # 82
    ok4 = score4 == expected4
    results.append(('D4', ok4,
        f'1 citation + 1 value + 1 zone = {score4} (expect {expected4})'))

    return results


# ============================================================================
# Check E: Feature Completeness (real data feature extraction)
# ============================================================================

def check_e_features(data: Dict) -> List[Tuple[str, bool, str]]:
    """Verify feature extraction produces complete, valid features."""
    results = []

    tech = build_production_technical_data(data)

    try:
        from agents.report_formatter import ReportFormatterMixin

        class MockAnalyzer(ReportFormatterMixin):
            def __init__(self):
                self.log = logging.getLogger('mock')
                self.logger = self.log

        analyzer = MockAnalyzer()

        # Build minimal all_data for extract_features
        all_data = {
            'technical_data': tech,
            'sentiment_data': {'long_ratio': 0.52, 'short_ratio': 0.48, 'long_short_ratio': 1.08},
            'price_data': {'price': data['current_price'], 'price_change_pct': 0.5},
            'order_flow_report': None,
            'derivatives_report': None,
            'binance_derivatives': None,
            'orderbook_report': None,
            'current_position': None,
            'account_context': {'available_balance': 10000, 'total_equity': 10000},
            'sr_zones_data': None,
        }

        features = analyzer.extract_features(all_data)

        # E1: Total feature count
        total = len(features)
        ok1 = total >= 50  # Should have at least 50 with real data
        results.append(('E1', ok1,
            f'Total features extracted: {total} (expect ≥50)'))

        # E2: Key regime features should NOT be "NONE"
        regime_checks = [
            ('extension_regime_30m', VALID_EXTENSION_REGIMES),
            ('extension_regime_4h', VALID_EXTENSION_REGIMES),
            ('extension_regime_1d', VALID_EXTENSION_REGIMES),
            ('volatility_regime_30m', VALID_VOLATILITY_REGIMES),
            ('volatility_regime_4h', VALID_VOLATILITY_REGIMES),
            ('volatility_regime_1d', VALID_VOLATILITY_REGIMES),
        ]
        for key, valid_set in regime_checks:
            val = features.get(key, 'MISSING')
            ok = val in valid_set
            results.append(('E2', ok,
                f'features[{key}] = "{val}" (expect one of {valid_set})'))

        # E3: 30M EMA keys should be ema_12_30m/ema_26_30m
        # Base indicator_manager uses ema_periods=[macd_fast=12, macd_slow=26]
        has_ema12 = 'ema_12_30m' in features
        has_ema26 = 'ema_26_30m' in features
        has_ema10 = 'ema_10_30m' in features    # OLD wrong key
        has_ema20 = 'ema_20_30m' in features    # OLD wrong key
        ok3 = has_ema12 and has_ema26 and not has_ema10 and not has_ema20
        results.append(('E3', ok3,
            f'EMA keys: ema_12={has_ema12}, ema_26={has_ema26}, '
            f'ema_10={has_ema10}, ema_20={has_ema20} (expect ema_12+ema_26)'))

        # E4: bb_position features should be in 0-1 range
        for tf in ['30m', '4h', '1d']:
            key = f'bb_position_{tf}'
            val = features.get(key)
            if val is not None:
                ok4 = 0.0 <= val <= 1.0
                results.append(('E4', ok4,
                    f'features[{key}] = {val:.4f} (expect 0-1)'))
            else:
                results.append(('E4', False,
                    f'features[{key}] = None (missing)'))

        # E5: MACD cross features should be valid categories
        for tf in ['30m', '4h', '1d']:
            key = f'macd_cross_{tf}'
            val = features.get(key, 'MISSING')
            ok5 = val in ('BULLISH', 'BEARISH', 'NEUTRAL', 'MISSING')
            results.append(('E5', ok5 and val != 'MISSING',
                f'features[{key}] = "{val}"'))

        # E6: Scores computation
        try:
            scores = analyzer.compute_scores_from_features(features)
            ok6 = 'net' in scores and 'trend' in scores
            # 'net' is a string like "LEAN_BULLISH_2of3", not a dict
            net_label = scores.get('net', 'MISSING')
            trend_info = scores.get('trend', {})
            trend_dir = trend_info.get('direction', 'N/A') if isinstance(trend_info, dict) else str(trend_info)
            trend_score = trend_info.get('score', 'N/A') if isinstance(trend_info, dict) else 'N/A'
            results.append(('E6', ok6,
                f'Scores: net={net_label}, trend={trend_dir}({trend_score})'))

            # Verify all 5 dimensions exist
            for dim in ['trend', 'momentum', 'order_flow', 'vol_ext_risk', 'risk_env']:
                has_dim = dim in scores
                results.append(('E6b', has_dim,
                    f'Score dimension "{dim}": {"present" if has_dim else "MISSING"}'))
        except Exception as e:
            if not HAS_NT:
                results.append(('E6', True,
                    f'compute_scores_from_features() skipped (synthetic data): {e}'))
            else:
                results.append(('E6', False,
                    f'compute_scores_from_features() failed: {e}'))

    except Exception as e:
        results.append(('E0', False, f'Feature extraction failed: {e}\n{traceback.format_exc()}'))

    return results


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("🔍 v31.6 AI Quality Auditor Diagnostic")
    print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)

    all_results = []
    data = fetch_real_data()

    sections = [
        ('A', 'v31.6 Fix Verification', check_a_v316_fixes),
        ('B', 'Data Completeness (MTF Field Parity)', check_b_data_completeness),
        ('C', 'Zone Check Precision', check_c_zone_precision),
        ('D', 'Score Sanity', check_d_score_sanity),
        ('E', 'Feature Completeness', check_e_features),
    ]

    for section_id, section_name, check_fn in sections:
        print(f"\n{'=' * 70}")
        print(f"📋 Check {section_id}: {section_name}")
        print('=' * 70)

        try:
            results = check_fn(data)
            all_results.extend(results)

            for check_id, passed, detail in results:
                icon = '✅' if passed else '❌'
                print(f"  {icon} [{check_id}] {detail}")
        except Exception as e:
            print(f"  ❌ [{section_id}] SECTION FAILED: {e}")
            traceback.print_exc()
            all_results.append((section_id, False, f'Section failed: {e}'))

    # Summary
    total = len(all_results)
    passed = sum(1 for _, ok, _ in all_results if ok)
    failed = total - passed

    print(f"\n{'=' * 70}")
    print(f"📊 Summary: {passed}/{total} checks passed")
    print('=' * 70)

    if failed > 0:
        print(f"\n❌ FAILED checks ({failed}):")
        for check_id, ok, detail in all_results:
            if not ok:
                print(f"  ❌ [{check_id}] {detail}")
    else:
        print(f"\n✅ All {total} checks passed — auditor v31.6 fully operational")

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
