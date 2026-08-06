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

- [x] Write `block5_agent/schemas.py` (the answer object, agent state, the
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
- [x] Write `block5_agent/build_eval_answer_key.py` — call the live search
      service and live graph directly (not through `rag_tool.py`/
      `graph_tool.py`, which don't exist yet) — and run it to write
      `data/eval/answer_key.json`: the correct patient list, drug count,
      and expected `confidence` (from the same rule in `docs/spec.md`'s
      Structured output section) for each answerable question, keyed by
      the same question ID. Import and use the shared query-building
      function from `block5_agent/schemas.py` to build the search-service call
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
- [x] Write `block5_agent/check_connection.py` — confirm the search service,
      graph database, language model key, and tracing service are all
      reachable
- [x] Write `block5_agent/rag_tool.py` — import the shared query-building
      function from `block5_agent/schemas.py` (the same one
      `build_eval_answer_key.py` used in Phase 2) rather than writing a
      second version of it — get its tests passing
- [x] Try a real search by hand
- [x] Write `block5_agent/graph_tool.py` — get its tests passing
- [x] Try a real count by hand
- [x] Write `block5_agent/agent.py` — returns whether the count step ran
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
- [x] Write `block5_agent/logging_utils.py` and wire it in
- [x] Confirm a run produces a correctly shaped log entry
- [x] Write `block5_agent/run_eval.py`, run it, record the score
- [x] Investigate real recall at the agent's actual `top_k=5` setting,
      measured directly against the graph's true patient counts for Block
      5's own 8 answerable questions (not borrowed from Block 4's separate
      eval set) — document the finding in `docs/spec.md`'s Important
      honesty point section, including whether raising `top_k` helps
- [x] Write `docs/eval_results.md`
- [x] Write `block5_agent/run_all.py` and `README.md`
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
- [x] Extend `block5_agent/rag_tool.py`'s `search_patients()` to forward
      `condition`/`lab`/`comparison`/`value` as structured filter fields to
      Block 4's `/query`, alongside the free-text query
- [x] Update `block5_agent/agent.py`'s `search_node` to pass the question's
      filter fields through and call at `top_k=20`
- [x] Update `block5_agent/build_eval_answer_key.py` to forward the same filter
      fields, so the golden answer key is built from the same candidate
      set the real agent now retrieves
- [x] Confirm the locally running RAG service was serving stale,
      pre-filter Block 4 code before trusting any of the above — restarted
      it from Block 4's `phase-7-metadata-filter` branch, confirmed via
      `/openapi.json` that the filter fields are actually exposed
- [x] Recapture `data/eval/rag_fixtures.json` and regenerate
      `data/eval/answer_key.json` against the live, filter-aware service
- [x] Update `tests/test_rag_tool.py`, `tests/test_agent_answers.py`, and
      `block5_agent/run_eval.py` for the new signature and `top_k` — all 21
      tests pass, fixture-mode eval scores 11/11
- [x] Measure real recall directly against the graph for all 8 answerable
      questions (not borrowed from Block 4's eval) — mean recall 0.761, up
      from 0.000/0.059, every question now finds at least one real match
- [x] Commit, push, open PR (base `phase-4-ci`)

## Phase 6 — Confidence recalibration (`phase-6-confidence-recalibration`, base: `phase-5-rag-filter-wiring`)

- [x] Recalibrate `compute_confidence()`'s tiers in `block5_agent/schemas.py`,
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
- [x] Update `block5_agent/rag_tool.py`'s `search_patients()` default and
      pre-flight validation range from `1–20` to `1–25`
- [x] Update the call site in `block5_agent/agent.py`, both eval-fixture
      generators (`block5_agent/build_eval_answer_key.py`,
      `block5_agent/capture_rag_fixtures.py`), and `block5_agent/run_eval.py`'s
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
      `block5_agent/capture_rag_fixtures.py` and regenerate
      `data/eval/answer_key.json` via `block5_agent/build_eval_answer_key.py`
      against the live, `top_k=25`-capable service
- [x] Recalibrate `compute_confidence()`'s tiers in `block5_agent/schemas.py`
      (`low` < 15, `medium` 15–24, `high` >= 25), grounded in the real
      per-question verified-patient counts the regenerated answer key
      produced — 1, 3, 3, 8, 18, 19, 25, 25 — not guessed; re-ran
      `build_eval_answer_key.py` again afterward so the golden answers'
      `confidence` field reflects the new thresholds
- [x] Re-ran `block5_agent/run_eval.py` (fixture mode, matching CI) — 11/11,
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
      `block5_agent/generate_ci_graph_seed.py`; verified against an isolated
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
      to `ClinicalAnswer` (`block5_agent/schemas.py`), threaded through
      `block5_agent/agent.py`'s five construction sites from the outcome value
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
        `block5_agent/graph_tool.py` here had no timeout at all on its
        `session.run()` calls. Nothing else had touched that file since
        (confirmed via `git log --all -- block5_agent/graph_tool.py`), so
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

- [x] `block5_agent/schemas.py`: refactor `dedupe_and_order_patient_ids()`'s
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
- [x] `block5_agent/rag_tool.py`: `search_patients()`'s 200 branch returns
      `"citations": build_rag_citations(body["sources"])` alongside
      `"patient_ids"` and `"retrieved_count"`
- [x] `block5_agent/agent.py`: `initial_state` defaults `rag_citations` to
      `[]`, mirroring `rag_patient_ids`. `count_node`'s two branches both
      add `"rag_citations": state["rag_result"]["citations"]`. Every
      `ClinicalAnswer(...)` site gets `rag_citations` following
      `rag_patient_ids`'s exact same pass/fail pairing —
      `state["rag_citations"]` where `rag_patient_ids` is populated
      (`synthesize_node`, `build_graph_error_answer_node`,
      `build_answer_error_answer_node`), `[]` where `rag_patient_ids=[]`
      is used (`build_fallback_answer_node`,
      `build_search_error_answer_node`). No new logic branches
- [x] Confirmed `block5_agent/build_eval_answer_key.py` needs no changes — it
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
- [x] Commit (not pushed yet)
- [x] **Known gap, tracked, not silently dropped:** `data/eval/
      rag_fixtures.json` was NOT regenerated this phase — Block 4's
      `phase-10-chunk-text-citations` (the source of `chunk_text`) isn't
      available to call yet. The cached fixtures predate this change and
      have no `"citations"` key at all, so `block5_agent/run_eval.py` with
      `USE_RAG_FIXTURES` set (matching CI) will `KeyError` on
      `state["rag_result"]["citations"]` in `count_node` until
      `block5_agent/capture_rag_fixtures.py` is re-run once Block 4's phase
      lands — the same category of follow-up as the `top_k=25` fixture
      regeneration in Phase 7. CI on this branch is expected to fail on
      the "Run evaluation" step until then; this is a known, deliberate
      gap, not a bug
- [x] **Gap resolved:** Block 4's `phase-10-chunk-text-citations` landed,
      so re-ran `block5_agent/capture_rag_fixtures.py` against the live search
      service — `data/eval/rag_fixtures.json` now carries real
      `chunk_text`-derived `"citations"` per fixture.
      `build_eval_answer_key.py`'s output untouched (it never used
      `chunk_text`). Verified: full `pytest` suite (24 passed, 1
      pre-existing skip) and `block5_agent/run_eval.py` in fixture mode
      (11/11, `docs/eval_results.md` byte-identical — citations don't
      affect any of the three scored dimensions) both green. Commit, push
- [x] Commit, push

## Phase 10 — Real packaging (`phase-10-packaging`, base: `main`)

Block 6 needs to install and import this repo's agent code properly,
instead of reaching into this folder's directory layout directly.

- [x] Renamed `scripts/` to `block5_agent/` (`git mv`, preserving history),
      added `block5_agent/__init__.py`
- [x] Updated every internal `from scripts.X import Y` / `from scripts
      import X` and every `scripts/`-prefixed comment, docstring, and
      `monkeypatch.setattr` string target across `block5_agent/*.py` and
      `tests/*.py` to `block5_agent` — found via grep, not memory
- [x] Updated `.github/workflows/ci.yml`'s two `python -m scripts.X`
      invocations and its comments to `block5_agent`
- [x] Added a minimal `pyproject.toml` (setuptools backend) declaring
      `block5_agent` as an installable package, with `dependencies`
      mirroring `requirements.txt`'s runtime packages and `pytest` moved
      to an `optional-dependencies.test` extra, since it's a test-only
      dependency, not something Block 6 needs to import this package
- [x] Grepped every doc (`README.md`, `docs/spec.md`, `docs/plan.md`,
      `docs/tasks.md`, `docs/eval_results.md`) for the old `scripts.`/
      `scripts/` module path and updated every hit to `block5_agent` —
      including this file's own Phase 1–9 history, at the user's explicit
      request, so no doc describes a package name that no longer matches
      the real code. The one surviving `scripts` hit, `README.md`'s
      `uvicorn scripts.api:app` line, is Block 4's own module in a
      different repo and was correctly left alone
- [x] No `pytest.ini`/`conftest.py` exist in this repo; none needed adding
      — `python -m pytest` already puts the repo root on `sys.path`,
      which resolves `import block5_agent` the same way it resolved
      `import scripts` before the rename
- [x] Ran the full test suite after the rename — all green before
      committing
- [x] Commit, push, open PR (base `main`)

## Phase 11 — Expose cost (`phase-11-expose-cost`, base: `phase-10-packaging`)

- [x] `run_agent()` (`block5_agent/agent.py`) now returns a 3-tuple
      `(answer, count_step_ran, cost_info)` instead of 2 — `cost_info` is
      `{"cost_usd", "input_tokens", "output_tokens"}`, taken directly from
      the same log entry `log_run()` already writes to
      `data/logs/runs.jsonl`, not recomputed a second way. Reads `0`/`$0`
      when `USE_STUB_ANSWER_FN` stubbed the answer step, since no real
      Claude call happened (commit `0df7ad3`)
- [x] Updated every call site to unpack 3 values: `block5_agent/run_eval.py`,
      `block5_agent/run_all.py` (prints `cost_info` after the smoke-test
      question), and all 5 `run_agent(...)` call sites in
      `tests/test_agent_answers.py`
- [x] Added a shape/type assertion on `cost_info` to the full-success test
      in `tests/test_agent_answers.py` — confirms the three keys are
      present and each a non-negative `int`/`float`
- [x] Documented the new return value in `docs/spec.md`'s Tracing and
      logging section
- [x] `python -m pytest` — 24 passed, 1 skipped (pre-existing integration
      skip)
- [x] Commit, push, open PR (base `phase-10-packaging`) — PR #12,
      reviewed and approved, CI green, merged into `main`
      via `d99e0c6`

## Phase 12 — Fix q1 seed (`phase-12-fix-q1-seed`, base: `main`)

- [x] `data/eval/ci_graph_seed.cypher`'s q1 population (Essential
      hypertension, SBP > 140) corrected from the exact 25 patients RAG's
      own `top_k=25` search returns (a seed too small to ever disagree
      with the agent's necessarily-capped output) to the true, exhaustive
      99-patient population, sourced from Block 4's real
      `data/raw/graph_export.jsonl`. Removed 10 leftover `PRESCRIBED`
      edges from the original 25's arbitrary synthetic drug assignment
      that didn't match real per-patient data. Independently verified by
      direct Neo4j count against the corrected seed, loaded into an
      ephemeral instance: 99 total, Lisinopril 49, Amlodipine 28,
      Hydrochlorothiazide 11. Updated `data/eval/answer_key.json`'s q1
      entry to these true counts, regenerated `docs/eval_results.md`
      (10/11, q1 FAILing on answer accuracy by design), updated
      `docs/spec.md`'s Known limitations (commit `9e450fd`)
- [x] Review feedback on PR #13: agreed with the diagnosis — seeding q1
      with exactly the 25 patients RAG returns had made the accuracy
      check tautological, structurally incapable of ever catching the
      retrieval-ceiling gap Block 6 exists to fix — but disagreed with
      scoring q1 against the full 99-patient population as a permanent,
      by-design failure
- [x] Fix, in response: added `data/eval/answer_key.json`'s
      `q1_expected_capped` entry — the same 25 patient IDs RAG's real
      search returns for q1, with drug counts and confidence
      independently verified against the corrected seed via a second
      ephemeral Neo4j check (Amlodipine 8, Lisinopril 10,
      Hydrochlorothiazide 11, 25 patients checked). `block5_agent/run_eval.py`'s
      `_check_answer_accuracy()` now special-cases q1 to score against
      this capped entry instead of the full-population entry — every
      other question's scoring is unchanged. Re-ran the eval — 11/11
      (1.000), `docs/eval_results.md` regenerated. Reworded
      `docs/spec.md`'s Known limitations note from "7 of 8, not 8 of 8"
      to describe q1 as scored against its known 25-of-99 cap, not full
      recall (commit `fbaeb70`)
- [x] Commit, push

**PR #13 status: merged into `main` via `1dcb8c8`.** `fbaeb70` was pushed
to update it after review feedback; CI was green, and it was approved and
merged.

## Phase 13 — Fix build_eval_answer_key.py (`phase-13-fix-build-eval-answer-key`, base: `phase-12-fix-q1-seed`)

- [x] Bug found: `build_eval_answer_key.py` had no idea
      `q1_expected_capped` existed — it was added to `answer_key.json` by
      hand in Phase 12. Re-running the script would have silently
      overwritten q1's true 99-patient population with the capped result
      and never touched `q1_expected_capped` at all, since its per-task
      loop can only ever produce the capped, 25-patient answer (search →
      verify → count)
- [x] Added `_query_full_population()` — an independently-written,
      unbounded Cypher query (`VERIFY_PATIENTS_QUERY_TEMPLATE`'s shape
      with the `person_ids IN` candidate-list check dropped entirely,
      same idea as Block 6's `FULL_COHORT_QUERY_TEMPLATE` in
      `genai-block6-multiagent/scripts/cohort_tool.py`, not imported
      across blocks). Refactored `main()`'s loop into a testable
      `build_answer_key(tasks, driver, search_fn=_search)` that
      special-cases q1: writes the normal pipeline's result to
      `q1_expected_capped`, and the unbounded query's result (drug counts
      via `_count_drugs()`, confidence via `compute_confidence()`, same
      as everywhere else) to `q1`. Every other task's behavior unchanged.
      Updated the module docstring to explain the special case (commit
      `835f84b`)
