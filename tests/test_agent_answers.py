"""Tests for the agent's fixed-wording outcomes.

TDD: written before scripts/agent.py, scripts/rag_tool.py, and
scripts/graph_tool.py exist - these tests define the contract run_agent()
must satisfy on every path except full success. All should fail with an
ImportError until Phase 3 implements the agent and both tools.

Per docs/spec.md's Agent steps section, both tools and the step 4
language-model call can be swapped out for fakes, so every path here is
exercised without a real search service, real graph, real outage, or a
real, costly, non-deterministic call to the language model. run_agent()
takes the tools/LLM call as keyword-only overrides for exactly this reason.
"""
import pytest

from scripts.agent import run_agent
from scripts.graph_tool import GraphServiceError
from scripts.rag_tool import RAGServiceError
from scripts.schemas import QuestionInput

QUESTION = QuestionInput(
    condition="hypertension",
    lab="SBP",
    comparison="above",
    value=140,
    drug_a="Lisinopril",
    drug_b="Amlodipine",
)


class _CountingFake:
    """Wraps a function and records how many times it was called."""

    def __init__(self, fn):
        self._fn = fn
        self.call_count = 0

    def __call__(self, *args, **kwargs):
        self.call_count += 1
        return self._fn(*args, **kwargs)


def _always_raise(exc):
    def _fn(*args, **kwargs):
        raise exc

    return _fn


def test_nothing_found_short_circuits_to_fixed_fallback_answer():
    search_fn = _CountingFake(
        lambda query_text, top_k=5: {
            "answer": "I don't know — I couldn't find any patient records relevant to that question.",
            "patient_ids": [],
            "retrieved_count": 0,
        }
    )
    count_fn = _CountingFake(lambda patient_ids: pytest.fail("count step must be skipped"))

    answer, count_step_ran = run_agent(QUESTION, search_fn=search_fn, count_fn=count_fn)

    assert search_fn.call_count == 1
    assert count_step_ran is False
    assert answer.answer == (
        "I don't know — I couldn't find any patient records relevant to that question."
    )
    assert answer.rag_patient_ids == []
    assert answer.graph_result == {}
    assert answer.confidence == "low"
    assert answer.caveat == (
        "No patients were found for this question, so the drug count step was skipped."
    )


def test_search_step_broken_after_retries_returns_fixed_error_answer():
    search_fn = _CountingFake(_always_raise(RAGServiceError("connection_error")))
    count_fn = _CountingFake(lambda patient_ids: pytest.fail("count step must be skipped"))

    answer, count_step_ran = run_agent(QUESTION, search_fn=search_fn, count_fn=count_fn)

    # 2 retries => 3 attempts total, per docs/spec.md's Agent steps section.
    assert search_fn.call_count == 3
    assert count_step_ran is False
    assert answer.answer == (
        "I wasn't able to answer this question because the patient search "
        "step could not be completed."
    )
    assert answer.rag_patient_ids == []
    assert answer.graph_result == {}
    assert answer.confidence == "low"
    assert answer.caveat == "The patient search service failed after repeated attempts."


def test_graph_step_broken_after_retries_returns_degraded_answer():
    search_fn = _CountingFake(
        lambda query_text, top_k=5: {
            "answer": "some patients matched",
            "patient_ids": [1, 2, 3],
            "retrieved_count": 3,
        }
    )
    count_fn = _CountingFake(_always_raise(GraphServiceError("ServiceUnavailable")))

    answer, count_step_ran = run_agent(QUESTION, search_fn=search_fn, count_fn=count_fn)

    assert search_fn.call_count == 1
    # 2 retries => 3 attempts total, per docs/spec.md's Agent steps section.
    assert count_fn.call_count == 3
    # The count step was attempted (and failed), not skipped - it "ran".
    assert count_step_ran is True
    assert answer.answer == (
        "Search found matching patients, but the exact drug count could not "
        "be completed."
    )
    assert answer.rag_patient_ids == [1, 2, 3]
    assert answer.graph_result == {}
    assert answer.confidence == "low"
    assert answer.caveat == (
        "The drug count step failed after repeated attempts. This answer is "
        "based on search results only, without an exact count."
    )


def test_answer_step_failed_after_one_retry_returns_fixed_answer():
    search_fn = _CountingFake(
        lambda query_text, top_k=5: {
            "answer": "some patients matched",
            "patient_ids": [1, 2, 3],
            "retrieved_count": 3,
        }
    )
    count_fn = _CountingFake(
        lambda patient_ids: {
            "drug_counts": {"Lisinopril": 2},
            "patients_checked": 3,
        }
    )
    answer_fn = _CountingFake(_always_raise(ValueError("unparseable model output")))

    answer, count_step_ran = run_agent(
        QUESTION, search_fn=search_fn, count_fn=count_fn, answer_fn=answer_fn
    )

    assert search_fn.call_count == 1
    assert count_fn.call_count == 1
    # 1 retry => 2 attempts total, per docs/spec.md's Agent steps section -
    # smaller than the tool retry budget since a retry here is a second,
    # slower, more expensive language-model call.
    assert answer_fn.call_count == 2
    assert count_step_ran is True
    assert answer.answer == (
        "I found matching patients and counted their drugs, but wasn't able "
        "to put together a valid written answer."
    )
    assert answer.rag_patient_ids == [1, 2, 3]
    assert answer.graph_result == {"Lisinopril": 2}
    assert answer.confidence == "low"
    assert answer.caveat == (
        "The final write-up step failed, even after retrying once. The "
        "patient list and drug counts above are accurate; only the summary "
        "sentence is missing."
    )
