# Indicator Signal Confidence Matrix (方案 A — Prompt 层增强)

> **状态**: **已实施 (v1.2)** — commit `7a5b07f`
> **目标**: 在 Judge 和 Risk Manager 的 system prompt 中插入结构化权重矩阵，让 AI 在不同 market regime 下对不同信号给予量化的置信度调整
> **影响范围**: `agents/prompt_constants.py` 中的 `INDICATOR_DEFINITIONS`、`SIGNAL_CONFIDENCE_MATRIX`、`INDICATOR_KNOWLEDGE_BRIEF` 常量
> **评审**: 10 维度专家评审 (v1.1) + 4 项阻塞问题修复 (v1.2)
> **当前状态**: v28.0 feature-driven 路径使用 `INDICATOR_KNOWLEDGE_BRIEF` (~500 tokens，浓缩版); text fallback 路径仍使用完整 `INDICATOR_DEFINITIONS` + `SIGNAL_CONFIDENCE_MATRIX`

---

## 一、背景与动机

当前系统在 `INDICATOR_DEFINITIONS` (v4.0) 中用文字描述了指标在不同 regime 下的行为，但：
- AI 可能选择性忽略文字描述（尤其在数据量大时）
- 没有量化的 per-signal、per-regime confidence 参考
- 时序数据（20 bar 序列）、多源同类数据、衍生品时间维度信号完全没有 confidence 指导

## 二、实施架构

### v28.0 双路径架构

v28.0 起系统有两套 prompt 路径，知识注入方式不同：

**路径 1: Feature-Driven (v27.0+, 默认)** — 所有 5 个 Agent 使用:
- `INDICATOR_KNOWLEDGE_BRIEF` (~500 tokens) — 浓缩的 8 条 regime-aware 规则
- Pre-computed `_scores` (dimensional assessment) 作为 primacy anchoring
- Feature dict (82 个 typed features) + `REASON_TAGS` 输出约束
- `SIGNAL_CONFIDENCE_MATRIX` 的知识已融入 `compute_valid_tags()` 标签预计算

**路径 2: Text-Based (fallback, feature extraction 失败时)**:
- `INDICATOR_DEFINITIONS` (~4K tokens) — 完整指标定义
- `SIGNAL_CONFIDENCE_MATRIX` (~5K tokens) — Judge/Entry Timing/Risk Manager
- 自然语言报告输入，自由文本输出

```python
# agents/prompt_constants.py

# v28.0 structured path (default):
INDICATOR_KNOWLEDGE_BRIEF = """=== INDICATOR INTERPRETATION RULES ===..."""  # ~500 tokens

# Text fallback path:
INDICATOR_DEFINITIONS = """..."""           # ~4K tokens (Bull/Bear/Judge/ET/Risk)
SIGNAL_CONFIDENCE_MATRIX = """..."""        # ~5K tokens (Judge/ET/Risk only)
```

## 三、Market Regime 定义

### v1.2 修正：与现有系统完全对齐 + 补全 VOLATILE TREND

现有系统定义 (INDICATOR_DEFINITIONS line 62-73):
```
ADX > 25 + clear price direction    → TRENDING
ADX < 20 + price oscillating        → RANGING
ADX < 20 + BB Width at lows         → SQUEEZE (pre-breakout)
ADX > 25 + BB Width expanding fast  → VOLATILE TREND
```

Judge prompt (line 941-945) 进一步将 TRENDING 细分:
```
强趋势 (ADX > 40) / 弱趋势 (25 < ADX < 40) / 震荡市 (ADX < 20) / 挤压
```

矩阵使用 **5 列**，对齐 Judge 的细分 + 补全 VOLATILE：

| 列名 | 条件 | 特征 |
|------|------|------|
| ADX>40 | ADX > 40, clear direction | 趋势层主导，逆势信号需极强确认 |
| ADX 25-40 | 25 < ADX ≤ 40 | 趋势重要但非绝对 |
| ADX<20 | ADX < 20, 价格振荡 | 关键水平层权重最高，均值回归有效 |
| SQUEEZE | ADX < 20 + BB Width 收窄 | 大动作临近，方向未知 |
| VOLATILE | ADX > 25 + BB Width expanding | 趋势跟随有效，但需更宽止损，噪声更大 |

**过渡区处理**：
| 过渡区 | ADX 范围 | 处理方式 |
|--------|---------|---------|
| ADX<20 → ADX 25-40 | 18-22 | 两个 regime 的 multiplier 取平均值 |
| ADX 25-40 → ADX>40 | 35-45 | 两个 regime 的 multiplier 取平均值 |

