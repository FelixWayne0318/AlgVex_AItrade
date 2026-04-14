# AlgVex Testing & Verification Guide (v23.0)

This guide covers the testing and verification tools available for the AlgVex trading system.

## Table of Contents

1. [Testing Pyramid](#testing-pyramid)
2. [Automated Diagnostics (Primary)](#automated-diagnostics-primary)
3. [Unit Tests (pytest)](#unit-tests-pytest)
4. [Regression Detection](#regression-detection)
5. [Manual Verification](#manual-verification)
6. [Live Testing Protocol](#live-testing-protocol)

---

## Testing Pyramid

```
                 /\
                /  \    Live Trading
               /____\   (production, monitored)
              /      \
             /        \   Real-time Diagnostics
            /__________\  (13 stages, real API calls)
           /            \
          /              \  Offline Diagnostics
         /________________\ (static analysis, math verification)
        /                  \
       /                    \  Unit Tests (pytest)
      /______________________\ (49+ tests, isolated functions)
```

---

## Automated Diagnostics (Primary)

The diagnostic suite is the **primary verification tool** for AlgVex. It covers more ground than unit tests and validates the entire AI decision pipeline.

### Real-time Diagnostics (13 Stages)

```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/diagnose_realtime.py
```

| Stage | Description |
|-------|-------------|
| 1 | Service health (systemd status, errors, resources) |
| 2 | API connectivity (Binance, DeepSeek, Coinalyze) |
| 3 | Code integrity (P1.1-P1.94: 94 static checks) |
| 4 | Configuration validation |
| 5 | Technical indicator calculation |
| 6 | Market data fetching |
| 7 | MTF components (1D/4H/30M layers) |
| 8 | Architecture verification |
| 9 | Math verification (51 formula tests) |
| 10 | Order flow simulation (14 scenarios) |
| 11 | Position state check |
| 12 | AI decision (7 real API calls, v23.0 Entry Timing Agent) |
| 13 | Summary + machine-readable JSON |

**Options**:
```bash
python3 scripts/diagnose_realtime.py --export           # Export to logs/
python3 scripts/diagnose_realtime.py --export --push    # Export + push to GitHub
python3 scripts/diagnose_realtime.py --summary          # Summary only
```

### Offline Diagnostics (No API)

```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/diagnose.py --quick    # Fast check (no AI calls)
```

---

## Unit Tests (pytest)

### Running Tests

```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 -m pytest tests/ -v
```

### Test Files (15 files, 49+ tests)

| File | Tests | Coverage |
|------|:-----:|----------|
| `test_config_manager.py` | 20 | ConfigManager validation (30+ rules) |
| `test_trading_logic.py` | 29 | R/R gates, SL/TP, trade evaluation (A+-F grades) |
| `test_strategy_components.py` | — | Position sizing, confidence scaling |
| `test_integration_mock.py` | — | End-to-end flow with mocked APIs |
| `test_multi_agent.py` | — | MultiAgentAnalyzer prompt construction |
| `test_bracket_order.py` | — | Bracket order submission flow |
| `test_telegram.py` | — | Telegram bot messaging |
| `test_telegram_commands.py` | — | Telegram command handling + PIN |
| `test_orderbook.py` | — | Order book processing |
| `test_binance_patch.py` | — | Binance enum/position patches |
| `test_command_listener.py` | — | Command listener infrastructure |
| `test_rounding_fix.py` | — | Price/quantity rounding |
| `test_sl_fix.py` | — | Stop loss calculation |
| `test_implementation_plan.py` | — | Implementation plan validation |
| `test_v19_1_verification.py` | — | v19.1 Extension Ratio verification |

### Configuration

- `pytest.ini`: Test configuration
- `tests/conftest.py`: Shared fixtures and mocks

---

## Regression Detection

### Smart Commit Analyzer

Run after **every code change** before committing:

```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/smart_commit_analyzer.py
```

Validates all critical code patterns still pass.

### Logic Sync Checker

Run after modifying any **SSoT (Single Source of Truth)** file:

```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/check_logic_sync.py          # 11 sync checks
  python3 scripts/check_logic_sync.py --verbose # Show all passing items
```

SSoT files that trigger sync checks:
- `utils/shared_logic.py` (CVD trend, Extension Ratio, Volatility Regime)
- `strategy/trading_logic.py` (mechanical SL/TP, trade evaluation)
- `utils/telegram_bot.py` (side_to_cn terminology)
- `agents/prompt_constants.py` (INDICATOR_DEFINITIONS, SIGNAL_CONFIDENCE_MATRIX)

### S/R Calibration Verification

```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/calibrate_hold_probability.py --dry-run  # Preview without saving
```

### Extension Ratio Verification

```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/verify_extension_ratio.py  # 47-check verification suite
```

---

## Manual Verification

### Configuration Dry Run

```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 main_live.py --env development --dry-run
```

Validates configuration loads correctly without starting trading.

### End-to-End Trade Pipeline Test

```bash
cd /home/linuxuser/nautilus_AlgVex && source venv/bin/activate && \
  python3 scripts/e2e_trade_pipeline_test.py
```

---

## Live Testing Protocol

### Prerequisites

- All unit tests pass (`pytest tests/ -v`)
- All diagnostic checks pass (`diagnose_realtime.py`)
- Regression detection clear (`smart_commit_analyzer.py`)
- Logic sync verified (`check_logic_sync.py`)

### Deployment

```bash
# Standard deployment
cd /home/linuxuser/nautilus_AlgVex && git pull origin main && \
  chmod +x setup.sh && ./setup.sh

# Monitor
sudo systemctl restart nautilus-trader
sudo journalctl -u nautilus-trader -f --no-hostname
```

### Safety Checklist

- [ ] `smart_commit_analyzer.py` passes
- [ ] `check_logic_sync.py` passes
- [ ] `diagnose.py --quick` passes
- [ ] Configuration reviewed (`--dry-run`)
- [ ] Telegram alerts enabled
- [ ] Position limits configured in `configs/production.yaml`

---

## Troubleshooting

### Tests Failing

```bash
# Check Python version (must be 3.12+)
python3 --version

# Run specific test with verbose output
python3 -m pytest tests/test_trading_logic.py -v

# Run single test function
python3 -m pytest tests/test_config_manager.py::test_specific -v
```

### Diagnostics Failing

```bash
# Check service status
sudo systemctl status nautilus-trader

# Check recent errors
sudo journalctl -u nautilus-trader -n 50 --no-hostname | grep -i error

# Full diagnostics with export
python3 scripts/diagnose_realtime.py --export
# Review: logs/diagnosis_*.txt
```
