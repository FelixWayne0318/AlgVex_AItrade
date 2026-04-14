"""
Report Formatter Mixin for MultiAgentAnalyzer

Extracted from multi_agent_analyzer.py for code organization.
Contains all data-to-text formatting methods used to prepare
AI prompt inputs from raw market data.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from agents.prompt_constants import _get_multiplier


class ReportFormatterMixin:
    """Mixin providing report formatting methods for MultiAgentAnalyzer."""

    def _format_technical_report(self, data: Dict[str, Any]) -> str:
        """Format technical data for prompts.

        v18.1: Restructured from timeframe-grouped to reliability-tier-grouped.
        Experiment validated: SKIP misuse 0.33→0, HIGH citation 1.33→3.33,
        MACD ranging awareness 33%→100%. Zero additional API calls.
        """
        if not data:
            return "Technical data not available"

        def safe_get(key, default=0):
            val = data.get(key)
            return float(val) if val is not None else default

        # v5.6: Prepend 1D TREND VERDICT at TOP of report so AI reads it first
        report = self._compute_trend_verdict(data)

        # Extract 1D ADX for regime-based tier classification
        _mtf_trend_data = data.get('mtf_trend_layer')
        _adx_1d = float(_mtf_trend_data.get('adx', 30)) if _mtf_trend_data and _mtf_trend_data.get('adx') is not None else 30.0

        # Determine regime name for display
        if _adx_1d >= 40:
            _regime_name = "STRONG TREND"
        elif _adx_1d >= 25:
            _regime_name = "WEAK TREND"
        else:
            _regime_name = "RANGING"

        # --- Always-visible price & volatility section ---
        period_hours = safe_get('period_hours')
        adx_30m = safe_get('adx')
        if adx_30m < 20:
            sr_note = "HIGH (~70% bounce rate, mean-reversion reliable)"
        elif adx_30m < 25:
            sr_note = "MODERATE (~50% bounce rate, confirm with volume)"
        elif adx_30m < 40:
            sr_note = "LOW (~25% bounce rate, S/R breakouts frequent)"
        else:
            sr_note = "VERY LOW (<25% bounce rate, counter-trend S/R historically poor)"

        # v19.1: ATR Extension Ratio — price displacement from SMA in ATR units
        ext_sma20 = safe_get('extension_ratio_sma_20')
        ext_sma50 = safe_get('extension_ratio_sma_50')
        ext_regime = data.get('extension_regime', 'N/A')

        # Build extension warning if overextended (v19.1.1: trend-aware)
        # v19.1.1 design: OVEREXTENDED + ADX>40 → NOTE (common & sustainable)
        #                  EXTREME → always WARNING (even ADX>40, >5 ATR is rare)
        ext_warning = ""
        if ext_regime == 'EXTREME':
            if _adx_1d >= 40:
                ext_warning = "\n⚠️ EXTENSION WARNING: Price is >5 ATR from SMA20 (EXTREME). Even in strong trends this is statistically rare — high probability of snapback. Monitor for exhaustion signals (ADX declining, DI convergence). Reduce position size significantly."
            else:
                ext_warning = "\n⚠️ EXTENSION WARNING: Price is EXTREMELY overextended (>5 ATR from SMA20). Mean-reversion pressure is very high. Entering in this direction carries significant snapback risk."
        elif ext_regime == 'OVEREXTENDED':
            if _adx_1d >= 40:
                ext_warning = "\nℹ️ EXTENSION NOTE: Price is >3 ATR from SMA20 (OVEREXTENDED). In strong trends (ADX>40) this is common and sustainable — not a reversal signal. Use for position sizing, not direction."
            else:
                ext_warning = "\n⚠️ EXTENSION WARNING: Price is overextended (>3 ATR from SMA20). Consider smaller position size or waiting for a pullback."

        # v20.0: ATR Volatility Regime — percentile-based environment classification
        vol_regime = data.get('volatility_regime', 'N/A')
        vol_pct = data.get('volatility_percentile', 0)
        atr_pct_val = data.get('atr_pct', 0)
        vol_warning = ""
        if vol_regime == 'EXTREME':
            vol_warning = "\n⚠️ EXTREME VOLATILITY (>90th percentile): High risk of whipsaws and stop-hunting. Reduce position size significantly or wait."
        elif vol_regime == 'HIGH':
            vol_warning = "\nℹ️ HIGH VOLATILITY (70-90th percentile): Widen stops and consider smaller position size."
        elif vol_regime == 'LOW':
            vol_warning = "\nℹ️ LOW VOLATILITY (<30th percentile): Squeeze environment — breakout may be imminent. Tighter stops viable."

        # v21.0: FR consecutive block context
        fr_block_ctx = data.get('fr_block_context')
        fr_block_warning = ""
        if fr_block_ctx and fr_block_ctx.get('consecutive_blocks', 0) >= 2:
            _fb_count = fr_block_ctx.get('consecutive_blocks', 0)
            _fb_dir = fr_block_ctx.get('blocked_direction', 'UNKNOWN').upper()
            _fb_exhaustion = fr_block_ctx.get('exhaustion_active', False)
            if _fb_exhaustion:
                fr_block_warning = (
                    f"\n🔄 FR TREND EXHAUSTION: Funding Rate has blocked {_fb_dir} entry "
                    f"{_fb_count}× consecutively. Market is structurally hostile to {_fb_dir}. "
                    f"Consider the OPPOSITE direction or HOLD — do NOT keep signaling {_fb_dir}."
                )
            else:
                fr_block_warning = (
                    f"\nℹ️ FR PRESSURE: Funding Rate has blocked {_fb_dir} entry "
                    f"{_fb_count}× consecutively. Elevated FR cost for {_fb_dir} direction."
                )

        report += f"""
=== PRICE & VOLATILITY (regime: {_regime_name}, 1D ADX={_adx_1d:.1f}) ===
- Current: ${safe_get('price'):,.2f}
- Period High ({period_hours:.0f}h): ${safe_get('period_high'):,.2f}
- Period Low ({period_hours:.0f}h): ${safe_get('period_low'):,.2f}
- Period Change ({period_hours:.0f}h): {safe_get('period_change_pct'):+.2f}%
- ATR(14): ${safe_get('atr'):,.2f} (use for SL/TP distance, NOT fixed %)
- Volatility Regime: {vol_regime} (ATR%={atr_pct_val:.3f}%, {vol_pct:.0f}th percentile)
  (LOW=<30pctl calm, NORMAL=30-70 standard, HIGH=70-90 elevated, EXTREME=>90 rare){vol_warning}
- Extension Ratio (SMA20): {ext_sma20:+.2f} ATR | (SMA50): {ext_sma50:+.2f} ATR — regime: {ext_regime}
  (|ratio| <2=NORMAL, 2-3=EXTENDED, 3-5=OVEREXTENDED, >5=EXTREME. Positive=above SMA, negative=below){ext_warning}
- S/R Reliability: {sr_note}{fr_block_warning}
"""

        # --- Collect all indicators with their tier classification ---
        indicators = []

        def add_ind(key, label, value_str, details=None, regime_note=None):
            nature, m, tier = _get_multiplier(key, _adx_1d)
            indicators.append({
                'label': label, 'value': value_str,
                'details': details or [], 'nature': nature,
                'multiplier': m, 'tier': tier,
                'regime_note': regime_note,
            })

        # 30M execution layer indicators (v18.2: 15M→30M migration)
        add_ind('30m_rsi', 'RSI (30M)', f"{safe_get('rsi'):.1f}",
                regime_note="Ranging: 30/70 overbought/oversold valid." if _adx_1d < 20 else
                            "Trending: Cardwell ranges (40-80 uptrend, 20-60 downtrend)." if _adx_1d >= 25 else None)

        add_ind('30m_macd', 'MACD (30M)', f"{safe_get('macd'):.4f}",
                details=[f"Signal: {safe_get('macd_signal'):.4f}, Histogram: {safe_get('macd_histogram'):.4f}"],
                regime_note="⚠️ 74-97% false positive rate in ranging markets." if _adx_1d < 20 else None)

        _di_plus_30m = safe_get('di_plus')
        _di_minus_30m = safe_get('di_minus')
        _di_cmp_30m = '>' if _di_plus_30m > _di_minus_30m else '<' if _di_plus_30m < _di_minus_30m else '='
        add_ind('30m_adx', 'ADX (30M)', f"{safe_get('adx'):.1f} ({data.get('adx_regime', 'N/A')})",
                details=[f"DI+: {_di_plus_30m:.1f} {_di_cmp_30m} DI-: {_di_minus_30m:.1f} → {data.get('adx_direction', 'N/A')}"])

        add_ind('30m_bb', 'BB Position (30M)', f"{safe_get('bb_position') * 100:.1f}%",
                details=[f"Upper: ${safe_get('bb_upper'):,.2f} | Middle: ${safe_get('bb_middle'):,.2f} | Lower: ${safe_get('bb_lower'):,.2f}"],
                regime_note="Ranging: Mean-reversion at bands (upper=overbought, lower=oversold)." if _adx_1d < 20 else
                            "Trending: Walking the band is NORMAL, not a reversal signal." if _adx_1d >= 25 else None)

        add_ind('30m_sma', 'SMA (30M)', f"5: ${safe_get('sma_5'):,.2f} | 20: ${safe_get('sma_20'):,.2f} | 50: ${safe_get('sma_50'):,.2f}",
                regime_note="⚠️ Whipsaws around SMA in ranging markets." if _adx_1d < 20 else None)

        add_ind('30m_volume', 'Volume Ratio (30M)', f"{safe_get('volume_ratio'):.2f}x average")

        # 4H decision layer indicators (if available)
        mtf_decision = data.get('mtf_decision_layer')
        if mtf_decision:
            def mtf_safe_get(key, default=0):
                val = mtf_decision.get(key)
                return float(val) if val is not None else default

            add_ind('4h_rsi', 'RSI (4H)', f"{mtf_safe_get('rsi'):.1f}")

            add_ind('4h_macd', 'MACD (4H)', f"{mtf_safe_get('macd'):.4f}",
                    details=[f"Signal: {mtf_safe_get('macd_signal'):.4f}"],
                    regime_note="⚠️ 74-97% false positive rate in ranging." if _adx_1d < 20 else None)

            mtf_di_plus = mtf_safe_get('di_plus')
            mtf_di_minus = mtf_safe_get('di_minus')
            _di_cmp_4h = '>' if mtf_di_plus > mtf_di_minus else '<' if mtf_di_plus < mtf_di_minus else '='
            add_ind('4h_adx_di', 'ADX/DI (4H)', f"ADX: {mtf_safe_get('adx'):.1f} ({mtf_decision.get('adx_regime', 'N/A')})",
                    details=[f"DI+: {mtf_di_plus:.1f} {_di_cmp_4h} DI-: {mtf_di_minus:.1f} → {'BULLISH' if mtf_di_plus > mtf_di_minus else 'BEARISH'}"])

            add_ind('4h_sma', 'SMA 20 (4H)', f"${mtf_safe_get('sma_20'):,.2f}",
                    details=[f"SMA 50: ${mtf_safe_get('sma_50'):,.2f}"])

            add_ind('4h_bb', 'BB Position (4H)', f"{mtf_safe_get('bb_position') * 100:.1f}%",
                    details=[f"Upper: ${mtf_safe_get('bb_upper'):,.2f} | Middle: ${mtf_safe_get('bb_middle'):,.2f} | Lower: ${mtf_safe_get('bb_lower'):,.2f}"])

            # v18 audit: ATR and Volume Ratio pass-through (previously dropped at strategy boundary)
            atr_4h = mtf_safe_get('atr')
            if atr_4h > 0:
                # v19.1: Compute 4H extension ratios inline
                ext_4h_details = [f"{atr_4h / data.get('price', 1) * 100:.2f}% of price" if data.get('price') else None]
                sma20_4h = mtf_safe_get('sma_20')
                if sma20_4h > 0 and data.get('price', 0) > 0:
                    ext_4h = round((data['price'] - sma20_4h) / atr_4h, 2)
                    ext_4h_details.append(f"Extension vs SMA20: {ext_4h:+.2f} ATR")
                add_ind('4h_atr', 'ATR (4H)', f"${atr_4h:,.2f}",
                        details=ext_4h_details)

            vol_ratio_4h = mtf_safe_get('volume_ratio', 1.0)
            vol_label = 'High Volume' if vol_ratio_4h > 1.5 else 'Low Volume' if vol_ratio_4h < 0.5 else 'Normal'
            add_ind('4h_vol_ratio', 'Volume Ratio (4H)', f"{vol_ratio_4h:.2f}x avg",
                    details=[vol_label])

        # 1D trend layer indicators (if available)
        mtf_trend = data.get('mtf_trend_layer')
        if mtf_trend:
            def trend_safe_get(key, default=0):
                val = mtf_trend.get(key)
                return float(val) if val is not None else default

            pct_vs_sma200 = ((data.get('price', 0) / trend_safe_get('sma_200') - 1) * 100) if trend_safe_get('sma_200') > 0 else 0
            add_ind('1d_sma200', 'SMA 200 (1D)', f"${trend_safe_get('sma_200'):,.2f}",
                    details=[f"Price vs SMA200: {'+' if pct_vs_sma200 > 0 else ''}{pct_vs_sma200:.2f}%"])

            add_ind('1d_macd', 'MACD (1D)', f"{trend_safe_get('macd'):.4f}",
                    details=[f"Signal: {trend_safe_get('macd_signal'):.4f}"])

            add_ind('1d_rsi', 'RSI (1D)', f"{trend_safe_get('rsi'):.1f}")

            trend_di_plus = trend_safe_get('di_plus')
            trend_di_minus = trend_safe_get('di_minus')
            add_ind('1d_adx_di', 'ADX/DI (1D)', f"ADX: {trend_safe_get('adx'):.1f} ({mtf_trend.get('adx_regime', 'UNKNOWN')})",
                    details=[f"DI+: {trend_di_plus:.1f}, DI-: {trend_di_minus:.1f}"])

            # v18 Item 21: 1D BB/ATR pass-through
            bb_pos_1d = trend_safe_get('bb_position', 0.5)
            if bb_pos_1d > 0.8:
                bb_context = "Upper band (overbought zone)"
            elif bb_pos_1d < 0.2:
                bb_context = "Lower band (oversold zone)"
            elif bb_pos_1d > 0.6:
                bb_context = "Above middle"
            elif bb_pos_1d < 0.4:
                bb_context = "Below middle"
            else:
                bb_context = "Near middle band"
            add_ind('1d_bb', 'BB Position (1D)', f"{bb_pos_1d * 100:.1f}%",
                    details=[f"Daily range context: {bb_context}"])

            atr_1d = trend_safe_get('atr')
            if atr_1d > 0:
                # v19.1: Compute 1D extension ratio inline (price vs SMA200 / ATR_1D)
                ext_1d_details = [f"Daily volatility scale (vs 30M ATR=${safe_get('atr'):,.2f})"]
                sma200_1d = trend_safe_get('sma_200')
                if sma200_1d > 0 and data.get('price', 0) > 0:
                    ext_1d = round((data['price'] - sma200_1d) / atr_1d, 2)
                    ext_1d_details.append(f"Extension vs SMA200: {ext_1d:+.2f} ATR (macro stretch)")
                add_ind('1d_atr', 'ATR (1D)', f"${atr_1d:,.2f}",
                        details=ext_1d_details)

        # v21.0: 1D TIME SERIES — trend exhaustion and ADX direction change detection
        if mtf_trend:
            hist_1d = mtf_trend.get('historical_context', {})
            if hist_1d and hist_1d.get('trend_direction') not in ['INSUFFICIENT_DATA', 'ERROR', None]:
                def format_series_1d(values, fmt=".1f"):
                    if not values or not isinstance(values, list):
                        return "N/A"
                    return " → ".join([f"{v:{fmt}}" for v in values])

                def annotate_trend_1d(values, name=""):
                    if not values or len(values) < 3:
                        return ""
                    first_third = values[:len(values)//3]
                    last_third = values[-(len(values)//3):]
                    avg_first = sum(first_third) / len(first_third)
                    avg_last = sum(last_third) / len(last_third)
                    pct_change = ((avg_last - avg_first) / abs(avg_first) * 100) if avg_first != 0 else 0
                    mn, mx = min(values), max(values)
                    if abs(pct_change) < 5:
                        return f"  → [TREND: Flat — range {mn:.1f}~{mx:.1f}]"
                    direction = "RISING" if pct_change > 0 else "FALLING"
                    return f"  → [TREND: {direction} {abs(pct_change):.0f}% — from ~{avg_first:.1f} to ~{avg_last:.1f}]"

                adx_1d_series = hist_1d.get('adx_trend', [])
                di_plus_1d_series = hist_1d.get('di_plus_trend', [])
                di_minus_1d_series = hist_1d.get('di_minus_trend', [])
                rsi_1d_series = hist_1d.get('rsi_trend', [])
                price_1d_series = hist_1d.get('price_trend', [])
                n_1d = len(adx_1d_series)

                if n_1d >= 2:
                    report += f"\n=== 1D TIME SERIES — 趋势强度演变 (last {n_1d} bars, ~{n_1d} days) ===\n"
                    report += f"1D ADX:       {format_series_1d(adx_1d_series)}\n"
                    report += f"{annotate_trend_1d(adx_1d_series, 'ADX')}\n"
                    if di_plus_1d_series:
                        report += f"1D DI+:       {format_series_1d(di_plus_1d_series)}\n"
                    if di_minus_1d_series:
                        report += f"1D DI-:       {format_series_1d(di_minus_1d_series)}\n"
                    if di_plus_1d_series and di_minus_1d_series and len(di_plus_1d_series) == len(di_minus_1d_series):
                        di_spread_1d = [p - m for p, m in zip(di_plus_1d_series, di_minus_1d_series)]
                        report += f"{annotate_trend_1d(di_spread_1d, 'DI Spread')}\n"
                    if rsi_1d_series and len(rsi_1d_series) >= 2:
                        report += f"1D RSI:       {format_series_1d(rsi_1d_series)}\n"
                        report += f"{annotate_trend_1d(rsi_1d_series, 'RSI')}\n"
                    if price_1d_series and len(price_1d_series) >= 2:
                        report += f"1D PRICE:     {format_series_1d(price_1d_series, ',.0f')}\n"
                        report += f"{annotate_trend_1d(price_1d_series, 'Price')}\n"

        # --- Group indicators by tier and format ---
        tiers = {'high': [], 'std': [], 'low': [], 'skip': []}
        for ind in indicators:
            tiers[ind['tier']].append(ind)

        tier_configs = [
            ('high', '🟢 PRIMARY EVIDENCE', 'HIGH reliability ≥1.2 in current regime',
             'Build your thesis on these indicators.'),
            ('std', '🟡 SUPPORTING EVIDENCE', 'STD reliability 0.8-1.1',
             'Use to CONFIRM primary signals, not as standalone basis.'),
            ('low', '⚪ LOW CONFIDENCE', 'multiplier 0.5-0.7, needs confirmation',
             'Do NOT use as primary evidence.'),
            ('skip', '❌ UNRELIABLE IN CURRENT REGIME', 'SKIP, multiplier <0.5',
             'Noise in this regime. Using these as evidence is an analytical error.'),
        ]

        for tier_key, tier_label, tier_desc, tier_instruction in tier_configs:
            tier_indicators = tiers[tier_key]
            if not tier_indicators:
                continue
            report += f"\n=== {tier_label} ({tier_desc}) ===\n"
            report += f"{tier_instruction}\n\n"
            for ind in tier_indicators:
                m_str = f"{ind['multiplier']:.1f}x" if ind['multiplier'] >= 0.5 else "SKIP"
                report += f"- {ind['label']}: {ind['value']} — {ind['nature']}, {m_str}\n"
                for detail in ind['details']:
                    report += f"  {detail}\n"
                if ind['regime_note']:
                    report += f"  → {ind['regime_note']}\n"

        # v18 Item 7fmt/19: 4H TIME SERIES (promoted to front half for primacy)
        mtf_decision = data.get('mtf_decision_layer')
        if mtf_decision:
            # v19.1 fix: Initialize before conditional blocks so 4H CVD-Price code doesn't hit UnboundLocalError
            price_4h_series = []
            hist_4h = mtf_decision.get('historical_context', {})
            if hist_4h and hist_4h.get('trend_direction') not in ['INSUFFICIENT_DATA', 'ERROR', None]:
                def format_series(values, fmt=".1f"):
                    if not values or not isinstance(values, list):
                        return "N/A"
                    return " → ".join([f"{v:{fmt}}" for v in values])

                def annotate_trend(values, name=""):
                    """v18 Item 19: Per-series trend annotation."""
                    if not values or len(values) < 3:
                        return ""
                    first_third = values[:len(values)//3]
                    last_third = values[-(len(values)//3):]
                    avg_first = sum(first_third) / len(first_third)
                    avg_last = sum(last_third) / len(last_third)
                    pct_change = ((avg_last - avg_first) / abs(avg_first) * 100) if avg_first != 0 else 0
                    mn, mx = min(values), max(values)
                    if abs(pct_change) < 5:
                        return f"  → [TREND: Flat — range {mn:.1f}~{mx:.1f}]"
                    direction = "RISING" if pct_change > 0 else "FALLING"
                    return f"  → [TREND: {direction} {abs(pct_change):.0f}% — from ~{avg_first:.1f} to ~{avg_last:.1f}]"

                rsi_4h_series = hist_4h.get('rsi_trend', [])
                macd_hist_4h_series = hist_4h.get('macd_histogram_trend', [])
                adx_4h_series = hist_4h.get('adx_trend', [])
                di_plus_4h_series = hist_4h.get('di_plus_trend', [])
                di_minus_4h_series = hist_4h.get('di_minus_trend', [])
                # v19.1: Initialize price_4h_series here (used by divergence + CVD-Price analysis below)
                price_4h_series = hist_4h.get('price_trend', [])
                n_4h = len(rsi_4h_series)

                if n_4h >= 2:
                    report += f"\n=== 4H TIME SERIES — 方向判断核心 (last {n_4h} bars, ~{n_4h * 4 / 24:.1f} days) ===\n"
                    report += f"4H RSI:       {format_series(rsi_4h_series)}\n"
                    report += f"{annotate_trend(rsi_4h_series, 'RSI')}\n"

                    if macd_hist_4h_series:
                        report += f"4H MACD Hist: {format_series(macd_hist_4h_series, '.4f')}\n"
                        report += f"{annotate_trend(macd_hist_4h_series, 'MACD Hist')}\n"
                    else:
                        # Compute histogram from MACD and signal series
                        macd_4h_series = hist_4h.get('macd_trend', [])
                        macd_sig_4h_series = hist_4h.get('macd_signal_trend', [])
                        if macd_4h_series and macd_sig_4h_series and len(macd_4h_series) == len(macd_sig_4h_series):
                            computed_hist = [m - s for m, s in zip(macd_4h_series, macd_sig_4h_series)]
                            report += f"4H MACD Hist: {format_series(computed_hist, '.4f')}\n"
                            report += f"{annotate_trend(computed_hist, 'MACD Hist')}\n"
                            # v19.1: Use computed histogram for divergence detection
                            macd_hist_4h_series = computed_hist

                    if adx_4h_series:
                        report += f"4H ADX:       {format_series(adx_4h_series)}\n"
                        report += f"{annotate_trend(adx_4h_series, 'ADX')}\n"
                    if di_plus_4h_series:
                        report += f"4H DI+:       {format_series(di_plus_4h_series)}\n"
                    if di_minus_4h_series:
                        report += f"4H DI-:       {format_series(di_minus_4h_series)}\n"
                    # v18 Item 19: DI spread annotation (DI+ - DI- trend)
                    if di_plus_4h_series and di_minus_4h_series and len(di_plus_4h_series) == len(di_minus_4h_series):
                        di_spread = [p - m for p, m in zip(di_plus_4h_series, di_minus_4h_series)]
                        report += f"{annotate_trend(di_spread, 'DI Spread')}\n"

                    # v18 audit: 4H price/volume/BB-width series (previously computed but not formatted)
                    if price_4h_series and len(price_4h_series) >= 2:
                        report += f"4H PRICE:     {format_series(price_4h_series, ',.0f')}\n"
                        report += f"{annotate_trend(price_4h_series, 'Price')}\n"

                    volume_4h_series = hist_4h.get('volume_trend', [])
                    if volume_4h_series and price_4h_series and len(volume_4h_series) == len(price_4h_series):
                        # Convert base-currency volume to USDT (same approach as 30M, line 3114)
                        vol_usdt = [v * p for v, p in zip(volume_4h_series, price_4h_series)]
                        report += f"4H VOLUME:    {format_series(vol_usdt, ',.0f')} USDT\n"
                        report += f"{annotate_trend(vol_usdt, 'Volume')}\n"
                    elif volume_4h_series and len(volume_4h_series) >= 2:
                        report += f"4H VOLUME:    {format_series(volume_4h_series, ',.0f')}\n"

                    bb_width_4h_series = hist_4h.get('bb_width_trend', [])
                    if bb_width_4h_series and len(bb_width_4h_series) >= 2:
                        report += f"4H BB WIDTH:  {format_series(bb_width_4h_series, '.2f')} (% of middle band)\n"
                        report += f"{annotate_trend(bb_width_4h_series, 'BB Width')}\n"

                    # v20.0: OBV divergence (EMA-smoothed) alongside RSI/MACD
                    obv_4h_raw = hist_4h.get('obv_trend', [])
                    obv_4h_smoothed = self._ema_smooth(obv_4h_raw, period=20) if len(obv_4h_raw) >= 20 else []
                    # Align length: trim to match price_4h_series if needed
                    if obv_4h_smoothed and len(obv_4h_smoothed) != len(price_4h_series):
                        min_len = min(len(obv_4h_smoothed), len(price_4h_series))
                        obv_4h_smoothed = obv_4h_smoothed[-min_len:]

                    # v19.1: 4H divergence pre-computation (RSI-Price, MACD-Price, OBV-Price)
                    divergence_tags = self._detect_divergences(
                        price_series=price_4h_series,
                        rsi_series=rsi_4h_series,
                        macd_hist_series=macd_hist_4h_series,
                        obv_series=obv_4h_smoothed if len(obv_4h_smoothed) >= 5 else None,
                        timeframe="4H",
                    )
                    if divergence_tags:
                        report += "\n=== 4H DIVERGENCE DETECTION (pre-computed) ===\n"
                        for tag in divergence_tags:
                            report += f"{tag}\n"

            # v18 Item 16: 4H CVD order flow
            order_flow_4h = data.get('order_flow_4h')
            if order_flow_4h:
                cvd_trend = order_flow_4h.get('cvd_trend', 'N/A')
                buy_ratio = order_flow_4h.get('buy_ratio', 0)
                cvd_cum = order_flow_4h.get('cvd_cumulative', 0)
                cvd_history = order_flow_4h.get('cvd_history', [])
                # v18 audit: Extract previously dropped fields
                volume_usdt_4h = order_flow_4h.get('volume_usdt', 0)
                trades_count_4h = order_flow_4h.get('trades_count', 0)
                avg_trade_4h = order_flow_4h.get('avg_trade_usdt', 0)
                recent_10_4h = order_flow_4h.get('recent_10_bars', [])

                report += f"\n=== 4H CVD ORDER FLOW — 方向判断核心 ===\n"
                report += f"- Buy Ratio (4H avg): {buy_ratio:.1%}\n"
                report += f"- CVD Trend: {cvd_trend}, Cumulative: {cvd_cum:+,.0f}\n"
                if cvd_history:
                    recent = cvd_history[-10:] if len(cvd_history) > 10 else cvd_history
                    report += f"- CVD History (last {len(recent)} bars): [{', '.join(f'{v:+,.0f}' for v in recent)}]\n"
                if volume_usdt_4h:
                    report += f"- Volume (USDT): ${volume_usdt_4h:,.0f}\n"
                if trades_count_4h:
                    report += f"- Avg Trade Size: ${avg_trade_4h:,.0f} USDT | Trades: {trades_count_4h:,}\n"
                if recent_10_4h:
                    recent_str = ", ".join([f"{r:.1%}" for r in recent_10_4h])
                    report += f"- Recent {len(recent_10_4h)} Bars Buy Ratio: [{recent_str}]\n"

                # v19.2: 4H CVD-Price divergence detection (time-aligned)
                # Use last 5 bars of 4H price (~20h) to match CVD 5-bar window, not full series (~64h)
                if cvd_history and len(cvd_history) >= 3 and price_4h_series and len(price_4h_series) >= 2:
                    _p4h_window = price_4h_series[-5:] if len(price_4h_series) >= 5 else price_4h_series
                    price_4h_change = ((_p4h_window[-1] - _p4h_window[0]) / _p4h_window[0] * 100) if _p4h_window[0] > 0 else 0
                    cvd_net_4h = sum(cvd_history[-5:]) if len(cvd_history) >= 5 else sum(cvd_history)
                    _p4h_flat = abs(price_4h_change) <= 0.3
                    if price_4h_change < -0.3 and cvd_net_4h > 0:
                        report += (
                            f"  → [4H CVD-PRICE DIVERGENCE: Price falling ({price_4h_change:+.1f}%) "
                            f"but CVD net positive ({cvd_net_4h:+,.0f}) — ACCUMULATION at 4H level]\n"
                        )
                    elif price_4h_change > 0.3 and cvd_net_4h < 0:
                        report += (
                            f"  → [4H CVD-PRICE DIVERGENCE: Price rising ({price_4h_change:+.1f}%) "
                            f"but CVD net negative ({cvd_net_4h:+,.0f}) — DISTRIBUTION at 4H level]\n"
                        )
                    elif price_4h_change < -0.3 and cvd_net_4h < 0:
                        report += (
                            f"  → [4H CVD-PRICE CONFIRM: Price falling ({price_4h_change:+.1f}%) "
                            f"with CVD negative ({cvd_net_4h:+,.0f}) — CONFIRMED selling at 4H level]\n"
                        )
                    elif _p4h_flat and cvd_net_4h > 0:
                        report += (
                            f"  → [4H CVD-PRICE ABSORPTION: Price flat ({price_4h_change:+.1f}%) "
                            f"despite CVD positive ({cvd_net_4h:+,.0f}) — passive seller absorbing buys at 4H level]\n"
                        )
                    elif _p4h_flat and cvd_net_4h < 0:
                        report += (
                            f"  → [4H CVD-PRICE ABSORPTION: Price flat ({price_4h_change:+.1f}%) "
                            f"despite CVD negative ({cvd_net_4h:+,.0f}) — passive buyer absorbing sells at 4H level]\n"
                        )

        # v18 Items 10b, 15 P5-P9: 30M EXECUTION DATA (de-weighted)
        historical = data.get('historical_context')
        if historical and historical.get('trend_direction') not in ['INSUFFICIENT_DATA', 'ERROR', None]:
            trend_dir = historical.get('trend_direction', 'N/A')
            momentum = historical.get('momentum_shift', 'N/A')
            price_change = historical.get('price_change_pct', 0)
            vol_ratio = historical.get('current_volume_ratio', 1.0)

            def format_all_values(values, fmt=".1f"):
                if not values or not isinstance(values, list):
                    return "N/A"
                return " → ".join([f"{v:{fmt}}" for v in values])

            price_trend = historical.get('price_trend', [])
            rsi_trend = historical.get('rsi_trend', [])
            macd_trend = historical.get('macd_trend', [])
            volume_trend = historical.get('volume_trend', [])
            n_bars = len(price_trend)
            hours_covered = n_bars * 30 / 60  # v18 Item 15 P6: 30min bars → hours

            report += f"""
