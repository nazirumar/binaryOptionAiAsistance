"""Feed-compatibility assessment, including OTC protection (Steps 3 & 4).

IQ Option OTC instruments quote *proprietary* prices that have no equivalent
real-market feed. A regular MT5 feed must therefore **never** be substituted to
"verify" an OTC screenshot. This module decides whether a compatible reference
feed exists at all.
"""

from __future__ import annotations

from apps.chart_vision.constants import OTCStatus
from apps.market_sync.constants import FeedCompatibilityStatus
from apps.market_sync.services.dto import FeedAssessment, InstrumentMatch


def _screenshot_is_otc(match: InstrumentMatch, metadata_otc_status: str | None) -> bool | None:
    symbol_otc = match.screenshot_is_otc
    metadata_otc: bool | None
    if metadata_otc_status == OTCStatus.OTC:
        metadata_otc = True
    elif metadata_otc_status == OTCStatus.REGULAR:
        metadata_otc = False
    else:
        metadata_otc = None

    # An explicit OTC marker anywhere wins (the safe interpretation).
    if symbol_otc is True or metadata_otc is True:
        return True
    if symbol_otc is False:
        return False
    return metadata_otc


class FeedCompatibilityAssessor:
    """Assesses whether a screenshot can be verified against the MT5 feed."""

    def assess(
        self,
        match: InstrumentMatch,
        *,
        metadata_otc_status: str | None = None,
    ) -> FeedAssessment:
        screenshot_is_otc = _screenshot_is_otc(match, metadata_otc_status)
        reference_is_otc = match.reference_is_otc
        reasons: list[str] = []

        if not match.supported:
            reasons.append("Instrument could not be matched to a usable MT5 mapping.")
            return FeedAssessment(
                compatibility=FeedCompatibilityStatus.UNKNOWN,
                screenshot_is_otc=screenshot_is_otc,
                reference_is_otc=reference_is_otc,
                reasons=tuple(reasons),
                mapping_verified=match.mapping_verified,
            )

        if screenshot_is_otc is True:
            if reference_is_otc is True and match.mapping_verified:
                reasons.append(
                    "Screenshot is OTC and an explicitly-verified OTC reference feed is "
                    "mapped. Prices remain broker-specific and are compared qualitatively only."
                )
                return FeedAssessment(
                    compatibility=FeedCompatibilityStatus.COMPATIBLE,
                    screenshot_is_otc=True,
                    reference_is_otc=True,
                    reasons=tuple(reasons),
                    evidence={"otc_reference_verified": True},
                    mapping_verified=True,
                )
            reasons.append(
                "The screenshot is an OTC instrument. Ordinary MT5 data cannot verify OTC "
                "prices, and no independently-verified compatible reference feed is mapped. "
                "Regular forex prices are not substituted."
            )
            return FeedAssessment(
                compatibility=FeedCompatibilityStatus.INCOMPATIBLE_FEED,
                screenshot_is_otc=True,
                reference_is_otc=reference_is_otc,
                reasons=tuple(reasons),
                evidence={"otc_reference_verified": False},
                mapping_verified=match.mapping_verified,
            )

        if reference_is_otc is True:
            reasons.append(
                "The screenshot appears to be a regular-market chart but the mapped MT5 "
                "symbol is flagged OTC; the feeds are not interchangeable."
            )
            return FeedAssessment(
                compatibility=FeedCompatibilityStatus.INCOMPATIBLE_FEED,
                screenshot_is_otc=screenshot_is_otc,
                reference_is_otc=True,
                reasons=tuple(reasons),
                mapping_verified=match.mapping_verified,
            )

        if screenshot_is_otc is None:
            reasons.append(
                "OTC/regular designation could not be confirmed; comparison proceeds against "
                "the regular reference feed with this uncertainty recorded."
            )
            return FeedAssessment(
                compatibility=FeedCompatibilityStatus.UNKNOWN,
                screenshot_is_otc=None,
                reference_is_otc=reference_is_otc,
                reasons=tuple(reasons),
                mapping_verified=match.mapping_verified,
            )

        reasons.append("Both the screenshot and the MT5 reference are regular-market feeds.")
        if not match.mapping_verified:
            reasons.append("The MT5 symbol mapping has not been validated against the broker.")
        return FeedAssessment(
            compatibility=FeedCompatibilityStatus.COMPATIBLE,
            screenshot_is_otc=False,
            reference_is_otc=reference_is_otc,
            reasons=tuple(reasons),
            mapping_verified=match.mapping_verified,
        )


def assess_feed_compatibility(
    match: InstrumentMatch,
    *,
    metadata_otc_status: str | None = None,
) -> FeedAssessment:
    return FeedCompatibilityAssessor().assess(match, metadata_otc_status=metadata_otc_status)


__all__ = ["FeedCompatibilityAssessor", "assess_feed_compatibility"]
