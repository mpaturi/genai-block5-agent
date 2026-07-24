# Block 5 Tasks

Each phase gets its own branch and its own pull request. Every phase
branches from the tip of the previous phase's branch (or from `main`, if
the previous phase's PR has already merged by then).

## Phase 1 — Spec, Plan, Tasks (`phase-1-spec`, base: `main`)

No code this phase.

- [x] Write `docs/spec.md`
- [x] Write `docs/plan.md`
- [x] Write `docs/tasks.md`
- [x] Commit all three, push, open PR (base `main`)

## Phase 2 — Tests first (`phase-2-tdd`, base: `phase-1-spec`)

The agent doesn't exist yet — this phase only writes down what "correct"
looks like.

- [x] Write `scripts/schemas.py` (the answer object, agent state, the
      structured question input: `condition`, `lab`, `comparison`,
      `value`, `drug_a`, `drug_b`, and the one shared function that
      builds the RAG query text from `condition`/`lab`/`comparison`/
      `value` — this is the only place that formatting logic lives)
- [x] Check the live graph database for its current list of conditions,
      drugs, and lab values before writing questions (see `docs/spec.md`'s
      Evaluation section) — `graph_tool.py` doesn't exist yet at this
      point, so do this with a one-off query run directly against Neo4j,
      not through the tool
