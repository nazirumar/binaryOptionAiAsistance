# screenshot_eval/constants.py
"""Enumerations and honesty constants for Phase 14 screenshot evaluation.

Phase 14 adds a *measured* evaluation workflow on top of the existing vision
pipeline (``apps.chart_vision``) and book-strategy recognizers
(``apps.book_strategies``). Nothing here rebuilds those modules; this app owns
only the dataset, the recognition run, the annotations, the immutable forward
paper predictions, the outcome verification and the review queue.

Two hard rules encoded as constants:

* **No fabrication** - screenshot evidence is qualitative; candle OHLC prices
  and pixel coordinates are never invented. An annotation is only written when
  the source coordinates are *reliable*, otherwise it is skipped with a reason.
* **Scope separation** - recognition accuracy (did we identify the pattern a
  human labelled?) and prediction accuracy (did the next outcome move the way
  we predicted?) live in different scopes and are never mixed.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Dataset (Checkpoint 1)
# ---------------------------------------------------------------------------
class CaseKind:
    """What kind of labelled example a screenshot case represents."""

    POSITIVE = "positive"  # a pattern the book strategy should recognise
    NEGATIVE = "negative"  # a lookalike that must NOT be recognised
    INCOMPLETE = "incomplete"  # a still-forming pattern
    UNLABELLED = "unlabelled"  # imported but not yet human-reviewed

    CHOICES = (
        (POSITIVE, "Positive example"),
        (NEGATIVE, "Negative example"),
        (INCOMPLETE, "Incomplete formation"),
        (UNLABELLED, "Not yet reviewed"),
    )
    ALL = (POSITIVE, NEGATIVE, INCOMPLETE, UNLABELLED)


class MarketType:
    """IQ Option market type of the captured chart."""

    OTC = "otc"
    REGULAR = "regular"
    UNKNOWN = "unknown"

    CHOICES = ((OTC, "OTC"), (REGULAR, "Regular session"), (UNKNOWN, "Unknown"))
    ALL = (OTC, REGULAR, UNKNOWN)


class ScreenshotQuality:
    """Reviewer-assessed usability of the screenshot for recognition."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNUSABLE = "unusable"
    UNKNOWN = "unknown"

    CHOICES = (
        (HIGH, "High"),
        (MEDIUM, "Medium"),
        (LOW, "Low"),
        (UNUSABLE, "Unusable"),
        (UNKNOWN, "Unknown"),
    )
    ALL = (HIGH, MEDIUM, LOW, UNUSABLE, UNKNOWN)


class Provenance:
    """How a case entered the dataset (recorded verbatim, never guessed)."""

    USER_UPLOAD = "user_upload"
    IMPORTED_DIR = "imported_directory"
    SEEDED = "seeded"
    UNKNOWN = "unknown"

    CHOICES = (
        (USER_UPLOAD, "User upload"),
        (IMPORTED_DIR, "Imported directory"),
        (SEEDED, "Seeded"),
        (UNKNOWN, "Unknown"),
    )


# ---------------------------------------------------------------------------
# Human review (Checkpoints 1 & 7)
# ---------------------------------------------------------------------------
class ReviewState:
    """Reviewer verdict on a case's human label."""

    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"  # reviewer agrees with the recorded expectation
    CORRECTED = "corrected"  # reviewer changed the expectation
    REJECTED = "rejected"  # case is unusable as ground truth

    CHOICES = (
        (UNREVIEWED, "Unreviewed"),
        (CONFIRMED, "Confirmed"),
        (CORRECTED, "Corrected"),
        (REJECTED, "Rejected"),
    )
    ALL = (UNREVIEWED, CONFIRMED, CORRECTED, REJECTED)


# ---------------------------------------------------------------------------
# Annotations (Checkpoint 3)
# ---------------------------------------------------------------------------
class AnnotationKind:
    """What a chart annotation marks."""

    PATTERN_CANDLES = "pattern_candles"
    SUPPORT = "support"
    RESISTANCE = "resistance"
    REFERENCE_LEVEL = "reference_level"
    CONFIRMATION_CANDLE = "confirmation_candle"
    INVALIDATION_LEVEL = "invalidation_level"
    PATTERN_NAME = "pattern_name"

    CHOICES = (
        (PATTERN_CANDLES, "Detected pattern candles"),
        (SUPPORT, "Support line"),
        (RESISTANCE, "Resistance line"),
        (REFERENCE_LEVEL, "Reference breakout level"),
        (CONFIRMATION_CANDLE, "Confirmation candle"),
        (INVALIDATION_LEVEL, "Invalidation level"),
        (PATTERN_NAME, "Pattern name"),
    )


class AnnotationStatus:
    """Honesty ladder for an annotation - unreliable coordinates are skipped."""

    AVAILABLE = "available"  # reliable coordinates present
    QUALITATIVE = "qualitative"  # label only, no coordinates (never invented)
    SKIPPED = "skipped"  # coordinates unreliable - nothing drawn

    CHOICES = (
        (AVAILABLE, "Available (coordinates recorded)"),
        (QUALITATIVE, "Qualitative (no coordinates)"),
        (SKIPPED, "Skipped (coordinates unreliable)"),
    )


