# v40.0 PLAN.md 正式评审报告

## 评审框架: `docs/CODE_REVIEW_EVALUATION.md` v2.0

> ⚠️ **Self-Review** — 本评审中 PLAN 作者 (Claude) 与评审者 (Claude) 为同一 AI。总分自动降一档（A→B, B→C, C→D），需外部确认后才可升回原档。

---

## D1: 逻辑正确性 (权重 ×2) — 评分: 3/5

### 发现

**正确的逻辑**:
- P0-1 zip 映射错位 fix: `(direction, dim_name)` 元组替代并行数组 — 正确解决维度跳过时权重错配
- P0-6 背离与 reversal 互斥: `if not reversal_active` — 消除双重扣分 (-2 + -3 = -5)
- P0-3 alignment enforcement 3 处同步: 提取 `_enforce_alignment_cap()` — SSoT 模式正确
- Phase 5c aligned≥1 门槛 — 防止纯 order_flow 单信号交易

**逻辑问题**:
1. **Phase 1b 跨维度变量共享**: `rsi_4h` 在 trend (L121 rsi_macd_4h, weight=0.5) 和 momentum (L151 rsi_4h_trend, weight=1.0) 中各计一次。`macd_4h` 同理出现 3 次 (trend L121 + momentum L152 + momentum L160)。PLAN 声称 Phase 1 删除了重复，但 Phase 1b 重新引入了跨维度重复。**缺乏独立性论证**: 为何 RSI 水平 (trend 维度) 和 RSI 5-bar 趋势 (momentum 维度) 是独立信号？
2. **TRANSITIONING 检测条件**: `trend_dir == "BEARISH" and flow_dir == "BULLISH"` 要求 `trend_raw < -0.15` (trend 已 committed)。但早期转换 trend_raw = -0.10 (NEUTRAL) 时不触发。这意味着只能检测**已部分完成**的转换，不是**正在发生**的转换。
3. **Phase 7 TP=1.3 在 R/R 1.3:1 下**: breakeven 胜率 ~43.5%。但系统历史 MEDIUM 胜率是否 ≥43.5% 未在 PLAN 中给出基线数据。

**结论**: 核心逻辑正确，但跨维度重复计数和 TRANSITIONING 时序盲区属于"有 bug 但不直接影响资金安全"（TRANSITIONING 信号即使错也只用 LOW=30% 仓位）。

---

## D2: 状态机完整性 — 评分: 3/5

### 发现

**完整的状态路径**:
- TRANSITIONING 激活: trend_dir ≠ flow_dir + 2-cycle hysteresis → confirmed
- TRANSITIONING 退出: 任一 cycle 对齐 → hysteresis reset → NONE
- aligned=0 保护: TRANSITIONING + aligned=0 → 强制 HOLD

**状态机缺陷**:
1. **`_prev_regime_transition` 无具体实现** (CB-3): 当前代码库零出现。PLAN 说 "推荐 feature_dict 传入" 但未指定:
   - 谁存储 (`ai_strategy.py` 实例变量)
   - 如何传入 (`extract_features()` 注入)
   - 重启后行为 (首个 TRANSITIONING 被 hysteresis 吃掉)
   - `on_timer()` 后处理逻辑
2. **TRANSITIONING → NONE 的退出时间未定义**: 一旦 trend_dir 和 flow_dir 对齐，hysteresis 立即 reset。但反复交替 (TRANSITIONING → NONE → TRANSITIONING) 每次重新要求 2-cycle，是否会导致永远无法 confirm？在剧烈振荡市场中这种情况概率不低。
3. **Layer C regime 权重切换无渐变**: ADX 39.9→40.1 时 trend 权重跳 +50%，无状态平滑。

**结论**: 主路径闭合，但 hysteresis 状态管理是新增变量且未完整指定，符合 "有未覆盖的边缘路径，但概率低" 的 3 分锚点。

---

