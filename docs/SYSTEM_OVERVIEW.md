# AlgVex 系统功能全面概述

本文档对 AlgVex 项目进行全面梳理，涵盖系统架构、核心功能、技术实现和运维要点。

## 1. 项目概述

AlgVex 是一个基于 NautilusTrader 框架的 AI 驱动加密货币交易系统，专注于 Binance Futures BTCUSDT-PERP 永续合约交易。使用 DeepSeek AI 多代理辩论式信号生成，结合三层多时间框架 (MTF) 分析和 ATR 机械止损止盈。

| 项目 | 说明 |
|------|------|
| **入口文件** | `main_live.py` (非 main.py) |
| **框架** | NautilusTrader 1.224.0 |
| **AI 引擎** | DeepSeek API (多代理辩论架构) |
| **Python** | 3.12+ (必须) |
| **交易对** | BTCUSDT-PERP (BTC/USDT 永续合约) |
| **执行层周期** | 30M K线 (v18.2: 15M→30M) |
| **分析间隔** | 15 分钟 (production), 30 分钟 (base) |
| **记忆系统** | `data/trading_memory.json` (最多 500 条) |

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                    执行层 (NautilusTrader)                            │
│              TradingNode + Binance Live Client                       │
└──────────────────────────────────────────────────────────────────────┘
                            ▲
                            │ (事件驱动)
┌──────────────────────────────────────────────────────────────────────┐
│                    策略层 (AITradingStrategy)                        │
│  • on_timer() 定时分析 (主触发)  • on_trade_tick() 价格监控          │
│  • on_position_opened()         • on_position_closed()               │
│  • on_order_filled()            • Telegram 双频道通知 (v14.0)        │
│  • _has_market_changed() 跳过门 • Entry Timing Agent (v23.0)         │
└──────────────────────────────────────────────────────────────────────┘
                            ▲
                    ┌───────┴────────┐
                    │                │
    ┌───────────────▼──────┐  ┌──────▼───────────────────┐
    │   技术分析层          │  │   AI 决策层               │
    │  TechnicalManager     │  │  MultiAgentAnalyzer       │
    │                      │  │                            │
    │ • SMA 5/20/50/200    │  │ Phase 0: Reflection (0~1)  │
    │ • RSI 14             │  │ Phase 1: Bull/Bear ×2 (4)  │
    │ • MACD 12/26/9       │  │ Phase 2: Judge (1)         │
    │ • Bollinger 20       │  │ Phase 2.5: Entry Timing (1)│
    │ • ADX/DI 14          │  │ Phase 3: Risk Manager (1)  │
    │ • ATR 14             │  │ = 7+1 AI calls total       │
    │ • ATR Extension Ratio│  │                            │
    │ • RSI/MACD 背离检测  │  │ 记忆系统 (500 条 FIFO)     │
    └──────────────────────┘  └────────────────────────────┘
                    │                │
    ┌───────────────┴────────────────┴────────────────────────────┐
    │                  数据获取层 (13 类数据)                        │
    │  AIDataAssembler.fetch_external_data() — SSoT (v7.0)         │
    │  • Binance Futures API (K线、订单、持仓、Ticker)              │
    │  • Binance Long/Short Ratio (情绪)                           │
    │  • Binance Derivatives (Top Traders 多空比)                   │
    │  • Binance Orderbook (订单簿深度)                             │
    │  • BinanceKlineClient (订单流 + CVD + Funding Rate)           │
    │  • Coinalyze (OI + Liquidations, 可选)                       │
    │  • DeepSeek API (AI 分析)                                    │
    │  • S/R Zone Calculator (支撑/阻力, v17.0: 1+1 简化)          │
    │  • Hold Probability Calibration (v16.0 自动校准)              │
    └────────────────────────────────────────────────────────────┘