=== 30M EXECUTION DATA (⚠️ 仅用于入场时机评估, 不用于方向判断) ===
=== Last {n_bars} bars, ~{hours_covered:.1f} hours ===

TREND ANALYSIS:
- Overall Direction: {trend_dir}
- Momentum Shift: {momentum}
- Price Change: {price_change:+.2f}% over {n_bars} bars
- Current Volume vs Avg: {vol_ratio:.2f}x

PRICE SERIES ({n_bars} bars, 30min each):
{format_all_values(price_trend, ",.0f")}

RSI SERIES ({len(rsi_trend)} values):
{format_all_values(rsi_trend)}

MACD SERIES ({len(macd_trend)} values):
{format_all_values(macd_trend, ".4f")}

MACD HISTOGRAM SERIES ({len(historical.get('macd_histogram_trend', []))} values):
{format_all_values(historical.get('macd_histogram_trend', []), ".4f")}

VOLUME SERIES ({len(volume_trend)} values, USDT, converted from {getattr(self, '_base_currency', 'BTC')}):
{format_all_values([v * p for v, p in zip(volume_trend, price_trend)] if price_trend and len(price_trend) == len(volume_trend) else volume_trend, ",.0f")}
"""
            # v3.24: ADX/DI history (trend strength trajectory)
            adx_trend = historical.get('adx_trend', [])
            di_plus_trend = historical.get('di_plus_trend', [])
            di_minus_trend = historical.get('di_minus_trend', [])
            if adx_trend and len(adx_trend) >= 2:
                report += f"""
ADX SERIES ({len(adx_trend)} values):
{format_all_values(adx_trend)}

DI+ SERIES:
{format_all_values(di_plus_trend)}

DI- SERIES:
{format_all_values(di_minus_trend)}
"""

            # v3.24: BB Width history (volatility squeeze/expansion)
            bb_width_trend = historical.get('bb_width_trend', [])
            if bb_width_trend and len(bb_width_trend) >= 2:
                report += f"""
BB WIDTH SERIES ({len(bb_width_trend)} values, % of middle band):
{format_all_values(bb_width_trend, ".2f")}
"""

            # v3.24: SMA history for crossover detection
            sma_history = historical.get('sma_history', {})
            if sma_history:
                report += "\nSMA SERIES (for crossover detection):\n"
                for sma_key, sma_vals in sorted(sma_history.items()):
                    if sma_vals and len(sma_vals) >= 2:
                        report += f"{sma_key.upper()} ({len(sma_vals)} values): {format_all_values(sma_vals, ',.0f')}\n"

            # v20.0: 30M OBV divergence (EMA-smoothed)
            obv_30m_raw = historical.get('obv_trend', [])
            obv_30m_smoothed = self._ema_smooth(obv_30m_raw, period=20) if len(obv_30m_raw) >= 20 else []
            if obv_30m_smoothed and len(obv_30m_smoothed) != len(price_trend):
                min_len = min(len(obv_30m_smoothed), len(price_trend))
                obv_30m_smoothed = obv_30m_smoothed[-min_len:]

            # v19.1: 30M divergence pre-computation (+ v20.0 OBV)
            macd_hist_30m = historical.get('macd_histogram_trend', [])
            divergence_tags_30m = self._detect_divergences(
                price_series=price_trend,
                rsi_series=rsi_trend,
                macd_hist_series=macd_hist_30m,
                obv_series=obv_30m_smoothed if len(obv_30m_smoothed) >= 5 else None,
                timeframe="30M",
            )
            if divergence_tags_30m:
                report += "\n30M DIVERGENCE DETECTION (pre-computed, entry timing only):\n"
                for tag in divergence_tags_30m:
                    report += f"{tag}\n"

        # v3.21: Add K-line OHLCV data (让 AI 看到实际价格形态)
        kline_ohlcv = data.get('kline_ohlcv')
        if kline_ohlcv and isinstance(kline_ohlcv, list) and len(kline_ohlcv) > 0:
            n_klines = len(kline_ohlcv)
            report += f"""
