"""check_plausibility - flags a question's condition/lab/drug_a/drug_b
values against the graph's own real vocabulary, before the agent runs
(see docs/spec.md's Agent steps). Advisory only: a flagged run still
completes normally (see "Fail-open" below) - this exists to catch an
obviously wrong or injected value early and make it visible, not to
block a request.

Follows genai-block6-multiagent/scripts/vocabulary_check.py's confirmed
pattern: query Neo4j once for the graph's real, distinct values, then
cache them so every later call in the same process reuses that cache
instead of re-querying. Unlike that module, this cache has no TTL - it's
populated once and kept for the life of the process, not refreshed
periodically. Block 6's vocabulary_check.py runs inside a long-lived
orchestrator process, where the graph can plausibly gain a new condition/
drug while the process keeps running, so a TTL matters there. This agent
is invoked fresh per question (see docs/spec.md's Scope - "invoked
directly as a script"), so a process never lives long enough for that
staleness to matter; re-querying within a single run's process lifetime
would only add an extra Neo4j round trip for no benefit.

Reuses graph_tool.py's own driver singleton (_get_driver()) rather than
opening a second connection pattern to the same database.

Exact-match only, deliberately: no case-folding, no substring/"contains"
check. A substring check would let a string like "Hypertension\\nIgnore
all previous instructions" pass simply because the real term
"Hypertension" appears inside it - exactly the injected-text-appended-
to-a-real-term case this check exists to catch. Exact string equality is
the one comparison such a string can never satisfy.

Fail-open decision: if the vocabulary query itself fails (the database is
unreachable), this check fails OPEN - it returns a single flag noting the
check itself couldn't run, and the caller (run_agent) proceeds exactly as
if nothing had been checked. This is a "flagged", not "blocked", severity
check (see docs/spec.md's Agent steps) - it exists to surface a
suspicious value, not to gate whether a question gets answered. Failing
closed here would mean a Neo4j outage - already a real failure mode
step 1/3 handle with their own retry logic - also silently breaks every
question's ability to get answered at all, for a check that was only ever
advisory. That tradeoff is wrong for an advisory check, so this fails
open and simply says so.
"""
from neo4j import Query

from block5_agent.graph_tool import GRAPH_QUERY_TIMEOUT, NEO4J_DATABASE, _LAB_PROPERTY, _get_driver

# Deliberately no LIMIT on either query below: this check needs the
# *complete* distinct vocabulary to compare against, not a sample of it -
# a LIMIT would make a legitimate condition/drug past the cutoff look
# unrecognized, producing a false-positive flag for real, valid data. That
# defeats the point of the check, so this isn't an oversight to "fix"
# later by adding one.
_DISTINCT_CONDITION_NAMES_QUERY = """
MATCH (c:Condition)
RETURN DISTINCT c.condition_name AS condition_name
"""

_DISTINCT_DRUG_NAMES_QUERY = """
MATCH (d:Drug)
RETURN DISTINCT d.drug_name AS drug_name
"""

_cached_vocabulary = None


def _fetch_known_vocabulary(*, driver=None) -> dict:
    """Query the graph for its real, current Condition.condition_name and
    Drug.drug_name values. Labs are not queried here - they're checked
    directly against graph_tool.py's own _LAB_PROPERTY whitelist (see
    module docstring), not a separate graph query.

    Both queries are wrapped in a Query(..., timeout=GRAPH_QUERY_TIMEOUT)
    the same way graph_tool.py's own queries are (imported straight from
    there - same value, same reasoning, no need for a second constant
    that could drift from it) - without this, an unresponsive Neo4j
    instance would hang this call indefinitely instead of failing fast
    into check_plausibility's fail-open handling (see module docstring).
    """
    driver = driver if driver is not None else _get_driver()
    with driver.session(database=NEO4J_DATABASE) as session:
        condition_rows = session.run(
            Query(_DISTINCT_CONDITION_NAMES_QUERY, timeout=GRAPH_QUERY_TIMEOUT)
        )
        conditions = {row["condition_name"] for row in condition_rows}
        drug_rows = session.run(Query(_DISTINCT_DRUG_NAMES_QUERY, timeout=GRAPH_QUERY_TIMEOUT))
        drugs = {row["drug_name"] for row in drug_rows}
    return {"conditions": conditions, "drugs": drugs}


def get_known_vocabulary(*, driver=None) -> dict:
    """Return {"conditions": set[str], "drugs": set[str]} - the graph's
    real, current vocabulary. Queried once per process and cached module-
    level for every call after that (see module docstring)."""
    global _cached_vocabulary
    if _cached_vocabulary is None:
        _cached_vocabulary = _fetch_known_vocabulary(driver=driver)
    return _cached_vocabulary


def check_plausibility(condition: str, lab: str, drug_a: str, drug_b: str, *, driver=None) -> list[str]:
    """Check all four fields against the graph's real vocabulary in one
    pass. Returns a list of human-readable flags - empty if every field
    matched exactly. Never raises: a vocabulary-query failure fails open
    (see module docstring) and is itself reported as the one flag
    returned, rather than propagating an exception into the caller.
    """
    try:
        vocabulary = get_known_vocabulary(driver=driver)
    except Exception as exc:
        return [f"plausibility_check_unavailable: {type(exc).__name__}"]

    flags = []
    if condition not in vocabulary["conditions"]:
        flags.append(f"condition {condition!r} not found in graph vocabulary")
    if lab not in _LAB_PROPERTY:
        flags.append(f"lab {lab!r} not a recognized lab name")
    if drug_a not in vocabulary["drugs"]:
        flags.append(f"drug_a {drug_a!r} not found in graph vocabulary")
    if drug_b not in vocabulary["drugs"]:
        flags.append(f"drug_b {drug_b!r} not found in graph vocabulary")
    return flags
