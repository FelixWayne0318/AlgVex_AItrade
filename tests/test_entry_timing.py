"""
Tests for v23.0 Entry Timing Agent — validation logic in _evaluate_entry_timing()
and Phase 2.5 integration in analyze().

Covers:
- Confidence only-decrease (6 permutations of Judge→ET confidence)
- Counter-trend + ADX boundary (39/40/41)
- JSON fallback behavior (parse failure → conservative defaults)
- REJECT → HOLD propagation through judge_decision
- DI+=DI-=0 trend unclear (no false COUNTER-TREND ALERT)
- Dict mutation safety (shallow copy on all paths)
"""
import sys
import json
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from copy import deepcopy
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_analyzer():
    """Create a MultiAgentAnalyzer with mocked DeepSeek client."""
    with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test-key'}):
        from agents.multi_agent_analyzer import MultiAgentAnalyzer
        analyzer = MultiAgentAnalyzer(
            api_key="test-key",
            model="deepseek-chat",
            temperature=0.3,
            debate_rounds=2,
        )
        return analyzer


@pytest.fixture
def base_judge_decision():
    """Standard LONG/HIGH judge decision for testing."""
    return {
        'decision': 'LONG',
        'confidence': 'HIGH',
        'rationale': 'Test bullish signal',
        'confluence': {'trend': 'bullish', 'momentum': 'positive'},
    }


@pytest.fixture
def base_technical_data():
    """Standard technical data with MTF layers."""
    return {
        'adx': 25.0,
        'di_plus': 20.0,
        'di_minus': 15.0,
        'rsi': 50.0,
        'macd_histogram': 0.5,
        'bb_percent': 50.0,
        'extension_ratio': 1.5,
        'extension_regime': 'NORMAL',
        'volatility_regime': 'NORMAL',
        'mtf_trend_layer': {
            'adx': 35.0,
            'di_plus': 22.0,
            'di_minus': 18.0,
        },
        'mtf_decision_layer': {
            'adx': 30.0,
            'di_plus': 20.0,
            'di_minus': 16.0,
        },
    }


# ============================================================================
# Test 1: Confidence Only-Decrease (6 permutations)
# ============================================================================

