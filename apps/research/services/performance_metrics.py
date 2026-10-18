# apps/research/services/performance_metrics.py
"""Performance metrics (Step 8)."""

from __future__ import annotations

from typing import Any


class PerformanceMetrics:
    """Calculate strategy performance with sample counts and uncertainty."""

    def compute(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        if not results:
            return {
                "total": 0,
                "accepted": 0,
                "no_trade": 0,
                "directional_accuracy": None,
                "sample_count": 0,
                "uncertainty": {},
            }

        total = len(results)
        accepted = sum(1 for r in results if r.get("decision") in ("up", "down"))
        no_trade = total - accepted
        hits = sum(1 for r in results if r.get("hit") is True)
        directional_accuracy = hits / accepted if accepted > 0 else None

        return {
            "total": total,
            "accepted": accepted,
            "no_trade": no_trade,
            "directional_accuracy": directional_accuracy,
            "hit_count": hits,
            "sample_count": total,
            "uncertainty": {
                "accepted": accepted,
                "note": "Metrics include sample counts; uncertainty intervals computed separately when large samples available",
            },
        }


__all__ = ["PerformanceMetrics"]
