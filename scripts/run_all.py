"""One-command setup check: confirms every external dependency is
reachable (scripts/check_connection.py), then runs one real example
question through the agent as an end-to-end smoke test.

There's no data pipeline of Block 5's own to run here - RAG and the graph
are already Block 3/4's completed pipelines, this repo only calls them.
Does NOT run scripts/run_eval.py, which stays a separate, deliberate
command you run on purpose (mirrors Block 3/4's run_all.py convention).

Run with: python -m scripts.run_all (from the repo root).
"""
import sys

from scripts import check_connection
from scripts.agent import run_agent
from scripts.schemas import QuestionInput

_SMOKE_TEST_QUESTION = QuestionInput(
    condition="Essential hypertension",
    lab="SBP",
    comparison="above",
    value=140,
    drug_a="Lisinopril",
    drug_b="Amlodipine",
)


def main() -> int:
    print("=== check_connection ===")
    try:
        check_connection.main()
    except SystemExit as exc:
        code = exc.code or 0
        if code != 0:
            print(f"\nFAIL - check_connection failed (exit code {code}). Stopping.")
            return code

    print("\n=== smoke test: one real question through the agent ===")
    answer, count_step_ran = run_agent(_SMOKE_TEST_QUESTION)
    print(answer.model_dump_json(indent=2))
    print(f"count_step_ran: {count_step_ran}")

    print("\nrun_all.py complete - setup check and a real agent run both succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
