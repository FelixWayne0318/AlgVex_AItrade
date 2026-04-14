# Phase 0 — 度量基线 (Measurement Baseline)

> **时间**: 1 周 | **前置**: 30 天实盘, trading_memory.json ≥100 条
> **目的**: 建立 v44.0 的精确性能基线，所有后续改进以此为参照。

---

## 1. 信号质量度量 (Alphalens)

### IC (Information Coefficient)

```python
# scripts/measure_signal_quality.py

import alphalens

# Signal score 编码:
# {LONG: +1, SHORT: -1, HOLD: 0} × confidence_rank
# confidence_rank: HIGH=3, MEDIUM=2, LOW=1
# 结果范围: signal_score ∈ [-3, +3]

# Forward returns: 4H 匹配决策层时间框架
forward_returns = alphalens.utils.get_clean_factor_and_forward_returns(
    factor=signal_scores,
    prices=btc_4h_close,
    periods=(1, 3, 6)  # 4H, 12H, 24H
)

# IC = Spearman rank correlation(signal_score, forward_return)
ic_analysis = alphalens.performance.factor_information_coefficient(forward_returns)
# 基准: IC > 0.05 (弱正向), IC > 0.10 (显著)

# IC 半衰期: IC 从峰值衰减到 50% 的周期数
# 用途: 确定最佳持仓时间
ic_halflife = calculate_ic_halflife(ic_analysis)
```

### Quantile Returns

```python
# 按 signal_score 分 5 档, 检查单调性
# 理想: Q5 (最高分) > Q4 > Q3 > Q2 > Q1 (最低分)
quantile_returns = alphalens.performance.mean_return_by_quantile(forward_returns)
```

---

## 2. 策略统计验证 (QuantStats)

### 蒙特卡洛置信区间

```python
import quantstats as qs

# 10,000 次随机 shuffle 交易顺序
# 实际 Sharpe > 95th percentile of shuffled → alpha 显著
qs.reports.full(returns, benchmark='BTC')  # BTC buy-and-hold 为基准

# 关键输出:
# - Sharpe Ratio (risk-free=0, annualized)
# - Calmar Ratio (annualized return / max drawdown)
# - Alpha vs BTC buy-and-hold
# - Monte Carlo p-value (p < 0.05 → alpha 统计显著)
```

---

## 3. 基线 KPI 定义

| KPI | 计算方式 | v44.0 预期 | v2.0 目标 |
|-----|---------|-----------|----------|
| **direction_accuracy** | correct_direction / total_trades | 50-60% | ≥65% |
| **avg_rr** | mean(realized_pnl / planned_sl) | 1.0-1.5 | ≥1.8 |
| **sharpe** | annualized(mean_return / std_return) | 0.5-1.5 | ≥2.0 |
| **max_dd** | max peak-to-trough drawdown | -10%~-15% | ≤-8% |
| **calmar** | annualized_return / abs(max_dd) | 1.0-3.0 | ≥5.0 |
| **IC_4h** | Spearman(signal, 4H forward return) | 0.02-0.08 | ≥0.10 |
| **IC_halflife** | IC 衰减到 50% 的 4H 周期数 | 2-4 | ≥6 |
| **win_rate** | profitable / total | 50-55% | ≥60% |
| **grade_A_pct** | (A+ + A) / total | 20-30% | ≥40% |
| **grade_F_pct** | F / total | 10-20% | ≤5% |

---

## 4. 输出格式

```json
{
  "version": "v44.0",
  "date": "2026-XX-XX",
  "sample_size": 150,
  "period_days": 30,
  "kpis": {
    "direction_accuracy": 0.55,
    "avg_rr": 1.2,
    "sharpe": 1.0,
    "max_dd": -0.12,
    "calmar": 2.1,
    "ic_4h": 0.05,
    "ic_halflife": 3,
    "win_rate": 0.53,
    "grade_a_pct": 0.25,
    "grade_f_pct": 0.15
  },
  "monte_carlo": {
    "p_value": 0.08,
    "alpha_significant": false,
    "confidence_95th_sharpe": 0.85
  }
}
```

**存储**: `data/baseline_v44.json`

---

## 5. 验收标准

1. `data/baseline_v44.json` 生成且全部 10 个 KPI 有值
2. Monte Carlo 10,000 次模拟完成
3. 基线报告推送 Telegram (`/baseline` 命令)
4. 所有后续 Phase 用 `--compare baseline_v44.json` 量化对比

---

## 6. 依赖

```
pip install alphalens-reloaded>=0.4.5 quantstats>=0.0.62
```