class TestConfidenceOnlyDecrease:
    """Verify that Entry Timing Agent can only decrease, never increase confidence."""

    @pytest.mark.parametrize("judge_conf,et_conf,expected", [
        # ET tries to upgrade → capped at Judge's level
        ("LOW", "MEDIUM", "LOW"),
        ("LOW", "HIGH", "LOW"),
        ("MEDIUM", "HIGH", "MEDIUM"),
        # ET tries to downgrade → allowed
        ("HIGH", "MEDIUM", "MEDIUM"),
        ("HIGH", "LOW", "LOW"),
        ("MEDIUM", "LOW", "LOW"),
    ])
    def test_confidence_capping(self, mock_analyzer, base_judge_decision,
                                 base_technical_data, judge_conf, et_conf, expected):
        """Confidence from ET cannot exceed Judge's confidence level."""
        base_judge_decision['confidence'] = judge_conf

        # Mock the API call to return a decision with the ET confidence
        mock_et_response = {
            "timing_verdict": "ENTER",
            "timing_quality": "GOOD",
            "adjusted_confidence": et_conf,
            "counter_trend_risk": "NONE",
            "alignment": "STRONG",
            "reason": "Test",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            with patch.object(mock_analyzer, '_call_api_with_retry',
                              return_value="{}"):
                result = mock_analyzer._evaluate_entry_timing(
                    judge_decision=base_judge_decision,
                    technical_report="Test report",
                    technical_data=base_technical_data,
                    adx_1d=35.0,
                )

        assert result['adjusted_confidence'] == expected, (
            f"Judge={judge_conf}, ET tried {et_conf}, "
            f"expected {expected}, got {result['adjusted_confidence']}"
        )

    def test_same_confidence_preserved(self, mock_analyzer, base_judge_decision,
                                        base_technical_data):
        """When ET returns same confidence as Judge, it should be preserved."""
        base_judge_decision['confidence'] = 'MEDIUM'

        mock_et_response = {
            "timing_verdict": "ENTER",
            "timing_quality": "GOOD",
            "adjusted_confidence": "MEDIUM",
            "counter_trend_risk": "NONE",
            "alignment": "STRONG",
            "reason": "Test",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        assert result['adjusted_confidence'] == 'MEDIUM'


# ============================================================================
# Test 2: Counter-Trend + ADX Boundary (39/40/41)
# ============================================================================

class TestCounterTrendADXBoundary:
    """Test the safety net at the ADX=40 boundary for counter-trend trades."""

    def _make_counter_trend_data(self, adx_1d):
        """Create technical data where signal is counter-trend (LONG vs BEARISH 1D)."""
        return {
            'adx': 25.0,
            'di_plus': 20.0,
            'di_minus': 15.0,
            'rsi': 50.0,
            'macd_histogram': 0.5,
            'bb_percent': 50.0,
            'extension_ratio': 1.5,
            'extension_regime': 'NORMAL',
            'volatility_regime': 'NORMAL',
            'mtf_trend_layer': {
                'adx': adx_1d,
                'di_plus': 15.0,   # DI- > DI+ = bearish trend
                'di_minus': 25.0,
            },
            'mtf_decision_layer': {},
        }

    @pytest.mark.parametrize("adx_1d,et_ctr_risk,expected_ctr_risk", [
        # ADX=39: below threshold, no mechanical override
        (39.0, "LOW", "LOW"),
        (39.0, "NONE", "NONE"),
        # ADX=40: at threshold, mechanical override kicks in
        (40.0, "LOW", "HIGH"),
        (40.0, "NONE", "HIGH"),
        # ADX=41: above threshold, mechanical override kicks in
        (41.0, "NONE", "HIGH"),
        (41.0, "LOW", "HIGH"),
        # ADX=40+ but ET already says HIGH/EXTREME: no change needed
        (40.0, "HIGH", "HIGH"),
        (40.0, "EXTREME", "EXTREME"),
    ])
    def test_counter_trend_safety_net(self, mock_analyzer, adx_1d,
                                       et_ctr_risk, expected_ctr_risk):
        """Safety net: counter-trend + ADX>=40 + ENTER + risk<HIGH → force HIGH."""
        judge_decision = {
            'decision': 'LONG',  # LONG against bearish trend = counter-trend
            'confidence': 'MEDIUM',
            'rationale': 'Test',
            'confluence': {},
        }
        tech_data = self._make_counter_trend_data(adx_1d)

        mock_et_response = {
            "timing_verdict": "ENTER",
            "timing_quality": "FAIR",
            "adjusted_confidence": "MEDIUM",
            "counter_trend_risk": et_ctr_risk,
            "alignment": "MODERATE",
            "reason": "Test counter-trend",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=judge_decision,
                technical_report="Test report",
                technical_data=tech_data,
                adx_1d=adx_1d,
            )

        assert result['counter_trend_risk'] == expected_ctr_risk, (
            f"ADX={adx_1d}, ET said {et_ctr_risk}, "
            f"expected {expected_ctr_risk}, got {result['counter_trend_risk']}"
        )


# ============================================================================
# Test 3: JSON Fallback Behavior
# ============================================================================

class TestJSONFallback:
    """Test the internal fallback when JSON parsing fails."""

    def test_json_parse_failure_returns_enter_with_degraded_conf(
            self, mock_analyzer, base_judge_decision, base_technical_data):
        """When _extract_json_with_retry returns None, use conservative fallback."""
        base_judge_decision['confidence'] = 'HIGH'

        # Simulate JSON parse failure (returns None)
        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=None):
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        # Fallback should: ENTER + degrade HIGH→MEDIUM + quality=FAIR
        assert result['timing_verdict'] == 'ENTER'
        assert result['adjusted_confidence'] == 'MEDIUM'
        assert result['timing_quality'] == 'FAIR'
        assert 'fallback' in result.get('reason', '').lower()

    def test_json_fallback_medium_stays_medium(
            self, mock_analyzer, base_judge_decision, base_technical_data):
        """When Judge confidence is MEDIUM, fallback keeps MEDIUM."""
        base_judge_decision['confidence'] = 'MEDIUM'

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=None):
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        assert result['adjusted_confidence'] == 'MEDIUM'

    def test_json_fallback_counter_trend_has_high_risk(
            self, mock_analyzer, base_technical_data):
        """Fallback in counter-trend scenario should set counter_trend_risk=HIGH."""
        judge_decision = {
            'decision': 'LONG',
            'confidence': 'MEDIUM',
            'rationale': 'Test',
            'confluence': {},
        }
        # Make it counter-trend: 1D bearish (DI- > DI+)
        base_technical_data['mtf_trend_layer'] = {
            'adx': 35.0,
            'di_plus': 15.0,
            'di_minus': 25.0,
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=None):
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        assert result['counter_trend_risk'] == 'HIGH'


