"""
Integration test for v34.0 logic-level coherence checks.

Constructs a full AnalysisContext → calls audit() → verifies v34.0 flags
appear in the returned QualityReport.

Tests cover all 6 checks:
  Check 1: Reason-Signal Alignment (PENALIZED)
  Check 2: Signal-Score Divergence (informational)
  Check 3: Confidence-Risk Coherence (PENALIZED)
  Check 4: Debate Conviction Spread (informational)
  Check 5: Decisive Reasons Diversity (informational)
  Check 6: Shallow Round 2 Detection (informational, v34.1)
"""
import pytest
from agents.analysis_context import AnalysisContext
from agents.ai_quality_auditor import AIQualityAuditor, QualityReport


def _make_ctx(**overrides) -> AnalysisContext:
    """Build a minimal AnalysisContext with sensible defaults for auditor testing."""
    ctx = AnalysisContext()
    # Minimal features so auditor doesn't skip all checks
    ctx.features = overrides.get('features', {
        'adx_1d': 30.0,
        'rsi_30m': 50.0,
        'current_price': 90000.0,
    })
    ctx.scores = overrides.get('scores', {
        'trend': {'score': 5, 'level': 'NEUTRAL', 'direction': 'NEUTRAL'},
        'momentum': {'score': 5, 'level': 'NEUTRAL', 'direction': 'NEUTRAL'},
        'order_flow': {'score': 5, 'level': 'NEUTRAL', 'direction': 'NEUTRAL'},
        'vol_ext_risk': {'score': 3, 'level': 'LOW'},
        'risk_env': overrides.get('risk_env', {'score': 3, 'level': 'LOW'}),
        'net': overrides.get('net', 'CONFLICTING_1of3'),
    })
    ctx.valid_tags = overrides.get('valid_tags', set())

    # Bull/Bear outputs
    ctx.bull_output = overrides.get('bull_output', {
        'conviction': 0.7,
        'evidence': ['TREND_1D_BULLISH'],
        'risk_flags': [],
        'reasoning': 'Bullish trend on 1D.',
        'summary': 'Bullish.',
    })
    ctx.bear_output = overrides.get('bear_output', {
        'conviction': 0.4,
        'evidence': ['TREND_1D_BEARISH'],
        'risk_flags': [],
        'reasoning': 'Bearish signals.',
        'summary': 'Bearish.',
    })
    ctx.debate_bull_text = overrides.get('debate_bull_text', 'Bull argues for uptrend.')
    ctx.debate_bear_text = overrides.get('debate_bear_text', 'Bear argues for downtrend.')

    # Judge output
    ctx.judge_output = overrides.get('judge_output', {
        'decision': 'HOLD',
        'confidence': 'MEDIUM',
        'decisive_reasons': [],
        'rationale': 'Market unclear.',
    })

    # ET/Risk outputs
    ctx.et_output = overrides.get('et_output', None)
    ctx.risk_output = overrides.get('risk_output', None)

    # Raw data fallback
    ctx.raw_data = overrides.get('raw_data', {
        'technical': {'rsi': 50.0},
    })
    return ctx


