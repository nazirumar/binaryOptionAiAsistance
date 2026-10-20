"""Phase 16 Checkpoint 6 - screenshot diagnostic evidence reader.

READ ONLY. Reports the real state of the stored screenshots and their
analyses so the 'stuck Screenshot #1 / failed Screenshot #2' report can be
substantiated without destroying the evidence.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from apps.ai_assistant.models import AIAnalysisJob  # noqa: E402
from apps.chart_vision.models import (  # noqa: E402
    ChartScreenshot,
    ScreenshotAnalysis,
    VisionProcessingEvent,
)


def main() -> int:
    print("=" * 74)
    print("SCREENSHOT DIAGNOSTIC EVIDENCE (read-only)")
    print("=" * 74)

    shots = list(ChartScreenshot.objects.order_by("pk"))
    print(f"ChartScreenshot rows: {len(shots)}")
    for s in shots:
        print(
            f"  id={s.pk} owner={s.owner_id} status={s.status} "
            f"uploaded={s.created_at:%Y-%m-%d %H:%M:%S} "
            f"fmt={s.image_format} {s.width}x{s.height} "
            f"bytes={s.size_bytes} file={getattr(s.image, 'name', '?')}"
        )
        if s.rejection_reason:
            print(f"      rejection_reason={s.rejection_reason}")

    print()
    analyses = list(ScreenshotAnalysis.objects.order_by("pk"))
    print(f"ScreenshotAnalysis rows: {len(analyses)}")
    for a in analyses:
        print(
            f"  id={a.pk} screenshot={a.screenshot_id} owner={a.owner_id} "
            f"status={a.status} attempts={a.attempts} "
            f"created={a.created_at:%Y-%m-%d %H:%M:%S} "
            f"started={a.started_at} finished={a.finished_at}"
        )
        if a.error_code or a.error_message:
            print(f"      error_code={a.error_code} msg={a.error_message[:80]}")
        print(f"      in_flight={a.is_in_flight} terminal={a.is_terminal}")

    print()
    events = list(VisionProcessingEvent.objects.order_by("pk"))
    print(f"VisionProcessingEvent rows: {len(events)}")
    for e in events[-25:]:
        kind = getattr(e, "event_type", None) or getattr(e, "kind", None) or "?"
        print(f"  id={e.pk} analysis={getattr(e, 'analysis_id', '?')} {kind} "
              f"at={e.created_at:%Y-%m-%d %H:%M:%S} "
              f"{str(getattr(e, 'message', ''))[:60]}")

    print()
    jobs = list(AIAnalysisJob.objects.order_by("pk"))
    print(f"AIAnalysisJob rows: {len(jobs)}")
    for j in jobs:
        print(f"  id={j.pk} status={j.status} attempts={getattr(j, 'attempts', '?')} "
              f"error_code={getattr(j, 'error_code', '')} "
              f"created={j.created_at:%Y-%m-%d %H:%M:%S}")

    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
