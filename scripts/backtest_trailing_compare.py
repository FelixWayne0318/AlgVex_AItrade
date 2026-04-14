#!/usr/bin/env python3
"""
Trailing Stop A/B/C/D Comparison Backtest
追踪止损四方案对比回测

Compares four trailing stop configurations using the same signal set:
  A. Current:  30M ATR × 1.5, activation 1.1R (production status quo)
  B. v43 Fix:  30M ATR × 2.5, activation 1.5R (≈ 4H ATR × 0.6, proposed fix)
  C. Wider:    30M ATR × 4.0, activation 1.5R (aggressive widening)
  D. Disabled: No trailing stop at all (fixed SL + TP only)

B is the proposed production fix: 4H ATR × 0.6. Since the backtest only has
30M ATR, we approximate as 30M × 2.5 (4H ATR ≈ 4× 30M, so 0.6×4 = 2.4 ≈ 2.5).

Uses the existing ProductionSimulator from backtest_from_logs.py by
monkey-patching the module-level trailing constants before each run.

Usage (on server):
  cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/backtest_trailing_compare.py

  # Custom days:
  python3 scripts/backtest_trailing_compare.py --days 30

  # Use previously exported signals:
  python3 scripts/backtest_trailing_compare.py --signals data/trade_analysis_export.json
"""

import argparse
import json
import logging
import sys
import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the existing backtest infrastructure
import scripts.backtest_from_logs as bt
from utils.backtest_math import calculate_atr_wilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SYMBOL = "BTCUSDT"

# ============================================================================
# Trailing stop configurations to compare
# ============================================================================
TRAILING_CONFIGS = {
    "A_current": {
        "label": "A. 当前 v43.0 (4H ATR×0.6, 1.5R 激活)",
        "short": "A.当前",
        "activation_r": 1.5,
        "atr_multiplier": 0.6,
        "enabled": True,
    },
    "B_wider": {
        "label": "B. 放宽 (4H ATR×0.8, 1.5R 激活)",
        "short": "B.放宽",
        "activation_r": 1.5,
        "atr_multiplier": 0.8,
        "enabled": True,
    },
    "C_tight": {
        "label": "C. 收紧 (4H ATR×0.4, 1.5R 激活)",
        "short": "C.收紧",
        "activation_r": 1.5,
        "atr_multiplier": 0.4,
        "enabled": True,
    },
    "D_disabled": {
        "label": "D. 禁用 Trailing (仅固定 SL+TP)",
        "short": "D.禁用",
        "activation_r": 999.0,
        "atr_multiplier": 0.6,
        "enabled": False,
    },
}


def set_trailing_config(config: dict):
    """Monkey-patch module-level trailing constants in backtest_from_logs."""
    bt.TRAILING_ACTIVATION_R = config["activation_r"]
    bt.TRAILING_ATR_MULTIPLIER = config["atr_multiplier"]
    if not config["enabled"]:
        bt.TRAILING_ACTIVATION_R = 999.0


def fill_signals(signals: List[Dict], bars_30m: List[Dict]) -> List[Dict]:
    """Fill missing entry prices and ATR values (mirrors backtest_from_logs logic)."""
    filled_price = 0
    filled_atr = 0

    for sig in signals:
        sig_dt = datetime.fromisoformat(sig["timestamp"]).replace(tzinfo=timezone.utc)
        sig_ms = int(sig_dt.timestamp() * 1000)

        if sig.get("entry_price") is None:
            for b in bars_30m:
                if b["open_time"] <= sig_ms <= b.get("close_time", b["open_time"] + 1799999):
                    sig["entry_price"] = b["close"]
                    filled_price += 1
                    break
            if sig.get("entry_price") is None:
                for i, b in enumerate(bars_30m):
                    if b["open_time"] > sig_ms and i > 0:
                        sig["entry_price"] = bars_30m[i - 1]["close"]
                        filled_price += 1
                        break

        if sig.get("atr") is None or sig.get("atr", 0) <= 0:
            bar_idx = None
            for i, b in enumerate(bars_30m):
                if b["open_time"] <= sig_ms <= b.get("close_time", b["open_time"] + 1799999):
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

    logger.info(f"Filled {filled_price} entry prices, {filled_atr} ATR values")
    valid = [s for s in signals if s.get("entry_price") and s.get("atr") and s["atr"] > 0]
    return valid


