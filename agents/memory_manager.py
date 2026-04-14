"""
Memory Manager Mixin for MultiAgentAnalyzer

Extracted from multi_agent_analyzer.py for code organization.
Contains the trading memory system: load/save, scoring, selection,
reflection generation, and outcome recording.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from agents.prompt_constants import (
    RECENCY_WEIGHT,
    RECENCY_HALF_LIFE_DAYS,
    EXTENDED_REFLECTION_INTERVAL,
    EXTENDED_REFLECTION_MAX_CHARS,
    EXTENDED_REFLECTIONS_FILE,
    EXTENDED_REFLECTIONS_MAX_COUNT,
    REASON_TAGS,
)


class MemoryManagerMixin:
    """Mixin providing memory management methods for MultiAgentAnalyzer."""

    def _load_memory(self) -> List[Dict]:
        """Load memory from JSON file."""
        import os
        try:
            if os.path.exists(self.memory_file):
                with open(self.memory_file, 'r') as f:
                    data = json.load(f)
                    self.logger.info(f"📚 Loaded {len(data)} memories from {self.memory_file}")
                    return data
        except Exception as e:
            self.logger.warning(f"Failed to load memory: {e}")
        return []

    def _save_memory(self):
        """Save memory to JSON file."""
        import os
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
            with open(self.memory_file, 'w') as f:
                json.dump(self.decision_memory, f, indent=2)
            self.logger.debug(f"💾 Saved {len(self.decision_memory)} memories")
        except Exception as e:
            self.logger.warning(f"Failed to save memory: {e}")

    def _load_extended_reflections(self) -> List[Dict]:
        """v18.0: Load extended reflections from separate JSON file.
        Uses per-cycle cache to avoid repeated file reads (F3 fix)."""
        # F3: Return cached result if available (cleared at start of analyze())
        if self._ext_reflections_cache is not None:
            return self._ext_reflections_cache
        import os
        try:
            if os.path.exists(EXTENDED_REFLECTIONS_FILE):
                with open(EXTENDED_REFLECTIONS_FILE, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._ext_reflections_cache = data
                        return data
        except Exception as e:
            self.logger.warning(f"Failed to load extended reflections: {e}")
        self._ext_reflections_cache = []
        return []

    def _save_extended_reflection(self, entry: Dict) -> None:
        """v18.0: Append an extended reflection entry and save."""
        import os
        reflections = self._load_extended_reflections()
        reflections.append(entry)
        # FIFO cap
        if len(reflections) > EXTENDED_REFLECTIONS_MAX_COUNT:
            reflections = reflections[-EXTENDED_REFLECTIONS_MAX_COUNT:]
        try:
            os.makedirs(os.path.dirname(EXTENDED_REFLECTIONS_FILE), exist_ok=True)
            with open(EXTENDED_REFLECTIONS_FILE, 'w') as f:
                json.dump(reflections, f, indent=2)
            # F3: Invalidate cache so next read sees updated data
            self._ext_reflections_cache = reflections
        except Exception as e:
            self.logger.warning(f"Failed to save extended reflection: {e}")

    # ── v5.10: Structured similarity matching for memory retrieval ──

    @staticmethod
    def _parse_conditions(conditions_str: str) -> Dict[str, str]:
        """
        Parse conditions string into structured fields.

        Input:  "price=$70,412, RSI=65, MACD=bullish, BB=72%, conf=HIGH, winner=bull, sentiment=neutral"
        Output: {"rsi": "65", "macd": "bullish", "bb": "72", "conf": "HIGH",
                 "sentiment": "neutral", "decision": ""}
        """
        result = {}
        if not conditions_str or conditions_str == 'N/A':
            return result
        for part in conditions_str.split(','):
            part = part.strip()
            if '=' not in part:
                continue
            key, val = part.split('=', 1)
            key = key.strip().lower()
            val = val.strip().rstrip('%')
            result[key] = val
        return result

    @staticmethod
    def _classify_rsi(rsi_val: float) -> str:
        if rsi_val < 35:
            return "oversold"
        if rsi_val > 65:
            return "overbought"
        return "neutral"

    @staticmethod
    def _classify_bb(bb_val: float) -> str:
        if bb_val < 30:
            return "low"
        if bb_val > 70:
            return "high"
        return "mid"

    @staticmethod
    def _classify_sentiment(raw: str) -> str:
        raw = raw.lower()
        if "crowded_long" in raw:
            return "crowded_long"
        if "crowded_short" in raw:
            return "crowded_short"
        return "neutral"

    def _score_memory(self, mem: Dict, current: Dict) -> float:
        """
        Score how similar a memory entry is to current market conditions.

        Base dimensions (old + new memories):
          direction  (LONG/SHORT)              : 3   — most important
          rsi_zone   (oversold/neutral/overbought) : 2
          macd       (bullish/bearish)          : 1
          bb_zone    (low/mid/high)             : 1
          sentiment  (crowded_long/neutral/crowded_short) : 1
          confidence (HIGH/MEDIUM/LOW)          : 0.5
          grade_value (A+/A→high, F→high for losses) : 0~1.0  — v5.11
          recency    (exponential decay, 14-day half-life) : 0~1.5  — v18.0

        New dimensions (only for conditions_v2 memories):
          adx_regime (STRONG_TREND/WEAK_TREND/RANGING) : 1.5
          extension_regime (NORMAL/EXTENDED/OVEREXTENDED/EXTREME) : 1.0
          volatility_regime (LOW/NORMAL/HIGH/EXTREME) : 0.5
          cvd_trend_30m (POSITIVE/NEGATIVE/NEUTRAL) : 0.5
          rsi_4h zone : 0.5

        Returns 0..15.5 (higher = more similar / more instructive).
        Old memories (max 11.0) get proportional compensation for missing dimensions.
        """
        # v5.12: Guard against empty current conditions
        if not current:
            return 0.0

        # ===== Extract mem_cond: dual-path for old vs new memories =====
        has_v2 = 'conditions_v2' in mem
        if has_v2:
            cv2 = mem['conditions_v2']
            mem_rsi = float(cv2.get('rsi_30m', 50))
            mem_macd = "bullish" if cv2.get('macd_bullish', False) else "bearish"
            mem_bb = float(cv2.get('bb_position_30m', 50))
            mem_sentiment = cv2.get('sentiment', 'neutral')
        else:
            raw = self._parse_conditions(mem.get('conditions', ''))
            if not raw:
                return 0.0
            mem_rsi = float(raw.get('rsi', 50))
            mem_macd = raw.get('macd', '').lower()
            mem_bb = float(raw.get('bb', 50))
            mem_sentiment = raw.get('sentiment', 'neutral')

        # ===== Extract current (always from MemoryConditions.to_dict() new keys) =====
        cur_rsi = float(current.get('rsi_30m', 50))
        cur_macd = "bullish" if current.get('macd_bullish', False) else "bearish"
        cur_bb = float(current.get('bb_position_30m', 50))
        cur_sentiment = current.get('sentiment', 'neutral')

        score = 0.0

        # Direction (from decision field, weight=3)
        cur_dir = current.get('direction', '').upper()
        mem_dir = mem.get('decision', '').upper()
        dir_map = {'BUY': 'LONG', 'SELL': 'SHORT'}
        cur_dir = dir_map.get(cur_dir, cur_dir)
        mem_dir = dir_map.get(mem_dir, mem_dir)
        if cur_dir and mem_dir and cur_dir == mem_dir:
            score += 3.0

        # RSI zone (weight=2)
        try:
            cur_rsi_zone = self._classify_rsi(cur_rsi)
            mem_rsi_zone = self._classify_rsi(mem_rsi)
            if cur_rsi_zone == mem_rsi_zone:
                score += 2.0
            elif {cur_rsi_zone, mem_rsi_zone} != {"oversold", "overbought"}:
                score += 0.6
        except (ValueError, TypeError) as e:
            self.logger.debug(f"RSI zone scoring skipped: {e}")

        # MACD direction (weight=1)
        if cur_macd and mem_macd and cur_macd == mem_macd:
            score += 1.0

        # BB zone (weight=1)
        try:
            cur_bb_zone = self._classify_bb(cur_bb)
            mem_bb_zone = self._classify_bb(mem_bb)
            if cur_bb_zone == mem_bb_zone:
                score += 1.0
            elif {cur_bb_zone, mem_bb_zone} != {"low", "high"}:
                score += 0.3
        except (ValueError, TypeError) as e:
            self.logger.debug(f"BB zone scoring skipped: {e}")

        # Sentiment (weight=1)
        cur_sent = self._classify_sentiment(cur_sentiment)
        mem_sent = self._classify_sentiment(mem_sentiment)
        if cur_sent == mem_sent:
            score += 1.0

        # Confidence (weight=0.5) — read from parsed old conditions
        if not has_v2:
            raw_cond = self._parse_conditions(mem.get('conditions', ''))
            cur_conf = current.get('conf', '').upper()
            mem_conf = raw_cond.get('conf', '').upper()
            if cur_conf and mem_conf and cur_conf == mem_conf:
                score += 0.5

        # v5.11: Grade instructive value (weight=1)
        ev = mem.get('evaluation', {})
        grade = ev.get('grade', '') if ev else ''
        _grade_value = {
            'A+': 1.0, 'A': 0.7, 'B': 0.4, 'C': 0.2,
            'D': 0.3, 'D-': 0.2, 'F': 1.0,
        }
        grade_value = _grade_value.get(grade, 0)

        # quality_score weight adjustment
        quality_weight = 1.0
        if 'ai_quality_score' in mem:
            qs = mem['ai_quality_score']
            if qs < 40:
                quality_weight = 0.3
            elif qs < 60:
                quality_weight = 0.5
            elif qs < 80:
                quality_weight = 0.8
        score += grade_value * quality_weight

        # v18.0: Recency factor (0..1, exponential decay with 14-day half-life)
        mem_ts = mem.get('timestamp', '')
        if mem_ts:
            try:
                mem_time = datetime.fromisoformat(mem_ts)
                days_ago = max(0, (datetime.now(timezone.utc) - mem_time).total_seconds() / 86400)
                recency = 2 ** (-days_ago / RECENCY_HALF_LIFE_DAYS)
            except (ValueError, TypeError):
                recency = 0.5
        else:
            recency = 0.5

        score += recency * RECENCY_WEIGHT

        # ===== New dimensions (only for conditions_v2 memories) =====
        if has_v2:
            cv2 = mem['conditions_v2']

            # ADX regime (weight=1.5)
            if cv2.get('adx_regime') == current.get('adx_regime'):
                score += 1.5

            # Extension regime (weight=1.0)
            if cv2.get('extension_regime') == current.get('extension_regime'):
                score += 1.0
            elif cv2.get('extension_regime') in ('OVEREXTENDED', 'EXTREME') and \
                 current.get('extension_regime') in ('OVEREXTENDED', 'EXTREME'):
                score += 0.5

            # Volatility regime (weight=0.5)
            if cv2.get('volatility_regime') == current.get('volatility_regime'):
                score += 0.5

            # CVD trend (weight=0.5)
            if cv2.get('cvd_trend_30m') == current.get('cvd_trend_30m'):
                score += 0.5

            # 4H RSI zone (weight=0.5)
            cur_rsi4h_zone = self._classify_rsi(float(current.get('rsi_4h', 50)))
            mem_rsi4h_zone = self._classify_rsi(float(cv2.get('rsi_4h', 50)))
            if cur_rsi4h_zone == mem_rsi4h_zone:
                score += 0.5
        else:
            # Old memory: proportional compensation for missing 5 new dimensions (max 4.5)
            max_old = 11.0
            if max_old > 0:
                score += 4.5 * (score / max_old)

        return score

    def _extract_role_reflection(self, mem: dict, agent_role: str) -> str:
        """
        v18 Item 9 / v23.0: Extract role-specific lesson from structured reflection.
        Handles JSON format {"bull": ..., "bear": ..., "judge": ..., "entry_timing": ...}
        and legacy plain text format.
        """
        reflection = mem.get('reflection', '')
        if not reflection:
            return ""

        # Try parsing as structured JSON
        import json as _json
        try:
            parsed = _json.loads(reflection) if isinstance(reflection, str) else reflection
            if isinstance(parsed, dict):
                # All 5 roles have dedicated reflection keys (risk added in v29+)
                # Old memories without risk key → fallback to judge (backward compat)
                ALL_REFLECTION_ROLES = ('bull', 'bear', 'judge', 'entry_timing', 'risk')
                role_key = agent_role if agent_role in ALL_REFLECTION_ROLES else 'judge'
                role_lesson = parsed.get(role_key, '')
                if role_lesson:
                    return f" | {role_key.capitalize()} lesson: {str(role_lesson)}"
                # Fallback to any available role
                for k in ('judge', 'bull', 'bear', 'entry_timing', 'risk'):
                    if parsed.get(k):
                        return f" | Insight: {str(parsed[k])}"
        except (ValueError, TypeError):
            self.logger.debug("Reflection JSON parse failed, using plain text fallback")

        # Legacy plain text format
        return f" | Insight: {str(reflection)}" if reflection else ""

    def _select_memories(
        self,
        current_conditions: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        v18.3: Score and select memories ONCE for all agents.

        Returns a dict with pre-selected memories and metadata, or None if
        no memories are available. Passed to _get_past_memories(preselected=...)
        to avoid 4x redundant similarity scoring.

        Returns
        -------
        Optional[Dict]
            {
                'successes': List[Dict],   # top-5 similar (or recent) wins
                'failures': List[Dict],    # top-5 similar (or recent) losses
                'use_similarity': bool,
                'retrieval_mode': str,     # "similarity" or "recent"
                'sim_scores': Dict[id, float],  # memory id → score cache
            }
        """
        if not self.decision_memory:
            return None

        successes = [m for m in self.decision_memory if m.get('pnl', 0) > 0]
        failures = [m for m in self.decision_memory if m.get('pnl', 0) <= 0]

        use_similarity = (
            current_conditions
            and len(self.decision_memory) >= 20
        )

        sim_scores: Dict[int, float] = {}

        if use_similarity:
            # Score all memories once and cache
            for m in successes + failures:
                sim_scores[id(m)] = self._score_memory(m, current_conditions)

            scored_wins = sorted(successes, key=lambda m: sim_scores[id(m)], reverse=True)
            scored_losses = sorted(failures, key=lambda m: sim_scores[id(m)], reverse=True)
            selected_successes = scored_wins[:5]
            selected_failures = scored_losses[:5]
            retrieval_mode = "similarity"
        else:
            selected_successes = successes[-5:] if successes else []
            selected_failures = failures[-5:] if failures else []
            retrieval_mode = "recent"

        return {
            'successes': selected_successes,
            'failures': selected_failures,
            'use_similarity': use_similarity,
            'retrieval_mode': retrieval_mode,
            'sim_scores': sim_scores,
        }

    def _get_past_memories(
        self,
        current_conditions: Optional[Dict[str, Any]] = None,
        agent_role: str = "",
        preselected: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Get past decision memories formatted for AI learning.

        v5.10: Similarity-based retrieval.
        v12.0: Per-agent role annotations.
        v18.3: Accepts preselected memories to avoid redundant scoring.

        Parameters
        ----------
        current_conditions : dict, optional
            Current market snapshot.
        agent_role : str
            v12.0/v23.0: Agent role for per-agent annotations (bull/bear/judge/entry_timing/risk/"")
        preselected : dict, optional
            v18.3: Pre-scored/selected memories from _select_memories().
            When provided, skips scoring entirely and uses cached results.
        """
        if not self.decision_memory:
            return ""

        if preselected:
            selected_successes = preselected['successes']
            selected_failures = preselected['failures']
            use_similarity = preselected['use_similarity']
            retrieval_mode = preselected['retrieval_mode']
            sim_scores = preselected['sim_scores']
        else:
            # Fallback: compute from scratch (backward compatibility)
            successes = [m for m in self.decision_memory if m.get('pnl', 0) > 0]
            failures = [m for m in self.decision_memory if m.get('pnl', 0) <= 0]

            use_similarity = (
                current_conditions
                and len(self.decision_memory) >= 20
            )

            sim_scores = {}
            if use_similarity:
                for m in successes + failures:
                    sim_scores[id(m)] = self._score_memory(m, current_conditions)
                scored_wins = sorted(successes, key=lambda m: sim_scores[id(m)], reverse=True)
                scored_losses = sorted(failures, key=lambda m: sim_scores[id(m)], reverse=True)
                selected_successes = scored_wins[:5]
                selected_failures = scored_losses[:5]
                retrieval_mode = "similarity"
            else:
                selected_successes = successes[-5:] if successes else []
                selected_failures = failures[-5:] if failures else []
                retrieval_mode = "recent"

        lines = []

        # v11.5: Helper to format SL/TP optimization context from evaluation
        def _fmt_sltp_context(ev: Dict) -> str:
            parts = []
            if ev.get('sl_atr_multiplier'):
                parts.append(f"SL={ev['sl_atr_multiplier']}×ATR")
            if ev.get('is_counter_trend'):
                parts.append("CT")
            if ev.get('trend_direction'):
                td = ev['trend_direction']
                adx_val = ev.get('adx', 0)
                parts.append(f"{td}(ADX={adx_val:.0f})" if adx_val else td)
            if ev.get('mae_pct') or ev.get('mfe_pct'):
                mae = ev.get('mae_pct', 0)
                mfe = ev.get('mfe_pct', 0)
                parts.append(f"MAE={mae:.1f}%/MFE={mfe:.1f}%")
            return f" [{', '.join(parts)}]" if parts else ""

        # v12.0: Per-agent role annotation helper
        def _role_annotation(mem: Dict, role: str) -> str:
            """Generate role-specific annotation for a memory entry."""
            if not role:
                return ""
            ws = str(mem.get('winning_side', '')).upper()
            decision = str(mem.get('decision', '')).upper()
            pnl = mem.get('pnl', 0)
            is_long = decision in ('LONG', 'BUY')

            if role == 'bull':
                if ws == 'BULL' and pnl > 0:
                    return " 🎯 你的论据被采纳且盈利"
                elif ws == 'BULL' and pnl <= 0:
                    return " ⚠️ 你的论据被采纳但亏损 — 审视论据质量"
                elif ws == 'BEAR':
                    # Bear won → bull's LONG argument was not adopted
                    return " 📝 你的看多论据未被采纳"
                return ""
            elif role == 'bear':
                if ws == 'BEAR' and pnl > 0:
                    return " 🎯 你的论据被采纳且盈利"
                elif ws == 'BEAR' and pnl <= 0:
                    return " ⚠️ 你的论据被采纳但亏损 — 审视论据质量"
                elif ws == 'BULL':
                    # Bull won → bear's SHORT argument was not adopted
                    return " 📝 你的看空论据未被采纳"
                return ""
            elif role == 'judge':
                ev = mem.get('evaluation', {})
                dc = ev.get('direction_correct', None)
                if dc is True:
                    return " ✅ 方向判断正确"
                elif dc is False:
                    return " ❌ 方向判断错误 — 审视决策逻辑"
                return ""
            elif role == 'entry_timing':
                # Entry Timing Agent cares about: was the entry timing good?
                # High MAE = bad entry (price moved against immediately)
                # High MFE with profit = good entry timing
                ev = mem.get('evaluation', {})
                mae = ev.get('mae_pct', 0)
                mfe = ev.get('mfe_pct', 0)
                exit_type = ev.get('exit_type', '')
                if pnl > 0 and mfe > 0:
                    return f" ⏱️ 入场时机佳 MFE={mfe:.1f}%"
                elif pnl <= 0 and mae > 2:
                    return f" ⏱️ 入场时机差 MAE={mae:.1f}% ({exit_type})"
                elif pnl <= 0 and exit_type:
                    return f" ⏱️ {exit_type}"
                return ""
            elif role == 'risk':
                ev = mem.get('evaluation', {})
                mae = ev.get('mae_pct', 0)
                sl_mult = ev.get('sl_atr_multiplier', 0)
                if pnl <= 0 and mae > 0 and sl_mult > 0:
                    return f" 📊 MAE={mae:.1f}% SL={sl_mult}×ATR"
                return ""
            return ""

        if selected_successes:
            lines.append("SUCCESSFUL TRADES (learn from these):")
            for mem in selected_successes:
                conditions = mem.get('conditions', 'N/A')
                ev = mem.get('evaluation', {})
                grade = ev.get('grade', '')
                rr_str = f" R/R={ev.get('actual_rr', 0):.1f}:1" if ev else ""
                grade_str = f" [{grade}]" if grade else ""
                ctx_str = _fmt_sltp_context(ev) if ev else ""
                sim_str = ""
                if use_similarity:
                    # v18.3: Use cached score instead of re-computing
                    sim = sim_scores.get(id(mem)) if sim_scores else None
                    if sim is None:
                        sim = self._score_memory(mem, current_conditions)
                    sim_str = f" (sim={sim:.1f})"
                role_str = _role_annotation(mem, agent_role)
                # v18 Item 9: Extract role-specific lesson from structured reflection
                refl_str = self._extract_role_reflection(mem, agent_role)
                lines.append(
                    f"  ✅ {mem.get('decision')} → {mem.get('pnl', 0):+.2f}%{grade_str}{rr_str}{ctx_str}{sim_str}{role_str}{refl_str} | "
                    f"Conditions: {conditions}"
                )

        if selected_failures:
            lines.append("FAILED TRADES (avoid repeating):")
            for mem in selected_failures:
                conditions = mem.get('conditions', 'N/A')
                lesson = mem.get('lesson', 'N/A')
                ev = mem.get('evaluation', {})
                grade = ev.get('grade', '')
                exit_type = ev.get('exit_type', '')
                grade_str = f" [{grade}]" if grade else ""
                exit_str = f" via {exit_type}" if exit_type else ""
                ctx_str = _fmt_sltp_context(ev) if ev else ""
                sim_str = ""
                if use_similarity:
                    # v18.3: Use cached score instead of re-computing
                    sim = sim_scores.get(id(mem)) if sim_scores else None
                    if sim is None:
                        sim = self._score_memory(mem, current_conditions)
                    sim_str = f" (sim={sim:.1f})"
                role_str = _role_annotation(mem, agent_role)
                # v18 Item 9: Extract role-specific lesson from structured reflection
                refl_str = self._extract_role_reflection(mem, agent_role)
                lines.append(
                    f"  ❌ {mem.get('decision')} → {mem.get('pnl', 0):+.2f}%{grade_str}{exit_str}{ctx_str}{sim_str}{role_str}{refl_str} | "
                    f"Conditions: {conditions} | Lesson: {lesson}"
                )

        # Aggregate stats (always based on full history, not filtered)
        # v5.12: Use last 20 from ALL trades (not just evaluated) so the window
        # is consistent regardless of how many trades had evaluation failures.
        recent_all = self.decision_memory[-20:]
        recent_evaluated = [m for m in recent_all if m.get('evaluation')]
        if recent_evaluated:
            grades = [m['evaluation'].get('grade', '?') for m in recent_evaluated]
            grade_counts: Dict[str, int] = {}
            for g in grades:
                grade_counts[g] = grade_counts.get(g, 0) + 1
            grade_summary = " ".join(f"{g}:{c}" for g, c in sorted(grade_counts.items()))

            correct = sum(1 for m in recent_evaluated if m['evaluation'].get('direction_correct'))
            total_evaluated = len(recent_evaluated)
            total_window = len(recent_all)
            accuracy = round(correct / total_evaluated * 100) if total_evaluated > 0 else 0

            # v5.12: Show both window size and evaluated count if they differ
            unevaluated = total_window - total_evaluated
            eval_note = f" ({unevaluated} unevaluated)" if unevaluated > 0 else ""
            lines.append(
                f"\nTRADE QUALITY (last {total_window} trades, "
                f"{total_evaluated} graded{eval_note}): "
                f"{grade_summary} | Direction accuracy: {accuracy}%"
            )

            # v11.5: SL/TP optimization summary (only if data available)
            mae_vals = [m['evaluation']['mae_pct'] for m in recent_evaluated if m['evaluation'].get('mae_pct')]
            mfe_vals = [m['evaluation']['mfe_pct'] for m in recent_evaluated if m['evaluation'].get('mfe_pct')]
            ct_trades = [m for m in recent_evaluated if m['evaluation'].get('is_counter_trend')]
            if mae_vals or mfe_vals:
                avg_mae = sum(mae_vals) / len(mae_vals) if mae_vals else 0
                avg_mfe = sum(mfe_vals) / len(mfe_vals) if mfe_vals else 0
                ct_count = len(ct_trades)
                lines.append(
                    f"SL/TP STATS: Avg MAE={avg_mae:.1f}% Avg MFE={avg_mfe:.1f}% | "
                    f"Counter-trend: {ct_count}/{total_evaluated}"
                )

        # v18.0: Append latest extended reflection (if available)
        ext_reflections = self._load_extended_reflections()
        if ext_reflections:
            latest = ext_reflections[-1]
            lines.append("")
            lines.append("## 🔄 EXTENDED REFLECTION (跨交易 Pattern 分析)")
            lines.append(f"{latest.get('insight', '')}")
            lines.append(f"⚠️ 基于最近 {latest.get('trade_count', '?')} 笔交易的统计结论 "
                         f"(胜率 {latest.get('win_rate', 0)*100:.0f}%, "
                         f"avg R/R {latest.get('avg_rr', 0):.1f}:1)")

        # v12.0: Only log at INFO for first role call (bull) or no-role call; DEBUG for others
        role_tag = f" role={agent_role}" if agent_role else ""
        log_level = self.logger.info if not agent_role or agent_role == "bull" else self.logger.debug
        log_level(
            f"📚 Memory retrieval: mode={retrieval_mode}{role_tag}, pool={len(self.decision_memory)}, "
            f"wins={len(selected_successes)}, losses={len(selected_failures)}"
        )

        return "\n".join(lines)

    def _get_structured_memories(
        self,
        selected_memories: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        v27.0: Extract structured memory features for snapshot persistence.

        Returns list of dicts per PLAN §1.4 for replay determinism.
        """
        result = []
        sim_scores = selected_memories.get('sim_scores', {})
        all_selected = (
            selected_memories.get('successes', []) +
            selected_memories.get('failures', [])
        )
        for mem in all_selected[:10]:
            entry = {
                "signal": mem.get("decision", ""),
                "grade": mem.get("evaluation", {}).get("grade", "?") if isinstance(mem.get("evaluation"), dict) else "?",
                "pnl_pct": mem.get("pnl", 0),
                "conditions_similarity": round(sim_scores.get(id(mem), 0), 3),
                "key_lesson_tags": mem.get("key_lesson_tags", []),
                "recency_weight": mem.get("_recency_weight", 1.0),
            }
            result.append(entry)
        return result

    def record_outcome(
        self,
        decision: str,
        pnl: float,
        conditions: str = "",
        lesson: str = "",
        evaluation: Optional[Dict[str, Any]] = None,
        eval_error_reason: Optional[str] = None,
        winning_side: str = "",
        entry_judge_summary: str = "",
        entry_timing_verdict: str = "",
        entry_timing_quality: str = "",
        close_reason: str = "",
        key_lesson_tags: Optional[List[str]] = None,
        conditions_v2: Optional[Dict[str, Any]] = None,
        ai_quality_score: Optional[int] = None,
    ):
        """
        Record trade outcome for learning.

        Call this after a trade is closed to help the system learn.

        Parameters
        ----------
        decision : str
            The decision that was made (BUY/SELL/HOLD)
        pnl : float
            Percentage profit/loss
        conditions : str
            Market conditions at entry (e.g., "RSI=65, trend=UP, funding=0.01%")
        lesson : str
            Lesson learned from this trade (auto-generated if empty)
        evaluation : Dict, optional
            Trade evaluation data from trading_logic.evaluate_trade()
            Contains: grade, direction_correct, actual_rr, planned_rr,
            execution_quality, exit_type, hold_duration_min, etc.
        winning_side : str
            v12.0: Judge's winning_side at entry (BULL/BEAR/TIE)
        entry_judge_summary : str
            v12.0: Judge rationale + risks at entry time for reflection context
        entry_timing_verdict : str
            v23.0: Entry Timing Agent verdict at entry (ENTER/REJECT)
        entry_timing_quality : str
            v23.0: Entry Timing Agent quality assessment (OPTIMAL/GOOD/FAIR/POOR)
        close_reason : str
            v24.2: How the trade was closed (STOP_LOSS/TRAILING_STOP/TAKE_PROFIT/
            MANUAL/EMERGENCY/TIME_BARRIER/REVERSAL)
        key_lesson_tags : List[str], optional
            v27.0: REASON_TAGS describing key lessons (e.g., LATE_ENTRY, TREND_ALIGNED).
            Filtered to only valid tags from REASON_TAGS set.
        conditions_v2 : Dict, optional
            v29+: MemoryConditions.to_dict() snapshot from analyze() time.
            Feature-based conditions for multi-dimensional similarity matching.
        ai_quality_score : int, optional
            v29+: AI quality auditor score (0-100) at entry time.
        """
        # v5.1: Auto-generate lesson based on evaluation grade (if available)
        if not lesson and evaluation:
            grade = evaluation.get('grade', '')
            actual_rr = evaluation.get('actual_rr', 0)
            exit_type = evaluation.get('exit_type', '')
            if grade in ('A+', 'A'):
                lesson = f"Grade {grade}: Strong win (R/R {actual_rr:.1f}:1) - repeat this pattern"
            elif grade == 'B':
                lesson = f"Grade B: Acceptable profit (R/R {actual_rr:.1f}:1)"
            elif grade == 'C':
                lesson = f"Grade C: Small profit but low R/R ({actual_rr:.1f}:1) - tighten entry"
            elif grade == 'D':
                lesson = f"Grade D: Controlled loss via {exit_type} - discipline maintained"
            elif grade == 'D-':
                lesson = f"Grade D-: Loss without SL data - discipline unknown, ensure SL/TP capture"
            elif grade == 'F':
                lesson = f"Grade F: Uncontrolled loss - review SL placement"

        # Fallback to original lesson generation
        if not lesson:
            if pnl < -2:
                lesson = "Significant loss - review entry conditions carefully"
            elif pnl < 0:
                lesson = "Small loss - timing or direction may need adjustment"
            elif pnl > 2:
                lesson = "Good profit - this setup worked well"
            elif pnl > 0:
                lesson = "Small profit - consider holding longer or tighter stops"
            else:
                lesson = "Breakeven - entry/exit timing needs improvement"

        entry = {
            "decision": decision,
            "pnl": round(pnl, 2),
            "conditions": conditions,
            "lesson": lesson,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # v12.0: Store Judge's winning_side and entry summary for per-agent reflection
        if winning_side:
            entry["winning_side"] = winning_side
        if entry_judge_summary:
            entry["entry_judge_summary"] = entry_judge_summary

        # v23.0: Store Entry Timing Agent verdict for reflection and memory
        if entry_timing_verdict:
            entry["entry_timing_verdict"] = entry_timing_verdict
        if entry_timing_quality:
            entry["entry_timing_quality"] = entry_timing_quality

        # v24.2: Store close reason for AI learning
        if close_reason:
            entry["close_reason"] = close_reason

        # v27.0: Store structured lesson tags (filtered to valid REASON_TAGS)
        if key_lesson_tags:
            valid_tags = [t.upper() for t in key_lesson_tags if t.upper() in REASON_TAGS]
            if valid_tags:
                entry["key_lesson_tags"] = valid_tags

        # v29+: Feature-based conditions snapshot (replaces free-text conditions)
        if conditions_v2:
            entry["conditions_v2"] = conditions_v2
        if ai_quality_score is not None:
            entry["ai_quality_score"] = ai_quality_score

        # v5.1: Attach evaluation data if provided
        # v5.12: Track evaluation failures so they are distinguishable from "not yet evaluated"
        if evaluation:
            entry["evaluation"] = evaluation
        elif eval_error_reason:
            entry["evaluation_failed"] = eval_error_reason

        self.decision_memory.append(entry)

        # v5.1: Increased from 50 to 500 for better statistical analysis
        if len(self.decision_memory) > 500:
            self.decision_memory.pop(0)

        # Persist to file
        self._save_memory()

        grade_str = f" [Grade: {evaluation.get('grade', '?')}]" if evaluation else ""
        self.logger.info(
            f"📝 Recorded: {decision} → {pnl:+.2f}%{grade_str} | "
            f"Conditions: {conditions} | Lesson: {lesson}"
        )

    def generate_reflection(
        self,
        memory_entry: Dict[str, Any],
        max_chars: int = 150,
        temperature: float = 0.3,
    ) -> str:
        """
        v12.0: Generate LLM-based deep reflection for a closed trade.

        Uses the trade's evaluation data, entry conditions, and Judge summary
        to produce a concise, quantitative reflection that replaces the template lesson.

        Parameters
        ----------
        memory_entry : Dict
            The memory entry from decision_memory (must have evaluation + conditions)
        max_chars : int
            Maximum Chinese characters for reflection (default 150)
        temperature : float
            LLM temperature for reflection generation

        Returns
        -------
        str
            Reflection text (≤ max_chars Chinese characters), or empty string on failure
        """
        ev = memory_entry.get('evaluation', {})
        if not ev:
            self.logger.debug("No evaluation data for reflection — skipping")
            return ""

        # Build compact context for reflection prompt
        decision = memory_entry.get('decision', '?')
        pnl = memory_entry.get('pnl', 0)
        conditions = memory_entry.get('conditions', 'N/A')
        grade = ev.get('grade', '?')
        actual_rr = ev.get('actual_rr', 0)
        planned_rr = ev.get('planned_rr', 0)
        exit_type = ev.get('exit_type', '?')
        mae_pct = ev.get('mae_pct', 0)
        mfe_pct = ev.get('mfe_pct', 0)
        adx = ev.get('adx', 0)
        trend_dir = ev.get('trend_direction', '')
        is_counter = ev.get('is_counter_trend', False)
        sl_atr_mult = ev.get('sl_atr_multiplier', 0)
        hold_min = ev.get('hold_duration_min', 0)
        confidence = ev.get('confidence', '?')
        pyramid_layers = ev.get('pyramid_layers_used', 1)
        entry_judge = memory_entry.get('entry_judge_summary', '')
        winning_side = memory_entry.get('winning_side', '')
        et_verdict = memory_entry.get('entry_timing_verdict', '')
        et_quality = memory_entry.get('entry_timing_quality', '')

        prompt = f"""你是量化交易反思助手。请基于以下交易结果，生成一段精炼的深度反思。

## 交易数据
- 方向: {decision} | 盈亏: {pnl:+.2f}% | 评级: {grade}
- 计划R/R: {planned_rr:.1f}:1 | 实际R/R: {actual_rr:.1f}:1
- 退出方式: {exit_type} | 持仓: {hold_min}分钟
- 信心: {confidence} | SL倍数: {sl_atr_mult}×ATR
- MAE(最大浮亏): {mae_pct:.1f}% | MFE(最大浮盈): {mfe_pct:.1f}%
- 趋势: {trend_dir} ADX={adx:.0f} | 逆势: {'是' if is_counter else '否'}
- 加仓层数: {pyramid_layers}
- 入场条件: {conditions}
- Judge决策: {winning_side} | {entry_judge if entry_judge else 'N/A'}
- Entry Timing: verdict={et_verdict or 'N/A'} quality={et_quality or 'N/A'}

## 反思要求
生成 JSON 格式的角色专属反思，每条 ≤{max_chars // 5} 字：
{{
  "bull": "多头分析师应该学到什么？(论据质量、趋势尊重)",
  "bear": "空头分析师应该学到什么？(风险识别、反驳强度)",
  "judge": "裁判应该学到什么？(信心校准、方向决策)",
  "entry_timing": "入场时机评估应该学到什么？(时机准确性、MTF对齐、quality评估)",
  "risk": "风险管理应该学到什么？(仓位大小、SL距离、波动率适应)"
}}

⚠️ 只输出 JSON，不要其他文字。每条用数据说话，不说空话。"""

        try:
            raw = self._call_api_with_retry(
                messages=[
                    {"role": "system", "content": "你是量化交易系统的反思引擎。输出 JSON 格式的角色专属反思。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                trace_label="Reflection",
            )
            if raw:
                raw = raw.strip()
                # v18 Item 9: Try to parse structured JSON reflection
                import json as _json
                try:
                    # Extract JSON from potential markdown code block
                    _text = raw
                    if '```' in _text:
                        _text = _text.split('```')[1]
                        if _text.startswith('json'):
                            _text = _text[4:]
                        _text = _text.strip()
                    parsed = _json.loads(_text)
                    ALL_REFLECTION_ROLES = ('bull', 'bear', 'judge', 'entry_timing', 'risk')
                    if isinstance(parsed, dict) and any(k in parsed for k in ALL_REFLECTION_ROLES):
                        # Truncate each role's reflection (dynamic limit based on actual roles present)
                        role_count = sum(1 for r in ALL_REFLECTION_ROLES if r in parsed)
                        per_role_limit = max_chars // max(role_count, 1)
                        # v30.2: No per-role truncation — zero truncation policy
                        for role in ALL_REFLECTION_ROLES:
                            pass  # Keep full content
                        self.logger.info(f"🔍 Structured reflection generated ({role_count} roles)")
                        return _json.dumps(parsed, ensure_ascii=False)
                except (_json.JSONDecodeError, IndexError, KeyError):
                    self.logger.debug("Structured reflection parse failed, using plain text")

                # Fallback: return as plain text (backward compatible)
                # v30.2: No truncation — zero truncation policy
                self.logger.info(f"🔍 Reflection generated ({len(raw)} chars, plain text)")
                return raw
        except Exception as e:
            self.logger.warning(f"Reflection generation failed: {e}")

        return ""

    def update_last_memory_reflection(
        self,
        target_timestamp: str,
        reflection: str,
    ) -> bool:
        """
        v12.0: Update a specific memory entry's lesson with LLM-generated reflection.

        Uses timestamp matching (not [-1] index) for robustness.

        Parameters
        ----------
        target_timestamp : str
            ISO timestamp of the memory entry to update
        reflection : str
            LLM-generated reflection text

        Returns
        -------
        bool
            True if memory was found and updated, False otherwise
        """
        if not reflection or not target_timestamp:
            return False

        # Search backwards (most recent first) for matching timestamp
        for mem in reversed(self.decision_memory):
            if mem.get('timestamp') == target_timestamp:
                mem['reflection'] = reflection
                # Keep original template lesson as fallback reference
                if 'lesson' in mem and not mem.get('original_lesson'):
                    mem['original_lesson'] = mem['lesson']
                mem['lesson'] = reflection
                self._save_memory()
                self.logger.info(
                    f"🔍 Reflection saved to memory (ts={target_timestamp[:19]}): "
                    f"{reflection}"
                )
                return True

        self.logger.warning(
            f"Memory entry not found for reflection (ts={target_timestamp[:19]})"
        )
        return False

    def check_and_generate_extended_reflection(self) -> Optional[Dict]:
        """
        v18.0: Check if extended reflection is due and generate if needed.

        Uses timestamp comparison instead of modulo to avoid fragility
        when FIFO cap (500) removes old entries.

        Returns the generated entry dict if a new extended reflection was
        created, or None if not triggered / failed. The caller
        (ai_strategy._process_pending_reflections) uses the return
        value for Telegram notification — no need to call private methods.
        """
        closed_trades = [m for m in self.decision_memory if m.get('pnl') is not None]
        if len(closed_trades) < EXTENDED_REFLECTION_INTERVAL:
            return None

        # Timestamp-based trigger: count trades since last extended reflection
        ext_reflections = self._load_extended_reflections()
        if ext_reflections:
            last_ext_ts = ext_reflections[-1].get('timestamp', '')
            trades_since = sum(
                1 for m in closed_trades
                if m.get('timestamp', '') > last_ext_ts
            )
        else:
            trades_since = len(closed_trades)

        if trades_since < EXTENDED_REFLECTION_INTERVAL:
            return None

        try:
            recent = closed_trades[-EXTENDED_REFLECTION_INTERVAL:]
            entry = self._generate_and_save_extended_reflection(recent)
            return entry
        except Exception as e:
            self.logger.warning(f"Extended reflection failed (non-critical): {e}")
            return None

    def _generate_and_save_extended_reflection(self, recent_trades: List[Dict]) -> Optional[Dict]:
        """
        v18.0: Generate meta-level insight from N recent trades.

        Unlike single-trade reflection (generate_reflection), this looks for
        PATTERNS across multiple trades — recurring errors, condition-outcome
        correlations, and systematic weaknesses.

        Saves to separate file data/extended_reflections.json (does NOT modify
        trading_memory.json to preserve backward compatibility).

        Returns the entry dict (for caller's Telegram notification) or None on failure.
        """
        # Build statistical summary
        wins = [t for t in recent_trades if t.get('pnl', 0) > 0]
        losses = [t for t in recent_trades if t.get('pnl', 0) < 0]
        counter_trend = [t for t in recent_trades if t.get('evaluation', {}).get('is_counter_trend')]

        trades_summary = "\n".join([
            f"- {t.get('decision','?')} | PnL: {t.get('pnl',0):+.2f}% | "
            f"Grade: {t.get('evaluation',{}).get('grade','?')} | "
            f"ADX: {t.get('evaluation',{}).get('adx',0):.0f} | "
            f"CT: {'Yes' if t.get('evaluation',{}).get('is_counter_trend') else 'No'} | "
            f"Reflection: {t.get('reflection','N/A')}"
            for t in recent_trades
        ])

        ct_count = len(counter_trend)
        ct_wins = sum(1 for t in counter_trend if t.get('pnl', 0) > 0)

        prompt = f"""你是量化交易系统的 Meta 反思引擎。请综合分析最近 {len(recent_trades)} 笔交易，
找出跨交易的系统性规律。

## 交易汇总
{trades_summary}

## 统计
- 胜率: {len(wins)}/{len(recent_trades)} ({len(wins)/len(recent_trades)*100:.0f}%)
- 逆势交易: {ct_count}/{len(recent_trades)}
- 逆势胜率: {ct_wins}/{ct_count if ct_count else 1}

## 分析要求
用中文写 ≤{EXTENDED_REFLECTION_MAX_CHARS} 字的 meta 反思，必须覆盖:
1. **Recurring Pattern**: 这些交易中反复出现的成功/失败模式是什么？
2. **Statistical Insight**: 哪些条件组合的胜率明显偏高或偏低？
3. **One Actionable Rule**: 基于以上分析，提出一条具体可执行的规则。

⚠️ 直接输出反思文字。用统计数据说话，不说空话。"""

        insight = self._call_api_with_retry(
            messages=[
                {"role": "system", "content": "你是量化交易系统的反思引擎。输出精炼、数据驱动的中文反思。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            trace_label="ExtendedReflection",
        )

        if not insight:
            return None

        # Truncate (same logic as generate_reflection)
        insight = insight.strip()
        # v30.2: No truncation — zero truncation policy
        # EXTENDED_REFLECTION_MAX_CHARS kept as prompt guidance only, not enforced

        # Build entry
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade_range": [
                recent_trades[0].get('timestamp', ''),
                recent_trades[-1].get('timestamp', ''),
            ],
            "trade_count": len(recent_trades),
            "win_rate": round(len(wins) / len(recent_trades), 2),
            "avg_rr": round(
                sum(t.get('evaluation', {}).get('actual_rr', 0) for t in recent_trades)
                / len(recent_trades), 2
            ),
            "insight": insight,
        }

        # Load, append, cap, save
        self._save_extended_reflection(entry)
        self.logger.info(
            f"🔄 Extended reflection generated ({len(insight)} chars): {insight}"
        )
        return entry

    def _create_fallback_signal(self, price_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create conservative fallback signal when analysis fails.

        v18.3: Removed legacy stop_loss/take_profit fields.
        Since v11.0, SL/TP are computed by calculate_mechanical_sltp() only for
        LONG/SHORT signals. HOLD signals never need SL/TP values.
        v23.0: Added _timing_assessment marker so Strategy layer can distinguish
        "Entry Timing skipped" vs "entire analysis failed".
        """
        return {
            "signal": "HOLD",
            "confidence": "LOW",
            "risk_level": "HIGH",
            "position_size_pct": 0,
            "reason": "Multi-agent analysis failed - defaulting to HOLD",
            "debate_summary": "Analysis error occurred",
            "is_fallback": True,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "_timing_assessment": {
                "timing_verdict": "N/A",
                "timing_quality": "N/A",
                "adjusted_confidence": "LOW",
                "counter_trend_risk": "NONE",
                "reason": "Analysis failed before Entry Timing phase",
            },
        }

    def get_last_debate(self) -> str:
        """Return the last debate transcript for debugging/logging."""
        return self.last_debate_transcript

    def get_last_prompts(self) -> Dict[str, Dict[str, str]]:
        """
        Return the last prompts sent to each agent (v11.4 diagnostic feature).

        Returns
        -------
        Dict[str, Dict[str, str]]
            {
                "bull": {"system": "...", "user": "..."},
                "bear": {"system": "...", "user": "..."},
                "judge": {"system": "...", "user": "..."},
                "entry_timing": {"system": "...", "user": "..."},
                "risk": {"system": "...", "user": "..."},
            }
        """
        return self.last_prompts

    def get_call_trace(self) -> List[Dict[str, Any]]:
        """
        Return the full call trace for the last analysis cycle.

        Each entry contains:
        - messages: List[Dict] (system + user prompts sent to API)
        - temperature: float
        - response: str (full API response)
        - elapsed_sec: float
        - tokens: Dict with prompt/completion/total counts
        """
        return self.call_trace

