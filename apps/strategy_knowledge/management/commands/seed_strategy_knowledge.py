# apps/strategy_knowledge/management/commands/seed_strategy_knowledge.py
"""Seed the versioned strategy knowledge base (Phase 12).

Creates one :class:`StrategyDefinition` per deterministic detector key in
:data:`~apps.strategy_knowledge.constants.DETECTOR_KEYS`, grouped by category,
plus the :class:`StrategyPatternLabel` rows that let the vision candidate mapper
resolve a screenshot observation back to a definition.

Every seeded definition is **knowledge only and honest about its status**:

* ``validation_status`` is ``draft`` (not ``approved``) — none of these setups
  has been validated against labelled outcomes, so nothing here may be
  presented as an accurate or approved signal;
* ``enabled=False`` — a seeded definition never silently participates in
  recognition or trade decisions until a reviewer approves and enables it;
* ``detector_key`` points at a *registry-backed* detector, so a definition
  carries no executable logic of its own (the registry runs deterministic
  Python; database content is never evaluated).

Run::

    python manage.py seed_strategy_knowledge
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.strategy_knowledge.constants import (
    DETECTOR_KEYS,
    ConditionKind,
    ValidationStatus,
)
from apps.strategy_knowledge.models import (
    StrategyCategory,
    StrategyCondition,
    StrategyDefinition,
    StrategyPatternLabel,
    StrategyVersion,
)

#: Category slug -> (name, description, order).
CATEGORIES: dict[str, tuple[str, str, int]] = {
    "candlestick": ("Candlestick patterns", "Single- and multi-candle shapes.", 10),
    "support-resistance": (
        "Support / resistance",
        "Level formation, flips, breakouts and failed tests.",
        20,
    ),
    "market-structure": (
        "Market structure",
        "Breaks of structure, changes of character and shifts.",
        30,
    ),
    "liquidity-ict": (
        "Liquidity & ICT concepts",
        "Sweeps, equal levels, displacement, order blocks and FVGs.",
        40,
    ),
    "wave-cycle": (
        "Wave & cycle readings",
        "Generic motive/counter wave readings.",
        50,
    ),
    "psychology": (
        "Candle psychology",
        "Run strength, close quality and continuation failures.",
        60,
    ),
    "abc": ("ABC corrections", "Generic textbook ABC pivot readings.", 70),
}

#: detector_key -> (name, category slug, variant, one-line description,
#:                   extra vision labels that should map to this definition).
#: ``labels`` are canonical :class:`StrategyPatternLabel` values; the vision
#: candidate mapper resolves them deterministically (no fuzzy matching).
DEFINITIONS: dict[str, tuple[str, str, str, str, tuple[str, ...]]] = {
    # -- candlestick ------------------------------------------------------
    "cs.bullish_engulfing": (
        "Bullish engulfing",
        "candlestick",
        "bullish",
        "A bullish candle engulfs the prior bearish candle body.",
        ("bullish_engulfing",),
    ),
    "cs.bearish_engulfing": (
        "Bearish engulfing",
        "candlestick",
        "bearish",
        "A bearish candle engulfs the prior bullish candle body.",
        ("bearish_engulfing",),
    ),
    "cs.bullish_pin_bar": (
        "Bullish pin bar",
        "candlestick",
        "bullish",
        "Long lower wick, tiny upper wick, small body closing near the high.",
        ("bullish_pin_bar", "pin_bar_bullish"),
    ),
    "cs.bearish_pin_bar": (
        "Bearish pin bar",
        "candlestick",
        "bearish",
        "Long upper wick, tiny lower wick, small body closing near the low.",
        ("bearish_pin_bar", "pin_bar_bearish"),
    ),
    "cs.hammer": (
        "Hammer",
        "candlestick",
        "bullish",
        "Small body near the high with a long lower wick after a decline.",
        ("hammer",),
    ),
    "cs.inverted_hammer": (
        "Inverted hammer",
        "candlestick",
        "bullish",
        "Small body near the low with a long upper wick after a decline.",
        ("inverted_hammer",),
    ),
    "cs.shooting_star": (
        "Shooting star",
        "candlestick",
        "bearish",
        "Small body near the low with a long upper wick after an advance.",
        ("shooting_star",),
    ),
    "cs.hanging_man": (
        "Hanging man",
        "candlestick",
        "bearish",
        "Hammer geometry that appears after an advance, not a decline.",
        ("hanging_man",),
    ),
    "cs.doji": (
        "Doji",
        "candlestick",
        "neutral",
        "Open and close are nearly equal; indecision.",
        ("doji",),
    ),
    "cs.dragonfly_doji": (
        "Dragonfly doji",
        "candlestick",
        "neutral",
        "Doji with a long lower wick and no upper wick.",
        ("dragonfly_doji",),
    ),
    "cs.gravestone_doji": (
        "Gravestone doji",
        "candlestick",
        "neutral",
        "Doji with a long upper wick and no lower wick.",
        ("gravestone_doji",),
    ),
    "cs.spinning_top": (
        "Spinning top",
        "candlestick",
        "neutral",
        "Small body centred between upper and lower wicks.",
        ("spinning_top",),
    ),
    "cs.bullish_harami": (
        "Bullish harami",
        "candlestick",
        "bullish",
        "A small bullish candle contained within the prior bearish candle.",
        ("bullish_harami",),
    ),
    "cs.bearish_harami": (
        "Bearish harami",
        "candlestick",
        "bearish",
        "A small bearish candle contained within the prior bullish candle.",
        ("bearish_harami",),
    ),
    "cs.inside_bar": (
        "Inside bar",
        "candlestick",
        "neutral",
        "A candle fully contained within the prior candle's range.",
        ("inside_bar",),
    ),
    "cs.outside_bar": (
        "Outside bar",
        "candlestick",
        "neutral",
        "A candle that fully engulfs the prior candle's range.",
        ("outside_bar",),
    ),
    "cs.morning_star": (
        "Morning star",
        "candlestick",
        "bullish",
        "Three-candle bullish reversal: big down, small body, big up.",
        ("morning_star",),
    ),
    "cs.evening_star": (
        "Evening star",
        "candlestick",
        "bearish",
        "Three-candle bearish reversal: big up, small body, big down.",
        ("evening_star",),
    ),
    "cs.three_white_soldiers": (
        "Three white soldiers",
        "candlestick",
        "bullish",
        "Three consecutive strong bullish candles with rising closes.",
        ("three_white_soldiers",),
    ),
    "cs.three_black_crows": (
        "Three black crows",
        "candlestick",
        "bearish",
        "Three consecutive strong bearish candles with falling closes.",
        ("three_black_crows",),
    ),
    "cs.tweezer_top": (
        "Tweezer top",
        "candlestick",
        "bearish",
        "Two candles whose highs match within tolerance at a top.",
        ("tweezer_top",),
    ),
    "cs.tweezer_bottom": (
        "Tweezer bottom",
        "candlestick",
        "bullish",
        "Two candles whose lows match within tolerance at a bottom.",
        ("tweezer_bottom",),
    ),
    "cs.piercing": (
        "Piercing line",
        "candlestick",
        "bullish",
        "Bullish candle opens below the prior low and closes above its midpoint.",
        ("piercing",),
    ),
    "cs.dark_cloud_cover": (
        "Dark cloud cover",
        "candlestick",
        "bearish",
        "Bearish candle opens above the prior high and closes below its midpoint.",
        ("dark_cloud_cover",),
    ),
    # -- support / resistance ---------------------------------------------
    "sr.support_rejection": (
        "Support rejection",
        "support-resistance",
        "bullish",
        "Price tests support and closes back above it.",
        (),
    ),
    "sr.resistance_rejection": (
        "Resistance rejection",
        "support-resistance",
        "bearish",
        "Price tests resistance and closes back below it.",
        (),
    ),
    "sr.support_becomes_resistance": (
        "Support became resistance",
        "support-resistance",
        "bearish",
        "A validated support flips to resistance after a break and retest.",
        ("support_becomes_resistance", "sbr"),
    ),
    "sr.resistance_becomes_support": (
        "Resistance became support",
        "support-resistance",
        "bullish",
        "A validated resistance flips to support after a break and retest.",
        ("resistance_becomes_support", "rbs"),
    ),
    "sr.breakout_retest": (
        "Breakout retest",
        "support-resistance",
        "neutral",
        "Price breaks a level, retests it and accepts the new role.",
        (),
    ),
    "sr.false_breakout": (
        "False breakout",
        "support-resistance",
        "neutral",
        "Price pierces a level but closes back inside; the break fails.",
        ("false_breakout",),
    ),
    "sr.failed_support_test": (
        "Failed support test",
        "support-resistance",
        "neutral",
        "Repeated support attacks without a close below.",
        (),
    ),
    "sr.failed_resistance_test": (
        "Failed resistance test",
        "support-resistance",
        "neutral",
        "Repeated resistance attacks without a close above.",
        (),
    ),
    "sr.multi_touch": (
        "Multi-touch level",
        "support-resistance",
        "neutral",
        "A level validated by several touches within tolerance.",
        (),
    ),
    "sr.engulfing_at_support": (
        "Engulfing at support",
        "support-resistance",
        "bullish",
        "Bullish engulfing located at a validated support zone.",
        (),
    ),
    "sr.engulfing_at_resistance": (
        "Engulfing at resistance",
        "support-resistance",
        "bearish",
        "Bearish engulfing located at a validated resistance zone.",
        (),
    ),
    "sr.doji_above_support": (
        "Doji above support",
        "support-resistance",
        "neutral",
        "A doji forming just above a validated support zone.",
        (),
    ),
    "sr.doji_below_resistance": (
        "Doji below resistance",
        "support-resistance",
        "neutral",
        "A doji forming just below a validated resistance zone.",
        (),
    ),
    # -- market structure --------------------------------------------------
    "ms.bos_bullish": (
        "Bullish break of structure",
        "market-structure",
        "bullish",
        "Price closes above a prior swing high in an uptrend.",
        ("bos_bullish", "bos"),
    ),
    "ms.bos_bearish": (
        "Bearish break of structure",
        "market-structure",
        "bearish",
        "Price closes below a prior swing low in a downtrend.",
        ("bos_bearish",),
    ),
    "ms.choch_bullish": (
        "Bullish change of character",
        "market-structure",
        "bullish",
        "A downtrend's last protective high breaks: character changes.",
        ("choch_bullish", "choch"),
    ),
    "ms.choch_bearish": (
        "Bearish change of character",
        "market-structure",
        "bearish",
        "An uptrend's last protective low breaks: character changes.",
        ("choch_bearish",),
    ),
    "ms.mss_bullish": (
        "Bullish market structure shift",
        "market-structure",
        "bullish",
        "A bullish change of character confirmed by displacement.",
        ("mss_bullish",),
    ),
    "ms.mss_bearish": (
        "Bearish market structure shift",
        "market-structure",
        "bearish",
        "A bearish change of character confirmed by displacement.",
        ("mss_bearish",),
    ),
    "ms.trend_exhaustion": (
        "Trend exhaustion",
        "market-structure",
        "neutral",
        "Observable exhaustion signals inside a live trend.",
        (),
    ),
    "ms.failed_structural_break": (
        "Failed structural break",
        "market-structure",
        "neutral",
        "A structural break that fails to hold and reverses back.",
        (),
    ),
    # -- liquidity / ICT ---------------------------------------------------
    "liq.bullish_sweep": (
        "Bullish liquidity sweep",
        "liquidity-ict",
        "bullish",
        "Price sweeps a prior swing low and closes back above it.",
        ("bullish_sweep", "low_sweep"),
    ),
    "liq.bearish_sweep": (
        "Bearish liquidity sweep",
        "liquidity-ict",
        "bearish",
        "Price sweeps a prior swing high and closes back below it.",
        ("bearish_sweep", "liquidity_sweep", "sweep", "high_sweep"),
    ),
    "liq.equal_highs": (
        "Equal highs",
        "liquidity-ict",
        "neutral",
        "Two swing highs within tolerance: an observable liquidity pool.",
        (),
    ),
    "liq.equal_lows": (
        "Equal lows",
        "liquidity-ict",
        "neutral",
        "Two swing lows within tolerance: an observable liquidity pool.",
        (),
    ),
    "liq.inducement": (
        "Inducement",
        "liquidity-ict",
        "neutral",
        "A swept level that may have trapped late entrants.",
        (),
    ),
    "liq.displacement": (
        "Displacement",
        "liquidity-ict",
        "neutral",
        "A wide, strong-bodied impulse candle that leaves an imbalance.",
        (),
    ),
    "fvg.bullish": (
        "Bullish fair value gap",
        "liquidity-ict",
        "bullish",
        "A three-candle imbalance where price gaps upward.",
        ("bullish_fvg", "fair_value_gap", "fvg"),
    ),
    "fvg.bearish": (
        "Bearish fair value gap",
        "liquidity-ict",
        "bearish",
        "A three-candle imbalance where price gaps downward.",
        ("bearish_fvg",),
    ),
    "fvg.retest": (
        "Fair value gap retest",
        "liquidity-ict",
        "neutral",
        "Price returns to trade back into an existing imbalance.",
        (),
    ),
    "ob.bullish": (
        "Bullish order block",
        "liquidity-ict",
        "bullish",
        "The last opposing candle before a strong bullish departure.",
        ("order_block", "bullish_order_block"),
    ),
    "ob.bearish": (
        "Bearish order block",
        "liquidity-ict",
        "bearish",
        "The last opposing candle before a strong bearish departure.",
        ("bearish_order_block",),
    ),
    "ob.breaker": (
        "Breaker block",
        "liquidity-ict",
        "neutral",
        "An invalidated order block that price trades back into.",
        (),
    ),
    "ob.mitigation": (
        "Order-block mitigation",
        "liquidity-ict",
        "neutral",
        "Price returns to mitigate an unmitigated order block.",
        (),
    ),
    "zone.premium_discount": (
        "Premium / discount zone",
        "liquidity-ict",
        "neutral",
        "Geometric position of price within a confirmed range.",
        (),
    ),
    # -- wave / cycle ------------------------------------------------------
    "cycle.motive_wave": (
        "Motive wave",
        "wave-cycle",
        "neutral",
        "Generic five-wave motive reading (course rules unavailable).",
        (),
    ),
    "cycle.counter_wave": (
        "Counter wave",
        "wave-cycle",
        "neutral",
        "Generic corrective counter-wave reading.",
        (),
    ),
    "cycle.weak_last_effort": (
        "Weak last effort",
        "wave-cycle",
        "neutral",
        "A final push with weakening candle quality.",
        (),
    ),
    "cycle.new_motive_wave": (
        "New motive wave",
        "wave-cycle",
        "neutral",
        "Start of a fresh motive reading after a correction.",
        (),
    ),
    # -- candle psychology -------------------------------------------------
    "psy.buyer_failure": (
        "Buyer failure",
        "psychology",
        "bearish",
        "Buyers fail to hold a push; sellers reclaim the range.",
        (),
    ),
    "psy.seller_failure": (
        "Seller failure",
        "psychology",
        "bullish",
        "Sellers fail to hold a push; buyers reclaim the range.",
        (),
    ),
    "psy.reference_sequence": (
        "Reference sequence",
        "psychology",
        "neutral",
        "The current run described against a reference sequence.",
        (),
    ),
    "psy.similar_sequence": (
        "Similar sequence",
        "psychology",
        "neutral",
        "A prior sequence similar to the current one, by distance.",
        (),
    ),
    "psy.lonely_candle": (
        "Lonely candle",
        "psychology",
        "neutral",
        "An isolated candle detached from the surrounding run.",
        (),
    ),
    "psy.candle_progress": (
        "Candle progress",
        "psychology",
        "neutral",
        "Where the close sits within the candle's own range.",
        ("candle_progress",),
    ),
    "psy.run_count": (
        "Run count",
        "psychology",
        "neutral",
        "Length and extension status of the current directional run.",
        ("run_count",),
    ),
    "psy.strong_close": (
        "Strong close",
        "psychology",
        "neutral",
        "A large body closing at the extreme of its range.",
        ("strong_close",),
    ),
    "psy.weak_close": (
        "Weak close",
        "psychology",
        "neutral",
        "A candle that closed off its own extreme.",
        ("weak_close",),
    ),
    "psy.failed_continuation": (
        "Failed continuation",
        "psychology",
        "neutral",
        "A directional run ended by a candle closing against it.",
        ("failed_continuation",),
    ),
    # -- ABC ---------------------------------------------------------------
    "abc.generic": (
        "Generic ABC correction",
        "abc",
        "neutral",
        "Textbook A-B-C pivot reading from confirmed swings.",
        (),
    ),
}

#: Condition rows per detector key: (kind, order, label, description, params).
#: Params are restricted to whitelisted scalar thresholds (see ``schemas.py``).
CONDITIONS: dict[str, tuple[tuple[str, int, str, str, dict], ...]] = {
    "cs.bullish_pin_bar": (
        (
            ConditionKind.REQUIRED,
            0,
            "Long lower wick",
            "Lower wick dominates the range.",
            {"min_wick_ratio": 0.55},
        ),
        (
            ConditionKind.REQUIRED,
            1,
            "Small body",
            "Body is a small fraction of the range.",
            {"max_body_ratio": 0.40},
        ),
        (
            ConditionKind.INVALIDATION,
            0,
            "Close back below the low",
            "A close under the pin's low invalidates it.",
            {},
        ),
    ),
    "cs.bearish_pin_bar": (
        (
            ConditionKind.REQUIRED,
            0,
            "Long upper wick",
            "Upper wick dominates the range.",
            {"min_wick_ratio": 0.55},
        ),
        (
            ConditionKind.REQUIRED,
            1,
            "Small body",
            "Body is a small fraction of the range.",
            {"max_body_ratio": 0.40},
        ),
        (
            ConditionKind.INVALIDATION,
            0,
            "Close back above the high",
            "A close over the pin's high invalidates it.",
            {},
        ),
    ),
    "sr.support_becomes_resistance": (
        (
            ConditionKind.REQUIRED,
            0,
            "Validated support",
            "Support confirmed by enough touches.",
            {"min_touches": 2},
        ),
        (
            ConditionKind.REQUIRED,
            1,
            "Close below the zone",
            "A completed close breaks the support.",
            {},
        ),
        (
            ConditionKind.REQUIRED,
            2,
            "Retest from below",
            "Price returns to the old support.",
            {"retest_window": 5},
        ),
        (ConditionKind.OPTIONAL, 0, "Rejection at retest", "A rejection candle at the retest.", {}),
        (
            ConditionKind.INVALIDATION,
            0,
            "Two closes back above",
            "Two closes above the zone invalidate the flip.",
            {},
        ),
    ),
    "sr.resistance_becomes_support": (
        (
            ConditionKind.REQUIRED,
            0,
            "Validated resistance",
            "Resistance confirmed by enough touches.",
            {"min_touches": 2},
        ),
        (
            ConditionKind.REQUIRED,
            1,
            "Close above the zone",
            "A completed close breaks the resistance.",
            {},
        ),
        (
            ConditionKind.REQUIRED,
            2,
            "Retest from above",
            "Price returns to the old resistance.",
            {"retest_window": 5},
        ),
        (ConditionKind.OPTIONAL, 0, "Rejection at retest", "A rejection candle at the retest.", {}),
        (
            ConditionKind.INVALIDATION,
            0,
            "Two closes back below",
            "Two closes below the zone invalidate the flip.",
            {},
        ),
    ),
    "abc.generic": (
        (
            ConditionKind.REQUIRED,
            0,
            "Three confirmed swings",
            "A, B and C must all be confirmed pivots.",
            {"lookback": 2},
        ),
        (
            ConditionKind.REQUIRED,
            1,
            "Retracement within band",
            "C retraces a textbook fraction of A->B.",
            {"retracement_min": 0.3, "retracement_max": 0.886},
        ),
        (
            ConditionKind.INVALIDATION,
            0,
            "C breaks past A",
            "If C trades past A the ABC reading fails.",
            {},
        ),
    ),
}

#: Shared knowledge-only caveat appended to every seeded definition.
_VALIDATION_NOTES = (
    "Knowledge-only entry generated from the deterministic detector registry. "
    "It has NOT been validated against labelled outcomes and carries no "
    "accuracy claim. Not enabled: it cannot participate in recognition or any "
    "trade decision until a reviewer approves and enables it."
)


class Command(BaseCommand):
    help = "Seed the strategy knowledge base with honest, knowledge-only definitions."

    def handle(self, *args, **options) -> None:
        version, _ = StrategyVersion.objects.get_or_create(
            version="12.0",
            defaults={
                "notes": "Initial knowledge base seeded from the Phase 12 detector registry.",
                "released_at": None,
            },
        )

        categories: dict[str, StrategyCategory] = {}
        for slug, (name, description, order) in CATEGORIES.items():
            category, _ = StrategyCategory.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "description": description, "order": order},
            )
            categories[slug] = category

        created_defs = 0
        created_labels = 0
        created_conds = 0

        for key in DETECTOR_KEYS:
            spec = DEFINITIONS.get(key)
            if spec is None:
                # A registry key without a knowledge entry stays knowledge-free
                # rather than being guessed at: skip it honestly.
                continue
            name, slug, variant, description, labels = spec
            definition, was_created = StrategyDefinition.objects.get_or_create(
                strategy_id=key,
                defaults={
                    "name": name,
                    "category": categories[slug],
                    "description": description,
                    "market_context": "",
                    "timeframe": "any",
                    "variant": variant,
                    "completion_rules": [],
                    "screenshot_guidance": "",
                    "detector_key": key,
                    "course_reference": "",
                    "validation_status": ValidationStatus.DRAFT,
                    "version": version,
                    "enabled": False,
                    "validation_notes": _VALIDATION_NOTES,
                },
            )
            created_defs += int(was_created)

            for label in labels:
                _, was_label = StrategyPatternLabel.objects.get_or_create(
                    label=label,
                    defaults={
                        "definition": definition,
                        "notes": "Vision label mapped deterministically to this detector.",
                    },
                )
                created_labels += int(was_label)

            for kind, order, label, description_c, params in CONDITIONS.get(key, ()):  # type: ignore[assignment]
                _, was_cond = StrategyCondition.objects.get_or_create(
                    definition=definition,
                    kind=str(kind),
                    order=order,
                    defaults={
                        "label": label,
                        "description": description_c,
                        "detector_key": key,
                        "params": params,
                    },
                )
                created_conds += int(was_cond)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_defs} definition(s), {created_labels} label(s), "
                f"{created_conds} condition(s); {len(DETECTOR_KEYS)} detector keys considered."
            )
        )
