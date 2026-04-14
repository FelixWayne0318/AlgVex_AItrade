# 10 — 安全层连续性保障

> **Phase**: 贯穿 Phase 0-3 | **依赖**: 07 (VaR/CVaR), 08 (LangGraph)
> **核心原则**: 安全层是经过 v6.1-v43.0 三十余次迭代的战斗检验代码。**最小化改动**，只在数据输入端适配新组件。

---

## 现状: 四道防线

```
防线 1: AI Risk Manager (agents/)
  └─ 否决权: R/R<1.3 / FR>0.1% / 流动性枯竭 → HOLD

防线 2: 代码硬保护 (strategy/)
  ├─ calculate_mechanical_sltp() → 构造性保证 R/R ≥ 1.3:1
  ├─ 清算缓冲 <5% → 阻止加仓
  ├─ min_notional 检查 → 防止极小仓位
  └─ FR exhaustion / ET exhaustion → 打破死循环

防线 3: 风险熔断器 (utils/risk_controller.py)
  ├─ Drawdown: REDUCE@10% → HALT@15%
  ├─ Daily Loss: HALT@3%
  ├─ Consecutive Losses: REDUCED@2 → COOLDOWN@3+
  └─ Volatility: HALT if ATR > 3× baseline

防线 4: 紧急保护 (strategy/safety_manager.py)
  ├─ Emergency SL: SL 提交失败 → 市价 reduce_only
  ├─ Emergency Market Close: 3 次重试 + _needs_emergency_review
  ├─ 30s one-shot 重试 (v18.0)
  ├─ 孤立订单检测 + 时间窗口/layer 匹配 guard (v36.3)
  ├─ Ghost position 双确认 + 强制清除 (v18.2/v24.1)
  └─ TP 恢复: 2 次重试 + Tier-2 启动恢复 + on_timer 周期检查 (v36.3-v36.4)
```

### 组件行数

| 文件 | 行数 | 核心职责 | 修改风险 |
|------|------|---------|---------|
| `safety_manager.py` | 1,064 | Emergency SL/TP、Ghost/Orphan、Tier-2 恢复 | **极高** |
| `event_handlers.py` | 2,073 | 订单/仓位事件回调、层级清理 | **极高** |
| `position_manager.py` | 1,792 | 层级管理、加仓/减仓、时间屏障 | **高** |
| `risk_controller.py` | 591 | 熔断器状态机 | **高** |
| `trading_logic.py` | 1,371 | SL/TP 计算、评估 (SSoT) | **高** |

**合计**: 6,891 行生命安全代码

---

## 升级原则: 输入端适配，内核不动

### 不改动的核心逻辑

| 逻辑 | 所在文件 | 原因 |
|------|---------|------|
| `_submit_emergency_sl()` | safety_manager.py | 最后一道防线，零容忍改动 |
| `_emergency_market_close()` | safety_manager.py | 同上 |
| `_cleanup_orphaned_orders()` 双重 guard | safety_manager.py | 时间窗口 + layer 匹配，v36.3 验证 |
| Ghost position 双确认 | event_handlers.py | 2 周期延迟防 API 抖动 |
| `on_order_filled()` 4-way close reason | event_handlers.py | TRAILING/STOP/TP/OTHER，v42.1 验证 |
| `_layer_orders` + `_order_to_layer` 数据结构 | position_manager.py | v7.2 每层独立 SL/TP，核心架构 |
| LIFO 减仓逻辑 | position_manager.py | 风险管理基础 |
| `_create_layer()` + 持久化 | position_manager.py | layer 生命周期根基 |
| `calculate_mechanical_sltp()` R/R 构造性保证 | trading_logic.py | 最后的 R/R 安全网 |
| `evaluate_trade()` 评估框架 | trading_logic.py | A+~F 评级系统 |

### 只在输入端适配的逻辑

| 逻辑 | 改动内容 | Phase |
|------|---------|-------|
| `risk_controller.py` 阈值 | 静态阈值 → VaR/CVaR 动态阈值 | 2 |
| `calculate_mechanical_sltp()` 仓位大小 | 固定 confidence_mapping → Kelly 输入 | 2 |
| `_activate_stoploss_cooldown()` 时长 | 固定 40min → regime-aware 调节 | 1 |
| `_check_time_barrier()` 时间屏障 | 固定 12h/6h → regime-aware (可选) | 2 |
| `evaluate_trade()` 新增字段 | 记录 hmm_regime_at_entry | 1 |

---

## Phase 1: HMM Regime 适配

### Risk Controller 预适配 (仅数据注入)

```python
# risk_controller.py — Phase 1 只新增一个方法
class RiskController:
    def set_regime_context(self, regime: str, confidence: float):
        """
        Receive HMM regime state for future Phase 2 VaR/CVaR integration.
        Phase 1: store only, no logic change.
        """
        self._current_regime = regime
        self._regime_confidence = confidence
```

