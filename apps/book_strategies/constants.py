# book_strategies/constants.py
"""Binary Options Trading Bible - extracted strategy catalog (Phase 13).

Every entry is transcribed from the supplied PDF (119 pages). Where the book
is ambiguous or self-contradictory the wording is *recorded*, not silently
repaired: see ``ambiguities`` and ``contradictions``. Nothing in this catalog
claims profitability; the book's own "up to 90% accuracy" marketing language
is never reproduced as a verified fact.

PDF page references use the physical page numbers of the supplied file
("PDF PAGE n" markers), so reviewers can jump straight to the source.
"""

from __future__ import annotations

from dataclasses import dataclass


class BookPatternState:
    """Explicit lifecycle of a book-pattern setup.

    A confirmed pattern is NOT a confirmed trade prediction: the decision
    remains NO TRADE until a calibrated decision engine says otherwise.
    """

    FORMING = "FORMING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    CONFIRMED_PATTERN = "CONFIRMED_PATTERN"
    INVALIDATED = "INVALIDATED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

    ALL = (
        FORMING,
        AWAITING_CONFIRMATION,
        CONFIRMED_PATTERN,
        INVALIDATED,
        INSUFFICIENT_DATA,
    )


class DataVerification:
    """How (and whether) the observation was verified against candle data."""

    OHLC_VERIFIED = "OHLC_VERIFIED"
    SCREENSHOT_ONLY = "SCREENSHOT_ONLY"
    INCOMPATIBLE_FEEDS = "INCOMPATIBLE_FEEDS"
    #: Catalogued but not deterministically evaluated (no detector yet).
    NOT_EVALUATED = "NOT_EVALUATED"

    ALL = (OHLC_VERIFIED, SCREENSHOT_ONLY, INCOMPATIBLE_FEEDS, NOT_EVALUATED)


class ResearchStatus:
    """Furthest *completed* research stage. Stages are never skipped or faked."""

    EXTRACTED = "extracted"
    IMPLEMENTED = "implemented"
    RECOGNITION_TESTED = "recognition_tested"
    BACKTESTED = "backtested"
    OOS_VALIDATED = "oos_validated"
    APPROVED = "approved"

    ALL = (
        EXTRACTED,
        IMPLEMENTED,
        RECOGNITION_TESTED,
        BACKTESTED,
        OOS_VALIDATED,
        APPROVED,
    )


#: Decision/probability fields of the structured response (Step 9). Book
#: detections never carry a probability: nothing here is calibrated.
DECISION_NO_TRADE = "NO_TRADE"
PROBABILITY_STATUS = "UNAVAILABLE_UNCALIBRATED"


@dataclass(frozen=True)
class BookStrategySpec:
    """One catalog entry, transcribed from the book."""

    number: int
    key: str
    name: str
    chapter: str
    pdf_pages: str
    market_types: tuple[str, ...]
    trade_type: str
    requirements: tuple[str, ...]
    confirmation_rule: str
    invalidation_rules: tuple[str, ...] = ()
    mtg_policy: str = ""
    #: Where the book does not specify enough to implement literally.
    ambiguities: tuple[str, ...] = ()
    #: Where the book contradicts itself. Recorded, never silently repaired.
    contradictions: tuple[str, ...] = ()
    #: Annotations lifted from the book's chart illustrations.
    illustration_evidence: str = ""
    #: Detector registered for this entry ("" = catalogued only).
    detector_key: str = ""
    #: Priority implementation from the Phase 13 brief.
    priority: bool = False


#: The stochastic condition repeated by nearly every Sure Shot pattern.
_STOCH_UP = (
    "Stochastic (default) green line (%K) above red line (%D) for up trades; "
    "the reverse for down trades.",
)
_PRECAUTIONS = (
    "Book precaution: back-test the pattern on the pair first; the book's own "
    "accuracy claims are unverified.",
)

