# PLAN: 统一指标分类体系 (Unified Indicator Classification) — v3 (评审二次修复版)

## 背景

当前系统对同一批指标使用**两套独立的分类体系**，且两套体系之间存在概念冲突：

### 现状：两套分类并行

系统中实际存在两处独立的指标分类：

1. **`_SIGNAL_ANNOTATIONS` dict** (L801-L835): 使用 **4 种** nature 标签 (`Lagging` × 9, `Sync` × 10, `Sync-lag` × 6, `Quality` × 2)，通过 `_get_multiplier()` 输出到技术报告中
2. **`SIGNAL_CONFIDENCE_MATRIX` 文本表** (L307+): 使用 **~16 种** nature 描述 (Leading / Lagging / Sync / Sync-lag / Realtime / Static / Event / Quality / Risk / Context / Confirm / Temporal / Sentiment / Warning / Sync-leading)，作为 AI 参考手册

| | `_SIGNAL_ANNOTATIONS` (代码) | `SIGNAL_CONFIDENCE_MATRIX` (文本) | `compute_scores_from_features()` |
|---|---|---|---|
| **标签类型** | 4 种时序标签 | ~16 种时序/杂项标签 | 5 个功能维度 |
| **消费方式** | → `_get_multiplier()` → 报告行 `"— Lagging, 1.3x"` | AI 直接阅读的参考表 | `_scores` 预计算评分，prompt 首位 |
| **权重机制** | 3 regime multiplier → tier 分组 | Nature 列 + multiplier 列 | 指标级 weight + 维度级 regime weight |

### 问题

1. **AI 认知冲突**：同一个指标（如 RSI），报告中标 "Sync"，评分中归入 "momentum"。AI 同时读到两套不同分类
2. **"Lagging" 暗示低价值**：AI 训练语料中 "lagging" 通常带负面含义（滞后=不好），但在强趋势中 Lagging 指标恰恰最可靠。multiplier=1.3 说"高可靠"，nature="Lagging" 暗示"不好"——互相矛盾
3. **两处标签系统不一致**：`_SIGNAL_ANNOTATIONS` 只有 4 种标签，但 `SIGNAL_CONFIDENCE_MATRIX` 使用 ~16 种，两者之间存在语义重叠（Leading vs Realtime、Sync vs Sync-lag vs Sync-leading、Risk vs Context vs Quality）
4. **与功能维度体系脱节**：`compute_scores_from_features()` 已使用功能性 5 维分类（trend/momentum/order_flow/vol_ext_risk/risk_env），v40.0 的 regime-dependent weighting 完全基于维度名。时序标签（Lagging/Sync）无法传达指标的**功能角色**，而功能角色才是 AI 决策需要的信息
5. **`INDICATOR_KNOWLEDGE_BRIEF` 第 7 条**教 AI 用 Leading/Lagging 思考（~500 tokens），可能引入偏见

## 方案

### 核心变更：统一到功能性分类

将 `_SIGNAL_ANNOTATIONS` 的 4 种时序标签和 `SIGNAL_CONFIDENCE_MATRIX` 的 ~16 种时序/杂项描述**统一**为 **7 种功能性标签**，以 `_scores` 5 维为基础，增加 2 个语义独立类别：

| 新标签 | 对应 `_scores` 维度 | 语义 | 覆盖指标 |
|--------|---------------------|------|----------|
| **Trend** | `trend` | 趋势方向确认，确定性最高但最慢 | SMA200, ADX/DI direction, MACD cross, SMA/EMA cross, HH/HL patterns |
| **Momentum** | `momentum` | 动量强弱变化，速度信号 | RSI, MACD histogram, BB position, Volume ratio, OBV, divergences, K-line 反转形态 |
| **Order Flow** | `order_flow` | 订单流微观结构，信息密度最高 | CVD, OBI, Taker ratio, Buy ratio, Avg Trade Size |
| **Volatility** | `vol_ext_risk` | 波动率/延伸风险，非方向信号 | ATR, Extension Ratio, Volatility Regime, BB Width |
| **Risk** | `risk_env` | 风险环境评估（衍生品+情绪+流动性） | FR, OI, Liquidation, Sentiment, Top Traders, Premium Index, Spread/Slippage |
| **Structure** | (无直接维度) | 价格结构信号（支撑/阻力） | S/R zone test, S/R breakout, Price vs period H/L |
| **Context** | (无直接维度) | 背景环境信息，非方向非风险 | 24h Volume level, 24h Price Change % |

