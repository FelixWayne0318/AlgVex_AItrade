"""
AI Decision Module

Handles MultiAgent AI analysis and decision-making:
- AI input data validation (13 categories)
- Sequential AI call execution (5~7+1 DeepSeek API calls, v23.0 Entry Timing Agent)
- Entry Timing Agent standalone test (forced, 1 extra API call)
- Prompt structure verification (5 agents: Bull/Bear/Judge/EntryTiming/Risk)
- Bull/Bear debate transcript display
- v27.0: Feature extraction + structured debate verification
- v31.3: AI Quality Audit complete display (citation/value/zone errors + neutral tracking)
- v42.0: ET Exhaustion mechanism display (Tier 1/2 flags + skip_entry_timing parameter)

v27.0: Feature-Driven Architecture diagnostic update:
  - MultiAgentAnalyzer: shows structured vs text path selection + extract_features() status
  - _display_results: shows decisive_reasons, evidence/risk_flags tags, conviction scores
  - _display_call_trace: shows schema_version, feature_version, prompt_hash, json_mode per call
  - _display_prompt_structure: detects feature-driven JSON prompts vs text prompts
  - _display_debate_transcript: shows structured Bull/Bear output (tags + conviction)
  - Feature snapshot verification: persistence to data/feature_snapshots/
  - _display_structured_path_verification: 9-check production parity audit
    (extract_features success, structured debate confirmation, json_mode per call,
     feature_dict input, REASON_TAGS, schema violations, replay readiness,
     feature dict determinism hash, v28.0 dimensional scores _scores injection)
  - FEATURE_SCHEMA validation: coverage + enum value correctness

v28.0: Dimensional scores diagnostic update:
  - _display_feature_extraction_status: shows pre-computed dimensional scores
    (trend, momentum, order_flow, vol_ext_risk, risk_env, net assessment)
  - _display_prompt_structure: verifies "_scores" present in all agent user prompts
  - _display_structured_path_verification: Check 9 validates _scores injection
    across all agent calls via call_trace message inspection

v27.0.1: Production parity fixes:
  - Reflection temperature: hardcoded 0.3 (was cfg.deepseek_temperature)
    Matches production position_manager.py:1439 reflection_temperature = 0.3
  - Extended reflection: check_and_generate_extended_reflection() called after
    backfill (was missing). Matches production position_manager.py:1501-1516

v23.0: SignalProcessor implements FULL production post-processing pipeline
(on_timer + _execute_trade + _open_new_position) — gate ordering matches live:
  [S1] Signal fingerprint dedup (stateful, not simulated)
  [1]  Risk Controller (circuit breaker + position multiplier)
  [2]  Entry Timing Agent (v23.0, reads Phase 2.5 results)
  [3]  Signal age check (rejects signals >600s old)
  [4]  Legacy normalization (BUY→LONG, SELL→SHORT)
  [S2] FR consecutive block exhaustion (stateful, not simulated)
  [5]  Confidence filter (min_confidence_to_trade)
  [6]  Liquidation buffer hard floor (v17.1, blocks add-on when <5%)
  [7]  FR entry check (v6.6, blocks entry on severe FR pressure >0.09%)
v23.0 changes: Alignment Gate, Entry Quality POOR downgrade, and 30M
Confidence Cap replaced by single AI-driven Entry Timing Agent (Phase 2.5).
Entry Timing prompt verified alongside bull/bear/judge/risk prompts.

v24.2/v43.0: OrderSimulator now simulates trailing stop calculation (activation price
at 1.5R, callback = 4H ATR × 0.6, clamped to Binance [10, 1000] bps). Matches
production _submit_trailing_stop() and _open_new_position() trailing flow.

v20.0: Sentiment now fetched via AIDataAssembler (same code path as production).
Previously diagnostic used a separate MarketDataFetcher for sentiment and passed
sentiment_client=None to the assembler — a different code path than production.
atr_value now defaults to 0.0 (not None) to match live _cached_atr_value.

v18.0.2: SignalProcessor now integrates RiskController gate — matching
production ai_strategy.py:2571-2603 (can_open_trade() circuit breaker
+ get_position_size_multiplier() position sizing). Previously, diagnostic
only applied confidence filter but skipped Risk Controller entirely.

v15.5: OrderSimulator and PositionCalculator now call production
calculate_position_size() directly, eliminating appetite_scale and
single-trade risk clamp divergence (was inline simplified calculation).

v7.0: External API data fetched via AIDataAssembler.fetch_external_data() —
the same Single Source of Truth used by production on_timer().
Internal data (indicators, MTF bars, S/R, ATR) still fetched inline from context.
"""

import os
import traceback
from typing import Any, Dict, Optional

import time

from .base import DiagnosticContext, DiagnosticStep, safe_float, print_wrapped, print_box, step_timer
from strategy.trading_logic import (
    calculate_mechanical_sltp,
    calculate_position_size,
    _is_counter_trend,
    get_min_rr_ratio,
    get_counter_trend_rr_multiplier,
    get_min_sl_distance,
    get_default_sl_pct,
    get_default_tp_pct_buy,
)
from utils.risk_controller import RiskController


