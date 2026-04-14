# 12 — 迁移策略 & 回滚方案

> **Phase**: 贯穿 Phase 0-3 | **依赖**: 所有前序文档
> **核心原则**: 每个 Phase 独立可回滚。回滚 = `git revert` 单次操作，不需要数据迁移。

---

## 回滚架构总览

```
Phase 0 (基线)          ← 纯观测，零代码改动，无需回滚
  ↓
Phase 1 (核心突破)      ← 9 个独立组件，各自可回滚
  ├─ HMM Regime        ← git revert + 删除 data/hmm_states.json
  ├─ Instructor        ← git revert + 恢复 _validate_agent_output()
  ├─ Qdrant            ← git revert + JSON 记忆继续工作
  ├─ DSPy              ← git revert + 恢复手写 prompt
  ├─ Fear & Greed      ← git revert (纯新增数据源)
  ├─ Ensemble Veto     ← git revert (纯新增验证层)
  ├─ Volume Profile    ← git revert + 恢复手写 sr_volume_profile.py
  ├─ Pivot Points      ← git revert + 恢复手写 sr_pivot_calculator.py
  └─ Calibration Lock  ← git revert (无锁版本可接受)
  ↓
Phase 2 (数据+风控)     ← 每个组件独立可回滚
  ├─ Kelly Sizing      ← git revert + 恢复 confidence_mapping
  ├─ VaR/CVaR          ← git revert + 恢复静态阈值
  ├─ Glassnode/FinBERT ← git revert (纯新增数据源)
  ├─ Optuna            ← git revert (纯新增脚本)
  ├─ Prometheus        ← git revert (纯新增监控)
  ├─ VWAP/TWAP         ← git revert + 恢复 LIMIT 逻辑
  ├─ Pandera           ← git revert (纯新增验证)
  └─ Audit Logger      ← git revert + 恢复手写 I/O 层
  ↓
Phase 3 (架构升级)      ← 原子回滚单位标注
  ├─ LangGraph         ← git revert + 恢复 multi_agent_analyzer.py
  ├─ QuestDB           ← git revert + JSON 文件继续工作
  ├─ W&B / Feast       ← git revert (纯新增)
  ├─ SGLang            ← git revert + 恢复 DeepSeek API 调用
  ├─ FinRL             ← git revert + 恢复 Kelly sizing
  └─ LoRA              ← git revert + 恢复基础模型
```

---

## Phase 0: 基线建立 (零侵入)

### 迁移步骤

```bash
# 1. 安装依赖 (不影响生产)
pip install alphalens-reloaded quantstats

# 2. 运行基线计算 (只读操作)
python3 scripts/calculate_baseline.py

# 3. 验证输出
cat data/baseline_v44.json | python3 -m json.tool

# 4. 注册 Telegram 命令 (可选)
# /baseline 命令
```

### 回滚

无需回滚。Phase 0 不修改任何生产代码，只生成 `data/baseline_v44.json`。

---

## Phase 1: 核心突破迁移

### 1A. HMM Regime Detection

**新增文件**:
- `utils/hmm_regime_detector.py` (新建 ~300 行)
- `data/hmm_states.json` (运行时生成)
- `data/hmm_model.pkl` (训练模型文件)

**修改文件**:
- `ai_strategy.py`: `on_start()` 中初始化 HMM，`on_timer()` 中调用
- `agents/report_formatter.py`: `_scores` 新增 regime 上下文
- `agents/prompt_constants.py`: `REASON_TAGS` 新增 HMM 相关 tag
- `agents/tag_validator.py`: `compute_valid_tags()` 新增 regime tag 逻辑
- `configs/base.yaml`: 新增 `hmm` 配置段

**迁移步骤**:

```bash
# 1. 安装依赖
pip install hmmlearn==0.3.2

# 2. 初始训练 (需要 60 天 K 线数据)
python3 scripts/train_hmm_regime.py --lookback-days 60

# 3. 验证
python3 -m pytest tests/test_hmm_regime.py -v

# 4. 部署 (重启服务)
sudo systemctl restart nautilus-trader
```

