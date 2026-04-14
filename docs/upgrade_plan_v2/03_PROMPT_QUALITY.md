# 环节 2 — Prompt 质量: DSPy MIPROv2 (Definitive)

> **Phase**: 1 | **前置**: Phase 0 基线 + trading_memory ≥300 条
> **替代**: 手写 prompt | **删除**: 5 个 Agent 的手写 system prompt 模板
> **预期**: direction_accuracy +5-15%, IC ≥+0.05

---

## 1. 为什么 DSPy 是唯一选择

| 维度 | DSPy | 手写 Prompt |
|------|------|-----------|
| 优化方法 | MIPROv2 Bayesian + 自动 few-shot | 人工直觉 |
| 目标函数 | 可定义 (胜率/R/R/IC) | 无 |
| 可复现 | ✅ (deterministic seed) | ❌ |
| 模型迁移 | 重新优化即可 | 全部重写 |
| 样本效率 | ~300 条 | — |

**核心价值**: prompt engineering 从**艺术**变为**工程**。

---

## 2. Module 定义

```python
# agents/dspy_modules.py

import dspy

class BullAnalystModule(dspy.Module):
    def __init__(self):
        self.analyst = dspy.ChainOfThought(
            "feature_dict, scores, memory, reflection -> "
            "conviction: float, evidence: list[str], risk_flags: list[str], reasoning: str"
        )

    def forward(self, feature_dict, scores, memory, reflection):
        return self.analyst(
            feature_dict=feature_dict, scores=scores,
            memory=memory, reflection=reflection
        )

class BearAnalystModule(dspy.Module):
    def __init__(self):
        self.analyst = dspy.ChainOfThought(
            "feature_dict, scores, memory, reflection -> "
            "conviction: float, evidence: list[str], risk_flags: list[str], reasoning: str"
        )

    def forward(self, feature_dict, scores, memory, reflection):
        return self.analyst(
            feature_dict=feature_dict, scores=scores,
            memory=memory, reflection=reflection
        )

class JudgeModule(dspy.Module):
    def __init__(self):
        self.judge = dspy.ChainOfThought(
            "bull_output, bear_output, feature_dict, scores, memory -> "
            "signal: str, confidence: str, decisive_reasons: list[str], reasoning: str"
        )

    def forward(self, bull_output, bear_output, feature_dict, scores, memory):
        return self.judge(
            bull_output=bull_output, bear_output=bear_output,
            feature_dict=feature_dict, scores=scores, memory=memory
        )

class EntryTimingModule(dspy.Module):
    def __init__(self):
        self.evaluator = dspy.ChainOfThought(
            "judge_output, feature_dict, scores -> "
            "verdict: str, adjusted_confidence: str, dimensions: dict"
        )

    def forward(self, judge_output, feature_dict, scores):
        return self.evaluator(
            judge_output=judge_output, feature_dict=feature_dict, scores=scores
        )

class RiskManagerModule(dspy.Module):
    def __init__(self):
        self.risk = dspy.ChainOfThought(
            "judge_output, entry_timing_output, feature_dict, memory -> "
            "risk_appetite: str, size_pct: int, reasoning: str"
        )

    def forward(self, judge_output, entry_timing_output, feature_dict, memory):
        return self.risk(
            judge_output=judge_output, entry_timing_output=entry_timing_output,
            feature_dict=feature_dict, memory=memory
        )
```

### Pipeline

```python
class TradingDebatePipeline(dspy.Module):
    """完整 5-agent 辩论 pipeline"""

    def __init__(self):
        self.bull = BullAnalystModule()
        self.bear = BearAnalystModule()
        self.judge = JudgeModule()
        self.entry_timing = EntryTimingModule()
        self.risk_manager = RiskManagerModule()

    def forward(self, feature_dict, scores, memory, reflection):
        bull_r1 = self.bull(feature_dict=feature_dict, scores=scores,
                           memory=memory, reflection=reflection)
        bear_r1 = self.bear(feature_dict=feature_dict, scores=scores,
                           memory=memory, reflection=reflection)

        bull_r2 = self.bull(feature_dict=feature_dict, scores=scores,
                           memory=memory,
                           reflection=f"{reflection}\nOpponent R1: {bear_r1}")
        bear_r2 = self.bear(feature_dict=feature_dict, scores=scores,
                           memory=memory,
                           reflection=f"{reflection}\nOpponent R1: {bull_r1}")

        judge_out = self.judge(bull_output=bull_r2, bear_output=bear_r2,
                              feature_dict=feature_dict, scores=scores, memory=memory)

        if judge_out.signal in ('LONG', 'SHORT'):
            et_out = self.entry_timing(judge_output=judge_out,
                                       feature_dict=feature_dict, scores=scores)
            rm_out = self.risk_manager(judge_output=judge_out,
                                       entry_timing_output=et_out,
                                       feature_dict=feature_dict, memory=memory)
        else:
            et_out, rm_out = None, None

        return dspy.Prediction(
            signal=judge_out.signal, confidence=judge_out.confidence,
            entry_timing=et_out, risk=rm_out
        )
```