```

---

## 3. 核心组件详解

### 3.1 入口文件 (`main_live.py`)

- 加载环境变量 (`~/.env.algvex` → `.env`)
- 应用 Binance 枚举补丁 (处理未知 filter types)
- 创建策略配置 `AITradingStrategyConfig`
- 支持命令行环境切换 (`--env production/development/backtest`)
- 初始化 `TradingNode` 并注册 Binance 工厂
- 启动事件处理循环

### 3.2 策略核心 (`strategy/` mixin 架构)

**主要职责：**
- 接收市场数据事件 (K线、Tick)
- 调用 AI 分析器生成信号 (7+1 AI calls)
- 执行订单 (LIMIT 入场 + 分步 SL/TP)
- 管理每层独立的 SL/TP (v7.2 `_layer_orders`)
- 发送 Telegram 双频道通知 (v14.0)
- 清算缓冲保护和紧急 SL 机制

**关键方法：**
| 方法 | 功能 |
|------|------|
| `on_start()` | 初始化指标、AI 客户端、Telegram、恢复 layer 状态 |
| `on_bar()` | 每根 K线更新指标，缓存 ATR/价格 |
| `on_timer()` | 定时分析主循环 (主触发器, 默认 1200s/production) |
| `on_trade_tick()` | 实时价格监控 + 1.5% 偏离触发 (v18.2) |
| `on_order_filled()` | 订单成交处理 (per-layer SL/TP 管理) |
| `on_position_opened()` | 分步提交 SL + TP (v4.13) |
| `on_position_closed()` | 交易评估 + 触发反思 + 设置 forced analysis |
| `_execute_signal()` | 执行交易信号 (LIMIT 入场, v4.17) |
| `_has_market_changed()` | Skip-gate: 价格/ATR/持仓状态变化检测 |
| `_evaluate_entry_timing()` | Entry Timing Agent (v23.0, 取代 Alignment Gate) |
| `calculate_mechanical_sltp()` | ATR 机械 SL/TP (R/R ≥ 2.0:1 构造性保证) |

**线程安全注意：**
- 使用 `_cached_current_price` 缓存价格 (Rust 不可跨线程)
- Telegram 命令处理不直接访问 `indicator_manager`
- 使用 Cython 指标 (非 Rust PyO3) 避免线程 panic

### 3.3 多代理分析器 (`agents/` mixin 架构)

实现 TradingAgents (UCLA/MIT) 框架的多代理辩论架构。每次分析产生 7+1 次 AI 调用，所有 Agent 均接收历史记忆和反思。

**决策流程 (7+1 AI calls)：**

```
on_timer (20分钟/production)
  ↓
Phase 0: Reflection (0~1 AI call, 仅平仓后首个周期)
  └─ generate_reflection(): 对上次平仓生成 LLM 深度反思 (≤150 字)
  └─ 替换模板 lesson，按 bull/bear/judge 角色结构化
  ↓
内联数据聚合 (13 类数据, AIDataAssembler SSoT)
  ↓
Phase 1: Bull/Bear 辩论 (×2 rounds = 4 AI calls, sequential)
  ├─ Round 1: Bull Analyst → Bear Analyst (互相反驳)
  └─ Round 2: Bull Analyst → Bear Analyst (深化辩论, 含 _opponent 交叉引用)
  │  • v27.0: Feature-driven structured prompt (feature_dict + REASON_TAGS)
  │  • v28.0: _scores dimensional anchoring (trend/momentum/order_flow/vol_ext/risk)
  │  • 输出: JSON {reasoning, evidence, risk_flags, conviction, summary}
  │  • v18.1: ADX>40 强趋势时角色调节为趋势跟随
  ↓
Phase 2: Judge 决策 (1 AI call)
  └─ 量化 confluence 框架 + Bull/Bear evidence + 历史记忆 + 反思
  └─ 逐层评估: trend_1d / momentum_4h / levels_30m / derivatives
  └─ 输出: JSON {confluence, decision, winning_side, confidence, decisive_reasons, ...}
  └─ aligned_layers 机械约束: ≤1 → LOW, ≤2 → cap MEDIUM
  ↓
Phase 2.5: Entry Timing Agent (1 AI call, v23.0, 仅 LONG/SHORT 时)
  └─ MTF alignment + 30M 执行层时机 + 逆势风险 + extension/volatility
  └─ 可 REJECT → HOLD，或降级 confidence (只降不升)
  └─ 取代 Alignment Gate + Entry Quality Downgrade + 30M Confidence Cap
  ↓
Phase 3: Risk Manager (1 AI call)
  └─ SL/TP 设定 + 仓位大小 (size_pct) + 风险评估
  └─ 输出: JSON {risk_appetite, position_size_pct, ...}
  └─ 仅否决权: R/R<1.5 / FR>0.1% / 流动性枯竭 → HOLD
  └─ 不重判方向 (v4.14)
  └─ v17.1: 清算缓冲 4 级评估
  ↓
calculate_mechanical_sltp() → ATR × confidence 构造性保证 R/R ≥ 2.0:1
  ↓
