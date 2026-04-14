"""
Layer 3: Quality-Outcome Correlation Analysis — Reusable Service Module.

Extracted from scripts/analyze_quality_correlation.py for production integration.
Used by: Telegram heartbeat, /layer3 command, Web API endpoints.

All functions are pure: take trades list in, return dict out.
"""
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def load_trades_from_file(data_dir: Path) -> List[Dict]:
    """Load and filter trades with valid evaluation data from trading_memory.json."""
    memory_file = data_dir / 'trading_memory.json'
    if not memory_file.exists():
        return []
    try:
        with open(memory_file) as f:
            memories = json.load(f)
        return [m for m in memories
                if m.get('evaluation') and 'direction_correct' in m['evaluation']]
    except (json.JSONDecodeError, Exception):
        return []


def load_counterfactuals_from_file(data_dir: Path) -> List[Dict]:
    """Load HOLD counterfactual records."""
    cf_file = data_dir / 'hold_counterfactuals.json'
    if not cf_file.exists():
        return []
    try:
        with open(cf_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception):
        return []


def pearson_r(xs: List[float], ys: List[float]) -> Optional[float]:
    """Pearson correlation coefficient. Returns None if < 5 pairs or zero variance."""
    n = len(xs)
    if n < 5:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / math.sqrt(var_x * var_y)


# ── Analysis 1: Quality Score Quintiles → Win Rate ──
def analyze_quality_quintiles(trades: List[Dict]) -> Dict:
    """Stratify trades by quality score quintile, compute win rate per bucket."""
    scored = [(m['ai_quality_score'], m['evaluation']['direction_correct'])
              for m in trades if m.get('ai_quality_score') is not None]
    if len(scored) < 10:
        return {'error': f'Insufficient data: {len(scored)} trades with quality score (need 10+)'}

    quintiles = {'Q1 (0-20)': [], 'Q2 (20-40)': [], 'Q3 (40-60)': [],
                 'Q4 (60-80)': [], 'Q5 (80-100)': []}
    for score, won in scored:
        if score < 20: quintiles['Q1 (0-20)'].append(won)
        elif score < 40: quintiles['Q2 (20-40)'].append(won)
        elif score < 60: quintiles['Q3 (40-60)'].append(won)
        elif score < 80: quintiles['Q4 (60-80)'].append(won)
        else: quintiles['Q5 (80-100)'].append(won)

    result = {}
    for q, outcomes in quintiles.items():
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o)
        result[q] = {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3) if n > 0 else None}

    scores = [s for s, _ in scored]
    outcomes = [1.0 if w else 0.0 for _, w in scored]
    result['pearson_r'] = pearson_r(scores, outcomes)
    result['total_trades'] = len(scored)
    return result


# ── Analysis 2: Confidence Level → Win Rate ──
def analyze_confidence_calibration(trades: List[Dict]) -> Dict:
    """Compute actual win rate per confidence level."""
    buckets = defaultdict(list)
    for m in trades:
        conf = m['evaluation'].get('confidence', 'UNKNOWN')
        won = m['evaluation']['direction_correct']
        buckets[conf].append(won)

    result = {}
    for conf in ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN']:
        outcomes = buckets.get(conf, [])
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o)
        result[conf] = {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3) if n > 0 else None}
    return result


# ── Analysis 3: Entry Timing Verdict → Win Rate ──
def analyze_entry_timing(trades: List[Dict]) -> Dict:
    """Compare outcomes for ENTER vs REJECT verdicts."""
    buckets = defaultdict(list)
    for m in trades:
        verdict = m.get('entry_timing_verdict')
        if verdict:
            won = m['evaluation']['direction_correct']
            buckets[verdict].append(won)

    result = {}
    for v in ['ENTER', 'REJECT']:
        outcomes = buckets.get(v, [])
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o)
        result[v] = {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3) if n > 0 else None}
    result['total_with_verdict'] = sum(len(v) for v in buckets.values())
    return result