## D3: 对已有架构的侵入性 — 评分: 3/5

### 发现

**修改范围**:
- `compute_scores_from_features()` (565 行) — **核心评分引擎**: 重写投票逻辑 (Phase 1/1b)、新增 TRANSITIONING 检测 (Phase 2)、重写 net 计算 (Phase 3)
- `multi_agent_analyzer.py` — **生产路径**: Judge/Bull/Bear prompt 文本修改 (Phase 4) + 新方法 `_enforce_alignment_cap()` (Phase 5)
- `ai_quality_auditor.py` — 1 行正则 (Phase 6)
- 3 处 SSoT 参数同步 (Phase 7)

**侵入性评估**:
- Phase 1/1b/2/3 **重写** `compute_scores_from_features()` 的核心投票逻辑和 net 计算 — 这是中等到高侵入
- Phase 4 修改 AI prompt — 效果不可预测但回滚简单
- Phase 5 提取共享方法 — 结构性重构，每处用新方法替换内联代码
- Phase 7 数值修改 — 最小侵入

**回滚**: `git revert` 可原子回滚。但 Phase 1b 引入 33 个硬编码权重常量，长期维护需理解每个权重的来源。

**结论**: 对 `compute_scores_from_features()` 是深度修改，涉及核心评分引擎。但不修改订单提交、SL/TP 生命周期、事件处理等交易执行路径。符合 "中等侵入、需逐文件回滚"。

---

## D4: 生产环境风险 (权重 ×2) — 评分: 3/5

### 发现

**安全措施**:
- TRANSITIONING → LOW confidence → 30% 仓位 — 小仓位限制单笔损失
- aligned≥1 门槛 — 防止无确认交易
- 2-cycle hysteresis — 防止单周期噪音触发
- Phase 7 TP 参数有条件回滚 (7d 胜率不达标保留原值)
- 评分变化不影响 SL/TP 机械计算 (`calculate_mechanical_sltp()` 独立)

**生产风险**:
1. **单信号放大** (CB-2): TRANSITIONING regime 中 CVD-Price cross 有效权重 = 2.0 (base) × 2.0 (dim weight) = 4.0。如果 CVD 数据 stale/spike (Binance API 抖动)，这个单信号可翻转 net 评分并触发 TRANSITIONING 交易。系统**无 CVD 数据新鲜度检查**。
2. **ADX 边界跳变** (CB-5): ADX 39.9→40.1 时 Layer C 权重突变。虽然 hysteresis 可能缓解频率，但无法缓解幅度。
3. **order_flow 全面不可用**: Phase 2c fallback 使用 momentum。但如果 momentum 也不可用 (`_avail_mtf_4h=False`)，fallback 链终止，系统回退到无 TRANSITIONING 检测 — 这是正确的优雅降级。
4. **Phase 4 de-anchoring AI**: 移除 `_scores.net` 作为 "analytical anchor" 可能增加 AI 输出方差。在市场闪崩时，无锚定的 AI 可能产生不一致判断。但 temperature=0.3 + structured JSON output 限制了方差范围。

**结论**: 主要场景覆盖 (数据不可用降级、小仓位限制)，但 CVD 单信号放大风险和 ADX 边界跳变是常见 crypto 场景。符合 "部分场景有风险但不涉及资金" 的 3 分锚点 (TRANSITIONING 最多 30% 仓位)。

---

## D5: 预期收益真实性 — 评分: 3/5

### 发现

**可量化的收益**:
- 删除 3 个重复 4H 投票 → 可通过 feature_snapshots before/after 对比 SHORT 信号比例
- zip 映射 fix → 可验证维度跳过时权重正确
- `_enforce_alignment_cap()` 共享方法 → 3 处一致性可通过单元测试验证

