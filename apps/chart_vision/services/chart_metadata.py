"""Chart-metadata normalisation and unknown-value reporting.

Metadata that cannot be read is reported as ``UNKNOWN`` and added to the
analysis ``missing_information`` list. A symbol or timeframe is **never**
guessed because it is common.
"""

from __future__ import annotations

from typing import Any

from apps.chart_vision.constants import UNKNOWN, ChartOrientation, OTCStatus

#: Human-readable labels for metadata fields that may be unreadable.
_FIELD_LABELS = {
    "platform": "Trading platform not readable",
    "instrument": "Instrument/symbol not readable",
    "otc_status": "OTC vs regular market designation not readable",
    "timeframe": "Chart timeframe not readable",
    "orientation": "Chart orientation not readable",
}


def _is_unknown(value: Any) -> bool:
    return value in (None, "", UNKNOWN, "unknown")


def missing_metadata_information(metadata: dict[str, Any]) -> list[str]:
    """Return a list of ``missing_information`` strings for unreadable fields."""
    missing: list[str] = []
    for field_name, label in _FIELD_LABELS.items():
        if _is_unknown(metadata.get(field_name)):
            missing.append(label)
    if not metadata.get("visible_price_labels"):
        missing.append("No readable price labels (prices cannot be measured)")
    return missing


def summarize_metadata(metadata: dict[str, Any]) -> str:
    """One-line, non-predictive metadata summary."""
    instrument = metadata.get("instrument", UNKNOWN)
    timeframe = metadata.get("timeframe", UNKNOWN)
    platform = metadata.get("platform", UNKNOWN)
    otc = metadata.get("otc_status", OTCStatus.UNKNOWN)
    otc_label = (
        "OTC"
        if otc == OTCStatus.OTC
        else ("regular" if otc == OTCStatus.REGULAR else "unknown market")
    )
    return f"{platform} · {instrument} · {timeframe} · {otc_label}"


def build_metadata_observations(
    metadata: dict[str, Any], quality: dict[str, Any]
) -> list[dict[str, Any]]:
    """Project metadata/quality into :class:`VisionObservation`-shaped dicts.

    Evidence carries the source path within the stored result so the UI can link
    back to the single authoritative payload (no duplication).
    """
    observations: list[dict[str, Any]] = [
        {
            "kind": "chart_metadata",
            "label": "Chart metadata",
            "summary": summarize_metadata(metadata),
            "confidence": metadata.get("confidence"),
            "confirmed": not _is_unknown(metadata.get("instrument")),
            "evidence": {"result_path": "chart_metadata"},
        },
        {
            "kind": "screenshot_quality",
            "label": "Screenshot quality",
            "summary": f"Rating: {quality.get('rating', UNKNOWN)}"
            + (
                f" · issues: {', '.join(quality.get('issues', []))}"
                if quality.get("issues")
                else ""
            ),
            "confidence": None,
            "confirmed": None,
            "evidence": {"result_path": "screenshot_quality"},
        },
    ]

    indicators = metadata.get("technical_indicators") or []
    if indicators:
        observations.append(
            {
                "kind": "chart_metadata",
                "label": "Technical indicators present",
                "summary": ", ".join(indicators),
                "confidence": metadata.get("confidence"),
                "confirmed": True,
                "evidence": {"result_path": "chart_metadata.technical_indicators"},
            }
        )

    if metadata.get("orientation") == ChartOrientation.INVERTED:
        observations.append(
            {
                "kind": "chart_metadata",
                "label": "Inverted chart orientation",
                "summary": "The chart appears to be inverted; price direction is read accordingly.",
                "confidence": metadata.get("confidence"),
                "confirmed": True,
                "evidence": {"result_path": "chart_metadata.orientation"},
            }
        )

    return observations


__all__ = [
    "build_metadata_observations",
    "missing_metadata_information",
    "summarize_metadata",
]
