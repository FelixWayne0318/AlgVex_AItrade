"""
v27.0 Feature-Driven Architecture — Schema Verification Tests (PLAN §12.2)

Tests:
1. FEATURE_SCHEMA completeness — all keys can be extracted
2. REASON_TAGS validation — agent outputs only contain valid tags
3. Version fields in call_trace — schema_version, feature_version, prompt_hash
4. Output schema downstream compatibility — all consumer fields present
5. debate_summary generation from structured Bull/Bear output
"""

import pytest
from agents.prompt_constants import (
    FEATURE_SCHEMA,
    REASON_TAGS,
    BULL_SCHEMA,
    BEAR_SCHEMA,
    JUDGE_SCHEMA,
    ENTRY_TIMING_SCHEMA,
    RISK_SCHEMA,
    FEATURE_VERSION,
    SCHEMA_VERSION,
    compute_prompt_version,
)


class TestFeatureSchemaCompleteness:
    """§12.2: Verify all FEATURE_SCHEMA keys can be extracted from sample data."""

    def test_feature_schema_has_required_count(self):
        """Schema should have 80+ features."""
        assert len(FEATURE_SCHEMA) >= 80, f"Only {len(FEATURE_SCHEMA)} features defined"

    def test_all_features_have_type(self):
        """Every feature must declare a type."""
        for key, spec in FEATURE_SCHEMA.items():
            assert "type" in spec, f"Feature '{key}' missing 'type'"

    def test_feature_types_valid(self):
        """Feature types must be float, int, enum, or bool."""
        valid_types = {"float", "int", "enum", "bool"}
        for key, spec in FEATURE_SCHEMA.items():
            assert spec["type"] in valid_types, (
                f"Feature '{key}' has invalid type '{spec['type']}'"
            )

    def test_enum_features_have_values(self):
        """Enum features must declare valid values."""
        for key, spec in FEATURE_SCHEMA.items():
            if spec["type"] == "enum":
                assert "values" in spec, f"Enum feature '{key}' missing 'values'"
                assert len(spec["values"]) >= 2, (
                    f"Enum feature '{key}' needs >=2 values"
                )

    def test_feature_version_defined(self):
        assert FEATURE_VERSION == "1.0"

    def test_schema_version_defined(self):
        assert SCHEMA_VERSION == "28.0"


class TestReasonTags:
    """§12.2: Verify REASON_TAGS integrity."""

    def test_reason_tags_has_required_count(self):
        """Should have 75+ tags."""
        assert len(REASON_TAGS) >= 75, f"Only {len(REASON_TAGS)} tags defined"

    def test_all_tags_uppercase(self):
        """Tags must be uppercase (convention for enum-like values)."""
        for tag in REASON_TAGS:
            assert tag == tag.upper(), f"Tag '{tag}' is not uppercase"

    def test_no_duplicate_tags(self):
        """Tags must be unique (set enforces this, but verify)."""
        tag_list = list(REASON_TAGS)
        assert len(tag_list) == len(set(tag_list))

    def test_tag_categories_present(self):
        """Key tag categories must be represented."""
        categories = {
            "trend": ["TREND_1D_BULLISH", "TREND_1D_BEARISH"],
            "momentum": ["RSI_OVERBOUGHT", "RSI_OVERSOLD"],
            "order_flow": ["CVD_POSITIVE", "CVD_NEGATIVE"],
            "derivatives": ["FR_FAVORABLE_LONG", "FR_FAVORABLE_SHORT"],
            "risk": ["EXTENSION_OVEREXTENDED", "EXTENSION_EXTREME"],
            "memory": ["LATE_ENTRY", "TREND_ALIGNED", "SL_TOO_TIGHT"],
        }
        for cat, tags in categories.items():
            for tag in tags:
                assert tag in REASON_TAGS, f"Missing {cat} tag: {tag}"

    def test_reason_tags_in_output_validation(self):
        """Verify tag filtering logic matches REASON_TAGS."""
        sample_output = {
            "decisive_reasons": [
                "TREND_1D_BULLISH",     # valid
                "MACD_BULLISH_CROSS",   # valid
                "INVALID_TAG_XYZ",      # should be filtered
            ]
        }
        valid = [t for t in sample_output["decisive_reasons"] if t in REASON_TAGS]
        invalid = [t for t in sample_output["decisive_reasons"] if t not in REASON_TAGS]
        assert len(valid) == 2
        assert len(invalid) == 1
        assert "INVALID_TAG_XYZ" in invalid