- [x] Write `data/eval/tasks.json` — at least 10 test questions, each with
      an ID (at least 7 answerable, at least 3 deliberately unanswerable).
      Store each question as separate `condition`, `lab`, `comparison`,
      `value`, `drug_a`, `drug_b` fields, not one opaque string (see
      `docs/spec.md`'s Question pattern) — derive the assembled full-text
      question from these fields for display/logging only
- [x] Write `scripts/build_eval_answer_key.py` — call the live search
      service and live graph directly (not through `rag_tool.py`/
      `graph_tool.py`, which don't exist yet) — and run it to write
      `data/eval/answer_key.json`: the correct patient list, drug count,
      and expected `confidence` (from the same rule in `docs/spec.md`'s
      Structured output section) for each answerable question, keyed by
      the same question ID. Import and use the shared query-building
      function from `scripts/schemas.py` to build the search-service call
      — do not write a second, separate version of that formatting logic
      — so the golden patient list matches what the agent will actually
      produce. Dedupe and order the raw result using Tool 1's exact rule
      (score descending, ties broken by patient ID) before writing it, so
      the exact-match check on `rag_patient_ids` compares against a
      golden list built the same way the agent builds its own
- [x] Spot-check a few entries in `data/eval/answer_key.json` by hand,
      including the expected `confidence` value
- [x] Write `tests/test_rag_tool.py` and `tests/test_graph_tool.py` —
      include a `test_graph_tool.py` case where one of two given drugs has
      zero matches among the checked patients, confirming it's absent
      from `graph_result` rather than present with a count of 0
- [x] Write `tests/test_agent_answers.py` — checks all four fixed-wording
      answers (nothing found, search broken, graph broken, answer step
      failed) match `docs/spec.md`'s outcome table exactly, without
      needing the real search service, graph database, or language model
- [x] Run the tests — confirm they fail (the tools and agent don't exist
      yet)
- [x] Commit, push, open PR (base `phase-1-spec`)

## Phase 3 — Build it (`phase-3-implement`, base: `phase-2-tdd`)

- [x] Set up `requirements.txt`, `.env.example`, virtual environment
- [x] Write `scripts/check_connection.py` — confirm the search service,
      graph database, language model key, and tracing service are all
      reachable
- [x] Write `scripts/rag_tool.py` — import the shared query-building
      function from `scripts/schemas.py` (the same one
      `build_eval_answer_key.py` used in Phase 2) rather than writing a
      second version of it — get its tests passing
- [x] Try a real search by hand
- [x] Write `scripts/graph_tool.py` — get its tests passing
- [x] Try a real count by hand
- [x] Write `scripts/agent.py` — returns whether the count step ran
      alongside the answer object
- [x] `pytest tests/test_agent_answers.py` — all pass
- [x] Confirm the returned "did the count step run" value is correct on
      an answerable question (`true`) and a deliberately unanswerable one
      (`false`) — not just that the log entry looks right
- [x] Run the example question end-to-end — confirm a valid answer
- [x] Run a deliberately unanswerable question — confirm it short-circuits
      and the answer matches the fixed "nothing found" wording exactly
- [x] Confirm every step of a run is traced, with token counts on the
      answer-writing step
- [x] Write `scripts/logging_utils.py` and wire it in
- [x] Confirm a run produces a correctly shaped log entry
- [x] Write `scripts/run_eval.py`, run it, record the score
- [x] Investigate real recall at the agent's actual `top_k=5` setting,
      measured directly against the graph's true patient counts for Block
      5's own 8 answerable questions (not borrowed from Block 4's separate
      eval set) — document the finding in `docs/spec.md`'s Important
      honesty point section, including whether raising `top_k` helps
- [x] Write `docs/eval_results.md`
- [x] Write `scripts/run_all.py` and `README.md`
- [x] Commit, push, open PR (base `phase-2-tdd`)

## Phase 4 — CI (`phase-4-ci`, base: `phase-3-implement`)

- [x] Decide how the search service, graph database, and language model
      will be reachable during CI runs
- [x] Write `.github/workflows/ci.yml` — runs tests, then the evaluation;
      fails the build if the score drops below 70%
- [x] Push a deliberately failing test — confirm the build goes red
- [x] Revert it; push a deliberately poor evaluation result — confirm the
      build goes red specifically on the score check
- [x] Revert that too — confirm the build is back to green before
      continuing
- [x] Commit, push, open PR (base `phase-3-implement`)

## Phase 5 — RAG filter wiring (`phase-5-rag-filter-wiring`, base: `phase-4-ci`)

- [x] Update `docs/spec.md`: Tool 1's default `top_k` raised to 20,
      documented the new metadata filter fields sent to Block 4's `/query`
      (`condition`/`lab`/`comparison`/`value`), added TODO markers on the
      two now-obsolete recall paragraphs (numbers not guessed, left for
      Phase 6)
- [x] Extend `scripts/rag_tool.py`'s `search_patients()` to forward
      `condition`/`lab`/`comparison`/`value` as structured filter fields to
      Block 4's `/query`, alongside the free-text query
- [x] Update `scripts/agent.py`'s `search_node` to pass the question's
      filter fields through and call at `top_k=20`
- [x] Update `scripts/build_eval_answer_key.py` to forward the same filter
      fields, so the golden answer key is built from the same candidate
      set the real agent now retrieves
- [x] Confirm the locally running RAG service was serving stale,
      pre-filter Block 4 code before trusting any of the above — restarted
      it from Block 4's `phase-7-metadata-filter` branch, confirmed via
      `/openapi.json` that the filter fields are actually exposed
- [x] Recapture `data/eval/rag_fixtures.json` and regenerate
      `data/eval/answer_key.json` against the live, filter-aware service
- [x] Update `tests/test_rag_tool.py`, `tests/test_agent_answers.py`, and
      `scripts/run_eval.py` for the new signature and `top_k` — all 21
      tests pass, fixture-mode eval scores 11/11
- [x] Measure real recall directly against the graph for all 8 answerable
      questions (not borrowed from Block 4's eval) — mean recall 0.761, up
      from 0.000/0.059, every question now finds at least one real match
- [x] Commit, push, open PR (base `phase-4-ci`)

## Phase 6 — Confidence recalibration (`phase-6-confidence-recalibration`, base: `phase-5-rag-filter-wiring`)

- [x] Recalibrate `compute_confidence()`'s tiers in `scripts/schemas.py`,
      using the same design principle as the original thresholds (`high`
      reachable at Tool 1's actual ceiling, not trivial, not practically
      unreachable) scaled to the new `top_k=20` default, grounded in the
      real per-question verified-patient counts Phase 5 measured — not
      guessed
- [x] Regenerate `data/eval/answer_key.json`'s `confidence` values under
      the new thresholds, so the golden answers stay consistent with what
      the recalibrated agent actually computes
- [x] Rewrite `docs/spec.md`'s Important honesty point and confidence-tier
      sections with the real, remeasured recall numbers (mean 0.761, up
      from 0.000/0.059) and the new tier boundaries, replacing Phase 5's
      TODO markers — stating plainly that the improvement is real but
      uneven, not a uniform fix
- [x] Commit, push

## Phase 7 — Filtered top_k ceiling (`phase-7-filtered-top-k-ceiling`, base: `phase-6-confidence-recalibration`)

Block 5's `search_patients()` always sends a `condition`/`lab`/
`comparison`/`value` filter, so every call already qualifies for Block
4's raised filtered-only `top_k` ceiling of 25 (up from 20).

- [x] Confirm the live RAG service's actual ceiling before trusting it —
      a live call at `top_k=25` against the locally running service was
      still rejected (`"top_k must be between 1 and 20"`), the same
      stale-service problem Phase 5 hit. Deferred every item below that
      needs live, filter-aware `top_k=25` data until the service is
      confirmed updated
- [x] Update `scripts/rag_tool.py`'s `search_patients()` default and
      pre-flight validation range from `1–20` to `1–25`
- [x] Update the call site in `scripts/agent.py`, both eval-fixture
      generators (`scripts/build_eval_answer_key.py`,
      `scripts/capture_rag_fixtures.py`), and `scripts/run_eval.py`'s
      fixture-replay stub signature
- [x] Update `tests/test_rag_tool.py`'s `invalid_top_k` boundary test
      (`top_k=21` → `26`) and `tests/test_agent_answers.py`'s fakes/
      assertions referencing the old ceiling — all 21 tests pass
- [x] Commit, push (code/test changes only)
- [ ] Once the local RAG service is confirmed running the new ceiling:
      live-verify `top_k=25`, recapture `data/eval/rag_fixtures.json`,
      regenerate `data/eval/answer_key.json`
- [ ] Remeasure real recall directly against the graph at the new
      ceiling and rewrite `docs/spec.md`'s Important honesty point and
      confidence-tier sections with the real numbers — not guessed
- [ ] Recalibrate `compute_confidence()`'s `high` threshold in
      `scripts/schemas.py` (currently hardcoded to `patients_checked >=
      20`, reasoned explicitly around the old ceiling) for the new
      `top_k=25` ceiling, grounded in the remeasured per-question counts
- [ ] Commit, push the follow-up
