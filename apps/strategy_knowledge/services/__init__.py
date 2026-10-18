# apps/strategy_knowledge/services/__init__.py
"""Services for the strategy knowledge base (CP8-CP11, CP14, CP15)."""

from __future__ import annotations

from apps.strategy_knowledge.services.candidate_mapper import (
    StrategyCandidate,
    build_candidates,
)
from apps.strategy_knowledge.services.dataset import (
    DatasetWorkflowError,
    StrategyDatasetWorkflow,
)
from apps.strategy_knowledge.services.dedup import dedupe_candidates
from apps.strategy_knowledge.services.metrics import DetectionMetricsService
from apps.strategy_knowledge.services.pattern_verification import (
    PatternVerificationService,
)
from apps.strategy_knowledge.services.recognition import MultiStrategyRecognitionService
from apps.strategy_knowledge.services.retrieval import KnowledgeRetrievalService

__all__ = [
    "DatasetWorkflowError",
    "DetectionMetricsService",
    "KnowledgeRetrievalService",
    "MultiStrategyRecognitionService",
    "PatternVerificationService",
    "StrategyCandidate",
    "StrategyDatasetWorkflow",
    "build_candidates",
    "dedupe_candidates",
]