# ── Analysis 4: Counter-Trend Performance ──
def analyze_counter_trend(trades: List[Dict]) -> Dict:
    """Compare trend-following vs counter-trend trade outcomes."""
    trend_following = []
    counter_trend = []
    for m in trades:
        is_ct = m['evaluation'].get('is_counter_trend', False)
        won = m['evaluation']['direction_correct']
        rr = m['evaluation'].get('actual_rr', 0)
        if is_ct:
            counter_trend.append((won, rr))
        else:
            trend_following.append((won, rr))

    def stats(trades_list):
        n = len(trades_list)
        if n == 0:
            return {'n': 0, 'win_rate': None, 'avg_rr': None}
        wins = sum(1 for w, _ in trades_list if w)
        avg_rr = sum(rr for _, rr in trades_list) / n
        return {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3), 'avg_rr': round(avg_rr, 3)}

    return {'trend_following': stats(trend_following), 'counter_trend': stats(counter_trend)}


# ── Analysis 5: Grade Distribution ──
def analyze_grade_distribution(trades: List[Dict]) -> Dict:
    """Count trades per evaluation grade."""
    grades = defaultdict(int)
    for m in trades:
        grade = m['evaluation'].get('grade', 'UNKNOWN')
        grades[grade] += 1
    return dict(sorted(grades.items()))


# ── Analysis 6: Debate Winner → Outcome ──
def analyze_debate_winner(trades: List[Dict]) -> Dict:
    """Does the debate winner predict outcome?"""
    buckets = defaultdict(list)
    for m in trades:
        winner = m.get('winning_side')
        decision = m.get('decision', '')
        if winner and decision:
            won = m['evaluation']['direction_correct']
            aligned = (winner == 'BULL' and decision == 'BUY') or \
                      (winner == 'BEAR' and decision == 'SELL')
            buckets['aligned' if aligned else 'overruled'].append(won)

    result = {}
    for key in ['aligned', 'overruled']:
        outcomes = buckets.get(key, [])
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o)
        result[key] = {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3) if n > 0 else None}
    return result


# ── Analysis 7 (Phase 2): Feature Importance ──
def analyze_feature_importance(trades: List[Dict]) -> Dict:
    """Rank 124 features by predictive power (Spearman rho vs direction_correct)."""
    try:
        from scipy.stats import spearmanr
    except ImportError:
        return {'error': 'scipy not installed (pip install scipy)'}

    feature_trades = [(m['conditions_v2'], m['evaluation']['direction_correct'])
                      for m in trades if m.get('conditions_v2')]
    if len(feature_trades) < 30:
        return {'error': f'Insufficient: {len(feature_trades)} trades with conditions_v2 (need 30+)'}

    all_features = set()
    for conds, _ in feature_trades:
        all_features.update(k for k, v in conds.items()
                            if isinstance(v, (int, float)) and not k.startswith('_'))

    correlations = {}
    for feat in all_features:
        values = []
        outcomes = []
        for conds, won in feature_trades:
            v = conds.get(feat)
            if v is not None and isinstance(v, (int, float)):
                values.append(float(v))
                outcomes.append(1.0 if won else 0.0)
        if len(values) >= 20:
            rho, pvalue = spearmanr(values, outcomes)
            correlations[feat] = {'rho': round(rho, 4), 'p': round(pvalue, 4), 'n': len(values)}

    ranked = sorted(correlations.items(), key=lambda x: abs(x[1]['rho']), reverse=True)
    return {
        'total_features_analyzed': len(correlations),
        'top_20': {k: v for k, v in ranked[:20]},
        'bottom_5': {k: v for k, v in ranked[-5:]},
    }


# ── Analysis 8 (Phase 3): Rolling Performance + Streak Detection ──
def analyze_rolling_performance(trades: List[Dict], window: int = 20) -> Dict:
    """Rolling win rate curve + streak detection."""
    sorted_trades = sorted(trades, key=lambda m: m.get('timestamp', ''))
    outcomes = [m['evaluation']['direction_correct'] for m in sorted_trades]

    rolling = []
    for i in range(window, len(outcomes) + 1):
        window_outcomes = outcomes[i - window:i]
        wr = sum(1 for o in window_outcomes if o) / window
        rolling.append(round(wr, 3))

    max_win_streak = max_loss_streak = current_streak = 0
    last_outcome = None
    for o in outcomes:
        if o == last_outcome:
            current_streak += 1
        else:
            current_streak = 1
        last_outcome = o
        if o:
            max_win_streak = max(max_win_streak, current_streak)
        else:
            max_loss_streak = max(max_loss_streak, current_streak)

    return {
        'rolling_win_rate': rolling,
        'max_win_streak': max_win_streak,
        'max_loss_streak': max_loss_streak,
        'total_trades': len(outcomes),
    }


