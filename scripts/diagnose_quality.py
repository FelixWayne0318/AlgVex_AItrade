#!/usr/bin/env python3
"""
Diagnose AI Quality Score trends.

Reads feature snapshots, runs compute_valid_tags() to determine which
REASON_TAGS are available, maps them to data categories, and identifies
which required categories systematically lack valid tags — the root cause
of low quality scores.

Also parses journalctl logs for historical quality audit records.

Usage:
  cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && python3 scripts/diagnose_quality.py
"""
import json
import glob
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_journal_logs(hours: int = 48) -> list[str]:
    """Get recent nautilus-trader logs from journalctl."""
    try:
        result = subprocess.run(
            ['journalctl', '-u', 'nautilus-trader', '--no-pager',
             '--since', f'{hours} hours ago', '-o', 'short-iso'],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.splitlines()
    except Exception as e:
        print(f"  journalctl failed: {e}")
        return []


def extract_quality_data(lines: list[str]) -> list[dict]:
    """Extract AI Quality Audit entries from log lines."""
    records = []
    quality_pattern = re.compile(r'AI Quality[^:]*?:\s*(\d+)/100')
    miss_pattern = re.compile(r'(\w+):miss=([\w,]+)')
    value_err_pattern = re.compile(r'value_errs=(\d+)')
    zone_err_pattern = re.compile(r'zone_errs=(\d+)')

    for line in lines:
        if 'AI Quality' not in line:
            continue

        score_match = quality_pattern.search(line)
        if not score_match:
            continue

        score = int(score_match.group(1))

        missing = {}
        for m in miss_pattern.finditer(line):
            agent = m.group(1)
            cats = m.group(2).split(',')
            missing[agent] = cats

        val_errs = 0
        zone_errs = 0
        val_m = value_err_pattern.search(line)
        if val_m:
            val_errs = int(val_m.group(1))
        zone_m = zone_err_pattern.search(line)
        if zone_m:
            zone_errs = int(zone_m.group(1))

        ts_match = re.search(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', line)
        ts = ts_match.group(1).replace('T', ' ') if ts_match else ''

        records.append({
            'score': score,
            'missing': missing,
            'value_errors': val_errs,
            'zone_errors': zone_errs,
            'timestamp': ts,
            'raw': line.strip()[:200],
        })

    return records


def analyze_snapshots_with_valid_tags():
    """Core analysis: read feature snapshots, compute valid tags, map to categories."""
    print("\n" + "=" * 65)
    print("  🔬 Feature Snapshot 深度分析 (compute_valid_tags)")
    print("=" * 65)

    try:
        from agents.tag_validator import compute_valid_tags, _ALWAYS_VALID
        from agents.ai_quality_auditor import _AGENT_REQUIRED_CATEGORIES, _TAG_TO_CATEGORIES
    except ImportError as e:
        print(f"  ❌ 无法导入: {e}")
        return

    snapshot_dir = 'data/feature_snapshots'
    if not os.path.isdir(snapshot_dir):
        print(f"  ❌ {snapshot_dir} 不存在")
        return

    snapshots = sorted(glob.glob(os.path.join(snapshot_dir, '*.json')))
    if not snapshots:
        print(f"  ❌ 无 snapshot 文件")
        return

    # Analyze last N snapshots
    last_n = min(20, len(snapshots))
    snapshots = snapshots[-last_n:]
    print(f"\n  分析最近 {last_n} 个 snapshots...\n")

    # Track per-snapshot category coverage
    category_miss = defaultdict(int)
    category_available_history = defaultdict(int)
    score_estimates = []
    fr_status_counts = Counter()  # Track FR_IGNORED vs FR_* distribution

    for snap_path in snapshots:
        try:
            with open(snap_path, 'r') as f:
                data = json.load(f)
            features = data.get('features', data)

            valid_tags = compute_valid_tags(features)

            # Determine coverable categories (≥1 non-always-valid tag)
            coverable = set()
            for tag in valid_tags:
                if tag in _ALWAYS_VALID:
                    continue
                cats = _TAG_TO_CATEGORIES.get(tag, [])
                for cat in cats:
                    coverable.add(cat)

            # Track FR status
            fr_tags = [t for t in valid_tags if t.startswith('FR_')]
            if fr_tags:
                for t in fr_tags:
                    fr_status_counts[t] += 1
            else:
                fr_status_counts['(none)'] += 1

            # Compute penalties
            penalty = 0
            for agent, required_cats in _AGENT_REQUIRED_CATEGORIES.items():
                effective = required_cats & coverable
                for cat in required_cats:
                    if cat not in effective:
                        category_miss[f"{agent}:{cat}"] += 1
                        penalty += 5

            # Track which categories had any valid tag (non-always-valid)
            all_cats = {c for _, cats in _TAG_TO_CATEGORIES.items() for c in cats}
            for cat in all_cats:
                if cat in coverable:
                    category_available_history[cat] += 1

            score_estimates.append(100 - penalty)

        except Exception as e:
            print(f"  ⚠️ Error reading {os.path.basename(snap_path)}: {e}")
            continue

    # === Report ===

    # 1. Score estimates
    if score_estimates:
        avg = sum(score_estimates) / len(score_estimates)
        print(f"  📊 estimated 评分 (仅 category coverage penalty):")
        print(f"  {'-' * 55}")
        print(f"    平均: {avg:.0f} | 最低: {min(score_estimates)} | 最高: {max(score_estimates)}")
        print(f"    最近 5 次: {score_estimates[-5:]}")
        print()

    # 2. FR tag distribution
    print(f"  💰 Funding Rate tag 分布 ({last_n} 个 snapshots):")
    print(f"  {'-' * 55}")
    for tag, count in fr_status_counts.most_common():
        pct = count / last_n * 100
        bar = '█' * int(pct / 5)
        print(f"    {tag:25s}: {count:3d}/{last_n} ({pct:5.1f}%) {bar}")
    print()

    # 3. Category availability across all snapshots
    all_cats_sorted = sorted(set(c for t, cats in _TAG_TO_CATEGORIES.items() for c in cats))
    print(f"  📋 各 Category 在 {last_n} 个 snapshots 中有 ≥1 非 always-valid tag:")
    print(f"  {'-' * 55}")

    required_anywhere = set()
    for cats in _AGENT_REQUIRED_CATEGORIES.values():
        required_anywhere.update(cats)

    for cat in all_cats_sorted:
        avail = category_available_history.get(cat, 0)
        pct = avail / last_n * 100
        bar = '█' * int(pct / 5)
        required_mark = " ← REQUIRED" if cat in required_anywhere else ""
        icon = '✅' if pct >= 80 else ('🟡' if pct >= 50 else '🔴')
        print(f"    {icon} {cat:20s}: {avail:3d}/{last_n} ({pct:5.1f}%) {bar}{required_mark}")

    # 4. Per-agent:category miss frequency
    if category_miss:
        print(f"\n  🚩 Agent:Category 缺失频率:")
        print(f"  {'-' * 55}")
        for combo, count in sorted(category_miss.items(), key=lambda x: -x[1]):
            if count == 0:
                continue
            pct = count / last_n * 100
            print(f"    {combo:30s}: {count}/{last_n} ({pct:.0f}%)")

    # 5. Deep dive: show WHAT data is in features for ALL categories
    print(f"\n  🔍 各 Category 详情 (最新 snapshot):")
    print(f"  {'-' * 50}")
    try:
        with open(snapshots[-1], 'r') as f:
            data = json.load(f)
        features = data.get('features', data)
        valid_tags = compute_valid_tags(features)

        # Show all categories that are required by at least one agent
        deep_dive_cats = sorted(required_anywhere)
        for cat in deep_dive_cats:
            print(f"\n    ┌─ {cat} ─────────────────────────")
            cat_features = _get_category_features(cat)
            for fkey in cat_features:
                val = features.get(fkey, '❌ NOT IN SNAPSHOT')
                if isinstance(val, float):
                    val = f"{val:.4f}" if abs(val) < 1 else f"{val:.2f}"
                print(f"    │  {fkey:35s} = {val}")

            cat_tags = [t for t, cats in _TAG_TO_CATEGORIES.items() if cat in cats]
            valid_in_cat = [t for t in cat_tags if t in valid_tags]
            invalid_in_cat = [t for t in cat_tags if t not in valid_tags]
            always_valid_in_cat = [t for t in valid_in_cat if t in _ALWAYS_VALID]
            data_valid_in_cat = [t for t in valid_in_cat if t not in _ALWAYS_VALID]
            print(f"    │")
            print(f"    │  ✅ data-driven valid tags ({len(data_valid_in_cat)}):")
            for t in sorted(data_valid_in_cat):
                print(f"    │    + {t}")
            if always_valid_in_cat:
                print(f"    │  ⚪ always-valid tags ({len(always_valid_in_cat)}):")
                for t in sorted(always_valid_in_cat):
                    print(f"    │    ~ {t} (不计入 _coverable)")
            if not data_valid_in_cat:
                print(f"    │    (无 data-driven tag → category 不在 _coverable → 不 require)")
            print(f"    │  ❌ invalid tags ({len(invalid_in_cat)}):")
            for t in sorted(invalid_in_cat):
                print(f"    │    - {t}")
            print(f"    └────────────────────────────────")

    except Exception as e:
        print(f"    ❌ 读取最新 snapshot 失败: {e}")


def _get_category_features(category: str) -> list[str]:
    """Map a data category to its corresponding FEATURE_SCHEMA keys.

    v29.2: Updated to include all new multi-TF features (4H/1D expansion).
    """
    mapping = {
        'derivatives': [
            'funding_rate_pct', 'funding_rate_trend', 'oi_trend',
            'liquidation_bias', 'premium_index',
        ],
        'order_flow': [
            'cvd_trend_30m', 'buy_ratio_30m', 'cvd_cumulative_30m',
            'cvd_price_cross_30m', 'cvd_trend_4h', 'buy_ratio_4h',
            'cvd_price_cross_4h',
        ],
        'orderbook': [
            'obi_weighted', 'obi_change_pct', 'bid_volume_usd', 'ask_volume_usd',
        ],
        'mtf_4h': [
            'rsi_4h', 'macd_4h', 'macd_signal_4h', 'macd_histogram_4h',
            'adx_4h', 'di_plus_4h', 'di_minus_4h', 'bb_position_4h',
            # v29.2 新增
            'bb_upper_4h', 'bb_lower_4h', 'sma_20_4h', 'sma_50_4h',
            'atr_4h', 'atr_pct_4h', 'ema_12_4h', 'ema_26_4h',
            'volume_ratio_4h',
            'extension_ratio_4h', 'extension_regime_4h',
            'volatility_regime_4h', 'volatility_percentile_4h',
        ],
        'mtf_1d': [
            'adx_1d', 'di_plus_1d', 'di_minus_1d', 'rsi_1d',
            'macd_1d', 'sma_200_1d', 'adx_direction_1d',
            # v29.2 新增
            'macd_signal_1d', 'macd_histogram_1d', 'bb_position_1d',
            'volume_ratio_1d', 'atr_1d', 'atr_pct_1d',
            'ema_12_1d', 'ema_26_1d',
            'extension_ratio_1d', 'extension_regime_1d',
            'volatility_regime_1d', 'volatility_percentile_1d',
        ],
        'sr_zones': [
            'nearest_support_price', 'nearest_support_strength',
            'nearest_support_dist_atr', 'nearest_resist_price',
            'nearest_resist_strength', 'nearest_resist_dist_atr',
        ],
        'sentiment': [
            'long_ratio', 'short_ratio', 'sentiment_degraded',
        ],
        'technical_30m': [
            'rsi_30m', 'macd_30m', 'macd_signal_30m', 'macd_histogram_30m',
            'adx_30m', 'bb_position_30m',
            # v29.2 新增
            'atr_pct_30m', 'ema_12_30m', 'ema_26_30m',
        ],
        'binance_derivatives': [
            'top_traders_long_ratio', 'taker_buy_ratio',
        ],
        'extension_ratio': [
            'extension_ratio_30m', 'extension_regime_30m',
            'extension_ratio_4h', 'extension_regime_4h',
            'extension_ratio_1d', 'extension_regime_1d',
        ],
        'volatility_regime': [
            'volatility_regime_30m', 'volatility_percentile_30m',
            'volatility_regime_4h', 'volatility_percentile_4h',
            'volatility_regime_1d', 'volatility_percentile_1d',
        ],
        'position_context': [
            'liquidation_buffer_pct', 'position_side',
            'position_pnl_pct', 'position_size_pct',
        ],
    }
    return mapping.get(category, [])


def analyze_log_history():
    """Parse and display historical quality scores from logs."""
    print("\n" + "=" * 65)
    print("  📜 历史质量评分 (journalctl)")
    print("=" * 65)

    lines = parse_journal_logs(hours=72)
    if not lines:
        print("  journalctl 无数据")
        return []

    print(f"  读取 {len(lines)} 行日志")
    records = extract_quality_data(lines)
    print(f"  提取到 {len(records)} 条质量审计记录")

    if not records:
        print("\n  调试: 搜索包含 'Quality' 的日志行 (前 5 条):")
        quality_lines = [l for l in lines if 'uality' in l][:5]
        for l in quality_lines:
            print(f"    {l[:150]}")
        if not quality_lines:
            print("    (无匹配行)")
        return []

    scores = [r['score'] for r in records]
    print(f"\n  📊 评分统计 ({len(records)} 次):")
    print(f"    平均: {sum(scores)/len(scores):.1f} | 中位: {sorted(scores)[len(scores)//2]}")
    print(f"    最低: {min(scores)} | 最高: {max(scores)}")

    total_miss = Counter()
    for r in records:
        for agent, cats in r['missing'].items():
            for cat in cats:
                total_miss[f"{agent}:{cat}"] += 1

    if total_miss:
        print(f"\n  🚩 缺失排名:")
        for combo, count in total_miss.most_common(10):
            pct = count / len(records) * 100
            print(f"    {combo:30s}: {count}/{len(records)} ({pct:.0f}%)")

    print(f"\n  📈 最近评分:")
    for r in records[-10:]:
        ts = r['timestamp'] or '?'
        score = r['score']
        icon = '🟢' if score >= 90 else '🟡' if score >= 70 else '🔴'
        miss_str = ''
        if r['missing']:
            parts = [f"{a}:{','.join(c)}" for a, c in r['missing'].items()]
            miss_str = f" | {'; '.join(parts)}"
        print(f"    {ts} {icon} {score}/100{miss_str}")

    return records


def print_summary(records: list[dict], snapshot_count: int):
    """Print final summary."""
    print("\n" + "=" * 65)
    print("  📋 诊断总结")
    print("=" * 65)

    print(f"""
  质量审计目标:
    验证 AI Agent 是否忠实基于提供的数据做判断，具体检查:
    1. 数据覆盖 — Agent 是否评估了所有可用的关键数据源
    2. 数值准确 — Agent 引用的数值是否与实际数据匹配
    3. 逻辑一致 — 结论是否与引用数据逻辑自洽

  v29.2 覆盖范围:
    - FEATURE_SCHEMA: 116 features (82→116)
    - REASON_TAGS: 119 tags (100→119)
    - 新增 4H features: bb_upper/lower_4h, sma_50_4h, atr_4h, ema_12/26_4h,
      extension_regime_4h, volatility_regime_4h 等
    - 新增 1D features: macd_signal/histogram_1d, bb_position_1d, atr_1d,
      ema_12/26_1d, extension_regime_1d, volatility_regime_1d 等
    - 新增 30M features: atr_pct_30m, ema_10/20_30m, obv_divergence_30m
    - 新增 multi-TF tags: EXTENSION_4H/1D, VOL_4H/1D, SMA/EMA_CROSS_4H, MACD_1D
    - Scoring 覆盖: 1D MACD, 4H SMA/EMA cross, OBI pressure, multi-TF vol/ext
    - Data categories: 新增 extension_ratio, volatility_regime, position_context

  核心原则: 同一指标×多时间框架完整覆盖
    每个指标 (RSI/MACD/ADX/BB/Extension/Volatility) 在所有可用时间框架
    (30M/4H/1D) 都有对应的 feature + tag + scoring 覆盖。
""")


def main():
    print("=" * 65)
    print("  📊 AI 质量评分深度诊断")
    print(f"  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # 1. Snapshot analysis (most reliable)
    analyze_snapshots_with_valid_tags()

    # 2. Log history
    records = analyze_log_history()

    # 3. Summary
    snapshot_count = len(glob.glob('data/feature_snapshots/*.json'))
    print_summary(records, snapshot_count)


if __name__ == '__main__':
    main()
