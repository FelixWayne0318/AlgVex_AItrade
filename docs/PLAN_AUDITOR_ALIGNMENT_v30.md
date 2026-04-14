# Auditor Alignment Plan v30.0 — "Agent 看到什么，Auditor 就验证什么"

## 根因分析：为什么 IMPLEMENTATION_PLAN 没有彻底解决这些问题

### 结论：实现不完整 + 设计不完善，两者兼有

**主因 — 实现不完整**: IMPLEMENTATION_PLAN 的 Phase 4 (Auditor 对齐) 和 Phase 3b (`_safe_filter_tags`) 从未编码实施。这是 P2 和 P7 未解决的**直接原因**。

**次因 — 原始 Phase 4 设计覆盖不足**: 即使按原设计实施，也只解决部分问题：

| 维度 | IMPLEMENTATION_PLAN Phase 4 设计 | 实际需求 (本方案) |
|------|-------------------------------|----------------|
| **覆盖方法** | 只提到 `_check_value_accuracy` (1/7) | 全部 7 个验证方法 |
| **数据源** | 只处理 `technical_data` (1/6) | 全部 6 个数据源 (含 sentiment/derivatives/orderbook/sr_zones) |
| **Key 映射策略** | 逐个方法散改 `rsi`→`rsi_30m` (分散, 易遗漏) | 集中翻译层 `_features_to_tf_data()` (一处变更) |
| **API 精简** | 保留 6 params + 新增 context (参数膨胀) | 精简为 `audit(ctx)` 唯一入参 |
| **30M ATR 命名** | 未识别 `atr` vs `atr_30m` 不对称 | 明确列出所有不遵循后缀规则的 key |
| **非技术数据** | 未涉及 sentiment/FR/OBI/SR zone 对齐 | `_features_to_nontech()` 完整覆盖 |
| **估计改动** | ~45 行 | ~190 行 |

本方案 (v30.0) 是对 IMPLEMENTATION_PLAN Phase 4 的**补全和重新设计**，而非简单实施。

---

## 设计意图

### 原始问题 (IMPLEMENTATION_PLAN Problem #2)

> 当前系统的数据获取、特征提取、AI 分析、记忆系统、质量审计 5 个子系统各自独立演化，导致：
> Quality Auditor 的数值验证 (`_check_value_accuracy`) 用 `technical_data` 原始字段名 (如 `rsi`, `adx`)，
> 但 Agent 看到 `feature_dict` 字段名 (如 `rsi_30m`, `adx_1d`) — 数据源和字段名均不对称。

### 设计目标

**核心原则**: Agent 看到什么，Auditor 就验证什么。

具体含义：
1. **同一份 ground truth** — Auditor 的数值比对必须使用 `ctx.features`（Agent 实际看到的数据），而非 `technical_data`（pipeline 原始输入）
2. **单一数据载体** — `AnalysisContext` 是全流程唯一数据载体。`audit()` 不应接收 ctx 之外的数据源参数
3. **确定性验证优先** — 能用结构化数据（features、tags）验证的，不用文本正则。正则仅用于从 AI 文本中**提取声称值**，不用于判断语义
4. **消除各自为政** — 修改任何数据源时，只需改 `extract_features()` 一处，Auditor 自动对齐

### 非目标

- ❌ 不改变 AI 决策逻辑（Bull/Bear/Judge/ET/Risk 的 prompt 和行为不变）
- ❌ 不改变 `extract_features()` 的输出 schema（FEATURE_SCHEMA 不变）
- ❌ 不改变交易执行逻辑
- ❌ 不删除任何现有验证维度（6 维验证全部保留）

---

## 当前状态审计

### IMPLEMENTATION_PLAN 7 个问题的完成度

