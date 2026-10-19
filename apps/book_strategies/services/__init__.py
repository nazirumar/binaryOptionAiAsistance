"""Book-strategy services: detectors, recognition, mapping, explanation, validation.

Phase 13 additions: deterministic backtesting, walk-forward validation,
comparison/ranking, recognition-vs-prediction metric separation, gated
settlement evaluation, paper forward-validation and the approval-gated
decision-engine integration.
"""

from apps.book_strategies.services.backtest import (
    BOOK_RUN_KIND,
    COMPARISON_RUN_KIND,
    BookBacktestService,
)
from apps.book_strategies.services.comparison import BookComparisonService
from apps.book_strategies.services.decision_integration import book_strategy_candidates
from apps.book_strategies.services.metrics import (
    RecognitionMetricsReport,
    RecognitionMetricsService,
)
from apps.book_strategies.services.paper_forward import PaperForwardService
from apps.book_strategies.services.recognition import (
    BookCandidate,
    BookDetection,
    BookStrategyRecognizer,
    build_book_candidates,
)
from apps.book_strategies.services.settlement import BookSettlementService
from apps.book_strategies.services.walk_forward import BookWalkForwardService

__all__ = [
    "BOOK_RUN_KIND",
    "COMPARISON_RUN_KIND",
    "BookBacktestService",
    "BookCandidate",
    "BookComparisonService",
    "BookDetection",
    "BookSettlementService",
    "BookStrategyRecognizer",
    "BookWalkForwardService",
    "PaperForwardService",
    "RecognitionMetricsReport",
    "RecognitionMetricsService",
    "book_strategy_candidates",
    "build_book_candidates",
]