---

## 3. 训练数据

```python
# scripts/build_dspy_dataset.py

def build_dataset(memory_path, snapshot_dir) -> list[dspy.Example]:
    """
    每条: feature_snapshot (输入) + 交易结果 (label)

    方向 label: price change >+0.3% = BULLISH, <-0.3% = BEARISH, else = NEUTRAL
    窗口: 4H (匹配决策层)
    """
    examples = []
    for trade in memory:
        snapshot = load_snapshot(trade['timestamp'], snapshot_dir)
        if snapshot is None:
            continue

        pct = (trade['exit_price'] - trade['entry_price']) / trade['entry_price']
        direction = 'BULLISH' if pct > 0.003 else 'BEARISH' if pct < -0.003 else 'NEUTRAL'

        examples.append(dspy.Example(
            feature_dict=snapshot['features'],
            scores=snapshot['scores'],
            memory=snapshot.get('memory_context', ''),
            reflection=snapshot.get('reflection', ''),
            actual_direction=direction,
            actual_rr=trade.get('realized_rr', 0),
            grade=trade.get('grade', 'C'),
        ).with_inputs('feature_dict', 'scores', 'memory', 'reflection'))
    return examples
```

**划分**: 60% train / 20% dev / 20% test (按时间排序, test = 最近 20%)

---

## 4. 优化目标函数

```python
def trading_metric(example, prediction, trace=None) -> float:
    """
    4 维加权: direction(40%) + rr(30%) + grade(20%) + calibration(10%)
    """
    score = 0.0

    # Direction accuracy (40%)
    pred_dir = 'BULLISH' if prediction.signal == 'LONG' else \
               'BEARISH' if prediction.signal == 'SHORT' else 'NEUTRAL'
    if pred_dir == example.actual_direction:
        score += 0.4

    # R/R quality (30%)
    if example.actual_rr >= 1.5: score += 0.3
    elif example.actual_rr >= 1.0: score += 0.2
    elif example.actual_rr >= 0: score += 0.1

    # Grade quality (20%)
    grade_map = {'A+': 0.2, 'A': 0.16, 'B': 0.12, 'C': 0.08, 'D': 0.04, 'F': 0}
    score += grade_map.get(example.grade, 0)

    # Calibration (10%)
    conf_wr = {'HIGH': 0.7, 'MEDIUM': 0.55, 'LOW': 0.45}
    expected = conf_wr.get(prediction.confidence, 0.5)
    actual = 1.0 if example.actual_rr > 0 else 0.0
    score += 0.1 * max(0, 1.0 - abs(expected - actual))

    return score
```

---

## 5. 优化执行

```python
from dspy.teleprompt import MIPROv2

optimizer = MIPROv2(
    metric=trading_metric,
    num_candidates=30,
    init_temperature=1.2,
    verbose=True
)

optimized = optimizer.compile(
    TradingDebatePipeline(),
    trainset=train_examples,
    num_trials=100,
    max_bootstrapped_demos=5,
    max_labeled_demos=3,
)

optimized.save('data/dspy_optimized/trading_pipeline.json')
```

---

## 6. 部署集成

```python
# agents/multi_agent_analyzer.py

class MultiAgentAnalyzer:
    def __init__(self):
        self._pipeline = TradingDebatePipeline()
        self._pipeline.load('data/dspy_optimized/trading_pipeline.json')

    def analyze(self, context: AnalysisContext) -> dict:
        result = self._pipeline(
            feature_dict=context.feature_dict,
            scores=context.scores,
            memory=context.memory_context,
            reflection=context.reflection
        )
        return {
            'signal': result.signal,
            'confidence': result.confidence,
            'entry_timing': result.entry_timing,
            'risk': result.risk,
        }
```

**删除**: 手写 system prompt 模板, `_build_*_prompt()` 函数, `_run_structured_debate()` 手写调用逻辑
**验收**: IC ≥+0.05 OR direction_accuracy ≥+5%

---

## 7. 依赖

```
pip install dspy-ai>=2.5
```
