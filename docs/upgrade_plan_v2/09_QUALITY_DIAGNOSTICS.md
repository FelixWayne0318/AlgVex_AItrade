# 09 — 质量保障 & 诊断系统演进

> **Phase**: 贯穿 Phase 0-3 | **依赖**: 02 (数据质量), 04 (Instructor)
> **核心原则**: AIQualityAuditor 是经过 v29-v36 十余次迭代的成熟系统 (3,188 行)，**保留并扩展**，不替代。

---

## 现状分析

### 质量保障三层架构 (v34.1)

```
Layer 1: 数据层验证
  ├─ extract_features() → 124 typed features + 8 个 _avail_* flags
  ├─ compute_scores_from_features() → 5 维评分 (trend/momentum/order_flow/vol_ext_risk/risk_env)
  └─ DATA_UNAVAILABLE Step 0 pre-check

Layer 2: AI 输出验证
  ├─ _validate_agent_output() → schema 合规 (v27.0)
  ├─ AIQualityAuditor → 6 维 + 5 逻辑一致性 (v34.0)
  └─ filter_output_tags() → REASON_TAG 过滤

Layer 3: Outcome Feedback
  ├─ utils/quality_analysis.py → 10 个分析函数 (v35.0 SSoT)
  ├─ /layer3 Telegram 命令
  └─ Web /quality 页面 + 5 个 API 端点
```

### 诊断系统规模

| 类别 | 文件数 | 总行数 | 覆盖 |
|------|--------|--------|------|
| **诊断模块** (`scripts/diagnostics/`) | 14 | ~19,000 | 代码完整性 (114 项)、AI 决策、架构合规、订单流模拟、指标验证 |
| **质量诊断** | 5 | ~5,800 | 评分、扣分、auditor 版本专项 |
| **回测套件** | 6 | ~6,500 | 反事实、日志回测、参数对比 |
| **验证脚本** | 4 | ~6,600 | 指标、Extension、数据管线、S/R |
| **同步检查** | 2 | ~1,130 | SSoT 逻辑同步 (14 项)、回归检测 |
| **合计** | **31** | **~39,000** | |

---

## 升级策略: 扩展而非替代

### 原则

1. **AIQualityAuditor 保留全部现有逻辑** — 6 维验证 + 5 逻辑一致性检查已经过生产验证
2. **新数据源 = 新审计维度** — HMM/Glassnode/FinBERT 接入后，扩展审计覆盖
3. **Instructor 替代 Layer 1 结构验证** — `_validate_agent_output()` 被 Pydantic schema 接管
4. **Layer 3 增加 regime 维度分析** — outcome feedback 按 HMM regime 分类
5. **诊断脚本跟随代码演进** — 新增检查项，不删除已有检查

---

## Phase 1: Instructor 接管结构验证

### 变更: Layer 1 → Layer 2 职责迁移

```
v44.0:
  LLM 输出 → _validate_agent_output() (手写 ~200 行)
           → AIQualityAuditor (6 维语义验证)

v2.0 Phase 1:
  LLM 输出 → Instructor Pydantic (结构/类型/Enum/自动 3 次重试)
           → AIQualityAuditor (6 维语义验证 + 扩展维度)
```

**AIQualityAuditor 不变**: Instructor 只保证结构正确 (字段存在、类型匹配、Enum 合法)，不保证语义正确 (citation 准确性、MTF 归属、逻辑一致性)。这是两层互补关系。

### 删除清单 (Phase 1)

| 删除内容 | 行数 | 原因 | 替代 |
|---------|------|------|------|
| `_validate_agent_output()` | ~200 | Instructor Pydantic 原生接管 | 04_OUTPUT_CONSTRAINTS.md |
| `_raw_{key}` 保全逻辑 | ~50 | Instructor 自动重试不产生截断问题 | Pydantic validator |
| 手写 JSON parse + try/except | ~80 | Instructor 内置 JSON 解析 | `instructor.from_openai()` |

### 保留清单 (不变)

| 保留内容 | 行数 | 原因 |
|---------|------|------|
| `AIQualityAuditor.audit()` | 3,188 | 语义验证不可替代 |
| `_SIGNAL_KEY_PATTERNS` | ~200 | 指标 citation 检测 regex |
| `_TAG_TO_CATEGORIES` | ~100 | tag → 数据类别映射 |
| `_check_*_citations()` | ~500 | 数值准确性验证 (±5% tolerance) |
| 5 个逻辑一致性检查 (v34.0) | ~300 | reason-signal/score-divergence/confidence-risk/debate/diversity |
| `filter_output_tags()` | ~50 | REASON_TAG 数据支持过滤 |

