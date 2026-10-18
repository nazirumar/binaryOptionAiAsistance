"""Book-strategy services: detectors, recognition, mapping, explanation, validation."""

from apps.book_strategies.services.recognition import (
    BookCandidate,
    BookDetection,
    BookStrategyRecognizer,
    build_book_candidates,
)

__all__ = [
    "BookCandidate",
    "BookDetection",
    "BookStrategyRecognizer",
    "build_book_candidates",
]
