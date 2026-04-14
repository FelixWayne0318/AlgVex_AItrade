"""
Quality Analysis Service — Layer 3 Outcome Feedback for Web API.

Wraps utils/quality_analysis.py functions for web endpoint consumption.
Data Source: data/trading_memory.json, data/hold_counterfactuals.json
"""
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from core.config import settings

logger = logging.getLogger(__name__)

# Add project root to path for importing utils/quality_analysis
_project_root = Path(settings.ALGVEX_PATH)
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from utils.quality_analysis import (
    load_trades_from_file,
    load_counterfactuals_from_file,
    run_full_analysis,
    get_heartbeat_summary,
    analyze_confidence_calibration,
    analyze_confidence_recalibration,
    analyze_counter_trend,
    analyze_grade_distribution,
    analyze_entry_timing,
    analyze_quality_quintiles,
    analyze_v34_flag_correlation,
    analyze_hold_counterfactuals,
)


class QualityAnalysisService:
    """Service for Layer 3 quality-outcome correlation analysis."""

    def __init__(self):
        self.data_dir = Path(settings.ALGVEX_PATH) / 'data'
        logger.info(f"QualityAnalysisService initialized, data_dir={self.data_dir}")

    def _load_trades(self):
        return load_trades_from_file(self.data_dir)

    def _load_counterfactuals(self):
        return load_counterfactuals_from_file(self.data_dir)

    def get_full_report(self) -> Dict[str, Any]:
        """Run all 10 analyses + HOLD counterfactuals. Returns complete report."""
        trades = self._load_trades()
        counterfactuals = self._load_counterfactuals()
        report = run_full_analysis(trades, counterfactuals)
        report['generated_at'] = datetime.now().isoformat()
        return report

    def get_summary(self) -> Dict[str, Any]:
        """Get compact summary for public display."""
        trades = self._load_trades()
        if not trades:
            return {
                'total_trades': 0,
                'status': 'no_data',
                'generated_at': datetime.now().isoformat(),
            }

        total = len(trades)
        wins = sum(1 for m in trades if m['evaluation']['direction_correct'])
        overall_wr = round(wins / total, 3) if total > 0 else 0

        conf_cal = analyze_confidence_calibration(trades)
        recal = analyze_confidence_recalibration(trades)
        ct = analyze_counter_trend(trades)
        grades = analyze_grade_distribution(trades)
        et = analyze_entry_timing(trades)

        return {
            'total_trades': total,
            'overall_win_rate': overall_wr,
            'confidence_calibration': conf_cal,
            'calibration_flags': recal.get('flags', []),
            'confidence_ev': {
                level: {
                    'ev': recal.get(level, {}).get('expected_ev'),
                    'avg_win_rr': recal.get(level, {}).get('avg_win_rr'),
                    'avg_loss_rr': recal.get(level, {}).get('avg_loss_rr'),
                }
                for level in ['HIGH', 'MEDIUM', 'LOW']
                if recal.get(level, {}).get('n', 0) > 0
            },
            'counter_trend': ct,
            'grade_distribution': grades,
            'entry_timing': et,
            'status': 'ok',
            'generated_at': datetime.now().isoformat(),
        }

    def get_quality_quintiles(self) -> Dict[str, Any]:
        """Get quality score quintile analysis (admin only, needs 10+ trades)."""
        trades = self._load_trades()
        result = analyze_quality_quintiles(trades)
        result['generated_at'] = datetime.now().isoformat()
        return result

    def get_v34_flags(self) -> Dict[str, Any]:
        """Get v34.0 flag correlation analysis (admin only)."""
        trades = self._load_trades()
        result = analyze_v34_flag_correlation(trades)
        result['generated_at'] = datetime.now().isoformat()
        return result

    def get_hold_counterfactuals(self) -> Dict[str, Any]:
        """Get HOLD counterfactual analysis."""
        counterfactuals = self._load_counterfactuals()
        result = analyze_hold_counterfactuals(counterfactuals)
        result['generated_at'] = datetime.now().isoformat()
        return result


# Singleton instance
_service_instance = None


def get_quality_analysis_service() -> QualityAnalysisService:
    """Get singleton instance of QualityAnalysisService"""
    global _service_instance
    if _service_instance is None:
        _service_instance = QualityAnalysisService()
    return _service_instance
