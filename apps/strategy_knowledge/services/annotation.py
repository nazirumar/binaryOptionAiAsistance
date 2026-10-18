"""CP13: pattern visualisation — annotation with *reliable coordinates only*.

Rules enforced here:

* The original screenshot bytes are **never modified**. Annotations are drawn on
  a copy held in memory; persistence (if requested) writes a new private file.
* Coordinates are only drawn when the vision model reported explicit pixel
  boxes on the candles (``high_px`` / ``low_px`` / ``body_top_px`` /
  ``body_bottom_px``). Zones and levels have *no* pixel coordinates in the v1
  schema, so they are rendered as text explanations — the service never
  guesses a pixel position from a price hint.
* When nothing can be drawn safely, a textual explanation is returned instead
  of an empty or fabricated overlay.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from apps.chart_vision.models import ChartScreenshot

#: Distinct colours (R, G, B) per annotation kind.
PALETTE: dict[str, tuple[int, int, int]] = {
    "bullish": (46, 204, 113),
    "bearish": (231, 76, 60),
    "zone": (52, 152, 219),
    "neutral": (241, 196, 15),
    "text": (236, 240, 241),
}

_LINE_WIDTH = 3
_BOX_PAD = 2


@dataclass(slots=True)
class Annotation:
    """One drawn element or one textual explanation line."""

    kind: str  # candle_box | text
    label: str
    candle_index: int | None = None
    drawn: bool = False
    note: str = ""


@dataclass(slots=True)
class AnnotationResult:
    """Outcome of an annotation pass."""

    image_bytes: bytes | None
    image_format: str
    annotations: list[Annotation] = field(default_factory=list)
    text_explanation: list[str] = field(default_factory=list)
    drew_anything: bool = False
    notes: list[str] = field(default_factory=list)


def _candle_has_box(candle: dict[str, Any]) -> bool:
    keys = ("high_px", "low_px", "body_top_px", "body_bottom_px")
    values = [candle.get(k) for k in keys]
    return all(isinstance(v, int) and v >= 0 for v in values)


def annotate_screenshot(
    screenshot: ChartScreenshot,
    *,
    detections: list[dict[str, Any]] | None = None,
    candles: list[dict[str, Any]] | None = None,
) -> AnnotationResult:
    """Annotate ``screenshot`` with the detections' candle boxes.

    ``detections`` entries: ``{"strategy_id", "direction", "candle_refs"}``
    (the recognition layer's output). ``candles`` is the normalised candle list
    from the vision result, which carries the pixel boxes.

    Candle boxes are drawn only for references that both belong to a detection
    and have a complete pixel box. Everything else becomes a text line.
    """
    detections = detections or []
    candles = candles or []
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover - Pillow is an optional dependency
        return AnnotationResult(
            image_bytes=None,
            image_format="",
            text_explanation=_text_lines(detections),
            notes=["Pillow is not installed; returning textual explanation only"],
        )

    with screenshot.image.open() as fh:
        raw = fh.read()
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    draw = ImageDraw.Draw(image)
    result = AnnotationResult(image_bytes=None, image_format=image.format or "PNG")
    result.text_explanation = _text_lines(detections)

    drew_anything = False
    for detection in detections:
        direction = str(detection.get("direction", "neutral"))
        colour = PALETTE.get(direction, PALETTE["neutral"])
        label = str(detection.get("strategy_id", ""))
        for ref in detection.get("candle_refs") or []:
            if not isinstance(ref, int) or ref < 0 or ref >= len(candles):
                result.annotations.append(
                    Annotation(
                        kind="text",
                        label=label,
                        candle_index=ref if isinstance(ref, int) else None,
                        drawn=False,
                        note="candle reference out of range; text only",
                    )
                )
                continue
            candle = candles[ref]
            if not _candle_has_box(candle):
                result.annotations.append(
                    Annotation(
                        kind="text",
                        label=label,
                        candle_index=ref,
                        drawn=False,
                        note="no reliable pixel box on this candle; text only",
                    )
                )
                continue
            y_top = min(candle["high_px"], candle["low_px"])
            y_bottom = max(candle["high_px"], candle["low_px"])
            body_top = min(candle["body_top_px"], candle["body_bottom_px"])
            body_bottom = max(candle["body_top_px"], candle["body_bottom_px"])
            # The v1 schema reports *vertical* pixel positions only. Horizontal
            # placement assumes evenly spaced slots across the image width; this
            # is a documented approximation used solely to position a box whose
            # vertical extent is model-reported and reliable. It is never used
            # to assert a price level.
            x_center = _slot_centre(ref, len(candles), image.width)
            half_width = max(4, image.width // max(1, len(candles) * 4))
            box = (
                x_center - half_width - _BOX_PAD,
                int(y_top) - _BOX_PAD,
                x_center + half_width + _BOX_PAD,
                int(y_bottom) + _BOX_PAD,
            )
            draw.rectangle(box, outline=colour, width=_LINE_WIDTH)
            body_box = (
                x_center - half_width,
                int(body_top),
                x_center + half_width,
                int(body_bottom),
            )
            draw.rectangle(body_box, fill=colour)
            draw.text((box[0], max(0, box[1] - 12)), label[:32], fill=colour)
            result.annotations.append(
                Annotation(kind="candle_box", label=label, candle_index=ref, drawn=True)
            )
            drew_anything = True

    result.drew_anything = drew_anything
    if not drew_anything:
        result.notes.append(
            "no candle had a reliable pixel box; returning the original image "
            "untouched with textual explanation only"
        )
    buffer = io.BytesIO()
    image_format = "PNG"
    image.save(buffer, format=image_format)
    result.image_bytes = buffer.getvalue()
    result.image_format = image_format
    return result


def _slot_centre(index: int, count: int, width: int) -> int:
    """Horizontal centre of candle ``index`` assuming even slots (a documented
    approximation used *only* to place an already-verified vertical box)."""
    if count <= 0:
        return width // 2
    slot = width / count
    return int(slot * (index + 0.5))


def _text_lines(detections: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for detection in detections:
        refs = detection.get("candle_refs") or []
        lines.append(
            f"{detection.get('strategy_id', 'unknown')} "
            f"({detection.get('direction', 'neutral')}) at candle(s) "
            f"{', '.join(str(r) for r in refs) if refs else 'n/a'}"
        )
    return lines


__all__ = ["Annotation", "AnnotationResult", "annotate_screenshot"]
