# 执行 + 基础设施 (Definitive)

> **Phase**: 2 (VWAP/TWAP + Optuna + Prometheus + Pandera), 3 (LangGraph + QuestDB + W&B + Feast)

---

## Phase 2A: VWAP/TWAP 智能执行

**替代**: 单一 LIMIT 订单
**删除**: 直接 LIMIT 提交逻辑

### 策略选择器

```python
# utils/execution_engine.py

class ExecutionEngine:
    """
    按订单金额自动选择执行策略:
    - <$1K: 单笔 LIMIT (当前行为, 无需优化)
    - $1K-$5K: TWAP (等时间拆分)
    - >$5K: VWAP + Iceberg (量加权 + 冰山)
    """

    def execute(self, signal: str, size_usdt: float, price: float) -> list:
        if size_usdt < 1000:
            return self._limit_order(signal, size_usdt, price)
        elif size_usdt < 5000:
            return self._twap(signal, size_usdt, price,
                             slices=4, interval_sec=120)
        else:
            return self._vwap_iceberg(signal, size_usdt, price,
                                      visible_pct=0.25)

    def _twap(self, signal, size, price, slices, interval_sec):
        """
        Time-Weighted: 等分为 N 份, 每 interval 秒下一单.
        超时 5 分钟未成交 → MARKET 收尾.
        """
        slice_size = size / slices
        orders = []
        for i in range(slices):
            orders.append({
                'type': 'LIMIT',
                'size': slice_size,
                'price': price,  # 实际需要小幅偏移
                'delay_sec': i * interval_sec,
                'timeout_sec': 300,
                'fallback': 'MARKET'
            })
        return orders

    def _vwap_iceberg(self, signal, size, price, visible_pct):
        """
        Volume-Weighted + Iceberg:
        - 根据近期成交量分布加权拆单
        - 每次只显示 25% 订单量
        - 降低市场冲击
        """
        visible = size * visible_pct
        hidden = size - visible
        return [{
            'type': 'ICEBERG',
            'total_size': size,
            'visible_size': visible,
            'price': price,
            'timeout_sec': 600,
            'fallback': 'MARKET'
        }]
```

---

## Phase 2B: Prometheus + Grafana 监控

**替代**: Telegram 心跳 + 日志
**删除**: Telegram 心跳中的监控指标 (保留心跳消息本身, 改为推 Prometheus metrics)

### Metrics 定义

```python
# utils/metrics.py

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Trading metrics
trades_total = Counter('algvex_trades_total', 'Total trades', ['signal', 'confidence'])
trade_pnl = Histogram('algvex_trade_pnl_pct', 'Trade PnL distribution',
                       buckets=[-5, -3, -2, -1, 0, 1, 2, 3, 5, 10])
position_size = Gauge('algvex_position_size_usdt', 'Current position size')
drawdown_pct = Gauge('algvex_drawdown_pct', 'Current drawdown')
equity = Gauge('algvex_equity_usdt', 'Portfolio equity')

# AI metrics
ai_latency = Histogram('algvex_ai_latency_sec', 'AI inference latency', ['agent'])
quality_score = Gauge('algvex_quality_score', 'AI quality score')
ic_rolling = Gauge('algvex_ic_rolling', 'Rolling Information Coefficient')

# Data metrics
data_freshness = Gauge('algvex_data_age_sec', 'Data source freshness', ['source'])
data_quality = Gauge('algvex_data_quality', 'Pandera validation score', ['source'])

# System metrics
api_errors = Counter('algvex_api_errors_total', 'API errors', ['service'])
regime = Gauge('algvex_regime', 'Current HMM regime', ['state'])

# Start metrics server
start_http_server(9090)
```

### Grafana Dashboards

| Dashboard | 核心面板 |
|-----------|---------|
| **Trading Overview** | Equity curve, DD, daily PnL, win rate (rolling 20) |
| **AI Quality** | Quality score, IC, direction accuracy, confidence calibration |
| **Data Pipeline** | Source freshness, validation pass rate, missing data |
| **System Health** | API latency, error rate, memory usage |

---

## Phase 2C: Optuna Walk-Forward 参数优化

**替代**: 手动回测调参
**删除**: 手动参数调优流程

```python
# scripts/optimize_params.py

import optuna

def objective(trial):
    """
    搜索空间: SL multiplier, TP target, trailing params
    目标: Calmar Ratio (年化 return / max DD)
    """
    sl_high = trial.suggest_float('sl_atr_high', 0.5, 1.5)
    sl_med = trial.suggest_float('sl_atr_med', 0.7, 2.0)
    tp_target = trial.suggest_float('tp_rr', 1.2, 2.5)
    trailing_mult = trial.suggest_float('trailing_mult', 0.3, 1.0)
    trailing_activation = trial.suggest_float('trailing_activation_r', 1.0, 2.0)

    # Run backtest with these params
    result = run_backtest(
        sl_atr={'HIGH': sl_high, 'MEDIUM': sl_med},
        tp_rr_target=tp_target,
        trailing_multiplier=trailing_mult,
        trailing_activation_r=trailing_activation,
    )

    # Pruning: 早停表现差的 trial
    if result['max_dd'] > 20:
        raise optuna.exceptions.TrialPruned()

    return result['calmar']

# Walk-Forward: 21 天训练, 7 天测试, 7 天滚动
study = optuna.create_study(
    direction='maximize',
    sampler=optuna.samplers.TPESampler(seed=42),
    pruner=optuna.pruners.HyperbandPruner()
)
study.optimize(objective, n_trials=200, timeout=3600)

# 验收: OOS mean_calmar > 5 AND std < 50% AND min > 0
```