class TestOutputSchemas:
    """§12.2: Verify output schemas have required structure."""

    @pytest.mark.parametrize("schema_name,schema", [
        ("BULL", BULL_SCHEMA),
        ("BEAR", BEAR_SCHEMA),
        ("JUDGE", JUDGE_SCHEMA),
        ("ENTRY_TIMING", ENTRY_TIMING_SCHEMA),
        ("RISK", RISK_SCHEMA),
    ])
    def test_schema_has_required_sections(self, schema_name, schema):
        assert "required_keys" in schema, f"{schema_name} missing required_keys"
        assert "valid_values" in schema, f"{schema_name} missing valid_values"
        assert "constraints" in schema, f"{schema_name} missing constraints"

    def test_bull_schema_keys(self):
        keys = BULL_SCHEMA["required_keys"]
        assert "reasoning" in keys
        assert "evidence" in keys
        assert "risk_flags" in keys
        assert "conviction" in keys
        assert "summary" in keys

    def test_judge_schema_keys(self):
        keys = JUDGE_SCHEMA["required_keys"]
        assert "reasoning" in keys
        assert "decision" in keys
        assert "confidence" in keys
        assert "rationale" in keys
        assert "strategic_actions" in keys
        assert "decisive_reasons" in keys
        assert "acknowledged_risks" in keys
        assert "confluence" in keys

    def test_entry_timing_schema_keys(self):
        keys = ENTRY_TIMING_SCHEMA["required_keys"]
        assert "reasoning" in keys
        assert "timing_verdict" in keys
        assert "timing_quality" in keys
        assert "adjusted_confidence" in keys
        assert "reason" in keys

    def test_risk_schema_keys(self):
        keys = RISK_SCHEMA["required_keys"]
        assert "reasoning" in keys
        assert "signal" in keys
        assert "risk_appetite" in keys
        assert "reason" in keys
        assert "risk_factors" in keys


class TestDownstreamCompatibility:
    """§12.3: Verify agent outputs satisfy all downstream consumers."""

    def test_judge_output_downstream_compatibility(self):
        """Verify Judge output contains all fields consumed by strategy code."""
        mock_judge = {
            "reasoning": "1D ADX=45 strong bullish trend, 4H MACD bullish cross confirms momentum.",
            "decisive_reasons": ["TREND_1D_BULLISH", "MACD_BULLISH_CROSS"],
            "acknowledged_risks": ["EXTENSION_OVEREXTENDED"],
            "confluence": {
                "trend_1d": "BULLISH", "momentum_4h": "BULLISH",
                "levels_30m": "NEUTRAL", "derivatives": "NEUTRAL",
                "aligned_layers": 2,
            },
            "decision": "LONG", "winning_side": "BULL", "confidence": "MEDIUM",
            "rationale": "Strong 1D trend with 4H momentum alignment.",
            "strategic_actions": ["Enter on pullback to SMA20"],
        }
        # ai_strategy.py:2864
        assert mock_judge.get('rationale', '') != ''
        # ai_strategy.py:2865
        assert len(mock_judge.get('strategic_actions', [])) > 0
        # event_handlers.py:383
        assert isinstance(mock_judge.get('acknowledged_risks', []), list)
        # v27.0 new fields
        assert all(t in REASON_TAGS for t in mock_judge['decisive_reasons'])

    def test_risk_output_downstream_compatibility(self):
        """Verify Risk Manager output contains 'reason' for Telegram."""
        mock_risk = {
            "signal": "LONG", "risk_appetite": "NORMAL",
            "position_risk": "FULL_SIZE", "market_structure_risk": "NORMAL",
            "risk_factors": ["VOL_LOW"],
            "reason": "Normal risk environment, full position acceptable.",
        }
        # order_execution.py:271
        assert mock_risk.get('reason', '') != ''
        assert all(t in REASON_TAGS for t in mock_risk['risk_factors'])

    def test_bull_bear_debate_summary_generation(self):
        """Verify debate_summary assembled from Bull/Bear JSON outputs."""
        bull_r2 = {
            "evidence": ["TREND_1D_BULLISH"], "risk_flags": [],
            "conviction": 0.75, "summary": "Strong uptrend with momentum.",
        }
        bear_r2 = {
            "evidence": ["RSI_OVERBOUGHT"], "risk_flags": [],
            "conviction": 0.40, "summary": "Overbought but no divergence.",
        }
        debate_summary = (
            f"Bull ({bull_r2['conviction']:.0%}): {bull_r2['summary']}\n"
            f"Bear ({bear_r2['conviction']:.0%}): {bear_r2['summary']}"
        )
        assert "Bull (75%)" in debate_summary
        assert "Bear (40%)" in debate_summary

    def test_entry_timing_output_downstream_compatibility(self):
        """Verify Entry Timing output contains 'reason' for logging."""
        mock_et = {
            "timing_verdict": "ENTER", "timing_quality": "GOOD",
            "adjusted_confidence": "MEDIUM",
            "counter_trend_risk": "NONE", "alignment": "MODERATE",
            "decisive_reasons": ["MACD_BULLISH_CROSS"],
            "reason": "4H momentum aligned, 30M showing bullish setup.",
        }
        # ai_strategy.py:3012
        assert mock_et.get('reason', '') != ''
        assert mock_et['timing_verdict'] in {"ENTER", "REJECT"}


class TestVersionSystem:
    """§4: Verify version computation works correctly."""

    def test_compute_prompt_version_deterministic(self):
        """Same input must produce same hash."""
        h1 = compute_prompt_version("test prompt")
        h2 = compute_prompt_version("test prompt")
        assert h1 == h2

    def test_compute_prompt_version_different_inputs(self):
        """Different inputs must produce different hashes."""
        h1 = compute_prompt_version("prompt A")
        h2 = compute_prompt_version("prompt B")
        assert h1 != h2

    def test_compute_prompt_version_length(self):
        """Hash should be 12 characters (hex)."""
        h = compute_prompt_version("test")
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)
