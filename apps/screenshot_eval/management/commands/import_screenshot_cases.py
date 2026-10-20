# screenshot_eval/management/commands/import_screenshot_cases.py
"""Import real screenshots as evaluation cases (Checkpoint 1).

Example::

    python manage.py import_screenshot_cases --directory C:\\shots --owner analyst \\
        --instrument EURUSD --timeframe M5 --market-type regular --kind positive \\
        --strategies SS1 --reviewed

The command never fabricates a case: every imported file must decode as an
image, and every case records the file SHA-256 as provenance. Unknown labels
stay unknown until a reviewer fills them in.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.chart_vision.services.upload import create_screenshot_from_upload
from apps.screenshot_eval.constants import (
    CaseKind,
    MarketType,
    Provenance,
    ReviewState,
    ScreenshotQuality,
)
from apps.screenshot_eval.services.dataset import CaseInput, ScreenshotDatasetService

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


class Command(BaseCommand):
    help = "Import real screenshot files as Phase 14 evaluation cases."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--directory", required=True, help="Folder of screenshots.")
        parser.add_argument("--owner", required=True, help="Username to own the cases.")
        parser.add_argument("--label-prefix", default="", help="Prefix for case labels.")
        parser.add_argument("--instrument", default="")
        parser.add_argument("--timeframe", default="")
        parser.add_argument(
            "--market-type",
            default=MarketType.UNKNOWN,
            choices=[MarketType.OTC, MarketType.REGULAR, MarketType.UNKNOWN],
        )
        parser.add_argument(
            "--quality",
            default=ScreenshotQuality.UNKNOWN,
            choices=[q for q, _ in ScreenshotQuality.CHOICES],
        )
        parser.add_argument(
            "--kind",
            default=CaseKind.UNLABELLED,
            choices=[k for k, _ in CaseKind.CHOICES],
        )
        parser.add_argument("--strategies", default="", help="Comma-separated expected keys.")
        parser.add_argument(
            "--reviewed",
            action="store_true",
            help="Mark imported cases as reviewer-confirmed (default: unreviewed).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options) -> None:
        from django.core.files.uploadedfile import SimpleUploadedFile

        directory = Path(options["directory"])
        if not directory.is_dir():
            raise CommandError(f"not a directory: {directory}")

        User = get_user_model()
        try:
            owner = User.objects.get(username=options["owner"])
        except User.DoesNotExist as exc:
            raise CommandError(f"unknown user: {options['owner']}") from exc

        files = sorted(
            p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES
        )
        if not files:
            raise CommandError(f"no image files found in {directory}")

        expected = [k.strip() for k in options["strategies"].split(",") if k.strip()]
        service = ScreenshotDatasetService()
        created = 0
        for path in files:
            data = path.read_bytes()
            sha256 = hashlib.sha256(data).hexdigest()
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] {path.name} sha256={sha256[:12]}…")
                continue
            uploaded = SimpleUploadedFile(path.name, data)
            try:
                screenshot = create_screenshot_from_upload(owner, uploaded)
            except Exception as exc:
                self.stderr.write(f"skipped {path.name}: {exc}")
                continue
            case_input = CaseInput(
                label=f"{options['label_prefix']}{path.stem}",
                instrument=options["instrument"],
                timeframe=options["timeframe"],
                market_type=options["market_type"],
                quality=options["quality"],
                case_kind=options["kind"],
                expected_strategy_keys=expected,
                source=Provenance.IMPORTED_DIR,
                provenance={
                    "source_file": path.name,
                    "source_sha256": sha256,
                    "importer": "import_screenshot_cases",
                },
            )
            case = service.create_case(owner=owner, screenshot=screenshot, data=case_input)
            if options["reviewed"]:
                service.review(
                    case=case,
                    reviewer=owner,
                    review_state=ReviewState.CONFIRMED,
                )
            created += 1
        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"created {created} case(s)"))
