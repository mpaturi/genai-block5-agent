# genai-block5-agent

Single-agent clinical reasoning app — a LangGraph agent that chains Block 4's RAG service (fuzzy semantic patient search) with Block 3's Neo4j graph (exact drug counts) to answer clinical questions neither tool can answer alone, with structured, validated, traced output.

Full design reasoning lives in `docs/spec.md`; this file covers setup and how the project was built.

## Setup

1. Python 3.11, then create and activate a virtual environment (`.venv`, matching Block 3/4 naming).
2. Install pinned dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Copy the env template and fill in real credentials:
   ```
   cp .env.example .env
   ```
   Required: `NEO4J_PASSWORD`, `LANGCHAIN_API_KEY`, `ANTHROPIC_API_KEY`. `RAG_API_URL`, `NEO4J_URI`/`NEO4J_USER`/`NEO4J_DATABASE`, and `LANGCHAIN_PROJECT` default to sensible local values (see `.env.example`).
4. Start Block 3's Neo4j and Block 4's RAG API first — this repo doesn't start either itself:
   ```
   # In genai-block3-graph-kb/
   docker compose up -d

   # In genai-block4-rag-eval/
   uvicorn scripts.api:app --port 8000
   ```
5. Run the one-command setup check:
   ```
   python -m scripts.run_all
   ```
   Confirms the search service, graph database, language model key, and LangSmith tracing are all reachable, then runs one real example question through the agent as an end-to-end smoke test.
6. Run the eval harness separately, on demand (not part of `run_all.py`):
   ```
   python -m scripts.run_eval
   ```
   Runs the real agent against every question in `data/eval/tasks.json`, scores all three dimensions from `docs/spec.md`'s Evaluation section, and writes the report to `docs/eval_results.md`. Exits non-zero if the score drops below 0.70.
7. Run the unit test suite:
   ```
   pytest
   ```

## Architecture

```
question (structured: condition/lab/comparison/value/drug_a/drug_b)
       |
       v
+------------+
|   search   |  Block 4's POST /query, built from condition/lab/comparison/value only
+------------+
       |
  retrieved_count == 0? --yes--> fixed "nothing found" answer --> END
       | no
       v
+------------+
|   count    |  Block 3's Neo4j, one fixed Cypher query over the found patient IDs
+------------+
       |
       v
+------------+
| synthesize |  Claude writes one sentence from the two named drugs' counts
+------------+
       |
       v
      END
```

Each of the three steps retries on a transient failure (2 retries for the two tools, 1 for the answer-writing step) before degrading to fixed, tested wording — see `docs/spec.md`'s Agent steps and Exact wording for each outcome. Every run is traced end to end in LangSmith and logged to `data/logs/runs.jsonl` with per-step latency, token counts, and estimated cost.

See `docs/spec.md` for the full reasoning behind every design decision (why `drug_a`/`drug_b` are excluded from the RAG query, the confidence-tier thresholds, the shared query-building/dedupe/confidence functions, etc.), and `docs/eval_results.md` for the eval run results.

## Project structure

```
scripts/    Agent code - see docs/spec.md's Agent steps for how each file fits together
tests/      pytest unit tests, written before their implementation existed (TDD) -
            tools are tested with mocked HTTP/Neo4j, the agent with swappable fakes,
            none needs a live service running
data/eval/  Fixed eval question set (tasks.json) and its golden answer key (answer_key.json)
data/logs/  Generated per-run logs (runs.jsonl) - not committed
docs/       spec.md, plan.md, tasks.md, eval_results.md
```

## AI-assisted workflow

This project was built with [Claude Code](https://claude.com/claude-code) (Anthropic's CLI) working alongside a human developer, following a spec-first workflow: `docs/spec.md` (what and why) was written and iterated on before `docs/plan.md` (what to build and in what order) or any code. Each phase got its own branch.

Notable practices used throughout:
- **Test-driven development.** `tests/test_rag_tool.py`, `tests/test_graph_tool.py`, and `tests/test_agent_answers.py` were all written before `scripts/rag_tool.py`, `scripts/graph_tool.py`, and `scripts/agent.py` existed, confirmed to fail with `ModuleNotFoundError` first, then made to pass without changing the tests.
- **Real services exercised during development, not just mocked.** Block 3's Neo4j and Block 4's RAG API were both run live throughout Phase 3 - `scripts/build_eval_answer_key.py`'s output was spot-checked against direct Cypher queries by hand, and `scripts/rag_tool.py`/`scripts/graph_tool.py` were each tried against the real services beyond their unit tests.
- **Ground truth computed, not hand-typed, and grounded in the live graph.** `data/eval/tasks.json`'s questions were chosen after querying the live graph for its actual whitelist of conditions/drugs/labs and testing real retrieval counts against the live RAG API, so the fixed eval set is confirmed to exercise all three confidence tiers rather than assumed to.
- **Shared logic lives in exactly one place.** `scripts/schemas.py` holds the RAG-query-building, patient-ID dedupe/ordering, and confidence-tier functions that both the real agent and `scripts/build_eval_answer_key.py` import - never two independently written copies that could silently drift apart.
