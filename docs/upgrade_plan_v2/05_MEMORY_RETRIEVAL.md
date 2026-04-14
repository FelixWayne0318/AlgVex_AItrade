# 环节 4 — 记忆检索: Qdrant 语义向量 (Definitive)

> **Phase**: 1 | **前置**: 无 (独立)
> **替代**: JSON 手写评分 O(N) | **删除**: `_get_past_memories()` 手写评分逻辑

---

## 1. 为什么 Qdrant 是唯一选择

| 维度 | Qdrant | JSON 手写评分 |
|------|--------|-------------|
| 搜索复杂度 | O(log N) HNSW | O(N) 线性扫描 |
| 语义理解 | ✅ (向量相似度) | ❌ (关键词匹配) |
| 性能 | Rust 实现, sub-ms | Python, 随 N 线性增长 |
| 过滤 | 内置 payload filter | 手写 if/else |
| 部署 | 本地文件 (无需 server) | JSON 文件 |

---

## 2. Embedding 模型

```python
# all-MiniLM-L6-v2: 22M params, 384-dim, ~5ms/text
# 选择理由: 参数最小 + 推理最快 + 质量足够 (交易 context 较短)
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
```

---

## 3. Feature → Text 映射

```python
# agents/memory_manager.py

def _features_to_text(self, features: dict) -> str:
    """
    将 124 个 typed features 转为自然语言描述, 用于 embedding.
    分 6 个维度组织 (匹配 compute_scores 维度):
    """
    parts = []

    # Trend dimension
    if features.get('adx_direction_1d'):
        parts.append(f"1D trend: {features['adx_direction_1d']}, "
                     f"ADX={features.get('adx_1d', 'N/A')}")
    if features.get('sma200_position_1d'):
        parts.append(f"Price vs SMA200: {features['sma200_position_1d']}")

    # Momentum dimension
    if features.get('rsi_14_4h') is not None:
        parts.append(f"4H RSI={features['rsi_14_4h']:.1f}")
    if features.get('macd_histogram_4h_trend'):
        parts.append(f"4H MACD histogram: {features['macd_histogram_4h_trend']}")
    if features.get('rsi_14_30m') is not None:
        parts.append(f"30M RSI={features['rsi_14_30m']:.1f}")

    # Order flow dimension
    if features.get('cvd_trend_30m'):
        parts.append(f"30M CVD trend: {features['cvd_trend_30m']}")
    if features.get('cvd_price_cross_30m'):
        parts.append(f"30M CVD-Price: {features['cvd_price_cross_30m']}")
    if features.get('taker_buy_ratio_30m') is not None:
        parts.append(f"Taker buy ratio: {features['taker_buy_ratio_30m']:.3f}")

    # Vol/extension risk
    if features.get('extension_regime_4h'):
        parts.append(f"4H extension: {features['extension_regime_4h']}")
    if features.get('volatility_regime_4h'):
        parts.append(f"4H volatility: {features['volatility_regime_4h']}")

    # Risk environment
    if features.get('funding_rate') is not None:
        parts.append(f"Funding rate: {features['funding_rate']:.5f}")
    if features.get('fear_greed_index') is not None:
        parts.append(f"Fear & Greed: {features['fear_greed_index']}")

    # Market structure
    if features.get('nearest_support_dist_pct') is not None:
        parts.append(f"Support dist: {features['nearest_support_dist_pct']:.2f}%")
    if features.get('nearest_resistance_dist_pct') is not None:
        parts.append(f"Resistance dist: {features['nearest_resistance_dist_pct']:.2f}%")

    return '. '.join(parts)
```

**设计决策**: 不嵌入全部 124 features (大部分是 enum/boolean, 不适合 text embedding)。选取 ~15 个最具区分度的 numeric/categorical features, 覆盖 6 个评分维度。

---

## 4. Qdrant 集成

```python
# agents/memory_manager.py

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, Range

class MemoryManager:
    _COLLECTION = 'trading_memories'
    _DIM = 384
    _MAX_DAYS = 90
    _TOP_K = 10

    def __init__(self, data_dir: str):
        self._client = QdrantClient(path=f"{data_dir}/qdrant_db")
        self._embedder = SentenceTransformer('all-MiniLM-L6-v2')
        self._ensure_collection()

    def _ensure_collection(self):
        collections = [c.name for c in self._client.get_collections().collections]
        if self._COLLECTION not in collections:
            self._client.create_collection(
                collection_name=self._COLLECTION,
                vectors_config=VectorParams(size=self._DIM, distance=Distance.COSINE)
            )

    def store(self, trade: dict, features: dict):
        """平仓后存储交易记忆 + 向量"""
        text = self._features_to_text(features)
        vector = self._embedder.encode(text).tolist()

        self._client.upsert(
            collection_name=self._COLLECTION,
            points=[PointStruct(
                id=hash(trade['timestamp']),
                vector=vector,
                payload={
                    'timestamp': trade['timestamp'],
                    'signal': trade['signal'],
                    'confidence': trade['confidence'],
                    'grade': trade['grade'],
                    'pnl_pct': trade['pnl_pct'],
                    'realized_rr': trade.get('realized_rr', 0),
                    'reflection': trade.get('reflection', ''),
                    'features_text': text,
                }
            )]
        )

    def retrieve(self, current_features: dict) -> list[dict]:
        """
        Hybrid 检索:
        - 5 条语义相似 (类似市场环境下的历史交易)
        - 3 条最高 grade (最佳实践)
        - 2 条最低 grade (教训)
        = 10 条记忆, 去重后返回
        """
        text = self._features_to_text(current_features)
        vector = self._embedder.encode(text).tolist()
        cutoff = (datetime.now() - timedelta(days=self._MAX_DAYS)).isoformat()

        time_filter = Filter(must=[
            FieldCondition(key='timestamp', range=Range(gte=cutoff))
        ])

        # Similar memories
        similar = self._client.search(
            collection_name=self._COLLECTION,
            query_vector=vector,
            query_filter=time_filter,
            limit=5
        )

        # Best grades
        best = self._client.scroll(
            collection_name=self._COLLECTION,
            scroll_filter=time_filter,
            limit=3,
            order_by='pnl_pct',  # descending
        )

        # Worst grades
        worst = self._client.scroll(
            collection_name=self._COLLECTION,
            scroll_filter=time_filter,
            limit=2,
            order_by='pnl_pct',  # ascending
        )

        return self._dedupe_and_format(similar, best, worst)
```

---

## 5. 迁移: 现有 trading_memory.json → Qdrant

```python
# scripts/migrate_memory_to_qdrant.py

def migrate():
    """一次性迁移, 将现有 JSON 记忆导入 Qdrant"""
    memory = json.load(open('data/trading_memory.json'))
    manager = MemoryManager('data')

    migrated = 0
    for trade in memory:
        # 尝试加载对应 feature snapshot
        snapshot = load_snapshot(trade.get('timestamp'), 'data/feature_snapshots')
        features = snapshot['features'] if snapshot else {}

        manager.store(trade, features)
        migrated += 1

    print(f"Migrated {migrated}/{len(memory)} trades to Qdrant")
```

**迁移后删除**: `_get_past_memories()` 手写评分逻辑, `_calculate_memory_score()` 函数

---

## 6. 依赖

```
pip install qdrant-client>=1.12 sentence-transformers>=3.0
```
