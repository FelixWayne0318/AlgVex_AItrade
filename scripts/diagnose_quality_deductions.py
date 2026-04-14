#!/usr/bin/env python3
"""
AI Quality Scoring Deduction Diagnosis — 生产数据全面扣分诊断

100% 还原生产 on_timer() 流程:
  AIDataAssembler.fetch_external_data() → MultiAgentAnalyzer.analyze() → QualityAuditor

每轮运行 7 次 DeepSeek AI 调用，收集质量审计的每项扣分细节。
多轮对比后分类为:
  - SYSTEMATIC (系统性): ≥80% 轮出现 → 代码/规则设计问题
  - FREQUENT (频繁):   40-79% 轮出现 → AI 倾向性问题
  - RANDOM (随机):     <40% 轮出现   → 正常 AI 输出波动

Usage:
  cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
    python3 scripts/diagnose_quality_deductions.py

  Options:
    --rounds N        Number of AI analysis rounds (default: 3)
    --quick           1 round only, max detail
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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

# ============================================================================
# Imports
# ============================================================================

import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('quality_diagnosis')

import requests
from decimal import Decimal

from utils.config_manager import ConfigManager
from utils.ai_data_assembler import AIDataAssembler
from agents.multi_agent_analyzer import MultiAgentAnalyzer
from agents.ai_quality_auditor import (
    AIQualityAuditor, QualityReport, _AGENT_REQUIRED_CATEGORIES,
)
from indicators.technical_manager import TechnicalIndicatorManager

_CATEGORY_PENALTY = AIQualityAuditor._CATEGORY_PENALTY
_MTF_VIOLATION_PENALTY = AIQualityAuditor._MTF_VIOLATION_PENALTY


# ============================================================================
# Data fetching (same as production on_timer)
# ============================================================================

def fetch_production_data(config: ConfigManager) -> Dict[str, Any]:
    """Fetch all 13 data categories via AIDataAssembler + build technical indicators from klines.

    Production on_timer() gets technical_data from NautilusTrader indicator_manager
    (fed by live bars). This script replicates that by fetching klines from Binance
    and warming up TechnicalIndicatorManager instances (same as diagnose_quality_scoring.py).
    """
    print("\n📡 Fetching production data...")

    from utils.binance_kline_client import BinanceKlineClient
    from utils.order_flow_processor import OrderFlowProcessor
    from utils.coinalyze_client import CoinalyzeClient
    from utils.sentiment_client import SentimentDataFetcher

    # ========== Step 1: Build technical indicators from klines ==========
    # MockBar for feeding klines to TechnicalIndicatorManager
    class MockBar:
        def __init__(self, o, h, l, c, v, ts):
            self.open = Decimal(str(o))
            self.high = Decimal(str(h))
            self.low = Decimal(str(l))
            self.close = Decimal(str(c))
            self.volume = Decimal(str(v))
            self.ts_init = int(ts)

    def feed_klines(mgr, klines):
        """Feed klines to indicator manager, excluding last incomplete bar."""
        for k in klines[:-1]:
            bar = MockBar(
                float(k[1]), float(k[2]), float(k[3]),
                float(k[4]), float(k[5]), int(k[0]),
            )
            mgr.update(bar)

    # Get current price
    resp = requests.get(
        "https://fapi.binance.com/fapi/v1/ticker/price",
        params={"symbol": "BTCUSDT"}, timeout=10,
    )
    current_price = float(resp.json()['price'])
    print(f"  BTC price: ${current_price:,.2f}")

    # Fetch klines for 3 timeframes
    klines_data = {}
    for interval, label in [("30m", "30M"), ("4h", "4H"), ("1d", "1D")]:
        resp_k = requests.get(
            "https://fapi.binance.com/fapi/v1/klines",
            params={"symbol": "BTCUSDT", "interval": interval, "limit": 250},
            timeout=10,
        )
        klines_data[interval] = resp_k.json()
        print(f"  {label} klines: {len(klines_data[interval])} bars")

    # Build indicator managers (match production MTF config)
    mgr_30m = TechnicalIndicatorManager(sma_periods=[5, 20])
    mgr_4h = TechnicalIndicatorManager(sma_periods=[20, 50])
    mgr_1d = TechnicalIndicatorManager(sma_periods=[200])

    feed_klines(mgr_30m, klines_data["30m"])
    feed_klines(mgr_4h, klines_data["4h"])
    feed_klines(mgr_1d, klines_data["1d"])

    # Get technical data (same as production indicator_manager.get_technical_data)
    tech_30m = mgr_30m.get_technical_data(current_price)
    tech_4h = mgr_4h.get_technical_data(current_price)
    tech_1d = mgr_1d.get_technical_data(current_price)

    # Merge MTF layers (matches production ai_strategy.py flow)
    # v31.5 fix: Match production ai_strategy.py MTF layer construction.
    # get_technical_data() unpacks extension_ratios/atr_regime with ** so keys
    # like extension_regime, volatility_regime are TOP-LEVEL strings, not nested dicts.
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
        # v31.6: Match production ai_strategy.py 1D trend layer pass-through
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
    tech_30m['price'] = current_price

    print(f"  30M: RSI={tech_30m.get('rsi', 0):.1f}, ADX={tech_30m.get('adx', 0):.1f}")
    print(f"  4H:  RSI={tech_4h.get('rsi', 0):.1f}, ADX={tech_4h.get('adx', 0):.1f}")
    print(f"  1D:  RSI={tech_1d.get('rsi', 0):.1f}, ADX={tech_1d.get('adx', 0):.1f}")

    # ========== Step 2: Fetch external data (order flow, derivatives, sentiment) ==========
    kline_client = BinanceKlineClient(timeout=10)
    processor = OrderFlowProcessor(logger=None)

    base_cfg = config.config if hasattr(config, 'config') else {}

    # Coinalyze
    coinalyze_cfg = base_cfg.get('order_flow', {}).get('coinalyze', {})
    coinalyze_api_key = coinalyze_cfg.get('api_key') or os.getenv('COINALYZE_API_KEY')
    coinalyze_client = CoinalyzeClient(
        api_key=coinalyze_api_key,
        timeout=coinalyze_cfg.get('timeout', 10),
        max_retries=coinalyze_cfg.get('max_retries', 2),
    )

    # Sentiment
    sentiment_client = None
    try:
        cfg = config.strategy_config if hasattr(config, 'strategy_config') else None
        if cfg:
            sentiment_client = SentimentDataFetcher(
                lookback_hours=cfg.sentiment_lookback_hours,
                timeframe=cfg.sentiment_timeframe,
            )
        else:
            sentiment_client = SentimentDataFetcher()
    except Exception as e:
        print(f"  ⚠️ SentimentDataFetcher init failed: {e}")

    # Orderbook (optional)
    binance_orderbook = None
    orderbook_processor = None
    order_book_cfg = base_cfg.get('order_book', {})
    if order_book_cfg.get('enabled', False):
        try:
            from utils.binance_orderbook_client import BinanceOrderBookClient
            from utils.orderbook_processor import OrderBookProcessor
            ob_api_cfg = order_book_cfg.get('api', {})
            ob_proc_cfg = order_book_cfg.get('processing', {})
            binance_orderbook = BinanceOrderBookClient(
                timeout=ob_api_cfg.get('timeout', 10),
                max_retries=ob_api_cfg.get('max_retries', 2),
                logger=None,
            )
            anomaly_cfg = ob_proc_cfg.get('anomaly_detection', {})
            weighted_obi_cfg = ob_proc_cfg.get('weighted_obi', {})
            orderbook_processor = OrderBookProcessor(
                price_band_pct=ob_proc_cfg.get('price_band_pct', 0.5),
                base_anomaly_threshold=anomaly_cfg.get('base_threshold', 3.0),
                slippage_amounts=ob_proc_cfg.get('slippage_amounts', [0.1, 0.5, 1.0]),
                weighted_obi_config={
                    "base_decay": weighted_obi_cfg.get('base_decay', 0.8),
                    "adaptive": weighted_obi_cfg.get('adaptive', True),
                    "volatility_factor": weighted_obi_cfg.get('volatility_factor', 0.1),
                    "min_decay": weighted_obi_cfg.get('min_decay', 0.5),
                    "max_decay": weighted_obi_cfg.get('max_decay', 0.95),
                },
                logger=None,
            )
        except Exception as e:
            print(f"  ⚠️ Orderbook init failed: {e}")

    # Binance Derivatives (optional)
    binance_derivatives_client = None
    try:
        from utils.binance_derivatives_client import BinanceDerivativesClient
        bd_cfg = base_cfg.get('binance_derivatives', {})
        binance_derivatives_client = BinanceDerivativesClient(
            timeout=bd_cfg.get('timeout', 10),
            logger=None,
        )
    except Exception as e:
        print(f"  ⚠️ BinanceDerivativesClient init failed: {e}")

    assembler = AIDataAssembler(
        binance_kline_client=kline_client,
        order_flow_processor=processor,
        coinalyze_client=coinalyze_client,
        sentiment_client=sentiment_client,
        binance_derivatives_client=binance_derivatives_client,
        binance_orderbook_client=binance_orderbook,
        orderbook_processor=orderbook_processor,
        logger=None,
    )

    ext = assembler.fetch_external_data(
        symbol="BTCUSDT", interval="30m",
        current_price=current_price,
        volatility=tech_30m.get('bb_bandwidth', 0.02),
    )

    available = [k for k, v in ext.items() if v]
    missing = [k for k, v in ext.items() if not v]
    print(f"  ✅ External data: {len(available)}/{len(ext)} categories")
    if missing:
        print(f"  ⚠️  Missing: {', '.join(missing)}")

    # ========== Step 3: Combine into production-equivalent data dict ==========
    return {
        'technical_data': tech_30m,
        'sentiment_data': ext.get('sentiment_report'),
        'price_data': ext.get('price_data') or {'price': current_price},
        'order_flow_report': ext.get('order_flow_report'),
        'order_flow_report_4h': ext.get('order_flow_report_4h'),
        'derivatives_report': ext.get('derivatives_report'),
        'binance_derivatives': ext.get('binance_derivatives_report'),
        'orderbook_report': ext.get('orderbook_report'),
        'account_context': {'equity': 10000},
    }


# ============================================================================
# Run one analysis round (100% production pipeline)
# ============================================================================

def run_analysis_round(config: ConfigManager, data: Dict[str, Any],
                       round_num: int) -> Tuple[Dict, Dict]:
    """Run full MultiAgentAnalyzer.analyze() and return (signal_data, quality_report_dict)."""
    print(f"\n🤖 Round {round_num}: Running AI analysis (7 DeepSeek calls)...")
    start = time.time()

    # Initialize with same parameters as ai_strategy.py / ai_decision.py
    cfg = config.strategy_config if hasattr(config, 'strategy_config') else None
    if cfg:
        api_key = cfg.deepseek_api_key
        model = cfg.deepseek_model
        temperature = cfg.deepseek_temperature
        debate_rounds = cfg.debate_rounds
    else:
        api_key = os.getenv('DEEPSEEK_API_KEY', '')
        model = 'deepseek-chat'
        temperature = 0.3
        debate_rounds = 2

    analyzer = MultiAgentAnalyzer(
        api_key=api_key,
        model=model,
        temperature=temperature,
        debate_rounds=debate_rounds,
    )

    # Call analyze() with exactly the same parameters as production on_timer()
    signal_data = analyzer.analyze(
        symbol="BTCUSDT",
        technical_report=data.get('technical_data'),
        sentiment_report=data.get('sentiment_data'),
        current_position=None,
        price_data=data.get('price_data'),
        order_flow_report=data.get('order_flow_report'),
        derivatives_report=data.get('derivatives_report'),
        binance_derivatives_report=data.get('binance_derivatives'),
        orderbook_report=data.get('orderbook_report'),
        account_context=data.get('account_context', {'equity': 10000}),
        bars_data=None,
        bars_data_4h=None,
        bars_data_1d=None,
        daily_bar=None,
        weekly_bar=None,
        atr_value=None,
        data_quality_warnings=None,
        order_flow_report_4h=data.get('order_flow_report_4h'),
    )

    elapsed = time.time() - start

    if signal_data is None:
        print(f"  ❌ analyze() returned None (feature extraction failed)")
        return {}, {}

    score = signal_data.get('_quality_score', '?')
    signal = signal_data.get('signal', '?')
    confidence = signal_data.get('confidence', '?')
    print(f"  ⏱️  {elapsed:.1f}s | Signal: {signal} ({confidence}) | Score: {score}/100")

    # Get detailed quality report
    quality_report = analyzer.last_quality_report or {}

    return signal_data, quality_report


# ============================================================================
# Deduction extraction from quality report dict
# ============================================================================

class Deduction:
    """One deduction with category, points, and explanation."""
    def __init__(self, category: str, points: int, detail: str, agent: str = ''):
        self.category = category
        self.points = points
        self.detail = detail
        self.agent = agent

    @property
    def key(self) -> str:
        return f"{self.category}|{self.agent}|{self.detail}"

    def __repr__(self):
        a = f"[{self.agent}] " if self.agent else ""
        return f"-{self.points}pts {a}{self.category}: {self.detail}"


def extract_deductions(qr: Dict) -> List[Deduction]:
    """Extract every deduction from quality report dict."""
    deductions: List[Deduction] = []
    if not qr:
        return deductions

    agents = qr.get('agents', {})
    for agent_name, ar in agents.items():
        # Missing data categories
        for cat in ar.get('missing_categories', []):
            penalty = _CATEGORY_PENALTY.get(cat, 5)
            deductions.append(Deduction(
                'MISSING_DATA', penalty,
                f"未引用 {cat} 数据", agent_name,
            ))

        # SKIP signal violations
        for sv in ar.get('skip_violations', []):
            deductions.append(Deduction(
                'SKIP_VIOLATION', 3,
                f"引用 SKIP 信号: {sv}", agent_name,
            ))

        # MTF violations
        for mv in ar.get('mtf_violations', []):
            penalty = _MTF_VIOLATION_PENALTY.get(mv, 10)
            deductions.append(Deduction(
                'MTF_VIOLATION', penalty,
                f"MTF 越界: {mv}", agent_name,
            ))

        # Flags that indicate issues
        for flag in ar.get('flags', []):
            if 'EMPTY_OUTPUT' in flag:
                deductions.append(Deduction(
                    'EMPTY_OUTPUT', 10,
                    f"Agent 输出为空/异常", agent_name,
                ))

    # Citation errors
    citation_errors = qr.get('citation_errors', 0)
    if citation_errors:
        # Try to get details from flags
        citation_details = [f for f in qr.get('flags', []) if 'citation' in f.lower() or 'reversal' in f.lower()]
        if citation_details:
            for cd in citation_details:
                deductions.append(Deduction('CITATION_ERROR', 8, cd))
        else:
            deductions.append(Deduction(
                'CITATION_ERROR', 8 * citation_errors,
                f"{citation_errors} 个方向性引用错误",
            ))

    # Value errors
    value_errors = qr.get('value_errors', 0)
    if value_errors:
        val_details = [f for f in qr.get('flags', []) if 'value' in f.lower() or 'fabricat' in f.lower()]
        if val_details:
            for vd in val_details:
                deductions.append(Deduction('VALUE_ERROR', 5, vd))
        else:
            deductions.append(Deduction(
                'VALUE_ERROR', 5 * value_errors,
                f"{value_errors} 个数值捏造",
            ))

    # Zone errors
    zone_errors = qr.get('zone_errors', 0)
    if zone_errors:
        zone_details = [f for f in qr.get('flags', []) if 'zone' in f.lower()]
        if zone_details:
            for zd in zone_details:
                deductions.append(Deduction('ZONE_ERROR', 5, zd))
        else:
            deductions.append(Deduction(
                'ZONE_ERROR', 5 * zone_errors,
                f"{zone_errors} 个区域误分类",
            ))

    # Confluence
    confluence = qr.get('confluence', {})
    if confluence:
        if confluence.get('alignment_mismatch'):
            declared = confluence.get('aligned_layers_declared', 0)
            actual = confluence.get('aligned_layers_actual', 0)
            diff = abs(declared - actual)
            if diff > 0:
                deductions.append(Deduction(
                    'CONFLUENCE', diff * 10,
                    f"Judge 声称 {declared} 层对齐，实际 {actual}", 'judge',
                ))
        if confluence.get('confidence_mismatch'):
            deductions.append(Deduction(
                'CONFLUENCE', 10,
                f"Confidence 不匹配: {confluence.get('confidence_declared')} "
                f"vs 预期 {confluence.get('confidence_expected')}", 'judge',
            ))

    # Counter-trend
    if qr.get('counter_trend_detected') and not qr.get('counter_trend_flagged'):
        deductions.append(Deduction(
            'COUNTER_TREND', 15,
            "逆势未被 Entry Timing 标记", 'entry_timing',
        ))

    # Parse remaining flags for unmatched deductions
    matched_flags = set()
    for d in deductions:
        matched_flags.add(d.detail)
    for flag in qr.get('flags', []):
        if flag not in matched_flags and not any(flag in d.detail for d in deductions):
            # Try to estimate points from flag name
            pts = 0
            if 'UNCONFIRMED' in flag:
                pts = 0  # Info-only flags
            deductions.append(Deduction('FLAG', pts, flag))

    return deductions


# ============================================================================
# Multi-round classification
# ============================================================================

def classify_deductions(all_rounds: List[List[Deduction]], num_rounds: int):
    """Classify by frequency: systematic / frequent / random."""
    key_counter: Counter = Counter()
    key_examples: Dict[str, Deduction] = {}
    key_points: Dict[str, List[int]] = defaultdict(list)

    for round_deductions in all_rounds:
        seen: Set[str] = set()
        for d in round_deductions:
            key = d.key
            if key not in seen:
                key_counter[key] += 1
                seen.add(key)
            key_examples[key] = d
            key_points[key].append(d.points)

    systematic, frequent, random_d = [], [], []
    for key, count in key_counter.most_common():
        freq = count / num_rounds
        entry = {
            'example': key_examples[key],
            'count': count,
            'frequency': freq,
            'avg_points': sum(key_points[key]) / len(key_points[key]),
        }
        if freq >= 0.8:
            systematic.append(entry)
        elif freq >= 0.4:
            frequent.append(entry)
        else:
            random_d.append(entry)

    return systematic, frequent, random_d


# ============================================================================
# Output formatting
# ============================================================================

CAT_NAMES = {
    'MISSING_DATA': '📉 数据覆盖缺失',
    'SKIP_VIOLATION': '⚠️ SKIP 信号引用',
    'MTF_VIOLATION': '🔀 MTF 越界',
    'CITATION_ERROR': '❌ 方向引用错误',
    'VALUE_ERROR': '🔢 数值捏造',
    'ZONE_ERROR': '🎯 区域误分类',
    'CONFLUENCE': '🔗 Confluence 不一致',
    'COUNTER_TREND': '⚡ 逆势未标记',
    'EMPTY_OUTPUT': '💀 Agent 空输出',
    'FLAG': '🏴 其他标记',
}


def print_round_detail(round_num: int, score: int, deductions: List[Deduction],
                       signal: str, confidence: str):
    """Print detailed deduction breakdown for one round."""
    print(f"\n{'='*70}")
    print(f"📋 Round {round_num} — Score: {score}/100 | Signal: {signal} ({confidence})")
    print(f"{'='*70}")

    if not deductions:
        print("  ✅ 满分！无任何扣分")
        return

    by_cat: Dict[str, List[Deduction]] = defaultdict(list)
    for d in deductions:
        by_cat[d.category].append(d)

    for cat in ['MISSING_DATA', 'SKIP_VIOLATION', 'MTF_VIOLATION', 'CITATION_ERROR',
                'VALUE_ERROR', 'ZONE_ERROR', 'CONFLUENCE', 'COUNTER_TREND',
                'EMPTY_OUTPUT', 'FLAG']:
        items = by_cat.get(cat, [])
        if not items:
            continue
        total_pts = sum(d.points for d in items)
        label = CAT_NAMES.get(cat, cat)
        print(f"\n  {label} — 扣 {total_pts} 分:")
        for d in items:
            a = f" [{d.agent}]" if d.agent else ""
            print(f"    -{d.points}pts{a} {d.detail}")


def print_ground_truth(data: Dict, config: ConfigManager):
    """Print key market data values as reference."""
    from agents.report_formatter import ReportFormatterMixin
    formatter = ReportFormatterMixin()
    formatter.logger = logging.getLogger('report_formatter')

    try:
        features = formatter.extract_features(
            technical_data=data.get('technical_data'),
            sentiment_data=data.get('sentiment_data'),
            order_flow_data=data.get('order_flow_report'),
            order_flow_4h=data.get('order_flow_report_4h'),
            derivatives_data=data.get('derivatives_report'),
            binance_derivatives=data.get('binance_derivatives'),
            orderbook_data=data.get('orderbook_report'),
            account_context=data.get('account_context'),
        )
    except Exception as e:
        print(f"\n⚠️  Feature extraction failed: {e}")
        return

    print(f"\n📐 当前市场数据 (Ground Truth)")
    print(f"{'—'*50}")
    pairs = [
        ('rsi_30m', 'RSI 30M'), ('rsi_4h', 'RSI 4H'), ('rsi_1d', 'RSI 1D'),
        ('adx_1d', 'ADX 1D'), ('di_plus_1d', 'DI+ 1D'), ('di_minus_1d', 'DI- 1D'),
        ('macd_4h', 'MACD 4H'), ('macd_signal_4h', 'Signal 4H'),
        ('bb_position_30m', 'BB Pos 30M'), ('bb_position_4h', 'BB Pos 4H'),
        ('extension_regime', 'Extension'), ('volatility_regime', 'Volatility'),
        ('market_regime', 'Market Regime'), ('cvd_trend_30m', 'CVD 30M'),
        ('long_ratio', 'Long Ratio'), ('funding_rate_pct', 'FR %'),
        ('price', 'Price'),
    ]
    for key, label in pairs:
        val = features.get(key)
        if val is None:
            continue
        if isinstance(val, float):
            if abs(val) > 100:
                print(f"  {label:<16}: ${val:,.2f}" if 'rice' in label else f"  {label:<16}: {val:.4f}")
            else:
                print(f"  {label:<16}: {val:.4f}")
        else:
            print(f"  {label:<16}: {val}")


def print_classification(systematic, frequent, random_d, num_rounds):
    """Print final classification report."""
    total_s = sum(e['avg_points'] for e in systematic)
    total_f = sum(e['avg_points'] for e in frequent)
    total_r = sum(e['avg_points'] for e in random_d)

    print(f"\n{'='*70}")
    print(f"📊 扣分分类报告 — {num_rounds} 轮分析")
    print(f"{'='*70}")

    # Systematic
    print(f"\n🔴 系统性问题 (每轮都扣) — 平均 {total_s:.0f} 分")
    print(f"   原因: 代码逻辑或评分规则设计问题")
    print(f"   {'—'*55}")
    if systematic:
        for e in systematic:
            d = e['example']
            a = f" [{d.agent}]" if d.agent else ""
            print(f"   [{e['count']}/{num_rounds}] -{e['avg_points']:.0f}pts{a} {d.detail}")
    else:
        print("   ✅ 无")

    # Frequent
    print(f"\n🟡 频繁问题 (经常扣) — 平均 {total_f:.0f} 分")
    print(f"   原因: AI 的系统性倾向，可通过优化 prompt 改善")
    print(f"   {'—'*55}")
    if frequent:
        for e in frequent:
            d = e['example']
            a = f" [{d.agent}]" if d.agent else ""
            print(f"   [{e['count']}/{num_rounds}] -{e['avg_points']:.0f}pts{a} {d.detail}")
    else:
        print("   ✅ 无")

    # Random
    print(f"\n🟢 随机波动 (偶尔扣) — 平均 {total_r:.0f} 分")
    print(f"   原因: AI 输出正常波动，无需修复")
    print(f"   {'—'*55}")
    if random_d:
        for e in random_d:
            d = e['example']
            a = f" [{d.agent}]" if d.agent else ""
            print(f"   [{e['count']}/{num_rounds}] -{e['avg_points']:.0f}pts{a} {d.detail}")
    else:
        print("   ✅ 无")

    # Conclusion
    print(f"\n{'='*70}")
    print(f"📌 诊断结论")
    print(f"{'='*70}")
    baseline = 100 - total_s
    if systematic:
        print(f"\n  ❗ {len(systematic)} 个系统性问题，每轮固定扣 ~{total_s:.0f} 分")
        print(f"     → 修改代码或评分规则可解决")
    if frequent:
        print(f"  ⚠️  {len(frequent)} 个频繁问题，额外波动 ~{total_f:.0f} 分")
        print(f"     → 优化 Agent prompt 可改善")
    if random_d:
        print(f"  ℹ️  {len(random_d)} 个随机波动，偶尔扣 ~{total_r:.0f} 分")
    if not systematic and not frequent:
        print(f"\n  ✅ 评分系统健康！所有扣分均为 AI 正常波动。")

    print(f"\n  📈 预期分数范围: {max(0, baseline - total_f - total_r):.0f} ~ {min(100, baseline):.0f}")
    print(f"     系统性基线: {baseline:.0f}/100")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='AI Quality Scoring Deduction Diagnosis')
    parser.add_argument('--rounds', type=int, default=3,
                        help='Number of AI analysis rounds (default: 3)')
    parser.add_argument('--quick', action='store_true',
                        help='1 round with max detail')
    args = parser.parse_args()

    num_rounds = 1 if args.quick else args.rounds

    print("=" * 70)
    print("🔍 AI 质量评分扣分诊断")
    print(f"   轮数: {num_rounds} | 每轮 7 次 DeepSeek 调用")
    print(f"   时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 70)

    # Load config
    config = ConfigManager(env='production')
    config.load()
    print("✅ Config loaded")

    # Fetch data once (shared across rounds)
    data = fetch_production_data(config)
    print_ground_truth(data, config)

    # Run rounds
    all_scores: List[int] = []
    all_deductions: List[List[Deduction]] = []

    for r in range(1, num_rounds + 1):
        try:
            signal_data, qr = run_analysis_round(config, data, r)
            if not signal_data:
                all_scores.append(0)
                all_deductions.append([])
                continue

            score = signal_data.get('_quality_score', 0)
            signal = signal_data.get('signal', '?')
            confidence = signal_data.get('confidence', '?')
            deductions = extract_deductions(qr)

            all_scores.append(score)
            all_deductions.append(deductions)
            print_round_detail(r, score, deductions, signal, confidence)

            if r < num_rounds:
                print(f"\n  ⏳ 等待 3 秒...")
                time.sleep(3)

        except Exception as e:
            print(f"\n❌ Round {r} failed: {e}")
            traceback.print_exc()
            all_scores.append(0)
            all_deductions.append([])

    # Score summary
    if all_scores:
        avg = sum(all_scores) / len(all_scores)
        print(f"\n{'='*70}")
        print(f"📊 分数汇总")
        print(f"{'='*70}")
        print(f"  平均: {avg:.1f}/100 | 范围: {min(all_scores)}~{max(all_scores)} | "
              f"波动: {max(all_scores) - min(all_scores)}")
        for i, s in enumerate(all_scores, 1):
            n_ded = len(all_deductions[i - 1])
            pts = sum(d.points for d in all_deductions[i - 1])
            print(f"  Round {i}: {s}/100 ({n_ded} 项扣分, 共 {pts} 分)")

    # Classification (multi-round)
    if num_rounds >= 2 and any(all_deductions):
        systematic, frequent, random_d = classify_deductions(all_deductions, num_rounds)
        print_classification(systematic, frequent, random_d, num_rounds)
    elif num_rounds == 1 and all_deductions and all_deductions[0]:
        print(f"\n  ℹ️  单轮无法区分系统性和随机问题。")
        print(f"  建议: python3 scripts/diagnose_quality_deductions.py --rounds 3")


if __name__ == '__main__':
    main()
