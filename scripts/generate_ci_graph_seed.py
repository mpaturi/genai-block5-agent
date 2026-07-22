"""One-off script: builds a synthetic Neo4j seed graph for CI, from
data/eval/tasks.json, data/eval/answer_key.json, and
data/eval/rag_fixtures.json. Not part of CI itself - run manually, once,
and commit the result (data/eval/ci_graph_seed.cypher). Re-run only if
answer_key.json or rag_fixtures.json change.

Tool 2 now verifies each candidate patient against the graph's own stored
condition and lab data before counting drugs (see docs/spec.md's Tool 2),
so the seed has to carry that data too, not just Patient/Drug/PRESCRIBED.
answer_key.json only records patients_checked as a count, not which
specific patient IDs verified - that information doesn't exist anywhere,
so this script picks deterministically: for each answerable task, the
first patients_checked patient IDs (in that task's RAG order) get a
HAS_CONDITION relationship to that task's condition and a lab property
value that satisfies its comparison. Every other patient gets neither -
not a failing lab value, just no condition or lab data at all, which
fails every possible verification check unconditionally.

For each answerable task, every drug in that task's golden graph_result
(not just drug_a/drug_b) gets assigned enough of that task's *verified*
patients to reproduce that drug's exact count when graph_tool.py's fixed
query runs against the seeded graph - preferring patients not yet
assigned to anything, then wrapping around to reuse already-assigned
patients once that pool runs dry (some tasks' graph_result counts sum to
more than the number of patients verified, since a real patient can be on
more than one drug).

Processing order is fixed - tasks.json's array order, then each task's
graph_result key order - so re-running this script on unchanged input
always produces byte-identical output.

A patient ID appearing in more than one answerable task's RAG results
(confirmed to happen in practice, now that real recall is much higher -
one real patient here genuinely has both Pulmonary embolism and
Congestive heart failure) is not automatically wrong to verify for more
than one task: HAS_CONDITION edges to different condition names never
conflict, and a shared lab property (e.g. SBP for both tasks above) gets
one combined value satisfying every sharing task's comparison at once
(the tightest bound across all of them) - raising loudly if two sharing
tasks' bounds are genuinely incompatible (e.g. "above 140" and "below
100" on the same property), since that would mean the real data itself
was self-contradictory.

Drug assignment is where sharing actually is unsafe: graph_tool.py's
drug-count query is scoped to whichever patient IDs pass verification for
ONE task, so if a shared patient held a PRESCRIBED edge assigned for a
different task, that edge would leak into this task's counted results
the moment the shared patient also verifies for this task. So a shared
patient (by raw candidate-list membership, independent of whether it ends
up in patients_checked) is still never chosen to hold a drug for any
task - only patients exclusive to one task's candidate list are eligible
for drug assignment, with the same not-enough-patients error as before if
a task's exclusive pool is empty while it still needs to assign a drug.
"""
import json
from pathlib import Path

from scripts.schemas import QuestionInput, build_rag_query

TASKS_PATH = Path("data/eval/tasks.json")
ANSWER_KEY_PATH = Path("data/eval/answer_key.json")
FIXTURES_PATH = Path("data/eval/rag_fixtures.json")
SEED_PATH = Path("data/eval/ci_graph_seed.cypher")

# This script's own copy - not imported from graph_tool.py or
# build_eval_answer_key.py, since this is a seed generator, not a check
# that stands independently of the code being tested.
_LAB_PROPERTY = {
    "SBP": "latest_sbp",
    "BMI": "latest_bmi",
    "Glucose": "latest_glucose",
    "HbA1c": "latest_hba1c",
}
# A satisfying value is the task's threshold shifted by this margin, in
# the direction that satisfies a strict >/< comparison.
_SATISFYING_MARGIN = 1


def _assign_patients_to_drugs(patient_ids: list[int], graph_result: dict) -> list[tuple[int, str]]:
    """Prefer patients not yet assigned to anything; once that pool is
    empty, wrap around and reuse already-assigned patients (in patient_ids
    order) so every drug's count is always fully satisfied."""
    unassigned = list(patient_ids)
    assignments = []
    for drug_name, count in graph_result.items():
        chosen = []
        while len(chosen) < count and unassigned:
            chosen.append(unassigned.pop(0))
        wrap_index = 0
        while len(chosen) < count:
            candidate = patient_ids[wrap_index % len(patient_ids)]
            wrap_index += 1
            if candidate not in chosen:
                chosen.append(candidate)
        for person_id in chosen:
            assignments.append((person_id, drug_name))
    return assignments


def _resolve_combined_lab_value(constraints: list[tuple[str, float]]) -> float:
    """Combine every sharing task's (comparison, threshold) constraint on
    one lab property into a single value that satisfies all of them at
    once - the tightest "above" bound and the tightest "below" bound,
    meeting in the middle if a patient is constrained from both sides.
    Raises if the bounds don't leave any valid value, since that would
    mean the real data was self-contradictory, not a generator bug.
    """
    above_thresholds = [t for c, t in constraints if c == "above"]
    below_thresholds = [t for c, t in constraints if c == "below"]

    lower_bound = max(above_thresholds) if above_thresholds else None
    upper_bound = min(below_thresholds) if below_thresholds else None

    if lower_bound is not None and upper_bound is not None:
        if lower_bound >= upper_bound:
            raise RuntimeError(
                f"impossible combined lab constraint: needs > {lower_bound} "
                f"and < {upper_bound} at the same time"
            )
        return (lower_bound + upper_bound) / 2
    if lower_bound is not None:
        return lower_bound + _SATISFYING_MARGIN
    return upper_bound - _SATISFYING_MARGIN


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _task_patient_ids(task: dict, fixtures: dict) -> list[int]:
    question = QuestionInput(
        condition=task["condition"],
        lab=task["lab"],
        comparison=task["comparison"],
        value=task["value"],
        drug_a=task["drug_a"],
        drug_b=task["drug_b"],
    )
    query_text = build_rag_query(question)
    return fixtures[query_text]["patient_ids"]