**执行频率**: 每周 cron, 结果需**人工审核**后才部署
**审核标准**: OOS Calmar > 5, 连续 4 周稳定, 无极端偏差

---

## Phase 3A: LangGraph Agent 编排

**替代**: 手写 `multi_agent_analyzer.py` (4,946 行)
**删除**: 该文件 (被 LangGraph 状态图替代)

```python
# agents/trading_graph.py

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

class TradingState(TypedDict):
    feature_dict: dict
    scores: dict
    memory: list
    reflection: str
    bull_r1: dict | None
    bear_r1: dict | None
    bull_r2: dict | None
    bear_r2: dict | None
    judge: dict | None
    entry_timing: dict | None
    risk: dict | None
    final_signal: str | None

def build_trading_graph():
    graph = StateGraph(TradingState)

    # Nodes
    graph.add_node('bull_r1', run_bull_r1)
    graph.add_node('bear_r1', run_bear_r1)
    graph.add_node('bull_r2', run_bull_r2)
    graph.add_node('bear_r2', run_bear_r2)
    graph.add_node('judge', run_judge)
    graph.add_node('entry_timing', run_entry_timing)
    graph.add_node('risk_manager', run_risk)

    # Edges
    graph.set_entry_point('bull_r1')
    graph.add_edge('bull_r1', 'bear_r1')
    graph.add_edge('bear_r1', 'bull_r2')
    graph.add_edge('bull_r2', 'bear_r2')
    graph.add_edge('bear_r2', 'judge')

    # Conditional: LONG/SHORT → ET, else → END
    graph.add_conditional_edges('judge', should_run_et,
        {'yes': 'entry_timing', 'no': END})
    graph.add_conditional_edges('entry_timing', should_run_risk,
        {'yes': 'risk_manager', 'no': END})
    graph.add_edge('risk_manager', END)

    # Checkpoint: SQLite (crash recovery)
    checkpointer = SqliteSaver.from_conn_string('data/langgraph_checkpoint.db')
    return graph.compile(checkpointer=checkpointer)
```

**每个 node 超时**: 60s (DeepSeek 正常 5-15s, 超时 → retry 1 次 → fail)
**Crash recovery**: SQLite checkpoint, 重启后从最后完成的 node 继续

---

## Phase 3B: QuestDB 时序存储

**替代**: JSON 文件存储
**删除**: `trading_memory.json` 读写逻辑, `layer_orders.json` 读写逻辑

```python
# utils/questdb_store.py

import questdb.ingress as qi

class QuestDBStore:
    """
    QuestDB: 11.4M rows/sec, 列式存储, 零关系开销.
    """
    _HOST = 'localhost'
    _PORT = 9009  # ILP (InfluxDB Line Protocol)

    def store_trade(self, trade: dict):
        with qi.Sender(self._HOST, self._PORT) as sender:
            sender.row(
                'trading_memory',
                symbols={'signal': trade['signal'], 'confidence': trade['confidence'],
                         'grade': trade['grade']},
                columns={
                    'entry_price': trade['entry_price'],
                    'exit_price': trade['exit_price'],
                    'pnl_pct': trade['pnl_pct'],
                    'realized_rr': trade.get('realized_rr', 0),
                    'quality_score': trade.get('quality_score', 0),
                },
                at=datetime.fromisoformat(trade['timestamp'])
            )
            sender.flush()

    def query(self, sql: str) -> list:
        """REST API query"""
        import requests
        r = requests.get(f'http://{self._HOST}:9000/exec', params={'query': sql})
        return r.json()['dataset']
```

---

## Phase 3C: Weights & Biases 实验追踪

```python
# scripts/optimize_prompts.py (集成 W&B)

import wandb

wandb.init(project='algvex-trading', config={
    'dspy_trials': 100,
    'sl_multiplier': {'HIGH': 0.8, 'MEDIUM': 1.0},
    'tp_rr_target': 1.5,
})

# 每次优化 trial 记录
wandb.log({
    'direction_accuracy': 0.63,
    'ic_4h': 0.11,
    'sharpe': 1.8,
    'calmar': 5.2,
})
```

---

## Phase 3D: Feast Feature Store

```python
# utils/feature_store.py

from feast import FeatureStore

store = FeatureStore(repo_path='feature_repo/')

# 定义 feature view
# offline: QuestDB (historical features)
# online: Redis (<1ms serving for real-time inference)

# 获取实时 features
features = store.get_online_features(
    features=['trading_features:rsi_14_4h', 'trading_features:adx_1d'],
    entity_rows=[{'symbol': 'BTCUSDT'}]
).to_dict()
```

---

## 完整依赖

```
# Phase 2
pip install prometheus-client>=0.21 optuna>=4.0

# Phase 3
pip install langgraph>=1.0 questdb>=2.0 wandb>=0.18 feast[redis]>=0.40
```

---

## 部署顺序

```
Phase 2 (并行):
  ├── VWAP/TWAP (order_execution.py 重写)
  ├── Prometheus + Grafana (metrics.py 新增)
  ├── Optuna (scripts/optimize_params.py 新增)
  └── Pandera (data_validator.py 新增)

Phase 3 (顺序):
  1. QuestDB (存储层先行, 迁移 JSON → QuestDB)
  2. LangGraph (编排层, 依赖 QuestDB checkpoint)
  3. W&B (实验追踪, 依赖 Optuna 产出)
  4. Feast + Redis (feature store, 依赖 QuestDB 作为 offline store)
  5. SGLang (推理层, 依赖 LangGraph 编排)
  6. FinRL (RL 层, 依赖 Feast 特征)
  7. LoRA (微调, 依赖 500+ 交易数据)
```
