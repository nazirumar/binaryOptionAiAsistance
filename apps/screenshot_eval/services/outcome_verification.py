# screenshot_eval/services/outcome_verification.py
"""Outcome verification against the correct feed (Checkpoint 5).

The rule is absolute: **do not substitute ordinary MT5 prices for IQ Option OTC
settlement prices**, and if an outcome cannot be independently verified, mark it
``unverified`` rather than assuming the prediction succeeded. Ties and
unresolved outcomes are recorded separately.

This service reuses :class:`~apps.book_strategies.services.settlement.BookSettlementService`
for the win/loss/tie arithmetic and adds the screenshot-level feed match:

* an OTC prediction needs an OTC price source; a regular/MT5 source is refused
  (``INCOMPATIBLE_FEEDS``);
* a regular prediction must not be settled from a source that lies about being
  OTC;
* with no settlement quote at all, the verdict is ``unverifiable`` and the
  prediction stays locked-to-unverified (never counted as correct).

A verification is written once; the prediction transitions out of ``locked``
exactly once through ``verify_outcome``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.book_strategies.services.settlement import (
    MT5_SOURCES,
    STATUS_REFUSED,
    STATUS_TIE,
    STATUS_UNVERIFIABLE,
    STATUS_WIN,
    BookSettlementService,
)
from apps.screenshot_eval.constants import (
    REASON_INCOMPATIBLE_FEEDS,
    REASON_NO_QUOTE,
    OutcomeVerdict,
    PredictionDirection,
    PredictionStatus,
)
from apps.screenshot_eval.models import (
    ForwardPaperPrediction,
    OutcomeVerification,
)


def _norm_source(price_source: str) -> str:
    return (price_source or "").strip().lower()


def feed_is_mt5(price_source: str) -> bool:
    source = _norm_source(price_source)
    return source in MT5_SOURCES or source.startswith("mt5")


class OutcomeVerificationService:
    """Verify one forward prediction's outcome from platform quotes."""

    def __init__(self) -> None:
        self._settlement = BookSettlementService()

    @transaction.atomic
    def verify(
        self,
        *,
        prediction: ForwardPaperPrediction,
        owner,
        entry_quote: float | None = None,
        settlement_quote: float | None = None,
        price_source: str = "",
        feed_market_type: str = "",
        feed: str = "",
        outcome_timestamp: datetime | None = None,
        payout_rate: float = 80.0,
    ) -> OutcomeVerification:
        """Independently verify the outcome and transition the prediction once.

        Refusals/unverifiable outcomes are persisted but do **not** falsely
        record the prediction as verified: the prediction moves to
        ``unverified`` (or stays locked for a pending window) and is excluded
        from accuracy statistics.
        """
        direction = "bullish" if prediction.direction == PredictionDirection.UP else "bearish"
        market_type = prediction.market_type or "regular"

        # NO TRADE decisions have no outcome to verify.
        if prediction.direction == PredictionDirection.NO_TRADE:
            return self._write(
                prediction=prediction,
                owner=owner,
                verdict=OutcomeVerdict.PENDING,
                status=PredictionStatus.UNRESOLVED,
                feed=feed,
                feed_market_type=feed_market_type,
                entry_quote=entry_quote,
                settlement_quote=settlement_quote,
                outcome_timestamp=outcome_timestamp,
                reason_code="NO_TRADE_NO_OUTCOME",
                reason="NO TRADE is a decision, not a prediction; there is no outcome to verify.",
                evidence={"direction": prediction.direction},
                transition=False,
            )

        # Feed gate (before any arithmetic): never coerce a wrong feed.
        if market_type == "otc" and (not price_source or feed_is_mt5(price_source)):
            ver = self._write(
                prediction=prediction,
                owner=owner,
                verdict=OutcomeVerdict.REFUSED,
                status=PredictionStatus.UNVERIFIED,
                feed=feed,
                feed_market_type=feed_market_type,
                entry_quote=entry_quote,
                settlement_quote=settlement_quote,
                outcome_timestamp=outcome_timestamp,
                reason_code=REASON_INCOMPATIBLE_FEEDS,
                reason=(
                    "OTC predictions settle on OTC-platform quotes; a regular/MT5 "
                    "price source is refused, not substituted."
                ),
                evidence={"market_type": market_type, "price_source": price_source},
                transition=True,
            )
            return ver

        record = self._settlement.evaluate(
            direction=direction,
            entry_quote=entry_quote,
            settlement_quote=settlement_quote,
            price_source=price_source,
            market_type=market_type,
            payout_rate=payout_rate,
        )
        status = record.get("status")

        if status == STATUS_REFUSED:
            return self._write(
                prediction=prediction,
                owner=owner,
                verdict=OutcomeVerdict.REFUSED,
                status=PredictionStatus.UNVERIFIED,
                feed=feed,
                feed_market_type=feed_market_type,
                entry_quote=entry_quote,
                settlement_quote=settlement_quote,
                outcome_timestamp=outcome_timestamp,
                reason_code=record.get("reason_code", REASON_INCOMPATIBLE_FEEDS),
                reason=record.get("reason", ""),
                evidence=record,
                transition=True,
            )

        if status == STATUS_UNVERIFIABLE or not record.get("verifiable"):
            return self._write(
                prediction=prediction,
                owner=owner,
                verdict=OutcomeVerdict.UNVERIFIABLE,
                status=PredictionStatus.UNVERIFIED,
                feed=feed,
                feed_market_type=feed_market_type,
                entry_quote=entry_quote,
                settlement_quote=settlement_quote,
                outcome_timestamp=outcome_timestamp,
                reason_code=REASON_NO_QUOTE,
                reason=record.get(
                    "reason",
                    "no settlement quote supplied; outcome marked unverified, "
                    "never assumed correct",
                ),
                evidence=record,
                transition=True,
            )

        # Verifiable: win / loss / tie.
        if status == STATUS_TIE:
            verdict = OutcomeVerdict.TIE
            terminal = PredictionStatus.TIE
        else:
            verdict = (
                OutcomeVerdict.CORRECT if status == STATUS_WIN else OutcomeVerdict.INCORRECT
            )
            terminal = PredictionStatus.VERIFIED
        return self._write(
            prediction=prediction,
            owner=owner,
            verdict=verdict,
            status=terminal,
            feed=feed,
            feed_market_type=feed_market_type,
            entry_quote=record.get("entry", entry_quote),
            settlement_quote=record.get("settlement", settlement_quote),
            outcome_timestamp=outcome_timestamp,
            reason_code="",
            reason="settled from platform quotes for the matching feed",
            evidence=record,
            transition=True,
        )

    # ------------------------------------------------------------------
    def _write(
        self,
        *,
        prediction: ForwardPaperPrediction,
        owner,
        verdict: str,
        status: str,
        feed: str,
        feed_market_type: str,
        entry_quote: float | None,
        settlement_quote: float | None,
        outcome_timestamp: datetime | None,
        reason_code: str,
        reason: str,
        evidence: dict[str, Any],
        transition: bool,
    ) -> OutcomeVerification:
        existing = OutcomeVerification.objects.filter(prediction=prediction).first()
        if existing is not None:
            return existing
        record = OutcomeVerification.objects.create(
            prediction=prediction,
            owner=owner,
            verdict=verdict,
            status=status,
            feed=feed,
            feed_market_type=feed_market_type,
            entry_quote=entry_quote,
            settlement_quote=settlement_quote,
            outcome_timestamp=outcome_timestamp,
            reason_code=reason_code,
            reason=reason,
            evidence=evidence,
            verified_at=timezone.now(),
        )
        if transition and prediction.status == PredictionStatus.LOCKED:
            # REFUSED/UNVERIFIABLE still leave "locked" via verify_outcome; the
            # status distinguishes them so they never reach verified accuracy.
            terminal = (
                PredictionStatus.UNVERIFIED
                if status in (PredictionStatus.UNVERIFIED, PredictionStatus.UNRESOLVED)
                else status
            )
            prediction.verify_outcome(verdict=terminal)
        return record


__all__ = ["OutcomeVerificationService", "feed_is_mt5"]
