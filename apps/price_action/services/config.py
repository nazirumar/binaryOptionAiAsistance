"""Configurable thresholds for the price-action knowledge engine.

Every numeric cut-off used by a detector lives here so that it is:

* **configurable** through environment variables (``PA_*``), and
* **testable** - callers may inject a :class:`PriceActionConfig` directly.

These thresholds are *pragmatic defaults chosen so that the detectors are
deterministic and reproducible*. They are **not** scientifically validated
market parameters, and they do not imply any predictive edge. They should be
tuned per instrument/timeframe and re-validated before any downstream phase
relies on them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from django.conf import settings

from apps.price_action.constants import PA_KNOWLEDGE_VERSION

#: field name -> (environment setting name, cast)
_ENV_MAP: dict[str, tuple[str, type]] = {
    "swing_lookback": ("PA_SWING_LOOKBACK", int),
    "min_swings_for_trend": ("PA_MIN_SWINGS_FOR_TREND", int),
    "equal_level_tolerance": ("PA_EQUAL_LEVEL_TOLERANCE", float),
    "consolidation_max_width": ("PA_CONSOLIDATION_MAX_WIDTH", float),
    "consolidation_min_candles": ("PA_CONSOLIDATION_MIN_CANDLES", int),
    "exhaustion_window": ("PA_EXHAUSTION_WINDOW", int),
    "exhaustion_body_shrink_ratio": ("PA_EXHAUSTION_BODY_SHRINK_RATIO", float),
    "exhaustion_opposing_wick_min": ("PA_EXHAUSTION_OPPOSING_WICK_MIN", float),
    "abc_retracement_min": ("PA_ABC_RETRACEMENT_MIN", float),
    "abc_retracement_max": ("PA_ABC_RETRACEMENT_MAX", float),
    "abc_min_leg_ratio": ("PA_ABC_MIN_LEG_RATIO", float),
    "zone_tolerance": ("PA_ZONE_TOLERANCE", float),
    "zone_min_touches": ("PA_ZONE_MIN_TOUCHES", int),
    "rejection_wick_min": ("PA_REJECTION_WICK_MIN", float),
    "breakout_close_margin": ("PA_BREAKOUT_CLOSE_MARGIN", float),
    "retest_window": ("PA_RETEST_WINDOW", int),
    "level_proximity": ("PA_LEVEL_PROXIMITY", float),
    "failed_test_min_attempts": ("PA_FAILED_TEST_MIN_ATTEMPTS", int),
    "doji_body_ratio_max": ("PA_DOJI_BODY_RATIO_MAX", float),
    "small_body_ratio_max": ("PA_SMALL_BODY_RATIO_MAX", float),
    "strong_body_ratio_min": ("PA_STRONG_BODY_RATIO_MIN", float),
    "strong_range_multiple": ("PA_STRONG_RANGE_MULTIPLE", float),
    "pin_bar_wick_min": ("PA_PIN_BAR_WICK_MIN", float),
    "pin_bar_opposite_wick_max": ("PA_PIN_BAR_OPPOSITE_WICK_MAX", float),
    "pin_bar_max_body": ("PA_PIN_BAR_MAX_BODY", float),
    "pin_bar_close_position": ("PA_PIN_BAR_CLOSE_POSITION", float),
    "doji_extreme_wick_min": ("PA_DOJI_EXTREME_WICK_MIN", float),
    "doji_opposite_wick_max": ("PA_DOJI_OPPOSITE_WICK_MAX", float),
    "spinning_top_body_max": ("PA_SPINNING_TOP_BODY_MAX", float),
    "spinning_top_wick_min": ("PA_SPINNING_TOP_WICK_MIN", float),
    "tweezer_tolerance": ("PA_TWEEZER_TOLERANCE", float),
    "extended_run_length": ("PA_EXTENDED_RUN_LENGTH", int),
    "sequence_signature_length": ("PA_SEQUENCE_SIGNATURE_LENGTH", int),
    "similar_sequence_min_samples": ("PA_SIMILAR_SEQUENCE_MIN_SAMPLES", int),
    "similar_sequence_min_similarity": ("PA_SIMILAR_SEQUENCE_MIN_SIMILARITY", float),
    "sweep_min_penetration": ("PA_SWEEP_MIN_PENETRATION", float),
    "opening_gap_min_size": ("PA_OPENING_GAP_MIN_SIZE", float),
    "high_volume_multiple": ("PA_HIGH_VOLUME_MULTIPLE", float),
    "low_volume_multiple": ("PA_LOW_VOLUME_MULTIPLE", float),
    "narrow_range_multiple": ("PA_NARROW_RANGE_MULTIPLE", float),
    "wide_range_multiple": ("PA_WIDE_RANGE_MULTIPLE", float),
    "volume_lookback": ("PA_VOLUME_LOOKBACK", int),
    "high_volatility_multiple": ("PA_HIGH_VOLATILITY_MULTIPLE", float),
    "low_volatility_multiple": ("PA_LOW_VOLATILITY_MULTIPLE", float),
    "max_candles": ("PA_MAX_CANDLES", int),
    "min_candles": ("PA_MIN_CANDLES", int),
    "knowledge_version": ("PA_KNOWLEDGE_VERSION", str),
}


@dataclass(frozen=True, slots=True)
class PriceActionConfig:
    """Immutable snapshot of the engine configuration for one run."""

    # -- structure ---------------------------------------------------------
    #: Candles required on each side to confirm a swing point.
    swing_lookback: int = 2
    #: Minimum swings of each kind required before a trend may be inferred.
    min_swings_for_trend: int = 2
    #: Absolute tolerance (as a fraction of price) for "equal" swings.
    equal_level_tolerance: float = 0.0005
    #: Range width (as a fraction of price) below which price is "consolidating".
    consolidation_max_width: float = 0.0025
    #: Minimum candles inside a consolidation window.
    consolidation_min_candles: int = 5
    # -- trend exhaustion (Phase 12) --
    #: Candles per window when comparing body sizes for exhaustion.
    exhaustion_window: int = 3
    #: Recent bodies must shrink below this fraction of the prior window's average.
    exhaustion_body_shrink_ratio: float = 0.6
    #: Opposing-wick/range minimum on the last candle to count as a signal.
    exhaustion_opposing_wick_min: float = 0.4

    # -- ABC pattern (Phase 12) --
    #: Minimum B retracement (fraction of the A→B leg) for a textbook ABC.
    abc_retracement_min: float = 0.3
    #: Maximum B retracement for a textbook ABC.
    abc_retracement_max: float = 0.886
    #: Minimum A→B leg size (fraction of price) to consider the pattern.
    abc_min_leg_ratio: float = 0.0

    # -- support / resistance ---------------------------------------------
    #: Half-width of a support/resistance zone, as a fraction of price.
    zone_tolerance: float = 0.0015
    #: Minimum touches for a candidate level to become a zone.
    zone_min_touches: int = 2
    #: Wick/range ratio above which a candle is a rejection candle.
    rejection_wick_min: float = 0.5
    #: Close must exceed a level by this fraction to confirm a breakout.
    breakout_close_margin: float = 0.0005
    #: Candles allowed for a breakout retest to appear.
    retest_window: int = 5
    #: A candle counts as "at the level" within this multiple of the zone width.
    level_proximity: float = 1.0
    #: Attacks into a zone (without a close beyond) required to call it a failed test.
    failed_test_min_attempts: int = 2

    # -- candlestick patterns ---------------------------------------------
    #: Body/range ratio at or below which a candle is a doji.
    doji_body_ratio_max: float = 0.12
    #: Body/range ratio at or below which a long-legged candle is a hammer/star.
    small_body_ratio_max: float = 0.30
    #: Minimum body/range ratio for a "strong" candle.
    strong_body_ratio_min: float = 0.60
    #: Minimum range multiple (vs recent average range) for a strong candle.
    strong_range_multiple: float = 1.2
    # -- pin bars (Phase 12) --
    #: Dominant-wick/range minimum for a pin bar.
    pin_bar_wick_min: float = 0.55
    #: Maximum opposite-wick/range allowed on a pin bar.
    pin_bar_opposite_wick_max: float = 0.12
    #: Maximum body/range for a pin bar.
    pin_bar_max_body: float = 0.40
    #: Close must sit within the top/bottom ``pin_bar_close_position`` of the range.
    pin_bar_close_position: float = 0.65
    # -- doji variants (Phase 12) --
    #: Dominant-wick/range minimum for dragonfly/gravestone dojis.
    doji_extreme_wick_min: float = 0.60
    #: Opposite-wick/range maximum for dragonfly/gravestone dojis.
    doji_opposite_wick_max: float = 0.10
    # -- spinning top (Phase 12) --
    #: Maximum body/range for a spinning top (must exceed the doji threshold).
    spinning_top_body_max: float = 0.40
    #: Minimum *each* wick/range for a spinning top.
    spinning_top_wick_min: float = 0.20
    # -- tweezers (Phase 12) --
    #: Relative tolerance for tweezer highs/lows to count as "matching".
    tweezer_tolerance: float = 0.001

    # -- sequences ---------------------------------------------------------
    #: Run length at or above which a directional run is "extended".
    extended_run_length: int = 3
    #: Window length used for similar-sequence signatures.
    sequence_signature_length: int = 3
    #: Minimum historical occurrences before a similar-sequence claim is made.
    similar_sequence_min_samples: int = 3
    #: Minimum directional similarity (0-1) to count as a match.
    similar_sequence_min_similarity: float = 1.0

    # -- sweeps / gaps -----------------------------------------------------
    #: Minimum penetration beyond a prior extreme, as a fraction of price.
    sweep_min_penetration: float = 0.0
    #: Minimum gap size (as a fraction of price) to be a reportable opening gap.
    opening_gap_min_size: float = 0.0

    # -- volume ------------------------------------------------------------
    #: Relative volume multiple considered "high".
    high_volume_multiple: float = 1.5
    #: Relative volume multiple considered "low".
    low_volume_multiple: float = 0.6
    #: Range multiple (vs average) considered "narrow".
    narrow_range_multiple: float = 0.7
    #: Range multiple (vs average) considered "wide".
    wide_range_multiple: float = 1.3
    #: Lookback used for average volume / average range.
    volume_lookback: int = 20

    # -- market context ----------------------------------------------------
    #: Relative range multiple above which volatility is "high".
    high_volatility_multiple: float = 1.5
    #: Relative range multiple below which volatility is "low".
    low_volatility_multiple: float = 0.6

    # -- limits ------------------------------------------------------------
    #: Hard bound on the number of candles the engine will evaluate.
    max_candles: int = 500
    #: Minimum candles required to produce any evidence at all.
    min_candles: int = 3

    #: Recorded on every run for auditability.
    knowledge_version: str = PA_KNOWLEDGE_VERSION

    @classmethod
    def from_settings(cls) -> PriceActionConfig:
        """Overlay any ``PA_*`` Django settings onto the defaults.

        ``slots=True`` turns the class-level defaults into member descriptors,
        so the defaults are read from a real instance, not off the class.
        """
        base = cls()
        changes: dict[str, object] = {}
        for field_name, (setting_name, cast) in _ENV_MAP.items():
            raw = getattr(settings, setting_name, None)
            if raw is None:
                continue
            changes[field_name] = cast(raw)
        return replace(base, **changes)


__all__ = ["PriceActionConfig"]
