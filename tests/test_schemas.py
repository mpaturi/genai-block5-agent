"""Tests for block5_agent/schemas.py - QuestionInput's bounds, and the
query-building/dedupe/confidence functions docs/spec.md requires to live
in exactly one place (see schemas.py's module docstring). None of these
had direct test coverage anywhere in this repo before now - other test
files only exercise them indirectly, through rag_tool.py/agent.py call
sites (checked tests/test_rag_tool.py first to confirm, before adding
tests here that would just duplicate existing coverage).
"""
import pytest
from pydantic import ValidationError

from block5_agent.schemas import (
    QuestionInput,
    _format_value,
    assemble_question_text,
    build_rag_citations,
    build_rag_query,
    compute_confidence,
    dedupe_and_order_patient_ids,
)

_VALID_KWARGS = dict(
    condition="Essential hypertension",
    lab="SBP",
    comparison="above",
    value=140,
    drug_a="Lisinopril",
    drug_b="Amlodipine",
)


def _make_question(**overrides):
    kwargs = dict(_VALID_KWARGS)
    kwargs.update(overrides)
    return QuestionInput(**kwargs)


def test_valid_in_bounds_question_constructs_successfully():
    # Guard against the bounds below being too tight for genuine input.
    question = _make_question()
    assert question.condition == "Essential hypertension"
    assert question.value == 140


def test_condition_over_200_chars_is_rejected():
    with pytest.raises(ValidationError):
        _make_question(condition="x" * 201)


def test_lab_over_100_chars_is_rejected():
    with pytest.raises(ValidationError):
        _make_question(lab="x" * 101)


def test_drug_a_over_100_chars_is_rejected():
    with pytest.raises(ValidationError):
        _make_question(drug_a="x" * 101)


def test_drug_b_over_100_chars_is_rejected():
    with pytest.raises(ValidationError):
        _make_question(drug_b="x" * 101)


def test_value_positive_infinity_is_rejected():
    with pytest.raises(ValidationError):
        _make_question(value=float("inf"))


def test_value_negative_infinity_is_rejected():
    with pytest.raises(ValidationError):
        _make_question(value=float("-inf"))


def test_value_nan_is_rejected():
    with pytest.raises(ValidationError):
        _make_question(value=float("nan"))


def test_value_below_ge_zero_is_rejected():
    with pytest.raises(ValidationError):
        _make_question(value=-1)


def test_value_above_le_ten_thousand_is_rejected():
    with pytest.raises(ValidationError):
        _make_question(value=10_001)


def test_format_value_renders_a_whole_number_without_a_decimal():
    assert _format_value(140) == "140"
    assert _format_value(140.0) == "140"


def test_format_value_renders_a_fractional_number_as_is():
    assert _format_value(7.5) == "7.5"


def test_build_rag_query_uses_condition_lab_comparison_value_only():
    question = _make_question(
        condition="hyperlipidemia", lab="HbA1c", comparison="below", value=7.5
    )
    assert build_rag_query(question) == "patients with hyperlipidemia and HbA1c below 7.5"


def test_build_rag_query_never_includes_drug_names():
    # See docs/spec.md's "Why drug_a/drug_b are left out of the RAG query".
    question = _make_question(drug_a="Metformin", drug_b="Insulin")
    query = build_rag_query(question)
    assert "Metformin" not in query
    assert "Insulin" not in query


def test_assemble_question_text_matches_the_documented_sentence_shape():
    question = _make_question()
    assert assemble_question_text(question) == (
        "Of patients with Essential hypertension and SBP > 140, how many "
        "are on Lisinopril vs. Amlodipine?"
    )


def test_assemble_question_text_uses_the_below_symbol_for_a_below_comparison():
    question = _make_question(comparison="below", value=7.5, lab="HbA1c")
    assert "HbA1c < 7.5" in assemble_question_text(question)


def test_compute_confidence_boundaries():
    # See docs/spec.md's Structured output: <15 low, 15-24 medium, 25 high.
    assert compute_confidence(0) == "low"
    assert compute_confidence(14) == "low"
    assert compute_confidence(15) == "medium"
    assert compute_confidence(24) == "medium"
    assert compute_confidence(25) == "high"


_SOURCES = [
    {"person_id": 5, "chunk_id": "5_chunk0", "score": 0.5, "chunk_text": "Patient 5, chunk 0 text."},
    {"person_id": 2, "chunk_id": "2_chunk0", "score": 0.9, "chunk_text": "Patient 2, chunk 0 text."},
    # A repeat of patient 5 with a higher score - dedupe should keep the
    # higher score, not the first-seen entry.
    {"person_id": 5, "chunk_id": "5_chunk1", "score": 0.7, "chunk_text": "Patient 5, chunk 1 text."},
    # Same score as patient 2 - tie broken by patient ID.
    {"person_id": 1, "chunk_id": "1_chunk0", "score": 0.9, "chunk_text": "Patient 1, chunk 0 text."},
]


def test_dedupe_and_order_patient_ids_dedupes_and_orders_by_score_then_id():
    assert dedupe_and_order_patient_ids(_SOURCES) == [1, 2, 5]


def test_build_rag_citations_uses_the_winning_higher_scored_chunk():
    citations = build_rag_citations(_SOURCES)
    assert citations == [
        {"patient_id": 1, "chunk_id": "1_chunk0", "snippet": "Patient 1, chunk 0 text."},
        {"patient_id": 2, "chunk_id": "2_chunk0", "snippet": "Patient 2, chunk 0 text."},
        {"patient_id": 5, "chunk_id": "5_chunk1", "snippet": "Patient 5, chunk 1 text."},
    ]
