"""Shared types for Block 5: the structured question input, the agent's
internal state, and the final structured answer (see docs/spec.md).

Also holds build_rag_query(), dedupe_and_order_patient_ids(), and
compute_confidence() - the pieces of logic docs/spec.md requires to live in
exactly one place so rag_tool.py, graph_tool.py, agent.py, and
build_eval_answer_key.py can never drift apart by each writing their own
copy.
"""
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel

Comparison = Literal["above", "below"]
Confidence = Literal["high", "medium", "low"]

_COMPARISON_SYMBOLS: dict[Comparison, str] = {"above": ">", "below": "<"}


class QuestionInput(BaseModel):
    """One structured clinical question (see docs/spec.md's Question pattern).

    Defined as separate fields, not one opaque string, so building the RAG
    query (below) is a plain lookup of which fields to use instead of a
    text-parsing problem.
    """

    condition: str
    lab: str
    comparison: Comparison
    value: float
    drug_a: str
    drug_b: str


def _format_value(value: float) -> str:
    """Render a whole-number value as "140", not "140.0"."""
    if value == int(value):
        return str(int(value))
    return str(value)


def build_rag_query(question: QuestionInput) -> str:
    """Build the RAG search text from condition/lab/comparison/value only.

    Never includes drug_a/drug_b (see docs/spec.md's "Why drug_a/drug_b are
    left out of the RAG query") and never parses the assembled display
    sentence. This is the one shared function rag_tool.py and
    build_eval_answer_key.py both import, so they always send RAG the exact
    same text for the same fields - two independently written versions of
    this formatting could drift in wording and silently change which
    patients a semantic search matches.
    """
    return (
        f"patients with {question.condition} and {question.lab} "
        f"{question.comparison} {_format_value(question.value)}"
    )


def assemble_question_text(question: QuestionInput) -> str:
    """Build the full, human-readable question sentence.

    Used for display, logging, and the `question` field in the structured
    output (see docs/spec.md's Question pattern) - never sent to RAG.
    """
    symbol = _COMPARISON_SYMBOLS[question.comparison]
    value_text = _format_value(question.value)
    return (
        f"Of patients with {question.condition} and {question.lab} "
        f"{symbol} {value_text}, how many are on {question.drug_a} vs. "
        f"{question.drug_b}?"
    )


def dedupe_and_order_patient_ids(sources: list[dict]) -> list[int]:
    """The one shared patient-ID rule (see docs/spec.md's Tool 1): dedupe by
    person_id (keeping the highest score seen for a repeat), then order by
    score descending, ties broken by patient ID.

    This is the one place this logic lives - rag_tool.py (Phase 3) and
    build_eval_answer_key.py both import it, so a golden answer key built
    from one implementation of "dedupe and order" can never silently drift
    from what the real tool does at run time.
    """
    # Step 1: build a notebook of each patient's best (highest) score,
    # throwing away any duplicate, lower-scoring entries for that patient.
    best_score: dict[int, float] = {}
    for source in sources:
        person_id = source["person_id"]
        score = source["score"]
        if person_id not in best_score or score > best_score[person_id]:
            best_score[person_id] = score

    def get_sort_key_for_patient(patient_id):
        """Build the value sorted() uses to compare two patients.

        Returns a pair: the patient's score with its sign flipped (so
        sorting smallest-to-normal actually puts the highest real score
        first), and the patient ID itself (used only to break a tie
        between two equal scores).
        """
        score = best_score[patient_id]
        negative_score = -score
        return (negative_score, patient_id)

    # Step 2: sort the deduped patient IDs, best score first, ties broken
    # by patient ID.
    patient_ids = list(best_score.keys())
    sorted_patient_ids = sorted(patient_ids, key=get_sort_key_for_patient)
    return sorted_patient_ids


def compute_confidence(patients_checked: int) -> Confidence:
    """The one shared confidence rule (see docs/spec.md's Structured output).

    Fewer than 3 patients checked is `low`, 3 or 4 is `medium`, 5 or more is
    `high` - calibrated against Tool 1's default of 5 results per question.
    Both agent.py (the real run) and build_eval_answer_key.py (the golden
    answer key) call this, so an off-by-one on the tier boundaries can never
    silently diverge between the two.
    """
    if patients_checked < 3:
        return "low"
    if patients_checked < 5:
        return "medium"
    return "high"


class ClinicalAnswer(BaseModel):
    """The one structured answer object every agent run returns."""

    question: str
    answer: str
    rag_patient_ids: list[int]
    graph_result: dict
    confidence: Confidence
    caveat: Optional[str] = None


class AgentState(TypedDict):
    """The LangGraph agent's internal state as it moves through its steps."""

    question: QuestionInput
    rag_result: Optional[dict]
    rag_patient_ids: list[int]
    rag_error: Optional[str]
    rag_error_retryable: bool
    rag_retry_count: int
    graph_result: Optional[dict]
    graph_error: Optional[str]
    graph_error_retryable: bool
    graph_retry_count: int
    answer_error: Optional[str]
    answer_retry_count: int
    final_answer: Optional[dict]
    count_step_ran: bool
    outcome: Optional[str]
