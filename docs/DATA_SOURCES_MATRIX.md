# 数据源矩阵 (Data Sources Matrix)

> 文档版本: v7.0
> 更新日期: 2026-03-01
> 适用版本: AlgVex v23.0+ (7+1 AI calls, Entry Timing Agent)

## 概述

本文档列出所有从 Binance、Coinalyze 及本地计算获取的数据字段，按时间周期组成矩阵，标明采用状态。系统当前覆盖 **13 类数据**，全部已实现。

### 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         数据处理架构 v7.0                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │     Binance       │  │  Coinalyze   │  │  本地计算     │               │
│  │  (K线+衍生品+     │  │   (7 APIs)   │  │ (技术指标+    │               │
│  │   订单簿+情绪)    │  │              │  │  S/R+背离+    │               │
│  │                   │  │              │  │  Extension)   │               │
│  └──────┬───────────┘  └──────┬───────┘  └──────┬───────┘               │
│         │                     │                   │                      │
│         └───────────┬─────────┴─────────┬─────────┘                      │
│                     ▼                   ▼                                │
│         ┌─────────────────────────────────────────┐                      │
│         │    AIDataAssembler (SSoT, v7.0)          │                      │
│         │   - 13 类数据统一聚合                     │                      │
│         │   - 趋势计算 (RISING/FALLING/STABLE)      │                      │
│         │   - CVD-Price 交叉检测 (v19.1)            │                      │
│         │   - OI×CVD 持仓分析 (v19.2)               │                      │
│         │   - RSI/MACD 背离预计算 (v19.1)           │                      │
│         │   - ATR Extension Ratio (v19.1)           │                      │
│         │   - Signal Reliability Tiers (v18.1)      │                      │
│         └─────────────────┬───────────────────────┘                      │
│                           ▼                                              │
│         ┌─────────────────────────────────────────┐                      │
│         │     MultiAgentAnalyzer (AI 决策)         │                      │
│         │   - Bull/Bear 辩论 (2 rounds)            │                      │
│         │   - Judge 量化决策                        │                      │
│         │   - Risk Manager 评估                     │                      │
│         │   - 全 Agent 记忆 + 反思 (v12.0)          │                      │
│         └─────────────────┬───────────────────────┘                      │
│                           ▼                                              │
│         ┌─────────────────────────────────────────┐                      │
│         │       执行层 + 风控                       │                      │
│         │   - S/R 纯信息化 (v11.0, 1+1 v17.0)      │                      │
│         │   - 每层独立 SL/TP (v7.2)                 │                      │
│         │   - Emergency SL 兜底 (v6.1)              │                      │
│         │   - Entry Timing Agent (v23.0)              │                      │
│         └─────────────────────────────────────────┘                      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**设计原则**:
- `AIDataAssembler.fetch_external_data()` 为唯一数据聚合入口 (SSoT, v7.0)
- 本地负责数据预处理 + 预计算 annotation (背离、CVD 交叉、Extension Ratio)
- 所有决策由 AI (MultiAgent Judge) 执行
- 本地负责风控边界检查和订单执行

---

## 一、13 类数据覆盖总览

| # | 数据类别 | 必需 | 来源 | 状态 |
|---|---------|:----:|------|:----:|
| 1 | technical_data (30M) | ✅ | IndicatorManager (含 ATR Extension Ratio) | ✅ |
| 2 | sentiment_data | ✅ | Binance 多空比 (`sentiment_client`) | ✅ |
| 3 | price_data | ✅ | Binance ticker | ✅ |
| 4 | order_flow_report | | BinanceKlineClient (CVD + Taker) | ✅ |
| 5 | derivatives_report (Coinalyze) | | CoinalyzeClient (OI + Liquidations) | ✅ |
| 6 | binance_derivatives (Top Traders) | | BinanceDerivativesClient | ✅ |
| 7 | orderbook_report | | BinanceOrderBookClient | ✅ |
| 8 | mtf_decision_layer (4H) | | 技术指标 + 背离检测 | ✅ |
| 9 | mtf_trend_layer (1D) | | 技术指标 (SMA200 + MACD) | ✅ |
| 10 | current_position | | Binance | ✅ |
| 11 | account_context | ✅ | Binance | ✅ |
| 12 | historical_context | | 内部计算 | ✅ |
| 13 | sr_zones_data | | S/R 计算器 (1+1, v17.0) | ✅ |

**数据完整度: 13/13 = 100%** ✅

---

## 二、Binance K线数据 (12 列)

