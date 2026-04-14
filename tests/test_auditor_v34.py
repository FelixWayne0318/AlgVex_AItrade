"""
Tests for v34.0 auditor enhancements:
1. Phantom citation detection (AI cites unavailable data)
2. Narrative misread detection (contradictory adjective for indicator value)
3. Contradictory data omission detection (informational flag)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.ai_quality_auditor import AIQualityAuditor


class TestPhantomCitation:
    """Test _check_phantom_citations: AI citing values from unavailable sources."""

    def setup_method(self):
        self.auditor = AIQualityAuditor()

    def test_sentiment_unavailable_but_cited(self):
        """Sentiment degraded, AI fabricates Long Ratio."""
        text = "Long Ratio 62.5% indicates crowded longs"
        errors = self.auditor._check_phantom_citations(
            text,
            sentiment_data=None,
            order_flow_data={'buy_ratio': 0.55},
            derivatives_data={'funding_rate': {'current_pct': 0.01}},
            orderbook_data={'obi': {'weighted': 0.3}},
        )
        assert len(errors) == 1
        assert 'Phantom' in errors[0]
        assert 'Long Ratio' in errors[0]

    def test_sentiment_degraded_but_cited(self):
        """Sentiment marked degraded, AI still cites ratio."""
        text = "Short Ratio 38.0% is bearish"
        errors = self.auditor._check_phantom_citations(
            text,
            sentiment_data={'degraded': True, 'positive_ratio': 0.0, 'negative_ratio': 0.0},
            order_flow_data=None,
            derivatives_data=None,
            orderbook_data=None,
        )
        assert len(errors) == 1
        assert 'Short Ratio' in errors[0]

    def test_derivatives_unavailable_but_fr_cited(self):
        """Derivatives unavailable, AI fabricates Funding Rate."""
        text = "FR: 0.01234% longs pay shorts"
        errors = self.auditor._check_phantom_citations(
            text,
            sentiment_data={'positive_ratio': 0.55, 'negative_ratio': 0.45},
            order_flow_data={'buy_ratio': 0.5},
            derivatives_data=None,
            orderbook_data={'obi': {'weighted': 0.1}},
        )
        assert len(errors) == 1
        assert 'Derivatives unavailable' in errors[0]

    def test_orderbook_unavailable_but_obi_cited(self):
        """Orderbook unavailable, AI fabricates OBI."""
        text = "OBI: 0.35 shows buy pressure"
        errors = self.auditor._check_phantom_citations(
            text,
            sentiment_data=None,
            order_flow_data=None,
            derivatives_data=None,
            orderbook_data=None,
        )
        # Should catch OBI phantom + possibly sentiment phantoms if no specific % in text
        obi_errors = [e for e in errors if 'OBI' in e]
        assert len(obi_errors) == 1
        assert 'Orderbook unavailable' in obi_errors[0]

    def test_order_flow_unavailable_but_buy_ratio_cited(self):
        """Order flow unavailable, AI fabricates Buy Ratio."""
        text = "Buy Ratio 71.0% shows aggressive buying"
        errors = self.auditor._check_phantom_citations(
            text,
            sentiment_data={'positive_ratio': 0.6, 'negative_ratio': 0.4},
            order_flow_data=None,
            derivatives_data={'funding_rate': {'current_pct': 0.01}},
            orderbook_data={'obi': {'weighted': 0.2}},
        )
        assert len(errors) == 1
        assert 'Buy Ratio' in errors[0]

    def test_no_phantom_when_data_available(self):
        """All data available — no phantom errors."""
        text = "Long Ratio 60.0%, FR: 0.01000%, Buy Ratio 55.0%, OBI: 0.20"
        errors = self.auditor._check_phantom_citations(
            text,
            sentiment_data={'positive_ratio': 0.6, 'negative_ratio': 0.4},
            order_flow_data={'buy_ratio': 0.55},
            derivatives_data={'funding_rate': {'current_pct': 0.01}},
            orderbook_data={'obi': {'weighted': 0.2}},
        )
        assert len(errors) == 0

    def test_no_phantom_when_no_specific_values(self):
        """Data unavailable but AI doesn't cite specific values — no error."""
        text = "Sentiment data was not available for this analysis"
        errors = self.auditor._check_phantom_citations(
            text,
            sentiment_data=None,
            order_flow_data=None,
            derivatives_data=None,
            orderbook_data=None,
        )
        assert len(errors) == 0