---

## Phase 1: HMM Regime 审计扩展

### AIQualityAuditor 新增维度

**Dimension 7: Regime Coherence** (新增)

```python
# ai_quality_auditor.py 新增方法
def _check_regime_coherence(self, agent_outputs, hmm_regime):
    """
    Check: Agent reasoning must be consistent with HMM regime state.

    Rules:
    - If regime=HIGH_VOLATILITY and agent claims "low volatility environment" → penalty
    - If regime=TRENDING_UP and Bull has low conviction (<0.3) without citing reversal evidence → warning
    - If regime=RANGING and Judge cites strong trend momentum → check if evidence supports
    """
```

**惩罚规则**:

| 检查 | 场景 | 扣分 | 类型 |
|------|------|------|------|
| REGIME_CLAIM_MISMATCH | Agent 文本声明与 HMM regime 矛盾 | -4 | PENALIZED |
| REGIME_CONVICTION_INCOHERENCE | Trending regime + 极低 conviction + 无反转证据 | -2 | INFORMATIONAL |
| REGIME_TRANSITION_IGNORED | 24h 内 ≥3 次 regime 转换但 Agent 未提及不确定性 | -2 | INFORMATIONAL |

### `_SIGNAL_KEY_PATTERNS` 扩展

```python
# 新增 regime-related patterns
'hmm_regime': [
    r'(?i)regime\s*[:=]\s*(trending|ranging|high.?vol)',
    r'(?i)HMM\s+(?:state|regime)',
    r'(?i)transition\s+(?:risk|probability)',
],
```

### `_DATA_CATEGORY_MARKERS` 扩展

```python
'hmm_regime': [
    r'regime.{0,30}(trending|ranging|volatile)',
    r'HMM.{0,20}(state|confidence)',
    r'transition.{0,15}(risk|prob)',
],
```

---

## Phase 2: 新数据源审计覆盖

### Glassnode On-Chain 审计

**`_TAG_TO_CATEGORIES` 新增映射**:

```python
'ONCHAIN_OVERVALUED': ['onchain'],
'ONCHAIN_UNDERVALUED': ['onchain'],
'EXCHANGE_INFLOW': ['onchain'],
'EXCHANGE_OUTFLOW': ['onchain'],
```

**`_SIGNAL_KEY_PATTERNS` 新增**:

```python
'onchain_mvrv': [r'(?i)MVRV.{0,10}[Zz].?[Ss]core'],
'onchain_sopr': [r'(?i)(?:a?SOPR|Spent.Output.Profit)'],
'onchain_nvt': [r'(?i)NVT.{0,10}(?:Signal|Ratio)'],
'exchange_netflow': [r'(?i)(?:exchange|net).{0,10}(?:flow|inflow|outflow)'],
```

### FinBERT NLP Sentiment 审计

**`_TAG_TO_CATEGORIES` 新增映射**:

```python
'NEWS_BULLISH': ['nlp_sentiment'],
'NEWS_BEARISH': ['nlp_sentiment'],
'NEWS_EXTREME_FEAR': ['nlp_sentiment'],
```

### `_effective_required()` 更新

```python
# 新增 _avail_* flags 对应关系
_AVAIL_TO_CATEGORIES = {
    # ... 现有 8 个 ...
    '_avail_onchain': ['onchain'],        # Glassnode
    '_avail_nlp_sentiment': ['nlp_sentiment'],  # FinBERT
    '_avail_hmm_regime': ['hmm_regime'],  # HMM
}
```

**关键**: 新数据源不可用时，Agent 不因未引用而被惩罚覆盖率 — 复用现有 v34.1 `_avail_*` 机制。

---

## Layer 3: Outcome Feedback 扩展

### `utils/quality_analysis.py` 新增分析函数

| # | 函数 | Phase | 输入 | 输出 |
|---|------|-------|------|------|
| 11 | `analyze_win_rate_by_regime()` | 1 | trades + hmm_regime_at_entry | 每个 regime 的 win rate / avg PnL / trade count |
| 12 | `analyze_regime_transition_trades()` | 1 | trades + regime transitions | 在 regime 转换期间开仓的交易表现 |
| 13 | `analyze_kelly_calibration()` | 2 | trades + kelly_fraction_at_entry | Kelly 预测 vs 实际 PnL 对比 |

### 实现模式 (复用现有架构)

