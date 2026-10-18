# apps/strategy_engine/services/trusted_input_builder.py
"""Server-derived evaluation input (Phase 11 CP1/CP2).

API clients may *reference* evidence (by id) but may never *assert* it.
Every trusted field — ``sync_status``, ``feed_compatibility``,
``data_freshness``, ``market_type``, ``instrument``, ``timeframe`` — is
resolved from **owned server-side rows**:

* ``chart_vision.ScreenshotAnalysis`` (what the vision pipeline observed),
* ``market_sync.MarketSyncSession`` (the verification verdict),
* ``market_data.MarketCandle`` (stored MT5 reference candles).

Request payloads are never consulted for these names; the views do not even
map them, so a forged ``sync_status="verified_alignment"`` in a POST body can
never reach the engine. The dual-source policy stays intact: without a
completed, owned sync session whose outcome is ``VERIFIED_ALIGNMENT`` the
invalidation engine forces NO TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.chart_vision.models import ScreenshotAnalysis
from apps.market_data.models import MarketCandle, MarketSymbol
from apps.market_sync.constants import SessionStatus, SyncStatus
from apps.market_sync.models import MarketSyncSession
from apps.strategy_engine.constants import InvalidationReasonCode

#: How many stored candles a single evaluation may load.
MAX_REFERENCE_CANDLES = 200


class EvidenceNotFound(Exception):
    """A referenced evidence row does not exist **for this owner**."""


class CandleValidationError(Exception):
    """Client-supplied candles are malformed (ambiguous timestamps, …)."""


@dataclass
class TrustedEvidence:
    """The fully server-derived evaluation input plus provenance."""

    input_data: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    analysis: ScreenshotAnalysis | None = None
    sync_session: MarketSyncSession | None = None
    candle_provenance: str = "none"

    @property
    def sync_status(self) -> str:
        return str(self.input_data.get("sync_status", "") or "")

    @property
    def is_verified(self) -> bool:
        return self.sync_status == SyncStatus.VERIFIED_ALIGNMENT


class TrustedInputBuilder:
    """Assemble evaluation input exclusively from owned server-side evidence."""

    def build(
        self,
        *,
        owner,
        screenshot_analysis_id: int | None = None,
        sync_session_id: int | None = None,
        requested_instrument: str = "",
        requested_timeframe: str = "",
        client_candles: list[dict[str, Any]] | None = None,
        analysis_obj: ScreenshotAnalysis | None = None,
        sync_session_obj: MarketSyncSession | None = None,
    ) -> TrustedEvidence:
        warnings: list[str] = []

        # Pre-resolved server objects (pipeline path) win over id lookups.
        analysis = analysis_obj or self._resolve_analysis(owner, screenshot_analysis_id)
        sync_session = sync_session_obj or self._resolve_sync_session(
            owner, sync_session_id, analysis
        )

        # -- instrument / timeframe / market type: server values only -------
        metadata = (analysis.chart_metadata if analysis else {}) or {}
        instrument, instrument_source = self._first(
            (sync_session.canonical_instrument if sync_session else ""),
            str(metadata.get("instrument") or ""),
        )
        timeframe, timeframe_source = self._first(
            (sync_session.mt5_timeframe if sync_session else ""),
            str(metadata.get("timeframe") or ""),
        )
        if not instrument:
            instrument = (requested_instrument or "").strip().upper()
            instrument_source = "client_reference"
            if instrument:
                warnings.append("instrument_unverified_client_reference")
        if not timeframe:
            timeframe = (requested_timeframe or "").strip().upper()
            timeframe_source = "client_reference"
            if timeframe:
                warnings.append("timeframe_unverified_client_reference")

        market_type = ""
        # Derive OTC from the only server evidence: vision otc_status and the
        # sync session's feed assessment (screenshot_is_otc). Never trust
        # arbitrary metadata "market_type" strings for the OTC guard.
        vision_otc = str(metadata.get("otc_status") or "").strip().lower()
        session_otc_flag = False
        if sync_session is not None:
            try:
                feed_assessment = getattr(sync_session, "feed_assessment", None)
            except Exception:
                feed_assessment = None
            if feed_assessment is not None:
                session_otc_flag = bool(getattr(feed_assessment, "screenshot_is_otc", False))
        if vision_otc == "otc" or session_otc_flag:
            market_type = "otc"
        else:
            if sync_session and sync_session.market_type:
                market_type = sync_session.market_type
            elif metadata.get("market_type"):
                mt = str(metadata.get("market_type")).strip().lower()
                if mt == "otc":
                    market_type = "otc"
                else:
                    market_type = mt

        # -- trusted sync verdicts ------------------------------------------
        sync_status = ""
        data_freshness = ""
        feed_compatibility = ""
        if sync_session is None:
            warnings.append(InvalidationReasonCode.INCOMPATIBLE_SYNC)
        elif sync_session.status != SessionStatus.COMPLETED:
            warnings.append("sync_session_not_completed")
        else:
            sync_status = sync_session.outcome or ""
            data_freshness = sync_session.freshness_status or ""
            feed_compatibility = sync_session.feed_compatibility or ""

        # -- candles: stored MT5 preferred, client candles are last resort --
        candles, provenance = self._resolve_candles(
            instrument=instrument,
            timeframe=timeframe,
            client_candles=client_candles,
            warnings=warnings,
        )

        screenshot_metadata: dict[str, Any] = {}
        if analysis is not None:
            screenshot_metadata = {
                "analysis_id": analysis.pk,
                "status": analysis.status,
                "provider": analysis.provider,
                "prompt_version": analysis.prompt_version,
                "chart_metadata": metadata,
                "warnings": list(analysis.warnings or []),
                "missing_information": list(analysis.missing_information or []),
            }

        mt5_snapshot: dict[str, Any] = {}
        if sync_session is not None:
            mt5_snapshot = {
                "sync_session_id": sync_session.pk,
                "outcome": sync_session.outcome,
                "feed_compatibility": sync_session.feed_compatibility,
                "freshness_status": sync_session.freshness_status,
                "reference_symbol": (
                    sync_session.reference_symbol.canonical if sync_session.reference_symbol else ""
                ),
                "broker_symbol": sync_session.mt5_broker_symbol,
                "aligned_candle_count": sync_session.aligned_candle_count,
                "matched_candle_count": sync_session.matched_candle_count,
                "comparison_method": sync_session.comparison_method,
            }

        input_data: dict[str, Any] = {
            "screenshot_analysis_id": analysis.pk if analysis else None,
            "screenshot_metadata": screenshot_metadata,
            "sync_session_id": sync_session.pk if sync_session else None,
            "instrument": instrument,
            "timeframe": timeframe,
            "market_type": market_type,
            "mt5_snapshot": mt5_snapshot,
            # Server-derived verdicts — never client input.
            "sync_status": sync_status,
            "data_freshness": data_freshness,
            "feed_compatibility": feed_compatibility,
            "completed_candles": candles,
            "all_candles": candles,
            "candle_provenance": provenance,
            "warnings": warnings,
        }
        del instrument_source, timeframe_source  # provenance kept in warnings only
        return TrustedEvidence(
            input_data=input_data,
            warnings=warnings,
            analysis=analysis,
            sync_session=sync_session,
            candle_provenance=provenance,
        )

    # -- lookups -----------------------------------------------------------

    #: Tokens vision/sync emit when something is genuinely unknown. They are
    #: *not* resolutions: an UNKNOWN instrument must fall through, not be
    #: treated as a verified identity.
    _UNRESOLVED = frozenset({"", "UNKNOWN", "UNRESOLVED", "NONE", "N/A"})

    @classmethod
    def _clean(cls, value: str) -> str:
        text = (value or "").strip()
        if text.upper() in cls._UNRESOLVED:
            return ""
        return text

    @classmethod
    def _first(cls, *values: str) -> tuple[str, str]:
        for index, value in enumerate(values):
            cleaned = cls._clean(value)
            if cleaned:
                return cleaned, f"server_{index}"
        return "", ""

    @staticmethod
    def _resolve_analysis(owner, analysis_id: int | None) -> ScreenshotAnalysis | None:
        if not analysis_id:
            return None
        try:
            return ScreenshotAnalysis.objects.get(pk=analysis_id, owner=owner)
        except ScreenshotAnalysis.DoesNotExist as exc:
            raise EvidenceNotFound("screenshot analysis not found") from exc

    @staticmethod
    def _resolve_sync_session(
        owner, sync_session_id: int | None, analysis: ScreenshotAnalysis | None
    ) -> MarketSyncSession | None:
        if not sync_session_id:
            return None
        try:
            session = MarketSyncSession.objects.select_related("reference_symbol").get(
                pk=sync_session_id
            )
        except MarketSyncSession.DoesNotExist as exc:
            raise EvidenceNotFound("sync session not found") from exc
        # Ownership: explicit owner match, or implicit via the linked analysis.
        owned = (session.owner_id is not None and session.owner_id == owner.pk) or (
            analysis is not None
            and session.analysis_id is not None
            and session.analysis_id == analysis.pk
        )
        if not owned:
            raise PermissionDenied("sync session does not belong to this user")
        return session

    # -- candles -----------------------------------------------------------

    def _resolve_candles(
        self,
        *,
        instrument: str,
        timeframe: str,
        client_candles: list[dict[str, Any]] | None,
        warnings: list[str],
    ) -> tuple[list[dict[str, Any]], str]:
        stored = self._stored_candles(instrument, timeframe)
        if stored:
            return stored, "stored_mt5"
        if client_candles:
            warnings.append("candles_unverified_client_supplied")
            return self._validate_client_candles(client_candles), "client_supplied"
        warnings.append("no_reference_candles_available")
        return [], "none"

    @staticmethod
    def _stored_candles(instrument: str, timeframe: str) -> list[dict[str, Any]]:
        if not instrument or not timeframe:
            return []
        symbols = MarketSymbol.objects.filter(
            Q(canonical__iexact=instrument) | Q(broker_symbol__iexact=instrument)
        )
        rows = MarketCandle.objects.filter(
            symbol__in=symbols, timeframe=timeframe, is_complete=True
        ).order_by("-open_time")[:MAX_REFERENCE_CANDLES]
        candles = [
            {
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                # ISO strings: JSONField-safe, and the timing validator parses
                # offsets correctly. close_time stays None so the validator
                # derives it from open + timeframe duration.
                "open_time": c.open_time.isoformat(),
                "close_time": None,
                "complete": bool(c.is_complete),
                "tick_volume": c.tick_volume,
                "source": c.source,
            }
            for c in reversed(list(rows))
        ]
        return candles

    @staticmethod
    def _validate_client_candles(client_candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from apps.core.timeutils import ensure_utc

        validated: list[dict[str, Any]] = []
        for index, raw in enumerate(client_candles):
            if not isinstance(raw, dict):
                raise CandleValidationError(f"candle {index} is not an object")
            for price in ("open", "high", "low", "close"):
                if not isinstance(raw.get(price), int | float):
                    raise CandleValidationError(f"candle {index} missing numeric {price}")
            open_time = raw.get("open_time")
            parsed = None
            if isinstance(open_time, datetime):
                parsed = ensure_utc(open_time)
            elif isinstance(open_time, str):
                from apps.core.timeutils import parse_iso_datetime

                parsed = parse_iso_datetime(open_time)
            if parsed is None:
                # An ambiguous/unparsable timestamp must never be silently
                # shifted — reject the whole request instead.
                raise CandleValidationError(
                    f"candle {index} open_time is missing a timezone offset"
                )
            close_time = raw.get("close_time")
            parsed_close = None
            if isinstance(close_time, datetime):
                parsed_close = ensure_utc(close_time)
            elif isinstance(close_time, str):
                from apps.core.timeutils import parse_iso_datetime

                parsed_close = parse_iso_datetime(close_time)
            validated.append(
                {
                    "open": float(raw["open"]),
                    "high": float(raw["high"]),
                    "low": float(raw["low"]),
                    "close": float(raw["close"]),
                    # ISO strings keep the input JSONField-safe; the timing
                    # validator re-parses the offsets exactly.
                    "open_time": parsed.isoformat(),
                    "close_time": parsed_close.isoformat() if parsed_close else None,
                    "complete": bool(raw.get("complete", True)),
                }
            )
        return validated


__all__ = [
    "MAX_REFERENCE_CANDLES",
    "CandleValidationError",
    "EvidenceNotFound",
    "TrustedEvidence",
    "TrustedInputBuilder",
]
