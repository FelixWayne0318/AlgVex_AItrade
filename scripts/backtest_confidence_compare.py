#!/usr/bin/env python3
"""
Confidence-level parameter comparison backtest.

Tests 6 parameter sets across HIGH/MEDIUM/LOW confidence tiers to determine
optimal SL/TP parameters for each tier. Uses the same ProductionSimulator
(v3.0) as backtest_from_logs.py for full production parity.

Each plan is tested with and without production gates for comparison.

Usage (on server):
  cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/backtest_confidence_compare.py

  # Specify days of logs to scan:
  python3 scripts/backtest_confidence_compare.py --days 30

  # Use previously exported signals:
  python3 scripts/backtest_confidence_compare.py --signals data/extracted_signals.json

  # Export signals only:
  python3 scripts/backtest_confidence_compare.py --export-only
"""

import argparse
import json
import os
import sys
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

# Reuse signal extraction, kline fetching, and ProductionSimulator from backtest_from_logs
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from backtest_from_logs import (
    ProductionSimulator,
    PRODUCTION_GATES,
    CONFIDENCE_RANK,
    fetch_klines,
    extract_signals_from_journalctl,
    load_hold_counterfactuals,
)
from utils.backtest_math import calculate_atr_wilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SYMBOL = "BTCUSDT"

# ============================================================================
# 6 Parameter Sets: 3 confidence tiers × 2 SL/TP variants
# ============================================================================

# Plan A: Current production (v37.1) — MEDIUM+ only, no LOW
PLAN_A_PRODUCTION = {
    "label": "A: v37.1 Production (MEDIUM+)",
    "sl_atr_multiplier": {"HIGH": 1.8, "MEDIUM": 2.2},
    "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.8},
    "sl_atr_multiplier_floor": 1.2,
    "min_confidence": "MEDIUM",
    "counter_trend_rr_multiplier": 1.3,
    "min_rr_ratio": 1.5,
}

# Plan B: Enable LOW with same SL/TP as MEDIUM (conservative LOW entry)
PLAN_B_LOW_AS_MEDIUM = {
    "label": "B: LOW=MEDIUM params (SL=2.2, R/R=1.8)",
    "sl_atr_multiplier": {"HIGH": 1.8, "MEDIUM": 2.2, "LOW": 2.2},
    "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.8, "LOW": 1.8},
    "sl_atr_multiplier_floor": 1.2,
    "min_confidence": "LOW",
    "counter_trend_rr_multiplier": 1.3,
    "min_rr_ratio": 1.5,
}

# Plan C: LOW with wider SL + lower R/R (more room to breathe)
PLAN_C_LOW_WIDE_SL = {
    "label": "C: LOW wider SL (SL=2.5, R/R=1.5)",
    "sl_atr_multiplier": {"HIGH": 1.8, "MEDIUM": 2.2, "LOW": 2.5},
    "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.8, "LOW": 1.5},
    "sl_atr_multiplier_floor": 1.2,
    "min_confidence": "LOW",
    "counter_trend_rr_multiplier": 1.3,
    "min_rr_ratio": 1.5,
}

# Plan D: LOW with tighter SL + same R/R as MEDIUM (aggressive LOW)
PLAN_D_LOW_TIGHT_SL = {
    "label": "D: LOW tight SL (SL=1.8, R/R=1.8)",
    "sl_atr_multiplier": {"HIGH": 1.8, "MEDIUM": 2.2, "LOW": 1.8},
    "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.8, "LOW": 1.8},
    "sl_atr_multiplier_floor": 1.2,
    "min_confidence": "LOW",
    "counter_trend_rr_multiplier": 1.3,
    "min_rr_ratio": 1.5,
}

# Plan E: All 3 tiers differentiated (graduated parameters)
PLAN_E_GRADUATED = {
    "label": "E: Graduated (H=1.8/2.0, M=2.2/1.8, L=2.5/1.5)",
    "sl_atr_multiplier": {"HIGH": 1.8, "MEDIUM": 2.2, "LOW": 2.5},
    "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.8, "LOW": 1.5},
    "sl_atr_multiplier_floor": 1.2,
    "min_confidence": "LOW",
    "counter_trend_rr_multiplier": 1.3,
    "min_rr_ratio": 1.5,
}

