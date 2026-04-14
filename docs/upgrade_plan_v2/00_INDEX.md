# AlgVex 2.0 升级方案 — 终极架构 (Definitive Edition)

> **版本**: v2.0 Final | **日期**: 2026-03-21
> **原则**: 每个环节只选一个世界最顶级工具，无备选，无 fallback，无 feature flag。
> 旧实现在新实现部署后**立即删除**。

---

## 核心公式

```
交易盈利能力 = 数据质量 × Prompt 质量 × 输出约束 × 记忆检索 × 模型能力
              × 仓位管理 × 执行质量 × 可观测性
              × 质量保障 × 安全连续性
```

10 个因子。前 8 个是**能力因子** (越高越好)，后 2 个是**保障因子** (质量 ≥ 当前水平，安全 = 零回退)。23 个工具覆盖全部环节，含 4 个基础代码加固替换 (tenacity REST 加固/market-profile/pandas-ta-classic/structlog)。

---

## 终极技术栈 (每个环节一个最优解)

| # | 环节 | 工具 | 为什么是 #1 | 替代什么 |
|---|------|------|-----------|---------|
| 1 | **Regime Detection** | HMM + GMM Ensemble | 概率输出 + 非序列 regime 转换检测 | ADX 二分法 |
| 2 | **On-Chain Analytics** | Glassnode | 7,500+ 指标, 1,200 资产, 900+ API endpoints | 无 (新增) |
| 3 | **Sentiment NLP** | FinBERT-BiLSTM | 98% crypto 准确率, 负面新闻高敏感度 | 无 (新增) |
| 4 | **Prompt Optimization** | DSPy (MIPROv2) | 唯一能自动优化 prompt+few-shot 的框架 | 手写 prompt |
| 5 | **Structured Output** | Instructor | 3M+ 月下载, 15+ provider, Pydantic 原生 | `_validate_agent_output()` |
| 6 | **Vector Memory** | Qdrant | Rust 高性能, sub-ms 延迟, HNSW 索引 | JSON 手写评分 |
| 7 | **Agent Orchestration** | LangGraph 1.0 | 6.17M 月下载, 状态持久化, 生产级稳定 | 手写 Python 4,946 行 |
| 8 | **Position Sizing** | Fractional Kelly (0.25-0.5×) | 数学最优 + 不确定性补偿 | 固定 confidence mapping |
| 9 | **Risk Management** | VaR/CVaR + Regime-Adaptive | 95% 置信区间尾部风险度量 | 静态阈值熔断器 |
| 10 | **Parameter Optimization** | Optuna (TPE + HyperBand) | Bayesian 优化 + 剪枝, v4.8.0 | 手动回测 |
| 11 | **Time-Series DB** | QuestDB | 11.4M rows/sec, 列式存储, 零关系开销 | JSON 文件 |
| 12 | **Execution** | VWAP (高流动) + TWAP (低流动) | 滑点降低 15-22% | 单一 LIMIT |
| 13 | **Monitoring** | Prometheus + Grafana | 行业标准, 多维时序 + 实时仪表盘 | Telegram + 日志 |
| 14 | **Experiment Tracking** | Weights & Biases | 最优可视化 UI, 行业迁移趋势 | 无 (新增) |
| 15 | **Data Validation** | Pandera | Python 原生, 3-5× 快于 Great Expectations | 无 (新增) |
| 16 | **Feature Store** | Feast + Redis | 唯一开源 offline+online 双存储 | 无 (新增) |
| 17 | **Constrained Decoding** | SGLang | 2.5× throughput, compressed FSM, 400K GPU 部署 | DeepSeek JSON mode |
| 18 | **RL Position Optimization** | FinRL | 唯一标准化交易 RL 框架, 2025 DeepSeek 集成 | 无 (新增) |
| 19 | **Fine-tuning** | LoRA (DeepSeek) | 参数高效, 可在消费级 GPU 训练 | 无 (新增) |
| 20 | **Volume Profile** | market-profile | 标准 VPOC + Value Area + TPO | 手写 `sr_volume_profile.py` (173 行, 含除零 bug) |
| 21 | **Pivot Points** | pandas-ta-classic | 15M+ 月下载, 5 种 Pivot 方法 | 手写 `sr_pivot_calculator.py` (118 行) |
| 22 | **Structured Logging** | structlog | 行业标准结构化日志 + JSON output | 手写 `audit_logger.py` I/O 层 (472 行, 含 race condition) |
| 23 | **REST Client 加固** | tenacity + requests 统一 | 标准 retry 装饰器, 指数退避 | 6 个手写 REST client (2,458 行, 4/6 无 retry, HTTP 库不一致) |

