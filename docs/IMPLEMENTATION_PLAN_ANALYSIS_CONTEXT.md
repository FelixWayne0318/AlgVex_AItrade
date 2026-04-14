# AnalysisContext 统一架构 — Implementation Plan v1.8

### v1.8 Changes (Self-Review Bug Fixes)

| # | Fix | Phase | Detail |
|---|-----|-------|--------|
| BUG-1 | `_score_memory()` 新记忆旧维度 key 不匹配 | P5b | Phase 5b 只更新 `current` 侧 key 读取，未更新 `mem_cond` 侧。新记忆的 `conditions_v2` 用新 key (`rsi_30m`/`macd_bullish`/`bb_position_30m`)，但旧维度匹配代码读 `mem_cond.get('rsi')` / `mem_cond.get('macd')` → 全部 fallback 默认值。修复: 双侧统一提取，新记忆显式 bool→string 转换 |
| BUG-2 | Phase 5e `else` 分支引用已删除函数 | P5e | v1.7 删除 `_build_current_conditions()`，但 Phase 5e 代码保留 `else` 分支调用该函数。修复: 删除 else 分支，fail-fast 在 conditions 构建之前 |
| BUG-3 | fail-fast 位置未明确 | P5e+P6 | `_build_current_conditions()` 在 line 845 (BEFORE `_use_structured` check at line 862)。v1.7 删除后 fail-fast 必须在 line 845 之前触发。修复: 明确 fail-fast 替换 line 833 处 |
| BUG-4 | Phase 5e `to_dict()` 注释与实际不符 | P5e | 声称 `to_dict()` 输出 `"macd": "bullish"` (旧 key string)，实际输出 `"macd_bullish": True` (新 key bool)。修复: 删除错误注释，明确 `_score_memory()` 双侧更新 |
| 矛盾-1 | 归一化补偿缺失 | P5b | v1.7 删除 R4 归一化但未替换，旧记忆 max=11.0 vs 新记忆 max=15.5 分数尺度差异未处理。修复: 旧记忆按比例补偿缺失维度 |

### v1.7 Changes (Occam's Razor — Single System)

| # | Fix | Phase | Detail |
|---|-----|-------|--------|
| R9 | 彻底执行奥卡姆剃刀 | P2+P5+P6 | 删除: text fallback path (~400-600 行)、`_compute_dimensional_scores()`、`_build_current_conditions()`、`conditions` 双写、`to_dict()` 双 key 输出。异常改为 fail-fast (跳过本周期)。旧记忆只读兼容 (自然淘汰) |

### v1.6 Changes (Expert Review Fixes)

| # | Fix | Phase | Detail |
|---|-----|-------|--------|
| R1 | 问题 #2 描述不精确 | 摘要 | Auditor `valid_tags` 是参数传入而非独立 `compute_valid_tags()`。修正描述为精确的字段名不对称 (`rsi`/`adx` vs `rsi_30m`/`adx_1d`) |
| R2 | `_score_memory()` 维度数描述错误 | 验证表 | 实际 8 个维度 (5 条件 + confidence + grade + recency)，满分 11.0。修正描述 |
| R3 | `FrozenSet[str]` 类型与下游不一致 | P1+P3 | `compute_valid_tags()` 返回 `Set[str]`，`filter_output_tags()` type-hint `Set[str]`。改为 `Set[str]` 统一，移除 `frozenset()` 转换 |
| R4 | 新旧记忆分数尺度偏差无量化缓解 | P5b | 新增归一化比较 (`score / max_possible`)，防止旧高质量记忆被新低质量记忆系统性排挤 |
| R5 | `_compute_dimensional_scores()` 在 structured path 白算 | P2→P6 | v1.6: 移入 text fallback 分支。v1.7: text fallback 删除，该函数一并删除 |
| R6 | `_build_current_conditions()` 在 structured path 白算 | P5e→P6 | v1.6: 移入分支结构。v1.7: text fallback 删除，该函数一并删除 |
| R7 | 过渡期双系统无退出计划 | 新增 | v1.6: 增加退出时间表。v1.7: 彻底删除双系统，改为「单一系统原则」 |
| R8 | Phase 6 错误声称两套 conditions 函数 "输出相同 schema" | P6 | `_build_current_conditions()` 输出 `macd`(string)，`_from_features()` 输出 `macd_bullish`(bool)。v1.7 两者均删除，此问题不再存在 |
| R9 | 彻底执行奥卡姆剃刀 | P2+P5+P6 | 删除 text fallback path、`_compute_dimensional_scores()`、`_build_current_conditions()`、conditions 双写、to_dict() 双 key 输出。异常改为 fail-fast |

### v1.5 Changes (External Review Fixes)

| # | Fix | Phase | Detail |
|---|-----|-------|--------|
| B1 | `quality_flags` field missing from `AnalysisContext` | P1+P4 | Phase 4 writes `context.quality_flags` but dataclass had no such field → added `quality_flags: Optional[List[str]] = None` |
| B2 | Method name `_run_structured_et()` incorrect | P2 | Actual method is `_run_structured_entry_timing()` — all references corrected |
| B3 | `_score_memory` grade_value double-counting risk | P5d | Clarified that `score += grade_value * quality_weight` **replaces** existing `score += _grade_value.get(grade, 0)` (line 286), not appends |
| B4 | Score scale divergence (11.0 vs 15.5) undocumented | P5b | ~~Added note: expected behavior~~ → v1.6 R4 改为归一化方案 |

### v1.4 Changes (Code Review Fixes)

| # | Fix | Phase | Detail |
|---|-----|-------|--------|
| F1 | Method name verification | all | Confirmed `_run_structured_*` names match actual code — no fix needed |
| F2 | `filter_output_tags()` count unified | P3 | 16/~10 → **14** (7 production + 7 replay), all references updated |
| F3 | `_clear_position_state()` cleanup | P5 | Added `_entry_memory_conditions` + `_entry_ai_quality_score` cleanup to `safety_manager.py` |
| F4 | Remove redundant `adx_1d` field | P1 | Removed from `AnalysisContext`, use `ctx.features.get('adx_1d', 30.0)` |
| F5 | Remove `to_legacy_conditions_str()` | P1 | No consumer, violates Occam's — removed |
| F6 | `bb_position_30m` unit confirmation | P1 | Added comment confirming feature_dict uses 0-1 range |
| F7 | `confidence_chain` logging | P3 | Added chain summary log at `analyze()` return + DEFAULT/COERCED warning |
| F8 | `AnalysisContext.to_dict()` | P1 | Added debug serialization method |

See full review: `docs/REVIEW_ANALYSIS_CONTEXT.md`

---

## 问题摘要

当前系统的数据获取、特征提取、AI 分析、记忆系统、质量审计 5 个子系统各自独立演化，导致：

1. **同一份数据有 3-4 种表示**（原始 dict / feature_dict / conditions 字符串 / scores dict），各自独立转换和阈值
2. **Quality Auditor 的数值验证 (`_check_value_accuracy`) 用 `technical_data` 原始字段名 (如 `rsi`, `adx`)，但 Agent 看到 `feature_dict` 字段名 (如 `rsi_30m`, `adx_1d`)** — 数据源和字段名均不对称
3. **记忆系统的 conditions 只存 4-5 个维度**（RSI/MACD/BB/sentiment/direction），缺失 ADX/Extension/Volatility 等 v19+ 关键字段
4. **Quality Score (0-100) 与 Trade Grade (A+~F) 完全隔离** — 低质量分析恰好盈利的交易被强化
5. **valid_tags / scores 重复计算 6+ 次** — 结果相同但浪费且脆弱（`compute_valid_tags` ×6, `compute_scores_from_features` ×4~8）
6. **Confidence 来源不追踪** — 无法区分 AI 真实输出 vs schema default 填充 vs type coercion
7. **filter_output_tags() 后不重新验证** — 14 个调用点均无 empty evidence 检查

---

## 问题真实性验证 (v1.3 — 代码审计确认)

> 以下验证基于对代码库的逐行审计，确认所有 7 个问题均真实存在。

