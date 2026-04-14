#!/usr/bin/env python3
"""
v39.0 Completeness Verification Script
=======================================
Verifies all v39.0 changes are correctly applied, SSoT is in sync,
and no regressions exist.

Checks:
  V1  - SL/TP multiplier SSoT sync (3 files: base.yaml, trading_logic.py, backtest_math.py)
  V2  - SL floor SSoT sync
  V3  - TP R/R target SSoT sync (unchanged from v37.1 but verify parity)
  V4  - calculate_mechanical_sltp() has atr_4h parameter
  V5  - calculate_position_size() has atr_4h parameter
  V6  - order_execution.py passes atr_4h to both functions
  V7  - ai_strategy.py initializes and caches _cached_atr_4h
  V8  - 4H ATR priority: atr_4h > 0 → use 4H, else fallback 30M
  V9  - Early return allows atr_value=0 when atr_4h > 0
  V10 - Method string includes atr_src=4H/30M
  V11 - Trend weight: SMA200 is single-weight (not double)
  V12 - Trend weight: 3 new 4H independent signals exist
  V13 - Reversal detection: 5-condition mechanism exists
  V14 - Reversal detection: trend_reversal in scores return dict
  V15 - market_regime uses max(1D, 4H) ADX
  V16 - market_regime logging includes source
  V17 - Judge few-shot Example 8 exists
  V18 - backtest_math.py mirrors trading_logic.py ATR logic
  V19 - Unit tests exist for atr_4h paths
  V20 - No orphaned old values remain (1.8/2.2 SL multipliers in defaults)
  V21 - CLAUDE.md documents v39.0
  V22 - Atomic rollback warning documented

Usage:
    python3 scripts/verify_v39_completeness.py
"""

import ast
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

results = []


def check(check_id: str, description: str, passed: bool, detail: str = ""):
    """Record a check result."""
    status = PASS if passed else FAIL
    results.append((check_id, description, passed, detail))
    suffix = f" — {detail}" if detail else ""
    print(f"  {status} {check_id}: {description}{suffix}")


def read_file(path: str) -> str:
    """Read file content relative to project root."""
    return (ROOT / path).read_text(encoding="utf-8")


