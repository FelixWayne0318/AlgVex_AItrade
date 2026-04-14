# v40.0 Implementation Plan: Hierarchical Signal Architecture

## 目标
解决系统性信号偏差问题：恢复行情中 88% SHORT 信号、LEAN 市场 55-65% HOLD、重复计票、AI 锚定偏差。

## 版本命名: v40.0 — Hierarchical Signal Architecture

---

## Phase 1: 消除重复计票 (compute_scores_from_features)

**文件**: `agents/report_formatter.py` L649-784

**修改内容**: 删除 v39.0 新增的 3 个重复 4H 独立投票

删除以下代码块 (L734-758):
- `4H DI pressure` (L734-742): 已在 momentum L817-823 使用
- `4H RSI standalone` (L744-750): 已在 4H RSI+MACD 合并投票 L709 和 momentum L791 使用
- `4H MACD standalone` (L752-758): 已在 4H RSI+MACD 合并投票 L709 和 momentum L801 使用

**效果**: trend_signals 从 ~14 → ~11，4H 数据不再被计入 4 次

---

## Phase 1b: 指标分类加权 (Indicator Classification Weighting)

### 问题诊断

当前 `compute_scores_from_features()` 对所有指标使用 **等权 ±1 投票**：

```python
# 当前: CVD-Price ACCUMULATION 和 buy_ratio=0.51 贡献相同的 ±1
flow_signals.append(1)   # CVD accumulation — 聪明钱逆价格操作
flow_signals.append(1)   # buy_ratio > 0.55 — 可能只是噪音
```

但系统已经有完整的指标分类和 regime 权重:
- `SIGNAL_CONFIDENCE_MATRIX` 定义了每个指标的 Nature (Leading/Lagging/Sync/Sync-lag) 和 5 种 regime 下的可靠性倍率 (0.3-1.3)
- `_SIGNAL_ANNOTATIONS` 编码了相同信息供代码使用
- `INDICATOR_KNOWLEDGE_BRIEF` 教 AI "CONFLUENCE HIERARCHY: Layer 1 > Layer 2 > Layer 3"

**但 `compute_scores_from_features()` 完全忽略了这些信息** — 它的 ±1 投票既不区分指标类型，也不根据 regime 调整权重。

### 调研发现

基于学术文献和行业实践的调研:

#### 1. 指标信息内容 (Information Coefficient) 差异

| 指标类型 | 典型 IC (crypto) | Signal Decay Half-life | 最佳用法 |
|----------|:---:|:---:|------|
| **领先 (Leading)**: CVD divergence, OBI shift, FR trend | 0.08-0.15 | 1-4h | 预判转折，高噪音需 2+ 确认 |
| **同步 (Sync)**: RSI level, BB position, volume ratio | 0.05-0.10 | 4-8h | 衡量当前状态，确认动量 |
| **同步-滞后 (Sync-lag)**: MACD histogram, CVD cumulative, OBV | 0.06-0.12 | 8-24h | 动量方向+强度，较低噪音 |
| **滞后 (Lagging)**: SMA cross, MACD cross, ADX/DI | 0.03-0.08 | 24h-7d | 趋势确认，高确定性但反应慢 |