# ── Analysis 9 (Phase 4): Confidence Recalibration ──
def analyze_confidence_recalibration(trades: List[Dict]) -> Dict:
    """Build confidence-bucket win rates and suggest recalibration."""
    buckets: Dict[str, List[Tuple[bool, float]]] = defaultdict(list)
    for m in trades:
        conf = m['evaluation'].get('confidence', 'UNKNOWN')
        won = m['evaluation']['direction_correct']
        rr = m['evaluation'].get('actual_rr', 0)
        buckets[conf].append((won, rr))

    result = {}
    for conf in ['HIGH', 'MEDIUM', 'LOW']:
        data = buckets.get(conf, [])
        n = len(data)
        if n == 0:
            result[conf] = {'n': 0, 'win_rate': None, 'avg_rr': None, 'expected_ev': None}
            continue
        wins = sum(1 for w, _ in data if w)
        avg_rr = sum(rr for _, rr in data) / n
        win_rate = wins / n
        win_rrs = [rr for w, rr in data if w and rr > 0]
        loss_rrs = [abs(rr) for w, rr in data if not w and rr < 0]
        avg_win_rr = sum(win_rrs) / len(win_rrs) if win_rrs else 0
        avg_loss_rr = sum(loss_rrs) / len(loss_rrs) if loss_rrs else 0
        ev = win_rate * avg_win_rr - (1 - win_rate) * avg_loss_rr if avg_win_rr or avg_loss_rr else None
        result[conf] = {
            'n': n,
            'wins': wins,
            'win_rate': round(win_rate, 3),
            'avg_rr': round(avg_rr, 3),
            'avg_win_rr': round(avg_win_rr, 3),
            'avg_loss_rr': round(avg_loss_rr, 3),
            'expected_ev': round(ev, 4) if ev is not None else None,
        }

    flags = []
    high_wr = result['HIGH'].get('win_rate')
    med_wr = result['MEDIUM'].get('win_rate')
    low_wr = result['LOW'].get('win_rate')
    if high_wr is not None and med_wr is not None and high_wr < med_wr:
        flags.append(f'OVERCONFIDENT: HIGH win_rate ({high_wr:.1%}) < MEDIUM ({med_wr:.1%})')
    if med_wr is not None and low_wr is not None and med_wr < low_wr:
        flags.append(f'MISCALIBRATED: MEDIUM win_rate ({med_wr:.1%}) < LOW ({low_wr:.1%})')
    high_ev = result['HIGH'].get('expected_ev')
    if high_ev is not None and high_ev < 0:
        flags.append(f'NEGATIVE_EV_HIGH: HIGH confidence EV={high_ev:.4f} (losing money)')

    result['flags'] = flags
    return result


# ── Analysis 10 (Phase 4): v34.0 Flag Correlation ──
def analyze_v34_flag_correlation(trades: List[Dict]) -> Dict:
    """Check if v34.0 flags predict worse outcomes."""
    flagged_trades = []
    clean_trades = []
    for m in trades:
        score = m.get('ai_quality_score')
        if score is None:
            continue
        won = m['evaluation']['direction_correct']
        flags = m.get('quality_flags', [])
        has_v34_flag = any(
            f.startswith(('REASON_SIGNAL_CONFLICT', 'CONFIDENCE_RISK_CONFLICT',
                         'DEBATE_CONVERGENCE', 'SIGNAL_SCORE_DIVERGENCE',
                         'SINGLE_DIMENSION_DECISION'))
            for f in flags
        )
        if has_v34_flag:
            flagged_trades.append((score, won))
        else:
            clean_trades.append((score, won))

    def _stats(items):
        n = len(items)
        if n == 0:
            return {'n': 0, 'win_rate': None, 'avg_score': None}
        wins = sum(1 for _, w in items if w)
        avg_score = sum(s for s, _ in items) / n
        return {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3), 'avg_score': round(avg_score, 1)}

    return {
        'flagged': _stats(flagged_trades),
        'clean': _stats(clean_trades),
        'total_with_score': len(flagged_trades) + len(clean_trades),
    }


