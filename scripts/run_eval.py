"""Runs the fixed eval task set through the real agent and scores three
dimensions per question (see docs/spec.md's Evaluation). Writes a score
report to docs/eval_results.md.
"""
import json
import os
import sys
from pathlib import Path

from scripts.agent import run_agent
from scripts.schemas import QuestionInput

TASKS_PATH = Path("data/eval/tasks.json")
ANSWER_KEY_PATH = Path("data/eval/answer_key.json")
FIXTURES_PATH = Path("data/eval/rag_fixtures.json")
RESULTS_PATH = Path("docs/eval_results.md")

# See docs/spec.md's CI gate.
THRESHOLD = 0.70


def _make_fixture_search_fn():
    """A search_fn backed by scripts/capture_rag_fixtures.py's recorded
    responses, for CI - which has no live RAG service to call. Only the
    search step is faked; count_fn and answer_fn always stay real."""
    fixtures = json.loads(FIXTURES_PATH.read_text())

    def _search_fn(
        query_text: str, condition=None, lab=None, comparison=None, value=None, top_k: int = 25
    ) -> dict:
        if query_text not in fixtures:
            raise RuntimeError(
                f"USE_RAG_FIXTURES is set, but no fixture is recorded for query "
                f"text {query_text!r}. Re-run scripts/capture_rag_fixtures.py "
                "if data/eval/tasks.json changed."
            )
        return fixtures[query_text]

    return _search_fn


def _stub_answer_fn(question, rag_patient_ids, drug_a_count, drug_b_count) -> str:
    """A stub answer_fn for CI - no real Claude call, no token usage to
    report. None of the three scored dimensions ever read the free-text
    answer's content (see docs/spec.md's Known limitations), so the scored
    evaluation doesn't need a real model call to be scored correctly."""
    return "Stub answer for CI - not a real model response."


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

    run_agent_kwargs = {}
    if os.environ.get("USE_RAG_FIXTURES"):
        run_agent_kwargs["search_fn"] = _make_fixture_search_fn()
    if os.environ.get("USE_STUB_ANSWER_FN"):
        run_agent_kwargs["answer_fn"] = _stub_answer_fn

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
        answer, count_step_ran = run_agent(question, **run_agent_kwargs)
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


def _describe_run_mode() -> str:
    """States the truth about what this specific run actually used - never
    a fixed claim, since search and the answer-writing step can each be
    stubbed independently (see USE_RAG_FIXTURES/USE_STUB_ANSWER_FN above).
    The graph is never stubbed, so that part is unconditional."""
    search_desc = (
        "recorded RAG fixtures, not the real search service"
        if os.environ.get("USE_RAG_FIXTURES")
        else "the real search service"
    )
    answer_desc = (
        "a stub answer-writing function, not the real language model"
        if os.environ.get("USE_STUB_ANSWER_FN")
        else "the real language model"
    )
    return f"the real graph, {search_desc}, and {answer_desc}"


def _write_report(summary: dict) -> None:
    lines = [
        "# Eval Results",
        "",
        "This file is produced by `scripts/run_eval.py`, run against "
        f"{_describe_run_mode()}, per `docs/spec.md`'s Evaluation section.",
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
