# apps/strategy_engine/exceptions.py
"""Exceptions for the strategy evaluation engine."""

from __future__ import annotations


class StrategyEngineError(Exception):
    """Base exception for strategy engine errors."""


class InvalidStrategyInputError(StrategyEngineError):
    """Raised when strategy input is invalid or incomplete."""


class MissingMarketDataError(StrategyEngineError):
    """Raised when required market data is missing."""


class IncompatibleFeedError(StrategyEngineError):
    """Raised when feed compatibility fails."""


__all__ = [
    "IncompatibleFeedError",
    "InvalidStrategyInputError",
    "MissingMarketDataError",
    "StrategyEngineError",
]