def run_comparison(signals: List[Dict], bars_1m: List[Dict], bars_30m: List[Dict],
                   use_gates: bool = True) -> Dict[str, Dict]:
    """Run backtest for each trailing config using V40a plan."""
    results = {}
    plan = bt.PLAN_V40A  # Current production plan

    for key, config in TRAILING_CONFIGS.items():
        logger.info(f"Running: {config['label']}")

        # Monkey-patch trailing constants
        set_trailing_config(config)

        # Deep copy signals so each run has fresh state
        sig_copy = copy.deepcopy(signals)

        sim = bt.ProductionSimulator(plan, bt.PRODUCTION_GATES, bars_1m, bars_30m,
                                     use_gates=use_gates)
        res = sim.run(sig_copy)
        results[key] = res

        s = res["summary"]
        trail = s.get("trailing_exits", s.get("trailing", 0))
        logger.info(
            f"  → PnL={res['pnl']:+.2f}% | DD={res['max_dd']:.2f}% | "
            f"WR={s['win_rate']:.1f}% | TP={s.get('tp',0)} SL={s.get('sl',0)} "
            f"Trail={trail} TB={s.get('tb',0)}"
        )

    # Restore original values (v43.0)
    bt.TRAILING_ACTIVATION_R = 1.5
    bt.TRAILING_ATR_MULTIPLIER = 0.6

    return results


