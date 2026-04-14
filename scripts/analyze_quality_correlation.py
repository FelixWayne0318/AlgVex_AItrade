#!/usr/bin/env python3
"""
Layer 3: Outcome Feedback Analysis — Quality Score vs Trade Outcome Correlation.

Read-only analysis of data/trading_memory.json.
Answers: "Does the auditor quality score predict trade outcomes?"

Core analysis logic lives in utils/quality_analysis.py (SSoT).
This script provides CLI interface and human-readable formatting.

Usage:
    python3 scripts/analyze_quality_correlation.py
    python3 scripts/analyze_quality_correlation.py --json    # Machine-readable output
    python3 scripts/analyze_quality_correlation.py --verbose  # Per-trade details
"""
import json
import sys
from pathlib import Path
from typing import Dict

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.quality_analysis import (
    load_trades_from_file,
    load_counterfactuals_from_file,
    run_full_analysis,
)

DATA_DIR = PROJECT_ROOT / 'data'


def main():
    json_mode = '--json' in sys.argv
    verbose = '--verbose' in sys.argv

    trades = load_trades_from_file(DATA_DIR)
    if not trades:
        print(f"❌ No trades with evaluation found in {DATA_DIR / 'trading_memory.json'}")
        sys.exit(1)

    counterfactuals = load_counterfactuals_from_file(DATA_DIR)
    report = run_full_analysis(trades, counterfactuals)

    if json_mode:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_human_readable(report, verbose=verbose)


