# 环节 1 — 数据质量 (Data Quality)

> **覆盖 Phase**: 1 (REST 加固 + HMM + Fear&Greed), 2 (Glassnode + FinBERT + Pandera), 3 (CoinGlass + Santiment)
> **目标**: 6 数据源 → 15 数据源, HMM 替代 ADX, Pandera 保证数据质量, REST Client 统一加固

---

## 0. REST API Client 统一加固 (Phase 1 — 前置项)

**背景**: 系统审计发现 6 个数据采集客户端 (2,458 行) 存在 3 类工程质量问题，但 upgrade_plan_v2 未覆盖。这些客户端是**数据管线的第一环** — 获取失败直接导致 AI 分析缺数据，后面的 Pandera/HMM 再强也无法补救。

### 6 个客户端现状

| 文件 | 行数 | HTTP 库 | 重试逻辑 | 错误处理 | 核心问题 |
|------|------|---------|----------|----------|---------|
| `binance_kline_client.py` | 243 | `requests` | ❌ 无 | ⚠️ 基础 | broad `except Exception`，无 retry |
| `binance_account.py` | 820 | `urllib`(!) | ✅ 有 (-1021) | ✅ 健壮 | HTTP 库与其他客户端不一致 |
| `binance_derivatives_client.py` | 464 | `requests` | ❌ 无 | ⚠️ 基础 | generic Exception suppression |
| `binance_orderbook_client.py` | 218 | `requests` | ✅ 有 (429) | ✅ 好 | 唯一有 rate limit 处理 |
| `sentiment_client.py` | 216 | `requests` | ❌ 无 | ⚠️ 差 | 用 `print()` 而非 logger |
| `coinalyze_client.py` | 497 | `requests` | ❌ 无 | ⚠️ 基础 | 无 retry，无 rate limit |

### 为什么不用 ccxt / python-binance 替换？

| 候选 | 结论 | 原因 |
|------|------|------|
| ccxt | ❌ 过度工程 | 我们只用 Binance + Coinalyze，ccxt 100+ 交易所抽象是浪费 |
| python-binance | ❌ 部分适用 | 只覆盖 Binance，不覆盖 Coinalyze；且已安装但未使用 |
| **requests + tenacity** | ✅ 最佳 | 最小改动，统一重试策略，不改 API 接口 |

### 设计: 共享重试装饰器

```python
# utils/http_retry.py (~40 行)

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests
import logging

logger = logging.getLogger(__name__)

# Shared retry decorator for all REST clients
api_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    )),
    before_sleep=lambda retry_state: logger.warning(
        f"API retry {retry_state.attempt_number}/3: {retry_state.outcome.exception()}"
    ),
)

DEFAULT_TIMEOUT = 10  # seconds
```

### 变更清单 (~200 行改动)

| 文件 | 改动 | 行数 |
|------|------|------|
| `utils/http_retry.py` | **新增**: 共享重试装饰器 | +40 |
| `binance_kline_client.py` | 加 `@api_retry`，统一 timeout | ~15 |
| `binance_account.py` | `urllib` → `requests`，加 `@api_retry` | ~50 |
| `binance_derivatives_client.py` | 加 `@api_retry`，统一 timeout | ~15 |
| `binance_orderbook_client.py` | 已有 retry，统一用 `@api_retry` 简化 | ~20 |
| `sentiment_client.py` | `print()` → `logger`，加 `@api_retry` | ~30 |
| `coinalyze_client.py` | 加 `@api_retry`，统一 timeout | ~15 |
| `requirements.txt` | 新增 `tenacity>=9.0.0` | +1 |

### 验收标准

- 6 个客户端全部使用 `requests` (删除 `urllib`)
- 6 个客户端全部使用 `@api_retry` 装饰器
- 0 个 `print()` 语句 (全部用 `logger`)
- `check_logic_sync.py` 新增: HTTP 库一致性检查

### 为什么放在 Phase 1 前置？

1. **零风险**: 只加重试+统一错误处理，不改 API 接口和返回值
2. **为 Phase 2 铺路**: Glassnode/FinBERT/CoinGlass/Santiment 4 个新数据源直接复用 `@api_retry`
3. **为 Pandera 铺路**: Pandera 验证的前提是数据能获取到 — 重试机制减少 NaN 输入

### 依赖

```
pip install tenacity>=9.0.0
```

---

## 1. HMM 4-State Regime Detection (Phase 1)

**替代**: ADX 二分法 (TRENDING/RANGING)
**删除**: `market_regime` ADX 分支逻辑, `compute_scores_from_features()` 中 ADX 20/40 阶梯权重

### 设计