> 来源: [Robot Wealth: Quantifying and Combining Crypto Alphas](https://robotwealth.com/quantifying-and-combining-crypto-alphas/), [arXiv:2507.07107 - Regime-Dependent Factor Rotation](https://www.arxiv.org/pdf/2507.07107), [SSRN: Systematic Trading with RMA](https://papers.ssrn.com/sol3/Delivery.cfm/5278107.pdf?abstractid=5278107), [Vadim's Blog: ML Features for Crypto Scalping](https://vadim.blog/ml-features-crypto-scalping-research-papers)

#### 2. Regime-Aware 动态权重 (行业共识)

Gresham LLC 2025 报告: "In more stable, directional environments, we lean into medium/long-term trend signals; during choppier periods, shorter-term models take on a greater role."

State Street 2025: 使用 QCD (Quantile-Conditional Density) 评估因子在不同 regime 下的稳定性和可预测性。

**共识**: ADX>40 时滞后指标最可靠 (趋势稳定); ADX<20 时领先+同步指标最可靠 (均值回归环境)。这与 `SIGNAL_CONFIDENCE_MATRIX` 的权重设计完全一致。

#### 3. Signal Combination 最佳实践

- **不等权组合**: "You might combine your signals using simple heuristics (equal weight, equal volatility contribution), or by selecting coefficients based on how the signals behave." — Robot Wealth
- **IC 稳定性加权**: "You'd want to down-weight factors that outperformed in the past but have levelled off recently."
- **Ensemble 多样性**: OFI (flow-based) + LSTM (learned) + OU (statistical) — "agreement approach works best with diverse model types"
- **Volatility-regime adjustment** 使 mean IC 提升 35% (crypto 因子研究)

#### 4. Confirmation Cascade (行业实践)

CME Group 2019: 85% 的专业交易者使用 ≥2 个指标确认入场，62% 使用 ≥3 个。

行业标准层级:
1. **结构 (Structure)**: 趋势方向 → 过滤器
2. **动量 (Momentum)**: 速度/加速度 → 确认
3. **成交量/订单流 (Volume/Flow)**: 参与度 → 最终确认

**关键**: "A lot of traders confuse correlated indicators with true confluence. Both RSI and Stochastics screaming oversold is really just one signal shown two ways." — 这正是当前系统的等权投票问题。

#### 5. 背离信号的特殊地位

- 单个背离 false positive 40-60% (系统已在 `INDICATOR_KNOWLEDGE_BRIEF` 中记录)
- 2+ 背离 confluence 显著降低 false positive
- 背离是**反转预警**，不应与趋势跟随信号等权投票
- 当前代码将 divergence 混在 `mom_signals` 中，被 ~10 个动量信号稀释

#### 6. Order Flow 的信息密度差异

CoinGlass 行业框架:
- **CVD-Price Cross** (ACCUMULATION/DISTRIBUTION): 高信息密度 — "聪明钱逆价格操作"
- **CVD trend**: 中信息密度 — 方向性买卖压力
- **Buy ratio**: 低信息密度 — 高噪音，0.51 vs 0.55 几乎无区别
- **OBI**: 中信息密度 — 挂单意愿，但可被 spoof

> 来源: [Scribd: Decoding Market Dynamics](https://www.scribd.com/document/829499049/Decoding-Market-Dynamics-Price-CVD-OI-and-Funding-Rate), [Bookmap: CVD Trading Guide](https://bookmap.com/blog/how-cumulative-volume-delta-transform-your-trading-strategy), [Mind Math Money: Order Flow Trading](https://www.mindmathmoney.com/articles/the-ultimate-order-flow-trading-course-full-guide-2025)

### 设计方案: 三层加权架构

基于以上调研，`compute_scores_from_features()` 的信号权重按 3 层组织:

#### Layer A: 指标内加权 (Intra-dimension Signal Weighting)

每个维度内部，不同指标根据信息密度获得不同权重:

```python
# ── Trend Dimension: 按滞后程度加权 ──
# 理由: 极滞后指标 (SMA200) 确认大方向，中等滞后 (DI spread) 确认近期变化
trend_weighted = [
    (sma200_signal, 1.5),    # 宏观过滤器，高权重 (Lagging, 最高确定性)
    (adx_dir_signal, 1.2),   # 趋势存在性确认 (Lagging)
    (macd_1d_signal, 1.0),   # 标准权重 (Lagging)
    (rsi_1d_signal, 0.6),    # 弱趋势信号 (Sync, 在趋势维度权重低)
    (di_spread_signal, 0.8), # 趋势强度变化 (Lagging)
    (adx_trend_signal, 0.7), # 趋势动态 (Lagging)
    # 4H 信号在 trend 维度权重较低 (它们主要贡献给 momentum)
    (rsi_macd_4h_signal, 0.5), # 4H 对 trend 的辅助确认
    (sma_4h_signal, 0.8),     # 4H SMA 交叉 (中期趋势)
    (ema_4h_signal, 0.7),     # 4H EMA 交叉
    (di_4h_signal, 0.6),      # 4H DI (已在 momentum 主要使用)
    (rsi_4h_trend_standalone, 0.4),  # 4H RSI 单独 (弱)
    (macd_4h_standalone, 0.5),       # 4H MACD 单独 (弱)
    (rsi_macd_30m_signal, 0.5),      # 30M 对趋势有限但不应完全忽略 (ET 核心输入, 0.3 太低导致 trend_score 与执行层脱节)
    (di_spread_1d_signal, 0.8),      # DI spread 趋势
]
weighted_sum = sum(s * w for s, w in trend_weighted if s is not None)
weight_total = sum(w for s, w in trend_weighted if s is not None)
trend_raw = weighted_sum / weight_total if weight_total > 0 else 0

# ── Order Flow Dimension: 按信息密度加权 ──
# 理由: CVD-Price Cross (聪明钱行为模式) >> CVD trend >> buy_ratio (噪音)
flow_weighted = [
    (cvd_cross_4h_signal, 2.0),   # 最高信息密度: 聪明钱逆价格操作 (Leading)
    (cvd_cross_30m_signal, 1.5),  # 30M 版本稍低 (更短 horizon)
    (cvd_4h_signal, 1.0),         # 方向性压力 (Sync-lag)
    (cvd_30m_signal, 0.8),        # 30M CVD trend
    (taker_ratio_signal, 0.6),    # 主动买卖 (Leading, 但高噪音)
    (buy_ratio_30m_signal, 0.5),  # 高噪音 (Sync)
    (buy_ratio_4h_signal, 0.5),   # 同上
    (obi_signal, 0.8),            # 挂单压力 (Leading, 可被 spoof)
    (obi_change_signal, 0.5),     # OBI 变化率 (高噪音)
]

# ── Momentum Dimension: 背离独立处理 ──
# 理由: 背离是反转预警，不应被 ~10 个趋势跟随信号稀释
mom_base_weighted = [
    (rsi_4h_trend_signal, 1.0),        # RSI 动量方向 (Sync)
    (macd_hist_4h_signal, 1.2),        # MACD histogram 动量强度 (Sync-lag)
    (adx_4h_trend_signal, 0.8),        # ADX 趋势强度变化
    (di_4h_pressure_signal, 0.7),      # DI 方向压力
    (volume_4h_signal, 0.9),           # 成交量确认
    (rsi_30m_trend_signal, 0.6),       # 30M 动量方向
    (mom_shift_30m_signal, 0.8),       # 30M 加速/减速
    (price_4h_change_signal, 0.7),     # 价格动量
    (bb_pos_4h_signal, 0.5),           # BB 位置 (弱动量信号)
    (macd_hist_30m_signal, 0.6),       # 30M MACD histogram
]

# 背离信号独立评估，作为 trend_score 修正因子而非 momentum 投票
divergence_adjustment = 0
if div_bull >= 3:
    divergence_adjustment = -3  # 强反转预警
elif div_bull >= 2:
    divergence_adjustment = -2  # 中等反转预警
if div_bear >= 3:
    divergence_adjustment = 3
elif div_bear >= 2:
    divergence_adjustment = 2
# 应用到 trend_score (降低趋势确信度) 而非 momentum 投票
# v40.0: 互斥 — reversal detection (v39.0) 已包含背离作为 5 条件之一
# reversal_active=True 时不再额外扣分，避免 -2 + -3 = -5 压碎 trend_score
# (reversal_active 在 v39.0 L1132 计算, 此处引用)
if not reversal_active:
    trend_score = max(0, trend_score + divergence_adjustment)
```

#### Layer B: (已合并到 Layer C — 避免双重放大)

经审查，独立的 Layer B regime 倍率与 Layer C 维度间权重叠加产生极端权重比:
- ADX>40: SMA200 = 1.5 (base) × 1.3 (regime) × 1.5 (dim) = **2.925**
- 同时: CVD-Price = 2.0 (base) × 0.7 (regime) × 0.8 (dim) = **1.12**
- 比值 **2.6:1** — 过度抑制领先指标 (CVD-Price 在趋势反转初期恰恰最有价值)

**设计决定**: 取消 Layer B 的 regime 倍率。Layer A (信息密度 base weight) 和 Layer C (维度间 regime 权重) 各司其职，不叠加。

删除后最大比值: `1.5 × 1.5` : `2.0 × 0.8` = 2.25 : 1.6 = **1.4:1** — 合理。

`_SIGNAL_ANNOTATIONS` 的 regime 权重保持用于文本报告 Tier 分级 (原有功能 `_get_multiplier()`)，不扩展到评分引擎。

#### Layer C: 维度间加权 (Inter-dimension Weighting)

已在 Phase 3 定义:
- TRANSITIONING: order_flow 2x (领先指标主导)
- ESTABLISHED (trend_score≥5): trend 1.5x (趋势确认主导)
- DEFAULT: 1:1:1

**新增**: Regime-aware 维度权重 (承担 Layer B 删除后的 regime 适配职责)

```python
# 当 ADX<20 (盘整)，领先指标维度权重提升
if adx_effective < 20 and _regime_transition == "NONE":
    weights = {"trend": 0.7, "momentum": 1.0, "order_flow": 1.5}
# 当 ADX>40 (强趋势)，滞后指标维度权重提升
elif adx_effective >= 40 and _regime_transition == "NONE":
    weights = {"trend": 1.5, "momentum": 1.0, "order_flow": 0.8}
```

### 实施约束

1. **不修改 `_SIGNAL_ANNOTATIONS`** — 它是 SSoT，只读取不写入 (继续用于文本报告 Tier 分级)
2. **不修改 `SIGNAL_CONFIDENCE_MATRIX`** — 它给 AI prompt 用，不给代码用
3. **背离信号移出 `mom_signals`** — 作为 `trend_score` 修正因子，与 v39.0 reversal 互斥应用
4. **权重硬编码为常量** — 不经 YAML 配置（领域知识，与 Extension/Volatility 阈值同理）
5. **保持函数签名不变** — `compute_scores_from_features(f)` 返回值结构不变
6. **只有两层加权** — Layer A (信息密度 base weight) + Layer C (维度间 regime 权重)，不叠加第三层

### 与现有 Phase 的交互

- **Phase 1**: 删除重复投票后再加权 (先去重再加权，顺序不可反)
- **Phase 2**: TRANSITIONING 检测不变，但加权后的 flow_dir/trend_dir 更准确
- **Phase 3**: 维度间权重保持不变，Layer C 是 Phase 3 的扩展
- **v39.0 Trend Reversal Detection**: 背离修正因子与 reversal detection **互斥应用** — 当 `reversal_active=True` 时 `divergence_adjustment` 不再额外扣分 (避免双重 -2 + -3 = -5 压碎 trend_score。背离已被 reversal 5 条件组合包含)

### 验证方法

1. 用现有 `data/feature_snapshots/` 对比加权前后的 dim_scores 差异
2. `diagnose_quality_scoring.py` 验证评分系统完整性
3. `backtest_from_logs.py` 对比加权前后的信号质量 (胜率/PnL)
4. 关注 ADX<20 regime 下 order_flow 信号是否更敏感 (目标: 减少盘整期误判)

---

## Phase 2: TRANSITIONING Regime 检测

**文件**: `agents/report_formatter.py` — `compute_scores_from_features()` 末尾 (L1134 之前)

**新增逻辑**: 在 Net Assessment 之前，检测领先指标 vs 滞后指标方向冲突

```python
# ── Regime Transition Detection ──
# When leading indicators (order_flow) oppose lagging indicators (trend),
# the market may be transitioning. This is NOT "conflicting" — it's informative.
_regime_transition = "NONE"
if flow_dir != "N/A" and flow_dir != "MIXED":
    if trend_dir == "BEARISH" and flow_dir == "BULLISH":
        _regime_transition = "TRANSITIONING_BULLISH"
    elif trend_dir == "BULLISH" and flow_dir == "BEARISH":
        _regime_transition = "TRANSITIONING_BEARISH"
```

**效果**: 当订单流与趋势方向相反时，系统识别为"过渡期"而非"冲突"

### 2b: TRANSITIONING 防抖 (Hysteresis)

**问题**: TRANSITIONING 可能在一个周期触发、下个周期消失，导致 whipsaw 交易。

**新增逻辑**: 2-cycle 持久性要求

```python
# ── Hysteresis: require 2 consecutive cycles of same transition signal ──
# _prev_regime_transition is stored as instance variable or returned in scores
_raw_transition = _regime_transition  # current cycle detection
if _raw_transition != "NONE":
    _prev = f.get("_prev_regime_transition", "NONE")
    if _prev == _raw_transition:
        _regime_transition = _raw_transition  # confirmed: 2 consecutive cycles
    else:
        _regime_transition = "NONE"  # first cycle: don't act yet
        # Store raw detection for next cycle comparison
```

**实现选项**: `_prev_regime_transition` 通过 feature_dict 传入 (由调用方从上次 `dim_scores` 中读取)，或作为模块级变量缓存。推荐前者，保持函数纯性。

### 2c: order_flow 不可用时的 Fallback

**问题**: TRANSITIONING 完全依赖 `flow_dir`。当 `_avail_order_flow=False` 时，feature 完全失效。

**新增逻辑**: 使用 momentum 方向作为 fallback leading indicator

```python
# Fallback when order_flow unavailable: use momentum as leading proxy
if not _avail_order_flow and _avail_mtf_4h:
    if trend_dir == "BEARISH" and mom_dir == "BULLISH":
        _regime_transition = "TRANSITIONING_BULLISH"
    elif trend_dir == "BULLISH" and mom_dir == "BEARISH":
        _regime_transition = "TRANSITIONING_BEARISH"
    # Note: momentum is less leading than order_flow, so this is weaker signal
```

**设计理由**: momentum (4H RSI/MACD) 通常早于 trend (1D SMA/ADX) 转向，虽然不如 order_flow (CVD/OI) 那么领先。有弱信号 > 无信号。

---

## Phase 3: Regime-Dependent 加权 Net 计算

**文件**: `agents/report_formatter.py` L1134-1173

**替换现有 Net Assessment 逻辑**:

当前: `net_raw = sum(dir_scores) / len(dir_scores)` (1:1:1 等权)

### ⚠️ P0 Bug Fix: zip 映射错位

**问题**: 原方案用 `zip(_available_dirs, ["trend", "momentum", "order_flow"][:len(_available_dirs)])` — 当某个维度因 `_avail_*=False` 被跳过时，后续维度的权重映射错位。

例如: `_avail_mtf_1d=False` → `_available_dirs = [mom_dir, flow_dir]` → 被 zip 映射为 `["trend", "momentum"]` → `flow_dir` 错误使用 `momentum` 权重。

**修复**: 使用 `(direction, dim_name)` 元组数组替代并行数组:

```python
# Regime-dependent weights for net calculation
if _regime_transition != "NONE":
    weights = {"trend": 1.0, "momentum": 1.0, "order_flow": 2.0}
elif trend_dir != "NEUTRAL" and trend_score >= 5:
    weights = {"trend": 1.5, "momentum": 1.0, "order_flow": 1.0}
else:
    weights = {"trend": 1.0, "momentum": 1.0, "order_flow": 1.0}

# Build (direction, dimension_name) tuples — no zip mapping possible
_dir_pairs = []
if _avail_mtf_1d:
    _dir_pairs.append((trend_dir, "trend"))
if _avail_mtf_4h:
    _dir_pairs.append((mom_dir, "momentum"))
if _avail_order_flow:
    _dir_pairs.append((flow_dir, "order_flow"))

weighted_scores = []
weight_list = []
for d, dim_name in _dir_pairs:
    w = weights.get(dim_name, 1.0)
    if d == "BULLISH": weighted_scores.append(1 * w)
    elif d == "BEARISH": weighted_scores.append(-1 * w)
    else: weighted_scores.append(0 * w)
    weight_list.append(w)

if len(weighted_scores) < 2:
    net_label = "INSUFFICIENT"
elif any(s != 0 for s in weighted_scores):
    net_raw = sum(weighted_scores) / sum(weight_list)
    # ... rest of net_label logic
```

**net_label 新增 TRANSITIONING**:
```python
if _regime_transition != "NONE":
    net_label = _regime_transition  # e.g., "TRANSITIONING_BULLISH"
    aligned = ...  # count aligned
    net_label += f"_{aligned}of{len(weighted_scores)}"
elif net_raw > 0.3:
    net_label = "LEAN_BULLISH"
    ...
```

**返回值新增**:
```python
return {
    ...
    "net": net_label,
    "regime_transition": _regime_transition,  # 新增字段
    ...
}
```

---

## Phase 4: Judge Prompt 去锚定化

**文件**: `agents/multi_agent_analyzer.py`

### 4a: Bull/Bear Round 1 — 移除 net 标签

**位置**: `_build_structured_bull_system()` L4597-4603 和 `_build_structured_bear_system()` L4652-4654

将:
```
START by reading `_scores` for the pre-computed market synthesis — it shows trend alignment,
momentum quality, order flow, vol/extension risk, and net assessment. Use this as your
analytical anchor, then validate against raw features.
```
改为:
```
START by reading `_scores` for dimensional market data — trend alignment,
momentum quality, order flow direction, vol/extension risk. Analyze each dimension
independently, then form your own directional assessment from raw features.
NOTE: `_scores.net` shows pre-computed consensus but may lag in transitioning markets.
Form your own view FIRST, then check against net.
```

### 4b: Judge Prompt — 移除 net 锚定

**位置**: `_build_structured_judge_system()` L4689-4691

将:
```
START by reading `_scores.net` for the pre-computed net assessment, then evaluate Bull vs Bear
evidence against raw features. Use `_scores` dimensions to anchor your confluence analysis.
```
改为:
```
START by independently evaluating each `_scores` dimension (trend, momentum, order_flow)
and the Bull vs Bear evidence. Form your own confluence assessment from raw features.
`_scores.net` is a simple average that may miss regime transitions — your judgment supersedes it.
If `_scores.regime_transition` is active, pay special attention to leading indicator (order_flow)
direction, which may be ahead of lagging trend indicators.
```

### 4c: Judge Alignment 规则弹性化

**位置 1**: Judge 用户 prompt L2050-2053

将:
```
对齐度规则 (基于 aligned_layers 计数):
- 3-4 层一致 → HIGH confidence 交易
- 2 层一致 → MEDIUM confidence 交易
- 0-1 层一致 → 应该 HOLD
```
改为:
```
对齐度规则 (基于 aligned_layers 计数):
- 3-4 层一致 → HIGH confidence 交易
- 2 层一致 → MEDIUM confidence 交易
- 0-1 层一致 → 通常 HOLD，但如果 regime_transition 激活且领先指标 (order_flow)
  方向明确，可以 LOW confidence 交易 (小仓位探索性入场)
```

**位置 2 (⚠️ P0 Fix)**: Judge 用户 prompt L2069

将:
```
- confidence 必须与 aligned_layers 一致 (受执行层降级约束)
```
改为:
```
- confidence 通常与 aligned_layers 一致，但 TRANSITIONING regime 中允许 LOW confidence
  override (受执行层降级约束)
```

**理由**: L2069 原文 "必须一致" 与 L2050-2053 新增的 TRANSITIONING 例外矛盾，AI 可能优先服从 "必须" 而忽略例外。

---

## Phase 5: Alignment 代码强制降级弹性化

### ⚠️ P0: 三处 alignment enforcement 必须全部同步修改

alignment enforcement 存在于 **3 个位置**:

| # | 位置 | 方法 | 路径 | `dim_scores` 可用? |
|---|------|------|------|-------------------|
| 1 | L2217 | `_get_judge_decision()` | 已废弃 text fallback (dead code) | ❌ 不可用 |
| 2 | L4047 | `_run_structured_judge()` | **生产路径** (structured debate) | ✅ L3998 |
| 3 | L4449 | `analyze_from_features()` | **生产路径** (replay/feature-based) | ✅ L4290 |

### 5a: 提取共享方法 (消除三处重复)

```python
def _enforce_alignment_cap(
    self,
    decision: Dict,
    confluence: Dict,
    dim_scores: Optional[Dict] = None,
) -> bool:
    """v40.0: Regime-aware alignment enforcement.
    Returns True if confidence was capped.
    """
    _al = confluence.get("aligned_layers", 0) if isinstance(confluence, dict) else 0
    _conf = decision.get("confidence", "LOW")
    _dec = decision.get("decision", "HOLD")
    _conf_capped = False

    if _dec in ("LONG", "SHORT"):
        _regime_trans = dim_scores.get("regime_transition", "NONE") if dim_scores else "NONE"

        if _al <= 1 and _conf != "LOW":
            if _regime_trans != "NONE":
                # TRANSITIONING: allow the trade at LOW confidence
                decision["confidence"] = "LOW"
                decision["_aligned_layers_cap"] = f"{_conf}→LOW (aligned={_al}, regime={_regime_trans})"
                self.logger.info(
                    f"ℹ️ v40.0: aligned_layers={_al} but regime={_regime_trans} "
                    f"→ allowing LOW confidence {_dec}"
                )
            else:
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
    return _conf_capped
```

### 5b: 三处调用替换

**L2217** (`_get_judge_decision`, dead code — 仍更新保持一致性):
```python
# dim_scores not available in text path → pass None (TRANSITIONING never activates)
_conf_capped = self._enforce_alignment_cap(decision, confluence, dim_scores=None)
```

**L4047** (`_run_structured_judge`, 生产路径):
```python
_conf_capped = self._enforce_alignment_cap(result, result.get("confluence", {}), dim_scores=dim_scores)
```

**L4449** (`analyze_from_features`, 生产路径):
```python
_conf_capped = self._enforce_alignment_cap(judge_decision, judge_decision.get("confluence", {}), dim_scores=dim_scores)
```

### 5c: TRANSITIONING 时的 aligned_layers 机械上限

**问题**: TRANSITIONING 放行 LOW confidence 后，如果 order_flow 的领先信号实际是噪音（如 CVD spike），系统没有额外保护。

**新增**: TRANSITIONING 路径中 `aligned_layers` 必须 ≥ 1 (至少 momentum 也同向):

```python
if _regime_trans != "NONE":
    if _al >= 1:  # At least momentum also agrees with leading indicator
        decision["confidence"] = "LOW"
        # ... allow trade
    else:  # _al == 0: pure order_flow solo signal — too risky
        decision["confidence"] = "LOW"
        decision["decision"] = "HOLD"
        decision["_aligned_layers_cap"] = f"HOLD (regime={_regime_trans} but aligned=0, no confirmation)"
```

---

## Phase 6: Auditor 正则兼容 TRANSITIONING 标签

### ⚠️ P0: `_NET_DIRECTION_RE` 不匹配新标签

**文件**: `agents/ai_quality_auditor.py` L2915

**问题**: 当前正则 `r'LEAN_(BULLISH|BEARISH)_(\d+)of(\d+)'` 只匹配 `LEAN_BULLISH_2of3` 格式。Phase 3 新增的 `TRANSITIONING_BULLISH_2of3` 不匹配，导致 `SIGNAL_SCORE_DIVERGENCE` 检查静默失效。

**修复**:
```python
# v40.0: Support both LEAN_ and TRANSITIONING_ net labels
_NET_DIRECTION_RE = re.compile(r'(?:LEAN|TRANSITIONING)_(BULLISH|BEARISH)_(\d+)of(\d+)')
```

**验证**: `_check_signal_score_divergence()` 需测试以下 `net` 值:
- `LEAN_BULLISH_2of3` (原有 — 继续工作)
- `TRANSITIONING_BULLISH_2of3` (新增 — 必须匹配)
- `TRANSITIONING_BEARISH_1of3` (新增 — 必须匹配)
- `INSUFFICIENT` (原有 — 继续 skip)
- `CONFLICTING_0of3` (原有 — 继续 skip)

---

## Phase 7: TP 参数优化 (V40c)

**文件**: 3 处 SSoT 同步修改

### 7a: `configs/base.yaml` L58-61
```yaml
tp_rr_target:
  HIGH: 1.5          # v40.0: was 2.0 (V40c 回测最优: 回撤 3.08%, TP 命中 21 次)
  MEDIUM: 1.3        # v40.0: was 1.8
  LOW: 1.3           # v40.0: was 1.8
```

### 7b: `strategy/trading_logic.py` L84
```python
'tp_rr_target': {'HIGH': 1.5, 'MEDIUM': 1.3, 'LOW': 1.3},
```

### 7c: `utils/backtest_math.py` L24
```python
"tp_rr_target": {"HIGH": 1.5, "MEDIUM": 1.3, "LOW": 1.3},
```

### 7d: TP 参数胜率验证 (⚠️ P1)

**问题**: TP 收紧提高了 breakeven win rate (HIGH: 33.3%→40%, MED: 35.7%→43.5%)。V40c 回测报告需要显式验证 per-confidence 胜率达标。

**验证方法**: 实施后运行 `backtest_from_logs.py`，检查:
- HIGH confidence 胜率 ≥ 40% (breakeven at R/R=1.5)
- MEDIUM confidence 胜率 ≥ 43.5% (breakeven at R/R=1.3)
- LOW confidence 胜率 ≥ 43.5% (breakeven at R/R=1.3)

如果任一级别胜率不达标，保留该级别原 TP 参数不变。

---

## Phase 8: 验证与回归

### 8a: 运行现有验证工具
```bash
python3 scripts/smart_commit_analyzer.py
python3 scripts/check_logic_sync.py
```

### 8b: 运行诊断
```bash
python3 scripts/diagnose_feature_pipeline.py      # Feature extraction 验证
python3 scripts/diagnose_quality_scoring.py        # 评分系统验证
```

### 8c: 单元测试
```bash
python3 -m pytest tests/ -x -v
```

### 8d: TRANSITIONING 专项测试 (⚠️ P1)

新增测试用例验证 TRANSITIONING 行为:

```python
# test_transitioning_regime.py
def test_transitioning_detection():
    """trend=BEARISH + flow=BULLISH → TRANSITIONING_BULLISH"""
def test_transitioning_hysteresis():
    """Single-cycle transition signal → should NOT activate"""
def test_transitioning_order_flow_unavailable():
    """_avail_order_flow=False → fallback to momentum-based detection"""
def test_transitioning_alignment_cap():
    """TRANSITIONING + aligned=0 → forced HOLD"""
def test_net_label_format():
    """TRANSITIONING_BULLISH_2of3 format correctness"""
def test_auditor_regex_transitioning():
    """_NET_DIRECTION_RE matches TRANSITIONING labels"""
def test_zip_mapping_with_missing_dims():
    """_avail_mtf_1d=False → weight mapping still correct"""
```

### 8e: Before/After 回测对比 (⚠️ P1)

在 v40.0 实施前后各运行一次 `backtest_from_logs.py`，对比:
- SHORT 信号比例 (目标: < 80%)
- HOLD 比例 (目标: < 55%)
- 新增 TRANSITIONING 信号数量
- 整体 PnL / win rate / max drawdown

---

## Phase 9: CLAUDE.md 更新 (⚠️ P1)

新增 v40.0 条目到 CLAUDE.md 核心架构决策表:

```
| v40.0 | Hierarchical Signal Architecture | (1) 删除 3 个重复 4H 投票 (trend_signals 14→11);
  (2) TRANSITIONING regime 检测 (leading vs lagging indicator divergence, 2-cycle hysteresis);
  (3) Regime-dependent weighted net (TRANSITIONING: order_flow 2x; ESTABLISHED: trend 1.5x);
  (4) Judge/Bull/Bear prompt 去锚定化 (_scores.net 不再作为 analytical anchor);
  (5) Alignment enforcement 弹性化 (TRANSITIONING + aligned≥1 → LOW confidence trade);
  (6) Auditor regex 兼容 TRANSITIONING labels;
  (7) TP 参数优化 (HIGH 2.0→1.5, MED/LOW 1.8→1.3) |
```

新增常见错误避免:
```
- ❌ `_available_dirs` 和 weight keys 用 zip 并行映射 → ✅ 使用 `(direction, dim_name)` 元组数组 (v40.0)
- ❌ TRANSITIONING regime 在单个周期就触发交易 → ✅ 2-cycle hysteresis 防抖 (v40.0)
- ❌ Alignment enforcement 只更新 1 处 → ✅ 3 处同步 (L2217/L4047/L4449)，提取为 `_enforce_alignment_cap()` (v40.0)
```

---

## Phase 10: Entry Timing Agent 与 TRANSITIONING 交互 (P2, 观察后决定)

**当前状态**: Entry Timing Agent (Phase 2.5) 在 Judge→LONG/SHORT 后评估入场时机。v40.0 TRANSITIONING 信号通过 LOW confidence 到达 ET。

**潜在问题**: ET 的 ADX>40 逆势 REJECT 规则可能在 TRANSITIONING 场景中误拦。例如:
- 1D ADX=45 DI->DI+ (强下跌) + order_flow BULLISH → TRANSITIONING_BULLISH → Judge LONG
- ET 看到 ADX=45 逆势 → REJECT

**当前决定**: 不修改 ET。理由:
1. TRANSITIONING + aligned≤1 已被 Phase 5c 限制为 HOLD
2. TRANSITIONING + aligned≥2 意味着 momentum 也同向，ET 应该不会 REJECT
3. 需要实际运行数据验证 ET 在 TRANSITIONING 中的行为

**后续观察**: 如果 ET REJECT 率 > 50% 的 TRANSITIONING 信号，考虑在 ET prompt 中添加 regime_transition 感知。

---

## 修改文件清单

| # | 文件 | 修改类型 | Phase |
|---|------|---------|-------|
| 1 | `agents/report_formatter.py` | 删除重复投票 + 指标分类加权 + regime transition + hysteresis + fallback + 加权 net (zip fix) | 1,1b,2,3 |
| 2 | `agents/multi_agent_analyzer.py` | Judge prompt 去锚定 + `_enforce_alignment_cap()` 提取 + 3 处调用替换 | 4,5 |
| 3 | `agents/ai_quality_auditor.py` | `_NET_DIRECTION_RE` 正则兼容 TRANSITIONING | 6 |
| 4 | `configs/base.yaml` | TP 参数 V40c | 7 |
| 5 | `strategy/trading_logic.py` | TP 参数同步 | 7 |
| 6 | `utils/backtest_math.py` | TP 参数同步 | 7 |
| 7 | `tests/test_transitioning_regime.py` | TRANSITIONING 专项测试 (新增) | 8d |
| 8 | `CLAUDE.md` | v40.0 条目 | 9 |

## 不修改的部分 (本次不动)

- REASON_TAGS 对称性: 实际 Bullish 27 vs Bearish 26，差异仅 1 个 (TREND_ALIGNED)，不是显著问题
- Entry Timing Agent: 观察 v40.0 效果后再决定 (Phase 10 记录了交互设计)
- Risk Manager: 不改
- 回测脚本: 不改

## 风险评估

| 风险 | 可能性 | 缓解 |
|------|--------|------|
| 指标加权后评分偏移导致信号比例变化 | 中 | 用 feature_snapshots 做 before/after 对比，权重保守 (1.5x max) |
| 背离移出 momentum 后 mom_score 变化 | 低 | 背离作为 trend_score 修正因子，momentum 维度逻辑更纯粹 |
| Regime-aware 权重调整在 ADX 边界不稳定 | 低 | 采用连续倍率而非阶梯函数，避免 ADX=19.9→20.1 跳变 |
| TRANSITIONING 误判导致错误交易 | 中 | LOW confidence = 30% 小仓位 + aligned≥1 确认 + 2-cycle hysteresis |
| TRANSITIONING whipsaw (频繁进出) | 中 | 2-cycle hysteresis + aligned≥1 门槛 |
| order_flow 不可用时 TRANSITIONING 失效 | 中 | momentum fallback (Phase 2c) |
| TP 收紧后胜率不达标 | 低 | Phase 7d 验证，不达标则保留原参数 |
| 去锚定化后 AI 辩论质量下降 | 低 | 维度评分仍然提供，只是不预聚合 |
| Judge 在 TRANSITIONING 中过于激进 | 低 | aligned_layers ≥1 限制 + LOW confidence |
| zip 映射错位 (原 P0 bug) | 已消除 | 使用 `(direction, dim_name)` 元组替代并行数组 |
| Auditor 静默失效 (原 P0 bug) | 已消除 | `_NET_DIRECTION_RE` 正则已扩展 |
| alignment enforcement 遗漏 (原 P0 bug) | 已消除 | 提取共享方法，3 处统一调用 |
| Layer B × Layer C 双重放大 (2.6:1 极端权重比) | 已消除 | 删除 Layer B regime 倍率，只保留 Layer A (信息密度) + Layer C (维度间 regime 权重) |
| 背离双重扣分 (divergence_adjustment + reversal -3) | 已消除 | 互斥应用: `if not reversal_active` 才扣分 |

## 回滚策略

所有修改集中在 8 个文件，可以 `git revert <commit>` 原子回滚。
TP 参数 (Phase 7) 与评分逻辑 (Phase 1-6) 独立，可以分别回滚。

## P0/P1/P2 修复项追踪

### P0 (必须在实施前修复, 否则产生 bug)

| # | 问题 | 修复位置 | 状态 |
|---|------|---------|------|
| P0-1 | `_available_dirs`/weights zip 映射错位 | Phase 3 — 改用 `(direction, dim_name)` 元组 | ✅ 已纳入 |
| P0-2 | Auditor `_NET_DIRECTION_RE` 不匹配 TRANSITIONING | Phase 6 — 正则扩展 | ✅ 已纳入 |
| P0-3 | alignment enforcement 仅覆盖 1/3 位置 | Phase 5 — 提取 `_enforce_alignment_cap()` + 3 处替换 | ✅ 已纳入 |
| P0-4 | Judge prompt L2069 与 TRANSITIONING 例外矛盾 | Phase 4c — 更新措辞 | ✅ 已纳入 |
| P0-5 | `dim_scores` 在 `_get_judge_decision` 不可用 | Phase 5b — 传入 `None` (dead code path, TRANSITIONING 不激活) | ✅ 已纳入 |
| P0-6 | 背离 `divergence_adjustment` 与 v39.0 `reversal_active` 双重扣分 (-2 + -3 = -5) | Phase 1b — 互斥应用 (`if not reversal_active`) | ✅ 已纳入 |

### P1 (实施后应尽快完成)

| # | 问题 | 修复位置 | 状态 |
|---|------|---------|------|
| P1-1 | TRANSITIONING hysteresis (防 whipsaw) | Phase 2b | ✅ 已纳入 |
| P1-2 | TRANSITIONING 专项测试 | Phase 8d | ✅ 已纳入 |
| P1-3 | Before/After 回测对比 | Phase 8e | ✅ 已纳入 |
| P1-4 | CLAUDE.md v40.0 条目 | Phase 9 | ✅ 已纳入 |
| P1-5 | TP 参数 per-confidence 胜率验证 | Phase 7d | ✅ 已纳入 |

### P2 (观察后决定)

| # | 问题 | 修复位置 | 状态 |
|---|------|---------|------|
| P2-1 | order_flow 不可用时 TRANSITIONING fallback | Phase 2c — momentum fallback | ✅ 已纳入 |
| P2-2 | TRANSITIONING + aligned=0 机械上限 | Phase 5c — 强制 HOLD | ✅ 已纳入 |
| P2-3 | ET 与 TRANSITIONING 交互 | Phase 10 — 观察后决定 | ✅ 已记录 |

---

## 独立评审发现: Critical Blockers (v2.0)

> 以下由独立量化评审发现，必须在实施前解决。

### CB-1: TP R/R Target 与 min_rr_ratio 交互 (⚠️ 部分影响)

**问题**: Phase 7 将 MEDIUM/LOW TP 从 1.8 降到 1.3。

**实际行为** (经代码验证 `trading_logic.py` L336-348):
- **顺势交易**: `effective_rr = rr_target = 1.3` → **Phase 7 参数生效**，R/R=1.3:1
- **逆势交易**: `effective_rr = max(1.3, 1.5 × 1.3) = 1.95` → **min_rr_ratio × ct_mult 覆盖**，Phase 7 参数被忽略

**影响**: Phase 7 对顺势交易有效，但逆势交易的 TP 始终被拉到 1.95:1。这意味着 Phase 7d 的 breakeven 胜率验证 (43.5%) 只对顺势交易有意义。

**建议**: 在 Phase 7d 验证中区分顺势/逆势胜率。PLAN.md 风险表中补充此交互。

### CB-2: 最大有效权重比 8:1 (PLAN 声称 1.4:1 不完整)

**问题**: PLAN L190 声称 Layer B 删除后最大比值 1.4:1，但这只考虑了 Layer A 内部。

**跨层计算** (TRANSITIONING regime + Layer C):
```
CVD-Price cross: 2.0 (Layer A) × 2.0 (Layer C order_flow dim weight) = 4.0 effective
buy_ratio in trend: 0.5 (Layer A) × 1.0 (Layer C default) = 0.5 effective
比值: 8:1
```

**ADX<20 regime + Layer C**:
```
CVD-Price cross: 2.0 × 1.5 (order_flow weight) = 3.0
buy_ratio: 0.5 × 0.7 (trend weight) = 0.35
比值: 8.6:1
```

**风险**: 单个 CVD spike/stale 数据可翻转 net 评分。

**建议**: (1) PLAN 中显式承认跨层最大权重比 8:1 → 8.6:1; (2) 考虑对跨层有效权重设上限 (如 max 6:1); (3) 或降低 CVD-Price base weight 到 1.5 (上限 4.3:1)。

### CB-3: `_prev_regime_transition` 状态持久化未指定

**问题** (经代码验证): `_prev_regime_transition` 在整个代码库中**零出现**。PLAN.md Phase 2b 设计了 hysteresis 但未指定:

1. **谁存储**: `ai_strategy.py` 需新增 `self._prev_regime_transition: str = "NONE"`
2. **如何传递**: `extract_features()` 中将上次 `dim_scores["regime_transition"]` 注入 `feature_dict["_prev_regime_transition"]`
3. **重启行为**: 首次启动丢失上次状态 → 第一个 TRANSITIONING 周期被 hysteresis 吃掉 (可接受)
4. **on_timer() 后处理**: `self._prev_regime_transition = ctx.scores.get("regime_transition", "NONE")`

**建议**: 在 Phase 2b 中补充上述 4 点实施细节。

### CB-4: Phase 4 去锚定化无法被现有测试方法验证

**问题**: Phase 8 的所有验证方法 (feature_snapshots replay, backtest_from_logs, 单元测试) 都**不重新调用 AI agents**。Phase 4 修改 AI prompt 文本，其效果只有在 AI 实际运行时才能体现。

**验证盲区**:
- `backtest_from_logs.py` → 回放历史信号 → Phase 4 效果不可见
- `replay_ab_compare.py` → 对比评分 → Phase 4 不影响评分
- 单元测试 → TRANSITIONING 机械逻辑 → Phase 4 改 prompt 文本，不相关

**建议**: (1) 在 Phase 8 新增 "Phase 4 验证: 使用 N 个 feature_snapshots 重新调用 AI agents (new prompt vs old prompt)，对比 signal distribution。至少 20 样本"; (2) 或承认 Phase 4 需生产数据积累后量化评估，设 30-cycle 观察窗口。

### CB-5: ADX 边界不连续与 PLAN 声称矛盾

**问题**: PLAN L720 声称 "采用连续倍率而非阶梯函数，避免 ADX=19.9→20.1 跳变"。

**实际代码** (经验证 `report_formatter.py`): 当前系统 ADX 全部使用离散阈值:
- `market_regime`: if >= 40 → STRONG, elif >= 25 → WEAK, else → RANGING
- `_format_technical_report()`: ADX >= 40 / < 20 / < 25 / < 40 离散分级
- `compute_scores_from_features()`: 完全不使用 ADX 作为权重乘数

**PLAN Phase 1b/3 新增的 Layer C 权重**:
```python
if adx_effective < 20:     weights = {"trend": 0.7, "order_flow": 1.5}
elif adx_effective >= 40:  weights = {"trend": 1.5, "order_flow": 0.8}
```
ADX 39.9→40.1: trend 权重 1.0→1.5 (+50%), order_flow 1.0→0.8 (-20%)

**建议**: (1) 删除 PLAN L720 "连续倍率" 声称; (2) 改为 "阶梯权重，ADX 20/40 边界跳变通过 2-cycle hysteresis 缓解"; (3) 或实现线性插值 `trend_w = 1.0 + 0.5 * (adx - 20) / 20` (ADX 20-40 区间平滑过渡)。
