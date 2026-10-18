# apps/price_action/exceptions.py
from __future__ import annotations


class PriceActionError(Exception):
    """Base exception for price-action engine."""

    def __init__(self, message: str, code: str = "price_action_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class InvalidInputError(PriceActionError):
    def __init__(self, message: str, code: str = "invalid_input") -> None:
        super().__init__(message, code)


class MissingInputError(PriceActionError):
    def __init__(self, message: str, code: str = "missing_input") -> None:
        super().__init__(message, code)


class SchemaValidationError(PriceActionError):
    def __init__(self, message: str, code: str = "schema_validation_failed") -> None:
        super().__init__(message, code)


class DetectorError(PriceActionError):
    def __init__(self, message: str, code: str = "detector_error") -> None:
        super().__init__(message, code)
