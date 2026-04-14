# v34.0 AI Quality Scoring System — Comprehensive Redesign

---

## Code Review Evaluation (per CODE_REVIEW_EVALUATION.md v2.0)

> ⚠️ **Self-Review** — 本评审为作者自评，总分自动降一档（A→B, B→C），需外部确认后才可升回原档。

### D1: 逻辑正确性 (权重 ×2) — **4/5**

**发现的问题 (已修复)**：

| # | Bug | 严重性 | 状态 |
|---|---|---|---|
| BUG-1 | Tag 计数错误: 方案写 "25 bullish / 24 bearish" 但实际为 **27 / 26** | 中 (不影响运行时，但误导实施者) | ✅ 已修复 |
| BUG-2 | Edge case 表自相矛盾: "1 bull + 1 bear → LONG" 先写 "0 penalty" 再自我纠正为 "8 penalty" | 中 (文档中的逻辑混乱) | ✅ 已修复 |
| BUG-3 | Section 5.2 集成代码用 `analysis_context` 变量名，但 `audit()` 签名是 `ctx: AnalysisContext` | 高 (直接实施会 NameError) | ✅ 已修复 |
| BUG-4 | risk_env 表 Volatility Regime 写 "+1~2"，实际 HIGH→+0, 仅 EXTREME→+1 per TF | 低 (方案正确使用 `level` 而非 `score`，不影响逻辑) | ✅ 已修复 |

**逻辑正确性确认**:
- Check 1 算法：weak filter → directional count → conflict ratio → penalty 三阶段正确。FR_FAVORABLE_* 在 weak 和 evidence 集合的 overlap 处理文档清晰
- Check 2 正则：`LEAN_(BULLISH|BEARISH)_(\d+)of(\d+)` 匹配 `compute_scores_from_features()` 的实际输出格式 ✅
- Check 3 判断：仅 HIGH+HIGH → 6 penalty，单条件判断无边界歧义 ✅
- Check 4/5 算法：标准数值比较/集合操作，无 off-by-one 风险 ✅
- Judge output key: 方案使用 `judge_decision.get('decision', '')` — 与 JUDGE_SCHEMA (`"decision": str`) 和 `audit()` 现有代码 (line 670) 一致 ✅

**扣分原因**: 文档中存在 4 处需要修复的错误 (虽均已修复，但原始提交包含这些错误)。

### D2: 状态机完整性 — **5/5**

- **QualityReport 生命周期**: 每个 `audit()` 调用创建、填充、返回、丢弃。无持久化状态，无状态转移需要管理
- **新字段默认值**: `reason_signal_conflict=0`, `confidence_risk_conflict=0` — 不会导致未初始化状态
- **Flag 累积**: 追加到 `report.flags[]` — 列表操作，无状态机
- **所有 check 方法**: `@staticmethod`，无实例状态，无副作用
- **重启安全**: 无新增持久化文件，无新增进程间状态

### D3: 对已有架构的侵入性 — **5/5**

- **修改范围**: 仅 `ai_quality_auditor.py` (5 个新 @staticmethod + 2 个 dataclass 字段 + audit() 中 ~30 行集成代码)
- **核心交易路径**: `on_timer()` → `_execute_trade()` → `on_order_filled()` — 完全不接触
- **新增 import**: 仅从 `prompt_constants.py` 导入已有常量 (`BULLISH_EVIDENCE_TAGS`, `BEARISH_EVIDENCE_TAGS`)
- **回滚**: `git revert <hash>` 即可，无需清理任何持久化文件
- **纯增量**: 新 checks 插入 audit() 的 Step 3d 之后、Step 4 之前，不修改任何现有 step

### D4: 生产环境风险 (权重 ×2) — **5/5**

- **数据缺失**: 所有 5 个 check 有 null-safety guard — `judge_decision` 为 None 时 skip（0 penalty），与现有 auditor 行为一致
- **异常传播**: 所有 check 是 `@staticmethod`，内部无 try/except 吞异常。若 `decisive_reasons` 包含非字符串元素，`in` 操作符仍安全 (set lookup)
- **Score 范围**: `max(0, 100 - penalty)` 保证 score ∈ [0, 100]，新增 penalty 最大 18 分，不可能导致负分
- **API 影响**: 零 — 不增加任何 API 调用，不修改 AI agent prompt
- **极端市场**: 新 checks 仅审计 AI 输出质量，不影响 SL/TP/仓位/订单执行
- **性能**: 5 个 set lookup + 1 个 regex match + 2 个 float 比较 → 纳秒级开销

### D5: 预期收益真实性 — **4/5**

**优点**:
- Check 1 (Reason-Signal Alignment) 捕获的是**明确的逻辑错误** — Judge 自己选的 tag 和自己的决策矛盾，这不存在信息不对称问题
- Check 3 (Confidence-Risk) 的不对称设计 (只罚高估风险，不罚保守) 符合交易系统的风险偏好
- Section 7.4 Layer 3 提出了验证路径：先运行 correlation script 确认 quality score 有预测价值，再增加新 penalty

**扣分原因**:
- 3 个 informational checks (Check 2/4/5) 的价值完全取决于**未来** Layer 3 correlation 分析结果，当前无法验证
- 方案诚实承认只覆盖 52 个 failure modes 中的 ~19% (从 13% 提升)，改进是真实但有限的

### D6: 奥卡姆合规 — **4/5**

**优点**:
- 2 penalized + 3 informational 的分层设计避免了过度惩罚
- 所有 check 是 @staticmethod，无新类/新配置项/新抽象层
- 复用现有常量 (`BULLISH_EVIDENCE_TAGS`, `_TAG_TO_CATEGORIES`, `_WEAK_SIGNAL_TAGS`)，无重复定义

**轻微过度**:
- Layer 1 (Input Validation) 和 Layer 3 (Outcome Feedback) 的完整实现方案写了 ~700 行，但明确标注 "NOT in v34.0 scope"。作为文档参考合理，但增加了方案的认知负荷
- Section 7.4.3 包含完整 ~200 行 Python 脚本代码嵌入方案文档中，应该直接作为文件而非文档内容

### D7: 可观测性/可调试 — **5/5**

- **Flag 命名**: 每个 check 产生带前缀的 flag (`REASON_SIGNAL_CONFLICT:`, `DEBATE_CONVERGENCE:` 等)，可 grep
- **Heartbeat**: `to_summary()` 输出 `reason_sig=12` / `conf_risk=6` → Telegram 私聊可见
- **Penalty 透明**: Flag 包含完整决策上下文 (`conflict_ratio=0.75`, `3 opposing / 4 directional`)
- **Feature snapshot**: 通过现有 `to_dict()` → `ctx.quality_flags` 自动持久化
- **Production monitoring checklist** (Section 10): 明确 7 天期待频率范围和异常处理

### D8: 上线前可验证性 — **4/5**

- **单元测试**: Section 11.7 提供完整 pytest 示例 (36 test cases, 6 test classes)
- **smart_commit_analyzer**: 3 条新规则 (P1.115-P1.117) 防回归
- **diagnose_quality_scoring**: Stage 8 集成方案

**扣分原因**:
- 没有针对**完整 audit() 流程**的集成测试 — 即构造一个完整 AnalysisContext，调用 audit()，验证 v34.0 flags 出现在返回的 QualityReport 中
- Layer 3 correlation script 是验证方案价值的关键，但方案建议 "先运行再决定"，意味着实施前无法确认收益

---

### 加权计算

```
D1 = 4 (×2 = 8)    逻辑正确性
D2 = 5 (×1 = 5)    状态机完整性
D3 = 5 (×1 = 5)    架构侵入性
D4 = 5 (×2 = 10)   生产环境风险
D5 = 4 (×1 = 4)    预期收益真实性
D6 = 4 (×1 = 4)    奥卡姆合规
D7 = 5 (×1 = 5)    可观测性
D8 = 4 (×1 = 4)    上线前可验证性
─────────────────────────
总分 = 45/50 → A 级
```

**自评降档**: A → **B 级 (有条件批准)**

### 有条件批准 — 需修复标记问题

1. ✅ **BUG-1~4 已修复** (tag 计数、edge case 矛盾、变量名、risk_env 表)
2. ⚠️ **建议**: 实施时增加一个完整 audit() 集成测试 (构造 AnalysisContext → audit() → 验证 QualityReport 中 v34.0 flags)
3. ⚠️ **建议**: Layer 3 correlation script (Section 7.4.3) 应从方案文档抽出为独立文件，而非嵌入方案

### 特别检查项 (逐条过)

| # | 检查项 | 结论 |
|---|---|---|
| 1 | **信号丢失** | ✅ 不适用 — v34.0 是 post-hoc audit，不过滤/阻止任何信号 |
| 2 | **状态持久化** | ✅ 无新增持久化文件。QualityReport 新字段有 default=0，向后兼容 |
| 3 | **与已有机制交互** | ✅ 不接触 cooldown/layer_orders/emergency SL/_pending_reversal。仅在 audit() 内部增加 checks |
| 4 | **变量引用正确性** | ✅ 已验证: `judge_decision.get('decision')` 匹配 JUDGE_SCHEMA line 1326; `ctx.scores` 匹配 AnalysisContext line 151; `ctx.bull_output`/`ctx.bear_output` 匹配 line 162-163。~~BUG-3: `analysis_context` 应为 `ctx`~~ 已修复 |
| 5 | **回滚计划** | ✅ Section 12 提供 per-layer rollback 命令。无需手动清理状态文件 |

---

## 0. Research Summary

### 0.1 External AI Quant Failure Modes (Industry Research)

| Category | Key Finding | Source |
|----------|------------|--------|
| LLM Hallucination | 3-27% in financial contexts; even best models hallucinate 7/1000 prompts; MIT correction reduced 4%→1% | Hughes 2025, MIT DSpace |
| Overconfidence | Structural in next-token training + RLHF reward optimization; confidence reflects reward, not calibration | ICLR 2025, KDD 2025 |
| Multi-Agent Degeneration | Echo chamber: agents converge by confirming shared bias, not finding truth; 41-86.7% failure rate in production | EMNLP 2024/2025, MASFT |
| Financial Competence | General LLM intelligence shows "negligible or negative correlation" with trading returns (LiveTradeBench, 21 models) | LiveTradeBench Nov 2025 |
| Bullish Bias | FinGPT demonstrates consistent bullish directional bias — aligns with uptrends, lags/flattens in downturns | FinGPT Assessment 2025 |
| Trial-and-Error | CAIA benchmark: some models jump 39→62% accuracy across 5 tries = guessing, not reasoning | CAIA (arXiv) |
| Cascading Failures | 79% of multi-agent failures originate from specification/coordination, not technical implementation | MASFT 2025 |
| Alpha Decay | US markets ~5.6%/year, Europe ~9.9%; momentum strategies last ~10 months before turning negative | Maven Securities |
| Signal Quality | Crypto time-series near Brownian noise; simpler models (even Naive) can outperform complex ML/DL | Lahmiri & Bekiros |
| Regulatory Pressure | IOSCO March 2025: mandatory development/testing/monitoring pipeline + data quality + transparency | IOSCO |

### 0.2 Internal System Analysis: 52 Failure Modes

Across 12 pipeline phases, 52 distinct failure modes were identified:

| Phase | Failure Modes | Currently Detectable by Auditor |
|-------|:---:|:---:|
| Phase 0: Data Assembly | 4 | 1 (phantom citation) |
| Phase 1: Bull/Bear Debate | 4 | 2 (tag validation + coverage) |
| Phase 1.5: Debate Round 2 | 2 | 0 |
| Phase 2: Judge Decision | 4 | 2 (confluence + citation) |
| Phase 2.5: Entry Timing | 3 | 1 (coverage) |
| Phase 3: Risk Manager | 4 | 1 (coverage) |
| Phase 4: Memory System | 4 | 0 |
| Phase 5: Validation Layer | 4 | 0 |
| Phase 6: Quality Audit Itself | 8 | N/A (self-referential) |
| Phase 7-12: Downstream | 15 | 0 |
| **Total** | **52** | **~7 (13%)** |

**Key insight**: Current auditor covers 6 citation-level dimensions. It catches ~40% of errors it CAN see (data coverage, value accuracy, zone claims, comparison direction, MTF responsibility, confluence). It catches 0% of logic-level errors (reasoning coherence, confidence calibration, debate quality, memory contamination).

### 0.3 Current Auditor Architecture (6 Dimensions)

```
Dimension 1: Data Coverage Rate        — Does AI mention required data categories?
Dimension 2: SIGNAL_CONFIDENCE_MATRIX  — Does AI skip low-reliability signals?
Dimension 3: MTF Responsibility        — Does each agent respect its timeframe?
Dimension 4: Citation Accuracy         — DI/MACD/EMA cross direction, value %, zone claims
Dimension 5: Production Quality        — Score + regime + flags
Dimension 6: User-Facing Report        — heartbeat summary + to_dict
```

These are all **citation-level** checks: "Did the AI correctly reference the data it was given?"

What's missing: **logic-level** checks: "Did the AI correctly reason with the data it referenced?"

---

