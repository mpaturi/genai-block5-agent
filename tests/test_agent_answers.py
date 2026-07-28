"""Tests for the agent's fixed-wording outcomes.

TDD: written before block5_agent/agent.py, block5_agent/rag_tool.py, and
block5_agent/graph_tool.py exist - these tests define the contract run_agent()
must satisfy on every path except full success. All should fail with an
ImportError until Phase 3 implements the agent and both tools.

Per docs/spec.md's Agent steps section, both tools and the step 4
language-model call can be swapped out for fakes, so every path here is
exercised without a real search service, real graph, real outage, or a
real, costly, non-deterministic call to the language model. run_agent()
takes the tools/LLM call as keyword-only overrides for exactly this reason.

One exception to "every path except full success": the full-success test
below exists only to confirm rag_citations is threaded through
ClinicalAnswer the same way rag_patient_ids already is - it stubs every
step, same as the others, and asserts nothing about the free-text answer
itself.
"""
import pytest

from block5_agent.agent import run_agent
from block5_agent.graph_tool import GraphServiceError
from block5_agent.rag_tool import RAGServiceError
from block5_agent.schemas import QuestionInput, assemble_question_text

QUESTION = QuestionInput(
    condition="hypertension",
    lab="SBP",
    comparison="above",
    value=140,
    drug_a="Lisinopril",
    drug_b="Amlodipine",
)


class _CountingFake:
    """Wraps a function and records how many times it was called, and with
    what arguments - so tests can assert the agent forwards the right
    filter fields, not just that it was called the right number of times.
    """

    def __init__(self, fn):
        self._fn = fn
        self.call_count = 0
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.call_count += 1
        self.calls.append((args, kwargs))
        return self._fn(*args, **kwargs)


def _always_raise(exc):
    def _fn(*args, **kwargs):
        raise exc

    return _fn


def test_nothing_found_short_circuits_to_fixed_fallback_answer():
    search_fn = _CountingFake(
        lambda query_text, condition, lab, comparison, value, top_k=25: {
            "answer": "I don't know — I couldn't find any patient records relevant to that question.",
            "patient_ids": [],
            "citations": [],
            "retrieved_count": 0,
        }
    )
    count_fn = _CountingFake(lambda *args: pytest.fail("count step must be skipped"))

    answer, count_step_ran, cost_info = run_agent(QUESTION, search_fn=search_fn, count_fn=count_fn)

    assert search_fn.call_count == 1
    # The agent forwards top_k=25 (up from 20, Block 4's raised
    # filtered-only ceiling) and the question's condition/lab/comparison/
    # value as structured filter fields, the same pattern already used for
    # the graph tool's count_fn.
    call_args, call_kwargs = search_fn.calls[0]
    assert call_args[1:] == (QUESTION.condition, QUESTION.lab, QUESTION.comparison, QUESTION.value)
    assert call_kwargs == {"top_k": 25}
    assert count_step_ran is False
    assert answer.question == assemble_question_text(QUESTION)
    assert answer.answer == (
        "I don't know — I couldn't find any patient records relevant to that question."
    )
    assert answer.rag_patient_ids == []
    assert answer.rag_citations == []
    assert answer.graph_result == {}
    assert answer.confidence == "low"
    assert answer.caveat == (
        "No patients were found for this question, so the drug count step was skipped."
    )
    assert answer.outcome == "nothing_found"


def test_search_step_broken_after_retries_returns_fixed_error_answer():
    search_fn = _CountingFake(_always_raise(RAGServiceError("connection_error")))
    count_fn = _CountingFake(lambda *args: pytest.fail("count step must be skipped"))

    answer, count_step_ran, cost_info = run_agent(QUESTION, search_fn=search_fn, count_fn=count_fn)

    # 2 retries => 3 attempts total, per docs/spec.md's Agent steps section.
    assert search_fn.call_count == 3
    assert count_step_ran is False
    assert answer.question == assemble_question_text(QUESTION)
    assert answer.answer == (
        "I wasn't able to answer this question because the patient search "
        "step could not be completed."
    )
    assert answer.rag_patient_ids == []
    assert answer.graph_result == {}
    assert answer.confidence == "low"
    assert answer.caveat == "The patient search service failed after repeated attempts."
    assert answer.outcome == "tool_error"