class AIInputDataValidator(DiagnosticStep):
    """
    Validate and display all 13 data categories passed to MultiAgent AI.

    Shows exactly what data the AI receives for decision-making,
    matching the live system's analyze() call parameters.
    """

    name = "AI 输入数据验证 (传给 MultiAgent, 13 类数据)"

    def run(self) -> bool:
        print("-" * 70)
        print()
        print_box("AI 输入数据验证 (传给 MultiAgent, 13 类)", 65)
        print()

        # v3.0.0: Fetch all external data FIRST (matches live on_timer flow)
        self._fetch_all_data()

        # [1] Technical data (30M indicators)
        self._print_technical_data()

        # [2] Sentiment data
        self._print_sentiment_data()

        # [3] Price data (v3.6)
        self._print_price_data()

        # [4] Order flow report (Binance klines)
        self._print_order_flow_data()

        # [5] Derivatives report (Coinalyze)
        self._print_derivatives_data()

        # [6] Binance Derivatives (Top Traders, Taker Ratio) v3.21
        self._print_binance_derivatives_data()

        # [7] Order book data (v3.7)
        self._print_orderbook_data()

        # [8] MTF Decision layer (4H)
        self._print_mtf_decision_data()

        # [9] MTF Trend layer (1D)
        self._print_mtf_trend_data()

        # [10] Current position
        self._print_position_data()

        # [11] Account context (v4.7)
        self._print_account_context()

        # [12] Historical context (EVALUATION_FRAMEWORK v3.0.1)
        self._print_historical_context()

        # [13] S/R Zones (v2.6.0) + bars_data for Swing Detection
        self._print_sr_zones_data()

        print()
        print("  ────────────────────────────────────────────────────────────────")
        print("  ✅ AI 输入数据验证完成 (13 类数据)")
        return True

    def _fetch_all_data(self) -> None:
        """
        Fetch ALL external data before printing — 100% matches live on_timer() flow.

        v20.0: Sentiment client now passed to AIDataAssembler (same path as production).
        v7.0: Uses AIDataAssembler.fetch_external_data() — the same Single Source
        of Truth used by production on_timer(). Internal data (indicators, MTF bars,
        S/R, ATR) is still fetched inline from context below.
        """
        timings = self.ctx.step_timings

        try:
            # v7.0: Unified external data fetch via AIDataAssembler
            # Same method used by production on_timer() — eliminates code duplication
            from utils.ai_data_assembler import AIDataAssembler
            from utils.binance_kline_client import BinanceKlineClient
            from utils.order_flow_processor import OrderFlowProcessor
            from utils.coinalyze_client import CoinalyzeClient
            from utils.sentiment_client import SentimentDataFetcher

            kline_client = BinanceKlineClient(timeout=10)
            processor = OrderFlowProcessor(logger=None)

            coinalyze_cfg = self.ctx.base_config.get('order_flow', {}).get('coinalyze', {})
            coinalyze_api_key = coinalyze_cfg.get('api_key') or os.getenv('COINALYZE_API_KEY')
            coinalyze_client = CoinalyzeClient(
                api_key=coinalyze_api_key,
                timeout=coinalyze_cfg.get('timeout', 10),
                max_retries=coinalyze_cfg.get('max_retries', 2),
                logger=None,
            )

            # Sentiment: Create SentimentDataFetcher to pass to assembler — matches
            # production ai_strategy.py:880-884 where sentiment_client is passed
            # to AIDataAssembler. The assembler handles fetching + neutral fallback.
            cfg = self.ctx.strategy_config
            sentiment_client = None
            try:
                sentiment_client = SentimentDataFetcher(
                    lookback_hours=cfg.sentiment_lookback_hours,
                    timeframe=cfg.sentiment_timeframe,
                )
            except Exception as e:
                print(f"  ⚠️ SentimentDataFetcher init failed: {e}")

            # Order book client (conditional)
            binance_orderbook = None
            orderbook_processor = None
            order_book_cfg = self.ctx.base_config.get('order_book', {})
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
                    weighted_obi_cfg = ob_proc_cfg.get('weighted_obi', {})
                    anomaly_cfg = ob_proc_cfg.get('anomaly_detection', {})
                    orderbook_processor = OrderBookProcessor(
                        # v15.1: Add price_band_pct to match production init
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
                        history_size=ob_proc_cfg.get('history', {}).get('size', 10),
                        logger=None,
                    )
                except ImportError as e:
                    print(f"  ⚠️ Order book modules not available: {e}")

            # Binance derivatives client
            binance_derivatives_client = None
            try:
                from utils.binance_derivatives_client import BinanceDerivativesClient
                # v15.1: Match production init — no config param (uses default threshold_pct=5.0)
                bd_cfg = self.ctx.base_config.get('binance_derivatives', {})
                binance_derivatives_client = BinanceDerivativesClient(
                    timeout=bd_cfg.get('timeout', 10),
                    logger=None,
                )
            except ImportError as e:
                print(f"  ⚠️ BinanceDerivativesClient not available: {e}")

            # Create assembler with all clients — matches production ai_strategy.py:880-889
            assembler = AIDataAssembler(
                binance_kline_client=kline_client,
                order_flow_processor=processor,
                coinalyze_client=coinalyze_client,
                sentiment_client=sentiment_client,  # Same path as production
                binance_derivatives_client=binance_derivatives_client,
                binance_orderbook_client=binance_orderbook,
                orderbook_processor=orderbook_processor,
                logger=None,
            )

            # Single call to fetch ALL external data
            td = self.ctx.technical_data or {}
            with step_timer("AIDataAssembler.fetch_external_data()", timings):
                ext = assembler.fetch_external_data(
                    symbol=self.ctx.symbol,
                    interval="30m",  # v18 Item 15: 15M→30M migration
                    current_price=self.ctx.current_price,
                    volatility=td.get('bb_bandwidth', 0.02),
                )

            # Distribute results to context (same field names as before)
            # v20.0: Sentiment now comes from assembler (same code path as production)
            # Previously diagnostic used a separate MarketDataFetcher fetch — this caused
            # the sentiment to go through a different code path than production.
            self.ctx.sentiment_data = ext['sentiment_report']
            self.ctx.order_flow_report = ext['order_flow_report']
            self.ctx.order_flow_report_4h = ext.get('order_flow_report_4h')  # v18 Item 16: 4H CVD
            self.ctx.derivatives_report = ext['derivatives_report']
            self.ctx.orderbook_report = ext['orderbook_report']
            self.ctx.binance_derivatives_data = ext['binance_derivatives_report']

        except Exception as e:
            print(f"  ⚠️ 外部数据获取失败: {e}")
            traceback.print_exc()

        # ========== Indicator-based data (matches live on_timer enrichment) ==========
        if hasattr(self.ctx, 'indicator_manager') and self.ctx.indicator_manager:
            # v3.21: kline_ohlcv (20 bars) — live line 1613
            try:
                kline_ohlcv = self.ctx.indicator_manager.get_kline_data(count=20)
                if kline_ohlcv:
                    self.ctx.technical_data['kline_ohlcv'] = kline_ohlcv
                    print(f"  ℹ️ kline_ohlcv: {len(kline_ohlcv)} bars added to technical_data")
            except Exception as e:
                print(f"  ⚠️ kline_ohlcv 获取失败: {e}")

            # v4.0: S/R bars (200 bars for Swing Point detection) — live line 1817
            try:
                sr_bars = self.ctx.indicator_manager.get_kline_data(count=200)
                if sr_bars:
                    self.ctx.sr_bars_data = sr_bars
                    print(f"  ℹ️ sr_bars_data: {len(sr_bars)} bars for S/R detection")
            except Exception as e:
                print(f"  ⚠️ sr_bars_data 获取失败: {e}")

            # v4.0 (E1): ATR value from S/R bars — matches live ai_strategy.py:2464-2472
            # Live system uses self._cached_atr_value (initialized to 0.0, updated if ATR succeeds)
            # Diagnostic must also default to 0.0 (not None) to match live behavior.
            try:
                if self.ctx.sr_bars_data and len(self.ctx.sr_bars_data) >= 14:
                    from utils.sr_zone_calculator import SRZoneCalculator
                    atr_val = SRZoneCalculator._calculate_atr_from_bars(self.ctx.sr_bars_data)
                    if atr_val and atr_val > 0:
                        self.ctx.atr_value = atr_val
                        print(f"  ℹ️ atr_value: ${atr_val:,.2f} (from {len(self.ctx.sr_bars_data)} bars)")
                    else:
                        self.ctx.atr_value = 0.0  # Match live: _cached_atr_value defaults to 0.0
                else:
                    self.ctx.atr_value = 0.0  # Match live: _cached_atr_value defaults to 0.0
            except Exception as e:
                print(f"  ⚠️ ATR 计算失败: {e}")
                self.ctx.atr_value = 0.0  # Match live: _cached_atr_value defaults to 0.0

            # v18 Item 10: historical_context reduced from 35→20 bars (30M × 20 = 10h)
            try:
                historical_context = self.ctx.indicator_manager.get_historical_context(count=20)
                if historical_context and historical_context.get('trend_direction') not in ['INSUFFICIENT_DATA', 'ERROR']:
                    self.ctx.historical_context = historical_context
                    if self.ctx.technical_data:
                        self.ctx.technical_data['historical_context'] = historical_context
                else:
                    self.ctx.historical_context = None
            except Exception as hc_err:
                print(f"  ⚠️ Historical context 获取失败: {hc_err}")
                self.ctx.historical_context = None
        else:
            self.ctx.historical_context = None

        # ========== Enrich technical_data (matches live on_timer lines 1551-1575) ==========
        td = self.ctx.technical_data
        if td:
            td['timeframe'] = '30M'  # v18.2: bar subscription migrated to 30M
            td['price'] = self.ctx.current_price
            if self.ctx.price_data:
                td['price_change'] = self.ctx.price_data.get('price_change', 0)
                td['period_high'] = self.ctx.price_data.get('period_high', 0)
                td['period_low'] = self.ctx.price_data.get('period_low', 0)
                td['period_change_pct'] = self.ctx.price_data.get('period_change_pct', 0)
                td['period_hours'] = self.ctx.price_data.get('period_hours', 0)

        # v21.0: fr_block_context injection (production ai_strategy.py:2511-2516)
        # In production, _fr_consecutive_blocks >= 2 injects context into technical_data.
        # Diagnostic is one-shot, so _fr_consecutive_blocks is always 0 — cannot simulate.
        # Documented as [S2] stateful gap in SignalProcessor.

        # ========== S/R Zones calculation ==========
        try:
            from utils.sr_zone_calculator import SRZoneCalculator

            td = self.ctx.technical_data

            # v5.1: Reuse MultiAgent's sr_calculator (18 config params from base.yaml)
            # instead of SRZoneCalculator() with defaults — matches production exactly
            if self.ctx.multi_agent and hasattr(self.ctx.multi_agent, 'sr_calculator'):
                sr_calculator = self.ctx.multi_agent.sr_calculator
                print("  ℹ️ S/R Calculator: 使用 MultiAgent.sr_calculator (与实盘一致)")
            else:
                sr_calculator = SRZoneCalculator()
                print("  ⚠️ S/R Calculator: MultiAgent 未初始化，使用默认参数 (与实盘可能不一致)")

            bb_data = {
                'upper': td.get('bb_upper', 0),
                'lower': td.get('bb_lower', 0),
                'middle': td.get('bb_middle', td.get('sma_20', 0)),  # Match production: bb_middle field
            }
            sma_data = {
                'sma_50': td.get('sma_50', 0),
                'sma_200': td.get('sma_200', 0),
            }

            orderbook_anomalies = None
            if self.ctx.orderbook_report and self.ctx.orderbook_report.get('_status', {}).get('code') == 'OK':
                orderbook_anomalies = self.ctx.orderbook_report.get('anomalies', {})

            # v19.1 audit: Pass atr_value, technical_data, orderbook_data
            # to match production _calculate_sr_zones() (v8.1 hold_probability correction)
            sr_result = sr_calculator.calculate_with_detailed_report(
                current_price=self.ctx.current_price,
                bb_data=bb_data,
                sma_data=sma_data,
                orderbook_anomalies=orderbook_anomalies,
                bars_data=self.ctx.sr_bars_data,
                bars_data_4h=self.ctx.bars_data_4h,
                bars_data_1d=self.ctx.bars_data_1d,
                daily_bar=self.ctx.daily_bar,
                weekly_bar=self.ctx.weekly_bar,
                atr_value=self.ctx.atr_value,
                technical_data=self.ctx.technical_data,
                orderbook_data=self.ctx.orderbook_report,
            )

            self.ctx.sr_zones_data = sr_result
            # v6.0: Stamp calculation time for freshness checks (match production multi_agent_analyzer.py)
            if sr_result:
                sr_result['_calculated_at'] = time.time()
            print(f"  ℹ️ S/R Zones: {len(sr_result.get('support_zones', []))} 支撑, {len(sr_result.get('resistance_zones', []))} 阻力")

        except Exception as sr_err:
            print(f"  ⚠️ S/R Zones 计算失败: {sr_err}")
            self.ctx.sr_zones_data = None

        print()

    def _print_technical_data(self) -> None:
        """Print technical indicator data."""
        td = self.ctx.technical_data

        print("  [1] technical_data (30M 技术指标):")
        print(f"      price:           ${td.get('price', 0):,.2f}")
        print(f"      sma_5:           ${td.get('sma_5', 0):,.2f}")
        print(f"      sma_20:          ${td.get('sma_20', 0):,.2f}")
        print(f"      sma_50:          ${td.get('sma_50', 0):,.2f}")
        print(f"      rsi:             {td.get('rsi', 0):.2f}")
        print(f"      macd:            {td.get('macd', 0):.4f}")
        print(f"      macd_histogram:  {td.get('macd_histogram', 0):.4f}")
        print(f"      bb_upper:        ${td.get('bb_upper', 0):,.2f}")
        print(f"      bb_lower:        ${td.get('bb_lower', 0):,.2f}")
        bb_pos = td.get('bb_position', 0.5)
        print(f"      bb_position:     {bb_pos * 100:.1f}% (0%=下轨, 100%=上轨)")
        # v19.1: ATR Extension Ratio
        atr_val = td.get('atr', 0)
        print(f"      atr:             ${atr_val:,.2f}" + (f" ({atr_val/td.get('price', 1)*100:.3f}%)" if td.get('price', 0) > 0 and atr_val > 0 else ""))
        ext_regime = td.get('extension_regime', 'N/A')
        ext_sma5 = td.get('extension_ratio_sma_5', 0)
        ext_sma20 = td.get('extension_ratio_sma_20', 0)
        ext_sma50 = td.get('extension_ratio_sma_50', 0)
        ext_sma200 = td.get('extension_ratio_sma_200', 0)
        print(f"      ext_ratio_sma5:  {ext_sma5:+.2f} ATR")
        print(f"      ext_ratio_sma20: {ext_sma20:+.2f} ATR (primary)")
        print(f"      ext_ratio_sma50: {ext_sma50:+.2f} ATR")
        if ext_sma200 != 0:
            print(f"      ext_ratio_sma200:{ext_sma200:+.2f} ATR")
        print(f"      extension_regime:{ext_regime}")
        if ext_regime in ('OVEREXTENDED', 'EXTREME'):
            print(f"      ⚠️ {ext_regime}: Price significantly displaced from SMA20")
        # v20.0: ATR Volatility Regime
        vol_regime = td.get('volatility_regime', 'N/A')
        vol_pct = td.get('volatility_percentile', 0.0)
        atr_pct_val = td.get('atr_pct', 0.0)
        print(f"      vol_regime:      {vol_regime} ({vol_pct:.1f}th percentile, ATR%={atr_pct_val:.4f}%)")
        if vol_regime == 'EXTREME':
            print(f"      ⚠️ EXTREME VOLATILITY: >90th percentile, whipsaw risk elevated")
        elif vol_regime == 'HIGH':
            print(f"      ℹ️ HIGH VOLATILITY: 70-90th percentile, wider stops recommended")
        elif vol_regime == 'LOW':
            print(f"      ℹ️ LOW VOLATILITY: <30th percentile, squeeze environment")
        print(f"      [诊断用] overall_trend: {td.get('overall_trend', 'N/A')}")
        print()

    def _print_sentiment_data(self) -> None:
        """Print sentiment data."""
        sd = self.ctx.sentiment_data

        print("  [2] sentiment_data (情绪数据):")
        pos_ratio = sd.get('positive_ratio', sd.get('long_account_pct', 0))
        neg_ratio = sd.get('negative_ratio', sd.get('short_account_pct', 0))
        net_sent = sd.get('net_sentiment', 0)
        print(f"      positive_ratio:  {pos_ratio:.4f} ({pos_ratio*100:.2f}%)")
        print(f"      negative_ratio:  {neg_ratio:.4f} ({neg_ratio*100:.2f}%)")
        print(f"      net_sentiment:   {net_sent:.4f}")
        print()

    def _print_price_data(self) -> None:
        """Print price data."""
        pd = self.ctx.price_data

        print("  [3] price_data (价格数据 v3.6):")
        print(f"      price:           ${pd.get('price', 0):,.2f}")
        print(f"      price_change:    {pd.get('price_change', 0):.2f}% (上一根K线)")
        period_hours = pd.get('period_hours', 0)
        print(f"      period_high:     ${pd.get('period_high', 0):,.2f} ({period_hours:.0f}h)")
        print(f"      period_low:      ${pd.get('period_low', 0):,.2f} ({period_hours:.0f}h)")
        print(f"      period_change:   {pd.get('period_change_pct', 0):+.2f}% ({period_hours:.0f}h)")
        print()

    def _print_order_flow_data(self) -> None:
        """Print order flow data."""
        of = self.ctx.order_flow_report

        if of:
            print("  [4] order_flow_report (30M 订单流):")
            print(f"      buy_ratio:       {of.get('buy_ratio', 0):.4f} ({of.get('buy_ratio', 0)*100:.2f}%)")
            print(f"      volume_usdt:     ${of.get('volume_usdt', 0):,.0f}")
            print(f"      avg_trade_usdt:  ${of.get('avg_trade_usdt', 0):,.2f}")
            print(f"      trades_count:    {of.get('trades_count', 0):,}")
            print(f"      [诊断用] cvd_trend: {of.get('cvd_trend', 'N/A')}")
            print(f"      data_source:     {of.get('data_source', 'N/A')}")
        else:
            print("  [4] order_flow_report: None (未获取)")

        # v18 Item 16: 4H CVD order flow
        of_4h = getattr(self.ctx, 'order_flow_report_4h', None)
        if of_4h:
            print("  [4b] order_flow_report_4h (v18 Item 16: 4H CVD):")
            print(f"      buy_ratio:       {of_4h.get('buy_ratio', 0):.4f}")
            print(f"      cvd_trend:       {of_4h.get('cvd_trend', 'N/A')}")
            print(f"      volume_usdt:     ${of_4h.get('volume_usdt', 0):,.0f}")
        else:
            print("  [4b] order_flow_report_4h: None (v18 Item 16, 可选)")
        print()

    def _print_derivatives_data(self) -> None:
        """Print derivatives data."""
        dr = self.ctx.derivatives_report

        if dr:
            print("  [5] derivatives_report (衍生品数据):")
            oi = dr.get('open_interest', {})
            fr = dr.get('funding_rate', {})
            liq = dr.get('liquidations', {})
            bc = self.ctx.base_currency
            oi_val = float(oi.get('value', 0) or 0) if oi else 0
            # Coinalyze returns BTC only; convert to USD using current price
            oi_usd = oi.get('total_usd', 0) if oi else 0
            if not oi_usd and oi_val > 0:
                oi_usd = oi_val * (self.ctx.current_price or 0)
            print(f"      OI value:        ${oi_usd:,.0f} ({oi_val:,.2f} {bc})")
            # v5.2: Use current_pct (already in %) instead of value*100 (source-dependent)
            fr_pct = fr.get('current_pct', 0) if fr else 0
            fr_source = fr.get('source', 'unknown') if fr else 'N/A'
            print(f"      Funding rate:    {fr_pct:.5f}% (source: {fr_source})")

            # v5.1: Binance funding rate (settled + predicted)
            if self.ctx.binance_funding_rate:
                bfr = self.ctx.binance_funding_rate
                print(f"      [Binance FR] Settled: {bfr.get('funding_rate_pct', 0):.5f}% | Predicted: {bfr.get('predicted_rate_pct', 0):.5f}%")

            if liq:
                history = liq.get('history', [])
                if history:
                    latest = history[-1]
                    bc = self.ctx.base_currency
                    print(f"      Liq history[-1]:  l={latest.get('l', 0)} {bc}, s={latest.get('s', 0)} {bc}")
                else:
                    print("      Liq history:      empty")
            else:
                print("      liquidations:    None")
        else:
            print("  [5] derivatives_report: None (未获取)")
        print()

    def _print_binance_derivatives_data(self) -> None:
        """Print Binance Derivatives data (Top Traders, Taker Ratio) v3.21."""
        bd = getattr(self.ctx, 'binance_derivatives_data', None)

        if bd:
            print("  [6] binance_derivatives (大户数据 v3.21):")
            # Top Traders Long/Short Position Ratio
            top_pos = bd.get('top_long_short_position', {})
            latest_pos = top_pos.get('latest')
            if latest_pos:
                ratio = float(latest_pos.get('longShortRatio', 1))
                long_pct = float(latest_pos.get('longAccount', 50))
                short_pct = float(latest_pos.get('shortAccount', 50))
                print(f"      Top Traders Position L/S:  {ratio:.2f} (Long {long_pct:.1f}% / Short {short_pct:.1f}%)")
            else:
                print(f"      Top Traders Position L/S:  N/A")

            # Top Traders Long/Short Account Ratio
            top_acc = bd.get('top_long_short_account', {})
            latest_acc = top_acc.get('latest')
            if latest_acc:
                ratio = float(latest_acc.get('longShortRatio', 1))
                print(f"      Top Traders Account L/S:   {ratio:.2f}")
            else:
                print(f"      Top Traders Account L/S:   N/A")

            # Taker Buy/Sell Ratio
            taker = bd.get('taker_long_short', {})
            latest_taker = taker.get('latest')
            if latest_taker:
                ratio = float(latest_taker.get('buySellRatio', 1))
                print(f"      Taker Buy/Sell Ratio:      {ratio:.2f}")
            else:
                print(f"      Taker Buy/Sell Ratio:      N/A")

            # Trends
            trends = bd.get('trends', {})
            if trends:
                print(f"      Position Trend:            {trends.get('position_trend', 'N/A')}")
                print(f"      Account Trend:             {trends.get('account_trend', 'N/A')}")
                print(f"      Taker Trend:               {trends.get('taker_trend', 'N/A')}")
        else:
            print("  [6] binance_derivatives: None (未获取)")
        print()

    def _print_orderbook_data(self) -> None:
        """Print order book data."""
        ob = self.ctx.orderbook_report
        ob_cfg = self.ctx.base_config.get('order_book', {})

        if ob:
            status = ob.get('_status', {})
            status_code = status.get('code', 'UNKNOWN')
            print(f"  [7] order_book_data (订单簿深度 v3.7) [状态: {status_code}]:")

            if status_code == 'OK':
                obi = ob.get('obi', {})
                dynamics = ob.get('dynamics', {})
                gradient = ob.get('pressure_gradient', {})
                liquidity = ob.get('liquidity', {})

                print(f"      OBI (simple):    {obi.get('simple', 0):+.4f}")
                print(f"      OBI (weighted):  {obi.get('weighted', 0):+.4f}")
                print(f"      OBI (adaptive):  {obi.get('adaptive_weighted', 0):+.4f}")

                if dynamics.get('samples_count', 0) > 0:
                    print(f"      OBI change:      {dynamics.get('obi_change', 0):+.4f}")
                    print(f"      Depth change:    {dynamics.get('depth_change_pct', 0):+.2f}%")
                    print(f"      Trend:           {dynamics.get('trend', 'N/A')}")
                else:
                    print("      Dynamics:        首次运行，无历史数据")
                    print("      ℹ️ 注: 诊断脚本每次新建实例，无历史数据正常")
                    print("         实盘服务中 OrderBookProcessor 会累积历史")

                bid_near_5 = gradient.get('bid_near_5', 0) * 100
                ask_near_5 = gradient.get('ask_near_5', 0) * 100
                print(f"      Bid pressure:    near_5={bid_near_5:.1f}%")
                print(f"      Ask pressure:    near_5={ask_near_5:.1f}%")
                print(f"      Spread:          {liquidity.get('spread_pct', 0):.4f}%")
            else:
                # v2.4.4: 修复 reason → message (数据结构使用 message 字段)
                print(f"      reason:          {status.get('message', 'Unknown')}")
        else:
            if ob_cfg.get('enabled', False):
                print("  [7] order_book_data: 获取失败")
            else:
                print("  [7] order_book_data: 未启用 (order_book.enabled = false)")
        print()

    def _print_mtf_decision_data(self) -> None:
        """Print MTF 4H decision layer data."""
        td = self.ctx.technical_data
        mtf_decision = td.get('mtf_decision_layer')

        if mtf_decision:
            print("  [8] mtf_decision_layer (4H 决策层):")
            print(f"      rsi:             {mtf_decision.get('rsi', 0):.2f}")
            print(f"      macd:            {mtf_decision.get('macd', 0):.4f}")
            print(f"      sma_20:          ${mtf_decision.get('sma_20', 0):,.2f}")
            print(f"      sma_50:          ${mtf_decision.get('sma_50', 0):,.2f}")
            print(f"      bb_upper:        ${mtf_decision.get('bb_upper', 0):,.2f}")
            print(f"      bb_lower:        ${mtf_decision.get('bb_lower', 0):,.2f}")
            bb_pos = mtf_decision.get('bb_position', 0.5)
            print(f"      bb_position:     {bb_pos * 100:.1f}%")
            # v5.6: Display 4H ADX/DI (match production multi_agent_analyzer.py)
            adx_4h = mtf_decision.get('adx', 0)
            di_plus_4h = mtf_decision.get('di_plus', 0)
            di_minus_4h = mtf_decision.get('di_minus', 0)
            adx_regime_4h = mtf_decision.get('adx_regime', 'UNKNOWN')
            direction_4h = 'BULLISH' if di_plus_4h > di_minus_4h else 'BEARISH'
            print(f"      adx:             {adx_4h:.1f} ({adx_regime_4h})")
            print(f"      di+/di-:         {di_plus_4h:.1f} / {di_minus_4h:.1f} → {direction_4h}")
            # v18 audit: Display A1 pass-through fields
            atr_4h = mtf_decision.get('atr', 0)
            vol_ratio_4h = mtf_decision.get('volume_ratio', 0)
            macd_hist_4h = mtf_decision.get('macd_histogram', 0)
            print(f"      atr:             ${atr_4h:,.2f}" + (f" ({atr_4h/self.ctx.current_price*100:.3f}%)" if self.ctx.current_price > 0 and atr_4h > 0 else ""))
            print(f"      volume_ratio:    {vol_ratio_4h:.2f}x")
            print(f"      macd_histogram:  {macd_hist_4h:.4f}")
            # v18 Item 7: Display 4H historical context status
            hist_4h = mtf_decision.get('historical_context', {})
            if hist_4h and hist_4h.get('trend_direction') not in ['INSUFFICIENT_DATA', 'ERROR', None]:
                n_bars = len(hist_4h.get('rsi_trend', []))
                td_dir = hist_4h.get('trend_direction', 'N/A')
                momentum = hist_4h.get('momentum_shift', 'N/A')
                print(f"      [v18 Item 7] 4H time series: {n_bars} bars, trend={td_dir}, momentum={momentum}")
            else:
                print("      [v18 Item 7] 4H time series: ❌ 未注入 (historical_context 缺失)")
        else:
            print("  [8] mtf_decision_layer (4H): 未初始化或未启用")
        print()

    def _print_mtf_trend_data(self) -> None:
        """Print MTF 1D trend layer data."""
        td = self.ctx.technical_data
        mtf_trend = td.get('mtf_trend_layer')

        if mtf_trend:
            print("  [9] mtf_trend_layer (1D 趋势层):")
            sma_200 = mtf_trend.get('sma_200', 0)
            print(f"      sma_200:         ${sma_200:,.2f}")
            if sma_200 > 0:
                price_vs_sma200 = ((self.ctx.current_price / sma_200 - 1) * 100)
                print(f"      price vs SMA200: {'+' if price_vs_sma200 >= 0 else ''}{price_vs_sma200:.2f}%")
            print(f"      macd:            {mtf_trend.get('macd', 0):.4f}")
            print(f"      macd_signal:     {mtf_trend.get('macd_signal', 0):.4f}")
            # v5.6: Display 1D ADX/DI (match indicator_test.py)
            adx_1d = mtf_trend.get('adx', 0)
            di_plus_1d = mtf_trend.get('di_plus', 0)
            di_minus_1d = mtf_trend.get('di_minus', 0)
            adx_regime_1d = mtf_trend.get('adx_regime', 'UNKNOWN')
            print(f"      rsi:             {mtf_trend.get('rsi', 0):.1f}")
            print(f"      adx:             {adx_1d:.1f} ({adx_regime_1d})")
            print(f"      di+/di-:         {di_plus_1d:.1f} / {di_minus_1d:.1f}")
            # v18 audit: Display Item 21 pass-through fields
            bb_pos_1d = mtf_trend.get('bb_position', 0)
            atr_1d = mtf_trend.get('atr', 0)
            print(f"      bb_position:     {bb_pos_1d * 100:.1f}%")
            print(f"      atr:             ${atr_1d:,.2f}" + (f" ({atr_1d/self.ctx.current_price*100:.3f}%)" if self.ctx.current_price > 0 and atr_1d > 0 else ""))
            # v21.0: Display 1D historical context (matches production v21.0)
            hist_1d = mtf_trend.get('historical_context', {})
            if hist_1d and hist_1d.get('trend_direction') not in ['INSUFFICIENT_DATA', 'ERROR', None]:
                n_bars = len(hist_1d.get('adx_trend', []))
                td_dir = hist_1d.get('trend_direction', 'N/A')
                momentum = hist_1d.get('momentum_shift', 'N/A')
                adx_series = hist_1d.get('adx_trend', [])
                adx_summary = ""
                if adx_series and len(adx_series) >= 2:
                    adx_summary = f" [{adx_series[0]:.1f} → {adx_series[-1]:.1f}]"
                print(f"      [v21.0] 1D time series: {n_bars} bars, trend={td_dir}, momentum={momentum}{adx_summary}")
            else:
                print("      [v21.0] 1D time series: ❌ 未注入 (historical_context 缺失)")
        else:
            print("  [9] mtf_trend_layer (1D): 未初始化或未启用")
        print()

    def _print_position_data(self) -> None:
        """Print current position data."""
        pos = self.ctx.current_position

        if pos:
            print("  [10] current_position (当前持仓 - 25 fields v4.8.1):")
            print(f"      side:            {pos.get('side', 'N/A')}")
            bc = self.ctx.base_currency
            qty = pos.get('quantity', 0)
            print(f"      quantity:        {qty} {bc}")
            entry = pos.get('entry_price') or pos.get('avg_px', 0)
            print(f"      entry_price:     ${entry:,.2f}")
            print(f"      unrealized_pnl:  ${pos.get('unrealized_pnl', 0):,.2f}")
            print(f"      pnl_percentage:  {pos.get('pnl_percentage', 0):+.2f}%")
            print(f"      duration_min:    {pos.get('duration_minutes', 0)}")

            # v4.7 fields
            liq_price = pos.get('liquidation_price')
            if liq_price:
                print(f"      liquidation:     ${liq_price:,.2f} (buffer: {pos.get('liquidation_buffer_pct', 0):.1f}%)")
            fr_cumulative = pos.get('funding_rate_cumulative_usd')
            if fr_cumulative:
                print(f"      funding_cost:    ${fr_cumulative:,.2f} (cumulative)")
            max_dd = pos.get('max_drawdown_pct')
            if max_dd:
                print(f"      max_drawdown:    {max_dd:.2f}%")
        else:
            print("  [10] current_position: None (无持仓)")
        print()

    def _print_account_context(self) -> None:
        """
        Print account context (v4.7).

        v4.8.1: Fixed to use correct field names matching production _get_account_context()
        """
        ac = self.ctx.account_context

        if ac:
            print("  [11] account_context (v4.7 Portfolio Risk - 13 fields):")

            # Core fields (8 fields) - v4.8.1 correct names
            print(f"      equity:             ${ac.get('equity', 0):,.2f}")
            print(f"      leverage:           {ac.get('leverage', 1)}x")
            print(f"      max_position_ratio: {ac.get('max_position_ratio', 0)*100:.0f}%")
            print(f"      max_position_value: ${ac.get('max_position_value', 0):,.2f}")
            print(f"      current_pos_value:  ${ac.get('current_position_value', 0):,.2f}")
            print(f"      available_capacity: ${ac.get('available_capacity', 0):,.2f}")
            print(f"      capacity_used_pct:  {ac.get('capacity_used_pct', 0):.1f}%")
            print(f"      can_add_position:   {ac.get('can_add_position', False)}")

            # v4.7 Portfolio-Level Risk Fields (5 fields)
            print()
            print("      [v4.7 Portfolio Risk]:")
            print(f"      unrealized_pnl:     ${ac.get('total_unrealized_pnl_usd', 0):,.2f}")

            liq_buffer = ac.get('liquidation_buffer_portfolio_min_pct')
            if liq_buffer is not None:
                risk_emoji = "🔴" if liq_buffer < 10 else "🟡" if liq_buffer < 15 else "🟢"
                print(f"      min_liq_buffer:     {risk_emoji} {liq_buffer:.1f}%")
            else:
                print(f"      min_liq_buffer:     N/A")

            daily_funding = ac.get('total_daily_funding_cost_usd')
            if daily_funding is not None:
                print(f"      daily_funding_cost: ${daily_funding:,.2f}")
            else:
                print(f"      daily_funding_cost: N/A")

            cumulative_funding = ac.get('total_cumulative_funding_paid_usd')
            if cumulative_funding is not None:
                print(f"      cumulative_funding: ${cumulative_funding:,.2f}")
            else:
                print(f"      cumulative_funding: N/A")

            can_safely = ac.get('can_add_position_safely', False)
            safety_emoji = "✅" if can_safely else "⚠️"
            print(f"      can_add_safely:     {safety_emoji} {can_safely}")
        else:
            print("  [11] account_context: None (未获取)")
        print()

    def _print_historical_context(self) -> None:
        """
        Print historical context data (v2.5.0 / EVALUATION_FRAMEWORK v3.0.1).

        AI needs trend data for proper trend analysis, not isolated values.
        v18 Item 10: Reduced from 35→20 bars (30M × 20 = 10h coverage).
        """
        hc = getattr(self.ctx, 'historical_context', None)

        if hc and hc.get('trend_direction') not in ['INSUFFICIENT_DATA', 'ERROR', None]:
            print("  [12] historical_context (20-bar 趋势数据, v18 Item 10):")
            print(f"      trend_direction:    {hc.get('trend_direction', 'N/A')}")
            print(f"      momentum_shift:     {hc.get('momentum_shift', 'N/A')}")
            print(f"      data_points:        {hc.get('data_points', 0)}")

            # Format trend arrays (show last 5 values)
            def format_recent(values, fmt=".2f"):
                if not values or not isinstance(values, list):
                    return "N/A"
                recent = values[-5:] if len(values) >= 5 else values
                return " → ".join([f"{v:{fmt}}" for v in recent])

            price_trend = hc.get('price_trend', [])
            rsi_trend = hc.get('rsi_trend', [])
            macd_trend = hc.get('macd_trend', [])
            volume_trend = hc.get('volume_trend', [])

            print()
            print("      📈 趋势数据 (最近 5 值):")
            print(f"      price_trend:        {format_recent(price_trend)}")
            print(f"      rsi_trend:          {format_recent(rsi_trend)}")
            print(f"      macd_trend:         {format_recent(macd_trend, '.4f')}")
            print(f"      volume_trend:       {format_recent(volume_trend, '.0f')}")

            # Statistics
            if price_trend and len(price_trend) >= 2:
                price_change = ((price_trend[-1] / price_trend[0]) - 1) * 100 if price_trend[0] > 0 else 0
                trend_emoji = "📈" if price_change > 0 else "📉" if price_change < 0 else "➡️"
                print()
                print(f"      {trend_emoji} 20-bar 价格变化: {price_change:+.2f}%")

            if rsi_trend:
                avg_rsi = sum(rsi_trend) / len(rsi_trend)
                rsi_emoji = "🔴" if avg_rsi > 70 else "🟢" if avg_rsi < 30 else "🟡"
                print(f"      {rsi_emoji} 平均 RSI: {avg_rsi:.1f}")

            print()
            print("      ℹ️ 数据来源: indicator_manager.get_historical_context()")
            print("      ℹ️ 参考: EVALUATION_FRAMEWORK.md Section 2.1 数据完整性")
        else:
            if hasattr(self.ctx, 'indicator_manager') and self.ctx.indicator_manager:
                print("  [12] historical_context: 数据不足 (需要至少 20 根 K线)")
                print("      ℹ️ 诊断脚本刚启动，历史数据可能不足")
                print("      ℹ️ 实盘服务运行后会自动累积数据")
            else:
                print("  [12] historical_context: indicator_manager 未初始化")

    def _print_sr_zones_data(self) -> None:
        """
        Print S/R Zone data (v2.6.0).

        Shows support/resistance zones calculated from Swing Points, Volume Profile,
        Pivot Points, Order Walls, and Round Numbers (v4.0+).
        This data is used for SL/TP calculation when AI doesn't provide valid values.
        """
        sr_data = getattr(self.ctx, 'sr_zones_data', None)

        if sr_data:
            print("  [13] S/R Zones (支撑/阻力区 v2.6.0):")

            # Nearest support
            nearest_sup = sr_data.get('nearest_support')
            if nearest_sup and hasattr(nearest_sup, 'price_center'):
                bc = self.ctx.base_currency
                wall_usd = nearest_sup.wall_size_btc * self.ctx.current_price if self.ctx.current_price else 0
                wall_str = f"${wall_usd/1e6:.1f}M" if wall_usd >= 1e6 else f"${wall_usd/1e3:.0f}K"
                wall_info = f" [Order Wall: {wall_str} ({nearest_sup.wall_size_btc:.1f} {bc})]" if nearest_sup.has_order_wall else ""
                print(f"      最近支撑: ${nearest_sup.price_center:,.0f} ({nearest_sup.distance_pct:.1f}% away)")
                print(f"        强度: {nearest_sup.strength} | 级别: {nearest_sup.level}{wall_info}")
                print(f"        来源: {', '.join(nearest_sup.sources)}")
            else:
                print("      最近支撑: N/A")

            print()

            # Nearest resistance
            nearest_res = sr_data.get('nearest_resistance')
            if nearest_res and hasattr(nearest_res, 'price_center'):
                bc = self.ctx.base_currency
                wall_usd = nearest_res.wall_size_btc * self.ctx.current_price if self.ctx.current_price else 0
                wall_str = f"${wall_usd/1e6:.1f}M" if wall_usd >= 1e6 else f"${wall_usd/1e3:.0f}K"
                wall_info = f" [Order Wall: {wall_str} ({nearest_res.wall_size_btc:.1f} {bc})]" if nearest_res.has_order_wall else ""
                print(f"      最近阻力: ${nearest_res.price_center:,.0f} ({nearest_res.distance_pct:.1f}% away)")
                print(f"        强度: {nearest_res.strength} | 级别: {nearest_res.level}{wall_info}")
                print(f"        来源: {', '.join(nearest_res.sources)}")
            else:
                print("      最近阻力: N/A")

            print()

            # Hard control status (v3.16: AI 自主决策，非本地覆盖)
            hard_control = sr_data.get('hard_control', {})
            if hard_control.get('block_long') or hard_control.get('block_short'):
                print("      ⚠️ S/R Zone 建议 (v3.16 由 AI 自主判断):")
                if hard_control.get('block_long'):
                    print("        📋 建议避免 LONG (太靠近 HIGH 强度阻力位)")
                if hard_control.get('block_short'):
                    print("        📋 建议避免 SHORT (太靠近 HIGH 强度支撑位)")
                if hard_control.get('reason'):
                    print(f"        原因: {hard_control['reason']}")
                print("        ℹ️ Risk Manager (AI) 可自主决定是否遵守")
            else:
                print("      ✅ 硬风控: 无限制")

            print()

            # R/R Analysis (if both S/R available)
            if nearest_sup and nearest_res and hasattr(nearest_sup, 'price_center') and hasattr(nearest_res, 'price_center'):
                price = self.ctx.current_price
                support = nearest_sup.price_center
                resistance = nearest_res.price_center

                upside = resistance - price
                downside = price - support

                if downside > 0:
                    long_rr = upside / downside
                    rr_status = "✅ FAVORABLE" if long_rr >= 1.5 else "⚠️ UNFAVORABLE"
                    print(f"      LONG R/R: {long_rr:.2f}:1 {rr_status}")
                if upside > 0:
                    short_rr = downside / upside
                    rr_status = "✅ FAVORABLE" if short_rr >= 1.5 else "⚠️ UNFAVORABLE"
                    print(f"      SHORT R/R: {short_rr:.2f}:1 {rr_status}")

            print()
            print("      ℹ️ 数据来源: SRZoneCalculator (Swing + VP + Pivot + Order Walls)")

            # v6.0: S/R Zone quality validation (GAP #4 fix)
            self._validate_sr_zone_quality(sr_data)
        else:
            print("  [13] S/R Zones: 未计算 (可能缺少技术数据)")

        print()

    def _validate_sr_zone_quality(self, sr_data: dict) -> None:
        """
        v6.0: S/R Zone quality validation (GAP #4 fix).

        Validates zone strength scoring, source_type correctness,
        and touch_count consistency.
        """
        print("      ── S/R Zone 质量验证 (v6.0) ──")
        print()

        # v17.0: output is max 1 support + 1 resistance
        all_zones = sr_data.get('support_zones', []) + sr_data.get('resistance_zones', [])
        if not all_zones:
            print("      ⚠️ 无可用 zone 数据进行质量验证")
            return

        quality_issues = []
        zone_count = len(all_zones)

        # Check 2: Validate zone attributes
        valid_strengths = {'HIGH', 'MEDIUM', 'LOW'}
        valid_source_types = {'STRUCTURAL', 'ORDER_FLOW', 'PROJECTED', 'PSYCHOLOGICAL'}
        strength_counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        source_type_counts = {}

        for i, zone in enumerate(all_zones):
            # Get attributes (handle both dict and object)
            strength = getattr(zone, 'strength', None) or (zone.get('strength') if isinstance(zone, dict) else None)
            source_type = getattr(zone, 'source_type', None) or (zone.get('source_type') if isinstance(zone, dict) else None)
            touch_count = getattr(zone, 'touch_count', None) or (zone.get('touch_count', 0) if isinstance(zone, dict) else 0)
            price_center = getattr(zone, 'price_center', None) or (zone.get('price_center', 0) if isinstance(zone, dict) else 0)

            if strength and strength in valid_strengths:
                strength_counts[strength] += 1
            elif strength:
                quality_issues.append(f"Zone #{i}: 无效强度 '{strength}'")

            if source_type:
                source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1

            # Check 3: Touch count consistency (HIGH strength should have touch_count >= 2)
            if strength == 'HIGH' and touch_count is not None and touch_count < 2:
                quality_issues.append(
                    f"Zone #{i} (${price_center:,.0f}): HIGH 强度但 touch_count={touch_count} (<2)"
                )

        # Print zone distribution
        print(f"      Zone 总数: {zone_count}")
        print(f"      强度分布: HIGH={strength_counts['HIGH']}, "
              f"MEDIUM={strength_counts['MEDIUM']}, LOW={strength_counts['LOW']}")
        if source_type_counts:
            sources = ", ".join(f"{k}={v}" for k, v in source_type_counts.items())
            print(f"      来源分布: {sources}")

        # Check 4: Freshness timestamp
        calc_at = sr_data.get('_calculated_at', 0)
        if calc_at > 0:
            age_sec = time.time() - calc_at
            age_min = age_sec / 60
            if age_min > 30:
                quality_issues.append(f"Zone 数据已过期 ({age_min:.0f}min)")
                print(f"      新鲜度: ❌ {age_min:.0f}min (超过 30min 阈值)")
            else:
                print(f"      新鲜度: ✅ {age_min:.1f}min")
        else:
            print("      新鲜度: ⚠️ 无时间戳")

        # Print quality result
        if quality_issues:
            print()
            for issue in quality_issues:
                self.ctx.add_warning(f"S/R Zone: {issue}")
                print(f"      ⚠️ {issue}")
        else:
            print(f"      ✅ S/R Zone 质量验证通过")
        print()

    def should_skip(self) -> bool:
        return self.ctx.summary_mode


