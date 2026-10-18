# tests/test_phase11_probability.py
"""Phase 11 CP6 — strict probability validation.

Only an approved, calibrated, sample-sufficient, compatible model may supply
a probability; every other path must return the exact unavailable message.
"""

from __future__ import annotations

import math

import pytest

from apps.ai_assistant.services.probability_presenter import (
    BINARY_SETTLEMENT,
    MIN_EVALUATION_SAMPLES,
    NEXT_CANDLE_DIRECTIONAL,
    PROBABILITY_UNAVAILABLE_MESSAGE,
    ProbabilityPresenter,
)

pytestmark = pytest.mark.django_db


def _valid_model(**overrides) -> dict:
    model = {
        "name": "direction-v1",
        "version": "m1",
        "is_approved": True,
        "prediction_target": NEXT_CANDLE_DIRECTIONAL,
        "probability": 0.63,
        "brier_score": 0.21,
        "calibration_error": 0.08,
        "calibration_method": "isotonic",
        "evaluation_metrics": {"sample_count": 120},
        "instrument": "EURUSD",
        "timeframe": "M1",
    }
    model.update(overrides)
    return model


class TestValidModelPasses:
    def test_complete_model_is_presented(self):
        result = ProbabilityPresenter().present(_valid_model())
        assert result["available"] is True
        assert result["value"] == 0.63
        assert result["probability_type"] == NEXT_CANDLE_DIRECTIONAL
        assert result["evaluation_sample_count"] == 120

    def test_perfect_brier_score_of_zero_is_valid(self):
        # Regression: the old truthy check rejected a valid brier_score of 0.0.
        result = ProbabilityPresenter().present(_valid_model(brier_score=0.0))
        assert result["available"] is True

    def test_binary_settlement_target_is_distinct_and_allowed(self):
        result = ProbabilityPresenter().present(_valid_model(prediction_target=BINARY_SETTLEMENT))
        assert result["available"] is True
        assert result["probability_type"] == BINARY_SETTLEMENT


class TestRejections:
    def test_missing_model(self):
        result = ProbabilityPresenter().present(None)
        assert result["available"] is False
        assert result["message"] == PROBABILITY_UNAVAILABLE_MESSAGE

    @pytest.mark.parametrize(
        "bad", [float("nan"), float("inf"), float("-inf"), -0.1, 1.5, 0.0, 1.0, "0.6", None]
    )
    def test_invalid_probability_values(self, bad):
        result = ProbabilityPresenter().present(_valid_model(probability=bad))
        assert result["available"] is False
        assert result["message"] == PROBABILITY_UNAVAILABLE_MESSAGE
        assert result["reason"] == "invalid_probability_value"

    def test_missing_probability(self):
        model = _valid_model()
        del model["probability"]
        result = ProbabilityPresenter().present(model)
        assert result["reason"] == "invalid_probability_value"

    def test_unapproved_model(self):
        result = ProbabilityPresenter().present(_valid_model(is_approved=False))
        assert result["reason"] == "model_not_approved"

    def test_truthy_string_approval_is_not_approval(self):
        result = ProbabilityPresenter().present(_valid_model(is_approved="true"))
        assert result["reason"] == "model_not_approved"

    def test_unsupported_target(self):
        result = ProbabilityPresenter().present(_valid_model(prediction_target="confluence_score"))
        assert result["reason"] == "unsupported_prediction_target"

    def test_missing_version(self):
        result = ProbabilityPresenter().present(_valid_model(version=""))
        assert result["reason"] == "missing_model_version"

    @pytest.mark.parametrize("brier", [None, -0.1, 1.2, float("nan"), "0.2"])
    def test_invalid_brier_score(self, brier):
        result = ProbabilityPresenter().present(_valid_model(brier_score=brier))
        assert result["reason"] == "invalid_brier_score"

    @pytest.mark.parametrize("err", [None, -0.05, 2.0, float("inf")])
    def test_invalid_calibration_error(self, err):
        result = ProbabilityPresenter().present(_valid_model(calibration_error=err))
        assert result["reason"] == "invalid_calibration_error"

    def test_missing_calibration_method(self):
        result = ProbabilityPresenter().present(_valid_model(calibration_method=""))
        assert result["reason"] == "missing_calibration_method"

    def test_missing_sample_size(self):
        result = ProbabilityPresenter().present(
            _valid_model(evaluation_metrics={"brier_score": 0.21})
        )
        assert result["reason"] == "missing_evaluation_sample_size"

    def test_insufficient_sample_size(self):
        result = ProbabilityPresenter().present(
            _valid_model(evaluation_metrics={"sample_count": MIN_EVALUATION_SAMPLES - 1})
        )
        assert result["reason"] == "insufficient_evaluation_samples"

    def test_incompatible_instrument(self):
        result = ProbabilityPresenter().present(
            _valid_model(), context={"instrument": "GBPUSD", "timeframe": "M1"}
        )
        assert result["reason"] == "incompatible_instrument"

    def test_incompatible_timeframe(self):
        result = ProbabilityPresenter().present(
            _valid_model(), context={"instrument": "EURUSD", "timeframe": "M5"}
        )
        assert result["reason"] == "incompatible_timeframe"

    def test_incompatible_prediction_target(self):
        result = ProbabilityPresenter().present(
            _valid_model(),
            context={
                "instrument": "EURUSD",
                "timeframe": "M1",
                "prediction_target": BINARY_SETTLEMENT,
            },
        )
        assert result["reason"] == "incompatible_prediction_target"

    def test_every_rejection_keeps_the_exact_message(self):
        presenter = ProbabilityPresenter()
        for kwargs in (
            {"probability": 1.2},
            {"is_approved": False},
            {"calibration_method": ""},
            {"evaluation_metrics": {"sample_count": 1}},
        ):
            result = presenter.present(_valid_model(**kwargs))
            assert result["message"] == PROBABILITY_UNAVAILABLE_MESSAGE


class TestTypeDistinction:
    def test_confluence_score_is_never_a_probability(self):
        result = ProbabilityPresenter().from_confluence_score(0.9)
        assert result["available"] is False
        assert result["reason"] == "confluence_score_is_not_a_probability"
        assert result["message"] == PROBABILITY_UNAVAILABLE_MESSAGE
        assert "value" not in result

    def test_directional_and_settlement_are_not_interchangeable(self):
        presenter = ProbabilityPresenter()
        directional = presenter.present(_valid_model())
        settlement = presenter.present(_valid_model(prediction_target=BINARY_SETTLEMENT))
        assert directional["probability_type"] != settlement["probability_type"]

    def test_from_calibrated_model_row(self):
        from django.contrib.auth import get_user_model

        from apps.research.models import CalibratedModel

        user = get_user_model().objects.create_user(username="cp6-model-user")
        row = CalibratedModel.objects.create(
            owner=user,
            name="direction-v1",
            version="m1",
            is_approved=True,
            brier_score=0.19,
            calibration_error=0.06,
            calibration_method="isotonic",
            evaluation_metrics={"sample_count": 90, "prediction_target": NEXT_CANDLE_DIRECTIONAL},
            model_data={"probability": 0.58, "instrument": "EURUSD", "timeframe": "M1"},
        )
        result = ProbabilityPresenter().from_calibrated_model(
            row, context={"instrument": "EURUSD", "timeframe": "M1"}
        )
        assert result["available"] is True
        assert result["value"] == 0.58
        assert not math.isnan(result["brier_score"])