def main():
    print("=" * 70)
    print("v39.0 Completeness Verification")
    print("=" * 70)

    # ================================================================
    # Section 1: SSoT Parameter Sync
    # ================================================================
    print("\n--- Section 1: SSoT Parameter Sync ---")

    tl_src = read_file("strategy/trading_logic.py")
    bm_src = read_file("utils/backtest_math.py")
    yaml_src = read_file("configs/base.yaml")

    # V1: SL multiplier values
    expected_sl = {"HIGH": 0.8, "MEDIUM": 1.0, "LOW": 1.0}

    # Check trading_logic.py defaults (multiple locations)
    tl_has_08 = "'HIGH': 0.8" in tl_src or '"HIGH": 0.8' in tl_src
    tl_has_10 = "'MEDIUM': 1.0" in tl_src or '"MEDIUM": 1.0' in tl_src
    tl_no_old_18 = "'HIGH': 1.8" not in tl_src and '"HIGH": 1.8' not in tl_src
    tl_no_old_22 = "'MEDIUM': 2.2" not in tl_src and '"MEDIUM": 2.2' not in tl_src
    check("V1a", "trading_logic.py SL multipliers = {HIGH:0.8, MED:1.0}",
          tl_has_08 and tl_has_10)
    check("V1b", "trading_logic.py no stale 1.8/2.2 SL defaults",
          tl_no_old_18 and tl_no_old_22,
          f"has_1.8={not tl_no_old_18}, has_2.2={not tl_no_old_22}")

    # Check backtest_math.py
    bm_has_08 = '"HIGH": 0.8' in bm_src
    bm_has_10 = '"MEDIUM": 1.0' in bm_src
    check("V1c", "backtest_math.py SL multipliers = {HIGH:0.8, MED:1.0}",
          bm_has_08 and bm_has_10)

    # Check base.yaml
    yaml_high = re.search(r'HIGH:\s*0\.8', yaml_src) is not None
    yaml_med = re.search(r'MEDIUM:\s*1\.0', yaml_src) is not None
    check("V1d", "base.yaml SL multipliers = {HIGH:0.8, MED:1.0}",
          yaml_high and yaml_med)

    # V2: SL floor
    tl_floor = "0.5" in tl_src and "sl_atr_multiplier_floor" in tl_src
    bm_floor = '"sl_atr_multiplier_floor": 0.5' in bm_src or "'sl_atr_multiplier_floor': 0.5" in bm_src
    yaml_floor = re.search(r'sl_atr_multiplier_floor:\s*0\.5', yaml_src) is not None
    check("V2", "SL floor = 0.5 in all 3 files",
          tl_floor and bm_floor and yaml_floor,
          f"tl={tl_floor}, bm={bm_floor}, yaml={yaml_floor}")

    # V3: TP R/R targets (unchanged from v37.1)
    for src_name, src in [("trading_logic", tl_src), ("backtest_math", bm_src)]:
        has_high_20 = "'HIGH': 2.0" in src or '"HIGH": 2.0' in src
        has_med_18 = "'MEDIUM': 1.8" in src or '"MEDIUM": 1.8' in src
        check(f"V3-{src_name[:2]}", f"{src_name} TP R/R = {{HIGH:2.0, MED:1.8}}",
              has_high_20 and has_med_18)

    # ================================================================
    # Section 2: Function Signatures & Logic
    # ================================================================
    print("\n--- Section 2: Function Signatures & Logic ---")

    # V4: calculate_mechanical_sltp has atr_4h param
    from strategy.trading_logic import calculate_mechanical_sltp
    sig = inspect.signature(calculate_mechanical_sltp)
    has_atr_4h_param = "atr_4h" in sig.parameters
    default_is_zero = sig.parameters.get("atr_4h", None)
    default_ok = default_is_zero is not None and default_is_zero.default == 0.0
    check("V4", "calculate_mechanical_sltp() has atr_4h param (default=0.0)",
          has_atr_4h_param and default_ok)

    # V5: calculate_position_size has atr_4h param
    from strategy.trading_logic import calculate_position_size
    sig_ps = inspect.signature(calculate_position_size)
    has_atr_4h_ps = "atr_4h" in sig_ps.parameters
    default_ps = sig_ps.parameters.get("atr_4h", None)
    default_ps_ok = default_ps is not None and default_ps.default == 0.0
    check("V5", "calculate_position_size() has atr_4h param (default=0.0)",
          has_atr_4h_ps and default_ps_ok)

    # V6: order_execution.py passes atr_4h
    oe_src = read_file("strategy/order_execution.py")
    oe_sltp_pass = "atr_4h=atr_4h_value" in oe_src
    oe_ps_pass = "atr_4h=_atr_4h" in oe_src
    check("V6a", "order_execution passes atr_4h to calculate_mechanical_sltp",
          oe_sltp_pass)
    check("V6b", "order_execution passes atr_4h to calculate_position_size",
          oe_ps_pass)

    # V7: ai_strategy.py initializes and caches _cached_atr_4h
    ai_src = read_file("strategy/ai_strategy.py")
    ai_init = "_cached_atr_4h" in ai_src and "float = 0.0" in ai_src
    ai_cache = "self._cached_atr_4h = _atr_4h" in ai_src
    check("V7a", "ai_strategy.py initializes _cached_atr_4h = 0.0", ai_init)
    check("V7b", "ai_strategy.py caches 4H ATR from decision_layer_data", ai_cache)

    # V8: ATR priority logic (4H > 30M)
    effective_atr_pattern = re.search(
        r'effective_atr\s*=\s*atr_4h\s+if\s+atr_4h\s*>\s*0\s+else\s+atr_value',
        tl_src
    )
    check("V8", "4H ATR priority: effective_atr = atr_4h if atr_4h > 0 else atr_value",
          effective_atr_pattern is not None)

    # V9: Early return allows atr_value=0 when atr_4h > 0
    # Should NOT have: "if entry_price <= 0 or atr_value <= 0:"
    old_guard = re.search(r'if entry_price <= 0 or atr_value <= 0:', tl_src)
    new_guard = re.search(r'if atr_value <= 0 and atr_4h <= 0:', tl_src)
    check("V9", "Early return: atr_value=0 allowed when atr_4h > 0",
          old_guard is None and new_guard is not None,
          f"old_guard_gone={old_guard is None}, new_guard_present={new_guard is not None}")

    # V10: Method string includes atr_src
    atr_src_in_method = "atr_src=" in tl_src
    check("V10", "Method string includes atr_src=4H/30M", atr_src_in_method)

    # ================================================================
    # Section 3: Trend Rebalance & Reversal
    # ================================================================
    print("\n--- Section 3: Trend Rebalance & Reversal ---")

    rf_src = read_file("agents/report_formatter.py")

    # V11: SMA200 single-weight
    # Should use .append() not .extend([...] * 2)
    sma200_double = re.search(r'trend_signals\.extend\(\[.*\]\s*\*\s*2\)', rf_src)
    sma200_single = re.search(r'trend_signals\.append\(1 if above else -1\)', rf_src)
    check("V11", "SMA200 is single-weight (append, not extend×2)",
          sma200_double is None and sma200_single is not None,
          f"double_gone={sma200_double is None}, single_present={sma200_single is not None}")

    # V12: 3 new 4H independent signals
    di_4h_signal = "di_p_4h > di_m_4h + 2" in rf_src or "di_p_4h > di_m_4h +2" in rf_src
    rsi_4h_55 = "rsi_4h > 55" in rf_src
    macd_4h_ind = "macd_4h > macd_sig_4h" in rf_src
    check("V12a", "4H DI directional pressure signal exists", di_4h_signal)
    check("V12b", "4H RSI broad direction signal exists (>55/<45)", rsi_4h_55)
    check("V12c", "4H MACD independent direction signal exists", macd_4h_ind)

    # V13: Reversal detection 5 conditions
    rev_adx = "adx_1d_trend == 'FALLING'" in rf_src
    rev_div = "div_bull >= 2" in rf_src
    rev_di = "di_spread_trend == 'NARROWING'" in rf_src
    rev_sr = "sup_dist < 2" in rf_src
    rev_mom = "mom_dir == 'BULLISH'" in rf_src
    all_5 = rev_adx and rev_div and rev_di and rev_sr and rev_mom
    check("V13", "5-condition reversal detection mechanism",
          all_5,
          f"adx={rev_adx}, div={rev_div}, di={rev_di}, sr={rev_sr}, mom={rev_mom}")

    # V14: trend_reversal in scores dict
    tr_in_scores = '"trend_reversal"' in rf_src
    tr_active = '"active": reversal_active' in rf_src or "'active': reversal_active" in rf_src
    check("V14", "trend_reversal field in scores return dict",
          tr_in_scores and tr_active)

    # V15: market_regime uses max(1D, 4H)
    max_adx = "effective_adx = max(adx_1d, adx_4h)" in rf_src
    check("V15", "market_regime uses max(1D, 4H) ADX", max_adx)

    # V16: market_regime logging
    regime_log = 'Market regime: max(1D=' in rf_src and 'adx_source' in rf_src
    check("V16", "market_regime logging includes ADX source", regime_log)

    # ================================================================
    # Section 4: Judge Few-Shot & Tests
    # ================================================================
    print("\n--- Section 4: Judge Few-Shot & Tests ---")

    ma_src = read_file("agents/multi_agent_analyzer.py")

    # V17: Example 8 exists
    ex8 = "示例 8" in ma_src or "Example 8" in ma_src
    ex8_exhaustion = "趋势衰竭" in ma_src or "trend exhaustion" in ma_src.lower()
    check("V17", "Judge few-shot Example 8 (trend exhaustion) exists",
          ex8 and ex8_exhaustion)

    # V18: backtest_math.py mirrors ATR logic
    bm_effective = re.search(
        r'effective_atr\s*=\s*atr_4h\s+if\s+atr_4h\s*>\s*0\s+else\s+atr_value',
        bm_src
    )
    bm_atr_4h_param = "atr_4h" in bm_src and "def calculate_mechanical_sltp" in bm_src
    check("V18a", "backtest_math mirrors 4H ATR priority logic", bm_effective is not None)
    check("V18b", "backtest_math has atr_4h parameter", bm_atr_4h_param)

    # V19: Unit tests exist
    test_src = read_file("tests/test_trading_logic.py")
    has_atr4h_tests = "TestMechanicalSltpAtr4h" in test_src
    has_ps_test = "TestPositionSizeAtr4h" in test_src
    test_count = len(re.findall(r'def test_.*atr', test_src, re.IGNORECASE))
    check("V19a", "TestMechanicalSltpAtr4h class exists", has_atr4h_tests)
    check("V19b", "TestPositionSizeAtr4h class exists", has_ps_test)
    check("V19c", f"ATR-related test methods count >= 6", test_count >= 6,
          f"found {test_count}")

    # ================================================================
    # Section 5: Cleanup & Documentation
    # ================================================================
    print("\n--- Section 5: Cleanup & Documentation ---")

    # V20: No orphaned old values in code defaults
    # Check that no function-level defaults still have 1.8/2.2 for SL
    # (yaml may have them in comments, that's ok)
    # Look for dict literals with old values in .py files
    old_sl_defaults_tl = re.findall(
        r"'sl_atr_multiplier'.*?'HIGH':\s*1\.8", tl_src, re.DOTALL
    )
    old_sl_defaults_bm = re.findall(
        r'"sl_atr_multiplier".*?"HIGH":\s*1\.8', bm_src, re.DOTALL
    )
    check("V20a", "No stale HIGH:1.8 SL defaults in trading_logic.py",
          len(old_sl_defaults_tl) == 0,
          f"found {len(old_sl_defaults_tl)} occurrences")
    check("V20b", "No stale HIGH:1.8 SL defaults in backtest_math.py",
          len(old_sl_defaults_bm) == 0,
          f"found {len(old_sl_defaults_bm)} occurrences")

    # V20c: Default SL fallback values (the .get() calls for SL multiplier)
    # Note: 1.8 for TP R/R is correct (unchanged from v37.1), only check SL-specific patterns
    old_fallback_22 = re.findall(r"\.get\(conf_for_sl,\s*2\.2\)", tl_src)
    # Check SL-specific context: sl_multipliers.get('MEDIUM', X)
    old_sl_medium_fallback = re.findall(r"sl_multipliers\.get\('MEDIUM',\s*1\.8\)", tl_src)
    check("V20c", "No stale SL .get() fallback values (2.2 for conf, 1.8 for SL MEDIUM)",
          len(old_fallback_22) == 0 and len(old_sl_medium_fallback) == 0,
          f"found get(conf,2.2)={len(old_fallback_22)}, sl_get(MEDIUM,1.8)={len(old_sl_medium_fallback)}")

    # V21: CLAUDE.md documents v39.0
    claude_md = read_file("CLAUDE.md")
    v39_doc = "v39.0" in claude_md
    v39_atr = "4H ATR" in claude_md and "SL/TP" in claude_md
    check("V21", "CLAUDE.md documents v39.0 changes", v39_doc and v39_atr)

    # V22: Atomic rollback warning
    atomic = "原子回滚" in claude_md or "atomic rollback" in claude_md.lower()
    coupled = "耦合设计" in claude_md or "coupled design" in claude_md.lower()
    check("V22", "Atomic rollback warning documented in CLAUDE.md",
          atomic and coupled)

    # ================================================================
    # Section 6: Functional Verification (Run actual functions)
    # ================================================================
    print("\n--- Section 6: Functional Verification ---")

    # Mock config to avoid dotenv dependency
    import strategy.trading_logic as tl_mod
    tl_mod._TRADING_LOGIC_CONFIG = {
        'mechanical_sltp': {
            'enabled': True,
            'sl_atr_multiplier': {'HIGH': 0.8, 'MEDIUM': 1.0, 'LOW': 1.0},
            'tp_rr_target': {'HIGH': 2.0, 'MEDIUM': 1.8, 'LOW': 1.8},
            'sl_atr_multiplier_floor': 0.5,
            'counter_trend_sl_tighten': 1.0,
        },
        'min_rr_ratio': 1.5,
        'counter_trend_rr_multiplier': 1.3,
    }
    from strategy.trading_logic import calculate_mechanical_sltp as calc_sltp

    # F1: 4H ATR is used when provided
    _, sl_30m, _, desc_30m = calc_sltp(
        entry_price=95000.0, atr_value=500.0, side="LONG",
        confidence="MEDIUM", atr_4h=0.0,
    )
    _, sl_4h, _, desc_4h = calc_sltp(
        entry_price=95000.0, atr_value=500.0, side="LONG",
        confidence="MEDIUM", atr_4h=1500.0,
    )
    sl_dist_30m = 95000.0 - sl_30m
    sl_dist_4h = 95000.0 - sl_4h
    check("F1", "4H ATR produces wider SL than 30M ATR",
          sl_dist_4h > sl_dist_30m * 2.5,
          f"30M_SL_dist=${sl_dist_30m:.0f}, 4H_SL_dist=${sl_dist_4h:.0f}, ratio={sl_dist_4h/sl_dist_30m:.1f}×")

    # F2: ATR source labels correct
    check("F2a", "atr_src=4H in method when 4H used", "atr_src=4H" in desc_4h,
          desc_4h.split("|")[1] if "|" in desc_4h else "")
    check("F2b", "atr_src=30M in method when 30M fallback", "atr_src=30M" in desc_30m,
          desc_30m.split("|")[1] if "|" in desc_30m else "")

    # F3: atr_value=0 + atr_4h > 0 → success
    ok, sl, tp, desc = calc_sltp(
        entry_price=95000.0, atr_value=0.0, side="LONG",
        confidence="MEDIUM", atr_4h=1500.0,
    )
    check("F3", "atr_value=0 + atr_4h=1500 → success (not rejected)",
          ok is True and sl > 0 and tp > 0,
          f"success={ok}, SL={sl:.0f}, TP={tp:.0f}")

    # F4: Both ATR = 0 → failure
    ok, _, _, desc = calc_sltp(
        entry_price=95000.0, atr_value=0.0, side="LONG",
        confidence="HIGH", atr_4h=0.0,
    )
    check("F4", "Both ATR=0 → failure with clear message",
          ok is False and "No valid ATR" in desc, desc)

    # F5: SL floor applied (0.5× 4H ATR)
    _, sl_floor, _, _ = calc_sltp(
        entry_price=95000.0, atr_value=100.0, side="LONG",
        confidence="HIGH", atr_4h=1500.0,
    )
    sl_floor_dist = 95000.0 - sl_floor
    min_expected = 1500.0 * 0.5 * 0.99  # floor × ATR, with tolerance
    check("F5", f"SL floor 0.5×4H applied (min ${min_expected:.0f})",
          sl_floor_dist >= min_expected,
          f"SL_dist=${sl_floor_dist:.0f}, floor_min=${min_expected:.0f}")

    # F6: R/R targets maintained
    for conf, expected_rr in [("HIGH", 2.0), ("MEDIUM", 1.8), ("LOW", 1.8)]:
        _, sl, tp, _ = calc_sltp(
            entry_price=95000.0, atr_value=500.0, side="LONG",
            confidence=conf, atr_4h=1500.0,
        )
        actual_rr = (tp - 95000.0) / (95000.0 - sl)
        check(f"F6-{conf}", f"R/R target {conf}={expected_rr}:1",
              abs(actual_rr - expected_rr) < 0.05,
              f"actual={actual_rr:.2f}")

    # F7: Counter-trend R/R escalation still works with 4H ATR
    _, sl_ct, tp_ct, _ = calc_sltp(
        entry_price=95000.0, atr_value=500.0, side="LONG",
        confidence="MEDIUM", atr_4h=1500.0, is_counter_trend=True,
    )
    ct_rr = (tp_ct - 95000.0) / (95000.0 - sl_ct)
    check("F7", "Counter-trend R/R >= 1.95 (1.5×1.3) with 4H ATR",
          ct_rr >= 1.94,
          f"actual={ct_rr:.2f}")

    # ================================================================
    # Section 7: Cross-File Consistency Deep Checks
    # ================================================================
    print("\n--- Section 7: Cross-File Consistency ---")

    # C1: order_execution uses getattr for _cached_atr_4h (safe for mixin)
    oe_getattr = "getattr(self, '_cached_atr_4h'" in oe_src
    check("C1", "order_execution uses getattr() for _cached_atr_4h (safe)",
          oe_getattr)

    # C2: Cache guard: only update when > 0
    cache_guard = re.search(r'if _atr_4h and _atr_4h > 0:', ai_src)
    check("C2", "ai_strategy only caches 4H ATR when > 0", cache_guard is not None)

    # C3: Emergency SL still uses 30M ATR (not affected by v39.0)
    safety_src = read_file("strategy/safety_manager.py")
    emergency_uses_cached_atr = "_cached_atr_value" in safety_src
    emergency_no_4h = "_cached_atr_4h" not in safety_src
    check("C3", "Emergency SL still uses _cached_atr_value (30M), not 4H",
          emergency_uses_cached_atr and emergency_no_4h,
          f"uses_30m={emergency_uses_cached_atr}, no_4h={emergency_no_4h}")

    # C4: Reversal detection threshold >= 3
    rev_threshold = re.search(r'max\(reversal_bull_count,\s*reversal_bear_count\)\s*>=\s*3', rf_src)
    check("C4", "Reversal activation threshold = 3 of 5 signals",
          rev_threshold is not None)

    # C5: trend_score penalty max(1, ...)
    penalty = re.search(r'trend_score\s*=\s*max\(1,\s*trend_score\s*-\s*3\)', rf_src)
    check("C5", "Reversal penalty: max(1, trend_score - 3) (never zero)",
          penalty is not None)

    # C6: market_regime adx_4h default prevents crash when feature missing
    adx_4h_default = re.search(r'features\.get\(["\']adx_4h["\'],\s*0\.0\)', rf_src)
    check("C6", "market_regime: adx_4h defaults to 0.0 if feature missing",
          adx_4h_default is not None)

    # C7: position_size risk clamp log shows ATR source
    ps_log_source = re.search(r'ATR\({atr_source}\)', tl_src) or \
                    re.search(r'ATR\(\{atr_source\}\)', tl_src)
    check("C7", "Position size risk clamp log includes ATR source label",
          ps_log_source is not None)

    # ================================================================
    # Summary
    # ================================================================
    print("\n" + "=" * 70)
    total = len(results)
    passed = sum(1 for _, _, p, _ in results if p)
    failed = total - passed

    if failed == 0:
        print(f"{PASS} ALL {total} CHECKS PASSED — v39.0 is complete")
    else:
        print(f"{FAIL} {failed}/{total} CHECKS FAILED — issues remain:")
        for cid, desc, ok, detail in results:
            if not ok:
                print(f"    {FAIL} {cid}: {desc}")
                if detail:
                    print(f"       → {detail}")

    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
