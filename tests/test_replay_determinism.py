"""
F5: Replay Determinism End-to-End Test

Verifies that analyze_from_features() produces identical results
when given identical inputs (features, memory, debate_r1) with
temperature=0.0 and seed=42.

Tests:
1. Full deterministic replay with saved R1 (no API calls for R1)
2. Schema validation on replay path (unknown keys stripped, enums coerced)
3. Two identical runs produce identical results
4. Entry Timing REJECT correctly downgrades to HOLD
5. Violation counter tracks corrections
"""

import json
import logging
from copy import deepcopy
from unittest.mock import patch, MagicMock

import pytest

from agents.prompt_constants import (
    FEATURE_SCHEMA,
    REASON_TAGS,
    FEATURE_VERSION,
)
from agents.multi_agent_analyzer import MultiAgentAnalyzer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build_synthetic_features() -> dict:
    """Build a minimal but complete feature dict matching FEATURE_SCHEMA."""
    features = {}
    for key, spec in FEATURE_SCHEMA.items():
        t = spec["type"]
        if t == "float":
            features[key] = 50.0
        elif t == "int":
            features[key] = 5
        elif t == "enum":
            features[key] = spec["values"][0]
        elif t == "bool":
            features[key] = False
    # Override key features for a realistic scenario
    features["price"] = 100000.0
    features["rsi_30m"] = 55.0
    features["adx_1d"] = 25.0  # Non-strong-trend
    features["market_regime"] = "RANGING"
    features["_feature_version"] = FEATURE_VERSION
    features["_snapshot_ts"] = "2025-01-01T00:00:00Z"
    return features


MOCK_BULL_R1 = {
    "evidence": ["TREND_1D_BULLISH", "MACD_BULLISH_CROSS"],
    "risk_flags": ["RSI_OVERBOUGHT"],
    "conviction": 0.65,
    "summary": "Moderate bullish case with overbought risk.",
}

MOCK_BEAR_R1 = {
    "evidence": ["RSI_OVERBOUGHT", "EXTENSION_OVEREXTENDED"],
    "risk_flags": [],
    "conviction": 0.40,
    "summary": "Overbought conditions may limit upside.",
}

# R2 outputs (returned by mocked API for cross-examination round)
MOCK_BULL_R2 = {
    "evidence": ["TREND_1D_BULLISH", "MACD_BULLISH_CROSS", "CVD_POSITIVE"],
    "risk_flags": ["RSI_OVERBOUGHT"],
    "conviction": 0.70,
    "summary": "Trend intact despite overbought RSI.",
}

MOCK_BEAR_R2 = {
    "evidence": ["RSI_OVERBOUGHT"],
    "risk_flags": [],
    "conviction": 0.35,
    "summary": "Risk is limited; bears lack conviction.",
}

MOCK_JUDGE = {
    "decision": "LONG",
    "winning_side": "BULL",
    "confidence": "MEDIUM",
    "rationale": "Bullish trend with moderate conviction.",
    "strategic_actions": ["Enter on next pullback"],
    "acknowledged_risks": ["RSI_OVERBOUGHT"],
    "decisive_reasons": ["TREND_1D_BULLISH", "MACD_BULLISH_CROSS"],
    "confluence": {
        "trend_1d": "BULLISH",
        "momentum_4h": "BULLISH",
        "levels_30m": "NEUTRAL",
        "derivatives": "NEUTRAL",
        "aligned_layers": 2,
    },
}

MOCK_ENTRY_TIMING = {
    "timing_verdict": "ENTER",
    "timing_quality": "GOOD",
    "adjusted_confidence": "MEDIUM",
    "counter_trend_risk": "NONE",
    "alignment": "MODERATE",
    "decisive_reasons": ["MACD_BULLISH_CROSS"],
    "reason": "4H momentum aligned, 30M setup acceptable.",
}

MOCK_RISK = {
    "signal": "LONG",
    "risk_appetite": "NORMAL",
    "position_risk": "FULL_SIZE",
    "market_structure_risk": "NORMAL",
    "risk_factors": ["VOL_LOW"],
    "reason": "Normal risk environment.",
}

MOCK_MEMORY = [
    {
        "outcome": "win",
        "pnl_pct": 2.5,
        "grade": "A",
        "lesson": "Trend following worked well.",
        "signal": "LONG",
        "confidence": "MEDIUM",
    }
]