**回滚**:

```bash
git revert <hmm-commit-hash>
rm -f data/hmm_states.json data/hmm_model.pkl
sudo systemctl restart nautilus-trader
# 系统自动 fallback 到 ADX regime 检测
```

### 1B. Instructor Pydantic

**新增文件**:
- `agents/schemas.py` (新建 ~200 行, 5 个 Pydantic BaseModel)

**修改文件**:
- `agents/multi_agent_analyzer.py`: LLM 调用改用 Instructor wrapper
- `requirements.txt`: 新增 `instructor>=1.7.0`

**删除文件/函数**:
- `_validate_agent_output()` (~200 行)
- `_raw_{key}` 保全逻辑 (~50 行)
- 手写 JSON parse try/except (~80 行)

**迁移步骤**:

```bash
# 1. 安装
pip install instructor>=1.7.0

# 2. 测试 schema 兼容性
python3 -m pytest tests/test_instructor_schemas.py -v

# 3. 灰度: 先用 Instructor 验证但保留旧逻辑作为对照
# (在 multi_agent_analyzer.py 中同时运行两套验证，比较差异)

# 4. 确认无差异后删除旧逻辑
```

**回滚**:

```bash
git revert <instructor-commit-hash>
# _validate_agent_output() 从 git 历史恢复
sudo systemctl restart nautilus-trader
```

### 1C. Qdrant 向量记忆

**新增文件**:
- `utils/qdrant_memory.py` (新建 ~250 行)
- `scripts/migrate_memory_to_qdrant.py` (一次性迁移脚本)

**修改文件**:
- `agents/memory_manager.py`: `_get_past_memories()` 改用 Qdrant 检索

**保留文件**:
- `data/trading_memory.json` — **保留写入**，Qdrant 是读取加速层

**迁移步骤**:

```bash
# 1. 安装
pip install qdrant-client>=1.12.0 sentence-transformers>=3.3.0

# 2. 启动 Qdrant (本地文件模式，无需 Docker)
# QdrantClient(path="data/qdrant_storage") — 嵌入式

# 3. 迁移现有记忆
python3 scripts/migrate_memory_to_qdrant.py

# 4. 验证
python3 -m pytest tests/test_qdrant_memory.py -v

# 5. 部署
sudo systemctl restart nautilus-trader
```

**回滚**:

```bash
git revert <qdrant-commit-hash>
rm -rf data/qdrant_storage/
# trading_memory.json 仍然完整，系统自动使用 JSON 检索
sudo systemctl restart nautilus-trader
```

**关键设计**: `trading_memory.json` 是 SSoT (写入+读取)。Qdrant 只是**读取加速层**，写入仍同时到 JSON。这确保回滚后数据零丢失。

### 1E. S/R Volume Profile → market-profile (P0 Bug Fix)

**删除文件**:
- `utils/sr_volume_profile.py` (173 行, 含除零 bug)

**修改文件**:
- `utils/sr_zone_calculator.py`: `_calculate_volume_profile()` 改用 `MarketProfile` API
- `scripts/validate_production_sr.py`: 适配新 API
- `requirements.txt`: 新增 `market-profile>=0.3.0`

**迁移步骤**:

```bash
# 1. 安装
pip install market-profile>=0.3.0

# 2. 重写 sr_zone_calculator.py 中的 volume profile 调用
# MarketProfile(df).value_area → vpoc, va_high, va_low

# 3. 验证输出一致性
python3 scripts/validate_production_sr.py

# 4. 部署
sudo systemctl restart nautilus-trader
```

**回滚**:

```bash
git revert <market-profile-commit-hash>
# 手写 sr_volume_profile.py 从 git 恢复 (注意: 除零 bug 也恢复)
sudo systemctl restart nautilus-trader
```

### 1F. S/R Pivot Calculator → pandas-ta-classic

**删除文件**:
- `utils/sr_pivot_calculator.py` (118 行)