| # | 字段名 | 数据类型 | 说明 | 1D | 4H | 30M | 采用状态 | 用途 | 建议 |
|---|-------|---------|------|:--:|:--:|:---:|---------|------|------|
| 1 | `open_time` | int64 | 开盘时间戳 (ms) | ✅ | ✅ | ✅ | ✅ 已用 | 时间索引 | - |
| 2 | `open` | float | 开盘价 | ✅ | ✅ | ✅ | ✅ 已用 | 技术指标 | - |
| 3 | `high` | float | 最高价 | ✅ | ✅ | ✅ | ✅ 已用 | S/R 计算 / BB | - |
| 4 | `low` | float | 最低价 | ✅ | ✅ | ✅ | ✅ 已用 | S/R 计算 / BB | - |
| 5 | `close` | float | 收盘价 | ✅ | ✅ | ✅ | ✅ 已用 | 所有指标 | - |
| 6 | `volume` | float | 成交量 (BTC) | ✅ | ✅ | ✅ | ✅ 已用 | 量价分析 / S/R 权重 | - |
| 7 | `close_time` | int64 | 收盘时间戳 (ms) | ✅ | ✅ | ✅ | ❌ 未用 | - | 可选 |
| 8 | `quote_volume` | float | 成交额 (USDT) | ✅ | ✅ | ✅ | ✅ 已用 | 订单流分析 | - |
| 9 | `trades_count` | int | 成交笔数 | ✅ | ✅ | ✅ | ✅ 已用 | 平均交易额 | - |
| 10 | `taker_buy_base` | float | Taker买入量 (BTC) | ✅ | ✅ | ✅ | ✅ 已用 | Buy Ratio | - |
| 11 | `taker_buy_quote` | float | Taker买入额 (USDT) | ✅ | ✅ | ✅ | ✅ 已用 | CVD 计算 | - |
| 12 | `ignore` | - | 忽略字段 | - | - | - | ❌ 未用 | - | - |

**K线利用率: 10/12 = 83%** ✅

**支持的时间周期**: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M

**当前采用**: 30M (执行层, v18.2 从 15M 迁移), 4H (决策层), 1D (趋势层)

---

## 三、Binance 衍生品 API

| API 端点 | 数据字段 | 返回格式 | 采用状态 | 用途 | 客户端 |
|---------|---------|---------|---------|------|--------|
| `/futures/data/topLongShortAccountRatio` | 大户账户比 | `longAccount`, `shortAccount`, `longShortRatio` | ✅ 已用 | 大户情绪 | BinanceDerivativesClient |
| `/futures/data/topLongShortPositionRatio` | 大户持仓比 ⭐ | `longAccount`, `shortAccount`, `longShortRatio` | ✅ 已用 | Top Traders 仓位 | BinanceDerivativesClient |
| `/futures/data/takerlongshortRatio` | Taker买卖比 ⭐ | `buySellRatio`, `buyVol`, `sellVol` | ✅ 已用 | 即时力量 | BinanceDerivativesClient |
| `/futures/data/openInterestHist` | OI历史 | `sumOpenInterest`, `sumOpenInterestValue` | ✅ 已用 | OI趋势 | BinanceDerivativesClient |
| `/fapi/v1/fundingRate` | 资金费率历史 | `fundingRate`, `fundingTime` | ✅ 已用 | 费率趋势 (5位小数) | BinanceDerivativesClient |
| `/fapi/v1/ticker/24hr` | 24h行情 | `priceChange`, `volume`, `highPrice`, `lowPrice` | ✅ 已用 | 波动统计 | BinanceDerivativesClient |
| `/futures/data/globalLongShortAccountRatio` | 全市场多空比 | `longAccount`, `shortAccount` | ✅ 已用 | 市场情绪 | sentiment_client |
| `/fapi/v1/depth` | 订单簿深度 ⭐ | `bids`, `asks` (价格,数量) | ✅ 已用 | 买卖墙 / 流动性 | BinanceOrderBookClient |
| `/fapi/v1/aggTrades` | 聚合成交 | `price`, `quantity`, `isBuyerMaker` | ❌ 未用 | 大单识别 | 可选 |

**Binance 衍生品利用率: 8/9 = 89%** ✅

**支持的周期 (period 参数)**: 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d

---

## 四、Coinalyze API