| # | 问题 | 状态 | 证据 |
|---|------|------|------|
| P1 | 3-4 种数据表示 | ✅ 已解决 | Agent 端统一到 `ctx.features` + `ctx.scores` + `ctx.valid_tags` |
| P2 | Auditor/Agent 数据不对称 | ❌ **未解决** | `audit()` 仍接收 6 个 raw data params；7 个验证方法读 `technical_data` (key: `rsi`) 而非 `ctx.features` (key: `rsi_30m`) |
| P3 | 记忆只存 5 维度 | ✅ 已解决 | `MemoryConditions` 12 维度 (v29+)，`from_feature_dict()` 确保与 Agent 数据一致 |
| P4 | Quality Score/Grade 隔离 | ✅ 已解决 | `ctx.quality_score` 写回 context，`record_outcome()` 携带 `ai_quality_score` |
| P5 | valid_tags 重复计算 | ✅ 已解决 | `analyze()` 入口一次计算，各 Agent 从 `ctx` 读取 |
| P6 | Confidence 来源不追踪 | ✅ 已解决 | `ConfidenceChain` 追踪 Judge→ET→Risk 全链路，含 DEFAULT/COERCED 警告 |
| P7 | filter 后不验证 | ⚠️ 部分解决 | v29.6 tag-based MTF 检查避免了 false positive，但 `_safe_filter_tags()` 尚未引入 |

### Auditor 当前架构问题 (P2 的具体表现)

**问题 A: 双数据路径**

```
audit(ctx, technical_data, sentiment_data, order_flow_data, derivatives_data, orderbook_data, sr_zones_data)
       │           │
       │           └─→ 7 个验证方法读取 (key: rsi, adx, di_plus, macd, sma_20, ...)
       └─→ Agent outputs、valid_tags、features 读取 (key: rsi_30m, adx_1d, ...)
```

Agent 和 Auditor 看到的是**同一份原始数据经过不同路径的两种表示**。虽然当前值一致（`extract_features` 不做变换），但架构上不保证：如果未来 `extract_features()` 做了任何变换（归一化、滤波、平滑），Auditor 仍然验证原始值，而非 Agent 实际看到的值。

**问题 B: Key 命名不对称**

| 验证方法读取 | `technical_data` key | `ctx.features` key |
|-------------|---------------------|-------------------|
| `_check_value_accuracy` | `rsi` | `rsi_30m` |
| `_check_value_accuracy` | `adx` | `adx_30m` |
| `_check_value_accuracy` | `di_plus` | `di_plus_30m` |
| `_check_value_accuracy` | `bb_position` | `bb_position_30m` |
| `_check_comparison_claims` | `macd` / `macd_signal` | `macd_30m` / `macd_signal_30m` |
| `_check_comparison_claims` | `sma_20` / `sma_50` | `sma_20_30m` / `sma_50_30m` |
| `_check_price_values` | `atr` / `sma_200` | `atr` / `sma_200_1d` |
| `_check_zone_claims` | `rsi` → 手动分类 | `features` 已有 `extension_regime`、`volatility_regime`、`market_regime` |
| `_audit_di_citations` | `di_plus` / `di_minus` | `di_plus_30m` / `di_minus_30m` |
| `_check_nontech_claims` | `sentiment_data['positive_ratio']` | `features['long_ratio']` |
| `_check_nontech_claims` | `derivatives_data['funding_rate']['current_pct']` | `features['funding_rate_pct']` |
| `_check_nontech_claims` | `orderbook_data['obi']['weighted']` | `features['obi_weighted']` |
| `_check_nontech_claims` | `sr_zones['nearest_support'].price_center` | `features['nearest_support_price']` |
| `_check_counter_trend` | `mtf_trend_layer['di_plus']` / `['di_minus']` | `features['di_plus_1d']` / `features['di_minus_1d']` |

**问题 C: 嵌套结构 vs 扁平结构**

`technical_data` 使用嵌套结构（30M 在顶层，4H 在 `mtf_decision_layer`，1D 在 `mtf_trend_layer`）。
`ctx.features` 使用扁平结构（`rsi_30m`、`rsi_4h`、`rsi_1d` 同级）。

7 个验证方法都通过以下模式遍历时间框架：
```python
timeframes = [
    ('30M', technical_data),
    ('4H', technical_data.get('mtf_decision_layer') or {}),
    ('1D', technical_data.get('mtf_trend_layer') or {}),
]
```

---

## 修复方案

### 架构设计