class TestNarrativeMisread:
    """Test _check_narrative_misread: contradictory adjective for RSI."""

    def setup_method(self):
        self.auditor = AIQualityAuditor()

    def test_rsi_high_but_exhaustion_claimed(self):
        """RSI=65 is bullish, AI says exhaustion."""
        gt_tech = {'rsi': 65.0}
        text = "30M RSI 65 indicates momentum exhaustion and weakening"
        errors = self.auditor._check_narrative_misread(text, gt_tech)
        assert len(errors) >= 1
        assert 'exhaustion' in errors[0].lower() or 'weakness' in errors[0].lower()

    def test_rsi_low_but_strong_claimed(self):
        """RSI=32 is bearish, AI says strong momentum."""
        gt_tech = {'rsi': 32.0}
        text = "30M RSI shows strong momentum with bullish signal"
        errors = self.auditor._check_narrative_misread(text, gt_tech)
        assert len(errors) >= 1
        assert 'strong' in errors[0].lower() or 'bullish' in errors[0].lower()

    def test_rsi_neutral_no_error(self):
        """RSI=50 is ambiguous — no error regardless of adjective."""
        gt_tech = {'rsi': 50.0}
        text = "30M RSI shows exhaustion and weakening momentum"
        errors = self.auditor._check_narrative_misread(text, gt_tech)
        assert len(errors) == 0

    def test_rsi_high_with_correct_description(self):
        """RSI=65 described as strong — no error."""
        gt_tech = {'rsi': 65.0}
        text = "30M RSI 65 confirms strong bullish momentum"
        errors = self.auditor._check_narrative_misread(text, gt_tech)
        assert len(errors) == 0

    def test_4h_rsi_misread(self):
        """4H RSI misread should also be caught."""
        gt_tech = {
            'rsi': 55.0,  # 30M neutral
            'mtf_decision_layer': {'rsi': 68.0},  # 4H bullish
        }
        text = "4H RSI衰竭信号明显"
        errors = self.auditor._check_narrative_misread(text, gt_tech)
        assert len(errors) >= 1

    def test_no_rsi_data_no_error(self):
        """No RSI in ground truth — skip gracefully."""
        gt_tech = {'adx': 30.0}
        text = "RSI shows exhaustion"
        errors = self.auditor._check_narrative_misread(text, gt_tech)
        assert len(errors) == 0


class TestContradictoryOmission:
    """Test _check_contradictory_omission: Bull/Bear ignoring contradictory dims."""

    def setup_method(self):
        self.auditor = AIQualityAuditor()

    def test_bull_ignores_bearish_order_flow(self):
        """Bull doesn't mention order flow when it's clearly bearish."""
        scores = {
            'order_flow': {'direction': 'BEARISH', 'score': -0.7},
            'momentum': {'direction': 'BULLISH', 'score': 0.5},
        }
        text = "Price is above SMA200 with strong momentum"
        flags = self.auditor._check_contradictory_omission('bull', text, scores)
        assert len(flags) >= 1
        assert 'order_flow' in flags[0]

    def test_bear_ignores_bullish_momentum(self):
        """Bear doesn't mention momentum when it's clearly bullish."""
        scores = {
            'order_flow': {'direction': 'BEARISH', 'score': -0.5},
            'momentum': {'direction': 'BULLISH', 'score': 0.8},
        }
        text = "CVD shows distribution, order flow is weak"
        flags = self.auditor._check_contradictory_omission('bear', text, scores)
        assert len(flags) >= 1
        assert 'momentum' in flags[0]

    def test_bull_addresses_bearish_data_no_flag(self):
        """Bull mentions order flow even though it's bearish — no flag."""
        scores = {
            'order_flow': {'direction': 'BEARISH', 'score': -0.7},
        }
        text = "Despite weak CVD, the trend structure remains intact"
        flags = self.auditor._check_contradictory_omission('bull', text, scores)
        assert len(flags) == 0

    def test_neutral_score_no_flag(self):
        """Neutral dimensions should never be flagged."""
        scores = {
            'order_flow': {'direction': 'NEUTRAL', 'score': 0.0},
            'momentum': {'direction': 'NEUTRAL', 'score': 0.0},
        }
        text = "Price is trending up"
        flags = self.auditor._check_contradictory_omission('bull', text, scores)
        assert len(flags) == 0

    def test_judge_role_skipped(self):
        """Judge should not be checked (only Bull/Bear are advocates)."""
        scores = {
            'order_flow': {'direction': 'BEARISH', 'score': -0.9},
        }
        text = "Strong bullish signal"
        flags = self.auditor._check_contradictory_omission('judge', text, scores)
        assert len(flags) == 0

    def test_no_scores_no_flag(self):
        """No scores available — skip gracefully."""
        flags = self.auditor._check_contradictory_omission('bull', 'text', None)
        assert len(flags) == 0


class TestScoreIntegration:
    """Test that new checks integrate into _calculate_score correctly."""

    def setup_method(self):
        self.auditor = AIQualityAuditor()

    def test_phantom_penalty(self):
        """Phantom citations should deduct 8 points each."""
        from agents.ai_quality_auditor import QualityReport
        report = QualityReport()
        report.phantom_citations = 2
        score = self.auditor._calculate_score(report)
        assert score == 100 - 16  # 2 × 8

    def test_narrative_penalty(self):
        """Narrative misreads should deduct 4 points each."""
        from agents.ai_quality_auditor import QualityReport
        report = QualityReport()
        report.narrative_misreads = 3
        score = self.auditor._calculate_score(report)
        assert score == 100 - 12  # 3 × 4

    def test_contradictory_omission_no_penalty(self):
        """Contradictory omission is informational — no score impact."""
        from agents.ai_quality_auditor import QualityReport
        report = QualityReport()
        report.flags.append('CONTRADICTORY_OMISSION: bull: order_flow is BEARISH')
        score = self.auditor._calculate_score(report)
        assert score == 100  # No penalty


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
