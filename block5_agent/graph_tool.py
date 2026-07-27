"""Tool 2 - exact drug count (see docs/spec.md's Tool 2).

Given a candidate patient list, first verifies each patient against the
graph's own stored data - a HAS_CONDITION relationship to a Condition
node (condition_name property), and the relevant Patient node lab
property (latest_sbp/latest_bmi/latest_glucose/latest_hba1c) satisfying
the asked-for comparison - then counts drugs only among the patients who
pass. Both steps are fixed, parameterized Cypher queries - never an
arbitrary, agent-written query. Read-only: never MERGE/CREATE/DELETE.

This file's verification logic is its own, separate implementation from
block5_agent/build_eval_answer_key.py's - not imported from there, per the
test-independence decision documented in that file's docstring: golden
answers must come from logic that couldn't share a bug with the code
being tested.
"""
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase, Query

load_dotenv()

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

# Matches rag_tool.py's timeout=10 on its HTTP call (see docs/spec.md's
# "Agent steps" - both tools use a fixed 10-second timeout). session.run()
# has no timeout kwarg of its own - passing timeout=10 straight to run()
# would silently become an unused Cypher parameter, not an actual limit.
# The only way to bound a query's execution time in this driver is to wrap
# the query text in a Query object carrying a server-side transaction
# timeout, which is what GRAPH_QUERY_TIMEOUT is used for below.
GRAPH_QUERY_TIMEOUT = 10

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
# the fixed whitelists above, never from unsanitized input.
VERIFY_PATIENTS_QUERY_TEMPLATE = """
MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition {{condition_name: $condition}})
WHERE p.person_id IN $person_ids
  AND p.{lab_property} IS NOT NULL AND p.{lab_property} {op} $value
RETURN collect(DISTINCT p.person_id) AS verified_ids
"""

# The one fixed drug-count query this tool ever runs, over the verified
# patients only. A drug with zero matching patients simply has no row
# here - it is never returned with a count of 0.
DRUG_COUNT_QUERY = """
MATCH (p:Patient)-[:PRESCRIBED]->(d:Drug)
WHERE p.person_id IN $person_ids
RETURN d.drug_name AS drug, count(DISTINCT p) AS patient_count
"""

_driver = None


def _get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver


class GraphServiceError(Exception):
    """Raised on any drug-count-tool failure. `detail` names what went
    wrong, mirroring Block 4's own {"error": ..., "detail": "<ExceptionType>"}
    shape so both tools fail the same way from the agent's point of view.
    `retryable` distinguishes a temporary problem (a database/driver
    failure) from bad input (an invalid patient ID, or an unrecognized
    lab/comparison) - a bad-input failure won't be fixed by trying again,
    so the agent's retry loop checks this flag before retrying (see
    docs/spec.md's Agent steps), same as RAGServiceError.
    """

    def __init__(self, detail: str, retryable: bool = True):
        super().__init__(detail)
        self.detail = detail
        self.retryable = retryable


def _validate_person_ids(person_ids: list) -> None:
    for person_id in person_ids:
        is_whole_number = isinstance(person_id, int) and not isinstance(person_id, bool)
        if not is_whole_number or person_id <= 0:
            raise GraphServiceError("invalid_person_id", retryable=False)


def count_drugs(
    person_ids: list[int],
    condition: str,
    lab: str,
    comparison: str,
    value: float,
    *,
    driver=None,
) -> dict:
    if not person_ids:
        # Nothing to count - return immediately without opening a session.
        return {"drug_counts": {}, "patients_checked": 0}

    # Validated before any database interaction, per docs/spec.md's Tool 2 -
    # fail fast locally rather than sending bad data to the graph.
    _validate_person_ids(person_ids)

    lab_property = _LAB_PROPERTY.get(lab)
    op = _COMPARISON_OP.get(comparison)
    if lab_property is None or op is None:
        raise GraphServiceError("invalid_lab_or_comparison", retryable=False)

    driver = driver if driver is not None else _get_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            verify_query = VERIFY_PATIENTS_QUERY_TEMPLATE.format(
                lab_property=lab_property, op=op
            )
            verify_row = session.run(
                Query(verify_query, timeout=GRAPH_QUERY_TIMEOUT),
                condition=condition,
                person_ids=person_ids,
                value=value,
            ).single()
            verified_ids = list(verify_row["verified_ids"])

            if not verified_ids:
                return {"drug_counts": {}, "patients_checked": 0}

            count_rows = session.run(
                Query(DRUG_COUNT_QUERY, timeout=GRAPH_QUERY_TIMEOUT),
                person_ids=verified_ids,
            )
            drug_counts = {row["drug"]: row["patient_count"] for row in count_rows}
    except Exception as exc:
        raise GraphServiceError(type(exc).__name__)

    return {"drug_counts": drug_counts, "patients_checked": len(verified_ids)}
