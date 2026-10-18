"""Tests for the versioned knowledge catalogue (Step 22)."""

from __future__ import annotations

from apps.price_action.constants import PA_KNOWLEDGE_VERSION
from apps.price_action.knowledge.catalogue import CONCEPTS, catalogue, get_concept


def test_catalogue_has_all_core_concepts():
    keys = {c.key for c in CONCEPTS}
    expected = {
        "market_structure",
        "support_resistance",
        "buyer_seller_failure",
        "candlestick_patterns",
        "candle_sequences",
        "market_cycle",
        "liquidity_sweeps",
        "order_blocks",
        "fair_value_gaps",
        "opening_gaps",
        "volume",
        "market_context",
    }
    assert expected <= keys


def test_every_concept_documents_required_sections():
    for concept in CONCEPTS:
        assert concept.course_interpretation
        assert concept.implementation
        assert concept.required_inputs
        assert concept.detection_logic
        assert concept.limitations


def test_catalogue_is_versioned():
    doc = catalogue()
    assert doc["knowledge_version"] == PA_KNOWLEDGE_VERSION
    assert doc["note"]


def test_get_concept():
    assert get_concept("order_blocks") is not None
    assert get_concept("does-not-exist") is None
