"""One-off script: captures real RAG API responses for every task in
data/eval/tasks.json, so CI can replay them without needing a live RAG
service or Pinecone/Anthropic access (see scripts/run_eval.py's
USE_RAG_FIXTURES support). Not part of CI itself - run manually, once,
and commit the result. Re-run only if the underlying patient data or eval
questions change.
"""
import json
from pathlib import Path

from scripts.rag_tool import search_patients
from scripts.schemas import QuestionInput, build_rag_query

TASKS_PATH = Path("data/eval/tasks.json")
FIXTURES_PATH = Path("data/eval/rag_fixtures.json")


def main() -> None:
    tasks = json.loads(TASKS_PATH.read_text())
    fixtures = {}

    for task in tasks:
        question = QuestionInput(
            condition=task["condition"],
            lab=task["lab"],
            comparison=task["comparison"],
            value=task["value"],
            drug_a=task["drug_a"],
            drug_b=task["drug_b"],
        )
        query_text = build_rag_query(question)
        if query_text in fixtures:
            continue  # same query text already captured for an earlier task
        fixtures[query_text] = search_patients(
            query_text,
            question.condition,
            question.lab,
            question.comparison,
            question.value,
            top_k=20,
        )

    FIXTURES_PATH.write_text(json.dumps(fixtures, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(fixtures)} RAG fixtures to {FIXTURES_PATH}")


if __name__ == "__main__":
    main()