```
analyze() 入口
  │
  ├─→ extract_features(raw_data) → ctx.features (扁平, 116 fields)
  │
  ├─→ 5 个 AI Agent 运行 (读 ctx.features + ctx.scores + ctx.valid_tags)
  │
  └─→ audit(ctx)                              ← 唯一入参
        │
        ├─→ _features_to_tf_data(ctx.features) → ground_truth (嵌套, 兼容现有方法)
        │     30M: {rsi, adx, di_plus, ...}
        │     4H:  {rsi, adx, di_plus, ...}
        │     1D:  {rsi, adx, di_plus, sma_200, ...}
        │
        ├─→ _features_to_nontech(ctx.features) → nontech_ground_truth
        │     sentiment: {positive_ratio, negative_ratio, ...}
        │     derivatives: {funding_rate: {current_pct, ...}}
        │     order_flow: {buy_ratio, ...}
        │     orderbook: {obi: {weighted, ...}}
        │     sr_zones: {nearest_support: {price_center}, nearest_resistance: {price_center}}
        │
        ├─→ 现有 7 个验证方法 (签名不变, 只是数据来源从 raw params 变为 ground_truth)
        │     _check_value_accuracy(text, ground_truth['technical'])
        │     _check_comparison_claims(text, ground_truth['technical'])
        │     _check_price_values(text, ground_truth['technical'])
        │     _check_zone_claims(text, ground_truth['technical'])
        │     _audit_di_citations(text, ground_truth['technical'])
        │     _check_nontech_claims(text, ground_truth['sentiment'], ...)
        │     _check_counter_trend(judge, ground_truth['technical'])
        │
        └─→ QualityReport → ctx.quality_score / ctx.quality_flags
```

**关键**: `_features_to_tf_data()` 从 `ctx.features` 反向构建嵌套结构。这意味着：
- **所有验证方法的内部逻辑不需要改动**（仍然用 `rsi`、`adx` 等 key 访问嵌套 dict）
- **Ground truth 来自 features**（= Agent 看到的数据），不来自 raw pipeline input
- **改动集中在 `audit()` 入口一处**（构建 ground_truth），而非分散在 7 个方法中

### Zone Claims 直接验证优化

对于 `_check_zone_claims()` 中的 regime 验证，`ctx.features` 已经包含预分类结果：

| 当前做法 (fragile) | 优化后 (deterministic) |
|-------------------|----------------------|
| 读 `technical_data['adx']` → 自行分类 → 比对 AI 文本中的 "trending"/"ranging" | 读 `features['market_regime']` 直接比对 |
| 读 `technical_data['extension_regime']` 字符串 → 正则匹配 AI 文本 | 读 `features['extension_regime']` 直接比对 |
| 读 `technical_data['volatility_regime']` 字符串 → 正则匹配 AI 文本 | 读 `features['volatility_regime']` 直接比对 |

**注意**: AI 文本中的 "claim detection" 仍然需要正则（必须从自由文本中提取 AI 声称了什么）。但 "ground truth" 部分从 features 读取，消除了数据路径不对称。

---

## Phase 实施

### Phase A: AnalysisContext 增加 raw_data 字段 (过渡期)

**目标**: 让 `AnalysisContext` 承载原始数据源，使 `audit()` 可以从 ctx 获取所有需要的数据。

**改动**: `agents/analysis_context.py`

```python
@dataclass
class AnalysisContext:
    # ... 现有字段 ...

    # ===== Phase 4b: Agent outputs (已存在) =====
    bull_output: Optional[Dict[str, Any]] = None
    # ...

    # ===== 新增: raw_data bundle (Phase A, 过渡期) =====
    # audit() 过渡期需要原始数据做 citation verification。
    # Phase B 完成后 (ground truth 全部从 features 构建)，此字段可删除。
    raw_data: Optional[Dict[str, Any]] = None
```

**改动**: `agents/multi_agent_analyzer.py` (analyze() 中)

```python
# 在 ctx 初始化后、audit() 调用前:
ctx.raw_data = {
    'technical': technical_report,
    'sentiment': sentiment_report,
    'order_flow': order_flow_report,
    'derivatives': derivatives_report,
    'orderbook': orderbook_report,
    'sr_zones': sr_zones,
}
```

**改动**: `audit()` 签名

```python
# 之前:
def audit(self, ctx, technical_data=None, sentiment_data=None, ...):

# 之后:
def audit(self, ctx: AnalysisContext) -> QualityReport:
    # 从 ctx 获取一切
```

**向后兼容**: `diagnose_quality_scoring.py` 等外部调用者需要同步更新（将 6 个 params 打包为 `ctx.raw_data`）。

### Phase B: Ground Truth 构建 — 从 features 反向映射