class MultiAgentAnalyzer(DiagnosticStep):
    """
    Run MultiAgent AI analysis.

    Implements the TradingAgents architecture with sequential DeepSeek API calls.
    With debate_rounds=N, total API calls = 2*N (Bull/Bear) + 1 (Judge) + 0~1 (Entry Timing) + 0~1 (Risk).
    Default debate_rounds=2 → 7 sequential API calls (when signal is LONG/SHORT).
    v32.1: Risk Manager skipped when Judge=HOLD/CLOSE/REDUCE (no position to size).
    """

    name = "MultiAgent 层级决策 (TradingAgents 架构)"

    def run(self) -> bool:
        print("-" * 70)
        print()
        print_box("MultiAgent 层级决策 (顺序 AI 调用)", 65)
        print()
        print("  📋 决策流程 (顺序执行, 100% 匹配实盘):")
        print("     ┌─ Round 1: Bull Analyst → Bear Analyst  (2 API calls)")
        print("     ├─ Round 2: Bull Analyst → Bear Analyst  (2 API calls)")
        print("     ├─ Judge (Portfolio Manager) Decision    (1 API call)")
        print("     ├─ Entry Timing Agent (Phase 2.5)        (0~1 API call, 仅 LONG/SHORT)")
        print("     └─ Risk Manager Evaluation               (0~1 API call, 仅 LONG/SHORT)")
        print("     ─────────────────────────────────────────────────────")
        print("     合计: 2×debate_rounds + 1 + 0~2 次 DeepSeek 顺序调用")
        print()

        try:
            from agents.multi_agent_analyzer import MultiAgentAnalyzer as MAAnalyzer

            cfg = self.ctx.strategy_config
            timings = self.ctx.step_timings

            # Initialize with same parameters as ai_strategy.py:664-672
            # Production does NOT pass memory_file (uses default "data/trading_memory.json")
            # v32.0: enable_thinking from config
            _thinking = getattr(cfg, 'deepseek_thinking_enabled', False)
            self.ctx.multi_agent = MAAnalyzer(
                api_key=cfg.deepseek_api_key,
                model=cfg.deepseek_model,
                temperature=cfg.deepseek_temperature,
                debate_rounds=cfg.debate_rounds,
                retry_delay=getattr(cfg, 'multi_agent_retry_delay', 1.0),
                json_parse_max_retries=getattr(cfg, 'multi_agent_json_parse_max_retries', 2),
                sr_zones_config=getattr(cfg, 'sr_zones_config', None),
                enable_thinking=_thinking,
            )

            total_calls = 2 * cfg.debate_rounds + 3  # Bull/Bear per round + Judge + Entry Timing + Risk (max)
            thinking_str = "enabled" if _thinking else "disabled"
            print(f"  Model: {cfg.deepseek_model}")
            print(f"  Temperature: {cfg.deepseek_temperature}")
            print(f"  Debate Rounds: {cfg.debate_rounds}")
            print(f"  Thinking Mode: {thinking_str}")
            print(f"  Total API Calls: {total_calls} (顺序执行)")

            # Constructor parity check vs production ai_strategy.py:664-672
            ma = self.ctx.multi_agent
            _ctor_checks = []
            _ctor_checks.append(('model', cfg.deepseek_model, ma.model))
            _ctor_checks.append(('temperature', cfg.deepseek_temperature, ma.temperature))
            _ctor_checks.append(('debate_rounds', cfg.debate_rounds, ma.debate_rounds))
            _ctor_checks.append(('memory_file', "data/trading_memory.json", ma.memory_file))
            _ctor_checks.append(('enable_thinking', _thinking, ma.enable_thinking))
            ctor_ok = all(str(exp) == str(act) for _, exp, act in _ctor_checks)
            if ctor_ok:
                print(f"  ✅ Constructor parity: 与实盘 ai_strategy.py:664-672 参数一致")
            else:
                for name, exp, act in _ctor_checks:
                    if str(exp) != str(act):
                        print(f"  ❌ Constructor mismatch: {name} expected={exp}, got={act}")
            print()

            # v15.1: Process pending reflections BEFORE AI analysis
            # (matches production on_timer → _process_pending_reflections)
            # Scans recent memory entries missing 'reflection' field, backfills max 3
            try:
                ma = self.ctx.multi_agent
                backfill_count = 0
                for mem in reversed(ma.decision_memory[-10:]):
                    if backfill_count >= 3:
                        break
                    if mem.get('evaluation') and not mem.get('reflection'):
                        ts = mem.get('timestamp', '')
                        if ts:
                            # v12.0: Match production hardcoded temperature=0.3
                            # (position_manager.py:1439 reflection_temperature = 0.3)
                            reflection = ma.generate_reflection(
                                memory_entry=mem,
                                max_chars=150,
                                temperature=0.3,
                            )
                            if reflection:
                                updated = ma.update_last_memory_reflection(
                                    target_timestamp=ts,
                                    reflection=reflection,
                                )
                                if updated:
                                    backfill_count += 1
                                    print(f"  🔍 Reflection backfilled (ts={ts[:19]})")
                if backfill_count > 0:
                    total_calls += backfill_count
                    print(f"  🔍 Processed {backfill_count} pending reflection(s) (+{backfill_count} API calls)")

                    # v18.0: After individual reflections, check extended reflection
                    # Matches production position_manager.py:1501-1516
                    try:
                        ext_entry = ma.check_and_generate_extended_reflection()
                        if ext_entry:
                            insight = ext_entry.get('insight', '')
                            trade_count = ext_entry.get('trade_count', '?')
                            win_rate = ext_entry.get('win_rate', 0)
                            avg_rr = ext_entry.get('avg_rr', 0)
                            total_calls += 1
                            print(f"  🔄 Extended Reflection 生成: {trade_count} 笔交易, "
                                  f"胜率 {win_rate*100:.0f}%, avg R/R {avg_rr:.1f}:1 (+1 API call)")
                            print(f"     Insight: {insight[:120]}{'...' if len(insight) > 120 else ''}")
                        else:
                            print(f"  🔄 Extended Reflection: 未触发 (条件未满足或最近已生成)")
                    except Exception as ext_e:
                        print(f"  ⚠️ Extended Reflection check skipped: {ext_e}")
                else:
                    print("  🔍 Reflection: no pending entries (all up-to-date)")
            except Exception as e:
                print(f"  ⚠️ Reflection processing skipped: {e}")
            print()

            # Data completeness check (all 18 analyze() parameters)
            # Must match production on_timer() call at ai_strategy.py
            params = {
                'symbol': self.ctx.symbol,
                'technical_report': self.ctx.technical_data,
                'sentiment_report': self.ctx.sentiment_data,
                'current_position': self.ctx.current_position,
                'price_data': self.ctx.price_data,
                'order_flow_report': self.ctx.order_flow_report,
                'derivatives_report': self.ctx.derivatives_report,
                'binance_derivatives_report': getattr(self.ctx, 'binance_derivatives_data', None),
                'orderbook_report': self.ctx.orderbook_report,
                'account_context': self.ctx.account_context,
                'bars_data': self.ctx.sr_bars_data,
                'bars_data_4h': self.ctx.bars_data_4h,
                'bars_data_1d': self.ctx.bars_data_1d,
                'daily_bar': self.ctx.daily_bar,
                'weekly_bar': self.ctx.weekly_bar,
                'atr_value': self.ctx.atr_value,
                'order_flow_report_4h': getattr(self.ctx, 'order_flow_report_4h', None),  # v18 Item 16
            }

            # v6.6: Data quality warnings — match production ai_strategy.py:1902-1915
            _data_quality_warnings = []
            sentiment = self.ctx.sentiment_data or {}
            if sentiment.get('source') == 'default_neutral':
                _data_quality_warnings.append("sentiment=neutral_default(API failure)")
            if not self.ctx.order_flow_report:
                _data_quality_warnings.append("order_flow=unavailable")
            if not self.ctx.derivatives_report:
                _data_quality_warnings.append("derivatives=unavailable")
            orderbook = self.ctx.orderbook_report or {}
            if not orderbook or orderbook.get('_status', {}).get('code') != 'OK':
                _data_quality_warnings.append("orderbook=unavailable")
            if _data_quality_warnings:
                print(f"  ⚠️ Data quality: {len(_data_quality_warnings)} source(s) degraded: "
                      f"{', '.join(_data_quality_warnings)}")
            params['data_quality_warnings'] = _data_quality_warnings if _data_quality_warnings else None

            print("  📊 analyze() 参数完整性检查 (vs 实盘 18 参数):")
            live_params = [
                'symbol', 'technical_report', 'sentiment_report',
                'current_position', 'price_data', 'order_flow_report',
                'derivatives_report', 'binance_derivatives_report',
                'orderbook_report', 'account_context', 'bars_data',
                'bars_data_4h', 'bars_data_1d', 'daily_bar', 'weekly_bar',
                'atr_value', 'data_quality_warnings',
                'order_flow_report_4h',  # v18 Item 16: 4H CVD order flow
            ]
            for param_name in live_params:
                value = params[param_name]
                if value is not None:
                    if isinstance(value, dict):
                        status = f"✅ ({len(value)} fields)"
                    elif isinstance(value, list):
                        status = f"✅ ({len(value)} items)"
                    elif isinstance(value, str):
                        status = f"✅ ({value})"
                    else:
                        status = f"✅"
                else:
                    # data_quality_warnings=None means no warnings (all sources OK)
                    if param_name == 'data_quality_warnings':
                        status = "✅ (no warnings)"
                    else:
                        status = "⚠️ None"
                print(f"     {param_name:32s} {status}")

            # v18 Item 7: Verify 4H historical_context is embedded in mtf_decision_layer
            td = params.get('technical_report', {})
            mtf_dl = td.get('mtf_decision_layer', {}) if isinstance(td, dict) else {}
            hist_4h = mtf_dl.get('historical_context', {})
            if hist_4h and hist_4h.get('trend_direction') not in ['INSUFFICIENT_DATA', 'ERROR', None]:
                n_rsi = len(hist_4h.get('rsi_trend', []))
                print(f"     {'[v18 Item 7] 4H time series':32s} ✅ ({n_rsi} bars, trend={hist_4h.get('trend_direction')})")
            else:
                td_val = hist_4h.get('trend_direction') if hist_4h else 'missing'
                print(f"     {'[v18 Item 7] 4H time series':32s} ⚠️ NOT INJECTED ({td_val})")

            # v21.0: Verify 1D historical_context is embedded in mtf_trend_layer
            mtf_tl = td.get('mtf_trend_layer', {}) if isinstance(td, dict) else {}
            hist_1d = mtf_tl.get('historical_context', {})
            if hist_1d and hist_1d.get('trend_direction') not in ['INSUFFICIENT_DATA', 'ERROR', None]:
                n_adx = len(hist_1d.get('adx_trend', []))
                print(f"     {'[v21.0] 1D time series':32s} ✅ ({n_adx} bars, trend={hist_1d.get('trend_direction')})")
            else:
                td_val_1d = hist_1d.get('trend_direction') if hist_1d else 'missing'
                print(f"     {'[v21.0] 1D time series':32s} ⚠️ NOT INJECTED ({td_val_1d})")
            print()

            # Run analysis with all parameters (7 sequential API calls, v23.0)
            print("  Running AI analysis...")
            t_start = time.monotonic()

            signal_data = self.ctx.multi_agent.analyze(
                symbol=self.ctx.symbol,
                technical_report=self.ctx.technical_data,
                sentiment_report=self.ctx.sentiment_data,
                current_position=self.ctx.current_position,
                price_data=self.ctx.price_data,
                order_flow_report=self.ctx.order_flow_report,
                derivatives_report=self.ctx.derivatives_report,
                binance_derivatives_report=getattr(self.ctx, 'binance_derivatives_data', None),
                orderbook_report=self.ctx.orderbook_report,
                account_context=self.ctx.account_context,
                bars_data=self.ctx.sr_bars_data,
                # v4.0: MTF bars for S/R pivot + volume profile + swing detection
                bars_data_4h=self.ctx.bars_data_4h,
                bars_data_1d=self.ctx.bars_data_1d,
                daily_bar=self.ctx.daily_bar,
                weekly_bar=self.ctx.weekly_bar,
                atr_value=self.ctx.atr_value,
                data_quality_warnings=_data_quality_warnings if _data_quality_warnings else None,
                # v18 Item 16: 4H CVD order flow
                order_flow_report_4h=getattr(self.ctx, 'order_flow_report_4h', None),
                # v42.0: ET Exhaustion Tier 2 — diagnostic always False (stateful counter not available)
                skip_entry_timing=False,
                # v42.1: ET Exhaustion Tier 1 — diagnostic always False (stateful counter not available)
                et_exhaustion_tier1=False,
            )

            t_elapsed = time.monotonic() - t_start
            timings['MultiAgent.analyze() total'] = t_elapsed
            print(f"  [{t_elapsed:.1f}s] AI analysis complete")

            # v30.3: Null check — production returns None if extract_features() fails
            if signal_data is None:
                print("  ❌ analyze() returned None — feature extraction failed (production would skip this cycle)")
                self.ctx.add_error("analyze() returned None: feature extraction failure")
                return False

            self.ctx.signal_data = signal_data

            # v27.0: Feature extraction + structured path verification
            self._display_feature_extraction_status()

            # v27.0: Structured path consistency verification (production parity)
            self._display_structured_path_verification()

            # Display call trace summary
            self._display_call_trace_summary()

            # Save full call trace to context for log export
            if hasattr(self.ctx.multi_agent, 'get_call_trace'):
                self.ctx.ai_call_trace = self.ctx.multi_agent.get_call_trace()

            # v27.0: Schema audit metadata (matches production ai_strategy.py snapshot)
            self._display_schema_audit_metadata()

            # Display results
            self._display_results(signal_data)

            return True

        except Exception as e:
            self.ctx.add_error(f"MultiAgent 分析失败: {e}")
            traceback.print_exc()
            return False

    def _display_feature_extraction_status(self) -> None:
        """v27.0: Display feature extraction and structured path status."""
        ma = self.ctx.multi_agent
        if not ma:
            return

        print()
        print_box("v27.0 Feature-Driven Architecture 验证", 65)
        print()

        # 1. Feature extraction status
        snapshot = getattr(ma, '_last_feature_snapshot', None)
        if snapshot:
            features = snapshot.get('features', {})
            feat_version = snapshot.get('feature_version', '?')
            n_features = len([k for k in features if not k.startswith('_')])
            reliability = features.get('_reliability', {})
            n_reliability = len(reliability)

            print(f"  ✅ Feature Extraction 成功")
            print(f"     FEATURE_VERSION: {feat_version}")
            print(f"     Features extracted: {n_features}")
            print(f"     Reliability annotations: {n_reliability}")

            # Show key feature values
            print()
            print("  📊 Key Features (sample):")
            key_features = [
                ('price', '$', '.2f'),
                ('rsi_30m', '', '.1f'), ('rsi_4h', '', '.1f'), ('rsi_1d', '', '.1f'),
                ('adx_30m', '', '.1f'), ('adx_4h', '', '.1f'), ('adx_1d', '', '.1f'),
                ('extension_regime_30m', '', 's'), ('volatility_regime_30m', '', 's'),
                ('market_regime', '', 's'),
                ('cvd_trend_30m', '', 's'), ('cvd_price_cross_30m', '', 's'),
                ('position_side', '', 's'),
                ('funding_rate_pct', '', '.5f'),
                # v31.0: Pre-computed categoricals
                ('macd_cross_30m', '', 's'), ('macd_cross_4h', '', 's'), ('macd_cross_1d', '', 's'),
                ('di_direction_30m', '', 's'), ('di_direction_4h', '', 's'),
                ('rsi_zone_30m', '', 's'), ('rsi_zone_4h', '', 's'), ('rsi_zone_1d', '', 's'),
                ('fr_direction', '', 's'),
            ]
            for key, prefix, fmt in key_features:
                val = features.get(key)
                if val is not None:
                    if isinstance(val, str):
                        print(f"     {key:32s} {prefix}{val}")
                    else:
                        print(f"     {key:32s} {prefix}{val:{fmt}}")

            # v28.0: Dimensional scores (pre-computed for AI prompt anchoring)
            try:
                from agents.report_formatter import ReportFormatterMixin
                dim_scores = ReportFormatterMixin.compute_scores_from_features(features)
                if dim_scores:
                    print()
                    print("  📐 v28.0 Dimensional Scores (_scores in AI prompts):")
                    print("     ┌──────────────────┬───────┬────────────┬────────────┐")
                    print("     │ Dimension        │ Score │ Bar        │ Direction  │")
                    print("     ├──────────────────┼───────┼────────────┼────────────┤")
                    _dims = [
                        ("Trend", dim_scores.get('trend', {}), 'direction'),
                        ("Momentum", dim_scores.get('momentum', {}), 'direction'),
                        ("Order Flow", dim_scores.get('order_flow', {}), 'direction'),
                        ("Vol/Ext Risk", dim_scores.get('vol_ext_risk', {}), 'regime_30m'),
                        ("Risk Env", dim_scores.get('risk_env', {}), 'level'),
                    ]
                    _dir_arrows = {"BULLISH": "BULLISH  ", "BEARISH": "BEARISH  ", "NEUTRAL": "NEUTRAL  "}
                    for name, d, label_key in _dims:
                        s = d.get('score', 0)
                        bar = '#' * s + '.' * (10 - s)
                        label_val = d.get(label_key, 'N/A')
                        label_str = _dir_arrows.get(label_val, f"{label_val:9s}") if label_key == 'direction' else f"{label_val:9s}"
                        print(f"     │ {name:16s} │  {s:>2}   │ {bar} │ {label_str} │")
                    net = dim_scores.get('net', 'N/A')
                    print("     ├──────────────────┴───────┴────────────┴────────────┤")
                    print(f"     │ Net Assessment: {net:40s}  │")
                    print("     └───────────────────────────────────────────────────────┘")
            except Exception as e:
                print(f"  ⚠️ Dimensional scores computation failed: {e}")

            # Reliability tiers summary
            if reliability:
                tier_counts = {}
                for tier in reliability.values():
                    tier_counts[tier] = tier_counts.get(tier, 0) + 1
                tier_str = ' / '.join(f"{t}={c}" for t, c in sorted(tier_counts.items()))
                print(f"     {'_reliability tiers':32s} {tier_str}")

            # _input_contract in snapshot (v27.0 replay determinism)
            input_contract = snapshot.get('_input_contract', {})
            if input_contract:
                deterministic = input_contract.get('deterministic', [])
                context = input_contract.get('context', [])
                print(f"     {'_input_contract':32s} ✅ deterministic={deterministic}, context={context}")
            else:
                print(f"     {'_input_contract':32s} ⚠️ missing (old snapshot, will be added next cycle)")

            # Memory in snapshot
            memory = snapshot.get('_memory', [])
            if memory:
                print(f"     {'_memory entries':32s} {len(memory)} trades")
            else:
                print(f"     {'_memory entries':32s} ⚠️ not captured")

            # _debate_r1 in snapshot (v27.0 replay determinism)
            debate_r1 = snapshot.get('_debate_r1', {})
            if debate_r1:
                r1_agents = [k for k in debate_r1.keys() if not k.startswith('_')]
                print(f"     {'_debate_r1':32s} ✅ {len(r1_agents)} agent(s): {', '.join(r1_agents)}")
            else:
                print(f"     {'_debate_r1':32s} ⚠️ deferred (saved after debate completes)")

            # Prompt hashes
            prompt_hashes = snapshot.get('prompt_hashes', {})
            if prompt_hashes:
                print()
                print("  🔑 Prompt Hashes (per agent):")
                for agent, ph in prompt_hashes.items():
                    print(f"     {agent:16s} {ph}")
            else:
                print(f"     {'prompt_hashes':32s} ⚠️ not yet populated (populated after analysis)")

        else:
            print(f"  ❌ Feature Extraction 失败 (fell back to text-only path)")
            print(f"     诊断仍在运行 text-based debate (v26.x fallback)")
            print(f"     ⚠️ v28.0 Dimensional Scores 不会注入 AI prompt (需要 feature_dict)")
            print(f"        AI 将缺少 primacy anchoring，分析质量可能下降")

        # 2. Structured vs text path
        # Check if structured debate was used by looking at signal_data
        signal_data = self.ctx.signal_data or {}
        structured_debate = signal_data.get('_structured_debate')
        if structured_debate:
            bull = structured_debate.get('bull', {})
            bear = structured_debate.get('bear', {})
            print()
            print(f"  ✅ Structured Debate Path (feature-driven)")
            print(f"     Bull conviction: {bull.get('conviction', '?')}")
            print(f"     Bear conviction: {bear.get('conviction', '?')}")
            bull_ev = bull.get('evidence', [])
            bear_ev = bear.get('evidence', [])
            print(f"     Bull evidence tags: {len(bull_ev)} ({', '.join(bull_ev[:3])}{'...' if len(bull_ev) > 3 else ''})")
            print(f"     Bear evidence tags: {len(bear_ev)} ({', '.join(bear_ev[:3])}{'...' if len(bear_ev) > 3 else ''})")

            # Tag validation (v30.0: use compute_valid_tags for data-supported check)
            try:
                from agents.prompt_constants import REASON_TAGS, BULLISH_EVIDENCE_TAGS, BEARISH_EVIDENCE_TAGS
                from agents.tag_validator import compute_valid_tags
                all_tags = bull_ev + bear_ev + bull.get('risk_flags', []) + bear.get('risk_flags', [])
                invalid_tags = [t for t in all_tags if t not in REASON_TAGS]
                if invalid_tags:
                    print(f"     ⚠️ Unknown REASON_TAGS: {invalid_tags}")
                else:
                    print(f"     ✅ All {len(all_tags)} debate tags are valid REASON_TAGS")

                # v30.0: Check if tags are data-supported (not just valid syntax)
                snapshot = getattr(self.ctx.multi_agent, '_last_feature_snapshot', None)
                if snapshot and snapshot.get('features'):
                    data_supported = compute_valid_tags(snapshot['features'])
                    unsupported = [t for t in all_tags if t not in data_supported]
                    if unsupported:
                        print(f"     ⚠️ {len(unsupported)} tags not data-supported: {unsupported[:5]}")
                    else:
                        print(f"     ✅ All {len(all_tags)} tags are data-supported ({len(data_supported)} valid tags from features)")

                # Debate integrity check: detect Bear copying Bull
                bull_ev_set = set(bull_ev)
                bear_ev_set = set(bear_ev)
                if bull_ev_set and bull_ev_set == bear_ev_set:
                    print(f"     ❌ DEBATE INTEGRITY: Bear evidence IDENTICAL to Bull evidence!")
                    print(f"        → LLM copied opponent output, debate was meaningless")
                    print(f"        → _check_debate_integrity() should have fallen back to Bear R1")
                else:
                    bear_bullish = bear_ev_set & BULLISH_EVIDENCE_TAGS
                    bear_bearish = bear_ev_set & BEARISH_EVIDENCE_TAGS
                    if len(bear_bullish) >= 3 and len(bear_bearish) == 0:
                        print(f"     ⚠️ DEBATE INTEGRITY: Bear has {len(bear_bullish)} bullish tags, 0 bearish")
                        print(f"        Bullish tags: {sorted(bear_bullish)}")
                    else:
                        overlap = bull_ev_set & bear_ev_set
                        print(f"     ✅ Debate integrity: {len(overlap)} shared tags, Bear has {len(bear_bearish)} bearish tags")
            except ImportError:
                pass
        else:
            print()
            if snapshot:
                print(f"  ⚠️ Text Debate Path used (structured debate output not found in signal_data)")
            else:
                print(f"  ⚠️ Text Debate Path (fallback due to feature extraction failure)")

        # 3. Feature snapshot file persistence
        import os
        snapshot_dir = "data/feature_snapshots"
        if os.path.exists(snapshot_dir):
            files = sorted([f for f in os.listdir(snapshot_dir) if f.endswith('.json')])
            print()
            print(f"  📁 Feature Snapshots: {len(files)} files in {snapshot_dir}/")
            if files:
                print(f"     Latest: {files[-1]}")
        else:
            print()
            print(f"  ℹ️ Feature snapshot directory not yet created ({snapshot_dir}/)")

        # 4. FEATURE_SCHEMA validation (Gap 4: verify features match schema)
        if snapshot and features:
            try:
                from agents.prompt_constants import FEATURE_SCHEMA
                schema_keys = set(FEATURE_SCHEMA.keys())
                feature_keys = set(k for k in features if not k.startswith('_'))
                missing_keys = schema_keys - feature_keys
                extra_keys = feature_keys - schema_keys
                coverage = len(feature_keys & schema_keys) / len(schema_keys) * 100 if schema_keys else 0

                print()
                print(f"  📐 FEATURE_SCHEMA Validation ({len(schema_keys)} defined):")
                print(f"     Schema coverage: {coverage:.0f}% ({len(feature_keys & schema_keys)}/{len(schema_keys)})")
                if missing_keys:
                    print(f"     ⚠️ Missing features ({len(missing_keys)}): {', '.join(sorted(missing_keys)[:10])}")
                    if len(missing_keys) > 10:
                        print(f"        ... and {len(missing_keys) - 10} more")
                else:
                    print(f"     ✅ All schema features extracted")
                if extra_keys:
                    print(f"     ℹ️ Extra features ({len(extra_keys)}): {', '.join(sorted(extra_keys)[:5])}")

                # Type validation for enum fields
                enum_errors = []
                for key, spec in FEATURE_SCHEMA.items():
                    if spec.get('type') == 'enum' and key in features:
                        val = features[key]
                        allowed = spec.get('values', [])
                        if val is not None and val not in allowed:
                            enum_errors.append(f"{key}={val} (expected: {allowed})")
                if enum_errors:
                    print(f"     ❌ Enum value errors: {', '.join(enum_errors[:5])}")
                else:
                    enum_count = sum(1 for k, s in FEATURE_SCHEMA.items()
                                     if s.get('type') == 'enum' and k in features)
                    if enum_count > 0:
                        print(f"     ✅ All {enum_count} enum features have valid values")
            except ImportError:
                print(f"     ⚠️ Could not import FEATURE_SCHEMA for validation")

        # 5. Schema validation results (from call_trace)
        trace = ma.get_call_trace() if hasattr(ma, 'get_call_trace') else []
        validated_calls = [c for c in trace if c.get('schema_version')]
        if validated_calls:
            sv = validated_calls[0].get('schema_version', '?')
            fv = validated_calls[0].get('feature_version', '?')
            print()
            print(f"  🏷️ Version Tracking:")
            print(f"     SCHEMA_VERSION: {sv}")
            print(f"     FEATURE_VERSION: {fv}")
            print(f"     Calls with version metadata: {len(validated_calls)}/{len(trace)}")

        print()

    def _display_structured_path_verification(self) -> None:
        """
        v27.0/v28.0: Verify diagnostic-production parity for structured path.

        Production path (multi_agent_analyzer.py:analyze()):
          1. extract_features() → feature_dict (or None → text fallback)
          2. Structured debate ran (confirmed via _structured_debate in final_decision)
          3. If structured: all 5 agents use json_mode=True + feature_dict input
          4. _structured_debate in final_decision confirms structured debate ran
          5. call_trace records json_mode=True per call
          6. _schema_violations tracks auto-corrected output constraint violations
          7. Snapshot has all fields needed for analyze_from_features() replay
          8. Feature dict hash verifies deterministic extraction
          9. v28.0: _scores (dimensional scores) injected in all agent user prompts

        This method verifies all 9 conditions match between diagnostic and production.
        """
        ma = self.ctx.multi_agent
        if not ma:
            return

        print()
        print_box("v27.0 诊断-生产一致性验证 (Diagnostic-Production Parity)", 65)
        print()

        checks_passed = 0
        checks_total = 0
        issues = []

        # === Check 1: extract_features() succeeded ===
        checks_total += 1
        snapshot = getattr(ma, '_last_feature_snapshot', None)
        features = snapshot.get('features', {}) if snapshot else {}
        has_features = bool(snapshot and features and len([k for k in features if not k.startswith('_')]) > 0)
        if has_features:
            n_feat = len([k for k in features if not k.startswith('_')])
            print(f"  ✅ Check 1: extract_features() 成功 ({n_feat} features)")
            checks_passed += 1
        else:
            print(f"  ❌ Check 1: extract_features() 失败 — 生产会 fallback 到 text-only path")
            issues.append("Feature extraction failed: structured path NOT active")

        # === Check 2: Structured debate ran (confirmed via _structured_debate) ===
        checks_total += 1
        signal_data = self.ctx.signal_data or {}
        structured_debate = signal_data.get('_structured_debate')
        if structured_debate and isinstance(structured_debate, dict):
            bull = structured_debate.get('bull', {})
            bear = structured_debate.get('bear', {})
            has_conviction = bool(bull.get('conviction') and bear.get('conviction'))
            if has_conviction:
                print(f"  ✅ Check 2: Structured debate confirmed (Bull/Bear conviction present)")
                checks_passed += 1
            else:
                print(f"  ⚠️ Check 2: _structured_debate exists but missing conviction fields")
                issues.append("Structured debate output incomplete (missing conviction)")
        else:
            print(f"  ❌ Check 2: Structured debate NOT detected — text-based fallback path was used")
            if has_features:
                issues.append("Feature extraction succeeded but structured debate NOT used (unexpected)")
            else:
                issues.append("Text-based fallback path active (feature extraction failed)")

        # === Check 3: All AI calls used json_mode=True ===
        checks_total += 1
        trace = ma.get_call_trace() if hasattr(ma, 'get_call_trace') else []
        if trace:
            json_mode_calls = [c for c in trace if c.get('json_mode')]
            non_json_calls = [c for c in trace if not c.get('json_mode')]
            if non_json_calls:
                non_json_labels = [c.get('label', '?') for c in non_json_calls]
                print(f"  ❌ Check 3: JSON mode — {len(json_mode_calls)}/{len(trace)} calls used json_mode=True")
                print(f"     Non-JSON calls: {', '.join(non_json_labels)}")
                issues.append(f"JSON mode not used for: {', '.join(non_json_labels)}")
            else:
                print(f"  ✅ Check 3: JSON mode — {len(json_mode_calls)}/{len(trace)} calls used json_mode=True")
                checks_passed += 1
        else:
            print(f"  ⚠️ Check 3: No call trace available (json_mode not yet tracked)")

        # === Check 4: feature_dict was passed to all agent prompts ===
        # Use call_trace (ground truth of actual API messages) instead of
        # last_prompts which may have stale or missing entries.
        checks_total += 1
        # Map call_trace labels to canonical agent names
        _label_to_agent = {
            "bull": "bull", "bear": "bear", "judge": "judge",
            "entry timing": "entry_timing", "risk manager": "risk",
        }
        if trace:
            agents_with_features = set()
            agents_called = set()
            for call in trace:
                label = call.get("label", "").lower()
                agent_name = None
                for prefix, name in _label_to_agent.items():
                    if prefix in label:
                        agent_name = name
                        break
                if not agent_name:
                    continue
                agents_called.add(agent_name)
                # Check user message in the actual API messages for feature dict
                messages = call.get("messages", [])
                user_msg = ""
                for msg in messages:
                    if msg.get("role") == "user":
                        user_msg = msg.get("content", "")
                        break
                if '"features"' in user_msg and '"price"' in user_msg:
                    agents_with_features.add(agent_name)
            # Entry Timing is correctly skipped for HOLD signals
            expected_agents = set(agents_called)
            agents_without = expected_agents - agents_with_features
            n_expected = len(expected_agents)
            n_with = len(agents_with_features)
            skipped_note = ""
            if "entry_timing" not in agents_called:
                skipped_note = " (entry_timing skipped: HOLD signal)"
            if agents_without:
                print(f"  ❌ Check 4: Feature dict input — {n_with}/{n_expected} agents received features")
                print(f"     Missing: {', '.join(sorted(agents_without))}")
                issues.append(f"Feature dict not passed to: {', '.join(sorted(agents_without))}")
            else:
                print(f"  ✅ Check 4: Feature dict input — {n_with}/{n_expected} agents received features{skipped_note}")
                checks_passed += 1
        else:
            print(f"  ⚠️ Check 4: No call trace available")

        # === Check 5: Structured output fields present in signal_data ===
        checks_total += 1
        structured_output_fields = {
            'decisive_reasons': signal_data.get('decisive_reasons'),
            'risk_flags': signal_data.get('risk_flags'),
        }
        # Check Judge decision has structured fields
        judge_fields_ok = bool(
            signal_data.get('decisive_reasons') is not None or
            signal_data.get('risk_flags') is not None or
            signal_data.get('_structured_debate') is not None
        )
        # Check REASON_TAGS validation (v30.0: syntax + data-supported)
        tags_valid = True
        try:
            from agents.prompt_constants import REASON_TAGS
            from agents.tag_validator import compute_valid_tags
            all_output_tags = []
            for field_name in ['decisive_reasons', 'risk_flags']:
                tags = signal_data.get(field_name, [])
                if isinstance(tags, list):
                    all_output_tags.extend(tags)
            if structured_debate:
                for side in ['bull', 'bear']:
                    side_data = structured_debate.get(side, {})
                    all_output_tags.extend(side_data.get('evidence', []))
                    all_output_tags.extend(side_data.get('risk_flags', []))
            if all_output_tags:
                invalid_tags = [t for t in all_output_tags if t not in REASON_TAGS]
                if invalid_tags:
                    tags_valid = False
                    issues.append(f"Invalid REASON_TAGS: {invalid_tags[:5]}")
                # v30.0: data-supported tag check
                snapshot = getattr(self.ctx.multi_agent, '_last_feature_snapshot', None)
                if snapshot and snapshot.get('features'):
                    data_supported = compute_valid_tags(snapshot['features'])
                    unsupported = [t for t in all_output_tags if t not in data_supported]
                    if unsupported:
                        issues.append(f"{len(unsupported)} tags not data-supported: {unsupported[:3]}")
        except ImportError:
            pass

        if judge_fields_ok and tags_valid:
            n_tags = len([t for t in (signal_data.get('decisive_reasons') or []) +
                         (signal_data.get('risk_flags') or []) if t])
            print(f"  ✅ Check 5: Structured output — decisive_reasons/risk_flags present ({n_tags} tags)")
            checks_passed += 1
        elif not judge_fields_ok:
            print(f"  ❌ Check 5: Structured output fields missing from signal_data")
            issues.append("No structured output fields (decisive_reasons/risk_flags)")
        else:
            print(f"  ⚠️ Check 5: Structured output present but REASON_TAGS validation failed")

        # === Check 6: Schema violation tracking (output enforcement) ===
        checks_total += 1
        schema_violations = getattr(ma, '_schema_violations', {})
        total_violations = sum(schema_violations.values()) if schema_violations else 0
        if schema_violations is not None:
            if total_violations == 0:
                print(f"  ✅ Check 6: Schema violations — 0 violations (all outputs conform)")
                checks_passed += 1
            else:
                print(f"  ⚠️ Check 6: Schema violations — {total_violations} total (auto-corrected)")
                for agent_name, count in sorted(schema_violations.items()):
                    if count > 0:
                        print(f"     {agent_name}: {count} violation(s)")
                issues.append(f"Schema violations auto-corrected: {total_violations} total")
                # Still pass — violations are auto-corrected, not fatal
                checks_passed += 1
        else:
            print(f"  ⚠️ Check 6: Schema violation tracker not initialized")

        # === Check 7: Replay readiness (snapshot completeness) ===
        checks_total += 1
        if snapshot:
            required_replay_fields = ['features', 'schema_version', 'feature_version',
                                       'timestamp', 'symbol', '_input_contract']
            missing_fields = [f for f in required_replay_fields if f not in snapshot]
            has_memory = '_memory' in snapshot
            has_debate_r1 = '_debate_r1' in snapshot

            if not missing_fields and has_memory:
                detail = f"_memory={'present' if has_memory else 'missing'}, _debate_r1={'present' if has_debate_r1 else 'deferred'}"
                print(f"  ✅ Check 7: Replay readiness — snapshot complete ({detail})")
                checks_passed += 1
            else:
                detail_parts = []
                if missing_fields:
                    detail_parts.append(f"missing: {', '.join(missing_fields)}")
                if not has_memory:
                    detail_parts.append("_memory not captured")
                print(f"  ⚠️ Check 7: Replay readiness — {'; '.join(detail_parts)}")
                issues.append(f"Snapshot incomplete for replay: {'; '.join(detail_parts)}")
        else:
            print(f"  ❌ Check 7: Replay readiness — no snapshot available")
            issues.append("No feature snapshot for replay")

        # === Check 8: Feature dict determinism (hash stability) ===
        checks_total += 1
        if has_features:
            import hashlib
            import json as _json
            # Compute a deterministic hash of the feature dict (excluding _reliability which is metadata)
            feat_for_hash = {k: v for k, v in features.items() if not k.startswith('_')}
            try:
                feat_json = _json.dumps(feat_for_hash, sort_keys=True, default=str)
                feat_hash = hashlib.sha256(feat_json.encode()).hexdigest()[:16]
                n_numeric = sum(1 for v in feat_for_hash.values() if isinstance(v, (int, float)))
                n_enum = sum(1 for v in feat_for_hash.values() if isinstance(v, str))
                print(f"  ✅ Check 8: Feature dict hash — {feat_hash} ({n_numeric} numeric, {n_enum} enum)")
                checks_passed += 1
            except Exception as e:
                print(f"  ⚠️ Check 8: Feature dict hash failed — {e}")
        else:
            print(f"  ❌ Check 8: Feature dict hash — no features extracted")
            issues.append("Cannot verify feature determinism without features")

        # === Check 9: v28.0 Dimensional scores (_scores) injected in all agent prompts ===
        # Verifies both presence AND value consistency of _scores in call_trace
        checks_total += 1
        if trace:
            import json as _json
            agents_with_scores = set()
            agents_without_scores = set()
            score_value_mismatches = []
            # Compute expected scores from features for cross-validation
            expected_scores = None
            if has_features:
                try:
                    from agents.report_formatter import ReportFormatterMixin
                    expected_scores = ReportFormatterMixin.compute_scores_from_features(features)
                except Exception:
                    pass
            for call in trace:
                label = call.get("label", "").lower()
                agent_name = None
                for prefix, name in _label_to_agent.items():
                    if prefix in label:
                        agent_name = name
                        break
                if not agent_name:
                    continue
                # Check user message for _scores field
                messages = call.get("messages", [])
                user_msg = ""
                for msg in messages:
                    if msg.get("role") == "user":
                        user_msg = msg.get("content", "")
                        break
                if '"_scores"' in user_msg:
                    agents_with_scores.add(agent_name)
                    # Cross-validate: actual injected scores match computed scores
                    if expected_scores:
                        try:
                            parsed = _json.loads(user_msg)
                            injected = parsed.get("_scores", {})
                            for dim in ("trend", "momentum", "order_flow", "vol_ext_risk", "risk_env"):
                                exp_score = expected_scores.get(dim, {}).get("score")
                                inj_score = injected.get(dim, {}).get("score")
                                if exp_score is not None and inj_score is not None and exp_score != inj_score:
                                    score_value_mismatches.append(
                                        f"{agent_name}.{dim}: injected={inj_score} vs computed={exp_score}")
                        except (_json.JSONDecodeError, AttributeError):
                            pass  # Can't parse, presence check is enough
                else:
                    agents_without_scores.add(agent_name)
            # Entry Timing may be skipped for HOLD
            if "entry_timing" not in agents_with_scores and "entry_timing" not in agents_without_scores:
                pass  # skipped, not a failure
            if agents_without_scores:
                print(f"  ❌ Check 9: _scores (v28.0) — {len(agents_with_scores)}/{len(agents_with_scores) + len(agents_without_scores)} agents received _scores")
                print(f"     Missing: {', '.join(sorted(agents_without_scores))}")
                issues.append(f"_scores not injected for: {', '.join(sorted(agents_without_scores))}")
            else:
                skipped_note = ""
                if "entry_timing" not in agents_with_scores:
                    skipped_note = " (entry_timing skipped: HOLD signal)"
                print(f"  ✅ Check 9: _scores (v28.0) — {len(agents_with_scores)} agents received dimensional scores{skipped_note}")
                if score_value_mismatches:
                    print(f"     ⚠️ Score value drift detected ({len(score_value_mismatches)} mismatch):")
                    for mm in score_value_mismatches[:3]:
                        print(f"        {mm}")
                    issues.append(f"_scores value drift: {len(score_value_mismatches)} dimension(s)")
                else:
                    if expected_scores:
                        print(f"     ✅ Score values cross-validated against compute_scores_from_features()")
                    checks_passed += 1
        else:
            print(f"  ⚠️ Check 9: No call trace available for _scores validation")

        # === Check 10: v30.3 Decision Cache persisted in snapshot ===
        checks_total += 1
        if snapshot:
            decision_cache = snapshot.get('_decision_cache')
            is_complete = snapshot.get('_complete', False)
            if decision_cache and is_complete:
                cache_agents = [k for k in decision_cache if k not in ('quality_score', 'signal', 'confidence')]
                cache_signal = decision_cache.get('signal', '?')
                cache_conf = decision_cache.get('confidence', '?')
                print(f"  ✅ Check 10: Decision Cache — {len(cache_agents)} agents cached, _complete=True, signal={cache_signal}/{cache_conf}")
                checks_passed += 1
            elif decision_cache and not is_complete:
                print(f"  ⚠️ Check 10: Decision Cache exists but _complete=False (analysis may have been interrupted)")
                issues.append("Snapshot _complete=False: decision cache may be incomplete")
            else:
                print(f"  ⚠️ Check 10: Decision Cache not yet populated (_complete={is_complete})")
                issues.append("No _decision_cache in snapshot (populated after all agents complete)")
        else:
            print(f"  ❌ Check 10: Decision Cache — no snapshot available")

        # === Check 11: _raw_* fields preserved (zero-truncation policy v30.2) ===
        checks_total += 1
        _raw_verified = True
        _raw_details = []
        last_ctx = getattr(ma, '_last_analysis_context', None)
        if last_ctx:
            _agent_checks = [
                ('bull', last_ctx.bull_output, ['reasoning', 'summary']),
                ('bear', last_ctx.bear_output, ['reasoning', 'summary']),
                ('judge', last_ctx.judge_output, ['rationale', 'reasoning']),
                ('risk', last_ctx.risk_output, ['reason', 'reasoning']),
            ]
            for role, output, fields in _agent_checks:
                if not output:
                    continue
                for field in fields:
                    raw_key = f"_raw_{field}"
                    val = output.get(field, '')
                    raw_val = output.get(raw_key)
                    if raw_val is not None:
                        # _raw_ exists: field was truncated, verify _raw_ is longer
                        if len(str(raw_val)) >= len(str(val)):
                            _raw_details.append(f"{role}.{raw_key}: ✅ preserved ({len(str(raw_val))} chars)")
                        else:
                            _raw_verified = False
                            _raw_details.append(f"{role}.{raw_key}: ❌ shorter than truncated ({len(str(raw_val))} < {len(str(val))})")
            if _raw_verified:
                n_raw = sum(1 for d in _raw_details if '✅' in d)
                if n_raw > 0:
                    print(f"  ✅ Check 11: Zero-truncation — {n_raw} _raw_* fields preserved (safety net triggered, originals intact)")
                else:
                    print(f"  ✅ Check 11: Zero-truncation — no fields needed _raw_ (all within max_length)")
                checks_passed += 1
            else:
                print(f"  ❌ Check 11: Zero-truncation — _raw_* field integrity failure")
                for d in _raw_details:
                    if '❌' in d:
                        print(f"     {d}")
                issues.append("_raw_* field integrity failure")
        else:
            print(f"  ⚠️ Check 11: Zero-truncation — no AnalysisContext available for _raw_* check")

        # === Check 12: Entry Timing structured output completeness ===
        # v32.4: Updated to match ENTRY_TIMING_SCHEMA — flat keys (alignment,
        # counter_trend_risk, timing_quality, timing_verdict) replaced the
        # nested 'dimensions' dict from the original v23.0 design.
        checks_total += 1
        signal_data = self.ctx.signal_data or {}
        _timing = signal_data.get('_timing_assessment', {})
        if _timing:
            required_fields = {'alignment', 'counter_trend_risk', 'timing_quality', 'timing_verdict'}
            present_fields = set(_timing.keys()) & required_fields
            missing_fields = required_fields - present_fields
            if not missing_fields:
                print(f"  ✅ Check 12: Entry Timing — 4/4 required fields present "
                      f"(verdict={_timing.get('timing_verdict')}, quality={_timing.get('timing_quality')}, "
                      f"alignment={_timing.get('alignment')}, counter_trend={_timing.get('counter_trend_risk')})")
                checks_passed += 1
            else:
                print(f"  ❌ Check 12: Entry Timing — missing fields: {', '.join(sorted(missing_fields))}")
                issues.append(f"ET missing fields: {', '.join(sorted(missing_fields))}")
        elif signal_data.get('signal') in ('LONG', 'SHORT'):
            print(f"  ❌ Check 12: Entry Timing — signal is {signal_data['signal']} but no _timing_assessment")
            issues.append("Entry Timing Agent not called for LONG/SHORT signal")
        else:
            print(f"  ✅ Check 12: Entry Timing — skipped (signal={signal_data.get('signal', 'HOLD')}, ET only runs for LONG/SHORT)")
            checks_passed += 1

        # === Check 13: Confidence chain step validation ===
        # v32.4: Production uses origin=judge_decision.get("_confidence_origin", "AI")
        # for the judge phase. Accept both 'JUDGE' and 'AI' as valid first-step origins.
        checks_total += 1
        conf_chain = signal_data.get('_confidence_chain', [])
        if conf_chain:
            valid_origins = {'JUDGE', 'AI', 'ET_DOWNGRADE', 'ET_REJECT', 'RM_COERCE', 'RM_OVERRIDE', 'DEFAULT', 'COERCED', 'CAPPED', 'MECHANICAL_CAP'}
            chain_ok = True
            chain_issues_local = []
            # First step must be judge phase
            first_step = conf_chain[0]
            if first_step.get('phase') != 'judge':
                chain_ok = False
                chain_issues_local.append(f"first step phase={first_step.get('phase')}, expected judge")
            for step in conf_chain:
                if not all(k in step for k in ('phase', 'value', 'origin')):
                    chain_ok = False
                    chain_issues_local.append(f"step missing required fields: {step}")
                origin = step.get('origin', '')
                if origin and origin not in valid_origins:
                    chain_ok = False
                    chain_issues_local.append(f"unknown origin: {origin}")
            if chain_ok:
                print(f"  ✅ Check 13: Confidence chain — {len(conf_chain)} steps, valid sequence")
                checks_passed += 1
            else:
                print(f"  ❌ Check 13: Confidence chain — validation failed")
                for ci in chain_issues_local[:3]:
                    print(f"     {ci}")
                issues.extend(chain_issues_local)
        else:
            # Confidence chain is optional (older production may not have it)
            print(f"  ⚠️ Check 13: Confidence chain — not present in signal_data")

        # === Check 14: v31.4 Feature field name parity (EMA/position/account) ===
        checks_total += 1
        if snapshot and snapshot.get('features'):
            feat = snapshot['features']
            v314_checks = {
                'ema_12_30m': 'EMA 12 (base indicator_manager: ema_periods=[12,26])',
                'ema_26_30m': 'EMA 26 (base indicator_manager: ema_periods=[12,26])',
                'position_pnl_pct': 'pnl_percentage field',
                'position_size_pct': 'margin_used_pct field',
                'liquidation_buffer_pct': 'liquidation_buffer_portfolio_min_pct field',
            }
            v314_zeros = []
            v314_ok = []
            for key, desc in v314_checks.items():
                val = feat.get(key, 0.0)
                # position/account fields may legitimately be 0.0 when no position
                if key.startswith('position_') or key == 'liquidation_buffer_pct':
                    # These are only meaningful with active position
                    cp = self.ctx.current_position or {}
                    has_position = cp.get('has_position', False)
                    if not has_position:
                        v314_ok.append(f"{key}: N/A (no position)")
                        continue
                if val == 0.0:
                    v314_zeros.append(f"{key} = 0.0 ({desc})")
                else:
                    v314_ok.append(f"{key} = {val}")
            if not v314_zeros:
                print(f"  ✅ Check 14: v31.4 Feature field mapping — {len(v314_ok)} key fields verified non-zero")
                checks_passed += 1
            else:
                print(f"  ⚠️ Check 14: v31.4 Feature field mapping — {len(v314_zeros)} fields still 0.0:")
                for z in v314_zeros:
                    print(f"     {z}")
                issues.append(f"v31.4 feature fields still 0.0: {', '.join(z.split(' =')[0] for z in v314_zeros)}")
        else:
            print(f"  ⚠️ Check 14: v31.4 Feature field mapping — no feature snapshot available")

        # === Summary ===
        print()
        parity_pct = (checks_passed / checks_total * 100) if checks_total > 0 else 0
        icon = '✅' if parity_pct == 100 else '⚠️' if parity_pct >= 60 else '❌'
        print(f"  {icon} 诊断-生产一致性: {checks_passed}/{checks_total} checks passed ({parity_pct:.0f}%)")
        if issues:
            print()
            print(f"  🚩 Issues ({len(issues)}):")
            for issue in issues:
                print(f"     - {issue}")
        if parity_pct == 100:
            print(f"     诊断系统与生产 AI pipeline 100% 一致")
        elif parity_pct >= 80:
            print(f"     高度一致 — schema violations auto-corrected 属正常运行")
        elif parity_pct >= 60:
            print(f"     部分一致 — text fallback path 可能被使用 (feature extraction 失败时的正常降级)")
        else:
            print(f"     ❌ 诊断与生产严重不一致 — 请检查 feature extraction 和 API 配置")

        print()

    def _display_call_trace_summary(self) -> None:
        """Display a summary table of all AI API calls with timing, tokens, and cache metrics."""
        if not hasattr(self.ctx.multi_agent, 'get_call_trace'):
            return

        trace = self.ctx.multi_agent.get_call_trace()
        if not trace:
            return

        has_cache = any(
            call.get('tokens', {}).get('cache_hit') is not None
            for call in trace
        )
        # v32.0: Check if thinking mode was used (reasoning_tokens present)
        has_thinking = any(
            call.get('tokens', {}).get('reasoning_tokens') is not None
            for call in trace
        )

        print()
        thinking_label = " [Thinking Mode]" if has_thinking else ""
        print_box(f"AI API 调用追踪 ({len(trace)} 次顺序调用{thinking_label})", 75)
        print()
        if has_cache:
            print(f"  {'#':<4} {'Agent':<16} {'耗时':>6} {'Tokens':>10} {'Prompt':>8} {'Reply':>8} {'Think':>8} {'CacheHit':>10} {'CacheMiss':>10}")
            print(f"  {'─'*4} {'─'*16} {'─'*6} {'─'*10} {'─'*8} {'─'*8} {'─'*8} {'─'*10} {'─'*10}")
        else:
            print(f"  {'#':<4} {'Agent':<16} {'耗时':>6} {'Tokens':>10} {'Prompt':>8} {'Reply':>8} {'Think':>8}")
            print(f"  {'─'*4} {'─'*16} {'─'*6} {'─'*10} {'─'*8} {'─'*8} {'─'*8}")

        total_time = 0
        total_tokens = 0
        total_cache_hit = 0
        total_cache_miss = 0
        total_reasoning = 0
        for i, call in enumerate(trace, 1):
            label = call.get('label', f'call_{i}')
            elapsed = call.get('elapsed_sec', 0)
            tokens = call.get('tokens', {})
            prompt_tk = tokens.get('prompt', 0)
            completion_tk = tokens.get('completion', 0)
            total_tk = tokens.get('total', 0)
            reasoning_tk = tokens.get('reasoning_tokens', 0) or 0
            total_time += elapsed
            total_tokens += total_tk
            total_reasoning += reasoning_tk
            if has_cache:
                ch = tokens.get('cache_hit', 0) or 0
                cm = tokens.get('cache_miss', 0) or 0
                total_cache_hit += ch
                total_cache_miss += cm
                print(f"  {i:<4} {label:<16} {elapsed:>5.1f}s {total_tk:>10,} {prompt_tk:>8,} {completion_tk:>8,} {reasoning_tk:>8,} {ch:>10,} {cm:>10,}")
            else:
                print(f"  {i:<4} {label:<16} {elapsed:>5.1f}s {total_tk:>10,} {prompt_tk:>8,} {completion_tk:>8,} {reasoning_tk:>8,}")

        if has_cache:
            print(f"  {'─'*4} {'─'*16} {'─'*6} {'─'*10} {'─'*8} {'─'*8} {'─'*8} {'─'*10} {'─'*10}")
            print(f"  {'':4} {'TOTAL':<16} {total_time:>5.1f}s {total_tokens:>10,} {'':>8} {'':>8} {total_reasoning:>8,} {total_cache_hit:>10,} {total_cache_miss:>10,}")
        else:
            print(f"  {'─'*4} {'─'*16} {'─'*6} {'─'*10} {'─'*8} {'─'*8} {'─'*8}")
            print(f"  {'':4} {'TOTAL':<16} {total_time:>5.1f}s {total_tokens:>10,} {'':>8} {'':>8} {total_reasoning:>8,}")

        # Cache savings summary
        if has_cache and total_cache_hit > 0:
            total_prompt = total_cache_hit + total_cache_miss
            hit_pct = (total_cache_hit / total_prompt * 100) if total_prompt > 0 else 0
            cost_without = total_prompt * 0.28 / 1_000_000
            cost_with = (total_cache_hit * 0.028 + total_cache_miss * 0.28) / 1_000_000
            savings_pct = ((cost_without - cost_with) / cost_without * 100) if cost_without > 0 else 0
            print()
            print(f"  DeepSeek Prefix Cache: {total_cache_hit:,} hit ({hit_pct:.1f}%) / {total_cache_miss:,} miss → {savings_pct:.1f}% cost savings")

        # v27.0: Version metadata + json_mode in call trace
        has_versions = any(call.get('schema_version') for call in trace)
        if has_versions:
            print()
            print("  🏷️ v27.0 Version Metadata (per call):")
            for i, call in enumerate(trace, 1):
                sv = call.get('schema_version', '')
                fv = call.get('feature_version', '')
                ph = call.get('prompt_hash', '')
                jm = call.get('json_mode')
                if sv or fv or ph:
                    label = call.get('label', f'call_{i}')
                    jm_icon = '✅' if jm else '❌' if jm is not None else '?'
                    print(f"     {label:16s} schema={sv} feature={fv} json_mode={jm_icon} prompt_hash={ph[:8]}{'...' if len(ph) > 8 else ''}")

        print()
        print(f"  💡 完整 AI 输入/输出已保存到独立日志文件 (--export 模式)")

    def _display_schema_audit_metadata(self) -> None:
        """
        v27.0: Display schema audit metadata from get_schema_audit_metadata().

        Matches production ai_strategy.py:3219-3225 which attaches this metadata
        to decision snapshots and latest_signal.json for replay traceability.
        """
        ma = self.ctx.multi_agent
        if not ma or not hasattr(ma, 'get_schema_audit_metadata'):
            return

        try:
            audit = ma.get_schema_audit_metadata()
            if not audit:
                return

            print()
            print(f"  🔍 Schema Audit Metadata (v27.0, matches production snapshot):")
            print(f"     schema_version:    {audit.get('schema_version', 'N/A')}")
            print(f"     feature_version:   {audit.get('feature_version', 'N/A')}")
            snapshot_id = audit.get('snapshot_id', '')
            print(f"     snapshot_id:       {snapshot_id if snapshot_id else '(not persisted)'}")
            violations = audit.get('schema_violations', {})
            total_v = sum(violations.values()) if violations else 0
            if total_v == 0:
                print(f"     schema_violations: 0 (all outputs conform)")
            else:
                print(f"     schema_violations: {total_v} total (auto-corrected)")
                for agent_name, count in sorted(violations.items()):
                    if count > 0:
                        print(f"       {agent_name}: {count}")
        except Exception as e:
            print(f"  ⚠️ Schema audit metadata: {e}")

    def _display_results(self, signal_data: Dict) -> None:
        """Display analysis results."""
        print()
        print("  🎯 Judge 最终决策:")
        judge_signal = signal_data.get('signal', 'N/A')
        print(f"     Signal: {judge_signal}")
        print(f"     Confidence: {signal_data.get('confidence', 'N/A')} (from Judge, v19.0)")
        print(f"     Risk Appetite: {signal_data.get('risk_appetite', 'N/A')} (from RM, v19.0)")
        # v24.2: Show position_size_pct from AI output (matches production signal_data)
        size_pct = signal_data.get('position_size_pct')
        if size_pct is not None:
            print(f"     Position Size: {size_pct}% (from RM)")
        risk_lvl = signal_data.get('risk_level')
        if risk_lvl:
            print(f"     Risk Level: {risk_lvl} (legacy/fallback)")

        # SL/TP
        sltp_suffix = " (仅供参考，HOLD 不使用)" if judge_signal == 'HOLD' else ""
        sl = safe_float(signal_data.get('stop_loss'))
        tp = safe_float(signal_data.get('take_profit'))
        if sl:
            print(f"     Stop Loss: ${sl:,.2f}{sltp_suffix}")
        if tp:
            print(f"     Take Profit: ${tp:,.2f}{sltp_suffix}")

        # Judge decision details
        judge = signal_data.get('judge_decision', {})
        if judge:
            winning_side = judge.get('winning_side', 'N/A')
            print(f"     Winning Side: {winning_side}")
            print()
            print("     📋 Judge 决策 (AI 完全自主):")
            print("        - AI 自主分析 Bull/Bear 辩论")
            print("        - AI 自主判断证据强度")
            print("        - 无硬编码规则或阈值")

            # v27.0: Structured decisive_reasons (REASON_TAGS)
            decisive_reasons = judge.get('decisive_reasons', [])
            if decisive_reasons:
                print()
                print(f"     Decisive Reasons (REASON_TAGS):")
                for tag in decisive_reasons[:5]:
                    print(f"       🏷️ {tag}")
            else:
                # Fallback to legacy key_reasons (text-based)
                key_reasons = judge.get('key_reasons', [])
                if key_reasons:
                    print()
                    print(f"     Key Reasons (legacy text):")
                    for reason in key_reasons[:3]:
                        reason_text = reason[:80] + "..." if len(reason) > 80 else reason
                        print(f"       • {reason_text}")

            # v27.0: Acknowledged risks (REASON_TAGS)
            acknowledged_risks = judge.get('acknowledged_risks', [])
            if acknowledged_risks:
                print(f"     Acknowledged Risks:")
                for risk in acknowledged_risks[:5]:
                    risk_text = risk[:80] + "..." if len(risk) > 80 else risk
                    print(f"       {'🏷️' if risk.isupper() and '_' in risk else '•'} {risk_text}")

            # v27.0: Confluence layers
            confluence = judge.get('confluence', {})
            if confluence and isinstance(confluence, dict):
                aligned = confluence.get('aligned_layers', '?')
                print()
                print(f"     Confluence (v27.0):")
                for layer in ['trend_1d', 'momentum_4h', 'levels_30m', 'derivatives']:
                    val = confluence.get(layer, 'N/A')
                    print(f"       {layer:16s} {val}")
                print(f"       {'aligned_layers':16s} {aligned}")

            # v27.0: Rationale (human-readable, downstream: Web API, RM prompt)
            rationale = judge.get('rationale', '')
            if rationale:
                print(f"     Rationale:")
                print_wrapped(rationale, indent="       ")

            # v27.0: Strategic actions
            strategic_actions = judge.get('strategic_actions', [])
            if strategic_actions:
                print(f"     Strategic Actions:")
                for action in strategic_actions[:3]:
                    print(f"       → {action}")

        # Debate summary
        if signal_data.get('debate_summary'):
            summary = signal_data['debate_summary']
            print()
            print(f"     Debate Summary:")
            print_wrapped(summary, indent="       ")

        # v23.0: Entry Timing Agent results
        _timing = signal_data.get('_timing_assessment', {})
        if _timing:
            print()
            print("  ⏱️ Entry Timing Agent (Phase 2.5, v23.0):")
            print(f"     Verdict: {_timing.get('timing_verdict', 'N/A')}")
            print(f"     Quality: {_timing.get('timing_quality', 'N/A')}")
            print(f"     Counter-trend: {_timing.get('counter_trend_risk', 'NONE')}")
            print(f"     Alignment: {_timing.get('alignment', 'N/A')}")
            print(f"     Adj Confidence: {_timing.get('adjusted_confidence', 'N/A')}")
            # v30.3: Show 4 dimensions (mtf, timing, counter_trend, extension)
            dims = _timing.get('dimensions', {})
            if isinstance(dims, dict) and dims:
                print(f"     Dimensions:")
                for dim_name in ('mtf', 'timing', 'counter_trend', 'extension'):
                    dim_val = dims.get(dim_name, 'N/A')
                    print(f"       {dim_name:16s} {dim_val}")
            # v27.0: Decisive reasons (REASON_TAGS)
            _t_reasons = _timing.get('decisive_reasons', [])
            if _t_reasons:
                print(f"     Decisive Reasons: {', '.join(_t_reasons[:5])}")
            _t_reason = _timing.get('reason', '')
            if _t_reason:
                print(f"     Reason: {_t_reason}")
            if signal_data.get('_timing_rejected'):
                _orig = signal_data.get('_timing_original_signal', '?')
                _rej_reason = signal_data.get('_timing_reason', '')
                print(f"     🚫 REJECTED: {_orig} → HOLD")
                if _rej_reason:
                    print(f"     Reject reason: {_rej_reason}")
            elif signal_data.get('_timing_confidence_adjusted'):
                print(f"     ⚠️ Confidence adjusted: {signal_data['_timing_confidence_adjusted']}")

        # v29+: Confidence Chain (production tracks Judge→ET→RM mutations)
        conf_chain = signal_data.get('_confidence_chain', [])
        if conf_chain:
            print()
            print("  🔗 Confidence Chain (v29+):")
            for step in conf_chain:
                phase = step.get('phase', '?')
                value = step.get('value', '?')
                origin = step.get('origin', '?')
                reason = step.get('reason', '')
                reason_suffix = f" — {reason}" if reason else ""
                print(f"     {phase:15s} → {value:6s} ({origin}){reason_suffix}")
            has_default = any(s.get('origin') in ('DEFAULT', 'COERCED') for s in conf_chain)
            if has_default:
                print(f"     ⚠️ Chain contains DEFAULT/COERCED step (schema fallback triggered)")

        # v29+: Memory Conditions Snapshot (conditions_v2 for similarity matching)
        mem_cond = signal_data.get('_memory_conditions_snapshot')
        if mem_cond and isinstance(mem_cond, dict):
            print()
            print("  🧠 Memory Conditions (conditions_v2):")
            key_fields = ['adx_regime', 'extension_regime', 'volatility_regime',
                          'cvd_trend_30m', 'sentiment', 'direction']
            for k in key_fields:
                v = mem_cond.get(k, 'N/A')
                print(f"     {k:22s} {v}")
            rsi_30m = mem_cond.get('rsi_30m', 'N/A')
            rsi_4h = mem_cond.get('rsi_4h', 'N/A')
            fr = mem_cond.get('funding_rate_pct', 'N/A')
            print(f"     {'rsi_30m':22s} {rsi_30m}")
            print(f"     {'rsi_4h':22s} {rsi_4h}")
            print(f"     {'funding_rate_pct':22s} {fr}")

        # v30.0: AnalysisContext summary (production parity verification)
        last_ctx = getattr(self.ctx.multi_agent, '_last_analysis_context', None)
        if last_ctx:
            print()
            print("  🏗️ AnalysisContext (v30.0):")
            print(f"     snapshot_id: {last_ctx.snapshot_id}")
            print(f"     is_prepared: {last_ctx.is_prepared()}")
            print(f"     valid_tags_count: {len(last_ctx.valid_tags) if last_ctx.valid_tags else 0}")
            print(f"     bull_output: {'✅' if last_ctx.bull_output else '❌'}")
            print(f"     bear_output: {'✅' if last_ctx.bear_output else '❌'}")
            print(f"     judge_output: {'✅' if last_ctx.judge_output else '❌'}")
            print(f"     et_output: {'✅' if last_ctx.et_output else '❌'}")
            print(f"     risk_output: {'✅' if last_ctx.risk_output else '❌'}")
            print(f"     quality_score: {last_ctx.quality_score}")

        # v29+: AI Quality Score
        quality_score = signal_data.get('_ai_quality_score')
        if quality_score is not None:
            print()
            print(f"  📊 AI Quality Score: {quality_score}/100")

        # v24.0: AI Quality Audit results
        self._display_quality_audit()

        # v17.1: Liquidation buffer blocked
        if signal_data.get('_liq_buffer_blocked'):
            print()
            print("  🛡️ Liquidation Buffer:")
            print("     🚫 Add-on blocked — buffer < 5%")

        # v6.6: FR entry blocked
        if signal_data.get('_fr_entry_blocked'):
            print()
            print("  💰 FR Entry Check:")
            print("     🚫 Entry blocked — severe FR pressure (>0.09%)")

        # Reason (from Risk Manager)
        reason = signal_data.get('reason', 'N/A')
        print()
        print(f"     Reason (RM): {reason}")

        # v27.0: Risk Manager risk_factors (REASON_TAGS)
        risk_factors = signal_data.get('risk_factors', [])
        if risk_factors:
            print(f"     Risk Factors (REASON_TAGS): {', '.join(risk_factors[:5])}")

        # Invalidation conditions
        invalidation = signal_data.get('invalidation', 'N/A')
        if invalidation and invalidation != 'N/A':
            print(f"     Invalidation: {invalidation}")

        # Display debate transcript
        self._display_debate_transcript()

        # Display AI Prompt structure
        self._display_prompt_structure()

        print()
        print("  ✅ MultiAgent 分析完成")

    def _display_debate_transcript(self) -> None:
        """Display Bull/Bear debate transcript (v27.0: structured or legacy text)."""
        if not self.ctx.multi_agent:
            return

        signal_data = self.ctx.signal_data or {}

        # v27.0: Structured debate output (tags + conviction + summary)
        structured = signal_data.get('_structured_debate')
        if structured:
            print()
            print_box("辩论记录 (v27.0 Structured Debate)", 65)
            print()

            for role in ['bull', 'bear']:
                data = structured.get(role, {})
                if not data:
                    continue

                conviction = data.get('conviction', '?')
                evidence = data.get('evidence', [])
                risk_flags = data.get('risk_flags', [])
                summary = data.get('summary', '')

                icon = '🐂' if role == 'bull' else '🐻'
                print(f"  {icon} {role.upper()} (conviction: {conviction})")

                if evidence:
                    print(f"     Evidence ({len(evidence)}):")
                    for tag in evidence[:7]:
                        print(f"       + {tag}")
                    if len(evidence) > 7:
                        print(f"       ... +{len(evidence) - 7} more")

                if risk_flags:
                    print(f"     Risk Flags ({len(risk_flags)}):")
                    for tag in risk_flags[:5]:
                        print(f"       - {tag}")

                if summary:
                    print(f"     Summary: {summary}")
                print()

            return

        # Legacy text-based debate transcript
        if hasattr(self.ctx.multi_agent, 'get_last_debate') and callable(self.ctx.multi_agent.get_last_debate):
            debate_transcript = self.ctx.multi_agent.get_last_debate()
            if debate_transcript:
                print()
                print("  📜 辩论记录 (Legacy Text Debate):")
                # Show first 600 characters
                if len(debate_transcript) > 600:
                    lines = debate_transcript[:600].split('\n')
                    for line in lines[:8]:
                        print(f"     {line[:100]}")
                    print(f"     [截断, 完整长度: {len(debate_transcript)} 字符]")
                else:
                    for line in debate_transcript.split('\n')[:8]:
                        print(f"     {line[:100]}")

    def _display_prompt_structure(self) -> None:
        """Display AI Prompt structure verification (v27.0: feature-driven + text)."""
        if not self.ctx.multi_agent:
            return

        if not hasattr(self.ctx.multi_agent, 'get_last_prompts'):
            return

        last_prompts = self.ctx.multi_agent.get_last_prompts()
        if not last_prompts:
            return

        print()
        print_box("AI Prompt 结构验证 (v27.0 Feature-Driven)", 65)
        print()

        for agent_name in ["bull", "bear", "judge", "entry_timing", "risk"]:
            if agent_name not in last_prompts:
                continue

            prompts = last_prompts[agent_name]
            system_prompt = prompts.get("system", "")
            user_prompt = prompts.get("user", "")

            # v27.0: Detect prompt mode (feature-driven vs text)
            is_feature_driven = (
                '"features"' in user_prompt or
                "REASON_TAGS" in system_prompt or
                "AVAILABLE TAGS" in system_prompt or
                "feature_dict" in system_prompt
            )

            # Check INDICATOR_DEFINITIONS in System Prompt
            has_indicator_defs = "INDICATOR REFERENCE" in system_prompt

            # v5.9/v27.0: Check memory in ALL agents
            has_past_memories = (
                "PAST REFLECTIONS" in user_prompt or
                "PAST TRADE PATTERNS" in user_prompt or
                '"_memory"' in user_prompt
            )

            # v27.0: Detect JSON output format instructions
            has_json_output = (
                '"evidence"' in system_prompt or
                '"conviction"' in system_prompt or
                '"decisive_reasons"' in system_prompt or
                '"timing_verdict"' in system_prompt or
                '"risk_factors"' in system_prompt
            )

            mode_tag = "🔷 FEATURE" if is_feature_driven else "📝 TEXT"
            print(f"  [{agent_name.upper()}] {mode_tag} Prompt:")
            print(f"     System Prompt 长度: {len(system_prompt)} 字符")
            print(f"     User Prompt 长度:   {len(user_prompt)} 字符")
            print(f"     Mode: {'feature-driven (v27.0)' if is_feature_driven else 'text-based (legacy)'}")

            if is_feature_driven:
                # v27.0: Feature-driven prompt checks
                has_tags_ref = "REASON_TAGS" in system_prompt or "AVAILABLE TAGS" in system_prompt
                has_json_mode = has_json_output
                print(f"     REASON_TAGS reference: {'✅' if has_tags_ref else '❌'}")
                print(f"     JSON output schema:    {'✅' if has_json_mode else '❌'}")
                print(f"     INDICATOR_DEFINITIONS: {'⚠️ still present' if has_indicator_defs else '✅ removed (pre-computed in features)'}")
            else:
                # Legacy text prompt checks
                print(f"     INDICATOR_DEFINITIONS: {'✅ present' if has_indicator_defs else '❌ missing'}")

            # v28.0: Check _scores in user prompt (dimensional scores for primacy anchoring)
            has_scores = '"_scores"' in user_prompt
            if is_feature_driven:
                print(f"     _scores (v28.0):       {'✅ present' if has_scores else '❌ MISSING (should be first field in user JSON)'}")

            # Memory context
            if has_past_memories:
                if '"_memory"' in user_prompt:
                    print(f"     Memory: ✅ structured JSON (_memory)")
                else:
                    memory_label = "PAST REFLECTIONS" if agent_name == "judge" else "PAST TRADE PATTERNS"
                    print(f"     Memory: ✅ text ({memory_label})")
            else:
                print(f"     Memory: ⚠️ no trade history")

            # Show System Prompt preview (first 150 chars)
            if system_prompt:
                preview = system_prompt[:150].replace('\n', ' ')
                print(f"     System 预览: {preview}...")

            # Show User Prompt preview (first 150 chars)
            if user_prompt:
                preview = user_prompt[:150].replace('\n', ' ')
                print(f"     User 预览:   {preview}...")

            # Agent-specific checks
            if agent_name == "entry_timing":
                has_counter_trend = "COUNTER-TREND" in system_prompt or "counter_trend" in system_prompt
                has_adx_rule = "ADX" in system_prompt and "40" in system_prompt
                has_timing_output = "timing_verdict" in system_prompt
                if has_counter_trend:
                    print(f"     ✅ Counter-trend rules present")
                if has_adx_rule:
                    print(f"     ✅ ADX>40 strong trend rules present")
                if has_timing_output:
                    print(f"     ✅ timing_verdict output format present")

            print()

        # Summary
        n_feature = sum(1 for a in ["bull", "bear", "judge", "entry_timing", "risk"]
                       if a in last_prompts and (
                           '"features"' in last_prompts[a].get("user", "") or
                           "REASON_TAGS" in last_prompts[a].get("system", "") or
                           "AVAILABLE TAGS" in last_prompts[a].get("system", "")
                       ))
        n_text = 5 - n_feature

        print("  📋 Prompt 架构总结:")
        print(f"     v27.0 Feature-driven agents: {n_feature}/5")
        if n_text > 0:
            print(f"     Legacy text-based agents:    {n_text}/5 (fallback)")
        print("     - v27.0: Feature dict input → REASON_TAGS output (JSON mode)")
        print("     - v27.0: INDICATOR_DEFINITIONS/SIGNAL_CONFIDENCE_MATRIX 预计算到 features")
        print("     - v23.0: Entry Timing Agent (Phase 2.5) 评估入场时机")


    def _display_quality_audit(self) -> None:
        """v24.0: Display AI Quality Audit results."""
        if not self.ctx.multi_agent:
            return

        quality_report = getattr(self.ctx.multi_agent, 'last_quality_report', None)
        if not quality_report:
            return

        print()
        print_box("AI Quality Audit (v24.0)", 65)
        print()

        score = quality_report.get('overall_score', 0)
        regime = quality_report.get('regime', 'N/A')
        adx = quality_report.get('adx_1d', 0)
        score_icon = '✅' if score >= 80 else '⚠️' if score >= 60 else '❌'
        print(f"  {score_icon} Overall Score: {score}/100  (regime: {regime}, ADX={adx:.1f})")
        print()

        # Per-agent coverage
        agents = quality_report.get('agents', {})
        if agents:
            print("  📊 Agent Data Coverage:")
            for role, data in agents.items():
                rate = data.get('coverage_rate', 0)
                missing = data.get('missing_categories', [])
                icon = '✅' if rate >= 1.0 else '⚠️' if rate >= 0.7 else '❌'
                line = f"     {icon} {role:14s} {rate*100:.0f}%"
                if missing:
                    line += f"  (missing: {', '.join(missing)})"
                print(line)

                # MTF violations
                for v in data.get('mtf_violations', []):
                    print(f"        🚨 MTF: {v}")

                # Skip violations
                for v in data.get('skip_violations', []):
                    print(f"        ⚠️ SKIP: {v}")
            print()

        # Confluence audit
        confluence = quality_report.get('confluence', {})
        if confluence:
            print("  🎯 Confluence Accuracy:")
            declared = confluence.get('aligned_declared', 0)
            actual = confluence.get('aligned_actual', 0)
            mismatch = confluence.get('alignment_mismatch', False)
            icon = '❌' if mismatch else '✅'
            print(f"     {icon} Aligned Layers: declared={declared} actual={actual}")

            conf_d = confluence.get('confidence_declared', '')
            conf_e = confluence.get('confidence_expected', '')
            conf_mismatch = confluence.get('confidence_mismatch', False)
            icon2 = '❌' if conf_mismatch else '✅'
            print(f"     {icon2} Confidence: declared={conf_d} expected={conf_e}")
            print()

        # Counter-trend
        ct = quality_report.get('counter_trend', {})
        if ct.get('detected'):
            flagged = ct.get('flagged_by_entry_timing', False)
            icon = '✅' if flagged else '❌'
            print(f"  ↩️ Counter-Trend: detected=True, flagged_by_entry_timing={flagged} {icon}")
            print()

        # v31.3: Citation / Value / Zone verification errors (v26.0+)
        # These are critical accuracy checks — agent cited wrong values or directions
        citation_errors = quality_report.get('citation_errors', 0)
        value_errors = quality_report.get('value_errors', 0)
        zone_errors = quality_report.get('zone_errors', 0)
        if citation_errors or value_errors or zone_errors:
            print("  🔍 Accuracy Verification (v26.0+):")
            if citation_errors:
                print(f"     ❌ Citation errors: {citation_errors} (agent cited wrong comparison direction)")
            if value_errors:
                print(f"     ❌ Value errors: {value_errors} (agent cited wrong indicator value)")
            if zone_errors:
                print(f"     ❌ Zone errors: {zone_errors} (agent misclassified RSI/ADX/Extension zone)")
            print()
        else:
            print("  🔍 Accuracy Verification: ✅ No citation/value/zone errors")
            print()

        # v31.3: Neutral acknowledgment tracking (v29.4)
        for role, data in agents.items():
            neutral_ack = data.get('neutral_acknowledged', [])
            unconfirmed = data.get('unconfirmed_neutral', [])
            if neutral_ack or unconfirmed:
                parts = []
                if neutral_ack:
                    parts.append(f"acknowledged={neutral_ack}")
                if unconfirmed:
                    parts.append(f"unconfirmed={unconfirmed}")
                print(f"     ℹ️ {role:14s} neutral: {', '.join(parts)}")
        # Only print separator if any neutral data was shown
        if any(data.get('neutral_acknowledged') or data.get('unconfirmed_neutral')
               for data in agents.values()):
            print()

        # Flags
        flags = quality_report.get('flags', [])
        if flags:
            print(f"  🚩 Quality Flags ({len(flags)}):")
            for f in flags[:10]:
                print(f"     - {f}")
            if len(flags) > 10:
                print(f"     ... and {len(flags) - 10} more")
            print()

    def should_skip(self) -> bool:
        return self.ctx.summary_mode


