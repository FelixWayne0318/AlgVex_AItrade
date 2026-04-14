# AlgVex - NautilusTrader DeepSeek 交易机器人

## 项目概述
基于 NautilusTrader 框架的 AI 驱动加密货币交易系统，使用 DeepSeek AI 进行多代理辩论式信号生成。

### 代码库规模

| 模块 | 行数 | 文件数 | 核心职责 |
|------|------|--------|---------|
| strategy/ | 15,411 | 8 | 策略主体 (mixin 架构) |
| agents/ | 15,500 | 8 | 多代理辩论系统 |
| utils/ | 13,274 | 25 | 工具/客户端/数据聚合/质量分析 |
| scripts/ | 48,217 | 44 | 诊断/回归/校准/回测/压力测试 |
| indicators/ | 1,420 | 3 | 技术指标计算 |
| tests/ | 6,642 | 22 | 单元/集成/回归测试 |
| web/backend/ | 5,554 | 23 | FastAPI Web 管理 |
| patches/ | 481 | 3 | NT 兼容性补丁 |
| **总计 Python** | **~106,482** | **137** | |

## 🌐 输出语言规范 (Output Language)

**默认**: 中英文混合输出。中文为主体语言，技术术语、代码相关内容保留英文。

**适用范围**: 本规范适用于**所有**面向用户的输出，包括但不限于：
- Claude 对话回复
- Telegram 消息 (交易信号、心跳、诊断摘要、命令响应等)
- Web 界面文本
- 脚本终端输出 (诊断工具、校准工具等)
- 日报/周报

| 场景 | 语言 | 示例 |
|------|------|------|
| 日常对话、解释、总结 | 中文 | "这个 bug 的根因是..." |
| 技术术语 | 英文原文 | R/R ratio, SL/TP, WebSocket, JWT, CRUD |
| 代码标识符 | 英文原文 | `calculate_mechanical_sltp()`, `on_timer` |
| 文件名/路径 | 英文原文 | `strategy/ai_strategy.py` |
| 命令行指令 | 英文原文 | `git pull origin main` |
| 代码注释 | 英文 | 代码中的注释保持英文 |
| Commit message | 英文 | Git 提交信息用英文 |
| CLAUDE.md 文档 | 中英混合 | 同本文档风格 |
| Telegram 消息标签 | 中文+英文 | "信号: 观望 (HOLD)", "检查: 110/110 通过" |
| Telegram 方向显示 | 中文 (via `side_to_cn()`) | 开多/开空/平多/平空/多仓/空仓 |
| 诊断摘要 | 中英混合 | "✅ 实时诊断 Realtime Diagnosis" |

## ⚠️ 关键信息

| 项目 | 值 |
|------|-----|
| **入口文件** | `main_live.py` (不是 main.py!) |
| **服务器 IP** | 139.180.157.152 |
| **用户名** | linuxuser |
| **安装路径** | /home/linuxuser/nautilus_AlgVex |
| **服务名** | nautilus-trader |
| **分支** | main |
| **Python** | 3.12+ (必须) |
| **NautilusTrader** | 1.224.0 |
| **配置文件** | ~/.env.algvex (永久存储) |
| **记忆文件** | data/trading_memory.json |

## 🪒 奥卡姆剃刀原则 (Occam's Razor)

**核心**: 如无必要，勿增实体。代码库只保留一套当前生效的系统，不保留"万一以后用到"的废弃代码。

| 规则 | 说明 |
|------|------|
| **一套系统** | 每个功能只有一种实现路径。不保留旧版 fallback、废弃分支、"备用方案" |
| **删除 > 注释** | 废弃代码直接删除，不注释保留。Git 历史可追溯 |
| **配置最小化** | 不保留 `enabled: false` 的废弃功能配置块。当前不用 = 删除 |
| **文档跟随代码** | 描述已删除功能的文档同步删除。设计文档在实现完成后归档或删除 |
| **无预防性抽象** | 不为假设的未来需求创建接口/抽象。三行重复代码优于一个过早抽象 |
| **单一真相源** | 同一逻辑不在多处重复。如需共享，提取为函数；否则只保留一处 |

**检查清单** (每次修改后自问):
1. 这段代码当前是否被生产路径调用？否 → 删除
2. 这个配置项当前是否影响系统行为？否 → 删除
3. 这个文档描述的是当前系统还是历史系统？历史 → 删除
4. 这个 fallback 路径在正常运行中是否可能触发？否 → 删除

## 🚫 零截断原则 (Zero Truncation Policy) — v30.2 绝对零截断

**核心**: 系统中**任何环节**都**不得截断**任何文本数据。包括 AI 输出、Agent 间传递、Telegram 消息、Web API 返回值、日志、诊断报告、记忆系统等**所有**环节，**无例外**。

**适用范围**: 全系统。数据层、显示层、传输层一律不截断。

### 规则

| 规则 | 说明 |
|------|------|
| **绝对禁止截断** | 任何 `[:N]` 字符串切片、`text[:limit]`、`.truncate()` 等截断行为一律禁止。不区分"数据层"和"显示层"——所有层都不截断 |
| **AI 输出 `max_length` 为安全网** | `_validate_agent_output()` 的 `max_length` (1500/800) 仅防御 AI 异常输出，正常情况下不触发。超长时仍保存 `_raw_{key}` 原始版本 |
| **Auditor 使用原始版本** | `AIQualityAuditor` 的 citation/value/zone 检查必须优先使用 `_raw_*` 字段 |
| **下游 Agent 使用原始版本** | Judge 接收 `_raw_summary`，Entry Timing / Risk Manager 接收 `_raw_rationale`。Agent 间传递永不截断 |
| **Telegram 超长消息自动分片** | `_split_message()` 在 4096 字符硬限制处自动按换行符拆分为多条消息发送，**不丢弃**任何内容 |
| **Web API 返回完整数据** | 前端自行处理显示长度，后端不截断任何字段 |
| **禁止新增任何截断** | 代码审查中发现 `[:N]` 切片必须说明理由。除非是数组索引 (`list[:5]` 取前 5 条记录) 或协议硬限制 (Telegram 4096)，否则拒绝合并 |
| **记忆 prompt 注入** | `_MEMORY_PROMPT_MAX_CHARS = 2000`，覆盖典型 5 胜 + 5 负 + 统计 ≈ 2000-3000 字符。Token 充足，不压缩 |

### 当前数据链路 (v30.2)

```
AI 原始输出 (无限制)
  ↓
_validate_agent_output()
  ├─ reasoning: max_length=1500 (安全网, _raw_reasoning 保全)
  ├─ summary:   max_length=800  (安全网, _raw_summary 保全)
  ├─ rationale: max_length=800  (安全网, _raw_rationale 保全)
  └─ reason:    max_length=800  (安全网, _raw_reason 保全)
  ↓
下游 Agent 传递 (使用 _raw_* 完整版本)
  ├─ Judge ← bull/bear _raw_summary
  ├─ Entry Timing ← judge _raw_rationale
  └─ Risk Manager ← judge _raw_rationale
  ↓
AIQualityAuditor (使用 _raw_* 版本审计)
  ↓
Telegram → _split_message() 自动分片 (零丢弃)
Web API → 返回完整数据 (前端自行处理显示)
```

### 检查清单 (所有代码修改必查)

1. 是否引入了任何 `[:N]` 字符串切片？→ 除非是数组索引或协议硬限制，否则禁止
2. Telegram 消息是否依赖 `_split_message()` 而非手动截断？
3. Agent 间数据传递是否使用 `_raw_*` 版本？
4. Web API 是否返回完整字段而非截断 snippet？

## 🚨 代码修改规范 (必读)

在修改任何代码之前，**必须**按以下顺序调研：