| # | 声称问题 | 验证状态 | 代码证据 |
|---|---------|---------|---------|
| 1 | 3-4 种数据表示 | ✅ **确认** | `technical_data` (raw dict) → `feature_dict` (extract_features) → `valid_tags` (set) → `scores` (dict)，每个 agent 阶段各自独立转换 |
| 2 | Auditor/Agent 数据不对称 | ✅ **确认** | `ai_quality_auditor.py:1010-1051`: `_check_value_accuracy()` 读 `technical_data` (key: `rsi`, `adx`)；Agent 读 `feature_dict` (key: `rsi_30m`, `adx_1d`)。字段名和数据源均不同 |
| 3 | 记忆只存 4 维度 | ✅ **确认 (修正为 5)** | `memory_manager.py:90-145`: `_build_current_conditions()` 输出 `rsi/macd/bb/sentiment/direction` 共 5 个维度。`_score_memory()` 匹配 8 个维度: 5 个条件维度 + confidence + grade + recency (RECENCY_WEIGHT=1.5, 14天半衰期指数衰减)，满分 11.0 |
| 4 | Quality Score 与 Grade 隔离 | ✅ **确认** | `quality_score` 存在 `signal_data['_quality_score']` 中，流向 execution → Telegram 显示，但 **不进入** `trading_memory.json` 的 memory entry |
| 5 | valid_tags 重复计算 5 次 | ✅ **确认 (修正为 6+)** | `compute_valid_tags()`: line 1193 (auditor) + line 3698 (debate) + line 3901 (judge) + line 3975 (ET) + line 4028 (risk) + line 4158 (replay) = **6 次**。`compute_scores_from_features()`: 4 次 production + 2 次 replay + 2 次 diagnostic = **8 次** |
| 6 | Confidence 来源不追踪 | ✅ **确认** | 全代码库无 `_confidence_origin` 字段。confidence 在 Judge→ET→Risk 链路中被修改但无来源记录 |
| 7 | filter 后不验证 | ✅ **确认** | `filter_output_tags()` 有 **14 个调用点** (multi_agent_analyzer.py: 7 production + 7 replay)，全部在 filter 后直接使用结果，无 empty evidence 检查 |

### 额外发现 (方案文档需修正)

| 发现 | 影响 | 修正 |
|------|------|------|
| `_build_current_conditions_from_features()` (line 4651) key 名不一致 — **现存 replay path bug** | `macd_bullish` (bool) vs `_build_current_conditions()` 的 `macd` (string)，`bb_position` vs `bb`。`_score_memory()` line 246 `current.get('macd', '')` 和 line 253 `current.get('bb', 50)` 均取不到值，**replay path 中 MACD(weight=1) + BB(weight=1) 两个维度评分始终为 0**。不影响生产 (生产用 `_build_current_conditions()`)。Phase 5a `to_dict()` 输出 `"macd": "bullish"/"bearish"` + `"bb"` 已修复 |
| `ALL_REFLECTION_ROLES` 已含 'risk' 但 prompt 不生成 | `memory_manager.py:897` 定义 5 角色常量，但 `generate_reflection()` prompt 只请求 4 角色 (bull/bear/judge/entry_timing) | Phase 5c 修复必要性确认：需在 prompt 中新增 risk 角色请求 |
| `_extract_role_reflection()` maps risk → judge | `memory_manager.py:321`: `role_key = agent_role if agent_role in ('bull', 'bear', 'judge', 'entry_timing') else 'judge'` — risk 退回 judge 反思 | Phase 5c 修复后此 fallback 仍保留为兼容旧数据 |
| Phase 3b "×4 处" filter 检查低估 | 实际有 14 处 filter 调用: production 7 (debate 4 + judge 1 + ET 1 + risk 1) + replay 7 (debate 4 + judge 1 + ET 1 + risk 1) | 下文 Phase 3b 已更新为准确数量 |

## 设计目标

引入 `AnalysisContext` 作为全流程唯一数据载体：

- **一次计算，全流程共享** — features/scores/valid_tags 只在 context 上计算一次
- **Agent 看到什么，Auditor 就验证什么** — 消除 Path A / Path B 不对称
- **记忆用 feature-based 相似度** — 替代自由文本 parse
- **信任链可追踪** — 每个 confidence 变更记录来源
- **向后兼容** — 渐进式替换，不破坏现有交易路径

## 非目标

- ❌ 不改变 AI 决策逻辑（Bull/Bear/Judge/ET/Risk 的 prompt 和行为不变）
- ❌ 不改变交易执行逻辑（`_execute_trade`, `calculate_mechanical_sltp` 不变）
- ❌ 不改变外部 API 调用逻辑（DataAssembler 的数据获取不变）
- ❌ 不改变 NautilusTrader 事件模型（on_timer, on_order_filled 等不变）

---

## Phase 1: AnalysisContext Dataclass 定义（纯增量）

### 目标
定义 typed dataclass，在 `analyze()` 入口创建并逐步填充，但**不改变现有任何逻辑**。Context 仅作为"影子记录"并行存在。

### 新增文件: `agents/analysis_context.py`