**为什么 7 个而非 5 个**：评审发现强制对齐 5 维会产生语义扭曲（S/R zones ≠ Risk，24h Volume ≠ Momentum）。增加 Structure 和 Context 两个类别，保留关键语义区分。`_SIGNAL_ANNOTATIONS` 从 4 种→7 种（+3），`SIGNAL_CONFIDENCE_MATRIX` 从 ~16 种→7 种（-9），实现两处统一。

### 不变的部分

以下内容**保持不变**：

1. **`_SIGNAL_ANNOTATIONS` 的 regime multiplier 值** (`{'strong': 1.3, 'weak': 1.0, 'ranging': 0.4}`) — 这些是经过多版本验证的
2. **`compute_scores_from_features()` 的所有权重值** — 指标级 `(signal, weight)` 和维度级 regime weights 不变
3. **Tier 分组逻辑** (`high/std/low/skip`) — 由 multiplier 值驱动，不受 nature 标签影响
4. **`SIGNAL_CONFIDENCE_MATRIX` 的 multiplier 数值** — 只改最后一列的 nature 标签文字
5. **`_get_multiplier()` 返回值签名** — 仍返回 `(nature, multiplier, tier)` 三元组，nature 从 16 种变为 7 种。当前 tests/ 中无 assert 旧标签的代码（已 grep 确认）

## 详细变更

### 1. `_SIGNAL_ANNOTATIONS` nature 标签映射