---

## 四阶段实施路线图

### 依赖图 (DAG)

```
Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ Phase 3
  │            │            │            │
  │            ├─ DSPy ◄────┤            │
  │            │   (需要 Phase 0 基线      │
  │            │    + 300+ trading_memory)  │
  │            │            │            │
  │            ├─ Instructor (独立)        │
  │            ├─ Qdrant (独立)           │
  │            ├─ HMM (独立)             │
  │            │            │            │
  │            │            ├─ Glassnode ◄┤
  │            │            ├─ FinBERT   │
  │            │            ├─ Kelly ◄───┤ (需要 HMM regime)
  │            │            ├─ Optuna    │
  │            │            ├─ Prometheus │
  │            │            ├─ VWAP/TWAP │
  │            │            ├─ Pandera   │
  │            │            │            │
  │            │            │            ├─ LangGraph ◄─ (需要 Instructor + Qdrant)
  │            │            │            ├─ QuestDB ◄── (需要 Pandera 验证层)
  │            │            │            ├─ W&B ◄───── (需要 Optuna 实验)
  │            │            │            ├─ Feast ◄─── (需要 QuestDB)
  │            │            │            ├─ SGLang ◄── (需要 LangGraph 编排)
  │            │            │            ├─ FinRL ◄─── (需要 Kelly 基线)
  │            │            │            └─ LoRA ◄──── (需要 500+ 交易数据)
```

### Phase 0 (1 周) — 度量基线

**前置**: 30 天实盘数据 (`trading_memory.json` ≥100 条)

```
├── Alphalens: IC (Information Coefficient) + IC 半衰期
├── QuantStats: 蒙特卡洛 10,000 次模拟 → alpha 显著性
├── 基线 KPI: direction_accuracy, avg_rr, sharpe, max_dd, calmar
└── 输出: data/baseline_v44.json (所有后续改进的参照)
```

### Phase 1 (2-4 周) — 核心突破

**前置**: Phase 0 完成 + trading_memory ≥300 条

| 组件 | 工具 | 替代什么 | 删除什么 |
|------|------|---------|---------|
| REST Client 加固 | tenacity + requests | 不一致的 HTTP 库 + 无 retry | `urllib` 引用 + `print()` 语句 |
| Prompt 优化 | DSPy MIPROv2 | 手写 prompt | agents/ 中手写 system prompt 模板 |
| 输出约束 | Instructor | `_validate_agent_output()` | 该函数全部代码 (~200 行) |
| 记忆检索 | Qdrant + all-MiniLM-L6-v2 | JSON 手写评分 | `_get_past_memories()` 手写逻辑 |
| Regime 检测 | HMM 4-state (hmmlearn) | ADX 二分法 | `market_regime` ADX 分支 |
| 宏观情绪 | Fear & Greed Index | 无 | — (纯新增) |
| 交叉验证 | Ensemble Veto (Claude Sonnet) | 单一 DeepSeek | — (新增层) |
| Volume Profile | market-profile | 手写 `sr_volume_profile.py` (含 bug) | 该文件 173 行 |
| Pivot Points | pandas-ta-classic | 手写 `sr_pivot_calculator.py` | 该文件 118 行 |
| Cache 加固 | threading.Lock | 无线程保护的全局缓存 | ~10 行修改 |

**验收标准**: IC 提升 ≥0.05 OR direction_accuracy 提升 ≥5%

### Phase 2 (4-8 周) — 数据 + 风控 + 基础设施

**前置**: Phase 1 验收通过

| 组件 | 工具 | 替代什么 | 删除什么 |
|------|------|---------|---------|
| 链上数据 | Glassnode (MVRV/SOPR/NVT) | 无 | — (新增第 14 类数据) |
| 情绪 NLP | FinBERT-BiLSTM | 无 | — (新增第 15 类数据) |
| 数据验证 | Pandera | 无 | 手写 data quality gate |
| 仓位管理 | Fractional Kelly × Regime | 固定 confidence_mapping | `calculate_position_size()` 固定逻辑 |
| 风控 | VaR/CVaR + Regime-Adaptive | 静态阈值 | `risk_controller.py` 静态 thresholds |
| 参数优化 | Optuna Walk-Forward | 手动回测 | 手动参数调优流程 |
| 监控 | Prometheus + Grafana | Telegram + 日志 | Telegram 心跳监控功能 |
| 执行 | VWAP + TWAP | 单一 LIMIT | 直接 LIMIT 提交逻辑 |
| 审计日志 | structlog + SHA256 chain | 手写 I/O + race condition | `audit_logger.py` I/O 层 (~320 行) |