```python
"""
AnalysisContext — 全流程唯一数据载体。

设计原则:
1. 所有预计算结果存在 context 上，消费者只读不重算
2. Agent 输出逐步填充，下游 agent 从 context 读上游结果
3. 信任链追踪每个 confidence 变更的来源
4. 预计算字段 (features, valid_tags) 创建后语义上不应修改 (convention, not enforced)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# DataQualityFlags 已简化为 List[str] warnings (见 AnalysisContext.data_warnings)
# 理由: 原 dataclass 有 11 个 bool 字段但无消费者，违反奥卡姆原则。
# 实际只需要一个 warnings 列表供日志和审计使用。


@dataclass
class ConfidenceStep:
    """信任链中的一步变更"""
    phase: str          # "judge" | "entry_timing" | "risk" | "schema_default"
    value: str          # "HIGH" | "MEDIUM" | "LOW"
    origin: str         # "AI" | "DEFAULT" | "COERCED" | "CAPPED"
    reason: str = ""    # 变更原因


@dataclass
class ConfidenceChain:
    """追踪 confidence 在各阶段的来源和变更"""
    steps: List[ConfidenceStep] = field(default_factory=list)

    def add(self, phase: str, value: str, origin: str, reason: str = ""):
        self.steps.append(ConfidenceStep(phase, value, origin, reason))

    @property
    def final(self) -> str:
        return self.steps[-1].value if self.steps else "MEDIUM"

    @property
    def final_origin(self) -> str:
        return self.steps[-1].origin if self.steps else "UNKNOWN"

    def has_default(self) -> bool:
        """是否有任何阶段使用了 schema default"""
        return any(s.origin in ("DEFAULT", "COERCED") for s in self.steps)


# ValidatedAgentOutput 已移除 (奥卡姆原则)
# 理由: Phase 3 中 confidence_origin 追踪已改为外部包装方式 (见 Phase 3a)。
# Agent 输出的 schema_violations 等信息已由现有 _schema_violations dict 追踪，
# 无需引入新 dataclass。如未来需要更结构化的追踪，可在有具体消费者时再引入。


@dataclass
class MemoryConditions:
    """
    Feature-based 记忆条件快照。

    替代自由文本 "RSI=65, MACD=bullish, BB=72%"，
    使用 feature_dict 的子集，支持多维度相似度匹配。
    """
    # v5.10 原有维度 (向后兼容)
    rsi_30m: float = 50.0
    macd_bullish: bool = True
    bb_position_30m: float = 50.0
    sentiment: str = "neutral"           # crowded_long / neutral / crowded_short
    direction: str = "LONG"              # LONG / SHORT

    # v29+ 新增维度 (记忆相似度关键缺失)
    adx_1d: float = 25.0
    adx_regime: str = "WEAK_TREND"       # STRONG_TREND / WEAK_TREND / RANGING
    extension_regime: str = "NORMAL"     # NORMAL / EXTENDED / OVEREXTENDED / EXTREME
    volatility_regime: str = "NORMAL"    # LOW / NORMAL / HIGH / EXTREME
    cvd_trend_30m: str = "NEUTRAL"       # POSITIVE / NEGATIVE / NEUTRAL
    funding_rate_pct: float = 0.0
    rsi_4h: float = 50.0

    @classmethod
    def from_feature_dict(cls, fd: Dict[str, Any]) -> "MemoryConditions":
        """从 feature_dict 构建，确保与 Agent 看到的数据一致"""
        macd_val = fd.get("macd_30m", 0)
        macd_sig = fd.get("macd_signal_30m", 0)
        lr = fd.get("long_ratio", 0.5)
        if lr > 0.6:
            sent = "crowded_long"
        elif lr < 0.4:
            sent = "crowded_short"
        else:
            sent = "neutral"

        # Direction: 与现有 _build_current_conditions() (v5.11) 保持一致
        # 优先用 MACD lean，fallback 到 RSI。不用 DI+/DI- (避免逻辑不一致)。
        macd_bullish = (macd_val > macd_sig)
        rsi = fd.get("rsi_30m", 50.0)
        if macd_val != 0 or macd_sig != 0:
            direction = "LONG" if macd_bullish else "SHORT"
        else:
            direction = "LONG" if rsi >= 50 else "SHORT"

        return cls(
            rsi_30m=fd.get("rsi_30m", 50.0),
            macd_bullish=(macd_val > macd_sig),
            # bb_position_30m 在 feature_dict 中为 0-1 范围 (见 report_formatter.py:2765
            # _sf(td, 'bb_position') 直接取 technical_data 的 0-1 值)，×100 转为 0-100%
            bb_position_30m=fd.get("bb_position_30m", 0.5) * 100,
            sentiment=sent,
            direction=direction,
            adx_1d=fd.get("adx_1d", 25.0),
            adx_regime=fd.get("market_regime", "WEAK_TREND"),
            extension_regime=fd.get("extension_regime", "NORMAL"),
            volatility_regime=fd.get("volatility_regime", "NORMAL"),
            cvd_trend_30m=fd.get("cvd_trend_30m", "NEUTRAL"),
            funding_rate_pct=fd.get("funding_rate_pct", 0.0),
            rsi_4h=fd.get("rsi_4h", 50.0),
        )

    # v1.4: to_legacy_conditions_str() 已移除 (奥卡姆原则 — 无消费者)
    # 如需 debug 输出，使用 to_dict() + json.dumps() 即可


@dataclass
class AnalysisContext:
    """
    全流程唯一数据载体 — 所有子系统共享同一实例。

    生命周期:
      analyze() 入口创建 → 预计算填充 → Agent 逐步填充 → Auditor 验证 → 返回
    """

    # ===== 元信息 =====
    snapshot_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    symbol: str = "BTCUSDT"

    # ===== 阶段 1: 数据质量 (简化为 List[str]) =====
    data_warnings: List[str] = field(default_factory=list)

    # ===== 阶段 2: 预计算 (一次计算，全流程共享) =====
    # 这些字段在 analyze() 入口填充后不再修改
    features: Optional[Dict[str, Any]] = None       # extract_features() 结果
    scores: Optional[Dict[str, Any]] = None         # compute_scores() 结果
    valid_tags: Optional[Set[str]] = None              # compute_valid_tags() 结果 (与下游 filter_output_tags type-hint 一致)
    annotated_tags: Optional[str] = None             # compute_annotated_tags() 结果
    # v1.4: adx_1d 冗余字段已移除 — 直接从 ctx.features.get('adx_1d', 30.0) 读取

    # ===== 阶段 3: 记忆 =====
    memory_conditions: Optional[MemoryConditions] = None

    # ===== 阶段 4: 信任链 =====
    confidence_chain: ConfidenceChain = field(default_factory=ConfidenceChain)

    # ===== 阶段 5: 质量审计 =====
    quality_score: Optional[int] = None
    quality_flags: Optional[List[str]] = None   # Phase 4: audit flags written back

    def is_prepared(self) -> bool:
        """预计算阶段是否完成"""
        return self.features is not None and self.valid_tags is not None

    def to_dict(self) -> Dict[str, Any]:
        """Debug/logging: 序列化关键状态为 dict"""
        return {
            "snapshot_id": self.snapshot_id,
            "symbol": self.symbol,
            "is_prepared": self.is_prepared(),
            "data_warnings": self.data_warnings,
            "valid_tags_count": len(self.valid_tags) if self.valid_tags else 0,
            "confidence_chain": [
                {"phase": s.phase, "value": s.value, "origin": s.origin}
                for s in self.confidence_chain.steps
            ],
            "quality_score": self.quality_score,
        }
```

### 改动范围

| 文件 | 改动 | 行数 |
|------|------|------|
| `agents/analysis_context.py` | **新增** (精简后: ConfidenceStep/Chain + MemoryConditions + AnalysisContext + to_dict) | ~130 行 |
| `agents/multi_agent_analyzer.py` | 在 `analyze()` 入口创建 context，逐步填充 | ~30 行插入 |

### 验证方式

```bash
python3 -c "from agents.analysis_context import AnalysisContext; ctx = AnalysisContext(); print(ctx.snapshot_id)"
```

---

## Phase 2: 预计算统一 — 一次计算，全流程共享

### 目标
将 `compute_valid_tags()` / `compute_scores_from_features()` / `compute_annotated_tags()` 从每个 agent 阶段各调一次，改为在 context 上只调一次。

### 改动: `agents/multi_agent_analyzer.py`

**之前** (6 次重复计算，v1.3 代码审计确认):
```python
# analyze() → quality_auditor.audit()
_audit_valid_tags = compute_valid_tags(feature_dict)  # 第 1 次 (line 1193)

# _run_structured_debate()
valid_tags = compute_valid_tags(feature_dict)      # 第 2 次 (line 3698)
tags_ref = compute_annotated_tags(feature_dict, valid_tags)
dim_scores = ReportFormatterMixin.compute_scores_from_features(feature_dict)

# _run_structured_judge()
valid_tags = compute_valid_tags(feature_dict)      # 第 3 次 (line 3901)
tags_ref = compute_annotated_tags(feature_dict, valid_tags)
dim_scores = ReportFormatterMixin.compute_scores_from_features(feature_dict)

# _run_structured_entry_timing()
valid_tags = compute_valid_tags(feature_dict)      # 第 4 次 (line 3975)
# ... 同样模式

# _run_structured_risk()
valid_tags = compute_valid_tags(feature_dict)      # 第 5 次 (line 4028)
# ...

# analyze_from_features() (replay path)
valid_tags = compute_valid_tags(feature_dict)      # 第 6 次 (line 4158)
```

**之后** (1 次计算，context 传递):
```python
# analyze() 中，feature_dict 提取后立即:
ctx.features = feature_dict
ctx.valid_tags = compute_valid_tags(feature_dict)
ctx.annotated_tags = compute_annotated_tags(feature_dict, ctx.valid_tags)
ctx.scores = ReportFormatterMixin.compute_scores_from_features(feature_dict)
# v1.7: text fallback path 已删除，_compute_dimensional_scores() 也一并删除。
# ctx.scores 是唯一的 scores 来源 (feature-based)。

# 各阶段只读:
# _run_structured_debate(ctx)  → 读 ctx.valid_tags, ctx.annotated_tags, ctx.scores
# _run_structured_judge(ctx)   → 同上
# _run_structured_entry_timing(ctx)      → 同上
# _run_structured_risk(ctx)    → 同上
# quality_auditor.audit(ctx)   → 读 ctx.valid_tags (而非重新计算)
```

### 改动范围

| 文件 | 改动 | 说明 |
|------|------|------|
| `agents/multi_agent_analyzer.py` | `analyze()` 中新增 context 初始化块 (~10 行) | 一次计算 |
| `agents/multi_agent_analyzer.py` | `_run_structured_debate()` 签名增加 `ctx` 参数 | 读 `ctx.valid_tags` 替代 `compute_valid_tags()` |
| `agents/multi_agent_analyzer.py` | `_run_structured_judge()` 同上 | 同上 |
| `agents/multi_agent_analyzer.py` | `_run_structured_entry_timing()` 同上 | 同上 |
| `agents/multi_agent_analyzer.py` | `_run_structured_risk()` 同上 | 同上 |
| `agents/multi_agent_analyzer.py` | `quality_auditor.audit()` 调用处 | 传 `ctx.valid_tags` 替代重新计算 |