- [x] Added `tests/test_build_eval_answer_key.py` — zero prior coverage on
      this file. Fake/injected-driver tests confirming `q1` and
      `q1_expected_capped` are both written, from genuinely independent
      query paths, and that every other task still writes directly to
      its own entry (commit `835f84b`)
- [x] Added `tests/test_run_eval.py` — zero prior coverage on
      `_check_answer_accuracy()` too. Confirms it reads
      `q1_expected_capped` for q1, not q1's full-population entry —
      verified by temporarily reverting the special case and confirming
      two of the four tests failed for the expected reason, before
      restoring it, so this isn't just asserting today's happy path
      (commit `f5b8206`)
- [x] Ran the fixed script against real services — an ephemeral Neo4j
      loaded with the corrected 99-patient seed, plus Block 4's real RAG
      API (`uvicorn scripts.api:app`, its own venv/credentials) — and
      regenerated `data/eval/answer_key.json`. `q1_expected_capped` and
      q2-q8 came back byte-identical to what was already committed; q1's
      counts (99 patients, Lisinopril 49/Amlodipine 28/Hydrochlorothiazide
      11) matched exactly too. The one real change: q1's
      `rag_patient_ids` now correctly holds all 99 true-population IDs
      instead of a stale 25-ID list left over from Phase 12 that never
      matched its own `patients_checked: 99`. Hand-written `note` fields
      are gone now that the script is the source of truth again (commit
      `5045087`)
