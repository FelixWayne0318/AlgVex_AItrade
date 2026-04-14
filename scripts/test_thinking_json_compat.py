#!/usr/bin/env python3
"""
Test: DeepSeek V3.2 thinking mode + json_object compatibility.

Verifies whether deepseek-chat can simultaneously use:
  1. response_format: {"type": "json_object"}
  2. extra_body: {"thinking": {"type": "enabled"}}

Uses a prompt structure similar to actual Bull/Bear agent prompts.
"""
import json
import os
import sys
import time

# Load API key from .env.algvex
env_path = os.path.expanduser("~/.env.algvex")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    print("ERROR: DEEPSEEK_API_KEY not found")
    sys.exit(1)

from openai import OpenAI

client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=120.0)

# ============================================================
# Test cases
# ============================================================

TESTS = [
    {
        "name": "Test 1: json_object ONLY (baseline)",
        "kwargs": {
            "model": "deepseek-chat",
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
    },
    {
        "name": "Test 2: json_object + thinking mode",
        "kwargs": {
            "model": "deepseek-chat",
            "response_format": {"type": "json_object"},
            "extra_body": {"thinking": {"type": "enabled"}},
        },
    },
    {
        "name": "Test 3: deepseek-reasoner + json_object",
        "kwargs": {
            "model": "deepseek-reasoner",
            "response_format": {"type": "json_object"},
        },
    },
    {
        "name": "Test 4: deepseek-reasoner WITHOUT json_object (control)",
        "kwargs": {
            "model": "deepseek-reasoner",
        },
    },
]

# Simplified Bull analyst prompt (mirrors actual system structure)
SYSTEM_PROMPT = """You are a Bull Analyst for BTC/USDT futures trading.
Analyze the provided data and output your analysis in JSON format.

Required JSON schema:
{
  "conviction": <float 0.0-1.0>,
  "evidence": [<list of reason tags>],
  "risk_flags": [<list of risk tags>],
  "reasoning": "<string explaining your bull case>"
}

Valid reason tags: SMA_GOLDEN_CROSS, RSI_OVERSOLD_BOUNCE, MACD_HISTOGRAM_EXPANDING,
VOLUME_ABOVE_MA, OI_INCREASING_WITH_PRICE, CVD_POSITIVE_TREND, SUPPORT_ZONE_HOLDING,
STRONG_UPTREND_ADX, EMA_BULLISH_CROSS, BB_SQUEEZE_BREAKOUT

Valid risk tags: OVEREXTENDED_PRICE, HIGH_FUNDING_RATE, BEARISH_DIVERGENCE_RSI,
RESISTANCE_ZONE_NEAR, LOW_VOLUME, EXTREME_VOLATILITY"""

USER_PROMPT = json.dumps({
    "_scores": {
        "trend": {"score": 0.65, "direction": "BULLISH", "details": "1D SMA200 slope positive, ADX=32"},
        "momentum": {"score": 0.55, "direction": "NEUTRAL", "details": "4H RSI=52, MACD slightly positive"},
        "order_flow": {"score": 0.60, "direction": "BULLISH", "details": "CVD positive, OI increasing"},
        "vol_ext_risk": {"score": 0.40, "direction": "NEUTRAL", "details": "Extension 1.8 ATR, Vol NORMAL"},
        "risk_env": {"score": 0.50, "direction": "NEUTRAL", "details": "FR 0.01%, sentiment balanced"},
        "net": {"score": 0.54, "direction": "BULLISH"},
    },
    "features": {
        "price_current": 84500.0,
        "rsi_14_4h": 52.3,
        "macd_histogram_4h": 15.2,
        "adx_14_1d": 32.1,
        "atr_14_4h": 1250.0,
        "sma_200_1d": 78500.0,
        "volume_ratio_4h": 1.15,
        "funding_rate": 0.0001,
        "oi_change_pct_24h": 2.5,
        "cvd_trend": "POSITIVE",
    },
})


def run_test(test_config):
    """Run a single test and return results."""
    name = test_config["name"]
    kwargs = test_config["kwargs"]

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT},
    ]

    try:
        t0 = time.monotonic()
        response = client.chat.completions.create(messages=messages, **kwargs)
        elapsed = time.monotonic() - t0

        content = response.choices[0].message.content
        reasoning_content = getattr(response.choices[0].message, "reasoning_content", None)

        # Check for reasoning_content in model_extra (Pydantic V2)
        if reasoning_content is None and hasattr(response.choices[0].message, "model_extra"):
            extras = response.choices[0].message.model_extra or {}
            reasoning_content = extras.get("reasoning_content")

        # Token usage
        usage = response.usage
        tokens = {}
        if usage:
            tokens = {
                "prompt": usage.prompt_tokens,
                "completion": usage.completion_tokens,
                "total": usage.total_tokens,
            }
            # Check for reasoning_tokens
            if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                details = usage.completion_tokens_details
                reasoning_tokens = getattr(details, "reasoning_tokens", None)
                if reasoning_tokens is None and hasattr(details, "model_extra"):
                    reasoning_tokens = (details.model_extra or {}).get("reasoning_tokens")
                if reasoning_tokens:
                    tokens["reasoning_tokens"] = reasoning_tokens

        # Try JSON parsing
        json_ok = False
        parsed = None
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > 0:
                parsed = json.loads(content[start:end])
                json_ok = True
        except (json.JSONDecodeError, TypeError):
            pass

        # Schema validation
        schema_ok = False
        if parsed:
            required_keys = {"conviction", "evidence", "risk_flags", "reasoning"}
            schema_ok = required_keys.issubset(parsed.keys())

        # Results
        print(f"  Status:      SUCCESS")
        print(f"  Elapsed:     {elapsed:.1f}s")
        print(f"  Tokens:      {tokens}")
        print(f"  JSON parse:  {'PASS' if json_ok else 'FAIL'}")
        print(f"  Schema:      {'PASS' if schema_ok else 'FAIL'}")

        if reasoning_content:
            preview = reasoning_content[:200].replace("\n", " ")
            print(f"  Thinking:    YES ({len(reasoning_content)} chars)")
            print(f"  Think preview: {preview}...")
        else:
            print(f"  Thinking:    NO (no reasoning_content)")

        if parsed:
            print(f"  Conviction:  {parsed.get('conviction')}")
            print(f"  Evidence:    {parsed.get('evidence')}")
            print(f"  Risk flags:  {parsed.get('risk_flags')}")
            reasoning_text = parsed.get("reasoning", "")
            print(f"  Reasoning:   {reasoning_text[:150]}...")
        elif content:
            print(f"  Raw content: {content[:300]}...")

        return {
            "name": name,
            "status": "SUCCESS",
            "json_ok": json_ok,
            "schema_ok": schema_ok,
            "has_thinking": bool(reasoning_content),
            "thinking_chars": len(reasoning_content) if reasoning_content else 0,
            "elapsed": round(elapsed, 1),
            "tokens": tokens,
        }

    except Exception as e:
        print(f"  Status:      FAILED")
        print(f"  Error:       {type(e).__name__}: {e}")
        return {
            "name": name,
            "status": "FAILED",
            "error": str(e),
        }


