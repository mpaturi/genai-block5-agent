"""Computes golden answers for data/eval/tasks.json, once, ahead of time.

Calls the live search service and live graph directly - not through
rag_tool.py/graph_tool.py, since neither exists yet (see docs/plan.md).
Writes data/eval/answer_key.json, keyed by question ID, holding only the
answerable questions' golden patient list, verified drug counts, and
expected confidence.

Golden answers must come from logic that is independent of the code
being tested. This script never imports graph_tool.py: if it did, a
mistake in Tool 2's verification or counting query would define its own
"correct" answer, and nothing would be left to catch it. The verification
and drug-count queries below are this script's own, separately written
implementation of the same real-world facts Tool 2 checks - condition is
a HAS_CONDITION relationship to a Condition node (condition_name
property), lab values are properties directly on the Patient node
(latest_sbp/latest_bmi/latest_glucose/latest_hba1c, whichever the
question's lab field names).

q1 is a special case, and writes two entries instead of one. RAG's
top_k=25 ceiling means q1's true matching population (99 patients) can
never be RAG's actual search result - the normal search -> verify -> count
pipeline below can only ever produce a capped, 25-patient answer for q1,
never the true one. So q1 gets both: "q1_expected_capped" holds exactly
that normal pipeline's result (what the real agent can actually achieve
today, scored against in run_eval.py's _check_answer_accuracy()), and
"q1" holds the true, full population instead - found by
_query_full_population(), a second, independently-written Cypher query
that enumerates every matching patient directly with no RAG involved and
no top_k limit at all, the same way this script never imports
graph_tool.py for its verification/count queries. "q1" is kept only as a
documented reference point (see docs/spec.md's Important honesty point) -
nothing scores against it.
"""
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase

from block5_agent.schemas import (
    QuestionInput,
    build_rag_query,
    compute_confidence,
    dedupe_and_order_patient_ids,
)

load_dotenv()

TASKS_PATH = Path("data/eval/tasks.json")
ANSWER_KEY_PATH = Path("data/eval/answer_key.json")

RAG_API_URL = os.environ.get("RAG_API_URL", "http://localhost:8000")
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

_LAB_PROPERTY = {
    "SBP": "latest_sbp",
    "BMI": "latest_bmi",
    "Glucose": "latest_glucose",
    "HbA1c": "latest_hba1c",
}
_COMPARISON_OP = {"above": ">", "below": "<"}

# Confirms each candidate patient genuinely has the stated condition and
# genuinely satisfies the lab comparison, using the graph's own stored
# data - not just RAG's fuzzy match. lab_property and op are chosen from
# a fixed whitelist above, never from unsanitized input.
VERIFY_PATIENTS_QUERY_TEMPLATE = """
MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition {{condition_name: $condition}})
WHERE p.person_id IN $person_ids
  AND p.{lab_property} IS NOT NULL AND p.{lab_property} {op} $value
RETURN collect(DISTINCT p.person_id) AS verified_ids
"""

# Counts drugs only among the patients who passed verification.
DRUG_COUNT_QUERY = """
MATCH (p:Patient)-[:PRESCRIBED]->(d:Drug)
WHERE p.person_id IN $person_ids
RETURN d.drug_name AS drug, count(DISTINCT p) AS patient_count
"""

# q1's true-population query (see module docstring): the same real-world
# facts VERIFY_PATIENTS_QUERY_TEMPLATE checks, just enumerated directly
# with no candidate list to narrow against - VERIFY_PATIENTS_QUERY_TEMPLATE
# with its "AND p.person_id IN $person_ids" line dropped entirely, since
# the whole point here is finding every matching patient, not narrowing
# one down.
FULL_POPULATION_QUERY_TEMPLATE = """
MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition {{condition_name: $condition}})
WHERE p.{lab_property} IS NOT NULL AND p.{lab_property} {op} $value
RETURN collect(DISTINCT p.person_id) AS matched_ids
"""


def _search(question: QuestionInput) -> list[int]:
    # Built from condition/lab/comparison/value only, never drug_a/drug_b,
    # via the one shared function - never a second, separate implementation
    # of this formatting (see docs/spec.md's Tool 1). condition/lab/
    # comparison/value are also forwarded as structured metadata filter
    # fields, identically to rag_tool.py's search_patients() - otherwise
    # this script would build its golden answers from a different,
    # unfiltered candidate set than what the real agent retrieves.
    query_text = build_rag_query(question)
    response = requests.post(
        f"{RAG_API_URL}/query",
        json={
            "question": query_text,
            "top_k": 25,
            "condition": question.condition,
            "lab": question.lab,
            "comparison": question.comparison,
            "value": question.value,
        },
        timeout=10,
    )
    response.raise_for_status()
    body = response.json()
    return dedupe_and_order_patient_ids(body["sources"])