最终交易信号: {signal, confidence, risk_appetite, size_pct, ...}
```

**关键设计：v27.0 Feature-Driven Architecture**
- 所有 5 个 Agent 接收 feature_dict (82 个 typed features) + REASON_TAGS
- v28.0: `_scores` pre-computed dimensional assessment 注入所有 prompt (primacy anchoring)
- v28.0: `INDICATOR_KNOWLEDGE_BRIEF` 替代文本路径的 `INDICATOR_DEFINITIONS` (~500 vs ~4000 tokens)
- Judge 通过 confluence 框架做出独立决策 (aligned_layers 计数)
- 输出结构化 JSON: `{confluence, decision, winning_side, confidence, decisive_reasons, ...}`
- Text-based debate 仅作为 feature extraction 失败时的 fallback

**记忆系统 (v5.9+)：**
- 文件: `data/trading_memory.json` (FIFO 500 条)
- 所有 4 个 Agent 都接收历史记忆 (`_get_past_memories()`)
- Bull/Bear/Risk: `PAST TRADE PATTERNS` 段落
- Judge: `PAST REFLECTIONS` 段落
- v12.0: 平仓后 LLM 生成深度反思 (Phase 0)
- v18.0: 记忆评分增加 recency factor (14 天半衰期指数衰减)
- v18.0: Extended reflections 独立 JSON 存储 (`data/extended_reflections.json`)

### 3.4 技术指标管理器 (`indicators/technical_manager.py`)

使用 NautilusTrader 的 **Cython 指标**（非 Rust PyO3）：

| 指标 | 周期 | 用途 |
|------|------|------|
| SMA | 5, 20, 50, 200 | 趋势判断 (200 用于 1D 趋势层 Risk-On/Off) |
| EMA | 12, 26 | MACD 计算 |
| RSI | 14 | 超买/超卖 + 入场时机 (执行层) |
| MACD | 12/26/9 | 动量和趋势 + 背离预计算 (v19.1) |
| Bollinger | 20, 2σ | 波动率 + Squeeze 检测 |
| ADX/DI | 14 | 趋势强度 + 方向 + 强趋势判定 (ADX>40) |
| ATR | 14 | 波动率 + SL/TP 机械计算 + Extension Ratio |
| ATR Extension Ratio | (Price-SMA)/ATR | 过度延伸检测 4 级: NORMAL/EXTENDED/OVEREXTENDED/EXTREME (v19.1) |
| Volume MA | 20 | 成交量分析 |

**v19.1 预计算分析 (减少 AI 推导负担)：**
- `_detect_divergences()`: RSI/MACD 背离检测 (4H + 30M)
- `_calculate_extension_ratios()`: ATR Extension Ratio 4 级 regime
- CVD-Price 交叉检测: ACCUMULATION/DISTRIBUTION/CONFIRMED/ABSORPTION (v19.1-v19.2)

**v18.1 信号可靠性分层 (Tier 1/2/3)：**
- 技术报告按可靠性层级分组，不按时间框架分组

**重要：** 必须使用 `from nautilus_trader.indicators import ...`，不能从 `nautilus_trader.core.nautilus_pyo3` 导入。

### 3.5 三层时间框架 (MTF)

| 层级 | 时间框架 | 职责 |
|------|---------|------|
| 趋势层 | 1D | SMA_200 + MACD，Risk-On/Off 过滤 |
| 决策层 | 4H | Bull/Bear 辩论 + Judge 决策 |
| 执行层 | 30M (v18.2: 15M→30M) | RSI 入场时机 + S/R 止损止盈 |

### 3.6 13 类数据覆盖

| # | 数据 | 必需 | 来源 |
|---|------|------|------|
| 1 | technical_data (30M) | ✅ | TechnicalManager (含 ATR Extension Ratio) |
| 2 | sentiment_data | ✅ | Binance 多空比 |
| 3 | price_data | ✅ | Binance ticker |
| 4 | order_flow_report | | BinanceKlineClient (含 CVD) |
| 5 | derivatives_report (Coinalyze) | | CoinalyzeClient (OI + Liquidations) |
| 6 | binance_derivatives (Top Traders) | | BinanceDerivativesClient |
| 7 | orderbook_report | | BinanceOrderbookClient |
| 8 | mtf_decision_layer (4H) | | 技术指标 + CVD-Price 交叉 |
| 9 | mtf_trend_layer (1D) | | 技术指标 |
| 10 | current_position | | Binance |
| 11 | account_context | ✅ | Binance |
| 12 | historical_context | | 内部计算 |
| 13 | sr_zones_data | | S/R 计算器 (v17.0: 1+1 简化) |

**v7.0 SSoT**: `AIDataAssembler.fetch_external_data()` 统一外部数据获取，on_timer() 和 ai_decision.py 共用。

### 3.7 S/R 支撑阻力 (v17.0 简化)

- `calculate()` 内部仍聚类全部候选，但输出仅保留 nearest 1 support + 1 resistance
- `support_zones`/`resistance_zones` 列表最多 1 个元素
- AI report 只显示 [S1]+[R1]，方向中性描述
- S/R 仅作为 AI 上下文信息 (v11.0)，不再机械锚定 SL/TP
- v16.0: Hold Probability 自动校准 (`scripts/calibrate_hold_probability.py`)

### 3.8 Telegram 双频道集成 (v14.0)

**控制频道 (私聊)：** 运维监控 + 命令交互
**通知频道 (订阅者)：** 交易信号 + 业绩展示

| 消息类型 | 私聊 | 通知频道 | 说明 |
|---------|:----:|:-------:|------|
| 系统启动/关闭 | ✅ | ❌ | 运维信息 |
| 心跳监控 | ✅ | ❌ | 20分钟/次 |
| **开仓/平仓/加减仓** | ❌ | ✅ | 核心交易信号 |
| **日报/周报** | ❌ | ✅ | 业绩展示 |
| 错误/告警 | ✅ | ❌ | 调试信息 |
| 命令响应 | ✅ | ❌ | 交互命令 |

`broadcast=True` → 仅通知频道，`broadcast=False` → 仅私聊。每条消息只发一个地方，零重复。

**术语规范:** 使用 `side_to_cn()` 统一转换方向显示为中文 (开多/开空/平多/平空/多仓/空仓)。

**`utils/telegram_command_handler.py`：**
- 快捷菜单 (`/menu`), 查询命令 (无需 PIN), 控制命令 (需 PIN)
- `/calibrate` 手动触发 S/R 校准
- `/force_analysis` 触发即时 AI 分析
- `/modify_sl`, `/modify_tp` 手动调整止损止盈

### 3.9 Binance 补丁 (`patches/binance_enums.py`)

解决 NautilusTrader 与 Binance 的兼容性问题：

- 动态处理未知枚举值 (如 `POSITION_RISK_CONTROL`)
- 使用 `_missing_` 钩子创建伪成员
- 必须在导入 NautilusTrader 前应用

---

## 4. 交易逻辑流程

### 4.1 on_timer() 主循环流程

**主触发器**: `on_timer()` (默认 1200 秒/production, 1800 秒/base)，不是 `on_bar()`。

```
on_timer() 被触发 (每 timer_interval_sec 秒)
│
├── Gate 0: 暂停检查 (is_trading_paused?)
├── Gate 1: 止损冷静期检查 (cooldown 类型: noise/reversal/volatility)
├── Gate 2: 紧急复查 (_needs_emergency_review → _submit_emergency_sl)
│
├── Gate 3: Skip-gate — _has_market_changed()
│   ├── Check 1: 价格变动 > 0.2%?
│   ├── Check 2: ATR regime shift > 15%?
│   ├── Check 3: 持仓状态变化?
│   └── Check 4: Post-close forced analysis (v18.3, 2 轮额外分析)
│   └── 未达标 → 跳过本周期 (consecutive skips 计数, 达上限强制分析)
│
├── Phase 0: Reflection (0~1 AI call, 仅平仓后首个周期)
│   └── generate_reflection() → 更新 trading_memory.json
│
├── 数据聚合: AIDataAssembler.fetch_external_data() (13 类数据)
│
├── Phase 1-3: MultiAgentAnalyzer.analyze() (7 AI calls, v23.0)
│   ├── Phase 1: Bull/Bear 辩论 (×2 rounds = 4 calls)
│   ├── Phase 2: Judge 决策 (1 call)
│   ├── Phase 2.5: Entry Timing Agent (1 call, 仅 LONG/SHORT)
│   └── Phase 3: Risk Manager (1 call)
│
├── Signal 验证 (7 gates + 2 stateful):
│   ├── [S1] Signal fingerprint dedup (同信号不重复执行, CLOSE/REDUCE 豁免)
│   ├── [1] Risk Controller 熔断 (circuit breaker + position multiplier)
│   ├── [2] Entry Timing Agent 结果读取 (REJECT → HOLD, confidence 降级)
│   ├── [3] Signal age check (>600s → HOLD)
│   ├── [4] Legacy normalization (BUY→LONG, SELL→SHORT)
│   ├── [S2] FR consecutive block exhaustion (≥3 次同方向 → HOLD)
│   ├── [5] 最低信心阈值 (MEDIUM+)
│   ├── [6] 清算缓冲检查 (buffer < 5% → 阻止加仓)
│   └── [7] FR entry check (paying FR > 0.09% → 阻止入场)
│
├── 订单执行:
│   ├── calculate_mechanical_sltp() → ATR-based SL/TP
│   │   └── R/R ≥ 2.0:1 构造性保证 (逆势 ≥ 1.95:1)
│   ├── Entry: LIMIT @ validated entry_price (v4.17)
│   ├── on_position_opened() → 分步提交 SL + TP (v4.13)
│   │   ├── SL: STOP_MARKET
│   │   └── TP: LIMIT_IF_TOUCHED (position-linked, v6.6)
│   └── _create_layer() → per-layer 独立 SL/TP (v7.2)
│
└── 通知: Telegram 双频道推送
```

**补充触发器:**
- `on_trade_tick()`: 实时价格监控，1.5% 偏离触发提前 AI 分析 (v18.2 Price Surge Trigger)
- `on_position_closed()`: 设置 `_force_analysis_cycles_remaining = 2` 强制 2 轮额外分析 (v18.3)

### 4.2 仓位计算 (ai_controlled, v4.8+)

当前默认方法: `position_sizing.method = "ai_controlled"`

```python
# Step 1: 最大仓位上限
max_usdt = equity × max_position_ratio × leverage
# 例: $1000 × 0.12 × 10 = $1200 最大仓位