**估计改动**: ~60 行修改（主要是参数传递），删除 ~20 行重复的 `compute_*` 调用。

---

## Phase 3: Agent 输出追踪 — 信任链 + 交叉验证

### 目标
1. 追踪 confidence 在 Judge → ET → Risk 链路中的来源
2. `_validate_agent_output()` 后记录 schema_violations 和 confidence_origin
3. `filter_output_tags()` 后检查 evidence 是否被清空

### 改动 3a: Confidence 来源追踪

**在 `_validate_agent_output()` 中**:
```python
# 当 confidence 字段被 default 填充时:
if key == "confidence" and key not in output:
    result[key] = defaults.get(key, "MEDIUM")
    violations += 1
    result["_confidence_origin"] = "DEFAULT"  # 新增

# 当 confidence 被 type coercion 修正时:
elif key == "confidence" and val_upper not in valid_set:
    result[key] = defaults.get(key, "MEDIUM")
    result["_confidence_origin"] = "COERCED"  # 新增
```

**在 `analyze()` 中，Judge 输出后**:
```python
ctx.confidence_chain.add(
    phase="judge",
    value=judge_decision["confidence"],
    origin=judge_decision.get("_confidence_origin", "AI"),
)
```

**在 Entry Timing 调整后**:
```python
if timing_assessment.get("adjusted_confidence") != judge_decision["confidence"]:
    ctx.confidence_chain.add(
        phase="entry_timing",
        value=timing_assessment["adjusted_confidence"],
        origin="AI",
        reason=timing_assessment.get("reason", ""),
    )
```

**在 `analyze()` 返回前，记录 confidence_chain summary** (v1.4 新增):
```python
# analyze() 末尾，信号返回前:
if ctx.confidence_chain.steps:
    chain_summary = " → ".join(
        f"{s.phase}:{s.value}({s.origin})" for s in ctx.confidence_chain.steps
    )
    self.logger.info(f"[{ctx.snapshot_id}] Confidence chain: {chain_summary}")
    if ctx.confidence_chain.has_default():
        self.logger.warning(f"[{ctx.snapshot_id}] ⚠️ Confidence chain contains DEFAULT/COERCED step")
```

### 改动 3b: filter_output_tags 后 re-validate

**当前问题**: `filter_output_tags()` 在 production structured path 有 **7 处调用点** (debate: bull_r1/bear_r1/bull_r2/bear_r2 各 1 + judge 1 + ET 1 + risk 1)，replay path 另有 **7 处**，共 **14 个调用点**，全部在 filter 后直接使用结果，无 empty evidence 检查。`filter_output_tags()` 只返回 removed count，不验证结果。

**修复方案**: 提取通用 helper，在每个 filter 调用后统一检查：
```python
def _safe_filter_tags(self, output: dict, valid_tags: Set[str], agent_label: str) -> int:
    """Filter invalid tags and ensure evidence is never empty."""
    removed = filter_output_tags(output, valid_tags)
    if not output.get("evidence"):
        output["evidence"] = ["INCONCLUSIVE"]
        self.logger.warning(f"[{agent_label}] All evidence tags filtered — using INCONCLUSIVE fallback")
    return removed
```

**应用到所有 7 处 production 调用点** (替代直接调用 `filter_output_tags()`)。replay path 7 处也同步替换：
```python
# 之前 (14 处):
filter_output_tags(bull_r1, valid_tags)

# 之后:
self._safe_filter_tags(bull_r1, ctx.valid_tags, "Bull R1")
```

**INCONCLUSIVE tag 设计** (v1.1 已确认):
- `INCONCLUSIVE` **不**加入 `REASON_TAGS` 集合 — Agent 无法选择此 tag
- 仅由 `_safe_filter_tags()` 代码自动填充，防止 Agent 滥用
- 仅在 filter 清空 **所有** evidence 后触发（极少见场景）

### ~~改动 3c~~ 已移除

~~`ValidatedAgentOutput` dataclass 已移除 (奥卡姆原则)~~。现有 `_schema_violations` dict 已追踪每个 Agent 的违规数。如未来需要更结构化的追踪，可在有具体消费者时再引入。

### 改动范围

| 文件 | 改动 | 行数 |
|------|------|------|
| `agents/multi_agent_analyzer.py` | `_validate_agent_output()` 增加 `_confidence_origin` 标记 | ~10 行 |
| `agents/multi_agent_analyzer.py` | `analyze()` 中记录 confidence_chain | ~15 行 |
| `agents/multi_agent_analyzer.py` | 新增 `_safe_filter_tags()` helper + 替换 14 处 filter 调用 (7 production + 7 replay) | ~25 行 |
| `agents/prompt_constants.py` | ~~REASON_TAGS 增加 `"INCONCLUSIVE"`~~ — 不需要 (INCONCLUSIVE 由代码注入，不进 REASON_TAGS) | 0 行 |

---

## Phase 4: Quality Auditor 对齐 — 用 context.features 验证

### 目标
Auditor 从 `context.features` 读取数据做验证，而非从原始 `technical_report` 独立提取。消除 Path A / Path B 不对称。

### 改动: `agents/ai_quality_auditor.py`

**数值验证 (`_check_value_accuracy`)**: 当前从 `technical_data` dict 直接读字段，改为从 `context.features` 读：

```python
# 之前:
rsi_actual = technical_data.get('rsi', None)

# 之后:
rsi_actual = context.features.get('rsi_30m', None) if context and context.features else technical_data.get('rsi', None)
```

**Data Coverage 检查**: 当前用 `_TAG_TO_CATEGORIES` + 文本正则双路径。有 context 时，直接用 tag-based 路径：

```python
# 之前: valid_tags 参数可选，可能为 None
# 之后: 从 context.valid_tags 读取，保证与 Agent 使用的完全一致

def audit(self, ..., context: Optional[AnalysisContext] = None):
    if context and context.valid_tags:
        _audit_valid_tags = context.valid_tags  # 同一份，不重算
    else:
        _audit_valid_tags = compute_valid_tags(feature_dict) if feature_dict else None
```

**新增: quality_score 写回 context**:
```python
if context:
    context.quality_score = quality_report.overall_score
    context.quality_flags = quality_report.flags
```

### 关键约束
- **Auditor 的所有数值比对都转为使用 feature_dict 字段名** (如 `rsi_30m` 而非 `rsi`)
- **保留原始 technical_data 作为 fallback** (feature_dict 为 None 时)
- BB position 单位对齐：feature_dict 中 0-1，auditor 比对时 ×100

### 改动范围

| 文件 | 改动 | 说明 |
|------|------|------|
| `agents/ai_quality_auditor.py` | `audit()` 签名增加 `context` 参数 | 可选，向后兼容 |
| `agents/ai_quality_auditor.py` | `_check_value_accuracy()` 优先读 context.features | ~30 行 |
| `agents/ai_quality_auditor.py` | `_check_data_coverage()` 使用 context.valid_tags | ~10 行 |
| `agents/ai_quality_auditor.py` | 写回 context.quality_score | ~5 行 |

---

## Phase 5: 记忆系统升级 — Feature-Based 相似度

### 目标
1. `record_outcome()` 存 `MemoryConditions`（feature-based）而非自由文本
2. `_score_memory()` 用新维度做相似度匹配
3. 反思增加 Risk Manager 角色
4. 记忆中关联 quality_score

### 改动 5a: 开仓时快照 MemoryConditions，平仓时取回

**关键设计问题**: `AnalysisContext` 在 `analyze()` 中创建，生命周期仅限该次调用。但 `record_outcome()` 在 `on_position_closed` 时调用（可能数小时甚至数天后）。**AnalysisContext 不能直接传递到 `record_outcome()`**。