```python
# 文件: agents/prompt_constants.py (L801-L835)
# 只改第一个元组元素（nature 标签），multiplier dict 完全不变

_SIGNAL_ANNOTATIONS = {
    # Layer 1 — TREND (1D)
    '1d_sma200':  ('Trend',       {'strong': 1.3, 'weak': 1.0, 'ranging': 0.4}),  # was 'Lagging'
    '1d_adx_di':  ('Trend',       {'strong': 1.2, 'weak': 1.0, 'ranging': 0.3}),  # was 'Lagging'
    '1d_macd':    ('Trend',       {'strong': 1.1, 'weak': 1.0, 'ranging': 0.3}),  # was 'Lagging'
    '1d_macd_h':  ('Momentum',    {'strong': 1.0, 'weak': 1.0, 'ranging': 0.3}),  # was 'Sync-lag'
    '1d_rsi':     ('Momentum',    {'strong': 0.9, 'weak': 1.0, 'ranging': 0.7}),  # was 'Sync'
    # Layer 2 — MOMENTUM (4H)
    '4h_rsi':     ('Momentum',    {'strong': 0.8, 'weak': 1.0, 'ranging': 1.2}),  # was 'Sync'
    '4h_macd':    ('Trend',       {'strong': 1.2, 'weak': 1.0, 'ranging': 0.3}),  # was 'Lagging'
    '4h_macd_h':  ('Momentum',    {'strong': 1.0, 'weak': 1.0, 'ranging': 0.5}),  # was 'Sync-lag'
    '4h_adx_di':  ('Trend',       {'strong': 1.1, 'weak': 1.0, 'ranging': 0.4}),  # was 'Lagging'
    '4h_bb':      ('Momentum',    {'strong': 0.6, 'weak': 0.9, 'ranging': 1.2}),  # was 'Sync' — BB position = 均值回归信号 (similar to RSI overbought/oversold)
    '4h_sma':     ('Trend',       {'strong': 1.1, 'weak': 1.0, 'ranging': 0.4}),  # was 'Lagging'
    # ATR/BB
    '1d_bb':      ('Momentum',    {'strong': 0.6, 'weak': 0.9, 'ranging': 1.2}),  # was 'Sync' — BB position
    '1d_atr':     ('Volatility',  {'strong': 1.0, 'weak': 1.0, 'ranging': 1.0}),  # was 'Quality'
    '4h_atr':     ('Volatility',  {'strong': 1.0, 'weak': 1.0, 'ranging': 1.0}),  # was 'Quality'
    '4h_vol_ratio': ('Momentum',  {'strong': 0.9, 'weak': 1.0, 'ranging': 1.1}),  # was 'Sync'
    # Layer 3 — KEY LEVELS (30M)
    '30m_rsi':    ('Momentum',    {'strong': 0.8, 'weak': 1.0, 'ranging': 1.2}),  # was 'Sync'
    '30m_macd':   ('Momentum',    {'strong': 1.0, 'weak': 1.0, 'ranging': 0.5}),  # was 'Sync-lag'
    '30m_macd_h': ('Momentum',    {'strong': 0.9, 'weak': 1.0, 'ranging': 0.5}),  # was 'Sync-lag'
    '30m_adx':    ('Trend',       {'strong': 1.1, 'weak': 1.0, 'ranging': 0.4}),  # was 'Lagging'
    '30m_bb':     ('Momentum',    {'strong': 0.6, 'weak': 0.9, 'ranging': 1.2}),  # was 'Sync' — BB position
    '30m_sma':    ('Trend',       {'strong': 0.9, 'weak': 1.0, 'ranging': 0.6}),  # was 'Lagging'
    '30m_volume': ('Momentum',    {'strong': 0.9, 'weak': 1.0, 'ranging': 1.1}),  # was 'Sync'
    # OBV
    '30m_obv':    ('Momentum',    {'strong': 0.7, 'weak': 0.9, 'ranging': 1.0}),  # was 'Sync-lag'
    '4h_obv':     ('Momentum',    {'strong': 0.8, 'weak': 1.0, 'ranging': 1.0}),  # was 'Sync-lag'
    '1d_obv':     ('Momentum',    {'strong': 0.9, 'weak': 1.0, 'ranging': 0.8}),  # was 'Lagging'
    # Volume ratio
    '1d_volume':  ('Momentum',    {'strong': 0.9, 'weak': 1.0, 'ranging': 1.0}),  # was 'Sync'
    '4h_volume':  ('Momentum',    {'strong': 0.9, 'weak': 1.0, 'ranging': 1.1}),  # was 'Sync'
}
```

**BB position 归类说明**：BB position（价格在布林带中的位置）是均值回归信号——触上轨=超买（类 RSI 超买）、触下轨=超卖。其 regime multiplier (`strong: 0.6, ranging: 1.2`) 也与 Momentum 类指标一致（ranging 市场最可靠），与 ATR 类 Volatility 指标 (`1.0/1.0/1.0`) 不一致。BB **Width** 才是 Volatility 信号。

### 2. `SIGNAL_CONFIDENCE_MATRIX` Nature 列映射