- [x] Re-ran `USE_RAG_FIXTURES=1 USE_STUB_ANSWER_FN=1 python -m
      block5_agent.run_eval` — still 11/11 (1.000), `docs/eval_results.md`
      unchanged
- [x] Updated `docs/spec.md`'s Known limitations to say both q1 entries
      are produced automatically every time the script runs, not
      hand-typed or hand-verified once (commit `8bfc009`)
- [x] Commit, push, open PR (base `phase-12-fix-q1-seed`) — PR #14,
      noting in the body that it's stacked on and depends on #13
- [x] CI gap found and fixed: `tests/test_build_eval_answer_key.py` was
      the first test in this suite to ever import
      `block5_agent/build_eval_answer_key.py`, which reads
      `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` from the environment at
      import time with no default (unlike `graph_tool.py`'s
      `.get(..., default)`). Masked locally by the module's own
      `load_dotenv()` picking up `.env`; CI's "Run tests" step never set
      these, so the whole suite failed to collect (`KeyError:
      'NEO4J_URI'`) on PR #14's first run. Added the same `NEO4J_*` env
      block the "Load CI graph seed" and "Run evaluation" steps already
      use to `.github/workflows/ci.yml`'s "Run tests" step — no service
      change needed, since these tests fake the driver (commit `7e6037f`)