```python
# quality_analysis.py — 遵循现有 10 个函数的模式
def analyze_win_rate_by_regime(trades: list) -> dict:
    """
    Analyze win rate grouped by HMM regime at entry time.
    Requires 'hmm_regime' field in trade records.
    Returns None if <5 trades have regime data.
    """
    regime_trades = [t for t in trades if t.get('hmm_regime')]
    if len(regime_trades) < 5:
        return None

    by_regime = {}
    for t in regime_trades:
        regime = t['hmm_regime']
        if regime not in by_regime:
            by_regime[regime] = {'wins': 0, 'total': 0, 'pnl_sum': 0.0}
        by_regime[regime]['total'] += 1
        if t.get('pnl_pct', 0) > 0:
            by_regime[regime]['wins'] += 1
        by_regime[regime]['pnl_sum'] += t.get('pnl_pct', 0)

    return {regime: {
        'trades': d['total'],
        'win_rate': d['wins'] / d['total'] if d['total'] > 0 else 0,
        'avg_pnl': d['pnl_sum'] / d['total'] if d['total'] > 0 else 0,
    } for regime, d in by_regime.items()}
```

**SSoT 更新**: `check_logic_sync.py` 的 `SYNC_REGISTRY` 新增对 `quality_analysis.py` 新函数的追踪 (如果有 script 副本的话)。

---

## 诊断系统演进

### Phase 1: 新增诊断检查

| 脚本 | 新增检查 | 验证内容 |
|------|---------|---------|
| `diagnostics/code_integrity.py` | P1.115-P1.120 | Instructor schema 定义完整性、Pydantic model 导入 |
| `diagnostics/code_integrity.py` | P1.121-P1.125 | Qdrant client 初始化、fallback 逻辑、collection 配置 |
| `diagnostics/code_integrity.py` | P1.126-P1.130 | HMM regime detector 初始化、retrain 周期、fallback |
| `diagnostics/ai_decision.py` | Check 9 | Instructor 集成: Pydantic schema → LLM → 自动验证 |
| `diagnostics/ai_decision.py` | Check 10 | Qdrant 检索: 写入测试向量 → 查询 → 验证结果 |
| `diagnose_quality_scoring.py` | Phase 18 | Regime coherence check 验证 (HMM 状态 + Agent 文本) |

### Phase 2: 新增诊断检查

| 脚本 | 新增检查 | 验证内容 |
|------|---------|---------|
| `diagnostics/code_integrity.py` | P1.131-P1.135 | Glassnode API client、FinBERT 模型加载、Pandera schema |
| `diagnostics/math_verification.py` | M17-M18 | Kelly 公式验证 (f* = (pb-q)/b)、VaR/CVaR 计算 |
| `diagnose_quality_scoring.py` | Phase 19 | Glassnode/FinBERT citation pattern 覆盖率 |
| `validate_data_pipeline.py` | Source 14-15 | Glassnode API + FinBERT pipeline 端到端 |

### Phase 3: 新增诊断检查

| 脚本 | 新增检查 | 验证内容 |
|------|---------|---------|
| `diagnostics/architecture_verify.py` | AV-25+ | LangGraph StateGraph 节点/边完整性 |
| `diagnose_quality_scoring.py` | Phase 20 | LangGraph checkpoint recovery 验证 |
| `check_logic_sync.py` | 新增 SYNC 项 | Kelly 公式 SSoT (trading_logic.py ↔ backtest_math.py) |

---

## SSoT 同步检查扩展

### `check_logic_sync.py` SYNC_REGISTRY 新增

```python
# Phase 1
{
    'id': 'HMM_REGIME_THRESHOLDS',
    'type': 'value_match',
    'source': 'utils/hmm_regime_detector.py',
    'target': 'agents/report_formatter.py',
    'description': 'HMM regime state names must match across detector and formatter',
},

# Phase 2
{
    'id': 'KELLY_FORMULA_PARITY',
    'type': 'signature',
    'source': 'strategy/trading_logic.py',
    'target': 'utils/backtest_math.py',
    'description': 'Kelly fraction formula must match between production and backtest',
},
{
    'id': 'VAR_CVAR_THRESHOLDS',
    'type': 'value_match',
    'source': 'utils/risk_controller.py',
    'target': 'configs/base.yaml',
    'description': 'VaR/CVaR regime-specific thresholds must match config',
},
```

---

## `smart_commit_analyzer.py` 演进

### 新增 Pattern Types (Phase 1)

```python
# Instructor schema 完整性
{
    'id': 'instructor_schema_complete',
    'type': 'contains',
    'file': 'agents/schemas.py',
    'pattern': 'class JudgeOutput(BaseModel)',
    'description': 'Instructor Pydantic schema must define JudgeOutput',
},

# Qdrant collection 名称一致性
{
    'id': 'qdrant_collection_name',
    'type': 'value_match',
    'source': 'agents/memory_manager.py',
    'target': 'scripts/migrate_memory_to_qdrant.py',
    'description': 'Qdrant collection name must match between production and migration',
},
```