def test_graph_step_broken_after_retries_returns_degraded_answer():
    search_fn = _CountingFake(
        lambda query_text, condition, lab, comparison, value, top_k=25: {
            "answer": "some patients matched",
            "patient_ids": [1, 2, 3],
            "citations": [
                {"patient_id": 1, "chunk_id": "1_chunk0", "snippet": "Patient 1 text."},
                {"patient_id": 2, "chunk_id": "2_chunk0", "snippet": "Patient 2 text."},
                {"patient_id": 3, "chunk_id": "3_chunk0", "snippet": "Patient 3 text."},
            ],
            "retrieved_count": 3,
        }
    )
    count_fn = _CountingFake(_always_raise(GraphServiceError("ServiceUnavailable")))

    answer, count_step_ran, cost_info = run_agent(QUESTION, search_fn=search_fn, count_fn=count_fn)

    assert search_fn.call_count == 1
    # 2 retries => 3 attempts total, per docs/spec.md's Agent steps section.
    assert count_fn.call_count == 3
    # The count step was attempted (and failed), not skipped - it "ran".
    assert count_step_ran is True
    assert answer.question == assemble_question_text(QUESTION)
    assert answer.answer == (
        "Search found matching patients, but the exact drug count could not "
        "be completed."
    )
    assert answer.rag_patient_ids == [1, 2, 3]
    assert answer.rag_citations == [
        {"patient_id": 1, "chunk_id": "1_chunk0", "snippet": "Patient 1 text."},
        {"patient_id": 2, "chunk_id": "2_chunk0", "snippet": "Patient 2 text."},
        {"patient_id": 3, "chunk_id": "3_chunk0", "snippet": "Patient 3 text."},
    ]
    assert answer.graph_result == {}
    assert answer.confidence == "low"
    assert answer.caveat == (
        "The drug count step failed after repeated attempts. This answer is "
        "based on search results only, without an exact count."
    )
    assert answer.outcome == "tool_error"


def test_answer_step_failed_after_one_retry_returns_fixed_answer():
    search_fn = _CountingFake(
        lambda query_text, condition, lab, comparison, value, top_k=25: {
            "answer": "some patients matched",
            "patient_ids": [1, 2, 3],
            "citations": [
                {"patient_id": 1, "chunk_id": "1_chunk0", "snippet": "Patient 1 text."},
                {"patient_id": 2, "chunk_id": "2_chunk0", "snippet": "Patient 2 text."},
                {"patient_id": 3, "chunk_id": "3_chunk0", "snippet": "Patient 3 text."},
            ],
            "retrieved_count": 3,
        }
    )
    count_fn = _CountingFake(
        lambda patient_ids, condition, lab, comparison, value: {
            "drug_counts": {"Lisinopril": 2},
            "patients_checked": 3,
        }
    )
    answer_fn = _CountingFake(_always_raise(ValueError("unparseable model output")))

    answer, count_step_ran, cost_info = run_agent(
        QUESTION, search_fn=search_fn, count_fn=count_fn, answer_fn=answer_fn
    )

    assert search_fn.call_count == 1
    assert count_fn.call_count == 1
    # 1 retry => 2 attempts total, per docs/spec.md's Agent steps section -
    # smaller than the tool retry budget since a retry here is a second,
    # slower, more expensive language-model call.
    assert answer_fn.call_count == 2
    assert count_step_ran is True
    assert answer.question == assemble_question_text(QUESTION)
    assert answer.answer == (
        "I found matching patients and counted their drugs, but wasn't able "
        "to put together a valid written answer."
    )
    assert answer.rag_patient_ids == [1, 2, 3]
    assert answer.rag_citations == [
        {"patient_id": 1, "chunk_id": "1_chunk0", "snippet": "Patient 1 text."},
        {"patient_id": 2, "chunk_id": "2_chunk0", "snippet": "Patient 2 text."},
        {"patient_id": 3, "chunk_id": "3_chunk0", "snippet": "Patient 3 text."},
    ]
    assert answer.graph_result == {"Lisinopril": 2}
    assert answer.confidence == "low"
    assert answer.caveat == (
        "The final write-up step failed, even after retrying once. The "
        "patient list and drug counts above are accurate; only the summary "
        "sentence is missing."
    )
    assert answer.outcome == "tool_error"


def test_full_success_threads_rag_citations_alongside_patient_ids():
    citations = [
        {"patient_id": 1, "chunk_id": "1_chunk0", "snippet": "Patient 1 text."},
        {"patient_id": 2, "chunk_id": "2_chunk0", "snippet": "Patient 2 text."},
        {"patient_id": 3, "chunk_id": "3_chunk0", "snippet": "Patient 3 text."},
    ]
    search_fn = _CountingFake(
        lambda query_text, condition, lab, comparison, value, top_k=25: {
            "answer": "some patients matched",
            "patient_ids": [1, 2, 3],
            "citations": citations,
            "retrieved_count": 3,
        }
    )
    count_fn = _CountingFake(
        lambda patient_ids, condition, lab, comparison, value: {
            "drug_counts": {"Lisinopril": 2, "Amlodipine": 1},
            "patients_checked": 3,
        }
    )
    answer_fn = _CountingFake(lambda *args: "Two patients are on Lisinopril, one on Amlodipine.")

    answer, count_step_ran, cost_info = run_agent(
        QUESTION, search_fn=search_fn, count_fn=count_fn, answer_fn=answer_fn
    )

    assert count_step_ran is True
    assert answer.outcome == "answered"
    assert answer.rag_patient_ids == [1, 2, 3]
    assert answer.rag_citations == citations

    # cost_info reports real, measured cost/token usage for this run - see
    # docs/spec.md's Tracing and logging. The fake answer_fn above returns a
    # plain string, not a (text, input_tokens, output_tokens) tuple, so no
    # real language-model call happened and usage is 0/$0 here.
    assert set(cost_info) == {"cost_usd", "input_tokens", "output_tokens"}
    for key in ("cost_usd", "input_tokens", "output_tokens"):
        assert isinstance(cost_info[key], (int, float))
        assert cost_info[key] >= 0