# Step 2: AI 建议百分比 → confidence mapping
size_pct = signal_data['position_size_pct']  # Risk Manager 输出
# 或 fallback: confidence_mapping[confidence]
#   HIGH: 80%, MEDIUM: 50%

# Step 3: Risk appetite 缩放 (仅影响仓位, 不影响 SL/TP)
appetite_scale = {'AGGRESSIVE': 1.0, 'NORMAL': 0.8, 'CONSERVATIVE': 0.5}

# Step 4: 计算最终仓位
position_usdt = max_usdt × (size_pct / 100) × appetite_scale[risk_appetite]

# Step 5: 硬性钳制 (v7.1)
final_usdt = min(position_usdt, max_usdt)  # 永不超过上限
final_usdt = max(final_usdt, 100)           # Binance 最低 $100

# Step 6: 单笔风险钳制 (2% equity)
# position × SL_distance / entry ≤ 2% equity

# Step 7: Risk multiplier (RiskController 电路保护)
final_usdt *= risk_multiplier  # 0.0~1.0

btc_quantity = final_usdt / current_price
```

### 4.3 止损止盈计算 (ATR 机械公式, v11.0+)

使用 `calculate_mechanical_sltp()` 纯机械 ATR-based 计算，基于 Lopez de Prado (2018) Triple Barrier Method。

```python
# Step 1: SL 距离 = ATR × confidence multiplier
sl_multipliers = {'HIGH': 2.0, 'MEDIUM': 2.5}
sl_distance = ATR × sl_multiplier[confidence]