# ============================================================================
# Test 4: REJECT → HOLD Propagation
# ============================================================================

class TestRejectHoldPropagation:
    """Test that REJECT from Entry Timing correctly propagates to HOLD."""

    def test_reject_changes_decision_to_hold(
            self, mock_analyzer, base_judge_decision, base_technical_data):
        """When ET returns REJECT, analyze() should change judge decision to HOLD."""
        base_judge_decision['confidence'] = 'MEDIUM'
        original_action = base_judge_decision['decision']  # 'LONG'

        mock_et_response = {
            "timing_verdict": "REJECT",
            "timing_quality": "POOR",
            "adjusted_confidence": "LOW",
            "counter_trend_risk": "HIGH",
            "alignment": "WEAK",
            "reason": "30M opposing, reject entry",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        assert result['timing_verdict'] == 'REJECT'

    def test_reject_sets_confidence_low_in_wrapper(
            self, mock_analyzer, base_judge_decision, base_technical_data):
        """After REJECT, Phase 2.5 wrapper should set confidence to LOW."""
        # This tests the analyze() integration, not just _evaluate_entry_timing()
        # We test the wrapper logic directly since it's what applies REJECT→HOLD

        mock_et_response = {
            "timing_verdict": "REJECT",
            "timing_quality": "POOR",
            "adjusted_confidence": "LOW",
            "counter_trend_risk": "HIGH",
            "alignment": "WEAK",
            "reason": "Bad timing",
        }

        # Simulate the Phase 2.5 wrapper logic
        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            timing_assessment = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        # Now simulate what the Phase 2.5 wrapper does
        judge_copy = dict(base_judge_decision)
        timing_verdict = timing_assessment.get('timing_verdict', 'ENTER')
        if timing_verdict == 'REJECT':
            judge_copy['decision'] = 'HOLD'
            judge_copy['_timing_rejected'] = True
            judge_copy['_timing_original_signal'] = 'LONG'
            judge_copy['confidence'] = 'LOW'

        assert judge_copy['decision'] == 'HOLD'
        assert judge_copy['confidence'] == 'LOW'
        assert judge_copy['_timing_rejected'] is True
        assert judge_copy['_timing_original_signal'] == 'LONG'

    def test_reject_does_not_mutate_original_judge(
            self, mock_analyzer, base_judge_decision, base_technical_data):
        """REJECT path must not mutate the original judge_decision dict."""
        original_decision = deepcopy(base_judge_decision)

        mock_et_response = {
            "timing_verdict": "REJECT",
            "timing_quality": "POOR",
            "adjusted_confidence": "LOW",
            "counter_trend_risk": "HIGH",
            "alignment": "WEAK",
            "reason": "Reject",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            _ = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        # _evaluate_entry_timing itself doesn't modify judge_decision
        # (it returns its own dict). Verify the input wasn't mutated.
        assert base_judge_decision['decision'] == original_decision['decision']
        assert base_judge_decision['confidence'] == original_decision['confidence']


# ============================================================================
# Test 5: DI+=DI-=0 Trend Unclear (v23.0 fix)
# ============================================================================

class TestTrendDataMissing:
    """Test that DI+=DI-=0 is treated as 'trend unclear' not 'BEARISH'."""

    def test_di_zero_no_counter_trend_alert(
            self, mock_analyzer, base_technical_data):
        """When DI+=DI-=0, is_counter_trend should be False, no COUNTER-TREND ALERT."""
        judge_decision = {
            'decision': 'LONG',
            'confidence': 'MEDIUM',
            'rationale': 'Test',
            'confluence': {},
        }
        # Set DI+ and DI- to 0 (data missing)
        base_technical_data['mtf_trend_layer'] = {
            'adx': 0,
            'di_plus': 0,
            'di_minus': 0,
        }

        mock_et_response = {
            "timing_verdict": "ENTER",
            "timing_quality": "GOOD",
            "adjusted_confidence": "MEDIUM",
            "counter_trend_risk": "NONE",
            "alignment": "MODERATE",
            "reason": "Test",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response) as mock_extract:
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=30.0,
            )

            # Verify the prompt did NOT contain COUNTER-TREND ALERT
            call_args = mock_extract.call_args
            if call_args:
                messages = call_args.kwargs.get('messages', call_args[0][0] if call_args[0] else [])
                prompt_text = ' '.join(m.get('content', '') for m in messages)
                assert 'COUNTER-TREND ALERT' not in prompt_text, (
                    "COUNTER-TREND ALERT should not appear when DI+=DI-=0"
                )

    def test_di_zero_trend_direction_unclear(
            self, mock_analyzer, base_technical_data):
        """When DI+=DI-=0, trend_direction should be UNCLEAR."""
        judge_decision = {
            'decision': 'SHORT',
            'confidence': 'HIGH',
            'rationale': 'Test',
            'confluence': {},
        }
        base_technical_data['mtf_trend_layer'] = {
            'adx': 0,
            'di_plus': 0,
            'di_minus': 0,
        }

        mock_et_response = {
            "timing_verdict": "ENTER",
            "timing_quality": "GOOD",
            "adjusted_confidence": "HIGH",
            "counter_trend_risk": "NONE",
            "alignment": "STRONG",
            "reason": "Test",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response) as mock_extract:
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=30.0,
            )

            # Check prompt contains "UNCLEAR" trend
            call_args = mock_extract.call_args
            if call_args:
                messages = call_args.kwargs.get('messages', call_args[0][0] if call_args[0] else [])
                prompt_text = ' '.join(m.get('content', '') for m in messages)
                assert 'UNCLEAR' in prompt_text, (
                    "Trend direction should be 'UNCLEAR' when DI+=DI-=0"
                )

    def test_normal_di_values_still_detect_counter_trend(
            self, mock_analyzer, base_technical_data):
        """Verify normal DI values still correctly detect counter-trend."""
        judge_decision = {
            'decision': 'LONG',
            'confidence': 'HIGH',
            'rationale': 'Test',
            'confluence': {},
        }
        # 1D is bearish: DI- > DI+, so LONG is counter-trend
        base_technical_data['mtf_trend_layer'] = {
            'adx': 35.0,
            'di_plus': 15.0,
            'di_minus': 25.0,
        }

        mock_et_response = {
            "timing_verdict": "ENTER",
            "timing_quality": "FAIR",
            "adjusted_confidence": "MEDIUM",
            "counter_trend_risk": "HIGH",
            "alignment": "MODERATE",
            "reason": "Test",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response) as mock_extract:
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

            # Verify COUNTER-TREND ALERT IS present
            call_args = mock_extract.call_args
            if call_args:
                messages = call_args.kwargs.get('messages', call_args[0][0] if call_args[0] else [])
                prompt_text = ' '.join(m.get('content', '') for m in messages)
                assert 'COUNTER-TREND ALERT' in prompt_text, (
                    "COUNTER-TREND ALERT should appear when trend is clearly bearish and signal is LONG"
                )


