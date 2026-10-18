"""Seed the book-strategy catalog from the immutable extraction constants.

Idempotent and knowledge-only: rows land as ``extracted``/``implemented``
research status with BOTH switches off. Nothing seeded here can affect a trade
decision - ``decision_use_approved`` is only ever set by an explicit human
approval (admin) after documented validation.

Usage:
    python manage.py seed_book_strategies
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.book_strategies.constants import BOOK_STRATEGIES
from apps.book_strategies.models import BookStrategy
from apps.strategy_knowledge.models import StrategyVersion

#: Version stamp for the book extraction itself (own version, not a course one).
BOOK_VERSION = "book-v1"
BOOK_VERSION_NOTES = (
    "Binary Options Trading Bible extraction (30 Sure Shot patterns + "
    "2 Chapter 7 indicator strategies). Draft knowledge: not approved for "
    "decision use."
)


class Command(BaseCommand):
    help = "Seed/refresh the book strategy catalog (idempotent, knowledge-only)."

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> str:
        version, _ = StrategyVersion.objects.get_or_create(
            version=BOOK_VERSION,
            defaults={"notes": BOOK_VERSION_NOTES},
        )
        created_count = 0
        updated_count = 0
        for spec in BOOK_STRATEGIES:
            defaults = {
                "number": spec.number,
                "name": spec.name,
                "chapter": spec.chapter,
                "pdf_pages": spec.pdf_pages,
                "market_types": list(spec.market_types),
                "trade_type": spec.trade_type,
                "requirements": list(spec.requirements),
                "confirmation_rule": spec.confirmation_rule,
                "invalidation_rules": list(spec.invalidation_rules),
                "mtg_policy": spec.mtg_policy,
                "ambiguities": list(spec.ambiguities),
                "contradictions": list(spec.contradictions),
                "illustration_evidence": spec.illustration_evidence,
                "detector_key": spec.detector_key,
                "priority": spec.priority,
                "research_status": "implemented" if spec.detector_key else "extracted",
                "version": version,
            }
            row, was_created = BookStrategy.objects.get_or_create(
                key=spec.key, defaults=defaults
            )
            if was_created:
                created_count += 1
                continue
            # Refresh transcribed fields but NEVER the review switches or a
            # research status a human/test has already advanced.
            for field_name, value in defaults.items():
                if field_name in ("research_status", "version"):
                    continue
                setattr(row, field_name, value)
            row.save(update_fields=[f for f in defaults if f not in ("research_status", "version")] + ["updated_at"])
            updated_count += 1

        return (
            f"book strategies: {created_count} created, {updated_count} refreshed, "
            f"{BookStrategy.objects.count()} total (all recognition/decision switches "
            "default OFF)"
        )