**修改文件**:
- `utils/sr_zone_calculator.py`: `_calculate_pivot_points()` 改用 `pandas_ta.pivot_points()`
- `requirements.txt`: 新增 `pandas-ta-classic>=0.2.0`

**迁移步骤**:

```bash
# 1. 安装
pip install pandas-ta-classic>=0.2.0

# 2. 验证: pivot 输出数值一致 (Standard/Fibonacci/Woodie 三种方法)
python3 scripts/validate_production_sr.py

# 3. 部署
sudo systemctl restart nautilus-trader
```

**回滚**:

```bash
git revert <pandas-ta-commit-hash>
# 手写 sr_pivot_calculator.py 从 git 恢复
sudo systemctl restart nautilus-trader
```

### 1G. Calibration Loader 线程安全加固

**修改文件**:
- `utils/calibration_loader.py`: 新增 `threading.Lock` (~10 行)

**回滚**:

```bash
git revert <calibration-lock-commit-hash>
# 恢复到无锁版本 (低概率 race condition 风险可接受)
sudo systemctl restart nautilus-trader
```

### 1D. DSPy MIPROv2

**新增文件**:
- `agents/dspy_modules.py` (新建 ~400 行)
- `scripts/train_dspy_pipeline.py` (训练脚本)
- `data/dspy_optimized/trading_pipeline.json` (优化后的 prompt)

**修改文件**:
- `agents/multi_agent_analyzer.py`: prompt 从手写切换到 DSPy 加载

**删除**: 手写 system prompt 模板中的 few-shot 示例

**迁移步骤**:

```bash
# 1. 安装
pip install dspy>=2.6.0

# 2. 构建训练数据 (需要 300+ 交易)
python3 scripts/build_dspy_training_data.py

# 3. 训练 (需要 ~2h, 100 trials)
python3 scripts/train_dspy_pipeline.py --trials 100

# 4. A/B 对比
python3 scripts/compare_dspy_vs_handwritten.py

# 5. 验收: IC 提升 ≥0.05 或 direction_accuracy 提升 ≥5%
# 不达标 → 不部署

# 6. 部署
sudo systemctl restart nautilus-trader
```

**回滚**:

```bash
git revert <dspy-commit-hash>
rm -rf data/dspy_optimized/
# 手写 prompt 从 git 历史恢复
sudo systemctl restart nautilus-trader
```

---

## Phase 2: 数据 + 风控迁移

### 2A. Kelly Sizing

**修改文件**:
- `strategy/trading_logic.py`: `calculate_mechanical_sltp()` 仓位部分
- `utils/backtest_math.py`: 同步 Kelly 公式 (SSoT)
- `configs/base.yaml`: 新增 `kelly` 配置段

**SSoT 同步**:

```python
# check_logic_sync.py 新增
{
    'id': 'KELLY_FORMULA_PARITY',
    'type': 'signature',
    'source': 'strategy/trading_logic.py',
    'target': 'utils/backtest_math.py',
    'regex': r'kelly_fraction\s*=.*',
}
```

**回滚**:

```bash
git revert <kelly-commit-hash>
# confidence_mapping {HIGH:80, MEDIUM:50, LOW:30} 从 git 恢复
python3 scripts/check_logic_sync.py  # 验证 SSoT 一致
sudo systemctl restart nautilus-trader
```

### 2B. VaR/CVaR 动态风控

**修改文件**:
- `utils/risk_controller.py`: 阈值从静态常量改为 regime-aware 字典
- `configs/base.yaml`: 新增 `risk.regime_thresholds` 配置段

**回滚**:

```bash
git revert <var-cvar-commit-hash>
# 静态阈值 (10%/15% DD) 从 git 恢复
sudo systemctl restart nautilus-trader
```

### 2C. Prometheus + Grafana

**新增文件**:
- `utils/prometheus_exporter.py` (~150 行)
- `deploy/prometheus.yml` (scrape 配置)
- `deploy/grafana/dashboards/*.json` (5 个 dashboard)

**回滚**:

