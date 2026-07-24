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
- [x] Local RAG service confirmed running `phase-9-external-call-timeouts`
      (Block 4's branch with the top_k=25 filtered ceiling) — live-verified
      `top_k=25` succeeds (25 sources returned) and `top_k=26` is still
      rejected (`"top_k must be between 1 and 25"`)
- [x] Recapture `data/eval/rag_fixtures.json` via
      `scripts/capture_rag_fixtures.py` and regenerate
      `data/eval/answer_key.json` via `scripts/build_eval_answer_key.py`
      against the live, `top_k=25`-capable service
- [x] Recalibrate `compute_confidence()`'s tiers in `scripts/schemas.py`
      (`low` < 15, `medium` 15–24, `high` >= 25), grounded in the real
      per-question verified-patient counts the regenerated answer key
      produced — 1, 3, 3, 8, 18, 19, 25, 25 — not guessed; re-ran
      `build_eval_answer_key.py` again afterward so the golden answers'
      `confidence` field reflects the new thresholds
- [x] Re-ran `scripts/run_eval.py` (fixture mode, matching CI) — 11/11,
      updated `docs/eval_results.md`
- [x] Measured true per-question population directly against the graph
      (not RAG/agent) for all 8 answerable questions, independent of and
      cross-checked against the previous phase's numbers (populations
      unchanged — only what's found changed); spot-checked one by hand
      (Congestive heart failure / SBP < 110: 18 of 333 total, matching the
      script's count exactly)
- [x] Rewrote `docs/spec.md`'s Important honesty point and confidence-tier
      sections with the real, remeasured recall numbers (mean 0.789, up
      from 0.761 at `top_k=20`) — 6 of 8 questions now find every real
      match (up from 4 of 8), the two large-population questions improve
      but stay structurally capped by the ceiling
- [x] Commit, push the follow-up
- [x] CI failed on the follow-up commit (`4d7028a`) — the "Run evaluation"
      step scored 0.636 (7/11), below the 0.70 gate.
      `data/eval/ci_graph_seed.cypher` was left byte-identical even though
      `answer_key.json`/`rag_fixtures.json` both changed, so the CI
      service's seeded graph still only had the old, smaller
      per-question verified-patient sets baked in. Re-ran
      `scripts/generate_ci_graph_seed.py`; verified against an isolated
      ephemeral Neo4j container (not the real Block 3 graph, matching
      CI's `neo4j:5.18-community` service) — full test suite (21/21) and
      `run_eval.py` in fixture mode both pass, score back to 1.000
      (11/11). Commit, push
- [x] **Known gap, tracked, not silently dropped — resolved on Phase 8,
      see that section.** The hand-written
      edge-case regression patient from Phase 4 (`_EDGE_CASE_PERSON_ID =
      900001` / `ZZZ_Test_Excluded_Drug`, commit `2af8057` on
      `phase-4-ci`, exercised by `tests/test_graph_tool_integration.py`)
      is absent from the regenerated seed above — not because
      regeneration dropped it, but because it was never inherited here.
      Phase 5, Phase 6, and this branch all forked from a point on
      `phase-4-ci` that predates `2af8057` (`git merge-base
      --is-ancestor 2af8057 HEAD` is false), and `c8d8737` — already in
      this branch's own history, done independently — rewrote
      `generate_ci_graph_seed.py`'s shared-patient handling in the
      meantime (patients can now verify for more than one task, with
      combined lab constraints), a design the original edge-case code
      never accounted for. Porting `_EDGE_CASE_PERSON_ID`/
      `_EDGE_CASE_TASK_ID`/`_EDGE_CASE_DRUG_NAME` forward needs real
      design work against that shared-patient/combined-constraint logic,
      not a mechanical re-application of the old diff — do this as its
      own follow-up, not bundled into a CI fix

## Phase 8 — Expose outcome (`phase-8-expose-outcome`, base: `phase-7-filtered-top-k-ceiling`)

- [x] Added `outcome: Literal["answered", "nothing_found", "tool_error"]`
      to `ClinicalAnswer` (`scripts/schemas.py`), threaded through
      `scripts/agent.py`'s five construction sites from the outcome value
      each one already computed, so a caller (a future Block 6
      orchestrator) can tell a genuine tool failure apart from a
      legitimate low-confidence success without parsing `caveat`'s free
      text. Searched for every place that constructs or depends on
      `ClinicalAnswer`'s shape (`build_eval_answer_key.py`,
      `run_eval.py`) rather than assuming — neither constructs one, so
      neither needed changes. Documented in `docs/spec.md`'s Structured
      output section
- [x] **This branch chain never merged to `main`, so before it does:
      confirmed, via `git merge-base --is-ancestor`, not assumed, that
      three fixes built and reviewed on sibling branches were never
      actually inherited here.** `phase-5-rag-filter-wiring` and
      `phase-4-ci` (and everything based on either) forked at points
      that predate these commits — the fixes exist on `phase-3-implement`,
      `phase-4-ci`, and `phase-5-rag-filter-wiring`'s own tips, but this
      chain (`phase-4-ci` (old point) → 5 (old point) → 6 → 7 → 8)
      branched before any of the three landed, so none of the three
      commits is an ancestor of this branch, and none of the three fixes
      was ever folded forward. Folded in all three:
  - [x] Phase 3's Neo4j timeout fix (`9d9375e` on `phase-3-implement`) —
        `scripts/graph_tool.py` here had no timeout at all on its
        `session.run()` calls. Nothing else had touched that file since
        (confirmed via `git log --all -- scripts/graph_tool.py`), so
        `git cherry-pick 9d9375e` applied with no conflicts
  - [x] Phase 4's CI-seed edge-case fix (`2af8057` on `phase-4-ci`) —
        real design work, not a copy-paste, since `c8d8737` (already in
        this branch's history) rewrote `generate_ci_graph_seed.py`'s
        shared-patient/combined-constraint handling after `2af8057` was
        written. Adapted `_EDGE_CASE_PERSON_ID`/`_EDGE_CASE_TASK_ID`/
        `_EDGE_CASE_DRUG_NAME` to inject directly into the rewritten
        script's `patient_lab_values` (post-resolution, bypassing the
        constraint-satisfaction machinery entirely, since that machinery
        only ever computes *satisfying* values), regenerated
        `data/eval/ci_graph_seed.cypher`, and ported
        `tests/test_graph_tool_integration.py` forward — its skip-guard
        needed a real redesign, not just new numbers: q7 now verifies 25
        real patients (up from 1), and at that scale the original
        "does `count_drugs()` with one real ID return `patients_checked
        == 1`" skip check turned out to be foolable by the very bug it
        was meant to help catch (an AND-regressed-to-OR bug, due to
        Cypher operator precedence, also detaches `person_id IN
        $person_ids` from the term it's AND'd with, letting the query
        match real patients outside the requested ID list — invisible
        with 1 real match, but with 25 it inflated the skip-check's own
        baseline and produced a false skip instead of a failure).
        Replaced it with a raw-driver existence check for the edge-case
        node that never touches `graph_tool.py`'s verify query, so it
        can't be fooled by a bug in that query
  - [x] Verified against an isolated ephemeral Neo4j container (not the
        real Block 3 graph): full test suite (23/23) and `run_eval.py`
        in fixture mode (11/11) both pass. Proved the new integration
        test actually catches the regression it exists for: flipped the
        verify query's `AND` to `OR`, confirmed only that one test fails
        (22 passed, 1 failed — first attempt, before the skip-guard
        redesign above, wrongly skipped instead; after the redesign, it
        correctly failed), reverted, confirmed clean (23/23) again
- [x] Confirmed CI green on the actual push
- [x] Commit, push
- [x] Third instance of the same root cause, found after the fact —
      Phase 5's 422-handling fix (`4e409a0` on `phase-5-rag-filter-wiring`,
      "treat a 422 from Block 4 as a non-retryable bad filter") was also
      missing. `phase-6-confidence-recalibration` branched from
      `c8d8737`, one commit before `4e409a0` landed on `phase-5`, so this
      whole chain (6 → 7 → 8) never inherited it either. `git cherry-pick
      -n 4e409a0` applied via auto-merge (`tests/test_rag_tool.py` had
      since diverged — the `invalid_top_k` boundary test moved from
      `top_k=21` to `26`), no conflicts, no leftover conflict markers,
      resulting diff matches the original commit exactly
  - [x] Restored `test_search_patients_raises_on_invalid_filter_422` in
        `tests/test_rag_tool.py` — confirmed it was also missing (not
        assumed) before restoring it
- [x] **Systematic check, not just the three found by chance:** ran
      `git merge-base --is-ancestor` for every one of the 36 unique
      commits across `phase-3-implement`, `phase-4-ci`, and
      `phase-5-rag-filter-wiring` against this branch's tip. Exactly
      three came back not-an-ancestor — `9d9375e`, `2af8057`, and
      `4e409a0`, the three already found and folded in above (their
      cherry-picked content is here under new commit hashes, which is
      why the *original* SHAs still correctly report as non-ancestors —
      cherry-picking necessarily creates new commits). No fourth
      instance found
- [x] Full suite (23/23, 1 skip against the real Block 3 graph — expected,
      it doesn't have the synthetic CI fixture) and `run_eval.py` (11/11)
      both green after folding in the third fix
- [x] Confirmed CI green on this push too
- [x] Commit, push

## Phase 9 — RAG citations (`phase-9-rag-citations`, base: `phase-8-expose-outcome`)

- [x] `scripts/schemas.py`: refactor `dedupe_and_order_patient_ids()`'s
      internals into a shared private `_dedupe_best_sources(sources) ->
      dict[int, dict]` (patient_id → its full winning source dict, not
      just the score) plus a small `_order_patient_ids_best_score_first()`
      ordering helper — one dedupe/sort pass, not two, per this file's own
      "logic lives in exactly one place" rule.
      `dedupe_and_order_patient_ids()` calls the helpers and returns just
      the ID list, byte-identical to today — no behavior change, so
      nothing that already imports it (including
      `build_eval_answer_key.py`) breaks
- [x] Add `build_rag_citations(sources) -> list[dict]`, built on the same
      helpers and the same best-score-first order, returning
      `[{"patient_id": ..., "chunk_id": ..., "snippet": ...}, ...]` —
      `chunk_text` from Block 4's source becomes `snippet`, `person_id`
      becomes `patient_id` (the external name `rag_patient_ids` already
      uses, not Block 4's internal naming)
- [x] Add `rag_citations: list[dict]` to `ClinicalAnswer`, next to
      `rag_patient_ids` — not inside `graph_result`, which is Neo4j drug
      counts only. Add `rag_citations: list[dict]` to `AgentState` too
- [x] `scripts/rag_tool.py`: `search_patients()`'s 200 branch returns
      `"citations": build_rag_citations(body["sources"])` alongside
      `"patient_ids"` and `"retrieved_count"`
- [x] `scripts/agent.py`: `initial_state` defaults `rag_citations` to
      `[]`, mirroring `rag_patient_ids`. `count_node`'s two branches both
      add `"rag_citations": state["rag_result"]["citations"]`. Every
      `ClinicalAnswer(...)` site gets `rag_citations` following
      `rag_patient_ids`'s exact same pass/fail pairing —
      `state["rag_citations"]` where `rag_patient_ids` is populated
      (`synthesize_node`, `build_graph_error_answer_node`,
      `build_answer_error_answer_node`), `[]` where `rag_patient_ids=[]`
      is used (`build_fallback_answer_node`,
      `build_search_error_answer_node`). No new logic branches
- [x] Confirmed `scripts/build_eval_answer_key.py` needs no changes — it
      only ever imports `dedupe_and_order_patient_ids` for the golden
      patient list, never chunk text
- [x] Updated `tests/test_rag_tool.py`'s existing hit-test fixture with
      `chunk_text` per source and asserted `result["citations"]`
      (best-score-first, deduped, same as `patient_ids`)
- [x] Updated every fake `search_fn` in `tests/test_agent_answers.py` to
      include a `"citations"` key (`count_node` now `KeyError`s without
      it). Added a `rag_citations` assertion to the no-patients-found
      test (empty) and to the graph-broken / answer-step-failed tests
      (populated, matching `rag_patient_ids`). Added one new test for the
      full-success path — the one deliberate exception to this file's
      "every path except full success" scope (see Phase 8's note on the
      same docstring claim), added specifically to confirm
      `rag_citations` threads through `ClinicalAnswer` the way
      `rag_patient_ids` already does
- [x] Documented `rag_citations` in `docs/spec.md`'s Structured output
      section — the field table, the "always filled in directly" list,
      a paragraph on what it is and why it's separate from `graph_result`,
      a "follows `rag_patient_ids` exactly" rule bullet, and the
      exact-wording outcome table's `rag_patient_ids` / `rag_citations` /
      `graph_result` column — matching how `outcome` was documented on
      Phase 8
- [x] Full suite green — 24 passed, 1 skipped (the pre-existing live-graph
      integration test, unaffected by this change)
- [ ] Commit, push
- [x] **Known gap, tracked, not silently dropped:** `data/eval/
      rag_fixtures.json` was NOT regenerated this phase — Block 4's
      `phase-10-chunk-text-citations` (the source of `chunk_text`) isn't
      available to call yet. The cached fixtures predate this change and
      have no `"citations"` key at all, so `scripts/run_eval.py` with
      `USE_RAG_FIXTURES` set (matching CI) will `KeyError` on
      `state["rag_result"]["citations"]` in `count_node` until
      `scripts/capture_rag_fixtures.py` is re-run once Block 4's phase
      lands — the same category of follow-up as the `top_k=25` fixture
      regeneration in Phase 7. CI on this branch is expected to fail on
      the "Run evaluation" step until then; this is a known, deliberate
      gap, not a bug
- [x] Commit, push