# ---------------------------------------------------------------------------
# Forward prediction (Checkpoint 4)
# ---------------------------------------------------------------------------
class PredictionDirection:
    """The decision recorded before the outcome is known."""

    UP = "up"
    DOWN = "down"
    NO_TRADE = "no_trade"

    CHOICES = ((UP, "UP"), (DOWN, "DOWN"), (NO_TRADE, "NO TRADE"))
    ALL = (UP, DOWN, NO_TRADE)


class PredictionStatus:
    """Lifecycle of a locked forward prediction."""

    LOCKED = "locked"  # frozen before the outcome; awaiting verification
    VERIFIED = "verified"  # outcome independently verified against the right feed
    UNVERIFIED = "unverified"  # outcome could not be independently verified
    TIE = "tie"  # settlement quote equals entry quote
    UNRESOLVED = "unresolved"  # outcome not yet available / window incomplete

    CHOICES = (
        (LOCKED, "Locked (awaiting outcome)"),
        (VERIFIED, "Verified"),
        (UNVERIFIED, "Unverified"),
        (TIE, "Tie"),
        (UNRESOLVED, "Unresolved"),
    )
    TERMINAL = (VERIFIED, UNVERIFIED, TIE)
    ALL = (LOCKED, VERIFIED, UNVERIFIED, TIE, UNRESOLVED)


class OutcomeVerdict:
    """Verdict of an outcome-verification attempt against a named feed."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    TIE = "tie"
    REFUSED = "refused"  # wrong feed (e.g. OTC checked against MT5) - never coerced
    UNVERIFIABLE = "unverifiable"  # no trustworthy quote available
    PENDING = "pending"  # outcome window not complete yet

    CHOICES = (
        (CORRECT, "Correct"),
        (INCORRECT, "Incorrect"),
        (TIE, "Tie"),
        (REFUSED, "Refused (incompatible feed)"),
        (UNVERIFIABLE, "Unverifiable (no quote)"),
        (PENDING, "Pending"),
    )


#: Reason codes used across the app (kept as plain strings for the JSON layer).
REASON_NOT_COMPUTABLE = "NOT_COMPUTABLE_NO_GROUND_TRUTH"
REASON_INCOMPATIBLE_FEEDS = "INCOMPATIBLE_FEEDS"
REASON_NO_QUOTE = "NO_SETTLEMENT_QUOTE"
REASON_INSUFFICIENT_LABELS = "INSUFFICIENT_LABELLED_CASES"
REASON_UNRELIABLE_COORDS = "COORDINATES_UNRELIABLE"

#: Probability is only ever recorded when a model has been calibrated AND
#: approved. Screenshot recognition itself never yields a probability.
PROBABILITY_UNAVAILABLE = "UNAVAILABLE_UNCALIBRATED"

# ---------------------------------------------------------------------------
# Metric scopes (Checkpoint 6) - never mixed
# ---------------------------------------------------------------------------
RECOGNITION_METRIC_SCOPE = "pattern_recognition"
PREDICTION_METRIC_SCOPE = "binary_settlement_outcome"
ANNOTATION_METRIC_SCOPE = "chart_annotation"

#: Minimum number of verified outcomes before any hit-rate claim is made.
DEFAULT_MIN_VERIFIED = 30
#: Minimum number of human-labelled cases before precision/recall is reported.
DEFAULT_MIN_LABELS = 30

RECOGNITION_SEPARATION = (
    "Recognition scope only: did the system identify the pattern a human "
    "labelled on the same screenshot? No next-candle or settlement outcome is "
    "included, and recognition accuracy is never borrowed from prediction "
    "accuracy."
)
PREDICTION_SEPARATION = (
    "Prediction scope only: verified outcomes against the correct market feed. "
    "Unverified, refused and unresolved records are reported separately and are "
    "never counted as correct or incorrect."
)


__all__ = [
    "ANNOTATION_METRIC_SCOPE",
    "DEFAULT_MIN_LABELS",
    "DEFAULT_MIN_VERIFIED",
    "PREDICTION_METRIC_SCOPE",
    "PREDICTION_SEPARATION",
    "PROBABILITY_UNAVAILABLE",
    "REASON_INCOMPATIBLE_FEEDS",
    "REASON_INSUFFICIENT_LABELS",
    "REASON_NOT_COMPUTABLE",
    "REASON_NO_QUOTE",
    "REASON_UNRELIABLE_COORDS",
    "RECOGNITION_METRIC_SCOPE",
    "RECOGNITION_SEPARATION",
    "AnnotationKind",
    "AnnotationStatus",
    "CaseKind",
    "MarketType",
    "OutcomeVerdict",
    "PredictionDirection",
    "PredictionStatus",
    "Provenance",
    "ReviewState",
    "ScreenshotQuality",
]
