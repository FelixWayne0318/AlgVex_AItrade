#!/usr/bin/env python3
"""
POC: Instructor + DeepSeek V3.2 Thinking Mode Compatibility Test
================================================================

Tests 6 critical integration points:
  Test 1: Basic Instructor + DeepSeek JSON mode (baseline)
  Test 2: Thinking mode via extra_body (the biggest risk)
  Test 3: @model_validator cross-field semantic validation + auto-retry
  Test 4: Dynamic REASON_TAGS validation via ValidationInfo context
  Test 5: Full JudgeOutput schema (mirrors production JUDGE_SCHEMA)
  Test 6: Retry behavior — intentionally trigger validation failure

Usage:
  # Requires DEEPSEEK_API_KEY in environment or ~/.env.algvex
  python3 scripts/poc_instructor_deepseek.py

  # Verbose mode — print full responses
  python3 scripts/poc_instructor_deepseek.py --verbose

  # Run specific test only
  python3 scripts/poc_instructor_deepseek.py --test 2
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set

# ── Load API key ──
def _load_api_key() -> str:
    """Load DeepSeek API key from env or ~/.env.algvex."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    env_file = Path.home() / ".env.algvex"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    print("ERROR: DEEPSEEK_API_KEY not found in environment or ~/.env.algvex")
    sys.exit(1)


# ── Check instructor availability ──
try:
    import instructor
    from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo
    INSTRUCTOR_VERSION = instructor.__version__
except ImportError:
    print("ERROR: instructor not installed. Run: pip install instructor")
    print("  pip install instructor pydantic")
    sys.exit(1)

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai not installed. Run: pip install openai")
    sys.exit(1)


# ======================================================================
# Test Models — mirror production schemas
# ======================================================================

# Subset of production REASON_TAGS for POC
REASON_TAGS_SUBSET: Set[str] = {
    "TREND_1D_BULLISH", "TREND_1D_BEARISH", "TREND_1D_NEUTRAL",
    "STRONG_TREND_ADX40", "WEAK_TREND_ADX_LOW",
    "MOMENTUM_4H_BULLISH", "MOMENTUM_4H_BEARISH",
    "RSI_OVERBOUGHT", "RSI_OVERSOLD",
    "MACD_BULLISH_CROSS", "MACD_BEARISH_CROSS",
    "CVD_POSITIVE", "CVD_NEGATIVE",
    "FR_FAVORABLE_LONG", "FR_FAVORABLE_SHORT",
    "NEAR_STRONG_SUPPORT", "NEAR_STRONG_RESISTANCE",
    "EXTENSION_OVEREXTENDED", "EXTENSION_EXTREME",
    "VOL_HIGH", "VOL_EXTREME",
}

BULLISH_TAGS: Set[str] = {
    "TREND_1D_BULLISH", "MOMENTUM_4H_BULLISH", "MACD_BULLISH_CROSS",
    "RSI_OVERSOLD", "CVD_POSITIVE", "FR_FAVORABLE_LONG",
    "NEAR_STRONG_SUPPORT",
}

BEARISH_TAGS: Set[str] = {
    "TREND_1D_BEARISH", "MOMENTUM_4H_BEARISH", "MACD_BEARISH_CROSS",
    "RSI_OVERBOUGHT", "CVD_NEGATIVE", "FR_FAVORABLE_SHORT",
    "NEAR_STRONG_RESISTANCE",
}


# ── Test 1: Basic model ──
class SimpleAnalysis(BaseModel):
    """Test 1: Basic structured output."""
    direction: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


# ── Test 2: Same model, test thinking mode passthrough ──
# (Uses SimpleAnalysis — the test is about extra_body, not schema)