---

## 测试套件演进

### 现有测试保留 (全部)

22 个测试文件 / 6,642 行全部保留。现有测试覆盖的逻辑 (SL/TP 计算、订单流、Telegram 命令等) 在升级中不变。

### 新增测试 (跟随 Phase)

| Phase | 新增测试文件 | 测试内容 | 行数 (估) |
|-------|------------|---------|----------|
| 1 | `test_instructor_schemas.py` | 5 个 Pydantic schema 验证 + edge case | ~200 |
| 1 | `test_qdrant_memory.py` | 向量写入/检索/Hybrid 策略 + fallback | ~300 |
| 1 | `test_hmm_regime.py` | HMM 4-state 检测 + 概率输出 + hysteresis | ~200 |
| 1 | `test_auditor_regime.py` | Regime coherence check + penalty 计算 | ~150 |
| 2 | `test_kelly_sizing.py` | Kelly 公式 + regime multiplier + drawdown scaling | ~200 |
| 2 | `test_var_cvar.py` | VaR/CVaR 计算 + regime-adaptive thresholds | ~200 |
| 3 | `test_langgraph_flow.py` | StateGraph 节点执行 + 条件分支 + checkpoint | ~300 |

### CI/CD 更新

```yaml
# .github/workflows/commit-analysis.yml 新增 step
- name: Instructor Schema Validation
  run: python3 -m pytest tests/test_instructor_schemas.py -v

- name: Qdrant Integration Test
  run: python3 -m pytest tests/test_qdrant_memory.py -v --timeout=30
```

---

## Phase 1: 基础代码加固 (7 组件审计)

全系统 137 个文件审计发现 7 个未被方案显式覆盖的组件。逐一评估后制定如下行动:

### 组件清单与行动矩阵

| 优先级 | 组件 | 行数 | 问题 | 行动 | 工具 | Phase |
|--------|------|------|------|------|------|-------|
| **P0** | `utils/sr_volume_profile.py` | 173 | **Bug**: L73 `current_price ≤ 0` 时除零崩溃 | 替换 | market-profile | 1 |
| **P1** | `utils/sr_pivot_calculator.py` | 118 | 无 bug，但手写 Floor Trader Pivots 可用成熟库 | 替换 | pandas-ta-classic | 1 |
| **P1** | `utils/audit_logger.py` | 472 | Race condition: 并发写入 hash chain 不一致；无日志轮转 | 重构 | structlog | 2 |
| **P2** | `utils/calibration_loader.py` | 289 | Race condition: 全局 `_cached_calibration` 无线程锁 | 加固 | threading.Lock | 1 |
| — | `utils/sr_swing_detector.py` | 217 | 无 bug，含自研 Spitsin 成交量加权算法，无现成替代 | 保留 + 补测试 | — | 1 |
| — | `utils/sr_types.py` | 69 | 纯 dataclass 定义，无逻辑 | 不变 | — | — |
| — | `scripts/validate_production_sr.py` | 546 | 系统专属验证脚本 | 不变 | — | — |

### P0: sr_volume_profile.py → market-profile 替换

**现状问题**:

```python
# sr_volume_profile.py:73 — 未防护的除零
tick_size = current_price * 0.001  # current_price ≤ 0 → crash
```