- [x] Confirmed CI green on both PR #13 and PR #14 after the fix

**PR #14 status: open, not merged, stacked on and blocked by #13** — do
not treat this phase as complete until #14 actually merges (and #13
merges first).

## Phase 14 — Retry/backoff hardening (`phase-14-retry-backoff-hardening`, base: `main`)

Closes genai-block7-security's docs/spec.md LLM10 (retry gap) — ports Block 6's Phase 8 pattern (exponential backoff, exception classification) into Block 5's own tool-calling code, which had none of it before this phase.

- [x] **Added retry/backoff hardening and exception classification to `agent.py`, ported from Block 6's Phase 8.** New `block5_agent/error_classification.py`'s `classify_exception` maps exceptions to `retryable`/non-retryable, matching Block 6's `cohort_tool.py`/`error_classification.py` pattern; `agent.py`'s retry loop now backs off between attempts instead of retrying back-to-back with zero delay.
- [x] **Recognized Anthropic's own transient exception types.** The answer-writing step's retry decision is the sole consumer of `classify_exception` for Anthropic calls, but it only recognized neo4j/httpx exceptions at first. Added, across two follow-up commits: `APITimeoutError`/`RateLimitError`/`InternalServerError` (checked against the installed `anthropic==0.116.0` package's real exception hierarchy rather than guessed class paths), then `APIConnectionError` (a real dropped/never-reached connection, no status code, unlike the others) — placed after the `APITimeoutError` check since it's a narrower subclass of the same base class and must keep matching "timeout" first. Closes all four Anthropic exception types review feedback named as a gap.
- [x] **Fixed `graph_tool.py`'s `count_drugs` defaulting every caught exception to retryable.** Its `except` block raised `GraphServiceError(type(exc).__name__)` with no `retryable=` argument, and the class defaults `retryable` to `True` — so a permanent failure (a Cypher syntax error) was retried 3 times for no reason. Now classifies via `classify_exception`, matching Block 6's own `cohort_tool.py` pattern exactly, including preserving the real exception message (`str(exc)`) as detail rather than just its type name.
- [x] **Verified `run_agent` can't silently return a `None` final answer.** Not a fix — Block 5 has no equivalent of the Block 6 state-validation mechanism that caused an analogous bug there. Confirms the same failure mode can't happen silently here: `synthesize_node` builds the final answer via `ClinicalAnswer(...)` directly, so a malformed `answer_fn` result fails loud with a real pydantic `ValidationError` (the same one Block 6's `_run_branch` already catches), never a silent `None`.
- [x] **Fixed `classify_exception`'s `ClientConfiguration` timeout-code bug.** `_CLIENT_ERROR_TIMEOUT_CODE` checked for exactly `"Neo.ClientError.Transaction.TransactionTimedOut"` — but verified directly against a live Neo4j 5.18-community server, a real `Query(timeout=...)` expiration actually raises the same code with a `ClientConfiguration` suffix (a client-requested transaction timeout specifically, distinct from a server-configured one via `dbms.transaction.timeout`, which does surface as the bare code). Every test exercising this path used the driver's own real construction path (`Neo4jError._hydrate_neo4j`) but with the wrong code, so none caught the mismatch — this had been silently misclassifying every real client-configured timeout as `"unknown"` (non-retryable) since this same phase's classifier was first added, a few commits up. `_CLIENT_ERROR_TIMEOUT_CODE` (singular) is now `_CLIENT_ERROR_TIMEOUT_CODES` (a set containing both real codes), checked via membership. Tests updated to the real `ClientConfiguration` code; a new test proves the base code still classifies correctly too. Same bug, same fix, ported identically to `genai-block6-multiagent`'s own `error_classification.py`. Unlike Block 6, there's no earlier already-merged phase to retroactively correct here — this classifier didn't exist in this repo before this same phase introduced it, so the bug and its fix both landed within Phase 14 itself, not as a footnote on an older entry.
- [x] 52 passed, 1 skipped (live-data integration test) — full suite
- [x] Push `phase-14-retry-backoff-hardening`, open PR against `main` (PR #15, open)