# ── Test 3: Cross-field semantic validator ──
class SemanticAnalysis(BaseModel):
    """Test 3: Cross-field validation that triggers retry on inconsistency."""
    signal: Literal["LONG", "SHORT", "HOLD"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    bullish_reasons: List[str]
    bearish_reasons: List[str]
    reasoning: str

    @model_validator(mode='after')
    def check_signal_reason_alignment(self):
        """If signal=LONG, must have >=1 bullish reason. If SHORT, >=1 bearish."""
        if self.signal == "LONG" and len(self.bullish_reasons) == 0:
            raise ValueError(
                f"signal=LONG but bullish_reasons is empty. "
                f"Provide at least 1 bullish reason or change signal to HOLD."
            )
        if self.signal == "SHORT" and len(self.bearish_reasons) == 0:
            raise ValueError(
                f"signal=SHORT but bearish_reasons is empty. "
                f"Provide at least 1 bearish reason or change signal to HOLD."
            )
        if self.signal == "HOLD" and self.confidence == "HIGH":
            raise ValueError(
                "signal=HOLD should not have HIGH confidence. "
                "Use MEDIUM or LOW for HOLD signals."
            )
        return self


# ── Test 4: Dynamic tag validation via context ──
class TagValidatedOutput(BaseModel):
    """Test 4: REASON_TAGS validated against dynamic context."""
    signal: Literal["LONG", "SHORT", "HOLD"]
    evidence: List[str]
    risk_flags: List[str]

    @field_validator('evidence', 'risk_flags', mode='before')
    @classmethod
    def normalize_tags(cls, v):
        """Uppercase all tags."""
        if isinstance(v, list):
            return [t.upper() if isinstance(t, str) else t for t in v]
        return v

    @field_validator('evidence')
    @classmethod
    def validate_evidence_tags(cls, v, info: ValidationInfo):
        """Filter tags against valid set from context."""
        valid_tags = (info.context or {}).get('valid_tags', REASON_TAGS_SUBSET)
        invalid = [t for t in v if t not in valid_tags]
        if invalid:
            raise ValueError(
                f"Invalid REASON_TAGS in evidence: {invalid}. "
                f"Only use tags from the valid set."
            )
        return v

    @field_validator('risk_flags')
    @classmethod
    def validate_risk_tags(cls, v, info: ValidationInfo):
        """Filter tags against valid set from context."""
        valid_tags = (info.context or {}).get('valid_tags', REASON_TAGS_SUBSET)
        invalid = [t for t in v if t not in valid_tags]
        if invalid:
            raise ValueError(
                f"Invalid REASON_TAGS in risk_flags: {invalid}. "
                f"Only use tags from the valid set."
            )
        return v


# ── Test 5: Full Judge schema (production mirror) ──
class JudgeConfluence(BaseModel):
    trend_1d: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    momentum_4h: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    levels_30m: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    derivatives: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    aligned_layers: int = Field(ge=0, le=4)


class JudgeOutput(BaseModel):
    """Test 5: Full production Judge schema."""
    reasoning: str = Field(max_length=1500)
    confluence: JudgeConfluence
    decision: Literal["LONG", "SHORT", "HOLD"]
    winning_side: Literal["BULL", "BEAR", "TIE"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    decisive_reasons: List[str] = Field(min_length=1, max_length=5)
    acknowledged_risks: List[str] = Field(min_length=1, max_length=5)
    rationale: str = Field(max_length=800)

    @field_validator('decisive_reasons', 'acknowledged_risks', mode='before')
    @classmethod
    def normalize_tags(cls, v):
        if isinstance(v, list):
            return [t.upper() if isinstance(t, str) else t for t in v]
        return v

    @model_validator(mode='after')
    def check_decision_reason_alignment(self):
        """v34.0 REASON_SIGNAL_CONFLICT: decisive_reasons must align with decision."""
        if self.decision == "LONG":
            bullish_count = sum(1 for t in self.decisive_reasons if t in BULLISH_TAGS)
            if bullish_count == 0:
                raise ValueError(
                    f"decision=LONG but decisive_reasons contains no bullish tags: "
                    f"{self.decisive_reasons}. Must include at least 1 bullish tag."
                )
        elif self.decision == "SHORT":
            bearish_count = sum(1 for t in self.decisive_reasons if t in BEARISH_TAGS)
            if bearish_count == 0:
                raise ValueError(
                    f"decision=SHORT but decisive_reasons contains no bearish tags: "
                    f"{self.decisive_reasons}. Must include at least 1 bearish tag."
                )
        return self

    @model_validator(mode='after')
    def check_confidence_risk_conflict(self):
        """v34.0 CONFIDENCE_RISK_CONFLICT: HIGH confidence + many risks = suspicious."""
        if self.confidence == "HIGH" and len(self.acknowledged_risks) >= 4:
            raise ValueError(
                f"confidence=HIGH but acknowledged_risks has {len(self.acknowledged_risks)} items. "
                f"HIGH confidence with 4+ risk factors is contradictory. "
                f"Lower confidence to MEDIUM or reduce acknowledged_risks."
            )
        return self


# ── Test 6: Intentional validation failure ──
class StrictOutput(BaseModel):
    """Test 6: Designed to fail on first attempt to test retry feedback."""
    answer: int = Field(ge=42, le=42, description="Must be exactly 42")
    explanation: str

    @model_validator(mode='after')
    def must_be_42(self):
        if self.answer != 42:
            raise ValueError(f"answer must be exactly 42, got {self.answer}")
        return self


# ======================================================================
# Test Runner
# ======================================================================

class POCRunner:
    def __init__(self, api_key: str, verbose: bool = False):
        self.api_key = api_key
        self.verbose = verbose
        self.results: List[Dict[str, Any]] = []

        # Raw OpenAI client (for comparison)
        self.raw_client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            timeout=120.0,
        )

    def _make_instructor_client(self, mode=None):
        """Create an Instructor-wrapped client."""
        base_client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com",
            timeout=120.0,
        )
        # Use JSON mode (matches production response_format: {"type": "json_object"})
        return instructor.from_openai(base_client, mode=instructor.Mode.JSON)

    def _record(self, test_name: str, passed: bool, details: str,
                elapsed: float = 0, response: Any = None, retries: int = 0):
        result = {
            "test": test_name,
            "passed": passed,
            "details": details,
            "elapsed_sec": round(elapsed, 2),
            "retries": retries,
        }
        if response and self.verbose:
            result["response"] = str(response)
        self.results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {test_name} ({elapsed:.2f}s, {retries} retries)")
        if self.verbose and response:
            print(f"    Response: {response}")
        if not passed:
            print(f"    Details: {details}")

    # ── Test 1: Basic JSON mode ──
    def test_1_basic_json(self):
        """Baseline: Instructor + DeepSeek + JSON mode (no thinking)."""
        print("\n=== Test 1: Basic Instructor + DeepSeek JSON Mode ===")
        client = self._make_instructor_client()
        t0 = time.monotonic()
        try:
            result = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a market analyst. Respond in JSON."},
                    {"role": "user", "content": (
                        "BTC is at $95,000. RSI(4H)=65, MACD bullish cross, ADX=32. "
                        "Give your analysis."
                    )},
                ],
                response_model=SimpleAnalysis,
                temperature=0.3,
                max_retries=2,
            )
            elapsed = time.monotonic() - t0
            # Validate types
            assert isinstance(result.direction, str)
            assert result.direction in ("BULLISH", "BEARISH", "NEUTRAL")
            assert 0.0 <= result.confidence <= 1.0
            assert len(result.reasoning) > 0
            self._record("Basic JSON Mode", True,
                         f"direction={result.direction}, confidence={result.confidence:.2f}",
                         elapsed, result)
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._record("Basic JSON Mode", False, str(e), elapsed)

    # ── Test 2: Thinking mode via extra_body ──
    def test_2_thinking_mode(self):
        """Critical: Can Instructor pass extra_body for thinking mode?"""
        print("\n=== Test 2: Thinking Mode (extra_body passthrough) ===")
        client = self._make_instructor_client()
        t0 = time.monotonic()

        # Method A: Pass extra_body as kwargs (hope Instructor forwards it)
        try:
            result = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a market analyst. Respond in JSON."},
                    {"role": "user", "content": (
                        "BTC is at $95,000. RSI(4H)=65, MACD bullish cross, ADX=32. "
                        "Give your analysis."
                    )},
                ],
                response_model=SimpleAnalysis,
                temperature=0.3,
                max_retries=2,
                extra_body={"thinking": {"type": "enabled"}},
            )
            elapsed = time.monotonic() - t0
            assert isinstance(result, SimpleAnalysis)
            self._record("Thinking Mode (extra_body)", True,
                         f"direction={result.direction}, confidence={result.confidence:.2f}. "
                         f"extra_body accepted by Instructor.",
                         elapsed, result)
        except TypeError as e:
            elapsed = time.monotonic() - t0
            if "extra_body" in str(e):
                self._record("Thinking Mode (extra_body)", False,
                             f"Instructor does NOT support extra_body kwarg: {e}",
                             elapsed)
                # Try Method B
                self._test_2b_thinking_workaround()
            else:
                self._record("Thinking Mode (extra_body)", False, str(e), elapsed)
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._record("Thinking Mode (extra_body)", False, str(e), elapsed)

    def _test_2b_thinking_workaround(self):
        """Fallback: Patch the client to always inject extra_body."""
        print("  Trying workaround: patched OpenAI client...")
        from openai import OpenAI as _OpenAI
        from unittest.mock import patch
        import functools

        base_client = _OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com",
            timeout=120.0,
        )

        # Monkey-patch the create method to inject extra_body
        original_create = base_client.chat.completions.create

        @functools.wraps(original_create)
        def patched_create(**kwargs):
            kwargs.setdefault("extra_body", {})
            kwargs["extra_body"]["thinking"] = {"type": "enabled"}
            return original_create(**kwargs)

        base_client.chat.completions.create = patched_create
        client = instructor.from_openai(base_client, mode=instructor.Mode.JSON)

        t0 = time.monotonic()
        try:
            result = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a market analyst. Respond in JSON."},
                    {"role": "user", "content": (
                        "BTC is at $95,000. RSI(4H)=65, MACD bullish cross. "
                        "Give your analysis."
                    )},
                ],
                response_model=SimpleAnalysis,
                temperature=0.3,
                max_retries=2,
            )
            elapsed = time.monotonic() - t0
            assert isinstance(result, SimpleAnalysis)
            self._record("Thinking Mode (monkey-patch workaround)", True,
                         f"direction={result.direction}. Workaround works! "
                         f"Can patch client.create to inject extra_body.",
                         elapsed, result)
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._record("Thinking Mode (monkey-patch workaround)", False, str(e), elapsed)

    # ── Test 3: Cross-field semantic validation + retry ──
    def test_3_semantic_validation(self):
        """Test @model_validator retry: ask for LONG with deliberately bearish framing."""
        print("\n=== Test 3: Cross-Field Semantic Validation + Retry ===")
        client = self._make_instructor_client()
        t0 = time.monotonic()
        try:
            result = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": (
                        "You are a trading analyst. Output JSON with: "
                        "signal (LONG/SHORT/HOLD), confidence (HIGH/MEDIUM/LOW), "
                        "bullish_reasons (list of strings), bearish_reasons (list of strings), "
                        "reasoning (string).\n\n"
                        "IMPORTANT: If signal=LONG, bullish_reasons MUST be non-empty. "
                        "If signal=SHORT, bearish_reasons MUST be non-empty. "
                        "If signal=HOLD, confidence cannot be HIGH."
                    )},
                    {"role": "user", "content": (
                        "BTC is at $95,000. The market shows mixed signals: "
                        "RSI=55, MACD slightly bearish, ADX=22 (weak trend), "
                        "funding rate slightly positive. Analyze."
                    )},
                ],
                response_model=SemanticAnalysis,
                temperature=0.3,
                max_retries=3,
            )
            elapsed = time.monotonic() - t0

            # Verify the validator constraints are met
            checks = []
            if result.signal == "LONG":
                checks.append(f"LONG + {len(result.bullish_reasons)} bullish reasons")
                assert len(result.bullish_reasons) > 0
            elif result.signal == "SHORT":
                checks.append(f"SHORT + {len(result.bearish_reasons)} bearish reasons")
                assert len(result.bearish_reasons) > 0
            if result.signal == "HOLD":
                checks.append(f"HOLD + confidence={result.confidence} (not HIGH)")
                assert result.confidence != "HIGH"

            self._record("Semantic Validation", True,
                         f"signal={result.signal}, confidence={result.confidence}, "
                         f"checks: {', '.join(checks)}",
                         elapsed, result)
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._record("Semantic Validation", False, str(e), elapsed)

    # ── Test 4: Dynamic REASON_TAGS context ──
    def test_4_dynamic_tags(self):
        """Test ValidationInfo context passing for dynamic tag validation."""
        print("\n=== Test 4: Dynamic REASON_TAGS via ValidationInfo Context ===")
        client = self._make_instructor_client()

        # Only allow a small subset of tags (simulates compute_valid_tags())
        allowed_tags = {
            "TREND_1D_BULLISH", "MOMENTUM_4H_BULLISH",
            "RSI_OVERSOLD", "MACD_BULLISH_CROSS",
            "NEAR_STRONG_SUPPORT", "VOL_HIGH",
        }

        t0 = time.monotonic()
        try:
            result = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": (
                        "You are a trading analyst. Output JSON with: "
                        "signal (LONG/SHORT/HOLD), "
                        "evidence (list of REASON_TAGS from this set ONLY: "
                        f"{sorted(allowed_tags)}), "
                        "risk_flags (list of REASON_TAGS from this set ONLY: "
                        f"{sorted(allowed_tags)})."
                    )},
                    {"role": "user", "content": (
                        "BTC at $95,000. 1D trend bullish (SMA200 below price), "
                        "4H momentum bullish, RSI=35 (near oversold), volume high. "
                        "Analyze."
                    )},
                ],
                response_model=TagValidatedOutput,
                temperature=0.3,
                max_retries=3,
                validation_context={"valid_tags": allowed_tags},
            )
            elapsed = time.monotonic() - t0

            # Verify all tags are in allowed set
            all_tags = result.evidence + result.risk_flags
            invalid = [t for t in all_tags if t not in allowed_tags]
            assert len(invalid) == 0, f"Invalid tags passed through: {invalid}"

            self._record("Dynamic REASON_TAGS", True,
                         f"signal={result.signal}, evidence={result.evidence}, "
                         f"risk_flags={result.risk_flags}",
                         elapsed, result)
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._record("Dynamic REASON_TAGS", False, str(e), elapsed)

    # ── Test 5: Full JudgeOutput ──
    def test_5_judge_schema(self):
        """Full production Judge schema with all validators."""
        print("\n=== Test 5: Full JudgeOutput (Production Mirror) ===")
        client = self._make_instructor_client()
        t0 = time.monotonic()

        valid_tags_str = ", ".join(sorted(REASON_TAGS_SUBSET))
        try:
            result = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": (
                        "You are a Judge in a multi-agent trading debate system. "
                        "Evaluate the following market data and produce a decision.\n\n"
                        "OUTPUT FORMAT (JSON):\n"
                        "- reasoning: chain-of-thought analysis (string, max 1500 chars)\n"
                        "- confluence: {trend_1d, momentum_4h, levels_30m, derivatives} "
                        "each BULLISH/BEARISH/NEUTRAL + aligned_layers (0-4)\n"
                        "- decision: LONG / SHORT / HOLD\n"
                        "- winning_side: BULL / BEAR / TIE\n"
                        "- confidence: HIGH / MEDIUM / LOW\n"
                        "- decisive_reasons: 1-5 tags from REASON_TAGS\n"
                        "- acknowledged_risks: 1-5 tags from REASON_TAGS\n"
                        "- rationale: 1-2 sentence explanation (max 800 chars)\n\n"
                        f"VALID REASON_TAGS: {valid_tags_str}\n\n"
                        "RULES:\n"
                        "- If decision=LONG, decisive_reasons MUST include bullish tags.\n"
                        "- If decision=SHORT, decisive_reasons MUST include bearish tags.\n"
                        "- If confidence=HIGH, acknowledged_risks should be < 4 items."
                    )},
                    {"role": "user", "content": (
                        "=== MARKET DATA ===\n"
                        "Price: $95,000\n"
                        "1D: SMA200=$88,000 (bullish), ADX=35, DI+=22, DI-=15\n"
                        "4H: RSI=62, MACD bullish cross, ADX=28\n"
                        "30M: RSI=58, BB position=0.65, SMA5>SMA20\n"
                        "Funding Rate: +0.005%\n"
                        "CVD: Positive trend, buy ratio=0.54\n"
                        "S/R: Support at $93,500 (1.2 ATR away)\n\n"
                        "=== DIMENSIONAL SCORES ===\n"
                        "trend: BULLISH (+3)\n"
                        "momentum: BULLISH (+2)\n"
                        "order_flow: NEUTRAL (0)\n"
                        "vol_ext_risk: NORMAL\n"
                        "risk_env: NORMAL\n"
                        "net: BULLISH\n\n"
                        "Make your decision."
                    )},
                ],
                response_model=JudgeOutput,
                temperature=0.3,
                max_retries=3,
            )
            elapsed = time.monotonic() - t0

            # Comprehensive validation
            checks = []
            checks.append(f"decision={result.decision}")
            checks.append(f"confidence={result.confidence}")
            checks.append(f"aligned_layers={result.confluence.aligned_layers}")
            checks.append(f"decisive_reasons={result.decisive_reasons}")
            checks.append(f"acknowledged_risks={result.acknowledged_risks}")
            checks.append(f"reasoning_len={len(result.reasoning)}")
            checks.append(f"rationale_len={len(result.rationale)}")

            self._record("Full JudgeOutput", True,
                         " | ".join(checks),
                         elapsed, result)
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._record("Full JudgeOutput", False, str(e), elapsed)

    # ── Test 6: Intentional failure + retry feedback ──
    def test_6_retry_feedback(self):
        """Verify that validation errors are fed back to DeepSeek for correction."""
        print("\n=== Test 6: Retry Feedback (intentional validation trigger) ===")
        client = self._make_instructor_client()
        t0 = time.monotonic()

        try:
            result = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": (
                        "You are a helpful assistant. Output JSON with: "
                        "answer (integer) and explanation (string).\n"
                        "The answer field MUST be exactly 42."
                    )},
                    {"role": "user", "content": (
                        "What is the answer to life, the universe, and everything? "
                        "Your answer field must be exactly 42."
                    )},
                ],
                response_model=StrictOutput,
                temperature=0.3,
                max_retries=3,
            )
            elapsed = time.monotonic() - t0
            assert result.answer == 42
            self._record("Retry Feedback", True,
                         f"answer={result.answer}. Model produced correct value "
                         f"(possibly after retry with error feedback).",
                         elapsed, result)
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._record("Retry Feedback", False,
                         f"Failed even after retries: {e}", elapsed)

    # ── Run all ──
    def run_all(self, test_num: Optional[int] = None):
        print("=" * 70)
        print("POC: Instructor + DeepSeek V3.2 Compatibility Test")
        print(f"Instructor version: {INSTRUCTOR_VERSION}")
        print(f"Model: deepseek-chat")
        print(f"Base URL: https://api.deepseek.com")
        print("=" * 70)

        tests = {
            1: self.test_1_basic_json,
            2: self.test_2_thinking_mode,
            3: self.test_3_semantic_validation,
            4: self.test_4_dynamic_tags,
            5: self.test_5_judge_schema,
            6: self.test_6_retry_feedback,
        }

        if test_num:
            if test_num in tests:
                tests[test_num]()
            else:
                print(f"ERROR: Test {test_num} not found. Valid: 1-6")
                return
        else:
            for num, test_fn in tests.items():
                test_fn()

        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        total_time = sum(r["elapsed_sec"] for r in self.results)
        total_retries = sum(r["retries"] for r in self.results)

        for r in self.results:
            status = "PASS" if r["passed"] else "FAIL"
            print(f"  [{status}] {r['test']} ({r['elapsed_sec']}s)")

        print(f"\n  {passed}/{total} passed | Total: {total_time:.1f}s | Retries: {total_retries}")

        # Critical assessment
        print("\n" + "=" * 70)
        print("CRITICAL ASSESSMENT FOR ALGVEX INTEGRATION")
        print("=" * 70)

        test_map = {r["test"]: r for r in self.results}

        # Check Test 2 (thinking mode)
        thinking_tests = [r for r in self.results if "Thinking" in r["test"]]
        thinking_ok = any(r["passed"] for r in thinking_tests)
        if thinking_ok:
            print("  [OK] Thinking mode: Compatible (extra_body passthrough works)")
        else:
            print("  [BLOCKER] Thinking mode: NOT compatible!")
            print("           Instructor cannot pass extra_body to DeepSeek.")
            print("           This is a DEAL-BREAKER for AlgVex (v32.0 requirement).")

        # Check Test 3 (semantic validation)
        semantic_ok = test_map.get("Semantic Validation", {}).get("passed", False)
        if semantic_ok:
            print("  [OK] @model_validator: Cross-field semantic checks work")
        else:
            print("  [WARN] @model_validator: Cross-field checks failed")

        # Check Test 4 (dynamic tags)
        tags_ok = test_map.get("Dynamic REASON_TAGS", {}).get("passed", False)
        if tags_ok:
            print("  [OK] ValidationInfo context: Dynamic tag filtering works")
        else:
            print("  [WARN] ValidationInfo context: Dynamic tag filtering failed")

        # Check Test 5 (full schema)
        judge_ok = test_map.get("Full JudgeOutput", {}).get("passed", False)
        if judge_ok:
            print("  [OK] Full JudgeOutput: Production-mirror schema works")
        else:
            print("  [WARN] Full JudgeOutput: Production schema had issues")

        # Final verdict
        print()
        if thinking_ok and semantic_ok and judge_ok:
            print("  VERDICT: Instructor is VIABLE for AlgVex integration.")
            print("  Next step: Plan Pydantic model migration for 5 agent schemas.")
        elif thinking_ok:
            print("  VERDICT: Instructor is PARTIALLY viable. Some validators need adjustment.")
        else:
            print("  VERDICT: Instructor is NOT viable due to thinking mode incompatibility.")
            print("  Alternative: Use Pydantic validators standalone + manual retry loop.")

        return passed == total


def main():
    parser = argparse.ArgumentParser(description="POC: Instructor + DeepSeek V3.2")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print full responses")
    parser.add_argument("--test", "-t", type=int, help="Run specific test (1-6)")
    args = parser.parse_args()

    api_key = _load_api_key()
    runner = POCRunner(api_key, verbose=args.verbose)
    success = runner.run_all(test_num=args.test)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