# Plan F: LOW with small position + wide SL (max survival)
PLAN_F_LOW_CONSERVATIVE = {
    "label": "F: LOW conservative (SL=2.8, R/R=1.5)",
    "sl_atr_multiplier": {"HIGH": 1.8, "MEDIUM": 2.2, "LOW": 2.8},
    "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.8, "LOW": 1.5},
    "sl_atr_multiplier_floor": 1.2,
    "min_confidence": "LOW",
    "counter_trend_rr_multiplier": 1.3,
    "min_rr_ratio": 1.5,
}

# Plan G: v39.0 Production (4H ATR basis — multipliers are 4H-scale)
# NOTE: These multipliers are designed for 4H ATR input. When this backtest
# uses 30M ATR (no 4H data available), SL distances will be ~2.8x tighter
# than production. This plan exists for parameter comparison, not absolute PnL.
PLAN_G_V39_PRODUCTION = {
    "label": "G: v39.0 Production (4H ATR scale, H=0.8/2.0, M=1.0/1.8, L=1.0/1.8)",
    "sl_atr_multiplier": {"HIGH": 0.8, "MEDIUM": 1.0, "LOW": 1.0},
    "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.8, "LOW": 1.8},
    "sl_atr_multiplier_floor": 0.5,
    "min_confidence": "LOW",
    "counter_trend_rr_multiplier": 1.3,
    "min_rr_ratio": 1.5,
}

ALL_PLANS = {
    "A_production": PLAN_A_PRODUCTION,
    "B_low_as_medium": PLAN_B_LOW_AS_MEDIUM,
    "C_low_wide_sl": PLAN_C_LOW_WIDE_SL,
    "D_low_tight_sl": PLAN_D_LOW_TIGHT_SL,
    "E_graduated": PLAN_E_GRADUATED,
    "F_low_conservative": PLAN_F_LOW_CONSERVATIVE,
    "G_v39_production": PLAN_G_V39_PRODUCTION,
}


def analyze_by_confidence(trades: List[Dict]) -> Dict:
    """Analyze trades broken down by confidence level."""
    result = {}
    closed = [t for t in trades if t["outcome"] not in ("FILTERED", "OPEN", "PYRAMID", "NO_DATA")]

    for conf in ["HIGH", "MEDIUM", "LOW"]:
        subset = [t for t in closed if t.get("confidence") == conf]
        if not subset:
            result[conf] = {
                "count": 0, "wins": 0, "win_rate": 0, "total_pnl": 0,
                "avg_pnl": 0, "tp": 0, "sl": 0, "tb": 0, "trailing": 0,
            }
            continue

        wins = sum(1 for t in subset if t.get("dollar_pnl", 0) > 0)
        total_pnl = sum(t.get("dollar_pnl", 0) for t in subset)
        tps = sum(1 for t in subset if t["outcome"] == "TP")
        sls = sum(1 for t in subset if t["outcome"] == "SL")
        tbs = sum(1 for t in subset if t["outcome"] == "TIME_BARRIER")
        trails = sum(1 for t in subset if t["outcome"] == "TRAILING")

        result[conf] = {
            "count": len(subset),
            "wins": wins,
            "win_rate": round(wins / len(subset) * 100, 1) if subset else 0,
            "total_pnl": round(total_pnl, 4),
            "avg_pnl": round(total_pnl / len(subset), 4) if subset else 0,
            "tp": tps,
            "sl": sls,
            "tb": tbs,
            "trailing": trails,
        }

    return result


