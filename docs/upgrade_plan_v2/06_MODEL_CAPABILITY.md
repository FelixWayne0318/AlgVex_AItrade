# 环节 5 — 模型能力 (Definitive)

> **路径**: Phase 1 Ensemble Veto → Phase 3 SGLang 自托管 + LoRA 微调
> **无备选, 无 fallback**: 每个 Phase 只有一个实现

---

## Phase 1: Ensemble Veto (Claude Sonnet 交叉验证)

### 设计

在 Judge 输出 LONG/SHORT 后, 用 Claude Sonnet 4.6 做独立交叉验证。
不替代 DeepSeek — 是**额外验证层**。

```python
# agents/ensemble_veto.py

import anthropic

class EnsembleVeto:
    """
    Claude Sonnet 独立评估 Judge 决策.
    输出: aligned_score ∈ [-1, +1]
      +1 = 完全同意
      -1 = 完全反对
    """
    _ALIGNED_THRESHOLD = -0.4     # < -0.4 → HOLD (强否决)
    _DOWNGRADE_THRESHOLD = 0.0    # < 0.0 → confidence 降一级

    def __init__(self, api_key: str):
        self._client = anthropic.Anthropic(api_key=api_key)

    def evaluate(self, judge_signal: str, judge_confidence: str,
                 feature_dict: dict, scores: dict) -> dict:
        """
        返回:
        {
            'aligned_score': 0.6,
            'action': 'PASS',          # PASS / DOWNGRADE / VETO
            'reasoning': '...',
            'adjusted_confidence': 'MEDIUM'
        }
        """
        prompt = self._build_prompt(judge_signal, feature_dict, scores)

        response = self._client.messages.create(
            model='claude-sonnet-4-6-20250514',
            max_tokens=500,
            temperature=0.2,
            messages=[{'role': 'user', 'content': prompt}]
        )

        score = self._parse_score(response.content[0].text)

        if score < self._ALIGNED_THRESHOLD:
            return {'aligned_score': score, 'action': 'VETO',
                    'adjusted_confidence': 'HOLD'}
        elif score < self._DOWNGRADE_THRESHOLD:
            downgraded = self._downgrade(judge_confidence)
            return {'aligned_score': score, 'action': 'DOWNGRADE',
                    'adjusted_confidence': downgraded}
        else:
            return {'aligned_score': score, 'action': 'PASS',
                    'adjusted_confidence': judge_confidence}

    def _build_prompt(self, signal, features, scores) -> str:
        return f"""You are a senior crypto trading analyst.
A trading system proposes: {signal}

Market data summary:
- Trend score: {scores.get('trend', 'N/A')}
- Momentum score: {scores.get('momentum', 'N/A')}
- Order flow score: {scores.get('order_flow', 'N/A')}
- Risk environment: {scores.get('risk_env', 'N/A')}
- Net assessment: {scores.get('net', 'N/A')}

Rate your agreement with this {signal} decision on a scale of -1 (strongly disagree) to +1 (strongly agree).
Output format: SCORE: X.X
REASONING: <brief>"""
```

**成本**: ~$15-20/月 (每 20 分钟 1 次, 每次 ~500 input + 200 output tokens)
**延迟**: +1-2s (可接受, 在 on_timer 内)

---

## Phase 3: SGLang 自托管 + LoRA 微调

### SGLang 约束解码

```python
# agents/sglang_client.py

import sglang as sgl

class SGLangClient:
    """
    自托管 DeepSeek-V3, token 级 JSON schema 约束.
    Compressed FSM: 2.5× throughput vs vLLM.
    """

    def __init__(self, model_path: str):
        self._runtime = sgl.Runtime(
            model_path=model_path,
            tp_size=2,                    # tensor parallel (2× GPU)
            mem_fraction_static=0.85,
        )

    def call_with_schema(self, system: str, user: str,
                         json_schema: dict) -> dict:
        """
        Token 级约束: 解码时强制匹配 JSON schema.
        不需要 retry — 输出保证合规.
        """

        @sgl.function
        def generate(s):
            s += sgl.system(system)
            s += sgl.user(user)
            s += sgl.assistant(sgl.gen('output', regex=self._schema_to_regex(json_schema)))

        state = generate.run(temperature=0.3)
        return json.loads(state['output'])
```

**硬件**: 2× A100 80GB 或 4× A6000 48GB
**优势**: 零 API 成本, token 级约束 (不需要 Instructor retry), 2.5× throughput

### LoRA 微调

```python
# scripts/finetune_trading_model.py

from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTTrainer

# LoRA 配置 (参数高效, 消费级 GPU 可训练)
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=['q_proj', 'v_proj', 'k_proj', 'o_proj'],
    task_type='CAUSAL_LM'
)

# 基础模型
base_model = AutoModelForCausalLM.from_pretrained(
    'deepseek-ai/DeepSeek-V3',
    load_in_4bit=True,          # QLoRA: 4-bit quantization
    device_map='auto'
)
model = get_peft_model(base_model, lora_config)

# 训练数据: TradingGroup 式 data-synthesis
# 1. A+/A grade 交易 → 正例 (保持原 signal)
# 2. D/F grade 交易 → 纠错例 (signal → HOLD)
# 3. 每条包含: feature_dict + scores + 正确输出
def build_finetune_data(memory: list) -> list:
    data = []
    for trade in memory:
        snapshot = load_snapshot(trade['timestamp'])
        if not snapshot:
            continue

        if trade['grade'] in ('A+', 'A', 'B'):
            # 正例: 保持原始 signal
            data.append({
                'input': format_input(snapshot),
                'output': format_correct_output(trade)
            })
        elif trade['grade'] in ('D', 'F'):
            # 纠错例: 将 signal 修正为 HOLD
            data.append({
                'input': format_input(snapshot),
                'output': format_hold_output(trade)
            })
    return data

# 训练
trainer = SFTTrainer(
    model=model,
    train_dataset=train_data,
    max_seq_length=4096,
    num_train_epochs=3,
    learning_rate=2e-4,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
)
trainer.train()
model.save_pretrained('data/models/deepseek-trading-lora')
```

**训练数据需求**: ≥500 条交易 (含 feature snapshots)
**训练时间**: ~2-4 小时 (单 A100)
**验证**: test set Sharpe 和 IC 必须优于 base model + DSPy

---

## 部署路径

```
Phase 1: DeepSeek API + Instructor + Ensemble Veto (Claude)
  ↓ (Phase 3, 有 500+ 交易数据后)
Phase 3: SGLang 自托管 DeepSeek + LoRA adapter + 约束解码
  └─ Instructor 删除 (SGLang 约束解码原生替代)
  └─ DeepSeek API 删除 (自托管替代)
  └─ Ensemble Veto 保留 (作为独立验证层)
```

---

## 依赖

```
# Phase 1
pip install anthropic>=0.40

# Phase 3
pip install sglang>=0.4 peft>=0.14 trl>=0.12 bitsandbytes>=0.44
```
