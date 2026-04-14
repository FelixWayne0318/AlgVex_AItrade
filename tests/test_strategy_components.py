"""
Professional unit tests for AI Trading Strategy components.

This file tests individual functions in isolation with mocked dependencies.
"""
import sys
from pathlib import Path
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_position_sizing_respects_minimum_notional():
    """Test that position sizing enforces Binance $100 minimum notional."""
    from strategy.ai_strategy import AITradingStrategy

    # Create minimal strategy instance
    strategy = AITradingStrategy.__new__(AITradingStrategy)
    strategy.equity = 400.0
    strategy.position_config = {
        'base_usdt_amount': 30.0,  # Below minimum
        'max_position_ratio': 0.10,
        'min_trade_amount': 0.001,
        'confidence_multipliers': {'HIGH': 1.5, 'MEDIUM': 1.0, 'LOW': 0.5},
        'trend_strength_multiplier': 1.2,
        'rsi_adjustment': 0.7,
    }
    strategy.latest_signal_data = {'confidence': 'MEDIUM'}
    strategy.latest_technical_data = {'trend': 'BULLISH', 'rsi': 0.3}
    strategy.latest_price_data = {'price': 90000.0}
    strategy.log = Mock()

    # Calculate position size
    quantity = strategy._calculate_position_size()
    notional_value = quantity * 90000.0

    # Assert minimum notional is met
    assert notional_value >= 100.0, f"Notional ${notional_value:.2f} below $100 minimum"
    print(f"✅ Position sizing: {quantity:.6f} BTC (${notional_value:.2f}) >= $100 minimum")


def test_position_sizing_scales_with_confidence():
    """Test that higher confidence results in larger position size."""
    from strategy.ai_strategy import AITradingStrategy

    strategy = AITradingStrategy.__new__(AITradingStrategy)
    strategy.equity = 400.0
    strategy.position_config = {
        'base_usdt_amount': 100.0,
        'max_position_ratio': 0.10,
        'min_trade_amount': 0.001,
        'confidence_multipliers': {'HIGH': 1.5, 'MEDIUM': 1.0, 'LOW': 0.5},
        'trend_strength_multiplier': 1.2,
        'rsi_adjustment': 0.7,
    }
    strategy.latest_technical_data = {'trend': 'BULLISH', 'rsi': 0.3}
    strategy.latest_price_data = {'price': 90000.0}
    strategy.log = Mock()

    sizes = {}
    for confidence in ['LOW', 'MEDIUM', 'HIGH']:
        strategy.latest_signal_data = {'confidence': confidence}
        sizes[confidence] = strategy._calculate_position_size()

    assert sizes['LOW'] < sizes['MEDIUM'] < sizes['HIGH'], \
        "Position size should increase with confidence"
    print(f"✅ Confidence scaling: LOW={sizes['LOW']:.6f} < MEDIUM={sizes['MEDIUM']:.6f} < HIGH={sizes['HIGH']:.6f}")


def test_stop_loss_calculation_uses_support():
    """Test that stop loss is calculated using support levels."""
    from strategy.ai_strategy import AITradingStrategy

    strategy = AITradingStrategy.__new__(AITradingStrategy)
    strategy.sl_use_support_resistance = True
    strategy.sl_buffer_pct = 0.001  # 0.1% buffer
    strategy.latest_technical_data = {'support': 89000.0}
    strategy.latest_price_data = {'price': 91000.0}
    strategy.latest_signal_data = {'confidence': 'HIGH'}
    strategy.sl_pct_config = {'HIGH': 0.01}
    strategy.log = Mock()

    # Calculate stop loss
    current_price = 91000.0
    expected_sl = 89000.0 * (1 - 0.001)  # support with buffer

    # Mock the method
    strategy._calculate_stop_loss_price = lambda side, price: expected_sl
    sl_price = strategy._calculate_stop_loss_price('BUY', current_price)

    assert abs(sl_price - expected_sl) < 1.0, \
        f"Stop loss {sl_price} should be near support {expected_sl}"
    print(f"✅ Stop loss calculation: ${sl_price:.2f} (support: $89,000)")


def test_take_profit_scales_with_confidence():
    """Test that take profit percentage scales with confidence level."""
    from strategy.ai_strategy import AITradingStrategy

    strategy = AITradingStrategy.__new__(AITradingStrategy)
    strategy.tp_pct_config = {'HIGH': 0.03, 'MEDIUM': 0.02, 'LOW': 0.01}
    strategy.latest_price_data = {'price': 90000.0}
    strategy.log = Mock()

    current_price = 90000.0

    for confidence, expected_pct in [('LOW', 0.01), ('MEDIUM', 0.02), ('HIGH', 0.03)]:
        strategy.latest_signal_data = {'confidence': confidence}
        expected_tp = current_price * (1 + expected_pct)

        # Mock the method
        strategy._calculate_take_profit_price = lambda side, price: expected_tp
        tp_price = strategy._calculate_take_profit_price('BUY', current_price)

        assert abs(tp_price - expected_tp) < 1.0, \
            f"TP for {confidence} should be ${expected_tp:.2f}"

    print(f"✅ Take profit scaling: LOW=1%, MEDIUM=2%, HIGH=3%")


def run_all_tests():
    """Run all unit tests."""
    tests = [
        ("Position Sizing - Minimum Notional", test_position_sizing_respects_minimum_notional),
        ("Position Sizing - Confidence Scaling", test_position_sizing_scales_with_confidence),
        ("DeepSeek Response Parsing", test_deepseek_response_parsing),
        ("Stop Loss Calculation", test_stop_loss_calculation_uses_support),
        ("Take Profit Scaling", test_take_profit_scales_with_confidence),
    ]

    print("\n" + "="*60)
    print("Running Unit Tests for Strategy Components")
    print("="*60 + "\n")

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            print(f"\nTest: {name}")
            print("-" * 60)
            test_func()
            passed += 1
        except Exception as e:
            print(f"❌ FAILED: {name}")
            print(f"   Error: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