def print_comparison_table(results: Dict, plan_keys: List[str]):
    """Print the main comparison table."""
    print(f"\n{'=' * 160}")
    print(f"  信心等级参数对比 — 总览 (v3.0 仿真器: 多层加仓+Trailing | 手续费 0.15%/RT | SL 滑点 0.03% | 10x 杠杆)")
    print(f"{'=' * 160}")
    print(f"  {'方案':<55} {'信号':>4} {'跳过':>5} {'仓位':>4} {'TP':>3} {'SL':>3} {'TB':>3} {'Trail':>5} "
          f"{'胜率':>6} {'PnL':>8} {'回撤':>7} {'Calmar':>7}")
    print(f"  {'-' * 150}")

    for key in plan_keys:
        r = results[key]
        s = r["summary"]
        pnl = r.get("pnl", 0)
        max_dd = r.get("max_dd", 0)
        calmar = round(pnl / max_dd, 1) if max_dd > 0.5 else 999.9
        closed = s.get("trades_closed", 0)
        wr = s.get("win_rate", 0)
        label = r.get("label", key)
        star = "★" if "production" in key.lower() or key.startswith("A_") else " "
        print(
            f"  {star}{label:<54} {s['total_signals_processed']:>4} "
            f"{s['signals_skipped_by_gates']:>5} "
            f"{closed:>4} "
            f"{s.get('tp', 0):>3} {s.get('sl', 0):>3} {s.get('tb', 0):>3} "
            f"{s.get('trailing_exits', 0):>5} "
            f"{wr:>5.1f}% "
            f"{pnl:>+7.2f}% "
            f"{max_dd:>6.2f}% "
            f"{calmar:>6.1f}"
        )


def print_confidence_breakdown(results: Dict, plan_keys: List[str]):
    """Print per-confidence-level breakdown for each plan."""
    print(f"\n{'=' * 160}")
    print(f"  按信心等级分组详情 — 每个方案的 HIGH / MEDIUM / LOW 独立表现")
    print(f"{'=' * 160}")

    for key in plan_keys:
        r = results[key]
        label = r.get("label", key)
        conf_data = r.get("by_confidence", {})

        print(f"\n  ── {label} ──")
        print(f"  {'等级':<8} {'笔数':>4} {'胜':>3} {'胜率':>6} {'TP':>3} {'SL':>3} {'TB':>3} {'Trail':>5} "
              f"{'总PnL':>9} {'均PnL':>9}")
        print(f"  {'-' * 75}")

        total_pnl = 0
        total_count = 0
        for conf in ["HIGH", "MEDIUM", "LOW"]:
            cd = conf_data.get(conf, {})
            count = cd.get("count", 0)
            if count == 0:
                print(f"  {conf:<8} {'—':>4} {'—':>3} {'—':>6} {'—':>3} {'—':>3} {'—':>3} {'—':>5} {'—':>9} {'—':>9}")
                continue
            total_pnl += cd.get("total_pnl", 0)
            total_count += count
            print(
                f"  {conf:<8} {count:>4} {cd['wins']:>3} {cd['win_rate']:>5.1f}% "
                f"{cd['tp']:>3} {cd['sl']:>3} {cd['tb']:>3} {cd['trailing']:>5} "
                f"{cd['total_pnl']:>+8.4f} {cd['avg_pnl']:>+8.4f}"
            )

        if total_count > 0:
            print(f"  {'合计':<8} {total_count:>4} {'':>3} {'':>6} {'':>3} {'':>3} {'':>3} {'':>5} {total_pnl:>+8.4f}")