**解决方案**: 沿用现有的 `on_position_opened` 快照模式。现有代码已在 `on_position_opened` 中保存 `_entry_winning_side`, `_entry_judge_summary` 等快照。MemoryConditions 遵循完全相同的模式：

**步骤 1 — 在 `analyze()` 返回数据中携带 MemoryConditions**:
```python
# multi_agent_analyzer.py: analyze() 返回的 signal_data dict
signal_data['_memory_conditions_snapshot'] = ctx.memory_conditions.to_dict() if ctx.memory_conditions else None
signal_data['_ai_quality_score'] = ctx.quality_score
```

**步骤 2 — 在 `on_position_opened()` 中快照** (`event_handlers.py`):
```python
# 与 _entry_winning_side 等同级，在 on_position_opened 中保存
if hasattr(self, 'latest_signal_data') and self.latest_signal_data:
    self._entry_memory_conditions = self.latest_signal_data.get('_memory_conditions_snapshot')
    self._entry_ai_quality_score = self.latest_signal_data.get('_ai_quality_score')
else:
    self._entry_memory_conditions = None
    self._entry_ai_quality_score = None
```

**步骤 3 — 在 `on_position_closed()` → `record_outcome()` 中使用**:
```python
# event_handlers.py: on_position_closed 中调用 record_outcome 时
self.multi_agent.record_outcome(
    ...,
    conditions_v2=getattr(self, '_entry_memory_conditions', None),
    ai_quality_score=getattr(self, '_entry_ai_quality_score', None),
)
```

**步骤 4 — `record_outcome()` 新增参数**:
```python
def record_outcome(
    self, ...,
    conditions_v2: Optional[Dict[str, Any]] = None,  # 新增
    ai_quality_score: Optional[int] = None,           # 新增
):
    # ...
    # v1.7: 只写 conditions_v2，不再写旧 conditions 字段
    if conditions_v2:
        entry["conditions_v2"] = conditions_v2
    if ai_quality_score is not None:
        entry["ai_quality_score"] = ai_quality_score
```

**为什么不直接传 context**: AnalysisContext 生命周期仅限 `analyze()` 调用栈。开仓到平仓可能经历多次 `analyze()` 调用（加仓、减仓判断），跨小时/天。快照模式是本系统的既有模式，安全可靠。

**快照时间点说明**: `conditions_v2` 取自 `analyze()` 时的 `feature_dict`，比旧 `conditions` (取自 `on_position_opened` 时实时读 indicator_manager) 更准确——它是 AI 做决策时看到的数据。

**v1.7 奥卡姆简化**: 不再写入旧 `conditions` 字段。旧记忆中已有的 `conditions` 由 `_score_memory()` 旧 parse 逻辑只读处理。随 500 条滚动窗口自然淘汰旧记忆，旧 parse 逻辑最终一并删除。

**MemoryConditions.to_dict() 方法** (v1.7: 只输出新 key):
```python
def to_dict(self) -> Dict[str, Any]:
    """Serialize for memory retrieval and snapshot storage.

    v1.7: Only new-format keys. _score_memory() Phase 5b reads these directly.
    No legacy key output (旧 rsi/macd/bb key 不再写入).
    """
    return {
        "rsi_30m": self.rsi_30m,
        "macd_bullish": self.macd_bullish,
        "bb_position_30m": self.bb_position_30m,
        "sentiment": self.sentiment,
        "direction": self.direction,
        "adx_regime": self.adx_regime,
        "extension_regime": self.extension_regime,
        "volatility_regime": self.volatility_regime,
        "cvd_trend_30m": self.cvd_trend_30m,
        "rsi_4h": self.rsi_4h,
        "adx_1d": self.adx_1d,
        "funding_rate_pct": self.funding_rate_pct,
    }
```

**旧记忆兼容** (只读): 旧记忆只有 `conditions` (string)，`_score_memory()` 检测到无 `conditions_v2` 时退回旧 parse 逻辑 (只读旧数据，不写新的旧格式)。随 500 条窗口淘汰后删除旧 parse。

### 改动 5b: 增强相似度匹配

**v1.7/v1.8 `_score_memory()` 重构**: `current` 参数现在来自 `MemoryConditions.to_dict()` (新 key: `rsi_30m`/`macd_bullish`/`bb_position_30m`)。旧维度匹配逻辑**双侧** (current + mem_cond) 同步更新：

```python
# ===== current 侧: 始终来自 MemoryConditions.to_dict() (新 key) =====
cur_rsi = float(current.get('rsi_30m', 50))
cur_macd = "bullish" if current.get('macd_bullish', False) else "bearish"
cur_bb = float(current.get('bb_position_30m', 50))
cur_sentiment = current.get('sentiment', 'neutral')

# ===== mem_cond 侧: 旧记忆用旧 key, 新记忆用新 key → 统一提取 =====
# ⚠️ v1.8 BUG-1 修复: 必须双侧都适配新 key, 否则新记忆旧维度全为 0
if 'conditions_v2' in mem:
    cv2 = mem['conditions_v2']
    mem_rsi = float(cv2.get('rsi_30m', 50))
    mem_macd = "bullish" if cv2.get('macd_bullish', False) else "bearish"
    mem_bb = float(cv2.get('bb_position_30m', 50))
    mem_sentiment = cv2.get('sentiment', 'neutral')
else:
    raw = self._parse_conditions(mem.get('conditions', ''))
    mem_rsi = float(raw.get('rsi', 50))
    mem_macd = raw.get('macd', '').lower()
    mem_bb = float(raw.get('bb', 50))
    mem_sentiment = raw.get('sentiment', 'neutral')

# ===== 旧维度匹配 (统一变量名, 与现有 _classify_rsi/_classify_bb 兼容) =====
# Direction (weight=3) — 不变, 读 current.get('direction') vs mem.get('decision')
# RSI zone (weight=2):
cur_rsi_zone = self._classify_rsi(cur_rsi)
mem_rsi_zone = self._classify_rsi(mem_rsi)
if cur_rsi_zone == mem_rsi_zone:
    score += 2.0
elif {cur_rsi_zone, mem_rsi_zone} != {"oversold", "overbought"}:
    score += 0.6

# MACD direction (weight=1):
if cur_macd and mem_macd and cur_macd == mem_macd:
    score += 1.0

# BB zone (weight=1):
cur_bb_zone = self._classify_bb(cur_bb)
mem_bb_zone = self._classify_bb(mem_bb)
if cur_bb_zone == mem_bb_zone:
    score += 1.0

# Sentiment (weight=1):
if cur_sentiment and mem_sentiment and cur_sentiment == mem_sentiment:
    score += 1.0
```

**新增维度** (仅当 `conditions_v2` 存在时):

**在 `_score_memory()` 中新增维度**:
```python
# 新增维度 (仅当 conditions_v2 存在时)
if 'conditions_v2' in mem:
    cv2 = mem['conditions_v2']

    # ADX regime 匹配 (权重 1.5 — 趋势/震荡区分对策略影响极大)
    if cv2.get('adx_regime') == current.get('adx_regime'):
        score += 1.5

    # Extension regime 匹配 (权重 1.0)
    if cv2.get('extension_regime') == current.get('extension_regime'):
        score += 1.0
    elif cv2.get('extension_regime') in ('OVEREXTENDED', 'EXTREME') and \
         current.get('extension_regime') in ('OVEREXTENDED', 'EXTREME'):
        score += 0.5  # 都是高延伸，相邻匹配

    # Volatility regime 匹配 (权重 0.5)
    if cv2.get('volatility_regime') == current.get('volatility_regime'):
        score += 0.5

    # CVD 趋势匹配 (权重 0.5)
    if cv2.get('cvd_trend_30m') == current.get('cvd_trend_30m'):
        score += 0.5

    # 4H RSI zone 匹配 (权重 0.5)
    cur_rsi4h_zone = self._classify_rsi(current.get('rsi_4h', 50))
    mem_rsi4h_zone = self._classify_rsi(cv2.get('rsi_4h', 50))
    if cur_rsi4h_zone == mem_rsi4h_zone:
        score += 0.5
```