def _print_human_readable(report: Dict, verbose: bool = False):
    print("=" * 60)
    print("Layer 3: Outcome Feedback Analysis")
    print(f"Total trades with evaluation: {report['total_trades_with_evaluation']}")
    print("=" * 60)

    # Quality quintiles
    print("\n── 1. Quality Score → Win Rate ──")
    qq = report['quality_quintiles']
    if 'error' in qq:
        print(f"  ⚠️  {qq['error']}")
    else:
        for q in ['Q1 (0-20)', 'Q2 (20-40)', 'Q3 (40-60)', 'Q4 (60-80)', 'Q5 (80-100)']:
            d = qq[q]
            wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
            print(f"  {q}: {d['wins']}/{d['n']} wins ({wr})")
        r = qq.get('pearson_r')
        print(f"  Pearson r(quality_score, direction_correct) = {r:.3f}" if r else "  Pearson r = N/A (insufficient data)")
        if r and r > 0.15:
            print("  ✅ Positive correlation — quality score has predictive value")
        elif r and r < -0.05:
            print("  ❌ Negative correlation — quality score may be miscalibrated")
        elif r:
            print("  ⚠️  Weak/no correlation — quality score may not predict outcomes")

    # Confidence calibration
    print("\n── 2. Confidence Level → Win Rate ──")
    cc = report['confidence_calibration']
    for level in ['HIGH', 'MEDIUM', 'LOW']:
        d = cc.get(level, {'n': 0, 'win_rate': None})
        wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
        print(f"  {level}: {d.get('wins', 0)}/{d['n']} wins ({wr})")

    # Entry timing
    print("\n── 3. Entry Timing Verdict → Win Rate ──")
    et = report['entry_timing']
    for v in ['ENTER', 'REJECT']:
        d = et.get(v, {'n': 0, 'win_rate': None})
        wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
        print(f"  {v}: {d.get('wins', 0)}/{d['n']} wins ({wr})")

    # Counter-trend
    print("\n── 4. Counter-Trend Performance ──")
    ct = report['counter_trend']
    for key in ['trend_following', 'counter_trend']:
        d = ct[key]
        wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
        rr = f"{d['avg_rr']:.2f}" if d['avg_rr'] is not None else "N/A"
        label = "Trend-following" if key == 'trend_following' else "Counter-trend"
        print(f"  {label}: {d.get('wins', 0)}/{d['n']} wins ({wr}), avg R/R={rr}")

    # Grade distribution
    print("\n── 5. Grade Distribution ──")
    for grade, count in report['grade_distribution'].items():
        print(f"  {grade}: {count}")

    # Debate winner
    print("\n── 6. Debate Winner → Outcome ──")
    dw = report['debate_winner']
    for key in ['aligned', 'overruled']:
        d = dw.get(key, {'n': 0, 'win_rate': None})
        wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
        print(f"  Judge {key} with debate winner: {d.get('wins', 0)}/{d['n']} wins ({wr})")

    # Feature importance (Phase 2)
    print("\n── 7. Feature Importance (Spearman ρ) ──")
    fi = report.get('feature_importance', {})
    if 'error' in fi:
        print(f"  ⚠️  {fi['error']}")
    else:
        print(f"  Features analyzed: {fi.get('total_features_analyzed', 0)}")
        top = fi.get('top_20', {})
        if top:
            print("  Top predictive features:")
            for feat, data in list(top.items())[:10]:
                sig = "***" if data['p'] < 0.01 else "**" if data['p'] < 0.05 else "*" if data['p'] < 0.1 else ""
                print(f"    {feat}: ρ={data['rho']:+.4f} (p={data['p']:.4f}{sig}, n={data['n']})")
            if verbose:
                for feat, data in list(top.items())[10:]:
                    print(f"    {feat}: ρ={data['rho']:+.4f} (p={data['p']:.4f}, n={data['n']})")

    # Rolling performance (Phase 3)
    print("\n── 8. Rolling Performance ──")
    rp = report.get('rolling_performance', {})
    if rp.get('total_trades', 0) < 20:
        print(f"  ⚠️  Insufficient data: {rp.get('total_trades', 0)} trades (need 20+)")
    else:
        rolling = rp.get('rolling_win_rate', [])
        if rolling:
            print(f"  Rolling win rate (window=20): min={min(rolling):.1%}, max={max(rolling):.1%}, latest={rolling[-1]:.1%}")
        print(f"  Max win streak: {rp.get('max_win_streak', 0)}")
        print(f"  Max loss streak: {rp.get('max_loss_streak', 0)}")

    # Confidence recalibration (Phase 4)
    print("\n── 9. Confidence Recalibration ──")
    cr = report.get('confidence_recalibration', {})
    for level in ['HIGH', 'MEDIUM', 'LOW']:
        d = cr.get(level, {'n': 0})
        if d['n'] == 0:
            continue
        wr = f"{d['win_rate']:.1%}" if d.get('win_rate') is not None else "N/A"
        ev = f"{d['expected_ev']:+.4f}" if d.get('expected_ev') is not None else "N/A"
        print(f"  {level}: {d.get('wins', 0)}/{d['n']} wins ({wr}), "
              f"avg_win_rr={d.get('avg_win_rr', 0):.2f}, avg_loss_rr={d.get('avg_loss_rr', 0):.2f}, EV={ev}")
    flags = cr.get('flags', [])
    for f in flags:
        print(f"  ⚠️  {f}")
    if not flags and any(cr.get(l, {}).get('n', 0) > 0 for l in ['HIGH', 'MEDIUM', 'LOW']):
        print("  ✅ Confidence levels properly calibrated (HIGH > MEDIUM > LOW)")

    # v34.0 flag correlation (Phase 4)
    print("\n── 10. v34.0 Flag Correlation ──")
    vf = report.get('v34_flag_correlation', {})
    if vf.get('total_with_score', 0) == 0:
        print("  ⚠️  No trades with quality score + v34.0 flags yet")
    else:
        flagged = vf.get('flagged', {})
        clean = vf.get('clean', {})
        f_wr = f"{flagged['win_rate']:.1%}" if flagged.get('win_rate') is not None else "N/A"
        c_wr = f"{clean['win_rate']:.1%}" if clean.get('win_rate') is not None else "N/A"
        print(f"  Flagged cycles: {flagged.get('n', 0)} trades, win_rate={f_wr}, avg_score={flagged.get('avg_score', 'N/A')}")
        print(f"  Clean cycles:   {clean.get('n', 0)} trades, win_rate={c_wr}, avg_score={clean.get('avg_score', 'N/A')}")
        if flagged.get('win_rate') is not None and clean.get('win_rate') is not None:
            if flagged['win_rate'] < clean['win_rate']:
                print("  ✅ v34.0 flags correlate with worse outcomes (flags are predictive)")
            else:
                print("  ⚠️  Flagged trades perform equally/better — flags may not be predictive")

    # HOLD counterfactuals
    hc = report.get('hold_counterfactuals')
    if hc and hc.get('total', 0) > 0:
        print("\n── 11. HOLD Counterfactual Analysis ──")
        print(f"  Total HOLD decisions evaluated: {hc['total']}")
        for source, stats in hc.get('by_source', {}).items():
            acc = f"{stats['accuracy']:.1%}" if stats.get('accuracy') is not None else "N/A"
            print(f"  {source}: {stats['total']} HOLDs, accuracy={acc} (correct={stats['correct']}, wrong={stats['wrong']})")

    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()