**难以量化的收益**:
- "88% SHORT 信号问题" — PLAN 未给出时间段和市场背景。如果该时段 BTC 确实下跌 15%，88% SHORT 是**正确**行为，修复它反而破坏 alpha
- "55-65% HOLD 问题" — HOLD 率与胜率的关系未分析。如果 HOLD 过滤掉的是亏损交易，降低 HOLD 率会**降低**系统表现
- "TRANSITIONING 检测捕捉反弹" — 理论合理但无历史回测验证。反弹期间 order_flow 是否确实先于 trend 翻转？需要 CVD vs SMA200 的 lead-lag 分析
- Phase 4 de-anchoring — 效果完全无法在上线前验证 (CB-4)

**建议**: PLAN 应补充 88% SHORT 期间的 BTC 实际收益率，以及 HOLD counterfactual 分析结果 (v34.2 已有数据)。

**结论**: 逻辑上成立，有 before/after 对比方案，但核心预期收益 (TRANSITIONING alpha + 去锚定化) 无法短期验证。

---

## D6: 奥卡姆合规 — 评分: 2/5

### 发现

**核心问题诊断** (88% SHORT + HOLD 过高):
- **最简解**: Phase 1 (删除 3 个重复 4H 投票) — 一次删除解决计票偏差
- **次简解**: + Phase 6 (1 行正则) + Phase 5 (`_enforce_alignment_cap()` 提取)

**PLAN 实际引入的复杂度**:
1. Phase 1b: **33 个硬编码权重常量** + 3 个 weighted 数组 (~90 行新代码)
2. Phase 2/2b/2c: TRANSITIONING 检测 + hysteresis + fallback (~50 行新代码 + 1 个新状态变量)
3. Phase 3: Regime-dependent weighted net + Layer C 维度间权重 + ADX-based 权重切换 (~30 行)
4. Phase 4: 4 处 prompt 文本修改 (AI 行为不可预测变更)
5. Phase 7: TP 参数收紧 (与评分变化同时实施)

**合计**: ~170 行新逻辑 + 33 个权重常量 + 1 个新状态变量 + 4 处 prompt 变更 + 3 处 TP 参数变更 = **9 个独立变化在 1 个版本中**。

**对比最简解**: Phase 1 (删除 ~24 行) 就能解决 4H 三重计票。Phase 1b 的 33 个权重能否用 `_SIGNAL_ANNOTATIONS` 的 Nature 分类自动推导 (Leading→1.5, Sync→1.0, Sync-lag→1.2, Lagging→0.8) 而非手工编码？

**`compute_scores_from_features()` 膨胀**: 当前 565 行，Phase 1b/2/3 预计增加 ~170 行 → **735 行**。单个函数超过 700 行是显著的维护性风险。

**结论**: 为解决 "4H 重复计票" 这一核心问题，引入了 3 层加权架构、regime 检测、状态机、33 个常量、prompt 重写。属于 "明显过度设计"。Phase 1 + Phase 6 + Phase 5 足以验证核心假设，其余应分批验证后增量实施。

---

## D7: 可观测性/可调试 — 评分: 4/5

### 发现

**充分的可观测性**:
- TRANSITIONING 检测结果写入 `dim_scores["regime_transition"]` → 心跳可显示
- `_enforce_alignment_cap()` 有详细日志: `ℹ️ v40.0: aligned_layers={_al} but regime={_regime_trans} → allowing LOW confidence {_dec}`
- `_aligned_layers_cap` 字段记录降级路径
- Auditor regex 修复确保 TRANSITIONING 信号被正确审计

**可改进**:
- Phase 1b 加权过程无日志 — 当 `weighted_sum / weight_total` 产生意外 trend_raw 时，无法回溯哪个权重贡献了什么
- TRANSITIONING hysteresis 状态转换无日志 — 第一次检测到 vs 确认激活之间的状态不可见

**结论**: 关键决策路径有结构化日志，但中间加权过程需推断。

---

## D8: 上线前可验证性 — 评分: 3/5

### 发现

