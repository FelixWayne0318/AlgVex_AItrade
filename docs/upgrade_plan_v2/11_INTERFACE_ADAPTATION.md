# 11 — 界面层适配 (Telegram + Web)

> **Phase**: 跟随 Phase 1-3 | **依赖**: 02 (HMM), 05 (Qdrant), 07 (Kelly/VaR), 08 (Prometheus)
> **核心原则**: 复用现有双频道架构 (v14.0) 和 Web 三层架构 (FastAPI + Next.js + SQLite)。新功能 = 新命令/端点/组件，不重构现有界面。

---

## 现有界面架构

### Telegram 双频道 (v14.0)

```
控制机器人 (私聊)                    通知频道 (订阅者)
  ├─ 心跳监控 (20min/次)              ├─ 开仓信号
  ├─ 错误/告警                        ├─ 平仓结果
  ├─ 命令响应                         ├─ 加仓/减仓
  └─ 运维信息                         ├─ 日报/周报
                                      └─ broadcast=True
```

- **查询命令** (14 个): /status, /position, /balance, /analyze, /orders, /history, /risk, /daily, /weekly, /config, /version, /logs, /profit, /layer3
- **控制命令** (10+ 个, 需 PIN): /pause, /resume, /close, /force_analysis, /partial_close, /set_leverage, /toggle, /set, /restart, /calibrate, /modify_sl, /modify_tp, /reload_config

### Web 后端 (FastAPI)

- **公开 API**: 14 端点 (性能、信号、评估、质量、系统状态)
- **管理 API**: 34+ 端点 (配置、服务控制、Telegram、安全事件)
- **WebSocket**: 6 流 (ticker 1s, account 5s, positions 3s)

### Web 前端 (Next.js 14)

- **页面**: 8 个 (index, dashboard, performance, chart, quality, admin, about, copy)
- **组件**: 35 个 (admin 11, charts 4, trading 6, evaluation 5, layout 2, ui 7)

---

## Phase 1: Telegram 新命令

### 新增查询命令

| 命令 | 回调 | 数据来源 | 显示内容 |
|------|------|---------|---------|
| `/regime` | `_cmd_regime_status` | HMM regime detector | 当前 regime + 概率分布 + 24h 转换历史 |
| `/baseline` | `_cmd_baseline` | `data/baseline_v44.json` | 10 个基线 KPI vs 当前 rolling KPI |
| `/memory [N]` | `_cmd_query_memory` | Qdrant 语义检索 | Top-N 相似历史交易 + 结局 |

### `/regime` 命令实现

```python
# strategy/telegram_commands.py
async def _cmd_regime_status(self, update, context):
    regime = getattr(self, '_current_hmm_regime', None)
    if not regime:
        msg = "⚠️ HMM Regime 检测未初始化"
    else:
        probs = getattr(self, '_hmm_regime_probs', {})
        transitions = getattr(self, '_hmm_transition_count_24h', 0)
        msg = (
            f"🤖 Regime 状态\n"
            f"━━━━━━━━━━━━━━\n"
            f"当前: {regime} ({probs.get(regime, 0):.0%} 置信度)\n"
            f"概率分布:\n"
        )
        for state, prob in sorted(probs.items(), key=lambda x: -x[1]):
            bar = '█' * int(prob * 20)
            msg += f"  {state}: {prob:.1%} {bar}\n"
        msg += f"24h 转换次数: {transitions}\n"

    await self.telegram_bot.send_message_sync(msg)
```

### `/memory` 命令实现

```python
# strategy/telegram_commands.py
async def _cmd_query_memory(self, update, context, n=5):
    if not hasattr(self, '_qdrant_client') or not self._qdrant_client:
        msg = "⚠️ Qdrant 记忆系统未初始化"
    else:
        # 用当前市场状态查询相似历史
        current_text = self._format_current_market_for_embedding()
        results = await self._qdrant_client.search_similar(current_text, top_k=n)
        if not results:
            msg = "📭 未找到相似历史交易"
        else:
            msg = f"🧠 相似历史 (Top-{len(results)})\n━━━━━━━━━━━━━━\n"
            wins = sum(1 for r in results if r.get('pnl_pct', 0) > 0)
            msg += f"相似环境胜率: {wins}/{len(results)} ({wins/len(results):.0%})\n\n"
            for i, r in enumerate(results, 1):
                pnl = r.get('pnl_pct', 0)
                grade = r.get('grade', '?')
                signal = r.get('signal', '?')
                similarity = r.get('score', 0)
                emoji = '✅' if pnl > 0 else '❌'
                msg += f"{i}. {emoji} {signal} | {pnl:+.2f}% | {grade} | 相似度 {similarity:.0%}\n"

    await self.telegram_bot.send_message_sync(msg)
```