def _verify_patients(driver, question: QuestionInput, person_ids: list[int]) -> list[int]:
    if not person_ids:
        return []
    lab_property = _LAB_PROPERTY[question.lab]
    op = _COMPARISON_OP[question.comparison]
    query = VERIFY_PATIENTS_QUERY_TEMPLATE.format(lab_property=lab_property, op=op)
    with driver.session(database=NEO4J_DATABASE) as session:
        row = session.run(
            query,
            condition=question.condition,
            person_ids=person_ids,
            value=question.value,
        ).single()
    verified_ids = set(row["verified_ids"])
    # Keep RAG's original order among the patients who passed.
    return [pid for pid in person_ids if pid in verified_ids]


def _count_drugs(driver, person_ids: list[int]) -> dict:
    if not person_ids:
        return {"drug_counts": {}, "patients_checked": 0}
    with driver.session(database=NEO4J_DATABASE) as session:
        rows = session.run(DRUG_COUNT_QUERY, person_ids=person_ids)
        drug_counts = {row["drug"]: row["patient_count"] for row in rows}
    return {"drug_counts": drug_counts, "patients_checked": len(person_ids)}


def _query_full_population(driver, question: QuestionInput) -> list[int]:
    """Every patient genuinely matching condition/lab/comparison/value -
    no RAG, no top_k, no candidate list to narrow (see module docstring's
    q1 special case). Sorted ascending by person_id for a stable, readable
    answer_key.json - unlike rag_patient_ids elsewhere in this file, this
    list isn't RAG output, so RAG's own best-score-first ordering rule
    doesn't apply to it.
    """
    lab_property = _LAB_PROPERTY[question.lab]
    op = _COMPARISON_OP[question.comparison]
    query = FULL_POPULATION_QUERY_TEMPLATE.format(lab_property=lab_property, op=op)
    with driver.session(database=NEO4J_DATABASE) as session:
        row = session.run(query, condition=question.condition, value=question.value).single()
    return sorted(row["matched_ids"])


def _build_capped_entry(driver, question: QuestionInput, search_fn) -> dict:
    """The normal search -> verify -> count pipeline's result, in the
    answer_key.json entry shape - what every question except q1's "q1"
    entry writes today, and what q1 writes to "q1_expected_capped"."""
    patient_ids = search_fn(question)
    verified_ids = _verify_patients(driver, question, patient_ids)
    graph_result = _count_drugs(driver, verified_ids)
    return {
        "rag_patient_ids": patient_ids,
        "graph_result": graph_result["drug_counts"],
        "patients_checked": graph_result["patients_checked"],
        "confidence": compute_confidence(graph_result["patients_checked"]),
    }


def build_answer_key(tasks: list[dict], driver, search_fn=_search) -> dict:
    """Builds the full answer_key dict for the given tasks (see module
    docstring's q1 special case for why q1 writes two entries instead of
    one). search_fn is injectable - defaults to the real _search() - so
    tests can exercise this without a live search service.
    """
    answer_key = {}
    for task in tasks:
        if not task["answerable"]:
            continue
        question = QuestionInput(
            condition=task["condition"],
            lab=task["lab"],
            comparison=task["comparison"],
            value=task["value"],
            drug_a=task["drug_a"],
            drug_b=task["drug_b"],
        )
        capped_entry = _build_capped_entry(driver, question, search_fn)
        if task["id"] == "q1":
            answer_key["q1_expected_capped"] = capped_entry
            full_population_ids = _query_full_population(driver, question)
            full_graph_result = _count_drugs(driver, full_population_ids)
            answer_key["q1"] = {
                "rag_patient_ids": full_population_ids,
                "graph_result": full_graph_result["drug_counts"],
                "patients_checked": full_graph_result["patients_checked"],
                "confidence": compute_confidence(full_graph_result["patients_checked"]),
            }
        else:
            answer_key[task["id"]] = capped_entry
    return answer_key


def main() -> None:
    tasks = json.loads(TASKS_PATH.read_text())

    with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
        driver.verify_connectivity()
        answer_key = build_answer_key(tasks, driver)

    ANSWER_KEY_PATH.write_text(json.dumps(answer_key, indent=2) + "\n")
    print(f"Wrote {len(answer_key)} golden answers to {ANSWER_KEY_PATH}")


if __name__ == "__main__":
    main()