class TestReasonSignalAlignment:
    """Check 1: Judge decision vs its own decisive_reasons tags."""

    def test_long_with_bearish_majority_triggers_conflict(self):
        """LONG decision with mostly bearish tags → REASON_SIGNAL_CONFLICT flag."""
        ctx = _make_ctx(judge_output={
            'decision': 'LONG',
            'confidence': 'MEDIUM',
            'decisive_reasons': [
                'CVD_NEGATIVE', 'CVD_DISTRIBUTION', 'OBI_SELL_PRESSURE',
                'TREND_1D_BULLISH',
            ],
            'rationale': 'Going long despite bearish order flow.',
        })
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        conflict_flags = [f for f in report.flags if 'REASON_SIGNAL_CONFLICT' in f]
        assert len(conflict_flags) >= 1, f"Expected REASON_SIGNAL_CONFLICT flag, got flags: {report.flags}"
        assert report.reason_signal_conflict > 0
        assert report.overall_score < 100

    def test_long_with_bullish_majority_no_conflict(self):
        """LONG decision with matching bullish tags → no conflict."""
        ctx = _make_ctx(judge_output={
            'decision': 'LONG',
            'confidence': 'MEDIUM',
            'decisive_reasons': [
                'CVD_POSITIVE', 'TREND_1D_BULLISH', 'OBI_BUY_PRESSURE',
            ],
            'rationale': 'Bullish signals align.',
        })
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        conflict_flags = [f for f in report.flags if 'REASON_SIGNAL_CONFLICT' in f]
        assert len(conflict_flags) == 0, f"Unexpected REASON_SIGNAL_CONFLICT: {conflict_flags}"
        assert report.reason_signal_conflict == 0

    def test_hold_exempt_from_check(self):
        """HOLD decision is exempt from reason-signal alignment check."""
        ctx = _make_ctx(judge_output={
            'decision': 'HOLD',
            'confidence': 'MEDIUM',
            'decisive_reasons': ['CVD_NEGATIVE', 'TREND_1D_BULLISH'],
            'rationale': 'Mixed signals.',
        })
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)
        assert report.reason_signal_conflict == 0

    def test_weak_signals_excluded(self):
        """Weak signal tags (FR_FAVORABLE_*) should not count in conflict ratio."""
        ctx = _make_ctx(judge_output={
            'decision': 'LONG',
            'confidence': 'MEDIUM',
            'decisive_reasons': [
                'TREND_1D_BULLISH', 'CVD_POSITIVE',
                'FR_FAVORABLE_SHORT',  # Weak signal — should be excluded
            ],
            'rationale': 'Bullish with negligible FR.',
        })
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)
        # FR_FAVORABLE_SHORT is weak → excluded → 2 bullish / 0 bearish → no conflict
        assert report.reason_signal_conflict == 0


