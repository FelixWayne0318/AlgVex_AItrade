# 仓位管理 + 风控 (Definitive)

> **Phase**: 2 (Fractional Kelly + VaR/CVaR), 3 (FinRL)
> **前置**: HMM Regime (Phase 1) — Kelly 需要 regime multiplier

---

## 1. Fractional Kelly × Regime × Drawdown (Phase 2)

**替代**: 固定 confidence_mapping (80/50/30%)
**删除**: `calculate_position_size()` 中固定仓位逻辑

### Kelly 公式

```
f* = (p × b - q) / b

其中:
  p = 胜率 (per confidence tier)
  q = 1 - p
  b = 平均 R/R (盈亏比)
  f* = 理论最优仓位比例
```

### 实际使用: Fractional Kelly (0.25-0.5×)

```python
# utils/kelly_sizer.py

class KellySizer:
    """
    Fractional Kelly: 数学最优 × 安全系数.
    Full Kelly 过于激进 (over-bet), 0.25-0.5× 补偿估算误差.
    """
    _FRACTION = 0.5               # Kelly fraction (保守端)
    _MIN_TRADES_FOR_KELLY = 50    # 最少 50 笔交易才启用 Kelly
    _KELLY_WEIGHT_FULL = 100      # 100 笔交易后 Kelly 权重 100%

    # Regime multipliers (from HMM)
    _REGIME_MULT = {
        'TRENDING_UP': 1.2,       # 顺势加仓
        'TRENDING_DOWN': 0.6,     # 逆势缩仓
        'RANGING': 0.8,           # 区间减小
        'HIGH_VOLATILITY': 0.3,   # 高波动最小化
    }

    def calculate(self, confidence: str, regime: str,
                  win_rate: float, avg_rr: float,
                  current_dd_pct: float, dd_threshold: float,
                  trade_count: int) -> float:
        """
        返回: position_size_pct ∈ [0, 1]

        三层复合:
        Layer 1: Kelly optimal × fraction
        Layer 2: × regime multiplier
        Layer 3: × drawdown scaling
        """
        # Layer 1: Kelly
        if trade_count < self._MIN_TRADES_FOR_KELLY:
            # 数据不足, 用固定 mapping
            kelly_pct = {'HIGH': 0.8, 'MEDIUM': 0.5, 'LOW': 0.3}[confidence]
            kelly_weight = trade_count / self._MIN_TRADES_FOR_KELLY
        else:
            q = 1 - win_rate
            kelly_raw = (win_rate * avg_rr - q) / avg_rr
            kelly_raw = max(0, kelly_raw)  # 负 Kelly = 不交易
            kelly_pct = kelly_raw * self._FRACTION

            # Kelly 权重: 50→100 笔线性增长到 100%
            kelly_weight = min(1.0,
                (trade_count - self._MIN_TRADES_FOR_KELLY) /
                (self._KELLY_WEIGHT_FULL - self._MIN_TRADES_FOR_KELLY))

        # 混合: Kelly × weight + fixed × (1-weight)
        fixed_pct = {'HIGH': 0.8, 'MEDIUM': 0.5, 'LOW': 0.3}[confidence]
        blended = kelly_pct * kelly_weight + fixed_pct * (1 - kelly_weight)

        # Layer 2: Regime
        regime_mult = self._REGIME_MULT.get(regime, 0.8)
        sized = blended * regime_mult

        # Layer 3: Drawdown scaling
        dd_scale = max(0.2, 1.0 - current_dd_pct / dd_threshold)
        sized *= dd_scale

        return min(1.0, max(0.05, sized))  # 钳制到 [5%, 100%]
```

### 数据流

```
交易历史 (win_rate, avg_rr per confidence)
  ↓
KellySizer.calculate(confidence, regime, win_rate, avg_rr, dd, trade_count)
  ↓
position_size_pct × max_usdt × leverage → final_usdt
```

---

## 2. VaR/CVaR + Regime-Adaptive 风控 (Phase 2)

**替代**: 静态阈值熔断器 (10%/15% DD)
**删除**: `risk_controller.py` 中静态 thresholds

### VaR/CVaR 计算