BOOK_STRATEGIES: tuple[BookStrategySpec, ...] = (
    BookStrategySpec(
        number=1,
        key="SS1",
        name="Sequence Breakout Continuation",
        chapter="6",
        pdf_pages="31-33",
        market_types=("trending", "ranging"),
        trade_type="continuation",
        requirements=(
            "Market trending or in a good ranging motion.",
            "Up setup: 1 green candle then 2 back-to-back red candles "
            "(down setup: 1 red then 2 back-to-back green).",
            "Place a horizontal line 'in between' the two back-to-back candles.",
            "Wait for the market to break the horizontal line, then trade in "
            "the same (breakout) direction.",
            *_STOCH_UP,
        ),
        confirmation_rule=(
            "A candle breaks the horizontal line; the chart annotation states "
            "'Breakout with wick and body is accepted'."
        ),
        mtg_policy="1-step martingale only if stochastic supports the direction (book rule).",
        ambiguities=(
            "The level is described only as 'in between of 2 back to back "
            "candles' - the exact price is not defined; the illustration shows "
            "a line spanning the two-candle area.",
        ),
        illustration_evidence=(
            "Page 32/33 annotations: 'Horizontal line In between two Back to "
            "back red Candles', 'Breakout with Wick and body is Accepted', "
            "'Breakout Candle', 'Trade Candle'."
        ),
        detector_key="ss1",
        priority=True,
    ),
    BookStrategySpec(
        number=2,
        key="SS2",
        name="Magic V",
        chapter="6",
        pdf_pages="34-36",
        market_types=("trending", "ranging"),
        trade_type="continuation",
        requirements=(
            "Market trending or in a good ranging motion.",
            "1 green candle and 2 back-to-back red candles (or 1 red and 2 "
            "back-to-back green).",
            "Place a horizontal line on top of the candles.",
            "Wait for a break of the line, then wait for ONE candle; trade in "
            "the direction of that candle.",
            *_STOCH_UP,
        ),
        confirmation_rule=(
            "After the breakout candle closes, the next candle's colour decides "
            "the trade direction (book illustration: 'If this candle is green "
            "then next candle green. If it is red then next candle red')."
        ),
        mtg_policy="1-step martingale only if stochastic supports the direction (book rule).",
        ambiguities=(
            "Requirement 4 says 'place the trade in the same direction' without "
            "naming a reference; the chart annotation resolves it as the colour "
            "of the waited-for candle.",
        ),
        contradictions=(
            "SS2 and SS3 are near-identical Magic V setups differing only in "
            "entry timing, yet the book states 'Either SS2 or SS3 will work' - "
            "it never defines how to know which one is 'working' on a given day.",
        ),
        illustration_evidence=(
            "Page 35 annotations: 'Horizontal line', 'Breakout candle', "
            "'If this candle is green Then next candle green. If it is Red "
            "then next candle red', 'Trade'."
        ),
        detector_key="ss2",
        priority=True,
    ),
    BookStrategySpec(
        number=3,
        key="SS3",
        name="Magic V Advanced",
        chapter="6",
        pdf_pages="37-39",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market trending in a motion (book requires a trend here, unlike SS2).",
            "1 green candle and 2 back-to-back red candles (or 1 red and 2 "
            "back-to-back green).",
            "Place a horizontal line on top of the candles.",
            "Wait for the break of the line, then trade immediately in the "
            "breakout direction (no waiting candle, unlike SS2).",
            *_STOCH_UP,
        ),
        confirmation_rule="The candle that breaks the line; trade follows the breakout direction.",
        mtg_policy="1-step martingale only if stochastic supports the direction (book rule).",
        contradictions=(
            "SS3 states 'Either SS2 or SS3 will work so back test properly' - "
            "the book never provides a rule for deciding which variant is "
            "active, so both are catalogued separately and implemented as "
            "separate detectors with the exact timing difference preserved.",
        ),
        illustration_evidence=(
            "Page 38/39 annotations: 'Breakout candle', 'Trade Candle' - no "
            "waiting candle between breakout and trade, versus SS2's extra candle."
        ),
        detector_key="ss3",
        priority=True,
    ),
    BookStrategySpec(
        number=4,
        key="SS4",
        name="Engulfing + Tailless Candle",
        chapter="6",
        pdf_pages="40-43",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market trending in motion.",
            "Bullish engulfing forms, then immediately a green tailless candle "
            "(no lower shadow) appears; mirrored for bearish.",
            *_STOCH_UP,
        ),
        confirmation_rule="The tailless candle immediately after the engulfing candle; trade in that direction.",
        mtg_policy="1-step martingale only if stochastic supports the direction (book rule).",
        ambiguities=(
            "'Immediately' is not quantified beyond the next candle.",
        ),
        illustration_evidence=(
            "Page 42/43 annotations: 'Bullish Engulfing', 'Tailless candle', "
            "'Trade candle'."
        ),
    ),
    BookStrategySpec(
        number=5,
        key="SS5",
        name="Four-Candle Pullback Hold",
        chapter="6",
        pdf_pages="44-48",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market trending (up or down).",
            "Back-to-back run of at least 4 same-colour candles.",
            "Then 1 opposite-colour candle appears (illustration allows 1 or 2).",
            "Place a horizontal line at the top of the opposite-colour candle "
            "(bottom for the down setup).",
            "If the NEXT candle does NOT break the line, trade with the trend.",
            *_STOCH_UP,
        ),
        confirmation_rule=(
            "The candle after the pullback candle fails to break the reference "
            "line - the pullback holds - so the trend trade is taken."
        ),
        invalidation_rules=(
            "Three opposite-colour candles: pattern is not valid (book note).",
            "If after 2 opposite candles the trend-colour candles break the "
            "horizontal line, the pattern is invalid (book note).",
        ),
        mtg_policy="1-step martingale only if stochastic supports the direction (book rule).",
        contradictions=(
            "Requirement 3 says 'wait for 1 opposite colour candle' but the "
            "chart illustrations label '1 or 2 opposite candle'; both readings "
            "are supported and the 3-opposite-candle invalidation is enforced.",
        ),
        illustration_evidence=(
            "Page 45 annotations: 'Minimum 4 same color candle it can also be "
            "more than 4', '1 or 2 opposite candle', 'If this candle doesn't "
            "break the horizontal line then place up trade in next candle'."
        ),
        detector_key="ss5",
        priority=True,
    ),
    BookStrategySpec(
        number=6,
        key="SS6",
        name="Four-Candle Body Breakout",
        chapter="6",
        pdf_pages="49-53",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market trending (up or down).",
            "Back-to-back run of at least 4 same-colour candles.",
            "Then 1 opposite-colour candle; place a horizontal line at the top "
            "of that candle (bottom for the down setup).",
            "If the next candle breaks the level WITH ITS BODY, trade in the "
            "trend direction.",
            *_STOCH_UP,
        ),
        confirmation_rule=(
            "Body-only breakout: the closing price must break the level. The "
            "book repeats 'Make sure the breakout only through the body is valid'."
        ),
        mtg_policy="NON-MTG: the book says do NOT take a martingale if this trade loses.",
        ambiguities=(
            "Requirement 4 says the level sits at the top of the single "
            "opposite candle, but the live-example annotation says 'at the top "
            "of Two candles which Ever is the highest point'.",
        ),
        illustration_evidence=(
            "Page 50/51 annotations: 'Place the horizontal line at the top', "
            "'Breakout candle', 'Only with the body is valid', 'Trade Candle'."
        ),
        detector_key="ss6",
        priority=True,
    ),
    BookStrategySpec(
        number=7,
        key="SS7",
        name="Green-Red-Green + Pullback",
        chapter="6",
        pdf_pages="54-58",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market trending in motion.",
            "Up setup: Green, Red, Green candles, then a minimum of 3-4 green "
            "candles; then wait for 1 red candle and trade UP on it. Mirrored "
            "for the down setup.",
            *_STOCH_UP,
        ),
        confirmation_rule="The single opposite-colour candle after the extended run; trade with the trend.",
        mtg_policy="1-step martingale only if stochastic supports the direction (book rule).",
        ambiguities=(
            "The text says 'minimum of 4 green candles' while the illustrations "
            "label 'Minimum 3-4 Green candle'.",
        ),
    ),
    BookStrategySpec(
        number=8,
        key="SS8",
        name="Colour-Pattern Break Reversal",
        chapter="6",
        pdf_pages="59-63",
        market_types=("trending", "ranging"),
        trade_type="reversal",
        requirements=(
            "Market trending or ranging.",
            "Back-to-back 4 same-colour candles, then an alternating colour "
            "pattern (Green Red Green Red...) begins.",
            "When the colour pattern breaks, trade in the OTHER direction.",
            *_STOCH_UP,
        ),
        confirmation_rule="The candle that breaks the alternating colour sequence; trade against it.",
        mtg_policy="1-step martingale only if stochastic supports the direction (book rule).",
        ambiguities=(
            "The number of alternating candles required before the break is "
            "not specified.",
        ),
    ),
    BookStrategySpec(
        number=9,
        key="SS9",
        name="SS8 Continuation Reversal",
        chapter="6",
        pdf_pages="64-67",
        market_types=("trending", "ranging"),
        trade_type="reversal",
        requirements=(
            "An SS8 setup must have formed perfectly first.",
            "After the SS8 trade candle, if the next candle has the SS8 trade "
            "candle's colour, trade in the opposite direction.",
            "Book note: only valid when SS8 won without a martingale.",
        ),
        confirmation_rule="A same-colour candle following the SS8 trade candle; trade reversed.",
        mtg_policy="1-step martingale allowed (book rule).",
    ),
    BookStrategySpec(
        number=10,
        key="SS10",
        name="Gap Up/Down Double Trade",
        chapter="6",
        pdf_pages="68-70",
        market_types=("trending", "ranging", "stack"),
        trade_type="continuation",
        requirements=(
            "Any market type.",
            "Up setup: wait for a gap-up candle opening; trade UP while the gap "
            "persists; then a DOWN trade follows because the market creates a "
            "red candle to fill the gap.",
            "Stochastic green above red for up.",
        ),
        confirmation_rule="The gapping open itself; second (counter) trade assumes gap-fill behaviour.",
        mtg_policy="1-step MTG only on the second trade (book rule).",
        ambiguities=(
            "No minimum gap size is defined; on continuous FX feeds genuine "
            "gaps rarely exist, so this pattern is catalogued but not "
            "implemented as a deterministic detector.",
        ),
    ),
    BookStrategySpec(
        number=11,
        key="SS11",
        name="Gap Fill Counter",
        chapter="6",
        pdf_pages="71-73",
        market_types=("trending", "ranging", "stack"),
        trade_type="continuation",
        requirements=(
            "Any market type.",
            "Up setup: a gap DOWN opening after a green candle - trade UP "
            "because the market creates an up candle to fill the gap.",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="Gap-down open after a green candle; trade in the trend colour to fill the gap.",
        mtg_policy="1-step MTG only on the second trade (book rule).",
        ambiguities=("No minimum gap size is defined; not implemented deterministically.",),
    ),
    BookStrategySpec(
        number=12,
        key="SS12",
        name="Doji Direction Follow",
        chapter="6",
        pdf_pages="74-76",
        market_types=("ranging", "stack"),
        trade_type="continuation",
        requirements=(
            "Ranging or stack market.",
            "A green and a red candle form, then a doji.",
            "Trade in the direction of the doji's colour (green doji -> up).",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The doji's own colour decides the trade direction.",
        mtg_policy="1-step MTG allowed (book rule).",
        ambiguities=(
            "The book never defines which doji types count ('green/red doji' "
            "is not standard terminology for a neutral candle).",
        ),
    ),
    BookStrategySpec(
        number=13,
        key="SS13",
        name="Three-Candle Doji Reversal",
        chapter="6",
        pdf_pages="77-79",
        market_types=("ranging",),
        trade_type="reversal",
        requirements=(
            "Good ranging motion; first a green and a red candle.",
            "Then 3 back-to-back same-colour candles.",
            "A red doji after 3 green candles -> down; a green doji after 3 red "
            "candles -> up.",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The counter-coloured doji after the 3-candle run.",
        mtg_policy="1-step MTG allowed (book rule).",
        ambiguities=("Doji colour terminology is undefined (see SS12).",),
    ),
    BookStrategySpec(
        number=14,
        key="SS14",
        name="Wick Break of Prior Body",
        chapter="6",
        pdf_pages="80-81",
        market_types=("ranging",),
        trade_type="reversal",
        requirements=(
            "Ranging market; a green and a red candle form.",
            "Then a green candle whose WICK breaks below the previous red "
            "candle's body - trade DOWN.",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The wick break below the prior red candle's body.",
        mtg_policy="1-step MTG allowed (book rule).",
        ambiguities=("Only the down direction is described; no mirrored up rule is given.",),
    ),
    BookStrategySpec(
        number=15,
        key="SS15",
        name="Hammer -> Inverted Hammer Reversal",
        chapter="6",
        pdf_pages="82",
        market_types=("trending", "ranging", "stack"),
        trade_type="reversal",
        requirements=(
            "A hammer candle forms.",
            "An inverted-hammer candle forms after it - trade DOWN.",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The inverted hammer following the hammer.",
        mtg_policy="1-step MTG allowed (book rule).",
        ambiguities=("The book's Chapter 1 calls the inverted hammer bearish 'after a long uptrend' but SS15 imposes no trend condition.",),
    ),
    BookStrategySpec(
        number=16,
        key="SS16",
        name="Inverted Hammer -> Hammer Reversal",
        chapter="6",
        pdf_pages="83",
        market_types=("trending", "ranging", "stack"),
        trade_type="reversal",
        requirements=(
            "An inverted hammer candle forms.",
            "A hammer candle forms after it - trade UP.",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The hammer following the inverted hammer.",
        mtg_policy="1-step MTG allowed (book rule).",
    ),
    BookStrategySpec(
        number=17,
        key="SS17",
        name="Headless Red -> Tailless Green",
        chapter="6",
        pdf_pages="84-85",
        market_types=("ranging", "stack"),
        trade_type="continuation",
        requirements=(
            "A headless red candle (small body at top, lower shadow equal to "
            "the body, no upper shadow) forms.",
            "A green tailless candle forms after it - trade UP.",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The tailless green candle after the headless red candle.",
        mtg_policy="1-step MTG allowed (book rule).",
        ambiguities=("Headless/tailless candles are defined with exact wick/body equalities that almost never occur literally in real data.",),
    ),
    BookStrategySpec(
        number=18,
        key="SS18",
        name="Tailless Green -> Tailless Red",
        chapter="6",
        pdf_pages="86-87",
        market_types=("ranging", "stack"),
        trade_type="continuation",
        requirements=(
            "A tailless green candle forms.",
            "A red tailless candle forms after it - trade DOWN.",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The tailless red candle after the tailless green candle.",
        mtg_policy="1-step MTG allowed (book rule).",
    ),
    BookStrategySpec(
        number=19,
        key="SS19",
        name="Doji-Level Breakout",
        chapter="6",
        pdf_pages="88-92",
        market_types=("trending",),
        trade_type="reversal",
        requirements=(
            "Market trending (up or down).",
            "Back-to-back run of at least 4 same-colour candles.",
            "A doji forms after the run.",
            "Place a horizontal line at the doji.",
            "Wait for the market to break that line, then trade in the "
            "breakout direction.",
            *_STOCH_UP,
        ),
        confirmation_rule=(
            "A closed candle breaking beyond the doji's range; direction = the "
            "break direction (our explicit interpretation, see ambiguities)."
        ),
        mtg_policy="1-step MTG allowed (book rule).",
        ambiguities=(
            "The book says 'wait for the market to reverse and break that "
            "horizontal line' then 'place the trade in same direction', while "
            "the sections are titled 'UP/DOWN-DIRECTION TRADE' - whether "
            "'same direction' means the break direction or the trend direction "
            "is not resolvable from the text.",
            "The single 'line at the doji' does not say which doji price "
            "(high/low/mid) it marks; the detector uses the doji range edges.",
        ),
        illustration_evidence=(
            "Page 89/91 annotations: 'Doji candle', 'Horizontal line at doji', "
            "'Breakout candle', 'Trade candle'."
        ),
        detector_key="ss19",
        priority=True,
    ),
    BookStrategySpec(
        number=20,
        key="SS20",
        name="Doji Continuation",
        chapter="6",
        pdf_pages="93-97",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market trending; at least 4 same-colour candles.",
            "A doji forms; if the NEXT candle is the run's colour, trade in "
            "that colour.",
            *_STOCH_UP,
        ),
        confirmation_rule="A same-run-colour candle immediately after the doji.",
        invalidation_rules=(
            "The last candle must not be a hammer, an abnormal candle, or a "
            "big candle (book precaution, undefined numerically).",
        ),
        mtg_policy="NO MTG (book rule).",
        ambiguities=("'Abnormal candle' and 'big candle' are not defined.",),
    ),
    BookStrategySpec(
        number=21,
        key="SS21",
        name="Five-Candle Reference-Candle Breakout",
        chapter="6",
        pdf_pages="98-102",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market in trending motion.",
            "Back-to-back run of at least 5 same-colour candles.",
            "Then one opposite-colour candle forms.",
            "Mark the High and Low of that opposite candle with horizontal "
            "line(s).",
            "Wait for a successful breakout of the line, then trade in the "
            "breakout direction.",
            *_STOCH_UP,
        ),
        confirmation_rule=(
            "A closed candle breaking beyond the reference candle's level; the "
            "detector requires a CLOSE beyond the level (body break)."
        ),
        invalidation_rules=(
            "The last candle must not be a hammer, an abnormal candle, or a "
            "big candle (book precaution).",
        ),
        mtg_policy="1-step MTG allowed (book rule).",
        ambiguities=(
            "'Successful breakout' is not defined as wick or body; the "
            "detector uses a closing break (conservative).",
            "'High and Low ... with the horizontal line' (two lines) versus "
            "the live-example annotation 'Horizontal line at Top of opposite "
            "Candle' (one line); the detector uses the single trend-side level.",
        ),
        illustration_evidence=(
            "Page 99/100 annotations: 'Minimum 5 Same color Candle', "
            "'Horizontal line at Top of opposite Candle', 'Breakout candle', "
            "'Trade candle'."
        ),
        detector_key="ss21",
        priority=True,
    ),
    BookStrategySpec(
        number=22,
        key="SS22",
        name="Rising Three Method",
        chapter="6",
        pdf_pages="103-104",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market in trending motion.",
            "3 back-to-back green candles.",
            "Then 3 back-to-back red candles.",
            "Then 1 green candle that engulfs all three red candles - trade UP.",
            *_STOCH_UP,
        ),
        confirmation_rule="The single green candle fully engulfing the three red candles' range.",
        mtg_policy="1-step MTG allowed (book rule).",
        ambiguities=(
            "'Engulf' is not defined as body-vs-body or full high/low range; "
            "the detector requires the full high/low range engulf.",
        ),
        illustration_evidence="Page 104 annotations: 'Trade candle', 'Breakout candle'.",
        detector_key="ss22",
        priority=True,
    ),
    BookStrategySpec(
        number=23,
        key="SS23",
        name="Falling Three Method",
        chapter="6",
        pdf_pages="105-106",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market in trending motion.",
            "3 back-to-back red candles.",
            "Then 3 back-to-back green candles.",
            "Then 1 red candle that engulfs all three green candles - trade DOWN.",
            *_STOCH_UP,
        ),
        confirmation_rule="The single red candle fully engulfing the three green candles' range.",
        mtg_policy="1-step MTG allowed (book rule).",
        contradictions=(
            "Requirement 4 literally reads 'Wait for 1 red candle to engulf "
            "all three red candle' - a typo; the mirrored SS22 rule and the "
            "down-setup illustration show it must be the three GREEN candles. "
            "The contradiction is recorded; the detector implements the "
            "mirror-accurate reading.",
        ),
        illustration_evidence="Page 106 annotations: 'Trade candle'.",
        detector_key="ss23",
        priority=True,
    ),
    BookStrategySpec(
        number=24,
        key="SS24",
        name="Increasing Body Exhaustion",
        chapter="6",
        pdf_pages="107-108",
        market_types=("trending",),
        trade_type="reversal",
        requirements=(
            "Market in trending motion.",
            "A 4-candle setup where the candle size keeps increasing.",
            "Then place a trade in the OPPOSITE direction.",
            "Avoid hammer and doji candles; an S/R level nearby is required for MTG.",
        ),
        confirmation_rule="Four consecutively larger candles, then a counter trade.",
        mtg_policy="1-step MTG allowed if an S/R level is nearby (book rule).",
        ambiguities=("'The candle size should keep on increasing' is not defined (body? range?).",),
    ),
    BookStrategySpec(
        number=25,
        key="SS25",
        name="Brazilian Pattern Up",
        chapter="6",
        pdf_pages="109-110",
        market_types=("ranging",),
        trade_type="continuation",
        requirements=(
            "Ranging market.",
            "Colour sequence: Green, Red, Red, Green, Red - then trade UP.",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The 5-candle colour sequence ending on red; trade up on the next candle.",
        mtg_policy="2-step MTG (book rule).",
        ambiguities=("The book labels 25/26 as up/down variants of one colour sequence and 27/28 as another; the exact sequence-to-direction mapping is only shown in illustrations.",),
    ),
    BookStrategySpec(
        number=26,
        key="SS26",
        name="Brazilian Pattern Down",
        chapter="6",
        pdf_pages="111-112",
        market_types=("ranging",),
        trade_type="continuation",
        requirements=(
            "Ranging market.",
            "Colour sequence: Red, Green, Green, Red, Green - then trade DOWN.",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The 5-candle colour sequence ending on green; trade down on the next candle.",
        mtg_policy="2-step MTG (book rule).",
    ),
    BookStrategySpec(
        number=27,
        key="SS27",
        name="Brazilian Pattern 3 Up",
        chapter="6",
        pdf_pages="113-114",
        market_types=("ranging",),
        trade_type="continuation",
        requirements=(
            "Ranging market.",
            "Colour sequence: Green, Red, Green, Green - then trade DOWN "
            "(as written by the book).",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The 4-candle colour sequence; trade on the next candle.",
        mtg_policy="1-step MTG (book rule).",
        contradictions=(
            "The book's requirement 3 says 'place the trade-in down-direction' "
            "for a sequence ending in GREEN (1 green 1 red 2 green) while SS28's "
            "mirror (1 red 1 green 2 red) trades UP; the direction-to-sequence "
            "mapping contradicts the trend logic used everywhere else in the "
            "book. Recorded, not repaired.",
        ),
    ),
    BookStrategySpec(
        number=28,
        key="SS28",
        name="Brazilian Pattern 3 Down",
        chapter="6",
        pdf_pages="115-116",
        market_types=("ranging",),
        trade_type="continuation",
        requirements=(
            "Ranging market.",
            "Colour sequence: Red, Green, Red, Red - then trade UP "
            "(as written by the book).",
            "Stochastic must support the direction.",
        ),
        confirmation_rule="The 4-candle colour sequence; trade on the next candle.",
        mtg_policy="1-step MTG (book rule).",
        contradictions=("See SS27: the direction mapping contradicts the book's own trend logic.",),
    ),
    BookStrategySpec(
        number=29,
        key="SS29",
        name="Colour Pattern Follow (paired 29/30 up)",
        chapter="6",
        pdf_pages="117",
        market_types=("ranging", "stack"),
        trade_type="continuation",
        requirements=(
            "Ranging or stack market.",
            "The market makes a green-red colour pattern; check the OVERALL "
            "trend and trade following the colour pattern in the trend direction.",
        ),
        confirmation_rule="The alternating colour pattern confirmed by the overall trend direction.",
        ambiguities=(
            "'Check the overall trend then place the trade ... following the "
            "colour pattern' is under-specified; SS29 and SS30 share one "
            "section with no separate rules, so they cannot be distinguished.",
        ),
    ),
    BookStrategySpec(
        number=30,
        key="SS30",
        name="Colour Pattern Follow (paired 29/30 down)",
        chapter="6",
        pdf_pages="117",
        market_types=("ranging", "stack"),
        trade_type="continuation",
        requirements=(
            "Ranging or stack market; green-red colour pattern; trade with the "
            "overall trend (see SS29).",
        ),
        confirmation_rule="Shared with SS29 - the book provides no separate rules.",
        contradictions=(
            "SS29 and SS30 are presented as one pattern with one requirement "
            "list; they cannot be separated from the text alone.",
        ),
    ),
    BookStrategySpec(
        number=1,
        key="CH7_S1",
        name="EMA5 + Parabolic SAR + Stochastic Alignment",
        chapter="7",
        pdf_pages="118",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market in trending motion.",
            "Apply EMA 5, Parabolic SAR at default 0.02 and Stochastic at 80/20.",
            "Once a strong candle breaks the EMA 5 line, with Parabolic SAR "
            "and Stochastic both supporting the same direction, trade in that "
            "direction.",
            "Continue until an opposite-colour candle crosses EMA 5.",
        ),
        confirmation_rule="Candle closes beyond EMA5 with SAR and stochastic on the same side.",
        invalidation_rules=(
            "An opposite-colour candle crosses the EMA 5 line (book exit rule).",
        ),
        mtg_policy="",
        ambiguities=(
            "'Strong candle' is never defined numerically.",
            "'Breaks the EMA 5 line' does not say wick or close crossing.",
            "The stochastic '80/20' refers to the overbought/oversold bands, "
            "not the smoothing; the book does not say the trade must be "
            "outside the bands, only that stochastic is 'supporting'.",
        ),
        illustration_evidence="Page 118 states the rule text only; no chart illustration.",
        detector_key="ch7_s1",
        priority=True,
    ),
    BookStrategySpec(
        number=2,
        key="CH7_S2",
        name="EMA5 + SAR + Donchian + Stochastic Tailless Entry",
        chapter="7",
        pdf_pages="119",
        market_types=("trending",),
        trade_type="continuation",
        requirements=(
            "Market in trending motion (uptrend for the up setup).",
            "Apply EMA 5, Parabolic SAR 0.02, Donchian channel period 17 and "
            "Stochastic 80/20.",
            "For up: price in the UPPER Donchian channel; wait for a tailless "
            "candle; with SAR and stochastic supporting - trade.",
        ),
        confirmation_rule="Tailless candle inside the upper Donchian channel with SAR + stochastic support.",
        mtg_policy="1-step MTG if conditions are perfect (book rule).",
        ambiguities=(
            "'In upper channel' is not defined as above the midline or above "
            "the upper band; the detector uses above the midline.",
            "Tailless is defined in Chapter 1 as a candle with no lower shadow "
            "and an upper shadow equal to the body - an exact equality that "
            "needs a tolerance, which the book never gives.",
        ),
        illustration_evidence="Page 119 shows a 'Tailless candle' + 'Trade candle' sketch.",
    ),
)

#: Fast lookup by key.
SPEC_BY_KEY: dict[str, BookStrategySpec] = {spec.key: spec for spec in BOOK_STRATEGIES}

#: Detector keys that have a deterministic implementation (Phase 13 priority).
IMPLEMENTED_KEYS: tuple[str, ...] = tuple(
    spec.detector_key for spec in BOOK_STRATEGIES if spec.detector_key
)

#: Catalog keys (e.g. ``"SS1"``) that have a deterministic detector - the form
#: accepted by ``SPEC_BY_KEY`` and the recognizer/validation services.
IMPLEMENTED_SPEC_KEYS: tuple[str, ...] = tuple(
    spec.key for spec in BOOK_STRATEGIES if spec.detector_key
)

#: The priority detector keys from the Phase 13 brief.
PRIORITY_KEYS: tuple[str, ...] = tuple(
    spec.detector_key for spec in BOOK_STRATEGIES if spec.priority and spec.detector_key
)
