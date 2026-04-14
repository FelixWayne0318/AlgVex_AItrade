#!/usr/bin/env python3
"""
replay_ab_compare.py — AB Test Comparison for Agent Prompts

Replays a saved feature snapshot through two prompt versions and compares
the outputs side-by-side.

Usage:
    # Standard AB test (requires API key, 5+ API calls per version)
    python3 scripts/replay_ab_compare.py \
        --snapshot data/feature_snapshots/2026-03-06T12-00-00.json \
        --version-a current --version-b v27.1-shorter-judge \
        --seed 42 --runs 1

    # v30.3 Cached baseline: version-A uses cached outputs (0 API calls),
    # version-B uses fresh API calls. Compares new prompts against
    # the original production decision.
    python3 scripts/replay_ab_compare.py \
        --snapshot data/feature_snapshots/2026-03-06T12-00-00.json \
        --version-a current --version-b v27.1-shorter-judge \
        --cached --seed 42

Requires:
    - A saved feature snapshot (produced by production analyze())
    - DEEPSEEK_API_KEY in environment (for API calls, not needed if --cached for version-A)
    - Prompt versions registered in PROMPT_REGISTRY (prompt_constants.py)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.multi_agent_analyzer import MultiAgentAnalyzer
from agents.prompt_constants import PROMPT_REGISTRY


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


def _extract_reason_tags(result: Dict[str, Any]) -> set:
    """Extract all REASON_TAGS from a replay result."""
    tags = set()
    # Judge decisive_reasons
    judge = result.get("judge_decision", result)
    for key in ("decisive_reasons", "acknowledged_risks", "risk_factors"):
        if isinstance(judge.get(key), list):
            tags.update(judge[key])
    return tags


def _compare_results(result_a: Dict[str, Any], result_b: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two replay results and produce a structured diff."""
    signal_a = result_a.get("signal", "HOLD")
    signal_b = result_b.get("signal", "HOLD")
    conf_a = result_a.get("confidence", "LOW")
    conf_b = result_b.get("confidence", "LOW")

    tags_a = _extract_reason_tags(result_a)
    tags_b = _extract_reason_tags(result_b)

    return {
        "signal_match": signal_a == signal_b,
        "signal_a": signal_a,
        "signal_b": signal_b,
        "confidence_match": conf_a == conf_b,
        "confidence_a": conf_a,
        "confidence_b": conf_b,
        "reason_tags_jaccard": round(_jaccard(tags_a, tags_b), 3),
        "tags_only_in_a": sorted(tags_a - tags_b),
        "tags_only_in_b": sorted(tags_b - tags_a),
        "tags_shared": sorted(tags_a & tags_b),
    }


def _run_single(
    analyzer: MultiAgentAnalyzer,
    snapshot: Dict[str, Any],
    version: str,
    seed: int,
    use_cache: bool = False,
) -> Dict[str, Any]:
    """Run a single replay and return result + timing."""
    features = snapshot["features"]
    memory = snapshot.get("_memory")
    debate_r1 = snapshot.get("_debate_r1")
    cached_outputs = snapshot.get("_decision_cache") if use_cache else None

    prompt_ver = version if version != "current" else None

    start = time.monotonic()
    result = analyzer.analyze_from_features(
        feature_dict=features,
        memory_features=memory,
        debate_r1=debate_r1,
        temperature=0.0,
        seed=seed,
        prompt_version=prompt_ver,
        cached_outputs=cached_outputs,
    )
    elapsed = time.monotonic() - start

    # Count API calls from trace
    if use_cache and cached_outputs:
        api_calls = 0
        total_tokens = 0
    else:
        trace = analyzer.get_call_trace()
        api_calls = len(trace)
        total_tokens = sum(
            entry.get("usage", {}).get("total_tokens", 0)
            for entry in trace
        )

    return {
        "result": result,
        "elapsed_sec": round(elapsed, 2),
        "api_calls": api_calls,
        "total_tokens": total_tokens,
    }