| API 端点 | 数据字段 | 返回格式 | 采用状态 | 用途 | 建议 |
|---------|---------|---------|---------|------|------|
| `/v1/open-interest` | 当前OI | `value` (BTC), `symbol` | ✅ 已用 | OI水平 | - |
| `/v1/open-interest-history` | OI历史 | `history` [{`t`, `c`}] | ✅ 已用 | OI趋势 | - |
| `/v1/funding-rate` | 当前资金费率 | `value` (小数) | ✅ 已用 | 费率水平 | - |
| `/v1/funding-rate-history` | 资金费率历史 | `history` [{`t`, `o`}] | ✅ 已用 | 费率趋势 | - |
| `/v1/liquidation` | 爆仓数据 | `history` [{`t`, `l`, `s`}] | ✅ 已用 | 极端行情 | - |
| `/v1/long-short-ratio` | 当前多空比 | `value`, `l`, `s` | ✅ 已用 | 多空情绪 | - |
| `/v1/long-short-ratio-history` | 多空比历史 | `history` [{`t`, `r`, `l`, `s`}] | ✅ 已用 | 多空趋势 | - |

**Coinalyze 利用率: 7/7 = 100%** ✅

**注意**: Coinalyze 为可选数据源 (`COINALYZE_API_KEY`)，缺失时系统自动降级

---

## 五、技术指标 (本地计算)

### 5.1 基础技术指标

| 指标 | 参数 | 1D (趋势层) | 4H (决策层) | 30M (执行层) | 用途 | 状态 |
|------|------|:----------:|:----------:|:-----------:|------|------|
| SMA | 200 | ✅ | ❌ | ❌ | 长期趋势 / Risk-On/Off | ✅ 已用 |
| SMA | 50 | ❌ | ✅ | ❌ | 中期趋势 | ✅ 已用 |
| SMA | 20 | ❌ | ✅ | ✅ | 短期趋势 / Extension Ratio 基准 | ✅ 已用 |
| SMA | 5 | ❌ | ❌ | ✅ | 快速趋势 | ✅ 已用 |
| EMA | 12, 26 | ✅ | ✅ | ❌ | MACD 基础 | ✅ 已用 |
| EMA | 10, 20 | ❌ | ❌ | ✅ | 快速均线 | ✅ 已用 |
| RSI | 14 | ✅ | ✅ | ✅ | 超买超卖 + 背离检测 | ✅ 已用 |
| MACD | 12/26/9 | ✅ | ✅ | ✅ | 动量 + 背离检测 | ✅ 已用 |
| BB | 20, 2.0 | ✅ | ✅ | ✅ | 波动率 | ✅ 已用 |
| ADX/DI | 14 | ✅ | ✅ | ✅ | 趋势强度 + 方向 | ✅ 已用 |
| ATR | 14 | ✅ | ✅ | ✅ | 波动率 + SL/TP 计算 | ✅ 已用 |

### 5.2 高级分析 (v19.1+)

| 分析类型 | 时间框架 | 说明 | 版本 | 状态 |
|---------|---------|------|------|:----:|
| **ATR Extension Ratio** | 30M | `(Price - SMA) / ATR` 波动率归一化偏离度。4 级 regime: NORMAL(<2) / EXTENDED(2-3) / OVEREXTENDED(3-5) / EXTREME(≥5)。强趋势 ADX>40 时 OVEREXTENDED 降权 (v19.1.1) | v19.1 | ✅ |
| **RSI 背离预计算** | 4H, 30M | `_detect_divergences()` 检测经典背离。Bearish: price HH + RSI/MACD LH。Bullish: price LL + RSI/MACD HL。Local extremes window=2, 偏差 ≤2 bar 匹配 | v19.1 | ✅ |
| **MACD 背离预计算** | 4H, 30M | 同 RSI 背离，独立检测 MACD histogram 背离 | v19.1 | ✅ |
| **CVD-Price 交叉检测** | 30M, 4H | 5-bar window (v19.2 时间对齐修复)。ACCUMULATION (price↓+CVD↑) / DISTRIBUTION (price↑+CVD↓) / CONFIRMED (price↓+CVD↓) / ABSORPTION (CVD active + price flat ±0.3%, v19.2) | v19.1-v19.2 | ✅ |
| **OI×CVD 持仓分析** | 4H | OI↑+CVD↑=多头开仓 / OI↑+CVD↓=空头开仓 / OI↓+CVD↓=多头平仓 / OI↓+CVD↑=空头平仓 (CoinGlass 行业标准) | v19.2 | ✅ |
| **S/R Zone 计算** | 30M | 聚类候选后输出 nearest 1 support + 1 resistance (v17.0 简化)。S/R 纯信息化 (v11.0)，不机械锚定 SL/TP | v17.0 | ✅ |
| **S/R Hold Probability** | 30M | 自动校准脚本 `calibrate_hold_probability.py` 计算 hold/break 统计因子，写入 `data/calibration/latest.json` | v16.0 | ✅ |