class TestSignalScoreDivergence:
    """Check 2: Judge decision vs _scores['net'] consensus."""

    def test_bullish_scores_short_decision_flags_divergence(self):
        """LEAN_BULLISH + SHORT decision → SIGNAL_SCORE_DIVERGENCE flag."""
        ctx = _make_ctx(
            net='LEAN_BULLISH_3of3',
            judge_output={
                'decision': 'SHORT',
                'confidence': 'MEDIUM',
                'decisive_reasons': ['CVD_NEGATIVE'],
                'rationale': 'Shorting against trend.',
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        div_flags = [f for f in report.flags if 'SIGNAL_SCORE_DIVERGENCE' in f]
        assert len(div_flags) >= 1, f"Expected SIGNAL_SCORE_DIVERGENCE flag, got: {report.flags}"

    def test_aligned_direction_no_flag(self):
        """LEAN_BULLISH + LONG decision → no divergence flag."""
        ctx = _make_ctx(
            net='LEAN_BULLISH_2of3',
            judge_output={
                'decision': 'LONG',
                'confidence': 'MEDIUM',
                'decisive_reasons': ['TREND_1D_BULLISH'],
                'rationale': 'Aligned with scores.',
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        div_flags = [f for f in report.flags if 'SIGNAL_SCORE_DIVERGENCE' in f]
        assert len(div_flags) == 0

    def test_conflicting_scores_exempt(self):
        """CONFLICTING net score → no divergence flag (no clear consensus)."""
        ctx = _make_ctx(
            net='CONFLICTING_1of3',
            judge_output={
                'decision': 'LONG',
                'confidence': 'MEDIUM',
                'decisive_reasons': ['TREND_1D_BULLISH'],
                'rationale': 'Going long.',
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        div_flags = [f for f in report.flags if 'SIGNAL_SCORE_DIVERGENCE' in f]
        assert len(div_flags) == 0


class TestConfidenceRiskCoherence:
    """Check 3: HIGH confidence + HIGH risk environment → penalty."""

    def test_high_confidence_high_risk_triggers_penalty(self):
        """HIGH confidence in HIGH risk environment → CONFIDENCE_RISK_CONFLICT."""
        ctx = _make_ctx(
            risk_env={'score': 7, 'level': 'HIGH'},
            judge_output={
                'decision': 'LONG',
                'confidence': 'HIGH',
                'decisive_reasons': ['TREND_1D_BULLISH', 'CVD_POSITIVE'],
                'rationale': 'Very confident.',
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        crc_flags = [f for f in report.flags if 'CONFIDENCE_RISK_CONFLICT' in f]
        assert len(crc_flags) >= 1, f"Expected CONFIDENCE_RISK_CONFLICT, got: {report.flags}"
        assert report.confidence_risk_conflict == 6
        assert report.overall_score < 100

    def test_medium_confidence_high_risk_no_penalty(self):
        """MEDIUM confidence in HIGH risk → no penalty (conservative is OK)."""
        ctx = _make_ctx(
            risk_env={'score': 7, 'level': 'HIGH'},
            judge_output={
                'decision': 'LONG',
                'confidence': 'MEDIUM',
                'decisive_reasons': ['TREND_1D_BULLISH'],
                'rationale': 'Moderate confidence.',
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)
        assert report.confidence_risk_conflict == 0

    def test_high_confidence_low_risk_no_penalty(self):
        """HIGH confidence in LOW risk → perfectly fine."""
        ctx = _make_ctx(
            risk_env={'score': 2, 'level': 'LOW'},
            judge_output={
                'decision': 'LONG',
                'confidence': 'HIGH',
                'decisive_reasons': ['TREND_1D_BULLISH', 'CVD_POSITIVE'],
                'rationale': 'Confident in safe environment.',
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)
        assert report.confidence_risk_conflict == 0


class TestDebateConvictionSpread:
    """Check 4: Echo chamber detection via conviction spread."""

    def test_low_spread_triggers_flag(self):
        """Bull 0.82 / Bear 0.78 (spread 0.04) → DEBATE_CONVERGENCE flag."""
        ctx = _make_ctx(
            bull_output={
                'conviction': 0.82, 'evidence': ['TREND_1D_BULLISH'],
                'risk_flags': [], 'reasoning': 'Bull.', 'summary': 'Bull.',
            },
            bear_output={
                'conviction': 0.78, 'evidence': ['TREND_1D_BEARISH'],
                'risk_flags': [], 'reasoning': 'Bear.', 'summary': 'Bear.',
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        dc_flags = [f for f in report.flags if 'DEBATE_CONVERGENCE' in f]
        assert len(dc_flags) >= 1, f"Expected DEBATE_CONVERGENCE flag, got: {report.flags}"

    def test_healthy_spread_no_flag(self):
        """Bull 0.9 / Bear 0.3 (spread 0.6) → no echo chamber flag."""
        ctx = _make_ctx(
            bull_output={
                'conviction': 0.9, 'evidence': ['TREND_1D_BULLISH'],
                'risk_flags': [], 'reasoning': 'Strong bull.', 'summary': 'Bull.',
            },
            bear_output={
                'conviction': 0.3, 'evidence': ['TREND_1D_BEARISH'],
                'risk_flags': [], 'reasoning': 'Weak bear.', 'summary': 'Bear.',
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        dc_flags = [f for f in report.flags if 'DEBATE_CONVERGENCE' in f]
        assert len(dc_flags) == 0


class TestReasonDiversity:
    """Check 5: Single-dimension decision detection."""

    def test_single_dimension_triggers_flag(self):
        """All decisive_reasons from same category → SINGLE_DIMENSION_DECISION."""
        ctx = _make_ctx(judge_output={
            'decision': 'LONG',
            'confidence': 'MEDIUM',
            'decisive_reasons': [
                'SMA_BULLISH_CROSS_4H', 'MOMENTUM_4H_BULLISH',
                'RSI_CARDWELL_BULL',
            ],
            'rationale': 'All 4H signals.',
        })
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        sd_flags = [f for f in report.flags if 'SINGLE_DIMENSION_DECISION' in f]
        assert len(sd_flags) >= 1, f"Expected SINGLE_DIMENSION_DECISION flag, got: {report.flags}"

    def test_diverse_reasons_no_flag(self):
        """Tags from multiple categories → no fixation flag."""
        ctx = _make_ctx(judge_output={
            'decision': 'LONG',
            'confidence': 'MEDIUM',
            'decisive_reasons': [
                'TREND_1D_BULLISH',    # mtf_1d
                'CVD_POSITIVE',        # order_flow
                'OBI_BUY_PRESSURE',    # orderbook
            ],
            'rationale': 'Multi-dimensional evidence.',
        })
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        sd_flags = [f for f in report.flags if 'SINGLE_DIMENSION_DECISION' in f]
        assert len(sd_flags) == 0


class TestQualityReportSerialization:
    """Verify new fields appear in to_summary() and to_dict()."""

    def test_to_summary_includes_new_fields(self):
        """to_summary() shows reason_sig and conf_risk when non-zero."""
        r = QualityReport(
            reason_signal_conflict=8,
            confidence_risk_conflict=6,
            overall_score=86,
        )
        s = r.to_summary()
        assert 'reason_sig=8' in s
        assert 'conf_risk=6' in s

    def test_to_summary_omits_zero_fields(self):
        """to_summary() does NOT show new fields when zero."""
        r = QualityReport()
        s = r.to_summary()
        assert 'reason_sig' not in s
        assert 'conf_risk' not in s

    def test_to_dict_always_includes_new_keys(self):
        """to_dict() always has the new keys (even if 0)."""
        r = QualityReport()
        d = r.to_dict()
        assert 'reason_signal_conflict' in d
        assert 'confidence_risk_conflict' in d
        assert d['reason_signal_conflict'] == 0
        assert d['confidence_risk_conflict'] == 0


class TestDebateShallowRound2:
    """Check 6: R1→R2 evidence stagnation detection (v34.1)."""

    def test_both_agents_stagnant_triggers_flag(self):
        """When both Bull and Bear produce identical R1/R2 evidence → DEBATE_SHALLOW_R2."""
        ctx = _make_ctx(
            bull_output={
                'conviction': 0.7, 'evidence': ['TREND_1D_BULLISH', 'CVD_POSITIVE'],
                'risk_flags': [], 'reasoning': 'Same as R1.', 'summary': 'Bull.',
                '_r1_r2_evidence_overlap': 1.0,  # Identical tags
                '_r1_r2_evidence_new': 0,          # No new tags
                '_r1_r2_conviction_delta': 0.02,   # Barely changed
            },
            bear_output={
                'conviction': 0.6, 'evidence': ['TREND_1D_BEARISH'],
                'risk_flags': [], 'reasoning': 'Same as R1.', 'summary': 'Bear.',
                '_r1_r2_evidence_overlap': 1.0,
                '_r1_r2_evidence_new': 0,
                '_r1_r2_conviction_delta': 0.01,
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)
        flag_prefixes = [f.split(':')[0] for f in report.flags]
        assert 'DEBATE_SHALLOW_R2' in flag_prefixes, \
            f"Missing DEBATE_SHALLOW_R2 in {report.flags}"

    def test_one_agent_evolved_no_flag(self):
        """When one agent introduces new evidence in R2, no shallow flag."""
        ctx = _make_ctx(
            bull_output={
                'conviction': 0.8, 'evidence': ['TREND_1D_BULLISH', 'CVD_POSITIVE'],
                'risk_flags': [], 'reasoning': 'Updated analysis.', 'summary': 'Bull.',
                '_r1_r2_evidence_overlap': 0.5,    # Significant change
                '_r1_r2_evidence_new': 2,           # New tags added
                '_r1_r2_conviction_delta': 0.15,    # Conviction shifted
            },
            bear_output={
                'conviction': 0.6, 'evidence': ['TREND_1D_BEARISH'],
                'risk_flags': [], 'reasoning': 'Same.', 'summary': 'Bear.',
                '_r1_r2_evidence_overlap': 1.0,
                '_r1_r2_evidence_new': 0,
                '_r1_r2_conviction_delta': 0.01,
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)
        flag_prefixes = [f.split(':')[0] for f in report.flags]
        assert 'DEBATE_SHALLOW_R2' not in flag_prefixes

    def test_conviction_shift_prevents_flag(self):
        """Even with same evidence tags, a significant conviction change means R2 engaged."""
        ctx = _make_ctx(
            bull_output={
                'conviction': 0.7, 'evidence': ['TREND_1D_BULLISH'],
                'risk_flags': [], 'reasoning': 'Analysis.', 'summary': 'Bull.',
                '_r1_r2_evidence_overlap': 1.0,
                '_r1_r2_evidence_new': 0,
                '_r1_r2_conviction_delta': 0.15,   # Conviction changed significantly
            },
            bear_output={
                'conviction': 0.6, 'evidence': ['TREND_1D_BEARISH'],
                'risk_flags': [], 'reasoning': 'Analysis.', 'summary': 'Bear.',
                '_r1_r2_evidence_overlap': 1.0,
                '_r1_r2_evidence_new': 0,
                '_r1_r2_conviction_delta': 0.10,   # Also shifted
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)
        flag_prefixes = [f.split(':')[0] for f in report.flags]
        assert 'DEBATE_SHALLOW_R2' not in flag_prefixes

    def test_no_metrics_skips_check(self):
        """When R1/R2 metrics are absent (text fallback path), check is skipped."""
        ctx = _make_ctx(
            bull_output={
                'conviction': 0.7, 'evidence': ['TREND_1D_BULLISH'],
                'risk_flags': [], 'reasoning': 'Analysis.', 'summary': 'Bull.',
                # No _r1_r2_* metrics
            },
            bear_output={
                'conviction': 0.6, 'evidence': ['TREND_1D_BEARISH'],
                'risk_flags': [], 'reasoning': 'Analysis.', 'summary': 'Bear.',
                # No _r1_r2_* metrics
            },
        )
        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)
        flag_prefixes = [f.split(':')[0] for f in report.flags]
        assert 'DEBATE_SHALLOW_R2' not in flag_prefixes


class TestFullAuditIntegration:
    """End-to-end: construct AnalysisContext → audit() → verify multiple v34.0 flags."""

    def test_multiple_v34_flags_in_single_audit(self):
        """A badly incoherent cycle should trigger multiple v34.0 flags simultaneously."""
        ctx = _make_ctx(
            # Bearish scores net but Judge goes LONG
            net='LEAN_BEARISH_3of3',
            # HIGH risk environment + HIGH confidence → confidence-risk conflict
            risk_env={'score': 8, 'level': 'HIGH'},
            # Echo chamber: similar convictions
            bull_output={
                'conviction': 0.72, 'evidence': ['TREND_1D_BULLISH'],
                'risk_flags': [], 'reasoning': 'Bull analysis.', 'summary': 'Bull.',
            },
            bear_output={
                'conviction': 0.68, 'evidence': ['TREND_1D_BEARISH'],
                'risk_flags': [], 'reasoning': 'Bear analysis.', 'summary': 'Bear.',
            },
            # Judge: LONG with mostly bearish reasons + HIGH confidence
            judge_output={
                'decision': 'LONG',
                'confidence': 'HIGH',
                'decisive_reasons': [
                    'CVD_NEGATIVE', 'OBI_SELL_PRESSURE', 'MACD_BEARISH_CROSS',
                    'TREND_1D_BULLISH',
                ],
                'rationale': 'Going long despite all bearish signals.',
            },
        )

        auditor = AIQualityAuditor()
        report = auditor.audit(ctx)

        # Verify all expected v34.0 flags are present
        flag_prefixes = [f.split(':')[0] for f in report.flags]

        assert 'REASON_SIGNAL_CONFLICT' in flag_prefixes, \
            f"Missing REASON_SIGNAL_CONFLICT in {report.flags}"
        assert 'SIGNAL_SCORE_DIVERGENCE' in flag_prefixes, \
            f"Missing SIGNAL_SCORE_DIVERGENCE in {report.flags}"
        assert 'CONFIDENCE_RISK_CONFLICT' in flag_prefixes, \
            f"Missing CONFIDENCE_RISK_CONFLICT in {report.flags}"
        assert 'DEBATE_CONVERGENCE' in flag_prefixes, \
            f"Missing DEBATE_CONVERGENCE in {report.flags}"

        # Verify penalties applied
        assert report.reason_signal_conflict > 0
        assert report.confidence_risk_conflict == 6
        assert report.overall_score < 100 - 14  # At least 8+6 = 14 from v34.0 alone