# Step 2: Floor 保护 (噪音)
sl_distance = max(sl_distance, ATR × sl_atr_multiplier_floor)  # floor=1.5

# Step 3: TP 距离 = SL 距离 × R/R target
rr_targets = {'HIGH': 2.5, 'MEDIUM': 2.0}
tp_distance = sl_distance × rr_target[confidence]

# Step 4: 逆势 R/R 提升 (v5.12)
if is_counter_trend:
    tp_distance = sl_distance × (rr_target × counter_trend_rr_multiplier)
    # 例: MEDIUM → 2.0 × 1.3 = 2.6:1

# Step 5: 计算价格
# LONG: SL = entry - sl_distance, TP = entry + tp_distance
# SHORT: SL = entry + sl_distance, TP = entry - tp_distance
```

**关键设计:**
- R/R ≥ 2.0:1 由公式**构造性保证** (不依赖 prompt)
- `risk_appetite` 不影响 SL/TP，仅影响仓位大小 (正交设计)
- 逆势交易自动提升 R/R 门槛: 1.5 × 1.3 = 1.95:1 (v5.12)
- ATR Extension Ratio 不影响 SL/TP，只影响 AI 仓位/入场质量评估 (v19.1)

### 4.4 Per-Layer SL/TP 管理 (v7.2)

```python
# 每次入场创建独立层级
_layer_orders = {
    "layer_001": {
        "entry_order_id": "O-001",
        "sl_order_id": "O-002",
        "tp_order_id": "O-003",
        "quantity": 0.01,
        "entry_price": 95000.0,
        ...
    },
    "layer_002": {...}  # 加仓创建新层，不影响已有层
}
```

- 加仓创建新层，每层独立 SL/TP
- LIFO 减仓 (最后加仓的先平)
- `_order_to_layer` 反查: on_order_filled 时只取消同层对手单
- `data/layer_orders.json` 持久化，重启恢复
- v7.3: 重启后交叉验证每层 `sl_order_id` 是否在交易所存活

### 4.5 紧急保护机制

| 机制 | 触发条件 | 行为 |
|------|---------|------|
| Emergency SL (v6.1) | SL 提交失败 | `_emergency_market_close()` 市价 reduce_only |
| Emergency 重试 (v18.0) | Emergency SL 失败 | 注册 30s one-shot timer 重试 |
| Emergency SL 升级 (v7.1) | 3 次重试失败 | `_needs_emergency_review` 标记，下个 on_timer 重新保护 |
| Telegram 平仓失败 (v13.1) | 取消 SL 后平仓失败 | 立即 `_submit_emergency_sl()` 防裸仓 |
| Ghost position (v18.2) | 3 次 -2022 rejection | 强制 `_clear_position_state()` |
| `on_stop()` (v7.3) | 策略停止 | 保留所有 SL/TP 订单，不 cancel_all |

### 4.6 交易评估框架

每笔交易平仓后自动评估 (`trading_logic.py:evaluate_trade()`):

| 等级 | 盈利交易 | 亏损交易 |
|------|---------|---------|
| A+ | R/R ≥ 2.5 | — |
| A | R/R ≥ 1.5 | — |
| B | R/R ≥ 1.0 | — |
| C | R/R < 1.0 (小盈利) | — |
| D | — | 亏损 ≤ 计划 SL × 1.2 (有纪律) |
| F | — | 亏损 > 计划 SL × 1.2 (失控) |

---

## 5. 配置管理

### 5.1 分层架构

```
Layer 1: 代码常量 (业务规则, 不可配置)
Layer 2: configs/base.yaml (所有业务参数)
Layer 3: configs/{env}.yaml (环境覆盖: production/development/backtest)
Layer 4: ~/.env.algvex (仅 API keys 等敏感信息)
```

### 5.2 环境变量 (`~/.env.algvex`)

```bash
# 必填
BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
DEEPSEEK_API_KEY=xxx

