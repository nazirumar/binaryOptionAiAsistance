# book_strategies/services/recognition.py
"""Book-strategy recognition over candle data and screenshot observations.

Two entry points:

- :func:`build_book_candidates` maps a screenshot analysis' *persisted vision
  records* to book-strategy candidates. Screenshot evidence is qualitative: no
  OHLC values are ever invented from pixels, so candidates are capped at
  ``AWAITING_CONFIRMATION`` with ``data_verification = SCREENSHOT_ONLY`` and
  every book requirement listed as missing until deterministically verified.

- :class:`BookStrategyRecognizer` evaluates a catalogued strategy against a
  supplied closed-candle series with the state-machine detectors. When the
  caller passes candles that are NOT compatible with the screenshot (e.g. MT5
  candles for an OTC capture), the evaluation is refused with
  ``INCOMPATIBLE_FEEDS`` and ``INSUFFICIENT_DATA``.

The structured response (``BookDetection.as_dict``) follows the Step 9 shape:
``decision`` is always ``NO_TRADE`` and ``probability`` always ``None`` -
recognised patterns are observations, never predictions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from apps.book_strategies.constants import (
    DECISION_NO_TRADE,
    PROBABILITY_STATUS,
    SPEC_BY_KEY,
    BookPatternState,
    DataVerification,
)
from apps.book_strategies.services.detectors import BOOK_DETECTORS, BookPatternResult

#: Vision label (normalised) -> book strategy keys it can seed a candidate for.
#: Anything absent here is simply not mapped - no fuzzy guessing, no invented
#: strategy numbers.
VISION_BOOK_MAP: dict[str, tuple[str, ...]] = {
    "bullish_engulfing": ("SS4",),
    "bearish_engulfing": ("SS4",),
    "doji": ("SS12", "SS19", "SS20"),
    "dragonfly_doji": ("SS12",),
    "gravestone_doji": ("SS12",),
    "hammer": ("SS15", "SS16"),
    "inverted_hammer": ("SS15", "SS16"),
    "three_white_soldiers": ("SS22",),
    "three_black_crows": ("SS23",),
    "morning_star": (),
    "evening_star": (),
}

_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


def _normalise(name: str) -> str:
    return _NORMALISE_RE.sub("_", str(name).strip().lower()).strip("_")


def analysis_is_otc(analysis: Any) -> bool:
    """True when the screenshot's chart metadata declares an OTC market."""
    metadata = ((getattr(analysis, "result", None) or {}).get("chart_metadata")) or {}
    status = str(metadata.get("otc_status", "") or "").lower()
    return "otc" in status


@dataclass(slots=True)
class BookCandidate:
    """A vision-sourced book-strategy candidate awaiting verification."""

    strategy_key: str
    book_number: int
    strategy_name: str
    source_kind: str  # pattern | observation
    source_label: str
    confidence: float | None
    evidence: list[str] = field(default_factory=list)
    missing_conditions: list[str] = field(default_factory=list)
    state: str = BookPatternState.AWAITING_CONFIRMATION
    data_verification: str = DataVerification.SCREENSHOT_ONLY

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": f"BOOK_{self.strategy_key}",
            "strategy_name": self.strategy_name,
            "book_pattern_number": self.book_number,
            "recognition_status": self.state,
            "observed_evidence": list(self.evidence),
            "missing_conditions": list(self.missing_conditions),
            "data_verification": self.data_verification,
            "decision": DECISION_NO_TRADE,
            "probability": None,
            "probability_status": PROBABILITY_STATUS,
        }


def build_book_candidates(analysis: Any) -> list[BookCandidate]:
    """Map a screenshot analysis' persisted vision records to book candidates.

    The mapping is a fixed table: unknown labels are never guessed, and every
    candidate carries the full requirement list of its book strategy as
    ``missing_conditions`` - because a screenshot cannot verify any of them
    deterministically. Deduplicated by strategy key (first source wins).
    """
    wanted: dict[str, tuple[str, str]] = {}  # book key -> (kind, source label)
    pattern_records = getattr(analysis, "patterns", None) if analysis else None
    observation_records = getattr(analysis, "observations", None) if analysis else None
    if pattern_records is not None:
        for record in pattern_records.all():
            label = _normalise(getattr(record, "name", ""))
            for key in VISION_BOOK_MAP.get(label, ()):
                wanted.setdefault(key, ("pattern", label))
    if observation_records is not None:
        for record in observation_records.all():
            label = _normalise(getattr(record, "label", ""))
            for key in VISION_BOOK_MAP.get(label, ()):
                wanted.setdefault(key, ("observation", label))

    candidates: list[BookCandidate] = []
    for book_key, (kind, label) in wanted.items():
        spec = SPEC_BY_KEY.get(book_key)
        if spec is None:  # defensive: the map must only hold catalog keys
            continue
        evidence = [
            f"vision {kind} '{label}' observed on the screenshot "
            "(qualitative observation - no OHLC values inferred from pixels)"
        ]
        candidates.append(
            BookCandidate(
                strategy_key=book_key,
                book_number=spec.number,
                strategy_name=spec.name,
                source_kind=kind,
                source_label=label,
                confidence=None,
                evidence=evidence,
                missing_conditions=list(spec.requirements),
            )
        )
    return candidates


