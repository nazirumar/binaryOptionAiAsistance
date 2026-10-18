"""Deterministic, lossless preprocessing of screenshots before the vision call.

Preprocessing normalises orientation (EXIF), colour mode and dimensions so the
provider receives a bounded PNG. It never *invents* content: no colour grading,
no synthetic candles, no upscaling.
"""

from __future__ import annotations

from io import BytesIO

from django.conf import settings
from PIL import Image, ImageOps

from apps.chart_vision.services.dto import PreprocessedImage
from apps.chart_vision.services.exceptions import CorruptedImageError


def preprocess_image(data: bytes) -> PreprocessedImage:
    """Return a normalised PNG copy of ``data`` suitable for a vision model."""
    notes: list[str] = []
    try:
        with Image.open(BytesIO(data)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode != "RGB":
                # Composite any transparency over white so charts stay legible.
                if image.mode in {"RGBA", "LA", "P"}:
                    image = image.convert("RGBA")
                    background = Image.new("RGB", image.size, (255, 255, 255))
                    background.paste(image, mask=image.split()[-1])
                    image = background
                    notes.append("Flattened transparency over a white background.")
                else:
                    image = image.convert("RGB")
                    notes.append(f"Converted colour mode to RGB (was {source.mode}).")
            else:
                image = image.copy()

            max_dimension = int(settings.VISION_PREPROCESS_MAX_DIMENSION)
            width, height = image.size
            longest = max(width, height)
            if max_dimension and longest > max_dimension:
                scale = max_dimension / float(longest)
                new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
                notes.append(
                    f"Downscaled {width}x{height} -> {new_size[0]}x{new_size[1]} "
                    "to bound provider payload size."
                )

            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            payload = buffer.getvalue()
            final_width, final_height = image.size
    except CorruptedImageError:
        raise
    except (OSError, ValueError) as exc:  # pragma: no cover - defensive
        raise CorruptedImageError(f"Failed to preprocess image: {exc}") from exc

    return PreprocessedImage(
        data=payload,
        width=final_width,
        height=final_height,
        mime_type="image/png",
        notes=notes,
    )


__all__ = ["preprocess_image"]