=== 30M K-LINE OHLCV (⚠️ 入场形态参考, 不用于方向判断) ===
=== Last {n_klines} bars ===
"""
            report += "Time            | Open      | High      | Low       | Close     | Volume\n"
            report += "-" * 85 + "\n"
            for bar in kline_ohlcv:
                ts = bar.get('timestamp', 0)
                try:
                    # NautilusTrader ts_init is in nanoseconds
                    time_str = datetime.utcfromtimestamp(ts / 1e9).strftime('%m-%d %H:%M') if ts > 1e15 else (
                        datetime.utcfromtimestamp(ts / 1000).strftime('%m-%d %H:%M') if ts > 1e10 else
                        datetime.utcfromtimestamp(ts).strftime('%m-%d %H:%M') if ts > 0 else "N/A"
                    )
                except (OSError, ValueError) as e:
                    self.logger.debug(f"Using default value, original error: {e}")
                    time_str = "N/A"
                o = bar.get('open', 0)
                h = bar.get('high', 0)
                l = bar.get('low', 0)
                c = bar.get('close', 0)
                v = bar.get('volume', 0)
                report += f"{time_str:<15} | ${o:>8,.0f} | ${h:>8,.0f} | ${l:>8,.0f} | ${c:>8,.0f} | {v:>8,.1f}\n"

        return report

    @staticmethod
    def compute_scores_from_features(f: Dict[str, Any]) -> Dict[str, Any]:
        """
        v28.0: Compute dimensional scores from feature dict (structured path).

        Takes the same feature_dict used by structured Bull/Bear/Judge/Risk
        and produces a compact scores dict for prompt anchoring.

        Parameters
        ----------
        f : Dict
            Feature dictionary (flat keys like rsi_30m, adx_1d, etc.)

        Returns
        -------
        Dict with keys: trend, momentum, order_flow, vol_risk, risk_env, net
        """
        def sg(key, default=0):
            val = f.get(key)
            if val is None:
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        # ── Trend Alignment ── (v39.0: rebalanced 1D↓ 4H↑)
        # v40.0 Phase 1b: Weighted voting by information density (Layer A).
        # Higher weight = higher certainty/information content.
        # Replaces equal ±1 voting that treated CVD-Price cross same as buy_ratio.
        trend_weighted = []  # (signal, weight) tuples

        # 1D SMA200 — macro filter, highest certainty (Trend)
        sma200 = sg('sma_200_1d')
        price = sg('price')
        if sma200 > 0 and price > 0:
            above = price > sma200
            trend_weighted.append((1 if above else -1, 1.5))

        # 1D ADX direction (Trend)
        adx_dir = f.get('adx_direction_1d', '')
        if adx_dir == 'BULLISH':
            trend_weighted.append((1, 1.2))
        elif adx_dir == 'BEARISH':
            trend_weighted.append((-1, 1.2))
        else:
            trend_weighted.append((0, 1.2))

        # 1D DI spread (Trend)
        di_p_1d = sg('di_plus_1d')
        di_m_1d = sg('di_minus_1d')
        if di_p_1d > di_m_1d + 2:
            trend_weighted.append((1, 0.8))
        elif di_m_1d > di_p_1d + 2:
            trend_weighted.append((-1, 0.8))
        else:
            trend_weighted.append((0, 0.8))

        # 1D RSI: weak trend signal in trend dimension (Momentum)
        rsi_1d = sg('rsi_1d', 50)
        if rsi_1d > 55:
            trend_weighted.append((1, 0.6))
        elif rsi_1d < 45:
            trend_weighted.append((-1, 0.6))
        else:
            trend_weighted.append((0, 0.6))

        # 1D MACD direction (Trend)
        macd_1d = sg('macd_1d')
        macd_sig_1d = sg('macd_signal_1d')
        if macd_1d > macd_sig_1d:
            trend_weighted.append((1, 1.0))
        elif macd_1d < macd_sig_1d:
            trend_weighted.append((-1, 1.0))
        else:
            trend_weighted.append((0, 1.0))

        # 1D ADX trend: rising ADX = trend gaining strength (Trend)
        # v36.2: NEUTRAL adx_dir → 0 (no directional signal when DI are equal)
        adx_1d_trend = f.get('adx_1d_trend_5bar', '')
        if adx_1d_trend == 'RISING':
            trend_weighted.append((1 if adx_dir == 'BULLISH' else (-1 if adx_dir == 'BEARISH' else 0), 0.7))
        elif adx_1d_trend == 'FALLING':
            trend_weighted.append((0, 0.7))  # Trend weakening

        # 4H RSI+MACD combined (Momentum)
        rsi_4h = sg('rsi_4h', 50)
        macd_4h = sg('macd_4h')
        macd_sig_4h = sg('macd_signal_4h')
        if rsi_4h > 55 and macd_4h > macd_sig_4h:
            trend_weighted.append((1, 0.5))
        elif rsi_4h < 45 and macd_4h < macd_sig_4h:
            trend_weighted.append((-1, 0.5))
        else:
            trend_weighted.append((0, 0.5))

        # 4H SMA cross (SMA20 vs SMA50) — medium-term trend (Trend)
        sma_20_4h = sg('sma_20_4h')
        sma_50_4h = sg('sma_50_4h')
        if sma_20_4h > 0 and sma_50_4h > 0:
            if sma_20_4h > sma_50_4h:
                trend_weighted.append((1, 0.8))
            elif sma_20_4h < sma_50_4h:
                trend_weighted.append((-1, 0.8))

        # 4H EMA cross (EMA12 vs EMA26) (Trend)
        ema_12_4h = sg('ema_12_4h')
        ema_26_4h = sg('ema_26_4h')
        if ema_12_4h > 0 and ema_26_4h > 0:
            if ema_12_4h > ema_26_4h:
                trend_weighted.append((1, 0.7))
            elif ema_12_4h < ema_26_4h:
                trend_weighted.append((-1, 0.7))

        # v40.0 Phase 1: Removed 3 duplicate 4H votes (v39.0).
        # 4H DI/RSI/MACD standalone were double-counted (trend + momentum).

        # 30M RSI+MACD combined — limited trend contribution (Momentum)
        rsi_30m = sg('rsi_30m', 50)
        macd_30m = sg('macd_30m')
        macd_sig_30m = sg('macd_signal_30m')
        if rsi_30m > 55 and macd_30m > macd_sig_30m:
            trend_weighted.append((1, 0.5))
        elif rsi_30m < 45 and macd_30m < macd_sig_30m:
            trend_weighted.append((-1, 0.5))
        else:
            trend_weighted.append((0, 0.5))

        # 1D DI spread trend: WIDENING = trend strengthening, NARROWING = exhaustion
        # v36.2: NEUTRAL adx_dir → 0 (spread change meaningless without direction)
        di_spread_trend = f.get('di_spread_1d_trend_5bar', '')
        if di_spread_trend == 'WIDENING':
            trend_weighted.append((1 if adx_dir == 'BULLISH' else (-1 if adx_dir == 'BEARISH' else 0), 0.8))
        elif di_spread_trend == 'NARROWING':
            trend_weighted.append((-1 if adx_dir == 'BULLISH' else (1 if adx_dir == 'BEARISH' else 0), 0.8))

        # v40.0: Compute weighted trend score
        if trend_weighted:
            _tw_sum = sum(s * w for s, w in trend_weighted)
            _tw_total = sum(w for _, w in trend_weighted)
            trend_raw = _tw_sum / _tw_total if _tw_total > 0 else 0
            trend_score = round(abs(trend_raw) * 10)
            trend_dir = "BULLISH" if trend_raw > 0.15 else ("BEARISH" if trend_raw < -0.15 else "NEUTRAL")
        else:
            trend_score, trend_dir = 0, "N/A"

        # ── Momentum Quality ──
        # v40.0 Phase 1b: Weighted voting by information density (Layer A).
        mom_weighted = []  # (signal, weight) tuples
        rsi_4h_trend = f.get('rsi_4h_trend_5bar', '')
        macd_hist_trend = f.get('macd_histogram_4h_trend_5bar', '')

        # RSI 4H trend direction (Momentum)
        if rsi_4h_trend == 'RISING':
            mom_weighted.append((1, 1.0))
        elif rsi_4h_trend == 'FALLING':
            mom_weighted.append((-1, 1.0))

        # v38.2 FIX: _classify_abs_trend() outputs EXPANDING/CONTRACTING/FLAT
        # Semantics: sign = direction, EXPANDING = strengthening, CONTRACTING = weakening.
        macd_hist_4h = sg('macd_histogram_4h')
        if macd_hist_trend != 'CONTRACTING':  # EXPANDING or FLAT: valid signal
            if macd_hist_4h > 0:
                mom_weighted.append((1, 1.2))   # Momentum (MACD histogram), higher weight
            elif macd_hist_4h < 0:
                mom_weighted.append((-1, 1.2))

        # 4H ADX trend: rising ADX = strengthening trend momentum
        adx_4h_trend = f.get('adx_4h_trend_5bar', '')
        if adx_4h_trend == 'RISING':
            mom_weighted.append((1, 0.8))
        elif adx_4h_trend == 'FALLING':
            mom_weighted.append((-1, 0.8))

        # 4H DI directional pressure
        di_p_4h = sg('di_plus_4h')
        di_m_4h = sg('di_minus_4h')
        if di_p_4h > 0 and di_m_4h > 0:
            if di_p_4h > di_m_4h + 5:
                mom_weighted.append((1, 0.7))
            elif di_m_4h > di_p_4h + 5:
                mom_weighted.append((-1, 0.7))

        # Volume confirmation: high volume validates momentum
        vol_4h = sg('volume_ratio_4h', 1.0)
        if vol_4h > 1.5:
            mom_weighted.append((1, 0.9))
        elif vol_4h < 0.5:
            mom_weighted.append((-1, 0.9))

        # 30M execution layer momentum direction
        rsi_30m_trend = f.get('rsi_30m_trend_5bar', '')
        if rsi_30m_trend == 'RISING':
            mom_weighted.append((1, 0.6))
        elif rsi_30m_trend == 'FALLING':
            mom_weighted.append((-1, 0.6))

        # 30M momentum acceleration/deceleration
        mom_shift = str(f.get('momentum_shift_30m', '')).upper()
        if mom_shift == 'ACCELERATING':
            mom_weighted.append((1, 0.8))
        elif mom_shift == 'DECELERATING':
            mom_weighted.append((-1, 0.8))

        # 4H price change: price momentum confirmation
        price_4h_chg = sg('price_4h_change_5bar_pct', 0)
        if price_4h_chg > 1.0:
            mom_weighted.append((1, 0.7))
        elif price_4h_chg < -1.0:
            mom_weighted.append((-1, 0.7))

        # v29.2: 4H BB position as momentum context (weak signal)
        bb_pos_4h = sg('bb_position_4h', 0.5)
        if bb_pos_4h > 0.8:
            mom_weighted.append((1, 0.5))
        elif bb_pos_4h < 0.2:
            mom_weighted.append((-1, 0.5))

        # v29.2: 30M MACD histogram direction
        macd_hist_30m = sg('macd_histogram_30m')
        if macd_hist_30m > 0:
            mom_weighted.append((1, 0.6))
        elif macd_hist_30m < 0:
            mom_weighted.append((-1, 0.6))

        # v40.0 P0-6: Divergence signals moved OUT of momentum voting.
        # They are reversal warnings and should not be diluted by ~10 trend-following signals.
        # Applied as trend_score modifier below (mutual exclusion with v39.0 reversal detection).
        div_bull = sum(1 for d in [
            f.get('rsi_divergence_4h', 'NONE'),
            f.get('macd_divergence_4h', 'NONE'),
            f.get('obv_divergence_4h', 'NONE'),
            f.get('rsi_divergence_30m', 'NONE'),
            f.get('macd_divergence_30m', 'NONE'),
            f.get('obv_divergence_30m', 'NONE'),
        ] if d == 'BULLISH')
        div_bear = sum(1 for d in [
            f.get('rsi_divergence_4h', 'NONE'),
            f.get('macd_divergence_4h', 'NONE'),
            f.get('obv_divergence_4h', 'NONE'),
            f.get('rsi_divergence_30m', 'NONE'),
            f.get('macd_divergence_30m', 'NONE'),
            f.get('obv_divergence_30m', 'NONE'),
        ] if d == 'BEARISH')

        # v40.0: Compute weighted momentum score
        if mom_weighted:
            _mw_sum = sum(s * w for s, w in mom_weighted)
            _mw_total = sum(w for _, w in mom_weighted)
            mom_raw = _mw_sum / _mw_total if _mw_total > 0 else 0
            mom_score = round(abs(mom_raw) * 10)
            mom_dir = "BULLISH" if mom_raw > 0.15 else ("BEARISH" if mom_raw < -0.15 else "FADING")
        else:
            mom_score, mom_dir = 0, "N/A"

        # ── Order Flow ──
        # v40.0 Phase 1b: Weighted by information density (Layer A).
        # CVD-Price cross (smart money behavior) >> CVD trend >> buy_ratio (noise).
        _avail_order_flow = f.get('_avail_order_flow', True)
        flow_weighted = []  # (signal, weight) tuples

        # CVD trend 30M (Order Flow)
        cvd_30m = str(f.get('cvd_trend_30m', '')).upper()
        if cvd_30m == 'POSITIVE':
            flow_weighted.append((1, 0.8))
        elif cvd_30m == 'NEGATIVE':
            flow_weighted.append((-1, 0.8))

        # Buy ratio 30M — high noise (Order Flow)
        buy_ratio = sg('buy_ratio_30m', 0.5)
        if buy_ratio > 0.55:
            flow_weighted.append((1, 0.5))
        elif buy_ratio < 0.45:
            flow_weighted.append((-1, 0.5))

        # CVD trend 4H (Order Flow)
        cvd_4h = str(f.get('cvd_trend_4h', '')).upper()
        if cvd_4h == 'POSITIVE':
            flow_weighted.append((1, 1.0))
        elif cvd_4h == 'NEGATIVE':
            flow_weighted.append((-1, 1.0))

        # CVD-Price cross — highest information density (Order Flow)
        cvd_cross_30m = str(f.get('cvd_price_cross_30m', '')).upper()
        cvd_cross_4h = str(f.get('cvd_price_cross_4h', '')).upper()
        if cvd_cross_4h in ('ACCUMULATION', 'ABSORPTION_BUY'):
            flow_weighted.append((1, 2.0))
        elif cvd_cross_4h in ('DISTRIBUTION', 'ABSORPTION_SELL'):
            flow_weighted.append((-1, 2.0))
        if cvd_cross_30m in ('ACCUMULATION', 'ABSORPTION_BUY'):
            flow_weighted.append((1, 1.5))
        elif cvd_cross_30m in ('DISTRIBUTION', 'ABSORPTION_SELL'):
            flow_weighted.append((-1, 1.5))

        # Buy ratio 4H — high noise (Order Flow)
        buy_ratio_4h = sg('buy_ratio_4h', 0.5)
        if buy_ratio_4h > 0.55:
            flow_weighted.append((1, 0.5))
        elif buy_ratio_4h < 0.45:
            flow_weighted.append((-1, 0.5))

        # Taker buy ratio: aggressive order direction (Order Flow, but noisy)
        taker = sg('taker_buy_ratio', 0.5)
        if taker > 0.55:
            flow_weighted.append((1, 0.6))
        elif taker < 0.45:
            flow_weighted.append((-1, 0.6))

        # OBI (orderbook pressure) — can be spoofed (Order Flow)
        obi = sg('obi_weighted')
        if obi > 0.2:
            flow_weighted.append((1, 0.8))
        elif obi < -0.2:
            flow_weighted.append((-1, 0.8))

        # OBI dynamic shift — high noise
        obi_change = sg('obi_change_pct')
        if obi_change > 20:
            flow_weighted.append((1, 0.5))
        elif obi_change < -20:
            flow_weighted.append((-1, 0.5))

        # v40.0: Compute weighted order flow score
        if not _avail_order_flow:
            flow_score, flow_dir = 0, "N/A"
        elif flow_weighted:
            _fw_sum = sum(s * w for s, w in flow_weighted)
            _fw_total = sum(w for _, w in flow_weighted)
            flow_raw = _fw_sum / _fw_total if _fw_total > 0 else 0
            flow_score = round(abs(flow_raw) * 10)
            flow_dir = "BULLISH" if flow_raw > 0.15 else ("BEARISH" if flow_raw < -0.15 else "MIXED")
        else:
            flow_score, flow_dir = 0, "N/A"

        # ── Vol/Extension Risk (0-10, higher = riskier) ──
        # v29.2: worst-case across all 3 timeframes
        _ext_map = {'NORMAL': 1, 'EXTENDED': 3, 'OVEREXTENDED': 6, 'EXTREME': 9}
        _vol_map = {'LOW': 1, 'NORMAL': 2, 'HIGH': 5, 'EXTREME': 8}
        ext_risks = [
            _ext_map.get(f.get('extension_regime_30m', 'NORMAL'), 2),
            _ext_map.get(f.get('extension_regime_4h', 'NORMAL'), 1),
            _ext_map.get(f.get('extension_regime_1d', 'NORMAL'), 1),
        ]
        vol_risks = [
            _vol_map.get(f.get('volatility_regime_30m', 'NORMAL'), 2),
            _vol_map.get(f.get('volatility_regime_4h', 'NORMAL'), 1),
            _vol_map.get(f.get('volatility_regime_1d', 'NORMAL'), 1),
        ]
        ext_risk = max(ext_risks)
        vol_risk = max(vol_risks)
        vol_ext_score = min(10, max(ext_risk, vol_risk))

        # v36.1: BB width squeeze amplifies vol_ext risk
        # _classify_trend() returns RISING/FALLING/FLAT for BB width series.
        # FALLING BB width = bands contracting = squeeze = impending breakout (risk +1)
        # RISING BB width already captured by volatility_regime, no double-count
        for bb_key in ('bb_width_30m_trend_5bar', 'bb_width_4h_trend_5bar'):
            bb_trend = str(f.get(bb_key, '')).upper()
            if bb_trend == 'FALLING':
                vol_ext_score = min(10, vol_ext_score + 1)
                break  # only +1 total, not per-TF

        # ── Risk Environment (0-10, higher = riskier) ──
        risk_score = 2
        _avail_derivatives = f.get('_avail_derivatives', True)
        fr = sg('funding_rate_pct')
        # v34.1: Skip FR factors when derivatives unavailable (0.0 is artifact)
        if _avail_derivatives and abs(fr) > 0.05:
            risk_score += 3
        elif _avail_derivatives and abs(fr) > 0.02:
            risk_score += 1

        # v34.3: Guard with _avail_sentiment — 0.0 default is artifact, not real data
        _avail_sentiment = f.get('_avail_sentiment', True)
        long_ratio = sg('long_ratio', 0.5)
        if _avail_sentiment and (long_ratio > 0.7 or long_ratio < 0.3):
            risk_score += 2
        elif _avail_sentiment and (long_ratio > 0.6 or long_ratio < 0.4):
            risk_score += 1

        # OI trend: rising OI = new positions opening = higher leverage in system
        oi_trend = str(f.get('oi_trend', '')).upper()
        if oi_trend == 'RISING':
            risk_score += 1

        # Liquidation cascade bias: directional liquidations = forced selling/buying
        liq_bias = str(f.get('liquidation_bias', '')).upper()
        if liq_bias in ('LONG_DOMINANT', 'SHORT_DOMINANT'):
            risk_score += 1

        # OBI imbalance: extreme orderbook skew = slippage risk
        # v34.2: Skip when orderbook data unavailable (0.0 is artifact)
        _avail_orderbook = f.get('_avail_orderbook', True)
        obi = sg('obi_weighted')
        if _avail_orderbook and abs(obi) > 0.4:
            risk_score += 1

        # Liquidation buffer: close to liquidation = critical risk
        # v34.2: Skip when account data unavailable (100.0 default is artifact)
        _avail_account = f.get('_avail_account', True)
        liq_buffer = sg('liquidation_buffer_pct', 100.0)
        # v36.0: liq_buffer=0 means at/past liquidation — most dangerous.
        # Previously `0 < liq_buffer < 5` missed the buffer=0 edge case.
        if _avail_account and 0 <= liq_buffer < 5:
            risk_score += 3
        elif _avail_account and 0 < liq_buffer < 10:
            risk_score += 1

        # FR trend: rising FR = increasing pressure on one side
        fr_trend = str(f.get('funding_rate_trend', '')).upper()
        if fr_trend in ('RISING', 'FALLING'):
            risk_score += 1

        # Premium index: extreme premium/discount = leverage risk
        premium = sg('premium_index')
        if abs(premium) > 0.001:
            risk_score += 1

        # Sentiment degraded: data quality risk
        if f.get('sentiment_degraded'):
            risk_score += 1

        # v29.2: 4H/1D volatility regime contributes to risk environment
        for vr_key in ('volatility_regime_4h', 'volatility_regime_1d'):
            vr = str(f.get(vr_key, '')).upper()
            if vr == 'EXTREME':
                risk_score += 1
            elif vr == 'HIGH':
                risk_score += 0  # Only EXTREME adds risk at higher TFs

        # FR consecutive blocks: operational risk (≥3 = stuck in loop)
        fr_blocks = sg('fr_consecutive_blocks', 0)
        if fr_blocks >= 3:
            risk_score += 1

        # Top traders extreme positioning: contrarian risk
        # v34.2: Skip when binance_derivatives data unavailable (0.5 default is artifact)
        _avail_binance_deriv = f.get('_avail_binance_derivatives', True)
        top_long = sg('top_traders_long_ratio', 0.5)
        if _avail_binance_deriv and (top_long > 0.65 or (0 < top_long < 0.35)):
            risk_score += 1

        # v36.1: S/R proximity risk — price within 1 ATR of support or resistance
        # increases risk of bounce/rejection (relevant for position management)
        _avail_sr = f.get('_avail_sr_zones', True)
        sup_dist = sg('nearest_support_dist_atr', 99)
        res_dist = sg('nearest_resist_dist_atr', 99)
        if _avail_sr and min(sup_dist, res_dist) < 1.0 and min(sup_dist, res_dist) > 0:
            risk_score += 1

        risk_score = min(10, risk_score)

        # ── Trend Reversal Detection ── (v39.0)
        # Detects conditions where trend is exhausting and reversal is building.
        # When active, reduces trend_score certainty to prevent stale trend bias.
        reversal_bull_count = 0
        reversal_bear_count = 0

        # Signal 1: ADX falling from elevated level (trend exhaustion)
        adx_1d = sg('adx_1d')
        if adx_1d > 25 and adx_1d_trend == 'FALLING':
            if trend_dir == 'BEARISH':
                reversal_bull_count += 1
            elif trend_dir == 'BULLISH':
                reversal_bear_count += 1

        # Signal 2: Multiple divergences (2+ across timeframes)
        if div_bull >= 2:
            reversal_bull_count += 1
        if div_bear >= 2:
            reversal_bear_count += 1

        # Signal 3: DI convergence (directional conviction weakening)
        if di_spread_trend == 'NARROWING':
            if trend_dir == 'BEARISH':
                reversal_bull_count += 1
            elif trend_dir == 'BULLISH':
                reversal_bear_count += 1

        # Signal 4: Price near strong support/resistance
        if trend_dir == 'BEARISH' and sup_dist < 2:
            reversal_bull_count += 1
        elif trend_dir == 'BULLISH' and res_dist < 2:
            reversal_bear_count += 1

        # Signal 5: 4H momentum opposing trend direction
        if trend_dir == 'BEARISH' and mom_dir == 'BULLISH':
            reversal_bull_count += 1
        elif trend_dir == 'BULLISH' and mom_dir == 'BEARISH':
            reversal_bear_count += 1

        # Determine reversal state (requires 3+ of 5 signals)
        reversal_active = max(reversal_bull_count, reversal_bear_count) >= 3
        reversal_dir = 'NONE'
        if reversal_bull_count >= 3:
            reversal_dir = 'BULLISH'
        elif reversal_bear_count >= 3:
            reversal_dir = 'BEARISH'

        # When reversal signal is active, reduce trend certainty
        if reversal_active:
            trend_score = max(1, trend_score - 3)

        # v40.0 P0-6: Divergence adjustment — reversal warning applied to trend_score.
        # Moved from momentum voting to prevent dilution by ~10 trend-following signals.
        # Mutual exclusion with v39.0 reversal detection: reversal_active already includes
        # divergence as one of its 5 conditions, so don't double-penalize (-2 + -3 = -5).
        if not reversal_active:
            divergence_adjustment = 0
            if div_bull >= 3:
                divergence_adjustment = -3  # Strong bullish reversal warning → weaken bearish trend
            elif div_bull >= 2:
                divergence_adjustment = -2
            if div_bear >= 3:
                divergence_adjustment = 3  # Strong bearish reversal warning → weaken bullish trend
            elif div_bear >= 2:
                divergence_adjustment = 2
            if divergence_adjustment != 0:
                trend_score = max(0, trend_score + divergence_adjustment)

        # ── Regime Transition Detection ── (v40.0 Phase 2)
        # When order_flow dimension opposes trend dimension,
        # the market may be transitioning. This is informative, not "conflicting".
        _avail_mtf_1d = f.get('_avail_mtf_1d', True)
        _avail_mtf_4h = f.get('_avail_mtf_4h', True)
        _regime_transition = "NONE"

        if _avail_order_flow and flow_dir not in ("N/A", "MIXED"):
            if trend_dir == "BEARISH" and flow_dir == "BULLISH":
                _regime_transition = "TRANSITIONING_BULLISH"
            elif trend_dir == "BULLISH" and flow_dir == "BEARISH":
                _regime_transition = "TRANSITIONING_BEARISH"
        # v40.0 Phase 2c: Fallback when order_flow unavailable — use momentum as proxy
        elif not _avail_order_flow and _avail_mtf_4h:
            if trend_dir == "BEARISH" and mom_dir == "BULLISH":
                _regime_transition = "TRANSITIONING_BULLISH"
            elif trend_dir == "BULLISH" and mom_dir == "BEARISH":
                _regime_transition = "TRANSITIONING_BEARISH"

        # v40.0 Phase 2b: 2-cycle hysteresis — require consecutive detection
        # _prev_regime_transition passed via feature_dict by caller (ai_strategy.py)
        _raw_transition = _regime_transition
        if _raw_transition != "NONE":
            _prev = f.get("_prev_regime_transition", "NONE")
            if _prev == _raw_transition:
                _regime_transition = _raw_transition  # Confirmed: 2 consecutive cycles
            else:
                _regime_transition = "NONE"  # First cycle: don't act yet

        # ── Net Assessment ── (v40.0 Phase 3: Regime-dependent weighted net)
        # v40.0 P0-1: Use (direction, dim_name) tuples to prevent zip mapping errors.
        _dir_pairs = []  # (direction_label, dimension_name)
        if _avail_mtf_1d:
            _dir_pairs.append((trend_dir, "trend"))
        if _avail_mtf_4h:
            _dir_pairs.append((mom_dir, "momentum"))
        if _avail_order_flow:
            _dir_pairs.append((flow_dir, "order_flow"))

        # v40.0 Phase 3 / Layer C: Regime-dependent dimension weights
        # ADX thresholds use discrete steps (not continuous — known limitation,
        # mitigated by 2-cycle hysteresis on TRANSITIONING).
        adx_1d_val = sg('adx_1d')
        adx_4h_val = sg('adx_4h', 0)
        adx_effective = max(adx_1d_val, adx_4h_val)

        if _regime_transition != "NONE":
            # TRANSITIONING: order_flow dimension gets 2x weight
            weights = {"trend": 1.0, "momentum": 1.0, "order_flow": 2.0}
        elif adx_effective < 20 and _regime_transition == "NONE":
            # Ranging: order_flow more reliable (mean-reversion environment)
            weights = {"trend": 0.7, "momentum": 1.0, "order_flow": 1.5}
        elif adx_effective >= 40:
            # Strong trend: trend dimension most reliable
            weights = {"trend": 1.5, "momentum": 1.0, "order_flow": 0.8}
        else:
            # Default: equal weights
            weights = {"trend": 1.0, "momentum": 1.0, "order_flow": 1.0}

        # Build weighted scores
        weighted_scores = []
        weight_list = []
        for d, dim_name in _dir_pairs:
            w = weights.get(dim_name, 1.0)
            if d == "BULLISH":
                weighted_scores.append(1 * w)
            elif d == "BEARISH":
                weighted_scores.append(-1 * w)
            else:
                # NEUTRAL, FADING, MIXED, N/A → 0 (inconclusive, still counted)
                weighted_scores.append(0)
            weight_list.append(w)

        if len(weighted_scores) < 2:
            net_label = "INSUFFICIENT"
        elif any(s != 0 for s in weighted_scores):
            net_raw = sum(weighted_scores) / sum(weight_list) if sum(weight_list) > 0 else 0
            # v40.0: TRANSITIONING regime gets its own net label prefix
            if _regime_transition != "NONE":
                net_label = _regime_transition
            elif net_raw > 0.3:
                net_label = "LEAN_BULLISH"
            elif net_raw < -0.3:
                net_label = "LEAN_BEARISH"
            else:
                net_label = "CONFLICTING"
            # Count aligned dimensions
            _majority_sign = 1 if net_raw >= 0 else -1
            aligned = sum(1 for s in weighted_scores if (s > 0 and _majority_sign > 0) or (s < 0 and _majority_sign < 0))
            net_label += f"_{aligned}of{len(weighted_scores)}"
        else:
            net_label = "INSUFFICIENT"

        return {
            "trend": {"score": trend_score, "direction": trend_dir},
            "momentum": {"score": mom_score, "direction": mom_dir},
            "order_flow": {"score": flow_score, "direction": flow_dir},
            "vol_ext_risk": {"score": vol_ext_score, "regime_30m": f"{f.get('extension_regime_30m', 'NORMAL')}/{f.get('volatility_regime_30m', 'NORMAL')}", "regime_4h": f"{f.get('extension_regime_4h', 'N/A')}/{f.get('volatility_regime_4h', 'N/A')}", "regime_1d": f"{f.get('extension_regime_1d', 'N/A')}/{f.get('volatility_regime_1d', 'N/A')}"},
            "risk_env": {"score": risk_score, "level": "HIGH" if risk_score >= 6 else ("MODERATE" if risk_score >= 4 else "LOW")},
            "net": net_label,
            # v40.0: Regime transition state
            "regime_transition": _regime_transition,
            # Store raw (pre-hysteresis) detection for next cycle
            "_raw_regime_transition": _raw_transition,
            # v39.0: Trend reversal detection
            "trend_reversal": {
                "active": reversal_active,
                "direction": reversal_dir,
                "signals": max(reversal_bull_count, reversal_bear_count),
            },
        }

    def _format_30m_summary(self, data: Dict[str, Any]) -> str:
        """
        v18 Item 22: 3-line 30M execution summary for direction agents (Bull/Bear).
        Replaces full 30M time series + K-LINE OHLCV.
        """
        rsi = data.get('rsi', 50)
        bb = data.get('bb_position', 0.5)
        macd_h = data.get('macd', 0) - data.get('macd_signal', 0) if data.get('macd') is not None and data.get('macd_signal') is not None else 0
        atr = data.get('atr', 0)
        vol = data.get('volume_ratio', 1.0)
        adx = data.get('adx', 25)

        rsi_label = "OVERBOUGHT" if rsi > 70 else ("OVERSOLD" if rsi < 30 else "NORMAL")
        bb_label = "UPPER" if bb > 0.8 else ("LOWER" if bb < 0.2 else "MID")
        macd_label = "POSITIVE" if macd_h > 0 else "NEGATIVE"
        adx_label = "STRONG" if adx >= 40 else ("MODERATE" if adx >= 25 else "WEAK")

        return (
            f"\n=== 30M EXECUTION SUMMARY (方向判断由 4H 层提供, 此处仅供参考) ===\n"
            f"RSI: {rsi:.1f} ({rsi_label}) | BB: {bb * 100:.1f}% ({bb_label}) | MACD Hist: {macd_h:+.4f} ({macd_label})\n"
            f"ATR: ${atr:,.2f} | Volume: {vol:.1f}x avg | ADX: {adx:.1f} ({adx_label})\n"
        )

    def _format_direction_report(self, data: Dict[str, Any]) -> str:
        """
        v18 Item 22: Format report for direction-arguing agents (Bull/Bear).
        Includes all sections EXCEPT 30M time series and K-LINE OHLCV,
        which are replaced by a 3-line summary.
        v19.1 fix: Preserves 30M divergence annotations (pre-computed signals
        are not noise — Bull/Bear need them for direction assessment).
        """
        full_report = self._format_technical_report(data)

        # Find and replace 30M sections with summary
        marker_exec = "=== 30M EXECUTION DATA"

        idx_exec = full_report.find(marker_exec)
        if idx_exec == -1:
            # No 30M section found — return as-is
            return full_report

        # v19.1 fix: Extract 30M divergence section before truncation.
        # Divergence annotations are pre-computed structural signals, not raw noise.
        # Bull/Bear need them even in trending markets (ADX>=25).
        marker_div = "30M DIVERGENCE DETECTION"
        div_section = ""
        idx_div = full_report.find(marker_div)
        if idx_div != -1:
            # Find the end of the divergence section (next === marker or end of report)
            div_end = full_report.find("\n===", idx_div + 1)
            if div_end == -1:
                div_end = len(full_report)
            div_section = "\n" + full_report[idx_div:div_end].rstrip() + "\n"

        # Everything before 30M sections
        before_30m = full_report[:idx_exec].rstrip()

        # 3-line 30M summary + preserved divergence annotations
        summary = self._format_30m_summary(data)

        return before_30m + "\n" + summary + div_section

    def _format_sentiment_report(self, data: Optional[Dict[str, Any]]) -> str:
        """Format sentiment data for prompts.

        TradingAgents v3.3: Pass raw ratios only, no interpretation.
        v3.24: Added history series for continuous data.
        """
        if not data:
            return "SENTIMENT: Data not available"

        # Fix: Ensure numeric types for formatting (API may return strings)
        try:
            net = float(data.get('net_sentiment') or 0)
        except (ValueError, TypeError) as e:
            self.logger.debug(f"Using default value, original error: {e}")
            net = 0.0
        try:
            pos_ratio = float(data.get('positive_ratio') or 0)
        except (ValueError, TypeError) as e:
            self.logger.debug(f"Using default value, original error: {e}")
            pos_ratio = 0.0
        try:
            neg_ratio = float(data.get('negative_ratio') or 0)
        except (ValueError, TypeError) as e:
            self.logger.debug(f"Using default value, original error: {e}")
            neg_ratio = 0.0
        sign = '+' if net >= 0 else ''

        lines = [
            "MARKET SENTIMENT (Binance Long/Short Ratio):",
            f"- Long Ratio: {pos_ratio:.1%}",
            f"- Short Ratio: {neg_ratio:.1%}",
            f"- Net: {sign}{net:.3f}",
        ]

        # v18.0: Degradation warning for AI
        if data.get('degraded') or data.get('source') == 'default_neutral':
            lines.append("")
            lines.append("⚠️ WARNING: Sentiment data UNAVAILABLE (Binance API failure).")
            lines.append("Above values are DEFAULT NEUTRAL (50/50) — NOT real market data.")
            lines.append("Do NOT use sentiment for this trading decision.")

        # v3.24: Show history series (oldest → newest)
        history = data.get('history', [])
        if history and len(history) >= 2:
            long_series = [f"{h['long']*100:.1f}%" for h in history]
            ratio_series = [f"{h['ratio']:.3f}" for h in history]
            lines.append(f"- Long% History: {' → '.join(long_series)}")
            lines.append(f"- L/S Ratio History: {' → '.join(ratio_series)}")

        return "\n" + "\n".join(lines) + "\n"

    def _format_position(self, position: Optional[Dict[str, Any]]) -> str:
        """
        Format current position for AI prompts with Tier 1 + Tier 2 + v4.7 fields.

        v4.5: Enhanced position data for better AI decision making.
        v4.7: Added liquidation risk, funding rate, and drawdown attribution.
        """
        if not position:
            return "No current position (FLAT)"

        # === Safe extraction of all fields ===
        def safe_float(val, default=0.0):
            try:
                return float(val) if val is not None else default
            except (ValueError, TypeError) as e:
                self.logger.debug(f"Using default value, original error: {e}")
                return default

        def safe_str(val, default='N/A'):
            return str(val) if val is not None else default

        # Basic fields
        side = position.get('side', 'N/A').upper()
        qty = safe_float(position.get('quantity'))
        avg_px = safe_float(position.get('avg_px'))
        unrealized_pnl = safe_float(position.get('unrealized_pnl'))
        current_price = safe_float(position.get('current_price'))

        # Tier 1 fields
        pnl_pct = safe_float(position.get('pnl_percentage'))
        duration_mins = position.get('duration_minutes', 0) or 0
        sl_price = position.get('sl_price')
        tp_price = position.get('tp_price')
        rr_ratio = position.get('risk_reward_ratio')

        # Tier 2 fields
        peak_pnl = position.get('peak_pnl_pct')
        worst_pnl = position.get('worst_pnl_pct')
        entry_conf = position.get('entry_confidence')
        margin_pct = position.get('margin_used_pct')

        # v4.7: Liquidation risk fields
        liquidation_price = position.get('liquidation_price')
        liquidation_buffer_pct = position.get('liquidation_buffer_pct')
        is_liquidation_risk_high = position.get('is_liquidation_risk_high', False)

        # v4.7: Funding rate fields
        funding_rate_current = position.get('funding_rate_current')
        funding_rate_cumulative_usd = position.get('funding_rate_cumulative_usd')
        effective_pnl = position.get('effective_pnl_after_funding')
        daily_funding_cost = position.get('daily_funding_cost_usd')

        # v4.7: Drawdown fields
        max_drawdown_pct = position.get('max_drawdown_pct')
        max_drawdown_duration_bars = position.get('max_drawdown_duration_bars')
        consecutive_lower_lows = position.get('consecutive_lower_lows', 0)

        # === Build formatted output ===
        lines = []

        # Header (v5.4: show notional USDT value + dynamic base currency for cross-check)
        bc = getattr(self, '_base_currency', 'BTC')
        notional_usd = qty * avg_px if avg_px > 0 else 0
        lines.append(f"Side: {side} | Size: ${notional_usd:,.0f} ({qty:.4f} {bc}) | Entry: ${avg_px:,.2f}")
        lines.append("")

        # Performance section
        lines.append("Performance:")
        pnl_sign = '+' if pnl_pct >= 0 else ''
        lines.append(f"  P&L: ${unrealized_pnl:+,.2f} ({pnl_sign}{pnl_pct:.2f}%)")

        # v4.7: Show effective PnL after funding
        if effective_pnl is not None and funding_rate_cumulative_usd:
            eff_sign = '+' if effective_pnl >= 0 else ''
            lines.append(f"  Effective P&L (after funding): ${effective_pnl:+,.2f}")

        # Peak/worst if available
        if peak_pnl is not None or worst_pnl is not None:
            peak_str = f"+{peak_pnl:.2f}%" if peak_pnl is not None else "N/A"
            worst_str = f"{worst_pnl:+.2f}%" if worst_pnl is not None else "N/A"
            lines.append(f"  Peak: {peak_str} | Worst: {worst_str}")

        # v4.7: Drawdown attribution
        if max_drawdown_pct is not None and max_drawdown_pct > 0:
            dd_bars = max_drawdown_duration_bars or 0
            lines.append(f"  Current Drawdown: -{max_drawdown_pct:.2f}% (for {dd_bars} bars)")

        # Duration
        if duration_mins > 0:
            if duration_mins >= 60:
                hours = duration_mins // 60
                mins = duration_mins % 60
                duration_str = f"{hours}h {mins}m"
            else:
                duration_str = f"{duration_mins} minutes"
            lines.append(f"  Duration: {duration_str}")

        lines.append("")

        # v4.7: Liquidation Risk section (CRITICAL)
        lines.append("Liquidation Risk:")
        if liquidation_price is not None:
            lines.append(f"  Liquidation Price: ${liquidation_price:,.2f}")
            if liquidation_buffer_pct is not None:
                risk_emoji = "🔴" if is_liquidation_risk_high else "🟢"
                lines.append(f"  Buffer: {risk_emoji} {liquidation_buffer_pct:.1f}%")
                if is_liquidation_risk_high:
                    lines.append("  ⚠️ WARNING: Liquidation risk HIGH (<10% buffer)")
        else:
            lines.append("  Liquidation data not available")

        lines.append("")

        # v5.1: Funding Rate section (settled + predicted)
        lines.append("Funding Rate Impact:")
        if funding_rate_current is not None:
            fr_pct = funding_rate_current * 100
            fr_emoji = "🔴" if fr_pct > 0.01 else "🟢" if fr_pct < -0.01 else "⚪"
            lines.append(f"  Last Settled Rate: {fr_emoji} {fr_pct:.5f}% per 8h")
            if daily_funding_cost is not None:
                lines.append(f"  Estimated Daily Cost: ${daily_funding_cost:.2f}")
            if funding_rate_cumulative_usd is not None:
                lines.append(f"  Cumulative Paid: ${funding_rate_cumulative_usd:+.2f}")
        else:
            lines.append("  Funding rate data not available")

        lines.append("")

        # Risk Management section
        lines.append("Risk Management:")
        if sl_price is not None:
            sl_dist = ((sl_price - avg_px) / avg_px * 100) if avg_px > 0 else 0
            lines.append(f"  Stop Loss: ${sl_price:,.2f} ({sl_dist:+.2f}%)")
        else:
            lines.append("  Stop Loss: NOT SET")

        if tp_price is not None:
            tp_dist = ((tp_price - avg_px) / avg_px * 100) if avg_px > 0 else 0
            lines.append(f"  Take Profit: ${tp_price:,.2f} ({tp_dist:+.2f}%)")
        else:
            lines.append("  Take Profit: NOT SET")

        if rr_ratio is not None:
            lines.append(f"  Risk/Reward Ratio: {rr_ratio:.1f}:1")

        if margin_pct is not None:
            lines.append(f"  Margin Used: {margin_pct:.1f}% of equity")

        lines.append("")

        # Entry Context section
        lines.append("Entry Context:")
        if entry_conf:
            lines.append(f"  Entry Confidence: {entry_conf}")
        else:
            lines.append("  Entry Confidence: UNKNOWN")

        if current_price and avg_px > 0:
            price_vs_entry = ((current_price - avg_px) / avg_px * 100)
            lines.append(f"  Current vs Entry: {price_vs_entry:+.2f}%")

        # v4.7: Market structure hint
        if consecutive_lower_lows and consecutive_lower_lows >= 3:
            lines.append(f"  ⚠️ Bearish structure: {consecutive_lower_lows} consecutive lower lows")

        return "\n".join(lines)

    def _format_account(self, account: Optional[Dict[str, Any]]) -> str:
        """
        Format account context for AI prompts (v4.6 + v4.7).

        Provides capital, capacity, and portfolio-level risk information.
        v4.7: Added liquidation buffer, funding costs, and total P&L.
        """
        if not account:
            return "Account context not available"

        lines = []

        # Capital info
        equity = account.get('equity', 0)
        leverage = account.get('leverage', 1)
        lines.append(f"Equity: ${equity:,.2f} | Leverage: {leverage}x")

        # Position capacity
        max_pos_value = account.get('max_position_value', 0)
        current_pos_value = account.get('current_position_value', 0)
        available = account.get('available_capacity', 0)
        capacity_pct = account.get('capacity_used_pct', 0)

        lines.append("")
        lines.append("Position Capacity:")
        lines.append(f"  Max Allowed: ${max_pos_value:,.2f}")
        lines.append(f"  Currently Used: ${current_pos_value:,.2f} ({capacity_pct:.1f}%)")
        lines.append(f"  Available: ${available:,.2f}")

        # v4.7: Portfolio P&L
        total_pnl = account.get('total_unrealized_pnl_usd')
        if total_pnl is not None:
            lines.append("")
            lines.append("Portfolio P&L:")
            pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
            lines.append(f"  Total Unrealized: {pnl_emoji} ${total_pnl:+,.2f}")

        # v4.7: Portfolio Liquidation Risk
        liq_buffer_min = account.get('liquidation_buffer_portfolio_min_pct')
        if liq_buffer_min is not None:
            lines.append("")
            lines.append("Portfolio Liquidation Risk:")
            risk_emoji = "🔴" if liq_buffer_min < 10 else "🟡" if liq_buffer_min < 15 else "🟢"
            lines.append(f"  Min Liquidation Buffer: {risk_emoji} {liq_buffer_min:.1f}%")
            if liq_buffer_min < 10:
                lines.append("  ⚠️ CRITICAL: Portfolio near liquidation!")
            elif liq_buffer_min < 15:
                lines.append("  ⚠️ WARNING: Reduce risk or add margin")

        # v4.7: Funding Costs
        daily_funding = account.get('total_daily_funding_cost_usd')
        cumulative_funding = account.get('total_cumulative_funding_paid_usd')
        if daily_funding is not None or cumulative_funding is not None:
            lines.append("")
            lines.append("Funding Costs:")
            if daily_funding is not None:
                lines.append(f"  Daily Cost: ${daily_funding:.2f}")
            if cumulative_funding is not None:
                lines.append(f"  Cumulative Paid: ${cumulative_funding:+.2f}")

        # Add/reduce guidance
        can_add = account.get('can_add_position', False)
        can_add_safely = account.get('can_add_position_safely', False)
        lines.append("")
        if can_add_safely:
            lines.append("✅ Safe to add position (capacity + liquidation buffer OK)")
        elif can_add:
            lines.append("⚠️ Capacity available but liquidation buffer low - add with caution")
        else:
            lines.append("🔴 Near max capacity - consider REDUCE or HOLD")

        return "\n".join(lines)

    # =========================================================================
    # v3.12: Persistent Memory System (TradingGroup-style experience summary)
    # =========================================================================


    def _format_order_flow_report(self, data: Optional[Dict[str, Any]], price_change_pct: float = 0.0) -> str:
        """
        Format order flow data for AI prompts.

        MTF v2.1: New method for order flow integration
        v19.1: Added price_change_pct for CVD-Price divergence detection

        Parameters
        ----------
        data : Dict, optional
            Order flow data containing buy_ratio, cvd_trend, etc.
        price_change_pct : float
            Period price change percentage for CVD-Price cross-analysis

        Returns
        -------
        str
            Formatted order flow report for AI prompts
        """
        if not data or data.get('data_source') == 'none':
            return "ORDER FLOW: Data not available (using neutral assumptions)"

        buy_ratio = data.get('buy_ratio', 0.5)
        avg_trade = data.get('avg_trade_usdt', 0)
        volume_usdt = data.get('volume_usdt', 0)
        trades_count = data.get('trades_count', 0)
        cvd_trend = data.get('cvd_trend', 'N/A')
        recent_bars = data.get('recent_10_bars', [])

        # Format recent bars (raw data only, AI infers trend)
        recent_str = ", ".join([f"{r:.1%}" for r in recent_bars]) if recent_bars else "N/A"

        # v5.1: Compute buy ratio range statistics for microstructure analysis
        # Helps AI detect: compression (low range → breakout imminent),
        # anomalies (extreme values → potential spoofing/wash), one-sided flow
        range_stats = ""
        if recent_bars and len(recent_bars) >= 3:
            br_min = min(recent_bars)
            br_max = max(recent_bars)
            br_range = br_max - br_min
            br_std = (sum((r - buy_ratio) ** 2 for r in recent_bars) / len(recent_bars)) ** 0.5
            range_stats = (
                f"- Buy Ratio Range: {br_min:.1%}-{br_max:.1%} "
                f"(spread={br_range:.1%}, stddev={br_std:.1%})\n"
            )

        # v5.2: Added CVD numerical history (was trend-only — AI needs magnitude)
        cvd_history = data.get('cvd_history', [])
        cvd_cumulative = data.get('cvd_cumulative', 0)
        cvd_history_str = ", ".join([f"{v:+,.0f}" for v in cvd_history]) if cvd_history else "N/A"

        # v5.3: Cold start warning when insufficient CVD history
        cvd_warning = ""
        if len(cvd_history) < 3:
            cvd_warning = " ⚠️ COLD_START (< 3 bars, trend unreliable)"

        # v18 Item 5b: Compute CVD bar-by-bar trend for inline annotation
        cvd_trend_tag = ""
        if len(cvd_history) >= 3:
            last_3 = cvd_history[-3:]
            if all(v > 0 for v in last_3):
                cvd_trend_tag = "\n  → [TREND: Consistent buying — last 3 bars all positive]"
            elif all(v < 0 for v in last_3):
                cvd_trend_tag = "\n  → [TREND: Consistent selling — last 3 bars all negative]"
            elif len(cvd_history) >= 5:
                first_half_avg = sum(cvd_history[:len(cvd_history)//2]) / max(len(cvd_history)//2, 1)
                second_half_avg = sum(cvd_history[len(cvd_history)//2:]) / max(len(cvd_history) - len(cvd_history)//2, 1)
                if first_half_avg > 0 and second_half_avg < first_half_avg * 0.5:
                    cvd_trend_tag = "\n  → [TREND: Buying momentum fading — recent bars weaker than earlier]"
                elif first_half_avg < 0 and second_half_avg > first_half_avg * 0.5:
                    cvd_trend_tag = "\n  → [TREND: Selling pressure easing — recent bars less negative]"

        # v19.2: CVD-Price cross-analysis (time-aligned, with absorption detection)
        cvd_price_tag = ""
        if len(cvd_history) >= 3:
            cvd_net = sum(cvd_history[-5:]) if len(cvd_history) >= 5 else sum(cvd_history)
            price_flat = abs(price_change_pct) <= 0.3
            price_falling = price_change_pct < -0.3
            price_rising = price_change_pct > 0.3
            cvd_positive = cvd_net > 0
            cvd_negative = cvd_net < 0
            if price_falling and cvd_positive:
                cvd_price_tag = (
                    f"\n  → [CVD-PRICE DIVERGENCE: Price falling ({price_change_pct:+.1f}%) "
                    f"but CVD net positive ({cvd_net:+,.0f}) — ACCUMULATION, smart money buying the dip]"
                )
            elif price_rising and cvd_negative:
                cvd_price_tag = (
                    f"\n  → [CVD-PRICE DIVERGENCE: Price rising ({price_change_pct:+.1f}%) "
                    f"but CVD net negative ({cvd_net:+,.0f}) — DISTRIBUTION, rally on weak buying]"
                )
            elif price_falling and cvd_negative:
                cvd_price_tag = (
                    f"\n  → [CVD-PRICE CONFIRM: Price falling ({price_change_pct:+.1f}%) "
                    f"with CVD negative ({cvd_net:+,.0f}) — CONFIRMED selling pressure]"
                )
            elif price_flat and cvd_positive:
                # v19.2: Absorption — aggressive buyers absorbed by passive sellers, price held
                cvd_price_tag = (
                    f"\n  → [CVD-PRICE ABSORPTION: Price flat ({price_change_pct:+.1f}%) "
                    f"despite CVD positive ({cvd_net:+,.0f}) — large passive seller absorbing buys, "
                    f"breakout or reversal imminent]"
                )
            elif price_flat and cvd_negative:
                # v19.2: Inverse absorption — aggressive sellers absorbed by passive buyers
                cvd_price_tag = (
                    f"\n  → [CVD-PRICE ABSORPTION: Price flat ({price_change_pct:+.1f}%) "
                    f"despite CVD negative ({cvd_net:+,.0f}) — large passive buyer absorbing sells, "
                    f"support holding]"
                )

        return f"""
