"""Seed global canonical -> broker symbol mappings for development.

Brokers suffix symbols (``EURUSDm``, ``EURUSD.pro``). This command creates a
global mapping for each canonical instrument using an optional suffix, so the
application can resolve symbols before a real mapping is configured::

    python manage.py seed_market_symbols --suffix m
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.market_data.models import MarketSymbol
from apps.market_data.services.symbol_mapper import list_instruments


class Command(BaseCommand):
    help = "Create global canonical -> broker symbol mappings."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--suffix", type=str, default="", help="Broker symbol suffix, e.g. 'm'."
        )
        parser.add_argument(
            "--canonical",
            type=str,
            default="",
            help="Comma-separated canonical codes (default: all regular).",
        )

    def handle(self, *args, **options) -> None:
        suffix = options["suffix"]
        if options["canonical"]:
            wanted = {c.strip().upper() for c in options["canonical"].split(",") if c.strip()}
            instruments = [i for i in list_instruments(include_otc=False) if i.code in wanted]
        else:
            instruments = list_instruments(include_otc=False)

        created = 0
        for instrument in instruments:
            _, was_created = MarketSymbol.objects.get_or_create(
                profile=None,
                broker_symbol=f"{instrument.base}{suffix}",
                defaults={
                    "canonical": instrument.code,
                    "description": instrument.name,
                    "category": instrument.category,
                    "is_otc": False,
                    "is_active": True,
                },
            )
            created += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} new global mapping(s); {len(instruments)} considered."
            )
        )