def print_low_signal_analysis(results: Dict, plan_keys: List[str]):
    """Focused analysis on LOW confidence signals across plans."""
    print(f"\n{'=' * 160}")
    print(f"  LOW 信心信号专项分析 — 决定是否值得放行 LOW 信号")
    print(f"{'=' * 160}")

    # Find plans that include LOW
    low_plans = []
    for key in plan_keys:
        r = results[key]
        cd = r.get("by_confidence", {}).get("LOW", {})
        if cd.get("count", 0) > 0:
            low_plans.append(key)

    if not low_plans:
        print("  没有任何方案包含 LOW 信号交易。")
        print("  所有 LOW 信号都被 min_confidence=MEDIUM 门槛拦截。")

        # Count how many LOW signals exist in the input
        # (from Plan A which filters them as "min_confidence")
        r_a = results.get("A_production_gates", {})
        skip_log = r_a.get("raw_skip_log", [])
        low_skips = sum(1 for s in skip_log if "min_confidence" in s.get("reason", ""))
        trades = r_a.get("raw_trades", [])
        low_filtered = sum(1 for t in trades if t.get("outcome") == "FILTERED" and "LOW" in t.get("skip_reason", ""))
        print(f"  被 min_confidence 拦截的 LOW 信号: {low_skips + low_filtered}")
        return

    print(f"\n  {'方案':<55} {'LOW笔':>5} {'LOW胜率':>7} {'LOW PnL':>9} {'LOW均PnL':>9} "
          f"{'全局PnL':>9} {'PnL差':>8}")
    print(f"  {'-' * 110}")

    baseline_pnl = results.get("A_production_gates", {}).get("pnl", 0)

    for key in plan_keys:
        r = results[key]
        label = r.get("label", key)
        cd = r.get("by_confidence", {}).get("LOW", {})
        low_count = cd.get("count", 0)
        low_wr = cd.get("win_rate", 0)
        low_pnl = cd.get("total_pnl", 0)
        low_avg = cd.get("avg_pnl", 0)
        total_pnl = r.get("pnl", 0)
        pnl_diff = total_pnl - baseline_pnl

        if low_count > 0:
            print(
                f"  {label:<55} {low_count:>5} {low_wr:>6.1f}% {low_pnl:>+8.4f} {low_avg:>+8.4f} "
                f"{total_pnl:>+8.2f}% {pnl_diff:>+7.2f}%"
            )
        else:
            print(f"  {label:<55} {'—':>5} {'—':>7} {'—':>9} {'—':>9} {total_pnl:>+8.2f}% {pnl_diff:>+7.2f}%")

    # Summary verdict
    print(f"\n  ── 决策建议 ──")
    best_key = None
    best_pnl = -999
    for key in plan_keys:
        r = results[key]
        pnl = r.get("pnl", 0)
        if pnl > best_pnl:
            best_pnl = pnl
            best_key = key

    best_r = results[best_key]
    best_dd = best_r.get("max_dd", 0)
    best_calmar = round(best_pnl / best_dd, 1) if best_dd > 0.5 else 999.9

    print(f"  最优方案: {best_r.get('label', best_key)}")
    print(f"  PnL: {best_pnl:+.2f}% | Max DD: {best_dd:.2f}% | Calmar: {best_calmar}")

    # Compare LOW contribution
    best_low = best_r.get("by_confidence", {}).get("LOW", {})
    if best_low.get("count", 0) > 0:
        low_ev = best_low["avg_pnl"]
        if low_ev > 0:
            print(f"  LOW 信号期望值: {low_ev:+.4f}%/笔 → ✅ 正期望，建议放行")
        else:
            print(f"  LOW 信号期望值: {low_ev:+.4f}%/笔 → ❌ 负期望，不建议放行")
    else:
        if best_key.startswith("A_"):
            print(f"  最优方案不含 LOW → 当前 MEDIUM 门槛可能已是最优")
        else:
            print(f"  最优方案中 LOW 无交易数据")


def print_trade_details(results: Dict, plan_key: str, max_trades: int = 50):
    """Print per-trade details for a specific plan."""
    r = results.get(plan_key, {})
    if not r:
        return

    trades = r.get("raw_trades", [])
    active_trades = [t for t in trades if t["outcome"] not in ("FILTERED",)]

    if not active_trades:
        return

    label = r.get("label", plan_key)
    print(f"\n{'=' * 160}")
    print(f"  {label} — 每笔详情 (前 {max_trades} 笔)")
    print(f"{'=' * 160}")
    print(f"  {'#':>3} {'时间':>14} {'方向':>6} {'信心':>6} {'Size':>5} {'入场':>12} "
          f"{'SL':>12} {'TP':>12} {'结果':>8} {'$PnL':>10} {'净值':>8}")
    print(f"  {'-' * 130}")

    for i, t in enumerate(active_trades[:max_trades], 1):
        outcome_str = t["outcome"]
        emoji = {"TP": "✅TP", "SL": "❌SL", "TIME_BARRIER": "⏰TB",
                 "TRAILING": "🔄Trail", "PYRAMID": "📈加仓", "CLOSE": "🔒平仓",
                 "REDUCE": "📉减仓", "OPEN": "🟢开仓"}.get(outcome_str, outcome_str)

        print(
            f"  {i:>3} {t['timestamp'][5:19]:>14} {t.get('signal', ''):>6} {t.get('confidence', ''):>6} "
            f"{t.get('size_multiplier', 0):>5.2f} "
            f"${t.get('entry_price', 0):>11,.2f} "
            f"${t.get('sl_price', 0):>11,.2f} ${t.get('tp_price', 0):>11,.2f} "
            f"{emoji:>8} {t.get('dollar_pnl', 0):>+9.4f} "
            f"{t.get('equity_after', 100):>7.2f}"
        )