**新的总分上限**: 11.0 (旧维度) + 4.5 (新维度) = **15.5**

> **v1.8 分数尺度补偿** (v1.7 矛盾-1 修复): 新记忆 max=15.5, 旧记忆 max=11.0。为防止旧记忆被系统性低估，`_score_memory()` 末尾对旧记忆补偿缺失维度：
>
> ```python
> # _score_memory() 末尾，return 前:
> if 'conditions_v2' not in mem:
>     # 旧记忆缺失 5 个新维度 (max 4.5)，按旧维度比例补偿
>     max_old = 11.0
>     score += 4.5 * (score / max_old) if max_old > 0 else 0
> ```
>
> 旧记忆 10.5/11.0 → 补偿后 10.5 + 4.3 = 14.8，与新记忆 14.8/15.5 可比。随 500 条自然淘汰后删除此补偿。

### 改动 5c: 反思增加 Risk Manager 角色

**代码审计确认** (v1.3):
- `memory_manager.py:897`: `ALL_REFLECTION_ROLES = ('bull', 'bear', 'judge', 'entry_timing', 'risk')` — 常量已包含 risk
- `generate_reflection()` prompt (line 850-871): 只请求 **4 角色** (bull/bear/judge/entry_timing)，**缺少 risk**
- `_extract_role_reflection()` (line 321): `role_key = agent_role if agent_role in ('bull', 'bear', 'judge', 'entry_timing') else 'judge'` — risk **退回 judge 反思**
- 结论: 常量已准备但 prompt 和 extract 逻辑未对齐，确认需要修复

**在 `generate_reflection()` 的 prompt 中**:
```python
# 之前 (4 角色, line 850-871):
# {"bull": "...", "bear": "...", "judge": "...", "entry_timing": "..."}

# 之后 (5 角色):
# {"bull": "...", "bear": "...", "judge": "...", "entry_timing": "...", "risk": "风险管理应该学到什么？仓位大小、SL距离、波动率适应..."}
```

**在 `_extract_role_reflection()` 中**:
```python
# 之前 (line 321):
role_key = agent_role if agent_role in ('bull', 'bear', 'judge', 'entry_timing') else 'judge'

# 之后:
role_key = agent_role if agent_role in ALL_REFLECTION_ROLES else 'judge'
# 新记忆有 risk key → 直接提取; 旧记忆无 risk key → fallback 到 judge (向后兼容)
```

### 改动 5d: 记忆关联 quality_score

**quality_score 已在 5a 中通过快照传递到 `record_outcome()`**。不再需要 context 直接传递。

**在 `_score_memory()` 中** (line 275-286, **替换**现有 `score += _grade_value.get(grade, 0)`)：
```python
# quality_score 影响 grade_value 权重
# ⚠️ 注意: 替换现有 line 286 的 `score += _grade_value.get(grade, 0)`,
# 不是追加！否则 grade 会被计算两次。
grade_value = _grade_value.get(grade, 0)
quality_weight = 1.0
if 'ai_quality_score' in mem:
    qs = mem['ai_quality_score']
    if qs < 40:
        quality_weight = 0.3   # 严重降权：低质量分析的经验不可靠
    elif qs < 60:
        quality_weight = 0.5
    elif qs < 80:
        quality_weight = 0.8
score += grade_value * quality_weight  # 替换原来的 score += _grade_value.get(grade, 0)
```

### 改动 5e: 检索条件与存储维度对齐

**问题**: `_select_memories()` 在 `analyze()` line 845 使用 `_build_current_conditions(technical_report, sentiment_report)` 构建检索条件。该函数只输出 4 个旧维度 (`rsi`, `macd`, `bb`, `sentiment`)。Phase 5b 新增的 5 个维度 (`adx_regime`, `extension_regime`, `volatility_regime`, `cvd_trend_30m`, `rsi_4h`) 在检索时永远为 0 分，等于白加。

**修复**: structured path 中改用 `MemoryConditions` 构建检索条件。

**⚠️ 奥卡姆修复 (v1.6 R6)**: 当前 `_build_current_conditions()` 在 line 845 无条件调用（在 `_use_structured` 分支之前）。此修复将其移入分支结构，**替换** line 845 的无条件调用，不保留两套并行调用：

```python
# multi_agent_analyzer.py: analyze() 中
# ⚠️ v1.8 BUG-2+3 修复: fail-fast 必须在 conditions 构建之前
# v1.7 删除了 _build_current_conditions()，只有 MemoryConditions 路径

# 位置: 替换原 line 833 (feature_dict = None 赋值处)
# feature extraction 失败 → fail-fast 返回 None
try:
    feature_dict = self.extract_features(...)
except Exception as e:
    self.logger.error(f"Feature extraction failed: {e}")
    return None  # fail-fast: 跳过本周期

# 位置: 替换原 line 845 的 _build_current_conditions() 调用
# feature_dict 一定非 None (fail-fast 已返回)
mc = MemoryConditions.from_feature_dict(feature_dict)
ctx.memory_conditions = mc
current_conditions = mc.to_dict()  # 12 维度
selected_memories = self._select_memories(current_conditions)
```

**v1.8 BUG-1+4 修复**: `to_dict()` 输出新 key (`rsi_30m`/`macd_bullish`(bool)/`bb_position_30m`)，与旧 `_build_current_conditions()` 的旧 key (`rsi`/`macd`(string)/`bb`) 不同。`_score_memory()` 的旧维度匹配逻辑**必须双侧更新** (见 Phase 5b 代码)：
- `current` 侧: 读新 key，bool → string 转换
- `mem_cond` 侧: 新记忆读新 key (bool → string)，旧记忆读旧 key (string 原样)

不再要求 `to_dict()` 输出旧 key。

### 改动范围

| 文件 | 改动 | 说明 |
|------|------|------|
| `agents/memory_manager.py` | `record_outcome()` 新增 `conditions_v2` + `ai_quality_score` 参数 | ~10 行 |
| `agents/memory_manager.py` | `_score_memory()` 增加 5 个新维度 | ~30 行 |
| `agents/memory_manager.py` | `generate_reflection()` prompt 增加 risk 角色 | ~10 行 |
| `agents/memory_manager.py` | `_get_past_memories()` risk 角色反思提取 | ~5 行 |
| `agents/multi_agent_analyzer.py` | `analyze()` structured path 改用 `MemoryConditions` 构建检索条件 | ~8 行 |
| `agents/multi_agent_analyzer.py` | `analyze()` 返回 `_memory_conditions_snapshot` + `_ai_quality_score` | ~5 行 |
| `strategy/event_handlers.py` | `on_position_opened` 快照 `_entry_memory_conditions` + `_entry_ai_quality_score` | ~8 行 |
| `strategy/event_handlers.py` | `on_position_closed` 传快照到 `record_outcome` | ~5 行 |
| `strategy/ai_strategy.py` | `__init__` 初始化 `_entry_memory_conditions` + `_entry_ai_quality_score` | ~2 行 |
| `strategy/safety_manager.py` | `_clear_position_state()` 清除 `_entry_memory_conditions` + `_entry_ai_quality_score` (与 `latest_signal_data = None` 同级) | ~2 行 |

### 向后兼容
- 旧记忆 (无 `conditions_v2`) → 退回旧的 conditions 字符串 parse
- 旧记忆 (无 `ai_quality_score`) → quality_weight = 1.0 (不调节)
- 旧反思 (无 `risk` key) → fallback 到通用文本
- `trading_memory.json` 格式完全向后兼容，新字段是纯增量
- 快照模式与现有 `_entry_winning_side` 等完全一致，无新设计模式

---

## Phase 6: 废弃旧路径 + 清理

### 目标
删除不再需要的重复代码和废弃路径。v1.7 扩展：text fallback path 整体删除。

### 清理项