@pytest.fixture
def analyzer():
    """Create MultiAgentAnalyzer with dummy API key (no real calls)."""
    return MultiAgentAnalyzer(
        api_key="test-key-not-real",
        model="deepseek-chat",
        temperature=0.0,
    )


def _mock_api_side_effect(*args, **kwargs):
    """Return appropriate mock response based on trace_label."""
    label = kwargs.get("trace_label", "")
    if "Bull R2" in label:
        return deepcopy(MOCK_BULL_R2)
    elif "Bear R2" in label:
        return deepcopy(MOCK_BEAR_R2)
    elif "Judge" in label:
        return deepcopy(MOCK_JUDGE)
    elif "Entry Timing" in label:
        return deepcopy(MOCK_ENTRY_TIMING)
    elif "Risk Manager" in label:
        return deepcopy(MOCK_RISK)
    elif "Bull R1" in label:
        return deepcopy(MOCK_BULL_R1)
    elif "Bear R1" in label:
        return deepcopy(MOCK_BEAR_R1)
    return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReplayDeterminism:
    """E2E: analyze_from_features() replay produces deterministic results."""

    def test_full_replay_with_saved_r1(self, analyzer):
        """Saved R1 path skips R1 API calls; result is deterministic."""
        features = _build_synthetic_features()
        debate_r1 = {"bull_r1": deepcopy(MOCK_BULL_R1), "bear_r1": deepcopy(MOCK_BEAR_R1)}

        with patch.object(analyzer, "_extract_json_with_retry", side_effect=_mock_api_side_effect):
            result = analyzer.analyze_from_features(
                feature_dict=features,
                memory_features=MOCK_MEMORY,
                debate_r1=debate_r1,
                temperature=0.0,
                seed=42,
            )

        assert result["signal"] == "LONG"
        assert result["confidence"] == "MEDIUM"
        assert result["replay_metadata"]["replay"] is True
        assert result["replay_metadata"]["temperature"] == 0.0
        assert result["replay_metadata"]["seed"] == 42
        assert result["replay_metadata"]["prompt_version"] == "current"

    def test_two_runs_produce_identical_results(self, analyzer):
        """Two replays with identical inputs must produce identical outputs."""
        features = _build_synthetic_features()
        debate_r1 = {"bull_r1": deepcopy(MOCK_BULL_R1), "bear_r1": deepcopy(MOCK_BEAR_R1)}

        results = []
        for _ in range(2):
            with patch.object(analyzer, "_extract_json_with_retry", side_effect=_mock_api_side_effect):
                r = analyzer.analyze_from_features(
                    feature_dict=deepcopy(features),
                    memory_features=deepcopy(MOCK_MEMORY),
                    debate_r1=deepcopy(debate_r1),
                    temperature=0.0,
                    seed=42,
                )
            # Remove timestamp (wall-clock dependent)
            r.pop("timestamp", None)
            results.append(r)

        assert results[0]["signal"] == results[1]["signal"]
        assert results[0]["confidence"] == results[1]["confidence"]
        assert results[0]["debate_summary"] == results[1]["debate_summary"]
        assert results[0]["replay_metadata"] == results[1]["replay_metadata"]
        judge0 = results[0]["judge_decision"]
        judge1 = results[1]["judge_decision"]
        assert judge0["decision"] == judge1["decision"]
        assert judge0["confidence"] == judge1["confidence"]
        assert judge0["decisive_reasons"] == judge1["decisive_reasons"]

    def test_entry_timing_reject_downgrades_to_hold(self, analyzer):
        """When Entry Timing returns REJECT, final signal becomes HOLD."""
        features = _build_synthetic_features()
        debate_r1 = {"bull_r1": deepcopy(MOCK_BULL_R1), "bear_r1": deepcopy(MOCK_BEAR_R1)}

        reject_et = deepcopy(MOCK_ENTRY_TIMING)
        reject_et["timing_verdict"] = "REJECT"
        reject_et["adjusted_confidence"] = "LOW"

        def _reject_side_effect(*args, **kwargs):
            label = kwargs.get("trace_label", "")
            if "Entry Timing" in label:
                return deepcopy(reject_et)
            return _mock_api_side_effect(*args, **kwargs)

        with patch.object(analyzer, "_extract_json_with_retry", side_effect=_reject_side_effect):
            result = analyzer.analyze_from_features(
                feature_dict=features,
                memory_features=MOCK_MEMORY,
                debate_r1=debate_r1,
                temperature=0.0,
                seed=42,
            )

        # Judge said LONG, but Entry Timing rejected → HOLD
        assert result.get("_timing_rejected") is True
        assert result.get("_timing_original_signal") == "LONG"
        # Risk Manager receives HOLD, may output HOLD
        assert result["judge_decision"]["decision"] == "HOLD"

    def test_schema_validation_strips_unknown_keys(self, analyzer):
        """Unknown keys in agent output are stripped (F1: additionalProperties=false)."""
        features = _build_synthetic_features()
        debate_r1 = {"bull_r1": deepcopy(MOCK_BULL_R1), "bear_r1": deepcopy(MOCK_BEAR_R1)}

        # Inject unknown keys into Judge output
        judge_with_extras = deepcopy(MOCK_JUDGE)
        judge_with_extras["extra_unknown_key"] = "should be stripped"
        judge_with_extras["another_extra"] = 999

        def _extras_side_effect(*args, **kwargs):
            label = kwargs.get("trace_label", "")
            if "Judge" in label:
                return deepcopy(judge_with_extras)
            return _mock_api_side_effect(*args, **kwargs)

        with patch.object(analyzer, "_extract_json_with_retry", side_effect=_extras_side_effect):
            result = analyzer.analyze_from_features(
                feature_dict=features,
                memory_features=MOCK_MEMORY,
                debate_r1=debate_r1,
                temperature=0.0,
                seed=42,
            )

        # Judge output should not contain extra keys
        judge = result["judge_decision"]
        assert "extra_unknown_key" not in judge
        assert "another_extra" not in judge
        # Valid keys still present
        assert "decision" in judge
        assert "confidence" in judge

    def test_violation_counter_tracks_corrections(self, analyzer):
        """F3: _schema_violations counter is populated after corrections."""
        features = _build_synthetic_features()

        # Bull R1 with invalid tag → will be filtered, creating a violation
        bad_bull = deepcopy(MOCK_BULL_R1)
        bad_bull["evidence"].append("COMPLETELY_INVALID_TAG")
        bad_bull["unknown_field"] = "strip me"  # F1 violation too
        debate_r1 = {"bull_r1": bad_bull, "bear_r1": deepcopy(MOCK_BEAR_R1)}

        with patch.object(analyzer, "_extract_json_with_retry", side_effect=_mock_api_side_effect):
            result = analyzer.analyze_from_features(
                feature_dict=features,
                memory_features=MOCK_MEMORY,
                debate_r1=debate_r1,
                temperature=0.0,
                seed=42,
            )

        # Violations should have been tracked for Bull R1
        assert hasattr(analyzer, "_schema_violations")
        assert "Bull R1" in analyzer._schema_violations
        assert analyzer._schema_violations["Bull R1"] >= 1

    def test_replay_without_saved_r1_makes_api_calls(self, analyzer):
        """Without debate_r1, R1 phase makes API calls (4+1+1+1 = 7 total)."""
        features = _build_synthetic_features()

        with patch.object(analyzer, "_extract_json_with_retry", side_effect=_mock_api_side_effect) as mock_api:
            result = analyzer.analyze_from_features(
                feature_dict=features,
                memory_features=MOCK_MEMORY,
                debate_r1=None,  # No saved R1
                temperature=0.0,
                seed=42,
            )

        # Should have called API for: Bull R1, Bear R1, Bull R2, Bear R2, Judge, Entry Timing, Risk
        assert mock_api.call_count == 7
        labels = [call.kwargs.get("trace_label", "") for call in mock_api.call_args_list]
        assert any("Bull R1" in l for l in labels)
        assert any("Bear R1" in l for l in labels)

    def test_replay_with_saved_r1_skips_r1_calls(self, analyzer):
        """With debate_r1, R1 is skipped (5 API calls: R2×2 + Judge + ET + Risk)."""
        features = _build_synthetic_features()
        debate_r1 = {"bull_r1": deepcopy(MOCK_BULL_R1), "bear_r1": deepcopy(MOCK_BEAR_R1)}

        with patch.object(analyzer, "_extract_json_with_retry", side_effect=_mock_api_side_effect) as mock_api:
            result = analyzer.analyze_from_features(
                feature_dict=features,
                memory_features=MOCK_MEMORY,
                debate_r1=debate_r1,
                temperature=0.0,
                seed=42,
            )

        # Should have called API for: Bull R2, Bear R2, Judge, Entry Timing, Risk = 5
        assert mock_api.call_count == 5
        labels = [call.kwargs.get("trace_label", "") for call in mock_api.call_args_list]
        assert not any("Bull R1" in l for l in labels)
        assert not any("Bear R1" in l for l in labels)

    def test_hold_signal_skips_entry_timing(self, analyzer):
        """When Judge returns HOLD, Entry Timing is not called."""
        features = _build_synthetic_features()
        debate_r1 = {"bull_r1": deepcopy(MOCK_BULL_R1), "bear_r1": deepcopy(MOCK_BEAR_R1)}

        hold_judge = deepcopy(MOCK_JUDGE)
        hold_judge["decision"] = "HOLD"
        hold_judge["confidence"] = "LOW"

        def _hold_side_effect(*args, **kwargs):
            label = kwargs.get("trace_label", "")
            if "Judge" in label:
                return deepcopy(hold_judge)
            return _mock_api_side_effect(*args, **kwargs)

        with patch.object(analyzer, "_extract_json_with_retry", side_effect=_hold_side_effect) as mock_api:
            result = analyzer.analyze_from_features(
                feature_dict=features,
                memory_features=MOCK_MEMORY,
                debate_r1=debate_r1,
                temperature=0.0,
                seed=42,
            )

        # Entry Timing should NOT be called for HOLD
        labels = [call.kwargs.get("trace_label", "") for call in mock_api.call_args_list]
        assert not any("Entry Timing" in l for l in labels)
        # Only R2×2 + Judge + Risk = 4 calls
        assert mock_api.call_count == 4

    def test_confidence_only_decreases(self, analyzer):
        """Entry Timing can lower confidence but never raise it."""
        features = _build_synthetic_features()
        debate_r1 = {"bull_r1": deepcopy(MOCK_BULL_R1), "bear_r1": deepcopy(MOCK_BEAR_R1)}

        # Judge says LOW, ET says HIGH → should stay LOW
        low_judge = deepcopy(MOCK_JUDGE)
        low_judge["confidence"] = "LOW"
        low_judge["confluence"]["aligned_layers"] = 1  # Forces LOW via alignment cap

        high_et = deepcopy(MOCK_ENTRY_TIMING)
        high_et["adjusted_confidence"] = "HIGH"

        def _conf_side_effect(*args, **kwargs):
            label = kwargs.get("trace_label", "")
            if "Judge" in label:
                return deepcopy(low_judge)
            if "Entry Timing" in label:
                return deepcopy(high_et)
            return _mock_api_side_effect(*args, **kwargs)

        with patch.object(analyzer, "_extract_json_with_retry", side_effect=_conf_side_effect):
            result = analyzer.analyze_from_features(
                feature_dict=features,
                memory_features=MOCK_MEMORY,
                debate_r1=debate_r1,
                temperature=0.0,
                seed=42,
            )

        # Confidence must not exceed Judge's level
        assert result["confidence"] == "LOW"

    def test_replay_metadata_populated(self, analyzer):
        """replay_metadata contains all expected fields."""
        features = _build_synthetic_features()
        debate_r1 = {"bull_r1": deepcopy(MOCK_BULL_R1), "bear_r1": deepcopy(MOCK_BEAR_R1)}

        with patch.object(analyzer, "_extract_json_with_retry", side_effect=_mock_api_side_effect):
            result = analyzer.analyze_from_features(
                feature_dict=features,
                memory_features=MOCK_MEMORY,
                debate_r1=debate_r1,
                temperature=0.0,
                seed=42,
            )

        meta = result["replay_metadata"]
        assert meta["replay"] is True
        assert meta["temperature"] == 0.0
        assert meta["seed"] == 42
        assert meta["prompt_version"] == "current"
        assert meta["source_snapshot_ts"] == "2025-01-01T00:00:00Z"
        assert meta["feature_version"] == FEATURE_VERSION