### 5.3 Signal Reliability Tiers (v18.1)

技术报告按可靠性层级分组，取代按时间框架分组 (v18.1):

| Tier | 名称 | 包含指标 | 使用指引 |
|------|------|---------|---------|
| **Tier 1** 🟢 | PRIMARY EVIDENCE | ADX/DI direction, RSI (regime-adjusted), BB Position, 1D Trend Verdict | 核心论据，可独立支撑决策 |
| **Tier 2** 🟡 | SUPPORTING EVIDENCE | MACD (带 ranging 警告), SMA crosses, 4H indicators | 辅助论据，需 Tier 1 确认 |
| **Tier 3** ⚪ | CONTEXT ONLY | Extension Ratio, 背离 annotation, S/R zones | 上下文信息，不可作为独立论据 |

**SIGNAL_CONFIDENCE_MATRIX** 根据 regime (STRONG TREND / WEAK TREND / RANGING) 对每个指标赋予不同权重，AI prompt 内嵌引用。

---

## 六、数据周期覆盖矩阵

| 数据类型 | 1m | 5m | 30m | 1h | 4h | 1d | 1w | 当前采用 |
|---------|:--:|:--:|:---:|:--:|:--:|:--:|:--:|---------|
| Binance K线 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 30M, 4H, 1D (v18.2: 15M→30M) |
| Binance 衍生品 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | 30M→4H |
| Binance 订单簿 | 实时 | - | - | - | - | - | - | ✅ 实时快照 |
| Coinalyze | - | - | - | ✅ | ✅ | - | - | 1H→4H |
| 本地技术指标 | - | - | ✅ | - | ✅ | ✅ | - | 30M, 4H, 1D |
| 背离检测 | - | - | ✅ | - | ✅ | - | - | 30M, 4H (v19.1) |
| CVD-Price 交叉 | - | - | ✅ | - | ✅ | - | - | 30M, 4H (v19.1) |
| Extension Ratio | - | - | ✅ | - | - | - | - | 30M (v19.1) |

---

## 七、三层时间框架 (MTF) 数据分配

| 层级 | 时间框架 | 技术指标 | 外部数据 | 高级分析 |
|------|---------|---------|---------|---------|
| **趋势层** | 1D | SMA200, MACD, RSI, BB, ADX/DI, ATR | — | Trend Verdict (Risk-On/Off) |
| **决策层** | 4H | SMA50, SMA20, MACD, RSI, BB, ADX/DI, ATR | Binance 衍生品, Coinalyze, Top Traders | RSI/MACD 背离, CVD-Price 交叉, OI×CVD 持仓 |
| **执行层** | 30M | SMA20, SMA5, EMA10/20, MACD, RSI, BB, ADX/DI, ATR | 订单流 (BinanceKlineClient), 订单簿 (BinanceOrderBookClient) | Extension Ratio, RSI/MACD 背离, CVD-Price 交叉, S/R zones (1+1) |

---

## 八、数据利用率统计

| 数据源 | 可用 API | 已用 API | 利用率 |
|-------|:--------:|:--------:|:------:|
| Binance K线 | 12 列 | 10 列 | 83% |
| Binance 衍生品 | 9 个 | 8 个 | 89% |
| Coinalyze | 7 个 | 7 个 | 100% |
| **总体** | **28** | **25** | **89%** |

### 未使用项 (P2 低优先级)

| 未使用项 | 数据源 | 原因 | 建议 |
|---------|-------|------|------|
| `close_time` | Binance K线 | 无额外信息 | 保持忽略 |
| 聚合成交 (aggTrades) | Binance | 大单识别为可选增强 | 可选添加 |

---

## 九、参考链接

- [Binance Futures API 文档](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/)
- [Binance Order Book API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/websocket-api/Order-Book)
- [Coinalyze API 文档](https://api.coinalyze.net/v1/doc/)

---

## 十、更新记录

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-01-31 | v3.0 | 初始文档，完整数据矩阵 |
| 2026-02-28 | v7.0 | 全面更新至 v19.2+: 执行层 15M→30M (v18.2); 订单簿已实现 (BinanceOrderBookClient); Top Traders 已实现 (BinanceDerivativesClient); S/R 简化 1+1 (v17.0); Signal Reliability Tiers (v18.1); ATR Extension Ratio (v19.1); RSI/MACD 背离预计算 (v19.1); CVD-Price 交叉 ACCUMULATION/DISTRIBUTION/CONFIRMED/ABSORPTION (v19.1-v19.2); OI×CVD 持仓分析 (v19.2); 移除"缺失数据"章节 (全部已实现); 更新利用率 78%→89% |