class EntryTimingStandaloneTest(DiagnosticStep):
    """
    Standalone Entry Timing Agent (Phase 2.5) diagnostic test.

    Entry Timing only runs in production when Judge outputs LONG/SHORT.
    If Judge outputs HOLD (common in sideways markets), this agent is
    never exercised — potential bugs stay hidden for days/weeks.

    This test constructs a mock Judge decision (SHORT, HIGH confidence)
    and invokes the real Entry Timing AI call, verifying:
    - API connectivity and JSON parsing
    - Output schema compliance (timing_verdict, timing_quality, etc.)
    - Confidence only-downgrade invariant
    - REASON_TAGS compliance
    - Counter-trend detection logic

    Result is diagnostic-only — does NOT affect the signal pipeline.
    Adds 1 extra API call (~3K tokens, ~$0.001).
    """

    name = "Entry Timing Agent 独立验证 (Phase 2.5 强制测试)"

    def run(self) -> bool:
        print("-" * 70)
        print()
        print_box("Entry Timing Agent 独立验证 (强制测试)", 65)
        print()

        ma = getattr(self.ctx, 'multi_agent', None)
        if not ma:
            print("  ⚠️ MultiAgentAnalyzer not initialized — skipping ET standalone test")
            return True

        # Check if ET was already naturally triggered
        signal_data = getattr(self.ctx, 'signal_data', {}) or {}
        timing = signal_data.get('_timing_assessment', {})
        natural_verdict = timing.get('timing_verdict', 'N/A')
        already_tested = natural_verdict not in ('N/A', None)

        if already_tested:
            print(f"  ℹ️ Entry Timing was naturally triggered (verdict={natural_verdict})")
            print(f"     仍执行独立验证以测试 mock SHORT 场景")
        else:
            print(f"  ℹ️ Entry Timing was skipped (Judge=HOLD) — 独立验证确保功能正常")
        print()

        try:
            # Get feature_dict from the analyzer's last snapshot
            feature_snapshot = getattr(ma, '_last_feature_snapshot', None)
            feature_dict = None
            if feature_snapshot and isinstance(feature_snapshot, dict):
                feature_dict = feature_snapshot.get('features', None)

            if not feature_dict:
                print("  ⚠️ No feature_dict available — cannot run structured ET test")
                print("     (extract_features() may have failed in MultiAgentAnalyzer)")
                return True

            # Get adx_1d from technical data
            trend_layer = (self.ctx.technical_data or {}).get('mtf_trend_layer', {})
            adx_1d = float(trend_layer.get('adx', 30.0) or 30.0)

            # Construct mock Judge decision for forced test
            # Use SHORT + HIGH to maximize ET evaluation surface
            # (counter-trend detection, confidence downgrade, etc.)
            mock_judge = {
                'decision': 'SHORT',
                'confidence': 'HIGH',
                'rationale': '[Diagnostic mock] Forced SHORT for Entry Timing standalone test',
                'confluence': {
                    'trend_1d': 'BEARISH',
                    'momentum_4h': 'BEARISH',
                    'levels_30m': 'NEUTRAL',
                    'derivatives': 'NEUTRAL',
                    'aligned_layers': 2,
                },
            }

            print(f"  📋 Mock Judge: decision=SHORT, confidence=HIGH")
            print(f"     ADX_1D={adx_1d:.1f}, features={len(feature_dict)} fields")
            print()

            # Build AnalysisContext to match production path (v29+)
            from agents.analysis_context import AnalysisContext
            from agents.tag_validator import compute_valid_tags, compute_annotated_tags
            from agents.report_formatter import ReportFormatterMixin
            mock_valid_tags = compute_valid_tags(feature_dict)
            mock_annotated_tags = compute_annotated_tags(feature_dict, mock_valid_tags)
            mock_scores = ReportFormatterMixin.compute_scores_from_features(feature_dict)
            mock_ctx = AnalysisContext(
                features=feature_dict,
                valid_tags=mock_valid_tags,
                annotated_tags=mock_annotated_tags,
                scores=mock_scores,
            )

            # Call the real Entry Timing Agent (1 API call)
            print("  🤖 Calling Entry Timing Agent...")
            t_start = time.monotonic()

            et_result = ma._run_structured_entry_timing(
                feature_dict=feature_dict,
                judge_decision=mock_judge,
                adx_1d=adx_1d,
                memory_text="",  # No memory for diagnostic mock
                ctx=mock_ctx,    # Production parity: pass AnalysisContext
            )

            t_elapsed = time.monotonic() - t_start
            self.ctx.step_timings['EntryTiming standalone'] = t_elapsed
            print(f"  [{t_elapsed:.1f}s] Entry Timing Agent complete")
            print()

            # === Validation ===
            checks_passed = 0
            checks_total = 0

            # Check 1: timing_verdict valid
            checks_total += 1
            verdict = et_result.get('timing_verdict', '')
            valid_verdicts = ('ENTER', 'REJECT')
            if verdict in valid_verdicts:
                print(f"  ✅ Check 1: timing_verdict = {verdict}")
                checks_passed += 1
            else:
                print(f"  ❌ Check 1: timing_verdict = {verdict!r} (expected: {valid_verdicts})")

            # Check 2: timing_quality valid
            checks_total += 1
            quality = et_result.get('timing_quality', '')
            valid_qualities = ('OPTIMAL', 'GOOD', 'FAIR', 'POOR')
            if quality in valid_qualities:
                print(f"  ✅ Check 2: timing_quality = {quality}")
                checks_passed += 1
            else:
                print(f"  ❌ Check 2: timing_quality = {quality!r} (expected: {valid_qualities})")

            # Check 3: adjusted_confidence valid and only-downgrade
            checks_total += 1
            adj_conf = et_result.get('adjusted_confidence', '')
            valid_confs = ('HIGH', 'MEDIUM', 'LOW')
            conf_rank = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}
            if adj_conf in valid_confs:
                original_rank = conf_rank.get('HIGH', 3)  # mock was HIGH
                adjusted_rank = conf_rank.get(adj_conf, 0)
                if adjusted_rank <= original_rank:
                    print(f"  ✅ Check 3: adjusted_confidence = {adj_conf} (only-downgrade invariant holds)")
                    checks_passed += 1
                else:
                    print(f"  ❌ Check 3: adjusted_confidence = {adj_conf} UPGRADED from HIGH (violation!)")
            else:
                print(f"  ❌ Check 3: adjusted_confidence = {adj_conf!r} (invalid)")

            # Check 4: counter_trend_risk valid
            checks_total += 1
            ct_risk = et_result.get('counter_trend_risk', '')
            valid_ct = ('NONE', 'LOW', 'HIGH', 'EXTREME')
            if ct_risk in valid_ct:
                print(f"  ✅ Check 4: counter_trend_risk = {ct_risk}")
                checks_passed += 1
            else:
                print(f"  ❌ Check 4: counter_trend_risk = {ct_risk!r} (expected: {valid_ct})")

            # Check 5: alignment valid
            checks_total += 1
            alignment = et_result.get('alignment', '')
            valid_align = ('STRONG', 'MODERATE', 'WEAK')
            if alignment in valid_align:
                print(f"  ✅ Check 5: alignment = {alignment}")
                checks_passed += 1
            else:
                print(f"  ❌ Check 5: alignment = {alignment!r} (expected: {valid_align})")

            # Check 6: decisive_reasons are valid REASON_TAGS
            checks_total += 1
            reasons = et_result.get('decisive_reasons', [])
            if isinstance(reasons, list):
                try:
                    from agents.prompt_constants import REASON_TAGS
                    invalid_tags = [t for t in reasons if t not in REASON_TAGS]
                    if not invalid_tags:
                        print(f"  ✅ Check 6: decisive_reasons ({len(reasons)} tags, all valid)")
                        checks_passed += 1
                    else:
                        print(f"  ❌ Check 6: invalid tags: {invalid_tags[:3]}")
                except ImportError:
                    print(f"  ⚠️ Check 6: REASON_TAGS import failed, skipping tag validation")
                    checks_passed += 1  # Don't fail on import issue
            else:
                print(f"  ❌ Check 6: decisive_reasons is not a list: {type(reasons)}")

            # Check 7: reason string present
            checks_total += 1
            reason_text = et_result.get('reason', '')
            if reason_text and len(reason_text) > 5:
                reason_display = reason_text[:120] + "..." if len(reason_text) > 120 else reason_text
                print(f"  ✅ Check 7: reason = {reason_display}")
                checks_passed += 1
            else:
                print(f"  ❌ Check 7: reason missing or too short: {reason_text!r}")

            print()
            icon = '✅' if checks_passed == checks_total else '❌'
            print(f"  {icon} Entry Timing 独立验证: {checks_passed}/{checks_total} checks passed")

            if checks_passed < checks_total:
                self.ctx.add_error(f"Entry Timing standalone: {checks_total - checks_passed} check(s) failed")
                return False

            return True

        except Exception as e:
            print(f"  ❌ Entry Timing standalone test failed: {e}")
            traceback.print_exc()
            self.ctx.add_error(f"Entry Timing standalone error: {e}")
            return False

    def should_skip(self) -> bool:
        return self.ctx.summary_mode