## 1. Design Philosophy

### 1.1 What a Post-Hoc Auditor CAN and CANNOT Do

**CAN** (implementable now):
- Verify internal consistency (reasons vs decision, confidence vs risk environment)
- Detect structural incoherence (bullish reasons → SHORT decision)
- Flag information-asymmetry divergence for correlation analysis
- Validate debate quality (conviction spread, argument diversity)
- Check schema compliance beyond `_validate_agent_output()`

**CANNOT** (requires outcome feedback pipeline):
- Judge whether AI was "right" (needs forward-looking price data)
- Assess HOLD quality (needs counterfactual: "what if we traded?")
- Calibrate confidence historically (needs win-rate-by-confidence-bucket)
- Detect subtle reasoning errors (needs LLM-as-judge, recursive/expensive)

### 1.2 Design Principles

1. **Asymmetric penalties**: Only penalize clearly wrong patterns (overconfidence in danger), never penalize conservative caution
2. **Information-aware**: Don't penalize AI for disagreeing with `_scores` — Judge has more information than `_scores` summarizes
3. **Incremental**: Add to existing 6-dimension system, don't replace it
4. **Observable**: Every check produces a named flag for diagnosis
5. **Testable**: Every check is a `@staticmethod` with deterministic inputs/outputs

---

## 2. New Checks (2 Penalized + 3 Informational)

### 2.1 Check 1: Reason-Signal Alignment (PENALIZED — primary value)

**What it catches**: Judge says LONG but its own `decisive_reasons` tags are bearish. This is always wrong — no information asymmetry issue, because we're checking the AI's internal consistency.

**Why this is the most valuable check**: Unlike other checks, there's no legitimate reason for Judge to say LONG while citing 3 bearish tags and 1 bullish tag. The `decisive_reasons` are the Judge's OWN selected evidence for its decision.

```python
@staticmethod
def _check_reason_signal_alignment(
    decision: str,
    decisive_reasons: List[str],
) -> tuple[int, str]:
    """
    Check if Judge's decisive_reasons tags align with its decision.

    Returns (penalty, flag_text). HOLD/CLOSE/REDUCE exempt.
    Need >= 2 directional tags (after excluding weak signals).

    Uses BULLISH_EVIDENCE_TAGS (27 tags) and BEARISH_EVIDENCE_TAGS (26 tags)
    from prompt_constants.py. Weak signals excluded via _WEAK_SIGNAL_TAGS (9 tags).
    """
```

#### 2.1.1 Tag Classification Reference

**Bullish Evidence Tags** (27 tags, from `prompt_constants.py:BULLISH_EVIDENCE_TAGS`):
```
TREND_1D_BULLISH, DI_BULLISH_CROSS, TREND_ALIGNED,
FR_FAVORABLE_LONG, MACD_BULLISH_CROSS, RSI_CARDWELL_BULL,
MOMENTUM_4H_BULLISH,
RSI_BULLISH_DIV_4H, RSI_BULLISH_DIV_30M,
MACD_BULLISH_DIV_4H, MACD_BULLISH_DIV_30M,
OBV_BULLISH_DIV_4H, OBV_BULLISH_DIV_30M,
CVD_POSITIVE, CVD_ACCUMULATION,
BUY_RATIO_HIGH, OBI_BUY_PRESSURE, OBI_SHIFTING_BULLISH,
OI_LONG_OPENING, TOP_TRADERS_LONG_BIAS, TAKER_BUY_DOMINANT,
NEAR_STRONG_SUPPORT, SMA_BULLISH_CROSS_30M, SMA_BULLISH_CROSS_4H,
EMA_BULLISH_CROSS_4H, MACD_1D_BULLISH, PREMIUM_POSITIVE
```

**Bearish Evidence Tags** (26 tags, from `prompt_constants.py:BEARISH_EVIDENCE_TAGS`):
```
TREND_1D_BEARISH, DI_BEARISH_CROSS,
FR_FAVORABLE_SHORT, MACD_BEARISH_CROSS, RSI_CARDWELL_BEAR,
MOMENTUM_4H_BEARISH,
RSI_BEARISH_DIV_4H, RSI_BEARISH_DIV_30M,
MACD_BEARISH_DIV_4H, MACD_BEARISH_DIV_30M,
OBV_BEARISH_DIV_4H, OBV_BEARISH_DIV_30M,
CVD_NEGATIVE, CVD_DISTRIBUTION,
BUY_RATIO_LOW, OBI_SELL_PRESSURE, OBI_SHIFTING_BEARISH,
OI_SHORT_OPENING, TOP_TRADERS_SHORT_BIAS, TAKER_SELL_DOMINANT,
NEAR_STRONG_RESISTANCE, SMA_BEARISH_CROSS_30M, SMA_BEARISH_CROSS_4H,
EMA_BEARISH_CROSS_4H, MACD_1D_BEARISH, PREMIUM_NEGATIVE
```

**Weak Signal Tags** (9 tags, from `ai_quality_auditor.py:_WEAK_SIGNAL_TAGS`):
These tags always have low or no directional value. When they are the ONLY tag covering a data category, that category is not penalized as missing. They are excluded from directional counting in Check 1.
```
FR_IGNORED,               # FR ≈ 0%, no cost/benefit
FR_FAVORABLE_LONG,        # FR < -0.001%, negligible edge
FR_FAVORABLE_SHORT,       # FR > 0.001%, negligible edge
FR_TREND_RISING,          # Direction-only, no magnitude
FR_TREND_FALLING,         # Direction-only, no magnitude
SENTIMENT_NEUTRAL,        # Balanced sentiment, nothing to flag
SENTIMENT_CROWDED_LONG,   # Threshold 0.60 is very low, edge case
SENTIMENT_CROWDED_SHORT,  # Threshold 0.60 is very low, edge case
OBI_BALANCED              # |OBI| ≤ 0.2, neutral orderbook pressure
```

**⚠️ Overlap note**: `FR_FAVORABLE_LONG` and `FR_FAVORABLE_SHORT` appear in BOTH `BULLISH/BEARISH_EVIDENCE_TAGS` AND `_WEAK_SIGNAL_TAGS`. The weak filter is applied FIRST, so these tags are excluded from directional counting. This is intentional — their directional value is negligible (< -0.001% FR edge), so they should not contribute to conflict ratio.

**Neutral Tags** (not in any of the above sets): Tags like `EXTENSION_OVEREXTENDED`, `VOL_HIGH`, `LIQUIDATION_RISK`, `BB_LOWER_ZONE` — these are condition/risk descriptors with no inherent directional bias. They are ignored in Check 1.

#### 2.1.2 Algorithm

```python
@staticmethod
def _check_reason_signal_alignment(
    decision: str,
    decisive_reasons: List[str],
) -> tuple[int, str]:
    # 0. Only check directional decisions
    if decision not in ('LONG', 'SHORT'):
        return (0, '')

    # 1. Filter out weak signals (applied BEFORE directional count)
    strong_reasons = [t for t in decisive_reasons if t not in _WEAK_SIGNAL_TAGS]

    # 2. Count directional tags
    bullish = sum(1 for t in strong_reasons if t in BULLISH_EVIDENCE_TAGS)
    bearish = sum(1 for t in strong_reasons if t in BEARISH_EVIDENCE_TAGS)
    total_directional = bullish + bearish

    # 3. Need >= 2 directional tags to have a meaningful sample
    if total_directional < 2:
        return (0, '')

    # 4. Calculate conflict ratio
    if decision == 'LONG':
        conflict_ratio = bearish / total_directional
    else:  # SHORT
        conflict_ratio = bullish / total_directional

    # 5. Penalty thresholds
    if conflict_ratio >= 0.75:
        penalty = 12
    elif conflict_ratio >= 0.50:
        penalty = 8
    else:
        return (0, '')

    # 6. Build human-readable flag
    flag = (f"decision={decision} conflict_ratio={conflict_ratio:.2f} "
            f"({bearish if decision == 'LONG' else bullish} opposing / "
            f"{total_directional} directional) penalty={penalty}")
    return (penalty, flag)
```

| conflict_ratio | Penalty | Rationale |
|:-:|:-:|---|
| >= 0.75 | 12 | 3/4+ tags oppose decision — reasoning chain fundamentally broken |
| >= 0.50 | 8 | Majority tags oppose — significant incoherence |
| < 0.50 | 0 | Minority opposing tags = legitimate risk acknowledgment |

#### 2.1.3 Edge Cases

| Edge Case | Behavior | Rationale |
|---|---|---|
| `decisive_reasons = []` | 0 penalty | No tags to evaluate |
| `decisive_reasons = None` | 0 penalty | Caller passes `[]` default |
| All tags are weak signals | 0 penalty | total_directional < 2 |
| All tags are neutral (non-directional) | 0 penalty | total_directional = 0 |
| decision = 'HOLD' / 'CLOSE' / 'REDUCE' | 0 penalty | No directional claim |
| 1 bullish + 1 bearish → LONG | 8 penalty | ratio=1/2=0.50 ≥ 0.50 → triggers moderate penalty. 50/50 split with a directional decision = incoherent |
| Tags contain duplicates | Counted per-occurrence | `[CVD_POSITIVE, CVD_POSITIVE, CVD_NEGATIVE]` → 2 bull + 1 bear → ratio 0.33 for LONG → 0 penalty |
| Unknown tags (not in any set) | Ignored (treated as neutral) | Future-proof — new tags don't break check |

**Exemptions**: HOLD/CLOSE/REDUCE (no directional claim to validate), < 2 directional tags (insufficient sample).

### 2.2 Check 2: Signal-Score Divergence (INFORMATIONAL — no penalty)

**What it catches**: Judge's decision direction opposes `_scores['net']` consensus.

**Why informational only**: Research confirmed `_scores['net']` is an incomplete proxy. Judge receives 7+ information sources NOT captured by `_scores`:

| Extra Information (Judge has, `_scores` doesn't) | Impact |
|---|---|
| S/R zone proximity + hold probability | Can flip direction near strong zone |
| Trading memory (up to 2000 chars, 5W+5L) | Historical pattern recognition |
| Bull/Bear conviction spread (0.0-1.0) | Debate quality signal |
| Bull/Bear reasoning text (1500 chars each) | Qualitative argument strength |
| Position P&L context | Existing exposure affects new decisions |
| FR block directionality (`fr_block_context`) | Consecutive block suppression |
| Regime-dependent interpretation under ADX context | ADX>40 changes meaning of signals |

Penalizing divergence would penalize the AI for being smarter than a rule-based voter.

**Future value**: Over time, correlate "When Judge diverges from _scores, does it win more or less often?" This answers whether AI genuinely adds value beyond rules.

#### 2.2.1 Algorithm

```python
import re

# Known net formats from compute_scores_from_features():
# LEAN_BULLISH_3of3, LEAN_BULLISH_2of3, LEAN_BULLISH_2of2, LEAN_BULLISH_1of1
# LEAN_BEARISH_3of3, LEAN_BEARISH_2of3, LEAN_BEARISH_2of2, LEAN_BEARISH_1of1
# CONFLICTING_1of3, CONFLICTING_0of3
# INSUFFICIENT (missing data)
_NET_DIRECTION_RE = re.compile(r'LEAN_(BULLISH|BEARISH)_(\d+)of(\d+)')

@staticmethod
def _check_signal_score_divergence(
    scores_net: str,
    judge_decision: str,
) -> Optional[str]:
    """
    Flag when Judge decision diverges from _scores['net'] consensus.
    Informational only — no penalty. Logged for correlation analysis.
    Returns flag text or None.
    """
    # Only check directional decisions
    if judge_decision not in ('LONG', 'SHORT'):
        return None

    m = _NET_DIRECTION_RE.match(scores_net)
    if not m:
        # CONFLICTING, INSUFFICIENT, or unknown format → no divergence to flag
        return None

    net_direction = m.group(1)  # BULLISH or BEARISH
    # Check for opposition
    if net_direction == 'BULLISH' and judge_decision == 'SHORT':
        return f"net={scores_net} decision={judge_decision}"
    if net_direction == 'BEARISH' and judge_decision == 'LONG':
        return f"net={scores_net} decision={judge_decision}"

    return None  # Aligned
```

| `_scores['net']` | Judge decision | Output |
|---|---|---|
| `LEAN_BULLISH_3of3` + SHORT | Divergence | `"net=LEAN_BULLISH_3of3 decision=SHORT"` |
| `LEAN_BEARISH_2of3` + LONG | Divergence | `"net=LEAN_BEARISH_2of3 decision=LONG"` |
| `LEAN_BULLISH_2of2` + LONG | Aligned | `None` |
| `CONFLICTING_1of3` + LONG | Exempt | `None` |
| `INSUFFICIENT` + SHORT | Exempt | `None` |
| Any + HOLD | Exempt (caller guard) | Not called |

#### 2.2.2 Edge Cases

| Edge Case | Behavior | Rationale |
|---|---|---|
| `scores_net = ''` or `None` | `None` (no match) | Graceful degradation |
| `scores_net = 'LEAN_BULLISH_1of1'` | Parsed normally | Single-dimension lean still counts |
| `scores_net` has unknown format | `None` (regex no match) | Future-proof |

### 2.3 Check 3: Confidence-Risk Coherence (PENALIZED)

**What it catches**: Judge outputs HIGH confidence when risk environment is objectively dangerous.

**Why this works**: `_scores['risk_env']` is based on FR, OI, liquidation, sentiment — objective metrics the Judge also receives. If risk_env says HIGH (score >= 6: extreme FR + liquidation cascade risk + sentiment divergence) and Judge says HIGH confidence, the Judge is ignoring objective danger signals.

**Asymmetric design**: Only penalizes **overconfidence in danger**, never **underconfidence in safety**.
- Overconfidence → oversized positions in volatile markets → capital risk
- Underconfidence → smaller/no position → opportunity cost only

#### 2.3.1 risk_env Score Reference

`risk_env` is computed in `report_formatter.py:compute_scores_from_features()`. Score range 0-10:

| Factor | Condition | Points | Max |
|---|---|---|---|
| Base | Always | +2 | 2 |
| Funding Rate | \|FR\| > 0.05% → +3; > 0.02% → +1 | +1~3 | 3 |
| Sentiment Crowding | L/S ratio > 0.7 or < 0.3 → +2; > 0.6 or < 0.4 → +1 | +1~2 | 2 |
| OI Trend | RISING → +1 | +1 | 1 |
| Liquidation Bias | LONG/SHORT_DOMINANT → +1 | +1 | 1 |
| OBI Imbalance | \|OBI\| > 0.4 → +1 | +1 | 1 |
| Liquidation Buffer | < 5% → +3; < 10% → +1 | +1~3 | 3 |
| FR Trend | RISING/FALLING → +1 | +1 | 1 |
| Premium Index | \|premium\| > 0.001 → +1 | +1 | 1 |
| Sentiment Degraded | True → +1 | +1 | 1 |
| Volatility Regime | 4H/1D EXTREME only → +1 each (HIGH → +0) | +0~2 | 2 |
| FR Consecutive Blocks | ≥ 3 → +1 | +1 | 1 |
| Top Traders Extreme | ratio > 0.65 or < 0.35 → +1 | +1 | 1 |
| **Total** | | | **capped at 10** |

**Level thresholds**: HIGH (≥6), MODERATE (4-5), LOW (<4)

**What score=6 (HIGH) means**: At least 3 independent risk factors beyond baseline. Example: extreme FR (3) + crowded sentiment (2) + base (2) = 7. This represents a genuinely dangerous environment where HIGH confidence is unjustified.

#### 2.3.2 Algorithm

```python
@staticmethod
def _check_confidence_risk_coherence(
    judge_confidence: str,
    risk_env_score: int,
    risk_env_level: str,
) -> tuple[int, str]:
    """
    Check if Judge confidence is appropriate given risk environment.
    Only penalizes overconfidence in danger (HIGH+HIGH).
    Never penalizes conservative caution (asymmetric by design).
    """
    # Only penalize HIGH confidence + HIGH risk
    if judge_confidence == 'HIGH' and risk_env_level == 'HIGH':
        flag = f"confidence={judge_confidence} risk_env={risk_env_level}({risk_env_score}) penalty=6"
        return (6, flag)
    return (0, '')
```

| Judge confidence | risk_env.level | Penalty | Rationale |
|---|---|:-:|---|
| HIGH | HIGH (score >= 6) | 6 | Overconfident in dangerous environment |
| HIGH | MODERATE (score 4-5) | 0 | Acceptable — moderate risk doesn't preclude confidence |
| MEDIUM/LOW | any | 0 | Conservative confidence is never penalized |
| any | LOW | 0 | Low risk doesn't invalidate any confidence level |

#### 2.3.3 Edge Cases

| Edge Case | Behavior | Rationale |
|---|---|---|
| `judge_confidence = ''` or `None` | 0 penalty | Not 'HIGH' |
| `risk_env_level = ''` or missing | 0 penalty | Not 'HIGH' |
| `risk_env_score = 0` but `level = 'HIGH'` | 6 penalty | Level is authoritative (but shouldn't happen normally) |
| Judge decision = HOLD + HIGH confidence | Still checked | Confidence is confidence regardless of decision |

**Why NOT penalize MEDIUM+HIGH**: MEDIUM confidence already reduces position size via `calculate_mechanical_sltp()`. The position sizing mechanism provides sufficient protection. Only HIGH confidence, which leads to maximum position size, is dangerous in HIGH risk environments.

### 2.4 Check 4: Debate Conviction Spread (INFORMATIONAL — no penalty)

**What it catches**: Bull and Bear arrive at near-identical conviction levels, suggesting shallow debate / echo chamber.

**Why this is critical to monitor**: Research confirms multi-agent debate degeneration is a well-documented problem:
- **Echo chamber effect** (EMNLP 2024): Homogeneous agents amplify shared biases; as round count increases, probability of changing dominant conclusion approaches zero
- **Majority herding** (EMNLP Findings 2025): Agents converge on early plausible-but-wrong conclusion; additional rounds entrench errors
- **Persuasiveness > accuracy** (OpenReview): Eloquent wrong arguments win over sound reasoning; LLM judges compound via verbosity/positional bias
- **Production failure rate**: Multi-agent LLM systems fail at 41-86.7% in production (MASFT 2025)

Bull conviction 0.8 + Bear conviction 0.8 (spread = 0.0) means neither agent found compelling counter-arguments — a classic echo chamber signature.

**Why informational**: Debate quality doesn't have a simple "correct" answer. The flag enables future correlation: "When conviction spread < 0.15, do trades perform worse?"

#### 2.4.1 Data Source

```python
# In AnalysisContext (analysis_context.py):
ctx.bull_output: Dict[str, Any]  # Bull structured output (Round 2)
ctx.bear_output: Dict[str, Any]  # Bear structured output (Round 2)

# Conviction field (from _validate_agent_output, schema: v27.0):
# Bull/Bear output schema: {conviction: float, evidence: [tags], risk_flags: [tags], reasoning: str}
# conviction: float 0.0-1.0, validated by _validate_agent_output()
#   - 0.0 = no conviction, 1.0 = maximum conviction
#   - Default: 0.5 if missing/invalid (from _validate_agent_output fallback)
```

#### 2.4.2 Algorithm

```python
_DEBATE_CONVERGENCE_THRESHOLD = 0.15

@staticmethod
def _check_debate_quality(
    bull_conviction: float,
    bear_conviction: float,
) -> Optional[str]:
    """
    Flag when Bull and Bear conviction spread is suspiciously low.
    Informational only — no penalty.
    Returns flag text or None.
    """
    spread = abs(bull_conviction - bear_conviction)
    if spread < _DEBATE_CONVERGENCE_THRESHOLD:
        return (f"bull={bull_conviction:.2f} bear={bear_conviction:.2f} "
                f"spread={spread:.2f}")
    return None
```

| Conviction spread | Output |
|---|---|
| < 0.15 | `"bull=0.82 bear=0.78 spread=0.04"` |
| >= 0.15 | `None` |

#### 2.4.3 Threshold Justification

**Why 0.15**: In a genuine adversarial debate about market direction, one side should find meaningfully stronger evidence than the other. A spread < 0.15 means "both sides are approximately equally convinced" — which in an adversarial setting suggests:
- Both agents converged to the same data interpretation (echo chamber)
- Both agents gave generic analysis without engaging with specific data (lazy debate)
- The data genuinely provides no clear directional edge (legitimate but rare)

**Why NOT penalize**: The third case (genuinely ambiguous data) is legitimate. We cannot distinguish it from degeneration without outcome data. Hence informational + Layer 3 correlation.

#### 2.4.4 Edge Cases

| Edge Case | Behavior | Rationale |
|---|---|---|
| `bull_conviction = 0.5, bear_conviction = 0.5` | Flag (spread=0.0) | Default values = likely both outputs invalid |
| `bull_conviction = 0.0, bear_conviction = 1.0` | None (spread=1.0) | Maximum divergence = healthy debate |
| `bull_output is None` | Not called (caller guard) | Graceful skip |
| Both outputs use default 0.5 | Flag | Schema validation fallback means output was invalid |

### 2.5 Check 5: Decisive Reasons Diversity (INFORMATIONAL — no penalty)

**What it catches**: Judge's `decisive_reasons` all come from the same data category, suggesting the AI fixated on one signal type.

**Why this matters**: A robust decision should cite evidence from multiple independent dimensions (trend + order flow + derivatives, not just 3 trend tags). Single-dimension dependency makes the decision fragile.

#### 2.5.1 Category Mapping Reference

Uses `_TAG_TO_CATEGORIES` from `ai_quality_auditor.py` (76 tags → 13 categories). Key category groupings for diversity check:

| Category | Example Tags | Independent Data Source |
|---|---|---|
| `mtf_1d` | TREND_1D_BULLISH, MACD_1D_BEARISH, DI_BULLISH_CROSS, STRONG_TREND_ADX40 | 1D candles |
| `mtf_4h` | MOMENTUM_4H_BULLISH, SMA_BULLISH_CROSS_4H, RSI_BEARISH_DIV_4H | 4H candles |
| `technical_30m` | RSI_BULLISH_DIV_30M, MACD_BEARISH_CROSS, SMA_BEARISH_CROSS_30M | 30M candles |
| `order_flow` | CVD_POSITIVE, CVD_ACCUMULATION, BUY_RATIO_HIGH | Binance trades |
| `derivatives` | FR_FAVORABLE_LONG, OI_LONG_OPENING, LIQUIDATION_CASCADE_SHORT | Futures data |
| `orderbook` | OBI_BUY_PRESSURE, OBI_SHIFTING_BEARISH, SLIPPAGE_HIGH | Order book depth |
| `sentiment` | SENTIMENT_CROWDED_LONG, SENTIMENT_EXTREME | Global L/S ratio |
| `binance_derivatives` | TOP_TRADERS_LONG_BIAS, TAKER_BUY_DOMINANT | Binance top traders |
| `sr_zones` | NEAR_STRONG_SUPPORT, SR_BREAKOUT_POTENTIAL | S/R calculation |
| `extension_ratio` | EXTENSION_OVEREXTENDED, EXTENSION_EXTREME | ATR extension |
| `volatility_regime` | VOL_HIGH, VOL_EXTREME, VOL_LOW | ATR% percentile |
| `price` | DIVERGENCE_CONFIRMED, SL_TOO_TIGHT | Price analysis |
| `position_context` | LIQUIDATION_BUFFER_CRITICAL, LIQUIDATION_BUFFER_LOW | Account state |

**Note**: Some tags map to MULTIPLE categories (e.g., `DI_BULLISH_CROSS → ['mtf_1d', 'mtf_4h']`). For diversity, a tag contributes to ALL its mapped categories.

#### 2.5.2 Algorithm

```python
@staticmethod
def _check_reason_diversity(
    decisive_reasons: List[str],
) -> Optional[str]:
    """
    Flag when all decisive_reasons map to the same data category.
    Informational only — no penalty.
    """
    if len(decisive_reasons) < 2:
        return None

    # Collect all categories covered by decisive_reasons
    categories_seen: Set[str] = set()
    mapped_count = 0
    for tag in decisive_reasons:
        cats = _TAG_TO_CATEGORIES.get(tag)
        if cats:
            categories_seen.update(cats)
            mapped_count += 1

    # Need >= 2 mapped tags (unmapped tags are neutral/risk, don't contribute)
    if mapped_count < 2:
        return None

    # Single category = fixation
    if len(categories_seen) == 1:
        single_cat = next(iter(categories_seen))
        return f"{mapped_count}/{len(decisive_reasons)} tags from {single_cat}"

    return None
```

| Category coverage | Output |
|---|---|
| All mapped tags → 1 category | `"4/4 tags from technical_30m"` |
| Mapped tags → 2+ categories | `None` |
| < 2 mapped tags | `None` (insufficient sample) |
| All tags unmapped (neutral/risk) | `None` (no category to evaluate) |

#### 2.5.3 Edge Cases

| Edge Case | Behavior | Rationale |
|---|---|---|
| `[TREND_1D_BULLISH, DI_BULLISH_CROSS]` | `None` — DI maps to `['mtf_1d', 'mtf_4h']` → 2 categories | Multi-category tag prevents fixation flag |
| `[EXTENSION_OVEREXTENDED, VOL_HIGH]` | `None` — 2 categories (extension_ratio + volatility_regime) | Different risk dimensions = diverse |
| `[SMA_BULLISH_CROSS_4H, MOMENTUM_4H_BULLISH, RSI_CARDWELL_BULL]` | `"3/3 tags from mtf_4h"` — all map to mtf_4h only | Single timeframe fixation |
| Tags not in `_TAG_TO_CATEGORIES` | `mapped_count` not incremented | Unknown tags gracefully ignored |

---

## 3. QualityReport Changes

### 3.1 New Fields

```python
@dataclass
class QualityReport:
    # --- Existing fields (unchanged) ---
    timestamp: float = 0.0
    adx_1d: float = 30.0
    regime: str = 'WEAK_TREND'
    agent_results: Dict[str, AgentAuditResult] = field(default_factory=dict)
    confluence_audit: Optional[ConfluenceAuditResult] = None
    counter_trend_detected: bool = False
    counter_trend_flagged_by_entry_timing: bool = False
    citation_errors: int = 0
    value_errors: int = 0
    zone_errors: int = 0
    phantom_citations: int = 0
    narrative_misreads: int = 0
    overall_score: int = 100
    flags: List[str] = field(default_factory=list)

    # --- v34.0: Logic-level coherence checks (NEW) ---
    reason_signal_conflict: int = 0     # penalty value (0/8/12)
    confidence_risk_conflict: int = 0   # penalty value (0/6)
    # Informational checks stored only in flags[] (no dedicated fields needed)
```

### 3.2 to_summary() Changes

```python
def to_summary(self) -> str:
    parts = [f"score={self.overall_score}"]
    # ... existing parts ...
    # v34.0
    if self.reason_signal_conflict > 0:
        parts.append(f"reason_sig={self.reason_signal_conflict}")
    if self.confidence_risk_conflict > 0:
        parts.append(f"conf_risk={self.confidence_risk_conflict}")
    return ' '.join(parts)
```

### 3.3 to_dict() Changes

```python
def to_dict(self) -> dict:
    d = {
        # ... existing fields ...
    }
    # v34.0
    d['reason_signal_conflict'] = self.reason_signal_conflict
    d['confidence_risk_conflict'] = self.confidence_risk_conflict
    # Informational flags are already in d['flags'] list
    return d
```

### 3.4 Flag Format Reference (All 5 Checks)

All checks produce named flags in `report.flags[]`. Flag prefixes enable programmatic retrieval:

| Flag Prefix | Type | Example |
|---|---|---|
| `REASON_SIGNAL_CONFLICT:` | Penalized | `decision=LONG conflict_ratio=0.67 (2 opposing / 3 directional) penalty=8` |
| `SIGNAL_SCORE_DIVERGENCE:` | Informational | `net=LEAN_BEARISH_3of3 decision=LONG` |
| `CONFIDENCE_RISK_CONFLICT:` | Penalized | `confidence=HIGH risk_env=HIGH(7) penalty=6` |
| `DEBATE_CONVERGENCE:` | Informational | `bull=0.82 bear=0.78 spread=0.04` |
| `SINGLE_DIMENSION_DECISION:` | Informational | `4/4 tags from technical_30m` |

### 3.5 Backward Compatibility

- **Additive only**: New fields have default values (0 for ints). Older consumers calling `to_dict()` will see new keys but won't break — unknown keys are ignored.
- **No removal**: All existing 13 fields preserved.
- **Score monotonic**: New penalties only decrease scores. A cycle that was 85 before v34.0 can be 85, 79, or 73 after, never higher.
- **Heartbeat**: `to_summary()` additions appear at the end of the existing summary string.

---

## 4. Scoring Integration

### 4.1 _calculate_score() Changes

```python
def _calculate_score(self, report: QualityReport) -> int:
    penalty = 0

    # === Existing penalties (unchanged) ===

    # Per-agent: missing categories (3-12 pts each)
    for role, result in report.agent_results.items():
        for cat in result.missing_categories:
            penalty += _CATEGORY_PENALTY[cat]
        if 'EMPTY_OUTPUT' in result.flags:
            penalty += 10
        for violation in result.mtf_violations:
            penalty += 8 ~ 15  # severity-aware
        penalty += len(result.skip_signal_violations) * 3

    # Confluence audit
    if report.confluence_audit:
        # alignment_mismatch * 10, confidence_mismatch * 10, missing layers * 15

    # Citation/value/zone (v33.1: no cap)
    penalty += report.citation_errors * 8
    penalty += report.value_errors * 5
    penalty += report.zone_errors * 5
    penalty += report.phantom_citations * 8
    penalty += report.narrative_misreads * 4

    # Counter-trend
    if report.counter_trend_detected and not report.counter_trend_flagged_by_entry_timing:
        penalty += 15

    # === v34.0: Logic-level coherence penalties (NEW) ===
    penalty += report.reason_signal_conflict      # 0 / 8 / 12
    penalty += report.confidence_risk_conflict     # 0 / 6
    # signal_score_divergence → informational only, NO penalty
    # debate_convergence → informational only, NO penalty
    # single_dimension_decision → informational only, NO penalty

    return max(0, 100 - penalty)
```

### 4.2 Penalty Budget Analysis

| Category | Existing Max | v34.0 New Max | Combined Max |
|---|---|---|---|
| Missing data categories | ~60 | 0 | ~60 |
| MTF violations | ~45 | 0 | ~45 |
| SKIP signal violations | ~15 | 0 | ~15 |
| Confluence audit | ~35 | 0 | ~35 |
| Citation/value/zone errors | Uncapped | 0 | Uncapped |
| Counter-trend | 15 | 0 | 15 |
| **Reason-signal conflict** | 0 | **12** | 12 |
| **Confidence-risk conflict** | 0 | **6** | 6 |
| **v34.0 total new max** | | **18** | |

**Impact assessment**: In a "normal" cycle (score ~75-90), a reason_signal_conflict=12 would drop score to ~63-78. This is a meaningful signal but not a score-destroying event. The 18-point maximum is comparable to one counter-trend miss (15) — proportional to severity.

### 4.3 No Deduplication Needed

| v34.0 Check | Data Source | Existing Check | Overlap? |
|---|---|---|---|
| reason_signal_conflict | `judge.decisive_reasons` tags | None (tags never checked for direction) | ❌ No overlap |
| confidence_risk_conflict | `judge.confidence` + `_scores.risk_env` | None (confidence never cross-checked) | ❌ No overlap |
| Both above | vs counter_trend penalty | Counter-trend uses 1D DI direction, not tags/confidence | ❌ Different data |

---

## 5. Audit Flow Integration

### 5.1 Data Flow: AnalysisContext → audit()

```
multi_agent_analyzer.py:analyze()
  │
  ├─ Phase 1: Bull/Bear debate
  │   ctx.bull_output = {conviction: 0.85, evidence: [...], risk_flags: [...], reasoning: "..."}
  │   ctx.bear_output = {conviction: 0.72, evidence: [...], risk_flags: [...], reasoning: "..."}
  │
  ├─ Phase 2: Judge decision
  │   ctx.judge_output = {signal: "LONG", confidence: "HIGH", decisive_reasons: [...], reasoning: "..."}
  │
  ├─ Precomputed scores
  │   ctx.scores = {
  │       trend: {score: ..., level: ...},
  │       momentum: {score: ..., level: ...},
  │       order_flow: {score: ..., level: ...},
  │       vol_ext_risk: {score: ..., level: ...},
  │       risk_env: {score: 7, level: "HIGH"},     ← Check 3 uses this
  │       net: "LEAN_BULLISH_3of3"                  ← Check 2 uses this
  │   }
  │
  └─ AIQualityAuditor.audit(ctx)
      │
      ├─ Step 1-3d: Existing citation-level checks (unchanged)
      │
      ├─ Step 3e: Check 1 — Reason-Signal Alignment
      │   Input: ctx.judge_output['decision'], ctx.judge_output['decisive_reasons']
      │
      ├─ Step 3f: Check 2 — Signal-Score Divergence
      │   Input: ctx.scores['net'], ctx.judge_output['decision']
      │
      ├─ Step 3g: Check 3 — Confidence-Risk Coherence
      │   Input: ctx.judge_output['confidence'], ctx.scores['risk_env']
      │
      ├─ Step 3h: Check 4 — Debate Conviction Spread
      │   Input: ctx.bull_output['conviction'], ctx.bear_output['conviction']
      │
      ├─ Step 3i: Check 5 — Reason Diversity
      │   Input: ctx.judge_output['decisive_reasons']
      │
      ├─ Step 4: Counter-trend check (existing, unchanged)
      │
      └─ Step 5: _calculate_score(report) → overall_score
```

### 5.2 Integration Point in audit()

In `audit()`, after Step 3d (contradictory omission), before Step 4 (counter-trend):

```python
# ── v34.0: Logic-level coherence checks ──

# 3e. Reason-Signal Alignment (decisive_reasons vs decision)
if judge_decision and judge_decision.get('decision', '') in ('LONG', 'SHORT'):
    _rsa_penalty, _rsa_flag = self._check_reason_signal_alignment(
        judge_decision.get('decision', ''),
        judge_decision.get('decisive_reasons', []))
    if _rsa_penalty > 0:
        report.reason_signal_conflict = _rsa_penalty
        report.flags.append(f'REASON_SIGNAL_CONFLICT: {_rsa_flag}')

# 3f. Signal-Score Divergence (informational, no penalty)
if judge_decision and _scores and judge_decision.get('decision', '') in ('LONG', 'SHORT'):
    _ssd_flag = self._check_signal_score_divergence(
        _scores.get('net', ''), judge_decision.get('decision', ''))
    if _ssd_flag:
        report.flags.append(f'SIGNAL_SCORE_DIVERGENCE: {_ssd_flag}')

# 3g. Confidence-Risk Coherence
if judge_decision and _scores:
    _risk_env = _scores.get('risk_env', {})
    _crc_penalty, _crc_flag = self._check_confidence_risk_coherence(
        judge_decision.get('confidence', ''),
        _risk_env.get('score', 0),
        _risk_env.get('level', 'LOW'))
    if _crc_penalty > 0:
        report.confidence_risk_conflict = _crc_penalty
        report.flags.append(f'CONFIDENCE_RISK_CONFLICT: {_crc_flag}')

# 3h. Debate Conviction Spread (informational)
# Note: audit() receives `ctx: AnalysisContext`, not `analysis_context`
if (ctx.bull_output is not None
        and ctx.bear_output is not None):
    _bull_conv = ctx.bull_output.get('conviction', 0.5)
    _bear_conv = ctx.bear_output.get('conviction', 0.5)
    _dq_flag = self._check_debate_quality(_bull_conv, _bear_conv)
    if _dq_flag:
        report.flags.append(f'DEBATE_CONVERGENCE: {_dq_flag}')

# 3i. Decisive Reasons Diversity (informational)
if judge_decision and judge_decision.get('decisive_reasons'):
    _rd_flag = self._check_reason_diversity(
        judge_decision.get('decisive_reasons', []))
    if _rd_flag:
        report.flags.append(f'SINGLE_DIMENSION_DECISION: {_rd_flag}')
```

### 5.3 Variable Mapping: audit() Locals → Check Parameters

The `audit()` method uses local variables extracted from `AnalysisContext`. Here's how they map:

| Check Parameter | audit() Local Variable | Extraction |
|---|---|---|
| `decision` | `judge_decision.get('decision', '')` | From `ctx.judge_output` |
| `decisive_reasons` | `judge_decision.get('decisive_reasons', [])` | From `ctx.judge_output` |
| `scores_net` | `_scores.get('net', '')` | From `ctx.scores` |
| `judge_confidence` | `judge_decision.get('confidence', '')` | From `ctx.judge_output` |
| `risk_env_score` | `_risk_env.get('score', 0)` | From `ctx.scores['risk_env']` |
| `risk_env_level` | `_risk_env.get('level', 'LOW')` | From `ctx.scores['risk_env']` |
| `bull_conviction` | `ctx.bull_output.get('conviction', 0.5)` | Directly from `ctx: AnalysisContext` |
| `bear_conviction` | `ctx.bear_output.get('conviction', 0.5)` | Directly from `ctx: AnalysisContext` |

**Note**: `judge_decision` and `_scores` are already extracted as local variables in the existing `audit()` method (`judge_decision = ctx.judge_output` at line 535, `_scores = ctx.scores` at line 812). No new extraction needed for Checks 1-3 and 5. Check 4 accesses `ctx.bull_output`/`ctx.bear_output` directly from the `ctx` parameter.

### 5.4 Required Import Addition

```python
from agents.prompt_constants import (
    _SIGNAL_ANNOTATIONS, _get_multiplier,
    BULLISH_EVIDENCE_TAGS, BEARISH_EVIDENCE_TAGS,  # v34.0
)
```

### 5.5 Null Safety Guards Summary

| Check | Guard Condition | Fallback |
|---|---|---|
| Check 1 | `judge_decision` exists + decision in (LONG, SHORT) | Skip entirely |
| Check 2 | `judge_decision` exists + `_scores` exists + decision in (LONG, SHORT) | Skip entirely |
| Check 3 | `judge_decision` exists + `_scores` exists | Skip entirely |
| Check 4 | `ctx.bull_output is not None` + `ctx.bear_output is not None` | Skip entirely |
| Check 5 | `judge_decision` exists + `decisive_reasons` non-empty | Skip entirely |

All guards use early-skip (no penalty), consistent with existing auditor behavior for missing data.

---

## 6. What This Design DOES and DOES NOT Solve

### Solves

| Problem | Check | Mechanism |
|---|---|---|
| Reasoning chain broken (LONG with bearish reasons) | Check 1 (penalized) | Tag direction vs decision direction |
| Overconfidence in dangerous markets | Check 3 (penalized) | confidence vs risk_env.level |
| Tracking whether AI beats simple rules | Check 2 (informational) | Divergence logging for correlation |
| Multi-agent debate degeneration | Check 4 (informational) | Conviction spread monitoring |
| Single-dimension decision fragility | Check 5 (informational) | Tag category diversity check |

### Does NOT Solve (and Why)

| Problem | Why Not Addressed | Future Path |
|---|---|---|
| **HOLD inflation** | 6-layer mechanism producing ~50-95% inaction cycles (see 6.1) | Per-cycle counterfactual + HOLD source classification |
| **Confidence calibration beyond HIGH** | Only catches HIGH+HIGH_RISK; MEDIUM overconfidence not detectable without outcomes | Historical win-rate-by-confidence-bucket |
| **Selective evidence** | Bull picks 3/10 supporting data points, ignores 7 opposing | Already partially covered by CONTRADICTORY_OMISSION |
| **Reasoning quality** | AI gives shallow/generic reasoning text | Would require LLM-as-judge (expensive, recursive) |
| **Memory contamination** | High-quality-score trade that lost money still gets weight 1.0 in memory | Needs decoupled quality/outcome weighting |
| **Schema default masking** | `_validate_agent_output()` silently replaces invalid values with defaults | Needs invalid-value counting, not replacement |
| **Cascading failures** | Single Phase 0 error (None propagation) cascades to all downstream agents | Needs data integrity pre-check before AI calls |

### 6.1 HOLD Inflation: Structural Analysis

HOLD inaction comes from 6 independent layers, each legitimate but cumulative:

| Layer | Source | Type | Location | Est. Impact |
|---|---|---|---|---|
| 1 | `_has_market_changed()` gate | Hard skip (no AI) | `position_manager.py:246` | ~20-35% cycles |
| 2 | Judge prompt: 0-1 aligned → HOLD | Prompt bias | `multi_agent_analyzer.py` | ~5-10% |
| 3 | `min_confidence_to_trade=MEDIUM` | Confidence gate | `order_execution.py:155` | ~10-20% |
| 4 | Entry Timing Agent REJECT | AI rejection | `multi_agent_analyzer.py:990` | ~8-15% |
| 5 | Risk controller circuit breaker | Risk logic | `ai_strategy.py:2980` | ~2-5% |
| 6 | Signal fingerprint dedup | Repeat filter | `ai_strategy.py:2964` | ~3-8% |

**Key insight**: Current metrics don't distinguish **explicit HOLD** (Judge decision) from **implicit HOLD** (gate rejection, ET REJECT, confidence filter). Layers 1/3/5/6 are invisible to the auditor.

**Why not addressed now**: Penalizing HOLD without outcome data punishes correct caution. Needs counterfactual pipeline first.

### 6.2 Coverage Map: 52 Failure Modes vs Auditor Checks

| Phase | Failure Mode | Existing Check | New v34.0 Check |
|---|---|---|---|
| P1 | Bull tag inflation (10 bullish, 0 risk_flags) | — | Check 5 (diversity) |
| P1 | Conviction inversion (Bull conviction 0.9 on weak data) | — | — |
| P1.5 | Shallow counter-argument (Round 2 = Round 1 repeat) | — | Check 4 (debate quality) |
| P2 | Judge ignores debate (cites 0 Bull/Bear tags) | — | Check 1 (reason-signal) |
| P2 | Signal reversal (LEAN_BULLISH → SHORT without justification) | — | Check 2 (divergence flag) |
| P2 | Confidence sourcing error (HIGH from 1 aligned layer) | Confluence | — |
| P2.5 | Contradictory regime assessment | Coverage | — |
| P3 | Wrong position state (size_pct based on stale data) | — | — |
| P4 | High-quality bad trade memory contamination | — | — (needs outcome pipeline) |
| P5 | Silent schema default substitution | — | — (needs validation reform) |
| P6 | Cross-TF false positive | v30.5 fixes | — |

**Net coverage improvement**: From ~13% (7/52) to ~19% (10/52) of all failure modes, plus 3 informational flags enabling future correlation analysis.

### 6.3 Honest Assessment

This design adds **2 penalized checks + 3 informational flags** to the existing 6-dimension citation audit. It catches:
- Internal reasoning incoherence (Check 1) — clear, unambiguous errors
- Overconfidence in danger (Check 3) — asymmetric, conservative
- Data-decision divergence (Check 2) — logged for future correlation
- Debate degeneration (Check 4) — logged for future correlation
- Decision fragility (Check 5) — logged for future correlation

The correct framing: **"adding logic sanity checks to the citation audit system."** A full logic audit would require:
1. Outcome-based feedback pipeline (trading_memory has data, no analysis)
2. HOLD counterfactual tracking (not implemented)
3. Per-confidence-bucket win-rate calibration (not implemented)
4. LLM-as-judge meta-evaluation (expensive, recursive)

Items 1-3 are achievable with engineering effort. Item 4 is a research problem.

---

## 7. Three-Layer Architecture: Feasibility Assessment

### 7.1 Architecture Overview

```
Layer 1: Input Validation (AI 收到的数据是否正确?)
  → Prevent None propagation and silent data masking

Layer 2: Process Audit (AI 的推理过程是否一致?)
  → Citation accuracy + logic coherence checks (v34.0 focus)

Layer 3: Outcome Feedback (AI 的决策结果如何?)
  → Quality score → trade outcome correlation
```

### 7.2 Layer 1: Input Validation — Detailed Implementation Spec

**NOT in v34.0 scope — separate PR. This section provides full implementation spec for future execution.**

#### 7.2.1 Problem Statement

6/13 external data sources return None on API failure. `extract_features()` uses `_sf()` (safe-float) to silently convert None→0.0. This means:
- CVD=0.0 could mean "balanced market" OR "API failed"
- FR=0.0% could mean "neutral funding" OR "no derivatives data"
- equity=0 could mean "empty account" OR "Binance API down"

Downstream `compute_scores_from_features()` and all 5 AI agents receive these 0.0 values as if they were real market data.

#### 7.2.2 None Propagation Audit (Full 13 Sources)

| # | Data Source | `fetch_external_data()` Behavior on Failure | `extract_features()` via `_sf()` | Risk Level | Fix Priority |
|---|---|---|---|---|---|
| 1 | technical_data (30M) | **Never None** (local indicators) | N/A | None | N/A |
| 2 | sentiment_data | **Fallback neutral dict** + `degraded=True` flag | ✅ Correct | Low | Already handled |
| 3 | price_data | **Never None** (ticker always available) | N/A | None | N/A |
| 4 | order_flow_report | **None** on failure | CVD=0, taker_ratio=0.5 | Medium | P2 |
| 5 | derivatives_report (Coinalyze) | **None** on failure | FR=0%, OI_change=0% | **High** | P1 |
| 6 | binance_derivatives | **None** on failure | top_traders_ratio=0.5 | Medium | P2 |
| 7 | orderbook_report | **None** on failure | OBI=0, slippage=0 | Medium | P3 |
| 8 | mtf_decision_layer (4H) | **None** if insufficient bars | All 4H indicators=0 | **High** | P1 |
| 9 | mtf_trend_layer (1D) | **None** if insufficient bars | All 1D indicators=0 | **High** | P1 |
| 10 | current_position | **Empty dict** on no position | position_side=None | Low | N/A |
| 11 | account_context | **None** on failure | equity=0, leverage=1 | **High** | P1 |
| 12 | historical_context | **None** on failure | N/A (not in features) | Low | N/A |
| 13 | sr_zones_data | **None** on failure | nearest_support=0, nearest_resistance=0 | Medium | P3 |

#### 7.2.3 Implementation: Phase 1 — Availability Flags

**File**: `agents/report_formatter.py` — in `extract_features()`

```python
def extract_features(
    technical_data, sentiment_data, price_data,
    order_flow_data, derivatives_data, binance_derivatives_data,
    orderbook_data, mtf_4h, mtf_1d, current_position, account_context,
    historical_context, sr_zones_data
) -> Dict[str, Any]:
    features = {}

    # ── Phase 1 (v34.1): Data availability flags ──
    features['_avail_order_flow'] = order_flow_data is not None
    features['_avail_derivatives'] = derivatives_data is not None
    features['_avail_binance_derivatives'] = binance_derivatives_data is not None
    features['_avail_orderbook'] = orderbook_data is not None
    features['_avail_mtf_4h'] = mtf_4h is not None
    features['_avail_mtf_1d'] = mtf_1d is not None
    features['_avail_account'] = account_context is not None
    features['_avail_sr_zones'] = sr_zones_data is not None
    # sentiment already has 'sentiment_degraded' flag
    # technical_data, price_data, current_position: always available

    # ... rest of existing feature extraction (unchanged) ...
```

**Naming convention**: Prefix `_avail_` to distinguish from data features. These are metadata about data quality, not market data.

#### 7.2.4 Implementation: Phase 2 — Score Exclusion

**File**: `agents/report_formatter.py` — in `compute_scores_from_features()`

```python
def compute_scores_from_features(features: Dict) -> Dict:
    f = features
    sg = lambda key, default=0.0: _sf(f.get(key), default)

    # ── order_flow score ──
    if not f.get('_avail_order_flow', True):
        order_flow_score = 0  # Neutral, excluded from net calculation
        order_flow_available = False
    else:
        # ... existing order_flow scoring (unchanged) ...
        order_flow_available = True

    # ── risk_env score ──
    # FR-related factors: skip if derivatives unavailable
    if f.get('_avail_derivatives', True):
        # ... existing FR scoring ...
    else:
        pass  # Don't add FR factors — they're 0.0 artifacts

    # ── net consensus ──
    # Only count dimensions with available data
    available_dimensions = []
    if f.get('_avail_mtf_1d', True):
        available_dimensions.append(trend_score)
    if f.get('_avail_mtf_4h', True):
        available_dimensions.append(momentum_score)
    if f.get('_avail_order_flow', True):
        available_dimensions.append(order_flow_score)
    # vol_ext_risk always available (based on technical_data)
    # risk_env always computable (base score = 2)

    # Compute net from available dimensions only
    # If < 2 dimensions available → INSUFFICIENT
```

#### 7.2.5 Implementation: Phase 3 — Auditor Integration

**File**: `agents/ai_quality_auditor.py`

```python
# In audit(), before existing Step 1:
# Step 0 (v34.1): Data availability pre-check
_avail_flags = {k: v for k, v in features.items() if k.startswith('_avail_')}
unavailable = [k for k, v in _avail_flags.items() if not v]
if unavailable:
    report.flags.append(f'DATA_UNAVAILABLE: {", ".join(unavailable)}')
    # Adjust expected coverage: don't penalize missing categories
    # if their data source was unavailable
```

**Effort**: ~50 lines Phase 1 + ~40 lines Phase 2 + ~20 lines Phase 3 = ~110 lines total
**Risk**: Low (additive flags, score exclusion is behavioral change but improves accuracy)
**Priority**: High (prevents garbage-in → all-dimensions-polluted)

### 7.3 Layer 2: Process Audit — Feasibility (v34.0 SCOPE)

**Confirmed data availability for all 5 checks**:

| Check | Required Data | Source on AnalysisContext | Available |
|---|---|---|---|
| Check 1 (Reason-Signal) | `decision`, `decisive_reasons` | `ctx.judge_output` | ✅ |
| Check 2 (Signal-Score) | `_scores['net']`, `decision` | `ctx.scores`, `ctx.judge_output` | ✅ |
| Check 3 (Confidence-Risk) | `confidence`, `risk_env` | `ctx.judge_output`, `ctx.scores` | ✅ |
| Check 4 (Debate Quality) | `bull_conviction`, `bear_conviction` | `ctx.bull_output`, `ctx.bear_output` | ✅ confirmed float 0.0-1.0 |
| Check 5 (Reason Diversity) | `decisive_reasons` + category mapping | `ctx.judge_output`, `_TAG_TO_CATEGORIES` | ✅ |

**Effort**: ~200 lines in `ai_quality_auditor.py` + ~150 lines tests
**Risk**: Low (additive checks, existing score calculation unchanged)

### 7.4 Layer 3: Outcome Feedback — Detailed Implementation Spec

**HIGHEST PRIORITY. Should be implemented BEFORE Layer 2 (v34.0 checks).**

#### 7.4.1 Problem Statement

The auditor produces a quality score (0-100) every analysis cycle. This score is stored in `trading_memory.json` alongside trade outcomes. But **no code anywhere** answers: "Does a higher quality score predict better trade outcomes?"

Without this answer, we cannot know:
- Whether adding more checks (v34.0) improves prediction accuracy
- Whether current penalty weights are calibrated correctly
- Whether the auditor is measuring signal or noise

#### 7.4.2 Data Source: `trading_memory.json`

```python
# File: data/trading_memory.json
# Format: List[Dict], max 500 entries (FIFO cap)
# Each entry created by: memory_manager.py:record_outcome()

# Per-trade entry fields relevant to correlation:
{
    "timestamp": "2025-11-15T08:30:00",        # ISO string
    "decision": "BUY",                          # BUY/SELL/HOLD at entry
    "pnl": -1.2,                                # Realized P&L %

    # Evaluation (computed by trading_logic.py:evaluate_trade())
    # Coverage: ~85% of trades (15% have evaluation_failed)
    "evaluation": {
        "grade": "D",                           # A+/A/B/C/D/D-/F
        "direction_correct": false,             # Win/loss binary
        "actual_rr": -0.8,                      # Realized R/R ratio
        "planned_rr": 2.1,                      # Planned R/R at entry
        "execution_quality": 0.38,              # actual_rr / planned_rr
        "exit_type": "STOP_LOSS",               # TAKE_PROFIT/STOP_LOSS/MANUAL/REVERSAL
        "confidence": "HIGH",                   # Entry confidence level
        "is_counter_trend": true,               # Against dominant trend
        "risk_appetite": "NORMAL",              # AGGRESSIVE/NORMAL/CONSERVATIVE
        "trend_direction": "DOWNTREND",         # UPTREND/DOWNTREND/SIDEWAYS
        "adx": 35.2,                            # ADX at entry
        "mae_pct": 2.1,                         # Max Adverse Excursion %
        "mfe_pct": 0.3,                         # Max Favorable Excursion %
        "hold_duration_min": 480,               # Minutes held
        "pyramid_layers_used": 1,               # Layer count
        "sl_atr_multiplier": 1.5,               # SL width in ATR units
    },

    # AI Quality Score (computed by ai_quality_auditor.py:audit())
    # Coverage: ~30% of trades (newer field, added v29+)
    "ai_quality_score": 85,                     # 0-100

    # Feature snapshot (124 typed features)
    # Coverage: ~50% of trades (added v27.0+)
    "conditions_v2": {
        "rsi_30m": 42.5,
        "macd_bullish": false,
        "adx_1d": 35.2,
        "funding_rate_pct": -0.012,
        "cvd_trend_30m": "POSITIVE",
        // ... 120 more features ...
    },

    # Agent decision metadata
    "entry_timing_verdict": "ENTER",            # ENTER/REJECT (v23.0+, ~50%)
    "entry_timing_quality": "GOOD",             # OPTIMAL/GOOD/FAIR/POOR (v23.0+)
    "winning_side": "BULL",                     # Debate winner (v12.0+, ~70%)
    "close_reason": "STOP_LOSS",                # How closed (v24.2+, ~50%)

    # Reflection
    "lesson": "Counter-trend trade in strong downtrend...",
    "reflection": "LLM-generated deep reflection..."         # v12.0+, ~60%
}
```

#### 7.4.3 Implementation: Phase 1 — Minimal Viable Correlation

**File**: `scripts/analyze_quality_correlation.py`

**Dependencies**: Only Python stdlib + json. No numpy/pandas/scipy required for Phase 1.

```python
#!/usr/bin/env python3
"""
Layer 3: Outcome Feedback Analysis — Quality Score vs Trade Outcome Correlation.

Read-only analysis of data/trading_memory.json.
Answers: "Does the auditor quality score predict trade outcomes?"

Usage:
    python3 scripts/analyze_quality_correlation.py
    python3 scripts/analyze_quality_correlation.py --json    # Machine-readable output
    python3 scripts/analyze_quality_correlation.py --verbose  # Per-trade details
"""
import json
import math
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

DATA_FILE = Path(__file__).parent.parent / 'data' / 'trading_memory.json'


def load_trades() -> List[Dict]:
    """Load and filter trades with valid evaluation data."""
    if not DATA_FILE.exists():
        print(f"❌ {DATA_FILE} not found")
        sys.exit(1)
    with open(DATA_FILE) as f:
        memories = json.load(f)
    # Filter: must have evaluation with direction_correct
    return [m for m in memories
            if m.get('evaluation') and 'direction_correct' in m['evaluation']]


def pearson_r(xs: List[float], ys: List[float]) -> Optional[float]:
    """Pearson correlation coefficient. Returns None if < 5 pairs or zero variance."""
    n = len(xs)
    if n < 5:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / math.sqrt(var_x * var_y)


# ── Analysis 1: Quality Score Quintiles → Win Rate ──
def analyze_quality_quintiles(trades: List[Dict]) -> Dict:
    """Stratify trades by quality score quintile, compute win rate per bucket."""
    scored = [(m['ai_quality_score'], m['evaluation']['direction_correct'])
              for m in trades if m.get('ai_quality_score') is not None]
    if len(scored) < 10:
        return {'error': f'Insufficient data: {len(scored)} trades with quality score (need 10+)'}

    quintiles = {'Q1 (0-20)': [], 'Q2 (20-40)': [], 'Q3 (40-60)': [],
                 'Q4 (60-80)': [], 'Q5 (80-100)': []}
    for score, won in scored:
        if score < 20: quintiles['Q1 (0-20)'].append(won)
        elif score < 40: quintiles['Q2 (20-40)'].append(won)
        elif score < 60: quintiles['Q3 (40-60)'].append(won)
        elif score < 80: quintiles['Q4 (60-80)'].append(won)
        else: quintiles['Q5 (80-100)'].append(won)

    result = {}
    for q, outcomes in quintiles.items():
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o)
        result[q] = {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3) if n > 0 else None}

    # Correlation
    scores = [s for s, _ in scored]
    outcomes = [1.0 if w else 0.0 for _, w in scored]
    result['pearson_r'] = pearson_r(scores, outcomes)
    result['total_trades'] = len(scored)
    return result


# ── Analysis 2: Confidence Level → Win Rate ──
def analyze_confidence_calibration(trades: List[Dict]) -> Dict:
    """Compute actual win rate per confidence level."""
    buckets = defaultdict(list)
    for m in trades:
        conf = m['evaluation'].get('confidence', 'UNKNOWN')
        won = m['evaluation']['direction_correct']
        buckets[conf].append(won)

    result = {}
    for conf in ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN']:
        outcomes = buckets.get(conf, [])
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o)
        result[conf] = {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3) if n > 0 else None}
    return result


# ── Analysis 3: Entry Timing Verdict → Win Rate ──
def analyze_entry_timing(trades: List[Dict]) -> Dict:
    """Compare outcomes for ENTER vs REJECT verdicts."""
    buckets = defaultdict(list)
    for m in trades:
        verdict = m.get('entry_timing_verdict')
        if verdict:
            won = m['evaluation']['direction_correct']
            buckets[verdict].append(won)

    result = {}
    for v in ['ENTER', 'REJECT']:
        outcomes = buckets.get(v, [])
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o)
        result[v] = {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3) if n > 0 else None}
    result['total_with_verdict'] = sum(len(v) for v in buckets.values())
    return result


# ── Analysis 4: Counter-Trend Performance ──
def analyze_counter_trend(trades: List[Dict]) -> Dict:
    """Compare trend-following vs counter-trend trade outcomes."""
    trend_following = []
    counter_trend = []
    for m in trades:
        is_ct = m['evaluation'].get('is_counter_trend', False)
        won = m['evaluation']['direction_correct']
        rr = m['evaluation'].get('actual_rr', 0)
        if is_ct:
            counter_trend.append((won, rr))
        else:
            trend_following.append((won, rr))

    def stats(trades_list):
        n = len(trades_list)
        if n == 0:
            return {'n': 0, 'win_rate': None, 'avg_rr': None}
        wins = sum(1 for w, _ in trades_list if w)
        avg_rr = sum(rr for _, rr in trades_list) / n
        return {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3), 'avg_rr': round(avg_rr, 3)}

    return {'trend_following': stats(trend_following), 'counter_trend': stats(counter_trend)}


# ── Analysis 5: Grade Distribution ──
def analyze_grade_distribution(trades: List[Dict]) -> Dict:
    """Count trades per evaluation grade."""
    grades = defaultdict(int)
    for m in trades:
        grade = m['evaluation'].get('grade', 'UNKNOWN')
        grades[grade] += 1
    return dict(sorted(grades.items()))


# ── Analysis 6: Debate Winner → Outcome ──
def analyze_debate_winner(trades: List[Dict]) -> Dict:
    """Does the debate winner predict outcome?"""
    buckets = defaultdict(list)
    for m in trades:
        winner = m.get('winning_side')
        decision = m.get('decision', '')
        if winner and decision:
            won = m['evaluation']['direction_correct']
            # Check alignment: winner=BULL + decision=BUY → aligned
            aligned = (winner == 'BULL' and decision == 'BUY') or \
                      (winner == 'BEAR' and decision == 'SELL')
            buckets['aligned' if aligned else 'overruled'].append(won)

    result = {}
    for key in ['aligned', 'overruled']:
        outcomes = buckets.get(key, [])
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o)
        result[key] = {'n': n, 'wins': wins, 'win_rate': round(wins / n, 3) if n > 0 else None}
    return result


def main():
    json_mode = '--json' in sys.argv
    trades = load_trades()

    report = {
        'total_trades_with_evaluation': len(trades),
        'quality_quintiles': analyze_quality_quintiles(trades),
        'confidence_calibration': analyze_confidence_calibration(trades),
        'entry_timing': analyze_entry_timing(trades),
        'counter_trend': analyze_counter_trend(trades),
        'grade_distribution': analyze_grade_distribution(trades),
        'debate_winner': analyze_debate_winner(trades),
    }

    if json_mode:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_human_readable(report)


def _print_human_readable(report: Dict):
    print("=" * 60)
    print("Layer 3: Outcome Feedback Analysis")
    print(f"Total trades with evaluation: {report['total_trades_with_evaluation']}")
    print("=" * 60)

    # Quality quintiles
    print("\n── 1. Quality Score → Win Rate ──")
    qq = report['quality_quintiles']
    if 'error' in qq:
        print(f"  ⚠️  {qq['error']}")
    else:
        for q in ['Q1 (0-20)', 'Q2 (20-40)', 'Q3 (40-60)', 'Q4 (60-80)', 'Q5 (80-100)']:
            d = qq[q]
            wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
            print(f"  {q}: {d['wins']}/{d['n']} wins ({wr})")
        r = qq.get('pearson_r')
        print(f"  Pearson r(quality_score, direction_correct) = {r:.3f}" if r else "  Pearson r = N/A (insufficient data)")
        if r and r > 0.15:
            print("  ✅ Positive correlation — quality score has predictive value")
        elif r and r < -0.05:
            print("  ❌ Negative correlation — quality score may be miscalibrated")
        elif r:
            print("  ⚠️  Weak/no correlation — quality score may not predict outcomes")

    # Confidence calibration
    print("\n── 2. Confidence Level → Win Rate ──")
    cc = report['confidence_calibration']
    for level in ['HIGH', 'MEDIUM', 'LOW']:
        d = cc.get(level, {'n': 0, 'win_rate': None})
        wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
        print(f"  {level}: {d.get('wins', 0)}/{d['n']} wins ({wr})")

    # Entry timing
    print("\n── 3. Entry Timing Verdict → Win Rate ──")
    et = report['entry_timing']
    for v in ['ENTER', 'REJECT']:
        d = et.get(v, {'n': 0, 'win_rate': None})
        wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
        print(f"  {v}: {d.get('wins', 0)}/{d['n']} wins ({wr})")

    # Counter-trend
    print("\n── 4. Counter-Trend Performance ──")
    ct = report['counter_trend']
    for key in ['trend_following', 'counter_trend']:
        d = ct[key]
        wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
        rr = f"{d['avg_rr']:.2f}" if d['avg_rr'] is not None else "N/A"
        label = "Trend-following" if key == 'trend_following' else "Counter-trend"
        print(f"  {label}: {d.get('wins', 0)}/{d['n']} wins ({wr}), avg R/R={rr}")

    # Grade distribution
    print("\n── 5. Grade Distribution ──")
    for grade, count in report['grade_distribution'].items():
        print(f"  {grade}: {count}")

    # Debate winner
    print("\n── 6. Debate Winner → Outcome ──")
    dw = report['debate_winner']
    for key in ['aligned', 'overruled']:
        d = dw.get(key, {'n': 0, 'win_rate': None})
        wr = f"{d['win_rate']:.1%}" if d['win_rate'] is not None else "N/A"
        print(f"  Judge {key} with debate winner: {d.get('wins', 0)}/{d['n']} wins ({wr})")

    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()
```

**Effort**: ~200 lines, zero production risk (read-only script)
**Output example**:
```
============================================================
Layer 3: Outcome Feedback Analysis
Total trades with evaluation: 423
============================================================

── 1. Quality Score → Win Rate ──
  Q1 (0-20): 2/8 wins (25.0%)
  Q2 (20-40): 5/15 wins (33.3%)
  Q3 (40-60): 12/32 wins (37.5%)
  Q4 (60-80): 28/55 wins (50.9%)
  Q5 (80-100): 18/30 wins (60.0%)
  Pearson r(quality_score, direction_correct) = 0.23
  ✅ Positive correlation — quality score has predictive value

── 2. Confidence Level → Win Rate ──
  HIGH: 45/85 wins (52.9%)
  MEDIUM: 80/200 wins (40.0%)
  LOW: 12/50 wins (24.0%)
```

#### 7.4.4 Implementation: Phase 2 — Feature Importance (Future)

```python
# Requires: scipy (Spearman ρ) — already in requirements.txt via empyrical-reloaded
# Add to analyze_quality_correlation.py

def analyze_feature_importance(trades: List[Dict]) -> Dict:
    """Rank 124 features by predictive power (Spearman ρ vs direction_correct)."""
    from scipy.stats import spearmanr

    feature_trades = [(m['conditions_v2'], m['evaluation']['direction_correct'])
                      for m in trades if m.get('conditions_v2')]
    if len(feature_trades) < 30:
        return {'error': f'Insufficient: {len(feature_trades)} trades (need 30+)'}

    # Collect all numeric features
    all_features = set()
    for conds, _ in feature_trades:
        all_features.update(k for k, v in conds.items()
                            if isinstance(v, (int, float)) and not k.startswith('_'))

    # Compute Spearman ρ per feature
    correlations = {}
    for feat in all_features:
        values = []
        outcomes = []
        for conds, won in feature_trades:
            v = conds.get(feat)
            if v is not None and isinstance(v, (int, float)):
                values.append(float(v))
                outcomes.append(1.0 if won else 0.0)
        if len(values) >= 20:
            rho, pvalue = spearmanr(values, outcomes)
            correlations[feat] = {'rho': round(rho, 4), 'p': round(pvalue, 4), 'n': len(values)}

    # Sort by |ρ|, return top 20
    ranked = sorted(correlations.items(), key=lambda x: abs(x[1]['rho']), reverse=True)
    return {
        'total_features_analyzed': len(correlations),
        'top_20': {k: v for k, v in ranked[:20]},
        'bottom_5': {k: v for k, v in ranked[-5:]},
    }
```

**Effort**: ~100 lines additional
**Dependencies**: scipy (already available)

#### 7.4.5 Implementation: Phase 3 — Time-Series (Future)

```python
def analyze_rolling_performance(trades: List[Dict], window: int = 20) -> Dict:
    """Rolling win rate curve + streak detection."""
    # Sort by timestamp
    sorted_trades = sorted(trades, key=lambda m: m.get('timestamp', ''))
    outcomes = [m['evaluation']['direction_correct'] for m in sorted_trades]

    # Rolling win rate
    rolling = []
    for i in range(window, len(outcomes) + 1):
        window_outcomes = outcomes[i - window:i]
        wr = sum(1 for o in window_outcomes if o) / window
        rolling.append(round(wr, 3))

    # Streak detection
    max_win_streak = max_loss_streak = current_streak = 0
    last_outcome = None
    for o in outcomes:
        if o == last_outcome:
            current_streak += 1
        else:
            current_streak = 1
        last_outcome = o
        if o:
            max_win_streak = max(max_win_streak, current_streak)
        else:
            max_loss_streak = max(max_loss_streak, current_streak)

    return {
        'rolling_win_rate': rolling,
        'max_win_streak': max_win_streak,
        'max_loss_streak': max_loss_streak,
        'total_trades': len(outcomes),
    }
```

**Effort**: ~100 lines additional

#### 7.4.6 Decision Tree: What to Do Based on Results

```
Phase 1 correlation results:

IF Pearson r(quality_score, direction_correct) > 0.15:
    ✅ Quality score is predictive
    → Proceed with v34.0 Layer 2 checks (add more signal to score)
    → Layer 3 Phase 2: identify WHICH features drive correlation

IF Pearson r ∈ [-0.05, 0.15]:
    ⚠️ Weak/no correlation
    → DO NOT add v34.0 penalty checks yet
    → Investigate: which existing penalty categories have the strongest
      individual correlation? Reweight before adding new checks

IF Pearson r < -0.05:
    ❌ Negative correlation — score is anti-predictive
    → STOP: existing penalty weights are wrong
    → Investigate: are high scores given to conservative (good) analysis
      that avoids trades (survivor bias)?
    → Root cause before any new checks

IF confidence calibration shows HIGH < MEDIUM win rate:
    → AI is systematically overconfident
    → Increase Check 3 penalty or expand to MEDIUM confidence

IF Entry Timing ENTER win rate ≈ REJECT win rate:
    → ET Agent adds no value
    → Consider simplification (remove ET Agent, save API cost)
```

**Effort**: Phase 1 = ~200 lines. Phase 2 = +100 lines. Phase 3 = +100 lines.
**Risk**: Zero (read-only analysis script, no production code changes)
**Priority**: **HIGHEST** — answers "is the auditor measuring the right things?"

### 7.5 Recommended Implementation Order

```
Priority 1: Layer 3 Phase 1 (Outcome Correlation Script)
  → scripts/analyze_quality_correlation.py
  → Answers: "Does quality score predict trade outcomes?"
  → If NO: auditor scoring weights need recalibration before adding more checks
  → If YES: validates v34.0 direction, proceed with confidence
  → Effort: ~200 lines, zero risk

Priority 2: Layer 2 (v34.0 Logic Checks)
  → Check 1 (Reason-Signal) + Check 3 (Confidence-Risk) → penalized
  → Check 2/4/5 → informational (value depends on Layer 3 analysis pipeline)
  → Effort: ~350 lines code + tests

Priority 3: Layer 1 (Data Availability Flags)
  → Add _available flags to extract_features()
  → Prevent zero-masking in compute_scores_from_features()
  → Effort: ~70 lines, separate PR

Priority 4: Layer 3 Phase 2-3 (Deep Correlation)
  → Feature importance, time-series analysis
  → Effort: ~500 lines
```

### 7.6 Future Roadmap Items (Not Current Scope)

**HOLD Source Classification**: Add `hold_source` field to signal log:
```python
hold_source: str  # 'explicit_judge' | 'et_reject' | 'confidence_gate' | 'risk_breaker' | 'gate_skip' | 'dedup'
```

**HOLD Counterfactual**: Track next-N-bar price movement after HOLD decisions.

**Confidence Calibration**: Build confidence-bucket win rates from Layer 3 data.

---

## 8. Migration & Backward Compatibility

### 8.1 Score Continuity

v34.0 new penalties can ONLY decrease scores. Historical quality scores (stored in `trading_memory.json:ai_quality_score`) are NOT retroactively recalculated.

| Scenario | Before v34.0 | After v34.0 | Impact |
|---|---|---|---|
| Normal cycle, no new violations | Score 85 | Score 85 | Zero change |
| Cycle with reason-signal conflict | Score 85 | Score 73 (85-12) | Reflects real incoherence |
| Cycle with confidence-risk conflict | Score 85 | Score 79 (85-6) | Reflects real overconfidence |
| Both violations | Score 85 | Score 67 (85-12-6) | Worst case |

**Historical score interpretation**: Quality scores before v34.0 did NOT check logic coherence. A pre-v34.0 score of 90 and a post-v34.0 score of 90 are NOT equivalent — the latter is more meaningful because it survived additional checks.

**Layer 3 correlation analysis impact**: When running `analyze_quality_correlation.py`, the script should note the v34.0 cutoff date. Correlation analysis on pre-v34.0 scores may show weaker signal because the score didn't capture logic errors.

### 8.2 Field Additions

| Field | Default | Impact on Consumers |
|---|---|---|
| `QualityReport.reason_signal_conflict` | 0 | `to_dict()` adds new key — Web API/Telegram ignore unknown keys |
| `QualityReport.confidence_risk_conflict` | 0 | Same as above |
| `report.flags[]` new prefixes | N/A | Additive — existing flag parsing unaffected |

### 8.3 Import Changes

```python
# ai_quality_auditor.py — new import
from agents.prompt_constants import BULLISH_EVIDENCE_TAGS, BEARISH_EVIDENCE_TAGS
```

These constants already exist in `prompt_constants.py`. No new module or file needed.

### 8.4 _WEAK_SIGNAL_TAGS Dependency

`_WEAK_SIGNAL_TAGS` is already defined in `ai_quality_auditor.py` (line ~85-95). v34.0 Check 1 reuses this existing constant. No changes to the set needed.

---

## 9. Diagnostic Integration

### 9.1 smart_commit_analyzer.py

Add a new rule to detect v34.0 regressions:

```python
# In RULES list:
{
    'id': 'P1.115',
    'description': 'v34.0: _check_reason_signal_alignment uses BULLISH/BEARISH_EVIDENCE_TAGS',
    'file': 'agents/ai_quality_auditor.py',
    'check': lambda content: 'BULLISH_EVIDENCE_TAGS' in content and 'BEARISH_EVIDENCE_TAGS' in content,
},
{
    'id': 'P1.116',
    'description': 'v34.0: reason_signal_conflict field exists in QualityReport',
    'file': 'agents/ai_quality_auditor.py',
    'check': lambda content: 'reason_signal_conflict' in content,
},
{
    'id': 'P1.117',
    'description': 'v34.0: confidence_risk_conflict field exists in QualityReport',
    'file': 'agents/ai_quality_auditor.py',
    'check': lambda content: 'confidence_risk_conflict' in content,
},
```

### 9.2 diagnose_quality_scoring.py

Add a Stage 8 for v34.0 logic checks:

```python
# Stage 8: v34.0 Logic Coherence Checks
# Test scenario: LONG decision with 3 bearish + 1 bullish decisive_reasons
# Expected: reason_signal_conflict = 12

# Test scenario: HIGH confidence + risk_env score=7 (HIGH)
# Expected: confidence_risk_conflict = 6

# Test scenario: HOLD decision with all bearish tags
# Expected: reason_signal_conflict = 0 (HOLD exempt)
```

### 9.3 check_logic_sync.py

No SSoT changes needed — v34.0 checks use existing constants (`BULLISH_EVIDENCE_TAGS`, `BEARISH_EVIDENCE_TAGS`, `_TAG_TO_CATEGORIES`, `_WEAK_SIGNAL_TAGS`) all defined in their respective modules. No logic duplication introduced.

### 9.4 Heartbeat Monitoring

v34.0 flags appear in `QualityReport.to_summary()` → Telegram heartbeat message:

```
🔍 AI Quality: score=73 reason_sig=12 | REASON_SIGNAL_CONFLICT: decision=LONG conflict_ratio=0.75
```

```
🔍 AI Quality: score=79 conf_risk=6 | CONFIDENCE_RISK_CONFLICT: confidence=HIGH risk_env=HIGH(7)
```

```
🔍 AI Quality: score=85 | DEBATE_CONVERGENCE: bull=0.82 bear=0.78 spread=0.04
```

These appear in the private chat (运维监控), NOT the notification channel (per v14.0 dual-channel design).

### 9.5 Feature Snapshot Persistence

v34.0 flag data is automatically captured in feature snapshots (`data/feature_snapshots/`) via existing `QualityReport.to_dict()` → `ctx.quality_flags`. No additional persistence needed.

### 9.6 Web API Impact

`/api/admin/trade-evaluation/full` returns `ai_quality_score` per trade. After v34.0, scores may be lower for cycles with logic incoherence. The Web API returns the final score — no field-level breakdown exposed (flags are in snapshot files, not API).

**Future**: If needed, add `/api/admin/quality-audit/flags` endpoint to expose per-cycle flags for debugging.

---

## 10. Production Monitoring Checklist

After deploying v34.0, monitor for 7 days:

| Metric | Check | Expected Range | Action if Out of Range |
|---|---|---|---|
| Average quality score | Compare pre/post v34.0 | Drop ≤ 5 points average | Expected — new checks catch real issues |
| Average quality score | Compare pre/post v34.0 | Drop > 10 points average | Investigate — may be over-penalizing |
| REASON_SIGNAL_CONFLICT frequency | Count flags per day | < 10% of LONG/SHORT cycles | Expected — occasional incoherence |
| REASON_SIGNAL_CONFLICT frequency | Count flags per day | > 30% of LONG/SHORT cycles | Investigate — may be tag classification issue |
| CONFIDENCE_RISK_CONFLICT frequency | Count flags per day | < 5% of all cycles | Expected — rare (requires HIGH+HIGH) |
| DEBATE_CONVERGENCE frequency | Count flags per day | 10-40% of all cycles | Informational — establishes baseline |
| SINGLE_DIMENSION_DECISION frequency | Count flags per day | 5-20% of all cycles | Informational — establishes baseline |
| SIGNAL_SCORE_DIVERGENCE frequency | Count flags per day | 10-30% of LONG/SHORT cycles | Informational — establishes baseline |

**Monitoring command**:
```bash
# Count v34.0 flags in recent feature snapshots
cd /home/linuxuser/nautilus_AlgVex && \
  grep -r "REASON_SIGNAL_CONFLICT\|CONFIDENCE_RISK_CONFLICT\|DEBATE_CONVERGENCE\|SIGNAL_SCORE_DIVERGENCE\|SINGLE_DIMENSION_DECISION" \
  data/feature_snapshots/ | wc -l
```

---

## 11. Test Plan

### 11.1 Reason-Signal Alignment (10 tests)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | LONG + 4 bullish tags | 0 penalty |
| 2 | SHORT + 4 bearish tags | 0 penalty |
| 3 | LONG + 3 bearish / 1 bullish | 12 penalty (ratio=0.75) |
| 4 | SHORT + 2 bullish / 2 bearish | 8 penalty (ratio=0.50) |
| 5 | HOLD + all bearish tags | 0 penalty (HOLD exempt) |
| 6 | LONG + all neutral tags | 0 penalty (no directional tags) |
| 7 | LONG + 1 bearish / 3 bullish | 0 penalty (ratio=0.25) |
| 8 | Empty decisive_reasons | 0 penalty |
| 9 | LONG + [FR_FAVORABLE_SHORT, TREND_1D_BULLISH] | 0 penalty (FR excluded as weak, < 2 directional) |
| 10 | SHORT + 1 bullish tag only | 0 penalty (< 2 directional) |

### 11.2 Signal-Score Divergence (8 tests)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | LEAN_BULLISH_3of3 + LONG | None (aligned) |
| 2 | LEAN_BEARISH_3of3 + SHORT | None (aligned) |
| 3 | LEAN_BULLISH_3of3 + SHORT | Flag text (divergence) |
| 4 | LEAN_BEARISH_2of3 + LONG | Flag text (divergence) |
| 5 | CONFLICTING_1of3 + LONG | None (exempt) |
| 6 | INSUFFICIENT + SHORT | None (exempt) |
| 7 | LEAN_BEARISH_3of3 + HOLD | None (HOLD exempt) |
| 8 | LEAN_BULLISH_2of2 + SHORT | Flag text (divergence) |

### 11.3 Confidence-Risk Coherence (6 tests)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | HIGH confidence + HIGH risk (score=7) | 6 penalty |
| 2 | HIGH confidence + MODERATE risk (score=5) | 0 penalty |
| 3 | HIGH confidence + LOW risk (score=2) | 0 penalty |
| 4 | MEDIUM confidence + HIGH risk | 0 penalty |
| 5 | LOW confidence + HIGH risk | 0 penalty |
| 6 | Empty/missing confidence | 0 penalty |

### 11.4 Debate Quality (4 tests)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | Bull=0.85, Bear=0.82 (spread=0.03) | Flag (convergence) |
| 2 | Bull=0.9, Bear=0.3 (spread=0.6) | None (healthy debate) |
| 3 | Bull=0.5, Bear=0.5 (spread=0.0) | Flag (convergence) |
| 4 | Bull=0.7, Bear=0.55 (spread=0.15) | None (borderline OK) |

### 11.5 Reason Diversity (4 tests)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | [TREND_1D_BULLISH, MOMENTUM_4H_BULLISH, CVD_POSITIVE] (3 categories) | None (diverse) |
| 2 | [TREND_1D_BULLISH, DI_BULLISH_CROSS, SMA_BULLISH_CROSS_4H] (1 category: trend/technical) | Flag |
| 3 | Single decisive_reason | None (< 2 reasons) |
| 4 | [EXTENSION_OVEREXTENDED, VOL_HIGH] (non-directional) | None (no category mapping needed) |

### 11.6 Score Integration (4 tests)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | reason_signal=12 only | score = 88 |
| 2 | confidence_risk=6 only | score = 94 |
| 3 | Both: reason=8 + conf_risk=6 | score = 86 |
| 4 | Divergence + debate flags only (no penalty checks) | score = 100 |

### 11.7 Test File Location

**File**: `tests/test_auditor_logic_checks.py` (NEW)

```python
"""Tests for v34.0 auditor logic-level coherence checks."""
import pytest
from agents.ai_quality_auditor import AIQualityAuditor

class TestReasonSignalAlignment:
    """Check 1: decisive_reasons tag direction vs decision."""

    def test_long_all_bullish(self):
        penalty, flag = AIQualityAuditor._check_reason_signal_alignment(
            'LONG', ['TREND_1D_BULLISH', 'MOMENTUM_4H_BULLISH',
                     'CVD_POSITIVE', 'OI_LONG_OPENING'])
        assert penalty == 0

    def test_long_majority_bearish(self):
        penalty, flag = AIQualityAuditor._check_reason_signal_alignment(
            'LONG', ['TREND_1D_BEARISH', 'CVD_NEGATIVE',
                     'OBV_BEARISH_DIV_4H', 'MOMENTUM_4H_BULLISH'])
        assert penalty == 12  # 3/4 = 0.75

    # ... (all 10 scenarios from table 11.1)


class TestSignalScoreDivergence:
    """Check 2: _scores['net'] vs Judge decision."""

    def test_bullish_long_aligned(self):
        result = AIQualityAuditor._check_signal_score_divergence(
            'LEAN_BULLISH_3of3', 'LONG')
        assert result is None

    def test_bullish_short_diverged(self):
        result = AIQualityAuditor._check_signal_score_divergence(
            'LEAN_BULLISH_3of3', 'SHORT')
        assert result is not None
        assert 'LEAN_BULLISH_3of3' in result

    # ... (all 8 scenarios from table 11.2)


class TestConfidenceRiskCoherence:
    """Check 3: confidence vs risk_env."""

    def test_high_confidence_high_risk(self):
        penalty, flag = AIQualityAuditor._check_confidence_risk_coherence(
            'HIGH', 7, 'HIGH')
        assert penalty == 6

    def test_medium_confidence_high_risk(self):
        penalty, flag = AIQualityAuditor._check_confidence_risk_coherence(
            'MEDIUM', 7, 'HIGH')
        assert penalty == 0

    # ... (all 6 scenarios from table 11.3)


class TestDebateQuality:
    """Check 4: conviction spread."""

    def test_convergence(self):
        result = AIQualityAuditor._check_debate_quality(0.85, 0.82)
        assert result is not None
        assert 'spread=0.03' in result

    def test_healthy_debate(self):
        result = AIQualityAuditor._check_debate_quality(0.9, 0.3)
        assert result is None

    # ... (all 4 scenarios from table 11.4)


class TestReasonDiversity:
    """Check 5: tag category diversity."""

    def test_diverse(self):
        result = AIQualityAuditor._check_reason_diversity(
            ['TREND_1D_BULLISH', 'MOMENTUM_4H_BULLISH', 'CVD_POSITIVE'])
        assert result is None  # 3 categories

    def test_single_dimension(self):
        result = AIQualityAuditor._check_reason_diversity(
            ['SMA_BULLISH_CROSS_4H', 'MOMENTUM_4H_BULLISH', 'RSI_CARDWELL_BULL'])
        assert result is not None
        assert 'mtf_4h' in result

    # ... (all 4 scenarios from table 11.5)


class TestScoreIntegration:
    """Verify new penalties integrate with _calculate_score()."""

    def test_reason_signal_only(self):
        # Construct QualityReport with reason_signal_conflict=12
        # Verify overall_score = 100 - 12 = 88 (no other penalties)
        pass

    def test_both_penalties(self):
        # reason_signal=8 + confidence_risk=6 = 14
        # Verify overall_score = 100 - 14 = 86
        pass

    def test_informational_no_penalty(self):
        # DEBATE_CONVERGENCE + SIGNAL_SCORE_DIVERGENCE flags present
        # Verify overall_score still 100
        pass
```

**Run command**:
```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && python3 -m pytest tests/test_auditor_logic_checks.py -v
```

---

## 12. Rollback Plan

### 12.1 Layer 2 Rollback (v34.0 checks)

```bash
git revert <commit-hash>
# No persistent state changes — QualityReport is ephemeral.
# to_dict() fields are additive — older consumers ignore unknown keys.
# trading_memory.json quality scores are not retroactively affected.
```

**Safety**: QualityReport is created, used, and discarded every analysis cycle. No data migration needed. Reverting the commit removes all 5 checks immediately.

### 12.2 Layer 3 Rollback (correlation script)

```bash
rm scripts/analyze_quality_correlation.py
# No production impact — it's a read-only analysis script.
# Not imported by any production code.
```

### 12.3 Layer 1 Rollback (availability flags)

```bash
git revert <commit-hash>
# _avail_* features are additive. Removing them reverts to previous
# behavior where None→0.0 silently propagates.
# No data stored depends on _avail_* flags.
```

---

## 13. Implementation Roadmap (Step-by-Step)

### Phase 0: Layer 3 Correlation Script (Do First)

```
Step 1: Create scripts/analyze_quality_correlation.py (Section 7.4.3)
Step 2: Run on production data/trading_memory.json
Step 3: Evaluate results (Section 7.4.6 decision tree)
Step 4: If Pearson r > 0.15 → proceed to Phase 1
        If Pearson r < -0.05 → STOP, investigate scoring weights
        If Pearson r ∈ [-0.05, 0.15] → proceed with caution, informational checks only
```

### Phase 1: Layer 2 Logic Checks (v34.0)

```
Step 1: Add 2 fields to QualityReport dataclass (Section 3.1)
Step 2: Implement _check_reason_signal_alignment() as @staticmethod (Section 2.1.2)
Step 3: Implement _check_signal_score_divergence() as @staticmethod (Section 2.2.1)
Step 4: Implement _check_confidence_risk_coherence() as @staticmethod (Section 2.3.2)
Step 5: Implement _check_debate_quality() as @staticmethod (Section 2.4.2)
Step 6: Implement _check_reason_diversity() as @staticmethod (Section 2.5.2)
Step 7: Add import for BULLISH/BEARISH_EVIDENCE_TAGS (Section 5.4)
Step 8: Integrate into audit() at Step 3e-3i (Section 5.2)
Step 9: Add new penalties to _calculate_score() (Section 4.1)
Step 10: Update to_summary() and to_dict() (Section 3.2, 3.3)
Step 11: Create tests/test_auditor_logic_checks.py (Section 11.7)
Step 12: Run: python3 -m pytest tests/test_auditor_logic_checks.py -v
Step 13: Run: python3 scripts/smart_commit_analyzer.py
Step 14: Run: python3 scripts/check_logic_sync.py
Step 15: Add P1.115-P1.117 rules to smart_commit_analyzer.py (Section 9.1)
```

### Phase 2: Layer 1 Data Availability Flags (Separate PR)

```
Step 1: Add _avail_* flags to extract_features() (Section 7.2.3)
Step 2: Add FEATURE_SCHEMA entries for _avail_* flags (type=bool)
Step 3: Modify compute_scores_from_features() to exclude unavailable dimensions (Section 7.2.4)
Step 4: Add DATA_UNAVAILABLE flag to auditor (Section 7.2.5)
Step 5: Update expected coverage calculation in existing checks
Step 6: Run full test suite + smart_commit_analyzer
```

### Phase 3: Layer 3 Phase 2-3 (After 30+ trades post-v34.0)

```
Step 1: Add feature importance analysis (Section 7.4.4)
Step 2: Add time-series analysis (Section 7.4.5)
Step 3: Add v34.0 flag correlation: "Do DEBATE_CONVERGENCE flagged cycles have worse outcomes?"
Step 4: Calibrate Check 4 threshold (0.15) based on data
Step 5: Decide whether to promote informational checks to penalized based on correlation
```

### Phase 4: Future Roadmap (Section 7.6)

```
Step 1: HOLD source classification
Step 2: HOLD counterfactual tracking
Step 3: Confidence calibration from Layer 3 data
Step 4: v34.0 flag → penalty promotion (if data supports)
```

---

## Appendix A: File Change Summary

| File | Changes | Lines (est.) |
|---|---|---|
| `agents/ai_quality_auditor.py` | 5 new @staticmethod checks + QualityReport fields + audit() integration + _calculate_score() | +200 |
| `tests/test_auditor_logic_checks.py` | New test file (36 test cases) | +250 |
| `scripts/analyze_quality_correlation.py` | New analysis script (Phase 1) | +200 |
| `scripts/smart_commit_analyzer.py` | 3 new rules (P1.115-P1.117) | +15 |
| **Total** | | **~665** |

## Appendix B: Constant Values Reference

| Constant | Value | Location | Used By |
|---|---|---|---|
| `BULLISH_EVIDENCE_TAGS` | 27 tags (see 2.1.1) | `prompt_constants.py:1243` | Check 1 |
| `BEARISH_EVIDENCE_TAGS` | 26 tags (see 2.1.1) | `prompt_constants.py:1257` | Check 1 |
| `_WEAK_SIGNAL_TAGS` | 9 tags (see 2.1.1) | `ai_quality_auditor.py:85` | Check 1 |
| `_TAG_TO_CATEGORIES` | 76 tags → 13 categories (see 2.5.1) | `ai_quality_auditor.py:144` | Check 5 |
| `_NET_DIRECTION_RE` | `r'LEAN_(BULLISH\|BEARISH)_(\d+)of(\d+)'` | NEW in auditor | Check 2 |
| `_DEBATE_CONVERGENCE_THRESHOLD` | 0.15 | NEW in auditor | Check 4 |
| Reason-signal penalty: severe | 12 | NEW in auditor | Check 1 |
| Reason-signal penalty: moderate | 8 | NEW in auditor | Check 1 |
| Confidence-risk penalty | 6 | NEW in auditor | Check 3 |
| risk_env HIGH threshold | score ≥ 6 | `report_formatter.py:1040` | Check 3 (reference) |
