# apps/research/services/historical_replay.py
"""Point-in-time strategy replay (Step 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.price_action.services.engine import PriceActionEngine
from apps.strategy_engine.services.evaluation_service import EvaluationService


class HistoricalReplay:
    """Event-driven historical replay with no future-data leakage.

    At each evaluation point, only data available at that time is exposed.
    Outcome evaluated only after target interval completes.
    """

    def __init__(
        self,
        price_action_engine: PriceActionEngine | None = None,
        evaluation_service: EvaluationService | None = None,
    ) -> None:
        self.pa_engine = price_action_engine or PriceActionEngine()
        self.eval_service = evaluation_service or EvaluationService()

    def replay(
        self,
        candles: list[dict[str, Any]],
        start_index: int = 20,
        min_history: int = 20,
    ) -> list[dict[str, Any]]:
        """Replay strategy over historical candles.

        Uses only prefix up to current index for each evaluation point.
        Prevents future-data leakage.
        """
        results = []
        for i in range(min_history, len(candles) - 1):
            # Only data up to i (current/last completed)
            history = candles[: i + 1]
            try:
                res = self.eval_service.evaluate(
                    {
                        "instrument": candles[0].get("instrument", ""),
                        "timeframe": candles[0].get("timeframe", "M1"),
                        "candles": history,
                        "data_freshness": "fresh",
                    },
                    now=self._get_time(history[-1]),
                )
                results.append(
                    {
                        "index": i,
                        "signal_time": self._get_time(history[-1]),
                        "decision": res.get("direction"),
                        "strategy_family": res.get("strategy_family"),
                        "reason_codes": res.get("reason_codes", []),
                    }
                )
            except Exception:
                continue  # skip problematic points
        return results

    def _get_time(self, candle: dict[str, Any]) -> datetime | None:
        t = candle.get("open_time") or candle.get("time")
        if isinstance(t, datetime):
            return t
        if isinstance(t, str):
            try:
                return datetime.fromisoformat(t.replace("Z", ""))
            except Exception:
                return None
        return None


__all__ = ["HistoricalReplay"]