def main():
    parser = argparse.ArgumentParser(
        description="AB Test: Compare two prompt versions on a saved snapshot"
    )
    parser.add_argument(
        "--snapshot", required=True,
        help="Path to feature snapshot JSON file"
    )
    parser.add_argument(
        "--version-a", default="current",
        help="First prompt version (default: 'current')"
    )
    parser.add_argument(
        "--version-b", required=True,
        help="Second prompt version (must be in PROMPT_REGISTRY)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="RNG seed for deterministic replay (default: 42)"
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of runs per version (default: 1)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output JSON file for structured report (optional)"
    )
    parser.add_argument(
        "--cached", action="store_true",
        help="Use cached decision outputs (zero API calls, v30.3)"
    )
    args = parser.parse_args()

    # Validate snapshot exists
    snap_path = Path(args.snapshot)
    if not snap_path.exists():
        print(f"Error: Snapshot not found: {args.snapshot}")
        sys.exit(1)

    # Validate prompt versions
    if args.version_b not in PROMPT_REGISTRY and args.version_b != "current":
        print(f"Error: Version '{args.version_b}' not found in PROMPT_REGISTRY")
        print(f"Available versions: {list(PROMPT_REGISTRY.keys())}")
        sys.exit(1)

    # Load snapshot
    print(f"Loading snapshot: {args.snapshot}")
    snapshot = MultiAgentAnalyzer.load_feature_snapshot(str(snap_path))
    print(f"  Schema: {snapshot.get('schema_version', '?')}, "
          f"Features: {snapshot.get('feature_version', '?')}, "
          f"Symbol: {snapshot.get('symbol', '?')}")
    print(f"  Timestamp: {snapshot.get('timestamp', '?')}")
    has_memory = "_memory" in snapshot
    has_r1 = "_debate_r1" in snapshot
    has_cache = "_decision_cache" in snapshot
    print(f"  Memory: {'yes' if has_memory else 'no'}, "
          f"Debate R1: {'yes' if has_r1 else 'no (will make fresh R1 calls)'}, "
          f"Decision Cache: {'yes' if has_cache else 'no'}")

    if args.cached and (not has_cache or not snapshot.get("_complete", False)):
        if not has_cache:
            print("Error: --cached requested but snapshot has no _decision_cache")
            print("  This snapshot was saved before v30.3. Re-run production analyze() to populate cache.")
        else:
            print("Error: --cached requested but snapshot is incomplete (_complete=False)")
            print("  Analysis may have failed before all agents completed. Use a complete snapshot.")
        sys.exit(1)

    # Create analyzer (API key not needed for cached replay)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key and not args.cached:
        print("Error: DEEPSEEK_API_KEY not set")
        sys.exit(1)

    analyzer = MultiAgentAnalyzer(
        api_key=api_key,
        model="deepseek-chat",
        temperature=0.0,  # Overridden by replay anyway
    )

    # Run AB test
    all_comparisons: List[Dict[str, Any]] = []
    print(f"\nRunning {args.runs} run(s) per version "
          f"(A={args.version_a}, B={args.version_b}, seed={args.seed})...")
    print("-" * 60)

    for run_idx in range(args.runs):
        if args.runs > 1:
            print(f"\n--- Run {run_idx + 1}/{args.runs} ---")

        # Version A: use cached outputs if --cached (zero API calls as baseline)
        print(f"  Running version A ({args.version_a})...", end=" ", flush=True)
        run_a = _run_single(analyzer, snapshot, args.version_a, args.seed,
                            use_cache=args.cached)
        print(f"done ({run_a['elapsed_sec']}s, {run_a['api_calls']} calls, "
              f"{run_a['total_tokens']} tokens)")

        # Version B: always uses fresh API calls (the point of AB testing)
        print(f"  Running version B ({args.version_b})...", end=" ", flush=True)
        run_b = _run_single(analyzer, snapshot, args.version_b, args.seed)
        print(f"done ({run_b['elapsed_sec']}s, {run_b['api_calls']} calls, "
              f"{run_b['total_tokens']} tokens)")

        comparison = _compare_results(run_a["result"], run_b["result"])
        comparison["run"] = run_idx + 1
        comparison["latency_a_sec"] = run_a["elapsed_sec"]
        comparison["latency_b_sec"] = run_b["elapsed_sec"]
        comparison["tokens_a"] = run_a["total_tokens"]
        comparison["tokens_b"] = run_b["total_tokens"]
        all_comparisons.append(comparison)

    # Summary
    print("\n" + "=" * 60)
    print("AB TEST RESULTS")
    print("=" * 60)

    signal_matches = sum(1 for c in all_comparisons if c["signal_match"])
    conf_matches = sum(1 for c in all_comparisons if c["confidence_match"])
    avg_jaccard = sum(c["reason_tags_jaccard"] for c in all_comparisons) / len(all_comparisons)

    print(f"  Signal agreement:     {signal_matches}/{len(all_comparisons)}")
    print(f"  Confidence agreement: {conf_matches}/{len(all_comparisons)}")
    print(f"  Avg REASON_TAGS Jaccard: {avg_jaccard:.3f}")

    for c in all_comparisons:
        run_label = f"Run {c['run']}: " if args.runs > 1 else ""
        match_icon = "✅" if c["signal_match"] else "❌"
        print(f"\n  {run_label}{match_icon} "
              f"A={c['signal_a']}/{c['confidence_a']} vs "
              f"B={c['signal_b']}/{c['confidence_b']}")
        if c["tags_only_in_a"]:
            print(f"    Tags only in A: {c['tags_only_in_a']}")
        if c["tags_only_in_b"]:
            print(f"    Tags only in B: {c['tags_only_in_b']}")
        print(f"    Latency: A={c['latency_a_sec']}s, B={c['latency_b_sec']}s")
        print(f"    Tokens:  A={c['tokens_a']}, B={c['tokens_b']}")

    # Output JSON report
    report = {
        "snapshot": args.snapshot,
        "version_a": args.version_a,
        "version_b": args.version_b,
        "seed": args.seed,
        "runs": args.runs,
        "signal_agreement_rate": signal_matches / len(all_comparisons),
        "confidence_agreement_rate": conf_matches / len(all_comparisons),
        "avg_reason_tags_jaccard": avg_jaccard,
        "comparisons": all_comparisons,
    }

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nReport saved to: {args.output}")

    print()


if __name__ == "__main__":
    main()