def main() -> None:
    tasks = json.loads(TASKS_PATH.read_text())
    answer_key = json.loads(ANSWER_KEY_PATH.read_text())
    fixtures = json.loads(FIXTURES_PATH.read_text())

    answerable_tasks = [t for t in tasks if t["answerable"]]

    # A patient given data for one task would leak into any other task
    # whose patient list also includes it - so any patient shared by more
    # than one answerable task never gets a condition, lab value, or drug.
    task_count_by_patient: dict[int, int] = {}
    for task in answerable_tasks:
        for person_id in _task_patient_ids(task, fixtures):
            task_count_by_patient[person_id] = task_count_by_patient.get(person_id, 0) + 1
    shared_patient_ids = {pid for pid, count in task_count_by_patient.items() if count > 1}

    # Plain dicts used as ordered sets/maps - insertion order is preserved
    # and deterministic given the same input files, which is what keeps
    # re-runs byte-identical.
    patient_ids_seen: dict[int, None] = {}
    condition_names_seen: dict[str, None] = {}
    drug_names_seen: dict[str, None] = {}
    has_condition_pairs_seen: dict[tuple[int, str], None] = {}
    prescribed_pairs_seen: dict[tuple[int, str], None] = {}
    # person_id -> lab_property -> list of (comparison, threshold), one
    # entry per sharing task - resolved to a single value per property
    # only after every task has contributed its constraint.
    patient_lab_constraints: dict[int, dict[str, list[tuple[str, float]]]] = {}
    task_verified_ids: dict[str, list[int]] = {}

    for task in answerable_tasks:
        patient_ids = _task_patient_ids(task, fixtures)
        patients_checked = answer_key[task["id"]]["patients_checked"]
        condition_names_seen.setdefault(task["condition"], None)

        for person_id in patient_ids:
            patient_ids_seen.setdefault(person_id, None)

        verified_ids = patient_ids[:patients_checked]
        task_verified_ids[task["id"]] = verified_ids

        lab_property = _LAB_PROPERTY[task["lab"]]
        for person_id in verified_ids:
            has_condition_pairs_seen.setdefault((person_id, task["condition"]), None)
            patient_lab_constraints.setdefault(person_id, {}).setdefault(
                lab_property, []
            ).append((task["comparison"], task["value"]))

    patient_lab_values: dict[int, dict[str, float]] = {
        person_id: {
            lab_property: _resolve_combined_lab_value(constraints)
            for lab_property, constraints in properties.items()
        }
        for person_id, properties in patient_lab_constraints.items()
    }

    for task in answerable_tasks:
        graph_result = answer_key[task["id"]]["graph_result"]
        if not graph_result:
            continue

        verified_ids = task_verified_ids[task["id"]]
        # Only patients exclusive to this task's own candidate list are
        # eligible to hold a drug - a shared patient's PRESCRIBED edge
        # would leak into every other task it also verifies for.
        eligible_for_drugs = [pid for pid in verified_ids if pid not in shared_patient_ids]
        if not eligible_for_drugs:
            raise RuntimeError(
                f"task {task['id']}: every verified patient is shared with another "
                "task, so there's no one left to safely hold a drug without "
                "cross-task contamination"
            )

        for person_id, drug_name in _assign_patients_to_drugs(eligible_for_drugs, graph_result):
            drug_names_seen.setdefault(drug_name, None)
            prescribed_pairs_seen.setdefault((person_id, drug_name), None)

    lines = []
    for person_id in patient_ids_seen:
        lab_properties = patient_lab_values.get(person_id)
        if lab_properties:
            props = ", ".join(
                f"{prop}: {value}" for prop, value in lab_properties.items()
            )
            lines.append(f"CREATE (:Patient {{person_id: {person_id}, {props}}});")
        else:
            lines.append(f"CREATE (:Patient {{person_id: {person_id}}});")
    for condition_name in condition_names_seen:
        lines.append(f"MERGE (:Condition {{condition_name: '{_escape(condition_name)}'}});")
    for drug_name in drug_names_seen:
        lines.append(f"MERGE (:Drug {{drug_name: '{_escape(drug_name)}'}});")
    for person_id, condition_name in has_condition_pairs_seen:
        lines.append(
            f"MATCH (p:Patient {{person_id: {person_id}}}), "
            f"(c:Condition {{condition_name: '{_escape(condition_name)}'}}) "
            f"CREATE (p)-[:HAS_CONDITION]->(c);"
        )
    for person_id, drug_name in prescribed_pairs_seen:
        lines.append(
            f"MATCH (p:Patient {{person_id: {person_id}}}), "
            f"(d:Drug {{drug_name: '{_escape(drug_name)}'}}) "
            f"CREATE (p)-[:PRESCRIBED]->(d);"
        )

    SEED_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} statements to {SEED_PATH}")


if __name__ == "__main__":
    main()
