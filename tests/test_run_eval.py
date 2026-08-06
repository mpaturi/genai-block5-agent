"""Tests for run_eval.py's answer-accuracy scoring logic.

RAG's top_k=25 ceiling structurally caps q1's true 99-patient population
(see docs/spec.md's Important honesty point), so q1 is deliberately
scored against answer_key.json's "q1_expected_capped" entry instead of
its own "q1" entry, which holds the true, full population for reference
only (see build_eval_answer_key.py's module docstring). These tests
confirm _check_answer_accuracy() actually reads from "q1_expected_capped"
for q1 - not just that it happens to pass today, but that it would catch
a real regression in the capped values specifically.
"""
from types import SimpleNamespace

from block5_agent.run_eval import _check_answer_accuracy

_Q1_TASK = {"id": "q1", "answerable": True}
_Q2_TASK = {"id": "q2", "answerable": True}

# Deliberately different from q1_expected_capped below - if
# _check_answer_accuracy ever reads this entry for q1 instead, every
# assertion here would flip.
_Q1_FULL_ENTRY = {
    "rag_patient_ids": list(range(1, 100)),
    "graph_result": {"Lisinopril": 49, "Amlodipine": 28, "Hydrochlorothiazide": 11},
    "patients_checked": 99,
    "confidence": "high",
}
_Q1_CAPPED_ENTRY = {
    "rag_patient_ids": [7253, 8737, 6700],
    "graph_result": {"Amlodipine": 8, "Lisinopril": 10, "Hydrochlorothiazide": 11},
    "patients_checked": 3,
    "confidence": "low",
}


def _answer(rag_patient_ids, graph_result, confidence):
    return SimpleNamespace(
        rag_patient_ids=rag_patient_ids, graph_result=graph_result, confidence=confidence
    )


def test_q1_passes_when_it_matches_the_capped_entry_not_the_full_entry():
    answer_key = {"q1": _Q1_FULL_ENTRY, "q1_expected_capped": _Q1_CAPPED_ENTRY}
    # Matches q1_expected_capped exactly; matches q1's full entry on
    # nothing (different patient list, different counts, different
    # confidence) - only passes if the check reads the capped entry.
    answer = _answer(
        rag_patient_ids=[7253, 8737, 6700],
        graph_result={"Amlodipine": 8, "Lisinopril": 10, "Hydrochlorothiazide": 11},
        confidence="low",
    )

    result = _check_answer_accuracy(_Q1_TASK, answer, answer_key["q1"], answer_key)

    assert result is True


def test_q1_fails_when_capped_values_regress():
    # A real regression: the drug count comes back wrong. This must be
    # caught, not silently pass - proving the check actually exercises
    # the capped entry's values, not just its presence.
    answer_key = {"q1": _Q1_FULL_ENTRY, "q1_expected_capped": _Q1_CAPPED_ENTRY}
    answer = _answer(
        rag_patient_ids=[7253, 8737, 6700],
        graph_result={"Amlodipine": 9, "Lisinopril": 10, "Hydrochlorothiazide": 11},
        confidence="low",
    )

    result = _check_answer_accuracy(_Q1_TASK, answer, answer_key["q1"], answer_key)

    assert result is False


def test_q1_fails_when_it_matches_the_full_entry_instead_of_the_capped_one():
    # If the agent (impossibly, since RAG is capped at 25) produced the
    # true 99-patient answer, that must still fail q1's check, since q1 is
    # scored against the achievable capped answer, not the full one.
    answer_key = {"q1": _Q1_FULL_ENTRY, "q1_expected_capped": _Q1_CAPPED_ENTRY}
    answer = _answer(
        rag_patient_ids=list(range(1, 100)),
        graph_result={"Lisinopril": 49, "Amlodipine": 28, "Hydrochlorothiazide": 11},
        confidence="high",
    )

    result = _check_answer_accuracy(_Q1_TASK, answer, answer_key["q1"], answer_key)

    assert result is False


def test_other_questions_are_unaffected_and_read_their_own_golden_entry():
    golden = {
        "rag_patient_ids": [10328, 2116],
        "graph_result": {"Alendronic acid": 2},
        "confidence": "low",
    }
    answer_key = {"q2": golden}
    answer = _answer(
        rag_patient_ids=[10328, 2116], graph_result={"Alendronic acid": 2}, confidence="low"
    )

    result = _check_answer_accuracy(_Q2_TASK, answer, golden, answer_key)

    assert result is True