**替换方案**: [market-profile](https://github.com/bburns/market-profile) (PyPI `market-profile>=0.3.0`)

- 行业标准 VPOC + Value Area 计算
- 内置 tick_size 安全处理
- TPO (Time-Price Opportunity) Chart 标准实现

**改动范围**:

| 文件 | 改动 |
|------|------|
| `utils/sr_volume_profile.py` | 删除 (173 行) |
| `utils/sr_zone_calculator.py` | `_calculate_volume_profile()` 改用 `MarketProfile` API |
| `requirements.txt` | 新增 `market-profile>=0.3.0` |
| `scripts/validate_production_sr.py` | Volume Profile 测试适配新 API |

**安全边际**: `sr_zone_calculator.py` 的 `calculate()` 仅消费 `vpoc` 和 `value_area_high/low` 三个值。market-profile 库直接输出这三个标准字段，接口无缝对接。

### P1: sr_pivot_calculator.py → pandas-ta-classic 替换

**现状**: 118 行手写 Floor Trader Pivot Points (Standard/Fibonacci/Woodie)。代码无 bug，但属于标准公式。

**替换方案**: [pandas-ta-classic](https://github.com/pandas-ta/pandas-ta-classic) (PyPI `pandas_ta_classic>=0.2.0`)

- `ta.pivot_points(high, low, close, method='standard')` 一行替代
- 支持 Standard / Fibonacci / Woodie / Camarilla / DeMark 5 种方法
- 15M+ 月下载量，经过大规模验证

**改动范围**:

| 文件 | 改动 |
|------|------|
| `utils/sr_pivot_calculator.py` | 删除 (118 行) |
| `utils/sr_zone_calculator.py` | `_calculate_pivot_points()` 改用 `pandas_ta.pivot_points()` |
| `requirements.txt` | 新增 `pandas-ta-classic>=0.2.0` |

### P1: audit_logger.py → structlog 重构

**现状问题**:
1. `_load_prev_hash()` 并发读写 race condition
2. 无日志文件轮转 (日志持续增长)
3. 472 行自维护 I/O + 格式化代码

**重构方案**: [structlog](https://github.com/hynek/structlog) (PyPI `structlog>=24.0.0`)

- 结构化日志行业标准
- 原生 JSON output + processor pipeline
- 与 Python logging 无缝集成

**保留**: SHA256 hash chain 完整性验证逻辑 (审计核心，非 I/O 层)

**改动范围**:

| 文件 | 改动 |
|------|------|
| `utils/audit_logger.py` | 重写 I/O 层 → structlog；保留 `_compute_hash()` / `_verify_chain()` (~150 行保留，~320 行替换) |
| `requirements.txt` | 新增 `structlog>=24.0.0` |

**Phase 2 部署**: audit_logger 非实时交易路径，风险可控，但改动量较大，放 Phase 2 与 Prometheus 同期部署。

### P2: calibration_loader.py 线程安全加固

**现状问题**: 模块级全局变量 `_cached_calibration` 无 `threading.Lock` 保护，`on_timer()` (主线程) 与 Telegram 命令 (bot 线程) 可能并发读写。

**修复** (Phase 1, ~10 行改动):

```python
# calibration_loader.py — 新增
import threading
_cache_lock = threading.Lock()

def load_calibration(...):
    with _cache_lock:
        # ... 现有缓存逻辑 ...
```

**零 API 变更**: 对外接口 `load_calibration()` 签名不变，所有调用方无需修改。

### sr_swing_detector.py: 保留 + 补充测试

**原因**: 含自研 Spitsin 成交量加权算法 (Williams Fractal 变体)，无现成库实现此组合逻辑。代码审计未发现 bug。

**行动**: Phase 1 新增 `tests/test_sr_swing_detector.py` (~100 行)，覆盖:
- 标准 Williams Fractal 检测 (window=2)
- 成交量加权排序
- 边界条件 (数据不足、全 0 成交量)

---

## 验收标准

### Phase 1 质量验收

- [ ] `_validate_agent_output()` 已删除，Instructor 接管所有结构验证
- [ ] AIQualityAuditor 6 维 + 5 逻辑一致性 + 1 新 Regime Coherence = 12 维验证
- [ ] `diagnose_quality_scoring.py` 18 阶段全部 PASS
- [ ] `check_logic_sync.py` 新增 SYNC 项全部 PASS
- [ ] `smart_commit_analyzer.py` 新增 pattern 全部 PASS
- [ ] **P0**: `sr_volume_profile.py` 已删除，market-profile 替代，VPOC/VA 输出一致
- [ ] **P1**: `sr_pivot_calculator.py` 已删除，pandas-ta-classic 替代，pivot 输出一致
- [ ] **P2**: `calibration_loader.py` 线程安全加固完成，`_cache_lock` 存在
- [ ] **测试**: `test_sr_swing_detector.py` 新增并全部 PASS
- [ ] `validate_production_sr.py` 适配新 API 后全部 PASS

### Phase 2 质量验收

- [ ] Glassnode/FinBERT citation patterns 在 auditor 中注册
- [ ] `validate_data_pipeline.py` 覆盖 14-15 类数据源
- [ ] Kelly 公式 SSoT 在 `check_logic_sync.py` 中注册并 PASS
- [ ] `quality_analysis.py` 新增 3 个分析函数 + `/layer3` 展示
- [ ] **P1**: `audit_logger.py` 重构完成 (structlog I/O + SHA256 hash chain 保留)
- [ ] audit log race condition 消除，并发写入测试 PASS

### Phase 3 质量验收

- [ ] LangGraph StateGraph 通过 `architecture_verify.py` 合规检查
- [ ] 全部 20 阶段 `diagnose_quality_scoring.py` PASS
- [ ] `smart_commit_analyzer.py` 覆盖所有新增组件的回归规则