**验收标准**: Sharpe 提升 ≥0.3 OR max_dd 降低 ≥2%

### Phase 3 (8-16 周) — 架构升级

**前置**: Phase 2 验收通过 + trading_memory ≥500 条 + **GPU 基础设施就绪** (详见 12_MIGRATION_ROLLBACK.md)

| 组件 | 工具 | 替代什么 | 删除什么 |
|------|------|---------|---------|
| Agent 编排 | LangGraph 1.0 | 手写 `multi_agent_analyzer.py` | 该文件 4,946 行 |
| 时序存储 | QuestDB | JSON 文件存储 | `trading_memory.json` 读写逻辑 |
| 实验追踪 | Weights & Biases | 无 | — (新增) |
| Feature Store | Feast + Redis | 内存 dict | `extract_features()` 临时存储 |
| 数据源 | CoinGlass + Santiment | 无 | — (新增第 16-17 类数据) |
| 约束解码 | SGLang (自托管 DeepSeek) | DeepSeek API JSON mode | API 调用逻辑 |
| RL 仓位 | FinRL (PPO) | Fractional Kelly | Kelly 作为 baseline 对比 (退出条件详见 07_POSITION_RISK.md) |
| 微调 | LoRA (DeepSeek-V3) | 基础模型 | — (model 替换) |

**验收标准**: Calmar Ratio ≥5 (年化 Sharpe/MaxDD)

---

## v44.0 vs v2.0 对比

| 维度 | v44.0 现状 | v2.0 目标 |
|------|-----------|----------|
| 数据源 | 6 源 (Binance + Coinalyze) | 10 源 (+Glassnode/FinBERT/CoinGlass/Santiment) |
| Regime | ADX 二分 (TRENDING/RANGING) | HMM 4-state 概率分布 |
| Prompt | 手写, 凭直觉调优 | DSPy MIPROv2 自动优化 |
| 输出验证 | 手写 200 行 validation | Instructor Pydantic 原生验证 |
| 记忆 | JSON O(N) 手写评分 | Qdrant HNSW O(log N) 语义向量 |
| 模型 | 单一 DeepSeek API | SGLang 自托管 + LoRA 微调 + Ensemble Veto |
| 仓位 | 固定 confidence 80/50/30% | Fractional Kelly × Regime × Drawdown → FinRL |
| 风控 | 静态阈值 (10%/15% DD) | VaR/CVaR + Regime-Adaptive 动态阈值 |
| 执行 | LIMIT 单笔 | VWAP/TWAP + Iceberg 智能拆单 |
| 参数 | 手动回测 6 轮 | Optuna Walk-Forward 自动优化 |
| 存储 | JSON 文件 | QuestDB 列式 (11.4M rows/sec) |
| 编排 | Python 4,946 行 | LangGraph 状态图 + checkpoint |
| 监控 | Telegram + 日志 | Prometheus + Grafana 实时仪表盘 |
| 实验 | 无 | Weights & Biases |
| 数据验证 | 手写 gate | Pandera 统计型验证 |
| Feature | 内存 dict | Feast + Redis sub-ms serving |
| RL | 无 | FinRL PPO 动态仓位 |

---

## 文件索引

