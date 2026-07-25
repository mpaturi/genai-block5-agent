"""Runs the fixed eval task set through the real agent and scores three
dimensions per question (see docs/spec.md's Evaluation). Writes a score
report to docs/eval_results.md.
"""
import json
import sys
from pathlib import Path

from scripts.agent import run_agent
from scripts.schemas import QuestionInput

TASKS_PATH = Path("data/eval/tasks.json")
ANSWER_KEY_PATH = Path("data/eval/answer_key.json")
RESULTS_PATH = Path("docs/eval_results.md")

# See docs/spec.md's CI gate.
THRESHOLD = 0.70


def _check_tool_call_correctness(task: dict, count_step_ran: bool) -> bool:
    """The count step should have run iff the question is answerable
    (see docs/spec.md's Evaluation, check 1)."""
    return count_step_ran == task["answerable"]


def _check_structured_output_validity(answer) -> bool:
    """caveat must be non-empty whenever confidence is low/medium, and
    empty when it's high (see docs/spec.md's Evaluation, check 2)."""
    if answer.confidence in ("low", "medium"):
        return bool(answer.caveat)
    return answer.caveat is None


def _check_answer_accuracy(task: dict, answer, golden: dict | None) -> bool:
    """Exact match against the golden patient list, count, and confidence
    for answerable questions; empty result + low confidence for
    deliberately unanswerable ones (see docs/spec.md's Evaluation, check 3)."""
    if task["answerable"]:
        return (
            answer.rag_patient_ids == golden["rag_patient_ids"]
            and answer.graph_result == golden["graph_result"]
            and answer.confidence == golden["confidence"]
        )
    return (
        answer.rag_patient_ids == []
        and answer.graph_result == {}
        and answer.confidence == "low"
    )


def run_evaluation() -> dict:
    tasks = json.loads(TASKS_PATH.read_text())
    answer_key = json.loads(ANSWER_KEY_PATH.read_text())

    results = []
    for task in tasks:
        question = QuestionInput(
            condition=task["condition"],
            lab=task["lab"],
            comparison=task["comparison"],
            value=task["value"],
            drug_a=task["drug_a"],
            drug_b=task["drug_b"],
        )
        answer, count_step_ran = run_agent(question)
        golden = answer_key.get(task["id"])

        checks = {
            "tool_call_correctness": _check_tool_call_correctness(task, count_step_ran),
            "structured_output_validity": _check_structured_output_validity(answer),
            "answer_accuracy": _check_answer_accuracy(task, answer, golden),
        }
        results.append(
            {
                "id": task["id"],
                "answerable": task["answerable"],
                "checks": checks,
                "passed": all(checks.values()),
            }
        )

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    score = passed_count / total if total else 0.0
    return {"results": results, "score": score, "passed": passed_count, "total": total}


def _mark(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _write_report(summary: dict) -> None:
    lines = [
        "# Eval Results",
        "",
        "This file is produced by `scripts/run_eval.py`, run against the real "
        "agent (real search service, real graph, real language model) per "
        "`docs/spec.md`'s Evaluation section.",
        "",
        f"**Task success rate: {summary['score']:.3f} "
        f"({summary['passed']}/{summary['total']})** — CI gate threshold is "
        f"{THRESHOLD:.2f} (see `docs/spec.md`'s CI gate).",
        "",
        "| Question | Answerable | Tool-call correctness | Structured output validity | Answer accuracy | Passed |",
        "|---|---|---|---|---|---|",
    ]
    for r in summary["results"]:
        c = r["checks"]
        lines.append(
            f"| {r['id']} | {r['answerable']} | "
            f"{_mark(c['tool_call_correctness'])} | "
            f"{_mark(c['structured_output_validity'])} | "
            f"{_mark(c['answer_accuracy'])} | "
            f"{_mark(r['passed'])} |"
        )
    lines.append("")
    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    summary = run_evaluation()
    _write_report(summary)
    print(f"Task success rate: {summary['score']:.3f} ({summary['passed']}/{summary['total']})")
    if summary["score"] < THRESHOLD:
        print(f"FAIL: below the {THRESHOLD:.2f} threshold", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
