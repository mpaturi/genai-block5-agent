"""Shared types for Block 5: the structured question input, the agent's
internal state, and the final structured answer (see docs/spec.md).

Also holds build_rag_query(), dedupe_and_order_patient_ids(),
build_rag_citations(), and compute_confidence() - the pieces of logic
docs/spec.md requires to live in exactly one place so rag_tool.py,
graph_tool.py, agent.py, and build_eval_answer_key.py can never drift
apart by each writing their own copy.
"""
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field

Comparison = Literal["above", "below"]
Confidence = Literal["high", "medium", "low"]
Outcome = Literal["answered", "nothing_found", "tool_error"]

_COMPARISON_SYMBOLS: dict[Comparison, str] = {"above": ">", "below": "<"}


class QuestionInput(BaseModel):
    """One structured clinical question (see docs/spec.md's Question pattern).

    Defined as separate fields, not one opaque string, so building the RAG
    query (below) is a plain lookup of which fields to use instead of a
    text-parsing problem.

    Bounds matter here directly, not just as a nice-to-have: condition/lab/
    drug_a/drug_b are f-string'd straight into text that reaches an LLM
    prompt (build_rag_query()/assemble_question_text() below) and, for
    condition/lab, a Pinecone-embedded RAG query, on every single request -
    an unbounded caller string is unbounded prompt-injection surface every
    time. value feeds the same two functions and _format_value() below;
    a non-finite float (inf/-inf/nan) would either format nonsensically or
    crash int()/str() coercion before it ever reached a real comparison.

    max_length=200 for condition, 100 for lab/drug_a/drug_b: real clinical
    condition names/phrases run longer than single lab or drug names (e.g.
    compound SNOMED-style descriptions), so condition gets a wider
    allowance; both limits are many times longer than any real entry in
    Block 3's graph vocabulary, generous for genuine clinical terms while
    still closing off multi-megabyte payloads.

    value: ge=0 (every lab this system knows - see graph_tool.py's
    _LAB_PROPERTY - is a non-negative measurement; a negative value can
    never match a real patient), le=10_000 (comfortably above any real
    unit in use - HbA1c tops out near 20, systolic BP near 300, glucose in
    the low thousands mg/dL at the extreme - while still rejecting a
    deliberately absurd float before it reaches a prompt). Also rejects
    inf/-inf/nan, none of which pydantic's float coercion treats as
    satisfying a finite ge/le range.

    Same field names, same limits, same reasoning as Block 8's own
    `QueryRequest(QuestionInput)` (genai-block8-capstone/app/api.py) -
    ported here so every caller of this schema gets the bounds, not just
    Block 8's API layer. This makes Block 8's own Field(...) redeclaration
    a redundant *second* layer at its own boundary now, not the only one -
    intentional defense-in-depth (each project validates independently at
    its own trust boundary, per this project's input-validation rule), not
    duplication to go clean up there.
    """

    condition: str = Field(max_length=200)
    lab: str = Field(max_length=100)
    comparison: Comparison
    value: float = Field(ge=0, le=10_000)
    drug_a: str = Field(max_length=100)
    drug_b: str = Field(max_length=100)


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


def _dedupe_best_sources(sources: list[dict]) -> dict[int, dict]:
    """The one shared dedupe rule (see docs/spec.md's Tool 1): for each
    patient_id, keep the full source dict with the highest score seen,
    throwing away any duplicate, lower-scoring entries for that patient.

    Keeps the full winning source dict, not just its score, so callers
    that need more than the score - build_rag_citations()'s chunk_id and
    chunk_text, for example - read it straight from here instead of a
    second, separately written dedupe pass. This is the one place this
    logic lives; dedupe_and_order_patient_ids() and build_rag_citations()
    both build on it, so their patient sets can never silently diverge.
    """
    best_source: dict[int, dict] = {}
    for source in sources:
        person_id = source["person_id"]
        score = source["score"]
        if person_id not in best_source or score > best_source[person_id]["score"]:
            best_source[person_id] = source
    return best_source