```python
# utils/regime_detector.py

from hmmlearn.hmm import GaussianHMM
import numpy as np

class RegimeDetector:
    """
    4 states: TRENDING_UP / TRENDING_DOWN / RANGING / HIGH_VOLATILITY
    输出概率分布 (非二分), 2-cycle hysteresis 防抖
    """
    _N_STATES = 4
    _RETRAIN_INTERVAL_DAYS = 7
    _LOOKBACK_DAYS = 60           # 60 天覆盖多 regime 转换 (30 天不足)
    _HYSTERESIS_CYCLES = 2

    def __init__(self):
        self._model = GaussianHMM(
            n_components=self._N_STATES,
            covariance_type='full',
            n_iter=200,
            random_state=42
        )
        self._current_regime = None
        self._regime_counter = 0

    def fit(self, features: np.ndarray):
        """
        features shape: (T, 5)
        列: [log_return, atr_pct, adx, volume_ratio, rsi_normalized]
        """
        self._model.fit(features)
        self._label_states()

    def predict(self, features: np.ndarray) -> dict:
        """
        返回:
        {
            'regime': 'TRENDING_UP',
            'probabilities': {'TRENDING_UP': 0.65, 'TRENDING_DOWN': 0.15,
                              'RANGING': 0.12, 'HIGH_VOLATILITY': 0.08},
            'confidence': 0.65,
            'transition_risk': 0.35
        }
        """
        probs = self._model.predict_proba(features)
        latest = probs[-1]
        candidate = self._state_names[np.argmax(latest)]

        if candidate != self._current_regime:
            self._regime_counter += 1
            if self._regime_counter >= self._HYSTERESIS_CYCLES:
                self._current_regime = candidate
                self._regime_counter = 0
        else:
            self._regime_counter = 0

        return {
            'regime': self._current_regime,
            'probabilities': dict(zip(self._state_names, latest.tolist())),
            'confidence': float(max(latest)),
            'transition_risk': float(1.0 - max(latest))
        }

    def retrain_check(self, last_train_date) -> bool:
        return (datetime.now() - last_train_date).days >= self._RETRAIN_INTERVAL_DAYS
```

### Retrain 监控

- **触发**: 每 7 天 cron 或 on_timer 检查
- **失败处理**: 保持最近成功 model (不降级到 ADX)
- **drift 检测**: log-likelihood < 前一次 90% → 告警 + 强制 retrain

### 下游消费

| 消费方 | 字段 | 用途 |
|--------|------|------|
| `compute_scores_from_features()` | regime, probabilities | trend 加权 |
| `calculate_position_size()` | regime, confidence | Kelly × regime_mult |
| `risk_controller.py` | regime | Regime-adaptive DD thresholds |
| All 5 Agents | probabilities | 概率分布作为 context |
| Telegram 心跳 | regime, confidence | 状态显示 |

---

## 2. Fear & Greed Index (Phase 1)

**来源**: alternative.me API (免费, 每日更新)

```python
# utils/fear_greed_client.py

class FearGreedClient:
    _URL = 'https://api.alternative.me/fng/?limit=1'

    async def fetch(self) -> dict:
        """返回 {'value': 25, 'classification': 'Extreme Fear'}"""
```

**注入**: `extract_features()` → `fear_greed_index: int` (0-100)
**评分**: <20 或 >80 → risk_env +1 (极端情绪 = 风险信号)
**Tags**: `EXTREME_FEAR`, `EXTREME_GREED`

---

## 3. Glassnode On-Chain Analytics (Phase 2)

**来源**: Glassnode API (7,500+ metrics, 900+ endpoints)
**核心 5 指标**:

| 指标 | Endpoint | 信号 |
|------|----------|------|
| MVRV Z-Score | `/v1/metrics/market/mvrv_z_score` | >7 极度高估, <0 极度低估 |
| SOPR | `/v1/metrics/indicators/sopr` | >1 获利卖出, <1 亏损卖出 |
| Exchange Netflow | `/v1/metrics/transactions/transfers_volume_exchanges_net` | >0 抛压, <0 积累 |
| aSOPR | `/v1/metrics/indicators/sopr_adjusted` | 排除 1-hop 的 SOPR |
| NVT Signal | `/v1/metrics/indicators/nvt` | >150 高估, <50 低估 |

```python
# utils/glassnode_client.py

class GlassnodeClient:
    _BASE_URL = 'https://api.glassnode.com'

    async def fetch_all(self) -> dict:
        """并行获取 5 指标, 单个失败不阻断"""
        endpoints = {
            'mvrv_z': '/v1/metrics/market/mvrv_z_score',
            'sopr': '/v1/metrics/indicators/sopr',
            'exchange_netflow': '/v1/metrics/transactions/transfers_volume_exchanges_net',
            'asopr': '/v1/metrics/indicators/sopr_adjusted',
            'nvt_signal': '/v1/metrics/indicators/nvt',
        }
        results = await asyncio.gather(*[
            self._fetch(ep) for ep in endpoints.values()
        ], return_exceptions=True)
        return self._to_feature_dict(endpoints.keys(), results)
```