**Phase 1 不改变熔断逻辑**。仅存储 regime 上下文，供 Phase 2 VaR/CVaR 消费。

### Stoploss Cooldown Regime 适配

```python
# position_manager.py — _activate_stoploss_cooldown() 微调
def _activate_stoploss_cooldown(self, ...):
    base_cooldown = self._config_cooldown_sec  # 2400s (40min)

    # Phase 1: regime-aware cooldown
    regime = getattr(self, '_current_hmm_regime', None)
    if regime == 'HIGH_VOLATILITY':
        cooldown_sec = int(base_cooldown * 1.5)  # 60min — 高波动多休息
    elif regime == 'RANGING':
        cooldown_sec = int(base_cooldown * 0.75)  # 30min — 震荡快速恢复
    else:
        cooldown_sec = base_cooldown  # 40min — 默认

    # ... 其余逻辑不变 ...
```

**安全边际**: regime 信息不可用时 (`_current_hmm_regime is None`)，fallback 到固定 40min — 行为与 v44.0 完全一致。

### evaluate_trade() 扩展记录

```python
# trading_logic.py — evaluate_trade() 新增记录字段
def evaluate_trade(self, ...):
    result = {
        # ... 现有所有字段 ...
        'hmm_regime_at_entry': getattr(self, '_current_hmm_regime', None),  # Phase 1
    }
    return result
```

**零侵入**: 仅在返回 dict 中新增一个可选字段，不影响任何现有逻辑。

---

## Phase 2: VaR/CVaR 替代静态阈值

### Risk Controller 核心升级

```python
# risk_controller.py — 静态阈值 → 动态 VaR/CVaR

# v44.0 (删除):
DRAWDOWN_REDUCE = 0.10  # 固定 10%
DRAWDOWN_HALT = 0.15    # 固定 15%
DAILY_LOSS_HALT = 0.03  # 固定 3%

# v2.0 Phase 2 (替代):
REGIME_THRESHOLDS = {
    'TRENDING_UP':     {'dd_reduced': 0.12, 'dd_halted': 0.18, 'daily_loss': 0.04},
    'TRENDING_DOWN':   {'dd_reduced': 0.06, 'dd_halted': 0.10, 'daily_loss': 0.02},
    'RANGING':         {'dd_reduced': 0.08, 'dd_halted': 0.12, 'daily_loss': 0.03},
    'HIGH_VOLATILITY': {'dd_reduced': 0.05, 'dd_halted': 0.08, 'daily_loss': 0.015},
}

def _get_current_thresholds(self) -> dict:
    regime = getattr(self, '_current_regime', None)
    if regime and regime in REGIME_THRESHOLDS:
        return REGIME_THRESHOLDS[regime]
    # Fallback: 使用最保守的 HIGH_VOLATILITY 阈值
    return REGIME_THRESHOLDS['HIGH_VOLATILITY']
```

### 安全约束

1. **Fallback 到最保守阈值**: HMM 不可用时，使用 HIGH_VOLATILITY (最紧) 而非 RANGING (中等)
2. **VaR 计算频率**: 每个 on_timer 周期 (20min) 更新一次，不在交易执行路径上
3. **状态机不变**: ACTIVE → REDUCED → HALTED → COOLDOWN 转换逻辑不变，只是阈值动态化
4. **Hysteresis 保留**: 恢复阈值仍低于触发阈值 (防震荡)

### Kelly 仓位计算接入点

```python
# trading_logic.py — calculate_mechanical_sltp() 仓位部分

# v44.0:
position_usdt = max_usdt * (confidence_mapping[confidence] / 100)

# v2.0 Phase 2:
kelly_fraction = self._kelly_sizer.calculate(
    win_rate=self._get_rolling_win_rate(confidence),
    avg_rr=self._get_rolling_avg_rr(confidence),
    regime=self._current_hmm_regime,
    current_drawdown=self._risk_controller.get_drawdown_pct(),
)
position_usdt = max_usdt * kelly_fraction

# 安全钳制: Kelly 输出必须在 [5%, 100%] 范围内
position_usdt = max(max_usdt * 0.05, min(position_usdt, max_usdt))
```

**关键安全网**: `calculate_mechanical_sltp()` 的 R/R 构造性保证 **完全不变**。Kelly 只影响仓位大小，不影响 SL/TP 距离。

---

## Phase 3: LangGraph 安全继承

### 安全层与 LangGraph 的关系