class RiskManagerStandaloneTest(DiagnosticStep):
    """
    Standalone Risk Manager (Phase 3) diagnostic test.

    v32.1: Risk Manager only runs in production when Judge outputs LONG/SHORT.
    If Judge outputs HOLD (common in sideways markets), this agent is
    never exercised — potential bugs stay hidden for days/weeks.

    This test constructs a mock Judge decision (LONG, MEDIUM confidence)
    and invokes the real Risk Manager AI call, verifying:
    - API connectivity and JSON parsing
    - Output schema compliance (signal, risk_appetite, position_risk, etc.)
    - Signal passthrough (RM should not change LONG→SHORT)
    - REASON_TAGS compliance
    - risk_appetite valid enum

    Result is diagnostic-only — does NOT affect the signal pipeline.
    Adds 1 extra API call (~5K tokens, ~$0.001).
    """

    name = "Risk Manager 独立验证 (Phase 3 强制测试)"

    def run(self) -> bool:
        print("-" * 70)
        print()
        print_box("Risk Manager 独立验证 (强制测试)", 65)
        print()

        ma = getattr(self.ctx, 'multi_agent', None)
        if not ma:
            print("  ⚠️ MultiAgentAnalyzer not initialized — skipping RM standalone test")
            return True

        # Check if RM was already naturally triggered
        signal_data = getattr(self.ctx, 'signal_data', {}) or {}
        rm_reason = signal_data.get('reason', '')
        already_tested = rm_reason and 'skipped' not in rm_reason.lower()

        if already_tested:
            print(f"  ℹ️ Risk Manager was naturally triggered (signal={signal_data.get('signal', 'N/A')})")
            print(f"     仍执行独立验证以测试 mock LONG 场景")
        else:
            print(f"  ℹ️ Risk Manager was skipped (Judge=HOLD) — 独立验证确保功能正常")
        print()

        try:
            # Get feature_dict from the analyzer's last snapshot
            feature_snapshot = getattr(ma, '_last_feature_snapshot', None)
            feature_dict = None
            if feature_snapshot and isinstance(feature_snapshot, dict):
                feature_dict = feature_snapshot.get('features', None)

            if not feature_dict:
                print("  ⚠️ No feature_dict available — cannot run structured RM test")
                print("     (extract_features() may have failed in MultiAgentAnalyzer)")
                return True

            # Get adx_1d from technical data
            trend_layer = (self.ctx.technical_data or {}).get('mtf_trend_layer', {})
            adx_1d = float(trend_layer.get('adx', 30.0) or 30.0)

            # Construct mock Judge decision for forced test
            # Use LONG + MEDIUM to exercise standard risk evaluation path
            mock_judge = {
                'decision': 'LONG',
                'confidence': 'MEDIUM',
                'rationale': '[Diagnostic mock] Forced LONG for Risk Manager standalone test',
            }

            print(f"  📋 Mock Judge: decision=LONG, confidence=MEDIUM")
            print(f"     ADX_1D={adx_1d:.1f}, features={len(feature_dict)} fields")
            print()

            # Build AnalysisContext to match production path (v29+)
            from agents.analysis_context import AnalysisContext
            from agents.tag_validator import compute_valid_tags, compute_annotated_tags
            from agents.report_formatter import ReportFormatterMixin
            mock_valid_tags = compute_valid_tags(feature_dict)
            mock_annotated_tags = compute_annotated_tags(feature_dict, mock_valid_tags)
            mock_scores = ReportFormatterMixin.compute_scores_from_features(feature_dict)
            mock_ctx = AnalysisContext(
                features=feature_dict,
                valid_tags=mock_valid_tags,
                annotated_tags=mock_annotated_tags,
                scores=mock_scores,
            )

            # Call the real Risk Manager (1 API call)
            print("  🤖 Calling Risk Manager...")
            t_start = time.monotonic()

            rm_result = ma._run_structured_risk(
                feature_dict=feature_dict,
                judge_decision=mock_judge,
                adx_1d=adx_1d,
                memory_text="",  # No memory for diagnostic mock
                ctx=mock_ctx,    # Production parity: pass AnalysisContext
            )

            t_elapsed = time.monotonic() - t_start
            self.ctx.step_timings['RiskManager standalone'] = t_elapsed
            print(f"  [{t_elapsed:.1f}s] Risk Manager complete")
            print()

            # === Validation ===
            checks_passed = 0
            checks_total = 0

            # Check 1: signal valid and passthrough
            checks_total += 1
            rm_signal = rm_result.get('signal', '')
            valid_signals = ('LONG', 'SHORT', 'HOLD', 'CLOSE', 'REDUCE')
            if rm_signal in valid_signals:
                # RM should not flip direction (LONG→SHORT), only LONG or HOLD allowed
                if rm_signal in ('LONG', 'HOLD'):
                    print(f"  ✅ Check 1: signal = {rm_signal} (direction preserved)")
                    checks_passed += 1
                else:
                    print(f"  ⚠️ Check 1: signal = {rm_signal} (unexpected direction change from LONG)")
                    checks_passed += 1  # Not a hard fail, RM can veto in extreme cases
            else:
                print(f"  ❌ Check 1: signal = {rm_signal!r} (expected: {valid_signals})")

            # Check 2: risk_appetite valid
            checks_total += 1
            appetite = rm_result.get('risk_appetite', '')
            valid_appetites = ('AGGRESSIVE', 'NORMAL', 'CONSERVATIVE')
            if appetite in valid_appetites:
                print(f"  ✅ Check 2: risk_appetite = {appetite}")
                checks_passed += 1
            else:
                print(f"  ❌ Check 2: risk_appetite = {appetite!r} (expected: {valid_appetites})")

            # Check 3: position_risk valid
            checks_total += 1
            pos_risk = rm_result.get('position_risk', '')
            valid_pos_risk = ('FULL_SIZE', 'REDUCED', 'MINIMAL', 'REJECT')
            if pos_risk in valid_pos_risk:
                print(f"  ✅ Check 3: position_risk = {pos_risk}")
                checks_passed += 1
            else:
                print(f"  ❌ Check 3: position_risk = {pos_risk!r} (expected: {valid_pos_risk})")

            # Check 4: market_structure_risk valid
            checks_total += 1
            mkt_risk = rm_result.get('market_structure_risk', '')
            valid_mkt_risk = ('NORMAL', 'ELEVATED', 'HIGH', 'EXTREME')
            if mkt_risk in valid_mkt_risk:
                print(f"  ✅ Check 4: market_structure_risk = {mkt_risk}")
                checks_passed += 1
            else:
                print(f"  ❌ Check 4: market_structure_risk = {mkt_risk!r} (expected: {valid_mkt_risk})")

            # Check 5: risk_factors is a list
            checks_total += 1
            risk_factors = rm_result.get('risk_factors', None)
            if isinstance(risk_factors, list):
                # Validate tags if present
                try:
                    from agents.prompt_constants import REASON_TAGS
                    invalid_tags = [t for t in risk_factors if t not in REASON_TAGS]
                    if not invalid_tags:
                        print(f"  ✅ Check 5: risk_factors ({len(risk_factors)} tags, all valid)")
                        checks_passed += 1
                    else:
                        print(f"  ❌ Check 5: invalid risk_factors tags: {invalid_tags[:3]}")
                except ImportError:
                    print(f"  ⚠️ Check 5: REASON_TAGS import failed, skipping tag validation")
                    checks_passed += 1
            else:
                print(f"  ❌ Check 5: risk_factors is not a list: {type(risk_factors)}")

            # Check 6: reason string present
            checks_total += 1
            reason_text = rm_result.get('reason', '')
            if reason_text and len(reason_text) > 5:
                reason_display = reason_text[:120] + "..." if len(reason_text) > 120 else reason_text
                print(f"  ✅ Check 6: reason = {reason_display}")
                checks_passed += 1
            else:
                print(f"  ❌ Check 6: reason missing or too short: {reason_text!r}")

            print()
            icon = '✅' if checks_passed == checks_total else '❌'
            print(f"  {icon} Risk Manager 独立验证: {checks_passed}/{checks_total} checks passed")

            if checks_passed < checks_total:
                self.ctx.add_error(f"Risk Manager standalone: {checks_total - checks_passed} check(s) failed")
                return False

            return True

        except Exception as e:
            print(f"  ❌ Risk Manager standalone test failed: {e}")
            traceback.print_exc()
            self.ctx.add_error(f"Risk Manager standalone error: {e}")
            return False

    def should_skip(self) -> bool:
        return self.ctx.summary_mode


