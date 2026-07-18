# Block 5 Plan

This document covers what gets built, in what order, and why that order —
the reasoning behind each decision lives in `docs/spec.md`.

## Build order, in short

The test questions and answer object come first, since nothing else can
be checked without them. The two tools come next, each with its own tests
written before the tool exists. The agent that connects the tools comes
after both tools work on their own. Logging and the evaluation runner come
last, once there's a real agent to measure. CI is added only once the
evaluation itself works locally.

## File map

| File | Purpose |
|---|---|
| `requirements.txt`, `.env.example`, `.gitignore` | project setup — see `docs/spec.md`'s Technology and Configuration sections for what goes in each |
| `scripts/check_connection.py` | confirms the search service, the graph database, the language model key, and the tracing service are all reachable |
| `scripts/schemas.py` | the answer object, the agent's internal state, and the structured question input (`condition`, `lab`, `comparison`, `value`, `drug_a`, `drug_b`) |
| `data/eval/tasks.json` | the fixed set of test questions, each with an ID; each question is stored as separate `condition`, `lab`, `comparison`, `value`, `drug_a`, `drug_b` fields, not as one opaque string (see `docs/spec.md`'s Question pattern) — the assembled full-text question is derived from these fields for display/logging only |
| `scripts/build_eval_answer_key.py` | reads `data/eval/tasks.json` and writes `data/eval/answer_key.json` — the correct patient list, drug count, and expected `confidence` for each answerable question, keyed by the same question ID, worked out once, ahead of time by making its own throwaway calls straight to the live search service and live graph, since `rag_tool.py`/`graph_tool.py` don't exist yet at this point; the call to the search service is built from the same `condition`/`lab`/`comparison`/`value` fields the real agent will use (see `docs/spec.md`'s What the agent does), never the assembled full question and never `drug_a`/`drug_b`, so the golden patient list matches what the agent actually produces; the raw result is deduped and ordered using Tool 1's exact rule (score descending, ties broken by patient ID) before being written, so the exact-match check on `rag_patient_ids` (an ordered list) is comparing against a golden list built the same way the agent builds its own |
| `tests/test_rag_tool.py`, `tests/test_graph_tool.py` | tests for each tool, written before the tool exists |
| `tests/test_agent_answers.py` | tests that every fixed-wording answer (nothing found, search broken, graph broken, answer step failed) matches `docs/spec.md`'s outcome table exactly, without needing the real search service, graph database, or language model |
| `scripts/rag_tool.py` | semantic search tool |
| `scripts/graph_tool.py` | exact drug count tool |
| `scripts/agent.py` | the agent itself — the steps described in `docs/spec.md`'s Agent steps section, built so the two tools and the step 4 language-model call can all be swapped for fakes in tests; returns whether the count step ran alongside the answer object, for `run_eval.py` to read directly |
| `scripts/logging_utils.py` | writes one log entry per run |
| `scripts/run_eval.py`, `docs/eval_results.md` | reads `data/eval/tasks.json` and `data/eval/answer_key.json`, runs the evaluation, saves the score |
| `.github/workflows/ci.yml` | runs tests and the evaluation on every push |
| `scripts/run_all.py`, `README.md` | one-command setup check, and setup docs |

## Notes on build order

- The project's virtual environment is set up when implementation starts,
  not during the spec/plan/tasks step — there's no code to run yet at that
  point.
- Tool tests are written and confirmed failing before each tool is built.
  This proves the test would actually catch a missing or broken tool. The
  test covering all four fixed-wording answers (nothing found, search
  broken, graph broken, answer step failed) is written the same way,
  before the agent exists, since that wording is fixed and doesn't depend
  on a real tool call to check.
- The evaluation runner calls the real agent, not the tools directly —
  since one of the three things it checks is whether the final answer
  object is valid, which only exists once the whole agent runs.
- Logging is wired in before the evaluation runner, so the first real
  evaluation run also produces a real log entry to sanity-check.
- CI is the last piece added, once everything it runs (tests, evaluation)
  already passes locally. Exactly how the search service, graph database,
  and language model are made reachable inside CI still needs to be
  decided at this step — see `docs/spec.md`'s Known limitations, which
  also covers the real, ongoing API cost this brings (the score itself
  stays deterministic — only cost and latency are affected).
