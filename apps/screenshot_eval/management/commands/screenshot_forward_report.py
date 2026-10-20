# screenshot_eval/management/commands/screenshot_forward_report.py
"""Print the Phase 14 forward-testing metrics (Checkpoint 6).

Emits JSON with two clearly separated scopes: recognition (precision/recall vs
human labels) and prediction (hit rate over verified outcomes only). Nothing is
combined and no rate is invented when data is insufficient.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.screenshot_eval.models import ReviewQueueItem
from apps.screenshot_eval.services.metrics import ScreenshotMetricsService


class Command(BaseCommand):
    help = "Report Phase 14 screenshot forward-testing metrics."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--out", default="", help="Write JSON to this path.")

    def handle(self, *args, **options) -> None:
        service = ScreenshotMetricsService()
        payload = service.build()
        payload["segments"] = {
            dim: service.by_segment(dim)
            for dim in ("strategy", "instrument", "timeframe", "market_type")
        }
        payload["review_queue"] = {
            "open": ReviewQueueItem.objects.filter(state="open").count()
        }
        text = json.dumps(payload, indent=2, default=str)
        if options["out"]:
            from pathlib import Path

            Path(options["out"]).write_text(text, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"wrote {options['out']}"))
        else:
            self.stdout.write(text)

        recognition = payload["recognition"]
        prediction = payload["prediction"]
        self.stdout.write(
            f"recognition: labels={recognition['labelled_cases']} "
            f"precision={recognition['precision']} recall={recognition['recall']}"
        )
        self.stdout.write(
            f"prediction: verified={prediction['verified_total']} "
            f"hit_rate={prediction['hit_rate']} excluded={prediction['excluded_from_accuracy']}"
        )