```bash
git revert <prometheus-commit-hash>
# Prometheus/Grafana 是独立服务，停止即可
sudo systemctl stop prometheus grafana-server
# Telegram 心跳完全不受影响
```

### 2D. VWAP/TWAP 执行

**修改文件**:
- `strategy/order_execution.py`: `_execute_trade()` 新增拆单逻辑

**回滚**:

```bash
git revert <vwap-commit-hash>
# 单一 LIMIT 逻辑从 git 恢复
sudo systemctl restart nautilus-trader
```

### 2E. Glassnode / FinBERT / Pandera

纯新增组件，回滚 = `git revert` + 删除运行时文件。

### 2F. Audit Logger → structlog 重构

**修改文件**:
- `utils/audit_logger.py`: I/O 层重写为 structlog (~320 行替换)，SHA256 hash chain 逻辑保留 (~150 行)
- `requirements.txt`: 新增 `structlog>=24.0.0`

**迁移步骤**:

```bash
# 1. 安装
pip install structlog>=24.0.0

# 2. 重构 audit_logger.py
# 保留: _compute_hash(), _verify_chain()
# 替换: 文件 I/O, 格式化, 轮转 → structlog processor pipeline

# 3. 验证 hash chain 完整性
python3 -c "from utils.audit_logger import AuditLogger; AuditLogger().verify_chain()"

# 4. 并发写入测试
python3 -m pytest tests/test_audit_logger.py -v

# 5. 部署
sudo systemctl restart nautilus-trader
```

**回滚**:

```bash
git revert <structlog-commit-hash>
# 手写 audit_logger.py 从 git 恢复 (注意: race condition 也恢复)
sudo systemctl restart nautilus-trader
```

---

## Phase 3 硬件前置条件 — GPU 基础设施

> **阻塞级别**: Phase 3 中 SGLang/FinRL/LoRA 三者共同依赖 GPU。无 GPU = Phase 3 的 3/8 组件不可部署。
> 这是 Phase 3 最大阻塞项，必须在 Phase 2 期间规划。

### 当前服务器 (Vultr VPS)

| 项目 | 规格 |
|------|------|
| IP | 139.180.157.152 |
| CPU | vCPU (共享) |
| RAM | 估计 8-16 GB |
| GPU | **无** |
| 用途 | 生产交易 (NautilusTrader + DeepSeek API) |

### Phase 3 GPU 需求

| 组件 | 最低 GPU | 推荐 GPU | VRAM 需求 | 用途 |
|------|---------|---------|-----------|------|
| **SGLang** (DeepSeek-V3 自托管) | 2× A100 80GB | 4× A6000 48GB | 160 GB+ | 推理服务 (24/7 运行) |
| **FinRL** (PPO 训练) | 1× A100 40GB | 1× A100 80GB | 40 GB+ | 训练 (每周 2-4h) |
| **LoRA** (QLoRA 4-bit) | 1× A100 40GB | 1× A100 80GB | 40 GB+ | 微调 (每月 2-4h) |

### 三种部署方案

| 方案 | 月成本 | 延迟 | 适合阶段 |
|------|--------|------|---------|
| **A. 云 GPU (RunPod/Lambda)** | $1,500-3,000 | ~5ms (同区) | Phase 3 初期验证 |
| **B. 专用 GPU 服务器** | $800-1,500 (租) | ~1ms (本地) | Phase 3 长期运行 |
| **C. 自建服务器** | $15K-30K (一次性) | ~1ms (本地) | 确认 ROI 正后 |

### 推荐路径

```
Phase 2 期间 (Week 4-8):
  ├─ 评估交易收益是否覆盖 GPU 成本 (月 PnL > $3,000?)
  ├─ 如果 YES → 申请 RunPod A100×2 (方案 A)
  └─ 如果 NO  → Phase 3 仅部署无 GPU 组件 (LangGraph/QuestDB/W&B/Feast)
       └─ SGLang/FinRL/LoRA 推迟到收益覆盖成本时

Phase 3A (Week 1-2):
  ├─ RunPod 部署 SGLang + 基准测试
  ├─ 验证: latency_p95 < 15s, accuracy parity ±2%
  └─ 通过 → 10% 流量切换

Phase 3B (确认 ROI 后):
  └─ 迁移到方案 B 或 C (降低长期成本)
```