# 可选 (Telegram 控制机器人)
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx

# 可选 (v14.0 通知频道机器人, 独立 bot)
TELEGRAM_NOTIFICATION_BOT_TOKEN=xxx
TELEGRAM_NOTIFICATION_CHAT_ID=xxx

# 可选 (Coinalyze, 无则自动降级)
COINALYZE_API_KEY=xxx

# ❌ 禁止放业务参数 (EQUITY, LEVERAGE 等应在 configs/*.yaml)
```

### 5.3 策略配置 (`configs/base.yaml`)

关键配置项：

| 配置 | 默认值 (base) | production 覆盖 | 说明 |
|------|--------------|-----------------|------|
| `timing.timer_interval_sec` | 1800 | 1200 | 分析间隔 (秒) |
| `risk.min_confidence_to_trade` | MEDIUM | — | 最低交易信心 |
| `capital.equity` | 1000 | — | 备用资金 (实际使用真实余额) |
| `capital.leverage` | 10 | — | 杠杆倍数 |
| `position.max_position_ratio` | 0.12 | — | 最大仓位比例 |
| `position_sizing.method` | ai_controlled | — | 仓位计算方法 |
| `trading_logic.min_rr_ratio` | 1.5 | — | R/R 硬性门槛 (顺势) |
| `trading_logic.counter_trend_rr_multiplier` | 1.3 | — | 逆势 R/R 倍数 (×1.3) |
| `ai.deepseek.model` | deepseek-chat | — | AI 模型 |
| `ai.deepseek.temperature` | 0.3 | — | 温度参数 |
| `ai.multi_agent.debate_rounds` | 2 | — | 辩论轮数 |
| `trading.timeframe` | 30m | — | 执行层 K线周期 |

**代码常量 (不经 YAML):**
- 反思参数: max_chars=150, temperature=0.3
- Extension Ratio 阈值: 2/3/5 ATR (行业共识)
- 校准参数: LOOKBACK_BARS, FORWARD_SCAN_BARS
- 背离检测窗口: window=2, 偏差 ≤2 bar

### 5.4 命令行环境切换

```bash
python3 main_live.py --env production    # 生产 (20分钟, INFO)
python3 main_live.py --env development   # 开发 (1分钟, DEBUG)
python3 main_live.py --env backtest      # 回测 (无Telegram)
python3 main_live.py --env development --dry-run  # 验证配置
```

---

## 6. 诊断工具

### 6.1 全面诊断 (`scripts/diagnose.py`)

```bash
python3 scripts/diagnose.py              # 完整检查
python3 scripts/diagnose.py --quick      # 跳过网络测试
python3 scripts/diagnose.py --update     # 更新代码后检查
python3 scripts/diagnose.py --restart    # 检查后重启服务
```

**检查项目：**
1. 系统环境 (Python 版本、虚拟环境)
2. 依赖包 (NautilusTrader 版本)
3. 文件完整性
4. 环境变量
5. 策略配置
6. 止损逻辑验证
7. Binance 补丁
8. 网络连接
9. API 认证
10. Systemd 服务状态
11. 进程检查
12. Git 状态
13. 模块导入测试

### 6.2 实时诊断 (`scripts/diagnose_realtime.py`)

调用真实 API 验证完整数据流：
- 获取真实 K线数据
- 调用 DeepSeek AI
- 生成完整信号
- 不模拟任何数据

### 6.3 回归检测 (`scripts/smart_commit_analyzer.py`)

代码修改后必须运行，验证架构合规性。

### 6.4 ATR Extension Ratio 验证 (`scripts/verify_extension_ratio.py`)

v19.1: 4-phase 47 checks，验证 Extension Ratio 集成完整性。

### 6.5 S/R Hold Probability 校准 (`scripts/calibrate_hold_probability.py`)

v16.0: 拉 30 天 K 线，滑窗计算 zones + 前向扫描 hold/break，统计因子写入 `data/calibration/latest.json`。

```bash
python3 scripts/calibrate_hold_probability.py                  # 交互式
python3 scripts/calibrate_hold_probability.py --auto-calibrate # Cron 模式
python3 scripts/calibrate_hold_probability.py --dry-run        # 预览不保存
```

---

## 7. 部署运维

### 7.1 服务管理

```bash
# 启动/停止/重启 (交易机器人)
sudo systemctl start|stop|restart nautilus-trader