```
# 文件: agents/prompt_constants.py (L307+, SIGNAL_CONFIDENCE_MATRIX 表格)
# 只改最后一列 Nature 文字，所有 multiplier 数值不变

LAYER 1 — TREND (1D):
  1D SMA200 direction        | Lagging  → Trend
  1D ADX/DI direction        | Lagging  → Trend
  1D MACD zero-line          | Lagging  → Trend
  1D MACD histogram          | Sync-lag → Momentum
  1D RSI level               | Sync     → Momentum

LAYER 2 — MOMENTUM (4H):
  4H RSI level               | Sync     → Momentum
  4H RSI divergence*         | Leading  → Momentum
  4H MACD cross              | Lagging  → Trend
  4H MACD histogram          | Sync-lag → Momentum
  4H ADX/DI direction        | Lagging  → Trend
  4H BB position             | Sync     → Momentum        ← 修正: 均值回归信号归 Momentum 非 Volatility
  4H SMA 20/50 cross         | Lagging  → Trend
  CVD single-bar delta       | Leading  → Order Flow
  CVD trend (cumul.)         | Sync-lag → Order Flow
  CVD divergence*            | Leading  → Order Flow
  CVD absorption**           | Leading  → Order Flow
  OI×CVD positioning         | Sync     → Order Flow
  Buy Ratio (taker %)        | Realtime → Order Flow
  Avg Trade Size chg         | Leading  → Order Flow

ATR Extension Ratio:
  Ext Ratio >3 (overextended)| Risk     → Volatility
  Ext Ratio >5 (extreme)     | Risk     → Volatility

ATR Volatility Regime:
  Vol LOW (<30th pctl)       | Context  → Volatility
  Vol HIGH (70-90th pctl)    | Risk     → Volatility
  Vol EXTREME (>90th pctl)   | Risk     → Volatility

OBV Divergence:
  4H OBV divergence          | Leading  → Momentum
  OBV+CVD confluence div     | Leading  → Momentum

LAYER 3 — KEY LEVELS (30M):
  S/R zone test (bnce)       | Static   → Structure       ← 修正: 价格结构信号非 Risk
  S/R zone breakout          | Event    → Structure       ← 修正: 突破事件属于价格结构
  30M BB position            | Sync     → Momentum        ← 修正: BB position 归 Momentum
  30M BB Width level         | Sync     → Volatility
  OBI (book imbalance)       | Realtime → Order Flow
  OBI change rate            | Leading  → Order Flow
  Bid/Ask depth change       | Leading  → Order Flow
  Pressure gradient          | Leading  → Order Flow
  Order walls (>3x)          | Realtime → Order Flow
  30M MACD cross             | Sync-lag → Momentum
  30M MACD histogram         | Sync-lag → Momentum
  30M SMA cross (5/20)       | Lagging  → Trend
  30M Volume ratio           | Sync     → Momentum
  Price vs period H/L        | Sync     → Structure       ← 修正: 价格结构信号
  Spread (liquidity)         | Quality  → Risk            ← 执行质量影响风险管理
  Slippage (execution)       | Quality  → Risk            ← 执行质量影响风险管理

LAYER 4 — DERIVATIVES:
  FR current value           | Sentiment→ Risk
  FR extreme (>±0.05%)       | Leading  → Risk
  FR predicted vs settled    | Leading  → Risk
  FR settlement history      | Sync     → Risk
  FR settlement countdown    | Temporal → Risk
  Premium Index              | Leading  → Risk
  OI↑+Price↑ (new longs)    | Confirm  → Risk
  OI↑+Price↓ (new shorts)   | Confirm  → Risk
  OI↓ (unwinding/liquidation)| Event    → Risk
  Top Traders L/S position   | Leading  → Risk
  Global L/S extreme         | Sentiment→ Risk
  Coinalyze L/S Ratio        | Sentiment→ Risk
  Taker Buy/Sell Ratio       | Realtime → Order Flow
  Liquidation (large event)  | Leading  → Risk
  24h Volume level           | Context  → Context         ← 修正: 背景环境信息非 Momentum
  24h Price Change %         | Context  → Context         ← 修正: 背景环境信息非 Momentum

SECTION B — TIME-SERIES PATTERNS:
  Higher/Lower highs/lows    | Confirm  → Trend
  Range-bound oscillation    | Confirm  → Structure       ← 修正: 价格结构模式
  Tightening range           | Leading  → Volatility
  Volume climax (spike)      | Event    → Momentum
  ADX series rising/falling  | Leading  → Trend
  BB Width narrowing/expanding| Leading/Confirm → Volatility
  SMA convergence/divergence | Leading/Confirm → Trend
  RSI trend (accel/decel)    | Sync     → Momentum
  MACD histogram momentum    | Sync-lag → Momentum
  Volume trend (expand/shrink)| Sync-leading/Warning → Momentum
  Engulfing candle           | Leading  → Momentum
  Doji at S/R                | Leading  → Momentum
  Long wicks (rejection)     | Leading  → Momentum
  Consecutive same-dir       | Confirm  → Trend
```