**可验证的部分**:
- Phase 8a: `smart_commit_analyzer.py` + `check_logic_sync.py` — 回归检测
- Phase 8b: `diagnose_feature_pipeline.py` + `diagnose_quality_scoring.py` — 评分系统完整性
- Phase 8c: pytest — 单元测试
- Phase 8d: 7 个 TRANSITIONING 专项测试用例
- Phase 8e: before/after 回测对比

**验证盲区** (CB-4):
- **Phase 4 de-anchoring 无验证方法**: 所有测试工具不重跑 AI agents。prompt 文本变更的效果完全无法上线前量化。
- **Phase 1b 权重优化无 sensitivity analysis**: 33 个权重中任一偏移 ±30%，信号分布变化如何？无计划。
- **Phase 7 TP 与 Phase 1-6 同时实施**: 无法归因性能变化是来自评分还是 TP 参数。

**结论**: 可通过 `diagnose.py` 和回测间接验证机械逻辑，但核心创新 (AI 行为变化 + 权重效果) 只能上线后观察。

---

## 特别检查项

### 1. 信号丢失
TRANSITIONING 检测要求 `trend_raw` 已 committed (-0.15)。早期转换 (trend_raw = -0.10 NEUTRAL) 不会被检测 → 可能错过最早期的趋势反转。但这也是一种保守设计，减少 false positive。**可接受**。

### 2. 状态持久化
`_prev_regime_transition` 是新增状态变量，重启后丢失。不影响资金安全 (只延迟 1 个 TRANSITIONING 周期)。但 PLAN 未指定存储方式。**需补充** (CB-3)。

### 3. 与已有机制的交互
- **cooldown**: TRANSITIONING 信号受 cooldown 限制 — 正确，SL 后 40min cooldown 不应被 TRANSITIONING bypass
- **circuit breaker**: TRANSITIONING LOW=30% 仓位仍受 CB 管理 — 正确
- **`_pending_reversal`**: TRANSITIONING 不修改反转逻辑 — 正确
- **trailing stop**: TRANSITIONING 不影响 trailing — 正确
- **Entry Timing**: Phase 10 已记录 ET 可能 REJECT TRANSITIONING 信号但不修改 — 需观察

### 4. 变量引用正确性
- `compute_scores_from_features()` L624-1189 — ✅ 经验证
- `_NET_DIRECTION_RE` L2915 — ✅ 行号可能因 Phase 1-5 偏移
- `_get_judge_decision()` L2217 — ✅ dead code path 确认
- `_run_structured_judge()` L4047 — ✅ 生产路径确认
- `analyze_from_features()` L4449 — ✅ 生产路径确认

### 5. 回滚计划
```bash
git revert <v40.0-commit-hash>  # 原子回滚全部 8 文件
```
- TP 参数 (Phase 7) 可独立回滚 — ✅
- 无运行时状态文件需清理 (`_prev_regime_transition` 是内存变量，重启自动清零) — ✅
- `_enforce_alignment_cap()` 回滚后 3 处内联代码恢复 — `git revert` 处理 — ✅

---

## 评分汇总

| 维度 | 分数 | 权重 | 加权分 | 关键理由 |
|------|:----:|:----:|:------:|---------|
| D1 逻辑正确性 | **3** | ×2 | **6** | 核心逻辑正确，但跨维度变量共享未论证独立性；TRANSITIONING 时序盲区 |
| D2 状态机完整性 | **3** | ×1 | **3** | 主路径闭合，hysteresis 状态管理未完整指定 (CB-3) |
| D3 架构侵入性 | **3** | ×1 | **3** | `compute_scores_from_features()` 核心重写，但不触及交易执行路径 |
| D4 生产环境风险 | **3** | ×2 | **6** | 30% 小仓位限制损失，但 CVD 单信号放大 8:1 + ADX 边界跳变 |
| D5 预期收益真实性 | **3** | ×1 | **3** | 理论合理，但 88% SHORT 缺市场背景；HOLD counterfactual 未引用 |
| D6 奥卡姆合规 | **2** | ×1 | **2** | 9 个独立变化 + 33 个硬编码权重 + 170 行新逻辑解决一个计票问题 |
| D7 可观测性 | **4** | ×1 | **4** | 关键决策有日志，加权过程可改进 |
| D8 上线前可验证性 | **3** | ×1 | **3** | 机械逻辑可测试，AI 行为变化和权重效果无法上线前验证 |