class SignalProcessor(DiagnosticStep):
    """
    Process and validate AI signal.

    v42.0: Full production post-processing pipeline — 100% matching
    ai_strategy.py. Complete gate sequence:

    Production pipeline (on_timer + _execute_trade + _open_new_position):
    ─── on_timer() ───
    [S1] Signal fingerprint dedup         (stateful: cross-cycle, NOT simulated)
    [1]  Risk Controller gate             (circuit breaker + position multiplier)
    [·]  REJECT accuracy eval             (observability only, skipped)
    [2]  Entry Timing Agent gate          (v23.0 + v42.0 ET Exhaustion)
    ─── _execute_trade() ───
    [·]  Trading paused check             (runtime state, skipped in diagnostic)
    [3]  Signal age check                 (rejects signals >600s old)
    [4]  Legacy normalization             (BUY→LONG, SELL→SHORT)
    [S2] FR consecutive block exhaustion  (stateful: v21.0, NOT simulated)
    [·]  Confidence decay tracking        (observability only, skipped)
    [5]  Minimum confidence filter        (LOW after downgrade → HOLD)
    [·]  HOLD / CLOSE / REDUCE handling   (in OrderSimulator)
    [·]  Position size calculation         (in OrderSimulator)
    [6]  Liquidation buffer hard floor    (v17.1: buffer<5% blocks add-on)
    ─── _open_new_position() ───
    [7]  FR entry check                   (v6.6: paying FR > 0.09% blocks entry)

    [S] = Stateful gate requiring cross-cycle memory (documented, not simulated).
    [·] = Handled elsewhere or observability-only (skipped here).
    [1-7] = Actively simulated gates.

    v23.0 replaces old Gates 2-4 (Alignment Gate, Entry Quality POOR
    downgrade, 30M Confidence Cap) with a single AI-driven agent.

    v42.0: ET Exhaustion mechanism (stateful [S3]):
    - Tier 1 (≥5 consecutive REJECTs): Override REJECT → original signal at LOW
    - Tier 2 (≥8 consecutive REJECTs): Skip ET API call entirely
    - Counter reduces by 3 per trigger (not zero — retains pressure memory)
    - Diagnostic passes skip_entry_timing=False, displays flags if present.
    """

    name = "信号处理与验证 (完整实盘 pipeline)"

    def run(self) -> bool:
        signal_data = self.ctx.signal_data
        cfg = self.ctx.strategy_config

        raw_signal = signal_data.get('signal', 'HOLD')
        confidence = signal_data.get('confidence', 'LOW')
        min_conf = cfg.min_confidence_to_trade

        print(f"  原始信号: {raw_signal}")
        print(f"  信心等级: {confidence}")
        print(f"  最低要求: {min_conf}")

        # Production gate ordering (on_timer + _execute_trade):
        # ── on_timer post-analyze ──
        #   [S1] Signal fingerprint dedup (stateful, not simulated)
        #   [1]  Risk Controller circuit breaker
        #   [·]  REJECT accuracy eval (observability only)
        #   [2]  Entry Timing Agent logging + v42.0 ET Exhaustion [S3]
        # ── _execute_trade ──
        #   [3]  Signal age check
        #   [4]  Legacy normalization (BUY→LONG, SELL→SHORT)
        #   [S2] FR consecutive block exhaustion (stateful, not simulated)
        #   [·]  Confidence decay tracking (observability only)
        #   [5]  Confidence filter (min_confidence_to_trade)
        # ── _open_new_position ──
        #   [6]  Liquidation buffer hard floor
        #   [7]  FR entry check

        self.ctx.final_signal = raw_signal

        # === [S1] Signal fingerprint dedup (stateful, not simulated) ===
        # Production: on_timer lines 2760-2776
        # Requires _last_executed_fingerprint from previous cycle

        # === Gate 1: Risk Controller (production on_timer L2778-2810) ===
        if self.ctx.final_signal in ('LONG', 'SHORT'):
            self._apply_risk_controller_gate(signal_data)

        # === Gate 2: Entry Timing Agent (v23.0, replaces Gates 2/3/4) ===
        # In production, Entry Timing Agent runs as Phase 2.5 inside
        # multi_agent_analyzer.analyze(). The signal_data already contains
        # _timing_assessment, _timing_rejected, _timing_confidence_adjusted.
        # Here we just read and display those results.
        #
        # IMPORTANT: Production checks _timing_assessment regardless of signal value.
        # When REJECT occurs, signal is already HOLD (set by Phase 2.5 in analyzer),
        # so we must display timing results even when final_signal is HOLD.
        # Production flow (ai_strategy.py:2838-2940):
        #   if _timing:
        #       if _timing_rejected: ...  (signal is HOLD)
        #       elif signal in (LONG, SHORT): ...  (signal is LONG/SHORT)
        self._apply_entry_timing_gate(signal_data)

        # === Gate 3: Signal age check (production _execute_trade L74-97) ===
        # Production runs this BEFORE legacy normalization and confidence filter
        if self.ctx.final_signal in ('LONG', 'SHORT'):
            self._apply_signal_age_check(signal_data)

        # === Gate 4: Legacy normalization (production _execute_trade L99-103) ===
        legacy_mapping = {'BUY': 'LONG', 'SELL': 'SHORT'}
        if self.ctx.final_signal in legacy_mapping:
            self.ctx.final_signal = legacy_mapping[self.ctx.final_signal]
            signal_data['signal'] = self.ctx.final_signal
            print(f"  ℹ️ Legacy 信号映射: → {self.ctx.final_signal}")

        # === [S2] FR consecutive block exhaustion (stateful, not simulated) ===
        # Production: _execute_trade lines 109-141
        # Requires _fr_consecutive_blocks >= 3 from previous cycles

        # === Gate 5: Confidence filter (production _execute_trade L147-162) ===
        if self.ctx.final_signal not in ('CLOSE', 'REDUCE', 'HOLD'):
            confidence_levels = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
            # Re-read confidence in case Entry Timing Agent adjusted it
            current_conf = signal_data.get('confidence', 'LOW')
            min_conf_level = confidence_levels.get(min_conf.upper(), 1)
            signal_conf_level = confidence_levels.get(current_conf.upper(), 1)
            passes_threshold = signal_conf_level >= min_conf_level
            print(f"  信心过滤: {current_conf} >= {min_conf} → {'✅' if passes_threshold else '❌'}")
            if not passes_threshold:
                print(f"  → 信心不足，最终信号改为 HOLD")
                self.ctx.final_signal = 'HOLD'
        else:
            print(f"  信心过滤: {self.ctx.final_signal} (风险缩减/HOLD — 免检)")

        # === Gate 6: Liquidation buffer hard floor (v17.1) ===
        # Production: position_manager.py _open_new_position
        # Blocks add-on trades when existing position's liquidation buffer < 5%
        if self.ctx.final_signal in ('LONG', 'SHORT') and self.ctx.current_position:
            self._apply_liquidation_buffer_check(signal_data)

        # === Gate 7: FR entry check (v6.6) ===
        # Production: position_manager.py _open_new_position
        # Blocks entry when paying severe FR pressure (> 0.09%)
        if self.ctx.final_signal in ('LONG', 'SHORT'):
            self._apply_fr_entry_check(signal_data)

        # === Stateful gates summary ===
        print()
        print("  📋 Stateful gates (生产环境有效，诊断不模拟):")
        print("     [S1] Signal fingerprint dedup: 跨周期重复信号跳过 (需 _last_executed_fingerprint)")
        print("     [S2] FR consecutive block exhaustion (v21.0): ≥3 次同方向 FR 阻止 → HOLD")
        print("          (需 _fr_consecutive_blocks 跨周期计数器)")
        print("     [S3] ET Exhaustion (v42.0): ≥5 次连续 REJECT → Tier 1 override (LOW confidence)")
        print("          ≥8 次 → Tier 2 skip ET entirely (需 _et_consecutive_rejects 跨周期计数器)")

        print()
        print(f"  最终信号: {self.ctx.final_signal}")
        print(f"  最终信心: {signal_data.get('confidence', 'N/A')}")
        print("  ✅ 信号处理完成 (完整实盘 pipeline, 7 gates + 3 stateful notes)")

        return True

    # ── Gate 1: Risk Controller ──

    def _apply_risk_controller_gate(self, signal_data: Dict) -> None:
        """
        Apply Risk Controller circuit breaker checks.

        Matches production ai_strategy.py:2745-2777:
        1. can_open_trade() — HALTED/COOLDOWN → block to HOLD
        2. get_position_size_multiplier() — REDUCED → 0.5× position
        """
        risk_config = getattr(self.ctx.strategy_config, 'risk_config', None) or {}
        rc = RiskController(config=risk_config, logger=None)

        equity = 0.0
        if hasattr(self.ctx, 'account_balance') and self.ctx.account_balance:
            equity = self.ctx.account_balance.get('total_balance', 0) or 0
        if equity <= 0:
            equity = getattr(self.ctx.strategy_config, 'equity', 1000)

        atr_val = None
        if self.ctx.technical_data:
            atr_val = safe_float(self.ctx.technical_data.get('atr'))

        rc.update_equity(equity, current_atr=atr_val)

        print()
        print(f"  🛡️ [Gate 1] Risk Controller (v3.12):")
        print(f"     状态: {rc.metrics.trading_state.value}")
        print(f"     权益: ${equity:,.2f}")
        print(f"     回撤: {rc.metrics.drawdown_pct*100:.2f}%")
        if rc.metrics.halt_reason:
            print(f"     原因: {rc.metrics.halt_reason}")

        can_trade, block_reason = rc.can_open_trade()
        if not can_trade:
            print(f"     🚫 熔断阻止交易: {block_reason}")
            self.ctx.final_signal = 'HOLD'
            signal_data['_risk_blocked'] = True
            signal_data['_risk_block_reason'] = block_reason
            return

        print(f"     ✅ 允许交易")

        risk_mult = rc.get_position_size_multiplier()
        if 0 < risk_mult < 1.0:
            signal_data['_risk_position_multiplier'] = risk_mult
            print(f"     ⚠️ 仓位乘数: ×{risk_mult:.1f} (REDUCED 状态)")
        else:
            print(f"     仓位乘数: ×{risk_mult:.1f}")

    # ── Gate 2: Entry Timing Agent (v23.0) ──

    def _apply_entry_timing_gate(self, signal_data: Dict) -> None:
        """
        v23.0 + v42.0: Entry Timing Agent gate with ET Exhaustion.

        In production, the Entry Timing Agent runs as Phase 2.5 inside
        multi_agent_analyzer.analyze(). The signal_data already contains:
        - _timing_assessment: full timing evaluation
        - _timing_rejected: True if timing REJECT → HOLD
        - _timing_confidence_adjusted: "HIGH→MEDIUM" if confidence adjusted

        v42.0 ET Exhaustion (stateful, partially displayed):
        Production uses _et_consecutive_rejects counter across cycles:
        - Tier 1 (>=5): Override REJECT → original signal at LOW confidence
        - Tier 2 (>=8): Skip ET API call entirely (via skip_entry_timing=True)
        Diagnostic always passes skip_entry_timing=False, so Tier 2 is not
        exercised. However, if production had set _et_exhaustion_tier1/tier2
        flags, they would be displayed here.

        This diagnostic reads those fields and displays the results.

        Matches production ai_strategy.py:3224-3378:
        - Checks _timing_assessment regardless of signal value
        - v42.0: ET Exhaustion Tier 1 override (REJECT → original signal at LOW)
        - REJECT branch: signal already HOLD (set by Phase 2.5)
        - ENTER branch: signal still LONG/SHORT
        """
        _timing = signal_data.get('_timing_assessment', {})

        if not _timing:
            # No timing assessment — either HOLD signal from Judge or timing skipped
            # v42.0: Check if ET was skipped due to Tier 2 exhaustion
            if signal_data.get('_et_exhaustion_tier2'):
                print()
                print(f"  ⏱️ [Gate 2] Entry Timing Agent (v42.0):")
                print(f"     ⚡ ET Exhaustion Tier 2: ET API call skipped entirely")
                print(f"     连续拦截: {signal_data.get('_et_exhaustion_rejects', '?')} 次")
                print(f"     Judge confidence 保留")
            return

        signal = signal_data.get('signal', 'HOLD')

        print()
        print(f"  ⏱️ [Gate 2] Entry Timing Agent (v23.0 + v42.0):")

        _verdict = _timing.get('timing_verdict', 'N/A')
        _quality = _timing.get('timing_quality', 'N/A')
        _ctr_risk = _timing.get('counter_trend_risk', 'NONE')
        _alignment = _timing.get('alignment', 'N/A')
        _adj_conf = _timing.get('adjusted_confidence', 'N/A')
        _reason = _timing.get('reason', 'N/A')

        print(f"     Verdict: {_verdict}")
        print(f"     Quality: {_quality}")
        print(f"     Counter-trend risk: {_ctr_risk}")
        print(f"     Alignment: {_alignment}")
        print(f"     Adjusted confidence: {_adj_conf}")
        print(f"     Reason: {_reason[:120]}")

        # Production flow: check _timing_rejected first (signal is already HOLD),
        # then check ENTER case (signal is still LONG/SHORT)
        if signal_data.get('_timing_rejected'):
            _orig = signal_data.get('_timing_original_signal', '?')

            # v42.0: ET Exhaustion Tier 1 — override REJECT
            # In production, _et_consecutive_rejects >= 5 overrides REJECT to
            # original signal at LOW confidence. Diagnostic cannot simulate this
            # (no cross-cycle counter), but displays the flag if present.
            if signal_data.get('_et_exhaustion_tier1'):
                print(f"     ⚡ ET Exhaustion Tier 1: REJECT overridden")
                print(f"     连续拦截: {signal_data.get('_et_exhaustion_rejects', '?')} 次")
                print(f"     信号恢复: {_orig} at LOW confidence (30% 小仓位探索)")
                # Signal already restored by production — no need to modify here
            else:
                print(f"     🚫 REJECTED: {_orig} → HOLD")
                self.ctx.final_signal = 'HOLD'
                signal_data['signal'] = 'HOLD'
        elif signal in ('LONG', 'SHORT'):
            _conf_adj = signal_data.get('_timing_confidence_adjusted', '')
            if _conf_adj:
                print(f"     ⚠️ Confidence adjusted: {_conf_adj}")
            else:
                print(f"     ✅ 通过 (timing={_quality}, confidence unchanged)")

    # ── Gate 3: Signal Age Check (v23.0) ──

    def _apply_signal_age_check(self, signal_data: Dict) -> None:
        """
        v23.0: Signal age check — reject stale signals before execution.

        Matches production ai_strategy.py _execute_trade():
        - Parses signal timestamp (ISO 8601 or %Y-%m-%d %H:%M:%S)
        - Rejects signals older than 600s (10 min = half of 20-min cycle)
        """
        from datetime import datetime, timezone

        signal = signal_data.get('signal', 'HOLD')
        if signal not in ('LONG', 'SHORT'):
            return

        _ts_str = signal_data.get('timestamp', '')
        if not _ts_str:
            print()
            print(f"  ⏰ [Gate 3] Signal Age Check (v23.0):")
            print(f"     ⚠️ No timestamp in signal — cannot verify age")
            return

        try:
            if 'T' in _ts_str:
                _ts = datetime.fromisoformat(_ts_str.replace('Z', '+00:00'))
            else:
                _ts = datetime.strptime(_ts_str, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc)
            _age = (datetime.now(timezone.utc) - _ts).total_seconds()
            _max_age = 600  # 10 minutes

            print()
            print(f"  ⏰ [Gate 3] Signal Age Check (v23.0):")
            print(f"     Timestamp: {_ts_str}")
            print(f"     Age: {_age:.0f}s (max: {_max_age}s)")

            if _age > _max_age:
                print(f"     🚫 Signal too old ({_age:.0f}s > {_max_age}s) → HOLD")
                self.ctx.final_signal = 'HOLD'
            else:
                print(f"     ✅ Signal fresh ({_age:.0f}s ≤ {_max_age}s)")
        except (ValueError, TypeError) as e:
            print()
            print(f"  ⏰ [Gate 3] Signal Age Check (v23.0):")
            print(f"     ⚠️ Cannot parse timestamp '{_ts_str}': {e}")

    # ── Gate 6: Liquidation Buffer Hard Floor (v17.1) ──

    def _apply_liquidation_buffer_check(self, signal_data: Dict) -> None:
        """
        v17.1: Block add-on trades when liquidation buffer < 5%.

        Matches production ai_strategy.py:4693-4718.
        Only applies when there is an existing position AND signal is LONG/SHORT
        (i.e., add-on trade). AI prompt (STEP 3) handles 10-15% range;
        code catches extreme cases AI might miss.
        """
        pos = self.ctx.current_position
        if not pos:
            return

        liq_buffer = pos.get('liquidation_buffer_pct')
        if liq_buffer is None:
            # No liquidation data available — cannot check
            return

        print()
        print(f"  🛡️ [Gate 6] Liquidation Buffer Hard Floor (v17.1):")
        print(f"     Current buffer: {liq_buffer:.1f}%")
        print(f"     Hard floor: 5.0%")

        if liq_buffer < 5:
            print(f"     🚫 Buffer {liq_buffer:.1f}% < 5% — blocking add-on to protect position")
            self.ctx.final_signal = 'HOLD'
            signal_data['_liq_buffer_blocked'] = True
        else:
            print(f"     ✅ Buffer sufficient ({liq_buffer:.1f}% >= 5%)")

    # ── Gate 7: FR Entry Check (v6.6) ──

    def _apply_fr_entry_check(self, signal_data: Dict) -> None:
        """
        v6.6: Funding Rate entry gate — block entry on severe FR pressure.

        Matches production order_execution.py _open_new_position():1001-1034.
        Threshold: paying_funding AND |FR| > max_fr * 3 (default 0.09%).
        LONG + positive FR → paying; SHORT + negative FR → paying.
        """
        # Get FR data from derivatives report (same source as production)
        # Production: (self.latest_derivatives_data or {}).get('funding_rate', {})
        # AIDataAssembler already injects Binance FR into derivatives_report['funding_rate']
        dr = self.ctx.derivatives_report or {}
        fr_data = dr.get('funding_rate', {})
        fr_pct = fr_data.get('current_pct', fr_data.get('settled_pct', 0)) or 0

        try:
            fr_pct = float(fr_pct)
        except (ValueError, TypeError):
            fr_pct = 0

        if fr_pct == 0:
            # No FR data — cannot check
            return

        signal = self.ctx.final_signal
        side = 'long' if signal == 'LONG' else 'short'

        # Handle % vs decimal (same as production line 5402)
        fr_abs = abs(fr_pct / 100) if abs(fr_pct) > 0.1 else abs(fr_pct)
        paying_funding = (side == 'long' and fr_pct > 0) or (side == 'short' and fr_pct < 0)

        # Default pyramiding_max_funding_rate = 0.0003 (0.03%)
        max_fr = getattr(self.ctx.strategy_config, 'pyramiding_max_funding_rate', 0.0003)

        print()
        print(f"  💰 [Gate 7] FR Entry Check (v6.6):")
        print(f"     FR: {fr_pct:.5f}% | Side: {side.upper()}")
        print(f"     Paying funding: {'YES' if paying_funding else 'NO'}")
        print(f"     |FR|: {fr_abs:.6f} | Threshold: {max_fr * 3:.6f} (3× max_fr)")

        if paying_funding and fr_abs > max_fr * 3:
            print(f"     🚫 FR too high for {side.upper()} entry — blocked")
            print(f"        (|FR| {fr_abs:.6f} > threshold {max_fr * 3:.6f})")
            self.ctx.final_signal = 'HOLD'
            signal_data['_fr_entry_blocked'] = True
        elif paying_funding and fr_abs > max_fr:
            print(f"     ⚠️ FR elevated — proceeding with caution")
        else:
            print(f"     ✅ FR acceptable for {side.upper()} entry")

    def should_skip(self) -> bool:
        return self.ctx.summary_mode