def print_results(results: Dict[str, Dict], use_gates: bool):
    """Print comparison results."""
    print(f"\n{'='*130}")
    print(f"  🔍 Trailing Stop 对比回测结果")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  SL/TP: V40a (SL=0.8/1.0 × ATR, R/R=1.5/1.3) | Gates: {'ON' if use_gates else 'OFF'}")
    print(f"{'='*130}")

    # Summary table
    print(f"\n  {'方案':<48} {'信号':>4} {'跳过':>4} {'仓位':>4} "
          f"{'TP':>3} {'SL':>3} {'Trail':>5} {'TB':>3} "
          f"{'胜率':>6} {'PnL':>8} {'回撤':>7} {'Calmar':>7}")
    print(f"  {'─'*120}")

    best_pnl = max(r["pnl"] for r in results.values())

    for key in ["A_current", "B_v43fix", "C_wider", "D_disabled"]:
        config = TRAILING_CONFIGS[key]
        r = results[key]
        s = r["summary"]

        trades_closed = s.get("trades_closed", 0)
        trail = s.get("trailing_exits", s.get("trailing", 0))
        pnl = r["pnl"]
        dd = r["max_dd"]
        calmar = abs(pnl / dd) if dd > 0.01 else 0

        marker = "★" if pnl == best_pnl else " "
        print(
            f"{marker} {config['label']:<47} "
            f"{s['total_signals_processed']:>4} "
            f"{s['signals_skipped_by_gates']:>4} "
            f"{trades_closed:>4} "
            f"{s.get('tp', 0):>3} {s.get('sl', 0):>3} {trail:>5} {s.get('tb', 0):>3} "
            f"{s['win_rate']:>5.1f}% "
            f"{pnl:>+7.2f}% "
            f"{dd:>6.2f}% "
            f"{calmar:>6.1f}"
        )

    print(f"  {'─'*120}")

    # Per-trade detail for each config
    for key in ["A_current", "B_v43fix", "C_wider", "D_disabled"]:
        config = TRAILING_CONFIGS[key]
        r = results[key]
        trades = r.get("trades", [])
        closed = [t for t in trades if t.get("outcome") not in ("FILTERED", "OPEN", "PYRAMID")]

        if not closed:
            print(f"\n  {config['short']}: 无平仓交易")
            continue

        print(f"\n  ── {config['label']} 逐笔 ──")
        print(f"  {'#':>3} {'时间':<18} {'方向':>4} {'入场':>10} "
              f"{'SL':>10} {'TP':>10} {'PnL%':>8} {'$PnL':>8} {'类型':>8}")
        print(f"  {'─'*100}")

        for i, t in enumerate(closed, 1):
            outcome = t.get("outcome", "?")
            side_cn = "多" if t.get("signal", "").upper() in ("LONG", "BUY") else "空"
            icon = {"TP": "🎯", "SL": "🛑", "TRAILING": "🔄", "TIME_BARRIER": "⏰",
                    "CLOSE": "👤"}.get(outcome, "❓")

            ts = t.get("timestamp", "?")[:16]
            entry = t.get("entry_price", 0)
            sl = t.get("sl_price", 0)
            tp = t.get("tp_price", 0)
            pnl_pct = t.get("pnl_pct", 0)
            dollar_pnl = t.get("dollar_pnl", 0)

            print(
                f"  {i:>3} {ts:<18} {side_cn:>4} "
                f"${entry:>9,.2f} "
                f"${sl:>9,.2f} "
                f"${tp:>9,.2f} "
                f"{pnl_pct:>+7.3f}% "
                f"${dollar_pnl:>+7.2f} " if dollar_pnl else f"{'':>9} "
                f"{icon} {outcome}"
            )

        # Sub-summary
        trailing_pnls = [t.get("dollar_pnl", 0) or 0 for t in closed if t.get("outcome") == "TRAILING"]
        sl_pnls = [t.get("dollar_pnl", 0) or 0 for t in closed if t.get("outcome") == "SL"]
        tp_pnls = [t.get("dollar_pnl", 0) or 0 for t in closed if t.get("outcome") == "TP"]

        print(f"\n    Trailing: {len(trailing_pnls)} 笔", end="")
        if trailing_pnls:
            print(f" | 总 ${sum(trailing_pnls):+.2f} | 均 ${sum(trailing_pnls)/len(trailing_pnls):+.2f}")
        else:
            print()
        print(f"    SL:       {len(sl_pnls)} 笔", end="")
        if sl_pnls:
            print(f" | 总 ${sum(sl_pnls):+.2f} | 均 ${sum(sl_pnls)/len(sl_pnls):+.2f}")
        else:
            print()
        print(f"    TP:       {len(tp_pnls)} 笔", end="")
        if tp_pnls:
            print(f" | 总 ${sum(tp_pnls):+.2f} | 均 ${sum(tp_pnls)/len(tp_pnls):+.2f}")
        else:
            print()

    # Key analysis
    a_pnl = results["A_current"]["pnl"]
    b_pnl = results["B_v43fix"]["pnl"]
    c_pnl = results["C_wider"]["pnl"]
    d_pnl = results["D_disabled"]["pnl"]

    a_trail = results["A_current"]["summary"].get("trailing_exits",
              results["A_current"]["summary"].get("trailing", 0))
    a_tp = results["A_current"]["summary"].get("tp", 0)
    d_tp = results["D_disabled"]["summary"].get("tp", 0)

    all_pnls = {"A.当前": a_pnl, "B.v43修复": b_pnl, "C.激进放宽": c_pnl, "D.禁用": d_pnl}
    best_key = max(all_pnls, key=all_pnls.get)
    best_val = all_pnls[best_key]

    print(f"\n{'='*130}")
    print(f"  📊 结论")
    print(f"{'='*130}")
    print(f"\n  A. 当前 Trailing:    PnL {a_pnl:>+7.2f}%  (trailing 平仓: {a_trail} 笔)")
    print(f"  B. v43 修复方案:     PnL {b_pnl:>+7.2f}%  (≈4H ATR×0.6, 1.5R 激活)")
    print(f"  C. 激进放宽:         PnL {c_pnl:>+7.2f}%  (30M ATR×4.0)")
    print(f"  D. 禁用 Trailing:    PnL {d_pnl:>+7.2f}%  (TP 命中: {d_tp} 笔)")

    print(f"\n  ★ 最优方案: {best_key} ({best_val:+.2f}%)")

    if best_key == "D.禁用" and a_trail > 0:
        diff = d_pnl - a_pnl
        print(f"\n  ⚠️ 禁用 Trailing 比当前好 {diff:+.2f}%")
        if d_tp > a_tp:
            print(f"     禁用后 TP 命中增加 {d_tp - a_tp} 笔 → trailing 确认在 TP 前过早止出")
        print(f"     建议: 暂时禁用 trailing stop")
    elif best_key == "B.v43修复":
        diff = b_pnl - a_pnl
        print(f"\n  ✅ v43 修复方案最优 (比当前好 {diff:+.2f}%)")
        print(f"     建议: 实施 v43 修复 — trailing 改用 4H ATR × 0.6, 激活 1.5R")
    elif best_key == "C.激进放宽":
        diff = c_pnl - a_pnl
        print(f"\n  ℹ️ 激进放宽最优 (比当前好 {diff:+.2f}%)")
        print(f"     建议: 大幅放宽 trailing 参数 (ATR×4.0, 激活 1.5R)")
    else:
        print(f"\n  ✅ 当前 Trailing 设置已是最优，无需修改")

    # Extra insight: B vs D
    if b_pnl > d_pnl:
        print(f"\n  ℹ️ B(v43修复) > D(禁用) → trailing 本身有价值，只是当前参数太紧")
    elif d_pnl > b_pnl:
        print(f"\n  ℹ️ D(禁用) > B(v43修复) → 在当前市况下 trailing 整体弊大于利")

    print(f"\n{'='*130}")