# 查看日志
sudo journalctl -u nautilus-trader -f --no-hostname

# 查看状态
sudo systemctl status nautilus-trader

# Web 服务 (前端 + 后端 + Caddy)
sudo systemctl status algvex-backend algvex-frontend caddy
```

### 7.2 一键部署

```bash
# 完全重装
curl -fsSL https://raw.githubusercontent.com/FelixWayne0318/AlgVex/main/reinstall.sh | bash

# 普通升级
cd /home/linuxuser/nautilus_AlgVex && git pull origin main && chmod +x setup.sh && ./setup.sh
```

### 7.3 代码同步

```bash
cd /home/linuxuser/nautilus_AlgVex && sudo systemctl stop nautilus-trader && \
  git fetch origin main && git reset --hard origin/main && \
  find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null && \
  echo "=== 最近提交 ===" && git log --oneline -5 && \
  source venv/bin/activate && python3 scripts/diagnose_realtime.py
```

### 7.4 Web 部署

```bash
# 一键重新部署 (推荐)
cd /home/linuxuser/nautilus_AlgVex && bash web/deploy/redeploy.sh

# 指定分支
cd /home/linuxuser/nautilus_AlgVex && bash web/deploy/redeploy.sh --branch claude/xxx
```

---

## 8. 已修复问题汇总

| 问题 | 修复 | 版本 |
|------|------|------|
| 止损价格在错误一侧 | 添加验证逻辑 | 7f940fb |
| CryptoOracle API 失效 | 替换为 Binance L/S Ratio | 07cd27f |
| Binance POSITION_RISK_CONTROL | 枚举 `_missing_` 钩子 | 1ed1357 |
| 非 ASCII 符号崩溃 | 升级 NautilusTrader 1.221.0 | — |
| Rust 指标线程 panic | 改用 Cython 指标 | — |
| Telegram webhook 冲突 | 预删除 webhook | — |
| 循环导入错误 | 移除 `__init__.py` 自动导入 | — |
| net_sentiment KeyError | 默认情绪数据添加必需字段 | — |
| 时间周期解析错误 | 检查顺序调整 | — |
| 反转竞态条件 | 两阶段提交 + `_pending_reversal` | v3.18 |
| Bracket 失败风险 | 不回退无保护单，CRITICAL 告警 | v3.18 |
| SL 提交失败裸仓 | Emergency SL 市价兜底 | v6.1 |
| TP 非 position-linked | `limit_if_touched()` → TAKE_PROFIT (Algo API) | v6.6 |
| 加仓影响已有层 SL/TP | Per-layer 独立 SL/TP (`_layer_orders`) | v7.2 |
| 重启恢复不验证交易所 | Tier 2 交叉验证 `sl_order_id` 存活 | v7.3 |
| 仓位上限溢出 | `min(position_usdt, max_usdt)` 钳制 | v7.1 |
| Telegram 平仓失败裸仓 | 取消 SL 后平仓失败 → Emergency SL | v13.1 |
| Ghost position loop | 3 次 -2022 rejection 后强制清除 | v18.2 |
| 平仓后长时间不分析 | `_force_analysis_cycles_remaining = 2` | v18.3 |
| Extension ratio 强趋势误报 | ADX>40 时 OVEREXTENDED 降级为 NOTE | v19.1.1 |
| 30M CVD-Price 时间错配 | 5-bar price change 匹配 CVD 5-bar 窗口 | v19.2 |

---

## 9. 开发注意事项

### 9.1 代码修改规范

1. **必须调研**：官方文档 → 社区 Issues → 原始仓库
2. **修改后必须运行**: `python3 scripts/smart_commit_analyzer.py`
3. **禁止**：
   - 凭猜测修改代码
   - 忽略原始仓库实现
   - 不了解框架线程模型就修改异步代码

### 9.2 常见错误避免

- ❌ `python` → ✅ `python3`
- ❌ `main.py` → ✅ `main_live.py`
- ❌ 从 `nautilus_pyo3` 导入指标 → ✅ 从 `nautilus_trader.indicators` 导入
- ❌ 后台线程访问 `indicator_manager` → ✅ 使用 `_cached_current_price`
- ❌ 直接 `data['key']` → ✅ `data.get('key', default)`
- ❌ 执行层用 15M → ✅ 30M (v18.2)
- ❌ SL/TP 百分比计算 → ✅ ATR 机械公式 (`calculate_mechanical_sltp()`)
- ❌ `order_factory.bracket()` → ✅ 分步提交 (v4.13)
- ❌ TP 用 `order_factory.limit()` → ✅ `limit_if_touched()` (v6.6)
- ❌ Risk Manager 重判方向 → ✅ 只设 SL/TP + 仓位 (v4.14)
- ❌ 加仓影响已有层 → ✅ Per-layer 独立 SL/TP (v7.2)
- ❌ Telegram 显示 LONG/SHORT → ✅ `side_to_cn()` (开多/开空/多仓/空仓)
- ❌ 反思参数放 base.yaml → ✅ 代码常量
- ❌ Extension Ratio 影响 SL/TP → ✅ 纯 RISK 信号，只影响 AI 仓位评估
- ❌ 服务器命令不带 cd → ✅ 始终先 `cd /home/linuxuser/nautilus_AlgVex`

---

## 10. 文件结构

```
/home/user/AlgVex/
├── main_live.py              # 入口文件
├── setup.sh / reinstall.sh   # 部署脚本
├── requirements.txt
├── nautilus-trader.service    # systemd 服务
│
├── strategy/                 # 策略模块 (mixin 架构)
│   ├── ai_strategy.py        # 主策略入口 + 核心循环
│   ├── event_handlers.py     # 事件回调 mixin (on_order_*, on_position_*)
│   ├── order_execution.py    # 订单执行 mixin (_execute_trade, _submit_*)
│   ├── position_manager.py   # 仓位管理 mixin (层级订单, 加仓/减仓)
│   ├── safety_manager.py     # 安全管理 mixin (emergency SL, 熔断)
│   ├── telegram_commands.py  # Telegram 命令 mixin (/close, /modify_sl 等)
│   └── trading_logic.py      # 交易逻辑 + evaluate_trade() + calculate_mechanical_sltp()
│
├── agents/                   # 多代理系统 (mixin 架构)
│   ├── multi_agent_analyzer.py # Bull/Bear/Judge/Risk 核心 + AI 调用
│   ├── prompt_constants.py   # 指标定义 + 信心矩阵
│   ├── report_formatter.py   # 报告格式化 mixin
│   └── memory_manager.py     # 记忆系统 mixin + 反思
│
├── indicators/               # 技术指标
│   └── technical_manager.py  # Cython 指标 + ATR Extension Ratio + 背离检测
│
├── utils/                    # 工具模块
│   ├── config_manager.py     # 统一配置管理器 (分层架构)
│   ├── ai_data_assembler.py  # 13 类数据聚合 (SSoT, v7.0)
│   ├── binance_kline_client.py       # K线 + 订单流 + CVD + Funding Rate
│   ├── binance_derivatives_client.py # Top Traders 多空比
│   ├── binance_orderbook_client.py   # 订单簿深度
│   ├── coinalyze_client.py   # OI + Liquidations (可选)
│   ├── sentiment_client.py   # Binance 多空比
│   ├── sr_zone_calculator.py # S/R 区域计算 (v17.0: 1+1 简化)
│   ├── telegram_bot.py       # Telegram 双频道通知 (v14.0)
│   ├── telegram_command_handler.py # Telegram 命令 (v3.0)
│   ├── binance_account.py    # 账户工具
│   ├── bar_persistence.py    # K线持久化
│   └── risk_controller.py    # 风险控制 (电路保护)
│
├── configs/                  # 配置 (分层架构)
│   ├── base.yaml             # 基础配置 (所有参数, timer 1800s)
│   ├── production.yaml       # 生产环境 (timer 1200s)
│   ├── development.yaml      # 开发环境 (timer 60s)
│   └── backtest.yaml         # 回测环境
│
├── scripts/                  # 脚本工具
│   ├── diagnostics/          # 诊断模块
│   ├── diagnose.py           # 全面诊断
│   ├── diagnose_realtime.py  # 实时 API 诊断
│   ├── smart_commit_analyzer.py # 回归检测
│   ├── calibrate_hold_probability.py # S/R 校准 (v16.0)
│   ├── verify_extension_ratio.py # Extension Ratio 验证 (v19.1)
│   └── ...
│
├── data/                     # 数据目录
│   ├── trading_memory.json   # 交易记忆 (FIFO 500 条)
│   ├── layer_orders.json     # Per-layer SL/TP 持久化 (v7.2)
│   ├── extended_reflections.json # 扩展反思 (v18.0)
│   ├── calibration/          # S/R 校准数据 (v16.0)
│   │   ├── latest.json       # 当前校准因子
│   │   └── history/          # 历史校准存档
│   └── snapshots/
│
├── web/                      # Web 管理界面
│   ├── backend/              # FastAPI
│   ├── frontend/             # Next.js
│   └── deploy/               # 部署脚本 (redeploy.sh, setup.sh)
│
├── patches/                  # 兼容性补丁
│   ├── binance_enums.py      # 未知枚举处理
│   └── binance_positions.py  # 持仓处理
│
├── tests/                    # 测试
├── tools/                    # 运维工具
├── docs/                     # 文档
└── .github/workflows/        # CI/CD
```

---

*文档版本: 2026-03-01*
*适用于: AlgVex v23.0+ NautilusTrader 1.224.0*