---

## 四、完整 Prompt 文本 (SIGNAL_CONFIDENCE_MATRIX)

以下是 `SIGNAL_CONFIDENCE_MATRIX` 常量的完整内容：

```
====================================================================
SIGNAL CONFIDENCE MATRIX (v1.2)
====================================================================
When evaluating each confluence layer in STEP 2, apply these confidence
multipliers to weight each signal's reliability in the current regime
(determined in STEP 1).

MULTIPLIER SCALE:
  HIGH (1.2+) = Signal is especially reliable in this regime
  STD  (1.0)  = Standard confidence
  LOW  (0.7)  = Needs other signals to confirm before trusting
  SKIP (≤0.4) = Unreliable in this regime — ignore as primary basis

REGIME COLUMNS: Match your STEP 1 regime to the correct column.
  ADX>40     = Strong trend (趋势层主导)
  ADX 25-40  = Weak trend (趋势重要但非绝对)
  ADX<20     = Ranging / 震荡 (关键水平层权重最高)
  SQUEEZE    = ADX<20 + BB Width at lows (等待突破)
  VOLATILE   = ADX>25 + BB Width expanding fast (趋势跟随 + 宽止损)

REGIME TRANSITION: When ADX is near a boundary (18-22 or 35-45),
blend the multipliers of adjacent regimes (take the average).

====================================================================
SECTION A: SNAPSHOT SIGNALS (per confluence layer)
====================================================================

--- LAYER 1: TREND (1D) → fill confluence.trend_1d ---

| Signal              | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature  |
|---------------------|:---:|:---:|:---:|:---:|:---:|---------|
| 1D SMA200 direction | 1.3 | 1.0 | 0.4 | 0.3 | 1.1 | Trend     |
| 1D ADX/DI direction | 1.2 | 1.0 | 0.3 | 0.3 | 1.1 | Trend     |
| 1D MACD zero-line   | 1.1 | 1.0 | 0.3 | 0.5 | 1.0 | Trend     |
| 1D RSI level        | 0.9 | 1.0 | 0.7 | 0.6 | 0.8 | Momentum  |

Notes:
- ADX>40: This layer is DOMINANT — all signals reliable.
- ADX<20: This layer is nearly irrelevant (trend data is noise).
- SQUEEZE: Historical trend direction has low predictive value (about to change).
- VOLATILE: Trend is real but noisy — slightly less reliable than calm strong trend.
- ⚠️ 1D TREND VERDICT (STRONG_BULLISH etc.) is pre-computed from these 4 signals.
  It is a SUMMARY — do NOT count it as a 5th independent signal. (See RULE 2)

--- LAYER 2: MOMENTUM (4H) → fill confluence.momentum_4h ---

| Signal               | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature   |
|----------------------|:---:|:---:|:---:|:---:|:---:|----------|
| 4H RSI level         | 0.8 | 1.0 | 1.2 | 0.9 | 0.7 | Momentum   |
| 4H RSI divergence*   | 0.6 | 0.8 | 1.3 | 1.1 | 0.5 | Momentum   |
| 4H MACD cross        | 1.2 | 1.0 | 0.3 | 0.5 | 1.1 | Trend      |
| 4H MACD histogram    | 1.0 | 1.0 | 0.5 | 0.7 | 0.9 | Momentum   |
| 4H ADX/DI direction  | 1.1 | 1.0 | 0.4 | 0.5 | 1.0 | Trend      |
| 4H BB position       | 0.6 | 0.9 | 1.2 | 0.8 | 0.5 | Momentum   |
| 4H SMA 20/50 cross   | 1.1 | 1.0 | 0.4 | 0.6 | 1.0 | Trend      |
| CVD single-bar delta | 0.9 | 1.0 | 1.2 | 1.3 | 1.0 | Order Flow |
| CVD trend (cumul.)   | 1.1 | 1.0 | 0.8 | 0.7 | 1.0 | Order Flow |
| CVD divergence*      | 0.7 | 0.9 | 1.3 | 1.2 | 0.5 | Order Flow |
| CVD absorption**     | 0.5 | 0.8 | 1.3 | 1.0 | 0.4 | Order Flow |
| OI×CVD positioning   | 1.1 | 1.0 | 0.8 | 0.9 | 1.0 | Order Flow |
| Buy Ratio (taker %)  | 0.8 | 1.0 | 1.1 | 1.2 | 0.9 | Order Flow |
| Avg Trade Size chg   | 0.7 | 0.9 | 1.0 | 1.2 | 0.8 | Order Flow |

Notes:
- *Divergence = inferred from series data (RSI or CVD vs price opposite directions).
- **Absorption = CVD positive/negative but price flat (±0.3%). Most reliable in RANGING (1.3)
  where passive orders are most visible. Unreliable in TRENDING (0.5) — trend absorbs volume naturally. (v19.2)
- OI×CVD: OI↑+CVD↑=longs opening, OI↑+CVD↓=shorts opening, OI↓+CVD↓=longs closing, OI↓+CVD↑=shorts closing.
  CoinGlass industry-standard framework. Bridges OI×Price and CVD×Price analysis. (v19.2)
- RSI in ADX>40: Cardwell range shifts apply (40-80 uptrend, 20-60 downtrend),
  traditional 30/70 FAIL. Divergence at 0.6 because it still signals deceleration.
- MACD cross in ADX<20: 74-97% false positive rate — nearly useless.
- VOLATILE: Divergence signals (RSI/CVD) are very unreliable (0.5) due to noise-induced
  false divergences. Trend signals (MACD cross, ADX/DI) remain useful.
  BB position also unreliable — price swings overshoot bands frequently.
- Buy Ratio: Taker buy % from Order Flow data. >55% = buy pressure, <45% = sell.
- Avg Trade Size: Sudden increase = institutional activity (order flow signal).

--- LAYER 3: KEY LEVELS (30M) → fill confluence.levels_30m ---

| Signal               | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature   |
|----------------------|:---:|:---:|:---:|:---:|:---:|----------|
| S/R zone test (bnce) | 0.5 | 0.8 | 1.3 | 1.0 | 0.4 | Structure  |
| S/R zone breakout    | 1.3 | 1.0 | 0.6 | 1.2 | 1.3 | Structure  |
| 30M BB position      | 0.6 | 0.9 | 1.2 | 0.8 | 0.5 | Momentum   |
| 30M BB Width level   | 0.7 | 0.8 | 0.9 | 1.3 | 0.8 | Volatility |
| OBI (book imbalance) | 0.6 | 0.8 | 1.1 | 1.2 | 0.5 | Order Flow |
| OBI change rate      | 0.7 | 0.9 | 1.2 | 1.3 | 0.6 | Order Flow |
| Bid/Ask depth change | 0.7 | 0.9 | 1.1 | 1.2 | 0.6 | Order Flow |
| Pressure gradient    | 0.6 | 0.8 | 1.1 | 1.2 | 0.5 | Order Flow |
| Order walls (>3x)    | 0.4 | 0.6 | 0.9 | 1.0 | 0.3 | Order Flow |
| 30M SMA cross (5/20) | 0.9 | 1.0 | 0.6 | 0.7 | 0.8 | Trend      |
| 30M Volume ratio     | 0.9 | 1.0 | 1.1 | 1.3 | 1.2 | Momentum   |
| Price vs period H/L  | 0.8 | 1.0 | 1.1 | 1.0 | 0.9 | Structure  |
| Spread (liquidity)   | 0.9 | 1.0 | 1.0 | 1.1 | 1.1 | Risk       |
| Slippage (execution) | 0.9 | 1.0 | 1.0 | 1.1 | 1.1 | Risk       |

| Ext Ratio >3 (overext)| 0.7 | 1.0 | 1.3 | 0.8 | 0.6 | Volatility |
| Ext Ratio >5 (extreme)| 1.0 | 1.2 | 1.4 | 0.9 | 0.8 | Volatility |

--- ATR VOLATILITY REGIME (v20.0) → supplements RISK assessment ---

| Signal                    | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature  |
|---------------------------|:---:|:---:|:---:|:---:|:---:|---------|
| Vol LOW (<30th pctl)      | 1.0 | 1.0 | 1.2 | 1.1 | 0.8 | Volatility |
| Vol HIGH (70-90th pctl)   | 0.8 | 0.9 | 0.8 | 0.7 | 1.0 | Volatility |
| Vol EXTREME (>90th pctl)  | 0.6 | 0.7 | 0.6 | 0.6 | 0.8 | Volatility |

--- OBV DIVERGENCE (v20.0) → supplements MOMENTUM assessment ---

| Signal                    | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature  |
|---------------------------|:---:|:---:|:---:|:---:|:---:|---------|
| 4H OBV divergence         | 0.7 | 0.9 | 1.2 | 1.0 | 0.6 | Momentum |
| OBV+CVD confluence div    | 1.1 | 1.2 | 1.4 | 1.2 | 0.8 | Momentum |

Notes:
- ATR Extension Ratio = `(Price - SMA) / ATR`. Measures volatility-normalized price displacement.
  Regimes: NORMAL(<2), EXTENDED(2-3), OVEREXTENDED(3-5), EXTREME(≥5). Pure RISK signal, does not
  affect direction. OVEREXTENDED/EXTREME → reduce position size, caution on entries. (v19.1)
- Volatility Regime = ATR% percentile rank over 90-bar lookback. Orthogonal to ADX.
  LOW vol in ranging market (1.2) = squeeze, breakout imminent. HIGH/EXTREME vol reduces
  confidence in all signals (wider stops needed, whipsaw risk). (v20.0)
- OBV divergence alone has 40-60% false positive rate — use as supplementary signal only.
  OBV + CVD confluence (both diverging from price) = strong volume-flow signal.
  ADX>40: OBV divergence less reliable (strong trends override). ADX<20: most actionable (1.2). (v20.0)
- S/R bounce rate: ADX>40 → ~25%, ADX<20 → ~70%.
- VOLATILE: S/R breaks violently (0.4 bounce, 1.3 breakout). Order book is unstable
  (walls eaten or pulled quickly). Volume ratio is meaningful (confirms volatile move).
- Order walls in crypto: Spoofing probability HIGH (>70% of large walls are pulled
  before touch in trending markets). SKIP in ADX>40 and VOLATILE.
- Spread & Slippage: Not directional — indicate execution quality. High spread (>0.05%)
  or high slippage (>0.1% for 1 BTC) → reduce Layer 3 confidence by one tier
  AND reduce position size.

--- LAYER 4: DERIVATIVES → fill confluence.derivatives ---
⚠️ This layer has the most signals. To prevent it from dominating,
group related signals and evaluate the GROUP as one input:
  Group A: Funding Rate (current + extreme + predicted + history + countdown) → 1 input
  Group B: Open Interest (OI 4-quadrant + OI trend + Premium Index) → 1 input
  Group C: Positioning (Top Traders + Global L/S + Coinalyze L/S) → 1 input
  Group D: Real-time flow (Taker Ratio + Liquidations + 24h context) → 1 input
Then synthesize the 4 group conclusions into ONE overall BULLISH/BEARISH/NEUTRAL
for confluence.derivatives.

| Signal                       | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature   |
|------------------------------|:---:|:---:|:---:|:---:|:---:|----------|
| — GROUP A: FUNDING RATE —    |     |     |     |     |     |          |
| FR current value             | 0.8 | 0.9 | 1.0 | 1.0 | 0.8 | Risk       |
| FR extreme (>±0.05%)        | 0.8 | 1.1 | 1.3 | 1.2 | 0.9 | Risk       |
| FR predicted vs settled diff | 0.9 | 1.0 | 1.1 | 1.2 | 0.9 | Risk       |
| FR settlement history trend  | 0.8 | 1.0 | 1.1 | 1.0 | 0.8 | Risk       |
| FR settlement countdown      | 0.7 | 0.8 | 0.9 | 1.0 | 0.7 | Risk       |
| — GROUP B: OPEN INTEREST —   |     |     |     |     |     |          |
| Premium Index                | 0.8 | 1.0 | 1.1 | 1.2 | 0.9 | Risk       |
| OI↑+Price↑ (new longs)      | 1.2 | 1.0 | 0.8 | 0.9 | 1.1 | Risk       |
| OI↑+Price↓ (new shorts)     | 1.2 | 1.0 | 0.8 | 0.9 | 1.1 | Risk       |
| OI↓ (unwinding/liquidation)  | 0.9 | 1.0 | 1.0 | 0.8 | 1.0 | Risk       |
| — GROUP C: POSITIONING —     |     |     |     |     |     |          |
| Top Traders L/S position     | 1.0 | 1.0 | 1.2 | 1.1 | 1.0 | Risk       |
| Global L/S extreme (>60%)   | 0.6 | 0.9 | 1.2 | 1.1 | 0.7 | Risk       |
| Coinalyze L/S Ratio + trend | 0.7 | 0.9 | 1.1 | 1.0 | 0.7 | Risk       |
| — GROUP D: REAL-TIME FLOW —  |     |     |     |     |     |          |
| Taker Buy/Sell Ratio         | 0.9 | 1.0 | 1.1 | 1.2 | 1.0 | Order Flow |
| Liquidation (large event)    | 1.0 | 1.1 | 1.2 | 1.3 | 1.2 | Risk       |
| 24h Volume level             | 0.8 | 1.0 | 1.0 | 1.1 | 1.1 | Context    |
| 24h Price Change %           | 0.7 | 0.9 | 0.9 | 1.0 | 0.8 | Context    |

Notes:
- ⚠️ GROUP RULE: Pick the strongest signal within each group to represent it.
  Do NOT stack all FR signals into one massive FR-driven conclusion.
- FR current in ADX>40: 0.01-0.03% in bull market is NORMAL — don't over-interpret.
- FR predicted vs settled: Sign reversal (+→-) = significant positioning change.
- OI 4-quadrant in ADX>40: New positioning confirms trend — high reliability.
- OI 4-quadrant in ADX<20: May be hedging — moderate value (0.8).
- Top Traders in ADX>40: Smart money WITH trend = confirmation (1.0).
  Top Traders AGAINST trend = early warning, needs 2+ confirmations.
- VOLATILE: FR signals slightly less predictive (volatile markets amplify FR).
  OI confirmation still useful (1.1). Liquidation events are significant (1.2)
  — cascade liquidations in volatile markets can be extreme.

====================================================================
SECTION B: TIME-SERIES PATTERN SIGNALS
====================================================================
AI receives 20-bar (30M) time-series data. Detect patterns from
series, then apply multipliers.

--- PRICE SERIES PATTERNS ---

| Pattern                | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature  |
|------------------------|:---:|:---:|:---:|:---:|:---:|---------|
| Higher highs/lows      | 1.3 | 1.0 | 0.5 | 0.6 | 1.2 | Trend      |
| Lower highs/lows       | 1.3 | 1.0 | 0.5 | 0.6 | 1.2 | Trend      |
| Range-bound oscillation| 0.4 | 0.7 | 1.3 | 1.0 | 0.3 | Structure  |
| Tightening range       | 0.5 | 0.8 | 1.0 | 1.3 | 0.5 | Volatility |
| Volume climax (spike)  | 1.0 | 1.1 | 1.2 | 1.3 | 1.2 | Momentum   |

--- INDICATOR SERIES PATTERNS ---

| Pattern                | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature  |
|------------------------|:---:|:---:|:---:|:---:|:---:|---------|
| ADX series rising      | 1.2 | 1.1 | 1.3 | 1.2 | 1.1 | Trend — trend strengthening      |
| ADX series falling     | 0.8 | 1.0 | 0.7 | 0.7 | 0.9 | Trend — trend weakening          |
| BB Width narrowing     | 0.6 | 0.8 | 1.0 | 1.3 | 0.5 | Volatility — squeeze forming     |
| BB Width expanding     | 1.1 | 1.0 | 0.8 | 1.3 | 1.2 | Volatility — breakout active     |
| SMA convergence (5→20) | 0.7 | 0.9 | 1.1 | 1.2 | 0.7 | Trend — regime change            |
| SMA divergence (spread)| 1.2 | 1.0 | 0.5 | 0.8 | 1.1 | Trend — trend established        |
| RSI trend (accel/decel)| 0.9 | 1.0 | 1.1 | 1.0 | 0.8 | Momentum                         |
| MACD histogram momentum| 1.0 | 1.0 | 0.5 | 0.8 | 0.9 | Momentum                         |
| Volume trend (expand)  | 1.1 | 1.0 | 1.0 | 1.3 | 1.2 | Momentum                         |
| Volume trend (shrink)  | 0.8 | 0.9 | 0.9 | 0.7 | 0.8 | Momentum                         |

--- K-LINE OHLCV PATTERNS ---

| Pattern                | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature  |
|------------------------|:---:|:---:|:---:|:---:|:---:|---------|
| Engulfing candle       | 0.7 | 1.0 | 1.2 | 1.3 | 0.6 | Momentum — reversal      |
| Doji at S/R            | 0.5 | 0.8 | 1.3 | 1.1 | 0.4 | Momentum — indecision    |
| Long wicks (rejection) | 0.6 | 0.9 | 1.2 | 1.1 | 0.5 | Momentum — rejection     |
| Consecutive same-dir   | 1.2 | 1.0 | 0.6 | 0.8 | 1.1 | Trend — continuation     |

Notes:
- ADX rising in ADX<20 (1.3) = CRITICAL early signal. ADX climbing 12→18 means
  regime is about to shift to TRENDING. One of the most valuable signals.
- BB Width narrowing in SQUEEZE at 1.3 (not 1.5): narrowing DEFINES squeeze,
  so highest multiplier would be circular. 1.3 for the process is appropriate.
- VOLATILE: Reversal patterns (engulfing, doji, wicks) are very unreliable
  (0.4-0.6) — volatility creates many false reversal signals. Trend continuation
  patterns remain useful (1.1-1.2). Volume and BB Width expansion confirm the move.

====================================================================
SECTION C: MULTI-SOURCE SIGNAL DIFFERENTIATION
====================================================================
The system receives similar data from multiple sources. These are NOT
redundant — each has different predictive characteristics.

--- LONG/SHORT POSITIONING (3 sources) ---

| Source                | Represents              | Edge                    | Relative |
|-----------------------|-------------------------|-------------------------|:---:|
| Top Traders Position  | Institutional/whale     | Best predictor          | Highest  |
| Taker Buy/Sell Ratio  | Real-time aggressive flow| Real-time direction    | High     |
| Binance Global L/S    | Retail sentiment        | Contrarian at extremes  | Base     |
| Coinalyze L/S Ratio   | Exchange-specific       | Cross-validates Binance | Below    |

RULE: Top Traders vs Global L/S diverge → weight Top Traders.
      All 3+ agree at extremes → very HIGH confidence.

--- OPEN INTEREST (2 sources) ---

| Source        | Characteristic            | Best for             |
|---------------|---------------------------|----------------------|
| Coinalyze OI  | Aggregated multi-exchange | Macro trend (4H)     |
| Binance OI    | Single exchange, real-time| Short-term moves(30M)|

RULE: Same trend → add one confidence tier to OI assessment.
      Disagree → use Binance for execution, Coinalyze for context.

--- FUND FLOW (2 sources) ---

| Source        | Calculation              | Best for              |
|---------------|--------------------------|----------------------|
| CVD (K-line)  | Cumulative taker delta   | Trend over bars      |
| Taker Ratio   | Buy/Sell vol snapshot    | Real-time pressure   |

RULE: Same direction → cross-validated, add one confidence tier.
      Diverge → transitioning, reduce one tier.

====================================================================
SECTION D: GLOBAL SIGNAL QUALITY MODIFIERS
====================================================================
These modify RELIABILITY of all signals. Apply BEFORE final decision.
Use TIER shifts (not math): each condition shifts confidence DOWN/UP
by one tier (HIGH→STD, STD→LOW, LOW→SKIP).

| Condition                                    | Effect        | Applies to              |
|----------------------------------------------|:---:|--------------------------|
| Volume Ratio < 0.5x (from 30M data)         | DOWN one tier | ALL signals              |
| Volume Ratio > 2.0x                          | UP one tier   | ALL signals              |
| Spread > 0.05% OR Slippage > 0.1%           | DOWN one tier | Layer 3 + position size  |
| 2+ data sources unavailable                  | DOWN one tier | Affected layers          |
| FR settlement < 30 min away                  | DOWN one tier | Short-term (30M) signals |
| Low volume + thin orderbook across bars      | DOWN one tier | ALL signals (weekend/off-hours) |

Notes:
- Tier shifts stack: 2 conditions = DOWN two tiers.
- Volume Ratio comes from 30M data ("Volume Ratio: X.XXx average").
- Weekend/off-hours: No date data available. Infer from persistently low
  volume ratio + reduced orderbook depth across multiple snapshots.

====================================================================
SECTION E: APPLICATION RULES
====================================================================

RULE 1 — Layer evaluation:
  For each confluence layer, assess each signal weighted by its
  confidence tier in the current regime:
    HIGH (1.2+) = Primary evidence for layer judgment
    STD  (1.0)  = Supporting evidence
    LOW  (0.7)  = Note but don't base judgment on it alone
    SKIP (≤0.4) = Ignore for this regime

RULE 2 — TREND VERDICT is not a 5th signal:
  The pre-computed 1D TREND VERDICT is a summary of the 4 Layer 1
  signals. Use for quick reference ONLY. Do NOT count as independent.

RULE 3 — Conflict resolution:
  If order flow and trend signals within one layer conflict, prioritize
  the one with HIGHER confidence tier in current regime.

RULE 4 — Neutral threshold:
  If only SKIP or LOW signals support a direction in a layer,
  that layer should be judged NEUTRAL.

RULE 5 — SQUEEZE special case:
  Wait for breakout confirmation (volume + price) before applying
  directional multipliers. Pre-breakout: focus on BB Width, Volume,
  OBI change rate, ADX rising.

RULE 6 — Counter-trend in ADX>40:
  Even HIGH counter-trend signals require at least 2 independent
  confirming signals before consideration.

RULE 7 — Multi-source agreement:
  3+ independent sources agree on direction → upgrade that layer
  by one confidence tier.

RULE 8 — Layer 4 grouping → confluence.derivatives:
  Evaluate Layer 4 in 4 groups (A/B/C/D). Each group = 1 input.
  Then synthesize the 4 group conclusions into ONE overall
  BULLISH/BEARISH/NEUTRAL judgment for the confluence.derivatives field.

RULE 9 — Global quality check:
  Before final decision, check Section D. Apply tier shifts.
```

