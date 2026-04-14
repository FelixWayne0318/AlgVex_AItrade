# 环节 3 — 输出约束: Instructor Pydantic (Definitive)

> **Phase**: 1 | **前置**: 无 (独立)
> **替代**: `_validate_agent_output()` (~200 行) | **删除**: 该函数全部代码
> **保留**: AIQualityAuditor (语义审计层)

---

## 1. 为什么 Instructor 是唯一选择

| 维度 | Instructor | 手写 validation |
|------|-----------|----------------|
| Schema | Pydantic (Python 原生) | 自定义 dict 检查 |
| 自动重试 | ✅ (3 次, 带 error context) | 需手写 |
| Provider | 15+ (DeepSeek/Claude/GPT) | 仅 DeepSeek |
| 类型安全 | mypy 兼容 | ❌ |
| 月下载量 | 3M+ | — |

**Guardrails AI 不需要**: Instructor Pydantic + AIQualityAuditor 已完全覆盖。第三层只增加复杂度。

---

## 2. Schema 定义

```python
# agents/output_schemas.py

from pydantic import BaseModel, Field, field_validator
from typing import Literal

class DebateOutput(BaseModel):
    """Bull/Bear Agent 输出"""
    conviction: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1, max_length=8)
    risk_flags: list[str] = Field(default_factory=list, max_length=5)
    reasoning: str = Field(min_length=50)

    @field_validator('evidence')
    @classmethod
    def validate_tags(cls, v):
        from agents.prompt_constants import BULLISH_EVIDENCE_TAGS, BEARISH_EVIDENCE_TAGS
        valid = BULLISH_EVIDENCE_TAGS | BEARISH_EVIDENCE_TAGS
        for tag in v:
            if tag not in valid:
                raise ValueError(f"Invalid tag: {tag}")
        return v


class JudgeOutput(BaseModel):
    """Judge 决策输出"""
    signal: Literal['LONG', 'SHORT', 'HOLD', 'CLOSE']
    confidence: Literal['HIGH', 'MEDIUM', 'LOW']
    decisive_reasons: list[str] = Field(min_length=1, max_length=5)
    reasoning: str = Field(min_length=100)

    @field_validator('decisive_reasons')
    @classmethod
    def validate_decisive_tags(cls, v):
        from agents.prompt_constants import BULLISH_EVIDENCE_TAGS, BEARISH_EVIDENCE_TAGS
        valid = BULLISH_EVIDENCE_TAGS | BEARISH_EVIDENCE_TAGS
        for tag in v:
            if tag not in valid:
                raise ValueError(f"Invalid tag: {tag}")
        return v


class DimensionScores(BaseModel):
    mtf: Literal['STRONG', 'FAIR', 'WEAK']
    timing: Literal['STRONG', 'FAIR', 'WEAK']
    counter_trend: Literal['STRONG', 'FAIR', 'WEAK']
    extension: Literal['STRONG', 'FAIR', 'WEAK']

class EntryTimingOutput(BaseModel):
    """Entry Timing Agent 输出"""
    verdict: Literal['ENTER', 'REJECT']
    adjusted_confidence: Literal['HIGH', 'MEDIUM', 'LOW']
    dimensions: DimensionScores
    reasoning: str = Field(min_length=50)


class RiskManagerOutput(BaseModel):
    """Risk Manager 输出"""
    risk_appetite: Literal['AGGRESSIVE', 'NORMAL', 'CONSERVATIVE']
    size_pct: int = Field(ge=10, le=100)
    reasoning: str = Field(min_length=50)
```

---

## 3. Instructor 集成

```python
# agents/llm_client.py

import instructor
from openai import OpenAI

class LLMClient:
    def __init__(self, config):
        base_client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url='https://api.deepseek.com'
        )
        self._client = instructor.from_openai(base_client, mode=instructor.Mode.JSON)

    def call(self, response_model: type[BaseModel], system_prompt: str,
             user_prompt: str, temperature: float = 0.3, max_retries: int = 3) -> BaseModel:
        """
        调用 LLM, 强制返回 Pydantic model.
        失败 3 次后抛出 InstructorRetryException.
        """
        return self._client.chat.completions.create(
            model='deepseek-chat',
            response_model=response_model,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            temperature=temperature,
            max_retries=max_retries,
        )
```

---

## 4. 两层验证架构

```
LLM 输出
  ↓
Layer 1: Instructor (结构验证)
  ├─ 类型 (float, str, Literal)
  ├─ 范围 (ge=0, le=1, min_length)
  ├─ Enum (REASON_TAGS 白名单)
  ├─ 自动重试 (3 次, 含 error context)
  └─ 输出: Pydantic model 实例
  ↓
Layer 2: AIQualityAuditor (语义验证, 保留)
  ├─ Citation 准确性
  ├─ 跨 TF 归属
  ├─ 逻辑一致性
  ├─ 数据覆盖率
  ├─ SIGNAL_CONFIDENCE_MATRIX 合规
  └─ 输出: quality_score (0-100)
```

**删除**:
- `_validate_agent_output()` 全部 (~200 行)
- `_raw_{key}` 保全逻辑 (Instructor 不截断)
- 手写 JSON parse + retry

**保留**:
- AIQualityAuditor (6 维 + 5 逻辑一致性)
- `filter_output_tags()`

---

## 5. 依赖

```
pip install instructor>=1.7
```