### 3. `INDICATOR_KNOWLEDGE_BRIEF` 第 7 条重写

```python
# 文件: agents/prompt_constants.py (L922-L933)

# 修改前 (v40.0):
"""
7. INDICATOR CLASSIFICATION & DYNAMIC WEIGHTING (v40.0):
   Indicators are classified by information type, each with different weights:
   - Leading (权重 1.5-2.0): CVD-Price cross, Taker ratio, OBI — earliest signals...
   - Lagging (权重 0.8-1.5): SMA200, ADX direction, DI spread, MACD cross — confirm...
   - Sync (权重 0.5-1.0): RSI, buy_ratio, BB position — real-time snapshots...
   - Sync-lag (权重 0.6-1.2): MACD histogram, CVD trend — between sync and lagging...
   REGIME-DEPENDENT PRIORITY (check _scores.regime_transition):
   - TRANSITIONING (领先≠滞后): order_flow dimension 2x weight — leading indicators...
   - ADX≥40 STRONG TREND: trend dimension 1.5x — lagging indicators most reliable.
   - ADX<20 RANGING: order_flow dimension 1.5x — micro-structure signals dominate.
   - WEAK TREND (20≤ADX<40): equal dimension weights — no single layer dominates.
   ⚠️ The old static "1D > 4H > 30M" hierarchy is WRONG in transitioning markets.
"""

# 修改后:
"""
7. INDICATOR DIMENSIONS & REGIME-DEPENDENT WEIGHTING (v41.0):
   Each indicator belongs to one functional dimension. Weights are REGIME-DEPENDENT:
   - Trend (趋势确认): SMA200, ADX/DI, MACD cross, SMA/EMA cross — highest certainty,
     confirms established direction. Most reliable when ADX≥40.
   - Momentum (动量): RSI, MACD histogram, BB position, OBV, Volume ratio, divergences —
     measures speed and acceleration. Divergences are reversal warnings (require 2+ confluence).
   - Order Flow (订单流): CVD-Price cross, CVD trend, OBI, Taker ratio — highest
     information density, earliest directional signal. Most reliable in TRANSITIONING.
   - Volatility (波动率): ATR, Extension Ratio, BB Width, Volatility Regime — risk
     sizing signal, NOT directional. Affects position size and stop width.
   - Risk (风险环境): FR, OI, Liquidation, Sentiment, Spread/Slippage — risk assessment,
     can veto trades but does NOT drive direction.
   - Structure (价格结构): S/R zones, Price vs H/L — reference levels for SL/TP placement.
   - Context (背景): 24h Volume/Price — environment awareness, neither directional nor risk.
   REGIME-DEPENDENT PRIORITY (check _scores.regime_transition):
   - TRANSITIONING (order_flow ≠ trend): order_flow 2x weight — new direction forming.
   - ADX≥40 STRONG TREND: trend 1.5x — confirmed direction is most reliable signal.
   - ADX<20 RANGING: order_flow 1.5x — micro-structure dominates, trend signals are noise.
   - WEAK TREND (20≤ADX<40): equal weights — no single dimension dominates.
   ⚠️ The old static "1D > 4H > 30M" hierarchy is WRONG in transitioning markets.
"""
```

### 4. `SIGNAL_CONFIDENCE_MATRIX` Notes 段落术语同步

