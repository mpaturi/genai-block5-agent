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
first patients_checked patient IDs (in that task's RAG order, among
patients exclusive to that task - see below) get a HAS_CONDITION
relationship to that task's condition and a lab property value that
satisfies its comparison. Every other patient gets neither - not a
failing lab value, just no condition or lab data at all, which fails
every possible verification check unconditionally.

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

Patients whose ID appears in more than one answerable task's RAG results
(confirmed to happen in practice - two tasks here share two patients)
never get a condition, a lab value, or a drug assigned, in any task: the
seeded graph is one shared graph, and a query for one task's patient IDs
has no way to exclude data that was really set for a different task's
purposes. A shared patient still gets its :Patient node either way; it
just never gets anything that could make it incorrectly pass verification
or incorrectly count toward a drug, for any task.
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


def _satisfying_lab_value(comparison: str, value: float) -> float:
    if comparison == "above":
        return value + _SATISFYING_MARGIN
    return value - _SATISFYING_MARGIN


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
    patient_lab_property: dict[int, tuple[str, float]] = {}

    for task in answerable_tasks:
        patient_ids = _task_patient_ids(task, fixtures)
        patients_checked = answer_key[task["id"]]["patients_checked"]
        graph_result = answer_key[task["id"]]["graph_result"]
        condition_names_seen.setdefault(task["condition"], None)

        for person_id in patient_ids:
            patient_ids_seen.setdefault(person_id, None)

        exclusive_candidates = [pid for pid in patient_ids if pid not in shared_patient_ids]
        if len(exclusive_candidates) < patients_checked:
            raise RuntimeError(
                f"task {task['id']}: only {len(exclusive_candidates)} patients are "
                f"exclusive to this task, but {patients_checked} need to verify - "
                "this generator can't do that without cross-task contamination"
            )
        verified_ids = exclusive_candidates[:patients_checked]

        lab_property = _LAB_PROPERTY[task["lab"]]
        satisfying_value = _satisfying_lab_value(task["comparison"], task["value"])
        for person_id in verified_ids:
            patient_lab_property[person_id] = (lab_property, satisfying_value)
            has_condition_pairs_seen.setdefault((person_id, task["condition"]), None)

        if not graph_result:
            continue

        for person_id, drug_name in _assign_patients_to_drugs(verified_ids, graph_result):
            drug_names_seen.setdefault(drug_name, None)
            prescribed_pairs_seen.setdefault((person_id, drug_name), None)

    lines = []
    for person_id in patient_ids_seen:
        if person_id in patient_lab_property:
            lab_property, lab_value = patient_lab_property[person_id]
            lines.append(
                f"CREATE (:Patient {{person_id: {person_id}, {lab_property}: {lab_value}}});"
            )
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
