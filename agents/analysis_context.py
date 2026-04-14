"""
AnalysisContext — unified data carrier for the entire analysis pipeline.

Design principles:
1. All precomputed results live on context, consumers read-only (no recompute)
2. Agent outputs fill context incrementally, downstream agents read upstream results
3. Confidence chain tracks every confidence change with its source
4. Precomputed fields (features, valid_tags) are semantically immutable after creation (convention, not enforced)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class ConfidenceStep:
    """A single step in the confidence chain."""
    phase: str          # "judge" | "entry_timing" | "risk" | "schema_default"
    value: str          # "HIGH" | "MEDIUM" | "LOW"
    origin: str         # "AI" | "DEFAULT" | "COERCED" | "CAPPED"
    reason: str = ""    # Why the change happened


@dataclass
class ConfidenceChain:
    """Tracks confidence source and mutations across phases."""
    steps: List[ConfidenceStep] = field(default_factory=list)

    def add(self, phase: str, value: str, origin: str, reason: str = ""):
        self.steps.append(ConfidenceStep(phase, value, origin, reason))

    @property
    def final(self) -> str:
        return self.steps[-1].value if self.steps else "MEDIUM"

    @property
    def final_origin(self) -> str:
        return self.steps[-1].origin if self.steps else "UNKNOWN"

    def has_default(self) -> bool:
        """Whether any phase used a schema default."""
        return any(s.origin in ("DEFAULT", "COERCED") for s in self.steps)


@dataclass
class MemoryConditions:
    """
    Feature-based memory condition snapshot.

    Replaces free-text "RSI=65, MACD=bullish, BB=72%"
    with feature_dict subset for multi-dimensional similarity matching.
    """
    # v5.10 original dimensions (backward compat)
    rsi_30m: float = 50.0
    macd_bullish: bool = True
    bb_position_30m: float = 50.0
    sentiment: str = "neutral"           # crowded_long / neutral / crowded_short
    direction: str = "LONG"              # LONG / SHORT

    # v29+ new dimensions (critical for memory similarity)
    adx_1d: float = 25.0
    adx_regime: str = "WEAK_TREND"       # STRONG_TREND / WEAK_TREND / RANGING
    extension_regime: str = "NORMAL"     # NORMAL / EXTENDED / OVEREXTENDED / EXTREME
    volatility_regime: str = "NORMAL"    # LOW / NORMAL / HIGH / EXTREME
    cvd_trend_30m: str = "NEUTRAL"       # POSITIVE / NEGATIVE / NEUTRAL
    funding_rate_pct: float = 0.0
    rsi_4h: float = 50.0

    @classmethod
    def from_feature_dict(cls, fd: Dict[str, Any]) -> "MemoryConditions":
        """Build from feature_dict to ensure consistency with what agents see."""
        macd_val = fd.get("macd_30m", 0)
        macd_sig = fd.get("macd_signal_30m", 0)
        lr = fd.get("long_ratio", 0.5)
        if lr > 0.6:
            sent = "crowded_long"
        elif lr < 0.4:
            sent = "crowded_short"
        else:
            sent = "neutral"

        # Direction: MACD lean priority, RSI fallback (consistent with v5.11)
        macd_bullish = (macd_val > macd_sig)
        rsi = fd.get("rsi_30m", 50.0)
        if macd_val != 0 or macd_sig != 0:
            direction = "LONG" if macd_bullish else "SHORT"
        else:
            direction = "LONG" if rsi >= 50 else "SHORT"

        return cls(
            rsi_30m=fd.get("rsi_30m", 50.0),
            macd_bullish=macd_bullish,
            # bb_position_30m in feature_dict is 0-1 range, multiply by 100 for 0-100%
            bb_position_30m=fd.get("bb_position_30m", 0.5) * 100,
            sentiment=sent,
            direction=direction,
            adx_1d=fd.get("adx_1d", 25.0),
            adx_regime=fd.get("market_regime", "WEAK_TREND"),
            extension_regime=fd.get("extension_regime_30m", "NORMAL"),
            volatility_regime=fd.get("volatility_regime_30m", "NORMAL"),
            cvd_trend_30m=fd.get("cvd_trend_30m", "NEUTRAL"),
            funding_rate_pct=fd.get("funding_rate_pct", 0.0),
            rsi_4h=fd.get("rsi_4h", 50.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for memory retrieval and snapshot storage.

        Only new-format keys. _score_memory() reads these directly.
        No legacy key output (old rsi/macd/bb keys are not written).
        """
        return {
            "rsi_30m": self.rsi_30m,
            "macd_bullish": self.macd_bullish,
            "bb_position_30m": self.bb_position_30m,
            "sentiment": self.sentiment,
            "direction": self.direction,
            "adx_regime": self.adx_regime,
            "extension_regime": self.extension_regime,
            "volatility_regime": self.volatility_regime,
            "cvd_trend_30m": self.cvd_trend_30m,
            "rsi_4h": self.rsi_4h,
            "adx_1d": self.adx_1d,
            "funding_rate_pct": self.funding_rate_pct,
        }


