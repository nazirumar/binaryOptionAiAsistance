# book_strategies/services/comparison.py
"""Strategy comparison and research ranking (Phase 13, requirement 5).

The ranking answers one question only: *where should limited research effort
go next?* It is never a performance claim and never an approval.

Ranking rule (recorded verbatim in every report):

* A strategy is **ranked** only when BOTH its chronological validation and
  its walk-forward report are ``sufficient_data`` (>= the minimum-signal
  threshold). Ranked rows are ordered by out-of-sample accuracy minus the
  out-of-sample baseline (point estimate), ties broken by sample size.
* Everything else is **unranked** and listed by key - never ordered by
  accuracy, because below the sample threshold differences are noise.
* ``approved_for_decision_use`` is ``False`` for every row, always: no
  ranking, however good, approves a strategy.

Recognition accuracy is deliberately NOT part of this comparison: the scopes
are different metrics (see ``services/metrics.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.book_strategies.services.validation import DISCLAIMER, METRIC_SCOPE

TIER_CANDIDATE = "candidate_for_further_research"
TIER_BELOW_BASELINE = "ranked_but_below_baseline"
TIER_INSUFFICIENT = "insufficient_evidence_unranked"

RANKING_RULE = (
    "Rank (research order only) is assigned solely to strategies whose "
    "chronological validation AND walk-forward report are both "
    "sufficient_data (>= minimum signals). Ranked rows are ordered by "
    "out-of-sample accuracy minus baseline (point estimate), ties broken by "
    "out-of-sample sample size. Insufficient-data strategies are unranked "
    "and listed by key - never ordered by accuracy - because differences "
    "below the sample threshold are noise. A rank is not approval: "
    "approved_for_decision_use is False for every row."
)


@dataclass(slots=True)
class ComparisonRow:
    strategy_key: str
    name: str
    tier: str
    rank: int | None
    metric_scope: str = METRIC_SCOPE
    sufficient_data: bool = False
    pooled: dict[str, Any] = field(default_factory=dict)
    out_of_sample: dict[str, Any] = field(default_factory=dict)
    walk_forward: dict[str, Any] = field(default_factory=dict)
    beats_baseline: bool | None = None
    oos_margin: float | None = None
    reasons: list[str] = field(default_factory=list)
    approved_for_decision_use: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.strategy_key,
            "name": self.name,
            "tier": self.tier,
            "rank": self.rank,
            "metric_scope": self.metric_scope,
            "sufficient_data": self.sufficient_data,
            "pooled": dict(self.pooled),
            "out_of_sample": dict(self.out_of_sample),
            "walk_forward": dict(self.walk_forward),
            "beats_baseline": self.beats_baseline,
            "oos_margin": self.oos_margin,
            "reasons": list(self.reasons),
            "approved_for_decision_use": False,
        }


@dataclass(slots=True)
class ComparisonReport:
    rows: list[ComparisonRow] = field(default_factory=list)
    ranking_rule: str = RANKING_RULE
    metric_scope: str = METRIC_SCOPE
    settlement_disclaimer: str = DISCLAIMER
    ranked_count: int = 0
    unranked_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": [row.as_dict() for row in self.rows],
            "ranking_rule": self.ranking_rule,
            "metric_scope": self.metric_scope,
            "settlement_disclaimer": self.settlement_disclaimer,
            "ranked_count": self.ranked_count,
            "unranked_count": self.unranked_count,
            "warnings": list(self.warnings),
            "approved_for_decision_use": False,
            "recognition_scope_note": (
                "recognition accuracy is a different metric scope and is not "
                "part of this comparison"
            ),
        }


class BookComparisonService:
    """Compare validation + walk-forward summaries into one honest ranking."""

    def compare(self, entries: list[dict[str, Any]]) -> ComparisonReport:
        """Build a comparison from per-strategy summary entries.

        Each entry: ``{"strategy_key", "name", "validation": <as_dict>,
        "walk_forward": <as_dict|None>}``.
        """
        rows: list[ComparisonRow] = []
        for entry in entries:
            rows.append(self._build_row(entry))

        ranked = [r for r in rows if r.rank is not None]
        unranked = [r for r in rows if r.rank is None]
        # Ranked: margin desc, then sample size desc. Unranked: by key only -
        # never by an accuracy figure the data cannot support.
        ranked.sort(key=lambda r: (-(r.oos_margin or 0.0), -(r.out_of_sample.get("n_signals") or 0)))
        for position, row in enumerate(ranked, start=1):
            row.rank = position
        unranked.sort(key=lambda r: r.strategy_key)

        warnings: list[str] = []
        if unranked:
            warnings.append(
                f"{len(unranked)} of {len(rows)} strategies are UNRANKED "
                "(insufficient data); their figures are shown with sample "
                "sizes but must not be read comparatively"
            )
        if ranked:
            warnings.append(
                "a rank is a research ordering, not a performance claim and "
                "not approval for decision use"
            )
        warnings.append(
            "all figures are next-candle direction from leakage-controlled "
            "replay - not binary-option settlement, not a real-trade win rate"
        )
        return ComparisonReport(
            rows=ranked + unranked,
            ranked_count=len(ranked),
            unranked_count=len(unranked),
            warnings=warnings,
        )

    @staticmethod
    def _build_row(entry: dict[str, Any]) -> ComparisonRow:
        validation = entry.get("validation") or {}
        walk_forward = entry.get("walk_forward") or {}
        splits = validation.get("splits") or {}
        pooled = splits.get("pooled") or {}
        oos = splits.get("out_of_sample") or {}

        reasons: list[str] = []
        validation_sufficient = bool(validation.get("sufficient_data"))
        walk_forward_sufficient = bool(walk_forward.get("sufficient_data")) if walk_forward else False

        if not validation_sufficient:
            reasons.append(validation.get("insufficient_reason") or "chronological validation insufficient")
        if not walk_forward:
            reasons.append("no walk-forward report was run for this strategy")
        elif not walk_forward_sufficient:
            reasons.append(
                walk_forward.get("insufficient_reason") or "walk-forward report insufficient"
            )

        beats_baseline: bool | None = None
        oos_margin: float | None = None
        accuracy = oos.get("accuracy")
        baseline = oos.get("baseline_accuracy")
        if accuracy is not None and baseline is not None:
            oos_margin = round(accuracy - baseline, 6)
            beats_baseline = oos_margin > 0

        sufficient = validation_sufficient and walk_forward_sufficient
        if not sufficient:
            tier = TIER_INSUFFICIENT
            rank: int | None = None
        elif beats_baseline is True:
            rank = 0  # assigned after sorting in compare()
            tier = TIER_CANDIDATE
        elif beats_baseline is False:
            rank = 0  # assigned after sorting in compare()
            tier = TIER_BELOW_BASELINE
            reasons.append(
                "out-of-sample point estimate is at or below the "
                "unconditional baseline of the same window"
            )
        else:
            # Sufficient samples but no computable baseline comparison cannot
            # be ranked: there is nothing to order it by.
            tier = TIER_INSUFFICIENT
            rank = None
            reasons.append("out-of-sample accuracy or baseline not computable")

        return ComparisonRow(
            strategy_key=str(entry.get("strategy_key", "")),
            name=str(entry.get("name", "")),
            tier=tier,
            rank=rank if sufficient else None,
            sufficient_data=sufficient,
            pooled=dict(pooled),
            out_of_sample=dict(oos),
            walk_forward=(
                {
                    "n_signals": (walk_forward.get("pooled") or {}).get("n_signals"),
                    "accuracy": (walk_forward.get("pooled") or {}).get("accuracy"),
                    "wilson_95": (walk_forward.get("pooled") or {}).get("wilson_95"),
                    "baseline_accuracy": (walk_forward.get("pooled") or {}).get("baseline_accuracy"),
                    "folds_scored": (walk_forward.get("pooled") or {}).get("folds_scored"),
                    "sufficient_data": walk_forward.get("sufficient_data"),
                }
                if walk_forward
                else {}
            ),
            beats_baseline=beats_baseline,
            oos_margin=oos_margin,
            reasons=reasons,
        )


__all__ = [
    "RANKING_RULE",
    "TIER_BELOW_BASELINE",
    "TIER_CANDIDATE",
    "TIER_INSUFFICIENT",
    "BookComparisonService",
    "ComparisonReport",
    "ComparisonRow",
]