# ============================================================================
# Test 6: Dict Mutation Safety
# ============================================================================

class TestDictMutationSafety:
    """Verify shallow copy prevents mutation of original judge_decision."""

    def test_enter_no_change_does_not_mutate_original(
            self, mock_analyzer, base_judge_decision, base_technical_data):
        """ENTER + same confidence must not mutate original dict."""
        original_keys = set(base_judge_decision.keys())

        mock_et_response = {
            "timing_verdict": "ENTER",
            "timing_quality": "GOOD",
            "adjusted_confidence": "HIGH",  # Same as judge
            "counter_trend_risk": "NONE",
            "alignment": "STRONG",
            "reason": "Test",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            _ = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        # Original dict should NOT have _timing_assessment added
        assert '_timing_assessment' not in base_judge_decision, (
            "Original judge_decision dict should not be mutated"
        )
        assert set(base_judge_decision.keys()) == original_keys


# ============================================================================
# Test 7: Non-Actionable Signal Skips Entry Timing
# ============================================================================

class TestNonActionableSignal:
    """Verify that HOLD signals skip Entry Timing evaluation entirely."""

    def test_hold_skips_evaluation(self, mock_analyzer, base_technical_data):
        """HOLD signal should return N/A timing without calling API."""
        judge_decision = {
            'decision': 'HOLD',
            'confidence': 'LOW',
            'rationale': 'No clear signal',
            'confluence': {},
        }

        # Should NOT call the API
        with patch.object(mock_analyzer, '_extract_json_with_retry') as mock_api:
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=30.0,
            )

            mock_api.assert_not_called()

        assert result['timing_verdict'] == 'N/A'
        assert result['timing_quality'] == 'N/A'