def main():
    parser = argparse.ArgumentParser(description="Trailing Stop A/B/C Comparison")
    parser.add_argument("--days", type=int, default=30, help="Days of logs (default: 30)")
    parser.add_argument("--signals", type=str, help="Use pre-exported signals JSON")
    parser.add_argument("--no-gates", action="store_true", help="Disable production gates")
    args = parser.parse_args()

    use_gates = not args.no_gates

    print(f"{'='*130}")
    print(f"  🔍 Trailing Stop 对比回测")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Gates: {'ON' if use_gates else 'OFF'}")
    print(f"{'='*130}")

    # Load or extract signals
    if args.signals:
        logger.info(f"Loading signals from {args.signals}...")
        with open(args.signals) as f:
            signals = json.load(f)
        logger.info(f"Loaded {len(signals)} signals")
    else:
        logger.info(f"Extracting signals from journalctl (last {args.days} days)...")
        signals = bt.extract_signals_from_journalctl(days=args.days)
        if not signals:
            logger.error("No signals extracted! Is nautilus-trader running?")
            sys.exit(1)
        logger.info(f"Extracted {len(signals)} signals")

    signals.sort(key=lambda s: s["timestamp"])

    # Stats
    total = len(signals)
    dir_dist = Counter(s["signal"] for s in signals)
    conf_dist = Counter(s["confidence"] for s in signals)
    print(f"\n  信号: {total} | 方向: {dict(dir_dist)} | 信心: {dict(conf_dist)}")

    # Determine time range
    first_dt = datetime.fromisoformat(signals[0]["timestamp"]).replace(tzinfo=timezone.utc)
    last_dt = datetime.fromisoformat(signals[-1]["timestamp"]).replace(tzinfo=timezone.utc)
    start_ms = int((first_dt - timedelta(days=1)).timestamp() * 1000)
    end_ms = int((last_dt + timedelta(hours=14)).timestamp() * 1000)
    days_span = (last_dt - first_dt).total_seconds() / 86400
    print(f"  范围: {signals[0]['timestamp'][:16]} → {signals[-1]['timestamp'][:16]} ({days_span:.1f} 天)")

    # Fetch kline data
    logger.info("Fetching 30M klines...")
    bars_30m = bt.fetch_klines(SYMBOL, "30m", start_ms, end_ms)
    logger.info(f"Got {len(bars_30m)} 30M bars")

    logger.info(f"Fetching 1M klines ({days_span:.0f} days)...")
    bars_1m = bt.fetch_klines(SYMBOL, "1m", start_ms, end_ms)
    logger.info(f"Got {len(bars_1m)} 1M bars")

    if not bars_1m or not bars_30m:
        logger.error("Failed to fetch kline data!")
        sys.exit(1)

    # Fill signal data
    valid_signals = fill_signals(signals, bars_30m)
    logger.info(f"Valid signals: {len(valid_signals)}/{total}")

    if not valid_signals:
        logger.error("No valid signals after data filling!")
        sys.exit(1)

    # Run comparison
    results = run_comparison(valid_signals, bars_1m, bars_30m, use_gates=use_gates)

    # Print results
    print_results(results, use_gates)

    # Save results
    output_file = Path("data/backtest_trailing_compare.json")
    output_file.parent.mkdir(exist_ok=True)
    save_data = {}
    for key, r in results.items():
        save_data[key] = {
            "config": TRAILING_CONFIGS[key],
            "summary": r["summary"],
            "pnl": r["pnl"],
            "max_dd": r["max_dd"],
            "equity": r["equity"],
        }
    with open(output_file, "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Results saved to {output_file}")


if __name__ == "__main__":
    main()
