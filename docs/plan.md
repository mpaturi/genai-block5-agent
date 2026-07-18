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
| `scripts/check_connection.py` | confirms the search service, the graph database, and the language model key are all reachable |
| `scripts/schemas.py` | the answer object and the agent's internal state |
| `data/eval/tasks.json` | the fixed set of test questions |
| `scripts/build_eval_answer_key.py` | works out the correct answer for each test question, once, ahead of time |
| `tests/test_rag_tool.py`, `tests/test_graph_tool.py` | tests for each tool, written before the tool exists |
| `tests/test_agent_answers.py` | tests that every fixed-wording answer (nothing found, search broken, graph broken, answer step failed) matches `docs/spec.md`'s outcome table exactly, without needing the real search service or graph database |
| `scripts/rag_tool.py` | semantic search tool |
| `scripts/graph_tool.py` | exact drug count tool |
| `scripts/agent.py` | the agent itself — the steps described in `docs/spec.md`'s Agent steps section |
| `scripts/logging_utils.py` | writes one log entry per run |
| `scripts/run_eval.py`, `docs/eval_results.md` | runs the evaluation, saves the score |
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
  already passes locally. Exactly how the search service and graph
  database are made reachable inside CI still needs to be decided at this
  step — see `docs/spec.md`'s Known limitations.