| 清理 | 文件 | 说明 |
|------|------|------|
| 删除 `_build_current_conditions_from_features()` | `multi_agent_analyzer.py` (line ~4651) | v28.0 structured path 的条件构建函数，被 `MemoryConditions.from_feature_dict()` 取代 |
| 删除 `_build_current_conditions()` | `memory_manager.py` (line ~90) | text fallback path 已删除，此函数无调用方 |
| 删除 `_compute_dimensional_scores()` | `report_formatter.py` (line ~623) | text fallback path 专用函数，structured path 用 `compute_scores_from_features()` |
| 删除 text fallback path | `multi_agent_analyzer.py` | `_use_structured = False` 分支下的全部 text-based debate 代码 (~400-600 行)。异常改为 fail-fast (跳过本周期) |
| 删除 `_format_entry_conditions()` | `memory_manager.py` | 旧 `conditions` string 格式化函数，被 `MemoryConditions.to_dict()` 取代 |
| 删除 4 次重复的 `compute_valid_tags()` 调用 | `multi_agent_analyzer.py` | 各 `_run_structured_*()` 中的独立调用 |
| 删除 4 次重复的 `compute_scores_from_features()` 调用 | `multi_agent_analyzer.py` | 同上 |
| 删除 4 次重复的 `compute_annotated_tags()` 调用 | `multi_agent_analyzer.py` | 同上 |

**实际调用关系** (已验证):
- `_build_current_conditions_from_features()` 在 `multi_agent_analyzer.py:4145` 被调用 (structured replay path)
- `_build_current_conditions()` 在 `multi_agent_analyzer.py:845` 被调用 (text fallback path)
- ⚠️ **两者输出 schema 不一致** (v1.6 R8 发现，v1.7 已通过删除两者解决):
  - `_build_current_conditions()`: key = `rsi`/`macd`(string)/`bb`(float) — **v1.7 删除**
  - `_build_current_conditions_from_features()`: key = `rsi`/`macd_bullish`(bool)/`bb_position`(float) — **v1.7 删除**
  - 统一替代: `MemoryConditions.from_feature_dict().to_dict()` → 新 key (`rsi_30m`/`macd_bullish`/`bb_position_30m`)

**v1.7 变更**: Text fallback path 已删除（见下方「奥卡姆剃刀合规声明」）。`_build_current_conditions()` 和 `_build_current_conditions_from_features()` 均删除，统一由 `MemoryConditions.from_feature_dict()` 取代。

**Replay path 同步** (`analyze_from_features()`, line ~4102):
- `_build_current_conditions_from_features()` (line 4145) → 替换为 `MemoryConditions.from_feature_dict(feature_dict).to_dict()`
- `compute_valid_tags()` / `compute_annotated_tags()` / `compute_scores_from_features()` (lines 4158-4217) → replay path 不使用 `AnalysisContext` (开发工具，不影响生产)，但重复调用仍应消除。改为在 `analyze_from_features()` 入口处一次计算，局部变量传递即可：
```python
# analyze_from_features() 入口:
_replay_valid_tags = compute_valid_tags(feature_dict)
_replay_tags_ref = compute_annotated_tags(feature_dict, _replay_valid_tags)
_replay_scores = ReportFormatterMixin.compute_scores_from_features(feature_dict)
# 各阶段读局部变量，不重新计算
```

---

## 奥卡姆剃刀合规声明 (v1.7 修订)

### 单一系统原则

v1.7 彻底执行奥卡姆剃刀：**每个功能只有一条路径，不保留 fallback、降级、过渡期双写**。

| 已删除 | 替代方案 | 说明 |
|--------|---------|------|
| Text fallback path (~400-600 行) | 无。`extract_features()` 失败 → 跳过本周期分析 (fail-fast) | CLAUDE.md: "这段代码当前是否被生产路径调用？否 → 删除" |
| `_compute_dimensional_scores()` | `compute_scores_from_features()` (via `ctx.scores`) | 只需 feature-based scores |
| `_build_current_conditions()` | `MemoryConditions.from_feature_dict()` | 只有一种 conditions 构建方式 |
| `_build_current_conditions_from_features()` | `MemoryConditions.from_feature_dict()` | 同上 |
| `conditions` 字段双写 | 只写 `conditions_v2` | 旧记忆中的 `conditions` 只读，自然淘汰 |
| `to_dict()` 双 key 输出 | 只输出新 key (`rsi_30m`/`macd_bullish`/...) | `_score_memory()` 直接读新 key |

### 旧记忆只读兼容 (自然淘汰)

旧记忆 (只有 `conditions` string，无 `conditions_v2`) 由 `_score_memory()` 旧 parse 逻辑**只读**处理。不写入新的旧格式数据。随 500 条滚动窗口自然淘汰 (~5 天)，淘汰完成后删除旧 parse 逻辑 (后续 cleanup PR)。

### Feature extraction 异常处理

Text fallback 删除后，`extract_features()` 异常处理改为 fail-fast：
```python
try:
    feature_dict = extract_features(...)
except Exception as e:
    self.logger.error(f"Feature extraction failed: {e}")
    # fail-fast: 跳过本周期，等下个 on_timer 重试
    return None  # 不降级到 text path
```
15 分钟后 `on_timer` 自动重试。比 text fallback 更安全——避免低质量降级路径产生错误交易信号。

### 已删除的无条件计算浪费

| 浪费 | 修复 | Phase |
|------|------|-------|
| `_compute_dimensional_scores()` 在 structured path 白算 | 删除该函数 (text path 一并删除) | P2 (R5) → P6 |
| `_build_current_conditions()` 在 structured path 白算 | 删除该函数 | P5e (R6) → P6 |

---

## SSoT 同步检查更新

Phase 1-6 涉及的 SSoT 变更需要在 `check_logic_sync.py` 注册：

| SSoT 文件 | 新增依赖方 |
|-----------|-----------|
| `agents/analysis_context.py` (新增) | `multi_agent_analyzer.py`, `ai_quality_auditor.py`, `memory_manager.py` |
| `agents/prompt_constants.py` | ~~REASON_TAGS 新增 INCONCLUSIVE~~ — 不需要 (INCONCLUSIVE 由代码注入) |

---

## 回滚计划

每个 Phase 独立可回滚：

| Phase | 回滚命令 | 清理 |
|-------|---------|------|
| Phase 1 | `git revert <hash>` | 无状态文件影响 |
| Phase 2 | `git revert <hash>` | 无状态文件影响 |
| Phase 3 | `git revert <hash>` | 无状态文件影响 |
| Phase 4 | `git revert <hash>` | 无状态文件影响 |
| Phase 5 | `git revert <hash>` | `trading_memory.json` 中新增的 `conditions_v2` 和 `ai_quality_score` 字段会被旧代码忽略（向后兼容） |
| Phase 6 | `git revert <hash>` | 恢复被删除的重复代码 |

---

## 验证计划

### 每个 Phase 完成后:
```bash
python3 scripts/smart_commit_analyzer.py    # 回归检测
python3 scripts/check_logic_sync.py         # SSoT 同步检查
python3 -c "from agents.analysis_context import AnalysisContext"  # 导入测试
```

### Phase 5 完成后额外验证:
```bash
# 验证旧记忆兼容性
python3 -c "
import json
with open('data/trading_memory.json') as f:
    memories = json.load(f)
# 验证旧记忆 (无 conditions_v2) 可以被新代码处理
from agents.memory_manager import MemoryManagerMixin
# 不应报错
print(f'Total memories: {len(memories)}, with conditions_v2: {sum(1 for m in memories if \"conditions_v2\" in m)}')
"
```

### 全流程验证 (development 环境):
```bash
python3 main_live.py --env development --dry-run
# 观察:
# 1. AnalysisContext 创建日志
# 2. 预计算只执行一次
# 3. confidence_chain 记录
# 4. quality_score 写入 context
```

### 单元测试计划 (v1.3 新增 — 修复 D8 测试缺失)

**新增文件**: `tests/test_analysis_context.py`