**目标**: 在 `audit()` 内部，从 `ctx.features` 构建与现有验证方法兼容的 ground truth 数据结构。

**新增方法**: `ai_quality_auditor.py`

```python
@staticmethod
def _features_to_tf_data(features: Dict[str, Any]) -> Dict[str, Any]:
    """Build nested TF-indexed ground truth from flat features dict.

    Produces the same nested structure as `technical_data` (30M top-level,
    4H in 'mtf_decision_layer', 1D in 'mtf_trend_layer') so existing
    verification methods work unchanged.

    This is the KEY alignment: ground truth comes from features (= what
    agents saw), not from raw pipeline input.
    """
    # Suffix → timeframe key mapping
    _TF_SUFFIXES = {
        '30m': None,   # 30M fields go to top-level
        '4h': 'mtf_decision_layer',
        '1d': 'mtf_trend_layer',
    }

    # Feature key → base indicator name mapping
    # e.g., 'rsi_30m' → base='rsi', tf='30m'
    # e.g., 'macd_signal_4h' → base='macd_signal', tf='4h'
    _INDICATOR_BASES = [
        'rsi', 'adx', 'di_plus', 'di_minus', 'bb_position',
        'volume_ratio', 'macd_histogram', 'macd_signal', 'macd',
        'sma_20', 'sma_50', 'sma_200', 'atr', 'atr_pct',
        'bb_upper', 'bb_lower', 'ema_10', 'ema_12', 'ema_20', 'ema_26',
        'extension_ratio', 'extension_regime',
        'volatility_regime', 'volatility_percentile',
    ]

    result: Dict[str, Any] = {}
    tf_4h: Dict[str, Any] = {}
    tf_1d: Dict[str, Any] = {}

    for base in _INDICATOR_BASES:
        for suffix, target_key in _TF_SUFFIXES.items():
            feat_key = f'{base}_{suffix}'
            val = features.get(feat_key)
            if val is not None:
                if target_key is None:
                    result[base] = val       # 30M → top level
                elif target_key == 'mtf_decision_layer':
                    tf_4h[base] = val        # 4H
                elif target_key == 'mtf_trend_layer':
                    tf_1d[base] = val        # 1D

    # ⚠️ 修正 1: 不遵循 {base}_{tf} 后缀规则的 feature key
    # 这些 key 在 extract_features() 中以顶层名称存储 (无 _30m 后缀),
    # 对应 30M/顶层数据, 必须通过此 fallback 路径映射:
    #   price       → features['price']            (30M 当前价)
    #   atr         → features['atr']              (30M ATR, 非 atr_30m)
    #   atr_pct     → features['atr_pct']          (30M ATR%, 非 atr_pct_30m)
    #   extension_ratio   → features['extension_ratio']   (30M, 非 extension_ratio_30m)
    #   extension_regime  → features['extension_regime']  (30M, 非 extension_regime_30m)
    #   volatility_regime → features['volatility_regime'] (30M, 非 volatility_regime_30m)
    #   volatility_percentile → features['volatility_percentile'] (30M)
    #   market_regime     → features['market_regime']     (预计算, ADX-based)
    _TOP_LEVEL_KEYS = (
        'price', 'atr', 'atr_pct', 'extension_ratio',
        'extension_regime', 'volatility_regime',
        'volatility_percentile', 'market_regime',
    )
    for key in _TOP_LEVEL_KEYS:
        val = features.get(key)
        if val is not None:
            result[key] = val

    if tf_4h:
        result['mtf_decision_layer'] = tf_4h
    if tf_1d:
        result['mtf_trend_layer'] = tf_1d

    return result


@staticmethod
def _features_to_nontech(features: Dict[str, Any]) -> Dict[str, Any]:
    """Build non-technical ground truth dicts from features.

    Returns dict with keys: sentiment, derivatives, order_flow, orderbook, sr_zones.
    Structure matches what existing _check_nontech_claims() expects.
    """
    result = {}

    # Sentiment
    lr = features.get('long_ratio')
    sr = features.get('short_ratio')
    if lr is not None or sr is not None:
        result['sentiment'] = {
            'positive_ratio': lr,
            'negative_ratio': sr,
            'degraded': features.get('sentiment_degraded', False),
        }

    # Derivatives
    fr = features.get('funding_rate_pct')
    if fr is not None:
        result['derivatives'] = {
            'funding_rate': {'current_pct': fr},
        }

    # Order flow
    br = features.get('buy_ratio_30m')
    if br is not None:
        result['order_flow'] = {'buy_ratio': br}

    # Orderbook
    obi = features.get('obi_weighted')
    if obi is not None:
        result['orderbook'] = {'obi': {'weighted': obi}}

    # S/R zones
    # ⚠️ 修正 2: 使用 SimpleNamespace 替代 type() hack
    # _check_nontech_claims 通过 .price_center 属性访问 zone 对象。
    # SimpleNamespace 是标准库, 比动态 type() 更安全可读。
    from types import SimpleNamespace
    sp = features.get('nearest_support_price')
    rp = features.get('nearest_resist_price')
    if sp is not None or rp is not None:
        sr_dict = {}
        if sp is not None:
            sr_dict['nearest_support'] = SimpleNamespace(price_center=sp)
        if rp is not None:
            sr_dict['nearest_resistance'] = SimpleNamespace(price_center=rp)
        result['sr_zones'] = sr_dict

    return result
```