### `/baseline` 命令实现

```python
# strategy/telegram_commands.py
async def _cmd_baseline(self, update, context):
    import json
    baseline_path = 'data/baseline_v44.json'
    try:
        with open(baseline_path) as f:
            baseline = json.load(f)
    except FileNotFoundError:
        await self.telegram_bot.send_message_sync("⚠️ 基线文件不存在，请先运行 Phase 0")
        return

    msg = "📊 基线对比 (v44.0 → 当前)\n━━━━━━━━━━━━━━━━━━━━\n"
    # 从 quality_analysis 获取当前 rolling 指标
    current = self._get_current_rolling_kpis()
    for kpi in ['direction_accuracy', 'avg_rr', 'sharpe', 'max_dd', 'win_rate']:
        v44 = baseline.get(kpi, '?')
        curr = current.get(kpi, '?')
        if isinstance(v44, (int, float)) and isinstance(curr, (int, float)):
            delta = curr - v44
            arrow = '↑' if delta > 0 else '↓' if delta < 0 else '→'
            msg += f"{kpi}: {v44:.2f} → {curr:.2f} ({arrow}{abs(delta):.2f})\n"
        else:
            msg += f"{kpi}: {v44} → {curr}\n"

    await self.telegram_bot.send_message_sync(msg)
```

### 命令注册

```python
# utils/telegram_command_handler.py — QUERY_COMMANDS 新增
QUERY_COMMANDS = {
    # ... 现有 14 个 ...
    'regime': 'regime_status',     # Phase 1
    'baseline': 'baseline',        # Phase 0
}

QUERY_COMMANDS_WITH_ARGS = {
    # ... 现有 ...
    'memory': ('query_memory', lambda args: int(args[0]) if args else 5),  # Phase 1
}
```

### 心跳数据扩展

```python
# utils/telegram_bot.py — format_heartbeat_message() 新增段落

# Phase 1: HMM Regime
if heartbeat_data.get('hmm_regime'):
    regime = heartbeat_data['hmm_regime']
    regime_conf = heartbeat_data.get('hmm_regime_confidence', 0)
    msg += f"\n🤖 Regime: {regime} ({regime_conf:.0%})"

# Phase 1: Qdrant 相似度 (如果最近一次查询有结果)
if heartbeat_data.get('similar_win_rate') is not None:
    msg += f"\n🧠 相似环境胜率: {heartbeat_data['similar_win_rate']:.0%}"

# Phase 2: Kelly 仓位
if heartbeat_data.get('kelly_fraction') is not None:
    msg += f"\n💰 Kelly: {heartbeat_data['kelly_fraction']:.1%} 仓位"
```

---

## Phase 2: Telegram + Prometheus 共存

### Telegram 心跳 ≠ Prometheus

**不删除 Telegram 心跳**。两者职责不同:

| 维度 | Telegram 心跳 | Prometheus + Grafana |
|------|-------------|---------------------|
| 受众 | 交易者 (手机) | 运维/开发 (桌面) |
| 频率 | 20min | 实时 (15s scrape) |
| 内容 | 决策摘要 + 仓位状态 | 时序指标 + 告警规则 |
| 用途 | "当前在做什么" | "历史趋势 + 异常检测" |

**方案**: Telegram 心跳保持不变。Prometheus 是**新增**的运维层，不替代用户端通知。

### Prometheus 指标导出