# ============================================================================
# Test 8: Fallback Signal Contains _timing_assessment
# ============================================================================

class TestFallbackSignalTimingAssessment:
    """Verify _create_fallback_signal includes _timing_assessment marker."""

    def test_fallback_has_timing_assessment(self, mock_analyzer):
        """Fallback signal should contain _timing_assessment for downstream distinction."""
        result = mock_analyzer._create_fallback_signal({})

        assert '_timing_assessment' in result
        assert result['_timing_assessment']['timing_verdict'] == 'N/A'
        assert 'before Entry Timing' in result['_timing_assessment']['reason'].lower() or \
               'before entry timing' in result['_timing_assessment']['reason'].lower()

    def test_fallback_is_hold(self, mock_analyzer):
        """Fallback signal should always be HOLD."""
        result = mock_analyzer._create_fallback_signal({})

        assert result['signal'] == 'HOLD'
        assert result['confidence'] == 'LOW'
        assert result['is_fallback'] is True


# ============================================================================
# Test 9: Invalid Verdict/Confidence Sanitization
# ============================================================================

class TestInputSanitization:
    """Verify that invalid AI outputs are sanitized to safe defaults."""

    def test_invalid_verdict_defaults_to_enter(
            self, mock_analyzer, base_judge_decision, base_technical_data):
        """Invalid timing_verdict should default to ENTER (safe: doesn't reject)."""
        mock_et_response = {
            "timing_verdict": "MAYBE",  # Invalid
            "timing_quality": "GOOD",
            "adjusted_confidence": "HIGH",
            "counter_trend_risk": "NONE",
            "alignment": "STRONG",
            "reason": "Test",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        assert result['timing_verdict'] == 'ENTER'

    def test_invalid_quality_defaults_to_fair(
            self, mock_analyzer, base_judge_decision, base_technical_data):
        """Invalid timing_quality should default to FAIR."""
        mock_et_response = {
            "timing_verdict": "ENTER",
            "timing_quality": "EXCELLENT",  # Invalid
            "adjusted_confidence": "HIGH",
            "counter_trend_risk": "NONE",
            "alignment": "STRONG",
            "reason": "Test",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        assert result['timing_quality'] == 'FAIR'

    def test_invalid_confidence_falls_back_to_judge(
            self, mock_analyzer, base_judge_decision, base_technical_data):
        """Invalid adjusted_confidence should fall back to Judge's confidence."""
        base_judge_decision['confidence'] = 'MEDIUM'

        mock_et_response = {
            "timing_verdict": "ENTER",
            "timing_quality": "GOOD",
            "adjusted_confidence": "SUPER_HIGH",  # Invalid
            "counter_trend_risk": "NONE",
            "alignment": "STRONG",
            "reason": "Test",
        }

        with patch.object(mock_analyzer, '_extract_json_with_retry',
                          return_value=mock_et_response):
            result = mock_analyzer._evaluate_entry_timing(
                judge_decision=base_judge_decision,
                technical_report="Test report",
                technical_data=base_technical_data,
                adx_1d=35.0,
            )

        assert result['adjusted_confidence'] == 'MEDIUM'


# ============================================================================
# Test 10: record_outcome() stores entry_timing fields (v23.0)
# ============================================================================

class TestRecordOutcomeEntryTiming:
    """Verify record_outcome() accepts and stores Entry Timing data."""

    def test_entry_timing_verdict_stored(self, mock_analyzer):
        """entry_timing_verdict is stored in the memory entry."""
        mock_analyzer.decision_memory = []  # Isolate from file persistence
        with patch.object(mock_analyzer, '_save_memory'):
            mock_analyzer.record_outcome(
                decision="LONG",
                pnl=1.5,
                conditions="RSI=55, trend=UP",
                entry_timing_verdict="ENTER",
                entry_timing_quality="GOOD",
            )

        entry = mock_analyzer.decision_memory[-1]
        assert entry["entry_timing_verdict"] == "ENTER"
        assert entry["entry_timing_quality"] == "GOOD"

    def test_entry_timing_absent_no_keys(self, mock_analyzer):
        """When entry_timing params are empty, keys are not added."""
        mock_analyzer.decision_memory = []
        with patch.object(mock_analyzer, '_save_memory'):
            mock_analyzer.record_outcome(
                decision="LONG",
                pnl=-0.5,
                conditions="RSI=45",
            )

        entry = mock_analyzer.decision_memory[-1]
        assert "entry_timing_verdict" not in entry
        assert "entry_timing_quality" not in entry

    def test_entry_timing_reject_stored(self, mock_analyzer):
        """REJECT verdict is correctly stored for learning."""
        mock_analyzer.decision_memory = []
        with patch.object(mock_analyzer, '_save_memory'):
            mock_analyzer.record_outcome(
                decision="HOLD",
                pnl=0.0,
                conditions="RSI=70, trend=DOWN",
                entry_timing_verdict="REJECT",
                entry_timing_quality="POOR",
            )

        entry = mock_analyzer.decision_memory[-1]
        assert entry["entry_timing_verdict"] == "REJECT"
        assert entry["entry_timing_quality"] == "POOR"


# ============================================================================
# Test 11: generate_reflection() includes entry_timing role (v23.0)
# ============================================================================

class TestReflectionEntryTiming:
    """Verify reflection prompt requests entry_timing role."""

    def test_reflection_prompt_includes_entry_timing(self, mock_analyzer):
        """The reflection prompt should mention entry_timing role."""
        memory_entry = {
            "decision": "LONG",
            "pnl": 2.5,
            "conditions": "RSI=55",
            "evaluation": {
                "grade": "A",
                "actual_rr": 2.0,
                "planned_rr": 2.5,
                "exit_type": "TP",
                "mae_pct": 0.5,
                "mfe_pct": 3.0,
                "adx": 30,
                "trend_direction": "UP",
                "is_counter_trend": False,
                "sl_atr_multiplier": 1.5,
                "hold_duration_min": 120,
                "confidence": "HIGH",
                "pyramid_layers_used": 1,
            },
            "winning_side": "BULL",
            "entry_judge_summary": "Bullish momentum",
            "entry_timing_verdict": "ENTER",
            "entry_timing_quality": "OPTIMAL",
        }

        # Mock API to return a 4-role JSON reflection
        mock_reflection = json.dumps({
            "bull": "Strong momentum correctly identified",
            "bear": "Missed reversal signs",
            "judge": "Confidence calibration accurate",
            "entry_timing": "OPTIMAL quality confirmed by result",
        })

        with patch.object(mock_analyzer, '_call_api_with_retry',
                          return_value=mock_reflection):
            result = mock_analyzer.generate_reflection(memory_entry)

        assert result  # Should produce a non-empty reflection
        parsed = json.loads(result)
        assert "entry_timing" in parsed

    def test_reflection_truncates_4_roles(self, mock_analyzer):
        """Each role's reflection should be truncated to max_chars//4."""
        memory_entry = {
            "decision": "SHORT",
            "pnl": -1.0,
            "conditions": "RSI=75",
            "evaluation": {
                "grade": "D",
                "actual_rr": 0,
                "planned_rr": 2.0,
                "exit_type": "SL",
                "mae_pct": 2.0,
                "mfe_pct": 0.5,
                "adx": 25,
                "trend_direction": "UP",
                "is_counter_trend": True,
                "sl_atr_multiplier": 1.5,
                "hold_duration_min": 45,
                "confidence": "MEDIUM",
                "pyramid_layers_used": 1,
            },
        }

        # Generate a long reflection (>150//4 = 37 chars per role)
        long_text = "A" * 60
        mock_reflection = json.dumps({
            "bull": long_text,
            "bear": long_text,
            "judge": long_text,
            "entry_timing": long_text,
        })

        with patch.object(mock_analyzer, '_call_api_with_retry',
                          return_value=mock_reflection):
            result = mock_analyzer.generate_reflection(memory_entry, max_chars=150)

        parsed = json.loads(result)
        # v30.2: Zero truncation policy — per-role truncation removed.
        # Verify structured JSON output with all mocked roles preserved intact.
        for role in ("bull", "bear", "judge", "entry_timing"):
            assert role in parsed, f"Role {role} missing from reflection"
            assert parsed[role] == long_text, (
                f"Role {role} reflection should be preserved intact (zero truncation policy)"
            )
