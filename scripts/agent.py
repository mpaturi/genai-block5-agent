"""The LangGraph agent (see docs/spec.md's Agent steps).

Moves through a fixed sequence - search -> decide -> count -> answer -
with retries on temporary tool failures and graceful degradation to fixed
wording once a step exhausts its retries. Both tools and the step 4
language-model call can be swapped for fakes via run_agent's keyword
arguments, which is what lets tests/test_agent_answers.py exercise every
non-full-success path without a real search service, graph, or LLM call.
"""
import os
import time

from anthropic import Anthropic
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph
from langsmith.wrappers import wrap_anthropic

from scripts.graph_tool import GraphServiceError, count_drugs
from scripts.logging_utils import log_run
from scripts.rag_tool import RAGServiceError, search_patients
from scripts.schemas import (
    AgentState,
    ClinicalAnswer,
    QuestionInput,
    assemble_question_text,
    build_rag_query,
    compute_confidence,
)

load_dotenv()

# 2 retries => 3 attempts total for each tool (see docs/spec.md's Agent steps).
_MAX_TOOL_RETRIES = 2
# 1 retry => 2 attempts total for the answer-writing step - smaller than the
# tool budget since a retry here is a second, slower, more expensive
# language-model call (see docs/spec.md's Agent steps).
_MAX_ANSWER_RETRIES = 1

_ANTHROPIC_MODEL = "claude-sonnet-4-6"

_anthropic_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = wrap_anthropic(Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]))
    return _anthropic_client