@dataclass(slots=True)
class BookDetection:
    """Structured recognition result for one book strategy (Step 9 shape)."""

    strategy_id: str
    strategy_key: str
    book_pattern_number: int
    strategy_name: str
    recognition_status: str
    observed_evidence: list[str]
    missing_conditions: list[str]
    data_verification: str
    decision: str = DECISION_NO_TRADE
    probability: float | None = None
    probability_status: str = PROBABILITY_STATUS
    direction: str = "neutral"
    candle_refs: list[int] = field(default_factory=list)
    reference_level: float | None = None
    level_kind: str = ""
    stochastic_supported: bool | None = None
    completed_at: int | None = None
    invalidations: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Step 9 structured analysis response (application schema)."""
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "book_pattern_number": self.book_pattern_number,
            "recognition_status": self.recognition_status,
            "observed_evidence": list(self.observed_evidence),
            "missing_conditions": list(self.missing_conditions),
            "data_verification": self.data_verification,
            "direction": self.direction,
            "candle_refs": list(self.candle_refs),
            "reference_level": self.reference_level,
            "level_kind": self.level_kind,
            "stochastic_supported": self.stochastic_supported,
            "completed_at": self.completed_at,
            "invalidations": list(self.invalidations),
            "contradictions": list(self.contradictions),
            "decision": self.decision,
            "probability": self.probability,
            "probability_status": self.probability_status,
        }


class BookStrategyRecognizer:
    """Evaluate catalogued book strategies against closed candle data."""

    def evaluate(
        self,
        key: str,
        candles: list[dict[str, Any]],
        *,
        instrument: str = "",
        timeframe: str = "",
        market_type: str = "",
        last_candle_forming: bool = False,
        feed_market_type: str = "",
        screenshot_is_otc: bool = False,
        analysis: Any = None,
        persist: bool = True,
    ) -> BookDetection:
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            raise KeyError(f"unknown book strategy key: {key!r}")

        feed_compatible = not (screenshot_is_otc and feed_market_type != "otc")
        detector = BOOK_DETECTORS.get(spec.detector_key) if spec.detector_key else None

        if detector is None:
            result = BookPatternResult(
                strategy_key=spec.key.lower(),
                state=BookPatternState.INSUFFICIENT_DATA,
                observed_evidence=[
                    "this strategy is catalogued from the book but has no "
                    "deterministic detector yet (Step 2 extraction only)"
                ],
            )
            verification = DataVerification.NOT_EVALUATED
        elif not feed_compatible:
            result = BookPatternResult(
                strategy_key=spec.detector_key,
                state=BookPatternState.INSUFFICIENT_DATA,
                observed_evidence=[
                    "market-data feeds are incompatible: an OTC screenshot "
                    "cannot be verified with non-OTC candle data (book "
                    "patterns stay screenshot-only here)"
                ],
            )
            verification = DataVerification.INCOMPATIBLE_FEEDS
        else:
            result = detector(candles, last_candle_forming=last_candle_forming)
            verification = DataVerification.OHLC_VERIFIED

        evidence = list(result.observed_evidence)
        missing = list(result.missing_conditions)

        detection = BookDetection(
            strategy_id=f"BOOK_{spec.key}",
            strategy_key=spec.key,
            book_pattern_number=spec.number,
            strategy_name=spec.name,
            recognition_status=result.state,
            observed_evidence=evidence,
            missing_conditions=missing,
            data_verification=verification,
            direction=result.direction,
            candle_refs=list(result.candle_refs),
            reference_level=result.reference_level,
            level_kind=result.level_kind,
            stochastic_supported=result.stochastic_supported,
            completed_at=result.completed_at,
            invalidations=list(result.invalidations),
            contradictions=list(spec.contradictions),
            ambiguities=[*spec.ambiguities, *result.ambiguities],
        )

        if persist:
            self._persist(detection, analysis=analysis, market_type=market_type,
                          instrument=instrument, timeframe=timeframe)
        return detection

    def evaluate_enabled(
        self,
        candles: list[dict[str, Any]],
        *,
        instrument: str = "",
        timeframe: str = "",
        market_type: str = "",
        last_candle_forming: bool = False,
        persist: bool = True,
    ) -> list[BookDetection]:
        """Evaluate every catalogued strategy whose admin switch is on."""
        from apps.book_strategies.models import BookStrategy

        rows = BookStrategy.objects.filter(recognition_enabled=True)
        return [
            self.evaluate(
                row.key,
                candles,
                instrument=instrument,
                timeframe=timeframe,
                market_type=market_type,
                last_candle_forming=last_candle_forming,
                persist=persist,
            )
            for row in rows
        ]

    @staticmethod
    def _persist(
        detection: BookDetection,
        *,
        analysis: Any,
        market_type: str,
        instrument: str,
        timeframe: str,
    ) -> None:
        from apps.book_strategies.models import BookStrategy, BookStrategyDetection

        try:
            strategy = BookStrategy.objects.get(key=detection.strategy_key)
        except BookStrategy.DoesNotExist:
            return
        BookStrategyDetection.objects.create(
            strategy=strategy,
            analysis=analysis,
            state=detection.recognition_status,
            direction=detection.direction,
            observed_evidence=detection.observed_evidence,
            missing_conditions=detection.missing_conditions,
            contradictions=detection.contradictions,
            candle_refs=detection.candle_refs,
            reference_level=detection.reference_level,
            level_kind=detection.level_kind,
            stochastic_supported=detection.stochastic_supported,
            data_verification=detection.data_verification,
            instrument=instrument,
            timeframe=timeframe,
            market_type=market_type,
        )
