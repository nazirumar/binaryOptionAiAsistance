# apps/research/services/binary_settlement.py
"""Binary settlement simulator (Step 7)."""

from __future__ import annotations

from typing import Any


class PayoutEngine:
    def compute_payout(self, stake: float, payout_percent: float, won: bool) -> dict[str, float]:
        if won:
            return {
                "stake": stake,
                "payout": stake * (1 + payout_percent / 100.0),
                "net": stake * payout_percent / 100.0,
            }
        return {"stake": stake, "payout": 0.0, "net": -stake}


class BinarySettlement:
    """Binary option settlement.

    If target-platform settlement data unavailable, mark as UNVERIFIABLE.
    Never substitute MT5 prices silently.
    """

    def evaluate_settlement(
        self,
        direction: str,  # CALL/PUT
        entry_quote: float | None = None,
        settlement_quote: float | None = None,
        stake: float = 1.0,
        payout_percent: float = 80.0,
        price_source: str = "unknown",
    ) -> dict[str, Any]:
        if settlement_quote is None or entry_quote is None:
            return {
                "verifiable": False,
                "status": "UNVERIFIABLE",
                "reason": "Missing target-platform entry/settlement prices; no silent MT5 substitution",
                "win": False,
                "tie": False,
            }

        if settlement_quote == entry_quote:
            return {
                "verifiable": True,
                "status": "TIE",
                "win": False,
                "tie": True,
                "price_source": price_source,
            }

        won = False
        if direction.upper() == "CALL" and settlement_quote > entry_quote:
            won = True
        if direction.upper() == "PUT" and settlement_quote < entry_quote:
            won = True

        payout = PayoutEngine().compute_payout(stake, payout_percent, won)
        return {
            "verifiable": True,
            "status": "WIN" if won else "LOSS",
            "win": won,
            "tie": False,
            "price_source": price_source,
            "entry": entry_quote,
            "settlement": settlement_quote,
            **payout,
        }


__all__ = ["BinarySettlement", "PayoutEngine"]