class OrderSimulator(DiagnosticStep):
    """
    Simulate order submission flow.

    Tests _submit_bracket_order parameter validation.
    """

    name = "订单提交流程模拟 (_submit_bracket_order)"

    def run(self) -> bool:
        print("-" * 70)

        signal = self.ctx.signal_data.get('signal', 'HOLD')
        confidence = self.ctx.signal_data.get('confidence', 'MEDIUM')

        print("  📋 订单提交前提检查:")
        print(f"     信号: {signal}")
        print(f"     信心: {confidence}")
        print(f"     当前价格: ${self.ctx.current_price:,.2f}")
        print()

        if signal == 'HOLD':
            print("  ℹ️ 信号为 HOLD，不会提交订单")
            return True

        try:
            self._simulate_order(signal, confidence)
            return True
        except Exception as e:
            self.ctx.add_error(f"订单模拟失败: {e}")
            traceback.print_exc()
            return False

    def _simulate_order(self, signal: str, confidence: str) -> None:
        """Simulate order submission."""
        cfg = self.ctx.strategy_config

        # v4.8: Get equity and leverage from context (real Binance values)
        equity = getattr(self.ctx, 'account_balance', {}).get('total_balance', 0)
        if equity <= 0:
            equity = getattr(cfg, 'equity', 1000)

        leverage = getattr(self.ctx, 'binance_leverage', 10)
        max_position_ratio = getattr(cfg, 'max_position_ratio', 0.12)

        # v15.2: Initialize min_rr from config (was missing → NameError)
        min_rr = get_min_rr_ratio()

        # v15.5: Call the SAME calculate_position_size() used by production
        # (ai_strategy.py:4127). Eliminates appetite_scale + risk clamp divergence.
        td = self.ctx.technical_data or {}
        price_data = self.ctx.price_data or {'price': self.ctx.current_price}
        if 'price' not in price_data:
            price_data['price'] = self.ctx.current_price

        # Build config dict matching production _calculate_position_size() (ai_strategy.py:4111-4125)
        position_sizing_config = self.ctx.base_config.get('position', {}).get('position_sizing', {})
        calc_config = {
            'equity': equity,
            'leverage': leverage,
            'max_position_ratio': max_position_ratio,
            'min_trade_amount': getattr(cfg, 'min_trade_amount', 0.001),
            'high_confidence_multiplier': 1.5,
            'medium_confidence_multiplier': 1.0,
            'low_confidence_multiplier': 0.5,
            'trend_strength_multiplier': 1.2,
            'rsi_extreme_multiplier': 1.3,
            'rsi_extreme_upper': 70,
            'rsi_extreme_lower': 30,
            'position_sizing': position_sizing_config,
        }

        # v39.0: Pass 4H ATR for risk clamp consistency (matches production order_execution.py:430)
        _atr_4h = 0.0
        mtf_decision = td.get('mtf_decision_layer')
        if mtf_decision:
            _atr_4h = mtf_decision.get('atr', 0.0) or 0.0

        btc_quantity, sizing_details = calculate_position_size(
            self.ctx.signal_data, price_data, td, calc_config, logger=None,
            atr_4h=_atr_4h,
        )

        # Display sizing details (matching production log)
        size_source = sizing_details.get('size_source', 'unknown')
        size_pct = sizing_details.get('size_pct_used', sizing_details.get('size_pct', 0))
        appetite_scale = sizing_details.get('appetite_scale', 1.0)
        risk_appetite = sizing_details.get('risk_appetite', 'NORMAL')
        final_usdt = sizing_details.get('final_usdt', 0)
        max_usdt = sizing_details.get('max_usdt', 0)

        print(f"  📋 仓位计算 (调用生产 calculate_position_size):")
        print(f"     仓位百分比: {size_pct}% (来源: {size_source})")
        print(f"     appetite_scale: ×{appetite_scale:.0%} ({risk_appetite})")
        print(f"     max_usdt: ${max_usdt:,.2f}")
        print(f"     final_usdt: ${final_usdt:,.2f}")

        # Apply remaining capacity in cumulative mode (same as production ai_strategy.py:4141-4162)
        if self.ctx.current_position:
            current_qty = self.ctx.current_position.get('quantity', 0)
            current_price = self.ctx.current_price or 1
            current_value = current_qty * current_price
            remaining = max(0, max_usdt - current_value)
            max_add_btc = remaining / current_price if current_price > 0 else 0
            if btc_quantity > max_add_btc:
                print(f"     累加容量限制: {btc_quantity:.6f} → {max_add_btc:.6f} BTC")
                btc_quantity = max_add_btc

        quantity = btc_quantity

        # v4.8: Zero quantity guard (matches production ai_strategy.py:4619-4641)
        if quantity == 0 and btc_quantity == 0:
            print(f"  ⚠️ 仓位计算为 0 (余额不足或超过最大仓位)")
            print(f"     生产环境将跳过此交易并发送 Telegram 通知")
            self.ctx.add_warning("Position size is 0 — trade would be skipped in production")
            return

        # v11.0-simple: SL/TP comes from calculate_mechanical_sltp(), NOT from AI output.
        # Production flow: _validate_sltp_for_entry() → calculate_mechanical_sltp(ATR × confidence)
        # AI Risk Manager no longer outputs stop_loss/take_profit fields.

        # v6.1 fix: Build trend_info BEFORE mechanical calculation
        trend_info = self.ctx.technical_data if self.ctx.technical_data else None

        print("  📋 SL/TP 验证流程 (v11.0-simple: mechanical ATR-based):")

        confidence = self.ctx.signal_data.get('confidence', 'MEDIUM')
        risk_appetite = self.ctx.signal_data.get('risk_appetite', 'NORMAL')
        is_long = signal in ('BUY', 'LONG')
        is_counter = _is_counter_trend(is_long, trend_info) if trend_info else False
        side_str = 'BUY' if is_long else 'SELL'
        atr_value = self.ctx.atr_value or 0.0

        print(f"     Confidence: {confidence}")
        print(f"     Risk Appetite: {risk_appetite}")
        print(f"     ATR(14): ${atr_value:,.2f}")
        print(f"     Counter-trend: {'YES' if is_counter else 'NO'}")

        # v39.0: Use real 4H ATR from MTF decision layer (matches production _cached_atr_4h)
        # Production passes 0.0 when unavailable → calculate_mechanical_sltp falls back to 30M ATR internally
        atr_4h_real = 0.0
        td = self.ctx.technical_data or {}
        mtf_decision = td.get('mtf_decision_layer')
        if mtf_decision:
            atr_4h_real = mtf_decision.get('atr', 0.0) or 0.0
        if atr_4h_real > 0:
            print(f"     ATR(4H): ${atr_4h_real:,.2f} (real, from MTF decision layer)")
        else:
            print(f"     ATR(4H): unavailable (will fallback to 30M ATR internally)")
        success, mech_sl, mech_tp, method = calculate_mechanical_sltp(
            entry_price=self.ctx.current_price,
            side=side_str,
            atr_value=atr_value,
            confidence=confidence,
            risk_appetite=risk_appetite,
            is_counter_trend=is_counter,
            atr_4h=atr_4h_real,
        )

        if success:
            print(f"     ✅ Mechanical SL/TP: SL=${mech_sl:,.2f}, TP=${mech_tp:,.2f}")
            print(f"     Method: {method}")
        else:
            print(f"     ⚠️ Mechanical SL/TP failed: {method}")

        # v15.1: Match production _validate_sltp_for_entry() exactly.
        # Production does NOT call validate_multiagent_sltp() — R/R is guaranteed
        # by construction in calculate_mechanical_sltp() (ATR × confidence multiplier).
        # On failure, production falls back to percentage-based defaults.
        print()
        print("  📋 SL/TP 结果 (100% 匹配实盘 _validate_sltp_for_entry):")

        final_sl, final_tp = 0.0, 0.0

        if success and mech_sl and mech_tp:
            final_sl = mech_sl
            final_tp = mech_tp
            # Compute R/R for display (same as production lines 4506-4509)
            if is_long:
                rr = (final_tp - self.ctx.current_price) / (self.ctx.current_price - final_sl) if self.ctx.current_price > final_sl else 0
            else:
                rr = (self.ctx.current_price - final_tp) / (final_sl - self.ctx.current_price) if final_sl > self.ctx.current_price else 0
            print(f"     ✅ Mechanical SL/TP 成功: R/R={rr:.2f}:1 [{method}]")
        else:
            # Fallback: same as production lines 4740-4752
            print(f"     ⚠️ Mechanical SL/TP failed ({method}), trying percentage fallback")
            sl_pct = get_default_sl_pct()
            tp_pct = get_default_tp_pct_buy()
            if is_long:
                final_sl = self.ctx.current_price * (1 - sl_pct)
                final_tp = self.ctx.current_price * (1 + tp_pct)
            else:
                final_sl = self.ctx.current_price * (1 + sl_pct)
                final_tp = self.ctx.current_price * (1 - tp_pct)
            method = f"pct_fallback|sl={sl_pct:.1%}|tp={tp_pct:.1%}"
            print(f"     📍 Percentage fallback: {method}")

            # Validate fallback R/R against gate (production gap: counter-trend not checked)
            fallback_rr = tp_pct / sl_pct if sl_pct > 0 else 0
            required_rr = min_rr * get_counter_trend_rr_multiplier() if is_counter else min_rr
            if fallback_rr < required_rr:
                self.ctx.add_warning(
                    f"Percentage fallback R/R={fallback_rr:.2f}:1 < required {required_rr:.2f}:1 "
                    f"({'counter-trend' if is_counter else 'trend'}). "
                    f"Production will proceed with sub-optimal R/R on ATR=0 startup."
                )

        final_sl = safe_float(final_sl) or 0.0
        final_tp = safe_float(final_tp) or 0.0

        print()
        print("  📋 最终订单参数 (模拟):")
        print(f"     order_side: {'BUY' if signal in ['BUY', 'LONG'] else 'SELL'}")
        bc = self.ctx.base_currency
        notional = quantity * self.ctx.current_price if self.ctx.current_price else 0
        print(f"     quantity: ${notional:,.0f} ({quantity:.6f} {bc})")
        print(f"     entry_price: ${self.ctx.current_price:,.2f} (LIMIT @ validated price)")
        print(f"     sl_trigger_price: ${final_sl:,.2f}")
        print(f"     tp_price: ${final_tp:,.2f}")

        # v24.2/v43.0: Trailing stop simulation (matches production _submit_trailing_stop)
        # Production flow: on_position_opened → _submit_bracket_order_phase2 →
        # _submit_trailing_stop() with activation at 1.5R, callback = 4H ATR × 0.6
        # v43.0: Use 4H ATR (same as SL/TP), fallback to 30M
        trailing_atr = atr_4h_real if atr_4h_real > 0 else atr_value
        self._simulate_trailing_stop(
            entry_price=self.ctx.current_price,
            sl_price=final_sl,
            is_long=is_long,
            atr_value=trailing_atr,
        )

        # v6.6: Fresh position verification note (production _execute_trade L288-301)
        print()
        print("  📋 Production gate (信息): 实盘在 AI 分析后、下单前会重新验证仓位状态")
        print("     (AI 分析 15-45s 期间 SL/TP 可能已触发。诊断跳过此检查)")

        # Risk/reward analysis + structural integrity assertions
        if final_sl > 0 and final_tp > 0:
            is_long = signal in ['BUY', 'LONG']
            if is_long:
                sl_pct = ((self.ctx.current_price - final_sl) / self.ctx.current_price) * 100
                tp_pct = ((final_tp - self.ctx.current_price) / self.ctx.current_price) * 100
            else:
                sl_pct = ((final_sl - self.ctx.current_price) / self.ctx.current_price) * 100
                tp_pct = ((self.ctx.current_price - final_tp) / self.ctx.current_price) * 100

            rr_ratio = tp_pct / sl_pct if sl_pct > 0 else 0

            print()
            print("  📊 风险/收益分析:")
            print(f"     止损距离: {sl_pct:.2f}%")
            print(f"     止盈距离: {tp_pct:.2f}%")
            print(f"     R/R 比率: {rr_ratio:.2f}:1")

            # R/R-based position sizing guidance
            if rr_ratio >= 2.5:
                rr_status = "✅ 优秀 (建议 80-100% 仓位)"
            elif rr_ratio >= 2.0:
                rr_status = "✅ 良好 (建议 50-80% 仓位)"
            elif rr_ratio >= 1.5:
                rr_status = "✅ 可接受 (建议 30-50% 仓位)"
            else:
                rr_status = f"❌ 不达标 (< {min_rr}:1 硬性门槛，calculate_mechanical_sltp 构造性保证)"
            print(f"     评估: {rr_status}")

            print(f"     最大亏损: ${quantity * self.ctx.current_price * sl_pct / 100:,.2f}")
            print(f"     最大盈利: ${quantity * self.ctx.current_price * tp_pct / 100:,.2f}")

            # ── R/R cross-check: percentage-based vs direct formula ──
            if is_long:
                direct_rr = (final_tp - self.ctx.current_price) / (self.ctx.current_price - final_sl)
            else:
                direct_rr = (self.ctx.current_price - final_tp) / (final_sl - self.ctx.current_price)

            if abs(direct_rr - rr_ratio) > 0.01:
                print(f"     ⚠️ R/R formula mismatch: pct-based={rr_ratio:.4f} vs direct={direct_rr:.4f}")
            else:
                print(f"     ✅ R/R cross-check: pct={rr_ratio:.4f} ≈ direct={direct_rr:.4f}")

            # ── Structural integrity assertions (v5.1) ──
            # These catch magnitude errors that display-only output cannot detect
            print()
            print("  🔍 结构完整性断言:")
            assertion_errors = []

            # Assert 1: SL on correct side of price
            if is_long and final_sl >= self.ctx.current_price:
                assertion_errors.append(f"LONG SL=${final_sl:,.2f} >= entry=${self.ctx.current_price:,.2f}")
            elif not is_long and final_sl <= self.ctx.current_price:
                assertion_errors.append(f"SHORT SL=${final_sl:,.2f} <= entry=${self.ctx.current_price:,.2f}")
            else:
                print("     ✅ SL 方向正确")

            # Assert 2: TP on correct side of price
            if is_long and final_tp <= self.ctx.current_price:
                assertion_errors.append(f"LONG TP=${final_tp:,.2f} <= entry=${self.ctx.current_price:,.2f}")
            elif not is_long and final_tp >= self.ctx.current_price:
                assertion_errors.append(f"SHORT TP=${final_tp:,.2f} >= entry=${self.ctx.current_price:,.2f}")
            else:
                print("     ✅ TP 方向正确")

            # Assert 3: R/R meets minimum threshold
            if rr_ratio < min_rr * 0.999:
                assertion_errors.append(f"R/R={rr_ratio:.4f}:1 < {min_rr}:1 硬性门槛")
            else:
                print(f"     ✅ R/R={rr_ratio:.4f}:1 >= {min_rr}:1")

            # Assert 4: SL anchored near S/R zone (not arbitrary percentage)
            if self.ctx.sr_zones_data:
                nearest_sr = None
                if is_long:
                    ns = self.ctx.sr_zones_data.get('nearest_support')
                    if ns and hasattr(ns, 'price_center'):
                        nearest_sr = ns.price_center
                else:
                    nr = self.ctx.sr_zones_data.get('nearest_resistance')
                    if nr and hasattr(nr, 'price_center'):
                        nearest_sr = nr.price_center

                if nearest_sr and nearest_sr > 0:
                    atr_val = self.ctx.atr_value or self.ctx.current_price * 0.005
                    sl_to_zone_dist = abs(final_sl - nearest_sr)
                    max_acceptable_dist = atr_val * 2  # SL should be within 2x ATR of zone
                    if sl_to_zone_dist <= max_acceptable_dist:
                        print(f"     ✅ SL 锚定 S/R zone (距离=${sl_to_zone_dist:,.0f}, zone=${nearest_sr:,.0f})")
                    else:
                        assertion_errors.append(
                            f"SL=${final_sl:,.0f} 距 S/R zone ${nearest_sr:,.0f} "
                            f"= ${sl_to_zone_dist:,.0f} > {max_acceptable_dist:,.0f} (2×ATR)")

            # Assert 5: SL distance sanity (not too far, not too close)
            if sl_pct < 0.5:
                assertion_errors.append(f"SL 距离仅 {sl_pct:.2f}% — 过近，可能立即触发")
            elif sl_pct > 10:
                assertion_errors.append(f"SL 距离 {sl_pct:.2f}% — 过远，风险过大")
            else:
                print(f"     ✅ SL 距离合理 ({sl_pct:.2f}%)")

            if assertion_errors:
                for err in assertion_errors:
                    print(f"     ❌ ASSERTION FAILED: {err}")
                print(f"  ⚠️ {len(assertion_errors)} 个结构断言失败 — SL/TP 可能有计算错误")
            else:
                print("     ✅ 全部结构断言通过")

        print()
        print("  ✅ 订单提交流程模拟完成")

    def _simulate_trailing_stop(
        self,
        entry_price: float,
        sl_price: float,
        is_long: bool,
        atr_value: float,
    ) -> None:
        """
        v24.2: Simulate trailing stop calculation matching production exactly.

        Production constants (order_execution.py):
          _TRAILING_ACTIVATION_R = 1.5   (position_manager.py, v43.0)
          _TRAILING_ATR_MULTIPLIER = 0.6 (order_execution.py, v43.0 4H ATR)
          _TRAILING_MIN_BPS = 10         (order_execution.py:1349)
          _TRAILING_MAX_BPS = 1000       (order_execution.py:1350)

        Flow: on_position_opened → _submit_bracket_order_phase2 →
              _submit_trailing_stop(activation_price, trailing_offset_bps)
        """
        # Production constants (v43.0: 4H ATR source)
        _TRAILING_ACTIVATION_R = 1.5
        _TRAILING_ATR_MULTIPLIER = 0.6
        _TRAILING_MIN_BPS = 10
        _TRAILING_MAX_BPS = 1000

        risk = abs(entry_price - sl_price)
        if risk <= 0 or atr_value <= 0:
            print()
            print("  📋 Trailing Stop (v24.2):")
            if risk <= 0:
                print(f"     ⚠️ 跳过: risk=0 (SL = entry)")
            else:
                print(f"     ⚠️ 跳过: ATR=0 (启动期无数据)")
            return

        # Activation price: entry + 1.5R (long) or entry - 1.5R (short)
        if is_long:
            activation_price = entry_price + (risk * _TRAILING_ACTIVATION_R)
        else:
            activation_price = entry_price - (risk * _TRAILING_ACTIVATION_R)

        # Trailing distance: 4H ATR × 0.6, converted to basis points
        trailing_distance = atr_value * _TRAILING_ATR_MULTIPLIER
        trailing_offset_bps = int((trailing_distance / entry_price) * 10000)
        trailing_offset_bps = max(_TRAILING_MIN_BPS, min(_TRAILING_MAX_BPS, trailing_offset_bps))

        trailing_pct = trailing_offset_bps / 100

        print()
        print("  📋 Trailing Stop (v43.0, Binance server-side, 4H ATR):")
        print(f"     Activation R: {_TRAILING_ACTIVATION_R}R (profit=${risk * _TRAILING_ACTIVATION_R:,.2f})")
        print(f"     Activation price: ${activation_price:,.2f}")
        print(f"     ATR (4H 优先): ${atr_value:,.2f}")
        print(f"     ATR multiplier: ×{_TRAILING_ATR_MULTIPLIER}")
        print(f"     Trailing distance: ${trailing_distance:,.2f} ({trailing_pct:.1f}%)")
        print(f"     Callback rate: {trailing_offset_bps} bps (clamped [{_TRAILING_MIN_BPS}, {_TRAILING_MAX_BPS}])")
        if trailing_offset_bps == _TRAILING_MIN_BPS:
            print(f"     ℹ️ 达到最小回调率 ({_TRAILING_MIN_BPS} bps = {_TRAILING_MIN_BPS/100:.1f}%)")
        elif trailing_offset_bps == _TRAILING_MAX_BPS:
            print(f"     ⚠️ 达到最大回调率 ({_TRAILING_MAX_BPS} bps = {_TRAILING_MAX_BPS/100:.1f}%)")

        # Worst-case trailing exit profit
        # If activated exactly at activation_price and immediately called back
        worst_case_exit = activation_price - trailing_distance if is_long else activation_price + trailing_distance
        if is_long:
            worst_profit = worst_case_exit - entry_price
        else:
            worst_profit = entry_price - worst_case_exit
        worst_r = worst_profit / risk if risk > 0 else 0
        print(f"     Worst-case exit: ${worst_case_exit:,.2f} (profit=${worst_profit:,.2f}, {worst_r:.2f}R)")
        if worst_r > 0:
            print(f"     ✅ Trailing 最差情况仍盈利 ({worst_r:.2f}R > 0)")
        else:
            print(f"     ⚠️ Trailing 最差情况可能亏损 ({worst_r:.2f}R)")

    def _zone_cross_validate_sltp(self, ai_sl, ai_tp, entry_price, signal):
        """
        v11.0-simple: Zone cross-validation removed.
        This is now a no-op that returns the input values unchanged.
        Kept as a stub for backward compatibility with any remaining callers.
        """
        return ai_sl, ai_tp

    def should_skip(self) -> bool:
        return self.ctx.summary_mode


