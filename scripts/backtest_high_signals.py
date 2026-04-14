#!/usr/bin/env python3
"""
纯信号回测: HIGH 信号 + 机械 SL/TP

用途:
  从 trade_analysis_export.json 读取所有 HIGH 信号,
  从 Binance 拉取历史 K 线, 用当前 calculate_mechanical_sltp() 公式
  计算 SL/TP, 然后用 1 分钟 K 线扫描看先触发 SL 还是 TP。

运行方式 (在服务器上):
  cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/backtest_high_signals.py

  # 也可以指定自定义 export 文件:
  python3 scripts/backtest_high_signals.py --export data/trade_analysis_export.json

输出:
  - 控制台: 完整统计 + 每笔信号结果
  - 文件: data/backtest_high_signals_result.json
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError

# Project root for shared imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.backtest_math import (
    calculate_atr_wilder,
    calculate_mechanical_sltp as _shared_mechanical_sltp,
    MECHANICAL_SLTP_DEFAULTS,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Configuration imported from utils.backtest_math (SSoT)
MECHANICAL_SLTP_CONFIG = MECHANICAL_SLTP_DEFAULTS

# Time barrier (Triple Barrier 第三层)
TIME_BARRIER = {
    "enabled": True,
    "max_holding_hours_trend": 12,
    "max_holding_hours_counter": 6,
}

SYMBOL = "BTCUSDT"
BINANCE_FUTURES_BASE = "https://fapi.binance.com"


# ============================================================================
# Binance API helpers
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
    limit = 1500  # Binance max

    while current_start < end_ms:
        url = (
            f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={current_start}&endTime={end_ms}&limit={limit}"
        )

        for attempt in range(max_retries):
            try:
                req = Request(url, headers={"User-Agent": "AlgVex-Backtest/1.0"})
                with urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                break
            except (URLError, OSError) as e:
                wait = 2 ** (attempt + 1)
                logger.warning(f"API request failed (attempt {attempt+1}): {e}, retrying in {wait}s...")
                time.sleep(wait)
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Failed to fetch klines after {max_retries} retries: {e}")

        if not data:
            break

        all_klines.extend(data)
        # Move start to after the last kline's close time
        last_close_time = data[-1][6]  # close_time_ms
        current_start = last_close_time + 1

        if len(data) < limit:
            break

        # Rate limit protection
        time.sleep(0.2)

    return all_klines


def parse_klines(raw: List[list]) -> List[Dict]:
    """Parse raw Binance kline data into dicts."""
    result = []
    for k in raw:
        result.append({
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": k[6],
        })
    return result


# ATR and mechanical SL/TP imported from utils.backtest_math (SSoT)
def calculate_atr(bars_15m: List[Dict], period: int = 14) -> Optional[float]:
    """Wrapper: returns None instead of 0.0 for insufficient data."""
    result = calculate_atr_wilder(bars_15m, period)
    return result if result > 0 else None

calculate_mechanical_sltp = _shared_mechanical_sltp


# ============================================================================
# Signal scanning: determine if SL or TP is hit first
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
    """
    Scan 1m bars forward from entry to determine outcome.

    Returns dict with: outcome ('TP'/'SL'/'TIME_BARRIER'/'OPEN'), exit_price, pnl_pct, bars_held, exit_time
    """
    is_long = side.upper() in ("BUY", "LONG")
    max_holding_ms = int(max_holding_hours * 3600 * 1000)
    deadline_ms = entry_time_ms + max_holding_ms

    for bar in bars_1m:
        bar_open_time = bar["open_time"]

        # Skip bars before entry
        if bar_open_time < entry_time_ms:
            continue

        # Time barrier check
        if bar_open_time > deadline_ms:
            # Close at the bar's open price (realistic: would close at market on next bar)
            exit_price = bar["open"]
            if is_long:
                pnl_pct = (exit_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - exit_price) / entry_price * 100
            minutes_held = (bar_open_time - entry_time_ms) / 60000
            return {
                "outcome": "TIME_BARRIER",
                "exit_price": exit_price,
                "pnl_pct": round(pnl_pct, 4),
                "minutes_held": round(minutes_held, 1),
                "exit_time_ms": bar_open_time,
            }

        # Check if SL or TP hit within this bar
        bar_high = bar["high"]
        bar_low = bar["low"]

        if is_long:
            sl_hit = bar_low <= sl_price
            tp_hit = bar_high >= tp_price
        else:  # SHORT
            sl_hit = bar_high >= sl_price
            tp_hit = bar_low <= tp_price

        if sl_hit and tp_hit:
            # Both hit in same bar — conservative: assume SL hit first
            # (worst case assumption for fair backtest)
            outcome = "SL"
            exit_price = sl_price
        elif sl_hit:
            outcome = "SL"
            exit_price = sl_price
        elif tp_hit:
            outcome = "TP"
            exit_price = tp_price
        else:
            continue

        # Calculate PnL
        if is_long:
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100

        minutes_held = (bar_open_time - entry_time_ms) / 60000
        return {
            "outcome": outcome,
            "exit_price": exit_price,
            "pnl_pct": round(pnl_pct, 4),
            "minutes_held": round(minutes_held, 1),
            "exit_time_ms": bar_open_time,
        }

    # Still open (data ran out)
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
            "exit_time_ms": last_bar["open_time"],
        }

    return {"outcome": "NO_DATA", "exit_price": 0, "pnl_pct": 0, "minutes_held": 0, "exit_time_ms": 0}


# ============================================================================
# Main backtest
# ============================================================================
def run_backtest(export_path: str, output_path: str):
    """Run the pure signal backtest."""

    # Load export data
    logger.info(f"Loading signals from {export_path}...")
    with open(export_path) as f:
        export_data = json.load(f)

    judge_decisions = export_data.get("judge_decisions", [])

    # Filter HIGH LONG/SHORT signals only
    high_signals = [
        d for d in judge_decisions
        if d.get("confidence") == "HIGH" and d.get("signal") in ("LONG", "SHORT")
    ]
    logger.info(f"Found {len(high_signals)} HIGH LONG/SHORT signals out of {len(judge_decisions)} total")

    if not high_signals:
        logger.error("No HIGH signals found!")
        return

    # Determine date range (add buffer for ATR warmup and forward scanning)
    timestamps = [d["timestamp"] for d in high_signals]
    first_ts = datetime.fromisoformat(timestamps[0]).replace(tzinfo=timezone.utc)
    last_ts = datetime.fromisoformat(timestamps[-1]).replace(tzinfo=timezone.utc)

    # Buffer: 2 days before for ATR warmup, 2 days after for outcome scanning
    data_start = first_ts - timedelta(days=2)
    data_end = last_ts + timedelta(days=2)

    start_ms = int(data_start.timestamp() * 1000)
    end_ms = int(data_end.timestamp() * 1000)

    logger.info(f"Signal range: {first_ts.isoformat()} to {last_ts.isoformat()}")
    logger.info(f"Data range:   {data_start.isoformat()} to {data_end.isoformat()}")

    # Fetch 15M klines (for ATR calculation)
    logger.info("Fetching 15M klines for ATR calculation...")
    raw_15m = fetch_klines(SYMBOL, "15m", start_ms, end_ms)
    bars_15m = parse_klines(raw_15m)
    logger.info(f"Got {len(bars_15m)} 15M bars")

    # Fetch 1M klines (for precise SL/TP trigger detection)
    logger.info("Fetching 1M klines for outcome scanning (this may take a minute)...")
    raw_1m = fetch_klines(SYMBOL, "1m", start_ms, end_ms)
    bars_1m = parse_klines(raw_1m)
    logger.info(f"Got {len(bars_1m)} 1M bars")

    # Build lookup: timestamp_ms -> index for 15M bars
    bar_15m_by_time = {b["open_time"]: i for i, b in enumerate(bars_15m)}

    # Process each signal
    results = []
    skipped = 0

    for sig_idx, signal in enumerate(high_signals):
        ts_str = signal["timestamp"]
        sig_side = signal["signal"]  # LONG or SHORT
        sig_confidence = signal["confidence"]  # HIGH
        sig_risk = signal.get("risk", "N/A")

        # Parse timestamp → ms
        sig_dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        sig_ms = int(sig_dt.timestamp() * 1000)

        # Find entry price: close of the 15M bar at signal time
        # Signal fires at on_timer (every 20 min), entry = close of nearest 15M bar
        # Find the closest 15M bar at or before signal time
        entry_bar = None
        entry_bar_idx = None
        for i, b in enumerate(bars_15m):
            if b["open_time"] <= sig_ms <= b["close_time"]:
                entry_bar = b
                entry_bar_idx = i
                break
            elif b["open_time"] > sig_ms:
                # Use previous bar
                if i > 0:
                    entry_bar = bars_15m[i - 1]
                    entry_bar_idx = i - 1
                break

        if entry_bar is None and bars_15m:
            entry_bar = bars_15m[-1]
            entry_bar_idx = len(bars_15m) - 1

        if entry_bar is None:
            logger.warning(f"[{sig_idx+1}] No 15M bar found for {ts_str}, skipping")
            skipped += 1
            continue

        entry_price = entry_bar["close"]

        # Calculate ATR(14) from 15M bars up to and including entry bar
        atr_bars = bars_15m[max(0, entry_bar_idx - 14 - 1) : entry_bar_idx + 1]
        atr_value = calculate_atr(atr_bars, period=14)

        if atr_value is None or atr_value <= 0:
            logger.warning(f"[{sig_idx+1}] ATR not available for {ts_str}, skipping")
            skipped += 1
            continue

        # Calculate mechanical SL/TP
        # v39.0: estimate 4H ATR from 15M ATR (ratio ~8x: 15M→4H = 16 bars)
        # This is an approximation; production uses actual 4H ATR from indicator manager
        atr_4h_estimate = atr_value * 8.0
        success, sl_price, tp_price, rr_ratio, desc = calculate_mechanical_sltp(
            entry_price=entry_price,
            side=sig_side,
            atr_value=atr_value,
            confidence=sig_confidence,
            is_counter_trend=False,  # Default: assume with trend (conservative for SHORT in downtrend)
            atr_4h=atr_4h_estimate,
        )

        if not success:
            logger.warning(f"[{sig_idx+1}] SL/TP calc failed for {ts_str}: {desc}")
            skipped += 1
            continue

        # Scan outcome using 1M bars
        # Entry time = the bar AFTER the signal bar (signal fires → next bar is execution)
        # For LIMIT order: entry at close of signal bar, but order fills on next bar's open
        # Conservative: use the signal bar close time as entry time
        entry_time_ms = entry_bar["close_time"] + 1  # Start scanning from next bar

        outcome = scan_outcome(
            bars_1m=bars_1m,
            entry_time_ms=entry_time_ms,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            side=sig_side,
            max_holding_hours=TIME_BARRIER["max_holding_hours_trend"],
        )

        result = {
            "signal_idx": sig_idx + 1,
            "timestamp": ts_str,
            "signal": sig_side,
            "confidence": sig_confidence,
            "risk_level": sig_risk,
            "entry_price": round(entry_price, 2),
            "atr": round(atr_value, 2),
            "sl_price": round(sl_price, 2),
            "tp_price": round(tp_price, 2),
            "rr_ratio": round(rr_ratio, 2),
            "sl_distance_pct": round(abs(sl_price - entry_price) / entry_price * 100, 3),
            "tp_distance_pct": round(abs(tp_price - entry_price) / entry_price * 100, 3),
            **outcome,
            "exit_price": round(outcome.get("exit_price", 0), 2),
        }
        results.append(result)

        # Progress log
        if (sig_idx + 1) % 20 == 0 or sig_idx == 0:
            logger.info(
                f"[{sig_idx+1}/{len(high_signals)}] {ts_str} {sig_side} "
                f"@ ${entry_price:,.2f} → {outcome['outcome']} "
                f"({outcome['pnl_pct']:+.4f}%) in {outcome['minutes_held']:.0f}m"
            )

    logger.info(f"\nProcessed {len(results)} signals, skipped {skipped}")

    # ========================================================================
    # Statistics
    # ========================================================================
    if not results:
        logger.error("No results to analyze!")
        return

    tp_wins = [r for r in results if r["outcome"] == "TP"]
    sl_losses = [r for r in results if r["outcome"] == "SL"]
    time_exits = [r for r in results if r["outcome"] == "TIME_BARRIER"]
    still_open = [r for r in results if r["outcome"] == "OPEN"]

    total_closed = len(tp_wins) + len(sl_losses) + len(time_exits)
    win_rate = len(tp_wins) / total_closed * 100 if total_closed > 0 else 0

    # PnL calculations
    all_pnl = [r["pnl_pct"] for r in results if r["outcome"] != "OPEN"]
    total_pnl = sum(all_pnl)
    avg_pnl = total_pnl / len(all_pnl) if all_pnl else 0

    avg_win = sum(r["pnl_pct"] for r in tp_wins) / len(tp_wins) if tp_wins else 0
    avg_loss = sum(r["pnl_pct"] for r in sl_losses) / len(sl_losses) if sl_losses else 0
    avg_time_exit_pnl = sum(r["pnl_pct"] for r in time_exits) / len(time_exits) if time_exits else 0

    # Holding time
    avg_hold_win = sum(r["minutes_held"] for r in tp_wins) / len(tp_wins) if tp_wins else 0
    avg_hold_loss = sum(r["minutes_held"] for r in sl_losses) / len(sl_losses) if sl_losses else 0

    # Expected value
    if total_closed > 0:
        ev = (len(tp_wins) / total_closed * avg_win) + (len(sl_losses) / total_closed * avg_loss) + (len(time_exits) / total_closed * avg_time_exit_pnl)
    else:
        ev = 0

    # Profit factor
    gross_profit = sum(r["pnl_pct"] for r in results if r["pnl_pct"] > 0)
    gross_loss = abs(sum(r["pnl_pct"] for r in results if r["pnl_pct"] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Max drawdown (sequential)
    cumulative = 0
    peak = 0
    max_dd = 0
    for r in results:
        if r["outcome"] == "OPEN":
            continue
        cumulative += r["pnl_pct"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Consecutive wins/losses
    max_consec_win = 0
    max_consec_loss = 0
    cur_win = 0
    cur_loss = 0
    for r in results:
        if r["outcome"] == "OPEN":
            continue
        if r["pnl_pct"] > 0:
            cur_win += 1
            cur_loss = 0
            max_consec_win = max(max_consec_win, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            max_consec_loss = max(max_consec_loss, cur_loss)

    # Time barrier analysis
    time_barrier_wins = len([r for r in time_exits if r["pnl_pct"] > 0])
    time_barrier_losses = len([r for r in time_exits if r["pnl_pct"] <= 0])

    # ========================================================================
    # Print report
    # ========================================================================
    print("\n" + "=" * 80)
    print("  AlgVex HIGH 信号纯回测 — 机械 SL/TP (v11.0-simple)")
    print("=" * 80)

    print(f"\n📊 基础统计")
    print(f"  总信号数:        {len(results)}")
    print(f"  已关闭:          {total_closed}")
    print(f"  仍持仓:          {len(still_open)}")
    print(f"  跳过 (无数据):   {skipped}")

    print(f"\n🎯 胜率分析")
    print(f"  TP 止盈:         {len(tp_wins)} 笔 ({len(tp_wins)/total_closed*100:.1f}%)" if total_closed else "  TP: N/A")
    print(f"  SL 止损:         {len(sl_losses)} 笔 ({len(sl_losses)/total_closed*100:.1f}%)" if total_closed else "  SL: N/A")
    print(f"  时间屏障平仓:    {len(time_exits)} 笔 ({len(time_exits)/total_closed*100:.1f}%)" if total_closed else "  Time: N/A")
    print(f"    ↳ 盈利: {time_barrier_wins}, 亏损: {time_barrier_losses}")
    print(f"  胜率 (TP only):  {win_rate:.1f}%")
    profitable = [r for r in results if r["outcome"] != "OPEN" and r["pnl_pct"] > 0]
    overall_wr = len(profitable) / total_closed * 100 if total_closed > 0 else 0
    print(f"  胜率 (含时间屏障): {overall_wr:.1f}%")

    print(f"\n💰 盈亏分析")
    print(f"  平均每笔 PnL:    {avg_pnl:+.4f}%")
    print(f"  平均盈利 (TP):   {avg_win:+.4f}%")
    print(f"  平均亏损 (SL):   {avg_loss:+.4f}%")
    print(f"  平均时间屏障:    {avg_time_exit_pnl:+.4f}%")
    print(f"  累计 PnL:        {total_pnl:+.4f}%")
    print(f"  期望值 (EV):     {ev:+.4f}%")
    print(f"  利润因子:        {profit_factor:.2f}")

    print(f"\n📈 风险指标")
    print(f"  最大回撤:        {max_dd:.4f}%")
    print(f"  最大连胜:        {max_consec_win}")
    print(f"  最大连亏:        {max_consec_loss}")
    print(f"  平均持仓 (盈利): {avg_hold_win:.0f} 分钟 ({avg_hold_win/60:.1f} 小时)")
    print(f"  平均持仓 (亏损): {avg_hold_loss:.0f} 分钟 ({avg_hold_loss/60:.1f} 小时)")

    # R/R analysis
    actual_rr_values = [r["rr_ratio"] for r in results]
    print(f"\n⚖️ R/R 分析")
    print(f"  配置 R/R:        2.5:1 (HIGH)")
    print(f"  实际平均 R/R:    {sum(actual_rr_values)/len(actual_rr_values):.2f}:1")
    print(f"  盈亏比实际:      {abs(avg_win/avg_loss):.2f}:1" if avg_loss != 0 else "  盈亏比: N/A")

    # Breakeven win rate
    if avg_win > 0 and avg_loss < 0:
        be_wr = abs(avg_loss) / (avg_win + abs(avg_loss)) * 100
        print(f"  盈亏平衡胜率:    {be_wr:.1f}%")
        print(f"  实际胜率:        {overall_wr:.1f}% {'✅ 高于盈亏平衡' if overall_wr > be_wr else '❌ 低于盈亏平衡'}")

    # Signal distribution by date
    print(f"\n📅 按日分布")
    from collections import Counter
    date_counts = Counter(r["timestamp"][:10] for r in results)
    date_pnl = {}
    for r in results:
        d = r["timestamp"][:10]
        if r["outcome"] != "OPEN":
            date_pnl.setdefault(d, []).append(r["pnl_pct"])

    for date in sorted(date_counts.keys()):
        pnls = date_pnl.get(date, [])
        day_total = sum(pnls)
        day_wins = len([p for p in pnls if p > 0])
        day_total_count = len(pnls)
        print(
            f"  {date}: {date_counts[date]} 信号, "
            f"胜率 {day_wins}/{day_total_count} ({day_wins/day_total_count*100:.0f}%), "
            f"PnL {day_total:+.4f}%"
            if day_total_count > 0 else f"  {date}: {date_counts[date]} 信号"
        )

    # Print every trade detail
    print(f"\n{'='*80}")
    print(f"  每笔信号详情")
    print(f"{'='*80}")
    print(f"{'#':>4} {'时间':>20} {'方向':>5} {'入场':>12} {'ATR':>10} {'SL':>12} {'TP':>12} {'结果':>12} {'PnL%':>10} {'持仓':>8}")
    print("-" * 120)

    for r in results:
        exit_time = ""
        if r.get("exit_time_ms"):
            exit_dt = datetime.fromtimestamp(r["exit_time_ms"] / 1000, tz=timezone.utc)
            exit_time = exit_dt.strftime("%H:%M")

        outcome_str = r["outcome"]
        if r["outcome"] == "TP":
            outcome_str = "✅ TP"
        elif r["outcome"] == "SL":
            outcome_str = "❌ SL"
        elif r["outcome"] == "TIME_BARRIER":
            outcome_str = "⏰ TIME" + (" ✅" if r["pnl_pct"] > 0 else " ❌")
        elif r["outcome"] == "OPEN":
            outcome_str = "🔄 OPEN"

        hours = r["minutes_held"] / 60
        print(
            f"{r['signal_idx']:>4} "
            f"{r['timestamp'][5:19]:>14} "
            f"{r['signal']:>5} "
            f"${r['entry_price']:>11,.2f} "
            f"${r['atr']:>9,.2f} "
            f"${r['sl_price']:>11,.2f} "
            f"${r['tp_price']:>11,.2f} "
            f"{outcome_str:>12} "
            f"{r['pnl_pct']:>+9.4f}% "
            f"{hours:>6.1f}h"
        )

    print("=" * 80)

    # ========================================================================
    # Deduplication analysis: What if we only take 1 signal per N hours?
    # ========================================================================
    print(f"\n{'='*80}")
    print(f"  去重分析: 如果每 N 小时只取第一个信号?")
    print(f"{'='*80}")

    for gap_hours in [1, 2, 4, 6]:
        deduped = []
        last_entry_ms = 0
        gap_ms = gap_hours * 3600 * 1000

        for r in results:
            sig_dt = datetime.fromisoformat(r["timestamp"]).replace(tzinfo=timezone.utc)
            sig_ms = int(sig_dt.timestamp() * 1000)
            if sig_ms - last_entry_ms >= gap_ms:
                deduped.append(r)
                last_entry_ms = sig_ms

        closed_deduped = [r for r in deduped if r["outcome"] != "OPEN"]
        wins_deduped = [r for r in closed_deduped if r["pnl_pct"] > 0]
        total_pnl_deduped = sum(r["pnl_pct"] for r in closed_deduped)
        wr_deduped = len(wins_deduped) / len(closed_deduped) * 100 if closed_deduped else 0

        print(
            f"  每 {gap_hours}h 一笔: {len(deduped)} 信号, "
            f"胜率 {wr_deduped:.1f}%, "
            f"累计 PnL {total_pnl_deduped:+.4f}%, "
            f"平均 {total_pnl_deduped/len(closed_deduped):+.4f}%/笔"
            if closed_deduped else f"  每 {gap_hours}h 一笔: {len(deduped)} 信号"
        )

    # ========================================================================
    # Save results
    # ========================================================================
    output = {
        "backtest_time": datetime.now(timezone.utc).isoformat(),
        "config": {
            "mechanical_sltp": MECHANICAL_SLTP_CONFIG,
            "time_barrier": TIME_BARRIER,
            "symbol": SYMBOL,
        },
        "summary": {
            "total_signals": len(results),
            "total_closed": total_closed,
            "tp_wins": len(tp_wins),
            "sl_losses": len(sl_losses),
            "time_barrier_exits": len(time_exits),
            "still_open": len(still_open),
            "skipped": skipped,
            "win_rate_tp_only": round(win_rate, 2),
            "win_rate_overall": round(overall_wr, 2),
            "avg_pnl_pct": round(avg_pnl, 4),
            "avg_win_pct": round(avg_win, 4),
            "avg_loss_pct": round(avg_loss, 4),
            "total_pnl_pct": round(total_pnl, 4),
            "expected_value_pct": round(ev, 4),
            "profit_factor": round(profit_factor, 4),
            "max_drawdown_pct": round(max_dd, 4),
            "max_consec_wins": max_consec_win,
            "max_consec_losses": max_consec_loss,
        },
        "trades": results,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info(f"\n✅ Results saved to {output_path}")

    return output


# ============================================================================
# Entry point
# ============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AlgVex HIGH 信号纯回测")
    parser.add_argument(
        "--export",
        default="data/trade_analysis_export.json",
        help="Path to trade_analysis_export.json",
    )
    parser.add_argument(
        "--output",
        default="data/backtest_high_signals_result.json",
        help="Output path for results",
    )
    args = parser.parse_args()

    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent
    export_path = project_root / args.export
    output_path = project_root / args.output

    if not export_path.exists():
        logger.error(f"Export file not found: {export_path}")
        sys.exit(1)

    run_backtest(str(export_path), str(output_path))
