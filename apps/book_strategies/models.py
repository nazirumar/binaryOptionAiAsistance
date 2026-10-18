# book_strategies/models.py
"""Persistent book-strategy knowledge and detection records (Phase 13)."""

from __future__ import annotations

from django.db import models

from apps.core.models import TimeStampedModel
from apps.strategy_knowledge.models import StrategyVersion


class BookStrategy(TimeStampedModel):
    """One strategy extracted from the Binary Options Trading Bible.

    Rows are seeded from the immutable catalog in
    ``apps.book_strategies.constants``. A book strategy can influence live
    directional decisions ONLY after ``decision_use_approved`` is set - which
    requires documented validation and explicit human approval. Experimental
    entries stay visible for education and never affect trade decisions.
    """

    number = models.PositiveSmallIntegerField()
    key = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=160)
    chapter = models.CharField(max_length=8)
    pdf_pages = models.CharField(max_length=40)
    market_types = models.JSONField(default=list, blank=True)
    trade_type = models.CharField(max_length=20, blank=True)
    requirements = models.JSONField(default=list, blank=True)
    confirmation_rule = models.TextField(blank=True)
    invalidation_rules = models.JSONField(default=list, blank=True)
    mtg_policy = models.CharField(max_length=200, blank=True)
    ambiguities = models.JSONField(default=list, blank=True)
    contradictions = models.JSONField(default=list, blank=True)
    illustration_evidence = models.TextField(blank=True)
    #: Registered detector ("" = catalogued only, no deterministic detection).
    detector_key = models.CharField(max_length=32, blank=True, default="")
    priority = models.BooleanField(default=False)
    #: Furthest COMPLETED research stage; never skipped or fabricated.
    research_status = models.CharField(
        max_length=32,
        choices=[
            ("extracted", "Extracted from book"),
            ("implemented", "Implemented"),
            ("recognition_tested", "Recognition tested"),
            ("backtested", "Historically backtested"),
            ("oos_validated", "Out-of-sample validated"),
            ("approved", "Approved for decision use"),
        ],
        default="extracted",
    )
    #: Admin switch for whether this strategy appears in recognition runs.
    #: It never enables trading - it only controls recognition participation.
    recognition_enabled = models.BooleanField(default=False)
    #: The ONLY switch that could ever affect directional decisions, and it
    #: must stay False until documented validation + explicit approval.
    decision_use_approved = models.BooleanField(default=False)
    validation_notes = models.TextField(blank=True)
    version = models.ForeignKey(
        StrategyVersion,
        on_delete=models.PROTECT,
        related_name="book_strategies",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("chapter", "number", "key")

    def __str__(self) -> str:
        return f"{self.key} - {self.name}"

    @property
    def status_label(self) -> str:
        """Explicit human label; book entries are never 'approved knowledge'."""
        if self.decision_use_approved:
            return "Approved for decision use"
        return f"Book extraction ({self.get_research_status_display()})"


class BookStrategyDetection(TimeStampedModel):
    """One evaluation of a book strategy against candle/visual evidence.

    ``decision`` is always NO_TRADE and ``probability`` always None: a
    recognised pattern is an observation, never a prediction.
    """

    strategy = models.ForeignKey(
        BookStrategy, on_delete=models.CASCADE, related_name="detections"
    )
    #: Optional link to a screenshot analysis (book candidates from vision).
    analysis = models.ForeignKey(
        "chart_vision.ScreenshotAnalysis",
        on_delete=models.CASCADE,
        related_name="book_detections",
        null=True,
        blank=True,
    )
    state = models.CharField(max_length=32)
    direction = models.CharField(max_length=10, default="neutral")
    observed_evidence = models.JSONField(default=list, blank=True)
    missing_conditions = models.JSONField(default=list, blank=True)
    contradictions = models.JSONField(default=list, blank=True)
    candle_refs = models.JSONField(default=list, blank=True)
    reference_level = models.FloatField(null=True, blank=True)
    level_kind = models.CharField(max_length=60, blank=True)
    stochastic_supported = models.BooleanField(null=True, blank=True)
    data_verification = models.CharField(max_length=32)
    decision = models.CharField(max_length=16, default="NO_TRADE")
    probability = models.FloatField(null=True, blank=True)
    probability_status = models.CharField(
        max_length=40, default="UNAVAILABLE_UNCALIBRATED"
    )
    instrument = models.CharField(max_length=40, blank=True)
    timeframe = models.CharField(max_length=10, blank=True)
    market_type = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.strategy.key} [{self.state}]"
