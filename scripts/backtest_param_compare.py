#!/usr/bin/env python3
"""
SL/TP parameter comparison backtest using real 1M klines.

Reads signals from the recent 48h trade analysis log (or exported JSON),
tests 4 parameter sets against each signal using Binance 1M data.

Usage (on server):
  cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/backtest_param_compare.py

  # Or with a specific signal file:
  python3 scripts/backtest_param_compare.py --signals data/backtest_counterfactual_result.json
"""

import argparse
import json
import math
import os
import sys
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError

# Project root for shared imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.backtest_math import calculate_atr_wilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SYMBOL = "BTCUSDT"
BINANCE_FUTURES_BASE = "https://fapi.binance.com"

# Time barrier
TIME_BARRIER_HOURS_TREND = 12
TIME_BARRIER_HOURS_COUNTER = 6

# Fee assumptions (Binance Futures VIP 0)
# LIMIT entry (maker 0.02%) + mixed exit (avg 0.035%) + slippage 0.01%
FEE_SCENARIOS = {
    "no_fee": 0.0,
    "optimistic": 0.04,   # Both sides maker, no slippage
    "normal": 0.075,      # Maker entry + mix exit + 0.01% slippage
    "conservative": 0.10, # Some taker + 0.02% slippage
}
DEFAULT_FEE = "normal"

# ============================================================================
# 4 Parameter sets to compare
# ============================================================================
PARAM_SETS = {
    "A_baseline": {
        "label": "A: Baseline (SL=2.5, R/R=2.0, conf>=MEDIUM)",
        "sl_atr_multiplier": {"HIGH": 2.0, "MEDIUM": 2.5, "LOW": 2.5},
        "tp_rr_target": {"HIGH": 2.5, "MEDIUM": 2.0, "LOW": 2.0},
        "sl_atr_multiplier_floor": 1.5,
        "min_confidence": "MEDIUM",  # LOW signals rejected
    },
    "I_balanced": {
        "label": "I: Balanced (SL=1.8, R/R=1.5, conf>=LOW)",
        "sl_atr_multiplier": {"HIGH": 1.5, "MEDIUM": 1.8, "LOW": 1.8},
        "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.5, "LOW": 1.5},
        "sl_atr_multiplier_floor": 1.2,
        "min_confidence": "LOW",
    },
    "E_tight": {
        "label": "E: Tight SL (SL=2.0, R/R=1.5, conf>=LOW)",
        "sl_atr_multiplier": {"HIGH": 1.5, "MEDIUM": 2.0, "LOW": 2.0},
        "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.5, "LOW": 1.5},
        "sl_atr_multiplier_floor": 1.5,
        "min_confidence": "LOW",
    },
    "D_tight_rr2": {
        "label": "D: Tight SL (SL=2.0, R/R=2.0, conf>=LOW)",
        "sl_atr_multiplier": {"HIGH": 1.5, "MEDIUM": 2.0, "LOW": 2.0},
        "tp_rr_target": {"HIGH": 2.5, "MEDIUM": 2.0, "LOW": 2.0},
        "sl_atr_multiplier_floor": 1.5,
        "min_confidence": "LOW",
    },
    # v39.0: 4H ATR basis — multipliers are 4H-scale
    # NOTE: This backtest uses 30M ATR. With 4H-scale multipliers on 30M ATR,
    # SL will be ~2.8x tighter than production. For parameter comparison only.
    "G_v39_production": {
        "label": "G: v39.0 (4H ATR, SL=0.8/1.0, R/R=2.0/1.8, conf>=LOW)",
        "sl_atr_multiplier": {"HIGH": 0.8, "MEDIUM": 1.0, "LOW": 1.0},
        "tp_rr_target": {"HIGH": 2.0, "MEDIUM": 1.8, "LOW": 1.8},
        "sl_atr_multiplier_floor": 0.5,
        "min_confidence": "LOW",
    },
    # V40a: Keep v39.0 SL, lower R/R target (TP ~25% closer)
    "H_v40a_lower_rr": {
        "label": "H: V40a (SL=0.8/1.0, R/R=1.5/1.3, conf>=LOW)",
        "sl_atr_multiplier": {"HIGH": 0.8, "MEDIUM": 1.0, "LOW": 1.0},
        "tp_rr_target": {"HIGH": 1.5, "MEDIUM": 1.3, "LOW": 1.3},
        "sl_atr_multiplier_floor": 0.5,
        "min_confidence": "LOW",
    },
    # V40b: Keep v39.0 SL, even lower R/R (TP ~40% closer, scalping-like)
    "J_v40b_scalp_rr": {
        "label": "J: V40b (SL=0.8/1.0, R/R=1.3/1.2, conf>=LOW)",
        "sl_atr_multiplier": {"HIGH": 0.8, "MEDIUM": 1.0, "LOW": 1.0},
        "tp_rr_target": {"HIGH": 1.3, "MEDIUM": 1.2, "LOW": 1.2},
        "sl_atr_multiplier_floor": 0.5,
        "min_confidence": "LOW",
    },
    # V40c: Tighter SL + lower R/R (both SL and TP closer)
    "K_v40c_tight_sl": {
        "label": "K: V40c (tight SL=0.6/0.8, R/R=1.5/1.3, conf>=LOW)",
        "sl_atr_multiplier": {"HIGH": 0.6, "MEDIUM": 0.8, "LOW": 0.8},
        "tp_rr_target": {"HIGH": 1.5, "MEDIUM": 1.3, "LOW": 1.3},
        "sl_atr_multiplier_floor": 0.4,
        "min_confidence": "LOW",
    },
}

CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


# ============================================================================
# Binance API
# ============================================================================
def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> List[Dict]:
    """Fetch klines with pagination and retry."""
    all_bars = []
    current_start = start_ms
    limit = 1500

    while current_start < end_ms:
        url = (
            f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={current_start}&endTime={end_ms}&limit={limit}"
        )

        data = None
        for attempt in range(4):
            try:
                req = Request(url, headers={"User-Agent": "AlgVex-Backtest/2.0"})
                with urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                break
            except (URLError, OSError) as e:
                wait = 2 ** (attempt + 1)
                logger.warning(f"API fail (attempt {attempt+1}): {e}, retry in {wait}s")
                time.sleep(wait)
                if attempt == 3:
                    raise RuntimeError(f"Failed after 4 retries: {e}")

        if not data:
            break

        for k in data:
            all_bars.append({
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": k[6],
            })

        current_start = data[-1][6] + 1
        if len(data) < limit:
            break
        time.sleep(0.2)

    return all_bars


# ============================================================================
# SL/TP calculation
# ============================================================================
def calc_sltp(entry_price: float, side: str, atr: float, confidence: str, params: Dict) -> Optional[Dict]:
    """Calculate SL/TP for given parameters. Returns None if confidence too low."""
    conf_upper = confidence.upper()

    # Confidence filter
    min_conf = params["min_confidence"]
    if CONFIDENCE_RANK.get(conf_upper, 0) < CONFIDENCE_RANK.get(min_conf, 0):
        return None

    is_long = side.upper() in ("BUY", "LONG")

    sl_mult = params["sl_atr_multiplier"].get(conf_upper, 2.5)
    sl_mult = max(sl_mult, params["sl_atr_multiplier_floor"])
    sl_distance = atr * sl_mult

    rr_target = params["tp_rr_target"].get(conf_upper, 2.0)
    tp_distance = sl_distance * rr_target

    if is_long:
        sl_price = entry_price - sl_distance
        tp_price = entry_price + tp_distance
    else:
        sl_price = entry_price + sl_distance
        tp_price = entry_price - tp_distance

    if sl_price <= 0 or tp_price <= 0:
        return None

    return {
        "sl_price": sl_price,
        "tp_price": tp_price,
        "sl_pct": sl_distance / entry_price * 100,
        "tp_pct": tp_distance / entry_price * 100,
        "rr_target": rr_target,
    }


# ============================================================================
# Outcome scanning
# ============================================================================
def scan_outcome(
    bars_1m: List[Dict],
    entry_time_ms: int,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    side: str,
    max_hours: float = 12.0,
) -> Dict:
    """Scan 1M bars to find if SL or TP hit first."""
    is_long = side.upper() in ("BUY", "LONG")
    deadline_ms = entry_time_ms + int(max_hours * 3600 * 1000)

    mfe = 0.0  # Maximum favorable excursion
    mae = 0.0  # Maximum adverse excursion

    for bar in bars_1m:
        if bar["open_time"] < entry_time_ms:
            continue

        # Time barrier
        if bar["open_time"] > deadline_ms:
            exit_price = bar["open"]
            pnl = (exit_price - entry_price) / entry_price * 100 if is_long else (entry_price - exit_price) / entry_price * 100
            return {
                "outcome": "TIME_BARRIER",
                "exit_price": exit_price,
                "pnl_pct": round(pnl, 4),
                "minutes_held": round((bar["open_time"] - entry_time_ms) / 60000, 1),
                "mfe_pct": round(mfe, 4),
                "mae_pct": round(mae, 4),
            }

        # Track MFE/MAE
        if is_long:
            favorable = (bar["high"] - entry_price) / entry_price * 100
            adverse = (entry_price - bar["low"]) / entry_price * 100
        else:
            favorable = (entry_price - bar["low"]) / entry_price * 100
            adverse = (bar["high"] - entry_price) / entry_price * 100
        mfe = max(mfe, favorable)
        mae = max(mae, adverse)

        # Check SL/TP
        if is_long:
            sl_hit = bar["low"] <= sl_price
            tp_hit = bar["high"] >= tp_price
        else:
            sl_hit = bar["high"] >= sl_price
            tp_hit = bar["low"] <= tp_price

        if sl_hit and tp_hit:
            outcome, exit_price = "SL", sl_price  # Conservative
        elif sl_hit:
            outcome, exit_price = "SL", sl_price
        elif tp_hit:
            outcome, exit_price = "TP", tp_price
        else:
            continue

        pnl = (exit_price - entry_price) / entry_price * 100 if is_long else (entry_price - exit_price) / entry_price * 100
        return {
            "outcome": outcome,
            "exit_price": exit_price,
            "pnl_pct": round(pnl, 4),
            "minutes_held": round((bar["open_time"] - entry_time_ms) / 60000, 1),
            "mfe_pct": round(mfe, 4),
            "mae_pct": round(mae, 4),
        }

    # Data ran out
    if bars_1m:
        last = bars_1m[-1]
        exit_price = last["close"]
        pnl = (exit_price - entry_price) / entry_price * 100 if is_long else (entry_price - exit_price) / entry_price * 100
        return {
            "outcome": "OPEN",
            "exit_price": exit_price,
            "pnl_pct": round(pnl, 4),
            "minutes_held": round((last["open_time"] - entry_time_ms) / 60000, 1),
            "mfe_pct": round(mfe, 4),
            "mae_pct": round(mae, 4),
        }
    return {"outcome": "NO_DATA", "exit_price": 0, "pnl_pct": 0, "minutes_held": 0, "mfe_pct": 0, "mae_pct": 0}