### Phase 3 无 GPU 降级方案

如果 GPU 成本始终不可承受，Phase 3 分为两类:

| 组件 | 需要 GPU? | 降级方案 |
|------|-----------|---------|
| LangGraph | ❌ | 正常部署 |
| QuestDB | ❌ | 正常部署 |
| W&B | ❌ | 正常部署 |
| Feast + Redis | ❌ | 正常部署 |
| SGLang | ✅ | 保留 DeepSeek API + Instructor (Phase 1 方案长期运行) |
| FinRL | ✅ | Kelly 为长期方案 (详见 07_POSITION_RISK.md 退出条件) |
| LoRA | ✅ | 保留 base model + DSPy 优化 prompt (Phase 1 方案长期运行) |

**结论**: Phase 3 的 8 个组件中 **5 个不需要 GPU**，即使无 GPU 也能获得 LangGraph 编排 + QuestDB 存储 + Feast Feature Store 的架构升级。GPU 组件是**锦上添花**，不是必要条件。

---

## Phase 3: 架构升级迁移

### 3A. LangGraph 编排

**替代**: `agents/multi_agent_analyzer.py` (4,946 行)

**迁移策略: Shadow Mode**

```
Week 1-2: Shadow Mode
  ├─ LangGraph 和现有 analyzer 并行运行
  ├─ 两者接收相同输入，输出对比
  └─ 记录差异到 data/langgraph_shadow.json

Week 3: 验证
  ├─ 差异率 <5% → 切换到 LangGraph
  └─ 差异率 ≥5% → 排查后重新 shadow

Week 4: 切换
  ├─ multi_agent_analyzer.py → langgraph_analyzer.py
  └─ 旧文件保留 1 周后删除
```

**回滚**:

```bash
git revert <langgraph-commit-hash>
# multi_agent_analyzer.py 从 git 恢复
sudo systemctl restart nautilus-trader
```

### 3B. QuestDB 时序存储

**迁移对象**:
- `data/trading_memory.json` → QuestDB `trading_memory` 表
- `data/hold_counterfactuals.json` → QuestDB `hold_counterfactuals` 表
- `data/feature_snapshots/` → QuestDB `feature_snapshots` 表

**不迁移**:
- `data/layer_orders.json` — 实时仓位状态，保留 JSON
- `data/extended_reflections.json` — 量小，保留 JSON

**迁移策略: 双写 (Dual Write)**

```
Phase 3A (2 周): 双写模式
  ├─ 写入: JSON + QuestDB 同时写入
  ├─ 读取: 仍从 JSON 读取
  └─ 验证: 定时比对 JSON vs QuestDB 数据一致性

Phase 3B (1 周): 读取切换
  ├─ 写入: JSON + QuestDB 同时写入 (不变)
  ├─ 读取: 改从 QuestDB 读取
  └─ JSON 作为冷备份

Phase 3C (部署后 2 周): 清理
  ├─ 确认 QuestDB 稳定
  ├─ 停止 JSON 写入
  └─ 保留 JSON 文件作为历史备份 (不删除)
```

**回滚** (任何阶段):

```bash
git revert <questdb-commit-hash>
# JSON 文件始终存在且完整 (双写保证)
sudo systemctl restart nautilus-trader
```

### 3C. SGLang 自托管

**前置**: 2× A100 80GB 或 4× A6000 48GB

**迁移策略: Canary 部署**

```
Step 1: SGLang 部署但不接入生产
  ├─ 启动 SGLang server
  ├─ 用历史数据做 throughput + accuracy 基准测试
  └─ 确认: latency_p95 < 15s, accuracy parity ±2%

Step 2: 10% 流量切换
  ├─ 每 10 个 on_timer 周期，1 个用 SGLang
  ├─ 监控: quality_score, latency, error_rate
  └─ 达标 → Step 3

Step 3: 100% 切换
  ├─ 所有 AI 调用切换到 SGLang
  ├─ DeepSeek API key 保留 30 天 (应急 fallback)
  └─ 30 天无事故后删除 API 调用代码
```

