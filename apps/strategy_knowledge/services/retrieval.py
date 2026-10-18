"""CP11: retrieve approved strategy knowledge for the reasoning assistant.

The retrieval service selects *stored, reviewed* strategy definitions and
condition lists for a query. It never generates content: everything returned
comes from the database (name, description, conditions, invalidations), and
definitions that are not enabled/approved are excluded unless explicitly asked
for (the dashboard's library view). Experimental definitions are always
labelled so they can never be presented as validated knowledge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Q

from apps.strategy_knowledge.constants import ConditionKind, ValidationStatus
from apps.strategy_knowledge.models import (
    StrategyCondition,
    StrategyDefinition,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "of",
        "on",
        "in",
        "at",
        "to",
        "for",
        "and",
        "or",
        "what",
        "how",
        "does",
        "it",
        "this",
        "that",
        "with",
    }
)

#: Hard cap so a retrieval can never blow up the reasoning context budget.
MAX_DEFINITIONS = 6
MAX_TEXT_CHARS = 1200


@dataclass(slots=True)
class RetrievedStrategy:
    """A definition plus its structured conditions, ready for context assembly."""

    strategy_id: str
    name: str
    category: str
    variant: str
    description: str
    market_context: str
    required_conditions: list[str] = field(default_factory=list)
    optional_confirmations: list[str] = field(default_factory=list)
    contradictory_evidence: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    completion_rules: list[str] = field(default_factory=list)
    validation_status: str = ""
    status_label: str = ""
    course_reference: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "category": self.category,
            "variant": self.variant,
            "description": self.description[:600],
            "market_context": self.market_context[:400],
            "required_conditions": self.required_conditions,
            "optional_confirmations": self.optional_confirmations,
            "contradictory_evidence": self.contradictory_evidence,
            "invalidation_conditions": self.invalidation_conditions,
            "completion_rules": self.completion_rules,
            "validation_status": self.validation_status,
            "status_label": self.status_label,
            "course_reference": self.course_reference,
        }


def _tokens(query: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(str(query).lower()) if t not in _STOPWORDS]


class KnowledgeRetrievalService:
    """Keyword retrieval over the versioned strategy knowledge base."""

    def retrieve(
        self,
        query: str,
        *,
        include_experimental: bool = False,
        limit: int = MAX_DEFINITIONS,
    ) -> list[RetrievedStrategy]:
        """Return the definitions best matching ``query`` (stored data only).

        Approved and reviewed definitions rank above drafts; experimental
        definitions are excluded unless ``include_experimental`` is set, and
        even then carry their explicit status label.
        """
        tokens = _tokens(query)
        qs = StrategyDefinition.objects.filter(enabled=True).select_related("category", "version")
        if not include_experimental:
            qs = qs.filter(
                validation_status__in=(ValidationStatus.APPROVED, ValidationStatus.REVIEWED)
            )
        if tokens:
            matched = Q()
            for token in tokens:
                matched |= (
                    Q(name__icontains=token)
                    | Q(strategy_id__icontains=token)
                    | Q(description__icontains=token)
                    | Q(market_context__icontains=token)
                    | Q(course_reference__icontains=token)
                    | Q(conditions__label__icontains=token)
                )
            qs = qs.filter(matched).distinct()
        status_rank = {
            ValidationStatus.APPROVED: 0,
            ValidationStatus.REVIEWED: 1,
            ValidationStatus.EXPERIMENTAL: 2,
            ValidationStatus.DRAFT: 3,
            ValidationStatus.RETIRED: 4,
        }
        definitions = sorted(
            qs[: limit * 3], key=lambda d: (status_rank.get(d.validation_status, 9), d.name)
        )[:limit]
        return [self._to_retrieved(d) for d in definitions]

    def context_blocks(
        self,
        query: str,
        *,
        include_experimental: bool = False,
    ) -> list[dict[str, Any]]:
        """Compact context entries for the reasoning provider.

        Each block carries an explicit ``source`` marker so the provider can
        cite stored knowledge rather than restate it as its own analysis.
        """
        blocks: list[dict[str, Any]] = []
        for retrieved in self.retrieve(query, include_experimental=include_experimental):
            block = retrieved.as_dict()
            block["source"] = "strategy_knowledge_base"
            blocks.append(block)
        return blocks

    def get(self, strategy_id: str) -> RetrievedStrategy | None:
        definition = (
            StrategyDefinition.objects.filter(strategy_id=strategy_id)
            .select_related("category", "version")
            .first()
        )
        if definition is None:
            return None
        return self._to_retrieved(definition)

    @staticmethod
    def _to_retrieved(definition: StrategyDefinition) -> RetrievedStrategy:
        conditions = StrategyCondition.objects.filter(definition=definition)
        by_kind: dict[str, list[str]] = {kind: [] for kind in ConditionKind.values}
        for condition in conditions:
            by_kind[condition.kind].append(condition.label)
        return RetrievedStrategy(
            strategy_id=definition.strategy_id,
            name=definition.name,
            category=definition.category.name if definition.category_id else "",
            variant=definition.variant,
            description=definition.description,
            market_context=definition.market_context,
            required_conditions=by_kind[ConditionKind.REQUIRED],
            optional_confirmations=by_kind[ConditionKind.OPTIONAL],
            contradictory_evidence=by_kind[ConditionKind.CONTRADICTORY],
            invalidation_conditions=by_kind[ConditionKind.INVALIDATION],
            completion_rules=list(definition.completion_rules or []),
            validation_status=definition.validation_status,
            status_label=definition.status_label,
            course_reference=definition.course_reference,
        )


def json_size(block: dict[str, Any]) -> int:
    """Rough serialized size, used to keep context blocks bounded."""
    return len(str(block))