# ============================================================================
# Load signals
# ============================================================================
def load_signals_from_counterfactual(path: str) -> List[Dict]:
    """Load from backtest_counterfactual_result.json format."""
    with open(path) as f:
        data = json.load(f)

    signals = []
    for s in data["signals"]:
        signals.append({
            "timestamp": s["timestamp"],
            "signal": s["signal"],
            "confidence": s["confidence"],
            "entry_price": s["entry_price"],
            "atr": s.get("atr"),
        })
    return signals


def load_signals_from_export(path: str) -> List[Dict]:
    """Load from trade_analysis_export.json format."""
    with open(path) as f:
        data = json.load(f)

    signals = []
    for d in data.get("judge_decisions", []):
        if d.get("signal") in ("LONG", "SHORT"):
            signals.append({
                "timestamp": d["timestamp"],
                "signal": d["signal"],
                "confidence": d.get("confidence", "LOW"),
                "entry_price": None,  # Will be filled from klines
                "atr": None,
            })
    return signals


# ============================================================================
# Equity simulation
# ============================================================================
def simulate_equity(trades: List[Dict], position_pct: float = 0.10, leverage: int = 10, fee_pct: float = 0.075) -> Dict:
    """Simulate equity curve with fees."""
    equity = 100.0
    peak = 100.0
    max_dd = 0
    returns = []
    equity_curve = [100.0]

    for t in trades:
        if t["outcome"] == "OPEN":
            continue
        pv = equity * position_pct * leverage
        fee = pv * fee_pct / 100
        dollar_pnl = pv * t["pnl_pct"] / 100 - fee
        ret_pct = dollar_pnl / equity * 100
        returns.append(ret_pct)
        equity += dollar_pnl
        equity_curve.append(round(equity, 4))
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Stats
    total_trades = len(returns)
    if total_trades == 0:
        return {"equity": 100, "pnl": 0, "dd": 0, "calmar": 0, "sharpe": 0, "pf": 0, "trades": 0, "wr": 0, "curve": equity_curve}

    wins = sum(1 for r in returns if r > 0)
    wr = wins / total_trades * 100
    pnl = equity - 100

    mean_ret = sum(returns) / total_trades
    var = sum((r - mean_ret) ** 2 for r in returns) / total_trades
    std = math.sqrt(var) if var > 0 else 0.001
    sharpe = mean_ret / std

    gross_profit = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    calmar = pnl / max_dd if max_dd > 0 else 0

    return {
        "equity": round(equity, 4),
        "pnl": round(pnl, 4),
        "dd": round(max_dd, 4),
        "calmar": round(calmar, 4),
        "sharpe": round(sharpe, 4),
        "pf": round(pf, 4),
        "trades": total_trades,
        "wr": round(wr, 2),
        "curve": equity_curve,
    }