| 测试类 | 覆盖内容 | Phase |
|--------|---------|-------|
| `TestMemoryConditions` | `from_feature_dict()` 正确性：RSI/BB 范围、MACD 方向、sentiment 分类、direction 推导 (MACD lean → RSI fallback) | P1 |
| `TestMemoryConditions` | `to_dict()` 输出新 key (`rsi_30m`/`macd_bullish`(bool)/`bb_position_30m` + `adx_regime` 等) | P1 |
| `TestConfidenceChain` | append-only：add() 后 steps 长度递增，final/final_origin 返回最后一步 | P1 |
| `TestConfidenceChain` | `has_default()` 检测 DEFAULT/COERCED origin | P1 |
| `TestAnalysisContext` | `is_prepared()` 在 features+valid_tags 填充前后状态正确 | P1 |
| `TestPrecompute` | 预计算结果与直接调用 `compute_valid_tags()`/`compute_scores()` 一致 | P2 |
| `TestSafeFilterTags` | filter 清空所有 evidence 后自动填充 INCONCLUSIVE | P3 |
| `TestSafeFilterTags` | filter 保留部分 evidence 时不触发 INCONCLUSIVE | P3 |
| `TestMemoryBackcompat` | 旧记忆 (无 `conditions_v2`) 在 `_score_memory()` 中正常评分 | P5 |
| `TestMemoryBackcompat` | 旧记忆 (无 `ai_quality_score`) → quality_weight = 1.0 | P5 |
| `TestMemoryNewDimensions` | `conditions_v2` 存在时新增 5 维度的分数贡献 > 0 | P5 |
| `TestMemoryNewDimensions` | **BUG-1 回归**: `conditions_v2` 记忆的旧维度 (RSI/MACD/BB) 正确匹配，MACD bool→string 转换正确 | P5 |
| `TestMemoryNewDimensions` | **矛盾-1 回归**: 旧记忆补偿后分数与新记忆可比 (高质量旧记忆不被低质量新记忆排挤) | P5 |
| `TestMemoryNewDimensions` | `quality_weight` 阈值边界：39→0.3, 40→0.5, 59→0.5, 60→0.8, 79→0.8, 80→1.0 | P5 |
| `TestReflectionRisk` | `generate_reflection()` prompt 包含 risk 角色 (mock LLM) | P5 |
| `TestReflectionRisk` | `_extract_role_reflection(mem, 'risk')` 提取 risk key (新记忆) 和 fallback judge (旧记忆) | P5 |

---

## 预期改动统计

| Phase | 新增行数 | 修改行数 | 删除行数 | 文件数 |
|-------|---------|---------|---------|--------|
| Phase 1 | ~130 | ~30 | 0 | 2 |
| Phase 2 | 0 | ~65 | ~20 | 1 |
| Phase 3 | ~15 | ~50 | 0 | 1 |
| Phase 4 | 0 | ~45 | 0 | 1 |
| Phase 5 | ~30 | ~92 | 0 | 5 |
| Phase 6 | 0 | ~15 | ~40 | 2 |
| Tests | ~200 | 0 | 0 | 1 |
| **总计** | **~375** | **~297** | **~60** | **9 文件** |

---

## 解决的问题对照表

| # | 问题 | 解决 Phase | 解决方式 |
|---|------|-----------|---------|
| 1 | 三套平行数据表示 | P2+P4 | features/scores/tags 一次计算，auditor 读同一份 |
| 2 | valid_tags 计算 6 次 + scores 4~8 次 | P2 | 只在 context 上计算一次 (v1.3 审计确认: valid_tags ×6, scores ×4~8, annotated_tags ×5) |
| 3 | Auditor 用 Path A 验证 Path B | P4 | Auditor 改读 context.features |
| 4 | Score 与 Tag 阈值不一致 | P2 | 共享 context，消除独立转换 |
| 5 | Feature extraction 缺失导致静默降级 | P1 | `data_warnings: List[str]` 显式追踪 |
| 6 | Divergence 双重路径 | P2+P4 | Auditor 用 context.features 中的背离字段 |
| 7 | Agent 间无交叉验证 | P3 | confidence_chain 追踪 + 现有 `_schema_violations` dict |
| 8 | Dimensional Scores 无验证 | P2 | 在 context 上只算一次，类型由 dataclass 保证 |
| 9 | filter 后不重验证 | P3 | filter 后检查 evidence 空 → INCONCLUSIVE fallback |
| 10 | Text/Structured path 格式不一致 | P2+P6 | v1.7: text path 删除，只保留 structured path + context 统一 |
| 11 | 记忆 conditions 与 feature_dict 不兼容 | P5 | MemoryConditions.from_feature_dict() |
| 12 | 反思缺 Risk 角色 | P5 | reflection JSON 增加 risk key |
| 13 | Quality Score 与 Grade 隔离 | P5 | quality_weight 影响 grade_value 维度 |
| 14 | conditions 只存 4 维度 | P5 | conditions_v2 存 12 个维度 |
| 15 | 缺失 ADX/Extension/Vol | P5 | MemoryConditions 包含所有 v19+ 字段 |
| 16 | 低质量分析盈利被强化 | P5 | ai_quality_score 降权 grade_value |
| 17 | Risk 无专属反思 | P5 | generate_reflection 增加 risk 角色 |
| 18 | 两套 _build_current_conditions | P6 | 删除 `multi_agent_analyzer.py` 中的 `_build_current_conditions_from_features()`，structured path 改用 `MemoryConditions.from_feature_dict()` |
| 19 | Extended reflection 引用已删除记忆 | — | 不在本方案范围（低优先级） |
| 20 | Auditor 不知记忆影响 | — | 降级：context 已移除 `selected_memories` 字段 (无消费者)。如需 auditor 引用记忆，可在有具体需求时再加 |

---

## 全流程覆盖审查 (v1.1 新增)

### 已覆盖阶段

| 阶段 | 当前代码路径 | 方案改动 | 状态 |
|------|------------|---------|------|
| 数据聚合 | `AIDataAssembler.fetch_external_data()` → `analyze()` 参数 | `data_warnings` 追踪降级数据源 | ✅ |
| Feature 提取 | `extract_features()` → `feature_dict` | 存入 `ctx.features` 一次性计算 | ✅ |
| 预计算 | `compute_valid_tags()` / `compute_scores()` / `compute_annotated_tags()` ×6 | 统一为 `ctx` 一次计算 | ✅ |
| Bull/Bear 辩论 | `_run_structured_debate()` | 读 `ctx.valid_tags` / `ctx.scores` | ✅ |
| Judge 决策 | `_run_structured_judge()` | 读 `ctx`，记录 confidence_chain | ✅ |
| Entry Timing | `_run_structured_entry_timing()` | 读 `ctx`，记录 confidence 变更 | ✅ |
| Risk Manager | `_run_structured_risk()` | 读 `ctx`，记录 confidence 变更 | ✅ |
| Quality Audit | `_quality_auditor.audit()` | 读 `ctx.features` / `ctx.valid_tags` | ✅ |
| 开仓快照 | `on_position_opened()` | 快照 `_entry_memory_conditions` + `_entry_ai_quality_score` | ✅ |
| 平仓记录 | `on_position_closed()` → `record_outcome()` | 传 `conditions_v2` + `ai_quality_score` | ✅ |
| 记忆匹配 | `_score_memory()` | 新增 5 维度 + quality_weight | ✅ |
| 反思生成 | `generate_reflection()` | 新增 risk 角色 | ✅ |

### 已修复的遗漏 (v1.2)

| 遗漏 | 严重度 | 修复位置 | 修复方式 |
|------|--------|---------|---------|
| ~~1: replay path~~ | 低 | Phase 6 | `analyze_from_features()` 入口一次计算局部变量，`_build_current_conditions_from_features()` 替换为 `MemoryConditions.from_feature_dict().to_dict()` |
| ~~2: 两套 scores~~ | 低 | Phase 6 | v1.7: `_compute_dimensional_scores()` 删除，`ctx.scores` 是唯一 scores 来源 |
| ~~3: 快照时间差~~ | 低 | Phase 5a | v1.7: 只写 `conditions_v2` (feature_dict 快照)，旧 `conditions` 不再写入 |
| ~~4: 检索维度不匹配~~ | **中** | Phase 5e | `MemoryConditions.from_feature_dict().to_dict()` 只输出新 key，`_score_memory()` 直接读新 key |