```python
# utils/prometheus_exporter.py (新增)
from prometheus_client import Counter, Gauge, Histogram, generate_latest

# Trading metrics
TRADES_TOTAL = Counter('algvex_trades_total', 'Total trades', ['signal', 'confidence'])
TRADE_PNL = Histogram('algvex_trade_pnl_pct', 'Trade PnL %', buckets=[-5, -2, -1, 0, 1, 2, 5, 10])
POSITION_SIZE = Gauge('algvex_position_size_pct', 'Current position size %')
DRAWDOWN = Gauge('algvex_drawdown_pct', 'Current drawdown %')
EQUITY = Gauge('algvex_equity_usdt', 'Portfolio equity USDT')

# AI metrics
AI_LATENCY = Histogram('algvex_ai_latency_seconds', 'AI decision latency', ['phase'])
QUALITY_SCORE = Gauge('algvex_quality_score', 'AI quality score (0-100)')
IC_ROLLING = Gauge('algvex_ic_rolling_4h', 'Rolling 4H Information Coefficient')

# Data metrics
DATA_FRESHNESS = Gauge('algvex_data_age_seconds', 'Data source age', ['source'])
DATA_QUALITY = Gauge('algvex_data_quality_pass', 'Data validation pass rate', ['source'])

# System metrics
API_ERRORS = Counter('algvex_api_errors_total', 'API errors', ['source', 'error_code'])
REGIME_STATE = Gauge('algvex_regime_state', 'HMM regime', ['state'])

def get_metrics_text() -> str:
    return generate_latest().decode('utf-8')
```

### ai_strategy.py 指标注入点

```python
# ai_strategy.py — on_timer() 中添加
import time

# 在 AI 分析前后
start = time.monotonic()
result = await self._multi_agent_analyzer.analyze(...)
AI_LATENCY.labels(phase='full_pipeline').observe(time.monotonic() - start)

# 在交易执行后
TRADES_TOTAL.labels(signal=signal, confidence=confidence).inc()
TRADE_PNL.observe(pnl_pct)

# 在每个 on_timer 周期
EQUITY.set(equity_usdt)
DRAWDOWN.set(drawdown_pct)
QUALITY_SCORE.set(quality_score)
```

---

## Phase 2: Web 新端点 + 新页面

### 新增 API 端点

| Phase | 路由 | 方法 | 认证 | 数据来源 |
|-------|------|------|------|---------|
| 0 | `/api/public/baseline/summary` | GET | ❌ | `data/baseline_v44.json` |
| 1 | `/api/public/regime/current` | GET | ❌ | HMM detector 内存状态 |
| 1 | `/api/admin/regime/history` | GET | ✅ | `data/hmm_states.json` |
| 1 | `/api/admin/memory/search` | POST | ✅ | Qdrant 语义检索 |
| 1 | `/api/admin/memory/stats` | GET | ✅ | Qdrant collection 统计 |
| 2 | `/api/public/kelly/current` | GET | ❌ | Kelly sizer 内存状态 |
| 2 | `/api/admin/risk/var-cvar` | GET | ✅ | VaR/CVaR 计算结果 |
| 2 | `/api/admin/metrics/prometheus` | GET | ✅ | Prometheus text format |
| 2 | `/api/admin/optuna/trials` | GET | ✅ | Optuna 历史 trials |

### 新增 Web 页面

#### `web/frontend/pages/regime.tsx` (Phase 1)

| 组件 | 内容 | API 调用 |
|------|------|---------|
| RegimeStatus | 当前 regime + 概率分布 (饼图) | `/api/public/regime/current` |
| RegimeHistory | 24h/7d regime 转换时间线 | `/api/admin/regime/history` |
| RegimePerformance | 每个 regime 的 win rate (柱图) | `/api/public/quality-analysis/summary` |

#### `web/frontend/pages/risk.tsx` (Phase 2)

| 组件 | 内容 | API 调用 |
|------|------|---------|
| KellyGauge | 当前 Kelly 分数 + 仓位大小 (仪表盘) | `/api/public/kelly/current` |
| VaRDisplay | VaR 95% + CVaR 尾部风险 | `/api/admin/risk/var-cvar` |
| CircuitBreakerStatus | 熔断器状态 + regime-adaptive 阈值 | `/api/admin/risk/var-cvar` |

### 后端 Service 新增

```python
# web/backend/services/regime_service.py (Phase 1)
class RegimeService:
    def get_current_regime(self) -> dict:
        """Read HMM state from strategy's shared state file."""
        path = 'data/hmm_states.json'
        # ...

    def get_regime_history(self, hours: int = 24) -> list:
        """Read regime transition log."""
        # ...
```