**加权总分: 30/50**

---

## 评级

| 加权总分 | 评级 | 行动 |
|---------|------|------|
| 30 | **C: 重大修改** | 返工核心逻辑后重新提交 |

> ⚠️ **Self-Review 降档**: C → **D: 否决** (自评降一档)。需外部评审确认后才可升回 C。

### 致命缺陷触发

**D6 = 2** → 触发致命缺陷规则 ("任何维度 ≤ 2 分 → 方案不通过，必须返工")。

即使总分达到 B 级 (33+)，D6=2 仍然阻止通过。

---

## 返工建议

### 最小可行方案 (MV-PLAN): 拆为 3 个独立版本

**v40.0a — Bug Fix Batch (低风险，立即可上)**:
- Phase 1: 删除 3 个重复 4H 投票 (纯删除)
- Phase 5: `_enforce_alignment_cap()` 提取 (SSoT 重构)
- Phase 6: Auditor 正则 1 行修复
- P0-1 zip fix: `(direction, dim_name)` 元组
- P0-6 背离互斥
- 预期: ~30 行修改/删除，零新增复杂度

**v40.0b — TRANSITIONING Detection (中风险，需单元测试)**:
- Phase 2/2b/2c: TRANSITIONING 检测 + hysteresis + fallback
- Phase 3: Weighted net (但维度间权重保持 1:1:1，仅 TRANSITIONING 时 order_flow 2x)
- Phase 4c: alignment 规则弹性化 (仅 L2069 措辞修改)
- CB-3: 明确 `_prev_regime_transition` 实施细节
- CB-5: 删除 "连续倍率" 声称
- 预期: ~80 行新增，1 个新状态变量

**v40.1 — Weight Optimization (高风险，需 sensitivity analysis 后实施)**:
- Phase 1b: 指标分类加权 (33 个权重)
- Phase 4a/4b: de-anchoring (AI prompt 变更)
- Layer C: ADX-based 维度间权重
- 前提: v40.0a/b 上线后收集 ≥50 个 TRANSITIONING 样本
- 前提: 对 top-5 权重做 ±30% sensitivity analysis

**v40.2 — TP Parameter Tuning (独立验证)**:
- Phase 7: TP 参数 (与评分完全解耦)
- Phase 7d: per-confidence 胜率验证
- 可独立回测、独立回滚

### D6 修复路径

将 D6 从 2→3 需要:
1. **拆版本**: 9 个变化 → 3-4 个独立可验证增量
2. **减常量**: 33 个手工权重 → 从 `_SIGNAL_ANNOTATIONS` Nature 自动推导 (减到 4 个类别权重)
3. **控膨胀**: `compute_scores_from_features()` 保持 <600 行 (v40.0a 删除后约 540 行)

---

## 结论

PLAN.md 的**问题诊断正确** (4H 重复计票、等权投票忽略信息密度、缺乏 regime transition 检测)，**解决方案合理** (分层加权、TRANSITIONING 检测、de-anchoring)。

但**实施打包过度** — 9 个独立变化捆绑为 1 个版本，违反奥卡姆原则和增量交付最佳实践。

**建议**: 拆为 v40.0a (bug fix) → v40.0b (TRANSITIONING) → v40.1 (weighting) → v40.2 (TP) 四步走，每步独立验证、独立回滚。v40.0a 可立即实施。
