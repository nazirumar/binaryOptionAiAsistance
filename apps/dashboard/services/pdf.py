# apps/dashboard/services/pdf.py
"""A tiny, dependency-free PDF writer for text reports.

Only the small subset of PDF required for a text report is generated. This
avoids adding a heavyweight dependency (ReportLab, WeasyPrint) while still
producing a valid, openable PDF. Layout is deliberately simple.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

PAGE_WIDTH = 595  # A4 portrait, in points
PAGE_HEIGHT = 842
MARGIN_X = 50
TOP_Y = 800
LINE_HEIGHT = 14
MAX_LINES_PER_PAGE = 50


@dataclass(frozen=True)
class Line:
    """A single line of report text."""

    text: str
    size: int = 10
    bold: bool = False


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _latin1(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def _content_stream(lines: Sequence[Line]) -> bytes:
    parts: list[str] = ["BT"]
    y = TOP_Y
    prev_font = None
    for line in lines:
        font = "/F2" if line.bold else "/F1"
        if font != prev_font:
            parts.append(f"{font} {line.size} Tf")
            prev_font = font
        parts.append(f"1 0 0 1 {MARGIN_X} {y} Tm")
        parts.append(f"({_escape(_latin1(line.text))}) Tj")
        y -= LINE_HEIGHT
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def build_pdf(lines: Iterable[Line], *, title: str = "Report") -> bytes:
    """Build a valid PDF document from a sequence of text lines."""
    lines = list(lines)
    pages: list[list[Line]] = []
    current: list[Line] = []
    for line in lines:
        current.append(line)
        if len(current) >= MAX_LINES_PER_PAGE:
            pages.append(current)
            current = []
    if current or not pages:
        pages.append(current)

    # Object numbering:
    #   1 = Catalog, 2 = Pages, 3 = Font F1, 4 = Font F2
    #   page i: page object = 5 + 2*i, content object = 6 + 2*i
    font_obj_id = 3
    font_bold_obj_id = 4
    page_ids = [5 + 2 * i for i in range(len(pages))]
    content_ids = [6 + 2 * i for i in range(len(pages))]

    objects: dict[int, bytes] = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("latin-1")
    objects[font_obj_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[font_bold_obj_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"

    for index, page_lines in enumerate(pages):
        page_id = page_ids[index]
        content_id = content_ids[index]
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_obj_id} 0 R /F2 {font_bold_obj_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("latin-1")
        stream = _content_stream(page_lines)
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
        )

    max_id = max(objects)
    buffer = bytearray()
    buffer += b"%PDF-1.4\n"
    buffer += b"%\xe2\xe3\xcf\xd3\n"  # binary marker
    offsets: dict[int, int] = {}
    for obj_id in range(1, max_id + 1):
        body = objects.get(obj_id)
        if body is None:
            body = b"<< >>"
        offsets[obj_id] = len(buffer)
        buffer += f"{obj_id} 0 obj\n".encode("latin-1")
        buffer += body
        buffer += b"\nendobj\n"

    xref_offset = len(buffer)
    buffer += f"xref\n0 {max_id + 1}\n".encode("latin-1")
    buffer += b"0000000000 65535 f \n"
    for obj_id in range(1, max_id + 1):
        buffer += f"{offsets[obj_id]:010d} 00000 n \n".encode("latin-1")
    buffer += b"trailer\n"
    buffer += f"<< /Size {max_id + 1} /Root 1 0 R >>\n".encode("latin-1")
    buffer += b"startxref\n"
    buffer += f"{xref_offset}\n".encode("latin-1")
    buffer += b"%%EOF\n"
    return bytes(buffer)


def heading(text: str) -> Line:
    return Line(text=text, size=14, bold=True)


def body(text: str) -> Line:
    return Line(text=text, size=10)


def spacer() -> Line:
    return Line(text="", size=10)


__all__ = ["Line", "body", "build_pdf", "heading", "spacer"]