```python
# web/backend/services/kelly_service.py (Phase 2)
class KellyService:
    def get_current_kelly(self) -> dict:
        """Read Kelly fraction from strategy's shared state."""
        # ...

    def get_var_cvar(self) -> dict:
        """Calculate VaR/CVaR from trading_memory.json."""
        # ...
```

---

## Phase 3: Grafana 嵌入

### 嵌入 vs 独立

**选择: Grafana 独立部署 + Web 页面链接**

原因:
1. Grafana 自带丰富的可视化 (无需在 Next.js 中重写)
2. 团队可以直接访问 Grafana (不需要 Web 登录)
3. 嵌入 iframe 会增加 CORS/auth 复杂度

```python
# web/frontend/pages/dashboard.tsx — 新增 Grafana 链接
<a href="http://139.180.157.152:3000/d/algvex/trading"
   target="_blank" rel="noopener noreferrer">
  📈 Grafana 实时仪表盘
</a>
```

### Grafana Dashboard 定义

| Dashboard | Panels | 数据源 |
|-----------|--------|--------|
| Trading Overview | Equity curve, DD, daily PnL, win rate (rolling 20) | Prometheus |
| AI Quality | Quality score, IC, direction accuracy, confidence cal | Prometheus |
| Data Pipeline | Source freshness, validation pass, missing data | Prometheus |
| System Health | API latency, error rate, memory | Prometheus |
| Regime Monitor | HMM state timeline, transition frequency, regime PnL | Prometheus |

---

## i18n 扩展

### `web/frontend/lib/i18n.ts` 新增翻译

```typescript
// Phase 1
regime: { en: 'Regime', zh: 'Regime 状态' },
regime_trending_up: { en: 'Trending Up', zh: '上升趋势' },
regime_trending_down: { en: 'Trending Down', zh: '下降趋势' },
regime_ranging: { en: 'Ranging', zh: '震荡' },
regime_high_volatility: { en: 'High Volatility', zh: '高波动' },
similar_trades: { en: 'Similar Trades', zh: '相似交易' },
similarity: { en: 'Similarity', zh: '相似度' },
baseline: { en: 'Baseline', zh: '基线' },

// Phase 2
kelly_fraction: { en: 'Kelly Fraction', zh: 'Kelly 分数' },
var_95: { en: 'VaR 95%', zh: 'VaR 95%' },
cvar: { en: 'CVaR', zh: 'CVaR (尾部风险)' },
circuit_breaker: { en: 'Circuit Breaker', zh: '风险熔断器' },
```

---

## 通知频道消息格式扩展

### 开仓信号 (broadcast=True) 新增

```
📊 AlgVex 交易信号

方向: 开多 (LONG)
信心: HIGH
价格: $67,234.50
━━━━━━━━━━━━━━
🤖 Regime: TRENDING_UP (92%)     ← Phase 1 新增
🧠 相似环境: 8/10 盈利 (80%)    ← Phase 1 新增
💰 Kelly: 65% 仓位               ← Phase 2 新增
━━━━━━━━━━━━━━
SL: $66,100.00 (-1.69%)
TP: $69,600.00 (+3.52%)
R/R: 2.08:1
```

---

## 验收标准

### Phase 1 界面验收

- [ ] `/regime` 命令正确显示 HMM 状态 + 概率分布
- [ ] `/memory` 命令返回 Top-N 相似交易 + 胜率统计
- [ ] `/baseline` 命令对比 v44.0 基线 vs 当前 KPI
- [ ] 心跳消息包含 regime 状态行
- [ ] Web `/api/public/regime/current` 返回正确 JSON
- [ ] `regime.tsx` 页面渲染 regime 状态 + 历史 + 表现

### Phase 2 界面验收

- [ ] Prometheus `/metrics` 端点返回正确的 text format
- [ ] Grafana 5 个 dashboard 数据正常
- [ ] 心跳消息包含 Kelly 仓位行
- [ ] Web `risk.tsx` 页面渲染 Kelly + VaR/CVaR
- [ ] 开仓信号通知包含 regime + Kelly 信息

### Phase 3 界面验收

- [ ] Grafana 链接在 Web dashboard 中可用
- [ ] 所有新增 Telegram 命令在 `/menu` 快捷菜单中
- [ ] i18n 覆盖所有新增文本 (EN + ZH)
