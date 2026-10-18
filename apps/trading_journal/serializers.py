# apps/trading_journal/serializers.py
"""Serializers for the trading journal (Phase 9)."""

from __future__ import annotations

from rest_framework import serializers

from apps.trading_journal.models import JournalTrade


class JournalTradeSerializer(serializers.ModelSerializer):
    """Read/write serializer for a journal entry.

    ``owner`` is never client-writable; it is assigned from the request user.
    """

    trade_type_display = serializers.CharField(source="get_trade_type_display", read_only=True)
    direction_display = serializers.CharField(source="get_direction_display", read_only=True)
    result_display = serializers.CharField(source="get_result_display", read_only=True)
    is_settled = serializers.BooleanField(read_only=True)

    class Meta:
        model = JournalTrade
        fields = [
            "id",
            "trade_type",
            "trade_type_display",
            "instrument",
            "market_type",
            "direction",
            "direction_display",
            "strategy_family",
            "entry_timestamp",
            "expiration_timestamp",
            "entry_quote",
            "settlement_quote",
            "stake",
            "payout_percent",
            "result",
            "result_display",
            "profit_loss",
            "is_settled",
            "screenshot",
            "analysis",
            "strategy_evaluation",
            "notes",
            "emotional_state",
            "mistakes",
            "lessons_learned",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "profit_loss", "created_at", "updated_at"]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        entry = attrs.get("entry_timestamp") or getattr(self.instance, "entry_timestamp", None)
        expiry = attrs.get("expiration_timestamp") or getattr(
            self.instance, "expiration_timestamp", None
        )
        if entry and expiry and expiry < entry:
            raise serializers.ValidationError(
                {"expiration_timestamp": "Expiration must be at or after entry."}
            )
        return attrs

    def _assert_owned(self, value):  # type: ignore[no-untyped-def]
        """Reject linking to another user's evidence."""
        request = self.context.get("request")
        if value is None or request is None:
            return value
        owner = getattr(value, "owner", None)
        if owner is not None and owner != request.user:
            raise serializers.ValidationError("Cannot link to another user's record.")
        return value

    def validate_screenshot(self, value):  # type: ignore[no-untyped-def]
        return self._assert_owned(value)

    def validate_analysis(self, value):  # type: ignore[no-untyped-def]
        """Reject linking to another user's screenshot analysis (IDOR)."""
        return self._assert_owned(value)

    def validate_strategy_evaluation(self, value):  # type: ignore[no-untyped-def]
        return self._assert_owned(value)