| # | 文件 | 环节 | Phase | 核心技术 |
|---|------|------|-------|---------|
| 01 | `01_PHASE0_BASELINE.md` | 度量基线 | 0 | Alphalens + QuantStats |
| 02 | `02_DATA_QUALITY.md` | 数据质量 | 1-3 | REST 加固 (tenacity) + HMM + Glassnode + FinBERT + CoinGlass + Santiment + Pandera |
| 03 | `03_PROMPT_QUALITY.md` | Prompt 质量 | 1 | DSPy MIPROv2 |
| 04 | `04_OUTPUT_CONSTRAINTS.md` | 输出约束 | 1 | Instructor Pydantic |
| 05 | `05_MEMORY_RETRIEVAL.md` | 记忆检索 | 1 | Qdrant + sentence-transformers |
| 06 | `06_MODEL_CAPABILITY.md` | 模型能力 | 1-3 | Ensemble Veto → SGLang + LoRA |
| 07 | `07_POSITION_RISK.md` | 仓位风控 | 2-3 | Fractional Kelly + VaR/CVaR → FinRL |
| 08 | `08_EXECUTION_INFRA.md` | 执行基础设施 | 2-3 | VWAP/TWAP + Optuna + LangGraph + QuestDB + Prometheus + W&B + Feast |
| 09 | `09_QUALITY_DIAGNOSTICS.md` | 质量保障 | 0-3 | AIQualityAuditor 扩展 + 诊断演进 + 测试套件 |
| 10 | `10_SAFETY_CONTINUITY.md` | 安全连续性 | 0-3 | 四道防线保留 + VaR/CVaR 适配 + Kelly 接入 |
| 11 | `11_INTERFACE_ADAPTATION.md` | 界面适配 | 1-3 | Telegram 新命令 + Web 新页面 + Prometheus 共存 |
| 12 | `12_MIGRATION_ROLLBACK.md` | 迁移回滚 | 0-3 | 分阶段迁移 + 双写策略 + 逐组件回滚 + **Phase 3 GPU 硬件前置条件** |

---

## 组件覆盖矩阵

全部 ~106K 行 Python 代码的升级归属:

| 子系统 | 行数 | 文件数 | 升级方案 | 变更级别 |
|--------|------|--------|---------|---------|
| **agents/** (多代理) | 15,500 | 8 | 03 (DSPy) + 04 (Instructor) + 05 (Qdrant) + 08 (LangGraph) + 09 (Auditor 扩展) | 重写 |
| **strategy/** (策略主体) | 15,411 | 8 | 07 (Kelly/VaR) + 08 (VWAP) + 10 (安全层保留) | 适配 |
| **utils/** (工具模块) | 13,274 | 25 | 02 (REST 加固 + 新数据源) + 07 (risk_controller) + 08 (Prometheus) + 11 (界面) | 加固 + 扩展 |
| **scripts/** (诊断/回测) | 48,217 | 44 | 01 (基线) + 09 (诊断演进) + 12 (迁移脚本) | 扩展 |
| **indicators/** (技术指标) | 1,420 | 3 | 02 (HMM regime 输入) | 最小改动 |
| **tests/** (测试) | 6,642 | 22 | 09 (新增测试文件) | 扩展 |
| **web/** (管理界面) | 5,554+ | 23+ | 11 (新端点+新页面) | 扩展 |
| **patches/** (兼容补丁) | 481 | 3 | 无变化 | 不变 |
| **configs/** (配置) | ~500 | 4 | 12 (新增配置段) | 扩展 |

### 安全层特别说明 (详见 10_SAFETY_CONTINUITY.md)

| 安全组件 | 行数 | 变更 |
|---------|------|------|
| `safety_manager.py` | 1,064 | **零改动** (Emergency SL/TP/Ghost/Orphan) |
| `event_handlers.py` | 2,073 | **零改动** (订单事件/层级清理) |
| `position_manager.py` | 1,792 | 最小改动 (cooldown regime-aware, 3 行) |
| `risk_controller.py` | 591 | Phase 2 阈值动态化 (~50 行) |
| `trading_logic.py` | 1,371 | Phase 2 Kelly 仓位接入 (~15 行) |
| **合计** | **6,891** | **改动 ~127 行 (1.8%)** |

---

## 设计原则

1. **度量先行**: Phase 0 建立基线，每次升级必须用 IC/Sharpe/Calmar 量化验证
2. **一个环节一个工具**: 不保留备选方案，不设 feature flag，不做 A/B 共存
3. **部署即删除**: 新实现验证通过后，立即删除旧实现，Git 历史可追溯
4. **Phase 门控**: 前一 Phase 验收标准未达标，不启动下一 Phase
5. **依赖显式化**: 每个组件的前置依赖在 DAG 中标明，不存在隐含依赖
6. **安全零回退**: 四道安全防线 (AI否决/代码硬保护/熔断器/紧急SL) 在任何 Phase 中都不削弱
7. **逐组件可回滚**: 每个工具独立部署、独立回滚，不存在跨组件原子性要求