**评分维度**: 新增 `onchain` (从 5 维扩展到 6 维)
**Tags**: `ONCHAIN_OVERVALUED`, `ONCHAIN_UNDERVALUED`, `EXCHANGE_INFLOW`, `EXCHANGE_OUTFLOW`

---

## 4. FinBERT-BiLSTM Sentiment NLP (Phase 2)

**模型**: ProsusAI/finbert (110M params, CPU ~50ms/title)
**输入**: CryptoPanic API 新闻标题 (免费 tier, 200 req/day)

```python
# utils/sentiment_nlp.py

from transformers import AutoTokenizer, AutoModelForSequenceClassification

class CryptoSentimentAnalyzer:
    _MODEL = 'ProsusAI/finbert'

    def analyze(self, headlines: list[str]) -> dict:
        """
        返回:
        {
            'sentiment_score': 0.35,     # -1.0 to +1.0
            'negative_ratio': 0.25,      # 负面占比 (风险信号)
            'headline_count': 20,
            'top_negative': '...',
            'top_positive': '...'
        }
        """
        inputs = self._tokenizer(headlines, return_tensors='pt',
                                  padding=True, truncation=True, max_length=128)
        with torch.no_grad():
            logits = self._model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)
            scores = probs[:, 0] - probs[:, 1]  # positive - negative
        return self._aggregate(scores, headlines)
```

**Tags**: `NEWS_BULLISH`, `NEWS_BEARISH`, `NEWS_EXTREME_FEAR`

---

## 5. Data Validation — Pandera (Phase 2)

**替代**: 手写 data quality gate
**删除**: `ai_data_assembler.py` 中手写验证逻辑

```python
# utils/data_validator.py

import pandera as pa
from pandera import Column, Check

technical_schema = pa.DataFrameSchema({
    'rsi_14': Column(float, Check.in_range(0, 100)),
    'atr_14': Column(float, Check.greater_than(0)),
    'adx_14': Column(float, Check.in_range(0, 100)),
    'sma_200': Column(float, Check.greater_than(0)),
    'bb_width': Column(float, Check.greater_than(0)),
})

sentiment_schema = pa.DataFrameSchema({
    'long_ratio': Column(float, Check.in_range(0, 1)),
    'short_ratio': Column(float, Check.in_range(0, 1)),
})

onchain_schema = pa.DataFrameSchema({
    'mvrv_z': Column(float, Check.in_range(-5, 15)),
    'sopr': Column(float, Check.in_range(0.5, 2.0)),
    'nvt_signal': Column(float, Check.greater_than(0)),
})
```

---

## 6. CoinGlass + Santiment (Phase 3)

### CoinGlass v4

| 指标 | 用途 |
|------|------|
| 清算热力图 | 大额清算聚集价位 → S/R 参考 |
| 多交易所 OI | 比单一 Binance 更全面 |
| 加权 FR | 多交易所加权 Funding Rate |

### Santiment

| 指标 | 用途 |
|------|------|
| Social Volume | 讨论量突增 → 情绪极端 |
| Whale Transactions (>$100K) | 大户异动 → 方向先行 |
| Dev Activity | 长期基本面 |

---

## 7. 完整数据源列表 (v2.0)

| # | 数据源 | Phase | 必需 | 类型 |
|---|--------|-------|------|------|
| 1 | Technical (30M/4H/1D) | 现有 | ✅ | 技术指标 |
| 2 | Sentiment (Binance L/S) | 现有 | ✅ | 情绪 |
| 3 | Price (Binance ticker) | 现有 | ✅ | 价格 |
| 4 | Order Flow (klines) | 现有 | | 订单流 |
| 5 | Derivatives (Coinalyze) | 现有 | | 衍生品 |
| 6 | Top Traders (Binance) | 现有 | | 衍生品 |
| 7 | Orderbook (depth) | 现有 | | 订单簿 |
| 8 | Account Context | 现有 | ✅ | 账户 |
| 9 | S/R Zones | 现有 | | 结构 |
| 10 | Fear & Greed | Phase 1 | | 宏观情绪 |
| 11 | HMM Regime | Phase 1 | ✅ | Regime |
| 12 | Glassnode (MVRV/SOPR/NVT) | Phase 2 | | 链上 |
| 13 | FinBERT NLP | Phase 2 | | NLP 情绪 |
| 14 | CoinGlass (清算/OI) | Phase 3 | | 衍生品 |
| 15 | Santiment (Social/Whale) | Phase 3 | | 社交 |

---

## 8. 依赖

```
pip install hmmlearn>=0.3 transformers>=4.40 pandera>=0.20
```