```python
# utils/risk_controller.py (重写)

class RiskController:
    """Regime-Adaptive VaR/CVaR 风控"""

    _CONFIDENCE_LEVEL = 0.95
    _LOOKBACK_DAYS = 30

    # Regime-specific thresholds
    _REGIME_THRESHOLDS = {
        'TRENDING_UP':    {'dd_reduced': 12, 'dd_halted': 18, 'daily_loss': 4},
        'TRENDING_DOWN':  {'dd_reduced': 6,  'dd_halted': 10, 'daily_loss': 2},
        'RANGING':        {'dd_reduced': 8,  'dd_halted': 12, 'daily_loss': 3},
        'HIGH_VOLATILITY':{'dd_reduced': 5,  'dd_halted': 8,  'daily_loss': 1.5},
    }

    def calculate_var(self, returns: np.ndarray) -> float:
        """Historical VaR at 95% confidence"""
        sorted_returns = np.sort(returns)
        idx = int(len(sorted_returns) * (1 - self._CONFIDENCE_LEVEL))
        return abs(sorted_returns[idx])

    def calculate_cvar(self, returns: np.ndarray) -> float:
        """CVaR (Expected Shortfall): 平均尾部损失"""
        var = self.calculate_var(returns)
        tail = returns[returns <= -var]
        return abs(np.mean(tail)) if len(tail) > 0 else var

    def get_thresholds(self, regime: str) -> dict:
        """根据 HMM regime 返回动态阈值"""
        return self._REGIME_THRESHOLDS.get(regime, self._REGIME_THRESHOLDS['RANGING'])

    def evaluate(self, current_dd: float, daily_pnl: float,
                 regime: str, returns_30d: np.ndarray) -> dict:
        """
        返回:
        {
            'state': 'ACTIVE',          # ACTIVE/REDUCED/HALTED/COOLDOWN
            'multiplier': 1.0,          # 仓位乘数
            'var_95': 0.035,            # 95% VaR
            'cvar_95': 0.048,           # 95% CVaR
            'thresholds': {...},        # 当前 regime 的阈值
        }
        """
        thresholds = self.get_thresholds(regime)
        var = self.calculate_var(returns_30d)
        cvar = self.calculate_cvar(returns_30d)

        if current_dd >= thresholds['dd_halted']:
            state, mult = 'HALTED', 0.0
        elif current_dd >= thresholds['dd_reduced']:
            state, mult = 'REDUCED', 0.5
        elif abs(daily_pnl) >= thresholds['daily_loss']:
            state, mult = 'HALTED', 0.0
        else:
            state, mult = 'ACTIVE', 1.0

        return {
            'state': state, 'multiplier': mult,
            'var_95': var, 'cvar_95': cvar,
            'thresholds': thresholds,
        }
```

---

## 3. FinRL 强化学习层 (Phase 3)

**补充**: Fractional Kelly (Phase 2 基线)
**用途**: 动态仓位优化, 学习 regime-dependent 最优 sizing

```python
# utils/finrl_sizer.py

from finrl.agents.stablebaselines3.models import DRLAgent
from stable_baselines3 import PPO

class FinRLPositionOptimizer:
    """
    RL agent 学习: given market state → optimal position size
    Reward: risk-adjusted return (Sharpe-like)

    状态空间: 124 features + regime + drawdown + portfolio_value
    动作空间: position_size_pct ∈ [0, 1] (continuous)
    奖励: (return - risk_free) / std(return) per episode
    """

    def __init__(self):
        self._model = PPO(
            'MlpPolicy',
            env=None,  # 在 train() 中创建
            learning_rate=3e-4,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            verbose=0
        )

    def train(self, historical_features: np.ndarray, historical_returns: np.ndarray):
        """
        训练数据: feature_snapshots + 对应的 forward returns
        Episode: 30 天滑窗
        """
        env = TradingEnv(historical_features, historical_returns)
        self._model.set_env(env)
        self._model.learn(total_timesteps=100_000)
        self._model.save('data/models/finrl_sizer')

    def predict(self, current_features: np.ndarray) -> float:
        """返回 position_size_pct"""
        action, _ = self._model.predict(current_features, deterministic=True)
        return float(np.clip(action, 0.05, 1.0))
```

### Phase 3 部署路径

```
Kelly output (Phase 2 baseline)
  ↓
FinRL output (Phase 3 learned)
  ↓
final_size = max(kelly, finrl) if both agree direction
           = min(kelly, finrl) if disagree (保守)
```

**验收**: FinRL Sharpe > Kelly Sharpe on 60-day OOS test

### FinRL 退出条件 — Kelly 为长期方案

FinRL 是 Plan 中 22 个工具里**成熟度最低**的一个 (唯一标准化交易 RL 框架，但生产案例有限)。明确退出条件，避免无限期投入:

**3 个退出门控 (任一触发 → 停止 FinRL，Kelly 为长期方案)**:

| # | 门控 | 条件 | 时间限制 |
|---|------|------|---------|
| 1 | **训练失败** | 500+ 交易数据训练后，OOS Sharpe ≤ Kelly Sharpe | Phase 3 启动后 4 周 |
| 2 | **生产劣化** | 30 天实盘 FinRL sizing 导致 max_dd 恶化 >2% vs Kelly baseline | 部署后 30 天 |
| 3 | **维护成本** | RL model retrain 频率 >2 周/次且每次需人工介入 | 部署后 60 天 |

**退出后状态**:

```
FinRL 退出 → Kelly 0.25-0.5× 为长期生产方案
           → FinRL 代码保留在 feature branch (不删除，Git 可追溯)
           → Optuna 继续优化 Kelly 参数 (fraction, regime_mult)
```

**根因**: FinRL (PPO) 的实际风险是:
1. **样本效率低**: 500 笔交易可能不足以训练稳定的 RL policy
2. **Reward shaping 敏感**: Sharpe-like reward 需要精细调优，否则 agent 学到保守不交易
3. **分布偏移**: 市场 regime 变化后 RL policy 可能失效 (Kelly 公式数学上更鲁棒)

Kelly 本身已是**信息论数学最优** (Shannon 1956)，Fractional Kelly + Regime × Drawdown 三层复合在 Phase 2 已经足够生产可用。FinRL 是 Phase 3 的**探索性升级**，不是必要条件。

---

## 4. 依赖

```
# Phase 2
pip install numpy scipy

# Phase 3
pip install finrl>=0.3 stable-baselines3>=2.3 gymnasium>=1.0
```