**改动**: `audit()` 方法体

```python
def audit(self, ctx: AnalysisContext) -> QualityReport:
    features = ctx.features or {}

    # Build ground truth from features (= what agents saw)
    if features:
        gt_tech = self._features_to_tf_data(features)
        gt_nontech = self._features_to_nontech(features)
    else:
        # Fallback: use raw data (for diagnostic scripts without features)
        rd = ctx.raw_data or {}
        gt_tech = rd.get('technical')
        gt_nontech = {
            'sentiment': rd.get('sentiment'),
            'derivatives': rd.get('derivatives'),
            'order_flow': rd.get('order_flow'),
            'orderbook': rd.get('orderbook'),
            'sr_zones': rd.get('sr_zones'),
        }

    # 所有验证方法使用 gt_tech / gt_nontech
    # (方法内部签名不变, 只是传入的数据来源不同)
```

### Phase C: `_check_zone_claims` 优化 — 直接使用 features 中的预分类

**目标**: Zone/regime 验证不再从 raw 数值重新分类，而是直接读 features 中的预计算结果。

**当前代码** (`_check_zone_claims` 中):
```python
# Extension regime (fragile: reads string from technical_data, regex-matches agent text)
ext_regime = technical_data.get('extension_regime', '')
# ... regex to detect AI's extension claim ...
# Compare
```

**改后**:
```python
# Ground truth from features already contains the regime classification
ext_regime = gt_tech.get('extension_regime', '')
vol_regime = gt_tech.get('volatility_regime', '')
mkt_regime = gt_tech.get('market_regime', '')

# Regex still needed to DETECT what AI claims, but ground truth is aligned
```

此优化的关键：Agent 在 prompt 中看到的 regime 分类来自 `_format_technical_report()` → 读取 `technical_report['extension_regime']`。`extract_features()` 也读取同一个字段。所以 `features['extension_regime']` 和 Agent 看到的完全一致。

### Phase D: `_safe_filter_tags()` 引入 (IMPLEMENTATION_PLAN Phase 3b)

**目标**: 完成 IMPLEMENTATION_PLAN 中未实现的 Phase 3b — filter 后 re-validate。

**改动**: `agents/multi_agent_analyzer.py`

```python
def _safe_filter_tags(self, output: dict, valid_tags: Set[str], agent_label: str) -> int:
    """Filter invalid tags and ensure evidence/decisive_reasons is never empty."""
    removed = filter_output_tags(output, valid_tags)
    # Check evidence (Bull/Bear)
    if 'evidence' in output and not output['evidence']:
        output['evidence'] = ['INCONCLUSIVE']
        self.logger.warning(f"[{agent_label}] All evidence tags filtered — INCONCLUSIVE fallback")
    # Check decisive_reasons (Judge/ET)
    if 'decisive_reasons' in output and not output['decisive_reasons']:
        output['decisive_reasons'] = ['INCONCLUSIVE']
        self.logger.warning(f"[{agent_label}] All decisive_reasons filtered — INCONCLUSIVE fallback")
    return removed
```

替换 `filter_output_tags()` 直接调用 (当前 1 处，line 587)。

### Phase E: 清理 — 移除旧接口