```
LangGraph StateGraph (Phase 3)
  ├─ bull_r1 → bull_r2 → bear_r1 → bear_r2 → judge → et → risk
  │                                                          │
  │  ← LangGraph 编排 AI Agent 调用链 (替代 multi_agent_analyzer.py)
  │
  ↓
ai_strategy.py::on_timer()
  │
  ├─ calculate_mechanical_sltp()  ← 不变 (R/R 安全网)
  ├─ _execute_trade()             ← 不变 (订单提交)
  ├─ risk_controller.can_open_trade()  ← Phase 2 已适配 VaR/CVaR
  └─ safety_manager._submit_emergency_sl()  ← 不变
```

**LangGraph 只替代 Agent 编排层 (`multi_agent_analyzer.py`)**。所有 4 道安全防线仍在 LangGraph 之外:
- 防线 1 (AI Risk Manager): 作为 LangGraph 的一个 node，其逻辑不变
- 防线 2 (代码硬保护): 在 `ai_strategy.py` 中，LangGraph 返回信号后执行
- 防线 3 (熔断器): 在 `on_timer()` 开头检查，早于 LangGraph 调用
- 防线 4 (紧急保护): 在 NautilusTrader 事件回调中，与 LangGraph 完全解耦

### QuestDB 迁移安全

**`data/layer_orders.json` 不迁移到 QuestDB**。

原因:
1. Layer orders 是**实时仓位状态**，需要原子性读写
2. 重启恢复依赖 JSON 文件的简单可靠性
3. QuestDB 适合时序追加 (trading_memory)，不适合频繁更新的状态文件

保留 JSON:
- `data/layer_orders.json` — 仓位层级状态 (实时)
- `data/extended_reflections.json` — 反思记录 (追加为主，量小)

迁移到 QuestDB:
- `data/trading_memory.json` — 历史交易记录 (时序追加，量大)
- `data/hold_counterfactuals.json` — HOLD 反事实记录 (时序追加)
- `data/feature_snapshots/` — Feature 快照 (时序追加，量大)

---

## 安全层适配矩阵

| 组件 | Phase 1 | Phase 2 | Phase 3 | 核心逻辑变更 |
|------|---------|---------|---------|------------|
| `safety_manager.py` | 无变化 | 无变化 | 无变化 | **零改动** |
| `event_handlers.py` | 无变化 | 无变化 | 无变化 | **零改动** |
| `position_manager.py` | cooldown regime-aware | 无变化 | 无变化 | 最小改动 (3 行) |
| `risk_controller.py` | 存储 regime 上下文 | VaR/CVaR 动态阈值 | 无变化 | Phase 2 重构阈值逻辑 |
| `trading_logic.py` | 记录 hmm_regime | Kelly 仓位输入 | 无变化 | Phase 2 仓位计算改动 |

### 改动行数估算

| Phase | 文件 | 新增行 | 修改行 | 删除行 | 风险 |
|-------|------|--------|--------|--------|------|
| 1 | risk_controller.py | 5 | 0 | 0 | 极低 |
| 1 | position_manager.py | 8 | 2 | 0 | 低 |
| 1 | trading_logic.py | 2 | 0 | 0 | 极低 |
| 2 | risk_controller.py | 50 | 20 | 15 | 中 |
| 2 | trading_logic.py | 15 | 5 | 5 | 中 |
| **合计** | | **80** | **27** | **20** | |

**6,891 行安全代码中仅改动 ~127 行 (1.8%)**

---

## 安全层回归测试

### 必须通过的现有测试 (每次改动后)

```bash
# 订单流模拟 (15 场景含 trailing stop)
python3 scripts/diagnose.py --check order_flow_simulation

# 数学验证 (16 项公式)
python3 scripts/diagnose.py --check math_verification

# 代码完整性 (114 项静态分析)
python3 scripts/smart_commit_analyzer.py

# SSoT 逻辑同步
python3 scripts/check_logic_sync.py

# 压力测试 (30+ 异常场景)
python3 scripts/stress_test_position_management.py
```

### Phase 2 新增回归测试

```bash
# VaR/CVaR 计算验证 (新增)
python3 -m pytest tests/test_var_cvar.py -v

# Kelly 公式验证 (新增)
python3 -m pytest tests/test_kelly_sizing.py -v

# Regime-aware 熔断器状态转换 (新增)
python3 -m pytest tests/test_risk_controller_regime.py -v
```

---

## 验收标准

### 安全层连续性验收 (每个 Phase 完成后)

- [ ] `stress_test_position_management.py` 30+ 场景全部 PASS
- [ ] `check_logic_sync.py` 全部 SYNC 项 PASS (含新增项)
- [ ] Emergency SL 路径未被修改 (git diff 验证)
- [ ] Ghost/Orphan 检测逻辑未被修改 (git diff 验证)
- [ ] Layer orders 数据结构未改变 (`_layer_orders` schema 不变)
- [ ] `on_order_filled()` 4-way close reason 逻辑未改变
- [ ] Tier-2 重启恢复流程未改变
- [ ] HMM 不可用时，所有安全逻辑 fallback 到 v44.0 行为
