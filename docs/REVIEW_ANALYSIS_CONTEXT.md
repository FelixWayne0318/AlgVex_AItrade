# AnalysisContext Implementation Plan — Code Review Evaluation

> ⚠️ **Self-Review** — 本评审为作者自评，总分自动降一档（A→B, B→C），需外部确认后才可升回原档。

---

## D1: 逻辑正确性 (权重 ×2) — **4 分**

**优点**:
- `MemoryConditions.from_feature_dict()` 的 direction 推导逻辑 (MACD lean → RSI fallback) 与现有 `_build_current_conditions()` 一致
- `to_dict()` 输出 `"macd": "bullish"/"bearish"` string 格式，正确对齐 `_score_memory()` 的 parse 逻辑
- `ConfidenceChain` 的 append-only 设计避免了竞态问题

**缺陷**:
1. ~~**`filter_output_tags()` 调用数不一致**: 方案标题说"16 个调用点"，Phase 3b 正文说"~10 处 production"，代码审计实际发现 **14 处**（debate 4 + judge/ET/risk 各 1-2 + replay 7）。数字不一致增加实施风险~~（已在 v1.3 区分 production vs replay，但文档仍混用 16/~10）
2. **`quality_weight` 阈值边界模糊**: `qs < 40` → 0.3, `qs < 60` → 0.5, `qs < 80` → 0.8。但 `qs >= 80` 时 quality_weight 保持 1.0（默认值），**没有显式 `else` 分支**。逻辑正确但代码风格易误读
3. **`bb_position_30m` 单位**: `from_feature_dict()` 中 `fd.get("bb_position_30m", 0.5) * 100`，但 `to_dict()` 输出 `"bb": self.bb_position_30m`。如果 feature_dict 中 bb_position_30m 已经是 0-100 范围（而非 0-1），则会变成 0-10000。需确认 feature_dict 中的实际单位

**评级理由**: 有不影响交易结果的小瑕疵（数字不一致、边界显式性），但核心逻辑 (to_dict key 对齐、direction 推导) 正确。

## D2: 状态机完整性 — **4 分**

**优点**:
- `AnalysisContext` 生命周期清晰：`analyze()` 入口创建 → 逐步填充 → 返回，不跨调用
- 快照模式沿用现有 `_entry_winning_side` 模式，状态传递可靠
- `ConfidenceChain` 是 append-only，无状态回退风险

**缺陷**:
1. **`_entry_memory_conditions` 初始化**: 方案在 `ai_strategy.py.__init__` 中初始化，但未说明 `_clear_position_state()` 是否需要同步清除。现有 `_entry_winning_side` 在 `_clear_position_state()` 中被清除 — `_entry_memory_conditions` 也必须
2. **`ctx.memory_conditions` 填充时机**: Phase 5e 中在 `analyze()` 的 structured path 中填充，但如果 `feature_dict` 为 None（text fallback path），`ctx.memory_conditions` 保持 None。Phase 5a 步骤 1 中 `ctx.memory_conditions.to_dict()` 会因 None 而跳过 — 行为正确但依赖隐式 None 检查

**评级理由**: 主路径闭合，边缘路径（clear state 同步）有合理推导但文档未显式声明。

## D3: 对已有架构的侵入性 — **4 分**

**优点**:
- Phase 1 纯增量，新增文件不触碰现有代码
- Phase 2 只改参数传递，不改逻辑
- `audit()` 增加可选 `context` 参数，完全向后兼容
- 快照模式是现有架构的自然延伸

**缺陷**:
1. **Phase 5 修改 4 个文件**: `memory_manager.py`, `multi_agent_analyzer.py`, `event_handlers.py`, `ai_strategy.py`。虽然每处改动小，但涉及开仓→平仓完整链路
2. **`_run_structured_*()` 签名变更**: 所有 4 个 structured agent 方法增加 `ctx` 参数，调用处全部需修改

**评级理由**: 微侵入，每处 1-5 行回滚，但涉及多文件协调。

## D4: 生产环境风险 (权重 ×2) — **4 分**

**优点**:
- 向后兼容设计：旧记忆无 `conditions_v2` → 退回旧 parse，不中断
- `AnalysisContext` 不参与订单执行路径 (`_execute_trade`, `calculate_mechanical_sltp` 不变)
- Phase 间独立可回滚
- `_safe_filter_tags()` 的 INCONCLUSIVE fallback 防止空 evidence 导致的下游异常

**缺陷**:
1. **Risk reflection prompt 变更增加 1 个 LLM 输出字段**: `generate_reflection()` 从 4 key → 5 key，如果 LLM 输出不稳定（偶尔不生成 risk key），`_extract_role_reflection()` fallback 到 judge — 安全但不完美
2. **`conditions_v2` 数据膨胀**: 每条记忆新增 12 个字段，500 条记忆文件大小增长 ~15-20%。不影响性能但需关注

**评级理由**: 主要极端场景覆盖，不涉及订单执行路径。LLM 输出不稳定有 fallback。

## D5: 预期收益真实性 — **4 分**

**优点**:
- 重复计算消除 (valid_tags ×6 → ×1) 是**确定性优化**，零风险
- Auditor/Agent 数据对齐是**结构性修复**，消除已验证的不对称
- 记忆维度扩展 (5 → 12) 的收益可通过记忆匹配分数分布变化观测

**缺陷**:
1. **"消除不对称"的实际影响难以量化**: Auditor 改读 feature_dict 后，quality_score 是否会显著变化？缺乏基线对比
2. **confidence_chain 的消费者未定义**: 记录了信任链但无明确的下游使用场景（日志？报告？决策？）

**评级理由**: 逻辑上成立，有可观测指标（重复计算次数、记忆匹配分数），但部分收益（质量分变化）需运行后验证。