**目标**: 删除 `audit()` 的 6 个 raw data params，统一到 `ctx` 唯一入口。

**改动 1**: `ai_quality_auditor.py` — `audit()` 签名精简

```python
# 之前:
def audit(self, ctx, technical_data=None, sentiment_data=None,
          order_flow_data=None, derivatives_data=None,
          orderbook_data=None, sr_zones_data=None):

# 之后:
def audit(self, ctx: AnalysisContext) -> QualityReport:
```

**改动 2**: `multi_agent_analyzer.py` — 调用处精简

```python
# 之前:
quality_report = self._quality_auditor.audit(
    ctx=ctx,
    technical_data=technical_report,
    sentiment_data=sentiment_report,
    order_flow_data=order_flow_report,
    derivatives_data=derivatives_report,
    orderbook_data=orderbook_report,
    sr_zones_data=sr_zones,
)

# 之后:
quality_report = self._quality_auditor.audit(ctx)
```

**改动 3**: `scripts/diagnose_quality_scoring.py` — 外部调用者适配

```python
# 之前:
report = auditor.audit(ctx=ctx, technical_data=data['technical_data'], ...)

# 之后:
ctx.raw_data = {
    'technical': data['technical_data'],
    'sentiment': data.get('sentiment_report'),
    # ...
}
report = auditor.audit(ctx)
```

---

## 改动范围汇总

| 文件 | Phase | 改动类型 | 估计行数 |
|------|-------|---------|---------|
| `agents/analysis_context.py` | A | 新增 `raw_data` 字段 + agent outputs 字段 (如缺失) | ~5 行 |
| `agents/ai_quality_auditor.py` | B | 新增 `_features_to_tf_data()` + `_features_to_nontech()` | ~80 行 |
| `agents/ai_quality_auditor.py` | B | 修改 `audit()` 方法体 — 构建 ground truth | ~30 行改 |
| `agents/ai_quality_auditor.py` | C | `_check_zone_claims` 使用 features 预分类 | ~15 行改 |
| `agents/ai_quality_auditor.py` | E | 删除 `audit()` 6 个 params | ~6 行删 |
| `agents/multi_agent_analyzer.py` | A | 设置 `ctx.raw_data` | ~8 行 |
| `agents/multi_agent_analyzer.py` | D | 新增 `_safe_filter_tags()` + 替换 1 处调用 | ~15 行 |
| `agents/multi_agent_analyzer.py` | E | 精简 `audit()` 调用处 | ~8 行删 |
| `scripts/diagnose_quality_scoring.py` | E | 适配新 `audit()` 签名 | ~15 行改 |
| **总计** | | | ~190 行改动 |

---

## 数据对齐验证矩阵

修复完成后，以下映射必须全部成立。

> **⚠️ 修正 3: bb_position 单位无需特殊处理**
> Features 存储 bb_position 为 0-1 范围 (如 0.72)。Auditor 的 `_VALUE_VERIFY_INDICATORS`
> 已有 `scale_factor=100.0`，自动执行 `actual_value × 100` 得到 72 用于比较。
> `_features_to_tf_data()` 直接传递 0-1 值即可，**不需要**在映射时做任何单位转换。
> 这与当前 `technical_data['bb_position']` (也是 0-1) 的行为完全一致。

| Auditor 验证 | Ground Truth 来源 | 与 Agent 看到的是否同一份数据 |
|-------------|------------------|--------------------------|
| RSI 数值准确性 | `ctx.features['rsi_30m']` → gt_tech['rsi'] | ✅ 同一份 |
| ADX 数值准确性 | `ctx.features['adx_30m']` → gt_tech['adx'] | ✅ 同一份 |
| DI+/DI- 比较方向 | `ctx.features['di_plus_1d']` → gt_tech['mtf_trend_layer']['di_plus'] | ✅ 同一份 |
| MACD vs Signal 方向 | `ctx.features['macd_30m']` / `ctx.features['macd_signal_30m']` | ✅ 同一份 |
| Extension Regime | `ctx.features['extension_regime']` | ✅ 同一份 |
| Volatility Regime | `ctx.features['volatility_regime']` | ✅ 同一份 |
| Funding Rate | `ctx.features['funding_rate_pct']` | ✅ 同一份 |
| Sentiment L/S | `ctx.features['long_ratio']` / `ctx.features['short_ratio']` | ✅ 同一份 |
| OBI | `ctx.features['obi_weighted']` | ✅ 同一份 |
| S/R Prices | `ctx.features['nearest_support_price']` / `ctx.features['nearest_resist_price']` | ✅ 同一份 |
| MTF 职责 (v29.6) | `result.citations` tag categories | ✅ 同一份 (tag-based) |
| Data Coverage | `_TAG_TO_CATEGORIES` + `_DATA_CATEGORY_MARKERS` | ✅ 同一份 (tag primary) |
| Counter-trend | `ctx.features['di_plus_1d']` / `ctx.features['di_minus_1d']` | ✅ 同一份 |