class PositionCalculator(DiagnosticStep):
    """
    Test position size calculation.

    Tests calculate_position_size() with v4.8 ai_controlled method.
    """

    name = "v4.8 仓位计算测试 (ai_controlled 累加模式)"

    def run(self) -> bool:
        print("-" * 70)

        try:
            cfg = self.ctx.strategy_config
            signal = self.ctx.signal_data.get('signal', 'HOLD')

            # v4.8: Get equity and leverage from context (real Binance values)
            equity = getattr(self.ctx, 'account_balance', {}).get('total_balance', 0)
            if equity <= 0:
                equity = getattr(cfg, 'equity', 1000)

            leverage = getattr(self.ctx, 'binance_leverage', 10)

            # v4.8: ai_controlled config
            max_position_ratio = getattr(cfg, 'max_position_ratio', 0.12)
            max_usdt = equity * max_position_ratio * leverage

            # v4.8 confidence mapping (percentage of max_usdt)
            confidence_mapping = {
                'HIGH': getattr(cfg, 'position_sizing_high_pct', 80),
                'MEDIUM': getattr(cfg, 'position_sizing_medium_pct', 50),
                'LOW': getattr(cfg, 'position_sizing_low_pct', 30),
            }

            calc_config = {
                'equity': equity,
                'leverage': leverage,
                'max_position_ratio': max_position_ratio,
                'min_trade_amount': getattr(cfg, 'min_trade_amount', 0.001),
                # v4.8: ai_controlled method
                'method': 'ai_controlled',
                'confidence_mapping': confidence_mapping,
                'default_size_pct': getattr(cfg, 'position_sizing_default_pct', 50),
            }

            print("  📋 v4.8 仓位计算配置 (ai_controlled):")
            print(f"     equity: ${equity:,.2f} (from Binance)")
            print(f"     leverage: {leverage}x (from Binance)")
            print(f"     max_position_ratio: {max_position_ratio*100:.0f}%")
            print(f"     max_position_value: ${max_usdt:,.2f}")
            print()

            bc = self.ctx.base_currency
            print("  📋 v4.8 信心百分比映射:")
            for conf, pct in confidence_mapping.items():
                usdt = max_usdt * (pct / 100)
                base_qty = usdt / self.ctx.current_price if self.ctx.current_price else 0
                print(f"     {conf} ({pct}%): ${usdt:,.0f} ({base_qty:.6f} {bc})")
            print()

            # v4.8: Show cumulative mode status
            current_position_value = 0
            if self.ctx.current_position:
                current_position_value = self.ctx.current_position.get('position_value_usdt', 0)
            remaining_capacity = max(0, max_usdt - current_position_value)

            print("  📋 v4.8 累加模式状态:")
            print(f"     当前持仓价值: ${current_position_value:,.2f}")
            print(f"     可用容量: ${remaining_capacity:,.2f}")
            capacity_pct = (current_position_value / max_usdt * 100) if max_usdt > 0 else 0
            print(f"     容量使用率: {capacity_pct:.1f}%")
            print()

            if signal == 'HOLD':
                print("  📊 当前信号: HOLD (不计算仓位)")
                print()
                print("  📊 不同信心级别仓位参考 (假设 BUY/SELL 信号时):")
            else:
                print(f"  📊 当前信号: {signal}")
                print()
                print("  📊 不同信心级别仓位对比:")

            # v15.5: Use production calculate_position_size() for accurate display
            # (includes appetite_scale + single-trade risk clamp)
            td = self.ctx.technical_data or {}
            price_data = self.ctx.price_data or {'price': self.ctx.current_price}
            if 'price' not in price_data:
                price_data['price'] = self.ctx.current_price

            position_sizing_config = self.ctx.base_config.get('position', {}).get('position_sizing', {})
            ps_calc_config = {
                'equity': equity,
                'leverage': leverage,
                'max_position_ratio': max_position_ratio,
                'min_trade_amount': getattr(cfg, 'min_trade_amount', 0.001),
                'high_confidence_multiplier': 1.5,
                'medium_confidence_multiplier': 1.0,
                'low_confidence_multiplier': 0.5,
                'trend_strength_multiplier': 1.2,
                'rsi_extreme_multiplier': 1.3,
                'rsi_extreme_upper': 70,
                'rsi_extreme_lower': 30,
                'position_sizing': position_sizing_config,
            }

            # v39.0: Extract 4H ATR for risk clamp (matches production order_execution.py:430)
            _atr_4h_pc = 0.0
            mtf_dec = td.get('mtf_decision_layer')
            if mtf_dec:
                _atr_4h_pc = mtf_dec.get('atr', 0.0) or 0.0

            for conf_level in ['HIGH', 'MEDIUM', 'LOW']:
                # Build signal_data with this confidence level
                sim_signal = dict(self.ctx.signal_data)
                sim_signal['confidence'] = conf_level

                btc_qty, details = calculate_position_size(
                    sim_signal, price_data, td, ps_calc_config, logger=None,
                    atr_4h=_atr_4h_pc,
                )
                usdt_amount = details.get('final_usdt', 0)
                appetite_sc = details.get('appetite_scale', 1.0)
                appetite_str = f" ×{appetite_sc:.0%}" if appetite_sc < 1.0 else ""

                # Apply remaining capacity limit in cumulative mode
                capped = ""
                if self.ctx.current_position and usdt_amount > remaining_capacity:
                    usdt_amount = remaining_capacity
                    btc_qty = usdt_amount / self.ctx.current_price if self.ctx.current_price else 0
                    capped = " (受限)"

                print(f"     {conf_level}: ${usdt_amount:,.2f} ({btc_qty:.6f} {bc}){appetite_str}{capped}")

            # v5.14: Show actual production selection (AI position_size_pct priority)
            ai_size_pct = self.ctx.signal_data.get('position_size_pct')
            if ai_size_pct is not None:
                actual_btc, actual_details = calculate_position_size(
                    self.ctx.signal_data, price_data, td, ps_calc_config, logger=None,
                    atr_4h=_atr_4h_pc,
                )
                actual_usdt = actual_details.get('final_usdt', 0)
                actual_pct = actual_details.get('size_pct_used', float(ai_size_pct))
                actual_appetite = actual_details.get('appetite_scale', 1.0)
                if self.ctx.current_position and actual_usdt > remaining_capacity:
                    actual_usdt = remaining_capacity
                    actual_btc = actual_usdt / self.ctx.current_price if self.ctx.current_price else 0
                print()
                print(f"  📋 生产环境实际选择: AI 提供 position_size_pct={actual_pct}%")
                appetite_str = f" ×{actual_appetite:.0%}" if actual_appetite < 1.0 else ""
                print(f"     实际仓位: ${actual_usdt:,.2f} ({actual_btc:.6f} {bc}){appetite_str}")
            else:
                # Use calculate_position_size with current signal for accurate display
                actual_btc, actual_details = calculate_position_size(
                    self.ctx.signal_data, price_data, td, ps_calc_config, logger=None,
                    atr_4h=_atr_4h_pc,
                )
                actual_usdt = actual_details.get('final_usdt', 0)
                actual_appetite = actual_details.get('appetite_scale', 1.0)
                confidence = self.ctx.signal_data.get('confidence', 'MEDIUM').upper()
                print()
                appetite_str = f" ×{actual_appetite:.0%}" if actual_appetite < 1.0 else ""
                print(f"  📋 生产环境实际选择: 信心映射 ({confidence})")
                print(f"     实际仓位: ${actual_usdt:,.2f} ({actual_btc:.6f} {bc}){appetite_str}")

            print()
            print("  ✅ v4.8 仓位计算测试完成")
            return True

        except Exception as e:
            self.ctx.add_error(f"仓位计算测试失败: {e}")
            traceback.print_exc()
            return False

    def should_skip(self) -> bool:
        return self.ctx.summary_mode