**回滚**:

```bash
# 配置切换回 DeepSeek API (configs/base.yaml)
# deepseek.endpoint: https://api.deepseek.com/v1  (恢复)
sudo systemctl restart nautilus-trader
```

---

## 配置迁移

### `configs/base.yaml` 新增段落

```yaml
# Phase 0
baseline:
  output_path: data/baseline_v44.json
  monte_carlo_iterations: 10000

# Phase 1
hmm:
  n_states: 4
  lookback_days: 60
  retrain_interval_days: 7
  hysteresis_cycles: 2

qdrant:
  storage_path: data/qdrant_storage
  collection_name: trading_memories
  embedding_model: all-MiniLM-L6-v2
  top_k: 10

ensemble_veto:
  enabled: true
  model: claude-sonnet-4-6
  veto_threshold: -0.4
  downgrade_threshold: 0.0

# Phase 2
kelly:
  fraction: 0.25  # 0.25× Kelly (保守)
  min_trades_for_kelly: 50  # <50 笔用固定比例
  min_position_pct: 5
  max_position_pct: 100

risk:
  regime_thresholds:
    TRENDING_UP: {dd_reduced: 0.12, dd_halted: 0.18, daily_loss: 0.04}
    TRENDING_DOWN: {dd_reduced: 0.06, dd_halted: 0.10, daily_loss: 0.02}
    RANGING: {dd_reduced: 0.08, dd_halted: 0.12, daily_loss: 0.03}
    HIGH_VOLATILITY: {dd_reduced: 0.05, dd_halted: 0.08, daily_loss: 0.015}

prometheus:
  enabled: true
  port: 9090

# Phase 3
questdb:
  host: localhost
  port: 9009  # ILP protocol
  enabled: false  # Phase 3 启用

sglang:
  enabled: false  # Phase 3 启用
  endpoint: http://localhost:30000/v1
```

### ConfigManager 验证规则新增

```python
# utils/config_manager.py — 新增验证
'hmm.n_states': (int, 2, 10),
'hmm.lookback_days': (int, 30, 365),
'kelly.fraction': (float, 0.1, 1.0),
'kelly.min_trades_for_kelly': (int, 20, 500),
'risk.regime_thresholds.*.dd_reduced': (float, 0.01, 0.30),
'risk.regime_thresholds.*.dd_halted': (float, 0.05, 0.50),
```

---

## SSoT 同步扩展

### `check_logic_sync.py` SYNC_REGISTRY 新增

| Phase | ID | Type | Source | Target | 检查内容 |
|-------|----|------|--------|--------|---------|
| 1 | `HMM_STATE_NAMES` | value_match | hmm_regime_detector.py | report_formatter.py | 4 个 regime 名称一致 |
| 1 | `QDRANT_COLLECTION` | value_match | qdrant_memory.py | migrate_memory_to_qdrant.py | collection 名称一致 |
| 2 | `KELLY_FORMULA` | signature | trading_logic.py | backtest_math.py | Kelly 公式一致 |
| 2 | `VAR_REGIME_THRESHOLDS` | value_match | risk_controller.py | configs/base.yaml | 阈值一致 |
| 2 | `SLTP_ATR_SOURCE` | signature | trading_logic.py | backtest_math.py | ATR 源 (4H) 一致 |

### `smart_commit_analyzer.py` 新增 Pattern

```python
# Phase 1
{'id': 'hmm_fallback', 'type': 'contains', 'file': 'ai_strategy.py',
 'pattern': '_current_hmm_regime', 'description': 'HMM regime fallback must exist'},
{'id': 'qdrant_fallback', 'type': 'contains', 'file': 'agents/memory_manager.py',
 'pattern': 'qdrant', 'description': 'Qdrant integration must exist'},

# Phase 2
{'id': 'kelly_clamp', 'type': 'contains', 'file': 'strategy/trading_logic.py',
 'pattern': 'min_position_pct', 'description': 'Kelly must have position clamp'},
```