```
# 文件: agents/prompt_constants.py
# Notes 和解释段落中引用旧标签的位置，需同步修改文字

L82:  "Critical leading signal."
  →   "Critical early signal." (去掉 leading/lagging 术语)

L85:  "⚠️ ADX is lagging — confirms late."
  →   "⚠️ ADX is a trend-confirming indicator — confirms direction after the fact."

L223: "⚠️ LAGGING data — shows what happened, not what will happen."
  →   "⚠️ This is trend-confirming data — shows established direction, not future prediction."

L383: "Avg Trade Size: Sudden increase = institutional activity (leading)."
  →   "Avg Trade Size: Sudden increase = institutional activity (order flow signal)."

L548: "ADX rising in ADX<20 (1.3) = CRITICAL leading signal."
  →   "ADX rising in ADX<20 (1.3) = CRITICAL early signal — regime shift imminent."

L929: "TRANSITIONING (领先≠滞后): order_flow dimension 2x weight — leading indicators drive decisions."
  →   (已在第 7 条重写中覆盖)

L930: "ADX≥40 STRONG TREND: trend dimension 1.5x — lagging indicators most reliable."
  →   (已在第 7 条重写中覆盖)
```

### 5. `compute_scores_from_features()` 代码注释

```python
# 文件: agents/report_formatter.py
# 只改注释文字，不改任何代码逻辑或数值

# 示例 (完整列表省略，按同样模式替换):
# L655: # 1D SMA200 — macro filter, highest certainty (Lagging)
#    →  # 1D SMA200 — macro filter, highest certainty (Trend)

# L884: # CVD trend 30M (Sync-lag)
#    →  # CVD trend 30M (Order Flow)

# L905: # CVD-Price cross — highest information density (Leading)
#    →  # CVD-Price cross — highest information density (Order Flow)

# L1143-L1200: Regime transition 注释
# "When leading indicators (order_flow) oppose lagging indicators (trend)"
# →  "When order_flow dimension opposes trend dimension"
```

### 6. `experiment_reliability_format.py` 处置

该脚本 (`scripts/experiment_reliability_format.py`) 中硬编码了 "Lagging"/"Sync-lag" 样本输出。按 CLAUDE.md 奥卡姆剃刀原则，该实验脚本已完成历史使命（v18.1 Tier 格式已定型），应**删除**。如需保留，则同步更新其样本输出中的标签文字。

### 7. AI 报告输出效果对比

```
修改前:
=== 🟢 PRIMARY EVIDENCE (HIGH reliability ≥1.2) ===
- SMA200 (1D): $95,182 Above — Lagging, 1.3x
- ADX/DI (1D): +DI=28.5 -DI=14.2 — Lagging, 1.2x
- MACD cross (4H): Bullish crossover — Lagging, 1.2x

=== 🟡 SUPPORTING EVIDENCE (STD reliability 0.8-1.1) ===
- RSI (4H): 58 — Sync, 0.8x
- BB position (4H): Upper band — Sync, 0.6x
- MACD histogram (4H): Positive expanding — Sync-lag, 1.0x
- CVD trend (4H): POSITIVE — Sync-lag, 1.0x
- CVD-Price cross: ACCUMULATION — Leading, 0.9x      ← 标签与 CVD trend 不同类别?

修改后:
=== 🟢 PRIMARY EVIDENCE (HIGH reliability ≥1.2) ===
- SMA200 (1D): $95,182 Above — Trend, 1.3x
- ADX/DI (1D): +DI=28.5 -DI=14.2 — Trend, 1.2x
- MACD cross (4H): Bullish crossover — Trend, 1.2x

=== 🟡 SUPPORTING EVIDENCE (STD reliability 0.8-1.1) ===
- RSI (4H): 58 — Momentum, 0.8x
- BB position (4H): Upper band — Momentum, 0.6x       ← 与 RSI 同类 (均值回归)
- MACD histogram (4H): Positive expanding — Momentum, 1.0x
- CVD trend (4H): POSITIVE — Order Flow, 1.0x
- CVD-Price cross: ACCUMULATION — Order Flow, 0.9x    ← 与 CVD trend 同类别 ✓
```