---

## 五、Judge Few-shot 示例 (新增 2 个)

### v1.2 修正：增加 2 个展示 confidence matrix 应用的示例

以下 2 个示例追加到 Judge 现有 4 个示例之后 (line ~1010)：

```
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
结果: {{"confluence":{{"trend_1d":"BEARISH — ADX=48 DI->DI+, 趋势层全 HIGH (矩阵 1.1-1.3)","momentum_4h":"BEARISH — MACD 负值顺势 (矩阵 1.2)，RSI 背离被降级 (矩阵 0.6=LOW + RULE 6 需 2 确认)","levels_30m":"BEARISH — S/R 被跌破 (矩阵 1.3=HIGH，趋势延续确认)","derivatives":"BEARISH — FR +0.06% 拥挤多头 (矩阵 0.8=LOW)","aligned_layers":4}},"decision":"SHORT","winning_side":"BEAR","confidence":"HIGH","rationale":"ADX=48 强下跌。矩阵将 RSI 背离从 HIGH 降为 LOW (0.6)，加上 RULE 6 要求 2 个逆势确认但只有 1 个。4 层一致看空。","strategic_actions":["顺势做空，SL 设在上方阻力位"],"acknowledged_risks":["RSI 背离可能预示反弹，但单一 LOW 信号不构成改变决策的理由"]}}
```

