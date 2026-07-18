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
- [ ] Check the live graph database for its current list of conditions,
      drugs, and lab values before writing questions (see `docs/spec.md`'s
      Evaluation section) — `graph_tool.py` doesn't exist yet at this
      point, so do this with a one-off query run directly against Neo4j,
      not through the tool
- [ ] Write `data/eval/tasks.json` — at least 10 test questions, each with
      an ID (at least 7 answerable, at least 3 deliberately unanswerable)
- [ ] Write `scripts/build_eval_answer_key.py` — call the live search
      service and live graph directly (not through `rag_tool.py`/
      `graph_tool.py`, which don't exist yet) — and run it to write
      `data/eval/answer_key.json`: the correct patient list, drug count,
      and expected `confidence` (from the same rule in `docs/spec.md`'s
      Structured output section) for each answerable question, keyed by
      the same question ID
- [ ] Spot-check a few entries in `data/eval/answer_key.json` by hand,
      including the expected `confidence` value
- [ ] Write `tests/test_rag_tool.py` and `tests/test_graph_tool.py`
- [ ] Write `tests/test_agent_answers.py` — checks all four fixed-wording
      answers (nothing found, search broken, graph broken, answer step
      failed) match `docs/spec.md`'s outcome table exactly
- [ ] Run the tests — confirm they fail (the tools and agent don't exist
      yet)
- [ ] Commit, push, open PR (base `phase-1-spec`)

## Phase 3 — Build it (`phase-3-implement`, base: `phase-2-tdd`)

- [ ] Set up `requirements.txt`, `.env.example`, virtual environment
- [ ] Write `scripts/check_connection.py` — confirm the search service,
      graph database, language model key, and tracing service are all
      reachable
- [ ] Write `scripts/rag_tool.py` — get its tests passing
- [ ] Try a real search by hand
- [ ] Write `scripts/graph_tool.py` — get its tests passing
- [ ] Try a real count by hand
- [ ] Write `scripts/agent.py` — returns whether the count step ran
      alongside the answer object
- [ ] `pytest tests/test_agent_answers.py` — all pass
- [ ] Confirm the returned "did the count step run" value is correct on
      an answerable question (`true`) and a deliberately unanswerable one
      (`false`) — not just that the log entry looks right
- [ ] Run the example question end-to-end — confirm a valid answer
- [ ] Run a deliberately unanswerable question — confirm it short-circuits
      and the answer matches the fixed "nothing found" wording exactly
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
- [ ] Revert that too — confirm the build is back to green before
      continuing
- [ ] Commit, push, open PR (base `phase-3-implement`)
