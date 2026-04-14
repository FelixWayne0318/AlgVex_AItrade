"""
Multi-Agent Trading Analyzer

Borrowed from TradingAgents (UCLA+MIT) and adapted for cryptocurrency trading.
Original: https://github.com/TaurusQ/tradingagents

This module implements a multi-agent debate system where Bull and Bear analysts
argue for their positions, followed by a Judge who makes the final decision,
and a Risk Evaluator who determines position sizing.

The analyzer is split into mixins for code organization:
- ReportFormatterMixin: Data-to-text formatting for AI prompts
- MemoryManagerMixin: Trading memory, scoring, and reflection system
- prompt_constants: INDICATOR_DEFINITIONS and SIGNAL_CONFIDENCE_MATRIX

Key Features:
- Bull/Bear Debate: Two opposing views debate the market direction
- Research Manager (Judge): Evaluates debate and makes definitive decision
- Entry Timing Agent: Evaluates optimal entry timing (v23.0)
- Risk Evaluator: Assesses risk and determines position sizing
- Memory System: Learns from past decisions to avoid repeating mistakes
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from openai import OpenAI

# S/R Zone Calculator (v3.8: Multi-source support/resistance detection)
from utils.sr_zone_calculator import SRZoneCalculator

# v18.3: get_default_sl_pct removed — SL validation handled by
# calculate_mechanical_sltp() in strategy/order_execution.py

from agents.prompt_constants import (
    INDICATOR_DEFINITIONS,
    _trim_matrix_for_regime,
    FEATURE_SCHEMA,
    FEATURE_VERSION,
    SCHEMA_VERSION,
    REASON_TAGS,
    BULLISH_EVIDENCE_TAGS,
    BEARISH_EVIDENCE_TAGS,
    BULL_SCHEMA,
    BEAR_SCHEMA,
    JUDGE_SCHEMA,
    ENTRY_TIMING_SCHEMA,
    RISK_SCHEMA,
    PROMPT_REGISTRY,
    compute_prompt_version,
)
from agents.report_formatter import ReportFormatterMixin
from agents.memory_manager import MemoryManagerMixin
from agents.ai_quality_auditor import AIQualityAuditor
from agents.analysis_context import AnalysisContext, MemoryConditions
from agents.tag_validator import compute_valid_tags, compute_annotated_tags, filter_output_tags, validate_judge_confluence

# Max characters for memory text injected into AI prompts.
# Typical memory: 5 wins + 5 losses + stats ≈ 2000-3000 chars.
# Previous value (500) truncated most trade history, severely limiting AI learning.
_MEMORY_PROMPT_MAX_CHARS = 2000


class MultiAgentAnalyzer(ReportFormatterMixin, MemoryManagerMixin):
    """
    Multi-agent trading analysis system with Bull/Bear debate mechanism.

    This replaces the single-agent DeepSeek analysis with a multi-perspective
    debate system that produces more balanced and well-reasoned trading decisions.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        temperature: float = 0.3,
        base_url: str = "https://api.deepseek.com",
        debate_rounds: int = 2,
        retry_delay: float = 1.0,  # Configurable retry delay
        json_parse_max_retries: int = 2,  # Configurable JSON parse retries
        memory_file: str = "data/trading_memory.json",  # v3.12: Persistent memory
        sr_zones_config: Optional[Dict] = None,  # v3.0: S/R Zone config from base.yaml
        enable_thinking: bool = False,  # v32.0: Enable DeepSeek V3.2 thinking mode
    ):
        """
        Initialize the multi-agent analyzer.

        Parameters
        ----------
        api_key : str
            DeepSeek API key
        model : str
            Model name (default: deepseek-chat)
        temperature : float
            Temperature for responses (higher = more creative)
        base_url : str
            API base URL
        debate_rounds : int
            Number of debate rounds between Bull and Bear
        retry_delay : float
            Delay in seconds between retry attempts (default: 1.0)
        json_parse_max_retries : int
            Maximum retries for JSON parsing failures (default: 2)
        enable_thinking : bool
            v32.0: Enable DeepSeek V3.2 thinking mode for deeper reasoning.
            When enabled, passes extra_body={"thinking": {"type": "enabled"}}
            to all API calls. Improves instruction following and analysis quality
            at the cost of ~10x latency per call.
        """
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
        self.model = model
        self.temperature = temperature
        self.debate_rounds = debate_rounds
        self.retry_delay = retry_delay
        self.json_parse_max_retries = json_parse_max_retries
        self.enable_thinking = enable_thinking

        # Setup logger
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # v3.12: Persistent memory for learning from past decisions
        # Based on TradingGroup paper: label outcomes, compile experience summary
        self.memory_file = memory_file
        self.decision_memory: List[Dict] = self._load_memory()

        # Track debate history for debugging
        self.last_debate_transcript: str = ""

        # v14.0: Phase timeline for web transparency
        self.last_phase_timeline: Dict[str, Any] = {}

        # Track last prompts for diagnosis (v11.4)
        self.last_prompts: Dict[str, Dict[str, str]] = {}

        # Full call trace: every AI API call with input/output/timing
        self.call_trace: List[Dict[str, Any]] = []

        # v18.0 F3: Per-cycle cache for extended reflections (avoid 5× file reads)
        self._ext_reflections_cache: Optional[List[Dict]] = None

        # v40.0: TRANSITIONING regime hysteresis state (CB-3)
        # Stores raw regime transition detection from previous cycle.
        # compute_scores_from_features() reads this via feature_dict.
        # Persisted to data/hysteresis_state.json for cross-restart consistency.
        self._prev_regime_transition: str = "NONE"
        self._load_hysteresis_state()

        # Retry configuration
        self.max_retries = 2

        # v3.8: S/R Zone Calculator (multi-source support/resistance)
        # v3.0: Accept config from base.yaml sr_zones section
        sr_cfg = sr_zones_config or {}
        swing_cfg = sr_cfg.get('swing_detection', {})
        cluster_cfg = sr_cfg.get('clustering', {})
        scoring_cfg = sr_cfg.get('scoring', {})
        hard_ctrl_cfg = sr_cfg.get('hard_control', {})
        aggr_cfg = sr_cfg.get('aggregation', {})
        round_cfg = sr_cfg.get('round_number', {})

        self.sr_calculator = SRZoneCalculator(
            cluster_pct=cluster_cfg.get('cluster_pct', 0.5),
            zone_expand_pct=sr_cfg.get('zone_expand_pct', 0.1),
            hard_control_threshold_pct=hard_ctrl_cfg.get('threshold_pct', 1.0),
            # v5.1: ATR-adaptive hard control
            hard_control_threshold_mode=hard_ctrl_cfg.get('threshold_mode', 'fixed'),
            hard_control_atr_multiplier=hard_ctrl_cfg.get('atr_multiplier', 0.5),
            hard_control_atr_min_pct=hard_ctrl_cfg.get('atr_min_pct', 0.3),
            hard_control_atr_max_pct=hard_ctrl_cfg.get('atr_max_pct', 2.0),
            # v3.0: Swing Point config
            swing_detection_enabled=swing_cfg.get('enabled', True),
            swing_left_bars=swing_cfg.get('left_bars', 5),
            swing_right_bars=swing_cfg.get('right_bars', 5),
            swing_weight=swing_cfg.get('weight', 1.2),
            swing_max_age=swing_cfg.get('max_swing_age', 100),
            # v3.0: ATR adaptive clustering
            use_atr_adaptive=cluster_cfg.get('use_atr_adaptive', True),
            atr_cluster_multiplier=cluster_cfg.get('atr_cluster_multiplier', 0.5),
            # v3.0: Touch count scoring
            touch_count_enabled=scoring_cfg.get('touch_count_enabled', True),
            touch_threshold_atr=scoring_cfg.get('touch_threshold_atr', 0.3),
            optimal_touches=tuple(scoring_cfg.get('optimal_touches', [2, 3])),
            decay_after_touches=scoring_cfg.get('decay_after_touches', 4),
            # v4.0: Aggregation rules (from base.yaml: sr_zones.aggregation.*)
            same_data_weight_cap=aggr_cfg.get('same_data_weight_cap', 2.5),
            max_zone_weight=aggr_cfg.get('max_zone_weight', 6.0),
            confluence_bonus_2=aggr_cfg.get('confluence_bonus_2_sources', 0.2),
            confluence_bonus_3=aggr_cfg.get('confluence_bonus_3_sources', 0.5),
            # v4.0: Round Number config (from base.yaml: sr_zones.round_number.*)
            round_number_btc_step=round_cfg.get('btc_step', 5000),
            round_number_count=round_cfg.get('count', 3),
            logger=self.logger,
        )

        # Cache for S/R zones (updated in analyze())
        self._sr_zones_cache: Optional[Dict[str, Any]] = None
        # v18 Item 14/17: Alignment data (updated in _compute_trend_verdict())
        self._alignment_data: Optional[Dict[str, Any]] = None
        # v18 Item 20: Direction compliance violation counter
        self._compliance_violations: int = 0

        # v24.0: AI Quality Auditor — validates agent outputs post-hoc
        self._quality_auditor = AIQualityAuditor()
        self.last_quality_report: Optional[Dict[str, Any]] = None

    # ── v40.0 CB-3: Hysteresis state persistence ──

    def _load_hysteresis_state(self) -> None:
        """Load TRANSITIONING hysteresis state from disk (cross-restart)."""
        path = os.path.join("data", "hysteresis_state.json")
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    state = json.load(f)
                self._prev_regime_transition = state.get("prev_regime_transition", "NONE")
        except Exception:
            self._prev_regime_transition = "NONE"

    def _save_hysteresis_state(self) -> None:
        """Persist TRANSITIONING hysteresis state to disk."""
        path = os.path.join("data", "hysteresis_state.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"prev_regime_transition": self._prev_regime_transition}, f)
        except Exception:
            pass  # Non-critical — hysteresis resets gracefully on failure

    def _enforce_alignment_cap(
        self,
        decision: Dict,
        confluence: Dict,
        dim_scores: Optional[Dict] = None,
    ) -> bool:
        """v40.0: Regime-aware alignment enforcement — replaces 3 inline copies.

        Mechanically caps confidence based on aligned_layers count.
        v22.1 rules: ≤1 aligned → LOW, ≤2 aligned + HIGH → MEDIUM.
        v36.0: If both 1D trend and 4H momentum oppose the decision → LOW.
        v40.0 Phase 5a: TRANSITIONING regime allows LOW confidence trades
        when aligned_layers ≥ 1 (at least momentum confirms).
        v40.0 Phase 5c: TRANSITIONING + aligned=0 → forced HOLD.

        Returns True if confidence was capped.
        """
        _al = confluence.get("aligned_layers", 0) if isinstance(confluence, dict) else 0
        _conf = decision.get("confidence", "LOW")
        _dec = decision.get("decision", "HOLD")
        _conf_capped = False
        _regime_trans = dim_scores.get("regime_transition", "NONE") if dim_scores else "NONE"

        if _dec in ("LONG", "SHORT"):
            # v22.1: aligned_layers ↔ confidence consistency
            if _al <= 1 and _conf != "LOW":
                if _regime_trans != "NONE" and _al >= 1:
                    # v40.0 Phase 5a: TRANSITIONING with at least 1 aligned dimension
                    # → allow trade at LOW confidence (exploratory position)
                    decision["confidence"] = "LOW"
                    decision["_aligned_layers_cap"] = (
                        f"{_conf}→LOW (aligned={_al}, regime={_regime_trans})"
                    )
                    _conf_capped = True
                    self.logger.info(
                        f"ℹ️ v40.0: aligned_layers={_al} but regime={_regime_trans} "
                        f"→ allowing LOW confidence {_dec}"
                    )
                elif _regime_trans != "NONE" and _al == 0:
                    # v40.0 Phase 5c: TRANSITIONING but zero confirmation → too risky
                    decision["confidence"] = "LOW"
                    decision["decision"] = "HOLD"
                    decision["_aligned_layers_cap"] = (
                        f"HOLD (regime={_regime_trans} but aligned=0, no confirmation)"
                    )
                    _conf_capped = True
                    self.logger.warning(
                        f"⚠️ v40.0: regime={_regime_trans} but aligned_layers=0 "
                        f"→ forced HOLD (no momentum confirmation)"
                    )
                else:
                    # Standard: no TRANSITIONING → cap to LOW
                    decision["confidence"] = "LOW"
                    decision["_aligned_layers_cap"] = f"{_conf}→LOW (aligned={_al})"
                    _conf_capped = True
                    self.logger.warning(
                        f"⚠️ v22.1: aligned_layers={_al} ≤1 but confidence={_conf} "
                        f"→ capped to LOW"
                    )
            elif _al <= 2 and _conf == "HIGH":
                decision["confidence"] = "MEDIUM"
                decision["_aligned_layers_cap"] = f"HIGH→MEDIUM (aligned={_al})"
                _conf_capped = True
                self.logger.warning(
                    f"⚠️ v22.1: aligned_layers={_al} ≤2 but confidence=HIGH "
                    f"→ capped to MEDIUM"
                )

        # v36.0: Layer priority check — high-priority layers (1D+4H) vs decision.
        if _dec in ("LONG", "SHORT") and isinstance(confluence, dict):
            _opposite_dir = "BEARISH" if _dec == "LONG" else "BULLISH"
            _trend_1d = confluence.get("trend_1d", "NEUTRAL")
            _momentum_4h = confluence.get("momentum_4h", "NEUTRAL")
            if _trend_1d == _opposite_dir and _momentum_4h == _opposite_dir:
                _prev_conf = decision.get("confidence", "LOW")
                if _prev_conf != "LOW":
                    decision["confidence"] = "LOW"
                    decision["_layer_priority_cap"] = (
                        f"{_prev_conf}→LOW (1D={_trend_1d},4H={_momentum_4h} "
                        f"both oppose {_dec})"
                    )
                    _conf_capped = True
                    self.logger.warning(
                        f"⚠️ v36.0: 1D trend={_trend_1d} + 4H momentum={_momentum_4h} "
                        f"both oppose {_dec} — confidence capped to LOW"
                    )

        if _conf_capped:
            self.logger.info(
                f"📊 Alignment cap: {decision.get('decision')} "
                f"({_conf} → {decision.get('confidence')}) "
                f"[aligned_layers={_al}, regime={_regime_trans}]"
            )
        return _conf_capped

    def _call_api_with_retry(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        trace_label: str = "",
        response_format: Optional[Dict[str, str]] = None,
        seed: Optional[int] = None,
    ) -> str:
        """
        Call DeepSeek API with retry logic for robustness.

        Parameters
        ----------
        messages : List[Dict]
            Chat messages to send
        temperature : float, optional
            Override default temperature
        response_format : dict, optional
            v27.0: {"type": "json_object"} for structured output
        seed : int, optional
            v27.0: RNG seed for deterministic sampling

        Returns
        -------
        str
            API response content

        Raises
        ------
        Exception
            If all retries fail
        """
        last_error = None
        temp = temperature if temperature is not None else self.temperature

        for attempt in range(self.max_retries + 1):
            try:
                t0 = time.monotonic()
                kwargs = dict(
                    model=self.model,
                    messages=messages,
                    temperature=temp,
                )
                if response_format:
                    kwargs["response_format"] = response_format
                if seed is not None:
                    kwargs["seed"] = seed
                # v32.0: Enable thinking mode for deeper reasoning
                if self.enable_thinking:
                    kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                response = self.client.chat.completions.create(**kwargs)
                elapsed = time.monotonic() - t0
                content = response.choices[0].message.content
                # v32.0: Capture reasoning_content from thinking mode
                reasoning_content = getattr(response.choices[0].message, 'reasoning_content', None)
                if reasoning_content is None and hasattr(response.choices[0].message, 'model_extra'):
                    reasoning_content = (response.choices[0].message.model_extra or {}).get('reasoning_content')
                # Record call trace for diagnostics
                usage = response.usage
                token_info = {}
                if usage:
                    token_info = {
                        "prompt": usage.prompt_tokens,
                        "completion": usage.completion_tokens,
                        "total": usage.total_tokens,
                    }
                    # v32.0: Track reasoning tokens from thinking mode
                    reasoning_tokens = None
                    if hasattr(usage, 'completion_tokens_details') and usage.completion_tokens_details:
                        details = usage.completion_tokens_details
                        reasoning_tokens = getattr(details, 'reasoning_tokens', None)
                        if reasoning_tokens is None and hasattr(details, 'model_extra'):
                            reasoning_tokens = (details.model_extra or {}).get('reasoning_tokens')
                    if reasoning_tokens is not None:
                        token_info["reasoning_tokens"] = reasoning_tokens
                    # DeepSeek context caching metrics (auto-enabled, prefix matching)
                    # Try direct attribute first (works if openai SDK allows extra fields),
                    # then fall back to model_extra dict (Pydantic V2 non-standard fields)
                    cache_hit = getattr(usage, 'prompt_cache_hit_tokens', None)
                    cache_miss = getattr(usage, 'prompt_cache_miss_tokens', None)
                    if cache_hit is None and hasattr(usage, 'model_extra'):
                        extras = usage.model_extra or {}
                        cache_hit = extras.get('prompt_cache_hit_tokens')
                        cache_miss = extras.get('prompt_cache_miss_tokens')
                    if cache_hit is not None:
                        token_info["cache_hit"] = cache_hit
                    if cache_miss is not None:
                        token_info["cache_miss"] = cache_miss
                trace_entry = {
                    "label": trace_label or f"call_{len(self.call_trace)+1}",
                    "messages": messages,
                    "temperature": temp,
                    "response": content,
                    "elapsed_sec": round(elapsed, 2),
                    "tokens": token_info,
                    "schema_version": SCHEMA_VERSION,
                    "feature_version": FEATURE_VERSION,
                    "model_version": self.model,
                    "json_mode": bool(response_format),
                    "thinking_enabled": self.enable_thinking,
                }
                # v32.0: Store reasoning_content in trace for audit trail
                if reasoning_content:
                    trace_entry["reasoning_content"] = reasoning_content
                # v27.0: Track prompt hash and seed for replay/AB testing
                if len(messages) >= 2:
                    trace_entry["prompt_hash"] = compute_prompt_version(
                        messages[0].get("content", "") + messages[-1].get("content", "")
                    )
                if seed is not None:
                    trace_entry["seed"] = seed
                self.call_trace.append(trace_entry)
                return content
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    self.logger.warning(
                        f"API call failed (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                        f"Retrying in {self.retry_delay}s..."
                    )
                    time.sleep(self.retry_delay)
                else:
                    self.logger.error(f"API call failed after {self.max_retries + 1} attempts: {e}")

        raise last_error

    def _extract_json_with_retry(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_json_retries: int = 2,
        trace_label: str = "",
        use_json_mode: bool = False,
        seed: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Call API and extract JSON, with retry on parse failure.

        Parameters
        ----------
        messages : List[Dict]
            Chat messages to send
        temperature : float
            Temperature for API call
        max_json_retries : int
            Maximum retries for JSON parsing failures
        use_json_mode : bool
            v27.0: Use DeepSeek json_object response_format
        seed : int, optional
            v27.0: RNG seed for deterministic sampling

        Returns
        -------
        Optional[Dict]
            Parsed JSON dict, or None if all retries fail
        """
        response_format = {"type": "json_object"} if use_json_mode else None
        for retry_attempt in range(max_json_retries + 1):
            try:
                result = self._call_api_with_retry(
                    messages=messages, temperature=temperature,
                    trace_label=trace_label, response_format=response_format,
                    seed=seed,
                )
                self.logger.debug(f"API response (attempt {retry_attempt + 1}): {result}")

                # Extract JSON from response
                start = result.find('{')
                end = result.rfind('}') + 1
                if start != -1 and end > 0 and start < end:
                    json_str = result[start:end]
                    if json_str.strip():
                        return json.loads(json_str)

                # If we reach here, JSON extraction failed
                if retry_attempt < max_json_retries:
                    self.logger.warning(
                        f"Failed to extract valid JSON (attempt {retry_attempt + 1}/{max_json_retries + 1}). Retrying..."
                    )
                    time.sleep(self.retry_delay)
                else:
                    self.logger.error(f"Failed to extract valid JSON after {max_json_retries + 1} attempts")

            except (json.JSONDecodeError, TypeError, ValueError) as e:
                if retry_attempt < max_json_retries:
                    self.logger.warning(
                        f"JSON parse error (attempt {retry_attempt + 1}/{max_json_retries + 1}): {e}. Retrying..."
                    )
                    time.sleep(self.retry_delay)
                else:
                    self.logger.error(f"JSON parse failed after {max_json_retries + 1} attempts: {e}")

        return None

    def _validate_agent_output(
        self,
        output: Dict[str, Any],
        schema: Dict[str, Any],
        agent_name: str,
        defaults: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        v27.0: Validate agent output against schema with type coercion.

        Checks:
        1. All required_keys present (missing -> apply default)
        2. Type coercion (LLM may return wrong types):
           - float fields: str "0.75" -> float 0.75, bool True -> 1.0
           - int fields: str "3" -> int 3, float 3.0 -> int 3
           - str enum fields: case-insensitive match ("high" -> "HIGH")
        3. Enum fields in valid_values (invalid after coercion -> apply default)
        4. List fields contain only REASON_TAGS (unknown tags removed + warning logged)
        5. Numeric constraints (min/max clamp)
        6. String constraints (max_length truncation)
        """
        if not output:
            output = {}
        if not defaults:
            defaults = {}

        required = schema.get("required_keys", {})
        valid = schema.get("valid_values", {})
        constraints = schema.get("constraints", {})
        violations = 0  # Track schema violations for monitoring

        result = dict(output)

        # Strip unknown keys (equivalent to JSON Schema additionalProperties: false)
        extra_keys = set(result.keys()) - set(required.keys())
        if extra_keys:
            for ek in extra_keys:
                del result[ek]
            violations += len(extra_keys)
            self.logger.debug(
                f"[{agent_name}] Stripped {len(extra_keys)} unknown key(s): "
                f"{', '.join(sorted(extra_keys))}"
            )

        for key, expected_type in required.items():
            if key not in result:
                if key in defaults:
                    result[key] = defaults[key]
                elif expected_type == list:
                    result[key] = []
                elif expected_type == float:
                    result[key] = 0.0
                elif expected_type == int:
                    result[key] = 0
                elif expected_type == str:
                    result[key] = ""
                elif expected_type == dict or isinstance(expected_type, dict):
                    result[key] = defaults.get(key, {})
                else:
                    result[key] = defaults.get(key, "")
                violations += 1
                self.logger.debug(f"[{agent_name}] Missing key '{key}', using default: {result[key]}")
                # Track confidence origin for confidence chain
                if key == "confidence":
                    result["_confidence_origin"] = "DEFAULT"

            val = result[key]

            # Nested dict validation (e.g. confluence sub-fields)
            if isinstance(expected_type, dict) and isinstance(val, dict):
                sub_valid = valid.get(key, {})
                for sub_key, sub_type in expected_type.items():
                    if sub_key not in val:
                        sub_default = defaults.get(key, {}).get(sub_key, "")
                        val[sub_key] = sub_default
                        self.logger.debug(
                            f"[{agent_name}] Missing nested key '{key}.{sub_key}', "
                            f"using default: {sub_default}"
                        )
                    sub_val = val[sub_key]
                    # Type coercion for nested fields
                    if sub_type == int and not isinstance(sub_val, int):
                        try:
                            val[sub_key] = int(float(sub_val))
                        except (ValueError, TypeError):
                            val[sub_key] = defaults.get(key, {}).get(sub_key, 0)
                    elif sub_type == str and isinstance(sub_val, str):
                        if isinstance(sub_valid, dict) and sub_key in sub_valid:
                            sv_set = sub_valid[sub_key]
                            if isinstance(sv_set, set):
                                sv_upper = sub_val.upper()
                                if sv_upper in sv_set:
                                    val[sub_key] = sv_upper
                                else:
                                    fallback = defaults.get(key, {}).get(sub_key, "")
                                    val[sub_key] = fallback
                                    violations += 1
                                    self.logger.warning(
                                        f"[{agent_name}] Invalid enum '{sub_val}' for "
                                        f"'{key}.{sub_key}', using default: {fallback}"
                                    )
                # Apply nested constraints
                if key in constraints and isinstance(constraints[key], dict):
                    for sub_key, sub_c in constraints[key].items():
                        if sub_key in val and isinstance(sub_c, dict):
                            if "min" in sub_c and isinstance(val[sub_key], (int, float)):
                                val[sub_key] = max(val[sub_key], sub_c["min"])
                            if "max" in sub_c and isinstance(val[sub_key], (int, float)):
                                val[sub_key] = min(val[sub_key], sub_c["max"])
                result[key] = val
                continue

            # Type coercion
            if expected_type == float and not isinstance(val, float):
                try:
                    result[key] = float(val)
                except (ValueError, TypeError):
                    result[key] = defaults.get(key, 0.0)

            elif expected_type == int and not isinstance(val, int):
                try:
                    result[key] = int(float(val))
                except (ValueError, TypeError):
                    result[key] = defaults.get(key, 0)

            elif expected_type == str and isinstance(val, str):
                # Case-insensitive enum matching
                if key in valid:
                    valid_set = valid[key]
                    if isinstance(valid_set, set):
                        val_upper = val.upper()
                        if val_upper in valid_set:
                            result[key] = val_upper
                        elif val_upper not in valid_set:
                            result[key] = defaults.get(key, list(valid_set)[0] if valid_set else "")
                            violations += 1
                            self.logger.warning(
                                f"[{agent_name}] Invalid enum '{val}' for '{key}', "
                                f"using default: {result[key]}"
                            )
                            # Track confidence origin for confidence chain
                            if key == "confidence":
                                result["_confidence_origin"] = "COERCED"

            elif expected_type == list and isinstance(val, list):
                # Validate REASON_TAGS in list fields
                if key in valid and valid[key] is REASON_TAGS:
                    cleaned = []
                    for tag in val:
                        tag_str = str(tag).upper()
                        if tag_str in REASON_TAGS:
                            cleaned.append(tag_str)
                        else:
                            violations += 1
                            self.logger.debug(f"[{agent_name}] Unknown tag '{tag}' in '{key}', removed")
                    result[key] = cleaned

            # Numeric constraints (min/max clamp)
            if key in constraints:
                c = constraints[key]
                if "min" in c and isinstance(result[key], (int, float)):
                    result[key] = max(result[key], c["min"])
                if "max" in c and isinstance(result[key], (int, float)):
                    result[key] = min(result[key], c["max"])
                if "max_length" in c and isinstance(result[key], str):
                    # v29.4+: Preserve raw text before truncation for downstream
                    # audit. Quality auditor needs full text to detect data
                    # references that may appear beyond the truncation point.
                    # v29.5: Extended to ALL text fields (reasoning, summary,
                    # rationale, reason) — prevents false citation errors from
                    # auditing truncated text.
                    if len(result[key]) > c["max_length"]:
                        result[f"_raw_{key}"] = result[key]
                    result[key] = result[key][:c["max_length"]]
                if "min_items" in c and isinstance(result[key], list):
                    # Don't pad, just log if under minimum
                    if len(result[key]) < c["min_items"]:
                        self.logger.debug(
                            f"[{agent_name}] '{key}' has {len(result[key])} items, "
                            f"minimum is {c['min_items']}"
                        )
                if "max_items" in c and isinstance(result[key], list):
                    result[key] = result[key][:c["max_items"]]
                if "item_max_length" in c and isinstance(result[key], list):
                    max_len = c["item_max_length"]
                    result[key] = [
                        str(item)[:max_len] if isinstance(item, str) else str(item)[:max_len]
                        for item in result[key]
                    ]

        # Track cumulative violations for monitoring
        if violations > 0:
            self.logger.warning(
                f"[{agent_name}] Schema validation: {violations} violation(s) corrected"
            )
            if not hasattr(self, '_schema_violations'):
                self._schema_violations = {}
            self._schema_violations[agent_name] = (
                self._schema_violations.get(agent_name, 0) + violations
            )

        # Monitor free-text fields for directional language leakage
        _directional_terms = {"must buy", "must sell", "definitely long", "definitely short",
                              "guaranteed profit", "100% chance"}
        for key in ("summary", "rationale", "reason"):
            if key in result and isinstance(result[key], str):
                val_lower = result[key].lower()
                for term in _directional_terms:
                    if term in val_lower:
                        self.logger.warning(
                            f"[{agent_name}] Free-text '{key}' contains "
                            f"directional language: '{term}'"
                        )
                        if not hasattr(self, '_schema_violations'):
                            self._schema_violations = {}
                        self._schema_violations[f"{agent_name}_freetext"] = (
                            self._schema_violations.get(f"{agent_name}_freetext", 0) + 1
                        )
                        break  # One warning per field is enough

        return result

    def _safe_filter_tags(self, output: dict, valid_tags, agent_label: str) -> int:
        """Filter invalid tags and ensure tag lists are never empty.

        Checks ALL possible tag fields (evidence, decisive_reasons, risk_flags,
        risk_factors) — not just 'evidence' — so that Judge, Entry Timing, and
        Risk Manager are handled correctly alongside Bull/Bear.
        """
        removed = filter_output_tags(output, valid_tags)

        # Determine which tag fields this agent actually uses
        _TAG_FIELDS = ("evidence", "risk_flags", "decisive_reasons", "risk_factors", "acknowledged_risks")
        present_fields = [f for f in _TAG_FIELDS if f in output and isinstance(output[f], list)]

        if not present_fields:
            # Agent has no tag fields at all — nothing to fallback
            return removed

        # Check if ALL present tag fields are empty after filtering
        all_empty = all(len(output[f]) == 0 for f in present_fields)
        if all_empty:
            # Pick the primary tag field for this agent to inject fallback
            primary = present_fields[0]
            output[primary] = ["INCONCLUSIVE"]
            self.logger.warning(
                f"[{agent_label}] All tags in {present_fields} filtered "
                f"— using INCONCLUSIVE fallback in '{primary}'"
            )
        return removed

    def _stamp_validated_output(self, validated: Dict[str, Any], trace_label: str) -> None:
        """Attach validated output to the matching call_trace entry for audit trail.

        The call_trace stores raw API responses under 'response'.  After
        _validate_agent_output() cleans/filters the output, this method saves the
        validated dict so the AI-call log shows *both* raw and validated results.
        """
        label_lower = trace_label.lower()
        # Walk backwards — the matching entry is usually the most recent one
        for entry in reversed(self.call_trace):
            if entry.get("label", "").lower() == label_lower:
                entry["validated_output"] = validated
                return

    def get_call_trace(self) -> List[Dict[str, Any]]:
        """Return the full AI API call trace for diagnostic export."""
        return self.call_trace

    def analyze(
        self,
        symbol: str,
        technical_report: Dict[str, Any],
        sentiment_report: Optional[Dict[str, Any]] = None,
        current_position: Optional[Dict[str, Any]] = None,
        price_data: Optional[Dict[str, Any]] = None,
        # ========== MTF v2.1: Multi-Timeframe Support ==========
        order_flow_report: Optional[Dict[str, Any]] = None,
        derivatives_report: Optional[Dict[str, Any]] = None,
        # ========== v3.0: Binance Derivatives (Top Traders, Taker Ratio) ==========
        binance_derivatives_report: Optional[Dict[str, Any]] = None,
        # ========== v3.7: Order Book Depth ==========
        orderbook_report: Optional[Dict[str, Any]] = None,
        # ========== v4.6: Account Context for Add/Reduce Decisions ==========
        account_context: Optional[Dict[str, Any]] = None,
        # ========== v3.0: OHLC bars for S/R Swing Detection ==========
        bars_data: Optional[List[Dict[str, Any]]] = None,
        # ========== v4.0: MTF bars for S/R pivot + volume profile ==========
        bars_data_4h: Optional[List[Dict[str, Any]]] = None,
        bars_data_1d: Optional[List[Dict[str, Any]]] = None,
        daily_bar: Optional[Dict[str, Any]] = None,
        weekly_bar: Optional[Dict[str, Any]] = None,
        atr_value: Optional[float] = None,
        # v6.6: Data quality warnings (list of degraded data sources)
        data_quality_warnings: Optional[List[str]] = None,
        # v18 Item 16: 4H CVD order flow
        order_flow_report_4h: Optional[Dict[str, Any]] = None,
        # v42.0: ET Exhaustion — skip Entry Timing Agent entirely (Tier 2)
        skip_entry_timing: bool = False,
        # v42.1: ET Exhaustion Tier 1 — override REJECT inside analyze()
        # so Risk Manager still evaluates the restored signal
        et_exhaustion_tier1: bool = False,
    ) -> Dict[str, Any]:
        """
        Run multi-agent analysis with Bull/Bear debate.

        TradingAgents Architecture (Judge-based decision):
        - Phase 1: Bull/Bear debate (2 × debate_rounds AI calls, sequential)
        - Phase 2: Judge decision (1 AI call with optimized prompt)
        - Phase 2.5: Entry Timing evaluation (1 AI call, v23.0)
        - Phase 3: Risk evaluation (1 AI call)

        Total: 2×debate_rounds + 3 AI calls (default debate_rounds=2 → 7 calls)

        Reference: https://github.com/TauricResearch/TradingAgents (UCLA/MIT paper)

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g., "BTCUSDT")
        technical_report : Dict
            Technical indicator data
        sentiment_report : Dict, optional
            Market sentiment data
        current_position : Dict, optional
            Current position information
        price_data : Dict, optional
            Current price data for stop/take profit calculation
        order_flow_report : Dict, optional
            Order flow data (buy/sell ratio, CVD trend) - MTF v2.1
        derivatives_report : Dict, optional
            Derivatives market data (OI, funding, liquidations) - MTF v2.1
        binance_derivatives_report : Dict, optional
            Binance-specific derivatives (top traders, taker ratio) - v3.0
        orderbook_report : Dict, optional
            Order book depth data (OBI, liquidity, slippage) - v3.7
        account_context : Dict, optional
            Account-level info for add/reduce decisions (v4.6):
            - equity, leverage, max_position_value
            - available_capacity, capacity_used_pct, can_add_position
        bars_data_4h : List[Dict], optional
            v4.0: 4H OHLCV bars for MTF swing detection
        bars_data_1d : List[Dict], optional
            v4.0: 1D OHLCV bars for MTF swing detection
        daily_bar : Dict, optional
            v4.0: Most recent completed daily bar for pivot calculation
        weekly_bar : Dict, optional
            v4.0: Aggregated weekly bar for pivot calculation
        atr_value : float, optional
            v4.0: Cached ATR value for S/R buffer calculation

        Returns
        -------
        Dict
            Final trading decision with structure:
            {
                "signal": "LONG|SHORT|CLOSE|HOLD|REDUCE",  # v3.12: Extended signals
                "confidence": "HIGH|MEDIUM|LOW",
                "risk_level": "LOW|MEDIUM|HIGH",
                "position_size_pct": 0-100,  # Target position as % of max allowed
                "stop_loss": float,
                "take_profit": float,
                "reason": str,
                "debate_summary": str,
                "timestamp": str
            }

            Signal types (v3.12):
            - LONG: Open/add to long position
            - SHORT: Open/add to short position
            - CLOSE: Close current position (no reverse)
            - HOLD: No action, maintain current state
            - REDUCE: Reduce current position size (keep direction)
        """
        try:
            self.logger.info("Starting multi-agent analysis (TradingAgents architecture)...")

            # Clear call trace for this analysis cycle
            self.call_trace = []

            # v18.0 F3: Clear per-cycle cache (avoid 5× file reads for bull/bear/judge/entry_timing/risk)
            self._ext_reflections_cache = None

            # v5.4: Extract base currency from symbol for dynamic unit display
            # e.g., "BTCUSDT" → "BTC", "ETHUSDT" → "ETH", "SOLUSDT" → "SOL"
            self._base_currency = symbol.replace('USDT', '') if 'USDT' in symbol else symbol

            # v6.6: Build data quality warning block for AI prompts
            _dq_block = ""
            if data_quality_warnings:
                _dq_block = (
                    "\n⚠️ DATA QUALITY WARNING: The following data sources are UNAVAILABLE or DEGRADED "
                    "this cycle. Weight your analysis accordingly — do NOT treat missing data as neutral:\n"
                    + "\n".join(f"  - {w}" for w in data_quality_warnings)
                    + "\n"
                )

            # v18 Item 16: Inject 4H CVD data into technical_report for formatting
            if order_flow_report_4h and technical_report is not None:
                technical_report['order_flow_4h'] = order_flow_report_4h

            # Format reports for prompts
            tech_summary = self._format_technical_report(technical_report)
            # v6.6: Prepend data quality warning so all 5 agents see it at top of data
            if _dq_block:
                tech_summary = _dq_block + tech_summary
            sent_summary = self._format_sentiment_report(sentiment_report)

            # Get current price for calculations (确保是数值类型)
            # 注意: 需要在 _format_derivatives_report 之前计算，用于 Liquidations BTC→USD 转换
            raw_price = price_data.get('price', 0) if price_data else technical_report.get('price', 0)
            try:
                current_price = float(raw_price) if raw_price is not None else 0.0
            except (ValueError, TypeError) as e:
                self.logger.debug(f"Using default value, original error: {e}")
                current_price = 0.0

            # MTF v2.1: Format order flow and derivatives for prompts
            # v19.2: Use 5-bar price change (not 122h period change) to match CVD 5-bar window
            # Previous bug: period_change_pct (~122h) vs cvd_net last 5 bars (~2.5h) = time-scale mismatch
            _hist_ctx = technical_report.get('historical_context', {}) if technical_report else {}
            _price_trend = _hist_ctx.get('price_trend', [])
            if _price_trend and len(_price_trend) >= 5:
                _cvd_price_change = ((_price_trend[-1] - _price_trend[-5]) / _price_trend[-5] * 100) if _price_trend[-5] > 0 else 0.0
            elif _price_trend and len(_price_trend) >= 2:
                _cvd_price_change = ((_price_trend[-1] - _price_trend[0]) / _price_trend[0] * 100) if _price_trend[0] > 0 else 0.0
            else:
                _cvd_price_change = float(technical_report.get('price_change', 0)) if technical_report else 0.0
            order_flow_summary = self._format_order_flow_report(order_flow_report, price_change_pct=_cvd_price_change)
            # v19.2: Pass order_flow_report for OI×CVD cross-analysis
            derivatives_summary = self._format_derivatives_report(
                derivatives_report, current_price, binance_derivatives_report,
                cvd_data=order_flow_report,
            )
            # v3.7: Format order book depth data
            orderbook_summary = self._format_orderbook_report(orderbook_report)

            # v3.8: Calculate S/R Zones (multi-source support/resistance)
            # v3.0: Pass bars_data for Swing Point detection and Touch Count
            # v4.0: Pass MTF bars for pivot points + volume profile
            # Phase 1.1: Pass order_flow_report so _calculate_sr_zones can inject
            #            taker_buy_volume into bars_data (indicator_manager bars lack it)
            sr_zones = self._calculate_sr_zones(
                current_price=current_price,
                technical_data=technical_report,
                orderbook_data=orderbook_report,
                bars_data=bars_data,
                bars_data_4h=bars_data_4h,
                bars_data_1d=bars_data_1d,
                daily_bar=daily_bar,
                weekly_bar=weekly_bar,
                atr_value=atr_value,
                order_flow_report=order_flow_report,
            )
            self._sr_zones_cache = sr_zones  # Cache for _evaluate_risk()
            # v6.0: Stamp calculation time for freshness checks
            if sr_zones:
                sr_zones['_calculated_at'] = time.time()
            # v2.0: Use detailed report (includes raw data + level/source_type)
            sr_zones_summary = sr_zones.get('ai_detailed_report', '') if sr_zones else ''
            if not sr_zones_summary:
                sr_zones_summary = sr_zones.get('ai_report', '') if sr_zones else ''

            # v27.0: Feature extraction (parallel path to text reports)
            # Try to extract features; on failure, continue with text-only path
            self._last_feature_snapshot = None
            try:
                feature_dict = self.extract_features(
                    technical_data=technical_report,
                    sentiment_data=sentiment_report,
                    order_flow_data=order_flow_report,
                    order_flow_4h=order_flow_report_4h,
                    derivatives_data=derivatives_report,
                    binance_derivatives=binance_derivatives_report,
                    orderbook_data=orderbook_report,
                    sr_zones=sr_zones,
                    current_position=current_position,
                    account_context=account_context,
                )
                # Persist feature snapshot for replay
                snapshot = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "schema_version": SCHEMA_VERSION,
                    "feature_version": FEATURE_VERSION,
                    "features": feature_dict,
                    "model_version": self.model,
                    "temperature": self.temperature,
                    "_complete": False,
                    "_input_contract": {
                        "deterministic": ["features"],
                        "context": ["_memory", "_opponent", "_debate_r1"],
                        "note": "Only 'features' is deterministic (same raw data -> same dict). "
                                "Context fields add state but break strict cross-session replay.",
                    },
                }
                self._last_feature_snapshot = snapshot
                self._persist_feature_snapshot(snapshot)
            except Exception as e:
                self.logger.error(
                    f"⚠️ Feature extraction failed: {e}. "
                    f"Skipping this analysis cycle (fail-fast). "
                    f"This should not happen in production — investigate root cause."
                )
                return None  # fail-fast: skip this cycle, retry in 20 min

            # v14.0: Phase timeline tracking for web transparency
            _analysis_start = time.monotonic()
            _phase_timeline = {}

            # v18.1: Extract 1D ADX early — needed by Bull/Bear for tier-aware prompts
            # (also used later by Judge for dynamic matrix trimming)
            _mtf_trend_early = technical_report.get('mtf_trend_layer') if isinstance(technical_report, dict) else None
            adx_1d_value = float(_mtf_trend_early.get('adx', 30)) if _mtf_trend_early and _mtf_trend_early.get('adx') is not None else 30.0

            # ===== AnalysisContext: create and precompute once =====
            ctx = AnalysisContext(symbol=symbol)
            ctx.features = feature_dict
            ctx.valid_tags = compute_valid_tags(feature_dict)
            ctx.annotated_tags = compute_annotated_tags(feature_dict, ctx.valid_tags)
            # v40.0 CB-3: Inject previous regime transition for hysteresis
            feature_dict["_prev_regime_transition"] = self._prev_regime_transition
            ctx.scores = ReportFormatterMixin.compute_scores_from_features(feature_dict)
            # v40.0 CB-3: Store raw detection for next cycle's hysteresis comparison
            self._prev_regime_transition = ctx.scores.get("_raw_regime_transition", "NONE")
            self._save_hysteresis_state()

            # Build memory conditions from feature_dict (replaces _build_current_conditions)
            mc = MemoryConditions.from_feature_dict(feature_dict)
            ctx.memory_conditions = mc
            current_conditions = mc.to_dict()

            # v12.0 / v18.3: Compute memory selection ONCE, then format per-role.
            selected_memories = self._select_memories(current_conditions)

            # v27.0: Attach structured memories to snapshot for replay determinism (§7.1)
            if self._last_feature_snapshot is not None and selected_memories:
                try:
                    self._last_feature_snapshot["_memory"] = self._get_structured_memories(selected_memories)
                except Exception as e:
                    self.logger.debug(f"Snapshot memory attach skipped: {e}")

            # Phase 1: Bull/Bear Debate (2 × debate_rounds AI calls)
            _phase1_start = time.monotonic()

            # v27.0: Feature-Driven Structured Debate (sole path, text fallback removed)
            self.logger.info("Phase 1: Starting structured Bull/Bear debate (feature-driven)...")
            _bull_r2, _bear_r2, debate_summary_text, debate_history = self._run_structured_debate(
                feature_dict=feature_dict,
                adx_1d=adx_1d_value,
                selected_memories=selected_memories,
                current_conditions=current_conditions,
                ctx=ctx,
            )
            # v27.0: Persist debate R1 outputs to snapshot for deterministic replay
            if self._last_feature_snapshot is not None and hasattr(self, '_last_debate_r1'):
                self._last_feature_snapshot["_debate_r1"] = self._last_debate_r1
                self._persist_feature_snapshot(self._last_feature_snapshot)

            # Store on context for downstream consumers (Auditor, snapshot)
            ctx.bull_output = _bull_r2
            ctx.bear_output = _bear_r2

            # Store transcript for debugging
            self.last_debate_transcript = debate_history
            _phase_timeline['debate'] = round(time.monotonic() - _phase1_start, 2)

            # Shared memory formatting for Judge and Risk
            past_memories_judge = self._get_past_memories(current_conditions, agent_role="judge", preselected=selected_memories)
            past_memories_risk = self._get_past_memories(current_conditions, agent_role="risk", preselected=selected_memories)

            # Phase 2: Judge makes decision (1 AI call)
            _phase2_start = time.monotonic()
            self.logger.info("Phase 2: Judge evaluating debate...")

            # v27.0: Feature-driven structured Judge (sole path)
            judge_decision = self._run_structured_judge(
                feature_dict=feature_dict,
                bull_r2=_bull_r2,
                bear_r2=_bear_r2,
                memory_text=past_memories_judge,
                adx_1d=adx_1d_value,
                ctx=ctx,
            )

            self.logger.info(
                f"🎯 Judge decision: {judge_decision.get('decision', 'HOLD')} "
                f"({judge_decision.get('confidence', 'LOW')} confidence)"
            )
            # Confidence chain: record Judge's confidence
            ctx.confidence_chain.add(
                phase="judge",
                value=judge_decision.get("confidence", "LOW"),
                origin=judge_decision.get("_confidence_origin", "AI"),
            )
            ctx.judge_output = judge_decision
            _phase_timeline['judge'] = round(time.monotonic() - _phase2_start, 2)

            # Phase 2.5: Entry Timing Agent (v23.0, 1 AI call)
            # Wrapped in independent try-except to prevent API/parse failures from
            # cascading to the outer except and discarding Phase 0-2 work.
            # v42.0: skip_entry_timing=True (Tier 2 exhaustion) bypasses ET entirely.
            _phase25_start = time.monotonic()
            judge_action = judge_decision.get('decision', 'HOLD')
            if judge_action in ('LONG', 'SHORT') and skip_entry_timing:
                self.logger.warning(
                    "⚡ v42.0: ET Exhaustion Tier 2 — skipping Entry Timing Agent entirely"
                )
                timing_assessment = {
                    'timing_verdict': 'ENTER',
                    'timing_quality': 'N/A',
                    'counter_trend_risk': 'N/A',
                    'adjusted_confidence': judge_decision.get('confidence', 'LOW'),
                    'reason': 'ET Exhaustion Tier 2: skipped (consecutive rejects >= threshold)',
                    '_et_exhaustion_skipped': True,
                }
                judge_decision = dict(judge_decision)
                judge_decision['_timing_assessment'] = timing_assessment
                judge_decision['_et_exhaustion_tier2'] = True
                _phase_timeline['entry_timing'] = 0.0
                ctx.et_output = timing_assessment
                ctx.judge_output = judge_decision
            elif judge_action in ('LONG', 'SHORT'):
                try:
                    self.logger.info("Phase 2.5: Entry Timing evaluation...")

                    # v27.0: Feature-driven structured Entry Timing (sole path)
                    past_memories_timing = self._get_past_memories(
                        current_conditions, agent_role="entry_timing", preselected=selected_memories
                    )
                    timing_assessment = self._run_structured_entry_timing(
                        feature_dict=feature_dict,
                        judge_decision=judge_decision,
                        adx_1d=adx_1d_value,
                        memory_text=past_memories_timing,
                        ctx=ctx,
                    )

                    # v23.0 fix: Shallow copy upfront to avoid mutating the original
                    # Judge dict in any code path (REJECT, ENTER+change, ENTER+no-change).
                    judge_decision = dict(judge_decision)

                    # Apply Entry Timing verdict
                    timing_verdict = timing_assessment.get('timing_verdict', 'ENTER')
                    if timing_verdict == 'REJECT':
                        # Entry Timing rejects: override Judge's signal to HOLD
                        self.logger.warning(
                            f"🚫 Entry Timing REJECT: {judge_action} → HOLD "
                            f"(reason: {timing_assessment.get('reason', 'N/A')})"
                        )
                        judge_decision['_timing_original_signal'] = judge_action
                        judge_decision['_timing_original_confidence'] = judge_decision.get('confidence', 'LOW')
                        judge_decision['decision'] = 'HOLD'
                        judge_decision['_timing_rejected'] = True
                        judge_decision['_timing_reason'] = timing_assessment.get('reason', '')
                        judge_decision['confidence'] = 'LOW'
                    else:
                        # ENTER: apply adjusted confidence (can only DECREASE, never upgrade)
                        adj_conf = timing_assessment.get('adjusted_confidence',
                                                          judge_decision.get('confidence', 'LOW'))
                        original_conf = judge_decision.get('confidence', 'LOW')
                        conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
                        # v23.0 invariant: confidence can only decrease from Entry Timing
                        if conf_rank.get(adj_conf, 0) > conf_rank.get(original_conf, 0):
                            self.logger.warning(
                                f"⏱️ Entry Timing tried to UPGRADE confidence: "
                                f"{original_conf} → {adj_conf}, clamping to {original_conf}"
                            )
                            adj_conf = original_conf
                        if adj_conf != original_conf:
                            self.logger.info(
                                f"⏱️ Entry Timing adjusted confidence: {original_conf} → {adj_conf}"
                            )
                            judge_decision['confidence'] = adj_conf
                            judge_decision['_timing_confidence_adjusted'] = f"{original_conf}→{adj_conf}"

                    # Store timing assessment in judge_decision for downstream access
                    judge_decision['_timing_assessment'] = timing_assessment

                    # Confidence chain: record Entry Timing adjustment
                    et_conf = judge_decision.get("confidence", "LOW")
                    if et_conf != ctx.confidence_chain.final:
                        ctx.confidence_chain.add(
                            phase="entry_timing",
                            value=et_conf,
                            origin="AI" if timing_verdict != "REJECT" else "CAPPED",
                            reason=timing_assessment.get("reason", ""),
                        )

                except Exception as e:
                    # Phase 2.5 failure should NOT discard Phase 0-2 results.
                    # Use conservative fallback: keep Judge's signal, degrade confidence.
                    self.logger.error(
                        f"Phase 2.5 Entry Timing failed: {e}. "
                        f"Preserving Judge decision ({judge_action}), applying conservative fallback."
                    )
                    is_counter_trend_phase25 = False
                    try:
                        _tl = (technical_report or {}).get('mtf_trend_layer', {})
                        _di_p = float(_tl.get('di_plus', 0) or 0)
                        _di_m = float(_tl.get('di_minus', 0) or 0)
                        if _di_p != 0 or _di_m != 0:
                            _bullish = _di_p > _di_m
                            is_counter_trend_phase25 = (
                                (judge_action == "LONG" and not _bullish) or
                                (judge_action == "SHORT" and _bullish)
                            )
                    except Exception as e:
                        self.logger.debug(f"Phase 2.5 fallback counter-trend detection failed: {e}")
                    original_conf = judge_decision.get('confidence', 'LOW')
                    fallback_conf = "MEDIUM" if original_conf == "HIGH" else original_conf
                    timing_assessment = {
                        "timing_verdict": "ENTER",
                        "timing_quality": "FAIR",
                        "adjusted_confidence": fallback_conf,
                        "counter_trend_risk": "HIGH" if is_counter_trend_phase25 else "NONE",
                        "alignment": "MODERATE",
                        "reason": f"Entry Timing error fallback — {type(e).__name__}: {e}",
                    }
                    # Always shallow copy to avoid mutating original Judge dict
                    # (mirrors happy-path line 1453)
                    judge_decision = dict(judge_decision)
                    if fallback_conf != original_conf:
                        judge_decision['confidence'] = fallback_conf
                        judge_decision['_timing_confidence_adjusted'] = f"{original_conf}→{fallback_conf}"
                    judge_decision['_timing_assessment'] = timing_assessment
            else:
                timing_assessment = {
                    'timing_verdict': 'N/A',
                    'timing_quality': 'N/A',
                    'adjusted_confidence': judge_decision.get('confidence', 'LOW'),
                    'counter_trend_risk': 'NONE',
                    'alignment': 'N/A',
                    'reason': 'Non-actionable signal',
                }

            ctx.et_output = timing_assessment
            # v32.4: Update ctx.judge_output after ET may have shallow-copied and
            # mutated judge_decision (REJECT → decision='HOLD', confidence='LOW').
            # Without this, ctx.judge_output still references the pre-copy dict,
            # causing Auditor's risk_received_hold check to see stale 'SHORT'
            # instead of 'HOLD', leading to false MISSING_DATA penalties on Risk.
            ctx.judge_output = judge_decision
            _phase_timeline['entry_timing'] = round(time.monotonic() - _phase25_start, 2)

            # v42.1: ET Exhaustion Tier 1 — override REJECT inside analyze()
            # BEFORE Risk Manager, so the restored LONG/SHORT signal gets properly
            # risk-evaluated. Previously this override happened in ai_strategy.py
            # AFTER analyze() returned, causing Risk Manager to be skipped entirely.
            #
            # v42.2: Severity-aware override — structural market risks block Tier 1.
            # ET REJECTs due to EXTREME counter-trend risk or HIGH counter-trend +
            # POOR timing quality indicate genuine structural danger (e.g., 1D extreme
            # extension + active reversal). Forcing a trade in these conditions is
            # "sending money against the trend". Only timing-related REJECTs (weak
            # 30M momentum, suboptimal entry timing) are eligible for override.
            # Tier 2 (>=8 rejects) remains as absolute safety valve.
            if (et_exhaustion_tier1
                    and judge_decision.get('_timing_rejected')
                    and judge_decision.get('_timing_original_signal') in ('LONG', 'SHORT')):
                # Check ET rejection severity from timing_assessment
                _ta = judge_decision.get('_timing_assessment', {})
                _ctr_risk = _ta.get('counter_trend_risk', 'NONE')
                _tq = _ta.get('timing_quality', 'FAIR')
                _is_structural_risk = (
                    _ctr_risk == 'EXTREME'
                    or (_ctr_risk == 'HIGH' and _tq == 'POOR')
                )

                if _is_structural_risk:
                    # Structural risk: DO NOT override — ET is correctly protecting
                    self.logger.warning(
                        f"🛡️ v42.2: ET Exhaustion Tier 1 BLOCKED — structural risk "
                        f"(counter_trend={_ctr_risk}, quality={_tq}). "
                        f"ET is correctly protecting against market structure danger. "
                        f"Signal remains HOLD."
                    )
                    judge_decision['_et_exhaustion_tier1_blocked'] = True
                    judge_decision['_et_exhaustion_block_reason'] = (
                        f"structural_risk: counter_trend={_ctr_risk}, quality={_tq}"
                    )
                    ctx.judge_output = judge_decision
                else:
                    # Timing risk only: safe to override
                    _restored_signal = judge_decision['_timing_original_signal']
                    self.logger.warning(
                        f"⚡ v42.1: ET Exhaustion Tier 1 override inside analyze() — "
                        f"restoring {_restored_signal} at LOW confidence for Risk evaluation "
                        f"(counter_trend={_ctr_risk}, quality={_tq})"
                    )
                    judge_decision['decision'] = _restored_signal
                    judge_decision['confidence'] = 'LOW'
                    judge_decision['_et_exhaustion_tier1'] = True
                    # Keep _timing_rejected=True so ai_strategy.py can detect
                    # that this was an exhaustion override (for counter management).
                    # But mark that the override already happened here.
                    judge_decision['_et_exhaustion_tier1_applied'] = True
                    ctx.judge_output = judge_decision

            # Phase 3: Risk evaluation
            # v32.1: Skip API call when Judge=HOLD/CLOSE/REDUCE — no new position
            # to size, so Risk Manager would just rubber-stamp the signal through.
            # Mirrors Entry Timing skip pattern (Phase 2.5).
            _phase3_start = time.monotonic()
            _final_signal = judge_decision.get('decision', 'HOLD')
            if _final_signal in ('LONG', 'SHORT'):
                self.logger.info("Phase 3: Risk evaluation...")

                # v27.0: Feature-driven structured Risk Manager (sole path)
                final_decision = self._run_structured_risk(
                    feature_dict=feature_dict,
                    judge_decision=judge_decision,
                    memory_text=past_memories_risk,
                    adx_1d=adx_1d_value,
                    ctx=ctx,
                )
            else:
                # Non-actionable signal: passthrough with safe defaults
                self.logger.info(
                    f"Phase 3: Risk evaluation skipped (signal={_final_signal}, "
                    f"no position to size)"
                )
                final_decision = {
                    "signal": _final_signal,
                    "confidence": judge_decision.get('confidence', 'LOW'),
                    "risk_appetite": "NORMAL",
                    "risk_level": "NORMAL",
                    "position_risk": "FULL_SIZE",
                    "market_structure_risk": "NORMAL",
                    "risk_factors": [],
                    "reason": f"Risk evaluation skipped — {_final_signal} signal",
                    "position_size_pct": 0,
                    "debate_summary": "",
                    "hold_source": "explicit_judge" if _final_signal == 'HOLD' else None,
                }

            ctx.risk_output = final_decision

            self.logger.info(f"Multi-agent decision: {final_decision.get('signal')} "
                           f"({final_decision.get('confidence')} confidence)")

            # v27.0: Populate debate_summary from structured or text debate
            if debate_summary_text:
                final_decision['debate_summary'] = debate_summary_text
            elif not final_decision.get('debate_summary'):
                # v29.5: Preserve full debate_history, no truncation.
                # Downstream consumers (Telegram, diagnostics) handle their own display limits.
                final_decision['debate_summary'] = debate_history if debate_history else ""

            # v27.0: Attach structured Bull/Bear tags for downstream (memory, logging)
            if _bull_r2 and _bear_r2:
                final_decision['_structured_debate'] = {
                    'bull': _bull_r2,
                    'bear': _bear_r2,
                }

            # v23.0: Propagate timing assessment into final decision
            final_decision['_timing_assessment'] = timing_assessment
            if judge_decision.get('_timing_rejected'):
                final_decision['_timing_rejected'] = True
                final_decision['_timing_original_signal'] = judge_decision.get('_timing_original_signal')
                final_decision['_timing_reason'] = judge_decision.get('_timing_reason', '')
            # v42.1: Propagate Tier 1 flag so ai_strategy.py knows the override
            # was applied inside analyze() (skips redundant signal override).
            if judge_decision.get('_et_exhaustion_tier1_applied'):
                final_decision['_et_exhaustion_tier1'] = True
                final_decision['_et_exhaustion_tier1_applied'] = True
            # v42.2: Propagate Tier 1 blocked flag (structural risk prevented override)
            if judge_decision.get('_et_exhaustion_tier1_blocked'):
                final_decision['_et_exhaustion_tier1_blocked'] = True
                final_decision['_et_exhaustion_block_reason'] = judge_decision.get(
                    '_et_exhaustion_block_reason', ''
                )

            # v14.0: Store phase timeline for web transparency
            _phase_timeline['risk'] = round(time.monotonic() - _phase3_start, 2)
            _phase_timeline['total'] = round(time.monotonic() - _analysis_start, 2)
            _phase_timeline['debate_rounds'] = self.debate_rounds
            _phase_timeline['api_calls'] = len(self.call_trace)

            # Token and cache summary from call trace
            total_tokens = sum(c.get('tokens', {}).get('total', 0) for c in self.call_trace)
            total_cache_hit = sum(c.get('tokens', {}).get('cache_hit', 0) or 0 for c in self.call_trace)
            total_cache_miss = sum(c.get('tokens', {}).get('cache_miss', 0) or 0 for c in self.call_trace)
            _phase_timeline['total_tokens'] = total_tokens
            if total_cache_hit > 0:
                _phase_timeline['cache_hit_tokens'] = total_cache_hit
                _phase_timeline['cache_miss_tokens'] = total_cache_miss
                total_prompt = total_cache_hit + total_cache_miss
                _phase_timeline['cache_hit_pct'] = round(total_cache_hit / total_prompt * 100, 1) if total_prompt > 0 else 0

            self.last_phase_timeline = _phase_timeline

            # Confidence chain summary logging
            if ctx.confidence_chain.steps:
                chain_summary = " → ".join(
                    f"{s.phase}:{s.value}({s.origin})" for s in ctx.confidence_chain.steps
                )
                self.logger.info(f"[{ctx.snapshot_id}] Confidence chain: {chain_summary}")
                if ctx.confidence_chain.has_default():
                    self.logger.warning(f"[{ctx.snapshot_id}] ⚠️ Confidence chain contains DEFAULT/COERCED step")

            # v24.0: Post-hoc AI quality audit
            try:
                _bull_text, _bear_text = self._extract_last_round_texts(debate_history)
                ctx.debate_bull_text = _bull_text
                ctx.debate_bear_text = _bear_text

                # v30.0: Bundle raw data onto ctx for audit fallback
                ctx.raw_data = {
                    'technical': technical_report,
                    'sentiment': sentiment_report,
                    'order_flow': order_flow_report,
                    'derivatives': derivatives_report,
                    'orderbook': orderbook_report,
                    'sr_zones': sr_zones,
                }

                quality_report = self._quality_auditor.audit(ctx)
                self.last_quality_report = quality_report.to_dict()
                final_decision['_quality_score'] = quality_report.overall_score
                # Write back to context for downstream snapshot
                ctx.quality_score = quality_report.overall_score
                ctx.quality_flags = quality_report.flags if quality_report.flags else []
                if quality_report.flags:
                    self.logger.info(
                        f"AI Quality Audit: {quality_report.to_summary()}")
                else:
                    self.logger.debug(
                        f"AI Quality Audit: {quality_report.overall_score}/100 (no flags)")
            except Exception as e:
                self.logger.debug(f"AI Quality Audit skipped: {e}")
                self.last_quality_report = None

            # v27.0: Update snapshot with prompt_hashes from call_trace (§7.1)
            if self._last_feature_snapshot is not None and self.call_trace:
                try:
                    prompt_hashes = {}
                    for entry in self.call_trace:
                        label = entry.get("label", "").lower()
                        ph = entry.get("prompt_hash")
                        if ph:
                            if "bull" in label:
                                prompt_hashes.setdefault("bull", ph)
                            elif "bear" in label:
                                prompt_hashes.setdefault("bear", ph)
                            elif "judge" in label:
                                prompt_hashes.setdefault("judge", ph)
                            elif "entry timing" in label:
                                prompt_hashes.setdefault("entry_timing", ph)
                            elif "risk" in label:
                                prompt_hashes.setdefault("risk", ph)
                    if prompt_hashes:
                        self._last_feature_snapshot["prompt_hashes"] = prompt_hashes

                    # v30.3: Decision Cache — persist all agent outputs for zero-API replay
                    self._last_feature_snapshot["_decision_cache"] = {
                        "bull_r2": ctx.bull_output,
                        "bear_r2": ctx.bear_output,
                        "judge": ctx.judge_output,
                        "entry_timing": ctx.et_output,
                        "risk": ctx.risk_output,
                        "quality_score": ctx.quality_score,
                        "signal": final_decision.get("signal", "HOLD"),
                        "confidence": final_decision.get("confidence", "LOW"),
                    }

                    # Mark snapshot as complete (all agents ran successfully)
                    self._last_feature_snapshot["_complete"] = True

                    # v33.0: Persist quality audit results for debugging
                    if ctx.quality_score is not None:
                        self._last_feature_snapshot["quality_score"] = ctx.quality_score
                    if ctx.quality_flags:
                        self._last_feature_snapshot["quality_flags"] = ctx.quality_flags

                    # Re-persist with updated data (prompt_hashes + decision_cache)
                    self._persist_feature_snapshot(self._last_feature_snapshot)
                except Exception as e:
                    self.logger.debug(f"Snapshot prompt hash attach skipped: {e}")

            # AnalysisContext: attach snapshots for downstream (event_handlers snapshot)
            final_decision['_memory_conditions_snapshot'] = ctx.memory_conditions.to_dict() if ctx.memory_conditions else None
            final_decision['_ai_quality_score'] = ctx.quality_score
            # Confidence chain: serialize for diagnostic inspection
            final_decision['_confidence_chain'] = [
                {"phase": s.phase, "value": s.value, "origin": s.origin, "reason": s.reason}
                for s in ctx.confidence_chain.steps
            ]

            # Persist last AnalysisContext for diagnostic access
            self._last_analysis_context = ctx

            return final_decision

        except Exception as e:
            self.logger.error(f"Multi-agent analysis failed: {e}")
            return self._create_fallback_signal(price_data or technical_report)

    @staticmethod
    def _extract_last_round_texts(debate_history: str) -> tuple:
        """
        v24.0: Extract Bull and Bear texts from the last debate round.

        Returns:
            (bull_text: str, bear_text: str)
        """
        # Split by round markers and take the last round
        import re as _re
        rounds = _re.split(r'=== ROUND \d+ ===', debate_history)
        last_round = rounds[-1] if rounds else debate_history

        bull_text = ''
        bear_text = ''

        # Extract Bull and Bear sections
        bull_match = _re.search(
            r'BULL ANALYST:\s*\n(.*?)(?=\n\nBEAR ANALYST:|\Z)',
            last_round, _re.DOTALL,
        )
        if bull_match:
            bull_text = bull_match.group(1).strip()

        bear_match = _re.search(
            r'BEAR ANALYST:\s*\n(.*)',
            last_round, _re.DOTALL,
        )
        if bear_match:
            bear_text = bear_match.group(1).strip()

        return bull_text, bear_text

    def _audit_citation_accuracy(
        self, agent_role: str, argument_text: str,
        technical_data: Optional[Dict] = None,
    ) -> str:
        """
        v25.0: Post-hoc audit — detect DI+/DI- comparison errors in agent output.

        Extracts DI+/DI- numerical citations from argument text via regex,
        cross-references against actual values in technical_data.
        Returns a DATA CORRECTION string to append (empty if no errors).

        Integrates with existing COMPLIANCE NOTE mechanism — appended to agent
        output BEFORE it enters debate_history, so downstream agents (Judge)
        see the correction alongside the original argument.
        """
        if not argument_text or not technical_data:
            return ""

        import re
        corrections = []

        # Check each timeframe's DI values
        _timeframes = [
            ('30M', technical_data),
            ('4H', technical_data.get('mtf_decision_layer', {})),
            ('1D', technical_data.get('mtf_trend_layer', {})),
        ]

        for tf_label, tf_data in _timeframes:
            if not tf_data or not isinstance(tf_data, dict):
                continue
            actual_di_plus = tf_data.get('di_plus')
            actual_di_minus = tf_data.get('di_minus')
            if actual_di_plus is None or actual_di_minus is None:
                continue
            actual_di_plus = float(actual_di_plus)
            actual_di_minus = float(actual_di_minus)
            actual_cmp = '>' if actual_di_plus > actual_di_minus else '<'
            actual_dir = 'BULLISH' if actual_di_plus > actual_di_minus else 'BEARISH'

            # Pattern: "DI+(X) < DI-(Y)" or "DI-(Y) > DI+(X)" in agent output
            # Matches various formats: DI+ (23.9) < DI- (22.1), DI+:23.9<DI-:22.1, etc.
            patterns = [
                # "DI+(X) < DI-(Y)" — agent claims DI+ less than DI-
                rf'DI\+\s*[\(:]?\s*({re.escape(f"{actual_di_plus:.1f}")})\s*[\)]?\s*<\s*DI-\s*[\(:]?\s*({re.escape(f"{actual_di_minus:.1f}")})',
                # "DI-(Y) > DI+(X)" — agent claims DI- greater than DI+
                rf'DI-\s*[\(:]?\s*({re.escape(f"{actual_di_minus:.1f}")})\s*[\)]?\s*>\s*DI\+\s*[\(:]?\s*({re.escape(f"{actual_di_plus:.1f}")})',
            ]

            if actual_di_plus > actual_di_minus:
                # Actual: DI+ > DI- (BULLISH). Check if agent reversed it.
                for p in patterns:
                    if re.search(p, argument_text, re.IGNORECASE):
                        corrections.append(
                            f"{tf_label} DI: {agent_role} stated DI+<DI- but actual "
                            f"DI+={actual_di_plus:.1f} {actual_cmp} DI-={actual_di_minus:.1f} → {actual_dir}"
                        )
                        break
            elif actual_di_minus > actual_di_plus:
                # Actual: DI- > DI+ (BEARISH). Check if agent reversed it.
                reverse_patterns = [
                    rf'DI\+\s*[\(:]?\s*({re.escape(f"{actual_di_plus:.1f}")})\s*[\)]?\s*>\s*DI-\s*[\(:]?\s*({re.escape(f"{actual_di_minus:.1f}")})',
                    rf'DI-\s*[\(:]?\s*({re.escape(f"{actual_di_minus:.1f}")})\s*[\)]?\s*<\s*DI\+\s*[\(:]?\s*({re.escape(f"{actual_di_plus:.1f}")})',
                ]
                for p in reverse_patterns:
                    if re.search(p, argument_text, re.IGNORECASE):
                        corrections.append(
                            f"{tf_label} DI: {agent_role} stated DI+>DI- but actual "
                            f"DI+={actual_di_plus:.1f} {actual_cmp} DI-={actual_di_minus:.1f} → {actual_dir}"
                        )
                        break

        if not corrections:
            return ""

        self.logger.warning(
            f"⚠️ {agent_role.upper()} citation accuracy: {len(corrections)} error(s) — "
            f"{'; '.join(corrections)}"
        )
        self._compliance_violations += 1
        return (
            f"\n\n⚠️ DATA CORRECTION: {'; '.join(corrections)}. "
            f"Judge should verify DI+/DI- values from KEY MARKET METRICS, "
            f"not from this analyst's claims."
        )

    def _audit_direction_compliance(self, agent_role: str, argument_text: str,
                                    adx_1d: float) -> tuple:
        """
        v18 Item 20: Post-hoc audit — does Bull/Bear use 30M data for direction claims?

        Returns:
            (audit_result: str, violations: list)
            audit_result: "COMPLIANT" | "MINOR_VIOLATION" | "MAJOR_VIOLATION"
        """
        # Skip audit in ranging markets — 30M data is legitimately important
        if adx_1d < 25:
            return "COMPLIANT", []

        violations = []
        import re

        # Pattern 1: 30M RSI/MACD/BB used as direction evidence
        patterns_direction_from_30m = [
            r'(?:30[Mm]|执行层)\s*RSI.*(?:表明|说明|确认|支持|shows?|indicates?|confirms?|suggests?).*(?:方向|趋势|momentum|bullish|bearish|看[多空]|上涨|下跌)',
            r'(?:30[Mm]|执行层)\s*(?:MACD|BB|SMA).*(?:方向|趋势|direction|trend)',
            r'(?:从|based on|according to)\s*(?:30[Mm]|执行层).*(?:方向|趋势|direction)',
        ]

        for pattern in patterns_direction_from_30m:
            matches = re.findall(pattern, argument_text, re.IGNORECASE)
            if matches:
                violations.append(f"30M→direction: '{str(matches[0])}")

        # Pattern 2: 30M data cited before 4H/1D in first 30% (micro-first ordering)
        first_30pct = argument_text[:len(argument_text) // 3]
        if re.search(r'(?:30[Mm]|执行层)\s*(?:RSI|MACD|BB|SMA)', first_30pct, re.IGNORECASE):
            if not re.search(r'(?:1[Dd]|4[Hh]|日线|趋势层|决策层)', first_30pct, re.IGNORECASE):
                violations.append("Micro-first: 30M data cited before any 1D/4H reference")

        if len(violations) == 0:
            return "COMPLIANT", []
        elif len(violations) == 1:
            return "MINOR_VIOLATION", violations
        else:
            return "MAJOR_VIOLATION", violations

    def _get_bull_argument(
        self,
        symbol: str,
        technical_report: str,
        sentiment_report: str,
        order_flow_report: str,      # MTF v2.1
        derivatives_report: str,     # MTF v2.1
        orderbook_report: str,       # v3.7
        sr_zones_report: str,        # v3.8
        history: str,
        bear_argument: str,
        trace_label: str = "Bull",
        past_memories: str = "",     # v5.9: Past trade patterns
        adx_1d: float = 30.0,       # v18.1: For strong-trend role condition
        dimensional_scores: str = "",  # v28.0: Pre-computed dimensional scores
    ) -> str:
        """
        Generate bull analyst's argument.

        Borrowed from: TradingAgents/agents/researchers/bull_researcher.py
        TradingAgents v3.3: Indicator definitions in system prompt (like TradingAgents)
        v3.8: Added S/R zones report
        v5.9: Added past_memories for pattern learning
        v18.1: Added adx_1d for strong-trend role conditioning
        v28.0: Added dimensional_scores for pre-computed anchoring
        """
        # v24.0: Strong-trend user prompt alignment (match system prompt role)
        # In ADX>=40, system prompt says "don't argue direction, assess trend health"
        # so user prompt must also frame tasks as trend health / entry timing, not LONG/SHORT
        if adx_1d >= 40:
            task_step2_3 = f"""**第二步：评估趋势健康度 (强趋势模式 — 方向已确立)**
分析顺序: 1D 趋势 → 4H 动量 → 30M 执行层 → 衍生品/订单流
方向已由 ADX={adx_1d:.0f}>40 确立。评估当前趋势是否仍然强劲:
- ADX 是仍在上升还是已见顶回落？DI 差距在扩大还是收窄？
- 成交量/CVD 是否确认趋势方向？订单流是否支持延续？
- 趋势跟随入场在当前价位是否合理？还是已追涨/追跌太远？
如果历史数据中有类似 ADX>40 条件的案例，可以引用。

**第三步：构建入场论点**
提出 2-3 个支持"趋势仍然健康、当前值得入场"的理由。
如果 Bear 认为趋势衰竭或入场时机不好，用数据反驳。"""
            audit_evidence_label = "为什么表明趋势仍然健康/值得入场"
            step5_question = "什么情况下你对趋势健康的判断会被推翻？（例如 ADX 跌破某值、DI 交叉、成交量背离）"
        else:
            task_step2_3 = """**第二步：从宏观到微观逐层识别看多信号 (v18 Item 13)**
分析顺序: 1D 趋势 → 4H 动量 → 30M 执行层 → 衍生品/订单流
从上方数据中找出具体的 BULLISH 信号，附带数值。
必须使用当前 regime 对应的解读规则 (例如 RSI 30 在趋势市场 vs 震荡市场含义不同)。
如果历史数据中有类似条件的成功做多案例，可以引用。

**第三步：构建论点**
提出 2-3 个有说服力的做多理由。
如果 Bear 已有论点，用数据反驳。"""
            audit_evidence_label = "为什么支持做多"
            step5_question = "什么情况下你的看多论点会被推翻？"

        # User prompt: v18 Item 5d section numbering [N/7] + v18 Item 13 macro-to-micro
        # v28.0: Dimensional scores at TOP for primacy anchoring, then reordered sections
        # (Derivatives promoted to [2/7] for importance, Orderbook demoted to [6/7])
        prompt = f"""{dimensional_scores}
## [1/7] 📊 MARKET DATA (Technical Indicators)
{technical_report}

## [2/7] 📉 DERIVATIVES (Funding / OI / Liquidations)
{derivatives_report}

## [3/7] 📈 ORDER FLOW (Taker Data)
{order_flow_report}

## [4/7] 🔑 SUPPORT / RESISTANCE ZONES
{sr_zones_report}

## [5/7] 💬 SENTIMENT (Long/Short Ratio)
{sentiment_report}

## [6/7] 📖 ORDER BOOK DEPTH
{orderbook_report}

## 🗣️ DEBATE CONTEXT
Previous Debate:
{history if history else "This is the opening argument."}

Last Bear Argument:
{bear_argument if bear_argument else ("No bear argument yet - make your opening case." if not history else "See BEAR ANALYST in the latest round above — directly rebut that argument.")}

## [7/7] 📚 PAST TRADE PATTERNS
{past_memories if past_memories else "No historical data yet."}

## 🎯 【分析任务 — 请严格按步骤执行】

**DATA SCAN (先扫描 7 个数据源，每个写一句方向信号):**
1.Tech: [方向] 2.Deriv: [方向] 3.Flow: [方向] 4.S/R: [方向] 5.Sent: [方向] 6.Book: [方向] 7.Mem: [有无相关]
然后执行 Signal Audit。

**第〇步：审视 DIMENSIONAL SCORES**
报告顶部的预计算评分是否与你的独立分析一致？如有分歧，说明原因。

**第一步：判断 MARKET REGIME**
用指标手册判断当前市场状态 (TRENDING / RANGING / SQUEEZE)
— 这决定了后续所有指标的解读方式。

{task_step2_3}

**第四步：评估入场条件**
入场价为当前市场价 — 基于 S/R zones 和市场结构评估入场质量。
⚠️ 必须检查 Extension Ratio:
   - ADX>40 强趋势中: OVEREXTENDED (>3 ATR) 在强趋势中常见且可持续。评估趋势是否仍有动能（ADX 上升？DI 扩张？），
     如果趋势健康，extension 不是拒绝入场的理由，但可建议等回调或缩小仓位。仅 EXTREME (>5 ATR) 需真正警惕。
   - ADX<40 非强趋势: OVEREXTENDED 是实质风险 — 你必须承认追涨风险并解释为什么仍值得入场。

**第五步：陈述失效条件**
{step5_question}

**第六步：Signal Audit (MANDATORY — 必须在论证之前完成)**
根据数据中标注的 reliability tier，对你引用的指标进行分类：

我在此次分析中使用的 PRIMARY 证据 (仅来自 🟢 HIGH reliability 区):
1. [指标名] = [数值] — {audit_evidence_label}
2. [指标名] = [数值] — {audit_evidence_label}

Extension Ratio 评估:
- SMA20 Extension: [值] ATR → [NORMAL/EXTENDED/OVEREXTENDED/EXTREME]
- 当前 ADX regime: [ADX 值] → 强趋势(>40)时 extension 降权 / 非强趋势时 extension 是实质风险
- 对入场的影响: [追涨风险评估]

Volatility Regime 评估:
- ATR Volatility: [regime] ([percentile]th pctl) → LOW=收紧止损有利 / HIGH/EXTREME=whipsaw 风险，评估趋势是否足够强以克服波动

我明确不采信的 SKIP 信号 (来自 ❌ UNRELIABLE 区):
1. [指标名] — 在当前 regime 下不可靠，因为 [原因]

⚠️ 规则: 🟢 PRIMARY EVIDENCE 区的指标才能作为核心论据。❌ UNRELIABLE 区的指标必须明确排除。

**数据覆盖确认** (在论证中至少引用以下每个类别一次):
□ 技术指标 (趋势/动量/背离检测)
□ 30M 入场时机 (ADX/DI 方向 + MACD Histogram 方向 — 是否与论证方向一致？)
□ 订单流 (CVD 趋势 + 买卖比 + CVD-Price 交叉)
□ 衍生品 (资金费率 + OI象限 + 清算偏向 + Top Traders 持仓)
□ 订单簿 (OBI + 压力梯度 + 深度分布)
□ 情绪 (Binance 多空比)
□ S/R (距离 + 可靠性)
□ Extension Ratio (价格偏离度)
□ Volatility Regime (波动率环境)
"""
        # v5.5: R2+ enhancement — force new arguments and direct rebuttals
        # v6.4: bear_argument may be empty for R2+ (it's in history instead),
        # so check history for "ROUND" marker to detect R2+
        # v15.0: Strengthened structural enforcement (P1 debate quality)
        if history and "ROUND" in history:
            # v24.0: Weak link label matches strong-trend role
            r2_weak_link = (
                "你的趋势健康评估中，哪一条证据最弱？为什么你仍然认为值得入场？"
                if adx_1d >= 40 else
                "你的看多论点中，哪一条证据最弱？为什么你仍然维持看多？"
            )
            prompt += f"""
⚠️ 【第二轮辩论规则 — 严格遵守】

🚫 **输出格式**: R2 只输出以下 3 个 mandatory 部分。不要重复 R1 的 DATA SCAN、Signal Audit、
第一步~第五步等内容 — 这些已在 R1 中完成，Judge 可以看到。重复 = 浪费 token + 论证无效。

**结构要求** (每条都必须出现在你的回复中):

1. 🎯 **直接反驳** (MANDATORY): 引用 Bear 最强论点的原文，逐条反驳。
   格式: "Bear 认为 [原文]。这是错误的，因为 [数据反驳]。"
   如果你无法反驳 Bear 的某个论点，必须明确承认: "Bear 在 [X] 点上正确。"

2. 📊 **新证据** (MANDATORY): 提出至少 1 个第一轮完全未提及的数据点。
   必须引用具体数值，不接受定性描述。
   ❌ "成交量在增加" → ✅ "4H CVD 从 -2.3M 反转至 +1.1M，多头吸筹信号"

3. ⚖️ **最弱环节坦白** (MANDATORY): {r2_weak_link}
   这帮助 Judge 评估你的论证质量。

最后附上简短的 **最终建议与总结** (2-3 句话) 和 **数据覆盖确认** 清单。

❌ 禁止: 重复第一轮的完整分析框架、模糊定性描述、忽略对手强项
⚠️ 不得重复 R1 已使用的论据。每个论点必须引用 R1 中未出现的数据或分析角度。违反此规则 = 论证无效。
"""

        # v24.0: Final delivery instruction matches strong-trend role
        final_delivery = (
            "请先完成 Signal Audit，然后用 2-3 段落交付你的趋势健康评估和入场建议："
            if adx_1d >= 40 else
            "请先完成 Signal Audit，然后用 2-3 段落交付你的论点："
        )
        prompt += f"\n{final_delivery}"

        # System prompt: Role + Indicator manual (v3.25: regime-aware)
        # v3.28: Chinese instructions for better DeepSeek instruction-following
        # v18.1: Strong-trend role conditioning — focus on entry timing when ADX>40
        if adx_1d >= 40:
            role_desc = f"""你是 {symbol} 的专业多头分析师 (Bull Analyst)。
当前处于 **强趋势市场** (ADX={adx_1d:.0f}>40)。在强趋势中，方向通常已经明确。
你的职责不是论证方向，而是：
1. 确认趋势是否仍然健康（ADX 还在上升？DI 差距在扩大？）
2. 寻找最优入场时机（回调到哪个水平是好的入场点？）
3. 评估当前价格是否为好的入场价（还是已经追涨/追跌太远？）"""
        else:
            # v18 Item 13: Add macro-to-micro ordering for ADX<40 (matches Bear's existing structure)
            role_desc = f"""你是 {symbol} 的专业多头分析师 (Bull Analyst)。
你的职责是分析原始市场数据，构建最强有力的做多论据。

🔍 【分析优先级 — 从宏观到微观】
你必须按此顺序分析数据，而不是从 30M 开始：
1. **1D 宏观趋势** — SMA_200 方向、ADX 趋势强度、MACD 趋势
2. **4H 中期动量** — RSI 位置、MACD 交叉、BB 位置
3. **30M 微观执行** — 仅用于入场时机判断

⚠️ 层级权重取决于 ADX 判定的市场环境:
- ADX > 40 (强趋势): 1D 趋势层主导，逆势信号需极强确认
- 25 < ADX < 40: 1D 趋势层重要但非绝对
- ADX < 20 (震荡市): 30M 关键水平层权重最高，均值回归信号有效"""

        # v25.0: INDICATOR_DEFINITIONS first for DeepSeek prefix caching
        # All 5 agents share this prefix → cache hit on 2nd+ call
        system_prompt = f"""{INDICATOR_DEFINITIONS}

{role_desc}

【关键规则 — 必须遵守】
⚠️ 你必须先判断 market regime (指标手册第一步)，然后用对应 regime 的规则解读所有指标。
⚠️ 在趋势市场使用震荡市场逻辑 (或反之) 是致命错误。
⚠️ 只基于数据中标注的 reliability tier 选择证据：🟢 PRIMARY EVIDENCE 区的指标才能作为核心论据。
⚠️ 只基于数据中的证据，不做无根据的假设。
🔴 语言强制规则: 所有文本输出必须用**中英混输** (中文为主体，技术术语保留英文)。纯英文输出将被系统拒绝。最终以 Markdown 格式输出结果。"""

        # Store prompts for diagnosis (v11.4)
        self.last_prompts["bull"] = {
            "system": system_prompt,
            "user": prompt,
        }

        result = self._call_api_with_retry([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ], trace_label=trace_label)

        # v18 Item 20: Post-hoc direction compliance audit
        if result:
            audit_result, violations = self._audit_direction_compliance(
                agent_role='bull', argument_text=result, adx_1d=adx_1d
            )
            if audit_result != "COMPLIANT":
                self.logger.warning(
                    f"⚠️ BULL direction compliance: {audit_result} — {violations}"
                )
                self._compliance_violations += 1
                result += (
                    f"\n\n⚠️ COMPLIANCE NOTE: Previous bull argument contained "
                    f"{len(violations)} layer-role violation(s): "
                    f"{'; '.join(violations)}. "
                    f"30M/执行层 data should only support entry timing arguments, "
                    f"not direction claims. The counterparty may challenge this."
                )
        return result

    def _get_bear_argument(
        self,
        symbol: str,
        technical_report: str,
        sentiment_report: str,
        order_flow_report: str,      # MTF v2.1
        derivatives_report: str,     # MTF v2.1
        orderbook_report: str,       # v3.7
        sr_zones_report: str,        # v3.8
        history: str,
        bull_argument: str,
        trace_label: str = "Bear",
        past_memories: str = "",     # v5.9: Past trade patterns
        adx_1d: float = 30.0,       # v18.1: For tier-aware system prompt
        dimensional_scores: str = "",  # v28.0: Pre-computed dimensional scores
    ) -> str:
        """
        Generate bear analyst's argument.

        Borrowed from: TradingAgents/agents/researchers/bear_researcher.py
        TradingAgents v3.3: AI interprets raw data using indicator definitions
        v3.8: Added S/R zones report
        v5.9: Added past_memories for pattern learning
        v18.1: Added adx_1d parameter
        v28.0: Added dimensional_scores for pre-computed anchoring
        """
        # v24.0: Strong-trend user prompt alignment (match system prompt role)
        if adx_1d >= 40:
            bear_step2_3 = f"""**第二步：识别趋势衰竭信号和入场风险 (强趋势模式)**
分析顺序: 1D 趋势 → 4H 动量 → 30M 执行层 → 衍生品/订单流
方向已由 ADX={adx_1d:.0f}>40 确立。评估趋势是否正在减弱或入场时机不佳:
- ADX 是否已见顶回落？DI 差距是否在收窄？
- 价格是否已过度延伸（追涨/追跌太远）？
- 成交量/CVD 是否出现与趋势方向的背离？
- 订单流或衍生品中是否有动能衰竭信号？
如果历史数据中有类似 ADX>40 条件下趋势反转或入场失败的案例，可以引用。

**第三步：评估入场风险**
提出 2-3 个"趋势可能衰竭"或"当前不是最佳入场时机"的理由。
用数据反驳 Bull 对趋势健康度的评估。"""
            bear_audit_label = "为什么表明趋势衰竭/入场风险高"
            bear_step5_question = "什么情况下你对趋势衰竭的判断会被推翻？（例如 ADX 重新上升、新的成交量确认趋势、DI 差距扩大）"
        else:
            bear_step2_3 = """**第二步：识别看空信号和风险**
从上方数据中找出具体的 BEARISH 信号或风险，附带数值。
必须使用当前 regime 对应的解读规则 (例如 "support" 在趋势市场 vs 震荡市场含义不同)。
如果历史数据中有类似条件的失败做多案例，可以引用作为风险警告。

**第三步：构建论点**
提出 2-3 个反对做多 (或支持做空) 的有力理由。
用数据反驳 Bull 的论点。"""
            bear_audit_label = "为什么支持看空/风险"
            bear_step5_question = "什么情况下你的看空论点会被推翻？"

        # User prompt: v18 Item 5d section numbering [N/7]
        # v28.0: Dimensional scores at TOP + reordered sections (Derivatives promoted, Orderbook demoted)
        prompt = f"""{dimensional_scores}
## [1/7] 📊 MARKET DATA (Technical Indicators)
{technical_report}

## [2/7] 📉 DERIVATIVES (Funding / OI / Liquidations)
{derivatives_report}

## [3/7] 📈 ORDER FLOW (Taker Data)
{order_flow_report}

## [4/7] 🔑 SUPPORT / RESISTANCE ZONES
{sr_zones_report}

## [5/7] 💬 SENTIMENT (Long/Short Ratio)
{sentiment_report}

## [6/7] 📖 ORDER BOOK DEPTH
{orderbook_report}

## 🗣️ DEBATE CONTEXT
Previous Debate:
{history}

Last Bull Argument:
{bull_argument}

## [7/7] 📚 PAST TRADE PATTERNS
{past_memories if past_memories else "No historical data yet."}

## 🎯 【分析任务 — 请严格按步骤执行】

**DATA SCAN (先扫描 7 个数据源，每个写一句方向信号):**
1.Tech: [方向] 2.Deriv: [方向] 3.Flow: [方向] 4.S/R: [方向] 5.Sent: [方向] 6.Book: [方向] 7.Mem: [有无相关]
然后执行 Signal Audit。

**第〇步：审视 DIMENSIONAL SCORES**
报告顶部的预计算评分是否与你的独立分析一致？如有分歧，说明原因。

**第一步：判断 MARKET REGIME**
用指标手册判断当前市场状态 (TRENDING / RANGING / SQUEEZE)
— 这决定了后续所有指标的解读方式。

{bear_step2_3}

**第四步：评估入场条件**
入场价为当前市场价 — 基于 S/R zones 和市场结构评估入场质量。
⚠️ 必须检查 Extension Ratio:
   - ADX>40 强趋势中: OVEREXTENDED (>3 ATR) 在强趋势中常见。仅作为入场时机风险的辅助参考，
     不能作为看空的核心论据。强趋势可以持续 OVEREXTENDED 很多根 K 线。仅 EXTREME (>5 ATR) 可作为实质风险论据。
   - ADX<40 非强趋势: OVEREXTENDED 是你的强力论据 — 追涨入场的回调风险很高。

**第五步：陈述失效条件**
{bear_step5_question}

**第六步：Signal Audit (MANDATORY — 必须在论证之前完成)**
根据数据中标注的 reliability tier，对你引用的指标进行分类：

我在此次分析中使用的 PRIMARY 证据 (仅来自 🟢 HIGH reliability 区):
1. [指标名] = [数值] — {bear_audit_label}
2. [指标名] = [数值] — {bear_audit_label}

Extension Ratio 评估:
- SMA20 Extension: [值] ATR → [NORMAL/EXTENDED/OVEREXTENDED/EXTREME]
- 当前 ADX regime: [ADX 值] → 强趋势(>40)时 extension 降权 / 非强趋势时 extension 权重高
- 对 Bull 论点的影响: [追涨风险/回调概率评估]

Volatility Regime 评估:
- ATR Volatility: [regime] ([percentile]th pctl) → HIGH/EXTREME=下行风险放大，已有回撤论据权重更高

我明确不采信的 SKIP 信号 (来自 ❌ UNRELIABLE 区):
1. [指标名] — 在当前 regime 下不可靠，因为 [原因]

⚠️ 规则: 🟢 PRIMARY EVIDENCE 区的指标才能作为核心论据。❌ UNRELIABLE 区的指标必须明确排除。

**数据覆盖确认** (在论证中至少引用以下每个类别一次):
□ 技术指标 (趋势/动量/背离检测)
□ 30M 入场时机 (ADX/DI 方向 + MACD Histogram 方向 — 是否与论证方向一致？)
□ 订单流 (CVD 趋势 + 买卖比 + CVD-Price 交叉)
□ 衍生品 (资金费率 + OI象限 + 清算偏向 + Top Traders 持仓)
□ 订单簿 (OBI + 压力梯度 + 深度分布)
□ 情绪 (Binance 多空比)
□ S/R (距离 + 可靠性)
□ Extension Ratio (价格偏离度)
□ Volatility Regime (波动率环境)
"""
        # v5.5: R2+ enhancement — force new arguments and direct rebuttals
        # v6.4: Align with Bull side — detect R2+ via history marker, not bull_argument param.
        # bull_argument is passed separately in the prompt above, so no need to re-check it here.
        # v15.0: Strengthened structural enforcement (P1 debate quality)
        if history and "ROUND" in history:
            # v24.0: Weak link label matches strong-trend role
            bear_r2_weak_link = (
                "你的风险评估中，哪一条证据最弱？为什么你仍然认为应该等待更好的入场时机？"
                if adx_1d >= 40 else
                "你的看空论点中，哪一条证据最弱？为什么你仍然维持看空？"
            )
            prompt += f"""
⚠️ 【第二轮辩论规则 — 严格遵守】

🚫 **输出格式**: R2 只输出以下 3 个 mandatory 部分。不要重复 R1 的 DATA SCAN、Signal Audit、
第一步~第五步等内容 — 这些已在 R1 中完成，Judge 可以看到。重复 = 浪费 token + 论证无效。

**结构要求** (每条都必须出现在你的回复中):

1. 🎯 **直接反驳** (MANDATORY): 引用 Bull 最强论点的原文，逐条反驳。
   格式: "Bull 认为 [原文]。这是错误的，因为 [数据反驳]。"
   如果你无法反驳 Bull 的某个论点，必须明确承认: "Bull 在 [X] 点上正确。"

2. 📊 **新证据** (MANDATORY): 提出至少 1 个第一轮完全未提及的数据点。
   必须引用具体数值，不接受定性描述。
   ❌ "资金费率偏空" → ✅ "Funding Rate = -0.00032 (前值 +0.00015)，空头支付增加"

3. ⚖️ **最弱环节坦白** (MANDATORY): {bear_r2_weak_link}
   这帮助 Judge 评估你的论证质量。

最后附上简短的 **最终建议与总结** (2-3 句话) 和 **数据覆盖确认** 清单。

❌ 禁止: 重复第一轮的完整分析框架、模糊定性描述、忽略对手强项
⚠️ 不得重复 R1 已使用的论据。每个论点必须引用 R1 中未出现的数据或分析角度。违反此规则 = 论证无效。
"""

        # v24.0: Final delivery instruction matches strong-trend role
        bear_final_delivery = (
            "请先完成 Signal Audit，然后用 2-3 段落交付你的风险评估和入场时机建议："
            if adx_1d >= 40 else
            "请先完成 Signal Audit，然后用 2-3 段落交付你的论点："
        )
        prompt += f"\n{bear_final_delivery}"

        # System prompt: Role + Indicator manual (v3.25: regime-aware)
        # v3.28: Chinese instructions for better DeepSeek instruction-following
        # v5.6: Adversarial mandate — structurally enforce opposition to Bull
        # v18.1: Strong-trend role conditioning — focus on exhaustion/timing risks when ADX>40
        if adx_1d >= 40:
            role_desc = f"""你是 {symbol} 的专业空头分析师 (Bear Analyst) — 你的角色是辩论中的 **反方**。
当前处于 **强趋势市场** (ADX={adx_1d:.0f}>40)。在强趋势中，方向通常已经明确。
你的职责不是构建完整的逆势论据，而是：
1. 评估趋势是否正在衰竭（ADX 是否见顶回落？DI 差距是否在收窄？）
2. 识别入场时机风险（当前价格是否已过度延伸？是否追涨/追跌太远？）
3. 评估潜在回调深度和风控风险（如果回调，到哪个水平才合理？）"""
        else:
            role_desc = f"""你是 {symbol} 的专业空头分析师 (Bear Analyst) — 你的角色是辩论中的 **反方**。

🚨 【核心使命 — 你必须与 Bull 对立】
你的存在价值就是找出 Bull 看不到或故意忽视的风险。
- 如果 Bull 说 "做多"，你必须解释为什么做多是危险的
- 如果 Bull 引用某个指标支持多头，你必须找到该指标的弱点或相反解读
- 你**禁止**得出与 Bull 相同的方向结论
- 如果你真的找不到反对 Bull 的理由，你必须解释为什么当前不是好的入场时机 (timing risk)"""

        # v25.0: INDICATOR_DEFINITIONS first for DeepSeek prefix caching
        system_prompt = f"""{INDICATOR_DEFINITIONS}

{role_desc}

🔍 【分析优先级 — 从宏观到微观】
你必须按此顺序分析数据，而不是从 30M 开始：
1. **1D 宏观趋势** — SMA_200 方向、ADX 趋势强度、MACD 趋势
2. **4H 中期动量** — RSI 位置、MACD 交叉、BB 位置
3. **30M 微观执行** — 仅用于入场时机判断

⚠️ 层级权重取决于 ADX 判定的市场环境:
- ADX > 40 (强趋势): 1D 趋势层主导，逆势信号需极强确认
- 25 < ADX < 40: 1D 趋势层重要但非绝对
- ADX < 20 (震荡市): 30M 关键水平层权重最高，均值回归信号有效

【关键规则 — 必须遵守】
⚠️ 你必须先判断 market regime (指标手册第一步)，然后用对应 regime 的规则解读所有指标。
⚠️ 在趋势市场使用震荡市场逻辑 (或反之) 是致命错误。
⚠️ 只基于数据中标注的 reliability tier 选择证据：🟢 PRIMARY EVIDENCE 区的指标才能作为核心论据。
⚠️ 聚焦于 Bull 论点中最薄弱的环节 — 用数据拆解它。
🔴 语言强制规则: 所有文本输出必须用**中英混输** (中文为主体，技术术语保留英文)。纯英文输出将被系统拒绝。最终以 Markdown 格式输出结果。"""

        # Store prompts for diagnosis (v11.4)
        self.last_prompts["bear"] = {
            "system": system_prompt,
            "user": prompt,
        }

        result = self._call_api_with_retry([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ], trace_label=trace_label)

        # v18 Item 20: Post-hoc direction compliance audit
        if result:
            audit_result, violations = self._audit_direction_compliance(
                agent_role='bear', argument_text=result, adx_1d=adx_1d
            )
            if audit_result != "COMPLIANT":
                self.logger.warning(
                    f"⚠️ BEAR direction compliance: {audit_result} — {violations}"
                )
                self._compliance_violations += 1
                result += (
                    f"\n\n⚠️ COMPLIANCE NOTE: Previous bear argument contained "
                    f"{len(violations)} layer-role violation(s): "
                    f"{'; '.join(violations)}. "
                    f"30M/执行层 data should only support entry timing arguments, "
                    f"not direction claims. The counterparty may challenge this."
                )

        return result

    def _get_judge_decision(
        self,
        debate_history: str,
        past_memories: str,
        key_metrics: str = "",
        adx_1d: float = 30.0,  # v5.13: For dynamic matrix trimming
        dimensional_scores: str = "",  # v28.0: Pre-computed dimensional scores
    ) -> Dict[str, Any]:
        """
        Judge evaluates the debate and makes decision.

        Borrowed from: TradingAgents/agents/managers/research_manager.py
        Simplified v3.0: Let AI autonomously evaluate without hardcoded rules
        v3.9: Removed duplicate S/R check from prompt (handled by _evaluate_risk)
        v3.10: Aligned with TradingAgents original design (rationale + strategic_actions)
        v3.23: Added key_metrics for independent sanity checking
        v28.0: Added dimensional_scores for pre-computed anchoring
        """
        prompt = f"""{dimensional_scores}
你是投资组合经理兼辩论裁判。请批判性地评估本轮辩论，做出明确的交易决策：
支持空头分析师、支持多头分析师、或仅在有强有力理由时选择 HOLD。

## 🗣️ DEBATE TRANSCRIPT
{debate_history}

## 📊 KEY MARKET METRICS (用于独立验证 — 检查分析师是否遗漏了什么)
{key_metrics if key_metrics else "N/A"}

## 📚 PAST REFLECTIONS ON MISTAKES
{past_memories if past_memories else "No past data - this is a fresh start."}

---

## ⚠️ 辩论质量评估 (MANDATORY — 在做决策之前先完成)

在分析辩论内容前，先评估辩论质量:

1. **共识度检查**: Bull 和 Bear 是否实质上同意？如果两者对方向的结论一致，
   这是 RED FLAG — 说明辩论未充分探索风险。在这种情况下，你应该:
   - 降低信心一级 (HIGH → MEDIUM, MEDIUM → LOW)
   - 在 rationale 中注明 "⚠️ 辩论质量警告: Bull/Bear 过度共识"

2. **证据重叠度**: 如果 Bull 和 Bear 在 R2 引用了相同的数据点且得出相同结论，
   说明辩论未产生信息增益。标记为 "低信息增益辩论"。

3. **反驳质量**: 如果 R2 中没有出现对 R1 论点的直接反驳（引用+反驳），
   说明辩论流于形式。降低相关方论证的权重。

## 🎯 【决策任务 — 请严格按步骤执行】

### STEP 1: 独立验证 MARKET REGIME
用指标手册和 Key Metrics 独立判断当前 regime (TRENDING / RANGING / SQUEEZE)。
然后评估：双方分析师是否都使用了正确的 regime 解读逻辑？
⚠️ 在趋势市场使用震荡逻辑 (或反之) = 结论不可信。

### STEP 2: Confluence 多层对齐度评估 (必须填入 JSON 的 confluence 字段)
逐层评估每一层的方向倾向，填入 JSON 输出的 confluence 对象中：

| 层级 | 评估内容 | 填入字段 |
|------|---------|---------|
| 趋势层 (1D) | SMA200 位置, ADX/DI 方向, MACD | confluence.trend_1d |
| 动量层 (4H) | RSI, MACD, ADX, CVD | confluence.momentum_4h |
| 执行层 (30M) | 入场时机, S/R zone, BB, Order Book | confluence.levels_30m |
| 衍生品数据 | Funding, OI, Liquidations | confluence.derivatives |

每层判定为 BULLISH / BEARISH / NEUTRAL，附简要理由。

⚠️ 层级权重取决于 1D ADX 判定的市场环境 (先完成 STEP 1 再评估):
- 强趋势 (ADX > 40): 趋势层主导，逆势信号需其他 3 层全部确认
- 弱趋势 (25 < ADX < 40): 趋势层重要但非绝对，2 层逆势确认即可考虑
- 震荡市 (ADX < 20): 关键水平层权重最高，均值回归信号有效，趋势层降权
- 挤压 (ADX < 20 + BB Width 收窄): 等待突破方向，不预判

对齐度规则 (基于 aligned_layers 计数):
- 3-4 层一致 → HIGH confidence 交易
- 2 层一致 → MEDIUM confidence 交易
- 0-1 层一致 → 通常 HOLD，但如果 regime_transition 激活且领先指标 (order_flow)
  方向明确，可以 LOW confidence 交易 (小仓位探索性入场)

⚠️ 执行层入场时机降级 (30M 逆向规则):
如果 30M 技术数据满足以下任一条件, confidence 不得超过 MEDIUM, 即使宏观 (1D/4H) 3-4 层一致:
  条件 A: ADX>35 且 DI 方向与交易相反 (如做空时 DI+>DI- = 强上涨趋势)
  条件 B: MACD Histogram 方向与交易相反 (如做空时 histogram > 0 = 上涨动能)
原因: 30M 是入场执行的时间框架, 反向短期动量/动能会推高被止损概率。
此规则不影响方向判断 — 方向仍由 1D/4H 决定, 但信心降级反映入场时机差。

### STEP 3: 总结双方核心论据
聚焦最有说服力的证据，不要罗列所有观点。

### STEP 4: 做出明确决策
- 你的建议 — LONG、SHORT 或 HOLD — 必须清晰可执行
- ‼️ 不要因为双方都有道理就默认 HOLD — 选择证据更强的一方
- 参考过去的失误教训，避免重复犯错
- confidence 通常与 aligned_layers 一致，但 TRANSITIONING regime 中允许 LOW confidence
  override (受执行层降级约束)
- (v23.0: 入场时机质量由独立的 Entry Timing Agent 评估，Judge 不再输出 entry_quality)

## 📤 OUTPUT FORMAT (只输出 JSON，不要其他文字):
{{
    "confluence": {{
        "trend_1d": "BULLISH|BEARISH|NEUTRAL — 简要理由 (如: ADX=55 DI->DI+, 强下跌趋势)",
        "momentum_4h": "BULLISH|BEARISH|NEUTRAL — 简要理由 (如: RSI=60 偏多, MACD 金叉)",
        "levels_30m": "BULLISH|BEARISH|NEUTRAL — 简要理由 (如: 价格在 S1 支撑上方, BB 下轨触及)",
        "derivatives": "BULLISH|BEARISH|NEUTRAL — 简要理由 (如: FR 偏多, OI 下降)",
        "aligned_layers": 0
    }},
    "decision": "LONG|SHORT|HOLD",
    "winning_side": "BULL|BEAR|TIE",
    "confidence": "HIGH|MEDIUM|LOW",
    "rationale": "<2-4 句中英混输: 基于 confluence 分析的决策理由，技术术语保留英文>",
    "strategic_actions": ["Concrete step 1", "Concrete step 2"],
    "acknowledged_risks": ["risk1", "risk2"]
}}"""

        # v3.28: Chinese instructions + few-shot + confluence matrix for better DeepSeek performance
        # v5.13: Dynamic matrix trimming based on 1D ADX regime
        # v25.0: INDICATOR_DEFINITIONS + trimmed_matrix first for DeepSeek prefix caching
        # Judge/Entry Timing/Risk Manager share this longer prefix → cache hit on 2nd+ call
        trimmed_matrix = _trim_matrix_for_regime(adx_1d)
        system_prompt = f"""{INDICATOR_DEFINITIONS}

{trimmed_matrix}

你是投资组合经理兼辩论裁判 (Portfolio Manager / Judge)。
批判性地评估辩论内容，做出果断的交易建议。选择证据更强的一方。从过去的错误中学习。

【关键规则 — 必须遵守】
⚠️ 用指标手册独立验证分析师是否使用了正确的 regime 解读。
⚠️ 参考信号置信度矩阵 (SIGNAL CONFIDENCE MATRIX) 量化评估每个信号在当前 regime 下的可靠性。
🔴 语言强制规则: 所有文本输出必须用**中英混输** (中文为主体，技术术语保留英文)。纯英文输出将被系统拒绝。最终以 JSON 格式输出结果。
⚠️ 不要因为双方都有道理就默认 HOLD — 这是最常见的错误。

【正确决策示例 — Few-shot】

示例 1: 趋势一致 → 选择顺势方
情况: 1D ADX=33 上涨趋势, Bull 引用趋势+动量, Bear 引用 RSI 超买
分析: ADX>25 = TRENDING。Bear 用震荡市场逻辑 (RSI 70 = 超买) 在趋势市场中是错误的。
结果: {{"confluence":{{"trend_1d":"BULLISH — ADX=33 DI+>DI-, 明确上涨趋势","momentum_4h":"BULLISH — RSI=65 趋势范围内, MACD 正值","levels_30m":"BULLISH — 价格在 SMA20 上方, BB 上半部","derivatives":"NEUTRAL — FR 正常, OI 稳定","aligned_layers":3}},"decision":"LONG","winning_side":"BULL","confidence":"HIGH","rationale":"3 层一致看多，趋势层确认上涨。Bear 用震荡逻辑解读 RSI，在趋势市场中无效。","strategic_actions":["顺势做多，目标下一阻力位"],"acknowledged_risks":["ADX 可能见顶回落"]}}

示例 2: 强趋势中逆势信号 (ADX>40 → 趋势层主导)
情况: 1D 强下跌趋势 (ADX=45), 4H 出现 MACD 金叉, Bull 认为反转
分析: ADX=45 > 40 = 强趋势，趋势层主导。4H MACD 金叉在强下跌中可能是反弹而非反转。
结果: {{"confluence":{{"trend_1d":"BEARISH — ADX=45 DI->DI+, 强下跌趋势","momentum_4h":"BULLISH — MACD 金叉, RSI 回升至 55","levels_30m":"NEUTRAL — 价格在 range 中间","derivatives":"BEARISH — FR 负值, OI 下降","aligned_layers":2}},"decision":"SHORT","winning_side":"BEAR","confidence":"MEDIUM","rationale":"趋势层(1D)看空 + 衍生品看空 = 2 层一致。4H MACD 金叉在强下跌趋势中有 74-97% 假信号率，不足以推翻 1D。","strategic_actions":["等待反弹至阻力位后做空"],"acknowledged_risks":["4H 动量转多可能形成更大反弹"]}}

示例 3: 真正需要 HOLD 的情况
情况: ADX=12 (RANGING), 价格在 range 中间, 两方都没有强证据
分析: 震荡市场 + 无明确方向 + 无关键水平触及。等待价格到达 range 边缘。
结果: {{"confluence":{{"trend_1d":"NEUTRAL — ADX=12 无趋势","momentum_4h":"NEUTRAL — RSI=50 中性","levels_30m":"NEUTRAL — 价格在 range 中间，远离 S/R","derivatives":"NEUTRAL — FR 接近零, OI 无变化","aligned_layers":0}},"decision":"HOLD","winning_side":"TIE","confidence":"LOW","rationale":"0 层有明确方向，所有层级均为中性。等待价格触及 range 边缘再决策。","strategic_actions":["等待价格到达 range 边缘"],"acknowledged_risks":["可能错过突破"]}}

示例 4: 震荡市 → 关键水平层主导 (均值回归)
情况: 1D ADX=15 (RANGING), 价格触及 BB 下轨 + S1 支撑, RSI=28 超卖, 订单簿买墙
分析: ADX<20 = 震荡市，关键水平层权重最高。价格在强支撑 + BB 下轨 + RSI 超卖 = 均值回归信号。
      虽然 1D 趋势不明确，但震荡市中这正是关键水平层发挥作用的时候。
结果: {{"confluence":{{"trend_1d":"NEUTRAL — ADX=15 无趋势，SMA200 持平","momentum_4h":"BULLISH — RSI=32 超卖反弹, MACD 柱状图收敛","levels_30m":"BULLISH — 价格触及 S1 支撑 + BB 下轨, OBI=+0.8 买墙","derivatives":"NEUTRAL — FR 接近零, OI 稳定","aligned_layers":2}},"decision":"LONG","winning_side":"BULL","confidence":"MEDIUM","rationale":"ADX=15 震荡市中，关键水平层权重最高。价格触及强支撑 + BB 下轨 + RSI 超卖，均值回归概率高。趋势层中性不构成阻碍。","strategic_actions":["在 S1 支撑做多，目标 BB 中轨"],"acknowledged_risks":["若支撑被跌破，震荡区间可能转为下跌趋势"]}}

示例 5: 信号置信度矩阵 — 震荡市忽略 MACD，信任 S/R + RSI
情况: 1D ADX=16 (ADX<20 = 震荡), 4H MACD 金叉, 4H RSI=33 超卖, 价格触及 S1 (HIGH 强度), OBI change +0.25
分析: ADX<20 = 震荡市。查信号矩阵:
  Layer 1 (趋势): ADX<20 列全部 ≤0.7 → 趋势层 NEUTRAL (忽略)
  Layer 2 (动量): MACD 交叉在 ADX<20 = 0.3 (SKIP，几乎无效)。RSI 值在 ADX<20 = 1.2 (HIGH)。RSI=33 超卖 = 看多信号。
  Layer 3 (水平): S/R 测试在 ADX<20 = 1.3 (HIGH)。OBI change 在 ADX<20 = 1.2 (HIGH)。两个 HIGH 信号确认。
  Layer 4: FR 正常，OI 稳定 → NEUTRAL
  → 动量+水平 2 层看多，MACD 金叉被矩阵标为 SKIP 正确忽略。
结果: {{"confluence":{{"trend_1d":"NEUTRAL — ADX=16 无趋势，矩阵标记趋势层 SKIP","momentum_4h":"BULLISH — RSI=33 超卖 (矩阵 1.2=HIGH)，MACD 交叉忽略 (矩阵 0.3=SKIP)","levels_30m":"BULLISH — S1 支撑触及 (矩阵 1.3=HIGH) + OBI 变化+0.25 (矩阵 1.2=HIGH)","derivatives":"NEUTRAL — FR 正常, OI 稳定","aligned_layers":2}},"decision":"LONG","winning_side":"BULL","confidence":"MEDIUM","rationale":"ADX=16 震荡市。矩阵指导: MACD 在震荡中 SKIP (0.3)，RSI+S/R 在震荡中 HIGH (1.2-1.3)。2 层以 HIGH 信号看多。","strategic_actions":["在 S1 支撑做多，目标 BB 中轨"],"acknowledged_risks":["若 S1 被跌破，考虑出场"]}}

示例 6: 信号置信度矩阵 — 强趋势中反转信号被降级
情况: 1D ADX=48 DI->DI+ (强下跌), 4H RSI 出现看多背离, 4H MACD 仍为负值, S/R zone 被跌破, FR=+0.06%
分析: ADX=48 > 40 = 强趋势 (ADX>40 列)。查信号矩阵:
  Layer 1 (趋势): SMA200=1.3 + ADX/DI=1.2 + MACD=1.1 → 全部 HIGH，强看空
  Layer 2 (动量): RSI 背离在 ADX>40 = 0.6 (LOW)。RULE 6: 逆势信号需 2 个独立确认。RSI 背离只有 1 个 → 不足。MACD 仍为负=顺势。
  Layer 3 (水平): S/R breakout 在 ADX>40 = 1.3 (HIGH) → 确认下跌延续
  Layer 4: FR=+0.06% extreme (ADX>40 = 0.8)，适度看空。Group A: BEARISH (LOW)。
  → 趋势+水平+衍生品 3 层看空，RSI 背离被矩阵降为 LOW + RULE 6 否决。
结果: {{"confluence":{{"trend_1d":"BEARISH — ADX=48 DI->DI+, 趋势层全 HIGH (矩阵 1.1-1.3)","momentum_4h":"BEARISH — MACD 负值顺势 (矩阵 1.2)，RSI 背离被降级 (矩阵 0.6=LOW + RULE 6 需 2 确认)","levels_30m":"BEARISH — S/R 被跌破 (矩阵 1.3=HIGH，趋势延续确认)","derivatives":"BEARISH — FR +0.06% 拥挤多头 (矩阵 0.8=LOW)","aligned_layers":4}},"decision":"SHORT","winning_side":"BEAR","confidence":"HIGH","rationale":"ADX=48 强下跌。矩阵将 RSI 背离从 HIGH 降为 LOW (0.6)，加上 RULE 6 要求 2 个逆势确认但只有 1 个。4 层一致看空。","strategic_actions":["顺势做空，趋势延续概率高"],"acknowledged_risks":["RSI 背离可能预示反弹，但单一 LOW 信号不构成改变决策的理由"]}}

示例 7: 宏观一致但 30M 执行层强逆向 → confidence 降级
情况: 1D ADX=52 强下跌趋势 (DI->DI+), 4H MACD 负值 + RSI=42, 但 30M ADX=43 DI+>DI- (强上涨反弹), 30M MACD Histogram=+15.2 (正值=上涨动能), 30M RSI=63
分析: 宏观 1D+4H+衍生品 3 层一致看空, 方向正确。但 30M 执行层两项逆向信号:
      条件 A: ADX=43>35 且 DI+>DI- (与 SHORT 相反) ✓
      条件 B: MACD Histogram=+15.2>0 (上涨动能, 与 SHORT 相反) ✓
      任一条件触发 → confidence 不得超过 MEDIUM (Entry Timing Agent 将进一步评估入场时机)。
结果: {{"confluence":{{"trend_1d":"BEARISH — ADX=52 DI->DI+, 强下跌趋势","momentum_4h":"BEARISH — MACD 负值, RSI=42 偏低","levels_30m":"NEUTRAL — 30M ADX=43 DI+>DI- + MACD histogram 正值, 短期上涨动量/动能均与空头入场冲突","derivatives":"BEARISH — FR 正常, OI↑+Price↓ 新空头入场","aligned_layers":3}},"decision":"SHORT","winning_side":"BEAR","confidence":"MEDIUM","rationale":"宏观 3 层一致看空方向正确, 但 30M 执行层处于强反弹 (ADX=43 DI+领先 + MACD histogram 正值), 入场时机不佳。信心降为 MEDIUM 以反映执行层风险。","strategic_actions":["等待 30M MACD histogram 转负或 DI- 上穿 DI+ 后做空"],"acknowledged_risks":["可能错过部分趋势延续, 但避免了在 30M 动能逆向时被止损"]}}

示例 8: 趋势衰竭 → 反转做多 (ADX 回落 + 多重背离 + 强支撑 + 4H 动量翻转)
情况: 1D ADX 从 42 回落到 28 (FALLING), DI- 仍 > DI+ 但差距从 15 收窄到 5 (NARROWING)。
      _scores: trend=BEARISH(2), momentum=BULLISH(4), trend_reversal=BULLISH(active, 4/5 signals)
      4H RSI bullish divergence + MACD bullish divergence + OBV bullish divergence (三重确认)。
      价格在 $60K 强支撑位附近 (距离 < 1.5 ATR)。4H RSI=48 从 28 回升, MACD histogram 连续 5 bar 收敛。
分析: ADX 从 42 跌到 28 = 下跌动能显著衰竭 (不再是强趋势, ADX<30 时趋势信号降权)。
      三重 4H bullish divergence = 价格新低但动量不再创新低, 卖方力竭。
      DI 收敛 (差距 15→5) = 空头信念持续减弱。
      强支撑位 + 4H 动量翻多 + trend_reversal=BULLISH(active) = 反转条件成熟。
      虽然 price < SMA200, 但 SMA200 距离 >15 ATR 已不具备短期方向指引意义。
      → LONG, MEDIUM confidence (非 HIGH, 因为 SMA200 仍在上方且趋势尚未完全反转)
结果: {{"confluence":{{"trend_1d":"BEARISH — 但 ADX 从 42 跌到 28, DI 收敛, 趋势衰竭中","momentum_4h":"BULLISH — 三重 bullish divergence (RSI+MACD+OBV), RSI=48 回升, MACD hist 收敛","levels_30m":"BULLISH — 价格在强支撑 (距 1.5 ATR), BB 下轨反弹","derivatives":"NEUTRAL — OI 稳定, FR 接近零","aligned_layers":2}},"decision":"LONG","winning_side":"BULL","confidence":"MEDIUM","decisive_reasons":["TREND_EXHAUSTION","RSI_BULLISH_DIV_4H","MACD_BULLISH_DIV_4H","OBV_BULLISH_DIV_4H","NEAR_STRONG_SUPPORT"],"rationale":"trend_reversal=BULLISH(active) 检测到 4/5 反转信号: ADX 衰竭+三重背离+DI 收敛+强支撑。虽然 1D 表面仍 BEARISH, 但趋势动能已大幅衰减。4H 动量翻转确认反转条件。MEDIUM confidence 因 SMA200 仍在上方。","strategic_actions":["在支撑位做多, 目标 4H SMA20","若跌破支撑 1 ATR 则止损"],"acknowledged_risks":["SMA200 仍远在上方, 这是逆趋势交易","若支撑被跌破, 趋势可能加速下跌"]}}"""

        # Store prompts for diagnosis (v11.4)
        self.last_prompts["judge"] = {
            "system": system_prompt,
            "user": prompt,
        }

        # v27.0: Use JSON mode for structured output
        decision = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # Slightly higher for more nuanced judgment
            max_json_retries=2,
            trace_label="Judge",
            use_json_mode=True,
        )

        if decision:
            # v27.0: Unified schema validation with type coercion
            judge_defaults = {
                "decision": "HOLD", "winning_side": "TIE", "confidence": "LOW",
                "rationale": "N/A", "strategic_actions": ["Wait"],
                "acknowledged_risks": [], "decisive_reasons": [],
            }
            decision = self._validate_agent_output(decision, JUDGE_SCHEMA, "Judge", defaults=judge_defaults)

            # Validate aligned_layers is an integer in [0, 4] (nested in confluence)
            confluence = decision.get("confluence", {})
            if isinstance(confluence, dict):
                raw_layers = confluence.get("aligned_layers", 0)
                try:
                    aligned = int(raw_layers)
                    confluence["aligned_layers"] = max(0, min(4, aligned))
                except (ValueError, TypeError):
                    self.logger.warning(f"⚠️ Judge returned invalid aligned_layers '{raw_layers}', defaulting to 0")
                    confluence["aligned_layers"] = 0

            # v40.0: Use shared alignment enforcement (replaces inline copy)
            # dim_scores not available in text fallback path → pass None
            _conf_capped = self._enforce_alignment_cap(decision, confluence, dim_scores=None)
            if not _conf_capped:
                self.logger.info(f"📊 Judge decision: {decision.get('decision')} ({decision.get('confidence')})")
            return decision

        # Fallback decision if all retries failed
        self.logger.warning("Judge decision parsing failed after retries, using fallback")
        return {
            "confluence": {
                "trend_1d": "N/A — parse failure",
                "momentum_4h": "N/A — parse failure",
                "levels_30m": "N/A — parse failure",
                "derivatives": "N/A — parse failure",
                "aligned_layers": 0,
            },
            "decision": "HOLD",
            "winning_side": "TIE",
            "confidence": "LOW",
            "rationale": "JSON parse error - defaulting to HOLD for safety",
            "strategic_actions": ["Wait for next analysis cycle"],
            "acknowledged_risks": ["Parse failure"]
        }

    def _build_key_metrics(
        self,
        technical_data: Optional[Dict] = None,
        derivatives_data: Optional[Dict] = None,
        order_flow_data: Optional[Dict] = None,
        current_price: float = 0.0,
        binance_derivatives_data: Optional[Dict] = None,
        sentiment_data: Optional[Dict] = None,
        orderbook_data: Optional[Dict] = None,
    ) -> str:
        """
        Build concise key metrics for Judge's independent sanity check (v3.23).

        v3.24: Expanded from ~8 to ~18 fields for comprehensive verification.
        v20.0: Added orderbook OBI, top trader account ratio, Coinalyze L/S ratio,
               and OI trend for comprehensive derivatives cross-check.
        Only includes raw numbers — no interpretation — so Judge can verify
        whether Bull/Bear analysts correctly used the data.
        """
        lines = []
        try:
            if current_price > 0:
                lines.append(f"Price: ${current_price:,.2f}")

            if technical_data and isinstance(technical_data, dict):
                # RSI
                rsi = technical_data.get('rsi')
                if rsi is not None:
                    lines.append(f"RSI: {rsi:.1f}")
                # ADX + DI+/DI- (v3.24: added DI for trend direction)
                adx = technical_data.get('adx')
                if adx is not None:
                    di_plus = technical_data.get('di_plus')
                    di_minus = technical_data.get('di_minus')
                    adx_str = f"ADX: {adx:.1f}"
                    if di_plus is not None and di_minus is not None:
                        # v25.0: Explicit comparison + direction assertion to prevent AI misreading
                        _cmp = '>' if di_plus > di_minus else '<' if di_plus < di_minus else '='
                        _dir = 'BULLISH' if di_plus > di_minus else 'BEARISH'
                        adx_str += f" (DI+: {di_plus:.1f} {_cmp} DI-: {di_minus:.1f} → {_dir})"
                    lines.append(adx_str)
                # MACD
                macd = technical_data.get('macd')
                macd_signal = technical_data.get('macd_signal')
                if macd is not None and macd_signal is not None:
                    lines.append(f"MACD: {macd:.2f} (signal: {macd_signal:.2f})")
                # v3.24: BB Position (where price sits within Bollinger Bands)
                bb_pos = technical_data.get('bb_position')
                if bb_pos is not None:
                    lines.append(f"BB Position: {bb_pos:.1%}")
                # v3.24: SMA positions relative to price
                # NOTE: These are 30M-based SMAs (SMA50 ≈ 25h, SMA200 ≈ 100h)
                # Daily SMA200 is in the 1D Timeframe section
                for period in [50, 200]:
                    sma_val = technical_data.get(f'sma_{period}')
                    if sma_val is not None and sma_val > 0 and current_price > 0:
                        pct = (current_price - sma_val) / sma_val * 100
                        lines.append(f"Price vs SMA{period}_30M: {pct:+.2f}%")
                # v6.5: ATR for SL/TP distance verification
                atr_val = technical_data.get('atr')
                if atr_val is not None and atr_val > 0 and current_price > 0:
                    lines.append(f"ATR(14): ${atr_val:,.2f} ({atr_val/current_price*100:.3f}%)")
                # v19.1: Extension ratio for overextension detection
                ext_sma20 = technical_data.get('extension_ratio_sma_20')
                ext_regime = technical_data.get('extension_regime')
                if ext_sma20 is not None:
                    lines.append(f"Extension Ratio (SMA20): {ext_sma20:+.2f} ATR ({ext_regime})")
                # v3.24: Volume ratio
                vol_ratio = technical_data.get('volume_ratio')
                if vol_ratio is not None:
                    lines.append(f"Volume Ratio: {vol_ratio:.2f}x")

                # v5.5: Add 1D trend layer data for Judge's independent verification
                # Previously 1D data was only in tech_summary (Bull/Bear debate text),
                # but Judge's key_metrics lacked it, preventing independent verification
                mtf_trend = technical_data.get('mtf_trend_layer')
                if mtf_trend and isinstance(mtf_trend, dict):
                    lines.append("")
                    lines.append("--- 1D MACRO TREND (weight depends on ADX regime) ---")
                    trend_sma200 = mtf_trend.get('sma_200')
                    if trend_sma200 is not None and trend_sma200 > 0 and current_price > 0:
                        pct_vs_sma200 = (current_price - trend_sma200) / trend_sma200 * 100
                        lines.append(f"1D SMA200: ${trend_sma200:,.2f} (Price vs SMA200: {pct_vs_sma200:+.2f}%)")
                    trend_adx = mtf_trend.get('adx')
                    trend_di_plus = mtf_trend.get('di_plus')
                    trend_di_minus = mtf_trend.get('di_minus')
                    trend_adx_regime = mtf_trend.get('adx_regime', '')
                    if trend_adx is not None:
                        adx_str = f"1D ADX: {trend_adx:.1f} ({trend_adx_regime})"
                        if trend_di_plus is not None and trend_di_minus is not None:
                            _cmp = '>' if trend_di_plus > trend_di_minus else '<' if trend_di_plus < trend_di_minus else '='
                            _dir = 'BULLISH' if trend_di_plus > trend_di_minus else 'BEARISH'
                            adx_str += f" | DI+: {trend_di_plus:.1f} {_cmp} DI-: {trend_di_minus:.1f} → {_dir}"
                        lines.append(adx_str)
                    trend_rsi = mtf_trend.get('rsi')
                    if trend_rsi is not None:
                        lines.append(f"1D RSI: {trend_rsi:.1f}")
                    trend_macd = mtf_trend.get('macd')
                    if trend_macd is not None:
                        lines.append(f"1D MACD: {trend_macd:.4f}")
                    # v5.5: Explicit macro trend assessment for Judge
                    if trend_adx is not None and trend_di_plus is not None and trend_di_minus is not None:
                        if trend_adx > 25 and trend_di_minus > trend_di_plus:
                            if trend_sma200 and current_price > 0 and current_price < trend_sma200 * 0.85:
                                lines.append("⚠️ MACRO ASSESSMENT: RISK_OFF (strong 1D downtrend + price far below SMA200)")
                            else:
                                lines.append("⚠️ MACRO ASSESSMENT: BEARISH (1D ADX strong, DI- > DI+)")
                        elif trend_adx > 25 and trend_di_plus > trend_di_minus:
                            lines.append("MACRO ASSESSMENT: RISK_ON (strong 1D uptrend, DI+ > DI-)")
                        else:
                            lines.append("MACRO ASSESSMENT: NEUTRAL (1D trend not decisively strong)")

            # v18 audit: Add 4H decision layer for Judge's independent verification
            # Previously Judge could only see 4H data via debate transcript,
            # breaking the "independent sanity check" design intent of key_metrics.
            mtf_decision = technical_data.get('mtf_decision_layer')
            if mtf_decision and isinstance(mtf_decision, dict):
                lines.append("")
                lines.append("--- 4H DECISION LAYER (momentum confirmation) ---")
                dec_rsi = mtf_decision.get('rsi')
                if dec_rsi is not None:
                    lines.append(f"4H RSI: {dec_rsi:.1f}")
                dec_macd = mtf_decision.get('macd')
                dec_signal = mtf_decision.get('macd_signal')
                if dec_macd is not None and dec_signal is not None:
                    lines.append(f"4H MACD: {dec_macd:.4f} (signal: {dec_signal:.4f})")
                dec_adx = mtf_decision.get('adx')
                dec_di_plus = mtf_decision.get('di_plus')
                dec_di_minus = mtf_decision.get('di_minus')
                if dec_adx is not None:
                    adx_str = f"4H ADX: {dec_adx:.1f} ({mtf_decision.get('adx_regime', '')})"
                    if dec_di_plus is not None and dec_di_minus is not None:
                        _cmp = '>' if dec_di_plus > dec_di_minus else '<' if dec_di_plus < dec_di_minus else '='
                        _dir = 'BULLISH' if dec_di_plus > dec_di_minus else 'BEARISH'
                        adx_str += f" | DI+: {dec_di_plus:.1f} {_cmp} DI-: {dec_di_minus:.1f} → {_dir}"
                    lines.append(adx_str)
                dec_bb = mtf_decision.get('bb_position')
                if dec_bb is not None:
                    lines.append(f"4H BB Position: {dec_bb:.1%}")
                dec_atr = mtf_decision.get('atr')
                if dec_atr is not None and dec_atr > 0 and current_price > 0:
                    lines.append(f"4H ATR: ${dec_atr:,.2f} ({dec_atr/current_price*100:.3f}%)")
                dec_vol = mtf_decision.get('volume_ratio')
                if dec_vol is not None:
                    lines.append(f"4H Volume Ratio: {dec_vol:.2f}x")

            if derivatives_data and isinstance(derivatives_data, dict):
                fr = derivatives_data.get('funding_rate', {})
                if isinstance(fr, dict):
                    fr_pct = fr.get('current_pct')
                    if fr_pct is not None:
                        predicted = fr.get('predicted_rate_pct')
                        fr_str = f"Funding Rate: {fr_pct:.5f}%"
                        if predicted is not None:
                            fr_str += f" (predicted: {predicted:.5f}%)"
                        lines.append(fr_str)
                # Liquidations: raw Coinalyze data has history=[{t, l, s}]
                # l/s are in BTC units, must multiply by price for USD
                liq = derivatives_data.get('liquidations')
                if isinstance(liq, dict):
                    liq_history = liq.get('history', [])
                    if liq_history:
                        total_btc = sum(
                            float(h.get('l', 0)) + float(h.get('s', 0))
                            for h in liq_history
                        )
                        price_for_conv = current_price if current_price > 0 else 88000
                        total_usd = total_btc * price_for_conv
                        if total_usd > 0:
                            lines.append(f"Liquidations (24h): ${total_usd:,.0f}")
                # OI: raw Coinalyze data has {value: BTC_amount}
                oi = derivatives_data.get('open_interest')
                if isinstance(oi, dict):
                    oi_btc = float(oi.get('value', 0) or 0)
                    if oi_btc > 0 and current_price > 0:
                        oi_usd = oi_btc * current_price
                        if oi_usd >= 1e9:
                            lines.append(f"OI: ${oi_usd / 1e9:.2f}B")
                        else:
                            lines.append(f"OI: ${oi_usd / 1e6:.1f}M")

            if order_flow_data and isinstance(order_flow_data, dict):
                buy_ratio = order_flow_data.get('buy_ratio')
                if buy_ratio is not None:
                    lines.append(f"Buy Ratio: {buy_ratio:.1%}")
                cvd = order_flow_data.get('cvd_trend')
                if cvd:
                    lines.append(f"CVD Trend: {cvd}")

            # v3.24: Binance derivatives (top traders)
            if binance_derivatives_data and isinstance(binance_derivatives_data, dict):
                top_pos = binance_derivatives_data.get('top_long_short_position', {})
                latest = top_pos.get('latest') if isinstance(top_pos, dict) else None
                if latest:
                    long_pct = float(latest.get('longAccount', 0.5)) * 100
                    lines.append(f"Top Traders Position Long: {long_pct:.1f}%")
                # v20.0: Top trader ACCOUNT ratio — headcount vs exposure divergence
                top_acct = binance_derivatives_data.get('top_long_short_account', {})
                acct_latest = top_acct.get('latest') if isinstance(top_acct, dict) else None
                if acct_latest:
                    acct_long = float(acct_latest.get('longAccount', 0.5)) * 100
                    lines.append(f"Top Traders Account Long: {acct_long:.1f}%")

            # v20.0: Coinalyze L/S ratio (distinct from Binance global L/S)
            if derivatives_data and isinstance(derivatives_data, dict):
                ls_hist = derivatives_data.get('long_short_ratio_history')
                if ls_hist and isinstance(ls_hist, dict) and ls_hist.get('history'):
                    latest_ls = ls_hist['history'][-1]
                    ls_ratio = float(latest_ls.get('r', 1))
                    lines.append(f"Coinalyze L/S Ratio: {ls_ratio:.2f}")
                # v20.0: OI trend from Coinalyze history
                trends = derivatives_data.get('trends', {})
                if isinstance(trends, dict):
                    oi_trend = trends.get('oi_trend')
                    if oi_trend:
                        lines.append(f"OI Trend (Coinalyze): {oi_trend}")

            # v20.0: Orderbook OBI for supply/demand imbalance verification
            if orderbook_data and isinstance(orderbook_data, dict):
                obi = orderbook_data.get('obi', {})
                if isinstance(obi, dict):
                    adaptive_obi = obi.get('adaptive_weighted')
                    if adaptive_obi is not None:
                        lines.append(f"OBI (Weighted): {adaptive_obi:+.3f}")

            # v3.24: Sentiment
            if sentiment_data and isinstance(sentiment_data, dict):
                net = sentiment_data.get('net_sentiment')
                if net is not None:
                    try:
                        lines.append(f"Sentiment Net: {float(net):+.3f}")
                    except (ValueError, TypeError):
                        self.logger.debug("Operation failed (non-critical)")
                        pass

        except Exception as e:
            self.logger.debug(f"Operation failed (non-critical): {e}")
            pass

        return "\n".join(lines) if lines else "N/A"

    # =================================================================
    # Phase 2.5: Entry Timing Agent (v23.0)
    #
    # Dedicated AI agent that evaluates WHEN to enter, not WHETHER.
    # Sits between Judge (direction/confidence) and Risk Manager (sizing).
    # Replaces 3 hardcoded post-processing gates:
    #   - Alignment Gate (_check_alignment_gate)
    #   - Entry Quality Downgrade (_apply_entry_quality_downgrade)
    #   - 30M Confidence Cap (_apply_30m_confidence_cap)
    # =================================================================

    def _evaluate_entry_timing(
        self,
        judge_decision: Dict[str, Any],
        technical_report: str,
        technical_data: Optional[Dict[str, Any]],
        order_flow_report: str = "",
        derivatives_report: str = "",
        orderbook_report: str = "",
        past_memories: str = "",
        adx_1d: float = 30.0,
        dimensional_scores: str = "",  # v28.0: Pre-computed dimensional scores
    ) -> Dict[str, Any]:
        """
        Phase 2.5: Entry Timing Agent evaluates entry timing quality.

        This agent receives the Judge's direction decision and evaluates
        whether the current moment is optimal for entry. It can:
        - Downgrade confidence (but not upgrade)
        - Change signal to HOLD (timing reject)
        - Recommend WAIT (direction correct, timing wrong)

        Parameters
        ----------
        judge_decision : Dict
            Judge's output (decision, confidence, confluence)
        technical_report : str
            Full technical report (all timeframes)
        technical_data : Dict
            Raw technical data dict for numeric access
        order_flow_report : str
            Formatted order flow summary
        derivatives_report : str
            Formatted derivatives summary
        orderbook_report : str
            Formatted orderbook summary
        past_memories : str
            Role-annotated past memories for timing agent
        adx_1d : float
            1D ADX value for regime detection

        Returns
        -------
        Dict
            Entry timing assessment with timing_verdict, confidence adjustment, etc.
        """
        action = judge_decision.get("decision", "HOLD")

        # Only evaluate timing for actionable signals
        if action not in ("LONG", "SHORT"):
            return {
                "timing_verdict": "N/A",
                "timing_quality": "N/A",
                "adjusted_confidence": judge_decision.get("confidence", "LOW"),
                "counter_trend_risk": "NONE",
                "reason": "Non-actionable signal, timing evaluation skipped",
            }

        confidence = judge_decision.get("confidence", "LOW")
        rationale = judge_decision.get("rationale", "")
        confluence = judge_decision.get("confluence", {})

        # Extract key MTF data for the prompt
        _trend_layer = technical_data.get('mtf_trend_layer', {}) if technical_data else {}
        _decision_layer = technical_data.get('mtf_decision_layer', {}) if technical_data else {}

        # 1D trend direction
        # v23.0 fix: When DI+=DI-=0 (data missing), treat as "trend unclear"
        # instead of defaulting to BEARISH (which would inject false COUNTER-TREND ALERT)
        di_plus_1d = float(_trend_layer.get('di_plus', 0) or 0)
        di_minus_1d = float(_trend_layer.get('di_minus', 0) or 0)
        trend_data_available = not (di_plus_1d == 0 and di_minus_1d == 0)
        if trend_data_available:
            trend_is_bullish = di_plus_1d > di_minus_1d
            trend_direction = "BULLISH" if trend_is_bullish else "BEARISH"
            is_counter_trend = (
                (action == "LONG" and not trend_is_bullish) or
                (action == "SHORT" and trend_is_bullish)
            )
        else:
            trend_is_bullish = None  # Unknown
            trend_direction = "UNCLEAR"
            is_counter_trend = False  # Cannot determine counter-trend without data

        # 30M execution layer data
        _30m_adx = float(technical_data.get('adx', 0) or 0) if technical_data else 0
        _30m_di_plus = float(technical_data.get('di_plus', 0) or 0) if technical_data else 0
        _30m_di_minus = float(technical_data.get('di_minus', 0) or 0) if technical_data else 0
        _30m_rsi = float(technical_data.get('rsi', 50) or 50) if technical_data else 50
        _30m_macd_hist = float(technical_data.get('macd_histogram', 0) or 0) if technical_data else 0
        _30m_bb_pct = float(technical_data.get('bb_percent', 50) or 50) if technical_data else 50

        # Extension ratio
        ext_ratio = float(technical_data.get('extension_ratio', 0) or 0) if technical_data else 0
        ext_regime = technical_data.get('extension_regime', 'NORMAL') if technical_data else 'NORMAL'

        # Volatility regime
        vol_regime = technical_data.get('volatility_regime', 'NORMAL') if technical_data else 'NORMAL'

        # Build the counter-trend context
        counter_trend_section = ""
        if is_counter_trend:
            counter_trend_section = f"""
## ⚠️ COUNTER-TREND ALERT
This is a **COUNTER-TREND** trade:
- Signal: {action}
- 1D Trend: {trend_direction} (ADX={adx_1d:.1f}, DI+={di_plus_1d:.1f}, DI-={di_minus_1d:.1f})
- Counter-trend trades have significantly lower win rates in strong trends (ADX>40).

**Counter-trend risk assessment rules:**
- ADX > 40 (strong trend): Counter-trend is EXTREMELY risky. Require HIGH confidence + 30M momentum reversal confirmed. If not → REJECT.
- ADX 30-40 (moderate trend): Counter-trend is risky. Require MEDIUM+ confidence + 30M showing momentum shift. If only 1D against → timing_quality = FAIR max.
- ADX < 30: Trend is weak, counter-trend risk is manageable.
"""

        # Build 30M execution layer detail
        _30m_bull = _30m_di_plus > _30m_di_minus
        _30m_direction = "BULLISH" if _30m_bull else "BEARISH"
        _30m_signal_aligned = (
            (action == "LONG" and _30m_bull) or
            (action == "SHORT" and not _30m_bull)
        )
        _macd_aligned = (
            (action == "LONG" and _30m_macd_hist > 0) or
            (action == "SHORT" and _30m_macd_hist < 0)
        )

        trimmed_matrix = _trim_matrix_for_regime(adx_1d)

        prompt = f"""{dimensional_scores}
## 🎯 JUDGE'S DECISION (你需要评估其入场时机)
- Direction: **{action}** ({confidence} confidence)
- Judge Rationale: {rationale}
- Confluence: {json.dumps(confluence, ensure_ascii=False) if isinstance(confluence, dict) else str(confluence)}
{counter_trend_section}
## 📊 EXECUTION LAYER (30M) — 入场时机的核心数据
- ADX: {_30m_adx:.1f} (direction: {_30m_direction})
- DI+: {_30m_di_plus:.1f} {'>' if _30m_di_plus > _30m_di_minus else '<' if _30m_di_plus < _30m_di_minus else '='} DI-: {_30m_di_minus:.1f} → {_30m_direction}
- RSI: {_30m_rsi:.1f}
- MACD Histogram: {_30m_macd_hist:.4f} ({'aligned with ' + action if _macd_aligned else 'OPPOSING ' + action})
- BB%: {_30m_bb_pct:.1f}%
- 30M momentum aligned with signal: {'YES' if _30m_signal_aligned else '**NO** (30M opposing trade direction)'}
- MACD histogram aligned with signal: {'YES' if _macd_aligned else '**NO** (momentum opposing trade direction)'}

## 📈 RISK CONTEXT
- 1D ADX: {adx_1d:.1f} (Trend: {trend_direction})
- Extension Ratio: {ext_ratio:.2f} (Regime: {ext_regime})
- Volatility Regime: {vol_regime}
- Counter-trend: {'**YES**' if is_counter_trend else 'No'}

## 📊 FULL TECHNICAL DATA
{technical_report}

## 📈 ORDER FLOW
{order_flow_report if order_flow_report else "N/A"}

## 📊 DERIVATIVES
{derivatives_report if derivatives_report else "N/A"}

## 📚 PAST TIMING MISTAKES
{past_memories if past_memories else "No past data."}

---

请评估当前 **{action}** 信号的入场时机质量。"""

        # v25.0: INDICATOR_DEFINITIONS + trimmed_matrix first for DeepSeek prefix caching
        system_prompt = f"""{INDICATOR_DEFINITIONS}

{trimmed_matrix}

你是入场时机专家 (Entry Timing Specialist)。
你的唯一职责是评估：**给定 Judge 的方向决策，现在是否是好的入场时机？**

【核心原则 — 必须遵守】
✅ **你不改变方向** — Judge 已决定 LONG/SHORT/HOLD，你只评估"此刻入场是否合适"。
✅ **你可以降低 confidence** — 如果入场时机差，将 confidence 降一级 (HIGH→MEDIUM 或 MEDIUM→LOW)。
✅ **你可以否决入场** — timing_verdict = REJECT 时，signal 应改为 HOLD。
✅ **你不能提升 confidence** — confidence 只能保持或降低，不能升高。
🔴 语言强制规则: 所有文本输出必须用**中英混输** (中文为主体，技术术语保留英文)。纯英文输出将被系统拒绝。最终以 JSON 格式输出结果。

【评估框架 — 按以下 4 个维度独立评估】

### 维度 1: MTF 对齐度 (alignment)
逐层评估 1D / 4H / 30M 是否支持 Judge 的方向：
- 3 层一致 → alignment = STRONG
- 2 层一致 → alignment = MODERATE
- 1 层或 0 层 → alignment = WEAK (考虑 REJECT)

⚠️ 权重取决于 ADX:
- ADX ≥ 40 (强趋势): 1D 权重 70%，4H 30%。1D 逆向 = 几乎必定 REJECT。
- ADX 25-40: 1D 和 4H 均重要。1D 逆向且非 HIGH confidence = REJECT。
- ADX < 25 (震荡): 30M 关键水平层权重最高，1D 趋势降权。

### 维度 2: 30M 执行层时机
30M 是实际入场的时间框架，其动量方向直接影响入场质量：

**做多时的最佳条件:**
- RSI 在 Cardwell 回调区 40-50 (非超买)
- MACD Histogram 正值且增长 (动能向上)
- DI+ > DI- (方向一致)
- BB% 20-60% (有上涨空间)

**做空时的最佳条件:**
- RSI 在 Cardwell 反弹区 50-60 (非超卖)
- MACD Histogram 负值且下降 (动能向下)
- DI- > DI+ (方向一致)
- BB% 40-80% (有下跌空间)

⚠️ 30M 强逆向 (ADX>35 + DI 反向 + MACD Histogram 反向) = timing_quality 不得高于 FAIR。

### 维度 3: 逆势风险 (Counter-Trend)
如果信号与 1D 趋势方向相反：
- **ADX > 40 强趋势 + 逆势**: 除非 30M 动量完全反转 (DI+/DI- 已交叉 + MACD histogram 翻转 + RSI 确认), 否则 REJECT。这是最危险的入场。
- **ADX 30-40 中等趋势 + 逆势**: confidence 最高 MEDIUM，且需要 30M 动量支持。
- **ADX < 30 弱趋势 + 逆势**: 风险可控，正常评估。
- **顺势交易**: counter_trend_risk = NONE，不影响评估。

### 维度 4: Extension 与 Volatility
- Extension Ratio > 5.0 (EXTREME): 即使强趋势也罕见 → 不宜入场
- Extension Ratio 3.0-5.0 + ADX < 40: 均值回归压力 → timing_quality 降级
- Extension Ratio 3.0-5.0 + ADX ≥ 40: 可接受 (强趋势延伸常见)
- Volatility EXTREME (>90th percentile): 波动太大 → timing_quality 降级

【正确评估示例 — Few-shot】

示例 1: 顺势 + 30M 一致 → ENTER (保持 confidence)
情况: Judge LONG (HIGH), 1D ADX=35 bullish, 30M DI+>DI-, MACD hist>0, RSI=47
分析: 顺势交易，30M 动量完全一致，RSI 在理想回调区。
结果: {{"timing_verdict":"ENTER","timing_quality":"OPTIMAL","adjusted_confidence":"HIGH","counter_trend_risk":"NONE","alignment":"STRONG","reason":"顺势做多，30M 动量完全一致 (DI+领先+MACD hist 正值)，RSI=47 在 Cardwell 回调区。3/3 层对齐。"}}

示例 2: 顺势但 30M 强逆向 → ENTER (降级 confidence)
情况: Judge SHORT (HIGH), 1D ADX=45 bearish, 但 30M ADX=40 DI+>DI-, MACD hist=+12
分析: 宏观方向正确，但 30M 处于强反弹，入场被止损概率高。
结果: {{"timing_verdict":"ENTER","timing_quality":"FAIR","adjusted_confidence":"MEDIUM","counter_trend_risk":"NONE","alignment":"MODERATE","reason":"1D 强下跌趋势方向正确，但 30M ADX=40 且 DI+领先 + MACD hist>0，短期反弹动量强。入场时机差，confidence HIGH→MEDIUM。等 30M 动量消退再入场更佳。"}}

示例 3: 逆势 + ADX>40 → REJECT
情况: Judge LONG (MEDIUM), 1D ADX=45 DI->DI+ (强下跌), 30M RSI=52
分析: 在 ADX=45 强下跌趋势中做多，逆势风险极高。30M 无明确反转信号。
结果: {{"timing_verdict":"REJECT","timing_quality":"POOR","adjusted_confidence":"LOW","counter_trend_risk":"EXTREME","alignment":"WEAK","reason":"ADX=45 强下跌趋势中逆势做多。30M 无确认反转信号 (DI 未交叉，MACD hist 未翻正)。逆强趋势入场是最危险的操作，REJECT。"}}

示例 4: 逆势 + ADX>40 但 30M 完全反转 → ENTER (降级)
情况: Judge LONG (HIGH), 1D ADX=42 DI->DI+ (强下跌), 但 30M ADX=38 DI+>DI-, MACD hist=+8, RSI=55
分析: 虽然逆 1D 强趋势，但 30M 已完成动量反转。可尝试但需降级。
结果: {{"timing_verdict":"ENTER","timing_quality":"FAIR","adjusted_confidence":"MEDIUM","counter_trend_risk":"HIGH","alignment":"MODERATE","reason":"逆 1D 强下跌趋势做多风险高，但 30M 动量已完全反转 (DI+ 领先 + MACD hist 正值 + RSI=55 偏多)。允许入场但 confidence 强制降为 MEDIUM，逆势 R/R 倍增器会自动调高门槛。"}}

示例 5: 震荡市 + 关键水平 → ENTER
情况: Judge LONG (MEDIUM), 1D ADX=15, 价格在 S1 支撑, 30M RSI=32 超卖
分析: 震荡市中，关键水平入场有效。30M 超卖 = 均值回归信号。
结果: {{"timing_verdict":"ENTER","timing_quality":"GOOD","adjusted_confidence":"MEDIUM","counter_trend_risk":"NONE","alignment":"MODERATE","reason":"ADX=15 震荡市中，价格触及 S1 支撑 + RSI=32 超卖，均值回归入场。趋势层降权。"}}

## 📤 OUTPUT FORMAT (只输出 JSON，不要其他文字):
{{
    "timing_verdict": "ENTER|REJECT",
    "timing_quality": "OPTIMAL|GOOD|FAIR|POOR",
    "adjusted_confidence": "HIGH|MEDIUM|LOW",
    "counter_trend_risk": "NONE|LOW|HIGH|EXTREME",
    "alignment": "STRONG|MODERATE|WEAK",
    "reason": "<2-3 句中英混输: 入场时机评估理由，引用具体数据，技术术语保留英文>"
}}"""

        # Store prompts for diagnosis (v11.4)
        self.last_prompts["entry_timing"] = {
            "system": system_prompt,
            "user": prompt,
        }

        # v27.0: Use JSON mode for structured output
        decision = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,  # Low temperature for disciplined timing assessment
            max_json_retries=2,
            trace_label="Entry Timing",
            use_json_mode=True,
        )

        if decision:
            # v27.0: Unified schema validation with type coercion
            et_defaults = {
                "timing_verdict": "ENTER", "timing_quality": "FAIR",
                "adjusted_confidence": confidence,
                "counter_trend_risk": "NONE" if not is_counter_trend else "LOW",
                "alignment": "MODERATE", "decisive_reasons": [],
                "reason": "N/A",
            }
            decision = self._validate_agent_output(
                decision, ENTRY_TIMING_SCHEMA, "Entry Timing", defaults=et_defaults
            )

            # v23.0 Business logic: adjusted_confidence cannot exceed Judge's confidence
            conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
            raw_adj_conf = decision.get("adjusted_confidence", confidence)
            if conf_rank.get(raw_adj_conf, 0) > conf_rank.get(confidence, 0):
                self.logger.info(
                    f"🔒 Entry Timing tried to upgrade confidence "
                    f"{confidence}→{raw_adj_conf}, capping at {confidence}"
                )
                decision["adjusted_confidence"] = confidence

            # Safety net: if counter-trend + ADX>40 + timing says ENTER,
            # but counter_trend_risk is not EXTREME, log warning
            if (is_counter_trend and adx_1d >= 40
                    and decision["timing_verdict"] == "ENTER"
                    and decision["counter_trend_risk"] not in ("HIGH", "EXTREME")):
                self.logger.warning(
                    f"⚠️ Entry Timing: counter-trend in ADX={adx_1d:.0f} "
                    f"but counter_trend_risk={decision['counter_trend_risk']}. "
                    f"Mechanical override: counter_trend_risk → HIGH"
                )
                decision["counter_trend_risk"] = "HIGH"

            self.logger.info(
                f"⏱️ Entry Timing: verdict={decision['timing_verdict']} "
                f"quality={decision['timing_quality']} "
                f"confidence={confidence}→{decision['adjusted_confidence']} "
                f"counter_trend={decision['counter_trend_risk']}"
            )
            return decision

        # Fallback: if API fails, use conservative defaults
        self.logger.warning(
            "Entry Timing parsing failed, using conservative fallback"
        )
        fallback_conf = "MEDIUM" if confidence == "HIGH" else confidence
        return {
            "timing_verdict": "ENTER",
            "timing_quality": "FAIR",
            "adjusted_confidence": fallback_conf,
            "counter_trend_risk": "HIGH" if is_counter_trend else "NONE",
            "alignment": "MODERATE",
            "reason": "Entry Timing parse failure — conservative fallback applied",
        }

    def _evaluate_risk(
        self,
        proposed_action: Dict[str, Any],
        technical_report: str,
        sentiment_report: str,
        current_position: Optional[Dict[str, Any]],
        current_price: float,
        technical_data: Optional[Dict[str, Any]] = None,
        account_context: Optional[Dict[str, Any]] = None,
        derivatives_report: str = "",
        order_flow_report: str = "",
        orderbook_report: str = "",
        past_memories: str = "",  # v5.9: Past trade patterns
        adx_1d: float = 30.0,  # v5.13: For dynamic matrix trimming
        dimensional_scores: str = "",  # v28.0: Pre-computed dimensional scores
    ) -> Dict[str, Any]:
        """
        Final risk evaluation and position sizing.

        Borrowed from: TradingAgents/agents/risk_mgmt/conservative_debator.py
        Simplified v3.0: Let AI determine SL/TP based on market structure
        v3.7: Added BB position hardcoded checks for support/resistance risk control
        v3.8: Replaced BB-only check with multi-source S/R Zone check
        v3.11: Removed preset rules from prompt, let AI decide autonomously
        v4.6: Added account_context for position sizing decisions
        v3.22: Added derivatives_report for funding rate cost analysis
        v3.23: Added order_flow_report + orderbook_report for liquidity/slippage
        """
        action = proposed_action.get("decision", "HOLD")
        confidence = proposed_action.get("confidence", "LOW")
        # v3.10: Support both rationale (new) and key_reasons (legacy)
        rationale = proposed_action.get("rationale", "")
        strategic_actions = proposed_action.get("strategic_actions", [])
        risks = proposed_action.get("acknowledged_risks", [])
        if isinstance(risks, list):
            risks = risks.copy()  # Don't modify original

        # ========== v3.16: S/R Zone Hard Control moved to AI ==========
        # v3.8-v3.15: Local hard control (blocked trades programmatically)
        # v3.16: Moved to AI - Risk Manager now decides autonomously
        #        Local override only for emergency (sr_hard_control_enabled: true)
        #
        # TradingAgents principle: "Autonomy is non-negotiable"
        # AI receives hard_control info and decides whether to block
        # ================================================================
        sr_hard_control_enabled = getattr(self, 'sr_hard_control_enabled', False)  # v3.16: Default FALSE
        blocked_reason = ""
        hard_control_info = {}

        if self._sr_zones_cache:
            hard_control_info = self._sr_zones_cache.get('hard_control', {})

            # v3.16: Only use local override if explicitly enabled (emergency mode)
            if sr_hard_control_enabled:
                # Block LONG if too close to HIGH strength resistance
                if action == "LONG" and hard_control_info.get('block_long'):
                    blocked_reason = hard_control_info.get('reason', 'Too close to resistance')
                    self.logger.warning(f"⚠️ [LOCAL OVERRIDE] {blocked_reason}")
                    proposed_action["decision"] = "HOLD"
                    proposed_action["confidence"] = "LOW"
                    rationale = f"Blocked: {blocked_reason}"
                    risks.append("Too close to HIGH strength resistance zone")
                    action = "HOLD"

                # Block SHORT if too close to HIGH strength support
                elif action == "SHORT" and hard_control_info.get('block_short'):
                    blocked_reason = hard_control_info.get('reason', 'Too close to support')
                    self.logger.warning(f"⚠️ [LOCAL OVERRIDE] {blocked_reason}")
                    proposed_action["decision"] = "HOLD"
                    proposed_action["confidence"] = "LOW"
                    rationale = f"Blocked: {blocked_reason}"
                    risks.append("Too close to HIGH strength support zone")
                    action = "HOLD"
        # ========== End of S/R Zone Hard Control ==========

        # Format strategic actions for prompt
        actions_str = ', '.join(strategic_actions) if strategic_actions else 'None specified'

        # v2.0: Get S/R zones summary for SL/TP reference
        sr_zones_for_risk = ""
        if self._sr_zones_cache:
            sr_zones_for_risk = self._sr_zones_cache.get('ai_detailed_report', '')
            if not sr_zones_for_risk:
                sr_zones_for_risk = self._sr_zones_cache.get('ai_report', '')

        # v3.16: Format hard control info for AI (moved from local override to AI decision)
        hard_control_section = ""
        if hard_control_info:
            block_long = hard_control_info.get('block_long', False)
            block_short = hard_control_info.get('block_short', False)
            hc_reason = hard_control_info.get('reason', '')
            if block_long or block_short:
                hard_control_section = f"""
## ‼️ 【S/R ZONE 风险警报 — 请务必评估】
⚠️ S/R ZONE PROXIMITY ALERT:
- 接近 HIGH 强度阻力位 (Near HIGH Strength RESISTANCE): {'**YES**' if block_long else 'No'}
- 接近 HIGH 强度支撑位 (Near HIGH Strength SUPPORT): {'**YES**' if block_short else 'No'}
- 详情 (Detail): {hc_reason if hc_reason else 'N/A'}

‼️ 评估要点:
- "HIGH 强度" = 多源确认 (Swing Point + Volume Profile + Pivot 共振)，历史反弹率较高
- 逆 HIGH 强度 zone 交易的成功率显著降低
- 但伴随放量的强力突破可能是强势信号
- 这是参考信息，不是硬性规则 — 请结合所有数据综合判断
"""

        prompt = f"""{dimensional_scores}
你是风险管理者 (Risk Manager)，负责为 Judge 的交易决策评估风险参数。
{hard_control_section}

## 📋 PROPOSED TRADE (Judge 建议 — 你必须尊重此方向)
- Action: {action}
- Confidence: {confidence}
- Rationale: {rationale}
- Strategic Actions: {actions_str}
- Acknowledged Risks: {', '.join(risks)}

## 📊 MARKET DATA
{technical_report}

{sentiment_report}

## 🔑 S/R ZONES (参考上下文 — 不用于锚定 SL/TP)
{sr_zones_for_risk}

## 📉 DERIVATIVES & FUNDING RATE
{derivatives_report if derivatives_report else "N/A"}

## 📈 ORDER FLOW & LIQUIDITY
{order_flow_report if order_flow_report else "N/A"}

{orderbook_report if orderbook_report else ""}

## 💼 CURRENT POSITION
{self._format_position(current_position)}

## 🏦 ACCOUNT CONTEXT
{self._format_account(account_context)}

## 📚 PAST TRADE PATTERNS
{past_memories if past_memories else "No historical data yet."}

**当前价格: ${current_price:,.2f}**

---

## 🎯 【你的职责 — 评估风险，设置仓位大小】

‼️ **v11.0 架构变更**: SL/TP 由系统机械公式自动计算 (ATR × 信心倍数)。
你**不需要**输出 stop_loss 或 take_profit 价格。

⚠️ **v19.0 职责分离**: **confidence 由 Judge 决定，你不能修改。**
你通过 risk_appetite 表达风险评估 (影响仓位大小)。

Judge 建议 {action} → 你的任务:
- 如果是 LONG/SHORT: 评估风险因素 → 输出 risk_appetite (仓位大小)
- 如果是 HOLD: 直接传递，signal = HOLD
- 如果是 CLOSE/REDUCE: 直接传递

### 机械 SL/TP 如何工作 (你需要理解但不需要计算):
系统根据 Judge 的 confidence 自动计算 (v11.0-simple):
- **SL 距离** = ATR × sl_multiplier (HIGH=2.0, MEDIUM=2.5) — Judge 的 confidence 决定
- **TP 距离** = SL × R/R 目标 (HIGH=2.5, MEDIUM=2.0)
- **逆势**: R/R ≥ 1.95 (×1.3), SL 宽度不变
- **risk_appetite**: 仅影响仓位大小 (AGGRESSIVE=100%, NORMAL=80%, CONSERVATIVE=50%), 不影响 SL/TP

这意味着:
- Judge 的 confidence 控制 SL 宽度和 R/R 目标 (你无权修改)
- 你通过 risk_appetite 控制仓位大小 — 这是你表达风险担忧的唯一方式
- 担忧多 → CONSERVATIVE (半仓); 正常 → NORMAL (80%); 趋势明确+低风险 → AGGRESSIVE (全仓)

### STEP 1: 评估风险偏好 (risk_appetite)
根据市场环境调整仓位大小 (不影响 SL/TP 距离):
- **AGGRESSIVE**: 波动率低 + 趋势明确 + 低滑点 → 全仓 (100% of max)
- **NORMAL**: 标准市况 → 80% 仓位
- **CONSERVATIVE**: 高波动 + Funding Rate 偏高 + 流动性差 → 半仓 (50%)

### STEP 2: 评估风险因素
- **Funding Rate 成本**:
  - |rate| < 0.03%: 正常 → 不影响
  - |rate| 0.03-0.05%: 偏高 → 降低 risk_appetite 到 CONSERVATIVE
  - |rate| 0.05-0.10%: 高 → risk_appetite = CONSERVATIVE
  - |rate| > 0.10%: 极端 → 否决 (signal = HOLD)
- **流动性**:
  - 深度充足 → 不影响
  - 预期滑点 > 50bps → risk_appetite = CONSERVATIVE 或否决
- **S/R 位置参考** (影响 risk_appetite):
  - 价格靠近强 S/R zone 顺方向 → NORMAL/AGGRESSIVE
  - 价格远离所有 zone → CONSERVATIVE
- **清算缓冲** (Liquidation Buffer — 见 ACCOUNT CONTEXT):
  - buffer > 15%: 正常 → 不影响
  - buffer 10-15%: 偏低 → 降低 risk_appetite 到 CONSERVATIVE
  - buffer 5-10%: 高 → risk_appetite = CONSERVATIVE
  - buffer < 5%: 极端 → 否决加仓 (signal = HOLD)

### STEP 3: 检查是否触发紧急否决条件
只有以下情况允许将 Judge 的 LONG/SHORT 改为 HOLD:
1. |Funding Rate| > 0.10% — 极端拥挤
2. 流动性枯竭 — 预期滑点 > 50bps 且深度极低
3. S/R zones 显示价格被双面高强度 zone 夹击且距离 < 2 ATR (无法展开)
4. 清算缓冲 < 5% 且已有仓位 — 极端爆仓风险

---

## 📋 SIGNAL TYPES
- **LONG**: 开新多仓或加仓
- **SHORT**: 开新空仓或加仓
- **CLOSE**: 完全平仓 (不开反向仓位)
- **HOLD**: 不操作，维持现状
- **REDUCE**: 减仓但保持方向

## 📤 OUTPUT FORMAT (只输出 JSON，不要其他文字):
{{
    "signal": "LONG|SHORT|CLOSE|HOLD|REDUCE",
    "risk_appetite": "AGGRESSIVE|NORMAL|CONSERVATIVE",
    "position_risk": "FULL_SIZE|REDUCED|MINIMAL|REJECT",
    "market_structure_risk": "NORMAL|ELEVATED|HIGH|EXTREME",
    "reason": "<2-3 句中英混输: 总结每个风险维度的结论和关键因素，技术术语保留英文>"
}}"""

        # v4.14: Risk Manager 角色重定义 — 只管风险不管方向
        # v11.0: Risk Manager 不再输出 SL/TP 价格 — 机械公式自动计算
        # v5.13: Dynamic matrix trimming based on 1D ADX regime
        # v25.0: INDICATOR_DEFINITIONS + trimmed_matrix first for DeepSeek prefix caching
        trimmed_matrix = _trim_matrix_for_regime(adx_1d)
        system_prompt = f"""{INDICATOR_DEFINITIONS}

{trimmed_matrix}

你是风险管理者 (Risk Manager)。
你的职责是评估风险因素并设置仓位大小 (risk_appetite)。
(v11.0: SL/TP 由系统机械公式自动计算，你不需要输出价格。)
(v19.0: confidence 由 Judge 决定，你不能修改。)

【核心原则 — 必须遵守】
✅ **信任 Judge 的方向和信心判断** — Judge 已听完 Bull/Bear 4 轮辩论后做出决策。
✅ **你不能修改 confidence** — confidence 是 Judge 的权力，决定 SL 宽度和 R/R 目标。
✅ 你的工作: 评估风险 → 输出 risk_appetite (仓位大小)。担忧多用 CONSERVATIVE (半仓)，不要降 confidence。
✅ risk_appetite 仅影响仓位: AGGRESSIVE=100% | NORMAL=80% | CONSERVATIVE=50%
✅ 参考信号置信度矩阵和 S/R zone 位置评估信号可靠性。
⚠️ 只有 4 种极端情况才允许否决方向 (改 signal 为 HOLD): |FR| > 0.10% | 流动性枯竭 | S/R 夹击 < 2ATR | 清算缓冲 < 5%
🔴 语言强制规则: 所有文本输出必须用**中英混输** (中文为主体，技术术语保留英文)。纯英文输出将被系统拒绝。最终以 JSON 格式输出结果。

【v23.0 双视角风险评估框架 — 按以下 2 个维度独立评估】
(v23.0: 入场时机风险已由 Entry Timing Agent 独立评估，Risk Manager 专注仓位和市场结构风险)

**视角 1: 仓位风险** (position_risk)
- 账户权益 vs 拟开仓规模 (max_position_ratio)
- 清算缓冲: >15% 正常 | 10-15% 降级 | 5-10% → MINIMAL | <5% → REJECT
- 关联持仓: 加仓 vs 首仓 (加仓风险更高)
- Extension Ratio / Volatility Regime 影响仓位大小:
  - Extension >5.0 EXTREME → CONSERVATIVE (无论 ADX)
  - Extension 3.0-5.0 + ADX<40 → CONSERVATIVE
  - Volatility EXTREME → CONSERVATIVE 或 HOLD
  - Volatility HIGH → 适度缩小仓位
- 结论: FULL_SIZE / REDUCED / MINIMAL / REJECT

**视角 2: 市场结构风险** (market_structure_risk)
- Funding Rate 异常: |FR| > 0.05% 为高风险, |FR| > 0.10% 为极端
- 流动性评估: OBI、spread、slippage
- 清算热图方向 (多空清算不对称)
- 结论: NORMAL / ELEVATED / HIGH / EXTREME

【正确分析示例 — Few-shot】

示例 1: 顺势交易 + 低风险 → NORMAL appetite
情况: ADX=35, DI+ > DI-, Judge 建议 LONG (HIGH confidence), 当前价 $95,500
分析: 趋势明确，价格靠近 S1 支撑。FR=0.01% 正常。流动性充足。无显著风险。
结果: {{"signal":"LONG","risk_appetite":"NORMAL","position_risk":"FULL_SIZE","market_structure_risk":"NORMAL","reason":"仓位: 首仓，清算缓冲 28%，无压力。市场结构: FR=0.01% 正常，OBI=+0.3 流动性充足。"}}

示例 2: 价格被两面 zone 夹击 → HOLD (极端否决)
情况: Judge 建议 SHORT, 当前价 $68,432, 价格在 S1=$68,187 和 R1=$68,971 之间
分析: 价格被双 zone 夹击，上下距离均 < 2 ATR → 触发极端否决条件 #3。
结果: {{"signal":"HOLD","risk_appetite":"CONSERVATIVE","position_risk":"MINIMAL","market_structure_risk":"ELEVATED","reason":"仓位: S/R 夹击间距 $539 < 2 ATR ($800)，即使入场也只能极小仓位，MINIMAL。市场结构: 窄幅震荡区间，突破方向不确定。"}}

示例 3: 逆势交易 → CONSERVATIVE appetite (不降 confidence!)
情况: ADX=38 (STRONG TREND down), Judge 建议 LONG (MEDIUM confidence, 逆势)
分析: 逆势风险高。但 confidence 由 Judge 决定，我不能修改。
      用 risk_appetite=CONSERVATIVE (半仓) 表达风险担忧。
结果: {{"signal":"LONG","risk_appetite":"CONSERVATIVE","position_risk":"REDUCED","market_structure_risk":"ELEVATED","reason":"仓位: 逆势首仓用 REDUCED 半仓控制风险。市场结构: FR=-0.02% 微空头拥挤有利反弹，但 ADX=38 趋势仍强。"}}

示例 4: 极端资金费率 → HOLD (极端否决)
情况: Judge 建议 LONG, FR=+0.12% (极端拥挤)
分析: |FR|=0.12% > 0.10% 极端阈值 → 触发极端否决条件 #1。
结果: {{"signal":"HOLD","risk_appetite":"CONSERVATIVE","position_risk":"REDUCED","market_structure_risk":"EXTREME","reason":"仓位: 已有仓位加仓风险高。市场结构: FR=+0.12% 触发极端否决 (>0.10%)，多头极度拥挤，清算风险高，EXTREME → HOLD。"}}

示例 5: 多重风险因素 → CONSERVATIVE appetite (不降 confidence!)
情况: Judge 建议 LONG (HIGH confidence), BB上轨99%, 卖墙30x, FR=+0.06%, OBI=-0.8
分析: 多重不利因素叠加但不足以否决 (单个都未达极端阈值)。
      用 risk_appetite=CONSERVATIVE (半仓) 表达综合风险担忧。
结果: {{"signal":"LONG","risk_appetite":"CONSERVATIVE","position_risk":"REDUCED","market_structure_risk":"HIGH","reason":"仓位: 多重逆风叠加，REDUCED 半仓。市场结构: FR=+0.06% 偏高 + 卖墙 30x + OBI=-0.8 → HIGH，单项未达极端但叠加风险显著。"}}"""

        # Store prompts for diagnosis (v11.4)
        self.last_prompts["risk"] = {
            "system": system_prompt,
            "user": prompt,
        }

        # v27.0: Use JSON mode for structured output
        decision = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_json_retries=2,
            trace_label="Risk Manager",
            use_json_mode=True,
        )

        if decision:
            # v27.0: Unified schema validation with type coercion
            risk_defaults = {
                "signal": "HOLD", "risk_appetite": "NORMAL",
                "position_risk": "FULL_SIZE", "market_structure_risk": "NORMAL",
                "risk_factors": [], "reason": "N/A",
            }
            decision = self._validate_agent_output(
                decision, RISK_SCHEMA, "Risk Manager", defaults=risk_defaults
            )

            decision["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            decision["debate_rounds"] = self.debate_rounds
            decision["judge_decision"] = proposed_action

            # v3.12: Normalize signal type (handle legacy BUY/SELL)
            decision = self._normalize_signal(decision)

            # v19.0: Confidence comes from Judge, not Risk Manager.
            # RM can veto to HOLD (extreme cases) but cannot change confidence level.
            valid_confidences = {"HIGH", "MEDIUM", "LOW"}
            signal = decision.get("signal", "HOLD").upper()

            if signal in ("LONG", "SHORT"):
                # For actionable signals: force Judge's confidence through
                judge_conf = str(proposed_action.get("confidence", "MEDIUM")).upper().strip()
                if judge_conf not in valid_confidences:
                    judge_conf = "MEDIUM"
                rm_conf = str(decision.get("confidence", "")).upper().strip()
                if rm_conf and rm_conf != judge_conf and rm_conf in valid_confidences:
                    self.logger.info(
                        f"🔒 v19.0: RM tried to change confidence {judge_conf}→{rm_conf}, "
                        f"overriding with Judge's {judge_conf} (RM uses risk_appetite for risk concerns)"
                    )
                decision["confidence"] = judge_conf
            else:
                # For HOLD/CLOSE/REDUCE: confidence doesn't drive execution
                decision["confidence"] = "LOW"

            # v19.0: Validate risk_appetite (RM's only mechanism for risk expression)
            valid_appetites = {"AGGRESSIVE", "NORMAL", "CONSERVATIVE"}
            raw_appetite = str(decision.get("risk_appetite", "NORMAL")).upper().strip()
            if raw_appetite not in valid_appetites:
                self.logger.warning(f"⚠️ RM returned invalid risk_appetite '{raw_appetite}', defaulting to NORMAL")
                raw_appetite = "NORMAL"
            decision["risk_appetite"] = raw_appetite

            # v11.0: Log mechanical SL/TP parameters
            if signal in ("LONG", "SHORT"):
                conf = decision.get("confidence", "MEDIUM")
                appetite = decision.get("risk_appetite", "NORMAL")
                self.logger.info(
                    f"🔧 RM output (v19.0): signal={signal} "
                    f"confidence={conf} (from Judge) risk_appetite={appetite} (from RM) "
                    f"→ SL/TP by mechanical formula, position size by appetite"
                )

            return decision

        # Fallback if all retries failed
        self.logger.warning("Risk evaluation parsing failed after retries, using fallback")
        return self._create_fallback_signal({"price": current_price})

    def _normalize_signal(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize signal type to v3.12 format.

        Handles legacy BUY/SELL signals and converts to LONG/SHORT.
        Valid signals: LONG, SHORT, CLOSE, HOLD, REDUCE

        Parameters
        ----------
        decision : Dict
            Raw decision from AI

        Returns
        -------
        Dict
            Decision with normalized signal
        """
        signal = decision.get("signal", "HOLD").upper().strip()

        # Legacy mapping
        legacy_mapping = {
            "BUY": "LONG",
            "SELL": "SHORT",
        }

        # Valid v3.12 signals
        valid_signals = {"LONG", "SHORT", "CLOSE", "HOLD", "REDUCE"}

        # Check if legacy signal
        if signal in legacy_mapping:
            new_signal = legacy_mapping[signal]
            self.logger.info(f"Signal normalized: {signal} → {new_signal}")
            decision["signal"] = new_signal
            decision["original_signal"] = signal  # Keep original for debugging
        elif signal in valid_signals:
            decision["signal"] = signal
        else:
            # Unknown signal, default to HOLD
            self.logger.warning(f"Unknown signal '{signal}', defaulting to HOLD")
            decision["signal"] = "HOLD"
            decision["original_signal"] = signal

        # Validate position_size_pct
        # v11.0: Risk Manager no longer outputs position_size_pct — it outputs risk_appetite instead.
        # When AI doesn't provide position_size_pct, leave as None so calculate_position_size()
        # uses the confidence mapping (HIGH=80%, MEDIUM=50%, LOW=30%) + appetite_scale.
        # Defaulting to 100 bypasses the confidence mapping and always uses max position.
        raw_size_pct = decision.get("position_size_pct")
        if raw_size_pct is not None:
            try:
                size_pct = float(raw_size_pct)
                size_pct = max(0, min(100, size_pct))  # Clamp to 0-100
            except (ValueError, TypeError) as e:
                self.logger.debug(f"Using default value, original error: {e}")
                size_pct = None  # Invalid value → let confidence mapping handle it
        else:
            size_pct = None  # Not provided → let confidence mapping handle it

        # Special handling for CLOSE signal
        if decision["signal"] == "CLOSE":
            size_pct = 0

        decision["position_size_pct"] = size_pct

        return decision

    def _compute_trend_verdict(self, data: Dict[str, Any]) -> str:
        """
        v5.6: Pre-compute 1D macro trend verdict and place it at TOP of technical report.
        v18 Item 14: Also computes MTF ALIGNMENT v2 (ternary direction + momentum).
        v18 Item 17: Also computes LAYER SUMMARY (cross-layer pre-digest).

        Stores alignment data on self._alignment_data for consumption by _compute_layer_summary().

        Returns
        -------
        str
            Formatted LAYER SUMMARY + 1D TREND VERDICT + MTF ALIGNMENT block.
        """
        mtf_trend = data.get('mtf_trend_layer')
        if not mtf_trend:
            self._alignment_data = None
            return ""

        def tget(key, default=0):
            val = mtf_trend.get(key)
            return float(val) if val is not None else default

        sma_200 = tget('sma_200')
        macd_1d = tget('macd')
        macd_signal_1d = tget('macd_signal')
        rsi_1d = tget('rsi')
        adx_1d = tget('adx')
        di_plus_1d = tget('di_plus')
        di_minus_1d = tget('di_minus')
        adx_regime = mtf_trend.get('adx_regime', 'UNKNOWN')
        price = data.get('price', 0)

        # Determine macro assessment
        above_sma200 = price > sma_200 if sma_200 > 0 else None
        macd_bullish = macd_1d > macd_signal_1d
        di_bullish = di_plus_1d > di_minus_1d

        # Count bullish/bearish signals (only count valid/non-None signals)
        signals = [above_sma200, macd_bullish, di_bullish, rsi_1d > 50]
        valid_signals = [s for s in signals if s is not None]
        bull_count = sum(1 for s in valid_signals if s)
        bear_count = len(valid_signals) - bull_count

        if adx_1d < 20:
            regime = "RANGING (weak trend)"
            if bull_count >= 3:
                verdict = "NEUTRAL_BULLISH — No strong trend, slight bullish lean"
            elif bear_count >= 3:
                verdict = "NEUTRAL_BEARISH — No strong trend, slight bearish lean"
            else:
                verdict = "NEUTRAL — No clear macro direction"
        elif bull_count >= 3:
            if adx_1d >= 30:
                verdict = "STRONG_BULLISH — Clear uptrend with momentum"
            else:
                verdict = "BULLISH — Uptrend developing"
            regime = f"TRENDING ({adx_regime})"
        elif bear_count >= 3:
            if adx_1d >= 30:
                verdict = "STRONG_BEARISH — Clear downtrend with momentum"
            else:
                verdict = "BEARISH — Downtrend developing"
            regime = f"TRENDING ({adx_regime})"
        else:
            verdict = "MIXED — Conflicting macro signals"
            regime = f"TRANSITIONAL ({adx_regime})"

        pct_vs_sma = ((price / sma_200 - 1) * 100) if sma_200 > 0 else 0

        # --- v18 Item 14: MTF ALIGNMENT v2 (ternary + momentum) ---
        # 1D direction (from verdict)
        if bull_count >= 3:
            dir_1d = "BULLISH"
        elif bear_count >= 3:
            dir_1d = "BEARISH"
        else:
            dir_1d = "MIXED"
        dir_1d_arrow = "↑" if dir_1d == "BULLISH" else ("↓" if dir_1d == "BEARISH" else "→")

        # 4H direction + momentum
        mtf_decision = data.get('mtf_decision_layer')
        dir_4h = "N/A"
        dir_4h_arrow = "?"
        momentum_4h = ""
        rsi_4h = 50.0
        macd_hist_4h = 0.0
        if mtf_decision:
            def dget(key, default=0):
                val = mtf_decision.get(key)
                return float(val) if val is not None else default
            rsi_4h = dget('rsi')
            macd_4h = dget('macd')
            macd_sig_4h = dget('macd_signal')
            macd_hist_4h = macd_4h - macd_sig_4h

            # Ternary direction with dead zone (RSI 45-55 = neutral)
            if rsi_4h > 55 and macd_4h > macd_sig_4h:
                dir_4h = "BULLISH"
                dir_4h_arrow = "↑"
            elif rsi_4h < 45 and macd_4h < macd_sig_4h:
                dir_4h = "BEARISH"
                dir_4h_arrow = "↓"
            elif rsi_4h > 55 or macd_4h > macd_sig_4h:
                dir_4h = "LEAN BULLISH"
                dir_4h_arrow = "↗"
            elif rsi_4h < 45 or macd_4h < macd_sig_4h:
                dir_4h = "LEAN BEARISH"
                dir_4h_arrow = "↘"
            else:
                dir_4h = "NEUTRAL"
                dir_4h_arrow = "→"

            # Momentum detection from 4H historical context
            hist_4h = mtf_decision.get('historical_context', {})
            rsi_trend_4h = hist_4h.get('rsi_trend', [])
            macd_hist_trend = hist_4h.get('macd_histogram_trend', [])

            if len(rsi_trend_4h) >= 2:
                rsi_rising = rsi_trend_4h[-1] > rsi_trend_4h[-2]
                rsi_delta = rsi_trend_4h[-1] - rsi_trend_4h[-2]
            else:
                rsi_rising = None
                rsi_delta = 0

            if len(macd_hist_trend) >= 2:
                hist_expanding = abs(macd_hist_trend[-1]) > abs(macd_hist_trend[-2])
            else:
                hist_expanding = None

            # Build momentum string
            momentum_parts = []
            if rsi_rising is not None:
                momentum_parts.append(f"RSI{'↑' if rsi_rising else '↓'}")
            if hist_expanding is not None:
                momentum_parts.append(f"MACD {'加速' if hist_expanding else '减速'}")
            momentum_4h = ",".join(momentum_parts)

            # Qualify direction with WEAKENING/STRENGTHENING
            if "BULLISH" in dir_4h and not dir_4h.startswith("LEAN"):
                if rsi_rising is False or hist_expanding is False:
                    dir_4h = f"WEAKENING {dir_4h}"
                elif rsi_rising is True and hist_expanding is True:
                    dir_4h = f"STRENGTHENING {dir_4h}"
            elif "BEARISH" in dir_4h and not dir_4h.startswith("LEAN"):
                if rsi_rising is True or hist_expanding is False:
                    dir_4h = f"WEAKENING {dir_4h}"
                elif rsi_rising is False and hist_expanding is True:
                    dir_4h = f"STRENGTHENING {dir_4h}"

        # 30M direction (from execution layer data)
        rsi_30m = data.get('rsi', 50)
        macd_30m = data.get('macd', 0)
        macd_sig_30m = data.get('macd_signal', 0)
        try:
            rsi_30m = float(rsi_30m)
            macd_30m = float(macd_30m)
            macd_sig_30m = float(macd_sig_30m)
        except (ValueError, TypeError):
            rsi_30m, macd_30m, macd_sig_30m = 50, 0, 0

        if rsi_30m > 55 and macd_30m > macd_sig_30m:
            dir_30m = "BULLISH"
            dir_30m_arrow = "↑"
        elif rsi_30m < 45 and macd_30m < macd_sig_30m:
            dir_30m = "BEARISH"
            dir_30m_arrow = "↓"
        else:
            dir_30m = "NEUTRAL"
            dir_30m_arrow = "→"

        # Cross-layer assessment
        dirs = [dir_1d, dir_4h.split()[-1] if dir_4h != "N/A" else "N/A", dir_30m]
        bullish_count = sum(1 for d in dirs if "BULLISH" in d)
        bearish_count = sum(1 for d in dirs if "BEARISH" in d)

        if bullish_count >= 2:
            alignment_label = f"ALIGNED BULLISH ({bullish_count}/3 layers)"
        elif bearish_count >= 2:
            alignment_label = f"ALIGNED BEARISH ({bearish_count}/3 layers)"
        else:
            alignment_label = "CONFLICTING (no 2/3 majority)"

        # Interpretive line
        interp_line = ""
        if dir_1d != "MIXED" and dir_30m != "NEUTRAL" and ("BULLISH" in dir_1d) != ("BULLISH" in dir_30m):
            if "WEAKENING" in dir_4h:
                interp_line = f"  → 4H hasn't confirmed turn — likely counter-trend rally, not reversal"
            else:
                interp_line = f"  → 30M diverges from 1D — watch for counter-trend exhaustion"
        elif bullish_count == 3 or bearish_count == 3:
            interp_line = f"  → Full alignment — high-conviction setup"

        # Build alignment text
        momentum_str = f"({momentum_4h})" if momentum_4h else ""
        alignment_text = f"""
MTF ALIGNMENT: 1D {dir_1d}({dir_1d_arrow}) | 4H {dir_4h}{momentum_str} | 30M {dir_30m}({dir_30m_arrow})
  → {alignment_label}
{interp_line}"""

        # Store alignment data for _compute_layer_summary()
        self._alignment_data = {
            'dir_1d': dir_1d, 'dir_4h': dir_4h, 'dir_30m': dir_30m,
            'dir_1d_arrow': dir_1d_arrow, 'dir_4h_arrow': dir_4h_arrow, 'dir_30m_arrow': dir_30m_arrow,
            'alignment_label': alignment_label,
            'pct_vs_sma': pct_vs_sma, 'adx_1d': adx_1d,
            'rsi_4h': rsi_4h, 'macd_hist_4h': macd_hist_4h,
            'momentum_4h': momentum_4h,
            'rsi_30m': rsi_30m,
        }

        # --- v18 Item 17: LAYER SUMMARY (top of report) ---
        layer_summary = self._compute_layer_summary(data)

        # Also include 4H snapshot
        decision_line = ""
        if mtf_decision:
            adx_4h = dget('adx')
            adx_regime_4h = mtf_decision.get('adx_regime', 'N/A')
            decision_line = f"""
4H SNAPSHOT: RSI={rsi_4h:.1f} | MACD Hist={macd_hist_4h:.4f} | ADX={adx_4h:.1f} ({adx_regime_4h})"""

        verdict_block = f"""
╔══════════════════════════════════════════════════════════╗
║  1D MACRO TREND VERDICT (weight depends on ADX regime)   ║
╚══════════════════════════════════════════════════════════╝
VERDICT: {verdict}
REGIME: {regime}
- Price vs SMA_200: {pct_vs_sma:+.2f}% ({'ABOVE' if above_sma200 else 'BELOW' if above_sma200 is False else 'N/A'})
- 1D MACD: {macd_1d:.4f} vs Signal {macd_signal_1d:.4f} ({'BULLISH' if macd_bullish else 'BEARISH'})
- 1D RSI: {rsi_1d:.1f} ({'Above 50' if rsi_1d > 50 else 'Below 50'})
- 1D ADX: {adx_1d:.1f} | DI+ {di_plus_1d:.1f} / DI- {di_minus_1d:.1f} ({'Bulls lead' if di_bullish else 'Bears lead'})
{decision_line}
{alignment_text}
⚠️ Layer weights depend on ADX: Strong trend (ADX>40) → 1D dominant | Ranging (ADX<20) → 30M levels dominant
"""
        # Output order: LAYER SUMMARY (primacy) → 1D VERDICT → alignment
        return layer_summary + verdict_block

    def _compute_layer_summary(self, data: Dict[str, Any]) -> str:
        """
        v18 Item 17: Pre-computed per-layer digest at ABSOLUTE TOP of report.
        Exploits primacy effect — AI reads this first before detailed data.

        Returns
        -------
        str
            4-line layer summary, or empty string if alignment data unavailable.
        """
        ad = self._alignment_data
        if not ad:
            return ""

        # 1D summary
        pct_str = f"SMA200 {'上方' if ad['pct_vs_sma'] > 0 else '下方'} {abs(ad['pct_vs_sma']):.1f}%"
        adx_str = f"ADX={ad['adx_1d']:.0f}"
        di_str = "DI+ 主导" if ad['dir_1d'] == "BULLISH" else ("DI- 主导" if ad['dir_1d'] == "BEARISH" else "方向不明")
        trend_strength = "强趋势" if ad['adx_1d'] >= 40 else ("中等趋势" if ad['adx_1d'] >= 25 else "弱趋势")
        line_1d = f"• 1D 趋势层: {ad['dir_1d']} — {pct_str}, {adx_str} {trend_strength}, {di_str}"

        # 4H summary
        momentum_desc = f", {ad['momentum_4h']}" if ad['momentum_4h'] else ""
        line_4h = f"• 4H 决策层: {ad['dir_4h']} — RSI={ad['rsi_4h']:.0f}{momentum_desc}"

        # 30M summary
        rsi_note = ""
        if ad['rsi_30m'] > 70:
            rsi_note = "超买"
        elif ad['rsi_30m'] < 30:
            rsi_note = "超卖"
        elif ad['rsi_30m'] > 60:
            rsi_note = "偏多"
        elif ad['rsi_30m'] < 40:
            rsi_note = "偏空"
        else:
            rsi_note = "中性"
        line_30m = f"• 30M 执行层: {ad['dir_30m']} — RSI={ad['rsi_30m']:.0f} {rsi_note}"

        # Cross-layer line
        cross = f"• 跨层: 1D{ad['dir_1d_arrow']} 4H{ad['dir_4h_arrow']} 30M{ad['dir_30m_arrow']} = {ad['alignment_label']}"

        return f"""
=== LAYER SUMMARY (读取此摘要后再分析详细数据) ===
{line_1d}
{line_4h}
{line_30m}
{cross}
"""

    # =========================================================================
    # v27.0: Feature Snapshot Persistence
    # =========================================================================

    _SNAPSHOT_DIR = "data/feature_snapshots"
    _MAX_SNAPSHOTS = 500

    def _persist_feature_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Save feature snapshot to disk for cross-process replay."""
        import os
        from pathlib import Path

        try:
            snap_dir = Path(self._SNAPSHOT_DIR)
            snap_dir.mkdir(parents=True, exist_ok=True)

            ts = snapshot.get("timestamp", "unknown").replace(":", "-")
            snap_path = snap_dir / f"{ts}.json"
            with open(snap_path, 'w') as f:
                json.dump(snapshot, f, indent=2, default=str)
            self._last_snapshot_id = f"{ts}.json"

            # Prune old snapshots
            existing = sorted(snap_dir.glob("*.json"))
            for old in existing[:-self._MAX_SNAPSHOTS]:
                old.unlink()
        except Exception as e:
            self._last_snapshot_id = ""
            self.logger.debug(f"Feature snapshot persistence failed: {e}")

    def get_schema_audit_metadata(self) -> Dict[str, Any]:
        """Return schema version + snapshot ID + violation counts for signal logging.

        Called by downstream code (e.g. signal_log_service) after analyze() to
        attach audit metadata to each signal entry, enabling replay traceability.
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "feature_version": FEATURE_VERSION,
            "snapshot_id": getattr(self, '_last_snapshot_id', ''),
            "schema_violations": dict(getattr(self, '_schema_violations', {})),
        }

    @staticmethod
    def load_feature_snapshot(path: str) -> Dict[str, Any]:
        """
        Load a saved feature snapshot from disk for replay.

        Usage:
            snapshot = MultiAgentAnalyzer.load_feature_snapshot(
                "data/feature_snapshots/2026-03-06T12-00-00.json"
            )
            result = analyzer.analyze_from_features(
                feature_dict=snapshot["features"],
                memory_features=snapshot.get("_memory"),
                debate_r1=snapshot.get("_debate_r1"),
                temperature=0.0, seed=42,
            )
        """
        from pathlib import Path
        snap_path = Path(path)
        if not snap_path.exists():
            raise FileNotFoundError(f"Snapshot not found: {path}")
        with open(snap_path, 'r') as f:
            return json.load(f)

    def _check_debate_integrity(
        self,
        bull_r2: Dict[str, Any],
        bear_r2: Dict[str, Any],
        bear_r1: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Detect when Bear R2 copies Bull R2 output instead of generating
        an independent bearish analysis.  Falls back to Bear R1 when:
        1. Bear R2 evidence is identical to Bull R2 evidence (exact copy), or
        2. Bear R2 evidence contains mostly bullish-only tags with no
           bearish-only tags (direction mismatch).

        Returns bear_r2 unchanged if valid, or bear_r1 if corruption detected.
        """
        bull_ev = set(bull_r2.get("evidence", []))
        bear_ev = set(bear_r2.get("evidence", []))

        # Check 1: exact duplicate
        if bull_ev and bull_ev == bear_ev:
            self.logger.warning(
                "[Debate Integrity] Bear R2 evidence identical to Bull R2 — "
                "LLM copied opponent output. Falling back to Bear R1."
            )
            if not hasattr(self, '_schema_violations'):
                self._schema_violations = {}
            self._schema_violations["Bear R2_copy"] = 1
            return bear_r1

        # Check 2: direction mismatch — Bear evidence has bullish tags but no bearish
        bear_bullish = bear_ev & BULLISH_EVIDENCE_TAGS
        bear_bearish = bear_ev & BEARISH_EVIDENCE_TAGS
        if len(bear_bullish) >= 3 and len(bear_bearish) == 0:
            self.logger.warning(
                f"[Debate Integrity] Bear R2 has {len(bear_bullish)} bullish-only tags "
                f"and 0 bearish tags — direction mismatch. "
                f"Bullish tags: {sorted(bear_bullish)}. Falling back to Bear R1."
            )
            if not hasattr(self, '_schema_violations'):
                self._schema_violations = {}
            self._schema_violations["Bear R2_direction"] = 1
            return bear_r1

        return bear_r2

    def _check_bull_integrity(
        self,
        bull_r2: Dict[str, Any],
        bear_r1: Dict[str, Any],
        bull_r1: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Detect when Bull R2 capitulates to Bear — mirror of _check_debate_integrity().

        Falls back to Bull R1 when:
        1. Bull R2 evidence is identical to Bear R1 evidence (exact copy), or
        2. Bull R2 evidence contains mostly bearish-only tags with no
           bullish-only tags (direction mismatch / capitulation).

        Returns bull_r2 unchanged if valid, or bull_r1 if capitulation detected.
        """
        bull_ev = set(bull_r2.get("evidence", []))
        bear_ev = set(bear_r1.get("evidence", []))

        # Check 1: exact duplicate of Bear R1
        if bear_ev and bull_ev == bear_ev:
            self.logger.warning(
                "[Debate Integrity] Bull R2 evidence identical to Bear R1 — "
                "LLM capitulated to opponent. Falling back to Bull R1."
            )
            if not hasattr(self, '_schema_violations'):
                self._schema_violations = {}
            self._schema_violations["Bull R2_capitulation"] = 1
            return bull_r1

        # Check 2: direction mismatch — Bull evidence has bearish tags but no bullish
        bull_has_bearish = bull_ev & BEARISH_EVIDENCE_TAGS
        bull_has_bullish = bull_ev & BULLISH_EVIDENCE_TAGS
        if len(bull_has_bearish) >= 3 and len(bull_has_bullish) == 0:
            self.logger.warning(
                f"[Debate Integrity] Bull R2 has {len(bull_has_bearish)} bearish-only tags "
                f"and 0 bullish tags — capitulation detected. "
                f"Bearish tags: {sorted(bull_has_bearish)}. Falling back to Bull R1."
            )
            if not hasattr(self, '_schema_violations'):
                self._schema_violations = {}
            self._schema_violations["Bull R2_direction"] = 1
            return bull_r1

        return bull_r2

    # =========================================================================
    # v27.0: Feature-Driven Structured Pipeline (used by analyze() + replay)
    # =========================================================================

    def _run_structured_debate(
        self,
        feature_dict: Dict[str, Any],
        adx_1d: float,
        selected_memories: List[Dict],
        current_conditions: Dict[str, Any],
        ctx: Optional[AnalysisContext] = None,
    ) -> tuple:
        """
        Run Bull/Bear debate using feature-driven structured prompts.

        Returns:
            (bull_r2, bear_r2, debate_summary, debate_history_text)
            - bull_r2, bear_r2: validated structured dicts
            - debate_summary: human-readable summary for downstream
            - debate_history_text: synthetic text for quality audit / logging
        """
        # Use precomputed values from context, or compute if no context
        valid_tags = ctx.valid_tags if ctx else compute_valid_tags(feature_dict)
        tags_ref = ctx.annotated_tags if ctx else compute_annotated_tags(feature_dict, valid_tags)
        feature_json = json.dumps(feature_dict, indent=2, default=str)

        # Memory formatting
        past_memories_bull = self._get_past_memories(
            current_conditions, agent_role="bull", preselected=selected_memories
        )
        past_memories_bear = self._get_past_memories(
            current_conditions, agent_role="bear", preselected=selected_memories
        )

        bull_system = self._build_bull_feature_system_prompt(adx_1d, tags_ref)
        bear_system = self._build_bear_feature_system_prompt(adx_1d, tags_ref)

        # Use precomputed scores from context, or compute if no context
        dim_scores = ctx.scores if ctx else ReportFormatterMixin.compute_scores_from_features(feature_dict)

        bull_user = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "_memory": past_memories_bull[:_MEMORY_PROMPT_MAX_CHARS] if past_memories_bull else "",
        }, default=str)

        bear_user = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "_memory": past_memories_bear[:_MEMORY_PROMPT_MAX_CHARS] if past_memories_bear else "",
        }, default=str)

        bull_defaults = {"evidence": [], "risk_flags": [], "conviction": 0.5, "summary": "N/A"}
        bear_defaults = {"evidence": [], "risk_flags": [], "conviction": 0.5, "summary": "N/A"}

        # Round 1 — Bull and Bear are independent, run in parallel
        def _call_bull_r1():
            return self._extract_json_with_retry(
                messages=[
                    {"role": "system", "content": bull_system},
                    {"role": "user", "content": bull_user},
                ],
                temperature=self.temperature,
                trace_label="Bull R1",
                use_json_mode=True,
            )

        def _call_bear_r1():
            return self._extract_json_with_retry(
                messages=[
                    {"role": "system", "content": bear_system},
                    {"role": "user", "content": bear_user},
                ],
                temperature=self.temperature,
                trace_label="Bear R1",
                use_json_mode=True,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            bull_r1_future = executor.submit(_call_bull_r1)
            bear_r1_future = executor.submit(_call_bear_r1)
            bull_r1_raw = bull_r1_future.result()
            bear_r1_raw = bear_r1_future.result()

        bull_r1 = bull_r1_raw or bull_defaults.copy()
        bull_r1 = self._validate_agent_output(bull_r1, BULL_SCHEMA, "Bull R1", defaults=bull_defaults)
        self._safe_filter_tags(bull_r1, valid_tags, "Bull R1")
        self._stamp_validated_output(bull_r1, "Bull R1")

        # Store prompts for diagnosis
        self.last_prompts["bull"] = {"system": bull_system, "user": bull_user}

        bear_r1 = bear_r1_raw or bear_defaults.copy()
        bear_r1 = self._validate_agent_output(bear_r1, BEAR_SCHEMA, "Bear R1", defaults=bear_defaults)
        self._safe_filter_tags(bear_r1, valid_tags, "Bear R1")
        self._stamp_validated_output(bear_r1, "Bear R1")

        self.last_prompts["bear"] = {"system": bear_system, "user": bear_user}

        # Round 2: cross-examine with opponent's output
        bull_r2_user = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "_opponent": {
                "evidence": bear_r1["evidence"],
                "risk_flags": bear_r1["risk_flags"],
                "conviction": bear_r1["conviction"],
                "summary": bear_r1.get("_raw_summary", bear_r1.get("summary", "")),
            },
            "_memory": past_memories_bull[:_MEMORY_PROMPT_MAX_CHARS] if past_memories_bull else "",
        }, default=str)

        bull_r2 = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": bull_system},
                {"role": "user", "content": bull_r2_user},
            ],
            temperature=self.temperature,
            trace_label="Bull R2",
            use_json_mode=True,
        ) or bull_r1
        bull_r2 = self._validate_agent_output(
            bull_r2, BULL_SCHEMA, "Bull R2",
            defaults={"conviction": bull_r1.get("conviction", 0.5), "summary": bull_r1.get("summary", "N/A")},
        )
        self._safe_filter_tags(bull_r2, valid_tags, "Bull R2")
        self._stamp_validated_output(bull_r2, "Bull R2")

        # v28.0: Detect Bull R2 capitulating to Bear (mirror of Bear R2 check)
        bull_r2 = self._check_bull_integrity(bull_r2, bear_r1, bull_r1)

        bear_r2_user = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "_opponent": {
                "evidence": bull_r2["evidence"],
                "risk_flags": bull_r2["risk_flags"],
                "conviction": bull_r2["conviction"],
                "summary": bull_r2.get("_raw_summary", bull_r2.get("summary", "")),
            },
            "_memory": past_memories_bear[:_MEMORY_PROMPT_MAX_CHARS] if past_memories_bear else "",
        }, default=str)

        # v27.0: Strengthen Bear R2 prompt to prevent copying Bull output.
        # DeepSeek at low temperature can collapse to identical output when
        # features are the same. Add explicit counter-argument instruction.
        bear_r2_system = bear_system + (
            "\n\nIMPORTANT: _opponent contains the Bull's argument. You MUST:"
            "\n- COUNTER the opponent's evidence, not repeat it"
            "\n- Your evidence tags MUST differ from the opponent's evidence tags"
            "\n- Focus on BEARISH tags (e.g. MACD_BEARISH_CROSS, CVD_NEGATIVE, "
            "TREND_EXHAUSTION) not BULLISH tags"
            "\n- If you agree the trend is strong, your evidence should still "
            "highlight SHORT risks and exhaustion signals"
        )

        bear_r2 = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": bear_r2_system},
                {"role": "user", "content": bear_r2_user},
            ],
            temperature=self.temperature,
            trace_label="Bear R2",
            use_json_mode=True,
        ) or bear_r1
        bear_r2 = self._validate_agent_output(
            bear_r2, BEAR_SCHEMA, "Bear R2",
            defaults={"conviction": bear_r1.get("conviction", 0.5), "summary": bear_r1.get("summary", "N/A")},
        )
        self._safe_filter_tags(bear_r2, valid_tags, "Bear R2")
        self._stamp_validated_output(bear_r2, "Bear R2")

        # Debate integrity: detect Bear R2 copying Bull R2 output
        bear_r2 = self._check_debate_integrity(bull_r2, bear_r2, bear_r1)

        # v34.1: Compute R1→R2 similarity metrics for shallow debate detection
        # Stored on R2 output dicts so auditor can read them from ctx.bull/bear_output
        for agent_label, r1, r2 in [("Bull", bull_r1, bull_r2), ("Bear", bear_r1, bear_r2)]:
            r1_ev = set(r1.get("evidence", []))
            r2_ev = set(r2.get("evidence", []))
            union = r1_ev | r2_ev
            r2["_r1_r2_evidence_overlap"] = len(r1_ev & r2_ev) / len(union) if union else 1.0
            r2["_r1_r2_evidence_new"] = len(r2_ev - r1_ev)
            r2["_r1_r2_conviction_delta"] = abs(r2.get("conviction", 0.5) - r1.get("conviction", 0.5))

        # v27.0: Save R1 validated outputs for snapshot deterministic replay
        self._last_debate_r1 = {"bull_r1": bull_r1, "bear_r1": bear_r1}

        # Build debate_summary from structured output (§3.2 of PLAN)
        debate_summary = (
            f"Bull ({bull_r2['conviction']:.0%}): {bull_r2['summary']}\n"
            f"Bear ({bear_r2['conviction']:.0%}): {bear_r2['summary']}"
        )

        # Build synthetic debate_history for downstream (quality audit, logging)
        # v29.4: Include reasoning field — use _raw_reasoning (pre-truncation)
        # when available so quality auditor can detect data category references
        # that were truncated from the 500-char reasoning field.
        debate_history_text = (
            f"\n\n=== ROUND 1 ===\n\n"
            f"BULL ANALYST:\n"
            f"Reasoning: {bull_r1.get('_raw_reasoning', bull_r1.get('reasoning', 'N/A'))}\n"
            f"Evidence: {', '.join(bull_r1.get('evidence', []))}\n"
            f"Risk flags: {', '.join(bull_r1.get('risk_flags', []))}\n"
            f"Conviction: {bull_r1.get('conviction', 0):.0%}\n"
            f"Summary: {bull_r1.get('summary', 'N/A')}\n\n"
            f"BEAR ANALYST:\n"
            f"Reasoning: {bear_r1.get('_raw_reasoning', bear_r1.get('reasoning', 'N/A'))}\n"
            f"Evidence: {', '.join(bear_r1.get('evidence', []))}\n"
            f"Risk flags: {', '.join(bear_r1.get('risk_flags', []))}\n"
            f"Conviction: {bear_r1.get('conviction', 0):.0%}\n"
            f"Summary: {bear_r1.get('summary', 'N/A')}\n\n"
            f"=== ROUND 2 ===\n\n"
            f"BULL ANALYST:\n"
            f"Reasoning: {bull_r2.get('_raw_reasoning', bull_r2.get('reasoning', 'N/A'))}\n"
            f"Evidence: {', '.join(bull_r2.get('evidence', []))}\n"
            f"Risk flags: {', '.join(bull_r2.get('risk_flags', []))}\n"
            f"Conviction: {bull_r2.get('conviction', 0):.0%}\n"
            f"Summary: {bull_r2.get('summary', 'N/A')}\n\n"
            f"BEAR ANALYST:\n"
            f"Reasoning: {bear_r2.get('_raw_reasoning', bear_r2.get('reasoning', 'N/A'))}\n"
            f"Evidence: {', '.join(bear_r2.get('evidence', []))}\n"
            f"Risk flags: {', '.join(bear_r2.get('risk_flags', []))}\n"
            f"Conviction: {bear_r2.get('conviction', 0):.0%}\n"
            f"Summary: {bear_r2.get('summary', 'N/A')}"
        )

        return bull_r2, bear_r2, debate_summary, debate_history_text

    # =========================================================================
    # v27.0 Phase 2: Structured Judge / Entry Timing / Risk for production
    # =========================================================================

    def _run_structured_judge(
        self,
        feature_dict: Dict[str, Any],
        bull_r2: Dict[str, Any],
        bear_r2: Dict[str, Any],
        memory_text: str,
        adx_1d: float,
        ctx: Optional[AnalysisContext] = None,
    ) -> Dict[str, Any]:
        """
        Feature-driven Judge decision (production structured path).

        Uses the same prompt builder and JSON format as analyze_from_features()
        to ensure replay parity.
        """
        valid_tags = ctx.valid_tags if ctx else compute_valid_tags(feature_dict)
        tags_ref = ctx.annotated_tags if ctx else compute_annotated_tags(feature_dict, valid_tags)
        system_prompt = self._build_judge_feature_system_prompt(adx_1d, tags_ref)

        # Use precomputed scores from context
        dim_scores = ctx.scores if ctx else ReportFormatterMixin.compute_scores_from_features(feature_dict)

        user_msg = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "bull_evidence": bull_r2.get("evidence", []),
            "bull_conviction": bull_r2.get("conviction", 0.5),
            "bull_summary": bull_r2.get("_raw_summary", bull_r2.get("summary", "")),
            "bear_evidence": bear_r2.get("evidence", []),
            "bear_conviction": bear_r2.get("conviction", 0.5),
            "bear_summary": bear_r2.get("_raw_summary", bear_r2.get("summary", "")),
            "_memory": memory_text[:_MEMORY_PROMPT_MAX_CHARS] if memory_text else "",
        }, default=str)

        # Record prompt for diagnostic parity checks
        self.last_prompts["judge"] = {"system": system_prompt, "user": user_msg}

        raw = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=self.temperature,
            trace_label="Judge (structured)",
            use_json_mode=True,
        ) or {}

        defaults = {
            "decision": "HOLD", "winning_side": "TIE", "confidence": "LOW",
            "rationale": "Parse failure", "strategic_actions": ["Wait"],
            "acknowledged_risks": [], "decisive_reasons": [],
            "confluence": {"trend_1d": "NEUTRAL", "momentum_4h": "NEUTRAL",
                          "levels_30m": "NEUTRAL", "derivatives": "NEUTRAL",
                          "aligned_layers": 0},
        }
        result = self._validate_agent_output(raw, JUDGE_SCHEMA, "Judge", defaults=defaults)
        self._safe_filter_tags(result, valid_tags, "Judge")
        validate_judge_confluence(result, feature_dict)
        self._stamp_validated_output(result, "Judge (structured)")

        # v40.0: Use shared alignment enforcement (replaces inline copy)
        self._enforce_alignment_cap(result, result.get("confluence", {}), dim_scores=dim_scores)

        return result

    def _run_structured_entry_timing(
        self,
        feature_dict: Dict[str, Any],
        judge_decision: Dict[str, Any],
        adx_1d: float,
        memory_text: str = "",
        ctx: Optional[AnalysisContext] = None,
    ) -> Dict[str, Any]:
        """
        Feature-driven Entry Timing evaluation (production structured path).

        Uses the same prompt builder and JSON format as analyze_from_features()
        to ensure replay parity.
        """
        valid_tags = ctx.valid_tags if ctx else compute_valid_tags(feature_dict)
        tags_ref = ctx.annotated_tags if ctx else compute_annotated_tags(feature_dict, valid_tags)
        system_prompt = self._build_et_feature_system_prompt(adx_1d, tags_ref)

        # Use precomputed scores from context
        dim_scores = ctx.scores if ctx else ReportFormatterMixin.compute_scores_from_features(feature_dict)

        user_msg = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "judge_decision": judge_decision.get("decision", "HOLD"),
            "judge_confidence": judge_decision.get("confidence", "LOW"),
            "judge_rationale": judge_decision.get("_raw_rationale", judge_decision.get("rationale", "")),
            "_memory": memory_text[:_MEMORY_PROMPT_MAX_CHARS] if memory_text else "",
        }, default=str)

        # Record prompt for diagnostic parity checks
        self.last_prompts["entry_timing"] = {"system": system_prompt, "user": user_msg}

        raw = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=self.temperature,
            trace_label="Entry Timing (structured)",
            use_json_mode=True,
        ) or {}

        defaults = {
            "timing_verdict": "ENTER", "timing_quality": "FAIR",
            "adjusted_confidence": judge_decision.get("confidence", "LOW"),
            "counter_trend_risk": "NONE", "alignment": "MODERATE",
            "decisive_reasons": [], "reason": "Parse failure",
        }
        result = self._validate_agent_output(raw, ENTRY_TIMING_SCHEMA, "Entry Timing", defaults=defaults)
        self._safe_filter_tags(result, valid_tags, "Entry Timing")
        self._stamp_validated_output(result, "Entry Timing (structured)")
        return result

    def _run_structured_risk(
        self,
        feature_dict: Dict[str, Any],
        judge_decision: Dict[str, Any],
        memory_text: str,
        adx_1d: float,
        ctx: Optional[AnalysisContext] = None,
    ) -> Dict[str, Any]:
        """
        Feature-driven Risk Manager evaluation (production structured path).

        Uses the same prompt builder and JSON format as analyze_from_features()
        to ensure replay parity.
        """
        valid_tags = ctx.valid_tags if ctx else compute_valid_tags(feature_dict)
        tags_ref = ctx.annotated_tags if ctx else compute_annotated_tags(feature_dict, valid_tags)
        system_prompt = self._build_risk_feature_system_prompt(adx_1d, tags_ref)

        # Use precomputed scores from context
        dim_scores = ctx.scores if ctx else ReportFormatterMixin.compute_scores_from_features(feature_dict)

        user_msg = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "proposed_action": judge_decision.get("decision", "HOLD"),
            "proposed_confidence": judge_decision.get("confidence", "LOW"),
            "judge_rationale": judge_decision.get("_raw_rationale", judge_decision.get("rationale", "")),
            "_memory": memory_text[:_MEMORY_PROMPT_MAX_CHARS] if memory_text else "",
        }, default=str)

        # Record prompt for diagnostic parity checks
        self.last_prompts["risk"] = {"system": system_prompt, "user": user_msg}

        raw = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=self.temperature,
            trace_label="Risk Manager (structured)",
            use_json_mode=True,
        ) or {}

        defaults = {
            "signal": "HOLD", "risk_appetite": "NORMAL",
            "position_risk": "FULL_SIZE", "market_structure_risk": "NORMAL",
            "risk_factors": [], "reason": "Parse failure",
        }
        risk_result = self._validate_agent_output(raw, RISK_SCHEMA, "Risk Manager", defaults=defaults)
        self._safe_filter_tags(risk_result, valid_tags, "Risk Manager")
        self._stamp_validated_output(risk_result, "Risk Manager (structured)")

        # Build final decision dict matching _evaluate_risk() output format
        final = dict(risk_result)
        final["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        final["debate_rounds"] = self.debate_rounds
        final["judge_decision"] = judge_decision

        # v3.12: Normalize signal type (handle legacy BUY/SELL)
        final = self._normalize_signal(final)

        # v19.0: Confidence comes from Judge, not Risk Manager
        valid_confidences = {"HIGH", "MEDIUM", "LOW"}
        signal = final.get("signal", "HOLD").upper()
        if signal in ("LONG", "SHORT"):
            judge_conf = str(judge_decision.get("confidence", "MEDIUM")).upper().strip()
            if judge_conf not in valid_confidences:
                judge_conf = "MEDIUM"
            final["confidence"] = judge_conf
        else:
            final["confidence"] = "LOW"

        # Validate risk_appetite
        valid_appetites = {"AGGRESSIVE", "NORMAL", "CONSERVATIVE"}
        raw_appetite = str(final.get("risk_appetite", "NORMAL")).upper().strip()
        if raw_appetite not in valid_appetites:
            raw_appetite = "NORMAL"
        final["risk_appetite"] = raw_appetite

        # Alias for downstream compatibility
        final["risk_level"] = final.get("market_structure_risk", "NORMAL")

        return final

    # =========================================================================
    # v27.0: Feature-Driven Replay Entry Point
    # =========================================================================

    def analyze_from_features(
        self,
        feature_dict: Dict[str, Any],
        memory_features: Optional[List[Dict]] = None,
        debate_r1: Optional[Dict[str, Dict]] = None,
        temperature: float = 0.0,
        seed: Optional[int] = None,
        prompt_version: Optional[str] = None,
        cached_outputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Replay analysis from a saved feature snapshot.

        Skips extract_features() entirely — uses provided feature_dict directly.
        This is the ONLY entry point for replay and AB testing.

        Args:
            feature_dict:    Pre-extracted features (from saved snapshot).
            memory_features: Structured memory list (from snapshot._memory).
                             If None, uses current trading_memory.json.
            debate_r1:       Saved R1 outputs from snapshot ({"bull_r1": {...}, "bear_r1": {...}}).
                             If provided, skips R1 API calls for deterministic replay.
                             If None, makes fresh R1 calls (non-deterministic with temp>0).
            temperature:     0.0 for deterministic replay. Default 0.0.
            seed:            Optional RNG seed for DeepSeek API.
            prompt_version:  Optional prompt set identifier for AB testing.
                             If None, uses current prompts.
                             If specified, loads from PROMPT_REGISTRY[prompt_version].
            cached_outputs:  v30.3 Decision Cache — saved agent outputs from snapshot._decision_cache.
                             If provided, skips ALL API calls (zero-cost replay).
                             Returns the cached decision directly with replay_metadata.

        Returns:
            Same structure as analyze(), plus replay_metadata.
        """
        # v30.3: Zero-API cached replay — return saved outputs directly
        if cached_outputs:
            judge_out = cached_outputs.get("judge", {})
            timing_out = cached_outputs.get("entry_timing", {})
            return {
                "signal": cached_outputs.get("signal", "HOLD"),
                "confidence": cached_outputs.get("confidence", "LOW"),
                "risk_level": cached_outputs.get("risk", {}).get("market_structure_risk", "NORMAL"),
                "risk_appetite": cached_outputs.get("risk", {}).get("risk_appetite", "NORMAL"),
                "reason": cached_outputs.get("risk", {}).get("reason", ""),
                "debate_summary": (
                    f"Bull ({cached_outputs.get('bull_r2', {}).get('conviction', 0):.0%}): "
                    f"{cached_outputs.get('bull_r2', {}).get('summary', 'N/A')}\n"
                    f"Bear ({cached_outputs.get('bear_r2', {}).get('conviction', 0):.0%}): "
                    f"{cached_outputs.get('bear_r2', {}).get('summary', 'N/A')}"
                ),
                "judge_decision": judge_out,
                "_timing_assessment": timing_out,
                "_timing_rejected": judge_out.get("_timing_rejected", False),
                "_quality_score": cached_outputs.get("quality_score"),
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "replay_metadata": {
                    "replay": True,
                    "cached": True,
                    "api_calls": 0,
                    "source_snapshot_ts": feature_dict.get("_snapshot_ts", None),
                    "temperature": 0.0,
                    "seed": None,
                    "prompt_version": "cached",
                    "feature_version": feature_dict.get("_feature_version", FEATURE_VERSION),
                },
            }
        self.call_trace = []
        self._ext_reflections_cache = None

        # Build user prompt from feature dict (JSON dump)
        feature_json = json.dumps(feature_dict, indent=2, default=str)

        # Memory handling
        if memory_features is not None:
            # Use provided structured memories
            memory_text = self._format_structured_memories(memory_features)
        else:
            # Use current trading_memory.json
            current_conditions = MemoryConditions.from_feature_dict(feature_dict).to_dict()
            selected = self._select_memories(current_conditions)
            memory_text = self._get_past_memories(current_conditions, agent_role="judge", preselected=selected)

        # Resolve prompt overrides
        prompt_overrides = {}
        if prompt_version and prompt_version in PROMPT_REGISTRY:
            prompt_overrides = PROMPT_REGISTRY[prompt_version]

        adx_1d = feature_dict.get("adx_1d", 30.0)
        regime = feature_dict.get("market_regime", "RANGING")

        # Replay path: compute once, use everywhere
        valid_tags = compute_valid_tags(feature_dict)
        tags_ref = compute_annotated_tags(feature_dict, valid_tags)
        dim_scores = ReportFormatterMixin.compute_scores_from_features(feature_dict)

        # Phase 1: Bull/Bear (using feature dict)
        bull_system = prompt_overrides.get("bull_system", self._build_bull_feature_system_prompt(adx_1d, tags_ref))
        bear_system = prompt_overrides.get("bear_system", self._build_bear_feature_system_prompt(adx_1d, tags_ref))

        if debate_r1 and "bull_r1" in debate_r1 and "bear_r1" in debate_r1:
            # Deterministic replay: use saved R1 outputs (skip 2 API calls)
            bull_r1 = self._validate_agent_output(
                debate_r1["bull_r1"], BULL_SCHEMA, "Bull R1",
                defaults={"conviction": 0.5, "summary": "N/A"})
            bear_r1 = self._validate_agent_output(
                debate_r1["bear_r1"], BEAR_SCHEMA, "Bear R1",
                defaults={"conviction": 0.5, "summary": "N/A"})
            self.logger.info("Replay: Using saved R1 outputs (deterministic)")
        else:
            # Fresh R1 calls
            dim_scores_json = json.dumps(dim_scores, default=str)
            bull_user = f'{{"_scores": {dim_scores_json}, "features": {feature_json}, "_memory": {json.dumps(memory_text[:_MEMORY_PROMPT_MAX_CHARS])}}}'

            bull_r1 = self._extract_json_with_retry(
                messages=[
                    {"role": "system", "content": bull_system},
                    {"role": "user", "content": bull_user},
                ],
                temperature=temperature,
                trace_label="Bull R1 (replay)",
                use_json_mode=True,
                seed=seed,
            ) or {"evidence": [], "risk_flags": [], "conviction": 0.5, "summary": "Parse failure"}

            bull_r1 = self._validate_agent_output(bull_r1, BULL_SCHEMA, "Bull R1",
                                                   defaults={"conviction": 0.5, "summary": "N/A"})
            self._safe_filter_tags(bull_r1, valid_tags, "Bull R1 (replay)")
            self._stamp_validated_output(bull_r1, "Bull R1 (replay)")

            bear_user = f'{{"_scores": {dim_scores_json}, "features": {feature_json}, "_memory": {json.dumps(memory_text[:_MEMORY_PROMPT_MAX_CHARS])}}}'

            bear_r1 = self._extract_json_with_retry(
                messages=[
                    {"role": "system", "content": bear_system},
                    {"role": "user", "content": bear_user},
                ],
                temperature=temperature,
                trace_label="Bear R1 (replay)",
                use_json_mode=True,
                seed=seed,
            ) or {"evidence": [], "risk_flags": [], "conviction": 0.5, "summary": "Parse failure"}

            bear_r1 = self._validate_agent_output(bear_r1, BEAR_SCHEMA, "Bear R1",
                                                   defaults={"conviction": 0.5, "summary": "N/A"})
            self._safe_filter_tags(bear_r1, valid_tags, "Bear R1 (replay)")
            self._stamp_validated_output(bear_r1, "Bear R1 (replay)")

        # Round 2: cross-examine (dim_scores already computed once at top)
        bull_r2_user = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "_opponent": {"evidence": bear_r1["evidence"], "risk_flags": bear_r1["risk_flags"],
                          "conviction": bear_r1["conviction"], "summary": bear_r1.get("_raw_summary", bear_r1.get("summary", ""))},
        }, default=str)

        bull_r2 = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": bull_system},
                {"role": "user", "content": bull_r2_user},
            ],
            temperature=temperature,
            trace_label="Bull R2 (replay)",
            use_json_mode=True,
            seed=seed,
        ) or bull_r1

        bull_r2 = self._validate_agent_output(bull_r2, BULL_SCHEMA, "Bull R2",
                                               defaults={"conviction": 0.5, "summary": bull_r1.get("summary", "N/A")})
        self._safe_filter_tags(bull_r2, valid_tags, "Bull R2 (replay)")
        self._stamp_validated_output(bull_r2, "Bull R2 (replay)")

        # v28.0: Detect Bull R2 capitulation in replay path too
        bull_r2 = self._check_bull_integrity(bull_r2, bear_r1, bull_r1)

        bear_r2_user = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "_opponent": {"evidence": bull_r2["evidence"], "risk_flags": bull_r2["risk_flags"],
                          "conviction": bull_r2["conviction"], "summary": bull_r2.get("_raw_summary", bull_r2.get("summary", ""))},
        }, default=str)

        bear_r2 = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": bear_system},
                {"role": "user", "content": bear_r2_user},
            ],
            temperature=temperature,
            trace_label="Bear R2 (replay)",
            use_json_mode=True,
            seed=seed,
        ) or bear_r1

        bear_r2 = self._validate_agent_output(bear_r2, BEAR_SCHEMA, "Bear R2",
                                               defaults={"conviction": 0.5, "summary": bear_r1.get("summary", "N/A")})
        self._safe_filter_tags(bear_r2, valid_tags, "Bear R2 (replay)")
        self._stamp_validated_output(bear_r2, "Bear R2 (replay)")

        # v28.0: Debate integrity check in replay path too
        bear_r2 = self._check_debate_integrity(bull_r2, bear_r2, bear_r1)

        # Debate summary from structured output
        debate_summary = (
            f"Bull ({bull_r2['conviction']:.0%}): {bull_r2['summary']}\n"
            f"Bear ({bear_r2['conviction']:.0%}): {bear_r2['summary']}"
        )

        # Phase 2: Judge
        judge_system = prompt_overrides.get("judge_system", self._build_judge_feature_system_prompt(adx_1d, tags_ref))
        judge_user = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "bull_evidence": bull_r2["evidence"],
            "bull_conviction": bull_r2["conviction"],
            "bull_summary": bull_r2.get("_raw_summary", bull_r2["summary"]),
            "bear_evidence": bear_r2["evidence"],
            "bear_conviction": bear_r2["conviction"],
            "bear_summary": bear_r2.get("_raw_summary", bear_r2["summary"]),
            "_memory": memory_text[:_MEMORY_PROMPT_MAX_CHARS],
        }, default=str)

        judge_raw = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": judge_system},
                {"role": "user", "content": judge_user},
            ],
            temperature=temperature,
            trace_label="Judge (replay)",
            use_json_mode=True,
            seed=seed,
        ) or {}

        judge_defaults = {
            "decision": "HOLD", "winning_side": "TIE", "confidence": "LOW",
            "rationale": "Parse failure", "strategic_actions": ["Wait"],
            "acknowledged_risks": [], "decisive_reasons": [],
            "confluence": {"trend_1d": "NEUTRAL", "momentum_4h": "NEUTRAL",
                          "levels_30m": "NEUTRAL", "derivatives": "NEUTRAL", "aligned_layers": 0},
        }
        judge_decision = self._validate_agent_output(judge_raw, JUDGE_SCHEMA, "Judge", defaults=judge_defaults)
        self._safe_filter_tags(judge_decision, valid_tags, "Judge (replay)")
        validate_judge_confluence(judge_decision, feature_dict)
        self._stamp_validated_output(judge_decision, "Judge (replay)")

        # v40.0: Use shared alignment enforcement (replaces inline copy)
        self._enforce_alignment_cap(judge_decision, judge_decision.get("confluence", {}), dim_scores=dim_scores)

        # Phase 2.5: Entry Timing (if actionable)
        judge_action = judge_decision.get("decision", "HOLD")
        if judge_action in ("LONG", "SHORT"):
            et_system = prompt_overrides.get("entry_timing_system",
                                              self._build_et_feature_system_prompt(adx_1d, tags_ref))
            et_user = json.dumps({
                "_scores": dim_scores,
                "features": feature_dict,
                "judge_decision": judge_action,
                "judge_confidence": judge_decision.get("confidence", "LOW"),
                "judge_rationale": judge_decision.get("_raw_rationale", judge_decision.get("rationale", "")),
                "_memory": memory_text[:_MEMORY_PROMPT_MAX_CHARS] if memory_text else "",
            }, default=str)

            et_raw = self._extract_json_with_retry(
                messages=[
                    {"role": "system", "content": et_system},
                    {"role": "user", "content": et_user},
                ],
                temperature=temperature,
                trace_label="Entry Timing (replay)",
                use_json_mode=True,
                seed=seed,
            ) or {}

            et_defaults = {
                "timing_verdict": "ENTER", "timing_quality": "FAIR",
                "adjusted_confidence": judge_decision.get("confidence", "LOW"),
                "counter_trend_risk": "NONE", "alignment": "MODERATE",
                "decisive_reasons": [], "reason": "Parse failure",
            }
            timing_assessment = self._validate_agent_output(et_raw, ENTRY_TIMING_SCHEMA, "Entry Timing",
                                                             defaults=et_defaults)
            self._safe_filter_tags(timing_assessment, valid_tags, "Entry Timing (replay)")
            self._stamp_validated_output(timing_assessment, "Entry Timing (replay)")

            # Apply timing verdict
            if timing_assessment.get("timing_verdict") == "REJECT":
                judge_decision = dict(judge_decision)
                judge_decision["_timing_original_signal"] = judge_action
                judge_decision["decision"] = "HOLD"
                judge_decision["_timing_rejected"] = True
                judge_decision["confidence"] = "LOW"

            # Confidence can only decrease
            conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
            adj_conf = timing_assessment.get("adjusted_confidence", "LOW")
            judge_conf = judge_decision.get("confidence", "LOW")
            if conf_rank.get(adj_conf, 0) < conf_rank.get(judge_conf, 0):
                judge_decision = dict(judge_decision)
                judge_decision["confidence"] = adj_conf

            judge_decision["_timing_assessment"] = timing_assessment
        else:
            timing_assessment = {
                "timing_verdict": "N/A", "timing_quality": "N/A",
                "adjusted_confidence": judge_decision.get("confidence", "LOW"),
                "counter_trend_risk": "NONE", "alignment": "N/A",
                "reason": "Non-actionable signal",
            }

        # Phase 3: Risk Manager
        risk_system = prompt_overrides.get("risk_system",
                                            self._build_risk_feature_system_prompt(adx_1d, tags_ref))
        risk_user = json.dumps({
            "_scores": dim_scores,
            "features": feature_dict,
            "proposed_action": judge_decision.get("decision", "HOLD"),
            "proposed_confidence": judge_decision.get("confidence", "LOW"),
            "judge_rationale": judge_decision.get("_raw_rationale", judge_decision.get("rationale", "")),
            "_memory": memory_text[:_MEMORY_PROMPT_MAX_CHARS] if memory_text else "",
        }, default=str)

        risk_raw = self._extract_json_with_retry(
            messages=[
                {"role": "system", "content": risk_system},
                {"role": "user", "content": risk_user},
            ],
            temperature=temperature,
            trace_label="Risk Manager (replay)",
            use_json_mode=True,
            seed=seed,
        ) or {}

        risk_defaults = {
            "signal": "HOLD", "risk_appetite": "NORMAL",
            "position_risk": "FULL_SIZE", "market_structure_risk": "NORMAL",
            "risk_factors": [], "reason": "Parse failure",
        }
        risk_result = self._validate_agent_output(risk_raw, RISK_SCHEMA, "Risk Manager",
                                                   defaults=risk_defaults)
        self._safe_filter_tags(risk_result, valid_tags, "Risk Manager (replay)")
        self._stamp_validated_output(risk_result, "Risk Manager (replay)")

        # Assemble final result
        final = {
            "signal": risk_result.get("signal", "HOLD"),
            "confidence": judge_decision.get("confidence", "LOW"),
            "risk_level": risk_result.get("market_structure_risk", "NORMAL"),
            "risk_appetite": risk_result.get("risk_appetite", "NORMAL"),
            "reason": risk_result.get("reason", ""),
            "debate_summary": debate_summary,
            "judge_decision": judge_decision,
            "_timing_assessment": timing_assessment,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            # v27.0 Replay metadata
            "replay_metadata": {
                "replay": True,
                "source_snapshot_ts": feature_dict.get("_snapshot_ts", None),
                "temperature": temperature,
                "seed": seed,
                "prompt_version": prompt_version or "current",
                "feature_version": feature_dict.get("_feature_version", FEATURE_VERSION),
            },
        }

        if judge_decision.get("_timing_rejected"):
            final["_timing_rejected"] = True
            final["_timing_original_signal"] = judge_decision.get("_timing_original_signal")

        return final

    # =========================================================================
    # v27.0: Feature-driven prompt builders (for replay and future migration)
    # =========================================================================

    @staticmethod
    def _build_bull_feature_system_prompt(adx_1d: float, tags_ref: str) -> str:
        """Build Bull Analyst system prompt for feature-driven mode."""
        from agents.prompt_constants import INDICATOR_KNOWLEDGE_BRIEF

        if adx_1d >= 40:
            role = (
                "You are a Bull Analyst assessing trend health and entry timing. "
                "The market is in a STRONG TREND (ADX>=40). Focus on: "
                "1) Is the trend still healthy? 2) Is current price a good entry? "
                "3) What extension/exhaustion risks exist?"
            )
        else:
            role = (
                "You are a Bull Analyst evaluating evidence for LONG. "
                "Construct the strongest bullish case from the feature data."
            )

        return f"""🔴 LANGUAGE RULE (MANDATORY): ALL text fields (reasoning, summary) MUST use Chinese-English mixed output (中文为主体，技术术语保留英文). Pure English output is FORBIDDEN. 纯英文输出将被系统拒绝。

{role}

{INDICATOR_KNOWLEDGE_BRIEF}
INPUT: JSON with `_scores` (pre-computed dimensional assessment) + `features` (raw data).
START by reading `_scores` for dimensional market data — trend alignment,
momentum quality, order flow direction, vol/extension risk. Analyze each dimension
independently, then form your own directional assessment from raw features.
NOTE: `_scores.net` shows pre-computed consensus but may lag in transitioning markets.
Form your own view FIRST, then check against net.

AVAILABLE TAGS:
{tags_ref}

RULES:
1. FIRST fill "reasoning" (max 500 chars, 中英混输) with your step-by-step analysis.
   Apply the interpretation rules above — e.g. check RSI Cardwell ranges if ADX>40,
   discount MACD if ADX<25, etc. This reasoning improves your tag selection quality.
   "summary" 字段也用中英混输 (1-2 句，技术术语保留英文)。
2. THEN select evidence and risk_flags ONLY from AVAILABLE TAGS
3. Do NOT use feature dictionary keys (e.g. adx_1d_trend_5bar) as tags
4. Each evidence tag must be justified by feature values
5. conviction 0.0-1.0: proportion of features supporting LONG
6. risk_flags: tags that WEAKEN the LONG case
7. summary: 1-2 sentence human-readable argument (max 200 chars)
8. NEUTRAL DATA: When a data category (derivatives, sentiment, orderbook) shows
   neutral/non-actionable readings, STILL select the neutral tag (e.g. FR_IGNORED,
   SENTIMENT_NEUTRAL, OBI_BALANCED) in evidence or risk_flags to confirm analysis.
   Omitting ALL tags for a data category = you did not analyze it.

⚠️ 语言: reasoning 和 summary 必须用**中英混输** (中文为主，技术术语如 RSI/MACD/SMA/ATR 保留英文)。禁止纯英文输出。
示例: "4H RSI 从超卖区反弹，MACD histogram 转正，配合 30M SMA 金叉确认多头动能。"

OUTPUT: JSON only.
{{"reasoning": "...", "evidence": [...], "risk_flags": [...], "conviction": 0.xx, "summary": "..."}}"""

    @staticmethod
    def _build_bear_feature_system_prompt(adx_1d: float, tags_ref: str) -> str:
        """Build Bear Analyst system prompt for feature-driven mode."""
        from agents.prompt_constants import INDICATOR_KNOWLEDGE_BRIEF

        if adx_1d >= 40:
            role = (
                "You are a Bear Analyst assessing trend exhaustion risk. "
                "The market is in a STRONG TREND (ADX>=40). Focus on: "
                "1) Is the trend exhausting? 2) What retracement risks exist? "
                "3) Are there timing risks for new entries?"
            )
        else:
            role = (
                "You are a Bear Analyst evaluating evidence for SHORT/caution. "
                "Construct the strongest bearish case from the feature data."
            )

        return f"""🔴 LANGUAGE RULE (MANDATORY): ALL text fields (reasoning, summary) MUST use Chinese-English mixed output (中文为主体，技术术语保留英文). Pure English output is FORBIDDEN. 纯英文输出将被系统拒绝。

{role}

{INDICATOR_KNOWLEDGE_BRIEF}
INPUT: JSON with `_scores` (pre-computed dimensional assessment) + `features` (raw data).
START by reading `_scores` for dimensional market data — trend alignment,
momentum quality, order flow direction, vol/extension risk. Analyze each dimension
independently, then form your own directional assessment from raw features.
NOTE: `_scores.net` shows pre-computed consensus but may lag in transitioning markets.
Form your own view FIRST, then check against net.

AVAILABLE TAGS:
{tags_ref}

RULES:
1. FIRST fill "reasoning" (max 500 chars, 中英混输) with your step-by-step analysis.
   Apply the interpretation rules above — e.g. check RSI Cardwell ranges if ADX>40,
   discount MACD if ADX<25, etc. This reasoning improves your tag selection quality.
   "summary" 字段也用中英混输 (1-2 句，技术术语保留英文)。
2. THEN select evidence and risk_flags ONLY from AVAILABLE TAGS
3. Do NOT use feature dictionary keys (e.g. adx_1d_trend_5bar) as tags
4. Each evidence tag must be justified by feature values
5. conviction 0.0-1.0: proportion of features supporting SHORT/caution
6. risk_flags: tags that WEAKEN the bear case
7. summary: 1-2 sentence human-readable argument (max 200 chars)
8. NEUTRAL DATA: When a data category (derivatives, sentiment, orderbook) shows
   neutral/non-actionable readings, STILL select the neutral tag (e.g. FR_IGNORED,
   SENTIMENT_NEUTRAL, OBI_BALANCED) in evidence or risk_flags to confirm analysis.
   Omitting ALL tags for a data category = you did not analyze it.

⚠️ 语言: reasoning 和 summary 必须用**中英混输** (中文为主，技术术语如 RSI/MACD/SMA/ATR 保留英文)。禁止纯英文输出。
示例: "1D 趋势偏空但 4H 形成 higher low，OI 增加配合 CVD 转正暗示空头回补。"

OUTPUT: JSON only.
{{"reasoning": "...", "evidence": [...], "risk_flags": [...], "conviction": 0.xx, "summary": "..."}}"""

    @staticmethod
    def _build_judge_feature_system_prompt(adx_1d: float, tags_ref: str) -> str:
        """Build Judge system prompt for feature-driven mode."""
        from agents.prompt_constants import INDICATOR_KNOWLEDGE_BRIEF

        return f"""🔴 LANGUAGE RULE (MANDATORY): ALL text fields (reasoning, rationale, strategic_actions) MUST use Chinese-English mixed output (中文为主体，技术术语保留英文). Pure English output is FORBIDDEN. 纯英文输出将被系统拒绝。

You are a Judge evaluating Bull vs Bear structured evidence.

{INDICATOR_KNOWLEDGE_BRIEF}
INPUT: JSON with `_scores` (pre-computed dimensional assessment) + `features` + Bull/Bear evidence.
START by independently evaluating each `_scores` dimension (trend, momentum, order_flow)
and the Bull vs Bear evidence. Form your own confluence assessment from raw features.
`_scores.net` is a simple average that may miss regime transitions — your judgment supersedes it.
If `_scores.regime_transition` is active, pay special attention to leading indicator (order_flow)
direction, which may be ahead of lagging trend indicators.

AVAILABLE TAGS:
{tags_ref}

IMPORTANT: Only use tags from the AVAILABLE TAGS list. Do NOT use feature dictionary keys as tags.

STEP 1: Fill "reasoning" (max 500 chars, 中英混输) with your confluence analysis.
  Apply interpretation rules — e.g. discount MACD signals if ADX<25,
  apply Cardwell RSI ranges if ADX>40, weight Layer 1 (trend) > Layer 2 > Layer 3.
  "rationale" 字段也用中英混输 (2-4 句，技术术语保留英文)。
STEP 2: Evaluate each confluence layer (trend_1d, momentum_4h, levels_30m, derivatives)
STEP 3: Count aligned layers -> confidence mapping:
  - 3-4 aligned: HIGH
  - 2 aligned: MEDIUM
  - 0-1 aligned: LOW / HOLD
STEP 4: Select decisive_reasons (top tags) and acknowledged_risks (top risk tags)
STEP 5: Write rationale (2-4 sentences) and strategic_actions (1-3 items)

⚠️ 语言: reasoning 和 rationale 必须用**中英混输** (中文为主，技术术语如 RSI/MACD/SMA/ATR/R/R 保留英文)。禁止纯英文输出。
示例 rationale: "4H 多头动能强劲，成交量配合 SMA 交叉确认入场信号，但 1D 趋势偏空且 extension 偏高，需控制仓位。"

OUTPUT: JSON only.
{{"reasoning": "...", "confluence": {{"trend_1d": "BULLISH|BEARISH|NEUTRAL", "momentum_4h": "...", "levels_30m": "...", "derivatives": "...", "aligned_layers": N}}, "decision": "LONG|SHORT|HOLD", "winning_side": "BULL|BEAR|TIE", "confidence": "HIGH|MEDIUM|LOW", "decisive_reasons": [...], "acknowledged_risks": [...], "rationale": "...", "strategic_actions": [...]}}"""

    @staticmethod
    def _build_et_feature_system_prompt(adx_1d: float, tags_ref: str) -> str:
        """Build Entry Timing Agent system prompt for feature-driven mode."""
        from agents.prompt_constants import INDICATOR_KNOWLEDGE_BRIEF

        return f"""🔴 LANGUAGE RULE (MANDATORY): ALL text fields (reasoning, reason) MUST use Chinese-English mixed output (中文为主体，技术术语保留英文). Pure English output is FORBIDDEN. 纯英文输出将被系统拒绝。

You are an Entry Timing Specialist evaluating whether NOW is optimal for entry.

{INDICATOR_KNOWLEDGE_BRIEF}
INPUT: JSON with `_scores` (pre-computed dimensional assessment) + `features` + Judge decision.
START by reading `_scores` for vol/extension risk and momentum quality — these directly
inform your timing verdict. Use `_scores.trend` to gauge alignment strength.

RULES:
- You CANNOT change the Judge's direction (LONG/SHORT stands)
- You CAN lower confidence (never upgrade)
- You CAN REJECT timing -> signal becomes HOLD
- Counter-trend + ADX>40 + no 30M reversal = REJECT
  ⚠️ CRITICAL: ADX is a LAGGING indicator — high ADX reflects PAST trend strength, NOT current direction.
  Before classifying a trade as "counter-trend", check CURRENT direction signals:
  • If `_scores.trend` direction MATCHES signal direction → NOT counter-trend (trend already shifted)
  • If `trend_reversal.active=True` in features → trend is reversing, signal WITH new direction is trend-following
  • If DI direction (adx_direction_1d/4h) has flipped to match signal → old ADX>40 is residual, NOT counter-trend
  Only apply counter-trend REJECT when BOTH ADX>40 AND current DI/trend direction OPPOSES the signal.

AVAILABLE TAGS:
{tags_ref}

IMPORTANT: Only use tags from the AVAILABLE TAGS list. Do NOT use feature dictionary keys as tags.

STEP 1: Fill "reasoning" (max 500 chars, 中英混输) with your 4-dimension analysis.
  Apply interpretation rules — e.g. in strong trends (ADX>40), extension 3-5 ATR
  is NORMAL, S/R bounce rate only ~25%. Use Cardwell RSI ranges for timing.
  "reason" 字段也用中英混输 (2-3 句，技术术语保留英文)。
STEP 2: Evaluate 4 dimensions:
  1. MTF alignment: STRONG (3 layers) / MODERATE (2) / WEAK (0-1)
  2. 30M execution timing: RSI, MACD histogram, DI direction
  3. Counter-trend risk: based on ADX AND current DI direction vs signal (not just historical ADX level)
  4. Extension & Volatility: extreme levels warrant downgrade

⚠️ 语言: reasoning 和 reason 必须用**中英混输** (中文为主，技术术语如 RSI/MACD/SMA/ATR 保留英文)。禁止纯英文输出。
示例 reason: "30M RSI 从超卖反弹配合 MACD histogram 转正，MTF 3 层一致，入场时机良好。"

OUTPUT: JSON only.
{{"reasoning": "...", "timing_verdict": "ENTER|REJECT", "timing_quality": "OPTIMAL|GOOD|FAIR|POOR", "adjusted_confidence": "HIGH|MEDIUM|LOW", "counter_trend_risk": "NONE|LOW|HIGH|EXTREME", "alignment": "STRONG|MODERATE|WEAK", "decisive_reasons": [...], "reason": "..."}}"""

    @staticmethod
    def _build_risk_feature_system_prompt(adx_1d: float, tags_ref: str) -> str:
        """Build Risk Manager system prompt for feature-driven mode."""
        from agents.prompt_constants import INDICATOR_KNOWLEDGE_BRIEF

        return f"""🔴 LANGUAGE RULE (MANDATORY): ALL text fields (reasoning, reason) MUST use Chinese-English mixed output (中文为主体，技术术语保留英文). Pure English output is FORBIDDEN. 纯英文输出将被系统拒绝。

You are a Risk Manager assessing risk and position sizing.

{INDICATOR_KNOWLEDGE_BRIEF}
INPUT: JSON with `_scores` (pre-computed dimensional assessment) + `features` + proposed action.
START by reading `_scores.vol_ext_risk` and `_scores.risk_env` — these directly inform your
risk appetite and position sizing. Review all `_scores` dimensions for risk context.

RULES:
- Trust Judge's direction & confidence (do NOT modify confidence)
- Express risk via risk_appetite: AGGRESSIVE / NORMAL / CONSERVATIVE
- Only 4 extreme cases allow veto to HOLD: |FR|>0.10%, liquidity failure, S/R trap <2ATR, liquidation buffer <5%

AVAILABLE TAGS:
{tags_ref}

IMPORTANT: Only use tags from the AVAILABLE TAGS list for risk_factors. Do NOT use feature dictionary keys as tags.

STEP 1: Fill "reasoning" (max 500 chars, 中英混输) with your risk assessment.
  Apply interpretation rules — e.g. FR 0.01-0.03% is NORMAL in bull markets,
  HIGH volatility → reduce position size, low volume → unreliable signals.
  "reason" 字段也用中英混输 (2-3 句，技术术语保留英文)。
STEP 2: Evaluate:
  1. Volatility regime -> position size guidance
  2. Funding rate -> cost/risk assessment
  3. Liquidation buffer -> safety check
  4. S/R proximity -> position viability

⚠️ 语言: reasoning 和 reason 必须用**中英混输** (中文为主，技术术语如 FR/ATR/R/R/OI 保留英文)。禁止纯英文输出。
示例 reason: "逆势 LONG 在高风险环境下需缩减仓位，FR 偏高增加持仓成本，但清算缓冲充足。"

OUTPUT: JSON only.
{{"reasoning": "...", "signal": "LONG|SHORT|CLOSE|HOLD|REDUCE", "risk_appetite": "AGGRESSIVE|NORMAL|CONSERVATIVE", "position_risk": "FULL_SIZE|REDUCED|MINIMAL|REJECT", "market_structure_risk": "NORMAL|ELEVATED|HIGH|EXTREME", "risk_factors": [...], "reason": "..."}}"""

    def _format_structured_memories(self, memory_features: List[Dict]) -> str:
        """Format structured memory features back to text for prompt injection."""
        if not memory_features:
            return ""
        lines = []
        for m in memory_features[:5]:
            signal = m.get("signal", "?")
            grade = m.get("grade", "?")
            pnl = m.get("pnl_pct", 0)
            tags = ", ".join(m.get("key_lesson_tags", []))
            lines.append(f"  {signal} → {pnl:+.1f}% [{grade}] Tags: {tags}")
        return "\n".join(lines)