@dataclass
class AnalysisContext:
    """
    Unified data carrier for the entire analysis pipeline.

    Lifecycle:
      analyze() entry creates → precompute fills → agents fill incrementally → auditor validates → return
    """

    # ===== Metadata =====
    snapshot_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    symbol: str = "BTCUSDT"

    # ===== Phase 1: Data quality (simplified to List[str]) =====
    data_warnings: List[str] = field(default_factory=list)

    # ===== Phase 2: Precomputed (computed once, shared across pipeline) =====
    # These fields are filled at analyze() entry, then read-only
    features: Optional[Dict[str, Any]] = None       # extract_features() result
    scores: Optional[Dict[str, Any]] = None         # compute_scores() result
    valid_tags: Optional[Set[str]] = None            # compute_valid_tags() result
    annotated_tags: Optional[str] = None             # compute_annotated_tags() result

    # ===== Phase 3: Memory =====
    memory_conditions: Optional[MemoryConditions] = None

    # ===== Phase 4: Confidence chain =====
    confidence_chain: ConfidenceChain = field(default_factory=ConfidenceChain)

    # ===== Phase 4b: Agent outputs (filled incrementally during pipeline) =====
    bull_output: Optional[Dict[str, Any]] = None    # Bull structured output (R2)
    bear_output: Optional[Dict[str, Any]] = None    # Bear structured output (R2)
    judge_output: Optional[Dict[str, Any]] = None   # Judge decision dict
    et_output: Optional[Dict[str, Any]] = None      # Entry Timing result
    risk_output: Optional[Dict[str, Any]] = None    # Risk Manager result
    debate_bull_text: str = ""                       # Bull last-round text
    debate_bear_text: str = ""                       # Bear last-round text

    # ===== Phase 5: Quality audit =====
    quality_score: Optional[int] = None
    quality_flags: Optional[List[str]] = None

    # ===== v30.0: Raw data bundle (transition) =====
    # audit() reads ground truth from ctx.features (= what agents saw).
    # raw_data is kept as fallback for diagnostic scripts that call audit()
    # without features. Keys: technical, sentiment, order_flow, derivatives,
    # orderbook, sr_zones.
    raw_data: Optional[Dict[str, Any]] = None

    def is_prepared(self) -> bool:
        """Whether the precompute phase is complete."""
        return self.features is not None and self.valid_tags is not None

    def to_dict(self) -> Dict[str, Any]:
        """Debug/logging: serialize key state to dict."""
        return {
            "snapshot_id": self.snapshot_id,
            "symbol": self.symbol,
            "is_prepared": self.is_prepared(),
            "data_warnings": self.data_warnings,
            "valid_tags_count": len(self.valid_tags) if self.valid_tags else 0,
            "confidence_chain": [
                {"phase": s.phase, "value": s.value, "origin": s.origin}
                for s in self.confidence_chain.steps
            ],
            "quality_score": self.quality_score,
        }