## D6: 奥卡姆合规 — **4 分**

**优点**:
- 移除了 `DataQualityFlags` (11 个 bool → 简单 List[str])
- 移除了 `ValidatedAgentOutput` (3c 已删除)
- `ConfidenceChain` 设计极简：一个 list + 几个 property
- Phase 6 主动清理废弃代码

**缺陷**:
1. **`AnalysisContext` 的 `adx_1d` 字段**: 同时存在于 `ctx.features['adx_1d']` 和 `ctx.adx_1d`，"频繁引用单独存"的理由不充分 — 一个 `.get()` 调用不算复杂
2. **`MemoryConditions` 同时有 `from_feature_dict()` + `to_dict()` + `to_legacy_conditions_str()`**: 三个序列化方法有轻微过度，`to_legacy_conditions_str()` 无明确消费者

**评级理由**: 总体精简，有少量冗余字段/方法但不影响理解。

## D7: 可观测性/可调试 — **4 分**

**优点**:
- `ConfidenceChain` 提供完整的 confidence 变更历史
- `_safe_filter_tags()` 的 WARNING 日志在 evidence 被清空时触发
- `data_warnings` 追踪数据降级
- `snapshot_id` 提供跨阶段关联

**缺陷**:
1. **`AnalysisContext` 无 `__repr__`/`to_dict()`**: 调试时无法方便地打印完整 context 状态
2. **confidence_chain 无日志输出点**: 方案记录了 chain 但未说明何时/何处打印到日志

**评级理由**: 关键路径可观测 (filter WARNING, confidence chain)，但缺少便利的 debug 输出。

## D8: 上线前可验证性 — **4 分**

**优点**:
- v1.3 新增了完整的单元测试计划 (14 个测试用例)
- 每 Phase 都有验证命令 (`smart_commit_analyzer.py`, `check_logic_sync.py`)
- Phase 5 有旧记忆兼容性验证脚本
- 全流程有 `--dry-run` 验证

**缺陷**:
1. **测试用例是计划而非实现**: 测试文件 `tests/test_analysis_context.py` 尚未编写
2. **缺少集成测试**: 单元测试验证各组件，但"context 贯穿 analyze() 全流程"的集成验证依赖 `--dry-run`（需真实 API）

**评级理由**: 有明确的手动验证步骤 + 单元测试计划，但测试尚未实现。

---

## 评分汇总

| 维度 | 分数 | 权重 | 加权分 |
|------|------|------|--------|
| D1 逻辑正确性 | 4 | ×2 | 8 |
| D2 状态机完整性 | 4 | ×1 | 4 |
| D3 架构侵入性 | 4 | ×1 | 4 |
| D4 生产环境风险 | 4 | ×2 | 8 |
| D5 预期收益真实性 | 4 | ×1 | 4 |
| D6 奥卡姆合规 | 4 | ×1 | 4 |
| D7 可观测性/可调试 | 4 | ×1 | 4 |
| D8 上线前可验证性 | 4 | ×1 | 4 |
| **总计** | | | **40** |

**原始评级**: **B: 有条件批准** (33-41 范围)

**自评降档**: B → **C: 重大修改**

---

## 特别检查项

### 1. 信号丢失
**通过**。方案不改变信号生成逻辑 (Bull/Bear/Judge/ET/Risk prompt 不变)。`_safe_filter_tags()` 的 INCONCLUSIVE fallback 防止 evidence 被全部过滤后的静默丢失。

### 2. 状态持久化
**通过 (有条件)**。`trading_memory.json` 新增字段 (`conditions_v2`, `ai_quality_score`) 是纯增量，旧代码忽略新字段。但需确认 `_entry_memory_conditions` 在 `_clear_position_state()` 中被清除。

### 3. 与已有机制的交互
**通过**。不触碰 cooldown、layer_orders、emergency SL、`_pending_reversal`。快照模式与现有 `_entry_winning_side` 完全一致。

### 4. 变量引用正确性
**通过**。方案引用的方法名 (`_run_structured_debate` 等) 与实际代码一致 (line 3681, 3887, 3962, 4015)。行号引用经代码审计确认准确。

### 5. 回滚计划
**通过**。每 Phase 独立 `git revert`，Phase 5 的 `trading_memory.json` 新字段向后兼容。

---

## 必修修复项 (升至 B 级的条件)

| # | 问题 | 严重度 | 修复方式 |
|---|------|--------|---------|
| ~~F1~~ | ~~方法名引用错误~~ — **代码验证确认方法名正确** (`_run_structured_debate` 等, line 3681+) | ~~中~~ → 无 | 无需修复 |
| F2 | `filter_output_tags()` 调用数文档不一致 (16/~10/14) | 低 | 统一为代码审计确认的 14 处 |
| F3 | `_clear_position_state()` 未提及清除 `_entry_memory_conditions` | 中 | Phase 5a 新增说明 |
| F4 | `AnalysisContext.adx_1d` 冗余字段 | 低 | 移除，直接从 `ctx.features` 读取 |
| F5 | `MemoryConditions.to_legacy_conditions_str()` 无消费者 | 低 | 移除 (奥卡姆) |
| F6 | `bb_position_30m` 单位确认缺失 | 中 | 添加注释确认 feature_dict 中 bb_position_30m 的单位范围 |
| F7 | `confidence_chain` 无日志输出点 | 低 | 在 analyze() 返回前添加 chain summary 日志 |
| F8 | `AnalysisContext` 缺少 `to_dict()` debug 方法 | 低 | 新增 `to_dict()` 方法 |

**修复后预期评级**: B (有条件批准) → 自评降档 → C (需外部确认升回 B)