# ── HOLD Counterfactual Summary ──
def analyze_hold_counterfactuals(counterfactuals: List[Dict]) -> Dict:
    """Summarize HOLD counterfactual verdicts by source."""
    if not counterfactuals:
        return {'total': 0, 'by_source': {}, 'by_verdict': {}}

    by_source = defaultdict(lambda: {'total': 0, 'correct': 0, 'wrong': 0, 'neutral': 0})
    by_verdict = defaultdict(int)

    for cf in counterfactuals:
        source = cf.get('hold_source', 'unknown')
        verdict = cf.get('verdict', 'neutral')
        by_source[source]['total'] += 1
        by_source[source][verdict] += 1
        by_verdict[verdict] += 1

    # Compute accuracy per source
    result_by_source = {}
    for source, stats in by_source.items():
        decided = stats['correct'] + stats['wrong']
        accuracy = round(stats['correct'] / decided, 3) if decided > 0 else None
        result_by_source[source] = {
            'total': stats['total'],
            'correct': stats['correct'],
            'wrong': stats['wrong'],
            'neutral': stats['neutral'],
            'accuracy': accuracy,
        }

    return {
        'total': len(counterfactuals),
        'by_source': result_by_source,
        'by_verdict': dict(by_verdict),
    }


def run_full_analysis(trades: List[Dict], counterfactuals: Optional[List[Dict]] = None) -> Dict:
    """Run all 10 analyses + HOLD counterfactual summary. Returns complete report dict."""
    report = {
        'total_trades_with_evaluation': len(trades),
        'quality_quintiles': analyze_quality_quintiles(trades),
        'confidence_calibration': analyze_confidence_calibration(trades),
        'entry_timing': analyze_entry_timing(trades),
        'counter_trend': analyze_counter_trend(trades),
        'grade_distribution': analyze_grade_distribution(trades),
        'debate_winner': analyze_debate_winner(trades),
        'feature_importance': analyze_feature_importance(trades),
        'rolling_performance': analyze_rolling_performance(trades),
        'confidence_recalibration': analyze_confidence_recalibration(trades),
        'v34_flag_correlation': analyze_v34_flag_correlation(trades),
    }
    if counterfactuals is not None:
        report['hold_counterfactuals'] = analyze_hold_counterfactuals(counterfactuals)
    return report


def get_heartbeat_summary(trades: List[Dict]) -> Optional[Dict]:
    """Compact Layer 3 summary for heartbeat display.

    Returns None if insufficient data (< 5 trades).
    Otherwise returns key metrics for heartbeat integration.
    """
    if len(trades) < 5:
        return None

    # Confidence calibration (always available with 5+ trades)
    conf_cal = analyze_confidence_calibration(trades)
    recal = analyze_confidence_recalibration(trades)

    # Overall win rate
    total = len(trades)
    wins = sum(1 for m in trades if m['evaluation']['direction_correct'])
    overall_wr = round(wins / total, 3) if total > 0 else 0

    # Streak info
    sorted_trades = sorted(trades, key=lambda m: m.get('timestamp', ''))
    outcomes = [m['evaluation']['direction_correct'] for m in sorted_trades]
    current_streak = 1
    current_type = outcomes[-1] if outcomes else None
    for i in range(len(outcomes) - 2, -1, -1):
        if outcomes[i] == current_type:
            current_streak += 1
        else:
            break

    summary = {
        'total_trades': total,
        'overall_win_rate': overall_wr,
        'current_streak': current_streak,
        'current_streak_type': 'win' if current_type else 'loss',
        'confidence_calibration': {},
        'flags': recal.get('flags', []),
    }

    # Compact confidence stats
    for level in ['HIGH', 'MEDIUM', 'LOW']:
        d = conf_cal.get(level, {})
        if d.get('n', 0) > 0:
            ev_data = recal.get(level, {})
            summary['confidence_calibration'][level] = {
                'n': d['n'],
                'win_rate': d['win_rate'],
                'ev': ev_data.get('expected_ev'),
            }

    return summary