---

## 验证方式

### 自动化验证

```bash
# 1. 逻辑同步检查
python3 scripts/check_logic_sync.py

# 2. 回归检测
python3 scripts/smart_commit_analyzer.py

# 3. 现有测试
python3 -m pytest tests/ -x -q

# 4. 质量评分端到端测试 (使用 feature snapshot)
python3 scripts/diagnose_quality_scoring.py
```

### 手动验证

| 验证点 | 方法 | 预期 |
|--------|------|------|
| ground truth 与 features 一致 | 在 `audit()` 中 assert `gt_tech['rsi'] == features['rsi_30m']` (debug 模式) | 完全一致 |
| audit() 只接收 ctx | grep 确认无其他参数传入 | 所有调用点只传 ctx |
| 6 个旧 params 完全删除 | grep `technical_data.*sentiment_data` in auditor | 0 匹配 |
| _safe_filter_tags 覆盖调用处 | grep `filter_output_tags` 确认无直接调用残留 (仅 import 保留) | 0 直接调用 |

---

## 实施顺序与安全保障

| 步骤 | 内容 | 回滚风险 |
|------|------|---------|
| 1 | Phase A: 新增 `raw_data` 字段 + 设置 | 零风险 (纯增量) |
| 2 | Phase B: 新增 ground truth 构建方法 | 零风险 (新方法, 未调用) |
| 3 | Phase B: `audit()` 切换到 ground truth | 低风险 (数据值一致, 只是来源变了) |
| 4 | Phase C: zone claims 直接使用 features 预分类 | 低风险 (同一数据, 更直接) |
| 5 | Phase D: `_safe_filter_tags()` + 1 处替换 | 低风险 (增加保护, 不改现有逻辑) |
| 6 | Phase E: 清理旧参数 + 更新调用者 | 中风险 (接口变更, 需同步所有调用者) |
| 7 | 运行全部验证 | — |

**回滚策略**: Phase A-D 都是纯增量，可随时回滚。Phase E 是破坏性变更（接口删除），但只有 2 个调用者需要同步，风险可控。

### 回滚命令

```bash
# 完整回滚 (所有 Phase)
cd /home/linuxuser/nautilus_AlgVex && git log --oneline -10  # 找到 v30.0 之前的 commit hash
cd /home/linuxuser/nautilus_AlgVex && git revert <v30.0-commit-hash> --no-edit

# 无需清理的状态文件:
# - 无新增持久化文件 (raw_data 是内存字段)
# - 无新增配置文件
# - 无数据库 migration
```

**回滚后验证**:
```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && python3 -m pytest tests/ -x -q && python3 scripts/check_logic_sync.py
```

---

## 修复后架构 vs 修复前

### 修复前 (各自为政)
```
extract_features(raw) → ctx.features ──→ 5 AI Agents
                                              │
                                              ↓
raw_data ─────────────────────────────→ audit(ctx, raw₁, raw₂, raw₃, raw₄, raw₅, raw₆)
                                              │
                                              ↓ (7 methods read raw)
                                        QualityReport
```
**问题**: Agent 看 features (path A)，Auditor 验 raw (path B)。两条独立路径。

### 修复后 (统一数据载体)
```
extract_features(raw) → ctx.features ──→ 5 AI Agents
                              │
                              ↓
                     _features_to_tf_data(ctx.features)
                              │
                              ↓
                     audit(ctx) → 7 methods read ground_truth (from features)
                              │
                              ↓
                        QualityReport
```
**结果**: Agent 和 Auditor 读同一份 features。一条路径。修改 `extract_features()` 自动对齐所有消费者。