---

## 依赖管理

### `requirements.txt` 分阶段新增

```
# Phase 0
alphalens-reloaded>=0.4.5
quantstats>=0.0.62

# Phase 1
hmmlearn>=0.3.2
instructor>=1.7.0
qdrant-client>=1.12.0
sentence-transformers>=3.3.0
dspy>=2.6.0
anthropic>=0.40.0  # Ensemble Veto (Claude)
market-profile>=0.3.0  # 替代手写 sr_volume_profile.py (P0 bug fix)
pandas-ta-classic>=0.2.0  # 替代手写 sr_pivot_calculator.py

# Phase 2
pandera>=0.20.0
optuna>=4.0.0
prometheus-client>=0.21.0
structlog>=24.0.0  # 替代手写 audit_logger.py I/O 层

# Phase 3
langgraph>=0.2.0
psycopg[binary]>=3.2.0  # QuestDB PostgreSQL wire protocol
wandb>=0.18.0
feast>=0.40.0
```

### 依赖兼容性检查

```bash
# 每个 Phase 部署前
pip install --dry-run -r requirements.txt 2>&1 | grep -i conflict
python3 -c "import nautilus_trader; print(nautilus_trader.__version__)"  # 确认 NT 1.224.0 不受影响
```

---

## 数据备份策略

### 每个 Phase 部署前

```bash
# 完整数据备份
tar czf data_backup_pre_phase{N}_$(date +%Y%m%d).tar.gz \
  data/trading_memory.json \
  data/layer_orders.json \
  data/extended_reflections.json \
  data/hold_counterfactuals.json \
  data/feature_snapshots/ \
  data/calibration/ \
  configs/

# Git 标签
git tag -a "v44.0-pre-phase{N}" -m "Backup before Phase {N} deployment"
git push origin "v44.0-pre-phase{N}"
```

### 回滚到任意 Phase

```bash
# 回滚到 Phase N 之前
git checkout "v44.0-pre-phase{N}"
tar xzf data_backup_pre_phase{N}_*.tar.gz
sudo systemctl restart nautilus-trader
```

---

## Phase 门控检查清单

### Phase 0 → Phase 1 门控

- [ ] `data/baseline_v44.json` 存在且包含 10 个 KPI
- [ ] Monte Carlo p-value < 0.05
- [ ] `trading_memory.json` ≥ 100 条交易
- [ ] 数据备份已创建 + git tag 已推送

### Phase 1 → Phase 2 门控

- [ ] IC 提升 ≥ 0.05 OR direction_accuracy 提升 ≥ 5%
- [ ] `smart_commit_analyzer.py` 全部 PASS
- [ ] `check_logic_sync.py` 全部 PASS (含新增项)
- [ ] `stress_test_position_management.py` 全部 PASS
- [ ] `trading_memory.json` ≥ 300 条交易
- [ ] 数据备份已创建 + git tag 已推送

### Phase 2 → Phase 3 门控

- [ ] Sharpe 提升 ≥ 0.3 OR max_dd 降低 ≥ 2%
- [ ] Kelly 仓位计算在回测中验证
- [ ] VaR/CVaR 动态阈值在回测中验证
- [ ] Prometheus + Grafana 运行稳定 ≥ 2 周
- [ ] `trading_memory.json` ≥ 500 条交易
- [ ] 数据备份已创建 + git tag 已推送

---

## 验收标准

### 迁移完整性

- [ ] 每个 Phase 的 git tag 存在且可 checkout
- [ ] 每个 Phase 的数据备份存在且可恢复
- [ ] 每个组件的回滚流程已文档化
- [ ] 每个组件的回滚流程已实际测试 (在 development 环境)
- [ ] `configs/base.yaml` 新增参数已在 ConfigManager 中注册验证
- [ ] `check_logic_sync.py` 新增 SYNC 项全部 PASS
- [ ] `requirements.txt` 无版本冲突