def _order_patient_ids_best_score_first(best_source: dict[int, dict]) -> list[int]:
    """Order deduped patient IDs best score first, ties broken by patient
    ID - the one shared ordering rule dedupe_and_order_patient_ids() and
    build_rag_citations() both use, so their patient orders can never
    silently diverge.
    """

    def get_sort_key_for_patient(patient_id):
        """Build the value sorted() uses to compare two patients.

        Returns a pair: the patient's score with its sign flipped (so
        sorting smallest-to-normal actually puts the highest real score
        first), and the patient ID itself (used only to break a tie
        between two equal scores).
        """
        score = best_source[patient_id]["score"]
        negative_score = -score
        return (negative_score, patient_id)

    patient_ids = list(best_source.keys())
    return sorted(patient_ids, key=get_sort_key_for_patient)


def dedupe_and_order_patient_ids(sources: list[dict]) -> list[int]:
    """The one shared patient-ID rule (see docs/spec.md's Tool 1): dedupe by
    person_id (keeping the highest score seen for a repeat), then order by
    score descending, ties broken by patient ID.

    This is the one place this logic lives - rag_tool.py (Phase 3) and
    build_eval_answer_key.py both import it, so a golden answer key built
    from one implementation of "dedupe and order" can never silently drift
    from what the real tool does at run time.
    """
    best_source = _dedupe_best_sources(sources)
    return _order_patient_ids_best_score_first(best_source)


def build_rag_citations(sources: list[dict]) -> list[dict]:
    """Build the per-patient citation list backing ClinicalAnswer's
    rag_citations field (see docs/spec.md's Structured output): one entry
    per deduped patient, in the same best-score-first order as
    dedupe_and_order_patient_ids(), each holding that patient's winning
    chunk's ID and text.

    Uses patient_id - the same external name rag_patient_ids already uses
    - not Block 4's internal person_id/chunk_text naming, so every field
    this agent exposes calls a patient and a chunk the same thing
    everywhere.
    """
    best_source = _dedupe_best_sources(sources)
    ordered_patient_ids = _order_patient_ids_best_score_first(best_source)
    return [
        {
            "patient_id": patient_id,
            "chunk_id": best_source[patient_id]["chunk_id"],
            "snippet": best_source[patient_id]["chunk_text"],
        }
        for patient_id in ordered_patient_ids
    ]


def compute_confidence(patients_checked: int) -> Confidence:
    """The one shared confidence rule (see docs/spec.md's Structured output).

    Fewer than 15 patients checked is `low`, 15 to 24 is `medium`, 25 (Tool
    1's top_k=25 ceiling - the most Tool 2 can ever be handed) is `high`.
    Same design principle as the original thresholds - `high` reachable
    only at the tool's actual operating ceiling, not trivially easy, and
    not practically unreachable - re-grounded in Phase 7's real,
    remeasured per-question counts (not guessed): sorted, they are 1, 3,
    3, 8, 18, 19, 25, 25, and 15 is the boundary that reproduces the same
    four `low` / two `medium` / two `high` split the original thresholds
    were grounded in (see docs/spec.md's Structured output section for
    the full numbers). 15 also happens to be 60% of the new 25 ceiling,
    the same fraction (12 of 20) the original `low` boundary sat at - not
    the reason it was chosen, but a useful confirmation it isn't an
    arbitrary cut. Both agent.py (the real run) and
    build_eval_answer_key.py (the golden answer key) call this, so an
    off-by-one on the tier boundaries can never silently diverge between
    the two.
    """
    if patients_checked < 15:
        return "low"
    if patients_checked < 25:
        return "medium"
    return "high"


class ClinicalAnswer(BaseModel):
    """The one structured answer object every agent run returns."""

    question: str
    answer: str
    rag_patient_ids: list[int]
    rag_citations: list[dict]
    graph_result: dict
    confidence: Confidence
    caveat: Optional[str] = None
    outcome: Outcome


class AgentState(TypedDict):
    """The LangGraph agent's internal state as it moves through its steps."""

    question: QuestionInput
    rag_result: Optional[dict]
    rag_patient_ids: list[int]
    rag_citations: list[dict]
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