def run_comparison(signals: List[Dict], use_gates: bool = True):
    """Run all 6 plans and compare."""
    if not signals:
        logger.error("No signals to backtest!")
        return

    signals.sort(key=lambda s: s["timestamp"])

    total = len(signals)
    dir_dist = Counter(s["signal"] for s in signals)
    conf_dist = Counter(s["confidence"] for s in signals)
    blocked_count = sum(1 for s in signals if s.get("blocked"))
    source_dist = Counter(s.get("source", "unknown") for s in signals)
    conf_source_dist = Counter(s.get("confidence_source", "unknown") for s in signals)

    print("\n" + "=" * 160)
    print(f"  AlgVex 信心等级参数对比回测 — v3.0 仿真器 (多层加仓 + Trailing Stop)")
    print("=" * 160)
    print(f"  交易对: {SYMBOL}")
    print(f"  信号数量: {total}")
    print(f"  时间范围: {signals[0]['timestamp']} → {signals[-1]['timestamp']}")
    print(f"  方向分布: {dict(dir_dist)}")
    print(f"  信心分布: {dict(conf_dist)}")
    print(f"  被拦截 (ET/conf): {blocked_count}/{total}")
    print(f"  数据来源: {dict(source_dist)}")
    print(f"  信心来源: {dict(conf_source_dist)}")

    # Calculate time span
    first_dt = datetime.fromisoformat(signals[0]["timestamp"]).replace(tzinfo=timezone.utc)
    last_dt = datetime.fromisoformat(signals[-1]["timestamp"]).replace(tzinfo=timezone.utc)
    data_start = first_dt - timedelta(days=1)
    data_end = last_dt + timedelta(hours=14)
    start_ms = int(data_start.timestamp() * 1000)
    end_ms = int(data_end.timestamp() * 1000)
    days_span = (last_dt - first_dt).total_seconds() / 86400
    print(f"  跨度: {days_span:.1f} 天")

    # Fetch klines (shared across all plans)
    logger.info("Fetching 30M klines for ATR calculation...")
    bars_30m = fetch_klines(SYMBOL, "30m", start_ms, end_ms)
    logger.info(f"Got {len(bars_30m)} 30M bars")

    logger.info(f"Fetching 1M klines ({days_span:.0f} days, may take a few minutes)...")
    bars_1m = fetch_klines(SYMBOL, "1m", start_ms, end_ms)
    logger.info(f"Got {len(bars_1m)} 1M bars")

    # Fill missing entry prices and ATR
    filled_price = 0
    filled_atr = 0
    for sig in signals:
        sig_dt = datetime.fromisoformat(sig["timestamp"]).replace(tzinfo=timezone.utc)
        sig_ms = int(sig_dt.timestamp() * 1000)

        if sig["entry_price"] is None:
            for b in bars_30m:
                if b["open_time"] <= sig_ms <= b["close_time"]:
                    sig["entry_price"] = b["close"]
                    filled_price += 1
                    break
            if sig["entry_price"] is None:
                for i, b in enumerate(bars_30m):
                    if b["open_time"] > sig_ms and i > 0:
                        sig["entry_price"] = bars_30m[i - 1]["close"]
                        filled_price += 1
                        break

        if sig["atr"] is None or sig["atr"] <= 0:
            bar_idx = None
            for i, b in enumerate(bars_30m):
                if b["open_time"] <= sig_ms <= b["close_time"]:
                    bar_idx = i
                    break
                elif b["open_time"] > sig_ms:
                    bar_idx = i - 1 if i > 0 else 0
                    break
            if bar_idx is not None:
                atr_bars = bars_30m[max(0, bar_idx - 15): bar_idx + 1]
                atr_val = calculate_atr_wilder(atr_bars, period=14)
                if atr_val > 0:
                    sig["atr"] = atr_val
                    filled_atr += 1

    logger.info(f"Filled {filled_price} entry prices, {filled_atr} ATR values from klines")

    valid_signals = [s for s in signals if s["entry_price"] and s.get("atr") and s["atr"] > 0]
    skipped = total - len(valid_signals)
    if skipped:
        logger.warning(f"Skipped {skipped} signals due to missing price/ATR data")
    print(f"  有效信号: {len(valid_signals)}/{total}")

    if not valid_signals:
        logger.error("No valid signals after data filling!")
        return

    # ========================================================================
    # Run all 6 plans × 2 modes (gates/no-gates) = 12 simulations
    # ========================================================================
    results = {}
    plan_keys_gates = []
    plan_keys_nogates = []

    for plan_id, plan_params in ALL_PLANS.items():
        # With gates
        key_gates = f"{plan_id}_gates"
        logger.info(f"Backtesting: {plan_params['label']} (with gates)...")
        sim = ProductionSimulator(plan_params, PRODUCTION_GATES, bars_1m, bars_30m, use_gates=True)
        res = sim.run(valid_signals)
        conf_breakdown = analyze_by_confidence(res["trades"])
        results[key_gates] = {
            **res,
            "label": plan_params["label"],
            "by_confidence": conf_breakdown,
            "raw_trades": res["trades"],
            "raw_skip_log": res["skip_log"],
        }
        plan_keys_gates.append(key_gates)

        # Without gates
        key_nogates = f"{plan_id}_nogates"
        logger.info(f"Backtesting: {plan_params['label']} (no gates, v1 mode)...")
        sim2 = ProductionSimulator(plan_params, PRODUCTION_GATES, bars_1m, bars_30m, use_gates=False)
        res2 = sim2.run(valid_signals)
        conf_breakdown2 = analyze_by_confidence(res2["trades"])
        results[key_nogates] = {
            **res2,
            "label": f"{plan_params['label']} [无Gate]",
            "by_confidence": conf_breakdown2,
            "raw_trades": res2["trades"],
            "raw_skip_log": res2["skip_log"],
        }
        plan_keys_nogates.append(key_nogates)

    # ========================================================================
    # Print results
    # ========================================================================

    # 1. Main comparison (with gates — production parity)
    print_comparison_table(results, plan_keys_gates)

    # 2. Per-confidence breakdown (with gates)
    print_confidence_breakdown(results, plan_keys_gates)

    # 3. LOW signal focused analysis
    print_low_signal_analysis(results, plan_keys_gates)

    # 4. No-gates comparison (raw signal quality)
    print(f"\n\n{'#' * 160}")
    print(f"  无 Gate 模式 (v1) — 纯信号质量评估，不考虑 cooldown/CB/dedup 等生产保护")
    print(f"{'#' * 160}")
    print_comparison_table(results, plan_keys_nogates)
    print_confidence_breakdown(results, plan_keys_nogates)
    print_low_signal_analysis(results, plan_keys_nogates)

    # 5. Trade details for best plan
    best_key = max(plan_keys_gates, key=lambda k: results[k].get("pnl", 0))
    print_trade_details(results, best_key)

    # 6. Skip reason breakdown
    print(f"\n{'=' * 120}")
    print(f"  Gate 跳过原因分布")
    print(f"{'=' * 120}")
    for key in plan_keys_gates:
        r = results[key]
        skip_reasons = r.get("skip_reasons", {})
        if skip_reasons:
            print(f"\n  ── {r['label']} ──")
            for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
                pct = count / r['summary']['total_signals_processed'] * 100
                print(f"    {reason:<50} {count:>4} ({pct:.1f}%)")

    # ========================================================================
    # Save results
    # ========================================================================
    output_path = Path(__file__).parent.parent / "data" / "backtest_confidence_compare.json"
    output = {
        "backtest_time": datetime.now(timezone.utc).isoformat(),
        "version": "1.0 (confidence comparison)",
        "simulator": "v3.0 (multi-layer + trailing stop)",
        "symbol": SYMBOL,
        "signals_count": len(valid_signals),
        "date_range": {
            "start": valid_signals[0]["timestamp"],
            "end": valid_signals[-1]["timestamp"],
            "days": round(days_span, 1),
        },
        "signal_distribution": {
            "direction": dict(dir_dist),
            "confidence": dict(conf_dist),
        },
        "plans": {
            plan_id: {
                "label": plan_params["label"],
                "params": plan_params,
            }
            for plan_id, plan_params in ALL_PLANS.items()
        },
        "results_with_gates": {
            key: {
                "label": results[key]["label"],
                "summary": results[key]["summary"],
                "equity": results[key].get("equity", 100),
                "pnl": results[key].get("pnl", 0),
                "max_dd": results[key].get("max_dd", 0),
                "by_confidence": results[key].get("by_confidence", {}),
                "skip_reasons": results[key].get("skip_reasons", {}),
            }
            for key in plan_keys_gates
        },
        "results_no_gates": {
            key: {
                "label": results[key]["label"],
                "summary": results[key]["summary"],
                "equity": results[key].get("equity", 100),
                "pnl": results[key].get("pnl", 0),
                "max_dd": results[key].get("max_dd", 0),
                "by_confidence": results[key].get("by_confidence", {}),
            }
            for key in plan_keys_nogates
        },
    }

    os.makedirs(output_path.parent, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info(f"Results saved to {output_path}")

    print(f"\n{'=' * 120}")
    print(f"  ✅ 完成! 结果已保存到 {output_path}")
    print(f"{'=' * 120}")


# ============================================================================
# Entry point
# ============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AlgVex 信心等级参数对比回测 (HIGH/MEDIUM/LOW)"
    )
    parser.add_argument("--days", type=int, default=30,
                        help="Scan last N days of logs (default 30)")
    parser.add_argument("--signals", type=str, default=None,
                        help="Use previously exported signals JSON")
    parser.add_argument("--export-only", action="store_true",
                        help="Only extract signals, don't run backtest")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent

    if args.signals:
        sig_path = Path(args.signals)
        if not sig_path.is_absolute():
            sig_path = project_root / args.signals
        logger.info(f"Loading signals from {sig_path}...")
        with open(sig_path) as f:
            signals = json.load(f)
        logger.info(f"Loaded {len(signals)} signals from file")
    else:
        signals = extract_signals_from_journalctl(days=args.days)

        # Merge hold_counterfactuals for wider signal coverage
        cf_path = project_root / "data" / "hold_counterfactuals.json"
        cf_signals = load_hold_counterfactuals(str(cf_path))

        if cf_signals:
            existing_ts = set()
            for s in signals:
                try:
                    dt = datetime.fromisoformat(s["timestamp"])
                    existing_ts.add(int(dt.timestamp()) // 120)
                except ValueError:
                    pass

            added = 0
            for s in cf_signals:
                try:
                    dt = datetime.fromisoformat(s["timestamp"])
                    bucket = int(dt.timestamp()) // 120
                    if bucket not in existing_ts:
                        signals.append(s)
                        existing_ts.add(bucket)
                        added += 1
                except ValueError:
                    pass
            logger.info(f"Added {added} non-duplicate signals from hold_counterfactuals")

        signals.sort(key=lambda s: s["timestamp"])

    if not signals:
        logger.error("No signals found! Check if nautilus-trader service has been running.")
        logger.info("Tip: Try 'journalctl -u nautilus-trader --since \"2026-02-22\" | grep \"Judge\" | head'")
        sys.exit(1)

    # Export signals if requested
    if args.export_only:
        export_path = project_root / "data" / "extracted_signals.json"
        os.makedirs(export_path.parent, exist_ok=True)
        with open(export_path, "w") as f:
            json.dump(signals, f, indent=2, ensure_ascii=False)
        logger.info(f"Exported {len(signals)} signals to {export_path}")
        sys.exit(0)

    run_comparison(signals)
