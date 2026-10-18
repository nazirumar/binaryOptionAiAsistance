# apps/research/services/model_registry.py
"""Model registry (Step 14)."""

from __future__ import annotations

from apps.research.models import CalibratedModel


class ModelRegistry:
    """Versioned model registry; never silently replace models. Supports rollback."""

    def register_model(
        self,
        name: str,
        version: str,
        owner=None,
        **kwargs,
    ) -> CalibratedModel:
        model, _created = CalibratedModel.objects.update_or_create(
            name=name,
            version=version,
            defaults={
                "owner": owner,
                "is_active": kwargs.get("is_active", False),
                "is_approved": kwargs.get("is_approved", False),
                "feature_schema": kwargs.get("feature_schema", {}),
                "evaluation_metrics": kwargs.get("evaluation_metrics", {}),
                "brier_score": kwargs.get("brier_score"),
                "calibration_error": kwargs.get("calibration_error"),
                "calibration_method": kwargs.get("calibration_method", ""),
                "model_data": kwargs.get("model_data", {}),
            },
        )
        return model

    def activate(self, name: str, version: str) -> bool:
        # Deactivate others
        CalibratedModel.objects.filter(name=name, is_active=True).update(is_active=False)
        updated = CalibratedModel.objects.filter(name=name, version=version).update(is_active=True)
        return updated > 0

    def rollback(self, name: str, version: str) -> bool:
        return self.activate(name, version)


__all__ = ["ModelRegistry"]