---

## 六、与现有系统的兼容性

| 现有 Prompt 段落 | 方案 A 关系 | 冲突 |
|-----------------|-----------|------|
| INDICATOR REFERENCE (v4.0) | 增强 — 量化文字描述为 multiplier | 无冲突 (独立常量) |
| Judge STEP 1 (Regime 判断) | 依赖 — multiplier 需要先确定 regime | 无冲突 |
| Judge STEP 2 (层级权重) | 互补 — 层级权重="哪层重要"，multiplier="层内哪个信号可信" | 无冲突 |
| Judge STEP 2 → confluence.derivatives | RULE 8 明确说明 4 组汇总为 1 个判断 | **v1.2 已解决** |
| Judge Few-shot (4→6 个示例) | 示例 5+6 展示矩阵应用 | **v1.2 已解决** |
| Risk Manager prompt | Section D 指导仓位调整 | 无冲突 |
| Bull/Bear prompt | 不插入，不影响辩论 | **v1.2 已解决 (独立常量)** |
| base.yaml weights | 不同维度 (数据类别 vs 信号级) | 无冲突 |

## 七、覆盖度验证

### AI 实际接收的 49 个数据点 vs 方案 A 覆盖

| 数据来源 | 数据点数 | 方案 A 覆盖 | 覆盖方式 |
|---------|:---:|:---:|---------|
| 30M 技术快照 | 9 | 9 | Section A Layer 2+3 |
| 4H 技术快照 | 5 | 5 | Section A Layer 2 |
| 1D 技术快照 | 5 | 5 | Section A Layer 1 (VERDICT as note) |
| Historical 时序 | 8 | 8 | Section B |
| K-line OHLCV | 1 | 1 | Section B K-line |
| Order Flow | 3 | 3 | Section A Layer 2 (显式) |
| CVD Absorption / OI×CVD | 2 | 2 | Section A Layer 2 (v19.2) |
| Coinalyze 衍生品 | 8 | 8 | Section A Layer 4 Group A+B |
| Binance 衍生品 | 4 | 4 | Section A Layer 4 Group C+D |
| 订单簿 | 5 | 5 | Section A Layer 3 (显式) |
| Sentiment | 1 | 1 | Section A Layer 4 Group C |
| ATR Vol Regime / OBV | 5 | 5 | Section A 独立段 (v20.0) |
| **合计** | **56** | **56** | **100%** |