def _default_answer_fn(
    question: QuestionInput,
    rag_patient_ids: list[int],
    drug_a_count: int,
    drug_b_count: int,
) -> tuple[str, int, int]:
    """Write the one plain-English sentence for the full-success case.

    Only picks which two counts to describe - never which drugs matter,
    that lookup already happened in code (see docs/spec.md's "Picking out
    the two named drugs"). Returns (text, input_tokens, output_tokens) so
    the caller can log real token usage (see docs/spec.md's Tracing and
    logging) - this is the only answer_fn implementation real runs use, so
    only it needs to report usage; the fakes tests substitute never do.
    """
    prompt = (
        f"Question: {assemble_question_text(question)}\n"
        f"Matching patient IDs: {rag_patient_ids}\n"
        f"{question.drug_a} count: {drug_a_count}\n"
        f"{question.drug_b} count: {drug_b_count}\n\n"
        "Write exactly one plain-English sentence answering the question. "
        "Name both drug counts and cite the patient IDs. Do not add "
        "anything beyond that one sentence."
    )
    response = _get_anthropic_client().messages.create(
        model=_ANTHROPIC_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    if not text:
        raise ValueError("empty answer from language model")
    return text, response.usage.input_tokens, response.usage.output_tokens


def run_agent(
    question: QuestionInput,
    *,
    search_fn=search_patients,
    count_fn=count_drugs,
    answer_fn=_default_answer_fn,
) -> tuple[ClinicalAnswer, bool]:
    """Run one clinical question through the agent.

    Returns (answer, count_step_ran). count_step_ran is handed back
    directly here, not read back from the log (see docs/spec.md's Tracing
    and logging), so a caller like run_eval.py can check tool-call
    correctness straight from the call it just made.
    """
    node_latency_ms: dict[str, float] = {}
    token_usage = {"input_tokens": 0, "output_tokens": 0}

    def _timed(name, node_fn):
        def wrapped(state: AgentState) -> dict:
            start = time.monotonic()
            result = node_fn(state)
            elapsed = (time.monotonic() - start) * 1000
            node_latency_ms[name] = node_latency_ms.get(name, 0.0) + elapsed
            return result

        return wrapped

    def search_node(state: AgentState) -> dict:
        try:
            question_input = state["question"]
            query_text = build_rag_query(question_input)
            result = search_fn(
                query_text,
                question_input.condition,
                question_input.lab,
                question_input.comparison,
                question_input.value,
                top_k=25,
            )
            return {"rag_result": result, "rag_error": None}
        except RAGServiceError as exc:
            return {
                "rag_error": exc.detail,
                "rag_error_retryable": exc.retryable,
                "rag_retry_count": state["rag_retry_count"] + 1,
            }

    def route_after_search(state: AgentState) -> str:
        if state.get("rag_error"):
            if state["rag_error_retryable"] and state["rag_retry_count"] < _MAX_TOOL_RETRIES + 1:
                return "search"
            return "build_search_error_answer"
        if state["rag_result"]["retrieved_count"] == 0:
            return "build_fallback_answer"
        return "count"

    def count_node(state: AgentState) -> dict:
        # Order: rag_patient_ids only exists once search succeeded, so this
        # node is only ever reached after a successful search.
        patient_ids = state["rag_result"]["patient_ids"]
        question_input = state["question"]
        try:
            result = count_fn(
                patient_ids,
                question_input.condition,
                question_input.lab,
                question_input.comparison,
                question_input.value,
            )
            return {
                "rag_patient_ids": patient_ids,
                "graph_result": result,
                "graph_error": None,
                "count_step_ran": True,
            }
        except GraphServiceError as exc:
            return {
                "rag_patient_ids": patient_ids,
                "graph_error": exc.detail,
                "graph_error_retryable": exc.retryable,
                "graph_retry_count": state["graph_retry_count"] + 1,
                "count_step_ran": True,
            }

    def route_after_count(state: AgentState) -> str:
        if state.get("graph_error"):
            if state["graph_error_retryable"] and state["graph_retry_count"] < _MAX_TOOL_RETRIES + 1:
                return "count"
            return "build_graph_error_answer"
        return "synthesize"

    def synthesize_node(state: AgentState) -> dict:
        question_input = state["question"]
        drug_counts = state["graph_result"]["drug_counts"]
        patients_checked = state["graph_result"]["patients_checked"]
        drug_a_count = drug_counts.get(question_input.drug_a, 0)
        drug_b_count = drug_counts.get(question_input.drug_b, 0)
        try:
            answer_result = answer_fn(
                question_input, state["rag_patient_ids"], drug_a_count, drug_b_count
            )
        except Exception as exc:
            return {
                "answer_error": str(exc),
                "answer_retry_count": state["answer_retry_count"] + 1,
            }

        if isinstance(answer_result, tuple):
            answer_text, input_tokens, output_tokens = answer_result
            token_usage["input_tokens"] += input_tokens
            token_usage["output_tokens"] += output_tokens
        else:
            answer_text = answer_result

        confidence = compute_confidence(patients_checked)
        caveat = None
        if confidence != "high":
            caveat = (
                f"Only {patients_checked} matching patient(s) were checked, so "
                "this count may not be representative."
            )
        return {
            "final_answer": ClinicalAnswer(
                question=assemble_question_text(question_input),
                answer=answer_text,
                rag_patient_ids=state["rag_patient_ids"],
                graph_result=drug_counts,
                confidence=confidence,
                caveat=caveat,
            ).model_dump(),
            "answer_error": None,
            "outcome": "answered",
        }

    def route_after_synthesize(state: AgentState) -> str:
        if state.get("answer_error"):
            if state["answer_retry_count"] < _MAX_ANSWER_RETRIES + 1:
                return "synthesize"
            return "build_answer_error_answer"
        return "done"

    def build_fallback_answer_node(state: AgentState) -> dict:
        return {
            "final_answer": ClinicalAnswer(
                question=assemble_question_text(state["question"]),
                answer=(
                    "I don't know — I couldn't find any patient records relevant "
                    "to that question."
                ),
                rag_patient_ids=[],
                graph_result={},
                confidence="low",
                caveat=(
                    "No patients were found for this question, so the drug "
                    "count step was skipped."
                ),
            ).model_dump(),
            "outcome": "nothing_found",
        }

    def build_search_error_answer_node(state: AgentState) -> dict:
        return {
            "final_answer": ClinicalAnswer(
                question=assemble_question_text(state["question"]),
                answer=(
                    "I wasn't able to answer this question because the patient "
                    "search step could not be completed."
                ),
                rag_patient_ids=[],
                graph_result={},
                confidence="low",
                caveat="The patient search service failed after repeated attempts.",
            ).model_dump(),
            "outcome": "tool_error",
        }

    def build_graph_error_answer_node(state: AgentState) -> dict:
        return {
            "final_answer": ClinicalAnswer(
                question=assemble_question_text(state["question"]),
                answer=(
                    "Search found matching patients, but the exact drug count "
                    "could not be completed."
                ),
                rag_patient_ids=state["rag_patient_ids"],
                graph_result={},
                confidence="low",
                caveat=(
                    "The drug count step failed after repeated attempts. This "
                    "answer is based on search results only, without an exact "
                    "count."
                ),
            ).model_dump(),
            "outcome": "tool_error",
        }

    def build_answer_error_answer_node(state: AgentState) -> dict:
        return {
            "final_answer": ClinicalAnswer(
                question=assemble_question_text(state["question"]),
                answer=(
                    "I found matching patients and counted their drugs, but "
                    "wasn't able to put together a valid written answer."
                ),
                rag_patient_ids=state["rag_patient_ids"],
                graph_result=state["graph_result"]["drug_counts"],
                confidence="low",
                caveat=(
                    "The final write-up step failed, even after retrying once. "
                    "The patient list and drug counts above are accurate; only "
                    "the summary sentence is missing."
                ),
            ).model_dump(),
            "outcome": "tool_error",
        }

    graph = StateGraph(AgentState)
    graph.add_node("search", _timed("search", search_node))
    graph.add_node("count", _timed("count", count_node))
    graph.add_node("synthesize", _timed("synthesize", synthesize_node))
    graph.add_node("build_fallback_answer", build_fallback_answer_node)
    graph.add_node("build_search_error_answer", build_search_error_answer_node)
    graph.add_node("build_graph_error_answer", build_graph_error_answer_node)
    graph.add_node("build_answer_error_answer", build_answer_error_answer_node)

    graph.set_entry_point("search")
    graph.add_conditional_edges(
        "search",
        route_after_search,
        {
            "search": "search",
            "build_search_error_answer": "build_search_error_answer",
            "build_fallback_answer": "build_fallback_answer",
            "count": "count",
        },
    )
    graph.add_conditional_edges(
        "count",
        route_after_count,
        {
            "count": "count",
            "build_graph_error_answer": "build_graph_error_answer",
            "synthesize": "synthesize",
        },
    )
    graph.add_conditional_edges(
        "synthesize",
        route_after_synthesize,
        {
            "synthesize": "synthesize",
            "build_answer_error_answer": "build_answer_error_answer",
            "done": END,
        },
    )
    graph.add_edge("build_fallback_answer", END)
    graph.add_edge("build_search_error_answer", END)
    graph.add_edge("build_graph_error_answer", END)
    graph.add_edge("build_answer_error_answer", END)

    compiled = graph.compile()

    initial_state: AgentState = {
        "question": question,
        "rag_result": None,
        "rag_patient_ids": [],
        "rag_error": None,
        "rag_error_retryable": True,
        "rag_retry_count": 0,
        "graph_result": None,
        "graph_error": None,
        "graph_error_retryable": True,
        "graph_retry_count": 0,
        "answer_error": None,
        "answer_retry_count": 0,
        "final_answer": None,
        "count_step_ran": False,
        "outcome": None,
    }
    final_state = compiled.invoke(initial_state)
    answer = ClinicalAnswer.model_validate(final_state["final_answer"])

    log_run(
        question=answer.question,
        node_latency_ms={k: round(v, 2) for k, v in node_latency_ms.items()},
        claude_input_tokens=token_usage["input_tokens"],
        claude_output_tokens=token_usage["output_tokens"],
        outcome=final_state["outcome"],
    )

    return answer, final_state["count_step_ran"]