1. **官方文档** - NautilusTrader、python-telegram-bot 等框架的官方文档
2. **社区/GitHub Issues** - 查看是否有相关问题和解决方案
3. **原始仓库** - 对比 [Patrick-code-Bot/nautilus_AItrader](https://github.com/Patrick-code-Bot/nautilus_AItrader) 的实现
4. **提出方案** - 基于以上调研，结合当前系统问题，提出合理修改方案

**禁止**：
- ❌ 凭猜测直接修改代码
- ❌ 未经调研就"优化"或"改进"代码
- ❌ 忽略原始仓库的已验证实现
- ❌ 不了解框架线程模型就修改异步/多线程代码

**修改后必须运行**：
```bash
python3 scripts/smart_commit_analyzer.py
# 预期: ✅ 所有规则验证通过

python3 scripts/check_logic_sync.py
# 预期: ✅ All logic clones in sync
```

## 🔗 SSoT 依赖表 (Single Source of Truth)

修改下列 SSoT 文件时，**必须**检查所有依赖方是否需要同步更新。`check_logic_sync.py` 会自动验证，但仍需人工确认语义一致性。

### 共享逻辑模块: `utils/shared_logic.py`

| 函数/常量 | 用途 | 导入方 |
|-----------|------|--------|
| `calculate_cvd_trend()` | CVD 趋势分类 | `utils/order_flow_processor.py`, `scripts/verify_indicators.py`, `scripts/validate_data_pipeline.py` |
| `classify_extension_regime()` | ATR Extension 级别分类 | `indicators/technical_manager.py`, `scripts/verify_extension_ratio.py` |
| `classify_volatility_regime()` | ATR Volatility Regime 分类 | `indicators/technical_manager.py`, `scripts/diagnostics/math_verification.py` |
| `VOLATILITY_REGIME_THRESHOLDS` | 30/70/90 百分位阈值常量 | 同上 |
| `EXTENSION_THRESHOLDS` | 2.0/3.0/5.0 阈值常量 | 同上 |
| `CVD_TREND_*` 常量 | CVD 计算参数 | 同上 |

### 其他 SSoT 文件及其依赖方

| SSoT 文件 | 关键逻辑 | 依赖方 (改源 → 必须检查) |
|-----------|---------|--------------------------|
| `strategy/trading_logic.py` | `calculate_mechanical_sltp()` | `utils/backtest_math.py` (standalone mirror), `scripts/backtest_high_signals.py` |
| `strategy/trading_logic.py` | `evaluate_trade()` (grade A+~F) | `web/backend/services/trade_evaluation_service.py` |
| `utils/backtest_math.py` | ATR Wilder's + SL/TP + SMA/BB | `scripts/backtest_high_signals.py`, `scripts/backtest_sr_zones.py`, `scripts/calibrate_hold_probability.py`, `scripts/validate_production_sr.py`, `scripts/verify_indicators.py` |
| `utils/telegram_bot.py` | `side_to_cn()` | `telegram_command_handler.py` (×2 inline), strategy mixin files: `telegram_commands.py`, `position_manager.py`, `safety_manager.py` |
| `strategy/ai_strategy.py` + 5 mixin files | `_layer_orders` / `_next_layer_idx` | 7 处 `.clear()` 必须伴随 `_next_layer_idx = 0` (paired 检查覆盖全部 4 个策略文件) |
| `indicators/technical_manager.py` | SMA/EMA/RSI/ATR 计算 | `scripts/verify_indicators.py` (reference impl), `utils/backtest_math.py` (standalone ATR) |
| `agents/prompt_constants.py` | `INDICATOR_DEFINITIONS` (v4.0) | Text fallback 路径: Bull/Bear/Judge/Entry Timing/Risk 全部 5 个 Agent, `docs/INDICATOR_CONFIDENCE_MATRIX.md` |
| `agents/prompt_constants.py` | `SIGNAL_CONFIDENCE_MATRIX` (v1.2) | Text fallback 路径: Judge + Entry Timing + Risk Manager prompt (3 个 Agent), `docs/INDICATOR_CONFIDENCE_MATRIX.md` |
| `agents/prompt_constants.py` | `INDICATOR_KNOWLEDGE_BRIEF` (v28.0) | Feature-driven 路径: 全部 5 个 Agent 的 system prompt (~500 tokens 浓缩版) |
| `utils/quality_analysis.py` | 10 个 Layer 3 分析函数 (v35.0) | `scripts/analyze_quality_correlation.py` (调用方), `web/backend/services/quality_analysis_service.py`, `utils/telegram_bot.py` (`/layer3` 命令), `strategy/ai_strategy.py` (心跳 Layer 3 指标) |

### 自动检测工具

```bash
# 逻辑同步检查 (修改 SSoT 文件后必须运行)
python3 scripts/check_logic_sync.py          # 14 项检查
python3 scripts/check_logic_sync.py --verbose # 显示所有通过项

# Hook 自动警告 (已配置)
# .claude/hooks/warn-ssot-edit.sh — 编辑 SSoT 文件时自动提醒
```

### 新增逻辑副本检查清单

如果你发现一段逻辑需要在多处使用：
1. **优先**: 提取到 `utils/shared_logic.py`，其他位置 import
2. **次选**: 如果不能 import (如纯 Python 脚本)，在 `check_logic_sync.py` 的 `SYNC_REGISTRY` 中注册
3. **禁止**: 直接 copy-paste 且不注册同步检查

## 🏗️ 策略 Mixin 架构

`AITradingStrategy(Strategy)` 继承 NautilusTrader `Strategy`，通过 5 个 Mixin 组织代码：

```python
AITradingStrategy(Strategy)
    ├─ EventHandlersMixin      # on_order_filled/rejected/canceled, on_position_opened/closed/changed
    ├─ OrderExecutionMixin     # _execute_trade, _open_new_position, _submit_bracket_order, trailing stops
    ├─ PositionManagerMixin    # _create_layer, time_barrier, cooldown, reflection, LIFO reduction
    ├─ SafetyManagerMixin      # _submit_emergency_sl, _emergency_market_close, _tier2_recovery
    └─ TelegramCommandsMixin   # /status, /close, /modify_sl 等 30+ 命令
```

### 核心生命周期

| 方法 | 触发 | 职责 |
|------|------|------|
| `on_start()` | 策略启动 | 恢复仓位状态、Tier 2 recovery、backfill trailing |
| `on_timer()` | 每 20 分钟 | 主决策循环 (数据聚合 → AI 分析 → 执行) |
| `on_bar()` | 每 Bar 完成 | 路由到 MTF manager (1D/4H/30M) |
| `on_trade_tick()` | 每笔成交 | 实时价格监控 + 1.5% surge trigger |
| `on_position_closed()` | 仓位关闭 | 评估 (grade)、记忆、反思、强制分析 |
| `on_stop()` | 策略停止 | 保留 SL/TP (不 cancel_all_orders) |

### 层级订单系统 (v7.2)

```
_layer_orders: Dict[str, Dict]    # layer_id → {entry_price, sl_price, tp_price, quantity, sl_order_id, tp_order_id, ...}
_order_to_layer: Dict[str, str]   # order_id → layer_id (反查)
```

- 每层独立 SL/TP，加仓不影响已有层
- LIFO 减仓 (最新层先平)
- `data/layer_orders.json` 持久化重启恢复
- Tier 2 startup: 交叉验证每层 SL 是否在交易所存活

## 🤖 TradingAgents 多代理架构

基于 [TradingAgents](https://github.com/TauricResearch/TradingAgents) (UCLA/MIT) 框架的多代理辩论架构。

### 决策流程 (5~7+1 次 AI 调用)

```
on_timer (20分钟)
  ↓
Phase 0: Reflection (0~1 AI call, 仅平仓后首个周期)
  └─ 对上次平仓生成 LLM 深度反思，替换模板 lesson
  ↓
内联数据聚合 (13 类数据)
  ↓
Phase 1: Bull/Bear 辩论 (×2 rounds = 4 AI calls)
  ├─ Bull Analyst (看多论据 + 历史记忆 + 反思)
  └─ Bear Analyst (看空论据 + 历史记忆 + 反思)
  ↓
Phase 2: Judge 决策 (1 AI call)
  └─ 量化决策框架 + 辩论总结 + 历史记忆 + 反思
  ↓
Phase 2.5: Entry Timing Agent (0~1 AI call, v23.0, 仅 LONG/SHORT 时)
  └─ MTF alignment + 30M 执行层时机 + 逆势风险 + extension/volatility
  └─ 可 REJECT → HOLD，或降级 confidence (只降不升)
  ↓
Phase 3: Risk Manager (0~1 AI call, v32.1, 仅 LONG/SHORT 时)
  └─ 仓位风险 + 市场结构风险 + 历史记忆
  ↓
calculate_mechanical_sltp() → ATR × confidence 构造性保证 R/R >= 1.3:1 (HIGH 1.5:1)
  ↓
最终交易信号
```

### 三层时间框架 (MTF)

| 层级 | 时间框架 | 职责 |
|------|---------|------|
| 趋势层 | 1D | SMA_200 + MACD，Risk-On/Off 过滤 |
| 决策层 | 4H | Bull/Bear 辩论 + Judge 决策 |
| 执行层 | 30M | RSI 入场时机 + S/R 止损止盈 |

### 13 类数据覆盖

| # | 数据 | 必需 | 来源 |
|---|------|------|------|
| 1 | technical_data (30M) | ✅ | IndicatorManager (含 ATR Extension Ratio) |
| 2 | sentiment_data | ✅ | Binance 多空比 |
| 3 | price_data | ✅ | Binance ticker |
| 4 | order_flow_report | | BinanceKlineClient |
| 5 | derivatives_report (Coinalyze) | | CoinalyzeClient |
| 6 | binance_derivatives (Top Traders) | | BinanceDerivativesClient |
| 7 | orderbook_report | | BinanceOrderbookClient |
| 8 | mtf_decision_layer (4H) | | 技术指标 |
| 9 | mtf_trend_layer (1D) | | 技术指标 |
| 10 | current_position | | Binance |
| 11 | account_context | ✅ | Binance |
| 12 | historical_context | | 内部计算 |
| 13 | sr_zones_data | | S/R 计算器 |

### 记忆系统 (v5.9)

**文件**: `data/trading_memory.json` (最多 500 条)

**数据流**:
```
on_position_closed → evaluate_trade() → record_outcome() → trading_memory.json
                                                                 ↓
                            _get_past_memories() ← 读取 ←────────┘
                                     ↓
                      Bull / Bear / Judge / Risk (全部 6 次 AI 调用)
                                     ↓
                      Web API / Telegram Daily/Weekly 报告
```

**v5.9 关键**: 所有 4 个 Agent 都接收历史记忆:
- Bull/Bear/Risk: `PAST TRADE PATTERNS` 段落
- Judge: `PAST REFLECTIONS` 段落

### v27.0 Feature-Driven Structured Debate

```
13 类原始数据
  ↓
extract_features() → 124 typed features (FEATURE_SCHEMA)
  ↓
compute_scores_from_features() → 5 维评分 (_scores)
  ├─ trend:        1D SMA200/ADX/DI 方向
  ├─ momentum:     4H RSI/MACD + 30M 确认
  ├─ order_flow:   CVD/OI/Taker/FR 综合
  ├─ vol_ext_risk: Extension Regime + Volatility Regime
  └─ risk_env:     FR/清算/sentiment 风险环境
  + net: 加权综合 (BULLISH/BEARISH/NEUTRAL)
  ↓
compute_valid_tags() → 预计算数据支持的 REASON_TAGS
compute_annotated_tags() → 带人类可读注释的 tags
  ↓
AI agents (JSON mode + feature_dict + REASON_TAGS 约束)
  ↓
_validate_agent_output() → 强制 schema 合规
filter_output_tags() → 过滤非 valid 的 tags
  ↓
AIQualityAuditor → 6 维质量评分
```

**Agent Output Schema (v27.0)**:
- Bull/Bear: `{conviction, evidence: [tags], risk_flags: [tags], reasoning}`
- Judge: `{signal, confidence, decisive_reasons: [tags], reasoning}`
- Entry Timing: `{verdict, adjusted_confidence, dimensions: {mtf, timing, counter_trend, extension}}`
- Risk: `{risk_appetite, size_pct, reasoning}`

### 交易评估框架

每笔交易平仓后自动评估 (`trading_logic.py:evaluate_trade()`):

| 等级 | 盈利交易 | 亏损交易 |
|------|---------|---------|
| A+ | R/R ≥ 2.5 | — |
| A | R/R ≥ 1.5 | — |
| B | R/R ≥ 1.0 | — |
| C | R/R < 1.0 (小盈利) | — |
| D | — | 亏损 ≤ 计划 SL × 1.2 (有纪律) |
| F | — | 亏损 > 计划 SL × 1.2 (失控) |

**Web 集成**: `TradeEvaluationService` 读取同一文件，提供:
- 公开 API: `/api/public/trade-evaluation/summary`, `/api/public/trade-evaluation/recent`
- 管理 API: `/api/admin/trade-evaluation/full`, `/api/admin/trade-evaluation/export`

### 核心架构决策 (仍生效)

| 版本 | 决策 | 说明 |
|------|------|------|
| v3.16 | S/R 硬风控移至 AI | Risk Manager prompt 包含 block_long/block_short，AI 自主判断 |
| v3.17 | R/R 驱动入场 | R/R ≥ 1.3:1 由 `calculate_mechanical_sltp()` 构造性保证 (ATR × confidence multiplier)。v40.0: HIGH 1.5:1, MEDIUM/LOW 1.3:1 |
| v3.18 | 订单流程安全 | 反转两阶段提交、Bracket 失败不回退 (加仓 SL/TP 数量同步已被 v7.2 每层独立取代) |
| v4.13 | 分步订单提交 | entry → on_position_opened → SL + TP 单独提交 (NT 1.222.0+) |
| v4.14 | Risk Manager 只管风险 | 不重判方向，只设 SL/TP + 仓位，仅 R/R<1.3/FR>0.1%/流动性枯竭否决 |
| v4.17 | LIMIT 入场 | LIMIT @ validated entry_price 取代 MARKET，R/R 永不低于验证值 |
| v5.9 | 全 Agent 记忆 | 所有 4 个 Agent 接收 past_memories，不仅仅是 Judge |
| v5.12 | 逆势 R/R 提升 | 逆势交易 R/R ≥ 1.69:1 (×1.3)，补偿较低胜率，消除负期望交易 |
| v6.1 | Emergency SL 市价兜底 | SL 提交失败 → `_emergency_market_close()` 市价 reduce_only 平仓，消除裸仓风险 |
| v6.6 | TP 位置挂单 (position-linked) | TP 从 `order_factory.limit()` (LIMIT) 改为 `order_factory.limit_if_touched()` (TAKE_PROFIT)，通过 Algo API 提交，仓位平仓后币安自动取消 |
| v6.7 | 9 项逻辑审计修复 | TP 重启恢复、数据质量门控、入场 FR 检查、过期仓位检测、时间屏障优先、逆势数据缺失保守、部分成交量同步、AI 输出范围验证 |
| v7.0 | 外部数据统一 (SSoT) | `AIDataAssembler.fetch_external_data()` — on_timer() 和 ai_decision.py 共用，消除 ~350 行重复代码 |
| v7.1 | 仓位上限硬性钳制 | `ai_controlled` 和 `hybrid_atr_ai` 的 `final_usdt` 增加 `min(position_usdt, max_usdt)` 保护，AI size_pct 钳制 ≤100 |
| v7.1 | 紧急平仓重试+升级 | `_emergency_market_close()` 3 次重试 + `_needs_emergency_review` 标记，下个 on_timer 重新保护 |
| v7.1 | ConfigManager R/R 验证 | `min_rr_ratio ∈ [1.0, 5.0]` + `counter_trend_rr_multiplier ∈ [1.0, 3.0]` 加入验证规则 |
| v7.1 | Sentiment 边界验证 | `long/short_ratio ∈ [0, 1]` + 和 ≈1.0 一致性检查，防止 API 异常值误导 AI |
| v7.2 | 每层独立 SL/TP | `_layer_orders` 追踪每层入场+SL+TP，加仓不影响已有层。LIFO 减仓。删除 `_replace_sltp_orders`/`_update_sltp_quantity`/`_check_confidence_degradation_sl`。`on_order_filled` 用 `_order_to_layer` 反查只取消同层对手单。`data/layer_orders.json` 持久化重启恢复 |
| v7.3 | 重启 SL 交叉验证 | Tier 2 恢复后交叉验证每层 `sl_order_id` 是否在交易所存活，过期/缺失 SL 立即触发 emergency SL。`_submit_emergency_sl` 通过 `_create_layer()` 创建层级条目+持久化。`on_stop()` fallback 不再 `cancel_all_orders()`，保留 SL/TP 保护 |
| v11.0 | S/R 纯信息化 | S/R zones 仅作为 AI 上下文信息，不再机械锚定 SL/TP。sr_sltp_calculator 已删除，path_obstacles 已移除 |
| v12.0 | Per-Agent 反思记忆 | 平仓后 LLM 生成深度反思（≤150 字），替换模板 lesson。4 个 Agent 按角色接收带反思的记忆。重启自动补回缺失反思（max 3）。每次平仓增加 1 次 API 调用（Phase 0）。反思参数为代码常量（max_chars=150, temperature=0.3），不经 YAML 配置 |
| v13.1 | Telegram 平仓失败 → Emergency SL | `_cmd_close`/`_cmd_partial_close`: 取消保护单成功后如果提交平仓单失败，立即调 `_submit_emergency_sl()` 防裸仓。P1.36 检查同步升级验证此路径 |
| v14.0 | Telegram 双频道职能分离 | 控制机器人(私聊：运维监控+命令交互) + 通知频道(订阅者：交易信号+业绩)。`broadcast=True` → 仅通知频道，`broadcast=False` → 仅私聊。每条消息只发一个地方，零重复 |
| v16.0 | S/R Hold Probability 自动校准 | `scripts/calibrate_hold_probability.py` 每周 cron 拉 30 天 K 线，滑窗计算 zones + 前向扫描 hold/break，统计因子写入 `data/calibration/latest.json`。`calibration_loader.py` mtime 缓存自动刷新。校准失败 → fallback v8.2 默认值，生产零影响。Telegram `/calibrate` 命令可手动触发。心跳显示校准版本和过期警告 |
| v17.0 | S/R 简化为 1+1 | `calculate()` 内部仍聚类全部候选，但输出仅保留 nearest 1 support + 1 resistance (按距离排序取最近合格 zone)。`support_zones`/`resistance_zones` 列表最多 1 个元素。AI report 只显示 [S1]+[R1]，方向中性描述。减少 prompt 噪音和 token 消耗，所有下游逻辑本就只用 `nearest_*` |
| v17.1 | 清算缓冲双层保护 | Risk Manager STEP 3 新增清算缓冲 4 级评估 (>15%正常/10-15%降confidence/5-10%→LOW/<5%否决)，与 FR 格式对齐。`_execute_trade()` 代码硬地板: buffer<5% 阻止加仓+Telegram 告警。S/R R/R >20:1 cap 为 `⚠️ UNRELIABLE` 防极端值误导 |
| v18.0 | 反思系统改革 + Emergency 短周期重试 | 平仓反思从模板改为 LLM 深度反思（≤150 字）。Extended reflections 独立 JSON 存储。记忆评分增加 recency factor（14 天半衰期指数衰减）。Emergency SL 失败后注册 30s one-shot 重试而非等 15 分钟 |
| v18.1 | Signal Reliability Annotations + 强趋势角色调节 | `_format_technical_report()` 从时间框架分组改为可靠性层级分组（Tier 1/2/3）。Bull/Bear 在 ADX>40 时角色调节为趋势跟随专注入场时机。`on_order_rejected()` 增加 -2022 ReduceOnly 专项处理 |
| v18.2 | 执行层 15M→30M + Price Surge Trigger | 执行层从 15M 迁移到 30M（减少噪音）。Ghost position 3 次 -2022 rejection 后强制清除状态。`on_trade_tick()` 实时价格监控 + 1.5% 偏离触发提前 AI 分析。(注: Alignment Gate 已被 v23.0 Entry Timing Agent 取代) |
| v18.3 | Post-Close 积极分析期 | 平仓后强制 2 轮额外 AI 分析（加上 Check 3 自然触发 = 共 3 轮 ~45 分钟）。`_force_analysis_cycles_remaining` 计数器在 `on_position_closed()` + `_clear_position_state()` 设置，在 `_has_market_changed()` Check 4 消费。放在 Check 1-3 之后避免浪费自然触发。与 stoploss cooldown 兼容（cooldown 优先，counter 延后消费）|
| v19.1 | ATR Extension Ratio 过度延伸检测 | `_calculate_extension_ratios()` 计算 `(Price - SMA) / ATR`，波动率归一化价格偏离度。4 级 regime：NORMAL(<2)/EXTENDED(2-3)/OVEREXTENDED(3-5)/EXTREME(≥5)。纯 RISK 信号不影响方向，与 `calculate_mechanical_sltp()` 正交。5 个 Agent prompt 全部集成：Bull 入场质量评估、Bear 回撤风险论据、Entry Timing Agent 入场质量 (v23.0)、Risk Manager 仓位缩减指引。SIGNAL_CONFIDENCE_MATRIX 新增 overextended/extreme 行。阈值为领域知识常量，不经 YAML 配置 |
| v19.1 | RSI/MACD 背离预计算 | `_detect_divergences()` 检测 4H 和 30M 两个时间框架的经典背离。Bearish: price higher high + RSI/MACD lower high。Bullish: price lower low + RSI/MACD higher low。使用 local extremes (window=2) 定位 peak/trough，indicator peak 与 price peak 偏差 ≤2 bar 才匹配。输出为 pre-computed annotation 直接插入技术报告，AI 无需自行推导 |
| v19.1 | CVD-Price 背离交叉分析 | 订单流报告和 4H 层新增 CVD-Price 交叉检测。Price falling + CVD positive → ACCUMULATION (smart money buying dip)。Price rising + CVD negative → DISTRIBUTION (rally on weak buying)。Price falling + CVD negative → CONFIRMED selling。阈值: price change >0.3%, CVD history ≥3 bars。30M 和 4H 层均独立检测 |
| v19.1.1 | Extension Ratio 趋势感知 | ADX>40 强趋势中 OVEREXTENDED(3-5 ATR) 降权：Bull 不强制"承认"追涨风险、Bear 不作为"强力论据"、Entry Timing Agent 最多降为 FAIR (v23.0)、Risk Manager 不直接 CONSERVATIVE、技术报告 warning 降级为 NOTE。仅 EXTREME(>5) 保留完整警告。ADX<40 行为不变。SIGNAL_CONFIDENCE_MATRIX ADX>40 列 overextended=0.7 已到位 |
| v19.2 | CVD-Price 时间对齐修复 | 30M CVD-Price 交叉分析从 `period_change_pct`(~122h) 改为 5-bar price change (~2.5h)，匹配 CVD 5-bar 窗口。4H 从全序列 (~64h) 改为 last-5-bar (~20h)。修复前时间尺度错配导致 ACCUMULATION/DISTRIBUTION 标注不准确 |
| v19.2 | OI×CVD 持仓分析 | `_format_derivatives_report()` 新增 `cvd_data` 参数，在 OI×Price 四象限后追加 OI×CVD 交叉：OI↑+CVD↑=多头开仓、OI↑+CVD↓=空头开仓、OI↓+CVD↓=多头平仓、OI↓+CVD↑=空头平仓 (CoinGlass 行业标准框架)。桥接 OI×Price 和 CVD×Price 两个独立分析段 |
| v19.2 | CVD Absorption 检测 | 30M 和 4H CVD-Price 交叉新增 ABSORPTION 分支：CVD 正 + price flat (±0.3%) = 被动卖方吸收买盘；CVD 负 + price flat = 被动买方吸收卖盘。SIGNAL_CONFIDENCE_MATRIX 新增 `CVD absorption**` 行 (RANGING 1.3 最高) 和 `OI×CVD positioning` 行 |
| v20.0 | ATR Volatility Regime | ATR% (ATR/Price) 百分位分级 (LOW<30/NORMAL/HIGH>70/EXTREME>90)。与 ADX 正交互补：ADX 测趋势方向性，Vol Regime 测波动率环境大小。纯 RISK/CONTEXT 信号，调整仓位和止损宽度，不影响方向。共享逻辑 `classify_volatility_regime()` 在 `shared_logic.py`。SIGNAL_CONFIDENCE_MATRIX 新增 3 行 (Vol LOW/HIGH/EXTREME)。阈值为领域知识常量 (30/70/90 百分位)，不经 YAML 配置 |
| v20.0 | OBV 背离检测 | EMA(20) 平滑后的 OBV 接入现有 `_detect_divergences(obv_series=...)`。4H 主要 + 30M 辅助。OBV 捕捉宏观成交量积累/派发，与 CVD (微观订单流激进度) 互补非冗余。单独 false positive 40-60%，需 RSI/MACD/CVD confluence。SIGNAL_CONFIDENCE_MATRIX 新增 `4H OBV divergence` + `OBV+CVD confluence div` 行。`_ema_smooth()` 纯 Python 静态方法。`_obv_values` 在 `technical_manager.py` 增量累积 |
| v21.0 | FR Consecutive Block Counter | `_fr_consecutive_blocks` / `_fr_block_direction` 追踪同方向连续 FR 阻止次数。≥3 次时将同方向 AI 信号降级为 HOLD，打破死循环（如 12× SHORT 全被 FR 阻止）。成功开仓后 reset 计数器。平仓不 reset（FR 压力是市场条件非仓位状态）。`fr_block_context` 注入 AI 数据，`_format_technical_report()` 输出 FR 阻止警告。Telegram 通知降级事件 |
| v21.0 | 1D Historical Context 时序注入 | `trend_manager.get_historical_context(count=10)` 获取 1D 层 10-bar 时序数据 (ADX/DI+/DI-/RSI/Price)。注入 `ai_technical_data['mtf_trend_layer']['historical_context']`。`_format_technical_report()` 生成 `=== 1D TIME SERIES ===` 段落，含自动趋势标注 (FALLING/RISING/Flat)。用于趋势衰竭检测 (ADX 从峰值下降) 和 DI 方向变化检测 |
| v23.0 | Entry Timing Agent (Phase 2.5) | 独立入场时机评估 Agent，位于 Judge 和 Risk Manager 之间（共 5~7 次 AI 调用）。取代 3 个硬编码 gate：`_check_alignment_gate()`、Entry Quality Downgrade、30M Confidence Cap。4 维评估：MTF alignment、30M 执行层时机、逆势风险、extension/volatility。ADX>40 逆势信号需 30M 完整动量反转确认否则 REJECT。Judge 不再输出 `entry_quality`/`entry_note`。Risk Manager 不再评估入场时机（`entry_timing_risk` 移除）。confidence 只降不升 |
| v27.0 | Feature-Driven Structured Debate | `extract_features()` 从 13 类原始数据提取 124 个 typed features (FEATURE_SCHEMA)。Bull/Bear/Judge/ET/Risk 全部使用 JSON mode + feature_dict 输入 + REASON_TAGS 输出约束。text-based debate 降为 fallback。`_validate_agent_output()` 强制 schema 合规。feature snapshot 持久化到 `data/feature_snapshots/` 支持 deterministic replay |
| v28.0 | Dimensional Scores + Knowledge Brief | `compute_scores_from_features()` 预计算 5 维评分 (trend/momentum/order_flow/vol_ext_risk/risk_env) + net 综合判断，注入所有 agent user prompt 首位 (`_scores`)，利用 primacy effect 锚定分析。`INDICATOR_KNOWLEDGE_BRIEF` (~500 tokens) 替代 text 路径的 `INDICATOR_DEFINITIONS` (~4K tokens)。`compute_valid_tags()` + `compute_annotated_tags()` 预计算数据支持的 REASON_TAGS + 人类可读注释 |
| v29.1 | AI Quality Auditor Tag+Text 融合覆盖 | `AIQualityAuditor` 6 维验证: data coverage rate, SIGNAL_CONFIDENCE_MATRIX compliance, MTF responsibility, per-agent citation tracking, production quality metrics, user-facing report。v29.1 tag+text 双通道覆盖检测避免 false negative。v29.3 weak-signal tag 过滤避免 false penalty。v29.4 pre-truncation reasoning 修复截断丢失。v29.5 所有文本字段 `_raw_{key}` 保全 + Pattern 3 cross-TF post-validation + MTF direction regex 区分技术描述 vs 方向论证 |
| v30.4 | Auditor Zone Check 修复 + Telegram 中文规范 | `_check_zone_claims()` RSI zone regex 增加 negative lookahead `(?!\s*extension)` 排除 "oversold/overbought extension" 上下文误判。Entry Timing + Risk coverage text 统一使用 `_raw_*` fallback (与 Bull/Bear/Judge 一致)。心跳信号显示 + 风控告警 + ET rejection + FR exhaustion + position size zero 等 6 处 Telegram 消息通过 `side_to_cn()` 转中文，符合 CLAUDE.md 中英混输规范 |
| v30.5 | Auditor 跨 TF 归属修复 + Regex 精度提升 | 3 处跨 TF 归属 bug：(1) MACD crossover check 的 ±100 char 窗口改用 `_claims_near_tf()` 带跨 TF 排除；(2) `_extract_indicator_value` Pattern 3 post-validation 从 20→50 char 覆盖中文文本中 TF-indicator 距离 >20 的场景（如 "1D ADX=35.5确认趋势，DI+ 17.9。4H"）；(3) `_extract_dollar_value` Pattern 3 缺少 `_no_tf` guard 和 post-validation。`_DATA_CATEGORY_MARKERS` 4 处 `.*` 改为 `.{0,N}` 防止跨上下文误匹配（order_flow/orderbook/volatility_regime/extension_ratio）。`_SIGNAL_KEY_PATTERNS` 16 处 `.*` 改为 `_NO_TF` tempered greedy token 防止跨 TF 误触发 SKIP signal violation |
| v31.2 | Auditor MACD 全 TF 完整覆盖 | (1) `_SIGNAL_KEY_PATTERNS` 新增 `1d_macd_h`/`30m_macd_h` (含中文直方图模式)，与 `4h_macd_h` 对齐；(2) `_DATA_CATEGORY_MARKERS` 三个 TF 分类新增 MACD 文本 fallback 标记；(3) `_TAG_TO_CATEGORIES` 中 `MACD_HISTOGRAM_*` 从仅 `['mtf_4h']` 扩展至 `['technical_30m', 'mtf_4h']`；(4) `_SIGNAL_ANNOTATIONS` 新增 `1d_macd_h`/`30m_macd_h` 可靠性评分；(5) `MACD Signal` value 提取 regex 从 `(?:MACD\s*)?Signal` 改为 `MACD\s*Signal` 防止 "Buy Signal" 等误匹配；(6) crossover claim 检测新增反向语序 (Signal crossed below/above MACD, 信号线下穿/上穿MACD)；(7) histogram claim 检测新增中文 "直方图" 模式；(8) `SIGNAL_CONFIDENCE_MATRIX` 新增 1D/30M MACD histogram 行 |
| v31.3 | Auditor DI/EMA 交叉方向验证 | (1) `_check_comparison_claims()` 新增 DI+/DI- 文本交叉声明验证 (补全 `_audit_di_citations()` 仅覆盖数值比较的空白)，支持 "DI bullish/bearish cross"、"DI+上穿/下穿DI-" 等模式；(2) `_check_comparison_claims()` 新增 EMA 12/26 交叉方向验证，支持 "EMA bullish/bearish/golden/death cross"、"EMA 金叉/死叉" 等模式；(3) 两项检查均使用 `_claims_near_tf()` 带跨 TF 排除 |
| v31.4 | Feature Extraction Production Parity | (1) `extract_features()` EMA key 修复: `ema_10_30m`/`ema_20_30m` → `ema_12_30m`/`ema_26_30m` (匹配 `ema_periods=[12, 26]`)；(2) `position_pnl_pct` 字段 `pnl_pct` → `pnl_percentage`；(3) `position_size_pct` 字段 `size_pct` → `margin_used_pct`；(4) `liquidation_buffer_pct` 字段 `liquidation_buffer_pct` → `liquidation_buffer_portfolio_min_pct`；(5) `FEATURE_SCHEMA` source 注释同步更新；(6) 诊断系统新增 Check 14: v31.4 feature field mapping parity verification |
| v32.0 | DeepSeek V3.2 Thinking Mode | `enable_thinking: true` 启用 DeepSeek V3.2 思维链推理。5 个 Agent 全部启用 (Bull/Bear/Judge/Entry Timing/Risk + Reflection)。与 `response_format: {"type": "json_object"}` 兼容 (V3.2 支持 thinking + json_object 同时使用)。`configs/base.yaml` 新增 `deepseek.enable_thinking` 参数。`/config` 命令和 Web UI 显示 Thinking 状态。Token 消耗增加 ~30-50%，但推理质量显著提升 |
| v32.1 | Risk Manager 条件跳过 | Judge=HOLD/CLOSE/REDUCE 时跳过 Risk Manager API 调用 (无仓位需要 sizing)，直接构造 passthrough 默认值。镜像 v23.0 Entry Timing skip 模式。HOLD 占 60-70% 周期时节省 ~25-35% API 成本。`RiskManagerStandaloneTest` 独立诊断确保 RM 功能正常 (mock LONG/MEDIUM Judge → 6 项 schema 验证) |
| v32.2 | Telegram 中英混输合规 | (1) 5 个 Agent structured prompt 新增中英混输指令 (`OUTPUT LANGUAGE: Chinese-English mixed`)，确保 AI 输出遵循 CLAUDE.md 语言规范；(2) Telegram 消息修复：启动消息 feature flags 中文化 ("自动 SL/TP"/"OCO 订单"/"MTF 多时间框架"/"多代理 AI")，CVD 信号显示中文 (吸筹/派发/吸收/确认)，Entry Timing verdict 中文化 (通过/拦截)，信号标签统一中文 ("观望"/"平仓"/"开多"/"开空") |
| v34.0 | Auditor Logic-Level Coherence Checks | `AIQualityAuditor` 新增 5 个跨维度一致性检查: (1) REASON_SIGNAL_CONFLICT: Judge decisive_reasons 与 decision 方向冲突 (PENALIZED 8/12); (2) SIGNAL_SCORE_DIVERGENCE: Judge decision 与 `_scores['net']` 共识方向对立 (informational); (3) CONFIDENCE_RISK_CONFLICT: HIGH confidence + HIGH risk_env (PENALIZED 6); (4) DEBATE_CONVERGENCE: Bull/Bear conviction spread < 0.15 echo chamber 检测 (informational); (5) SINGLE_DIMENSION_DECISION: decisive_reasons 仅覆盖单一数据类别 (informational)。最大新增扣分 18 分。使用现有 `BULLISH/BEARISH_EVIDENCE_TAGS` + `_TAG_TO_CATEGORIES`，零新增依赖。P1.115-P1.117 回归检测。`diagnose_quality_scoring.py` Phase 8 验证。`scripts/analyze_quality_correlation.py` Layer 3 outcome feedback 分析 |
| v34.1 | Three-Layer Auditor Architecture 完整实现 | **Layer 1**: `extract_features()` 新增 8 个 `_avail_*` boolean flags 区分 "数据中性" vs "数据缺失"；`compute_scores_from_features()` 排除不可用维度防 0.0 artifacts 污染 net 评分；auditor Step 0 `DATA_UNAVAILABLE` pre-check + `_effective_required()` 覆盖率惩罚调整。**Layer 2**: (6) DEBATE_SHALLOW_R2: R1→R2 evidence stagnation 检测 (Jaccard overlap ≥ 0.85 + 0 new tags + conviction delta < 0.05，双 agent 均 stagnant 才触发，informational)；`_run_structured_debate()` 计算 `_r1_r2_evidence_overlap`/`_r1_r2_evidence_new`/`_r1_r2_conviction_delta` 三个指标存储于 R2 output。**Layer 3**: `scripts/analyze_quality_correlation.py` 10 项分析 (quality quintiles/confidence calibration/entry timing/counter-trend/grade distribution/debate winner/feature importance Spearman ρ/rolling performance + streak/confidence recalibration + EV per bucket/v34.0 flag correlation)；`hold_source` 6 种 HOLD 路径分类 (cooldown/gate_skip/dedup/risk_breaker/et_reject/explicit_judge)；`_hold_counterfactual_record` 记录+评估 HOLD 反事实 |
| v34.2 | HOLD Counterfactual 持久化 + 覆盖率惩罚修复 | (1) `_hold_counterfactual_record` 持久化到 `data/hold_counterfactuals.json` (最多 200 条, FIFO)，记录 timestamp/proposed_signal/hold_source/entry_price/eval_price/price_change_pct/verdict (correct/wrong/neutral)，支持 Layer 3 outcome feedback 分析；(2) `_effective_required()` 排除 `_avail_*=False` 对应的数据类别 (`_AVAIL_TO_CATEGORIES` 映射)，Agent 不再因未收到数据而被惩罚覆盖率；(3) `compute_scores_from_features()` OBI/liquidation_buffer/top_traders 评分增加 `_avail_*` 守卫，防 0.0 默认值 artifacts 污染 risk_env 评分；(4) `hold_source` 传播到 `_last_signal_status` 并在心跳显示中文 HOLD 来源 |
| v34.3 | Feature Extraction Bug Fixes | (1) `extract_features()` CVD-Price cross features (`cvd_price_cross_30m`/`cvd_price_cross_4h`) 从始终 `None` 修复为正确从 `order_flow_report`/`mtf_decision_layer` 提取；(2) `_avail_sentiment` flag 缺失修复，sentiment 数据不可用时不再污染 risk_env 评分 |
| v35.0 | Layer 3 Outcome Feedback (Telegram + Web) | (1) `utils/quality_analysis.py` (447 行) 作为 SSoT 提取 `analyze_quality_correlation.py` 的 10 个分析函数（confidence calibration/entry timing/counter-trend/grade distribution/debate winner/feature importance/rolling performance/confidence recalibration/v34.0 flags/HOLD counterfactuals）；(2) 心跳新增 Layer 3 指标：win rate/streak/confidence calibration EV + overconfident/miscalibrated 警告；(3) `/layer3` Telegram 命令：完整 outcome feedback 分析；(4) Web 后端 5 个新端点 (`/api/public/quality-analysis/summary` + 4 个 admin)；(5) `web/frontend/pages/quality.tsx` 质量分析仪表盘 (confidence calibration table/entry timing progress bars/grade distribution chart)；(6) i18n EN+ZH 翻译；(7) 导航栏新增 AI Quality 链接 |
| v35.1 | Tag Annotation Numeric Context 统一标准 | `compute_annotated_tags()` 系统性审计：**统一标准**——每个 tag 注释必须包含 (1) 触发该 tag 的关键数值 (2) 影响解读的上下文信息 (regime/strength/reliability)。修复 7 个 gap：(1) `NEAR_STRONG_SUPPORT`/`NEAR_STRONG_RESISTANCE` 注释新增 `strength=LOW/MEDIUM/HIGH`，防 AI 误将 tag 名 "STRONG" 当作实际强度；(2) `SR_BREAKOUT_POTENTIAL` 新增最近 level 的 strength + dist；(3) `SR_REJECTION` 新增两个 level 的 strength；(4) `SR_TRAPPED` 新增两个 level 的 strength；(5) `CVD_ACCUMULATION`/`CVD_DISTRIBUTION` 新增 CVD 数值 + price change %；(6) `CVD_ABSORPTION_BUY`/`CVD_ABSORPTION_SELL` 新增 CVD 数值 + price change %。**根因**：tag 名 `NEAR_STRONG_SUPPORT` 在 `compute_valid_tags()` 中 `sup_strength != "NONE"` 即触发 (LOW 也通过)，但注释无 strength → AI 误判 LOW 支撑为"强支撑"并作为 decisive reason |
| v36.0 | Feature Pipeline Production Parity + Tag Annotation 全覆盖 | (1) `extract_features()` 多处数据源修复: 30M SMA 从 `sma_50` → `sma_5` (30M 只有 `sma_periods=[5,20]`), 1D time series 从 30M `hist_ctx` → 正确的 `hist_ctx_1d`, 4H time series 从 30M `hist_ctx` → `hist_ctx_4h`, OBV key 从 `obv_ema_trend` → `obv_trend`；(2) `compute_annotated_tags()` 完成全部 REASON_TAGS 注释覆盖 (1D/4H extension, S/R context, divergence per-type, order flow CVD/OBI, OI positioning, liquidation, top traders, volatility per-TF, sentiment, BB squeeze/expansion)；(3) `compute_scores_from_features()` 修复 NEUTRAL 维度被 skip 导致 net 评分 length mismatch, `liq_buffer=0` 边界处理；(4) BB_SQUEEZE/BB_EXPANSION 从硬编码迁移到 data-driven validation (via `bb_width_trend`)；(5) `FEATURE_SCHEMA` 新增 `bb_width_4h_trend_5bar`/`bb_width_30m_trend_5bar` enum fields；(6) `compute_valid_tags()` 30M SMA crossover 修复为 SMA 5/20 (匹配执行层配置)；(7) 新增 layer priority cap: 1D+4H 均反对 Judge 方向时降级 confidence |
| v36.1 | Auditor Coverage Gaps + Score Risk Factors | (1) `_SIGNAL_KEY_PATTERNS` 新增 OBV citation 检测 (3 个 TF: `obv_trend_30m`/`obv_trend_4h`/`obv_trend_1d`), 1D BB/Volume 检测模式；(2) `_DATA_CATEGORY_MARKERS` 补全 1D/4H volume ratio 文本 fallback；(3) `compute_scores_from_features()` 新增 BB width squeeze amplification (FALLING BB width = contracting = +1 vol_ext_risk) + S/R proximity risk (price within 1 ATR of support/resistance = +1 risk_env)；(4) Auditor reasoning text 增加 narrative misread pattern 检测；(5) RSI bullish keyword boundary 修复 (`\b` word boundaries)；(6) `diagnose_quality_scoring.py` 生产数据 parity 修复 |
| v36.2 | Three-State ADX Direction | `adx_direction_1d` 从二值 (BULLISH/BEARISH) 扩展为三态 (BULLISH/BEARISH/NEUTRAL)。DI+ == DI- (含两者均为 0 时 1D 数据不可用) 产生 NEUTRAL 而非虚假 BEARISH。`FEATURE_SCHEMA` 更新 `values: ["BULLISH", "BEARISH", "NEUTRAL"]`。`compute_scores_from_features()` NEUTRAL → 0 分 (无方向信号)。`tag_validator.py` 映射 NEUTRAL → `TREND_1D_NEUTRAL`。全部诊断脚本同步更新适配三态 |
| v36.3 | Ghost Detection + TP Recovery + Orphan Cleanup Guards | (1) Ghost position 检测修复: `_ghost_first_seen` 在 `on_position_closed()` 和 `_clear_position_state()` 中清零，防止 flag 永久残留导致正常仓位被误判为 ghost 并取消 SL/TP/trailing；(2) TP 提交增加 retry (2 次尝试)，Tier 2 recovery 新增 TP never-submitted 恢复 (`tp_order_id` 为空但 `tp_price > 0`)；(3) `_cleanup_orphaned_orders()` 双重防护: 时间窗口 guard (仓位开立 <120s 内不清理) + layer 匹配 guard (订单存在于 `_order_to_layer` 中不清理)，防止刚提交的 SL/TP/trailing 被误删；(4) CVD cross tags 从 mutual exclusion group 中移除 (允许同时出现 accumulation + distribution tags 在不同 TF) |
| v36.4 | Quality Scoring Diagnostic Expansion + In-Session TP Recovery | `diagnose_quality_scoring.py` 从 14 阶段扩展至 17 阶段: Phase 15 (tag annotation completeness + numeric context verification), Phase 16 (structured debate quality metrics + evidence stagnation), Phase 17 (coherence check validation + tag-signal alignment)。完整覆盖 Layer 1/2/3 auditor pipeline。**In-Session TP Recovery**: `_check_tp_coverage()` 在每个 on_timer 周期检查所有层的 TP 覆盖状态，发现 `tp_order_id` 为空但 `tp_price > 0` 的层立即调用 `_resubmit_tp_for_layer()` 恢复。修复 v36.3 遗留缺口：TP 2 次重试都失败后，直到重启前 TP 不会被恢复的问题 |
| v37.0 | Plan I SL/TP 参数优化 + LOW Confidence 放行 | 基于 48h 真实信号反事实回测 (33 笔交易, +2.19% PnL 含手续费)。**参数变更**: `min_confidence_to_trade`: MEDIUM→LOW (48h 内 34/36 信号为 LOW 导致 0 交易)；`sl_atr_multiplier`: HIGH 2.0→1.5, MEDIUM 2.5→1.8, 新增 LOW=1.8；`tp_rr_target`: HIGH 2.5→2.0, MEDIUM 2.0→1.5, 新增 LOW=1.5；`sl_atr_multiplier_floor`: 1.5→1.2；`confidence_mapping` 新增 LOW=30 (保守 30% 仓位)。**安全边际**: breakeven fee rate 0.141% vs 实际 0.075%，47% 安全余量。R/R 由构造性保证 ≥1.5:1 (HIGH 2.0:1)。SSoT 同步: `configs/base.yaml` + `strategy/trading_logic.py` + `utils/backtest_math.py` 三处一致更新。**已被 v37.1 取代** |
| v37.1 | Plan II SL 放宽 + MEDIUM Confidence 恢复 | 基于 18.6 天生产级回测 (283 信号, v2.1 仿真器含双边手续费/滑点/DD 熔断)。Plan I 的紧 SL 导致 circuit breaker 级联 (38% 信号被跳过)。**参数变更**: `min_confidence_to_trade`: LOW→MEDIUM (LOW 仅 1 笔 -0.19%, 增加 CB 级联风险)；`sl_atr_multiplier`: HIGH 1.5→1.8, MEDIUM 1.8→2.2 (SL 率从 38.5%→26.2%)；`tp_rr_target`: MEDIUM 1.5→1.8 (配合更宽 SL, HIGH 2.0 不变)；移除 LOW tier。**回测结果**: Plan II +96.46% PnL, 4.21% DD, Calmar 22.9 (vs Plan I +51.42%, Calmar 13.5)。SSoT 同步: `configs/base.yaml` + `strategy/trading_logic.py` + `utils/backtest_math.py` 三处一致更新 |
| v38.0 | Confidence Chain Resolution + NULL Filtering | 回测仿真器 v3.0 新增 Confidence Chain 日志解析。**格式**: `[ctx_id] Confidence chain: judge:HIGH(AI) → entry_timing:MEDIUM(AI)`，链中最后一步为权威 confidence 值。**NULL 处理**: 未匹配到 confidence 的信号不再默认 LOW，而是标记为 None 并过滤。HOLD counterfactual 记录缺少 `proposed_confidence` 字段时跳过 (之前默认 LOW 污染数据)。新增 `confidence_source` 追踪 (judge/entry_timing/confidence_chain) 和 data quality breakdown 审计报告 |
| v38.1 | LOW Confidence 放行 + 数据积累 | 基于 18.4 天回测 (257 信号, v3.0 仿真器)。Plan B (LOW=MEDIUM params) 表现最优：LOW 3 笔 66.7% 胜率 +0.43% PnL，均 PnL +0.14%/笔正期望。**参数变更**: `min_confidence_to_trade`: MEDIUM→LOW；新增 `sl_atr_multiplier.LOW`=2.2 (同 MEDIUM)；新增 `tp_rr_target.LOW`=1.8 (同 MEDIUM)；新增 `confidence_mapping.LOW`=30 (30% 最保守仓位)。**设计意图**: 小仓位放行 LOW 信号积累数据，为后续参数优化提供样本。SSoT 同步: `configs/base.yaml` + `strategy/trading_logic.py` + `utils/backtest_math.py` 三处一致更新 |
| v38.2 | MACD Histogram Enum Mismatch Fix | `compute_scores_from_features()` 中 4H MACD histogram trend 检查使用 RISING/FALLING，但 `_classify_abs_trend()` 实际输出 EXPANDING/CONTRACTING/FLAT — **永远不匹配**，导致 4H MACD histogram 对 momentum 评分的贡献完全为零。315 个生产 feature snapshot 验证 90% 受影响。**修复**: 将 RISING/FALLING 改为 EXPANDING/CONTRACTING/FLAT。语义映射：sign (正/负) = 方向 (bullish/bearish)，EXPANDING = 动量增强，CONTRACTING = 动量衰减 (不贡献方向信号)。`FEATURE_SCHEMA` 已正确定义 `values: ["EXPANDING", "CONTRACTING", "FLAT"]`，bug 仅在 `compute_scores_from_features()` 消费端。修复后 momentum 维度从平均 1/10 FADING 恢复到正确反映 MACD histogram 方向 |
| v39.0 | 4H ATR SL/TP + Trend Rebalance + Reversal Detection | **SL/TP ATR 源迁移**: `calculate_mechanical_sltp()` 新增 `atr_4h` 参数，优先使用 4H ATR (30M fallback)。SL multiplier 从 30M 尺度 (HIGH=1.8/MED=2.2) 调整为 4H 尺度 (HIGH=0.8/MED=1.0/LOW=1.0)，floor 从 1.2→0.5。`ai_strategy.py` 缓存 `_cached_atr_4h`，`order_execution.py` 传递到 SL/TP 计算。**趋势权重再平衡**: `compute_scores_from_features()` 1D SMA200 从双权重降为单权重；新增 3 个独立 4H 趋势信号 (DI direction/RSI/MACD)。**趋势衰竭反转检测**: 5 条件组合 (ADX exhaustion/2+ divergences/DI convergence/S/R proximity/momentum opposition)，≥3 条件触发 `trend_reversal.active=True`，trend_score 减 3 (min 1)。返回值新增 `trend_reversal: {active, direction, signals}`。**market_regime**: 从 1D ADX 改为 `max(1D, 4H)` ADX，日志记录 effective_adx source。**Judge few-shot**: 新增 Example 8 (趋势衰竭→反转交易场景)。SSoT 同步: `configs/base.yaml` + `strategy/trading_logic.py` + `utils/backtest_math.py` 三处一致。**⚠️ 原子回滚**: ATR source (4H) 与 multiplier 值 (0.8/1.0) 是**耦合设计** — 回滚必须同时 revert 两者 (`git revert <hash>`)。单独回滚 multiplier 回 1.8/2.2 但保留 4H ATR 会导致 SL 距离 ~2.75× 过宽；单独回滚 ATR source 回 30M 但保留 0.8/1.0 会导致 SL ~2.5× 过紧 |

| v40.0 | Hierarchical Signal Architecture | (1) 删除 3 个重复 4H 投票 (trend_signals 14→11); (2) **指标分类加权 (Layer A)**: `compute_scores_from_features()` 所有三个维度 (trend/momentum/order_flow) 从等权 ±1 改为信息密度加权 `(signal, weight)` 元组——CVD-Price cross 2.0 (Order Flow, 最高信息密度) vs buy_ratio 0.5 (Momentum, 高噪音)，SMA200 1.5 (Trend, 最高确定性) vs RSI_1d 0.6 (Momentum, 弱趋势信号); (3) **TRANSITIONING regime 检测**: order_flow 维度与 trend 维度方向冲突时识别为"过渡期"，2-cycle hysteresis 防 whipsaw，order_flow 不可用时 fallback 到 momentum; (4) **Regime-dependent weighted net (Layer C)**: TRANSITIONING→order_flow 2x, ADX≥40→trend 1.5x, ADX<20→order_flow 1.5x; (5) **背离独立处理 (P0-6)**: 背离信号移出 momentum 投票，作为 trend_score 修正因子，与 v39.0 reversal detection 互斥应用 (避免 -2+-3=-5); (6) **Judge/Bull/Bear prompt 去锚定化**: `_scores.net` 不再作为 analytical anchor，AI 独立评估维度后再 check net; (7) **Alignment 弹性化**: TRANSITIONING + aligned≥1 → LOW confidence trade (30% 仓位探索), aligned=0 → forced HOLD, 提取为 `_enforce_alignment_cap()` 共享方法 (3 处同步); (8) P0-1 zip 映射修复 `(direction, dim_name)` 元组; (9) Auditor regex 兼容 TRANSITIONING labels; (10) TP 参数 V40c: HIGH 2.0→1.5, MED/LOW 1.8→1.3。**ADX 阶梯权重已知限制**: ADX 20/40 边界跳变通过 2-cycle hysteresis 缓解 (非连续函数)。**跨层最大有效权重比**: 8:1 (CVD-Price 2.0 × order_flow 2.0 vs buy_ratio 0.5 × trend 1.0)，由 hysteresis + LOW confidence + aligned≥1 三层防护缓解 |

| v41.0 | Unified Indicator Classification | `_SIGNAL_ANNOTATIONS` nature labels 从 4 种时间分类 (Lagging/Sync/Sync-lag/Quality) 统一为 7 种功能分类 (Trend/Momentum/Order Flow/Volatility/Risk/Structure/Context)，与 `compute_scores_from_features()` 5 维评分系统对齐。`SIGNAL_CONFIDENCE_MATRIX` 全部 Nature 列同步更新 (~16 种时间标签→7 种功能标签)。`INDICATOR_KNOWLEDGE_BRIEF` Section 7 重写为功能分类体系含 regime-dependent 优先级。**纯展示层变更**: nature 标签仅在 `report_formatter.py:322` 消费用于格式化显示 (`f"— {nature}, {multiplier}"`)，无任何逻辑分支依赖 nature 值。所有 regime multiplier 数值 `{'strong': X, 'weak': Y, 'ranging': Z}` 保持不变。删除废弃脚本 `experiment_reliability_format.py` (Occam's razor)。**原子回滚**: `git revert <hash>` 单次提交即可完全回滚 |

| v42.0 | ET Exhaustion Mechanism | 镜像 v21.0 FR exhaustion 设计，打破 Entry Timing Agent 连续 REJECT 死循环。**两级渐进响应**: Tier 1 (≥5 次连续 REJECT): ET REJECT 被覆盖，信号强制放行为原方向 + LOW confidence (30% 小仓位探索)；Tier 2 (≥8 次): ET API 调用完全跳过，Judge confidence 保留。**One-shot**: 每次触发只放行一笔，计数器减 3 (非归零，保留近期压力记忆)。成功开仓后计数器归零 (镜像 FR reset 语义)。**数据验证**: 120h 反事实回测 N=5 产生 5 笔交易 (3 TP/1 SL/1 open)，净 PnL +1.98% vs 现实 0 笔 0%。`ai_strategy.py` 新增 `_ET_EXHAUSTION_TIER1=5` / `_ET_EXHAUSTION_TIER2=8` 常量。`multi_agent_analyzer.py:analyze()` 新增 `skip_entry_timing` 参数。Telegram `/status` 显示 exhaustion tier 状态。**原子回滚**: `git revert <hash>` 单次提交即可完全回滚 |
| v42.1 | Close Reason Fix + ET Tier 1 Risk Manager Fix + Reduce Guard + Pyramiding Gate | (1) `event_handlers.py:on_order_filled()` fallback close reason 从二元判断 (STOP_MARKET=SL, else=TP) 改为 4-way dispatch: TRAILING_STOP_MARKET→追踪止损, STOP_MARKET→止损, LIMIT_IF_TOUCHED→止盈, else→手动/其他。修复 MARKET 平仓被误判为"止盈"导致亏损交易显示 TP 标签。(2) ET Exhaustion Tier 1 override 从 `ai_strategy.py` post-analyze 移入 `multi_agent_analyzer.py:analyze()` 内部 (ET REJECT 之后、Risk Manager 之前)，修复 override 后 Risk Manager 仍看到 HOLD→skip→passthrough `position_size_pct=0` 导致零仓位的 bug。`analyze()` 新增 `et_exhaustion_tier1: bool` 参数。(3) `position_manager.py:_reduce_position()` 部分层级减仓时，layer quantity 更新改为 resubmit 成功后才持久化；resubmit 失败时恢复原值 + 立即 `_submit_emergency_sl()` 兜底，消除 quantity 已减但无 SL/TP 保护的窗口。(4) `pyramiding.min_confidence`: HIGH→MEDIUM，已有浮盈仓位 (≥0.5× ATR) 用 MEDIUM confidence 加仓风险可控，解决 HIGH 门槛过严导致加仓长期无法触发的问题。**已知限制**: REDUCE 信号为架构性死代码 (Judge schema 不含 REDUCE, `_reduce_position()` 不可达)，待后续版本处理 |

| v43.0 | Trailing Stop 4H ATR Migration | Trailing stop ATR 源从 30M (`_cached_atr_value`) 迁移至 4H (`_cached_atr_4h`)，与 v39.0 SL/TP ATR 源统一。**参数变更**: `_TRAILING_ATR_MULTIPLIER`: 1.5→0.6 (4H 尺度)；`_TRAILING_ACTIVATION_R`: 1.1→1.5 (匹配更宽的 4H callback 距离)。**根因**: v39.0 将 SL/TP 迁移至 4H ATR 但 trailing 仍用 30M ATR，导致 trailing callback 仅为 SL 距离的 ~30-37%，正常价格波动频繁触发 trailing stop，本该持有到 TP 的交易被提前止出。**修复后比例**: trailing callback (4H_ATR×0.6) ≈ SL 距离 (4H_ATR×1.0) 的 60%，合理容忍波动。4 个策略文件 (order_execution/event_handlers/safety_manager/position_manager) + backtest_from_logs + 5 个诊断脚本同步更新。所有 ATR 引用改为 `self._cached_atr_4h or self._cached_atr_value` (4H 优先, 30M fallback)。**⚠️ 原子回滚**: ATR source (4H) 与 multiplier (0.6) 是**耦合设计** — 回滚必须同时 revert。单独回滚 multiplier 回 1.5 但保留 4H ATR 会导致 trailing 距离 ~2.5× 过宽；单独回滚 ATR source 回 30M 但保留 0.6 会导致 trailing ~2.5× 过紧 |

### 技术指标一览

| # | 指标 | 周期 | 用途 | 首次版本 |
|---|------|------|------|---------|
| 1 | SMA | 5, 20, 50, 200 | 趋势跟踪、交叉检测 | v1.0 |
| 2 | EMA | 12, 26 | MACD 参考 | v1.0 |
| 3 | RSI (Wilder's) | 14 | 超买超卖、背离检测 | v1.0 |
| 4 | MACD | 12/26/9 | 趋势+动量背离 | v1.0 |
| 5 | Bollinger Bands | 20, 2σ | Squeeze 检测、价格极端 | v1.0 |
| 6 | ADX / +DI / -DI | 14 | 趋势强度 (RANGING/WEAK/STRONG/VERY_STRONG) | v14.2 |
| 7 | ATR (Wilder's) | 14 | 波动率、SL/TP 距离 | v6.5 |
| 8 | Volume MA | 20 | 成交量比率 | v1.0 |
| 9 | ATR Extension Ratio | Per SMA | `(Price-SMA)/ATR` 价格偏离度 | v19.1 |
| 10 | ATR Volatility Regime | 90-bar lookback | ATR% 百分位 (LOW/NORMAL/HIGH/EXTREME) | v20.0 |
| 11 | OBV | Running sum + EMA(20) | 宏观成交量积累/派发 | v20.0 |

### 仓位计算方法

| 方法 | 说明 | 公式 |
|------|------|------|
| `ai_controlled` (默认) | AI 控制仓位大小 | `max_usdt × (AI_size_pct/100) × appetite_scale × risk_multiplier` |
| `hybrid_atr_ai` | ATR 基础 × AI 乘数 | `ATR_position × AI_multiplier` |
| `atr_based` | 纯 ATR | `dollar_risk / (ATR × mult / price)` |
| `fixed_pct` | 固定百分比 (legacy) | `base_usdt × conf_mult × trend_mult × rsi_mult` |

### Trailing Stop (v24.0-v24.2)

Binance 原生 `TRAILING_STOP_MARKET` (服务端追踪止损)：
- **激活**: 入场 + 1R 利润时激活
- **回调率**: `1.5×ATR / entry_price`，钳制到 [10, 1000] bps (0.1%-10%)
- **v24.2**: 已有仓位层的 trailing 自动回补 (`_backfill_trailing_for_existing_layers`)
- 与固定 SL 并存，trailing 保护利润，固定 SL 保护本金

## 📋 配置管理

### 分层架构

```
Layer 1: 代码常量 (业务规则，不可配置)
Layer 2: configs/base.yaml (所有业务参数)
Layer 3: configs/{env}.yaml (环境覆盖: production/development/backtest)
Layer 4: ~/.env.algvex (仅 API keys 等敏感信息)
```

| 数据类型 | 正确来源 | 错误做法 |
|---------|---------|---------|
| **敏感信息** (API keys) | `~/.env.algvex` | ❌ 写在代码或 YAML 中 |
| **业务参数** (止损比例等) | `configs/*.yaml` | ❌ 环境变量或代码硬编码 |
| **环境差异** (日志级别等) | `configs/{env}.yaml` | ❌ 在代码中 if/else 判断 |

### ConfigManager 使用

```python
from utils.config_manager import ConfigManager
config = ConfigManager(env='production')
config.load()
temperature = config.get('ai', 'deepseek', 'temperature')
```

### 命令行环境切换

```bash
python3 main_live.py --env production    # 生产 (20分钟, INFO)
python3 main_live.py --env development   # 开发 (1分钟, DEBUG)
python3 main_live.py --env backtest      # 回测 (无Telegram)
python3 main_live.py --env development --dry-run  # 验证配置
```

### 环境变量 (~/.env.algvex)

```bash
# ===== 仅敏感信息 =====
BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
DEEPSEEK_API_KEY=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
# v14.0: 通知频道机器人 (独立 bot，可选。交易信号+业绩专用)
TELEGRAM_NOTIFICATION_BOT_TOKEN=xxx   # 通知频道机器人 token
TELEGRAM_NOTIFICATION_CHAT_ID=xxx     # 通知频道 chat_id
COINALYZE_API_KEY=xxx          # 可选，无则自动降级
# ❌ 禁止放业务参数 (EQUITY, LEVERAGE 等应在 configs/*.yaml)
```

### 关键策略参数 (configs/base.yaml)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `position_sizing.method` | ai_controlled | 仓位计算方法 |
| `max_position_ratio` | 0.12 | 最大仓位比例 (10x杠杆下控制总仓位) |
| `min_confidence_to_trade` | LOW | 最低信心 (v38.1: MEDIUM→LOW, 30% 小仓位积累数据, 回测 Plan B 正期望 +0.14%/笔) |
| `trading_logic.min_rr_ratio` | 1.3 | R/R 硬性门槛 (v40.0: 从 1.5 降为 1.3，与 tp_rr_target 对齐) |
| `trading_logic.counter_trend_rr_multiplier` | 1.3 | 逆势 R/R 倍数 (1.3×1.3=1.69) |
| `deepseek.model` | deepseek-chat | AI 模型 |
| `deepseek.temperature` | 0.3 | 温度参数 |
| `deepseek.enable_thinking` | true | DeepSeek V3.2 思维链推理 (v32.0) |
| `debate_rounds` | 2 | 辩论轮数 |
| `timer_interval_sec` | 1800 (base) / 1200 (production) | 分析间隔 (秒)，生产环境 20 分钟 |
| `pyramiding.min_confidence` | MEDIUM | 加仓最低信心 (v42.1: HIGH→MEDIUM, 已有浮盈仓位风险可控) |
| `pyramiding.min_profit_atr` | 0.5 | 加仓最低浮盈 (0.5× ATR) |

完整参数列表参见 `configs/base.yaml`。

## 🚨 服务器操作铁律 (每次必须遵守)

**给 AI 助手的强制要求**：向用户提供服务器命令时，必须满足以下三点，缺一不可：

### 1. 每条命令都必须先 cd
```bash
# ❌ 错误 (会报 "not a git repository" 或 "No such file or directory")
git pull origin main
python3 scripts/xxx.py

# ✅ 正确 (始终以 cd 开头)
cd /home/linuxuser/nautilus_AlgVex && git pull origin main
cd /home/linuxuser/nautilus_AlgVex && python3 scripts/xxx.py
```

### 2. checkout 后必须 pull，再运行脚本
```bash
# ❌ 错误 (branch 显示 "behind by N commits" 却没有 pull 就直接运行)
git checkout some-branch
python3 scripts/xxx.py   # 运行的是旧代码！

# ✅ 正确
cd /home/linuxuser/nautilus_AlgVex && \
  git fetch origin <branch> && \
  git checkout <branch> && \
  git pull origin <branch> && \
  source venv/bin/activate && \
  python3 scripts/xxx.py
```

### 3. 提供给用户的命令必须是完整一行可直接粘贴的
```bash
# ✅ 标准模板
cd /home/linuxuser/nautilus_AlgVex && git pull origin claude/<branch> && source venv/bin/activate && python3 scripts/xxx.py [args]
```

> **根本原因**：用户每次 SSH 登录后默认在 `/home/linuxuser`，不在项目目录。不加 `cd` 必然报错。这是已发生过的真实错误，必须在所有命令中避免。

---

## 常用命令

```bash
# 全面诊断
python3 scripts/diagnose.py              # 运行全部检查
python3 scripts/diagnose.py --quick      # 快速检查
python3 scripts/diagnose.py --update --restart  # 更新+重启

# 实时诊断 (调用真实 API)
python3 scripts/diagnose_realtime.py
python3 scripts/diagnose_realtime.py --summary   # 仅关键结果
python3 scripts/diagnose_realtime.py --export --push  # 导出+推送

# 回归检测 (代码修改后必须运行)
python3 scripts/smart_commit_analyzer.py

# S/R Hold Probability 校准 (v16.0)
python3 scripts/calibrate_hold_probability.py                  # 交互式
python3 scripts/calibrate_hold_probability.py --auto-calibrate # Cron 模式
python3 scripts/calibrate_hold_probability.py --dry-run        # 预览不保存

# 交易频率诊断 (v2.0, 24-48h 日志分析 + SL/TP 效能)
python3 scripts/diagnose_trade_frequency.py
python3 scripts/diagnose_trade_frequency.py --hours 48

# 回测套件 (v37.0+)
python3 scripts/backtest_counterfactual.py              # 被拒信号反事实分析
python3 scripts/backtest_counterfactual.py --hours 72   # 自定义时间范围
python3 scripts/backtest_from_logs.py                   # 生产级多层仓位回测 (v3.0)
python3 scripts/backtest_from_logs.py --days 30         # 自定义天数
python3 scripts/backtest_confidence_compare.py          # Confidence 级别对比
python3 scripts/backtest_param_compare.py               # SL/TP 参数矩阵对比

# 仓位管理压力测试 (需先停止生产服务)
sudo systemctl stop nautilus-trader
python3 scripts/stress_test_position_management.py
sudo systemctl start nautilus-trader

# 服务器操作
sudo systemctl restart nautilus-trader
sudo journalctl -u nautilus-trader -f --no-hostname
```

### 服务器代码同步 (一行命令)

```bash
cd /home/linuxuser/nautilus_AlgVex && sudo systemctl stop nautilus-trader && git fetch origin main && git reset --hard origin/main && find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null && echo "=== 最近提交 ===" && git log --oneline -5 && source venv/bin/activate && python3 scripts/diagnose_realtime.py
```

## 部署/升级

```bash
# 一键清空重装
curl -fsSL https://raw.githubusercontent.com/FelixWayne0318/AlgVex/main/reinstall.sh | bash

# 普通升级
cd /home/linuxuser/nautilus_AlgVex && git pull origin main && chmod +x setup.sh && ./setup.sh

# systemd 服务
sudo cp nautilus-trader.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable nautilus-trader && sudo systemctl restart nautilus-trader
```

## 🧪 Backtest & Stress Test Suite (v3.0)

### 回测工具链

| 脚本 | 行数 | 用途 | 版本 | 输出 |
|------|------|------|------|------|
| `backtest_counterfactual.py` | 826 | 被拒信号反事实分析 (ET/FR/confidence 过滤的 what-if) | v1.0 | `data/backtest_counterfactual_result.json` |
| `backtest_from_logs.py` | 1,997 | 生产级多层仓位回测 (pyramiding + trailing stop 仿真) | v3.0 | `data/backtest_from_logs_result.json` |
| `backtest_confidence_compare.py` | 665 | Confidence 级别参数优化 (6 plan × with/without gates) | v3.0 | `data/backtest_confidence_compare.json` |
| `backtest_param_compare.py` | 936 | SL/TP 参数矩阵对比 (4 set × 3 fee scenarios) | v2.0 | `data/backtest_param_compare_result.json` |
| `stress_test_position_management.py` | 1,390 | 仓位管理异常场景压力测试 (8 大类 30+ 子场景) | v1.0 | Console pass/fail report |

### backtest_from_logs.py v3.0 Production Simulator

生产级仿真器，完全镜像 live 系统行为：
- **多层仓位**: 同方向信号叠加层 (最多 7 层)，每层独立 SL/TP
- **Trailing Stop**: 1.5R 利润激活，0.6× 4H ATR callback，钳制 [10, 1000] bps (v43.0)
- **LIFO 减仓**: 最新层先平
- **仓位 sizing**: `confidence_mapping {HIGH:80%, MED:50%} × appetite_scale(0.8) × max_ratio(0.12)`
- **费用仿真**: 0.075% × 2 (round-trip) + 0.03% SL slippage
- **Production Gates**: cooldown (40min) + CB (3 SL→4h, 2 SL→0.5×) + dedup + market change + daily loss (3%) + DD breaker (10%→REDUCED, 15%→HALT)

### 压力测试覆盖 (stress_test_position_management.py)

| 类别 | 场景数 | 覆盖内容 |
|------|--------|---------|
| A. Layer State Machine | 5+ | 层级创建/删除/持久化一致性 |
| B. Emergency Escalation | 5+ | SL 失败 → Emergency SL → Market Close |
| C. Ghost & Orphan | 4+ | 幽灵仓位检测 + 孤立订单清理竞态 |
| D. Restart Recovery | 3+ | Tier 1/2/3 重启恢复 |
| E. Risk Controller | 4+ | 熔断器状态转换 (ACTIVE→REDUCED→HALTED→COOLDOWN) |
| F. Manual Operations | 3+ | 用户在币安手动平仓/取消 SL |
| G. Network & API Errors | 4+ | Binance API 超时/拒绝/-2021/-2022 |
| H. Position Sizing Edge | 3+ | 极端仓位计算 (零余额/极小仓位/溢出) |

### 验证链 (推荐执行顺序)

```
1. backtest_counterfactual.py  — 提取信号 + 参数敏感性测试
   ↓
2. backtest_from_logs.py       — 全仿真 (多层 + gates + trailing)
   ↓
3. backtest_confidence_compare.py — Confidence 层级盈利性
   ↓
4. backtest_param_compare.py   — SL/TP + dedup 影响分析
   ↓
5. stress_test_position_management.py — 异常场景压力测试
```

## 📝 Telegram 显示术语规范

用户端 Telegram 消息**禁止**出现原始英文 LONG/SHORT/BUY/SELL，必须使用中国期货行业标准术语（币安/OKX/Bybit 中文版一致）。

### 标准术语表

| 场景 | 标准中文 | ❌ 禁止使用 | `side_to_cn()` action |
|------|---------|-------------|----------------------|
| 开仓方向 | **开多** / **开空** | 做多、买入、LONG、BUY | `'open'` |
| 平仓方向 | **平多** / **平空** | 卖出、SELL、CLOSE LONG | `'close'` |
| 持仓状态 | **多仓** / **空仓** | LONG、SHORT、多头、空头 | `'position'` |
| 简短标签 | **多** / **空** | LONG、SHORT | `'side'` |

### 唯一入口: `TelegramBot.side_to_cn()`

```python
# utils/telegram_bot.py — 所有方向显示必须通过此方法
TelegramBot.side_to_cn(side, action)
# side:   'LONG' | 'SHORT' | 'BUY' | 'SELL'
# action: 'open' | 'close' | 'position' | 'side'
```

### 已覆盖位置

| 模块 | 方法 | 用法 |
|------|------|------|
| `telegram_bot.py` | 心跳 (`_send_heartbeat`) | `side_to_cn(side, 'position')` → 多仓/空仓 |
| `telegram_bot.py` | 交易执行 (`format_trade_execution`) | `side_to_cn(side, 'side')` + signal_map 开多/开空 |
| `telegram_bot.py` | 持仓更新 (`format_position_update`) | `side_to_cn(side, 'side')` → 开多仓/平空仓 |
| `telegram_bot.py` | 状态查询 (`format_status_response`) | `side_to_cn(side, 'position')` → 多仓/空仓 |
| `telegram_bot.py` | 持仓查询 (`format_position_response`) | `side_to_cn(side, 'position')` → 多仓 |
| `telegram_bot.py` | 加减仓 (`format_scaling_notification`) | `side_to_cn(side, 'side')` → 加仓 — 多 |
| `telegram_command_handler.py` | 平仓确认对话框 (×2) | inline `多仓`/`空仓` |
| `telegram_commands.py` | `_cmd_orders` | inline 开多/开空/平多/平空 (reduce_only 判断) |
| `telegram_commands.py` | `_cmd_history` | inline 开多/开空/平多/平空 (realizedPnl 判断) |
| `telegram_commands.py` | `_cmd_risk` | inline 多仓/空仓 (持仓状态) |
| `telegram_commands.py` | `_cmd_modify_sl` | inline 多仓止损/空仓止损 (验证错误消息) |
| `telegram_commands.py` | `_cmd_modify_tp` | inline 多仓止盈/空仓止盈 (验证错误消息) |
| `telegram_commands.py` | `_cmd_close` / `_cmd_partial_close` | inline `多仓`/`空仓` |
| `safety_manager.py` | `_submit_emergency_sl` (×2) | `side_to_cn(position_side, 'position')` → 多仓/空仓 |
| `safety_manager.py` | `_emergency_market_close` | `side_to_cn(position_side, 'position')` → 多仓/空仓 |
| `safety_manager.py` | Emergency SL context | `side_to_cn(position_side, 'position')` → 多仓/空仓 |
| `safety_manager.py` | TP resubmit 告警 | `side_to_cn(side, 'position')` → 多仓/空仓 |
| `position_manager.py` | `_check_time_barrier` | `side_to_cn(position_side, 'position')` → 多仓/空仓 |
| `position_manager.py` | Stoploss cooldown 激活 | `side_to_cn(side, 'position')` → 多仓/空仓 |
| `position_manager.py` | 方向反转警告 | `side_to_cn(position_side/signal, 'position'/'side')` |
| `position_manager.py` | Layer quantity 修正 | `side_to_cn(pos_side, 'position')` → 多仓/空仓 |
| `order_execution.py` | 开仓 action_taken | `f'开{side_cn}仓'` |
| `order_execution.py` | 反转 action_taken | inline `多`/`空` |
| `ai_strategy.py` | 平仓 action_taken | `f'平{side_cn}仓'` |
| `ai_strategy.py` | Entry Timing REJECT 通知 | `side_to_cn(_orig_signal, 'side')` → 多/空 |
| `ai_strategy.py` | Risk controller 告警 | `side_to_cn(signal, 'side')` → 多/空 |
| `ai_strategy.py` | ET confidence 降级通知 | `side_to_cn(signal, 'side')` → 多/空 |
| `order_execution.py` | FR exhaustion 降级 (×2) | `side_to_cn(signal/direction, 'side')` → 多/空 |
| `order_execution.py` | Position size zero 告警 | `side_to_cn(signal, 'side')` → 多/空 |
| `telegram_bot.py` | 心跳信号显示 (`_send_heartbeat`) | `side_to_cn(signal, 'open')` → 开多/开空 + signal_map 观望/平仓/减仓 |

### 新增显示代码检查清单

修改或新增 Telegram 消息时，必须确认:
1. 方向显示是否通过 `side_to_cn()` 或遵循上表术语？
2. 是否有 `f"...{side}..."` 直接拼接原始英文 side 到用户消息？→ 改用 `side_to_cn()`
3. 区分"开仓 vs 平仓"时，是否正确判断？(用 `reduce_only` 或 `realizedPnl != 0`)

## 常见错误避免

- ❌ 使用 `python` → ✅ **始终 `python3`**
- ❌ 使用 `main.py` → ✅ `main_live.py`
- ❌ 忘记 `AUTO_CONFIRM=true` → 会卡在确认提示
- ❌ Python 3.11 或更低 → ✅ 必须 3.12+ (NT 1.224.0 要求)
- ❌ 从后台线程访问 `indicator_manager` → ✅ 使用 `_cached_current_price` (Rust 不可跨线程)
- ❌ `nautilus_trader.core.nautilus_pyo3` 指标 → ✅ `nautilus_trader.indicators` (Cython 版本)
- ❌ `__init__.py` 自动导入 → ✅ 直接导入模块 (避免循环导入)
- ❌ `sentiment_data['key']` → ✅ `sentiment_data.get('key', default)` (防 KeyError)
- ❌ 环境变量存业务参数 → ✅ 业务参数只在 `configs/*.yaml`
- ❌ 服务器命令不带 cd → ✅ 始终先 `cd /home/linuxuser/nautilus_AlgVex`（见上方「服务器操作铁律」）
- ❌ git checkout 后忘记 git pull → ✅ checkout 完必须 pull 再运行，否则跑的是旧代码
- ❌ `order_factory.bracket()` + `submit_order_list()` → ✅ 分步提交 (v4.13)
- ❌ TP 用 `order_factory.limit()` (非 position-linked) → ✅ `order_factory.limit_if_touched()` → TAKE_PROFIT (Algo API, position-linked, 自动取消) (v6.6)
- ❌ Risk Manager 重判方向 → ✅ 只设 SL/TP + 仓位 (v4.14)
- ❌ BB/卖墙/OBI 否决方向 → ✅ 只调仓位大小 (v4.14)
- ❌ Bracket 失败回退无保护单 → ✅ CRITICAL 告警 + HOLD (v3.18)
- ❌ 反转交易直接平仓后开仓 → ✅ `_pending_reversal` 两阶段提交 (v3.18)
- ❌ 加仓影响已有层 SL/TP → ✅ 每层独立 SL/TP，加仓创建新层 (v7.2 `_layer_orders`)
- ❌ 重启恢复信任 JSON 不验证交易所 → ✅ Tier 2 交叉验证 `sl_order_id` 是否在交易所存活 (v7.3)
- ❌ Emergency SL 不创建 layer 条目 → ✅ `_submit_emergency_sl` 调用 `_create_layer()` 持久化 (v7.3)
- ❌ `on_stop()` fallback `cancel_all_orders()` → ✅ 保留所有订单，SL/TP 保护优先于清理 (v7.3)
- ❌ Telegram close/partial_close 取消 SL 后平仓失败时不处理 → ✅ 立即 `_submit_emergency_sl()` 防裸仓 (v13.1)
- ❌ 仅 prompt 要求 R/R ≥ 1.3 → ✅ `calculate_mechanical_sltp()` 构造性保证 R/R ≥ 1.3:1 (v40.0: HIGH 1.5:1, MEDIUM/LOW 1.3:1)
- ❌ 逆势交易用同样 R/R 1.3 门槛 → ✅ 逆势自动提升至 1.69:1 (v5.12 `_is_counter_trend`)
- ❌ Funding Rate 精度 4 位 → ✅ 5 位小数 `:.5f` / `round(..., 6)` (匹配 Binance)
- ❌ Telegram 显示原始 LONG/SHORT/BUY/SELL → ✅ `side_to_cn()` 转换为 开多/开空/平多/平空/多仓/空仓
- ❌ Telegram 显示 "多头/空头" → ✅ 持仓状态统一用 "多仓/空仓"（含错误消息、风控查询等）
- ❌ 反思参数放 base.yaml `evaluation.reflection` → ✅ 代码常量 (NautilusTrader StrategyConfig 无法传递自定义配置)
- ❌ 校准参数放 base.yaml → ✅ 代码常量 (LOOKBACK_BARS, FORWARD_SCAN_BARS 等在 `calibrate_hold_probability.py` 中，不经 YAML)
- ❌ 手动编辑 `data/calibration/latest.json` → ✅ 运行 `calibrate_hold_probability.py` 或 Telegram `/calibrate` 自动生成
- ❌ 遍历 `support_zones[1:]`/`resistance_zones[1:]` 访问多个 zones → ✅ v17.0 后列表最多 1 元素，只用 `nearest_support`/`nearest_resistance`
- ❌ 执行层用 15M → ✅ v18.2 迁移至 30M (`execution_bar_type` = 30-MINUTE-LAST-EXTERNAL)
- ❌ 强趋势(ADX≥40)时 4H 权重高于 1D → ✅ Entry Timing Agent 强趋势逆势 REJECT (v23.0, 取代 v18.2 `_check_alignment_gate()`)
- ❌ Ghost position loop 无限重试 → ✅ 3 次 -2022 rejection 后强制 `_clear_position_state()` (v18.2)
- ❌ 技术报告按时间框架分组 → ✅ v18.1 按可靠性层级分组 (Tier 1/2/3)
- ❌ 平仓后立即进入 skip-gate 导致长时间不分析 → ✅ `_force_analysis_cycles_remaining = 2` 强制额外 2 轮分析 (v18.3)
- ❌ Extension ratio 阈值放 base.yaml → ✅ 领域知识常量 (2/3/5 ATR 是行业共识，不应可配置) (v19.1)
- ❌ Extension ratio 影响 `calculate_mechanical_sltp()` → ✅ 纯 RISK 信号，只影响 AI 仓位/入场质量评估，与 SL/TP 正交 (v19.1)
- ❌ 用 Mayer Multiple (Price/SMA200) 检测过度延伸 → ✅ ATR Extension Ratio `(Price-SMA)/ATR` 波动率自适应 (v19.1)
- ❌ AI prompt 中要求 AI 自行检测背离 → ✅ `_detect_divergences()` 预计算 RSI/MACD 背离，以 annotation 形式注入报告 (v19.1)
- ❌ `_format_direction_report()` 截断 30M 数据时丢弃背离标注 → ✅ 截断前提取 30M divergence section，追加到 3-line summary 之后 (v19.1 fix)
- ❌ CVD 数据只显示数值不分析 → ✅ CVD-Price 交叉检测自动标注 ACCUMULATION/DISTRIBUTION/CONFIRMED (v19.1)
- ❌ ADX>40 强趋势中 OVEREXTENDED 也发 ⚠️ WARNING → ✅ 降级为 ℹ️ NOTE，强趋势中 extension 常见且可持续 (v19.1.1)
- ❌ Bull 在强趋势中被迫"承认"追涨风险 → ✅ ADX>40 时仅评估趋势动能，不要求承认 (v19.1.1)
- ❌ Bear 在强趋势中用 extension 作为"强力论据" → ✅ ADX>40 时降权为辅助参考 (v19.1.1)
- ❌ Volatility Regime 阈值放 base.yaml → ✅ 领域知识常量 (30/70/90 百分位)，不经 YAML 配置 (v20.0)
- ❌ Volatility Regime 影响方向判断 → ✅ 纯 RISK/CONTEXT 信号，只影响仓位大小和止损宽度 (v20.0)
- ❌ 用固定 ATR% 阈值判断波动率高低 → ✅ 滚动百分位 (90 bar lookback) 自适应市场结构变化 (v20.0)
- ❌ 原始 OBV 做背离检测 → ✅ EMA(20) 平滑后的 OBV 降低 24/7 crypto 噪音 (v20.0)
- ❌ OBV 单独作为交易信号 → ✅ 需 RSI/MACD/CVD confluence 确认 (40-60% 单独 false positive) (v20.0)
- ❌ OBV 与 CVD 视为冗余 → ✅ 互补：OBV 捕捉宏观成交量流向，CVD 捕捉微观订单流激进度 (v20.0)
- ❌ FR 连续阻止同方向信号仍继续输出该方向 → ✅ `_fr_consecutive_blocks >= 3` 时降级为 HOLD，打破死循环 (v21.0)
- ❌ FR block counter 在平仓时 reset → ✅ 平仓不 reset（FR 压力是市场条件非仓位状态），仅成功开仓后 reset (v21.0)
- ❌ 1D 趋势层无历史时序数据供 AI 分析趋势演变 → ✅ `get_historical_context(count=10)` 注入 10-bar 1D 时序 (ADX/DI/RSI/Price) (v21.0)
- ❌ 用 `_check_alignment_gate()` 硬编码 MTF 验证 → ✅ Entry Timing Agent 智能评估入场时机 (v23.0)
- ❌ Judge 同时评估方向+入场时机 (entry_quality) → ✅ 职责分离：Judge 只评方向/信心，Entry Timing Agent 评入场时机 (v23.0)
- ❌ Risk Manager 评估入场时机风险 (entry_timing_risk) → ✅ 职责分离：Risk Manager 只评仓位/市场结构风险 (v23.0)
- ❌ Entry Timing Agent 可升级 confidence → ✅ 只降不升 (conf_rank 比较强制) (v23.0)
- ❌ Bull/Bear 输出自由文本 → ✅ v27.0 REASON_TAGS 约束 + `_validate_agent_output()` 强制 schema 合规
- ❌ AI prompt 中注入 4K+ tokens INDICATOR_DEFINITIONS → ✅ v28.0 `INDICATOR_KNOWLEDGE_BRIEF` ~500 tokens (structured path)
- ❌ AI 自行综合 10+ 个冲突信号 → ✅ v28.0 `_scores` pre-computed dimensional assessment 锚定分析 (primacy effect)
- ❌ `scripts/high_signal_backtest.py` 存在于 SSoT 依赖表但文件不存在 → ✅ 已清理 (v28.0)
- ❌ Trailing stop 回调率超出 Binance 范围 → ✅ 钳制到 [10, 1000] bps (0.1%-10%) (v24.0)
- ❌ 重启后已有层没有 trailing 保护 → ✅ `_backfill_trailing_for_existing_layers()` 自动补回 (v24.2)
- ❌ Ghost position 一次检测就清除 → ✅ 双确认 (等 2 个周期防 API 抖动) (v24.1)
- ❌ Quality Auditor 只检查 tag 覆盖 → ✅ tag+text 双通道检测 (v29.1), weak-signal 过滤 (v29.3), pre-truncation reasoning (v29.4), 全字段 `_raw_{key}` 保全 (v29.5)
- ❌ `_validate_agent_output()` 只保存 `_raw_reasoning` → ✅ v29.5 所有文本字段 (`reasoning`, `summary`, `rationale`, `reason`) 超长时均保存 `_raw_{key}` 原始版本，auditor 优先使用 `_raw_*`，防止截断文本导致 false citation error
- ❌ Auditor Pattern 3 跨 TF 误归属 (`"1D(ADX=36.8)和4H"` → 错判 4H ADX) → ✅ v29.5 post-validation: Pattern 3 匹配后检查前 20 字符是否有其他 TF 标签，属于其他 TF 则 reject (v29.5)
- ❌ Auditor MTF violation 正则匹配技术描述 (`"30M shows bearish SMA cross"`) → ✅ v29.5 `bearish/bullish` 后跟技术术语 (SMA/MACD/EMA/cross/divergence 等) 时排除匹配，区分"方向论证"和"技术事实描述" (v29.5)
- ❌ 124 个 feature 不做类型检查 → ✅ FEATURE_SCHEMA typed validation in `_validate_agent_output()` (v27.0)
- ❌ Feature snapshot 不持久化 → ✅ `data/feature_snapshots/` 支持 deterministic replay (v27.0)
- ❌ Auditor zone check 匹配 "oversold extension" 为 RSI oversold → ✅ `(?!\s*extension)` negative lookahead 排除 extension 上下文 (v30.4)
- ❌ Entry Timing / Risk coverage text 不用 `_raw_*` fallback → ✅ 统一使用 `_raw_*` 优先，与 Bull/Bear/Judge 一致 (v30.4)
- ❌ MACD crossover check 用 ±100 char 窗口导致跨 TF 误归属 → ✅ 改用 `_claims_near_tf()` 带跨 TF 排除 (v30.5)
- ❌ `_extract_indicator_value` Pattern 3 post-validation 20 char 不足覆盖中文文本 → ✅ 扩展到 50 char (v30.5)
- ❌ `_extract_dollar_value` Pattern 3 无 cross-TF 保护 → ✅ 添加 `_no_tf` guard + post-validation (v30.5)
- ❌ `_DATA_CATEGORY_MARKERS` 中 `.*` 跨上下文误匹配 (如 `ATR.*[Ee]xt` 匹配 "ATR distance...Volatility ext") → ✅ 改为 `.{0,N}` 限定范围 (v30.5)
- ❌ `_SIGNAL_KEY_PATTERNS` 中 `.*` 跨 TF 误触发 (如 `1[Dd].*MACD` 匹配 "1D bearish trend...4H MACD") → ✅ 使用 `_NO_TF` tempered greedy token (v30.5)
- ❌ `_SIGNAL_KEY_PATTERNS` 只有 `4h_macd_h` 无 `1d_macd_h`/`30m_macd_h` → ✅ 三个 TF 均有 MACD histogram signal pattern (v31.2)
- ❌ `_TAG_TO_CATEGORIES` `MACD_HISTOGRAM_*` 仅映射 `['mtf_4h']` → ✅ 扩展至 `['technical_30m', 'mtf_4h']` (v31.2)
- ❌ `MACD Signal` value regex `(?:MACD\s*)?Signal` 误匹配 "Buy Signal" → ✅ 改为 `MACD\s*Signal` 强制前缀 (v31.2)
- ❌ Crossover claim 检测只覆盖 MACD-first 语序 → ✅ 新增 Signal-first 反向语序 + 中文 "信号线下穿/上穿" (v31.2)
- ❌ DI+/DI- 交叉方向仅验证数值比较 (`_audit_di_citations`) 不验证文本声明 → ✅ `_check_comparison_claims()` 新增 "DI bullish/bearish cross" + "DI+上穿/下穿DI-" 文本验证 (v31.3)
- ❌ EMA 12/26 交叉方向无任何 comparison 验证 → ✅ `_check_comparison_claims()` 新增 "EMA bullish/bearish/golden/death cross" + "EMA 金叉/死叉" 验证 (v31.3)
- ❌ `extract_features()` 用 `ema_10`/`ema_20` 键名 → ✅ `ema_12`/`ema_26` 匹配 `ema_periods=[12, 26]` (v31.4)
- ❌ `extract_features()` 用 `pnl_pct`/`size_pct` 字段名 → ✅ `pnl_percentage`/`margin_used_pct` 匹配生产 `_get_current_position_data()` (v31.4)
- ❌ `extract_features()` 用 `liquidation_buffer_pct` 直接取 account → ✅ `liquidation_buffer_portfolio_min_pct` 匹配生产 `_get_account_context()` (v31.4)
- ❌ Judge=HOLD 时仍调用 Risk Manager API (浪费 ~8K tokens) → ✅ 条件跳过，passthrough 默认值，镜像 ET skip 模式 (v32.1)
- ❌ DeepSeek 不启用 thinking mode → ✅ `enable_thinking: true` (V3.2 支持 thinking + json_object 兼容) (v32.0)
- ❌ AI Agent 输出纯英文分析 → ✅ structured prompt 新增中英混输指令，AI 输出遵循 CLAUDE.md 语言规范 (v32.2)
- ❌ Telegram 启动消息显示 "Auto SL/TP"/"Bracket Orders" → ✅ "自动 SL/TP"/"OCO 订单"/"MTF 多时间框架"/"多代理 AI" (v32.2)
- ❌ CVD 信号显示原始 ACCUMULATION/DISTRIBUTION → ✅ 吸筹/派发/吸收/确认 (v32.2)
- ❌ Entry Timing verdict 显示 ENTER/REJECT → ✅ 通过/拦截 (v32.2)
- ❌ 心跳信号标签显示 HOLD/LONG/SHORT → ✅ 观望/开多/开空 (v32.2)
- ❌ 回撤 bar 计算用 `duration_minutes // 15` (旧 15M 执行层) → ✅ `// 30` 匹配 v18.2 执行层 30M (v32.3)
- ❌ Auditor 仅检查 citation 准确性不检查逻辑一致性 → ✅ v34.0 新增 5 个跨维度一致性检查 (reason-signal/score-divergence/confidence-risk/debate-convergence/reason-diversity)
- ❌ Judge LONG 但 decisive_reasons 全是 bearish tags 无任何扣分 → ✅ REASON_SIGNAL_CONFLICT 扣 8/12 分 (v34.0)
- ❌ HIGH confidence 在 HIGH risk 环境无任何警告 → ✅ CONFIDENCE_RISK_CONFLICT 扣 6 分 (v34.0)
- ❌ Bull/Bear 辩论 conviction 趋同 (echo chamber) 无检测 → ✅ DEBATE_CONVERGENCE flag (spread < 0.15) (v34.0)
- ❌ Bull/Bear Round 2 重复 Round 1 (shallow debate) 无检测 → ✅ DEBATE_SHALLOW_R2 flag (evidence overlap ≥ 0.85 + 0 new tags + conviction delta < 0.05) (v34.1)
- ❌ `extract_features()` None→0.0 无法区分 "数据中性" vs "数据缺失" → ✅ 8 个 `_avail_*` boolean flags + `compute_scores_from_features()` 维度排除 + DATA_UNAVAILABLE Step 0 (v34.1)
- ❌ Layer 3 无 quality score → outcome 相关性分析 → ✅ `analyze_quality_correlation.py` 10 项分析 (quintiles/Pearson r/feature importance/rolling performance/confidence recalibration) (v34.1)
- ❌ HOLD 决策无来源分类 → ✅ `hold_source` 6 种路径 (cooldown/gate_skip/dedup/risk_breaker/et_reject/explicit_judge) + `_hold_counterfactual_record` 反事实追踪 (v34.1)
- ❌ `_hold_counterfactual_record` 仅 DEBUG 日志不持久化 → ✅ 写入 `data/hold_counterfactuals.json` (最多 200 条 FIFO)，支持 Layer 3 outcome feedback 分析 (v34.2)
- ❌ `_effective_required()` 对数据不可用的类别仍计入覆盖率惩罚 → ✅ `_AVAIL_TO_CATEGORIES` 映射排除 `_avail_*=False` 对应类别 (v34.2)
- ❌ `compute_scores_from_features()` OBI/liquidation_buffer/top_traders 用 0.0 默认值参与评分 → ✅ `_avail_*` 守卫排除不可用数据源 (v34.2)
- ❌ `extract_features()` CVD-Price cross features 始终返回 `None` → ✅ 正确从 `order_flow_report`/`mtf_decision_layer` 提取 (v34.3)
- ❌ `_avail_sentiment` flag 缺失导致 sentiment 不可用时污染 risk_env 评分 → ✅ 添加 `_avail_sentiment` flag (v34.3)
- ❌ Layer 3 分析函数分散在 `scripts/analyze_quality_correlation.py` 中不可复用 → ✅ `utils/quality_analysis.py` 作为 SSoT 提取 10 个分析函数 (v35.0)
- ❌ 心跳无 Layer 3 outcome feedback 指标 → ✅ 心跳新增 win rate/streak/confidence calibration EV + overconfident/miscalibrated 警告 (v35.0)
- ❌ Layer 3 质量分析仅 CLI 脚本可用 → ✅ `/layer3` Telegram 命令 + Web `/quality` 页面 + 5 个 API 端点 (v35.0)
- ❌ `NEAR_STRONG_SUPPORT` 注释无 strength 字段，AI 误将 tag 名 "STRONG" 当实际强度 → ✅ 注释新增 `strength=LOW/MEDIUM/HIGH`，含具体数值 (v35.1)
- ❌ `SR_BREAKOUT_POTENTIAL`/`SR_REJECTION`/`SR_TRAPPED` 注释无 strength 字段 → ✅ 统一添加 strength + dist 数值 (v35.1)
- ❌ `CVD_ACCUMULATION`/`CVD_DISTRIBUTION`/`CVD_ABSORPTION_*` 注释纯文字描述无数值 → ✅ 添加 CVD 数值 + price change % (v35.1)
- ❌ Tag 注释标准不统一，部分含数值部分纯文字 → ✅ 统一标准：每个 tag 注释必须包含触发数值 + 上下文信息 (v35.1)
- ❌ `extract_features()` 30M 用 `sma_50` 键 → ✅ `sma_5` (30M 只有 `sma_periods=[5,20]`，无 SMA 50) (v36.0)
- ❌ `extract_features()` 1D time series 从 30M `hist_ctx` 取 → ✅ 从 `hist_ctx_1d` (1D `historical_context`) 取 (v36.0)
- ❌ `extract_features()` 4H time series 从 30M `hist_ctx` 取 → ✅ 从 `hist_ctx_4h` (4H `historical_context`) 取 (v36.0)
- ❌ `extract_features()` OBV 用 `obv_ema_trend` 键 → ✅ `obv_trend` (匹配生产 `historical_context` 实际键名) (v36.0)
- ❌ `compute_scores_from_features()` NEUTRAL 维度被 skip → ✅ NEUTRAL/FADING/MIXED 计为 0 分而非跳过，防 length mismatch (v36.0)
- ❌ `compute_scores_from_features()` `liq_buffer=0` 未处理 → ✅ `0 <= liq_buffer < 5` 边界覆盖 (v36.0)
- ❌ BB_SQUEEZE/BB_EXPANSION 为硬编码 tag → ✅ data-driven validation via `bb_width_trend` RISING/FALLING (v36.0)
- ❌ `compute_valid_tags()` 30M SMA crossover 用 SMA 20/50 → ✅ SMA 5/20 匹配 30M 执行层 `sma_periods=[5,20]` (v36.0)
- ❌ `adx_direction_1d` DI+ == DI- 产生虚假 BEARISH → ✅ 三态 BULLISH/BEARISH/NEUTRAL (v36.2)
- ❌ Ghost position `_ghost_first_seen` 永久残留 → ✅ `on_position_closed()` + `_clear_position_state()` 清零 (v36.3)
- ❌ Ghost 检测同 cycle 取消 SL/TP/trailing → ✅ 双确认 + 时间窗口 guard (v36.3)
- ❌ TP 提交失败无重试 → ✅ 2 次尝试 + Tier 2 never-submitted TP 恢复 (v36.3) + on_timer 周期内 `_check_tp_coverage()` 自动恢复 (v36.4)
- ❌ TP 2 次重试都失败后运行期间不会恢复 → ✅ `_check_tp_coverage()` 每个 on_timer 检查所有层 TP 覆盖，`tp_order_id` 为空但 `tp_price > 0` 立即调用 `_resubmit_tp_for_layer()` (v36.4)
- ❌ `_cleanup_orphaned_orders()` 误删刚提交的 SL/TP/trailing → ✅ 时间窗口 guard (仓位 <120s) + layer 匹配 guard (v36.3)
- ❌ `sl_atr_multiplier` Plan I 过紧 (HIGH=1.5) 导致 29 次 SL + circuit breaker 级联跳过 38% 信号 → ✅ v37.1 Plan II: HIGH=1.8/MEDIUM=2.2, SL 率降至 26.2%, CB 跳过降至 26%
- ❌ `tp_rr_target` MEDIUM=1.5 配合紧 SL 导致 TP 命中率不足 → ✅ v37.1: HIGH=2.0/MEDIUM=1.8 (79.5%/61.9% 胜率验证)
- ❌ `min_confidence_to_trade=LOW` 放行 LOW 信心 (v37.0 仅 1 笔 -0.19%) → ✅ v38.1 重新放行: 18.4 天回测 Plan B 正期望 +0.14%/笔, 30% 小仓位+MEDIUM 同参数控制风险, 积累数据优先
- ❌ `sl_atr_multiplier_floor=1.5` 与新 SL multiplier 冲突 (HIGH=1.5 被 floor 钳制) → ✅ floor 降至 1.2 (v37.0)
- ❌ 回测中未匹配 confidence 的信号默认 LOW → ✅ v38.0: None 表示 unknown，过滤而非默认 (防数据污染)
- ❌ HOLD counterfactual 无 `proposed_confidence` 时默认 LOW 参与回测 → ✅ v38.0: 跳过无 confidence 的记录 + `skipped_no_conf` 审计追踪
- ❌ `compute_scores_from_features()` MACD histogram trend 检查 RISING/FALLING → ✅ v38.2: `_classify_abs_trend()` 输出 EXPANDING/CONTRACTING/FLAT，之前永远不匹配导致 4H MACD histogram 对 momentum 评分贡献为零 (90% snapshot 受影响)
- ❌ SL/TP 用 30M ATR 导致日内噪音频繁触发 → ✅ v39.0: 4H ATR 为主 (30M fallback)，multiplier 同步调整为 4H 尺度 (HIGH=0.8/MED=1.0)
- ❌ 1D SMA200 在 trend_score 中双权重压制 4H 信号 → ✅ v39.0: SMA200 降为单权重，新增 3 个 4H 独立趋势信号
- ❌ 趋势衰竭时系统仍锁定原方向 → ✅ v39.0: 5 条件反转检测 (≥3 触发)，trend_score 减 3 (min 1)
- ❌ market_regime 仅用 1D ADX (4H 已强趋势但 1D 未跟上时误判 RANGING) → ✅ v39.0: `max(1D, 4H)` ADX + 日志记录 source
- ❌ 单独回滚 v39.0 ATR source 或 multiplier → ✅ 必须原子回滚 (`git revert <hash>`)。ATR source (4H) 与 multiplier (0.8/1.0) 耦合设计，拆分回滚导致 SL 距离 2.5-2.75× 偏差
- ❌ `_available_dirs` 和 weight keys 用 zip 并行映射 → ✅ 使用 `(direction, dim_name)` 元组数组防映射错位 (v40.0)
- ❌ Alignment enforcement 只更新 1 处 → ✅ 3 处同步 (L2217/L4047/L4449)，提取为 `_enforce_alignment_cap()` (v40.0)
- ❌ `tp_rr_target` HIGH=2.0/MED=1.8 过高导致 TP 命中率低 → ✅ HIGH=1.5/MED=1.3 (v40.0 V40c 回测验证，逆势仍被 min_rr×ct_mult=1.95 覆盖)
- ❌ `compute_scores_from_features()` 所有指标等权 ±1 投票 → ✅ v40.0 Layer A 信息密度加权 (CVD-Price 2.0 vs buy_ratio 0.5)
- ❌ TRANSITIONING regime 在单个周期就触发交易 → ✅ 2-cycle hysteresis 防抖 (v40.0)
- ❌ 背离信号混在 momentum 投票中被 ~10 个趋势信号稀释 → ✅ v40.0 移出为独立 trend_score 修正因子，与 reversal detection 互斥
- ❌ ET 连续 REJECT 10+ 次仍继续拦截 (死循环) → ✅ v42.0 ET Exhaustion: Tier 1 (≥5) 覆盖 REJECT→LOW 放行，Tier 2 (≥8) 跳过 ET
- ❌ ET Exhaustion 触发后计数器归零导致下次又要积累 5 次 → ✅ 计数器减 3 (非归零)，保留近期压力记忆 (v42.0)
- ❌ ET Exhaustion 放行后无仓位控制 → ✅ Tier 1 强制 LOW confidence (30% 最小仓位)，风险可控 (v42.0)
- ❌ 非 STOP_MARKET 平仓单一律判为 TAKE_PROFIT → ✅ 4-way dispatch: TRAILING_STOP_MARKET/STOP_MARKET/LIMIT_IF_TOUCHED/其他 (v42.1)
- ❌ ET Exhaustion Tier 1 override 在 `analyze()` 返回后执行，Risk Manager 已 skip → ✅ override 移入 `analyze()` 内部，在 ET REJECT 后、Risk Manager 前执行 (v42.1)
- ❌ `_reduce_position()` 部分减仓时 layer quantity 在 resubmit 前更新 → ✅ resubmit 失败时恢复原值 + emergency SL 兜底 (v42.1)
- ❌ `pyramiding.min_confidence: HIGH` 导致加仓长期无法触发 → ✅ 降为 MEDIUM，已有浮盈仓位风险可控 (v42.1)
- ❌ Judge schema 不含 REDUCE，`_reduce_position()` 是死代码 → ⚠️ 已知限制，待后续版本处理 (v42.1 documented)
- ❌ Trailing stop 使用 30M ATR 但 SL/TP 使用 4H ATR → ✅ v43.0: trailing 迁移至 4H ATR (`_cached_atr_4h or _cached_atr_value`)，multiplier 1.5→0.6，activation 1.1R→1.5R
- ❌ 单独回滚 v43.0 ATR source 或 multiplier → ✅ 必须原子回滚 (`git revert <hash>`)。ATR source (4H) 与 multiplier (0.6) 耦合设计，拆分回滚导致 trailing 距离严重偏差

## 文件结构

```
/home/user/AlgVex/
├── main_live.py              # 入口文件 (765 行)
├── setup.sh / reinstall.sh   # 部署脚本
├── requirements.txt          # Python 依赖 (NT 1.224.0, empyrical-reloaded 等)
├── nautilus-trader.service    # systemd 服务
│
├── strategy/                 # 策略模块 (mixin 架构, 15,411 行)
│   ├── ai_strategy.py        # 主策略入口 + 核心循环 + HOLD counterfactual (5,263 行)
│   ├── event_handlers.py     # 事件回调 mixin (on_order_*, on_position_*) + ghost/orphan guards (2,073 行)
│   ├── order_execution.py    # 订单执行 mixin (_execute_trade, trailing stop) (1,528 行)
│   ├── position_manager.py   # 仓位管理 mixin (层级订单, 加仓/减仓, 反思) (1,792 行)
│   ├── safety_manager.py     # 安全管理 mixin (emergency SL, 孤立检测, TP 恢复) (1,064 行)
│   ├── telegram_commands.py  # Telegram 命令 mixin (/close, /modify_sl 等) (2,271 行)
│   └── trading_logic.py      # 交易逻辑 + evaluate_trade() 评估 (SSoT) (1,371 行)
│
├── agents/                   # 多代理系统 (15,500 行)
│   ├── multi_agent_analyzer.py # Bull/Bear/Judge/EntryTiming/Risk 核心 + v27.0 structured debate (4,946 行)
│   ├── prompt_constants.py   # INDICATOR_DEFINITIONS/KNOWLEDGE_BRIEF + FEATURE_SCHEMA + REASON_TAGS (1,485 行)
│   ├── report_formatter.py   # 报告格式化 mixin + compute_scores + _avail_* flags + v36.x fixes (3,214 行)
│   ├── tag_validator.py      # REASON_TAGS 验证 + compute_valid_tags/annotated_tags + v36.0 全覆盖 (1,097 行)
│   ├── ai_quality_auditor.py # AI 输出质量审计 (v24.0-v36.1, 6 维+5 逻辑一致性) (3,188 行)
│   ├── analysis_context.py   # 分析上下文数据类 (198 行)
│   └── memory_manager.py     # 记忆系统 mixin (评分/反思/extended reflections) (1,174 行)
│
├── indicators/               # 技术指标 (1,420 行)
│   ├── technical_manager.py  # Cython 指标 + ATR Extension/Volatility Regime (1,112 行)
│   └── multi_timeframe_manager.py # 三层 MTF 管理 (1D/4H/30M) (301 行)
│
├── utils/                    # 工具模块 (13,274 行)
│   ├── config_manager.py     # 统一配置管理器 (30+ 验证规则) (490 行)
│   ├── ai_data_assembler.py  # 13 类数据聚合 (SSoT, v7.0) (971 行)
│   ├── telegram_bot.py       # Telegram 双频道通知 (v14.0) + /layer3 命令 (v35.0) (2,064 行)
│   ├── telegram_command_handler.py # Telegram 命令 + PIN 验证 (v3.0) (1,048 行)
│   ├── telegram_queue.py     # SQLite 持久化消息队列 (458 行)
│   ├── binance_kline_client.py       # K线 + 订单流 + CVD + FR (242 行)
│   ├── binance_derivatives_client.py # Top Traders 多空比 (463 行)
│   ├── binance_orderbook_client.py   # 订单簿深度 (217 行)
│   ├── binance_account.py    # 账户工具 (HMAC 签名 + 时间同步) (819 行)
│   ├── coinalyze_client.py   # OI + Liquidations (497 行)
│   ├── sentiment_client.py   # Binance 全球多空比 (215 行)
│   ├── sr_zone_calculator.py # S/R 区域计算 (v17.0: 1+1) (2,062 行)
│   ├── sr_pivot_calculator.py # Floor Trader Pivot Points (118 行)
│   ├── sr_swing_detector.py  # Williams Fractal + 成交量加权 (217 行)
│   ├── sr_volume_profile.py  # VPOC + Value Area (173 行)
│   ├── sr_types.py           # S/R 数据类型定义 (69 行)
│   ├── order_flow_processor.py  # 订单流处理 (CVD, taker buy ratio) (204 行)
│   ├── orderbook_processor.py   # 订单簿处理 (OBI, 滑点, 动态) (811 行)
│   ├── risk_controller.py    # 风险熔断器 (drawdown/daily loss/consecutive loss) (591 行)
│   ├── calibration_loader.py # 校准数据加载 (mtime 缓存) (289 行)
│   ├── backtest_math.py      # 回测共享数学 (ATR Wilder's, SL/TP, SMA/BB) (185 行)
│   ├── shared_logic.py       # SSoT 共享逻辑常量 (Extension/Volatility/CVD) (139 行)
│   ├── quality_analysis.py   # Layer 3 质量分析 SSoT (10 个分析函数, v35.0) (447 行)
│   └── audit_logger.py       # 审计日志 (SHA256 hash chain) (472 行)
│
├── configs/                  # 配置 (分层架构)
│   ├── base.yaml             # 基础配置 (所有参数, SSoT)
│   ├── production.yaml       # 生产环境覆盖 (timer=1200s, INFO)
│   ├── development.yaml      # 开发环境覆盖 (1m timeframe, DEBUG)
│   └── backtest.yaml         # 回测环境覆盖 (无 Telegram)
│
├── scripts/                  # 脚本工具 (48,217 行)
│   ├── diagnostics/          # 诊断模块 (15 个检查步骤)
│   │   ├── base.py           # 诊断基类 + 上下文 (1,072 行)
│   │   ├── code_integrity.py # 114 项静态分析 (P1.0-P1.113) (3,539 行)
│   │   ├── ai_decision.py    # AI 决策验证 (5~7+1 次真实调用 + Entry Timing 独立测试) (4,114 行)
│   │   ├── architecture_verify.py # 20+ 架构合规检查 (v7.2/v12.0/v14.0/v24.0) (1,990 行)
│   │   ├── order_flow_simulation.py # 15 场景订单流程模拟 (含 trailing stop) (1,845 行)
│   │   ├── config_checker.py # 配置验证 (549 行)
│   │   ├── indicator_test.py # 指标计算验证 (371 行)
│   │   ├── math_verification.py # 16 项数学公式验证 (M1-M16) (1,236 行)
│   │   ├── market_data.py    # 市场数据获取 (205 行)
│   │   ├── mtf_components.py # MTF + Telegram + 错误恢复 (724 行)
│   │   ├── position_check.py # 仓位 + 记忆系统 + 裸仓扫描 (1,219 行)
│   │   ├── service_health.py # systemd 服务状态 (411 行)
│   │   ├── lifecycle_test.py # 交易生命周期测试 (256 行)
│   │   └── summary.py        # 数据流总结 + JSON 导出 (707 行)
│   ├── diagnose.py           # 离线诊断 (13 检查, 1,159 行)
│   ├── diagnose_realtime.py  # 实时 API 诊断 (12 阶段, 513 行)
│   ├── diagnose_quality.py   # AI 输出质量分析 (feature snapshot + log 解析) (438 行)
│   ├── diagnose_quality_scoring.py # 生产数据全面评分测试 (17 阶段, v36.4) (2,933 行)
│   ├── diagnose_quality_deductions.py # AI 质量审计扣分规则详情 (816 行)
│   ├── diagnose_v31_6_auditor.py # Auditor v31.6/v31.7 专项验证 (46 检查) (932 行)
│   ├── diagnose_auditor_v33.py # Auditor v33.x 6 维验证 (regex 精度+评分边界) (681 行)
│   ├── diagnose_trade_frequency.py # 交易频率 + SL/TP 效能诊断 (v2.0, 24-48h 日志分析) (866 行)
│   ├── diagnose_feature_pipeline.py # Feature Pipeline 诊断 (v36.0, extract_features 验证) (1,394 行)
│   ├── smart_commit_analyzer.py # 自进化回归检测 (722 行)
│   ├── check_logic_sync.py   # SSoT 逻辑同步检查 (14 检查项) (410 行)
│   ├── calibrate_hold_probability.py # S/R Hold Probability 自动校准 (936 行)
│   ├── test_thinking_json_compat.py # DeepSeek V3.2 Thinking+JSON 兼容性测试 (272 行)
│   ├── verify_extension_ratio.py # ATR Extension Ratio 4 阶段验证 (472 行)
│   ├── verify_indicators.py  # 技术指标计算验证 (v4.0 全覆盖) (2,017 行)
│   ├── validate_data_pipeline.py # 13 类数据管线验证 (3,579 行)
│   ├── validate_production_sr.py # 生产 S/R v17.0 验证 (546 行)
│   ├── backtest_high_signals.py # 高信心信号回测 (694 行)
│   ├── backtest_sr_zones.py  # S/R 区域历史回测 (1,387 行)
│   ├── backtest_counterfactual.py # 被拒信号反事实回测 (rejected/filtered 信号 what-if 分析) (826 行)
│   ├── backtest_from_logs.py # 生产级日志信号回测 (v3.0, 多层仓位+trailing stop 仿真) (1,997 行)
│   ├── backtest_confidence_compare.py # Confidence 级别参数对比回测 (HIGH/MEDIUM/LOW 最优参数) (665 行)
│   ├── backtest_param_compare.py # SL/TP 参数矩阵对比回测 (1M K线仿真) (936 行)
│   ├── stress_test_position_management.py # 仓位管理压力测试 (8 大类 30+ 异常场景) (1,390 行)
│   ├── e2e_trade_pipeline_test.py # 端到端交易管线测试 (15 场景) (1,776 行)
│   ├── replay_ab_compare.py  # A/B 版本 feature snapshot 对比 (298 行)
│   ├── analyze_dependencies.py # 代码依赖分析 (351 行)
│   └── analyze_quality_correlation.py # Layer 3 quality-outcome 相关性分析 (10 项) (193 行)
│
├── data/                     # 数据目录 (运行时生成)
│   ├── trading_memory.json   # 交易记忆 (最多 500 条)
│   ├── layer_orders.json     # 每层 SL/TP 持久化 (v7.2)
│   ├── extended_reflections.json # 扩展反思存储 (v18.0, 最多 100 条)
│   ├── calibration/          # S/R 校准数据 (v16.0)
│   │   ├── latest.json       # 当前校准因子
│   │   └── history/          # 历史校准存档 (最多 12 份)
│   ├── feature_snapshots/    # v27.0 Feature snapshot (deterministic replay)
│   └── hold_counterfactuals.json # HOLD 反事实评估记录 (v34.2, 最多 200 条)
│
├── web/                      # Web 管理界面 (5,554 行后端 + ~35 前端组件)
│   ├── backend/              # FastAPI
│   │   ├── main.py           # FastAPI 入口 (171 行)
│   │   ├── core/             # config.py (205 行), database.py (40 行)
│   │   ├── models/           # settings.py — SocialLink, CopyTradingLink, SiteSettings (49 行)
│   │   ├── api/routes/       # public (395), admin (1,054), auth (104), trading (136), performance (181), websocket (443)
│   │   └── services/         # trade_evaluation, performance, trading, config, signal_log, notification, quality_analysis
│   ├── frontend/             # Next.js 14 + React 18 + TypeScript + Tailwind CSS
│   │   ├── pages/            # index, dashboard, performance, chart, admin, about, copy, quality
│   │   ├── components/       # admin(11), charts(4), trading(6), trade-evaluation(5), layout(2), ui(7)
│   │   ├── hooks/            # useTradeEvaluation.ts, useQualityAnalysis.ts
│   │   └── lib/              # utils.ts (60 行), i18n.ts (136 行, EN+ZH)
│   └── deploy/               # Caddyfile, systemd services, redeploy.sh, setup.sh
│
├── patches/                  # 兼容性补丁 (必须在 NT 导入前加载)
│   ├── binance_enums.py      # 未知枚举处理 (_missing_ hook)
│   └── binance_positions.py  # 非 ASCII 持仓过滤 (币安人生USDT)
│
├── tests/                    # 测试 (22 个文件, 6,642 行)
│   ├── conftest.py           # pytest fixtures (project_root, config, mock_logger, sample_data)
│   ├── test_config_manager.py # ConfigManager (加载/合并/验证)
│   ├── test_trading_logic.py # SL/TP 计算 + 仓位大小
│   ├── test_entry_timing.py  # Entry Timing Agent (v23.0, 4 维评估)
│   ├── test_feature_schema.py # 124 features 类型验证
│   ├── test_multi_agent.py   # 多代理 prompt 结构
│   ├── test_v19_1_verification.py # v19.1 extension/divergence/CVD/OBV
│   ├── test_auditor_v34.py   # v34.0 phantom citation/narrative/contradiction (263 行)
│   ├── test_auditor_v34_integration.py # v34.0 端到端 mock agent 评分 (504 行)
│   ├── test_replay_determinism.py # 确定性重放
│   ├── test_bracket_order.py # OCO 订单流
│   ├── test_telegram.py / test_telegram_commands.py # Telegram 通知+命令
│   ├── test_orderbook.py     # OBI + 订单簿
│   ├── test_sl_fix.py / test_rounding_fix.py # SL + 精度修复
│   ├── test_integration_mock.py / test_strategy_components.py # 集成测试
│   ├── test_binance_patch.py # 枚举补丁
│   ├── test_command_listener.py # 命令监听测试
│   ├── test_implementation_plan.py # 功能实现验证
│   └── manual_order_test.py  # 手动订单测试
├── docs/                     # 文档
└── .github/workflows/        # CI/CD (commit-analysis, codeql, claude)
```

## 🌐 Web 管理界面架构

### 后端 (FastAPI)

**认证**: Google OAuth 2.0 → JWT → admin 白名单 (`ADMIN_EMAILS`)
**数据库**: SQLite (async via aiosqlite) — SocialLink, CopyTradingLink, SiteSettings

| 路由组 | 认证 | 端点数 | 核心功能 |
|--------|------|--------|---------|
| `/api/public/*` | ❌ | 14 | 性能摘要、信号历史、交易评估、系统状态、质量分析摘要 |
| `/api/admin/*` | ✅ | 34+ | 策略配置、服务控制、Telegram 配置、层级订单、安全事件、质量分析详情 |
| `/auth/*` | ❌/✅ | 4 | Google OAuth login/callback/me/logout |
| `/trading/*` | 混合 | 12 | Binance 实时数据 (ticker/klines/orderbook/positions) |
| `/api/performance/*` | ✅ | 8 | 盈亏曲线、通知管理、信号统计 |
| `/ws/*` | 混合 | 6 | WebSocket 实时流 (ticker 1s, account 5s, positions 3s) |

### 前端 (Next.js 14)

**页面**: index (首页), dashboard (管理面板), performance, chart, admin, about, copy, quality (AI 质量分析)
**组件**: 35 个 — admin(11), charts(4), trading(6), trade-evaluation(5), layout(2), ui(7)
**i18n**: EN + ZH (via `lib/i18n.ts`)
**实时数据**: WebSocket 订阅 + SWR 数据获取

## 🎨 Web 前端设计规范 (DipSway 风格)

### 导航栏设计

导航栏采用 **DipSway 风格**：透明背景 + 独立浮动组件组。

| 组件组 | 背景 | 说明 |
|--------|------|------|
| Logo (AlgVex) | 无背景 | Logo 图标 + 文字 |
| 导航链接 | `bg-background/60 backdrop-blur-xl border rounded-xl` | 独立浮动 |
| Bot Status / Signal / Markets | `bg-background/60 backdrop-blur-xl border rounded-xl` | 独立浮动 |
| CTA 按钮 | `bg-gradient-to-r from-primary to-primary/80` | 主色渐变 |

### 响应式设计

| 屏幕 | 显示内容 |
|------|----------|
| 桌面 (lg+) | 全部组件 |
| 手机横屏 | 同桌面 |
| 手机竖屏 | Logo + Bot Status + Signal + 汉堡菜单 |

### Web 部署 (修改网站后必须执行)

```bash
# 一键重新部署 (推荐，解决所有已知显示问题)
cd /home/linuxuser/nautilus_AlgVex && bash web/deploy/redeploy.sh

# 指定分支
cd /home/linuxuser/nautilus_AlgVex && bash web/deploy/redeploy.sh --branch claude/xxx

# 已经 pull 过了，跳过拉代码
cd /home/linuxuser/nautilus_AlgVex && bash web/deploy/redeploy.sh --skip-pull
```

**为什么需要一键脚本**: 之前反复出现 CSS 不加载的问题，根因是部署步骤顺序不对或遗漏:

| 错误做法 | 后果 | 正确做法 |
|---------|------|---------|
| 服务运行中重建 `.next` | 服务读到不完整的构建产物 → 无 CSS | 先停服务 → 重建 → 再启动 |
| 只重启不重建 | 旧 `.next` 和新代码不匹配 | 每次修改必须 `npm run build` |
| 不更新 Caddyfile | 浏览器缓存旧 HTML → 引用旧 CSS hash → 404 | 每次部署复制最新 Caddyfile |
| 只重启前端不重启 Caddy | Caddy 缓存旧配置 | 三个服务都重启 |

### 缓存策略 (Caddyfile)

| 资源类型 | Cache-Control | 原因 |
|---------|--------------|------|
| `/_next/static/*` | `public, max-age=31536000, immutable` | 文件名含 content hash，可永久缓存 |
| HTML 页面 (`/`) | `no-cache, no-store, must-revalidate` | 确保浏览器总是获取最新 HTML（引用正确的 CSS hash） |

### 服务管理 (统一使用 systemd)

```bash
# 查看状态
sudo systemctl status algvex-backend algvex-frontend caddy

# 查看日志
sudo journalctl -u algvex-frontend -n 30
sudo journalctl -u algvex-backend -n 30
sudo journalctl -u caddy -n 10
```

**服务文件**: `web/deploy/algvex-backend.service`, `web/deploy/algvex-frontend.service`
**首次安装**: `cd /home/linuxuser/nautilus_AlgVex/web/deploy && chmod +x setup.sh && ./setup.sh`

## Telegram 双频道消息归属 (v14.0)

每条消息只发一个地方，零重复。`broadcast=True` → 仅通知频道，`broadcast=False` → 仅私聊。

| 消息类型 | 私聊 (控制面板) | 通知频道 (订阅者) | 说明 |
|---------|:--------------:|:----------------:|------|
| 系统启动 | ✅ | ❌ | 运维信息 |
| 系统关闭 | ✅ | ❌ | 运维信息 |
| 心跳监控 | ✅ | ❌ | 20分钟/次，监控用 |
| **开仓信号** | ❌ | ✅ 完整版 | 核心交易信号 |
| **平仓结果** | ❌ | ✅ 完整版 | 盈亏展示 |
| **加仓/减仓** | ❌ | ✅ 完整版 | 仓位变动 |
| **日报** | ❌ | ✅ 完整版 | 业绩展示 |
| **周报** | ❌ | ✅ 完整版 | 业绩展示 |
| 错误/告警 | ✅ | ❌ | 调试信息 |
| SL/TP 调整 | ✅ | ❌ | 风控细节 |
| 紧急 SL | ✅ | ❌ | 运维告警 |
| 命令响应 | ✅ | ❌ | 交互命令 |
| 订单拒绝 | ✅ | ❌ | 运维告警 |

## Telegram 命令 (v3.0)

**快捷菜单** (/ 自动补全): `/menu` (推荐入口), `/s` 状态, `/p` 持仓, `/b` 余额, `/a` 技术面, `/fa` 触发分析, `/profit` 盈亏, `/close` 平仓, `/help`

**查询命令** (无需 PIN): `/status`, `/position`, `/balance`, `/analyze`, `/orders`, `/history`, `/risk`, `/daily`, `/weekly`, `/config`, `/version` (`/v`), `/logs` (`/l`), `/profit`, `/layer3`

**控制命令** (需 PIN): `/pause`, `/resume`, `/close`, `/force_analysis`, `/partial_close 50` (`/pc`), `/set_leverage 10`, `/toggle trailing`, `/set min_confidence HIGH`, `/restart` (`/update`), `/calibrate`, `/modify_sl`, `/modify_tp`, `/reload_config`

## GitHub Actions

| 工作流 | 触发 | 功能 |
|--------|------|------|
| Commit Analysis | push/PR to main | 回归检测 + AI 分析 + 依赖分析 |
| CodeQL Analysis | push/PR + 每周一 | 安全漏洞 + 代码质量 |
| Claude Code | issue/PR | Claude Code Action |

## 📡 外部 API 依赖

| API | 模块 | 用途 | 认证 |
|-----|------|------|------|
| Binance Futures (fapi) | `binance_kline_client.py` | K线、FR、价格 | 无 (公开) |
| Binance Futures (fapi) | `binance_account.py` | 账户、仓位、订单 | HMAC-SHA256 |
| Binance Futures (fapi) | `binance_derivatives_client.py` | Top Traders L/S、OI | 无 (公开) |
| Binance Futures (fapi) | `binance_orderbook_client.py` | 订单簿深度 | 无 (公开) |
| Binance Futures (fapi) | `sentiment_client.py` | 全球 L/S 比 | 无 (公开) |
| Coinalyze | `coinalyze_client.py` | OI + Liquidations + L/S | API Key (可选) |
| DeepSeek | `multi_agent_analyzer.py` | AI 多代理辩论 (5~7+1 次/周期) | API Key |
| Telegram | `telegram_bot.py` | 通知 + 命令 | Bot Token |

## 🔄 数据持久化

| 文件 | 用途 | 大小限制 |
|------|------|---------|
| `data/trading_memory.json` | 交易记忆 + 评估 + 反思 | 最多 500 条 |
| `data/layer_orders.json` | 每层 SL/TP 持久化 (重启恢复) | 按活跃层数 |
| `data/extended_reflections.json` | 扩展反思 (v18.0) | 最多 100 条 |
| `data/calibration/latest.json` | S/R Hold Probability 校准因子 | 单文件 |
| `data/calibration/history/` | 校准历史存档 | 最多 12 份 |
| `data/feature_snapshots/` | Feature snapshot (v27.0, replay 用) | 按周期 |
| `data/hold_counterfactuals.json` | HOLD 反事实评估 (v34.2, verdict/hold_source/price_change) | 最多 200 条 |
| `data/telegram_queue.db` | Telegram 消息持久化队列 | 7 天保留 |
| `data/backtest_counterfactual_result.json` | 被拒信号反事实回测结果 (v37.0+) | 按运行覆盖 |
| `data/backtest_from_logs_result.json` | 生产级回测结果 (v3.0 仿真器) | 按运行覆盖 |
| `data/trade_analysis_export.json` | 信号分析导出 (回测输入) | 按运行覆盖 |
| `logs/audit/` | Telegram 命令审计日志 (SHA256 hash chain) | 按日轮转 |

## 联系方式

- GitHub: FelixWayne0318
- 仓库: https://github.com/FelixWayne0318/AlgVex
