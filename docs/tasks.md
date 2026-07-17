# Block 5 Tasks

Four phases, each on its own branch, each with its own pull request.
Every phase branches from the tip of the previous phase's branch (or from
`main`, if the previous phase's PR has already merged by then).

## Phase 1 — Spec, Plan, Tasks (`phase-1-spec`, base: `main`)

No code this phase.

- [ ] Write `docs/spec.md`
- [ ] Write `docs/plan.md`
- [ ] Write `docs/tasks.md`
- [ ] Commit all three, push, open PR (base `main`)

## Phase 2 — Tests first (`phase-2-tdd`, base: `phase-1-spec`)

The agent doesn't exist yet — this phase only writes down what "correct"
looks like.

- [ ] Write `scripts/schemas.py` (the answer object and agent state)
- [ ] Write `data/eval/tasks.json` — at least 10 test questions (at least
      7 answerable, at least 3 deliberately unanswerable)
- [ ] Write `scripts/build_eval_answer_key.py` and run it to work out the
      correct answer for each answerable question
- [ ] Spot-check a few of those correct answers by hand
- [ ] Write `tests/test_rag_tool.py` and `tests/test_graph_tool.py`
- [ ] Run the tests — confirm they fail (the tools don't exist yet)
- [ ] Commit, push, open PR (base `phase-1-spec`)

## Phase 3 — Build it (`phase-3-implement`, base: `phase-2-tdd`)

- [ ] Set up `requirements.txt`, `.env.example`, virtual environment
- [ ] Write `scripts/check_connection.py` — confirm the search service,
      graph database, and language model key are all reachable
- [ ] Write `scripts/rag_tool.py` — get its tests passing
- [ ] Try a real search by hand
- [ ] Write `scripts/graph_tool.py` — get its tests passing
- [ ] Try a real count by hand
- [ ] Write `scripts/agent.py`
- [ ] Run the example question end-to-end — confirm a valid answer
- [ ] Run a deliberately unanswerable question — confirm it short-circuits
      correctly
- [ ] Confirm every step of a run is traced, with token counts on the
      answer-writing step
- [ ] Write `scripts/logging_utils.py` and wire it in
- [ ] Confirm a run produces a correctly shaped log entry
- [ ] Write `scripts/run_eval.py`, run it, record the score
- [ ] Write `docs/eval_results.md`
- [ ] Write `scripts/run_all.py` and `README.md`
- [ ] Commit, push, open PR (base `phase-2-tdd`)

## Phase 4 — CI (`phase-4-ci`, base: `phase-3-implement`)

- [ ] Decide how the search service and graph database will be reachable
      during CI runs
- [ ] Write `.github/workflows/ci.yml` — runs tests, then the evaluation;
      fails the build if the score drops below 70%
- [ ] Push a deliberately failing test — confirm the build goes red
- [ ] Revert it; push a deliberately poor evaluation result — confirm the
      build goes red specifically on the score check
- [ ] Commit, push, open PR (base `phase-3-implement`)
