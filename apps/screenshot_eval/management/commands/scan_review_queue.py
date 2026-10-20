# screenshot_eval/management/commands/scan_review_queue.py
"""Raise error-review queue items from stored records (Checkpoint 7)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.screenshot_eval.services.review import ReviewQueueService


class Command(BaseCommand):
    help = "Scan recognitions/predictions and raise review-queue items."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--owner", default="", help="Limit to one username.")

    def handle(self, *args, **options) -> None:
        owner = None
        if options["owner"]:
            User = get_user_model()
            owner = User.objects.filter(username=options["owner"]).first()
            if owner is None:
                raise CommandError(f"unknown user: {options['owner']}")
        result = ReviewQueueService().scan(owner=owner)
        self.stdout.write(self.style.SUCCESS(f"raised {result.created} review item(s)"))
