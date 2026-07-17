# Block 5 Specification

## Project title

Single-Agent Clinical Reasoning App — LangGraph Agent over RAG + Graph Tools

## Acceptance criteria

> **Project — Single-agent application**
> Agent uses ≥2 tools (Block 4's RAG service + a direct Neo4j Cypher tool
> against Block 3's graph); produces structured output (Pydantic, not free
> text) for every run; completes a multi-step clinical task combining
> semantic retrieval and exact graph aggregation; every run traced with
> tokens + latency per step; per-run cost + tokens logged; automated eval
> suite scores the agent on a fixed task set and runs in CI; a regression
> below the defined threshold fails the CI build; built spec-first.

## Goal

Build a LangGraph agent that answers clinical questions no single Block
4/5 tool can answer alone, by chaining fuzzy semantic retrieval with exact
graph aggregation:

- Tool 1 (Block 4 RAG) finds the *set* of patients a natural-language
  question is about — semantic, approximate, recall-limited by design
  (baseline recall 0.073 at top_k=5).
- Tool 2 (Block 3's Neo4j graph) takes that exact patient set and computes
  an exact aggregate over it — deterministic, no approximation.
- The agent synthesizes both results into one structured, cited,
  self-aware answer — "self-aware" meaning it must say so when its own
  inputs (RAG's low recall) limit how much the exact-sounding number can be
  trusted.

## Problem statement

Block 4's RAG service answers "which patients match X?" in prose, with
citations, but cannot count or aggregate — an LLM asked "how many of these
patients are on Lisinopril vs. Amlodipine?" would have to eyeball a handful
of retrieved chunks and guess. Block 3's graph can compute exact drug
counts, but only for someone who already knows Cypher and already has a
patient ID list. Neither tool alone answers "for patients with hypertension
and high blood pressure, how many are on Lisinopril vs. Amlodipine?" in one
step. This agent closes that gap — and must be honest that the "exact"
count it hands back is only exact over the patients RAG happened to find,
not the full population, because RAG's recall is 0.073.

## Relationship to Block 4 and Block 3

Data source: no data files are copied into this repo. Both tools call live
services — Block 4's FastAPI at `http://localhost:8000/query` and Block
3's Neo4j at `bolt://localhost:7687` — the same pattern Block 4 used for
Pinecone (call the live service, don't re-derive its data locally).

Block 4 artifacts reused:
- `POST /query` contract exactly as documented in Block 4's `docs/spec.md`
  API design section (request/response shapes, the 502 error contract,
  `top_k` validation range) — Block 4's own spec calls this "the interface
  contract Block 5 is expected to call," so this repo treats that section
  as frozen and does not renegotiate it.

Block 3 artifacts reused:
- Graph schema exactly as documented in Block 3's `docs/spec.md` Graph
  schema section: `Patient` nodes keyed on `person_id`, `Drug` nodes keyed
  on `drug_concept_id` with a human-readable `drug_name`, and the
  `PRESCRIBED` relationship (`Patient -[:PRESCRIBED]-> Drug`). The agent's
  Cypher tool reuses this relationship directly rather than redefining it.

Block 3/4 artifacts NOT reused:
- Pinecone, embedding logic, chunking — all hidden behind Block 4's API;
  this repo never talks to Pinecone directly
- Block 3's own Python scripts (`load_graph.py`, `export_graph.py`) — this
  repo only reads the already-loaded graph, it never writes to it

## Architecture

```
question (+ optional top_k)
       |
       v
+----------------+
|   call_rag     |  POST http://localhost:8000/query
+----------------+
       |
       v
  retrieved_count == 0?  ----yes----> build_fallback_answer --> END
       |
       no
       |
       v
+----------------+
|  call_graph    |  Cypher: drug distribution over rag_patient_ids
+----------------+
       |
       v
  graph tool exhausted retries (Neo4j unreachable)?  --yes--> build_error_answer --> END
       |
       no
       v
+----------------+
|   synthesize   |  Claude (claude-sonnet-4-6) writes ClinicalAnswer
+----------------+
       |
       v
      END

Retry edges (not drawn above, see State machine below):
call_rag  -(transient error, retries < 2)-> call_rag
call_rag  -(retries exhausted)-> build_error_answer --> END
call_graph -(transient error, retries < 2)-> call_graph
call_graph -(retries exhausted)-> build_error_answer --> END (using rag data only)

Tracing: every node above is a traced LangSmith run. call_rag/call_graph
carry latency only (no LLM tokens — they are deterministic tool calls).
synthesize carries latency + Claude input/output tokens. Every run also
appends one line to data/logs/runs.jsonl (question, per-node latency_ms,
tokens, computed cost_usd).
```

## Tech stack

| Component | Notes |
|---|---|
| Python | 3.11 |
| langgraph | agent loop + state machine |
| langsmith | tracing (env vars: `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`) |
| anthropic==0.116.0 | `claude-sonnet-4-6` for the `synthesize` node only |
| pydantic (v2) | `ClinicalAnswer` structured output |
| neo4j==6.2.0 | same driver version as Block 3, read-only Cypher |
| requests | HTTP calls to Block 4's `POST /query` |
| pytest==9.1.1 | unit tests (Phase 3) + eval harness assertions |
| GitHub Actions | CI: runs pytest + eval harness on every push |

> Per project convention, `requirements.txt` pins exact versions (`==`),
> never `>=`.

## Credentials and configuration

`.env` (git-ignored), `.env.example` committed as a template. Required
variables:

| Variable | Purpose |
|---|---|
| `RAG_API_URL` | Block 4 service base URL (default `http://localhost:8000`) |
| `NEO4J_URI` | Block 3's Neo4j (default `bolt://localhost:7687`) |
| `NEO4J_USER` | Neo4j auth |
| `NEO4J_PASSWORD` | Neo4j auth |
| `NEO4J_DATABASE` | default `neo4j` |
| `ANTHROPIC_API_KEY` | Claude API for the `synthesize` node |
| `LANGCHAIN_API_KEY` | LangSmith tracing |
| `LANGCHAIN_PROJECT` | LangSmith project name for this block |

Both Block 4's API and Block 3's Neo4j must already be running locally
(`uvicorn scripts.api:app` from `genai-block4-rag-eval/`, Neo4j via Block
3's `docker compose up -d`) before this agent runs — this repo does not
start either service itself.

## State schema

```python
class AgentState(TypedDict):
    question: str
    top_k: int                      # passed through to the RAG tool, default 5
    rag_result: dict | None         # raw Block 4 response
    rag_patient_ids: list[int]      # person_ids extracted from rag_result["sources"]
    rag_error: str | None           # set on tool failure, cleared on success
    rag_retry_count: int
    graph_result: dict | None       # raw drug-distribution result
    graph_error: str | None
    graph_retry_count: int
    final_answer: dict | None       # ClinicalAnswer.model_dump(), set by the terminal node
```

## Nodes and edges

Five nodes. `call_rag` and `call_graph` are deterministic tool wrappers —
no LLM involved, so they never appear in a token/cost log, only a latency
one. `synthesize` is the only node that calls Claude. `build_fallback_answer`
and `build_error_answer` are also deterministic — no Claude call — matching
Block 4's own principle of not paying for an LLM call when there is nothing
for it to reason about.

1. **`call_rag`** — calls the RAG tool wrapper (see Tool 1 contract) with
   `question` and `top_k`. On success, sets `rag_result` and
   `rag_patient_ids` (deduped `person_id`s from `sources`, in score-descending
   order). On a transient failure (network error or HTTP 502), sets
   `rag_error` and increments `rag_retry_count`.

2. **Edge — route after RAG:**
   - `rag_error` set and `rag_retry_count < 2` → back to `call_rag`
     (retry, no backoff sleep needed for a local service — see Known
     limitations)
   - `rag_error` set and `rag_retry_count >= 2` → `build_error_answer`
   - `rag_result["retrieved_count"] == 0` → `build_fallback_answer`
     (short-circuit — see "RAG miss" behavior below)
   - otherwise → `call_graph`

3. **`call_graph`** — calls the graph tool wrapper (see Tool 2 contract)
   with `rag_patient_ids`. On success, sets `graph_result`. On a transient
   failure (Neo4j driver exception), sets `graph_error` and increments
   `graph_retry_count`.

4. **Edge — route after graph:**
   - `graph_error` set and `graph_retry_count < 2` → back to `call_graph`
   - `graph_error` set and `graph_retry_count >= 2` → `build_error_answer`
     (degraded answer using RAG data only, `graph_result` stays `{}`)
   - otherwise → `synthesize`

5. **`synthesize`** — the only node that calls Claude. Prompt includes
   `question`, `rag_result["answer"]`, `rag_patient_ids`, and `graph_result`.
   Claude is instructed to write `answer` (prose, must reference specific
   counts from `graph_result` and cite `person_id`s from `rag_patient_ids`),
   choose `confidence`, and write `caveat` when applicable. The wrapper
   validates Claude's JSON output against `ClinicalAnswer` before returning
   it — a validation failure triggers one retry with a stricter
   "return valid JSON matching this schema" follow-up prompt; a second
   failure routes to `build_error_answer` instead of returning free text.

6. **`build_fallback_answer`** (no Claude call) — used when RAG found
   nothing. Produces `ClinicalAnswer(answer=rag_result["answer"],
   rag_patient_ids=[], graph_result={}, confidence="low", caveat="RAG
   retrieved no patients (retrieved_count=0) — the graph step was skipped
   because there is nothing to aggregate.")`.

7. **`build_error_answer`** (no Claude call) — used when a tool exhausts
   its retries. Produces a `ClinicalAnswer` with whatever partial data is
   available (e.g. `rag_patient_ids` populated but `graph_result={}` if
   only the graph tool failed), `confidence="low"`, and a `caveat` naming
   which tool failed and why (from `rag_error`/`graph_error`).

All five nodes route to `END` after running. There is no cycle back into
`synthesize` — retries only ever loop within `call_rag` or `call_graph`.

## Tool 1 — RAG tool (Block 4 wrapper)

- **Input:** `question: str` (non-empty), `top_k: int = 5` (validated
  1–20 before the call is made, same range Block 4 enforces server-side —
  the wrapper fails fast locally rather than relying only on Block 4's 422)
- **Call:** `POST {RAG_API_URL}/query`, JSON body
  `{"question": question, "top_k": top_k}`, `requests` with a 10s timeout
- **Success (HTTP 200):** returns the response body unchanged — the hit
  shape (`answer`, `sources`, `retrieved_count`) and the miss shape
  (`retrieved_count: 0`, `sources: []`) are both "success" as far as this
  wrapper is concerned; `retrieved_count == 0` is a routing decision made
  by the graph, not a tool error
- **Error (HTTP 502):** raises `RAGServiceError(detail=response.json()["detail"])`
  — the `ExceptionType` string Block 4 puts in `detail`
- **Error (timeout / connection refused):** raises
  `RAGServiceError(detail="connection_error")`
- **Error (any other non-200 status):** raises
  `RAGServiceError(detail=f"unexpected_status_{status_code}")`
- The wrapper itself does not retry — retry policy lives in the LangGraph
  edge (`rag_retry_count < 2`), so the tool function stays a thin, easily
  unit-testable translation of "HTTP call in, typed result or typed
  exception out"

## Tool 2 — Cypher tool (Block 3 graph)

Deliberately **not** a free-form "run whatever Cypher the LLM writes" tool
— the agent's multi-step task is fixed (drug distribution over a given
patient set), so the tool exposes one parameterized query, not arbitrary
query execution. This avoids Cypher injection from LLM-generated strings
and keeps the tool wrapper's logic — not an external service — the thing
Phase 3's unit tests exercise.

- **Input:** `person_ids: list[int]` (the `rag_patient_ids` from state; if
  empty, the wrapper returns immediately without opening a driver session)
- **Query:**
  ```cypher
  MATCH (p:Patient)-[:PRESCRIBED]->(d:Drug)
  WHERE p.person_id IN $person_ids
  RETURN d.drug_name AS drug, count(DISTINCT p) AS patient_count
  ORDER BY patient_count DESC
  ```
- **Success:** returns
  `{"drug_distribution": [{"drug": "Lisinopril", "patient_count": 4}, ...],
  "patients_queried": len(person_ids)}`
- **Error (Neo4j driver exception — `ServiceUnavailable`, `AuthError`,
  session errors):** raises `GraphServiceError(detail=type(exc).__name__)`
  — mirrors Block 4's `{"error": ..., "detail": "<ExceptionType>"}` shape
  so both tools fail the same way from the agent's point of view
- Read-only: the tool never runs `MERGE`/`CREATE`/`DELETE` — Block 3's
  graph is a dependency this repo consumes, never writes to

## Structured output schema

```python
class ClinicalAnswer(BaseModel):
    question: str
    answer: str                          # prose answer synthesised from both tools
    rag_patient_ids: list[int]           # person_ids returned by RAG
    graph_result: dict                   # raw result from the Cypher follow-up
    confidence: Literal["high", "medium", "low"]
    caveat: str | None                   # e.g. "Recall is low — top_k=5 may miss patients"
```

- `confidence` is set by the node that produces the answer, not
  freely chosen by Claude in every path: `build_fallback_answer` and
  `build_error_answer` always set `"low"` (deterministic, no ambiguity);
  only `synthesize` lets Claude choose between `"high"`/`"medium"`/`"low"`,
  and even then it is instructed to prefer `"medium"` whenever
  `graph_result["patients_queried"] < 5` — a small denominator is a second,
  independent reason (beyond RAG recall) the count can't be called `"high"`
  confidence.
- `caveat` is `None` only on the full-success path when
  `patients_queried >= 5`. Every short-circuit or error path sets a
  specific, non-generic caveat (see Nodes above) — this is enforced by the
  eval harness's structured-output-validity check (see Eval task set
  design), not left to convention alone.

## Multi-step clinical task design

**Question template:** "Of patients with `{condition}` and `{lab} {op}
{threshold}`, how many are on `{drug_a}` vs. `{drug_b}`?"

**Concrete example:** "Of patients with hypertension and SBP > 140, how
many are on Lisinopril vs. Amlodipine?"

**Step 1 (RAG):** the question text is sent to Block 4's `/query`
verbatim — RAG semantically retrieves patients whose chunk text mentions
hypertension and an SBP value, returning up to `top_k` `person_id`s.

**Step 2 (Cypher):** the graph tool runs the fixed drug-distribution query
scoped to exactly those `person_id`s (not the true, larger population of
all hypertensive SBP>140 patients — RAG's recall of 0.073 means most of
that true population is never retrieved). This is the deliberate design
point: the graph step's output is **exact over an approximate set**, and
`caveat` must say so whenever the RAG-retrieved set is small enough that a
2–3 patient difference would flip which drug "wins."

**Step 3 (synthesize):** Claude turns the drug-distribution dict into a
prose sentence naming the winning drug and the counts, citing the specific
`person_id`s RAG found, and setting confidence/caveat per the rules above.

This template generalizes across Block 3's 11 conditions, 17 drugs, and 4
lab values (SBP, BMI, Glucose, HbA1c) — the eval task set (below) uses
different condition/lab/drug-pair combinations from the same whitelist,
not just the SBP/hypertension example.

## Behavior when RAG returns "I don't know" (retrieved_count = 0)

**Short-circuits.** The graph tool is not called. Rationale: the graph
tool's only input is `rag_patient_ids`; with an empty list there is
nothing to aggregate, and calling Neo4j anyway would either need a
special-cased "return empty distribution for empty input" path in the tool
(untestable against anything meaningful) or would need to fall back to
querying the *whole* graph (a different, larger, and misleading result
that silently drops the "only among RAG's retrieved patients" framing the
rest of this spec relies on). Skipping is also consistent with Block 4's
own precedent: it does not call Claude when retrieval is empty, for the
same "nothing to reason about, don't pay for it" reason. `build_fallback_answer`
still returns a fully valid `ClinicalAnswer` — the acceptance criterion
"structured output for every run" holds even on this path.

## Tracing requirements

- LangSmith wraps the LangGraph app (`LANGCHAIN_TRACING_V2=true`) so every
  node execution is a traced run under one parent run per agent invocation.
- Every node's run captures latency automatically (LangSmith's default).
  `call_rag`/`call_graph` have no token counts (not LLM calls) — this is
  expected and not an error in the trace.
- `synthesize`'s run additionally captures `usage.input_tokens` and
  `usage.output_tokens` from the Anthropic response object.
- Retried nodes (`call_rag`, `call_graph`) appear as multiple runs under
  the same parent when retries fire — this is intentional, so a slow/flaky
  dependency is visible in the trace, not hidden by the retry.

## Per-run cost + token logging

Every agent invocation appends one JSON line to `data/logs/runs.jsonl`:

```json
{
  "run_id": "...",
  "question": "...",
  "timestamp": "...",
  "node_latency_ms": {"call_rag": 142, "call_graph": 38, "synthesize": 891},
  "claude_input_tokens": 612,
  "claude_output_tokens": 187,
  "cost_usd": 0.0041,
  "total_latency_ms": 1071,
  "outcome": "success" | "rag_empty" | "tool_error"
}
```

`cost_usd` is computed from a small hardcoded per-token rate table for
`claude-sonnet-4-6` (input/output rates as separate constants) — rates must
be confirmed against Anthropic's current published pricing at
implementation time (Phase 4), since this spec is not the source of truth
for pricing and rates can change.

## Eval task set design

- `data/eval/tasks.json`: **≥10 fixed multi-step tasks**, each following
  the question template above, drawing from Block 3's real whitelist (11
  conditions, 17 drugs, 4 labs) so tasks stay answerable against real data.
  - **≥7 answerable tasks** — realistic condition + lab-threshold + named
    drug-pair questions, varied across different conditions/labs/drugs (not
    all hypertension/SBP)
  - **≥3 short-circuit tasks** — deliberately reference a condition outside
    Block 3's 11-condition whitelist (e.g. "chronic kidney disease"),
    expected to produce `retrieved_count = 0` and exercise the
    `build_fallback_answer` path
- **Ground truth is computed, not hand-typed**, and is fully
  reproducible: Block 4's retrieval is deterministic (same embedding model,
  same index, same question → same ranked chunks — see Block 4's own
  Reproducibility section) and the graph tool's Cypher is deterministic
  against a static Neo4j graph. So for each answerable task, `scripts/
  build_eval_answer_key.py` runs the real `call_rag` step once, records the
  resulting `rag_patient_ids` as the golden ID set, then runs the real
  `call_graph` step against that golden set and records `graph_result` as
  the golden aggregate. Re-running the builder against an unchanged
  RAG/graph deployment must reproduce the same golden values — if it
  doesn't, that's a signal the RAG index or graph data changed underneath
  the eval, not that the eval is flaky.
- **Three scoring dimensions per task, all three required for a pass (per
  key question 4 — this eval measures all three, not just one):**
  1. **Tool-call correctness** — `call_graph` was invoked iff
     `retrieved_count > 0` (never invoked on a short-circuit task, always
     invoked on an answerable task)
  2. **Structured output validity** — `ClinicalAnswer.model_validate`
     succeeds; `confidence` is a valid `Literal`; `caveat` is `None` only
     when the full-success, `patients_queried >= 5` path was taken
  3. **Answer accuracy** — `rag_patient_ids` exactly matches the golden ID
     set and `graph_result` exactly matches the golden aggregate (both are
     deterministic, so exact match — not a similarity score — is the
     correct bar)
- A task **passes** only if all three dimensions pass. **Task success rate
  = passed / total.** `scripts/run_eval.py` writes a reproducible score
  report to `docs/eval_results.md`, mirroring Block 4's own
  reproducible-score precedent.
- Note on scope: this eval does not re-derive the *true* population for
  each answerable task (e.g. the actual count of all hypertensive,
  SBP>140 patients in the graph, independent of what RAG retrieved) — that
  would be testing Block 4's retrieval quality, which Block 4's own eval
  harness already covers. This eval tests whether *this agent* correctly
  chains, aggregates, and reports on top of whatever Block 4 returns.

## CI regression gate

- **Threshold: task success rate ≥ 0.70.** Below that, `scripts/run_eval.py`
  exits non-zero.
- `.github/workflows/ci.yml` runs on every push: `pytest` (unit tests, Phase
  3) then `scripts/run_eval.py` (requires Block 4's API and Block 3's Neo4j
  reachable in CI — see Known limitations for how this is resolved) then
  checks the exit code. A non-zero exit from either step fails the build.
- 0.70 (not a stricter number) is chosen because two of the three scoring
  dimensions (tool-call correctness, structured output validity) are
  expected to be near-deterministic once the agent is implemented
  correctly, while the third (answer accuracy, an exact-match bar against
  a live external service two hops away) has more surface area for
  incidental drift — 0.70 catches a real regression without making the
  build flaky on a single edge-case task.

## Phases (SDD + TDD, per project workflow)

| Phase | Deliverables |
|---|---|
| 1 | `docs/spec.md` (this document) |
| 2 | `docs/plan.md`, `docs/tasks.md` |
| 3 | `data/eval/tasks.json`, `scripts/build_eval_answer_key.py`, `scripts/run_eval.py` (harness only — agent doesn't exist yet), `tests/test_rag_tool.py` (mocked HTTP), `tests/test_graph_tool.py` (mocked Neo4j driver) — all failing at this point, correctly |
| 4 | `scripts/rag_tool.py`, `scripts/graph_tool.py`, `scripts/agent.py` (LangGraph app), `scripts/schemas.py` (`ClinicalAnswer`, `AgentState`), LangSmith wiring, `data/logs/runs.jsonl` logging — tests go green |
| 5 | `.github/workflows/ci.yml` — pytest + eval harness on every push, 0.70 regression gate |

Each phase branches from the previous phase's branch tip (Block 3/4
convention), gets its own PR.

## Scope

Block 5 does not include:
- A general-purpose ReAct-style agent that writes its own Cypher — the
  graph tool is one fixed, parameterized query (see Tool 2 contract)
- Multi-turn conversation or follow-up questions — one question in, one
  `ClinicalAnswer` out, same as Block 4's single-turn API
- Re-deriving Block 4's retrieval-quality metrics (precision/recall) —
  that eval already exists in Block 4; this repo's eval measures agent
  orchestration and output correctness on top of it
- Authentication on any new interface (this agent is invoked as a script/
  library, not exposed as its own HTTP API in this block)

## Known limitations

- **CI must reach two live local-only services** (Block 4's `uvicorn` API,
  Block 3's Neo4j). This is the one open question Phase 2 (`docs/plan.md`)
  must resolve concretely — options include a GitHub Actions job that
  spins up both as service containers, or marking the live-eval CI step
  as a separate job gated on a self-hosted runner. Phase 1 (this spec)
  flags the problem; Phase 2 picks the mechanism.
- **Answer accuracy in eval is capped by whatever Block 4 returns**, not
  by this agent's own correctness — a change to Block 4's index or
  threshold could shift golden values and look like a Block 5 regression.
  Re-running `build_eval_answer_key.py` after any known Block 4 change is
  the mitigation, not automatic detection.
- **`caveat` correctness relies on the `synthesize` prompt**, not a
  code-level check that the prose text actually mentions the low-recall
  risk — the eval's structured-output-validity check only confirms
  `caveat` is non-null on the right paths, not that its *content* is
  accurate. Same class of limitation Block 4 documented for citation
  grounding.

## Functional requirements

Block 5 must:
1. Wrap Block 4's `POST /query` as a typed tool function that returns a
   typed result or raises a typed error — never a raw `requests` exception.
2. Wrap a fixed, parameterized Cypher query (drug distribution over a given
   patient-ID set) against Block 3's Neo4j as a typed tool function with
   the same typed-result/typed-error contract.
3. Run both tools inside a LangGraph state machine with the node/edge
   design in this spec — including short-circuiting the graph tool when
   RAG retrieves nothing, and retrying each tool up to 2 times on a
   transient error before degrading to a structured error answer.
4. Produce a `ClinicalAnswer` (Pydantic v2) on every run, with no code path
   that returns free text instead.
5. Trace every node (LangSmith), with token counts captured for the
   `synthesize` node and latency captured for all nodes.
6. Log per-run cost and token usage to `data/logs/runs.jsonl`.
7. Provide a fixed eval task set (≥10 tasks, ≥3 short-circuit) with
   reproducible, programmatically-computed golden values.
8. Score three dimensions per eval task (tool-call correctness, structured
   output validity, answer accuracy) and report task success rate.
9. Run pytest + the eval harness in GitHub Actions on every push, failing
   the build when task success rate drops below 0.70.

## Success criteria

Block 5 is complete when:
- Both tool wrappers have passing unit tests with mocked externals
  (Phase 3 tests, initially red, later green)
- The agent answers the example multi-step question end-to-end, producing
  a valid `ClinicalAnswer` with non-empty `graph_result`
- A RAG-miss question correctly short-circuits (graph tool not called,
  fallback answer still structurally valid)
- LangSmith shows a full trace (all nodes, tokens on `synthesize`) for at
  least one real run
- `data/logs/runs.jsonl` has an entry with cost and token counts for that run
- `scripts/run_eval.py` produces a reproducible task success rate against
  `docs/eval_results.md`
- GitHub Actions runs pytest + the eval harness on push and fails the build
  when the score drops below 0.70 (verified by deliberately breaking
  something and confirming CI goes red)