## 改动范围

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `agents/prompt_constants.py` `_SIGNAL_ANNOTATIONS` | nature 标签替换 | ~35 行 |
| `agents/prompt_constants.py` `SIGNAL_CONFIDENCE_MATRIX` 表格 | 最后列标签替换 | ~70 行 |
| `agents/prompt_constants.py` `SIGNAL_CONFIDENCE_MATRIX` Notes | 术语同步 | ~10 行 |
| `agents/prompt_constants.py` `INDICATOR_DEFINITIONS` Notes | 术语同步 | ~5 行 |
| `agents/prompt_constants.py` `INDICATOR_KNOWLEDGE_BRIEF` | 第 7 条重写 | ~15 行 |
| `agents/report_formatter.py` `compute_scores_from_features()` | 注释文字替换 | ~25 行 |
| `scripts/experiment_reliability_format.py` | 删除 (奥卡姆剃刀) 或同步更新样本 | ~680 行 |
| `agents/ai_quality_auditor.py` | 无改动（不引用 nature 标签） | 0 行 |
| **总计** | **纯标签/注释/术语替换** | **~160 行 (不含脚本删除)** |

## 不变的部分（明确确认）

- [ ] `_SIGNAL_ANNOTATIONS` 的所有 regime multiplier 数值 (`{'strong': 1.3, 'weak': 1.0, 'ranging': 0.4}`)
- [ ] `_get_multiplier()` 函数逻辑（返回签名不变，nature 字段从 16 种 → 7 种）
- [ ] `compute_scores_from_features()` 的所有指标级 `(signal, weight)` 数值
- [ ] `compute_scores_from_features()` 的维度级 regime weights (`trend: 1.5, order_flow: 2.0` 等)
- [ ] Tier 分组逻辑 (`high ≥1.2 / std ≥0.8 / low ≥0.5 / skip <0.5`)
- [ ] TRANSITIONING / reversal detection / divergence 逻辑
- [ ] `ai_quality_auditor.py` 所有代码
- [ ] `report_formatter.py` 除注释外的所有代码
- [ ] 当前 `tests/` 中无 assert 旧 nature 标签的代码（已 grep 确认）

## 风险评估

| 风险 | 级别 | 说明 |
|------|------|------|
| 权重计算错误 | ⬜ 零 | 不改任何数值或逻辑 |
| Auditor 回归 | ⬜ 零 | Auditor 不引用 nature 标签 |
| AI 行为变化 | 🟡 中 | 报告文本变化会改变 AI 输出。`_SIGNAL_ANNOTATIONS` 从 4 种→7 种标签，`SIGNAL_CONFIDENCE_MATRIX` 从 ~16 种→7 种。语义更清晰，但 DeepSeek 已在旧标签下运行 v27-v40 约 20 个版本。方向预期正向，但不确定性存在。需 A/B 对比验证（见验证计划第 5 步） |
| 诊断脚本回归 | ⬜ 零 | 诊断脚本不检查 nature 标签 |

## 验证计划

改动后运行：

```bash
# 1. 静态回归检测
python3 scripts/smart_commit_analyzer.py

# 2. 逻辑同步检查
python3 scripts/check_logic_sync.py

# 3. 单元测试
python3 -m pytest tests/ -v

# 4. 确认 AI 报告输出格式正确
python3 scripts/diagnose.py --quick

# 5. Feature snapshot A/B 对比 (验证 AI 行为变化)
# 步骤:
#   a) 记录当前 main 分支的 commit hash 作为 baseline
#   b) 在 development 环境部署新代码，运行 3-5 个 on_timer 周期生成新 snapshot
#   c) 使用 replay_ab_compare.py 对比新旧 snapshot 的 AI 输出差异
#   d) 检查: 信号方向是否一致？confidence 是否偏移？reasoning 是否更聚焦功能维度？
python3 scripts/replay_ab_compare.py \
  --snapshot-dir data/feature_snapshots/ \
  --baseline-commit <main-branch-hash> \
  --compare-commit <v41.0-branch-hash>
# 预期: 信号方向一致率 >95%, confidence 偏移 ≤1 级
```

## 回滚计划

本次变更为**单 commit 纯文本替换**，回滚极简：