## 八、Token 成本估算

| 段落 | 估算 Tokens |
|------|:---:|
| Section A (5 列 × 4 层 + grouping) | ~750 |
| Section B (时序 × 5 列) | ~400 |
| Section C (多源区分) | ~200 |
| Section D (全局修正器) | ~120 |
| Section E (9 条规则) | ~180 |
| Few-shot 示例 5+6 | ~350 |
| **合计** | **~2,000** |

当前 Judge prompt = 11,681 tokens，增加后约 13,700 tokens。仍在 DeepSeek 64K 上下文内。

## 九、实施步骤

1. **创建常量**：在 `multi_agent_analyzer.py` 的 `INDICATOR_DEFINITIONS` 后面 (line ~183) 新建 `SIGNAL_CONFIDENCE_MATRIX` 字符串常量
2. **Judge prompt**：在 `{INDICATOR_DEFINITIONS}` 后追加 `{SIGNAL_CONFIDENCE_MATRIX}`，在示例 4 后追加示例 5+6
3. **Risk Manager prompt**：在 `{INDICATOR_DEFINITIONS}` 后追加 `{SIGNAL_CONFIDENCE_MATRIX}`
4. **Bull/Bear**：不修改
5. **验证**：`python3 scripts/diagnose_realtime.py --export` 检查 AI 输出
6. **迭代**：根据 ai_calls 日志调整 multiplier

