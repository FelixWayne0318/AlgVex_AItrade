#!/usr/bin/env python3
"""
backtest_counterfactual.py — Counterfactual analysis for rejected signals (v1.0)

Extracts ALL directional signals (LONG/SHORT) from recent logs — including
those rejected by Entry Timing, FR, or confidence filters — then simulates
"what if we had entered?" under multiple SL/TP parameter sets using real
Binance 1-minute klines.

Usage (on production server):
    cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
    python3 scripts/backtest_counterfactual.py

    # Custom hours range:
    python3 scripts/backtest_counterfactual.py --hours 72

    # Include HOLD signals (treat them as if Judge said LONG at current price):
    python3 scripts/backtest_counterfactual.py --include-hold

Output:
    - Console: parameter matrix comparison for each signal + aggregate stats
    - File: data/backtest_counterfactual_result.json
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

# Project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.backtest_math import calculate_atr_wilder, MECHANICAL_SLTP_DEFAULTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SYMBOL = "BTCUSDT"
BINANCE_FUTURES_BASE = "https://fapi.binance.com"


# ============================================================================
# Parameter matrix — all combinations to test
# ============================================================================
PARAM_SETS = [
    # --- Current production v44.0 (baseline) ---
    # Note: Script uses 30M ATR. Production uses 4H ATR × 1.0 (MEDIUM).
    # 4H ATR ≈ 2.5× 30M ATR, so sl_atr_mult=2.5 approximates production SL distance.
    {
        "name": "A: Current (baseline)",
        "sl_atr_mult": 2.5,  # ≈ 4H_ATR × 1.0 (production MEDIUM)
        "tp_rr_target": 1.5,  # v44.0: MEDIUM/LOW = 1.5
        "time_barrier_hours": 12,
    },
    # --- Higher R/R (further TP) ---
    {
        "name": "B: R/R 1.8",
        "sl_atr_mult": 2.5,
        "tp_rr_target": 1.8,
        "time_barrier_hours": 12,
    },
    {
        "name": "C: R/R 2.0",
        "sl_atr_mult": 2.5,
        "tp_rr_target": 2.0,
        "time_barrier_hours": 12,
    },
    # --- Tighter SL ---
    {
        "name": "D: Tight SL (2.0 ATR)",
        "sl_atr_mult": 2.0,
        "tp_rr_target": 1.5,
        "time_barrier_hours": 12,
    },
    {
        "name": "E: Tight SL + R/R 1.3",
        "sl_atr_mult": 2.0,
        "tp_rr_target": 1.3,
        "time_barrier_hours": 12,
    },
    # --- Wider SL ---
    {
        "name": "F: Wide SL (3.0 ATR)",
        "sl_atr_mult": 3.0,
        "tp_rr_target": 1.5,
        "time_barrier_hours": 12,
    },
    {
        "name": "G: Wide SL + R/R 1.8",
        "sl_atr_mult": 3.0,
        "tp_rr_target": 1.8,
        "time_barrier_hours": 12,
    },
    # --- Shorter time barrier ---
    {
        "name": "H: Short barrier 6h",
        "sl_atr_mult": 2.5,
        "tp_rr_target": 1.5,
        "time_barrier_hours": 6,
    },
    # --- Mixed optimal candidates ---
    {
        "name": "I: Balanced (SL=1.8, R/R=1.3)",
        "sl_atr_mult": 1.8,
        "tp_rr_target": 1.3,
        "time_barrier_hours": 12,
    },
    {
        "name": "J: Balanced (SL=2.2, R/R=1.8)",
        "sl_atr_mult": 2.2,
        "tp_rr_target": 1.8,
        "time_barrier_hours": 12,
    },
]


# ============================================================================
# Binance API helpers (reused from backtest_high_signals.py)
# ============================================================================
def fetch_klines(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    max_retries: int = 4,
) -> List[list]:
    """Fetch klines from Binance Futures API with pagination and retry."""
    all_klines = []
    current_start = start_ms
    limit = 1500

    while current_start < end_ms:
        url = (
            f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={current_start}&endTime={end_ms}&limit={limit}"
        )

        for attempt in range(max_retries):
            try:
                req = Request(url, headers={"User-Agent": "AlgVex-Backtest/2.0"})
                with urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                break
            except (URLError, OSError) as e:
                wait = 2 ** (attempt + 1)
                logger.warning(f"API failed (attempt {attempt+1}): {e}, retry in {wait}s...")
                time.sleep(wait)
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Failed after {max_retries} retries: {e}")

        if not data:
            break

        all_klines.extend(data)
        last_close_time = data[-1][6]
        current_start = last_close_time + 1

        if len(data) < limit:
            break

        time.sleep(0.2)

    return all_klines


def parse_klines(raw: List[list]) -> List[Dict]:
    """Parse raw Binance kline data into dicts."""
    return [
        {
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": k[6],
        }
        for k in raw
    ]


# ============================================================================
# Log parsing — extract signals from journalctl
# ============================================================================
def get_logs(hours: int) -> List[str]:
    """Fetch journalctl logs for nautilus-trader service."""
    cmd = [
        "journalctl", "-u", "nautilus-trader",
        f"--since={hours} hours ago",
        "--no-pager", "--no-hostname", "-o", "short-iso",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        lines = result.stdout.strip().split('\n')
        return [l for l in lines if l.strip()]
    except Exception as e:
        logger.error(f"journalctl failed: {e}")
        return []


def extract_signals(lines: List[str], include_hold: bool = False) -> List[Dict]:
    """
    Extract all directional signals with timestamps and context.

    Captures:
    1. Judge decisions (LONG/SHORT/HOLD) with confidence
    2. Entry prices from SL/TP calculation lines
    3. ET rejections
    4. Actual entries
    """
    signals = []
    # Track current cycle state
    current_cycle = {}

    for line in lines:
        # Extract timestamp from journalctl short-iso format
        # Format: 2026-03-13T00:37:25+0000
        ts_match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line)
        if not ts_match:
            continue
        ts_str = ts_match.group(1)

        # Judge Decision with signal and confidence
        judge_match = re.search(
            r'Judge Decision:\s*(\w+).*?Confidence:\s*(\w+)',
            line
        )
        if judge_match:
            signal = judge_match.group(1)
            confidence = judge_match.group(2)
            current_cycle = {
                'timestamp': ts_str,
                'signal': signal,
                'confidence': confidence,
                'rejected_by': None,
                'reject_reason': '',
                'entry_price': None,
                'sl_price': None,
                'tp_price': None,
            }

            # For HOLD with include_hold, we still need a price
            if signal == 'HOLD' and include_hold:
                current_cycle['signal'] = 'HOLD_LONG'  # hypothetical long
            continue

        # SL/TP calculation line — contains entry price and ATR-based SL/TP
        sltp_match = re.search(
            r'SL/TP validated.*Price=\$([\d,\.]+)\s+'
            r'SL=\$([\d,\.]+)\s+TP=\$([\d,\.]+)\s+'
            r'R/R=([\d\.]+):1',
            line
        )
        if sltp_match and current_cycle:
            current_cycle['entry_price'] = float(sltp_match.group(1).replace(',', ''))
            current_cycle['sl_price'] = float(sltp_match.group(2).replace(',', ''))
            current_cycle['tp_price'] = float(sltp_match.group(3).replace(',', ''))
            current_cycle['rr_planned'] = float(sltp_match.group(4))

        # Entry Timing REJECT
        if ('Entry Timing' in line and 'REJECT' in line) or '🚫 Entry Timing REJECT' in line:
            et_match = re.search(r'REJECT:\s*(\w+)\s*→\s*HOLD', line)
            if et_match and current_cycle:
                current_cycle['rejected_by'] = 'ET'
                current_cycle['signal'] = et_match.group(1)
                # Extract reason
                reason_match = re.search(r'reason:\s*(.+?)(?:\)|$)', line)
                if reason_match:
                    current_cycle['reject_reason'] = reason_match.group(1).strip()

                # Save this signal
                signals.append(dict(current_cycle))
                current_cycle = {}
            continue

        # FR block
        if 'FR' in line and ('block' in line.lower() or '阻止' in line):
            if current_cycle and current_cycle.get('signal') in ('LONG', 'SHORT'):
                current_cycle['rejected_by'] = 'FR'
                signals.append(dict(current_cycle))
                current_cycle = {}

        # Duplicate signal skip
        if '重复信号' in line or 'Duplicate signal' in line:
            if current_cycle and current_cycle.get('signal') in ('LONG', 'SHORT'):
                current_cycle['rejected_by'] = 'DEDUP'
                signals.append(dict(current_cycle))
                current_cycle = {}

        # Confidence too low
        if 'below minimum' in line.lower() and current_cycle:
            if current_cycle.get('signal') in ('LONG', 'SHORT'):
                current_cycle['rejected_by'] = 'CONF_LOW'
                signals.append(dict(current_cycle))
                current_cycle = {}

        # Actual execution (trade opened)
        if ('开多' in line or '开空' in line) and ('LIMIT' in line or 'MARKET' in line):
            if current_cycle and current_cycle.get('signal') in ('LONG', 'SHORT'):
                current_cycle['rejected_by'] = None  # Actually executed
                signals.append(dict(current_cycle))
                current_cycle = {}

        # HOLD signal — if include_hold, capture with current price from heartbeat
        if include_hold and 'Signal: HOLD' in line:
            # Try to extract price from heartbeat context
            price_match = re.search(r'Price[=:]\s*\$?([\d,\.]+)', line)
            if price_match and current_cycle.get('signal') == 'HOLD_LONG':
                current_cycle['entry_price'] = float(price_match.group(1).replace(',', ''))
                current_cycle['rejected_by'] = 'HOLD'
                signals.append(dict(current_cycle))
                current_cycle = {}

    # If there are directional signals without explicit price, try to fill from Binance
    return signals


def get_price_at_time(bars_1m: List[Dict], target_ms: int) -> Optional[float]:
    """Find the 1m bar close price closest to the target timestamp."""
    best = None
    best_diff = float('inf')
    for bar in bars_1m:
        diff = abs(bar['open_time'] - target_ms)
        if diff < best_diff:
            best_diff = diff
            best = bar['close']
        if bar['open_time'] > target_ms + 60000:
            break
    return best


# ============================================================================
# Outcome simulation
# ============================================================================
def scan_outcome(
    bars_1m: List[Dict],
    entry_time_ms: int,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    side: str,
    max_holding_hours: float = 12.0,
) -> Dict:
    """Scan 1m bars forward to determine SL/TP/TIME_BARRIER outcome."""
    is_long = side.upper() in ("BUY", "LONG")
    max_holding_ms = int(max_holding_hours * 3600 * 1000)
    deadline_ms = entry_time_ms + max_holding_ms

    max_favorable = 0.0  # Track maximum favorable excursion (MFE)
    max_adverse = 0.0    # Track maximum adverse excursion (MAE)

    for bar in bars_1m:
        if bar["open_time"] < entry_time_ms:
            continue

        # Time barrier
        if bar["open_time"] > deadline_ms:
            exit_price = bar["open"]
            if is_long:
                pnl_pct = (exit_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - exit_price) / entry_price * 100
            return {
                "outcome": "TIME_BARRIER",
                "exit_price": exit_price,
                "pnl_pct": round(pnl_pct, 4),
                "minutes_held": round((bar["open_time"] - entry_time_ms) / 60000, 1),
                "mfe_pct": round(max_favorable, 4),
                "mae_pct": round(max_adverse, 4),
            }

        # Track MFE/MAE
        if is_long:
            favorable = (bar["high"] - entry_price) / entry_price * 100
            adverse = (entry_price - bar["low"]) / entry_price * 100
        else:
            favorable = (entry_price - bar["low"]) / entry_price * 100
            adverse = (bar["high"] - entry_price) / entry_price * 100

        max_favorable = max(max_favorable, favorable)
        max_adverse = max(max_adverse, adverse)

        # SL/TP check
        if is_long:
            sl_hit = bar["low"] <= sl_price
            tp_hit = bar["high"] >= tp_price
        else:
            sl_hit = bar["high"] >= sl_price
            tp_hit = bar["low"] <= tp_price

        if sl_hit and tp_hit:
            outcome = "SL"  # Conservative assumption
            exit_price = sl_price
        elif sl_hit:
            outcome = "SL"
            exit_price = sl_price
        elif tp_hit:
            outcome = "TP"
            exit_price = tp_price
        else:
            continue

        if is_long:
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100

        return {
            "outcome": outcome,
            "exit_price": exit_price,
            "pnl_pct": round(pnl_pct, 4),
            "minutes_held": round((bar["open_time"] - entry_time_ms) / 60000, 1),
            "mfe_pct": round(max_favorable, 4),
            "mae_pct": round(max_adverse, 4),
        }

    # Still open
    last_bar = bars_1m[-1] if bars_1m else None
    if last_bar:
        exit_price = last_bar["close"]
        if is_long:
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100
        return {
            "outcome": "OPEN",
            "exit_price": exit_price,
            "pnl_pct": round(pnl_pct, 4),
            "minutes_held": round((last_bar["open_time"] - entry_time_ms) / 60000, 1),
            "mfe_pct": round(max_favorable, 4),
            "mae_pct": round(max_adverse, 4),
        }

    return {"outcome": "NO_DATA", "exit_price": 0, "pnl_pct": 0, "minutes_held": 0, "mfe_pct": 0, "mae_pct": 0}


# ============================================================================
# Main backtest logic
# ============================================================================
def run_backtest(hours: int, include_hold: bool):
    """Run the counterfactual backtest."""

    print()
    print("=" * 74)
    print("  📊 反事实回测: 被拦截信号 × 多参数组合 (Counterfactual Backtest)")
    print("=" * 74)

    # Step 1: Extract signals from logs
    print(f"\n  ⏳ 正在获取最近 {hours} 小时的日志...")
    lines = get_logs(hours)
    if not lines:
        print("  ❌ 无法获取日志。请确保在生产服务器上运行。")
        return

    print(f"  ✅ 获取到 {len(lines)} 行日志")

    signals = extract_signals(lines, include_hold)
    # Filter to only directional signals
    directional = [s for s in signals if s.get('signal') in ('LONG', 'SHORT')]
    print(f"  ✅ 提取到 {len(directional)} 个方向信号 (LONG/SHORT)")

    if not directional:
        print("\n  ⚠️ 未找到方向信号。尝试从心跳中提取价格做假设性测试...")
        # Fallback: extract prices from heartbeat and create hypothetical signals
        directional = _extract_hypothetical_signals(lines, hours)
        if not directional:
            print("  ❌ 无法提取任何信号数据。")
            return

    # Step 2: Determine data range and fetch klines
    now = datetime.now(timezone.utc)
    data_start = now - timedelta(hours=hours + 24)  # Extra 24h for ATR warmup
    data_end = now + timedelta(hours=1)  # Small buffer

    start_ms = int(data_start.timestamp() * 1000)
    end_ms = int(data_end.timestamp() * 1000)

    print(f"\n  ⏳ 正在从 Binance 拉取 30M K 线数据 (ATR 计算)...")
    raw_30m = fetch_klines(SYMBOL, "30m", start_ms, end_ms)
    bars_30m = parse_klines(raw_30m)
    print(f"  ✅ 获取到 {len(bars_30m)} 根 30M K 线")

    print(f"  ⏳ 正在从 Binance 拉取 1M K 线数据 (精确扫描)...")
    raw_1m = fetch_klines(SYMBOL, "1m", start_ms, end_ms)
    bars_1m = parse_klines(raw_1m)
    print(f"  ✅ 获取到 {len(bars_1m)} 根 1M K 线")

    if not bars_30m or not bars_1m:
        print("  ❌ K 线数据不足。")
        return

    # Step 3: For each signal, compute ATR and test all parameter sets
    all_results = []

    for i, sig in enumerate(directional, 1):
        ts_str = sig['timestamp']
        signal = sig['signal']
        confidence = sig.get('confidence', 'MEDIUM')
        rejected_by = sig.get('rejected_by', 'EXECUTED')
        reject_reason = sig.get('reject_reason', '')

        # Parse timestamp to ms
        try:
            dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        except ValueError:
            dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        signal_ms = int(dt.timestamp() * 1000)

        # Get entry price
        entry_price = sig.get('entry_price')
        if not entry_price:
            entry_price = get_price_at_time(bars_1m, signal_ms)
        if not entry_price:
            logger.warning(f"Signal {i}: Cannot determine entry price, skipping")
            continue

        # Calculate ATR at signal time using 30M bars
        bars_before = [b for b in bars_30m if b['open_time'] <= signal_ms]
        if len(bars_before) < 15:
            logger.warning(f"Signal {i}: Insufficient 30M bars for ATR, skipping")
            continue
        atr = calculate_atr_wilder(bars_before[-30:], period=14)
        if atr <= 0:
            logger.warning(f"Signal {i}: ATR is 0, skipping")
            continue

        atr_pct = atr / entry_price * 100

        # Print signal header
        print(f"\n{'─' * 74}")
        status = f"[{rejected_by}]" if rejected_by else "[EXECUTED]"
        print(f"  Signal #{i}: {signal} @ ${entry_price:,.0f} | {confidence} | {status}")
        print(f"  时间: {ts_str} | ATR: ${atr:,.0f} ({atr_pct:.2f}%)")
        if reject_reason:
            print(f"  拦截原因: {reject_reason[:80]}")
        print()

        # Test each parameter set
        signal_results = []
        header = f"  {'方案':<32} {'SL%':>6} {'TP%':>6} {'R/R':>5} │ {'结果':>6} {'PnL%':>8} {'持仓':>6} {'MFE%':>6} {'MAE%':>6}"
        print(header)
        print(f"  {'─' * 31} {'─' * 6} {'─' * 6} {'─' * 5} ┼ {'─' * 6} {'─' * 8} {'─' * 6} {'─' * 6} {'─' * 6}")

        for params in PARAM_SETS:
            sl_mult = params['sl_atr_mult']
            rr_target = params['tp_rr_target']
            tb_hours = params['time_barrier_hours']

            # Calculate SL/TP
            sl_distance = atr * sl_mult
            tp_distance = sl_distance * rr_target
            is_long = signal.upper() in ('LONG', 'BUY')

            if is_long:
                sl_price = entry_price - sl_distance
                tp_price = entry_price + tp_distance
            else:
                sl_price = entry_price + sl_distance
                tp_price = entry_price - tp_distance

            sl_pct = sl_distance / entry_price * 100
            tp_pct = tp_distance / entry_price * 100

            # Scan outcome
            result = scan_outcome(
                bars_1m, signal_ms, entry_price,
                sl_price, tp_price, signal,
                max_holding_hours=tb_hours,
            )

            outcome = result['outcome']
            pnl_pct = result['pnl_pct']
            minutes = result['minutes_held']
            mfe = result['mfe_pct']
            mae = result['mae_pct']

            hours_held = minutes / 60

            # Color-code outcome
            if outcome == 'TP':
                outcome_str = '✅ TP'
            elif outcome == 'SL':
                outcome_str = '❌ SL'
            elif outcome == 'TIME_BARRIER':
                outcome_str = '⏰ TB'
            elif outcome == 'OPEN':
                outcome_str = '⏳ 持仓'
            else:
                outcome_str = outcome

            pnl_str = f"{pnl_pct:+.2f}%"

            print(f"  {params['name']:<32} {sl_pct:>5.2f}% {tp_pct:>5.2f}% {rr_target:>4.1f}:1 │ {outcome_str:>6} {pnl_str:>8} {hours_held:>5.1f}h {mfe:>5.2f}% {mae:>5.2f}%")

            signal_results.append({
                'params': params['name'],
                'sl_pct': round(sl_pct, 4),
                'tp_pct': round(tp_pct, 4),
                'rr_target': rr_target,
                **result,
            })

        all_results.append({
            'signal': signal,
            'timestamp': ts_str,
            'entry_price': entry_price,
            'confidence': confidence,
            'rejected_by': rejected_by,
            'reject_reason': reject_reason,
            'atr': round(atr, 2),
            'atr_pct': round(atr_pct, 4),
            'results': signal_results,
        })

    # Step 4: Aggregate results by parameter set
    if not all_results:
        print("\n  ❌ 无信号可分析。")
        return

    print(f"\n{'=' * 74}")
    print(f"  📊 汇总: {len(all_results)} 个信号 × {len(PARAM_SETS)} 种参数组合")
    print(f"{'=' * 74}")

    # Aggregate stats per parameter set
    agg = defaultdict(lambda: {
        'tp_count': 0, 'sl_count': 0, 'tb_count': 0, 'open_count': 0,
        'total_pnl': 0.0, 'pnls': [], 'mfes': [], 'maes': [],
        'total_signals': 0,
    })

    for sig_result in all_results:
        for r in sig_result['results']:
            name = r['params']
            a = agg[name]
            a['total_signals'] += 1
            a['pnls'].append(r['pnl_pct'])
            a['total_pnl'] += r['pnl_pct']
            a['mfes'].append(r['mfe_pct'])
            a['maes'].append(r['mae_pct'])
            if r['outcome'] == 'TP':
                a['tp_count'] += 1
            elif r['outcome'] == 'SL':
                a['sl_count'] += 1
            elif r['outcome'] == 'TIME_BARRIER':
                a['tb_count'] += 1
            elif r['outcome'] == 'OPEN':
                a['open_count'] += 1

    # Print aggregate comparison
    print()
    header = f"  {'方案':<32} {'胜率':>6} {'TP':>3} {'SL':>3} {'TB':>3} {'总PnL':>8} {'平均PnL':>8} {'平均MFE':>8} {'平均MAE':>8}"
    print(header)
    print(f"  {'─' * 100}")

    best_name = None
    best_pnl = float('-inf')

    for params in PARAM_SETS:
        name = params['name']
        a = agg[name]
        total = a['total_signals']
        if total == 0:
            continue

        win_rate = a['tp_count'] / total * 100 if total > 0 else 0
        avg_pnl = a['total_pnl'] / total
        avg_mfe = sum(a['mfes']) / total if a['mfes'] else 0
        avg_mae = sum(a['maes']) / total if a['maes'] else 0

        # Track best
        if a['total_pnl'] > best_pnl:
            best_pnl = a['total_pnl']
            best_name = name

        # Winning indicator
        indicator = ' ⭐' if name == best_name else ''

        print(
            f"  {name:<32} {win_rate:>5.0f}% {a['tp_count']:>3} {a['sl_count']:>3} "
            f"{a['tb_count']:>3} {a['total_pnl']:>+7.2f}% {avg_pnl:>+7.2f}% "
            f"{avg_mfe:>7.2f}% {avg_mae:>7.2f}%{indicator}"
        )

    # Print recommendation
    print(f"\n{'─' * 74}")
    print(f"  🏆 最佳方案: {best_name}")
    a = agg[best_name]
    total = a['total_signals']
    print(f"     总 PnL: {a['total_pnl']:+.2f}% | 胜率: {a['tp_count']}/{total} ({a['tp_count']/total*100:.0f}%)")
    print(f"     平均 MFE: {sum(a['mfes'])/total:.2f}% (最大有利偏移)")
    print(f"     平均 MAE: {sum(a['maes'])/total:.2f}% (最大不利偏移)")

    # MFE analysis — shows optimal TP distance
    all_mfes = []
    for sig_result in all_results:
        if sig_result['results']:
            all_mfes.append(sig_result['results'][0]['mfe_pct'])  # MFE is same for all param sets
    if all_mfes:
        avg_mfe_all = sum(all_mfes) / len(all_mfes)
        max_mfe_all = max(all_mfes)
        print(f"\n  📈 MFE 分析 (所有信号平均最大有利偏移):")
        print(f"     平均: {avg_mfe_all:.2f}% | 最大: {max_mfe_all:.2f}%")
        print(f"     → TP 距离应 ≤ {avg_mfe_all:.2f}% 才能被多数信号触达")

    all_maes = []
    for sig_result in all_results:
        if sig_result['results']:
            all_maes.append(sig_result['results'][0]['mae_pct'])
    if all_maes:
        avg_mae_all = sum(all_maes) / len(all_maes)
        max_mae_all = max(all_maes)
        print(f"\n  📉 MAE 分析 (所有信号平均最大不利偏移):")
        print(f"     平均: {avg_mae_all:.2f}% | 最大: {max_mae_all:.2f}%")
        print(f"     → SL 距离应 > {avg_mae_all:.2f}% 才能避免被震出")

    print(f"\n{'=' * 74}")
    print()

    # Save results
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'data', 'backtest_counterfactual_result.json'
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    export_data = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'hours_analyzed': hours,
        'total_signals': len(all_results),
        'signals': all_results,
        'aggregate': {
            name: {
                'tp_count': a['tp_count'],
                'sl_count': a['sl_count'],
                'tb_count': a['tb_count'],
                'open_count': a['open_count'],
                'total_pnl': round(a['total_pnl'], 4),
                'avg_pnl': round(a['total_pnl'] / a['total_signals'], 4) if a['total_signals'] > 0 else 0,
                'win_rate': round(a['tp_count'] / a['total_signals'] * 100, 1) if a['total_signals'] > 0 else 0,
            }
            for name, a in agg.items()
        },
        'best_params': best_name,
    }

    try:
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        print(f"  📁 结果已保存: {output_path}")
    except Exception as e:
        logger.warning(f"Failed to save results: {e}")


def _extract_hypothetical_signals(lines: List[str], hours: int) -> List[Dict]:
    """
    Fallback: if no explicit LONG/SHORT signals found, extract price data
    from heartbeat logs and create hypothetical LONG signals at regular intervals.
    This allows testing SL/TP parameters even when the bot only outputs HOLD.
    """
    prices = []
    for line in lines:
        # Match heartbeat price patterns
        # Common patterns: "BTC: $70,256" or "Price: $70256" or "price=$70256.5"
        m = re.search(r'(?:BTC|Price|price)[=:\s]*\$?([\d,]+\.?\d*)', line)
        if m:
            ts_match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line)
            if ts_match:
                price = float(m.group(1).replace(',', ''))
                if price > 1000:  # Sanity check for BTC price
                    prices.append({
                        'timestamp': ts_match.group(1),
                        'price': price,
                    })

    if not prices:
        return []

    # Sample evenly: take one signal every ~4 hours
    interval = max(1, len(prices) // (hours // 4))
    sampled = prices[::interval]

    signals = []
    for p in sampled[:20]:  # Cap at 20 hypothetical signals
        signals.append({
            'timestamp': p['timestamp'],
            'signal': 'LONG',
            'confidence': 'MEDIUM',
            'rejected_by': 'HYPOTHETICAL',
            'reject_reason': 'Hypothetical LONG for parameter testing',
            'entry_price': p['price'],
        })

    logger.info(f"Created {len(signals)} hypothetical LONG signals from heartbeat prices")
    return signals


# ============================================================================
# Entry point
# ============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Counterfactual backtest for rejected trading signals"
    )
    parser.add_argument(
        "--hours", type=int, default=48,
        help="Hours of log history to analyze (default: 48)"
    )
    parser.add_argument(
        "--include-hold", action="store_true",
        help="Include HOLD signals as hypothetical LONG entries"
    )
    args = parser.parse_args()

    run_backtest(args.hours, args.include_hold)