ORDER FLOW (Binance Taker Data):
- Buy Ratio (10-bar avg): {buy_ratio:.1%}
{range_stats}- CVD Trend: {cvd_trend}{cvd_warning}
- CVD History (last {len(cvd_history)} bars): [{cvd_history_str}]{cvd_trend_tag}{cvd_price_tag}
- CVD Cumulative: {cvd_cumulative:+,.0f}
- Volume (USDT): ${volume_usdt:,.0f}
- Avg Trade Size: ${avg_trade:,.0f} USDT
- Trade Count: {trades_count:,}
- Recent 10 Bars: [{recent_str}]
"""

    def _format_derivatives_report(
        self,
        data: Optional[Dict[str, Any]],
        current_price: float = 0.0,
        binance_derivatives: Optional[Dict[str, Any]] = None,
        cvd_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Format derivatives data for AI prompts.

        MTF v2.1: New method for derivatives integration
        v3.0: Added binance_derivatives (top traders, taker ratio)
        v19.2: Added cvd_data for OI×CVD cross-analysis (CoinGlass framework)

        Parameters
        ----------
        data : Dict, optional
            Coinalyze derivatives data (OI, liquidations) + Binance funding rate
        current_price : float
            Current BTC price for converting BTC-denominated data to USDT
        binance_derivatives : Dict, optional
            Binance-specific derivatives (top traders, taker ratio) - v3.0
        cvd_data : Dict, optional
            Order flow data containing cvd_trend and cvd_history for OI×CVD analysis

        Returns
        -------
        str
            Formatted derivatives report for AI prompts
        """
        parts = []

        # =========================================================================
        # Section 1: Derivatives Data (OI/Liq from Coinalyze, FR from Binance)
        # =========================================================================
        if data and data.get('enabled', True):
            parts.append("DERIVATIVES DATA:")

            # Open Interest (v5.2: add hourly history series for OI×Price analysis)
            trends = data.get('trends', {})
            oi = data.get('open_interest')
            if oi:
                try:
                    oi_btc = float(oi.get('value', 0) or 0)
                except (ValueError, TypeError) as e:
                    self.logger.debug(f"Using default value, original error: {e}")
                    oi_btc = 0.0
                oi_usd = oi_btc * current_price if current_price > 0 else 0
                oi_trend = trends.get('oi_trend', 'N/A')
                bc = getattr(self, '_base_currency', 'BTC')
                # v5.4: USDT primary + base currency for cross-check
                if oi_usd >= 1e9:
                    parts.append(f"- Open Interest: ${oi_usd/1e9:.2f}B ({oi_btc:,.0f} {bc}) [Trend: {oi_trend}]")
                else:
                    parts.append(f"- Open Interest: ${oi_usd/1e6:.1f}M ({oi_btc:,.0f} {bc}) [Trend: {oi_trend}]")

                # v5.2: OI hourly history (price divergence analysis)
                # v5.4: Convert BTC series to USDT + base currency for cross-check
                oi_hist = data.get('open_interest_history')
                if oi_hist and oi_hist.get('history'):
                    oi_closes_btc = [float(h.get('c', 0)) for h in oi_hist['history']]
                    if len(oi_closes_btc) >= 2 and current_price > 0:
                        oi_closes_usd = [v * current_price for v in oi_closes_btc]
                        oi_series_str = " → ".join([f"${v/1e9:.2f}B" for v in oi_closes_usd])
                        oi_change_btc = oi_closes_btc[-1] - oi_closes_btc[0]
                        oi_change_usd = oi_closes_usd[-1] - oi_closes_usd[0]
                        oi_change_pct = (oi_change_usd / oi_closes_usd[0] * 100) if oi_closes_usd[0] != 0 else 0
                        parts.append(f"  OI History ({len(oi_closes_btc)}h): {oi_series_str}")
                        parts.append(f"  OI Change: ${oi_change_usd/1e6:+,.0f}M ({oi_change_btc:+,.0f} {bc}, {oi_change_pct:+.2f}%)")
            else:
                parts.append("- Open Interest: N/A")

            # Funding Rate (v5.2: use current_pct directly from Binance, no manual *100)
            funding = data.get('funding_rate')
            if funding:
                # 已结算费率 (from Binance /fapi/v1/fundingRate, already in % form)
                settled_pct = 0.0
                try:
                    # Prefer current_pct (already in percentage), fall back to value * 100
                    raw_pct = funding.get('current_pct') or funding.get('settled_pct')
                    if raw_pct is not None:
                        settled_pct = float(raw_pct)
                    else:
                        settled_pct = float(funding.get('value', 0) or 0) * 100
                except (ValueError, TypeError) as e:
                    self.logger.debug(f"Using default value, original error: {e}")
                    settled_pct = 0.0
                parts.append(f"- Last Settled Funding Rate: {settled_pct:.5f}%")

                # 预期费率 (from premiumIndex.lastFundingRate, 实时变化)
                predicted_pct = funding.get('predicted_rate_pct')
                if predicted_pct is not None:
                    parts.append(f"- Predicted Next Funding Rate: {predicted_pct:.5f}%")
                    # v5.2: Settled vs Predicted delta (key sentiment shift signal)
                    delta_pct = predicted_pct - settled_pct
                    direction = "↑ more bullish pressure" if delta_pct > 0 else "↓ more bearish pressure" if delta_pct < 0 else "→ stable"
                    parts.append(f"- Funding Delta (Predicted - Settled): {delta_pct:+.5f}% ({direction})")
                    # v18 Item 5a: Inline relevance tag for significant FR shift
                    if abs(delta_pct) >= 0.005:
                        sign_change = "sign reversal" if (settled_pct > 0) != (predicted_pct > 0) else "same-sign shift"
                        parts.append(f"  → [SIGNAL: Significant FR delta ({sign_change}) — Reliability: HIGH in strong trend]")

                # 溢价指数 (瞬时值)
                premium_index = funding.get('premium_index')
                if premium_index is not None:
                    pi_pct = premium_index * 100
                    mark = funding.get('mark_price', 0)
                    index = funding.get('index_price', 0)
                    parts.append(
                        f"- Premium Index: {pi_pct:+.4f}% "
                        f"(Mark: ${mark:,.2f}, Index: ${index:,.2f})"
                    )

                # 下次结算倒计时
                countdown = funding.get('next_funding_countdown_min')
                if countdown is not None:
                    hours = countdown // 60
                    mins = countdown % 60
                    parts.append(f"- Next Settlement: {hours}h {mins}m")

                # 结算历史 (最近 10 次 = ~3.3 天)
                history = funding.get('history', [])
                if history and len(history) >= 2:
                    rates_str = " → ".join(
                        [f"{r['rate_pct']:.5f}%" for r in history]
                    )
                    parts.append(f"- Funding History (last {len(history)}): {rates_str}")

                    # 趋势
                    trend = funding.get('trend', 'N/A')
                    if trend != 'N/A':
                        parts.append(f"- Funding Trend: {trend}")
            else:
                parts.append("- Funding Rate: N/A")

            # Liquidations (v3.24: expanded to 24h with history trend)
            # v5.4: USDT-primary display for consistent denomination
            liq = data.get('liquidations')
            if liq:
                history = liq.get('history', [])
                if history:
                    price_for_conversion = current_price if current_price > 0 else 88000

                    # Calculate 24h totals in USDT
                    total_long_btc = sum(float(h.get('l', 0)) for h in history)
                    total_short_btc = sum(float(h.get('s', 0)) for h in history)
                    total_long_usd = total_long_btc * price_for_conversion
                    total_short_usd = total_short_btc * price_for_conversion
                    total_btc = total_long_btc + total_short_btc
                    total_usd = total_long_usd + total_short_usd
                    bc = getattr(self, '_base_currency', 'BTC')

                    parts.append(f"- Liquidations (24h): ${total_usd:,.0f} ({total_btc:.4f} {bc})")
                    # v19.1: Total volume magnitude tag
                    if total_usd > 500_000_000:
                        parts.append(f"  → [MAGNITUDE: Extreme liquidation volume (>${total_usd/1e6:.0f}M) — market stress event, high volatility]")
                    elif total_usd > 200_000_000:
                        parts.append(f"  → [MAGNITUDE: Heavy liquidation volume (${total_usd/1e6:.0f}M) — significant forced selling/buying]")
                    elif total_usd > 50_000_000:
                        parts.append(f"  → [MAGNITUDE: Moderate liquidation volume (${total_usd/1e6:.0f}M)]")
                    if total_usd > 0:
                        long_ratio = total_long_usd / total_usd
                        parts.append(f"  - Long Liq: ${total_long_usd:,.0f} ({total_long_btc:.4f} {bc}, {long_ratio:.0%})")
                        parts.append(f"  - Short Liq: ${total_short_usd:,.0f} ({total_short_btc:.4f} {bc}, {1-long_ratio:.0%})")
                        # v18 Item 5a: Inline relevance tag for liquidation data
                        if long_ratio > 0.6:
                            parts.append(f"  → [KEY INSIGHT: Long liquidations dominate ({long_ratio:.0%}) — longs being squeezed]")
                        elif long_ratio < 0.4:
                            parts.append(f"  → [KEY INSIGHT: Short liquidations dominate ({1-long_ratio:.0%}) — shorts being squeezed]")

                    # v3.24: Show hourly history (oldest → newest) for trend
                    if len(history) >= 3:
                        hourly_totals = []
                        for h in history:
                            h_total = float(h.get('l', 0)) + float(h.get('s', 0))
                            h_usd = h_total * price_for_conversion
                            hourly_totals.append(f"${h_usd:,.0f}")
                        parts.append(f"  Hourly Trend: {' → '.join(hourly_totals)}")
                else:
                    parts.append("- Liquidations (24h): N/A")
            else:
                parts.append("- Liquidations (24h): N/A")

            # Long/Short Ratio from Coinalyze (v3.26: restored trend for single-snapshot context)
            ls_hist = data.get('long_short_ratio_history')
            if ls_hist and ls_hist.get('history'):
                latest = ls_hist['history'][-1]
                ls_ratio = float(latest.get('r', 1))
                long_pct = float(latest.get('l', 50))
                short_pct = float(latest.get('s', 50))
                ls_trend = trends.get('long_short_trend', 'N/A')
                parts.append(
                    f"- Long/Short Ratio: {ls_ratio:.2f} (Long {long_pct:.1f}% / Short {short_pct:.1f}%) "
                    f"(Trend: {ls_trend})"
                )
        else:
            parts.append("COINALYZE: Data not available")

        # =========================================================================
        # Section 2: Binance Derivatives (Unique Data)
        # v3.24: Unhide full history series (previously only showed latest)
        # =========================================================================
        if binance_derivatives:
            parts.append("\nBINANCE DERIVATIVES (Top Traders & Taker):")

            # Top Traders Position Ratio — with full history series
            top_pos = binance_derivatives.get('top_long_short_position', {})
            latest = top_pos.get('latest')
            if latest:
                ratio = float(latest.get('longShortRatio', 1))
                long_pct = float(latest.get('longAccount', 0.5)) * 100
                short_pct = float(latest.get('shortAccount', 0.5)) * 100
                parts.append(
                    f"- Top Traders Position: Long {long_pct:.1f}% / Short {short_pct:.1f}% "
                    f"(Ratio: {ratio:.2f})"
                )
                # v3.24: Show history series
                history = top_pos.get('data', [])
                if history and len(history) >= 2:
                    ratios = [f"{float(h.get('longAccount', 0.5))*100:.1f}%" for h in reversed(history)]
                    parts.append(f"  History (Long%): {' → '.join(ratios)}")
                # v19.1: Inline tag for Top Traders positioning (lowered threshold + trend detection)
                if long_pct > 55:
                    parts.append(f"  → [SMART MONEY: Professional traders lean long ({long_pct:.0f}%) — contrast with retail sentiment]")
                elif short_pct > 55:
                    parts.append(f"  → [SMART MONEY: Professional traders lean short ({short_pct:.0f}%) — contrast with retail sentiment]")
                elif long_pct > 52:
                    parts.append(f"  → [SMART MONEY: Slight long bias ({long_pct:.1f}%) — marginal, monitor for shift]")
                elif short_pct > 52:
                    parts.append(f"  → [SMART MONEY: Slight short bias ({short_pct:.1f}%) — marginal, monitor for shift]")
                # v19.1: Detect positioning shift trend from history
                if history and len(history) >= 3:
                    oldest_long = float(history[-1].get('longAccount', 0.5)) * 100
                    newest_long = float(history[0].get('longAccount', 0.5)) * 100
                    shift = newest_long - oldest_long
                    if abs(shift) > 2.0:
                        shift_dir = "increasing long" if shift > 0 else "increasing short"
                        parts.append(f"  → [SHIFT: Top traders {shift_dir} ({shift:+.1f}pp over {len(history)} periods)]")

            # Top Traders Account Ratio — how many accounts are long vs short
            # This is DISTINCT from position ratio: position = exposure size, account = headcount
            # Divergence signal: few accounts holding large positions = concentrated conviction
            top_acct = binance_derivatives.get('top_long_short_account', {})
            acct_latest = top_acct.get('latest')
            if acct_latest:
                acct_ratio = float(acct_latest.get('longShortRatio', 1))
                acct_long_pct = float(acct_latest.get('longAccount', 0.5)) * 100
                acct_short_pct = float(acct_latest.get('shortAccount', 0.5)) * 100
                parts.append(
                    f"- Top Traders Accounts: Long {acct_long_pct:.1f}% / Short {acct_short_pct:.1f}% "
                    f"(Ratio: {acct_ratio:.2f})"
                )
                # Account vs Position divergence (CoinGlass-style analysis)
                # Position ratio measures exposure SIZE, Account ratio measures HEADCOUNT
                # Divergence = concentrated conviction by fewer, larger players
                if latest:  # position data available for comparison
                    pos_long = float(latest.get('longAccount', 0.5)) * 100
                    acct_long = acct_long_pct
                    divergence = pos_long - acct_long
                    if abs(divergence) > 3.0:
                        if divergence > 0:
                            parts.append(
                                f"  → [DIVERGENCE: Position long {pos_long:.1f}% > Account long {acct_long:.1f}% "
                                f"({divergence:+.1f}pp) — fewer accounts hold LARGER long positions = concentrated long conviction]"
                            )
                        else:
                            parts.append(
                                f"  → [DIVERGENCE: Account long {acct_long:.1f}% > Position long {pos_long:.1f}% "
                                f"({divergence:+.1f}pp) — more accounts long but with SMALLER positions = scattered, weak long conviction]"
                            )

            # Taker Buy/Sell Ratio — with full history series
            taker = binance_derivatives.get('taker_long_short', {})
            latest = taker.get('latest')
            if latest:
                ratio = float(latest.get('buySellRatio', 1))
                parts.append(f"- Taker Buy/Sell Ratio: {ratio:.3f}")
                # v19.1: Absolute value interpretation tag (always present)
                if ratio > 1.05:
                    parts.append(f"  → [FLOW: Buyer-dominant ({ratio:.3f}) — takers aggressively buying]")
                elif ratio < 0.95:
                    parts.append(f"  → [FLOW: Seller-dominant ({ratio:.3f}) — takers aggressively selling]")
                elif ratio < 0.98:
                    parts.append(f"  → [FLOW: Slight seller pressure ({ratio:.3f})]")
                elif ratio > 1.02:
                    parts.append(f"  → [FLOW: Slight buyer pressure ({ratio:.3f})]")
                else:
                    parts.append(f"  → [FLOW: Balanced ({ratio:.3f})]")
                # v3.24: Show history series
                history = taker.get('data', [])
                if history and len(history) >= 2:
                    ratios = [f"{float(h.get('buySellRatio', 1)):.3f}" for h in reversed(history)]
                    parts.append(f"  History: {' → '.join(ratios)}")
                    # v19.1: Lowered trend threshold from 30% to 15% for earlier detection
                    first_val = float(history[-1].get('buySellRatio', 1))
                    last_val = float(history[0].get('buySellRatio', 1))
                    if first_val > 0 and abs(last_val - first_val) / first_val > 0.15:
                        trend_dir = "fading" if last_val < first_val else "surging"
                        parts.append(f"  → [TREND: Buying momentum {trend_dir} — {first_val:.3f} → {last_val:.3f}]")

            # OI from Binance — with full history series
            oi_hist = binance_derivatives.get('open_interest_hist', {})
            latest = oi_hist.get('latest')
            if latest:
                oi_usd = float(latest.get('sumOpenInterestValue', 0))
                parts.append(f"- OI (Binance): ${oi_usd:,.0f}")
                # v3.24: Show history series
                history = oi_hist.get('data', [])
                if history and len(history) >= 2:
                    oi_values = [f"${float(h.get('sumOpenInterestValue', 0))/1e9:.2f}B" for h in reversed(history)]
                    parts.append(f"  History: {' → '.join(oi_values)}")

                    # v5.3: OI×Price 4-Quadrant analysis
                    # (Price ↑+OI ↑=New longs, Price ↑+OI ↓=Short covering,
                    #  Price ↓+OI ↑=New shorts, Price ↓+OI ↓=Long liquidation)
                    ticker_data = binance_derivatives.get('ticker_24hr')
                    if ticker_data and current_price > 0:
                        price_change = float(ticker_data.get('priceChangePercent', 0))
                        oldest_oi = float(history[-1].get('sumOpenInterestValue', 0))
                        newest_oi = float(history[0].get('sumOpenInterestValue', 0))
                        if oldest_oi > 0:
                            oi_change_pct = (newest_oi - oldest_oi) / oldest_oi * 100
                            # v19.1: Lowered OI threshold from 0.5% to 0.15% to catch marginal OI changes
                            # Added graduated labels for marginal zone and KEY INSIGHTs for all 4 quadrants
                            price_dir = "↑" if price_change > 0.1 else "↓" if price_change < -0.1 else "→"
                            oi_dir = "↑" if oi_change_pct > 0.15 else "↓" if oi_change_pct < -0.15 else "→"
                            quadrant_map = {
                                ("↑", "↑"): "New longs entering → BULLISH CONFIRMATION",
                                ("↑", "↓"): "Short covering → WEAK rally (no new conviction)",
                                ("↓", "↑"): "New shorts entering → BEARISH CONFIRMATION",
                                ("↓", "↓"): "Long liquidation → BEARISH EXHAUSTION",
                                ("↑", "→"): f"Price rising, OI flat ({oi_change_pct:+.2f}%) → Low-conviction rally",
                                ("↓", "→"): f"Price falling, OI flat ({oi_change_pct:+.2f}%) → Low-conviction decline",
                                ("→", "↑"): f"Price flat, OI rising ({oi_change_pct:+.2f}%) → Position buildup (breakout imminent?)",
                                ("→", "↓"): f"Price flat, OI falling ({oi_change_pct:+.2f}%) → Position unwind / consolidation",
                                ("→", "→"): f"Both flat — indecision / consolidation",
                            }
                            signal = quadrant_map.get(
                                (price_dir, oi_dir),
                                f"Price {price_dir} + OI {oi_dir}"
                            )
                            parts.append(
                                f"  OI×Price: Price {price_dir}{price_change:+.1f}% + "
                                f"OI {oi_dir}{oi_change_pct:+.1f}% = {signal}"
                            )
                            # v19.1: KEY INSIGHT tags for all 4 directional quadrants
                            if (price_dir, oi_dir) == ("↑", "↑"):
                                parts.append("  → [KEY INSIGHT: New longs entering on strength — bullish conviction, trend likely to continue]")
                            elif (price_dir, oi_dir) == ("↑", "↓"):
                                parts.append("  → [KEY INSIGHT: Rally driven by short covering, NOT new longs — bearish for continuation]")
                            elif (price_dir, oi_dir) == ("↓", "↑"):
                                parts.append("  → [KEY INSIGHT: New shorts entering on weakness — bearish conviction increasing]")
                            elif (price_dir, oi_dir) == ("↓", "↓"):
                                parts.append("  → [KEY INSIGHT: Long liquidation cascade — bearish exhaustion, potential bounce after flush]")

                            # v19.2: OI×CVD cross-analysis (CoinGlass framework)
                            # Bridges the gap between OI×Price and CVD×Price sections
                            # Answers: WHO is opening/closing positions?
                            if cvd_data and isinstance(cvd_data, dict):
                                _cvd_hist = cvd_data.get('cvd_history', [])
                                if _cvd_hist and len(_cvd_hist) >= 3:
                                    _cvd_net = sum(_cvd_hist[-5:]) if len(_cvd_hist) >= 5 else sum(_cvd_hist)
                                    cvd_dir = "↑" if _cvd_net > 0 else "↓" if _cvd_net < 0 else "→"
                                    oi_cvd_map = {
                                        ("↑", "↑"): "LONGS OPENING — new buyers entering aggressively",
                                        ("↑", "↓"): "SHORTS OPENING — new sellers entering aggressively",
                                        ("↓", "↓"): "LONGS CLOSING — bulls exiting positions",
                                        ("↓", "↑"): "SHORTS CLOSING — bears covering positions",
                                    }
                                    oi_cvd_signal = oi_cvd_map.get(
                                        (oi_dir, cvd_dir),
                                        f"OI {oi_dir} + CVD {cvd_dir} — indeterminate"
                                    )
                                    parts.append(
                                        f"  OI×CVD: OI {oi_dir}{oi_change_pct:+.1f}% + "
                                        f"CVD {cvd_dir}({_cvd_net:+,.0f}) = {oi_cvd_signal}"
                                    )

            # 24h Stats
            ticker = binance_derivatives.get('ticker_24hr')
            if ticker:
                change_pct = float(ticker.get('priceChangePercent', 0))
                volume = float(ticker.get('quoteVolume', 0))
                parts.append(f"- 24h: Change {change_pct:+.2f}%, Volume ${volume:,.0f}")

        if not parts:
            return "DERIVATIVES: No data available"

        return "\n".join(parts)

    def _calculate_sr_zones(
        self,
        current_price: float,
        technical_data: Optional[Dict[str, Any]],
        orderbook_data: Optional[Dict[str, Any]],
        bars_data: Optional[List[Dict[str, Any]]] = None,
        bars_data_4h: Optional[List[Dict[str, Any]]] = None,
        bars_data_1d: Optional[List[Dict[str, Any]]] = None,
        daily_bar: Optional[Dict[str, Any]] = None,
        weekly_bar: Optional[Dict[str, Any]] = None,
        atr_value: Optional[float] = None,
        order_flow_report: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate S/R Zones from multiple data sources (v3.0, v4.0).

        Combines:
        - Bollinger Bands (BB Upper/Lower)
        - SMA (SMA_50, SMA_200)
        - Order Book Walls (bid/ask anomalies)
        - v3.0: Swing Points (from OHLC bars)
        - v3.0: ATR-adaptive clustering
        - v3.0: Touch Count scoring
        - v4.0: MTF swing detection (4H, 1D)
        - v4.0: Pivot Points (Daily + Weekly)
        - v4.0: Volume Profile (VPOC, VAH, VAL)

        Parameters
        ----------
        current_price : float
            Current market price
        technical_data : Dict, optional
            Technical indicator data containing BB and SMA values
        orderbook_data : Dict, optional
            Order book data containing anomalies (walls)
        bars_data : List[Dict], optional
            v3.0: OHLC bar data for swing detection and touch count
            [{'high': float, 'low': float, 'close': float}, ...]
        bars_data_4h : List[Dict], optional
            v4.0: 4H OHLCV bars for MTF swing detection
        bars_data_1d : List[Dict], optional
            v4.0: 1D OHLCV bars for MTF swing detection
        daily_bar : Dict, optional
            v4.0: Most recent completed daily bar for pivot calculation
        weekly_bar : Dict, optional
            v4.0: Aggregated weekly bar for pivot calculation
        atr_value : float, optional
            v4.0: ATR value for buffer calculation

        Returns
        -------
        Dict
            S/R zones result from SRZoneCalculator
        """
        if current_price <= 0:
            return self.sr_calculator._empty_result()

        # Extract BB data
        bb_data = None
        if technical_data:
            bb_upper = technical_data.get('bb_upper')
            bb_lower = technical_data.get('bb_lower')
            bb_middle = technical_data.get('bb_middle')
            if bb_upper and bb_lower:
                bb_data = {
                    'upper': bb_upper,
                    'lower': bb_lower,
                    'middle': bb_middle,
                }

        # Extract SMA data
        sma_data = None
        if technical_data:
            sma_50 = technical_data.get('sma_50')
            sma_200 = technical_data.get('sma_200')
            if sma_50 or sma_200:
                sma_data = {
                    'sma_50': sma_50,
                    'sma_200': sma_200,
                }

        # Extract Order Book anomalies (walls)
        orderbook_anomalies = None
        if orderbook_data:
            anomalies = orderbook_data.get('anomalies', {})
            if anomalies:
                orderbook_anomalies = {
                    'bid_anomalies': anomalies.get('bid_anomalies', []),
                    'ask_anomalies': anomalies.get('ask_anomalies', []),
                }

        # Phase 1.1: Inject taker_buy_volume into bars_data.
        # indicator_manager.get_kline_data() only returns {timestamp,open,high,low,close,volume}.
        # order_flow_report['recent_10_bars'] contains per-bar buy ratios for the last 10 bars;
        # approximate taker_buy_volume = volume × buy_ratio for those bars.
        if bars_data and order_flow_report and isinstance(order_flow_report, dict):
            per_bar_ratios = order_flow_report.get('recent_10_bars', [])
            if per_bar_ratios:
                n_inject = min(len(per_bar_ratios), len(bars_data))
                # Align: per_bar_ratios[-n_inject:] maps to bars_data[-n_inject:]
                offset = len(bars_data) - n_inject
                for _idx, _ratio in enumerate(per_bar_ratios[-n_inject:]):
                    _bar = bars_data[offset + _idx]
                    # Only inject if taker_buy_volume is missing (avoid overwriting real data)
                    if 'taker_buy_volume' not in _bar:
                        _bar = dict(_bar)  # shallow copy — do NOT mutate caller's list
                        _bar['taker_buy_volume'] = _bar.get('volume', 0) * float(_ratio)
                        bars_data = bars_data[:offset + _idx] + [_bar] + bars_data[offset + _idx + 1:]

        # Calculate S/R zones with detailed report (v3.0: bars_data for swing/touch)
        # v4.0: Pass MTF bars for pivot points + volume profile
        # v8.1: Pass technical_data + orderbook_data for hold_probability real-time correction
        try:
            result = self.sr_calculator.calculate_with_detailed_report(
                current_price=current_price,
                bb_data=bb_data,
                sma_data=sma_data,
                orderbook_anomalies=orderbook_anomalies,
                bars_data=bars_data,
                bars_data_4h=bars_data_4h,
                bars_data_1d=bars_data_1d,
                daily_bar=daily_bar,
                weekly_bar=weekly_bar,
                atr_value=atr_value,
                technical_data=technical_data,
                orderbook_data=orderbook_data,
            )

            # Log S/R zone detection
            if result.get('nearest_resistance'):
                r = result['nearest_resistance']
                swing_tag = " [Swing]" if r.has_swing_point else ""
                touch_tag = f" [T:{r.touch_count}]" if r.touch_count > 0 else ""
                self.logger.debug(
                    f"S/R Zone: Nearest Resistance ${r.price_center:,.0f} "
                    f"({r.distance_pct:.1f}% away) [{r.strength}]{swing_tag}{touch_tag}"
                )
            if result.get('nearest_support'):
                s = result['nearest_support']
                swing_tag = " [Swing]" if s.has_swing_point else ""
                touch_tag = f" [T:{s.touch_count}]" if s.touch_count > 0 else ""
                self.logger.debug(
                    f"S/R Zone: Nearest Support ${s.price_center:,.0f} "
                    f"({s.distance_pct:.1f}% away) [{s.strength}]{swing_tag}{touch_tag}"
                )

            return result

        except Exception as e:
            self.logger.warning(f"S/R zone calculation failed: {e}")
            return self.sr_calculator._empty_result()

    @staticmethod
    def _ema_smooth(series: list, period: int = 20) -> list:
        """v20.0: Apply EMA smoothing to a series. Pure Python, no pandas."""
        if not series or len(series) < 2:
            return series
        multiplier = 2.0 / (period + 1)
        ema = [series[0]]
        for i in range(1, len(series)):
            ema.append(series[i] * multiplier + ema[-1] * (1 - multiplier))
        return ema

    def _detect_divergences(
        self,
        price_series: list,
        rsi_series: list = None,
        macd_hist_series: list = None,
        obv_series: list = None,
        timeframe: str = "4H",
    ) -> list:
        """
        v19.1: Pre-compute divergences between price and momentum indicators.
        v20.0: Added OBV divergence detection.

        Detects:
        - Bullish divergence: price makes lower low, indicator makes higher low
        - Bearish divergence: price makes higher high, indicator makes lower high

        Uses a simple peak/trough detection on the last N data points.

        Parameters
        ----------
        price_series : list
            Price values (oldest → newest)
        rsi_series : list, optional
            RSI values (same length as price_series)
        macd_hist_series : list, optional
            MACD histogram values (same length as price_series)
        obv_series : list, optional
            EMA-smoothed OBV values (same length as price_series) (v20.0)
        timeframe : str
            Label for the timeframe (e.g., "4H", "30M")

        Returns
        -------
        list of str
            Divergence annotation strings, empty if none detected
        """
        tags = []
        min_points = 5  # Need at least 5 data points for meaningful divergence

        if not price_series or len(price_series) < min_points:
            return tags

        def find_local_extremes(series, window=2):
            """Find local highs and lows with indices.

            Extends scan to the end of the series so that recent
            divergences are not missed.  At boundaries where fewer
            than *window* forward neighbours exist, only available
            neighbours are checked (backward neighbours still require
            the full window to avoid false positives at the very start).
            """
            highs = []  # (index, value)
            lows = []
            n = len(series)
            for i in range(window, n):
                fwd = min(window, n - 1 - i)  # available forward neighbours
                if fwd == 0:
                    continue  # last element can't be a local extreme
                if all(series[i] >= series[i - j] for j in range(1, window + 1)) and \
                   all(series[i] >= series[i + j] for j in range(1, fwd + 1)):
                    highs.append((i, series[i]))
                if all(series[i] <= series[i - j] for j in range(1, window + 1)) and \
                   all(series[i] <= series[i + j] for j in range(1, fwd + 1)):
                    lows.append((i, series[i]))
            return highs, lows

        price_highs, price_lows = find_local_extremes(price_series)

        def check_divergence(indicator_series, indicator_name):
            """Check for divergences between price and an indicator."""
            if not indicator_series or len(indicator_series) != len(price_series):
                return
            ind_highs, ind_lows = find_local_extremes(indicator_series)
            # v20.0: OBV uses integer format and custom descriptions
            if "OBV" in indicator_name:
                ind_fmt = ",.0f"
                bearish_desc = "volume not confirming price rise, distribution likely"
                bullish_desc = "accumulation despite price decline, smart money buying"
            elif "MACD" in indicator_name:
                ind_fmt = ".4f"
                bearish_desc = "momentum weakening despite price rise"
                bullish_desc = "selling exhaustion, reversal signal"
            else:
                ind_fmt = ".1f"
                bearish_desc = "momentum weakening despite price rise"
                bullish_desc = "selling exhaustion, reversal signal"

            # Bearish divergence: price higher high + indicator lower high
            if len(price_highs) >= 2 and len(ind_highs) >= 2:
                ph1, ph2 = price_highs[-2], price_highs[-1]
                # Find indicator highs closest to these price highs
                ih_candidates_1 = [(i, v) for i, v in ind_highs if abs(i - ph1[0]) <= 2]
                ih_candidates_2 = [(i, v) for i, v in ind_highs if abs(i - ph2[0]) <= 2]
                if ih_candidates_1 and ih_candidates_2:
                    ih1 = ih_candidates_1[-1]
                    ih2 = ih_candidates_2[-1]
                    if ph2[1] > ph1[1] and ih2[1] < ih1[1]:
                        tags.append(
                            f"→ [DIVERGENCE: {timeframe} BEARISH — Price higher high "
                            f"(${ph1[1]:,.0f}→${ph2[1]:,.0f}) but {indicator_name} lower high "
                            f"({ih1[1]:{ind_fmt}}→{ih2[1]:{ind_fmt}}) — {bearish_desc}]"
                        )

            # Bullish divergence: price lower low + indicator higher low
            if len(price_lows) >= 2 and len(ind_lows) >= 2:
                pl1, pl2 = price_lows[-2], price_lows[-1]
                il_candidates_1 = [(i, v) for i, v in ind_lows if abs(i - pl1[0]) <= 2]
                il_candidates_2 = [(i, v) for i, v in ind_lows if abs(i - pl2[0]) <= 2]
                if il_candidates_1 and il_candidates_2:
                    il1 = il_candidates_1[-1]
                    il2 = il_candidates_2[-1]
                    if pl2[1] < pl1[1] and il2[1] > il1[1]:
                        tags.append(
                            f"→ [DIVERGENCE: {timeframe} BULLISH — Price lower low "
                            f"(${pl1[1]:,.0f}→${pl2[1]:,.0f}) but {indicator_name} higher low "
                            f"({il1[1]:{ind_fmt}}→{il2[1]:{ind_fmt}}) — {bullish_desc}]"
                        )

        if rsi_series:
            check_divergence(rsi_series, "RSI")
        if macd_hist_series:
            check_divergence(macd_hist_series, "MACD Hist")
        if obv_series:
            check_divergence(obv_series, "OBV")

        return tags

    def _format_orderbook_report(self, data: Optional[Dict[str, Any]]) -> str:
        """
        Format order book depth data for AI prompts.

        v3.7.2: Fully compliant with ORDER_BOOK_IMPLEMENTATION_PLAN.md v2.0 spec

        Spec reference: docs/ORDER_BOOK_IMPLEMENTATION_PLAN.md section 3.3

        Parameters
        ----------
        data : Dict, optional
            Order book depth data from OrderBookProcessor.process()

        Returns
        -------
        str
            Formatted order book report for AI prompts (v2.0 format)
        """
        if not data:
            return "ORDER BOOK DEPTH: Data not available"

        # Check data status
        status = data.get('_status', {})
        status_code = status.get('code', 'UNKNOWN')

        # v2.0: NO_DATA status handling
        if status_code == 'NO_DATA':
            return f"""ORDER BOOK DEPTH (Binance /fapi/v1/depth):
Status: NO_DATA
Reason: {status.get('message', 'Unknown')}

[All metrics unavailable - AI should not assume neutral market]"""

        if status_code != 'OK':
            return f"ORDER BOOK DEPTH: {status.get('message', 'Error occurred')}"

        # ========== Header ==========
        levels = status.get('levels_analyzed', 100)
        history_samples = status.get('history_samples', 0)
        parts = [
            f"ORDER BOOK DEPTH (Binance /fapi/v1/depth, {levels} levels):",
            f"Status: OK ({history_samples} history samples)",
            "",
        ]

        # ========== IMBALANCE Section ==========
        # Fix: Ensure numeric types for formatting (data may contain strings)
        def _safe_float(val, default=0.0):
            try:
                return float(val) if val is not None else default
            except (ValueError, TypeError) as e:
                self.logger.debug(f"Using default value, original error: {e}")
                return default

        obi = data.get('obi', {})
        simple_obi = _safe_float(obi.get('simple', 0))
        weighted_obi = _safe_float(obi.get('weighted', 0))
        adaptive_obi = _safe_float(obi.get('adaptive_weighted', weighted_obi))
        decay_used = _safe_float(obi.get('decay_used', 0.8), 0.8)

        bid_vol_usd = _safe_float(obi.get('bid_volume_usd', 0))
        ask_vol_usd = _safe_float(obi.get('ask_volume_usd', 0))
        bid_vol_btc = _safe_float(obi.get('bid_volume_btc', 0))
        ask_vol_btc = _safe_float(obi.get('ask_volume_btc', 0))
        bc = getattr(self, '_base_currency', 'BTC')

        parts.append("IMBALANCE:")
        parts.append(f"  Simple OBI: {simple_obi:+.2f}")
        parts.append(f"  Weighted OBI: {weighted_obi:+.2f} (decay={decay_used:.2f}, adaptive)")
        # v5.4: USDT-primary + base currency cross-check
        parts.append(f"  Bid Volume: ${bid_vol_usd/1e6:.1f}M ({bid_vol_btc:.1f} {bc})")
        parts.append(f"  Ask Volume: ${ask_vol_usd/1e6:.1f}M ({ask_vol_btc:.1f} {bc})")
        parts.append("")

        # ========== DYNAMICS Section (v2.0 Critical) ==========
        dynamics = data.get('dynamics', {})
        samples_count = int(_safe_float(dynamics.get('samples_count', 0))) if dynamics else 0

        parts.append("⭐ DYNAMICS (vs previous snapshot):")
        if samples_count > 0:
            obi_change = dynamics.get('obi_change')
            obi_change_pct = dynamics.get('obi_change_pct')
            bid_depth_change = dynamics.get('bid_depth_change_pct')
            ask_depth_change = dynamics.get('ask_depth_change_pct')
            spread_change = dynamics.get('spread_change_pct')
            trend = dynamics.get('trend', 'N/A')

            if obi_change is not None:
                obi_change_f = _safe_float(obi_change)
                pct_str = f" ({_safe_float(obi_change_pct):+.1f}%)" if obi_change_pct is not None else ""
                parts.append(f"  OBI Change: {obi_change_f:+.2f}{pct_str}")
            if bid_depth_change is not None:
                parts.append(f"  Bid Depth Change: {_safe_float(bid_depth_change):+.1f}%")
            if ask_depth_change is not None:
                parts.append(f"  Ask Depth Change: {_safe_float(ask_depth_change):+.1f}%")
            if spread_change is not None:
                parts.append(f"  Spread Change: {_safe_float(spread_change):+.1f}%")
            parts.append(f"  Trend: {trend}")

            # v5.10: OBI trend array (oldest → newest) for multi-cycle analysis
            obi_trend = dynamics.get('obi_trend', [])
            if len(obi_trend) >= 2:
                trend_str = " → ".join(f"{v:+.2f}" for v in obi_trend[-5:])
                parts.append(f"  OBI Trend ({len(obi_trend)} samples): {trend_str}")
        else:
            parts.append("  [First snapshot - no historical data yet] ⚠️ COLD_START (dynamics available after 2nd cycle)")
        parts.append("")

        # ========== PRESSURE GRADIENT Section (v2.0) ==========
        gradient = data.get('pressure_gradient', {})
        if gradient:
            # Convert to percentage (values are 0-1 ratios)
            bid_near_5 = _safe_float(gradient.get('bid_near_5', 0)) * 100
            bid_near_10 = _safe_float(gradient.get('bid_near_10', 0)) * 100
            bid_near_20 = _safe_float(gradient.get('bid_near_20', 0)) * 100
            ask_near_5 = _safe_float(gradient.get('ask_near_5', 0)) * 100
            ask_near_10 = _safe_float(gradient.get('ask_near_10', 0)) * 100
            ask_near_20 = _safe_float(gradient.get('ask_near_20', 0)) * 100
            bid_conc = gradient.get('bid_concentration', 'N/A')
            ask_conc = gradient.get('ask_concentration', 'N/A')

            parts.append("⭐ PRESSURE GRADIENT:")
            parts.append(f"  Bid: {bid_near_5:.0f}% near-5, {bid_near_10:.0f}% near-10, {bid_near_20:.0f}% near-20 [{bid_conc} concentration]")
            parts.append(f"  Ask: {ask_near_5:.0f}% near-5, {ask_near_10:.0f}% near-10, {ask_near_20:.0f}% near-20 [{ask_conc} concentration]")
            parts.append("")

        # ========== DEPTH DISTRIBUTION Section (v2.0 - Previously Missing!) ==========
        depth_dist = data.get('depth_distribution', {})
        bands = depth_dist.get('bands', [])
        if bands:
            parts.append("DEPTH DISTRIBUTION (0.5% bands):")
            for band in bands:
                range_str = band.get('range', '')
                side = band.get('side', '').upper()
                volume_usd = _safe_float(band.get('volume_usd', 0))
                # Format volume in millions with 1 decimal
                vol_str = f"${volume_usd/1e6:.1f}M" if volume_usd >= 1e6 else f"${volume_usd/1e3:.0f}K"
                parts.append(f"  {range_str}: {side} {vol_str}")
            parts.append("")

        # ========== ANOMALIES Section ==========
        anomalies = data.get('anomalies', {})
        bid_anomalies = anomalies.get('bid_anomalies', [])
        ask_anomalies = anomalies.get('ask_anomalies', [])
        threshold = _safe_float(anomalies.get('threshold_used', 3.0), 3.0)
        threshold_reason = anomalies.get('threshold_reason', 'default')

        if bid_anomalies or ask_anomalies:
            bc = getattr(self, '_base_currency', 'BTC')
            parts.append(f"ANOMALIES (threshold={threshold:.1f}x, {threshold_reason}):")
            for anom in bid_anomalies[:3]:  # Show up to 3 per side
                price = _safe_float(anom.get('price', 0))
                amount_btc = _safe_float(anom.get('volume_btc', anom.get('amount', 0)))
                amount_usd = amount_btc * price if price > 0 else 0
                multiple = _safe_float(anom.get('multiplier', anom.get('multiple', 0)))
                # v5.4: USDT-primary + base currency cross-check
                vol_str = f"${amount_usd/1e6:.1f}M" if amount_usd >= 1e6 else f"${amount_usd/1e3:.0f}K"
                parts.append(f"  Bid: ${price:,.0f} @ {vol_str} ({amount_btc:.1f} {bc}, {multiple:.1f}x)")
            for anom in ask_anomalies[:3]:
                price = _safe_float(anom.get('price', 0))
                amount_btc = _safe_float(anom.get('volume_btc', anom.get('amount', 0)))
                amount_usd = amount_btc * price if price > 0 else 0
                multiple = _safe_float(anom.get('multiplier', anom.get('multiple', 0)))
                vol_str = f"${amount_usd/1e6:.1f}M" if amount_usd >= 1e6 else f"${amount_usd/1e3:.0f}K"
                parts.append(f"  Ask: ${price:,.0f} @ {vol_str} ({amount_btc:.1f} {bc}, {multiple:.1f}x)")
            parts.append("")

        # ========== LIQUIDITY Section ==========
        liquidity = data.get('liquidity', {})
        if liquidity:
            spread_pct = _safe_float(liquidity.get('spread_pct', 0))
            spread_usd = _safe_float(liquidity.get('spread_usd', 0))

            parts.append("LIQUIDITY:")
            parts.append(f"  Spread: {spread_pct:.2f}% (${spread_usd:.2f})")

            # Slippage estimates with confidence and range (v2.0)
            slippage = liquidity.get('slippage', {})
            if slippage:
                bc = getattr(self, '_base_currency', 'BTC')
                # Show 1 unit slippage as the main indicator
                for side in ['buy', 'sell']:
                    key = f"{side}_1.0_btc"  # data key from order book processor
                    est = slippage.get(key, {})
                    if isinstance(est, dict) and est.get('estimated') is not None:
                        pct = _safe_float(est.get('estimated', 0))
                        conf = _safe_float(est.get('confidence', 0))
                        range_vals = est.get('range', [0, 0])
                        range_low = _safe_float(range_vals[0] if range_vals[0] is not None else 0)
                        range_high = _safe_float(range_vals[1] if range_vals[1] is not None else 0)
                        side_label = "Buy" if side == "buy" else "Sell"
                        parts.append(
                            f"  Slippage ({side_label} 1 {bc}): {pct:.2f}% "
                            f"[confidence={conf:.0%}, range={range_low:.2f}%-{range_high:.2f}%]"
                        )

        return "\n".join(parts)

    # =========================================================================
    # v27.0: Feature Extraction — Deterministic mapping from raw data to schema
    # =========================================================================

    def extract_features(
        self,
        technical_data: Dict[str, Any],
        sentiment_data: Optional[Dict] = None,
        order_flow_data: Optional[Dict] = None,
        order_flow_4h: Optional[Dict] = None,
        derivatives_data: Optional[Dict] = None,
        binance_derivatives: Optional[Dict] = None,
        orderbook_data: Optional[Dict] = None,
        sr_zones: Optional[Dict] = None,
        current_position: Optional[Dict] = None,
        account_context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Extract fixed-schema feature dict from raw data sources.

        Returns dict conforming to FEATURE_SCHEMA.
        Missing data sources -> default values (0.0 for float, "NONE" for enum).

        Deterministic: same raw data -> same feature dict (no randomness).
        Safe defaults: missing/degraded data -> neutral defaults, never raises.
        Pre-computes all derived features (divergences, CVD cross, regime, reliability).
        Does NOT call _format_*_report() — parallel path, not replacement.
        """
        from agents.prompt_constants import FEATURE_SCHEMA, _get_multiplier

        def _sf(d, key, default=0.0):
            """Safe float extraction."""
            if not d:
                return default
            v = d.get(key)
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        def _se(d, key, valid_values, default="NONE"):
            """Safe enum extraction."""
            if not d:
                return default
            v = d.get(key, default)
            if v is None:
                return default
            v_upper = str(v).upper()
            if v_upper in valid_values:
                return v_upper
            return default

        td = technical_data or {}
        mtf_dec = td.get('mtf_decision_layer') or {}
        mtf_trend = td.get('mtf_trend_layer') or {}
        hist_ctx = td.get('historical_context') or {}
        hist_ctx_4h = mtf_dec.get('historical_context') or {}  # v34.3: top-level for CVD-Price cross
        hist_ctx_1d = mtf_trend.get('historical_context') or {}  # v36.0: 1D historical context

        features = {}

        # ── Data Availability Flags (v34.1) ──
        # Distinguish "data says neutral" from "data is missing"
        features['_avail_order_flow'] = order_flow_data is not None
        features['_avail_derivatives'] = derivatives_data is not None
        features['_avail_binance_derivatives'] = binance_derivatives is not None
        features['_avail_orderbook'] = orderbook_data is not None
        features['_avail_mtf_4h'] = mtf_dec is not None and bool(mtf_dec)
        features['_avail_mtf_1d'] = mtf_trend is not None and bool(mtf_trend)
        features['_avail_account'] = account_context is not None
        features['_avail_sr_zones'] = sr_zones is not None
        features['_avail_sentiment'] = (sentiment_data is not None
                                        and not bool((sentiment_data or {}).get('degraded')))
        # technical_data, price_data: always available

        # ── 30M Execution Layer ──
        try:
            features["price"] = _sf(td, 'price')
            features["rsi_30m"] = _sf(td, 'rsi')
            features["macd_30m"] = _sf(td, 'macd')
            features["macd_signal_30m"] = _sf(td, 'macd_signal')
            features["macd_histogram_30m"] = _sf(td, 'macd_histogram')
            features["adx_30m"] = _sf(td, 'adx')
            features["di_plus_30m"] = _sf(td, 'di_plus')
            features["di_minus_30m"] = _sf(td, 'di_minus')
            features["bb_position_30m"] = _sf(td, 'bb_position')
            features["bb_upper_30m"] = _sf(td, 'bb_upper')
            features["bb_lower_30m"] = _sf(td, 'bb_lower')
            features["sma_5_30m"] = _sf(td, 'sma_5')     # v36.0 FIX: 30M has sma_periods=[5,20]
            features["sma_20_30m"] = _sf(td, 'sma_20')
            features["volume_ratio_30m"] = _sf(td, 'volume_ratio')
            # v29.2: 30M EMA + ATR%
            features["atr_pct_30m"] = _sf(td, 'atr_pct')
            # Production base indicator_manager uses ema_periods=[macd_fast, macd_slow]=[12,26]
            # (NOT the MTF execution_layer config [10]). So technical_data has ema_12/ema_26.
            features["ema_12_30m"] = _sf(td, 'ema_12')
            features["ema_26_30m"] = _sf(td, 'ema_26')
        except Exception:
            pass  # Partial extraction is OK

        # ── 4H Decision Layer ──
        try:
            features["rsi_4h"] = _sf(mtf_dec, 'rsi')
            features["macd_4h"] = _sf(mtf_dec, 'macd')
            features["macd_signal_4h"] = _sf(mtf_dec, 'macd_signal')
            features["macd_histogram_4h"] = _sf(mtf_dec, 'macd_histogram')
            features["adx_4h"] = _sf(mtf_dec, 'adx')
            features["di_plus_4h"] = _sf(mtf_dec, 'di_plus')
            features["di_minus_4h"] = _sf(mtf_dec, 'di_minus')
            features["bb_position_4h"] = _sf(mtf_dec, 'bb_position')
            features["bb_upper_4h"] = _sf(mtf_dec, 'bb_upper')
            features["bb_lower_4h"] = _sf(mtf_dec, 'bb_lower')
            features["sma_20_4h"] = _sf(mtf_dec, 'sma_20')
            features["sma_50_4h"] = _sf(mtf_dec, 'sma_50')
            features["volume_ratio_4h"] = _sf(mtf_dec, 'volume_ratio')
            # v29.2: 4H ATR, EMA, extension, volatility
            features["atr_4h"] = _sf(mtf_dec, 'atr')
            features["atr_pct_4h"] = _sf(mtf_dec, 'atr_pct')
            features["ema_12_4h"] = _sf(mtf_dec, 'ema_12')
            features["ema_26_4h"] = _sf(mtf_dec, 'ema_26')
            features["extension_ratio_4h"] = _sf(mtf_dec, 'extension_ratio_sma_20')
            features["extension_regime_4h"] = _se(mtf_dec, 'extension_regime',
                                                   {"NORMAL", "EXTENDED", "OVEREXTENDED", "EXTREME"})
            features["volatility_regime_4h"] = _se(mtf_dec, 'volatility_regime',
                                                    {"LOW", "NORMAL", "HIGH", "EXTREME"})
            features["volatility_percentile_4h"] = _sf(mtf_dec, 'volatility_percentile')
        except Exception:
            self.logger.debug("Feature extraction: 4H decision layer partial failure")

        # ── 1D Trend Layer ──
        try:
            features["adx_1d"] = _sf(mtf_trend, 'adx')
            features["di_plus_1d"] = _sf(mtf_trend, 'di_plus')
            features["di_minus_1d"] = _sf(mtf_trend, 'di_minus')
            features["rsi_1d"] = _sf(mtf_trend, 'rsi')
            features["macd_1d"] = _sf(mtf_trend, 'macd')
            features["macd_signal_1d"] = _sf(mtf_trend, 'macd_signal')
            features["macd_histogram_1d"] = _sf(mtf_trend, 'macd_histogram')
            features["sma_200_1d"] = _sf(mtf_trend, 'sma_200')
            # v29.2: 1D BB, vol, ATR, EMA, extension, volatility
            features["bb_position_1d"] = _sf(mtf_trend, 'bb_position')
            features["volume_ratio_1d"] = _sf(mtf_trend, 'volume_ratio')
            features["atr_1d"] = _sf(mtf_trend, 'atr')
            features["atr_pct_1d"] = _sf(mtf_trend, 'atr_pct')
            features["ema_12_1d"] = _sf(mtf_trend, 'ema_12')
            features["ema_26_1d"] = _sf(mtf_trend, 'ema_26')
            features["extension_ratio_1d"] = _sf(mtf_trend, 'extension_ratio_sma_200')
            features["extension_regime_1d"] = _se(mtf_trend, 'extension_regime',
                                                   {"NORMAL", "EXTENDED", "OVEREXTENDED", "EXTREME"})
            features["volatility_regime_1d"] = _se(mtf_trend, 'volatility_regime',
                                                    {"LOW", "NORMAL", "HIGH", "EXTREME"})
            features["volatility_percentile_1d"] = _sf(mtf_trend, 'volatility_percentile')
        except Exception:
            self.logger.debug("Feature extraction: 1D trend layer partial failure")

        # ── Risk Context (30M, suffixed to match 4H/1D convention) ──
        try:
            features["extension_ratio_30m"] = _sf(td, 'extension_ratio_sma_20')
            features["extension_regime_30m"] = _se(td, 'extension_regime',
                                                    {"NORMAL", "EXTENDED", "OVEREXTENDED", "EXTREME"})
            features["volatility_regime_30m"] = _se(td, 'volatility_regime',
                                                     {"LOW", "NORMAL", "HIGH", "EXTREME"})
            features["volatility_percentile_30m"] = _sf(td, 'volatility_percentile')
            features["atr_30m"] = _sf(td, 'atr')
        except Exception:
            self.logger.debug("Feature extraction: risk context partial failure")

        # ── Market Regime (pre-computed from ADX) ──
        # v39.0: Use max(1D, 4H) ADX for regime determination.
        # Rationale: 4H is the decision layer — if 4H shows strong trend
        # (ADX>40) but 1D hasn't caught up (ADX<25), the market IS trending
        # at the actionable timeframe. Using only 1D would misclassify as
        # RANGING and cause SIGNAL_CONFIDENCE_MATRIX to underweight trend signals.
        try:
            adx_1d = features.get("adx_1d", 30.0)
            adx_4h = features.get("adx_4h", 0.0)
            effective_adx = max(adx_1d, adx_4h)
            if effective_adx >= 40:
                features["market_regime"] = "STRONG_TREND"
            elif effective_adx >= 25:
                features["market_regime"] = "WEAK_TREND"
            else:
                features["market_regime"] = "RANGING"
            adx_source = "4H" if adx_4h >= adx_1d else "1D"
            self.logger.info(
                f"Market regime: max(1D={adx_1d:.1f}, 4H={adx_4h:.1f}) "
                f"= {effective_adx:.1f} (source={adx_source}) -> {features['market_regime']}"
            )

            di_p_1d = features.get("di_plus_1d", 0)
            di_m_1d = features.get("di_minus_1d", 0)
            # v36.2: Three-state direction — equal DI (including both 0 when
            # 1D data unavailable) must produce NEUTRAL, not spurious BEARISH.
            # tag_validator.py already maps NEUTRAL → TREND_1D_NEUTRAL (line 178).
            if di_p_1d > di_m_1d:
                features["adx_direction_1d"] = "BULLISH"
            elif di_m_1d > di_p_1d:
                features["adx_direction_1d"] = "BEARISH"
            else:
                features["adx_direction_1d"] = "NEUTRAL"
        except Exception:
            features.setdefault("market_regime", "RANGING")
            features.setdefault("adx_direction_1d", "NEUTRAL")

        # ── Pre-computed Categorical (v31.0) ──
        # MACD crossover: avoid LLM comparing negative floats
        try:
            for suffix, macd_key, sig_key in [
                ("30m", "macd_30m", "macd_signal_30m"),
                ("4h",  "macd_4h",  "macd_signal_4h"),
                ("1d",  "macd_1d",  "macd_signal_1d"),
            ]:
                macd_val = features.get(macd_key, 0.0)
                macd_sig = features.get(sig_key, 0.0)
                diff = macd_val - macd_sig
                # Use ATR-relative threshold for NEUTRAL zone
                atr_ref = features.get(f"atr_pct_{suffix}", 0.0)
                threshold = atr_ref * 0.01 if atr_ref > 0 else 0.0
                if diff > threshold:
                    features[f"macd_cross_{suffix}"] = "BULLISH"
                elif diff < -threshold:
                    features[f"macd_cross_{suffix}"] = "BEARISH"
                else:
                    features[f"macd_cross_{suffix}"] = "NEUTRAL"
        except Exception:
            for s in ("30m", "4h", "1d"):
                features.setdefault(f"macd_cross_{s}", "NEUTRAL")

        # DI direction: pre-compare DI+/DI- for 30M and 4H
        try:
            for suffix, dp_key, dm_key in [
                ("30m", "di_plus_30m", "di_minus_30m"),
                ("4h",  "di_plus_4h",  "di_minus_4h"),
            ]:
                di_p = features.get(dp_key, 0.0)
                di_m = features.get(dm_key, 0.0)
                features[f"di_direction_{suffix}"] = "BULLISH" if di_p > di_m else "BEARISH"
        except Exception:
            for s in ("30m", "4h"):
                features.setdefault(f"di_direction_{s}", "BULLISH")

        # RSI zone: categorical from raw RSI value
        try:
            for suffix, rsi_key in [("30m", "rsi_30m"), ("4h", "rsi_4h"), ("1d", "rsi_1d")]:
                rsi_val = features.get(rsi_key, 50.0)
                if rsi_val < 30:
                    features[f"rsi_zone_{suffix}"] = "OVERSOLD"
                elif rsi_val > 70:
                    features[f"rsi_zone_{suffix}"] = "OVERBOUGHT"
                else:
                    features[f"rsi_zone_{suffix}"] = "NEUTRAL"
        except Exception:
            for s in ("30m", "4h", "1d"):
                features.setdefault(f"rsi_zone_{s}", "NEUTRAL")

        # ── Divergences (pre-computed) ──
        try:
            # 4H divergences use mtf_decision_layer's historical_context (not 30M hist_ctx)
            # hist_ctx_4h already defined at top scope (v34.3)
            price_4h = hist_ctx_4h.get('price_trend', [])
            rsi_4h = hist_ctx_4h.get('rsi_trend', [])
            macd_4h = hist_ctx_4h.get('macd_histogram_trend', [])
            obv_4h = hist_ctx_4h.get('obv_trend', [])

            div_4h = self._detect_divergences(
                price_series=price_4h, rsi_series=rsi_4h,
                macd_hist_series=macd_4h,
                obv_series=obv_4h if len(obv_4h) >= 5 else None,
                timeframe="4H"
            ) if price_4h and len(price_4h) >= 5 else []

            features["rsi_divergence_4h"] = "NONE"
            features["macd_divergence_4h"] = "NONE"
            features["obv_divergence_4h"] = "NONE"
            for tag in div_4h:
                tag_upper = tag.upper()
                if "RSI" in tag_upper:
                    features["rsi_divergence_4h"] = "BEARISH" if "BEARISH" in tag_upper else "BULLISH"
                elif "MACD" in tag_upper:
                    features["macd_divergence_4h"] = "BEARISH" if "BEARISH" in tag_upper else "BULLISH"
                elif "OBV" in tag_upper:
                    features["obv_divergence_4h"] = "BEARISH" if "BEARISH" in tag_upper else "BULLISH"

            price_30m = hist_ctx.get('price_trend', [])
            rsi_30m = hist_ctx.get('rsi_trend', [])
            macd_30m = hist_ctx.get('macd_histogram_trend', [])
            obv_30m = hist_ctx.get('obv_trend', [])  # v36.0 FIX: was 'obv_ema_trend' (non-existent key)

            div_30m = self._detect_divergences(
                price_series=price_30m, rsi_series=rsi_30m,
                macd_hist_series=macd_30m,
                obv_series=obv_30m if len(obv_30m) >= 5 else None,
                timeframe="30M"
            ) if price_30m and len(price_30m) >= 5 else []

            features["rsi_divergence_30m"] = "NONE"
            features["macd_divergence_30m"] = "NONE"
            features["obv_divergence_30m"] = "NONE"
            for tag in div_30m:
                tag_upper = tag.upper()
                if "RSI" in tag_upper:
                    features["rsi_divergence_30m"] = "BEARISH" if "BEARISH" in tag_upper else "BULLISH"
                elif "OBV" in tag_upper:
                    features["obv_divergence_30m"] = "BEARISH" if "BEARISH" in tag_upper else "BULLISH"
                elif "MACD" in tag_upper:
                    features["macd_divergence_30m"] = "BEARISH" if "BEARISH" in tag_upper else "BULLISH"
        except Exception:
            for k in ("rsi_divergence_4h", "macd_divergence_4h", "obv_divergence_4h",
                      "rsi_divergence_30m", "macd_divergence_30m", "obv_divergence_30m"):
                features.setdefault(k, "NONE")

        # ── Order Flow ──
        try:
            of = order_flow_data or {}
            features["cvd_trend_30m"] = _se(of, 'cvd_trend',
                                            {"POSITIVE", "NEGATIVE", "NEUTRAL"}, "NEUTRAL")
            features["buy_ratio_30m"] = _sf(of, 'buy_ratio')
            features["cvd_cumulative_30m"] = _sf(of, 'cvd_cumulative')
            # v34.3: Compute CVD-Price cross inline (OrderFlowProcessor doesn't produce this field)
            # Mirrors _format_order_flow_report() logic: CVD net (5-bar) vs price change (5-bar)
            features["cvd_price_cross_30m"] = self._compute_cvd_price_cross(
                of.get('cvd_history', []),
                hist_ctx.get('price_trend', []),
            )
        except Exception:
            self.logger.debug("Feature extraction: order flow partial failure")

        # ── 4H CVD ──
        try:
            of4 = order_flow_4h or {}
            features["cvd_trend_4h"] = _se(of4, 'cvd_trend',
                                           {"POSITIVE", "NEGATIVE", "NEUTRAL"}, "NEUTRAL")
            features["buy_ratio_4h"] = _sf(of4, 'buy_ratio')
            # v34.3: Compute CVD-Price cross inline (same fix as 30M above)
            features["cvd_price_cross_4h"] = self._compute_cvd_price_cross(
                of4.get('cvd_history', []),
                hist_ctx_4h.get('price_trend', []) if hist_ctx_4h else [],
            )
        except Exception:
            self.logger.debug("Feature extraction: 4H CVD partial failure")

        # ── Derivatives (Coinalyze + Binance FR merged) ──
        try:
            dd = derivatives_data or {}
            # funding_rate is injected by ai_data_assembler into derivatives_report
            fr_data = dd.get('funding_rate') or {}
            features["funding_rate_pct"] = _sf(fr_data, 'current_pct')
            features["funding_rate_trend"] = _se(fr_data, 'trend',
                                                  {"RISING", "FALLING", "STABLE"}, "STABLE")
            # OI trend lives in dd['trends']['oi_trend'] (from fetch_all_with_history)
            _trends = dd.get('trends') or {}
            _oi_trend_val = str(_trends.get('oi_trend', 'STABLE')).upper()
            features["oi_trend"] = _oi_trend_val if _oi_trend_val in {"RISING", "FALLING", "STABLE"} else "STABLE"
            # Liquidation bias: compute from raw history {l: long_btc, s: short_btc}
            _liq = dd.get('liquidations') or {}
            _liq_history = _liq.get('history', []) if isinstance(_liq, dict) else []
            _total_long = sum(float(h.get('l', 0)) for h in _liq_history) if _liq_history else 0
            _total_short = sum(float(h.get('s', 0)) for h in _liq_history) if _liq_history else 0
            _total_liq = _total_long + _total_short
            if _total_liq > 0:
                _long_pct = _total_long / _total_liq
                if _long_pct > 0.6:
                    features["liquidation_bias"] = "LONG_DOMINANT"
                elif _long_pct < 0.4:
                    features["liquidation_bias"] = "SHORT_DOMINANT"
                else:
                    features["liquidation_bias"] = "BALANCED"
            else:
                features["liquidation_bias"] = "NONE"
            features["premium_index"] = _sf(fr_data, 'premium_index')
        except Exception:
            self.logger.debug("Feature extraction: derivatives partial failure")

        # ── FR Direction (depends on funding_rate_pct from derivatives above) ──
        try:
            fr_val = features.get("funding_rate_pct", 0.0)
            if fr_val > 0.005:
                features["fr_direction"] = "POSITIVE"
            elif fr_val < -0.005:
                features["fr_direction"] = "NEGATIVE"
            else:
                features["fr_direction"] = "NEUTRAL"
        except Exception:
            features.setdefault("fr_direction", "NEUTRAL")

        # ── Orderbook ──
        try:
            ob = orderbook_data or {}
            obi = ob.get('obi') or {}
            dynamics = ob.get('dynamics') or {}
            features["obi_weighted"] = _sf(obi, 'weighted')
            features["obi_change_pct"] = _sf(dynamics, 'obi_change_pct')
            features["bid_volume_usd"] = _sf(obi, 'bid_volume_usd')
            features["ask_volume_usd"] = _sf(obi, 'ask_volume_usd')
        except Exception:
            self.logger.debug("Feature extraction: orderbook partial failure")

        # ── Sentiment ──
        try:
            sd = sentiment_data or {}
            features["long_ratio"] = _sf(sd, 'positive_ratio')
            features["short_ratio"] = _sf(sd, 'negative_ratio')
            features["sentiment_degraded"] = bool(sd.get('degraded', False))
        except Exception:
            features.setdefault("sentiment_degraded", False)

        # ── Top Traders (Binance Derivatives) ──
        try:
            bd = binance_derivatives or {}
            # fetch_all() returns nested: top_long_short_position.latest.longShortRatio
            _top_pos = bd.get('top_long_short_position') or {}
            _top_latest = _top_pos.get('latest') or {} if isinstance(_top_pos, dict) else {}
            features["top_traders_long_ratio"] = _sf(_top_latest, 'longShortRatio')
            # fetch_all() returns nested: taker_long_short.latest.buySellRatio
            _taker = bd.get('taker_long_short') or {}
            _taker_latest = _taker.get('latest') or {} if isinstance(_taker, dict) else {}
            features["taker_buy_ratio"] = _sf(_taker_latest, 'buySellRatio')
        except Exception:
            self.logger.debug("Feature extraction: top traders partial failure")

        # ── S/R Zones ──
        # nearest_support / nearest_resistance are SRZone dataclass objects (not dicts),
        # so use getattr() instead of .get().  Field is price_center (not 'price').
        try:
            sz = sr_zones or {}
            ns = sz.get('nearest_support')  # SRZone dataclass or None
            nr = sz.get('nearest_resistance')
            atr_val = features.get('atr_30m', 1.0) or 1.0
            price = features.get('price', 0.0)

            sp = float(getattr(ns, 'price_center', 0.0)) if ns else 0.0
            features["nearest_support_price"] = sp
            features["nearest_support_strength"] = str(getattr(ns, 'strength', 'NONE')).upper() if ns else "NONE"
            features["nearest_support_dist_atr"] = abs(price - sp) / atr_val if sp > 0 and atr_val > 0 else 0.0

            rp = float(getattr(nr, 'price_center', 0.0)) if nr else 0.0
            features["nearest_resist_price"] = rp
            features["nearest_resist_strength"] = str(getattr(nr, 'strength', 'NONE')).upper() if nr else "NONE"
            features["nearest_resist_dist_atr"] = abs(price - rp) / atr_val if rp > 0 and atr_val > 0 else 0.0
        except Exception:
            self.logger.debug("Feature extraction: S/R zones partial failure")

        # ── Position Context ──
        try:
            cp = current_position or {}
            ac = account_context or {}
            ps = cp.get('side', 'FLAT')
            if ps and str(ps).upper() in ("LONG", "SHORT"):
                features["position_side"] = str(ps).upper()
            else:
                features["position_side"] = "FLAT"
            # v31.4: Fix field name mapping to match production data structures:
            # - _get_current_position_data() returns 'pnl_percentage' (not 'pnl_pct')
            # - _get_current_position_data() returns 'margin_used_pct' (not 'size_pct')
            # - _get_account_context() returns 'liquidation_buffer_portfolio_min_pct' (not 'liquidation_buffer_pct')
            features["position_pnl_pct"] = _sf(cp, 'pnl_percentage')
            features["position_size_pct"] = _sf(cp, 'margin_used_pct')
            features["account_equity_usdt"] = _sf(ac, 'equity')
            features["liquidation_buffer_pct"] = _sf(ac, 'liquidation_buffer_portfolio_min_pct')
            features["leverage"] = int(_sf(ac, 'leverage', 1))
        except Exception:
            features.setdefault("position_side", "FLAT")
            features.setdefault("leverage", 1)

        # ── FR Block Context ──
        try:
            fr_ctx = td.get('fr_block_context') or {}
            features["fr_consecutive_blocks"] = int(_sf(fr_ctx, 'consecutive_blocks', 0))
            features["fr_blocked_direction"] = _se(fr_ctx, 'blocked_direction',
                                                    {"LONG", "SHORT", "NONE"})
        except Exception:
            self.logger.debug("Feature extraction: FR block context partial failure")

        # ── Trend Time Series (1D, 5-bar summary) ──
        # v36.0 FIX: was using hist_ctx (30M) — adx_trend/di_plus_trend were 30M data
        # labeled as 1D, and rsi_trend_1d/price_trend_1d keys didn't exist → always empty.
        # Correct source is hist_ctx_1d (1D historical_context) with plain keys.
        try:
            adx_trend = hist_ctx_1d.get('adx_trend', [])
            rsi_1d_trend = hist_ctx_1d.get('rsi_trend', [])
            di_plus_trend = hist_ctx_1d.get('di_plus_trend', [])
            di_minus_trend = hist_ctx_1d.get('di_minus_trend', [])
            price_1d_trend = hist_ctx_1d.get('price_trend', [])

            features["adx_1d_trend_5bar"] = self._classify_trend(adx_trend[-5:]) if len(adx_trend) >= 5 else "FLAT"
            features["rsi_1d_trend_5bar"] = self._classify_trend(rsi_1d_trend[-5:]) if len(rsi_1d_trend) >= 5 else "FLAT"
            features["price_1d_change_5bar_pct"] = (
                ((price_1d_trend[-1] - price_1d_trend[-5]) / price_1d_trend[-5] * 100)
                if len(price_1d_trend) >= 5 and price_1d_trend[-5] > 0 else 0.0
            )

            if len(di_plus_trend) >= 5 and len(di_minus_trend) >= 5:
                spreads = [di_plus_trend[-5+i] - di_minus_trend[-5+i] for i in range(5)]
                features["di_spread_1d_trend_5bar"] = self._classify_spread_trend(spreads)
            else:
                features["di_spread_1d_trend_5bar"] = "FLAT"
        except Exception:
            for k in ("adx_1d_trend_5bar", "di_spread_1d_trend_5bar", "rsi_1d_trend_5bar"):
                features.setdefault(k, "FLAT")
            features.setdefault("price_1d_change_5bar_pct", 0.0)

        # ── 4H Time Series (5-bar summary) ──
        # v36.0 FIX: was using hist_ctx (30M) with '_4h' suffix keys that don't exist.
        # Correct source is hist_ctx_4h (4H historical_context) with plain keys.
        try:
            rsi_4h_hist = hist_ctx_4h.get('rsi_trend', [])
            macd_hist_4h_hist = hist_ctx_4h.get('macd_histogram_trend', [])
            adx_4h_hist = hist_ctx_4h.get('adx_trend', [])
            price_4h_hist = hist_ctx_4h.get('price_trend', [])

            features["rsi_4h_trend_5bar"] = self._classify_trend(rsi_4h_hist[-5:]) if len(rsi_4h_hist) >= 5 else "FLAT"
            features["adx_4h_trend_5bar"] = self._classify_trend(adx_4h_hist[-5:]) if len(adx_4h_hist) >= 5 else "FLAT"
            features["price_4h_change_5bar_pct"] = (
                ((price_4h_hist[-1] - price_4h_hist[-5]) / price_4h_hist[-5] * 100)
                if len(price_4h_hist) >= 5 and price_4h_hist[-5] > 0 else 0.0
            )

            if len(macd_hist_4h_hist) >= 5:
                abs_vals = [abs(v) for v in macd_hist_4h_hist[-5:]]
                features["macd_histogram_4h_trend_5bar"] = self._classify_abs_trend(abs_vals)
            else:
                features["macd_histogram_4h_trend_5bar"] = "FLAT"

            # v36.0: BB width trend for squeeze/expansion detection
            bb_width_4h = hist_ctx_4h.get('bb_width_trend', [])
            if len(bb_width_4h) >= 5:
                features["bb_width_4h_trend_5bar"] = self._classify_trend(bb_width_4h[-5:])
            else:
                features["bb_width_4h_trend_5bar"] = "FLAT"
        except Exception:
            for k in ("rsi_4h_trend_5bar", "macd_histogram_4h_trend_5bar", "adx_4h_trend_5bar",
                       "bb_width_4h_trend_5bar"):
                features.setdefault(k, "FLAT")
            features.setdefault("price_4h_change_5bar_pct", 0.0)

        # ── 30M Time Series (5-bar summary) ──
        try:
            price_30m_hist = hist_ctx.get('price_trend', [])
            rsi_30m_hist = hist_ctx.get('rsi_trend', [])

            features["rsi_30m_trend_5bar"] = self._classify_trend(rsi_30m_hist[-5:]) if len(rsi_30m_hist) >= 5 else "FLAT"
            features["price_30m_change_5bar_pct"] = (
                ((price_30m_hist[-1] - price_30m_hist[-5]) / price_30m_hist[-5] * 100)
                if len(price_30m_hist) >= 5 and price_30m_hist[-5] > 0 else 0.0
            )

            if len(rsi_30m_hist) >= 5:
                recent_slope = rsi_30m_hist[-1] - rsi_30m_hist[-3]
                older_slope = rsi_30m_hist[-3] - rsi_30m_hist[-5]
                if abs(recent_slope) > abs(older_slope) * 1.3:
                    features["momentum_shift_30m"] = "ACCELERATING"
                elif abs(recent_slope) < abs(older_slope) * 0.7:
                    features["momentum_shift_30m"] = "DECELERATING"
                else:
                    features["momentum_shift_30m"] = "STABLE"
            else:
                features["momentum_shift_30m"] = "STABLE"

            # v36.0: BB width trend for squeeze/expansion detection
            bb_width_30m = hist_ctx.get('bb_width_trend', [])
            if len(bb_width_30m) >= 5:
                features["bb_width_30m_trend_5bar"] = self._classify_trend(bb_width_30m[-5:])
            else:
                features["bb_width_30m_trend_5bar"] = "FLAT"
        except Exception:
            features.setdefault("momentum_shift_30m", "STABLE")
            features.setdefault("rsi_30m_trend_5bar", "FLAT")
            features.setdefault("bb_width_30m_trend_5bar", "FLAT")
            features.setdefault("price_30m_change_5bar_pct", 0.0)

        # ── Reliability annotations ──
        try:
            adx_1d = features.get("adx_1d", 30.0)
            reliability = {}
            indicator_keys = {
                'rsi_30m': '30m_rsi', 'macd_30m': '30m_macd', 'adx_30m': '30m_adx',
                'bb_position_30m': '30m_bb', 'volume_ratio_30m': '30m_volume',
                'rsi_4h': '4h_rsi', 'macd_4h': '4h_macd', 'adx_4h': '4h_adx',
                'bb_position_4h': '4h_bb', 'volume_ratio_4h': '4h_vol_ratio',
                'adx_1d': '1d_adx', 'rsi_1d': '1d_rsi', 'macd_1d': '1d_macd',
                'bb_position_1d': '1d_bb', 'atr_1d': '1d_atr', 'atr_4h': '4h_atr',
            }
            for feat_key, annot_key in indicator_keys.items():
                _, _, tier = _get_multiplier(annot_key, adx_1d)
                reliability[feat_key] = tier.upper()
            features["_reliability"] = reliability
        except Exception:
            features["_reliability"] = {}

        # Fill defaults for any missing keys
        for key, schema in FEATURE_SCHEMA.items():
            if key.startswith("_"):
                continue
            if key not in features:
                ftype = schema.get("type", "float")
                if ftype == "float":
                    features[key] = 0.0
                elif ftype == "int":
                    features[key] = 0
                elif ftype == "bool":
                    features[key] = False
                elif ftype == "enum":
                    vals = schema.get("values", ["NONE"])
                    features[key] = "NONE" if "NONE" in vals else vals[0]

        # --- Runtime cross-validation against FEATURE_SCHEMA ---
        _validation_warnings: list = []
        for key, spec in FEATURE_SCHEMA.items():
            if key.startswith("_"):
                continue
            val = features.get(key)
            if val is None:
                continue
            expected_type = spec.get("type", "float")
            if expected_type == "float" and not isinstance(val, (int, float)):
                _validation_warnings.append(f"{key}: expected float, got {type(val).__name__}")
                features[key] = 0.0
            elif expected_type == "int" and not isinstance(val, int):
                _validation_warnings.append(f"{key}: expected int, got {type(val).__name__}")
                features[key] = int(val) if isinstance(val, (float, int)) else 0
            elif expected_type == "enum" and isinstance(val, str):
                valid_vals = spec.get("values", [])
                if valid_vals and val not in valid_vals:
                    _validation_warnings.append(f"{key}: '{val}' not in {valid_vals}")
                    features[key] = "NONE" if "NONE" in valid_vals else valid_vals[0]
            elif expected_type == "bool" and not isinstance(val, bool):
                features[key] = bool(val)

        # Drift detection: keys in features but NOT in FEATURE_SCHEMA
        extra_keys = set(k for k in features if not k.startswith("_")) - set(FEATURE_SCHEMA.keys())
        if extra_keys:
            _validation_warnings.append(f"Extra keys not in FEATURE_SCHEMA: {extra_keys}")

        if _validation_warnings:
            self.logger.warning(
                f"Feature validation: {len(_validation_warnings)} warning(s): "
                + "; ".join(_validation_warnings[:5])
            )

        # ── Data Quality Metadata (v28.0) ──
        # Tracks which data sources were unavailable, so AI can distinguish
        # "data says neutral" from "data is missing".
        unavailable = []
        if not order_flow_data:
            unavailable.append("order_flow_30m")
        if not order_flow_4h:
            unavailable.append("order_flow_4h")
        if not derivatives_data:
            unavailable.append("derivatives")
        if not binance_derivatives:
            unavailable.append("top_traders")
        if not orderbook_data:
            unavailable.append("orderbook")
        if features.get("sentiment_degraded"):
            unavailable.append("sentiment")
        if not sr_zones or (not sr_zones.get('nearest_support') and not sr_zones.get('nearest_resistance')):
            unavailable.append("sr_zones")
        features["_unavailable"] = unavailable

        return features

    @staticmethod
    def _classify_trend(series: List[float]) -> str:
        """Classify a short numeric series as RISING/FALLING/FLAT.

        Uses last-vs-first comparison instead of half-average.
        Half-average is structurally flawed for 5-bar series with
        mountain/valley shapes: a peak at index 2 gets assigned to
        second_half, masking the actual trend direction.
        """
        if not series or len(series) < 2:
            return "FLAT"
        diff_pct = (series[-1] - series[0]) / max(abs(series[0]), 1e-9) * 100
        if diff_pct > 5:
            return "RISING"
        elif diff_pct < -5:
            return "FALLING"
        return "FLAT"

    @staticmethod
    def _classify_abs_trend(abs_series: List[float]) -> str:
        """Classify absolute-value trend as EXPANDING/CONTRACTING/FLAT.

        Uses last-vs-first ratio instead of half-average ratio.
        Half-average masks momentum collapse when peak is in the middle
        (e.g. [100, 107, 130, 106, 35] → half-avg says FLAT, but
        momentum clearly collapsed to 27% of peak).
        """
        if not abs_series or len(abs_series) < 2:
            return "FLAT"
        first_val = abs(abs_series[0])
        last_val = abs(abs_series[-1])
        if first_val < 1e-9:
            return "FLAT"
        ratio = last_val / first_val
        if ratio > 1.15:
            return "EXPANDING"
        elif ratio < 0.85:
            return "CONTRACTING"
        return "FLAT"

    @staticmethod
    def _classify_spread_trend(spreads: List[float]) -> str:
        """Classify DI spread trend as WIDENING/NARROWING/FLAT.

        Uses last-vs-first abs-spread ratio instead of half-average.
        """
        if not spreads or len(spreads) < 2:
            return "FLAT"
        first_abs = abs(spreads[0])
        last_abs = abs(spreads[-1])
        if first_abs < 1e-9:
            return "FLAT"
        ratio = last_abs / first_abs
        if ratio > 1.1:
            return "WIDENING"
        elif ratio < 0.9:
            return "NARROWING"
        return "FLAT"

    @staticmethod
    def _compute_cvd_price_cross(
        cvd_history: List[float],
        price_series: List[float],
    ) -> str:
        """
        v34.3: Compute CVD-Price cross classification from raw data.

        Mirrors _format_order_flow_report() logic (v19.2):
        - CVD net = sum of last 5 bars (or all if < 5)
        - Price change = 5-bar percentage change
        - Thresholds: ±0.3% for price flat/rising/falling

        Returns one of: ACCUMULATION, DISTRIBUTION, CONFIRMED_SELL,
                        ABSORPTION_BUY, ABSORPTION_SELL, NONE
        """
        if len(cvd_history) < 3 or len(price_series) < 2:
            return "NONE"

        cvd_net = sum(cvd_history[-5:]) if len(cvd_history) >= 5 else sum(cvd_history)

        # 5-bar price change (matching CVD window)
        if len(price_series) >= 5 and price_series[-5] > 0:
            price_change_pct = (price_series[-1] - price_series[-5]) / price_series[-5] * 100
        elif price_series[0] > 0:
            price_change_pct = (price_series[-1] - price_series[0]) / price_series[0] * 100
        else:
            return "NONE"

        price_flat = abs(price_change_pct) <= 0.3
        price_falling = price_change_pct < -0.3
        price_rising = price_change_pct > 0.3
        cvd_positive = cvd_net > 0
        cvd_negative = cvd_net < 0

        if price_falling and cvd_positive:
            return "ACCUMULATION"
        elif price_rising and cvd_negative:
            return "DISTRIBUTION"
        elif price_falling and cvd_negative:
            return "CONFIRMED_SELL"
        elif price_flat and cvd_positive:
            return "ABSORPTION_BUY"
        elif price_flat and cvd_negative:
            return "ABSORPTION_SELL"
        return "NONE"