## 十、风险与注意事项

1. **AI 遵循度**：通过 few-shot 示例 5+6 强化。若仍不足，可在 STEP 2 指令中加一句 "参考信号置信度矩阵"
2. **Multiplier 数值需迭代**：基于理论估算，非回测验证
3. **Prompt 长度**：增加约 2,000 tokens → Judge 总计 ~13,700，安全范围
4. **Bull/Bear 不受影响**：独立常量确保辩论者自由发挥
5. **VOLATILE regime**：v1.2 新增列，特征 = 趋势有效 + 噪声大 + 止损需更宽

## 十一、v1.1 → v1.2 变更日志

### 4 项阻塞问题修复

| # | 阻塞问题 | v1.1 状态 | v1.2 修正 |
|---|---------|----------|----------|
| B1 | `INDICATOR_DEFINITIONS` 被 4 个 Agent 共享 | 计划追加到共享常量 → Bull/Bear 也会收到 | 改为独立常量 `SIGNAL_CONFIDENCE_MATRIX`，仅 Judge + Risk Manager 引用 |
| B2 | Regime 命名不匹配 + VOLATILE TREND 缺失 | 使用 STRONG_TREND/WEAK_TREND (4列)，不匹配现有系统，缺 VOLATILE | 列名改为 ADX>40/ADX 25-40/ADX<20/SQUEEZE/VOLATILE (5列)，与系统完全对齐 |
| B3 | 无 Few-shot 示例展示矩阵应用 | 仅建议"增加 1-2 个" | 完成 2 个完整示例：示例 5 (震荡市 MACD SKIP) + 示例 6 (强趋势 RSI背离降级) |
| B4 | RULE 8 与 Judge STEP 2 交互未定义 | "4 组各 1 输入" 但未说明如何填 confluence.derivatives | RULE 8 明确: "synthesize 4 group conclusions into ONE BULLISH/BEARISH/NEUTRAL for confluence.derivatives" |

### VOLATILE 列设计理由

VOLATILE TREND = ADX>25 + BB Width 快速扩张。特征：趋势跟随有效，但价格波动大、噪声多。

| 信号类型 | VOLATILE 列逻辑 | 典型值 |
|---------|---------------|:---:|
| 趋势确认 (SMA, ADX/DI, MACD cross) | 有效但略低于 ADX>40 (噪声干扰) | 1.0-1.1 |
| 反转/背离 (RSI div, CVD div, engulfing) | 很不可靠 (波动创造大量假信号) | 0.4-0.6 |
| S/R 测试 (bounce) | 极不可靠 (价格暴力穿越) | 0.3-0.4 |
| S/R 突破 | 非常可靠 (突破确认趋势延续) | 1.3 |
| 订单簿 (OBI, walls, gradient) | 不稳定 (快速变化) | 0.3-0.6 |
| Volume | 有意义 (确认波动的真实性) | 1.1-1.2 |
| Spread/Slippage | 更重要 (波动市场执行风险更高) | 1.1 |
