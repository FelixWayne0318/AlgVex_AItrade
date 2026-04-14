# AlgVex - NautilusTrader DeepSeek AI Trading Strategy

## AI-Powered Multi-Timeframe Trading System

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NautilusTrader](https://img.shields.io/badge/NautilusTrader-Latest-green.svg)](https://nautilustrader.io/)
[![DeepSeek AI](https://img.shields.io/badge/DeepSeek-AI%20Powered-purple.svg)](https://www.deepseek.com/)
[![License](https://img.shields.io/badge/license-Educational-orange.svg)](LICENSE)

**Professional algorithmic trading system combining DeepSeek AI decision-making, advanced technical analysis, and institutional-grade risk management for automated BTC/USDT perpetual futures trading on Binance.**

---

## ⚡ 部署快速参考 (Deployment Quick Reference)

> **重要**: 入口文件是 `main_live.py`，不是 `main.py`

| 项目 | 值 |
|------|-----|
| 入口文件 | `main_live.py` |
| 服务器路径 | `/home/linuxuser/nautilus_AlgVex` |
| 服务名 | `nautilus-trader` |
| 分支 | `main` |

```bash
# 常用命令
sudo systemctl restart nautilus-trader          # 重启
sudo journalctl -u nautilus-trader -f           # 查看日志
cd /home/linuxuser/nautilus_AlgVex && git pull origin main  # 更新代码
python3 scripts/smart_commit_analyzer.py        # 回归检测
python3 scripts/diagnose.py --quick             # 快速诊断
```

---

## Table of Contents

- [Features](#features)
- [What's New](#whats-new)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Advanced Features](#advanced-features)
- [Usage](#usage)
- [Risk Management](#risk-management)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Performance](#performance-expectations)
- [Documentation](#documentation)
- [Disclaimer](#disclaimer)

---

## Features

### Core Capabilities

- **AI-Powered Decision Making**: DeepSeek AI analyzes market conditions and generates intelligent trading signals with confidence levels (HIGH/MEDIUM/LOW)
- **Comprehensive Technical Analysis**:
  - Moving Averages (SMA 5/20/50, EMA 12/26)
  - Momentum Indicators (RSI 14, MACD)
  - Volatility Bands (Bollinger 20, 2σ)
  - Support/Resistance Detection
  - Volume Analysis
- **Sentiment Integration**: Binance Long/Short Ratio API for real-time market sentiment analysis
- **Intelligent Position Sizing**: Dynamic sizing based on AI confidence, trend strength, RSI extremes, and risk limits
- **Event-Driven Architecture**: Built on NautilusTrader's professional framework for high-performance execution

### Advanced Risk Management (v1.2.x)

- **Per-Layer SL/TP (v7.2+)**:
  - Each scaling layer has independent SL/TP orders
  - ATR-based mechanical SL/TP calculation with R/R >= 2.0:1 guarantee
  - Step-by-step order submission (entry first, SL/TP after fill)
  - Position-linked TP orders (auto-cancel on position close)
  - Emergency SL fallback with 3-retry escalation

### Remote Control & Monitoring

- **Telegram Integration**:
  - Real-time notifications for signals, fills, positions, and errors
  - Remote control commands (`/status`, `/position`, `/pause`, `/resume`)
  - View current equity, P&L, and strategy status
  - Pause/resume trading without stopping the strategy

### Safety Features

- Minimum confidence filtering (configurable: LOW/MEDIUM/HIGH)
- Maximum position size limits (default: 10% of equity)
- RSI extreme condition handling (0.7x multiplier at RSI >75 or <25)
- Position reversal protection with confidence requirements
- Minimum adjustment thresholds to prevent excessive trading
- Comprehensive logging and monitoring
- Per-layer order tracking with JSON persistence for crash recovery

---

## What's New

### v21.0 (Current - March 2026)
- **FR Consecutive Block Counter**: Tracks consecutive funding rate blocks in same direction; ≥3 blocks degrades signal to HOLD to break dead loops
- **1D Historical Context**: 10-bar 1D time series (ADX/DI+/DI-/RSI/Price) injected into AI for trend exhaustion and ADX direction change detection

### v20.0 (February 2026)
- **ATR Volatility Regime**: ATR% percentile ranking (LOW/NORMAL/HIGH/EXTREME) for position sizing and stop width adjustment
- **OBV Divergence Detection**: EMA(20)-smoothed OBV divergence across 4H and 30M, complementary to CVD micro order flow

### v19.2 (February 2026)
- **CVD-Price time alignment fix**: 30M and 4H CVD-Price crossover analysis aligned to 5-bar windows
- **OI x CVD positioning analysis**: CoinGlass-standard 4-quadrant framework (bull/bear open/close)
- **CVD Absorption detection**: Identifies passive buyer/seller absorption in flat markets

### v19.1 - v19.1.1 (February 2026)
- **ATR Extension Ratio**: `(Price - SMA) / ATR` overextension detection with 4 regimes (NORMAL/EXTENDED/OVEREXTENDED/EXTREME)
- **RSI/MACD divergence pre-computation**: Automated divergence detection across 4H and 30M timeframes
- **CVD-Price crossover analysis**: ACCUMULATION/DISTRIBUTION/CONFIRMED automatic annotation
- **Trend-aware extension**: ADX>40 downgrades OVEREXTENDED warnings (strong trends can sustain extension)

### v18.0 - v18.3 (February 2026)
- **LLM deep reflection (v18.0)**: Post-close Phase 0 generates AI reflection (replaces template lessons), +1 API call per close
- **Signal reliability annotations (v18.1)**: Technical report reorganized by reliability tiers (Tier 1/2/3)
- **Execution layer 30M (v18.2)**: Migrated from 15M to 30M for reduced noise
- **Alignment gate (v18.2)**: Deterministic MTF verification with trend-aware weighting (ADX>=40: 1D=0.7, 4H=0.3)
- **Post-close active analysis (v18.3)**: 2 forced AI analysis cycles after position close (~45 min coverage)

### v16.0 - v17.1 (February 2026)
- **S/R Hold Probability auto-calibration (v16.0)**: Weekly cron calculates zone hold factors from 30-day klines
- **S/R simplified to 1+1 (v17.0)**: Output trimmed to nearest 1 support + 1 resistance zone
- **Liquidation buffer dual-layer protection (v17.1)**: 4-tier buffer evaluation + code hard floor at 5%

### v11.0 - v14.0 (February 2026)
- **S/R purely informational (v11.0)**: S/R zones as AI context only, no mechanical SL/TP anchoring
- **Per-agent reflection memory (v12.0)**: LLM-generated reflections distributed to all 4 agents by role
- **Telegram close safety (v13.1)**: Failed close after SL cancel triggers immediate emergency SL
- **Telegram dual-channel (v14.0)**: Control bot (private) + notification channel (subscribers), zero message duplication

### v7.2 - v7.3 (February 2026)
- **Per-layer SL/TP (v7.2)**: Each scaling layer has independent SL/TP orders, LIFO reduction
- **Restart SL cross-validation (v7.3)**: Tier 2 recovery verifies each layer's SL exists on exchange

### v7.0 - v7.1 (February 2026)
- **External data SSoT (v7.0)**: `AIDataAssembler.fetch_external_data()` as single source of truth
- **Position sizing safety (v7.1)**: `ai_controlled` and `hybrid_atr_ai` enforce `max_usdt` ceiling
- **Emergency close retry (v7.1)**: `_emergency_market_close()` retries 3 times + flags for next cycle

### v3.0 - v6.6 (December 2025 - February 2026)
- **TradingAgents architecture**: 6+1 AI calls (Phase 0 Reflection + Bull x2, Bear x2, Judge, Risk)
- **Multi-Timeframe Framework**: 1D trend / 4H decision / 30M execution
- **13 data sources**: Technical, sentiment, order flow, derivatives, S/R zones, etc.
- **LIMIT entry orders**: R/R preserved at validation value
- **Two-phase SL/TP submission**: Entry first, SL/TP after fill (NT 1.222.0+)
- **Full agent memory (v5.9)**: All 4 agents receive trade history
- **Counter-trend R/R (v5.12)**: 1.95:1 (1.3x multiplier) for counter-trend trades
- **Emergency SL escalation (v6.1)**: SL failure -> emergency SL -> market close with 3 retries
- **Position-linked TP (v6.6)**: LIMIT_IF_TOUCHED via Algo API, auto-cancel on position close

### v1.0 - v2.1 (October - November 2025)
- Initial NautilusTrader + DeepSeek AI integration
- Binance Futures BTCUSDT-PERP support
- Telegram remote control, trailing stop, partial take profit

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    User Interface                        │
│              (Telegram Bot / Logs / CLI)                 │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│              DeepSeek AI Strategy (v21.0 MTF)            │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Multi-Timeframe Framework (1D/4H/30M)            │  │
│  │  • Trend Layer (1D): Risk-On/Off Filter          │  │
│  │  • Decision Layer (4H): Bull/Bear Debate         │  │
│  │  • Execution Layer (30M): Precise Entry          │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  AI Decision Engine (TradingAgents)               │  │
│  │  • Bull Analyst (persuasive bullish case)        │  │
│  │  • Bear Analyst (skeptical bearish case)         │  │
│  │  • Judge (quantitative decision framework)       │  │
│  │  • Risk Manager (position sizing + SL/TP)        │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Risk Management                                  │  │
│  │  • Per-Layer SL/TP (v7.2+)                      │  │
│  │  • Emergency SL Escalation (v6.1+)              │  │
│  │  • Position Sizing Calculator                    │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Technical Analysis                               │  │
│  │  • SMA/EMA/RSI/MACD/Bollinger                    │  │
│  │  • ATR Extension Ratio (v19.1)                   │  │
│  │  • ATR Volatility Regime (v20.0)                 │  │
│  │  • OBV / RSI / MACD Divergence Detection         │  │
│  │  • Support/Resistance (1+1 nearest, v17.0)       │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│            NautilusTrader Framework                      │
│  • Event Engine  • Order Management  • Position Cache   │
└────────────────────────┬────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┬────────────────┬───────────────┐
         │                               │                │
┌────────┴─────────┐  ┌─────────────────┴──────┐  ┌──────┴──────┐
│ Binance Futures  │  │ Binance L/S + K-line   │  │ Coinalyze   │
│  (Market Data &  │  │ (Sentiment + Order Flow│  │ (Derivatives│
│   Execution)     │  │  Data)                 │  │  Data)      │
└──────────────────┘  └────────────────────────┘  └─────────────┘
```

### Data Flow

```
┌─ Multi-Timeframe Data Sources ────────────────────────────┐
│                                                           │
│  1D Bars → Trend Filter (SMA_200, MACD)                  │
│     ↓                                                     │
│  4H Bars → Technical Indicators → ─────────┐             │
│  Order Flow (Buy/Sell Ratio, CVD) → ───────┤             │
│  Derivatives (OI, Funding, Liquidations) → ─┤→ AI Data   │
│  Sentiment (L/S Ratio) → ──────────────────┘  Assembler  │
│                                                     ↓     │
└─────────────────────────────────────────────────────────┘
                                                      ↓
┌─ TradingAgents Framework (6+1 AI Calls) ──────────────┐
│  Phase 0: Reflection (0~1 call, post-close only)       │
│  Phase 1: Bull × 2 rounds ┐                            │
│           Bear × 2 rounds ├→ Phase 2: Judge Decision   │
│                            └→ Phase 3: Risk Manager    │
└────────────────────────────────────────────────────────┘
                          ↓
                Trading Signal (with confidence)
                          ↓
        Per-Layer Position Management (SL/TP per layer)
```

### Project Structure

```
AlgVex/
├── configs/
│   ├── base.yaml                     # Base configuration (all parameters)
│   ├── production.yaml               # Production environment overrides
│   ├── development.yaml              # Development environment overrides
│   └── backtest.yaml                 # Backtesting environment overrides
├── indicators/
│   ├── technical_manager.py          # Technical indicators + ATR Extension Ratio (v19.1)
│   └── multi_timeframe_manager.py    # Multi-timeframe data management (1D/4H/30M)
├── strategy/
│   ├── ai_strategy.py                # Main strategy (core loop + mixin composition)
│   ├── event_handlers.py             # Event callbacks mixin (on_order_*, on_position_*)
│   ├── order_execution.py            # Order execution mixin (_execute_trade, _submit_*)
│   ├── position_manager.py           # Position management mixin (layers, scaling)
│   ├── safety_manager.py             # Safety mixin (emergency SL, orphan cleanup)
│   ├── telegram_commands.py          # Telegram command handlers mixin
│   └── trading_logic.py              # Trading logic + evaluate_trade() evaluation
├── agents/
│   ├── multi_agent_analyzer.py       # Bull/Bear/Judge/Risk AI core
│   ├── prompt_constants.py           # Indicator definitions + confidence matrix
│   ├── report_formatter.py           # Data-to-text formatting mixin
│   └── memory_manager.py             # Trading memory + reflection mixin
├── utils/
│   ├── ai_data_assembler.py          # 13-category data aggregation (SSoT)
│   ├── sentiment_client.py           # Binance Long/Short ratio fetcher
│   ├── telegram_bot.py               # Telegram notifications & control
│   ├── telegram_command_handler.py   # Telegram command processor
│   ├── binance_kline_client.py       # K-line + order flow + Funding Rate
│   ├── binance_derivatives_client.py # Top Traders long/short ratio
│   ├── binance_orderbook_client.py   # Orderbook depth analysis
│   ├── coinalyze_client.py           # OI + Liquidations (optional)
│   └── sr_zone_calculator.py         # S/R zone calculation
├── scripts/
│   ├── diagnose.py                   # Full diagnostic suite
│   ├── diagnose_realtime.py          # Real-time API diagnostics
│   ├── smart_commit_analyzer.py      # Regression detection
│   └── calibrate_hold_probability.py # S/R hold probability calibration (v16.0)
├── main_live.py                      # Live trading entrypoint
├── requirements.txt                  # Python dependencies
├── data/                             # Runtime data (trading_memory.json, layer_orders.json, calibration/)
├── README.md                         # This file
└── docs/                             # Additional documentation
    ├── SYSTEM_OVERVIEW.md            # System architecture overview
    └── SECURITY.md                   # Security best practices
```

---

## Prerequisites

### System Requirements

- **Python**: 3.12 or higher (required for NautilusTrader 1.224.0)
- **Operating System**: Linux/macOS recommended (Windows with WSL2)
- **Memory**: 512MB+ RAM
- **Storage**: 1GB+ free space

### Trading Requirements

- **Binance Account**:
  - Futures trading enabled
  - API key with trading permissions (no withdrawal needed)
  - Sufficient USDT balance (minimum $500 recommended)
- **DeepSeek API Key**: Get from [platform.deepseek.com](https://platform.deepseek.com/)
- **Telegram Bot** (optional): For notifications and remote control

### Knowledge Requirements

- Basic understanding of cryptocurrency trading
- Familiarity with perpetual futures contracts
- Understanding of leverage and margin trading
- Basic Python and command line usage

---

## Quick Start

### 5-Minute Setup

```bash
# 1. Clone repository
cd /home/linuxuser
git clone https://github.com/FelixWayne0318/AlgVex.git nautilus_AlgVex
cd nautilus_AlgVex

# 2. Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure environment
cat > ~/.env.algvex << 'EOF'
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
DEEPSEEK_API_KEY=your_key
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
EOF
chmod 600 ~/.env.algvex

# 6. Set up Binance account
# - Navigate to Futures → BTCUSDT-PERP
# - Set margin mode: CROSS
# - Set leverage: 10x
# - Fund account with USDT

# 5. Start trading
python3 main_live.py --env production
```

---

## Installation

### Detailed Installation Steps

#### 1. System Preparation

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3.12+ if not available
sudo apt install python3.12 python3.12-venv python3-pip -y
```

#### 2. Project Setup

```bash
# Clone repository
cd /home/linuxuser  # or your preferred directory
git clone https://github.com/FelixWayne0318/AlgVex.git nautilus_AlgVex
cd nautilus_AlgVex

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Verify installation
python3 -c "import nautilus_trader; print(f'NautilusTrader {nautilus_trader.__version__} installed')"
```

#### 4. Configuration

##### Environment Variables

Create `~/.env.algvex` (sensitive info only — business parameters go in `configs/base.yaml`):

```bash
cat > ~/.env.algvex << 'EOF'
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_api_secret_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
# Optional: Notification channel (v14.0 dual-channel)
TELEGRAM_NOTIFICATION_BOT_TOKEN=
TELEGRAM_NOTIFICATION_CHAT_ID=
# Optional: Coinalyze derivatives data
COINALYZE_API_KEY=
EOF
chmod 600 ~/.env.algvex
```

**Security Best Practices:**

```bash
# Set proper file permissions
chmod 600 ~/.env.algvex

# NEVER commit sensitive files to version control
git status  # ~/.env.algvex should not appear (it's outside the repo)
```

##### Strategy Configuration

Edit `configs/base.yaml` for advanced settings, with environment-specific overrides in `configs/{env}.yaml`. Key sections are documented in [Configuration](#configuration) section below.

#### 5. Binance Account Setup

**Critical Steps:**

1. **Login to Binance** → Navigate to Futures Trading
2. **Find BTCUSDT-PERP Contract**
3. **Set Margin Mode**:
   - Click margin mode selector
   - Select "Cross" (not Isolated)
   - This strategy uses cross-margin
4. **Set Leverage**:
   - Adjust leverage slider to **10x**
   - Must match `leverage` in `configs/base.yaml`
5. **Fund Account**:
   - Transfer USDT to Futures wallet
   - Minimum recommended: $500 USDT
6. **Create API Key**:
   - Account → API Management
   - Create new API key
   - Enable: "Enable Futures" + "Enable Reading"
   - Do NOT enable: "Enable Withdrawals"
   - Optional: Add IP restriction for security

#### 6. Verification

```bash
# Test API connectivity
python3 -c "
from dotenv import load_dotenv
import os
load_dotenv()
print('✅ API Keys loaded' if os.getenv('BINANCE_API_KEY') else '❌ Missing API keys')
"

# Test strategy configuration
python3 -c "
from strategy.ai_strategy import AITradingStrategyConfig
config = AITradingStrategyConfig(
    instrument_id='BTCUSDT-PERP.BINANCE',
    bar_type='BTCUSDT-PERP.BINANCE-30-MINUTE-LAST-EXTERNAL',
)
print(f'✅ Strategy config loaded: {config.name}')
"
```

---

## Configuration

### Configuration Management System

**New**: ConfigManager provides unified configuration with multi-environment support.

#### Environment Switching

```bash
# Production (30-minute bars, INFO logging)
python3 main_live.py --env production

# Development (1-minute bars, DEBUG logging)
python3 main_live.py --env development

# Backtest (fixed equity, no Telegram)
python3 main_live.py --env backtest

# Validate configuration (dry-run)
python3 main_live.py --env development --dry-run
```

#### Configuration Files Structure

```
configs/
├── base.yaml           # Complete configuration definition (all parameters)
├── production.yaml     # Production environment overrides
├── development.yaml    # Development environment overrides
└── backtest.yaml       # Backtesting environment overrides

~/.env.algvex         # Sensitive information (API keys)
```

#### Validation Tools

```bash
# Validate PATH_ALIASES mappings
python3 scripts/validate_path_aliases.py

# Performance benchmark (target: < 200ms)
python3 scripts/benchmark_config.py

# Circular import check
bash scripts/check_circular_imports.sh
```

### Strategy Configuration File

Location: `configs/base.yaml` (with environment-specific overrides)

#### Core Settings

```yaml
strategy:
  name: "AITradingStrategy"
  instrument_id: "BTCUSDT-PERP.BINANCE"
  bar_type: "BTCUSDT-PERP.BINANCE-30-MINUTE-LAST-EXTERNAL"

  equity: 400           # Trading capital (USDT)
  leverage: 10          # Futures leverage multiplier
```

#### Position Management

```yaml
position_management:
  base_usdt_amount: 30                  # Base position size per trade
  high_confidence_multiplier: 1.5       # 1.5x for HIGH confidence
  medium_confidence_multiplier: 1.0     # 1.0x for MEDIUM confidence
  low_confidence_multiplier: 0.5        # 0.5x for LOW confidence
  max_position_ratio: 0.10              # Max 10% of equity per position
  trend_strength_multiplier: 1.2        # Bonus for STRONG trends
  min_trade_amount: 0.001               # Minimum BTC amount
```

#### Risk Management Features

```yaml
risk:
  # Basic Risk Controls
  min_confidence_to_trade: "MEDIUM"     # Minimum signal confidence
  allow_reversals: true                 # Allow position reversals
  require_high_confidence_for_reversal: false
  rsi_extreme_threshold_upper: 70       # RSI overbought level
  rsi_extreme_threshold_lower: 30       # RSI oversold level
  rsi_extreme_multiplier: 0.7           # Size reduction in extremes

  # Stop Loss & Take Profit
  enable_auto_sl_tp: true               # Enable automatic SL/TP
  sl_use_support_resistance: false      # v11.0: SL by ATR mechanical formula
  sl_buffer_pct: 0.001                  # Stop loss buffer (0.1%)
  tp_high_confidence_pct: 0.03          # HIGH confidence TP: 3%
  tp_medium_confidence_pct: 0.02        # MEDIUM confidence TP: 2%
  tp_low_confidence_pct: 0.01           # LOW confidence TP: 1%

  # OCO handled automatically by per-layer SL/TP (v7.2+)
```

#### Technical Indicators

```yaml
indicators:
  sma_periods: [5, 20, 50]              # Simple Moving Average periods
  ema_periods: [12, 26]                 # Exponential MA (for MACD)
  rsi_period: 14                        # Relative Strength Index
  macd_fast: 12                         # MACD fast period
  macd_slow: 26                         # MACD slow period
  macd_signal: 9                        # MACD signal line
  bollinger_period: 20                  # Bollinger Bands period
  bollinger_std: 2.0                    # Bollinger standard deviation
  volume_ma_period: 20                  # Volume moving average
  support_resistance_lookback: 20       # Bars for S/R detection
```

#### AI Configuration

```yaml
deepseek:
  model: "deepseek-chat"
  temperature: 0.1                      # Low for consistent decisions
  max_retries: 2
  base_url: "https://api.deepseek.com"
```

#### Sentiment Data

```yaml
sentiment:
  enabled: true
  provider: "binance"                   # Binance Long/Short Ratio API
  update_interval_minutes: 15
  lookback_hours: 4
  weight: 0.30                          # 30% weight in decisions
```

#### Telegram Notifications

```yaml
telegram:
  enabled: true                         # Enable Telegram integration
  bot_token: ""                         # Read from .env
  chat_id: ""                           # Read from .env
  notify_signals: true                  # Notify on AI signals
  notify_fills: true                    # Notify on order fills
  notify_positions: true                # Notify on position changes
  notify_errors: true                   # Notify on errors
```

#### Timing

```yaml
timer_interval_sec: 1200                # AI analysis every 20 minutes
```

### Configuration Profiles

#### Conservative (Low Risk)

```yaml
risk:
  min_confidence_to_trade: "HIGH"
  require_high_confidence_for_reversal: true

position_management:
  base_usdt_amount: 20
  max_position_ratio: 0.05              # 5% max
  high_confidence_multiplier: 1.2

risk:
  tp_high_confidence_pct: 0.02          # 2% TP
```

#### Aggressive (High Risk)

```yaml
risk:
  min_confidence_to_trade: "LOW"
  require_high_confidence_for_reversal: false

position_management:
  base_usdt_amount: 50
  max_position_ratio: 0.20              # 20% max (⚠️ high risk)
  high_confidence_multiplier: 2.0

risk:
  tp_high_confidence_pct: 0.05          # 5% TP
```

---

## Advanced Features

### 1. Per-Layer SL/TP (v7.2+)

Each scaling layer has independent SL/TP orders, tracked in `data/layer_orders.json`.

**SL/TP Calculation:**
- `calculate_mechanical_sltp()` uses ATR × confidence multiplier
- Guarantees R/R >= 2.0:1 (counter-trend: >= 1.95:1 via 1.3x multiplier)
- S/R zones are informational context for AI, not mechanical anchors (v11.0+)

**Order Submission (v4.13+):**
1. Entry order submitted first
2. On `on_position_opened`: SL (STOP_MARKET) + TP (LIMIT_IF_TOUCHED) submitted separately
3. TP is position-linked — auto-cancels when position closes (v6.6)

**Emergency Fallback (v6.1+):**
- SL submission failure → `_emergency_market_close()` (3 retries + next-cycle flag)
- Telegram close failure → immediate `_submit_emergency_sl()` (v13.1)

### 2. Telegram Remote Control (v14.0 Dual-Channel)

Monitor and control your trading strategy remotely via Telegram.

**Available Commands:**

| Command | Description |
|---------|-------------|
| `/status` | View strategy status, equity, P&L, uptime |
| `/position` | View current position details with SL/TP |
| `/pause` | Pause trading (stop new orders) |
| `/resume` | Resume trading |
| `/help` | Show all available commands |

**Setup:**

1. Create Telegram bot via [@BotFather](https://t.me/botfather)
2. Get bot token and your chat ID
3. Add to `~/.env.algvex`:

```bash
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

4. Enable in configuration:

```yaml
telegram:
  enabled: true
  notify_signals: true
  notify_fills: true
  notify_positions: true
  notify_errors: true
```

**Example Interactions:**

```
You: /status
Bot: 🟢 Strategy Status
     Status: RUNNING
     Instrument: BTCUSDT-PERP.BINANCE
     Current Price: $70,125.50
     Equity: $408.50
     Unrealized P&L: 📈 $8.50 (+2.12%)

     Last Signal: BUY (HIGH)
     Uptime: 2h 15m

You: /position
Bot: 🟢 Open Position
     Side: LONG
     Quantity: 0.0012 BTC
     Entry: $69,500.00
     Current: $70,125.50

     Unrealized P&L: 📈 $0.75 (+0.90%)

     🛡️ Stop Loss: $69,125.50
     🎯 Take Profit: $71,585.00

You: /pause
Bot: ⏸️ Strategy Paused
     Trading has been paused. No new orders will be placed.
     Existing positions remain active.
     Use /resume to continue trading.
```

**Notifications:**

The bot automatically sends notifications for:
- AI trading signals with confidence and reasoning (notification channel)
- Order fills and executions (notification channel)
- Position changes (opened/closed) with P&L (notification channel)
- Errors and warnings (private chat)
- SL/TP adjustments and emergency alerts (private chat)

**Details:** See [CLAUDE.md](CLAUDE.md) for full Telegram command reference and dual-channel message routing.

---

## Usage

### Starting the Strategy

#### Foreground (Testing)

```bash
# Activate virtual environment
source venv/bin/activate

# Start strategy
python3 main_live.py
```

#### Background (Production)

```bash
# Start in background with logging
nohup python3 main_live.py > logs/trader_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Save process ID
echo $! > trader.pid

# Monitor logs
tail -f logs/trader_*.log

# Stop strategy
kill $(cat trader.pid)
```

#### Using Helper Scripts

```bash
# Start trader
./start_trader.sh

# Restart trader
./restart_trader.sh

# Stop trader
./stop_trader.sh

# Check status
./check_strategy_status.sh
```

### Expected Startup Sequence

```
🚀 Starting DeepSeek AI Trading Strategy
✅ Environment loaded
✅ Binance credentials validated
✅ DeepSeek API key loaded
✅ Telegram bot connected
✅ Connecting to Binance Futures...
✅ Subscribed to BTCUSDT-PERP 30-MINUTE bars
✅ Strategy started successfully
⏱️  Analysis timer set: 1200 seconds (20 minutes)
📊 Waiting for indicators to initialize (need 50 bars)...
🤖 First analysis in ~20 minutes...
```

### Operation Cycle

**Every 20 minutes (configurable):**

1. **Data Collection**:
   - Latest market data from Binance
   - Technical indicators updated
   - Sentiment data fetched from Binance Long/Short Ratio API

2. **AI Analysis (6+1 calls)**:
   - Phase 0: Reflection (post-close only, 0~1 call)
   - Phase 1: Bull/Bear debate (2 rounds = 4 calls)
   - Phase 2: Judge quantitative decision (1 call)
   - Phase 3: Risk Manager SL/TP + sizing (1 call)
   - Generates signal: BUY/SELL/HOLD with confidence HIGH/MEDIUM/LOW

3. **Position Management**:
   - Check existing position
   - Calculate desired position size
   - Determine action (open/add/reduce/reverse/hold)

4. **Execution**:
   - Validate signal confidence + R/R ratio
   - Calculate mechanical SL/TP (ATR x confidence)
   - Submit LIMIT entry order
   - On fill: submit per-layer SL + TP orders
   - Send Telegram notifications (dual-channel)

5. **Risk Management**:
   - Per-layer SL/TP tracking (v7.2+)
   - Emergency SL escalation on failure (v6.1+)
   - Position-linked TP auto-cancel (v6.6+)
   - Alignment gate MTF verification (v18.2+)
   - Log all actions

### Trading Examples

#### Example 1: Opening a Long Position

```log
[2025-11-17 10:00:00] 📊 Running periodic analysis...
[2025-11-17 10:00:01] 📈 Technical Analysis:
                       Price: $70,125.50
                       SMA5: $69,800 | SMA20: $69,200 | SMA50: $68,500
                       RSI: 62.5 (neutral)
                       MACD: Bullish crossover
                       Support: $69,500 | Resistance: $71,200

[2025-11-17 10:00:02] 💭 Sentiment: Bullish 65% | Bearish 35% | Net: +30

[2025-11-17 10:00:03] 🤖 DeepSeek AI Signal: BUY
                       Confidence: HIGH
                       Reasoning:
                       (1) Strong uptrend with price above all SMAs
                       (2) Bullish MACD crossover confirms momentum
                       (3) RSI at 62 shows room for upside
                       (4) Positive sentiment (+30) supports bullish bias
                       (5) Price respected support at $69,500
                       (6) Volume increasing on up moves

[2025-11-17 10:00:04] 📊 Position Sizing:
                       Base: $30 USDT
                       Confidence: 1.5x (HIGH)
                       Trend: 1.2x (STRONG)
                       RSI: 1.0x (normal)
                       Final: $54 USDT → 0.00077 BTC

[2025-11-17 10:00:05] ✅ Order submitted: BUY 0.00077 BTC MARKET
[2025-11-17 10:00:06] ✅ Order filled: BUY 0.00077 @ $70,125.50
[2025-11-17 10:00:07] 🟢 Position opened: LONG 0.00077 @ $70,125.50

[2025-11-17 10:00:08] 🛡️ Submitted Stop Loss: $69,430.50 (-0.99%)
[2025-11-17 10:00:09] 🎯 Submitted Take Profit Level 1: 50% @ $71,528.00 (+2.0%)
[2025-11-17 10:00:10] 🎯 Submitted Take Profit Level 2: 50% @ $72,930.50 (+4.0%)
[2025-11-17 10:00:11] 📱 Telegram: Position opened notification sent
```

#### Example 2: Trailing Stop in Action

```log
[2025-11-17 10:15:00] 📊 Periodic check: Position LONG @ $70,125.50
                       Current price: $70,850.50
                       Unrealized P&L: +$0.56 (+1.03%)

[2025-11-17 10:15:01] 🎯 Trailing stop ACTIVATED
                       Entry: $70,125.50
                       Current: $70,850.50
                       Profit: +1.03% (above 1% threshold)

[2025-11-17 10:30:00] ⬆️ Price continues rising: $71,550.00
                       Highest price: $71,550.00
                       Trailing stop update:
                       Old SL: $69,430.50
                       New SL: $71,192.50 ($71,550 - 0.5%)
                       Locked profit: +1.52%

[2025-11-17 10:30:01] 🔴 Cancelled old SL: O-20251117-001-SL
[2025-11-17 10:30:02] ✅ New trailing SL submitted: O-20251117-002-SL
[2025-11-17 10:30:03] 🔄 Per-layer SL/TP updated

[2025-11-17 10:45:00] ⬆️ Price reaches $72,300.00
                       New trailing SL: $71,941.50
                       Locked profit: +2.59%

[2025-11-17 11:00:00] 📉 Price retraces to $71,941.50
[2025-11-17 11:00:01] ✅ Trailing SL triggered: SELL 0.00077 @ $71,941.50
[2025-11-17 11:00:02] 🔴 Position closed: LONG
                       Entry: $70,125.50
                       Exit: $71,941.50
                       P&L: +$1.40 (+2.59%) ✅

[2025-11-17 11:00:03] 📱 Telegram: Position closed notification sent
```

---

## Risk Management

### Multi-Layer Protection

#### 1. Position Size Limits

```yaml
max_position_ratio: 0.10  # Maximum 10% of equity per position

# Example with $400 equity:
# Max position = $400 × 0.10 = $40 USDT
# At $70,000 BTC = ~0.00057 BTC maximum
```

#### 2. Confidence Filtering

```yaml
min_confidence_to_trade: "MEDIUM"

# Results:
# HIGH confidence → Trade ✅
# MEDIUM confidence → Trade ✅
# LOW confidence → Skip ❌
```

#### 3. Reversal Protection

```yaml
require_high_confidence_for_reversal: true

# When reversing from LONG to SHORT (or vice versa):
# HIGH confidence → Execute reversal ✅
# MEDIUM/LOW confidence → Close position only, no reversal ❌
```

#### 4. RSI Extreme Handling

```yaml
rsi_extreme_threshold_upper: 70
rsi_extreme_threshold_lower: 30
rsi_extreme_multiplier: 0.7

# When RSI > 75 or RSI < 25:
# Position size = calculated_size × 0.7 (30% reduction)
```

#### 5. Stop Loss Protection

All positions automatically have stop loss protection:

- **ATR-based**: `calculate_mechanical_sltp()` constructs SL/TP with R/R >= 2.0:1
- **Per-layer**: Each scaling layer has independent SL/TP (v7.2+)
- **Position-linked TP**: Auto-cancels when position closes (v6.6+)
- **Emergency fallback**: SL failure triggers market close with 3 retries (v6.1+)

### Risk Profiles

#### Conservative Profile

```yaml
# Minimum risk, maximum safety
risk:
  min_confidence_to_trade: "HIGH"
  require_high_confidence_for_reversal: true
  enable_partial_tp: true
  partial_tp_levels:
    - {profit_pct: 0.01, position_pct: 0.5}
    - {profit_pct: 0.02, position_pct: 0.5}
position_management:
  base_usdt_amount: 20
  max_position_ratio: 0.05  # 5% max
  high_confidence_multiplier: 1.2
```

**Expected Performance:**
- Lower returns, lower drawdown
- Win rate: 65-70%
- Max drawdown: <3%
- Suitable for: Risk-averse traders, beginners

#### Balanced Profile (Recommended)

```yaml
# Balance between risk and reward
risk:
  min_confidence_to_trade: "MEDIUM"
  require_high_confidence_for_reversal: false
  enable_partial_tp: true
  partial_tp_levels:
    - {profit_pct: 0.02, position_pct: 0.5}
    - {profit_pct: 0.04, position_pct: 0.5}
position_management:
  base_usdt_amount: 30
  max_position_ratio: 0.10  # 10% max
  high_confidence_multiplier: 1.5
```

**Expected Performance:**
- Balanced risk/reward
- Win rate: 55-65%
- Max drawdown: <5%
- Suitable for: Most traders, intermediate level

#### Aggressive Profile

```yaml
# Maximum returns, higher risk
risk:
  min_confidence_to_trade: "LOW"
  require_high_confidence_for_reversal: false
  enable_partial_tp: false  # Single large TP
  tp_high_confidence_pct: 0.05  # 5% target
position_management:
  base_usdt_amount: 50
  max_position_ratio: 0.20  # 20% max (⚠️ high risk)
  high_confidence_multiplier: 2.0
```

**Expected Performance:**
- Higher returns, higher drawdown
- Win rate: 45-55%
- Max drawdown: >8%
- Suitable for: Experienced traders only

---

## Monitoring

### Log Files

```bash
logs/
├── trader.log                      # Main strategy log
├── trader_error.log                # Errors and warnings
├── trader_YYYYMMDD_HHMMSS.log     # Archived sessions
└── ai_strategy.log                 # Strategy-specific logs
```

### Real-Time Monitoring

```bash
# Monitor all activity
tail -f logs/trader.log

# Monitor signals only
tail -f logs/trader.log | grep "🤖 Signal:"

# Monitor position changes
tail -f logs/trader.log | grep -E "Position opened|Position closed"

# Monitor errors
tail -f logs/trader_error.log

# Monitor trailing stops
tail -f logs/trader.log | grep "Trailing"

# Monitor layer SL/TP activity
tail -f logs/trader.log | grep "layer"
```

### Performance Tracking

```bash
# Count trades today
grep "Order filled" logs/trader.log | grep $(date +%Y-%m-%d) | wc -l

# Signal distribution
grep "🤖 Signal:" logs/trader.log | grep -oE "Signal: \w+" | sort | uniq -c

# Win/loss tracking
grep "Position closed" logs/trader.log | grep "P&L:" | tail -20

# Layer SL/TP statistics
grep "Layer created" logs/trader.log | wc -l
grep "Emergency SL" logs/trader.log | wc -l
```

### Telegram Monitoring

If Telegram is enabled:
- Real-time notifications on your phone
- `/status` command for quick overview
- `/position` command for current holdings
- Pause/resume trading remotely

### External Monitoring

1. **Binance App**:
   - Live positions and P&L
   - Order book and execution
   - Account balance

2. **TradingView**:
   - Chart analysis
   - Technical indicator visualization
   - Price alerts

3. **System Resources**:
   ```bash
   # Check if strategy is running
   ps aux | grep main_live.py

   # Monitor CPU/memory
   top -p $(pgrep -f main_live.py)

   # Disk usage
   df -h
   du -sh logs/
   ```

---

## Troubleshooting

### Common Issues

#### 1. Indicators Not Initialized

**Error:** `Indicators not yet initialized, skipping analysis`

**Cause:** Strategy needs 50+ bars before indicators are ready (SMA50 requires 50 periods)

**Solution:**
```bash
# Wait for initialization
# 30-minute bars (default): ~25 hours
# 1-minute bars: ~50 minutes

# Check progress
grep "initialized" logs/trader.log
```

#### 2. Order Quantity Below Minimum

**Error:** `Order quantity below minimum`

**Cause:** Position size < 0.001 BTC (Binance minimum)

**Solution:**
```yaml
# Increase base position size in configs/base.yaml
position_management:
  base_usdt_amount: 80  # Increase from 30

# At $70,000 BTC:
# 80 / 70000 = 0.00114 BTC ✅ (above 0.001 minimum)
```

#### 3. WebSocket Connection Failed

**Error:** `WebSocket connection failed`

**Solution:**
```bash
# Check internet connectivity
ping binance.com

# Check Binance API status
curl -I https://fapi.binance.com/fapi/v1/ping

# Check DNS
nslookup fstream.binance.com

# If in restricted region, use VPN
```

#### 5. API Rate Limit Exceeded

**Error:** `Rate limit exceeded`

**Solution:**
```yaml
# Increase analysis interval in configs/base.yaml
timer_interval_sec: 1800  # 30 minutes instead of 15

# Check for multiple running instances
ps aux | grep main_live.py  # Should only show one

# Wait 1-5 minutes for rate limit reset
```

#### 6. Sentiment Data Fetch Failed

**Warning:** `Failed to fetch sentiment data`

**Impact:** AI analysis continues with technical data only (60% weight instead of 90%)

**Solution:**
```bash
# Check Binance API
curl https://fapi.binance.com/fapi/v1/ping

# Temporarily disable sentiment
# Edit configs/base.yaml:
sentiment:
  enabled: false
```

### Emergency Procedures

#### Stop Trading Immediately

```bash
# Method 1: Keyboard interrupt (if in terminal)
Ctrl+C

# Method 2: Kill process
ps aux | grep main_live.py
kill <PID>

# Method 3: Stop script
./stop_trader.sh

# Verify stopped
ps aux | grep main_live.py  # Should return nothing
```

#### Close All Positions Manually

**Via Binance Web:**
1. Login → Futures → Positions
2. Find BTCUSDT-PERP position
3. Click "Close" → "Market Close"

**Via Binance App:**
1. Futures → Positions
2. BTCUSDT-PERP
3. Swipe to close

#### Backup Data

```bash
# Backup logs
mkdir -p logs/backups/$(date +%Y%m%d)
cp logs/trader*.log logs/backups/$(date +%Y%m%d)/

# Backup configuration
cp configs/base.yaml configs/base.yaml.backup

# Backup .env (BE CAREFUL - contains secrets)
cp .env .env.backup
chmod 600 .env.backup
```

### Debug Mode

```yaml
# Enable verbose logging in configs/development.yaml
logging:
  level: "DEBUG"  # Instead of "INFO"

# Restart and monitor
./restart_trader.sh
tail -f logs/trader.log
```

---

## Performance Expectations

### Target Metrics

Based on backtesting and live trading with v1.2.x features:

| Metric | Target | Notes |
|--------|--------|-------|
| **Weekly Return** | 0.5-1.5% | Net of fees, with partial TP and trailing stops |
| **Monthly Return** | 2-6% | Compounded weekly |
| **Annualized Return** | 26-72% | Assuming consistent performance |
| **Sharpe Ratio** | >1.5 | Risk-adjusted returns |
| **Max Drawdown** | <5% | Peak to trough |
| **Win Rate** | 60-70% | With partial TP improving win rate |
| **Avg Win/Loss** | 2.0:1 | Reward:Risk ratio |

### Assumptions

- Market conditions: Normal volatility (not extreme crashes/pumps)
- Leverage: 10x cross-margin
- Trading frequency: 3-6 signals per day with 20-minute analysis
- Position duration: 2-12 hours average
- Binance fees: Maker 0.02%, Taker 0.04%
- Slippage: ~0.01% average
- Features enabled: Per-layer SL/TP, Emergency SL escalation

### Realistic Scenarios

#### Best Case (Strong Trending Market)

```
Starting Capital: $400
Monthly Return: 5-7%
Ending Capital: $420-428
Profit: $20-28
Key Factor: Trailing stops capture extended trends
```

#### Average Case (Mixed Market)

```
Starting Capital: $400
Monthly Return: 3-4%
Ending Capital: $412-416
Profit: $12-16
Key Factor: Partial TP locks in gains early
```

#### Worst Case (Choppy/Unfavorable)

```
Starting Capital: $400
Monthly Return: -1% to +1%
Ending Capital: $396-404
Loss/Profit: -$4 to +$4
Key Factor: Stop losses limit downside
```

### Performance by Feature

| Configuration | Avg Return | Win Rate | Max DD | Notes |
|---------------|------------|----------|--------|-------|
| Base (no advanced features) | 2-3% | 55% | -5% | Original strategy |
| + SL/TP | 3-4% | 58% | -4% | Better risk management |
| + Partial TP | 3.5-4.5% | 62% | -3.5% | Improved win rate |
| + Trailing Stop | 4-5% | 65% | -3% | Captures trends |
| All Features | 5-6% | 68% | -2.5% | Optimal combination |

### Important Disclaimers

⚠️ **Past performance does not guarantee future results**

- Market conditions constantly change
- AI models can make mistakes
- High leverage (10x) amplifies both gains and losses
- Fees and slippage reduce net returns
- Unexpected events (flash crashes, news) can cause significant losses
- No trading system is profitable 100% of the time

### Performance Tracking Template

```
Week 1 (Nov 17-24, 2025):
- Starting: $400.00
- Ending: $418.50
- Return: +4.63%
- Trades: 28 (19 wins, 9 losses)
- Win Rate: 68%
- Max DD: -1.2%
- Features: Full suite enabled

Week 2:
- Starting: $418.50
- Ending: $425.20
- Return: +1.60%
...

Monthly Summary:
- Total Return: +6.3%
- Sharpe Ratio: 1.8
- Total Trades: 112
- Win Rate: 65%
```

---

## Documentation

### Core Documentation

- **[README.md](README.md)** - This file (overview and setup)
- **[CLAUDE.md](CLAUDE.md)** - Authoritative system reference (architecture decisions, file structure)
- **[docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md)** - System architecture overview
- **[docs/SECURITY.md](docs/SECURITY.md)** - Security best practices

### External Resources

- **NautilusTrader**: [https://nautilustrader.io/docs/](https://nautilustrader.io/docs/)
- **DeepSeek API**: [https://platform.deepseek.com/docs](https://platform.deepseek.com/docs)
- **Binance Futures API**: [https://binance-docs.github.io/apidocs/futures/en/](https://binance-docs.github.io/apidocs/futures/en/)
- **Binance Long/Short Ratio**: [https://www.binance.com/en/futures/funding-history/4](https://www.binance.com/en/futures/funding-history/4)

---

## Disclaimer

### Risk Warning

**⚠️ CRYPTOCURRENCY TRADING INVOLVES SUBSTANTIAL RISK OF LOSS**

This software is provided for **educational and research purposes only**. By using this strategy, you acknowledge:

- ❌ **No Guarantees**: Past performance does not guarantee future results
- ❌ **Loss Risk**: You can lose your entire investment
- ❌ **Leverage Risk**: 10x leverage amplifies losses as well as gains
- ❌ **AI Limitations**: AI models can make incorrect predictions
- ❌ **Market Risk**: Crypto markets are highly volatile and unpredictable
- ❌ **Technical Risk**: Software bugs, API failures, or network issues can occur
- ❌ **Regulatory Risk**: Cryptocurrency regulations vary by jurisdiction
- ❌ **Operational Risk**: Exchange outages, liquidations, funding rate changes

### Recommendations

✅ **DO:**
- Start with small capital ($500-1000) you can afford to lose
- Use testnet or paper trading first (if available)
- Monitor closely for the first few weeks
- Understand the code and features before running live
- Set conservative risk limits initially
- Keep API keys secure (no withdrawal permissions)
- Maintain adequate system resources and backups
- Enable all risk management features
- Start with conservative configuration profile
- Test each feature individually before combining

❌ **DON'T:**
- Invest more than you can afford to lose
- Use maximum leverage without understanding risks
- Leave strategy unmonitored for long periods
- Share your API keys or .env file
- Modify code without thorough testing
- Rely solely on AI decisions without human oversight
- Disable stop loss protection
- Trade with insufficient capital (<$500)
- Run multiple instances with same API keys
- Ignore error messages or warnings

### Legal Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Trading cryptocurrencies is regulated differently in each jurisdiction. Ensure compliance with your local laws before trading. This software is not financial advice and should not be considered as such.

---

## License

This project is for **educational and research purposes only**.

- No warranty or guarantee of profitability
- Use at your own risk
- Not financial advice
- Not investment advice

---

## Acknowledgments

**Built with:**
- [**NautilusTrader**](https://github.com/nautechsystems/nautilus_trader) - Professional algorithmic trading platform
- [**DeepSeek**](https://www.deepseek.com/) - Advanced AI language model for decision making
- [**Binance**](https://www.binance.com/) - Long/Short Ratio API for sentiment data
- [**Binance**](https://www.binance.com/) - Cryptocurrency exchange and API
- [**python-telegram-bot**](https://python-telegram-bot.org/) - Telegram bot library

**Special Thanks:**
- NautilusTrader community for the excellent framework
- DeepSeek team for accessible AI API
- Open source community for Python libraries
- Contributors and testers

---

## Support & Contact

### For Issues

1. Check this README thoroughly
2. Review relevant feature documentation
3. Check logs in `logs/` directory
4. Search existing GitHub issues (if applicable)
5. Review [TROUBLESHOOTING](#troubleshooting) section

### For Development

- **Python**: 3.12+
- **NautilusTrader**: 1.224.0+
- **Testing**: Refer to feature documentation

---

**Version**: 19.2
**Last Updated**: February 2026
**Status**: Production Ready
**Branch**: `main`

---

*Trade responsibly and never risk more than you can afford to lose. This strategy is a tool, not a guarantee of profits. Always maintain proper risk management and monitor your positions actively.*

---

## Quick Links

- [Installation](#installation) | [Configuration](#configuration) | [Usage](#usage)
- [Features](#features) | [Risk Management](#risk-management) | [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting) | [Documentation](#documentation)
- [Performance](#performance-expectations) | [Disclaimer](#disclaimer)

---

**Happy Trading! 🚀**