# ============================================================================
# Main
# ============================================================================
def run_backtest(signals: List[Dict], use_cached_klines: bool = False):
    """Run the parameter comparison backtest."""

    if not signals:
        logger.error("No signals to backtest!")
        return

    logger.info(f"Loaded {len(signals)} signals")
    logger.info(f"Date range: {signals[0]['timestamp']} to {signals[-1]['timestamp']}")

    # Determine data range
    first_dt = datetime.fromisoformat(signals[0]["timestamp"]).replace(tzinfo=timezone.utc)
    last_dt = datetime.fromisoformat(signals[-1]["timestamp"]).replace(tzinfo=timezone.utc)
    data_start = first_dt - timedelta(days=1)  # ATR warmup
    data_end = last_dt + timedelta(hours=14)    # Forward scanning (12h + buffer)
    start_ms = int(data_start.timestamp() * 1000)
    end_ms = int(data_end.timestamp() * 1000)

    # Fetch 30M klines for ATR (production uses 30M execution layer)
    logger.info("Fetching 30M klines for ATR calculation...")
    bars_30m = fetch_klines(SYMBOL, "30m", start_ms, end_ms)
    logger.info(f"Got {len(bars_30m)} 30M bars")

    # Fetch 1M klines for outcome scanning
    logger.info("Fetching 1M klines for outcome scanning (may take 1-2 minutes)...")
    bars_1m = fetch_klines(SYMBOL, "1m", start_ms, end_ms)
    logger.info(f"Got {len(bars_1m)} 1M bars")

    # Fill missing entry prices and ATR from klines
    for sig in signals:
        sig_dt = datetime.fromisoformat(sig["timestamp"]).replace(tzinfo=timezone.utc)
        sig_ms = int(sig_dt.timestamp() * 1000)

        # Find entry price from 30M bar
        if sig["entry_price"] is None:
            for b in bars_30m:
                if b["open_time"] <= sig_ms <= b["close_time"]:
                    sig["entry_price"] = b["close"]
                    break
            if sig["entry_price"] is None:
                for i, b in enumerate(bars_30m):
                    if b["open_time"] > sig_ms and i > 0:
                        sig["entry_price"] = bars_30m[i - 1]["close"]
                        break

        # Calculate ATR if not provided
        if sig["atr"] is None or sig["atr"] <= 0:
            # Find the 30M bar index for this signal
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
                sig["atr"] = calculate_atr_wilder(atr_bars, period=14)

    # Filter out signals with missing data
    valid_signals = [s for s in signals if s["entry_price"] and s["atr"] and s["atr"] > 0]
    skipped = len(signals) - len(valid_signals)
    if skipped:
        logger.warning(f"Skipped {skipped} signals due to missing price/ATR data")

    # ========================================================================
    # Run backtest for each parameter set
    # ========================================================================
    all_results = {}

    for param_key, params in PARAM_SETS.items():
        logger.info(f"\nBacktesting: {params['label']}")
        trades = []

        for sig in valid_signals:
            sig_dt = datetime.fromisoformat(sig["timestamp"]).replace(tzinfo=timezone.utc)
            sig_ms = int(sig_dt.timestamp() * 1000)

            # Calculate SL/TP
            sltp = calc_sltp(sig["entry_price"], sig["signal"], sig["atr"], sig["confidence"], params)

            if sltp is None:
                trades.append({
                    "timestamp": sig["timestamp"],
                    "signal": sig["signal"],
                    "confidence": sig["confidence"],
                    "entry_price": sig["entry_price"],
                    "outcome": "FILTERED",
                    "pnl_pct": 0,
                    "reason": f"confidence {sig['confidence']} < {params['min_confidence']}",
                })
                continue

            # Find entry time (close of the 30M bar containing the signal)
            entry_time_ms = sig_ms
            for b in bars_30m:
                if b["open_time"] <= sig_ms <= b["close_time"]:
                    entry_time_ms = b["close_time"] + 1
                    break

            # Scan outcome
            outcome = scan_outcome(
                bars_1m=bars_1m,
                entry_time_ms=entry_time_ms,
                entry_price=sig["entry_price"],
                sl_price=sltp["sl_price"],
                tp_price=sltp["tp_price"],
                side=sig["signal"],
                max_hours=TIME_BARRIER_HOURS_TREND,
            )

            trades.append({
                "timestamp": sig["timestamp"],
                "signal": sig["signal"],
                "confidence": sig["confidence"],
                "entry_price": round(sig["entry_price"], 2),
                "atr": round(sig["atr"], 2),
                "sl_price": round(sltp["sl_price"], 2),
                "tp_price": round(sltp["tp_price"], 2),
                "sl_pct": round(sltp["sl_pct"], 4),
                "tp_pct": round(sltp["tp_pct"], 4),
                "rr_target": sltp["rr_target"],
                **outcome,
                "exit_price": round(outcome.get("exit_price", 0), 2),
            })

        all_results[param_key] = {
            "params": params,
            "trades": trades,
        }

    # ========================================================================
    # Print comparison report
    # ========================================================================
    print("\n" + "=" * 120)
    print("  AlgVex SL/TP 参数对比回测 — 真实 1M K 线 (Binance Futures)")
    print("=" * 120)
    print(f"  交易对: {SYMBOL}")
    print(f"  信号来源: {len(valid_signals)} 个 LONG/SHORT 信号")
    print(f"  时间范围: {valid_signals[0]['timestamp']} → {valid_signals[-1]['timestamp']}")
    print(f"  仓位: 10% × 10x 杠杆")

    # Signal distribution
    from collections import Counter
    conf_dist = Counter(s["confidence"] for s in valid_signals)
    dir_dist = Counter(s["signal"] for s in valid_signals)
    print(f"  信心分布: {dict(conf_dist)}")
    print(f"  方向分布: {dict(dir_dist)}")

    # ── Per-parameter summary ──
    for fee_label, fee_pct in [("no_fee", 0.0), ("normal", 0.075), ("conservative", 0.10)]:
        print(f"\n{'─' * 120}")
        print(f"  手续费: {fee_label} ({fee_pct}%/笔)")
        print(f"{'─' * 120}")
        print(f"  {'方案':<45} {'信号':>4} {'交易':>4} {'过滤':>4} {'TP':>3} {'SL':>3} {'TB':>3} {'胜率':>6} {'PnL':>8} {'含费PnL':>8} {'净值':>8} {'回撤':>7} {'Calmar':>7} {'Sharpe':>7} {'PF':>5}")
        print(f"  {'-' * 115}")

        for param_key, result in all_results.items():
            trades = result["trades"]
            active = [t for t in trades if t["outcome"] != "FILTERED"]
            filtered = len(trades) - len(active)
            closed = [t for t in active if t["outcome"] not in ("OPEN", "FILTERED")]

            tps = sum(1 for t in closed if t["outcome"] == "TP")
            sls = sum(1 for t in closed if t["outcome"] == "SL")
            tbs = sum(1 for t in closed if t["outcome"] == "TIME_BARRIER")
            wins = sum(1 for t in closed if t["pnl_pct"] > 0)
            wr = wins / len(closed) * 100 if closed else 0
            raw_pnl = sum(t["pnl_pct"] for t in closed)

            eq = simulate_equity(closed, fee_pct=fee_pct)

            label = result["params"]["label"]
            print(
                f"  {label:<45} {len(trades):>4} {len(active):>4} {filtered:>4} "
                f"{tps:>3} {sls:>3} {tbs:>3} {wr:>5.1f}% "
                f"{raw_pnl:>+7.2f}% {eq['pnl']:>+7.2f}% {eq['equity']:>7.2f} "
                f"{eq['dd']:>6.2f}% {eq['calmar']:>6.2f} {eq['sharpe']:>6.3f} {eq['pf']:>5.2f}"
            )

    # ── Per-trade detail for each param set ──
    for param_key, result in all_results.items():
        trades = result["trades"]
        active = [t for t in trades if t["outcome"] != "FILTERED"]

        if not active:
            print(f"\n  {result['params']['label']}: 无交易 (全部被 confidence 过滤)")
            continue

        print(f"\n{'=' * 120}")
        print(f"  {result['params']['label']} — 每笔详情")
        print(f"{'=' * 120}")
        print(f"  {'#':>3} {'时间':>14} {'方向':>5} {'信心':>6} {'入场':>12} {'ATR':>8} {'SL':>12} {'TP':>12} {'结果':>8} {'PnL%':>10} {'MFE%':>7} {'MAE%':>7} {'持仓':>6}")
        print(f"  {'-' * 118}")

        for i, t in enumerate(active, 1):
            outcome_str = t["outcome"]
            if outcome_str == "TP":
                outcome_str = "✅TP"
            elif outcome_str == "SL":
                outcome_str = "❌SL"
            elif outcome_str == "TIME_BARRIER":
                outcome_str = "⏰TB" + ("+" if t["pnl_pct"] > 0 else "-")

            hours = t.get("minutes_held", 0) / 60
            print(
                f"  {i:>3} {t['timestamp'][5:19]:>14} {t['signal']:>5} {t['confidence']:>6} "
                f"${t['entry_price']:>11,.2f} ${t.get('atr', 0):>7,.2f} "
                f"${t.get('sl_price', 0):>11,.2f} ${t.get('tp_price', 0):>11,.2f} "
                f"{outcome_str:>8} {t['pnl_pct']:>+9.4f}% "
                f"{t.get('mfe_pct', 0):>6.3f} {t.get('mae_pct', 0):>6.3f} "
                f"{hours:>5.1f}h"
            )

    # ── MFE/MAE analysis ──
    print(f"\n{'=' * 120}")
    print(f"  MFE/MAE 分析 (最大有利/不利偏移)")
    print(f"{'=' * 120}")

    for param_key, result in all_results.items():
        active = [t for t in result["trades"] if t["outcome"] not in ("FILTERED", "OPEN", "NO_DATA")]
        if not active:
            continue

        sl_trades = [t for t in active if t["outcome"] == "SL"]
        tp_trades = [t for t in active if t["outcome"] == "TP"]

        print(f"\n  {result['params']['label']}:")
        if sl_trades:
            avg_sl_mfe = sum(t.get("mfe_pct", 0) for t in sl_trades) / len(sl_trades)
            avg_sl_mae = sum(t.get("mae_pct", 0) for t in sl_trades) / len(sl_trades)
            sl_could_tp = sum(1 for t in sl_trades if t.get("mfe_pct", 0) > 0.5)
            print(f"    SL 交易 ({len(sl_trades)} 笔): 平均 MFE={avg_sl_mfe:.3f}%, 平均 MAE={avg_sl_mae:.3f}%")
            print(f"    SL 交易中 MFE>0.5% (曾有机会盈利): {sl_could_tp}/{len(sl_trades)}")
        if tp_trades:
            avg_tp_mfe = sum(t.get("mfe_pct", 0) for t in tp_trades) / len(tp_trades)
            avg_tp_mae = sum(t.get("mae_pct", 0) for t in tp_trades) / len(tp_trades)
            print(f"    TP 交易 ({len(tp_trades)} 笔): 平均 MFE={avg_tp_mfe:.3f}%, 平均 MAE={avg_tp_mae:.3f}%")

    # ── Breakeven analysis ──
    print(f"\n{'=' * 120}")
    print(f"  盈亏平衡分析")
    print(f"{'=' * 120}")

    for param_key, result in all_results.items():
        active = [t for t in result["trades"] if t["outcome"] not in ("FILTERED", "OPEN", "NO_DATA")]
        if not active:
            print(f"  {result['params']['label']}: 无交易")
            continue

        # Binary search for breakeven fee
        lo, hi = 0.0, 1.0
        for _ in range(50):
            mid = (lo + hi) / 2
            eq = simulate_equity(active, fee_pct=mid)
            if eq["pnl"] > 0:
                lo = mid
            else:
                hi = mid

        avg_pnl = sum(t["pnl_pct"] for t in active) / len(active)
        print(f"  {result['params']['label'][:40]:<40}: 平均 PnL={avg_pnl:+.4f}%/笔, 盈亏平衡费率={lo:.3f}%")

    # ── Signal dedup/cooldown analysis ──
    # Test different minimum intervals between trades
    print(f"\n{'=' * 120}")
    print(f"  信号去重分析: 不同冷却时间 × 参数方案 (手续费: normal 0.075%)")
    print(f"{'=' * 120}")

    cooldown_hours_list = [0, 1, 2, 3, 4, 6, 8]

    # Dedup modes:
    # 1. "any"       — cooldown applies to any signal (no new trade within N hours of last trade)
    # 2. "same_dir"  — cooldown only for same direction (LONG after LONG blocked, but SHORT after LONG allowed)
    # 3. "same_dir_or_open" — same direction blocked, plus no new trade while previous trade still open
    dedup_modes = [
        ("任意方向冷却", "any"),
        ("同方向冷却", "same_dir"),
    ]

    for mode_label, mode in dedup_modes:
        print(f"\n  ┌─ 模式: {mode_label}")
        print(f"  │ {'冷却':>4}h ", end="")
        for param_key in PARAM_SETS:
            label = PARAM_SETS[param_key]["label"][:20]
            print(f"│ {label:>20} ", end="")
        print()
        print(f"  │ {'':>5} ", end="")
        for _ in PARAM_SETS:
            print(f"│ {'笔 胜率    含费PnL':>20} ", end="")
        print()
        print(f"  │ {'-' * (6 + 23 * len(PARAM_SETS))}")

        for cooldown_h in cooldown_hours_list:
            cooldown_ms = cooldown_h * 3600 * 1000
            print(f"  │ {cooldown_h:>4}h ", end="")

            for param_key, result in all_results.items():
                trades = result["trades"]
                # Apply dedup filter
                deduped = []
                last_entry_ms = 0
                last_direction = ""

                for t in trades:
                    if t["outcome"] == "FILTERED":
                        continue

                    t_dt = datetime.fromisoformat(t["timestamp"]).replace(tzinfo=timezone.utc)
                    t_ms = int(t_dt.timestamp() * 1000)

                    if cooldown_h == 0:
                        deduped.append(t)
                        last_entry_ms = t_ms
                        last_direction = t["signal"]
                        continue

                    if mode == "any":
                        if t_ms - last_entry_ms >= cooldown_ms:
                            deduped.append(t)
                            last_entry_ms = t_ms
                            last_direction = t["signal"]
                    elif mode == "same_dir":
                        # Different direction always allowed; same direction needs cooldown
                        if t["signal"] != last_direction or t_ms - last_entry_ms >= cooldown_ms:
                            deduped.append(t)
                            last_entry_ms = t_ms
                            last_direction = t["signal"]

                closed = [t for t in deduped if t["outcome"] not in ("OPEN", "NO_DATA")]
                if not closed:
                    print(f"│ {'  0   -       -':>20} ", end="")
                    continue

                wins = sum(1 for t in closed if t["pnl_pct"] > 0)
                wr = wins / len(closed) * 100
                eq = simulate_equity(closed, fee_pct=0.075)
                print(f"│ {len(closed):>3} {wr:>4.0f}% {eq['pnl']:>+7.2f}% ", end="")

            print()

        print(f"  └{'─' * (6 + 23 * len(PARAM_SETS))}")

    # ── Detailed dedup analysis for best plan (I) ──
    print(f"\n{'=' * 120}")
    print(f"  Plan I 去重详情 (含费 0.075%)")
    print(f"{'=' * 120}")
    print(f"  {'冷却':>4}h {'模式':<12} {'笔':>3} {'TP':>3} {'SL':>3} {'TB':>3} {'胜率':>6} {'无费PnL':>8} {'含费PnL':>8} {'净值':>8} {'回撤':>7} {'Calmar':>7} {'Sharpe':>7} {'PF':>5} {'平均PnL':>8} {'BE费率':>6}")
    print(f"  {'-' * 125}")

    i_trades = all_results["I_balanced"]["trades"]

    for cooldown_h in cooldown_hours_list:
        cooldown_ms = cooldown_h * 3600 * 1000

        for mode_label, mode in dedup_modes:
            deduped = []
            last_entry_ms = 0
            last_direction = ""

            for t in i_trades:
                if t["outcome"] == "FILTERED":
                    continue

                t_dt = datetime.fromisoformat(t["timestamp"]).replace(tzinfo=timezone.utc)
                t_ms = int(t_dt.timestamp() * 1000)

                if cooldown_h == 0:
                    deduped.append(t)
                    last_entry_ms = t_ms
                    last_direction = t["signal"]
                    continue

                if mode == "any":
                    if t_ms - last_entry_ms >= cooldown_ms:
                        deduped.append(t)
                        last_entry_ms = t_ms
                        last_direction = t["signal"]
                elif mode == "same_dir":
                    if t["signal"] != last_direction or t_ms - last_entry_ms >= cooldown_ms:
                        deduped.append(t)
                        last_entry_ms = t_ms
                        last_direction = t["signal"]

            closed = [t for t in deduped if t["outcome"] not in ("OPEN", "NO_DATA")]
            if not closed:
                if cooldown_h == 0 and mode == "same_dir":
                    continue  # Skip duplicate "0h same_dir" row
                print(f"  {cooldown_h:>4}h {mode_label:<12}   0   -   -   -      -        -        -        -       -       -       -     -        -      -")
                continue

            if cooldown_h == 0 and mode == "same_dir":
                continue  # Same as "any" at 0h

            tps = sum(1 for t in closed if t["outcome"] == "TP")
            sls = sum(1 for t in closed if t["outcome"] == "SL")
            tbs = sum(1 for t in closed if t["outcome"] == "TIME_BARRIER")
            wins = sum(1 for t in closed if t["pnl_pct"] > 0)
            wr = wins / len(closed) * 100
            raw_pnl = sum(t["pnl_pct"] for t in closed)
            avg_pnl = raw_pnl / len(closed)

            eq_nofee = simulate_equity(closed, fee_pct=0)
            eq = simulate_equity(closed, fee_pct=0.075)

            # Breakeven fee
            lo_be, hi_be = 0.0, 1.0
            for _ in range(50):
                mid_be = (lo_be + hi_be) / 2
                eq_be = simulate_equity(closed, fee_pct=mid_be)
                if eq_be["pnl"] > 0:
                    lo_be = mid_be
                else:
                    hi_be = mid_be

            print(
                f"  {cooldown_h:>4}h {mode_label:<12} {len(closed):>3} {tps:>3} {sls:>3} {tbs:>3} "
                f"{wr:>5.1f}% {eq_nofee['pnl']:>+7.2f}% {eq['pnl']:>+7.2f}% {eq['equity']:>7.2f} "
                f"{eq['dd']:>6.2f}% {eq['calmar']:>6.2f} {eq['sharpe']:>6.3f} {eq['pf']:>5.2f} "
                f"{avg_pnl:>+7.4f}% {lo_be:>5.3f}%"
            )

    # ── Which trades survive each cooldown? ──
    print(f"\n{'=' * 120}")
    print(f"  Plan I: 各冷却级别保留的交易 (任意方向冷却)")
    print(f"{'=' * 120}")

    for cooldown_h in [0, 2, 4, 6]:
        cooldown_ms = cooldown_h * 3600 * 1000
        deduped = []
        last_entry_ms = 0

        for t in i_trades:
            if t["outcome"] == "FILTERED":
                continue
            t_dt = datetime.fromisoformat(t["timestamp"]).replace(tzinfo=timezone.utc)
            t_ms = int(t_dt.timestamp() * 1000)
            if cooldown_h == 0 or t_ms - last_entry_ms >= cooldown_ms:
                deduped.append(t)
                last_entry_ms = t_ms

        closed = [t for t in deduped if t["outcome"] not in ("OPEN", "NO_DATA")]
        print(f"\n  冷却 {cooldown_h}h: {len(closed)} 笔交易")
        print(f"  {'#':>3} {'时间':>14} {'方向':>5} {'结果':>6} {'PnL%':>10} {'距上笔':>8}")
        print(f"  {'-' * 55}")

        prev_ms = 0
        for i, t in enumerate(closed, 1):
            t_dt = datetime.fromisoformat(t["timestamp"]).replace(tzinfo=timezone.utc)
            t_ms = int(t_dt.timestamp() * 1000)
            gap = f"{(t_ms - prev_ms) / 3600000:.1f}h" if prev_ms > 0 else "  -"
            prev_ms = t_ms

            outcome_str = "✅TP" if t["outcome"] == "TP" else "❌SL" if t["outcome"] == "SL" else "⏰TB"
            print(f"  {i:>3} {t['timestamp'][5:19]:>14} {t['signal']:>5} {outcome_str:>6} {t['pnl_pct']:>+9.4f}% {gap:>8}")

    # ── Save results ──
    output_path = Path(__file__).parent.parent / "data" / "backtest_param_compare_result.json"
    output = {
        "backtest_time": datetime.now(timezone.utc).isoformat(),
        "symbol": SYMBOL,
        "signals_count": len(valid_signals),
        "date_range": {
            "start": valid_signals[0]["timestamp"],
            "end": valid_signals[-1]["timestamp"],
        },
        "fee_scenarios": FEE_SCENARIOS,
        "results": {},
    }

    for param_key, result in all_results.items():
        active = [t for t in result["trades"] if t["outcome"] not in ("FILTERED",)]
        closed = [t for t in active if t["outcome"] not in ("OPEN", "NO_DATA")]

        eq_no_fee = simulate_equity(closed, fee_pct=0)
        eq_normal = simulate_equity(closed, fee_pct=0.075)
        eq_conservative = simulate_equity(closed, fee_pct=0.10)

        output["results"][param_key] = {
            "label": result["params"]["label"],
            "params": {k: v for k, v in result["params"].items() if k != "label"},
            "summary": {
                "total_signals": len(result["trades"]),
                "active_trades": len(active),
                "filtered": len(result["trades"]) - len(active),
                "closed": len(closed),
                "tp": sum(1 for t in closed if t["outcome"] == "TP"),
                "sl": sum(1 for t in closed if t["outcome"] == "SL"),
                "time_barrier": sum(1 for t in closed if t["outcome"] == "TIME_BARRIER"),
                "win_rate": round(sum(1 for t in closed if t["pnl_pct"] > 0) / len(closed) * 100, 2) if closed else 0,
                "raw_pnl": round(sum(t["pnl_pct"] for t in closed), 4),
            },
            "equity": {
                "no_fee": eq_no_fee,
                "normal_fee": eq_normal,
                "conservative_fee": eq_conservative,
            },
            "trades": result["trades"],
        }

    os.makedirs(output_path.parent, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info(f"\n✅ Results saved to {output_path}")

    print(f"\n{'=' * 120}")
    print(f"  ✅ 完成! 结果已保存到 {output_path}")
    print(f"{'=' * 120}")


# ============================================================================
# Entry point
# ============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AlgVex SL/TP 参数对比回测")
    parser.add_argument(
        "--signals",
        default=None,
        help="Signal source file (auto-detects format from counterfactual or export JSON)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent

    # Auto-detect signal source
    if args.signals:
        sig_path = project_root / args.signals
    else:
        # Prefer counterfactual (recent 48h data)
        cf_path = project_root / "data" / "backtest_counterfactual_result.json"
        export_path = project_root / "data" / "trade_analysis_export.json"
        if cf_path.exists():
            sig_path = cf_path
        elif export_path.exists():
            sig_path = export_path
        else:
            logger.error("No signal file found! Provide --signals path")
            sys.exit(1)

    logger.info(f"Loading signals from {sig_path}...")

    # Detect format
    with open(sig_path) as f:
        raw = json.load(f)

    if "signals" in raw:
        signals = load_signals_from_counterfactual(str(sig_path))
        logger.info(f"Detected counterfactual format: {len(signals)} signals")
    elif "judge_decisions" in raw:
        signals = load_signals_from_export(str(sig_path))
        logger.info(f"Detected export format: {len(signals)} signals")
    else:
        logger.error(f"Unknown signal file format: {list(raw.keys())}")
        sys.exit(1)

    if not signals:
        logger.error("No LONG/SHORT signals found in file!")
        sys.exit(1)

    run_backtest(signals)
