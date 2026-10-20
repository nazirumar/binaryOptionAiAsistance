"""Admin registration for book strategies.

``decision_use_approved`` is intentionally NOT exposed as a casual checkbox:
approval requires documented validation and explicit user authorization, so it
is only settable through a deliberate change here (never by seed/imports).

Approval is available as an explicit, audited admin **action** that refuses to
run unless the strategy has reached ``oos_validated`` (or is already approved)
and the operator supplies the validation evidence as a written justification.
A companion action revokes approval. Nothing here can be triggered in bulk
without a human deliberately selecting rows and typing the justification.
"""

from django.contrib import admin, messages

from apps.book_strategies.models import (
    BookStrategy,
    BookStrategyDetection,
    PaperForwardPrediction,
)
from apps.book_strategies.services.validation import DEFAULT_MIN_SIGNALS

#: Research stages from which explicit approval may be granted. Anything
#: earlier must still complete the documented pipeline first.
_APPROVABLE_STATUSES = ("oos_validated", "approved")


@admin.register(BookStrategy)
class BookStrategyAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "number",
        "name",
        "chapter",
        "research_status",
        "recognition_enabled",
        "decision_use_approved",
    )
    list_filter = ("research_status", "recognition_enabled", "decision_use_approved")
    search_fields = ("key", "name")
    readonly_fields = ("created_at", "updated_at")
    actions = ("approve_for_decision_use", "revoke_decision_use_approval")

    @admin.action(description="Approve for decision use (requires justification)")
    def approve_for_decision_use(self, request, queryset):
        """Explicit human approval, refused unless the pipeline is complete.

        The operator must supply the validation evidence (accuracy, Wilson
        interval, sample size, OOS result) as a written justification; it is
        stored on each row's ``validation_notes`` and is the only record of
        why approval was granted.
        """
        from django.shortcuts import render

        if "apply" in request.POST:
            justification = (request.POST.get("justification") or "").strip()
            if len(justification) < 20:
                self.message_user(
                    request,
                    "Approval refused: provide the validation evidence "
                    "(accuracy, Wilson interval, sample size and out-of-sample "
                    "result) — at least 20 characters.",
                    messages.ERROR,
                )
                return None
            approved = 0
            refused: list[str] = []
            for strategy in queryset:
                if not strategy.detector_key:
                    refused.append(f"{strategy.key} (no detector)")
                    continue
                if strategy.research_status not in _APPROVABLE_STATUSES:
                    refused.append(
                        f"{strategy.key} (status={strategy.research_status}, "
                        "needs oos_validated)"
                    )
                    continue
                strategy.decision_use_approved = True
                strategy.research_status = "approved"
                strategy.validation_notes = justification
                strategy.save(
                    update_fields=[
                        "decision_use_approved",
                        "research_status",
                        "validation_notes",
                        "updated_at",
                    ]
                )
                approved += 1
            if approved:
                self.message_user(
                    request,
                    f"Approved {approved} strateg{'y' if approved == 1 else 'ies'} "
                    "for decision use. Probability remains uncalibrated and the "
                    "engine's NO TRADE safeguards still apply.",
                    messages.WARNING,
                )
            if refused:
                self.message_user(
                    request,
                    "Not approved — " + "; ".join(refused),
                    messages.ERROR,
                )
            return None

        context = {
            **self.admin_site.each_context(request),
            "title": "Approve book strategies for decision use",
            "queryset": queryset,
            "approvable": sorted(_APPROVABLE_STATUSES),
            "min_signals": DEFAULT_MIN_SIGNALS,
            "opts": self.model._meta,
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
        }
        return render(request, "admin/book_strategies/approve.html", context)

    @admin.action(description="Revoke decision-use approval")
    def revoke_decision_use_approval(self, request, queryset):
        revoked = 0
        skipped = 0
        for strategy in queryset:
            if not strategy.decision_use_approved:
                skipped += 1
                continue
            strategy.decision_use_approved = False
            # Approval is what "approved" stage means; step back to the last
            # completed research stage so the record never overstates progress.
            if strategy.research_status == "approved":
                strategy.research_status = "oos_validated"
            strategy.save(
                update_fields=[
                    "decision_use_approved",
                    "research_status",
                    "updated_at",
                ]
            )
            revoked += 1
        if revoked:
            self.message_user(
                request,
                f"Revoked decision-use approval for {revoked} "
                f"strateg{'y' if revoked == 1 else 'ies'}.",
                messages.WARNING,
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} selected row(s) were already unapproved.",
                messages.INFO,
            )


@admin.register(BookStrategyDetection)
class BookStrategyDetectionAdmin(admin.ModelAdmin):
    list_display = ("strategy", "state", "direction", "data_verification", "decision", "created_at")
    list_filter = ("state", "decision")
    search_fields = ("strategy__key",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(PaperForwardPrediction)
class PaperForwardPredictionAdmin(admin.ModelAdmin):
    """Read-mostly view: prediction fields are immutable in the model itself."""

    list_display = (
        "strategy",
        "direction",
        "signal_candle_open_time",
        "status",
        "outcome_correct",
        "settlement_status",
        "created_at",
    )
    list_filter = ("status", "direction", "settlement_status")
    search_fields = ("strategy__key", "instrument")

    def has_add_permission(self, request):
        # Predictions are created by the paper service from live signals -
        # never hand-added after outcomes could be known.
        return False

    # Deliberately NOT editable in bulk: pre-outcome fields are frozen by the
    # model's save() guard and outcomes may only be written through resolve().
    readonly_fields = (
        "strategy",
        "instrument",
        "timeframe",
        "market_type",
        "source",
        "detector_key",
        "direction",
        "signal_candle_open_time",
        "signal_candle_close_time",
        "signal_close_price",
        "prediction_payload",
        "payload_sha256",
        "status",
        "outcome_candle_open_time",
        "outcome_close_price",
        "outcome_up",
        "outcome_correct",
        "outcome_basis",
        "resolved_at",
        "settlement_status",
        "settlement",
        "created_at",
        "updated_at",
    )
