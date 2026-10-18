# apps/trading_journal/forms.py
"""Dashboard forms for manual journal entry (Phase 9, Step 8)."""

from __future__ import annotations

from django import forms

from apps.trading_journal.models import JournalTrade


class JournalTradeForm(forms.ModelForm):
    """Create/edit a journal entry from the dashboard.

    The form intentionally exposes ``trade_type`` prominently: a hypothetical or
    backtested record must be labelled as such and can never masquerade as real.
    """

    class Meta:
        model = JournalTrade
        fields = (
            "trade_type",
            "instrument",
            "market_type",
            "direction",
            "strategy_family",
            "entry_timestamp",
            "expiration_timestamp",
            "entry_quote",
            "settlement_quote",
            "stake",
            "payout_percent",
            "result",
            "notes",
            "emotional_state",
            "mistakes",
            "lessons_learned",
        )
        widgets = {
            "entry_timestamp": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "expiration_timestamp": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "mistakes": forms.Textarea(attrs={"rows": 2}),
            "lessons_learned": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.fields["entry_timestamp"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        self.fields["expiration_timestamp"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
        ]
        base = (
            "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm "
            "text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none "
            "focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 "
            "dark:text-slate-100"
        )
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} {base}".strip()

    def clean(self):  # type: ignore[no-untyped-def]
        cleaned = super().clean()
        entry = cleaned.get("entry_timestamp")
        expiry = cleaned.get("expiration_timestamp")
        if entry and expiry and expiry < entry:
            self.add_error("expiration_timestamp", "Expiration must be at or after entry.")
        return cleaned