```bash
# 1. 回滚 commit
cd /home/linuxuser/nautilus_AlgVex && git revert <v41.0-commit-hash>

# 2. 无状态文件需清理
# - data/trading_memory.json: 不受影响 (不存储 nature 标签)
# - data/layer_orders.json: 不受影响
# - data/feature_snapshots/: 不受影响 (snapshot 不含 nature 标签)
# - data/hold_counterfactuals.json: 不受影响

# 3. 重启服务
sudo systemctl restart nautilus-trader

# 4. 验证回滚成功
python3 scripts/diagnose.py --quick
```

**回滚触发条件**：
- A/B 对比发现信号方向一致率 <90%
- 部署后 48h 内 AI 决策质量明显下降（quality score 均值下降 >5 分）
- 任何诊断脚本报错

## 版本标记

如果实施，建议标记为 **v41.0** — Unified Indicator Classification。

CLAUDE.md 新增架构决策条目：

```
| v41.0 | Unified Indicator Classification | `_SIGNAL_ANNOTATIONS` nature 标签从 4 种时序标签 (Lagging/Sync/Sync-lag/Quality) 统一为 7 种功能性标签 (Trend/Momentum/Order Flow/Volatility/Risk/Structure/Context)。`SIGNAL_CONFIDENCE_MATRIX` Nature 列从 ~16 种标签同步统一为相同 7 种。与 `compute_scores_from_features()` 的 5 维评分维度对齐 (+2 语义独立类别: Structure/Context)。`INDICATOR_KNOWLEDGE_BRIEF` 第 7 条同步重写。BB position 归 Momentum (均值回归特征) 非 Volatility (BB Width 才是 Volatility)。消除 AI 认知冲突 (同一指标在报告中标 "Sync" 但评分归入 "momentum")。零逻辑变更，零权重变更 |
```

## 评审修复追踪

### v2 评审 (第一轮)

| 评审问题 | 修复状态 | 修复内容 |
|---------|---------|---------|
| MUST-FIX 1: 信息降维丢失 | ✅ | 5→7 标签，增加 Structure + Context；BB position 从 Volatility 改为 Momentum |
| MUST-FIX 2: Notes 段落遗漏 | ✅ | 新增 Section 4 "SIGNAL_CONFIDENCE_MATRIX Notes 段落术语同步" |
| MUST-FIX 3: experiment 脚本遗漏 | ✅ | 新增 Section 6，建议按奥卡姆剃刀删除 |
| 建议 1: 行业论证改进 | ✅ | 重写"问题"第 4 条，聚焦 AlgVex 自身双系统冲突 |
| 建议 2: AI 风险评估 | ✅ | 风险评估从"低"升为"中"，验证计划增加 A/B 对比步骤 |
| 建议 3: BB position 归类 | ✅ | `4h_bb`/`30m_bb`/`1d_bb` 改为 Momentum，附注说明 |
| 建议 4: 返回值文档 | ✅ | "不变的部分"中明确记录 `_get_multiplier()` nature 字段变化 |

### v3 评审 (第二轮 — 代码验证 + 评估框架)

| 评审问题 | 修复状态 | 修复内容 |
|---------|---------|---------|
| MUST-FIX 1: 背景描述夸大 ("16 种") | ✅ | 区分 `_SIGNAL_ANNOTATIONS` (4 标签) 和 `SIGNAL_CONFIDENCE_MATRIX` (~16 描述)，修正所有 "16 种" 引用 |
| MUST-FIX 2: 回滚计划缺失 | ✅ | 新增"回滚计划"段落：`git revert` + 状态文件检查 + 触发条件 |
| MUST-FIX 3: A/B 验证步骤不可执行 | ✅ | 重写步骤 5：明确 baseline commit 记录 → dev 环境部署 → 对比新旧 snapshot → 预期指标 |
| 建议 1: SIGNAL_CONFIDENCE_MATRIX 行号修正 | ✅ | 表格起始于 L307 (非 L335) |
| 建议 2: CLAUDE.md 条目措辞修正 | ✅ | "4 种时序标签" 替代 "16 种"，区分 dict 和文本表 |
