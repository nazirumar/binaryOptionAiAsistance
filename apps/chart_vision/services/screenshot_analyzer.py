"""End-to-end screenshot analysis orchestration.

Pipeline: read private bytes -> validate/preprocess -> build prompt -> call the
configured provider (bounded retries + rate-limit backoff) -> parse JSON ->
strict schema validation -> normalise candles/metadata/structure/patterns/zones ->
persist the single authoritative result plus compact derived rows.

A provider or schema failure transitions the analysis to ``failed`` with a
machine-readable code and **never** produces a fabricated result.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.chart_vision.constants import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    AnalysisStatus,
    EventKind,
    ScreenshotQuality,
    Severity,
)
from apps.chart_vision.models import (
    ChartScreenshot,
    DetectedPattern,
    DetectedPriceZone,
    ScreenshotAnalysis,
    VisionObservation,
)
from apps.chart_vision.services.candle_extractor import normalize_candles
from apps.chart_vision.services.chart_metadata import (
    build_metadata_observations,
    missing_metadata_information,
)
from apps.chart_vision.services.events import record_event
from apps.chart_vision.services.exceptions import (
    ChartVisionError,
    SchemaValidationError,
    VisionProviderUnavailableError,
    VisionRateLimitError,
    VisionTimeoutError,
)
from apps.chart_vision.services.image_preprocessor import preprocess_image
from apps.chart_vision.services.pattern_observer import (
    advance_pattern_records,
    build_cycle_observations,
    build_liquidity_observations,
    build_patterns,
    build_price_zones,
    build_sequence_observations,
    build_structure_observations,
    build_volume_observations,
)
from apps.chart_vision.services.schema_validator import (
    parse_json_object,
    validate_payload,
)
from apps.chart_vision.services.vision_provider import VisionProvider, get_vision_provider

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

#: Upper bound on any single retry sleep (seconds) to keep jobs bounded.
_MAX_BACKOFF_SECONDS = 30.0


def build_idempotency_key(
    screenshot_id: int,
    *,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """Stable key deduplicating analysis jobs for a screenshot/prompt/schema."""
    return f"analyze:{screenshot_id}:{prompt_version}:{schema_version}"


def get_or_create_analysis(
    screenshot: ChartScreenshot,
    *,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> tuple[ScreenshotAnalysis, bool]:
    """Return the (unique) analysis row for a screenshot, creating it if needed."""
    key = build_idempotency_key(
        screenshot.pk, prompt_version=prompt_version, schema_version=schema_version
    )
    return ScreenshotAnalysis.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "screenshot": screenshot,
            "owner": screenshot.owner,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
        },
    )


class ScreenshotAnalyzer:
    """Runs the analysis pipeline for a single screenshot/analysis pair."""

    def __init__(
        self,
        provider: VisionProvider | None = None,
        *,
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
        sleep=time.sleep,
    ) -> None:
        self.provider = provider
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self._sleep = sleep

    # -- prompt -----------------------------------------------------------
    def build_prompt(self) -> str:
        path = PROMPTS_DIR / f"chart_analysis_{self.prompt_version}.md"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - packaging guard
            logger.warning("chart_vision.prompt_missing", extra={"path": str(path)})
            return (
                "Analyse the attached candlestick chart. Return only a JSON object "
                "matching the chart-analysis v1 schema. Use UNKNOWN when a value is "
                "unreadable. Never invent prices or probabilities."
            )

    # -- provider call with bounded retries -------------------------------
    def _analyze_with_retries(self, provider: VisionProvider, image, prompt: str):
        max_retries = max(0, int(getattr(provider.config, "max_retries", 0)))
        backoff = float(getattr(provider.config, "backoff_seconds", 1.5))
        attempt = 0
        while True:
            try:
                return provider.analyze(
                    image_bytes=image.data, mime_type=image.mime_type, prompt=prompt
                )
            except (VisionRateLimitError, VisionTimeoutError) as exc:
                if attempt >= max_retries:
                    raise
                delay = getattr(exc, "retry_after", None)
                delay = float(delay) if delay is not None else backoff * (2**attempt)
                delay = min(delay, _MAX_BACKOFF_SECONDS)
                logger.warning(
                    "chart_vision.provider_retry",
                    extra={"error": type(exc).__name__, "attempt": attempt + 1, "delay": delay},
                )
                self._sleep(delay)
                attempt += 1
            except VisionProviderUnavailableError as exc:
                if not getattr(exc, "retryable", True) or attempt >= max_retries:
                    raise
                delay = min(backoff * (2**attempt), _MAX_BACKOFF_SECONDS)
                self._sleep(delay)
                attempt += 1

    # -- main entry point -------------------------------------------------
    def analyze(
        self, screenshot: ChartScreenshot, analysis: ScreenshotAnalysis
    ) -> ScreenshotAnalysis:
        """Run the pipeline and return the (updated) analysis row."""
        analysis.status = AnalysisStatus.RUNNING
        analysis.attempts = (analysis.attempts or 0) + 1
        analysis.started_at = timezone.now()
        analysis.error_code = ""
        analysis.error_message = ""
        analysis.provider = analysis.provider or str(
            getattr(settings, "VISION_LLM_PROVIDER", "mock")
        )
        analysis.save(
            update_fields=[
                "status",
                "attempts",
                "started_at",
                "error_code",
                "error_message",
                "provider",
                "updated_at",
            ]
        )

        try:
            raw_bytes = self._read_image(screenshot)
            image = preprocess_image(raw_bytes)
            prompt = self.build_prompt()
            provider = self.provider or get_vision_provider()

            record_event(
                analysis=analysis,
                kind=EventKind.PROVIDER_REQUEST,
                message="Sending screenshot to vision provider.",
                detail={
                    "provider": provider.name,
                    "model": provider.model,
                    "prompt_version": self.prompt_version,
                    "image": {"width": image.width, "height": image.height},
                },
            )
            result = self._analyze_with_retries(provider, image, prompt)
            record_event(
                analysis=analysis,
                kind=EventKind.PROVIDER_RESPONSE,
                message="Vision provider responded.",
                detail={
                    "provider": result.provider,
                    "model": result.model,
                    "latency_ms": result.latency_ms,
                    "usage": {
                        "prompt_tokens": result.usage.prompt_tokens,
                        "completion_tokens": result.usage.completion_tokens,
                        "total_tokens": result.usage.total_tokens,
                    },
                },
            )

            payload = parse_json_object(result.raw_text)
            validation = validate_payload(payload, schema_version=self.schema_version)
            if not validation.valid:
                raise SchemaValidationError(
                    "Structured output failed schema validation.",
                    errors=validation.errors,
                )

            normalized = self._normalize(validation.payload, validation.warnings)
            record_event(
                analysis=analysis,
                kind=EventKind.SCHEMA,
                message="Structured output validated.",
                detail={"warnings": normalized["warnings"][:20]},
            )
            return self._persist(analysis, screenshot, result, normalized)
        except ChartVisionError as exc:
            self._fail(analysis, exc)
            raise
        except Exception as exc:  # pragma: no cover - unexpected; never fabricate
            logger.exception("chart_vision.unexpected_error")
            self._fail(analysis, exc, code="unexpected_error")
            raise

    # -- internal helpers -------------------------------------------------
    def _read_image(self, screenshot: ChartScreenshot) -> bytes:
        storage = screenshot.image.storage
        with storage.open(screenshot.image.name, "rb") as handle:
            return handle.read()

    def _normalize(self, payload: dict[str, Any], schema_warnings: list[str]) -> dict[str, Any]:
        warnings = list(schema_warnings) + list(payload.get("warnings", []))
        metadata = payload["chart_metadata"]
        quality = payload["screenshot_quality"]

        candles = normalize_candles(payload.get("candles"), warnings)

        if quality.get("rating") in (ScreenshotQuality.LOW, ScreenshotQuality.UNUSABLE):
            warnings.append("Low-quality screenshot: observations may be unreliable or incomplete.")
        for issue in quality.get("issues", []) or []:
            warnings.append(f"Screenshot issue reported: {issue}")

        missing = list(payload.get("missing_information", []))
        for item in missing_metadata_information(metadata):
            if item not in missing:
                missing.append(item)

        observations = (
            build_metadata_observations(metadata, quality)
            + build_structure_observations(payload.get("market_structure", {}))
            + build_sequence_observations(payload.get("sequence_observations"))
            + build_liquidity_observations(payload.get("liquidity"))
            + build_cycle_observations(payload.get("market_cycle"))
            + build_volume_observations(payload.get("volume"))
        )
        patterns = build_patterns(payload.get("patterns")) + advance_pattern_records(
            payload.get("sequence_observations"), payload.get("liquidity")
        )
        zones = build_price_zones(payload.get("support_resistance"))

        status = self._resolve_status(payload.get("analysis_status"), quality, missing)

        result_payload = dict(payload)
        result_payload["candles"] = candles
        result_payload["missing_information"] = missing
        result_payload["warnings"] = warnings
        result_payload["analysis_status"] = status
        result_payload["provider_meta"] = {
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
        }

        return {
            "payload": result_payload,
            "chart_metadata": metadata,
            "candles": candles,
            "observations": observations,
            "patterns": patterns,
            "price_zones": zones,
            "warnings": warnings,
            "missing_information": missing,
            "observation_confidence": (payload.get("observation_confidence") or {}).get("overall"),
            "status": status,
        }

    @staticmethod
    def _resolve_status(provider_status: Any, quality: dict[str, Any], missing: list[str]) -> str:
        rating = quality.get("rating")
        if provider_status == "insufficient_evidence" or rating == ScreenshotQuality.UNUSABLE:
            return AnalysisStatus.INSUFFICIENT
        if provider_status == "partial" or missing:
            return AnalysisStatus.PARTIAL
        return AnalysisStatus.COMPLETED

    def _persist(
        self,
        analysis: ScreenshotAnalysis,
        screenshot: ChartScreenshot,
        result,
        normalized: dict[str, Any],
    ) -> ScreenshotAnalysis:
        with transaction.atomic():
            analysis.result = normalized["payload"]
            analysis.chart_metadata = normalized["chart_metadata"]
            analysis.candle_count = len(normalized["candles"])
            analysis.observation_confidence = normalized["observation_confidence"]
            analysis.warnings = normalized["warnings"]
            analysis.missing_information = normalized["missing_information"]
            analysis.status = normalized["status"]
            analysis.provider = result.provider
            analysis.model_name = result.model
            analysis.prompt_version = self.prompt_version
            analysis.schema_version = self.schema_version
            analysis.prompt_tokens = result.usage.prompt_tokens
            analysis.completion_tokens = result.usage.completion_tokens
            analysis.total_tokens = result.usage.total_tokens
            analysis.provider_latency_ms = result.latency_ms
            analysis.error_code = ""
            analysis.error_message = ""
            analysis.finished_at = timezone.now()
            analysis.save()

            # Idempotent derived rows: replace any from a previous attempt.
            analysis.observations.all().delete()
            analysis.patterns.all().delete()
            analysis.price_zones.all().delete()

            VisionObservation.objects.bulk_create(
                [
                    VisionObservation(
                        analysis=analysis,
                        kind=item["kind"],
                        label=str(item.get("label", ""))[:120],
                        summary=str(item.get("summary", ""))[:2000],
                        confidence=item.get("confidence"),
                        confirmed=item.get("confirmed"),
                        evidence=item.get("evidence", {}),
                    )
                    for item in normalized["observations"]
                ]
            )
            DetectedPattern.objects.bulk_create(
                [
                    DetectedPattern(
                        analysis=analysis,
                        name=str(item.get("name", ""))[:80],
                        category=item.get("category", "candlestick"),
                        direction=item.get("direction", "unknown"),
                        candle_refs=item.get("candle_refs", []),
                        confidence=item.get("confidence"),
                        confirmed=item.get("confirmed"),
                        description=str(item.get("description", ""))[:2000],
                        evidence=item.get("evidence", {}),
                    )
                    for item in normalized["patterns"]
                ]
            )
            DetectedPriceZone.objects.bulk_create(
                [
                    DetectedPriceZone(
                        analysis=analysis,
                        zone_type=item.get("zone_type", "support"),
                        approx_location=str(item.get("approx_location", ""))[:60],
                        price_hint=str(item.get("price_hint", ""))[:60],
                        supporting_candles=item.get("supporting_candles", []),
                        repeated_rejection=bool(item.get("repeated_rejection")),
                        broken=bool(item.get("broken")),
                        flip=str(item.get("flip", ""))[:40],
                        confidence=item.get("confidence"),
                        description=str(item.get("description", ""))[:2000],
                        evidence=item.get("evidence", {}),
                    )
                    for item in normalized["price_zones"]
                ]
            )

            record_event(
                analysis=analysis,
                kind=EventKind.PERSIST,
                message="Analysis stored.",
                detail={
                    "status": analysis.status,
                    "candles": analysis.candle_count,
                    "observations": len(normalized["observations"]),
                    "patterns": len(normalized["patterns"]),
                    "zones": len(normalized["price_zones"]),
                },
            )

        logger.info(
            "chart_vision.analysis_completed",
            extra={
                "analysis_id": analysis.pk,
                "status": analysis.status,
                "candles": analysis.candle_count,
                "tokens": analysis.total_tokens,
            },
        )
        return analysis

    def _fail(
        self, analysis: ScreenshotAnalysis, exc: Exception, *, code: str | None = None
    ) -> None:
        error_code = code or getattr(exc, "code", "error")
        analysis.status = AnalysisStatus.FAILED
        analysis.error_code = str(error_code)[:60]
        analysis.error_message = str(exc)[:2000]
        analysis.finished_at = timezone.now()
        analysis.save(
            update_fields=[
                "status",
                "error_code",
                "error_message",
                "finished_at",
                "updated_at",
            ]
        )
        record_event(
            analysis=analysis,
            kind=EventKind.SCHEMA
            if isinstance(exc, SchemaValidationError)
            else EventKind.PROVIDER_RESPONSE,
            severity=Severity.ERROR,
            message=f"Analysis failed: {error_code}",
            detail={"error": type(exc).__name__, "message": str(exc)[:500]},
        )
        logger.warning(
            "chart_vision.analysis_failed",
            extra={"analysis_id": analysis.pk, "error_code": error_code},
        )


__all__ = [
    "PROMPTS_DIR",
    "ScreenshotAnalyzer",
    "build_idempotency_key",
    "get_or_create_analysis",
    "record_event",
]
