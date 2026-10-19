# book_strategies/services/settlement.py
"""Binary-option expiry/payout evaluation, gated on settlement data (requirement 7).

Next-candle direction is NOT settlement, so settlement is only ever computed
when the caller supplies actual platform entry + expiry quotes:

* no quotes -> ``UNVERIFIABLE`` (the research engine's policy; MT5 candle
  closes are never silently substituted as expiry prices);
* OTC predictions refuse regular/MT5 price sources outright
  (``INCOMPATIBLE_FEEDS``) - OTC platforms settle on their own quotes;
* only verified WIN/LOSS/TIE outcomes enter ``summarize``, which reports the
  excluded/unverifiable counts next to any win rate and labels the scope
  ``binary_settlement`` distinctly from ``next_candle_direction``.
"""

from __future__ import annotations

from typing import Any

from apps.book_strategies.services.validation import DEFAULT_MIN_SIGNALS, wilson_interval
from apps.research.services.binary_settlement import BinarySettlement

SETTLEMENT_METRIC_SCOPE = "binary_settlement"

STATUS_NOT_EVALUATED = "not_evaluated"
STATUS_UNVERIFIABLE = "unverifiable"
STATUS_REFUSED = "refused"
STATUS_WIN = "win"
STATUS_LOSS = "loss"
STATUS_TIE = "tie"

#: Price sources that are broker-feed (MT5) prices, not platform settlement.
MT5_SOURCES = ("mt5", "mt5_candle", "candles", "candle", "market_data")

QUOTE_REQUIRED_REASON = (
    "entry and expiry settlement quotes from the trading platform are "
    "required; without them settlement is UNVERIFIABLE and no win rate is "
    "computed (MT5 candle closes are not substituted for platform expiry)"
)

OTC_REFUSAL_REASON = (
    "OTC market predictions must settle on OTC-platform quotes; a regular "
    "or MT5 price source is INCOMPATIBLE_FEEDS and is refused, not coerced"
)


class BookSettlementService:
    """Evaluate one settled (or un-settleable) book prediction."""

    def __init__(self) -> None:
        self._engine = BinarySettlement()

    def evaluate(
        self,
        *,
        direction: str,
        entry_quote: float | None = None,
        settlement_quote: float | None = None,
        price_source: str = "",
        market_type: str = "regular",
        stake: float = 1.0,
        payout_rate: float = 80.0,
        expiry_time: str = "",
    ) -> dict[str, Any]:
        """Return an explicit settlement record (win/loss/tie/unverifiable/refused)."""
        if direction not in ("bullish", "bearish"):
            return {
                "status": STATUS_NOT_EVALUATED,
                "verifiable": False,
                "reason": f"unsupported direction {direction!r}",
            }

        source = (price_source or "").strip().lower()
        if market_type == "otc" and (not source or source in MT5_SOURCES or source.startswith("mt5")):
            return {
                "status": STATUS_REFUSED,
                "verifiable": False,
                "reason_code": "INCOMPATIBLE_FEEDS",
                "reason": OTC_REFUSAL_REASON,
                "price_source": price_source,
                "market_type": market_type,
                "metric_scope": SETTLEMENT_METRIC_SCOPE,
            }

        side = "CALL" if direction == "bullish" else "PUT"
        raw = self._engine.evaluate_settlement(
            side,
            entry_quote=entry_quote,
            settlement_quote=settlement_quote,
            stake=stake,
            payout_percent=payout_rate,
            price_source=price_source or "unknown",
        )
        status = str(raw.get("status", "")).lower()
        record: dict[str, Any] = {
            "status": status if raw.get("verifiable") else (
                STATUS_UNVERIFIABLE if status == "unverifiable" else status
            ),
            "verifiable": bool(raw.get("verifiable")),
            "metric_scope": SETTLEMENT_METRIC_SCOPE,
            "price_source": price_source,
            "market_type": market_type,
            "direction": direction,
            "expiry_time": expiry_time,
            "payout_rate_assumption": payout_rate if raw.get("verifiable") else None,
        }
        if not raw.get("verifiable"):
            record["reason"] = raw.get("reason") or QUOTE_REQUIRED_REASON
            return record
        record.update(
            {
                "win": raw.get("win"),
                "tie": raw.get("tie"),
                "entry": raw.get("entry", entry_quote),
                "settlement": raw.get("settlement", settlement_quote),
                "stake": raw.get("stake", stake),
                "payout": raw.get("payout"),
                "net": raw.get("net"),
                "note": (
                    "settled from platform quotes supplied by the caller; "
                    "next-candle accuracy and settlement are different scopes"
                ),
            }
        )
        return record

    @staticmethod
    def summarize(
        records: list[dict[str, Any]], *, min_signals: int = DEFAULT_MIN_SIGNALS
    ) -> dict[str, Any]:
        """Aggregate settlement records without hiding what could not be verified."""
        verifiable = [r for r in records if r.get("verifiable")]
        wins = sum(1 for r in verifiable if r.get("status") == STATUS_WIN)
        losses = sum(1 for r in verifiable if r.get("status") == STATUS_LOSS)
        ties = sum(1 for r in verifiable if r.get("status") == STATUS_TIE)
        unverifiable = sum(1 for r in records if r.get("status") == STATUS_UNVERIFIABLE)
        refused = sum(1 for r in records if r.get("status") == STATUS_REFUSED)
        not_evaluated = sum(1 for r in records if r.get("status") == STATUS_NOT_EVALUATED)

        decided = wins + losses
        win_rate = (wins / decided) if decided else None
        lo, hi = wilson_interval(wins, decided)
        return {
            "metric_scope": SETTLEMENT_METRIC_SCOPE,
            "records": len(records),
            "verifiable": len(verifiable),
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_rate": win_rate,
            "wilson_95": [lo, hi],
            "sufficient_data": decided >= min_signals,
            "insufficient_reason": (
                None
                if decided >= min_signals
                else f"only {decided} settled win/loss records; below the "
                f"{min_signals}-record threshold for settlement claims"
            ),
            "unverifiable": unverifiable,
            "refused": refused,
            "not_evaluated": not_evaluated,
            "overall_status": (
                "UNVERIFIABLE"
                if not verifiable
                else ("PARTIAL" if (unverifiable or refused or not_evaluated) else "FULL")
            ),
            "warning": (
                "only platform-verified settlements are counted; unverifiable, "
                "refused and not-evaluated records are reported separately and "
                "never counted as wins"
            ),
            "approved_for_decision_use": False,
        }


__all__ = [
    "SETTLEMENT_METRIC_SCOPE",
    "STATUS_LOSS",
    "STATUS_NOT_EVALUATED",
    "STATUS_REFUSED",
    "STATUS_TIE",
    "STATUS_UNVERIFIABLE",
    "STATUS_WIN",
    "BookSettlementService",
]