def main():
    print("DeepSeek V3.2 Thinking + JSON Mode Compatibility Test")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Model: deepseek-chat / deepseek-reasoner")

    results = []
    for test in TESTS:
        result = run_test(test)
        results.append(result)
        time.sleep(1)  # Rate limit courtesy

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    print(f"{'Test':<50} {'Status':<10} {'JSON':<6} {'Schema':<8} {'Think':<8} {'Time':<6}")
    print("-" * 88)
    for r in results:
        status = r.get("status", "?")
        json_ok = "PASS" if r.get("json_ok") else "FAIL" if status == "SUCCESS" else "N/A"
        schema_ok = "PASS" if r.get("schema_ok") else "FAIL" if status == "SUCCESS" else "N/A"
        thinking = "YES" if r.get("has_thinking") else "NO" if status == "SUCCESS" else "N/A"
        elapsed = f"{r.get('elapsed', 0)}s" if status == "SUCCESS" else "N/A"
        print(f"{r['name']:<50} {status:<10} {json_ok:<6} {schema_ok:<8} {thinking:<8} {elapsed:<6}")

    # Recommendation
    print(f"\n{'='*60}")
    print("  RECOMMENDATION")
    print(f"{'='*60}")

    test2 = results[1] if len(results) > 1 else {}
    if test2.get("status") == "SUCCESS" and test2.get("json_ok") and test2.get("schema_ok") and test2.get("has_thinking"):
        print("  json_object + thinking mode: COMPATIBLE")
        print("  Recommended: Enable thinking mode on deepseek-chat")
        print(f"  Extra latency: ~{test2.get('elapsed', 0) - results[0].get('elapsed', 0):.0f}s per call")
        print(f"  Thinking depth: {test2.get('thinking_chars', 0)} chars reasoning")
    elif test2.get("status") == "SUCCESS" and test2.get("json_ok") and test2.get("schema_ok"):
        print("  json_object + thinking mode: PARTIAL (JSON OK but no reasoning_content)")
        print("  May still improve quality via internal reasoning even if not exposed")
    else:
        print("  json_object + thinking mode: INCOMPATIBLE or UNRELIABLE")
        print("  Fallback: Use deepseek-chat without thinking, or switch to tool calling")

    test3 = results[2] if len(results) > 2 else {}
    if test3.get("status") == "SUCCESS" and test3.get("json_ok") and test3.get("schema_ok"):
        print(f"\n  deepseek-reasoner + json_object: WORKS (backup option)")
    elif test3.get("status") == "FAILED":
        print(f"\n  deepseek-reasoner + json_object: FAILED ({test3.get('error', 'unknown')})")


if __name__ == "__main__":
    main()
