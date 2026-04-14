#!/usr/bin/env python3
"""
Test script for Multi-Agent Trading Analyzer

Usage:
    python test_multi_agent.py

This will run a simulated analysis with sample data to verify the
Bull/Bear debate mechanism works correctly.
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.multi_agent_analyzer import MultiAgentAnalyzer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    # Load environment
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        logger.error("DEEPSEEK_API_KEY not found in environment")
        return

    logger.info("=" * 60)
    logger.info("Multi-Agent Trading Analyzer Test")
    logger.info("=" * 60)

    # Initialize analyzer
    analyzer = MultiAgentAnalyzer(
        api_key=api_key,
        model="deepseek-chat",
        temperature=0.3,
        debate_rounds=2,  # 2 rounds of Bull vs Bear
    )

    # Sample technical data (simulating a bullish scenario)
    technical_data = {
        "price": 105000.00,
        "price_change": 2.5,
        "overall_trend": "BULLISH",
        "short_term_trend": "BULLISH",
        "macd_trend": "BULLISH",
        "sma_5": 104500.00,
        "sma_20": 103000.00,
        "sma_50": 100000.00,
        "rsi": 58.5,
        "macd": 150.5,
        "macd_signal": 120.3,
        "macd_histogram": 30.2,
        "bb_upper": 108000.00,
        "bb_middle": 103000.00,
        "bb_lower": 98000.00,
        "bb_position": 0.70,
        "resistance": 108000.00,
        "support": 102000.00,
        "volume_ratio": 1.35,
    }

    # Sample sentiment data (slightly bullish)
    sentiment_data = {
        "positive_ratio": 0.58,
        "negative_ratio": 0.42,
        "net_sentiment": 0.16,
    }

    # No current position
    current_position = None

    # Price data for SL/TP calculations
    price_data = {"price": 105000.00}

    logger.info("\nInput Data:")
    logger.info(f"  Price: ${technical_data['price']:,.2f}")
    logger.info(f"  Trend: {technical_data['overall_trend']}")
    logger.info(f"  RSI: {technical_data['rsi']}")
    logger.info(f"  Sentiment: {sentiment_data['net_sentiment']:+.3f}")

    logger.info("\nRunning multi-agent analysis (this may take 30-60 seconds)...")

    # Run analysis
    try:
        result = analyzer.analyze(
            symbol="BTCUSDT",
            technical_report=technical_data,
            sentiment_report=sentiment_data,
            current_position=current_position,
            price_data=price_data,
        )

        logger.info("\n" + "=" * 60)
        logger.info("ANALYSIS RESULT")
        logger.info("=" * 60)

        logger.info(f"\nSignal: {result.get('signal', 'N/A')}")
        logger.info(f"Confidence: {result.get('confidence', 'N/A')}")
        logger.info(f"Risk Level: {result.get('risk_level', 'N/A')}")
        logger.info(f"Position Size: {result.get('position_size_pct', 0)}%")
        logger.info(f"Stop Loss: ${result.get('stop_loss', 0):,.2f}")
        logger.info(f"Take Profit: ${result.get('take_profit', 0):,.2f}")
        logger.info(f"\nReason: {result.get('reason', 'N/A')}")
        logger.info(f"\nDebate Summary: {result.get('debate_summary', 'N/A')}")

        # Show judge decision if available
        judge = result.get('judge_decision', {})
        if judge:
            logger.info(f"\nJudge Decision:")
            logger.info(f"  Winner: {judge.get('winning_side', 'N/A')}")
            logger.info(f"  Key Reasons: {judge.get('key_reasons', [])}")

        # Show debate transcript
        logger.info("\n" + "=" * 60)
        logger.info("FULL DEBATE TRANSCRIPT")
        logger.info("=" * 60)
        logger.info(analyzer.get_last_debate())

        # Test with bearish scenario
        logger.info("\n" + "=" * 60)
        logger.info("TESTING BEARISH SCENARIO")
        logger.info("=" * 60)

        technical_data_bearish = {
            "price": 95000.00,
            "price_change": -3.2,
            "overall_trend": "BEARISH",
            "short_term_trend": "BEARISH",
            "macd_trend": "BEARISH",
            "sma_5": 96000.00,
            "sma_20": 98000.00,
            "sma_50": 100000.00,
            "rsi": 32.5,
            "macd": -180.5,
            "macd_signal": -120.3,
            "macd_histogram": -60.2,
            "bb_upper": 100000.00,
            "bb_middle": 97000.00,
            "bb_lower": 94000.00,
            "bb_position": 0.25,
            "resistance": 98000.00,
            "support": 93000.00,
            "volume_ratio": 1.8,
        }

        sentiment_data_bearish = {
            "positive_ratio": 0.35,
            "negative_ratio": 0.65,
            "net_sentiment": -0.30,
        }

        result2 = analyzer.analyze(
            symbol="BTCUSDT",
            technical_report=technical_data_bearish,
            sentiment_report=sentiment_data_bearish,
            current_position=None,
            price_data={"price": 95000.00},
        )

        logger.info(f"\nBearish Scenario Result:")
        logger.info(f"  Signal: {result2.get('signal', 'N/A')}")
        logger.info(f"  Confidence: {result2.get('confidence', 'N/A')}")
        logger.info(f"  Reason: {result2.get('reason', 'N/A')}")

        logger.info("\n" + "=" * 60)
        logger.info("TEST COMPLETED SUCCESSFULLY")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
