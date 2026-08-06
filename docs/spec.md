# Block 5 Specification

## Project title

Single-Agent Clinical Reasoning App

## Goal

Build an agent that answers a clinical question in two steps: it uses
semantic search to find the patients a question is about, then runs an
exact count on the graph over exactly those patients. It always returns a
structured, validated answer — never free text — and every run is traced,
timed, and cost-logged.

## Background

The 16-week plan builds this agent on top of two earlier pieces of work:
a graph database of patients, conditions, and drugs, and a RAG service
that answers questions in plain English using that data. Neither tool
alone can answer a question like "how many patients with hypertension and
high blood pressure are on Lisinopril vs. Amlodipine?" — the RAG service
can find matching patients but can't count reliably, and the graph can
count exactly but only for someone who already has a patient list and
knows how to query it. This agent chains the two: semantic search finds
the patients, the graph counts them.

## Technology

- Language: Python.
- The step that writes the final answer uses Claude, specifically the
  `claude-sonnet-4-6` model — a step up from the model the search service
  uses, since this step has to reason across two combined results instead
  of just describing one.
- The agent's step-by-step flow is built with LangGraph; each run is
  traced with LangSmith.
- The answer object's shape (see Structured output) is enforced with
  Pydantic.
- The graph tool connects to Neo4j using the same driver version the
  graph database itself was built with.
- Tests use pytest.
- Exact library versions get pinned once installed, during the build
  phase — this list names what's used, not exact version numbers.

## Configuration

The agent needs to be told how to reach four things, kept out of the
codebase itself, in a local, git-ignored settings file:

| What | Purpose |
|---|---|
| Search service address | where to send questions for semantic search |
| Graph database address, username, password | where to run the exact drug count |
| Language model key | authenticates the answer-writing step |
| Tracing service key and project name | authenticates and labels traces sent to LangSmith (see Technology) |

A template file listing these (with no real values filled in) is
committed to the repo, so anyone can see what's needed without seeing the
actual secrets.

## What the agent does

**Question pattern:** "Of patients with `{condition}` and `{lab} {above/
below} {value}`, how many are on `{drug A}` vs. `{drug B}`?"

**Example:** "Of patients with hypertension and SBP > 140, how many are on
Lisinopril vs. Amlodipine?"

**Verified against the graph's real data, not just handed to search as
text:** the `condition` and `lab`/`comparison`/`value` criteria are not
only used to phrase what gets sent to RAG (see step 1 below) — the graph
step (see Tool 2) checks every RAG-returned patient against the graph's
own stored condition and lab values and drops anyone who doesn't actually
satisfy them, before counting drugs. The final count is never just
"whatever RAG's fuzzy match happened to return."

Each question is defined as separate fields — `condition`, `lab`,
`comparison` (above/below), `value`, `drug_a`, `drug_b` — not as one
opaque string. The sentence above is only the assembled, human-readable
form of those fields, used for display, logging, and the `question`
field in the structured output. Keeping the fields separate end to end
is what makes step 1 (below) a plain lookup of which fields to use,
instead of a text-parsing problem.

Three steps:
1. Build the RAG query from the `condition`, `lab`, `comparison`, and
   `value` fields only — never `drug_a`/`drug_b`, and never by parsing
   the assembled question string (see Question pattern above) to guess
   which words are drug names. Send that built query to the RAG service.
   It returns a list of matching patients.
2. Send that patient list to the graph. It returns an exact count of how
   many of those patients are on each drug.
3. Combine both results into one structured answer, with a plain-English
   summary and a note on how much to trust the count.

**Why `drug_a`/`drug_b` are left out of the RAG query:** if they were
included, RAG's semantic search would naturally favor patients whose
records already mention those two drugs — quietly biasing the found
patient set toward people already on one of them. That would undercut
the whole point of the graph step, which exists specifically to give an
exact count that can include patients on neither named drug. Leaving
`drug_a`/`drug_b` out keeps RAG's job limited to what it's actually
suited for — matching on condition and lab values — and leaves the drug
comparison to the graph's exact count.

**Important honesty point:** the RAG service does not find every matching
patient — it only returns a handful of likely matches. So the graph's
count is exact, but only over the patients RAG happened to find, not
every matching patient in the system. This gap is real, but it is now
substantially smaller than it was: wiring in Block 4's Phase 7 metadata
filter and raising Tool 1's default `top_k`, first to 20 and then, once
Block 4 raised its filtered-only ceiling, to 25 (see Tool 1 above)
measurably improved it, re-measured directly against the graph's true
patient counts (not estimated, and not borrowed from Block 4's own,
separate eval set), across the same 8 answerable questions as before.

**The real, current number: mean recall is 0.789**, up from 0.000 at the
old `top_k=5`, unfiltered setting, 0.059 at Block 4's old `top_k=20`
unfiltered ceiling, and 0.761 at the filtered `top_k=20` setting. Every
one of the 8 questions now finds at least one real match — zero of them
find nothing, down from 5 of 8 before filtering went in. Per question,
the true population size in the graph versus what search actually finds
(and Tool 2 verifies):

| Question (condition / lab) | True matching patients | Found & verified | Recall |
|---|---|---|---|
| Essential hypertension / SBP > 140 | 99 | 25 | 0.253 |
| Osteoporosis / BMI < 22 | 3 | 3 | 1.000 |
| Pulmonary embolism / SBP < 100 | 8 | 8 | 1.000 |
| Atrial fibrillation / SBP > 150 | 1 | 1 | 1.000 |
| Hyperlipidemia / HbA1c > 7 | 3 | 3 | 1.000 |
| Congestive heart failure / SBP < 110 | 18 | 18 | 1.000 |
| Streptococcal pharyngitis / BMI < 25 | 397 | 25 | 0.063 |
| Anemia / Glucose > 150 | 19 | 19 | 1.000 |

Honestly, the improvement is real but uneven, not a uniform fix. Six of
the eight questions now find every real match (recall 1.000) — up from
four at the old `top_k=20` ceiling, since raising it to 25 was enough to
close the last small gaps for Congestive heart failure (16 of 18 before,
18 of 18 now) and Anemia (18 of 19 before, 19 of 19 now). But the two
questions with the largest true populations — Essential hypertension (99
patients) and Streptococcal pharyngitis (397 patients) — are still capped
hard by Tool 1's `top_k=25` ceiling itself, not by filter or semantic
quality: across all 8 questions, every single patient the filter returns
genuinely passes Tool 2's verification (zero false positives measured) —
it simply cannot return more than 25 of them no matter how many really
exist. For those two, recall improved (0.253 up from 0.202, 0.063 up from
0.050) but stays low, for a structural reason that raising `top_k` again
could narrow further but not eliminate: the gap between 25 and a true
population in the hundreds is still enormous, and Block 4's ceiling is a
real limit each time, not a setting this project simply chose not to
raise (confirmed live: a call at `top_k=26` is hard-rejected with HTTP
422, `"top_k must be between 1 and 25"`).

This was also spot-checked by hand for confidence, not just trusted from
the measurement script: confirmed directly against the graph that exactly
1 of 117 real Atrial fibrillation patients has SBP > 150, and search now
finds that one patient — matching the measured result exactly, the same
spot-check fact as before this filter went in.

The Tool 2 verification step (see Tool 2) guarantees the count is
accurate over whichever patients are found — but it does not, and cannot,
guarantee that's every real match. For large-population questions like
Essential hypertension and Streptococcal pharyngitis above, that gap is
still a Block 4 retrieval-ceiling limitation, out of Block 5's scope to
fix (see Scope). The agent must say so whenever that matters (see
Structured output, `caveat` field).

**Picking out the two named drugs:** the graph step always returns a
count for every drug the checked patients are on, not just the two named
in the question. Looking up `drug_a` and `drug_b` (see Question pattern)
in that full mapping is done directly by the agent's own code, before
the language model is ever involved — not by having the model read the
question and figure out which two rows matter. The model's job in step 4
is only to write a sentence describing the two counts it's handed; it
never has to identify which drugs are the relevant ones itself. If
either name isn't a key in the mapping (see Tool 2), that means 0, not a
missing or broken result — a patient can be on both named drugs, on
neither, or on some other drug entirely, so the two counts are not
guaranteed to add up to the total number of patients checked, and either
one landing at 0 is a normal outcome the write-up should handle, not
treat as an error.

## Tools

### Tool 1 — semantic patient search

Calls the existing RAG service with a question and gets back a list of
matching patients with a relevance score for each, or an empty list if
nothing matched.

| | |
|---|---|
| Input | a question, and how many results to return (1–25, default 25) |
| Output (match) | a short prose answer, a list of matching patients, how many were found |
| Output (no match) | an explicit "nothing found" result — not an error |
| Output (failure) | a clear error, distinguishing "service down" from "bad input" |

The question this tool receives is built directly from the `condition`,
`lab`, `comparison`, and `value` fields (see What the agent does) —
never the assembled full question string, and never including
`drug_a`/`drug_b`. This text is built by one shared function (see
`block5_agent/schemas.py` in plan.md), not reimplemented separately anywhere
it's needed — `rag_tool.py` and `build_eval_answer_key.py` (see
Evaluation) both call it, so they always send RAG the exact same text
for the same fields. Two independently written versions of this
formatting logic could drift in wording while both still technically
follow this rule, and since RAG's matching is semantic, that drift could
silently change which patients come back — which is exactly the kind of
mismatch the golden answer key is supposed to catch, not cause.

The agent now calls this tool at its default of 20 results — up from
5 — every time; it never overrides that number.

Tool 1 also sends the question's `condition`, `lab`, `comparison`, and
`value` fields to Block 4's API as structured metadata filter fields, not
just embedded in the free-text query built above. Block 4 uses these to
narrow results to patients whose own graph-derived metadata actually
matches — not just patients whose record text is semantically similar —
per Block 4's Phase 7 filter work (see also Important honesty point
below).

The agent does not retry inside the tool itself — retries happen at the
agent level (see Agent steps).

The list of matching patients used in later steps (`rag_patient_ids`) is
built by taking the patient IDs from this result, removing duplicates (a
patient can show up more than once if several of their records matched),
and ordering them by match score, highest first — ties broken by patient
ID. This makes the order the same every time, given the same input.

### Tool 2 — exact drug count

Given a list of RAG-returned patient IDs, this tool now does two things,
both via one fixed, parameterized Cypher query — never an arbitrary,
agent-written query. First, it verifies each patient against the graph's
own stored data: does a `HAS_CONDITION` relationship connect them to a
`Condition` node whose `condition_name` matches the question's
`condition`, and does their own `Patient` node's lab property
(`latest_sbp`, `latest_bmi`, `latest_glucose`, or `latest_hba1c` —
whichever the question's `lab` field names) satisfy the
`comparison`/`value` asked for? Anyone who fails either check is dropped.
Second, it counts drugs only among the patients who passed verification —
never over the original, unverified list. This keeps the tool simple,
predictable, and safe (no risk of a malformed or unsafe query being
generated on the fly), and it only ever reads from the graph — it never
changes it.

**Why this verification step exists:** RAG's semantic match can return a
patient whose record merely *mentions* the condition and a lab reading,
without that patient actually having the condition or satisfying the
threshold in the graph's own stored data (see "Important honesty point"
above) — RAG's job is approximate by design. Without checking against the
graph's real values, the "exact" drug count would still be silently built
on top of RAG's fuzziness. Verifying first is what makes the count
genuinely exact, not just exact-sounding.

**Resolved:** "how many patients were checked" (see below, and the
confidence-tier rule in Structured output) now means the number of
patients who passed this verification step — not the number of IDs
originally handed to this tool. No new field name was introduced for
this; the existing meaning was simply tightened to the verified count,
consistently, everywhere it's used.

| | |
|---|---|
| Input | a list of patient IDs, plus the question's `condition`, `lab`, `comparison`, and `value` fields (needed to verify each patient before counting) |
| Output | a count of patients on each drug, among only the patients who passed verification |
| Output (empty input) | returns immediately with nothing to count — no query is run |
| Output (failure) | a clear error naming what went wrong |

The per-drug counts are given back as a mapping from drug name to count
(like a lookup table), not an ordered list — so there's nothing about
their order to ever disagree on. This matters for the evaluation's exact
match check on `graph_result` (see Evaluation): two runs that found the
same counts always compare equal, regardless of what order the graph
happened to return them in.

The mapping only contains entries for drugs at least one checked patient
is actually on — a drug with zero matching patients is left out of the
mapping entirely, not included with a count of 0. Anything that looks up
a drug in this mapping (see "Picking out the two named drugs") must treat
a missing key as a count of 0, never as an error — since "none of the
checked patients are on this drug" is an expected, ordinary result, not a
failure.

"How many patients were checked" always means the number of patients who
passed verification — not the number of IDs originally handed to this
tool. A patient ID that fails verification (wrong condition, or doesn't
satisfy the lab threshold) is dropped before this count is taken and no
longer contributes to it, including contributing zero to every drug's
count — it simply isn't part of the checked group at all. This is the one
number the confidence rule (see Structured output) is based on, so it
needs a single, fixed meaning — it is never recomputed a second way
anywhere else in the agent.

Before running the query, the tool checks that every ID in the list is a
whole, positive number. If any aren't, it fails immediately with a clear
error, rather than sending bad data to the graph.

## When RAG finds nothing

If the semantic search step returns no patients, the agent skips the
graph step entirely — there is nothing to count — and returns a
structured answer saying so. This is a deliberate shortcut, not a
missing feature: it avoids running a meaningless "count zero patients"
query and avoids paying for a step that has nothing to reason about.

## Structured output

Every run returns one answer object with these fields:

| Field | Meaning |
|---|---|
| `question` | the original question |
| `answer` | a plain-English answer combining both tool results |
| `rag_patient_ids` | the patient IDs the semantic search step found |
| `rag_citations` | per-patient chunk-level evidence backing `rag_patient_ids` — see below |
| `graph_result` | the exact count result from the graph step |
| `confidence` | `high`, `medium`, or `low` |
| `caveat` | a short note on anything that limits trust in the answer, or nothing if there's no caveat |
| `outcome` | `answered`, `nothing_found`, or `tool_error` — see the outcome table below |

The final answer object has no separate field for "how many patients
were checked" (see Tool 2) — it is never shown on its own. It only ever
feeds the `confidence` rule below; anyone reading the answer sees its
effect only through `confidence` and `caveat`. This number is *not* the
same as the length of `rag_patient_ids`: the agent still sends every ID
RAG found straight to Tool 2, but Tool 2 now verifies each one against
the graph's real data first (see Tool 2) and only counts the patients who
pass — so `rag_patient_ids` can be longer than the number that actually
determines `confidence`.

Not all fields come from the same place. `question`, `rag_patient_ids`,
`rag_citations`, and `graph_result` are always filled in directly by the
agent's own code, copied straight from what steps 1–3 already found — the language model
never generates these. `confidence` is also always computed directly by
code, from the patient-count rule below — it's a fixed, number-based
decision, not something that benefits from the model's judgment, so it's
never left up to it. `caveat` works the same way as `confidence`: it's
always fixed template text, chosen by code, based on which step failed or
how many patients were checked — never freely written either. `outcome`
is the same again: always one of three fixed, code-chosen values, never
freely written.

`outcome` exists so a caller (a future Block 6 orchestrator, for example)
can tell a genuine tool failure apart from a legitimate low-confidence
success without having to parse `caveat`'s free text to guess which
happened. `tool_error` means a step actually broke — search, the graph
count, or the answer write-up — after exhausting its retries.
`nothing_found` means every step that ran worked correctly and correctly
found no matching patients — not a failure, a true negative.
`nothing_found` and a `low`-confidence `tool_error` can look similar at a
glance (both fixed wording, both `confidence: "low"`), but they mean
different things: one says "the system worked and there's nothing here,"
the other says "the system didn't work." `answered` means step 4 actually
ran and produced a real, freely-written sentence — `confidence` can still
be `low` or `medium` on this path (see the rule below), so `answered`
does not imply `high`; it only means nothing broke.

`rag_citations` is the semantic search step's own chunk-level evidence,
not the graph step's. It holds one entry per patient in
`rag_patient_ids` — same patient set, same best-score-first order, built
from the exact same dedupe pass via `build_rag_citations()` in
`block5_agent/schemas.py` — each entry naming that patient's winning chunk's
ID and the chunk text itself (`patient_id`, `chunk_id`, `snippet`). It
sits next to `rag_patient_ids`, never inside `graph_result`:
`graph_result` is Neo4j's drug-count output only, and mixing RAG chunk
text into it would blur "what Tool 1 retrieved" with "what Tool 2
counted." Like `rag_patient_ids`, it's empty exactly when search found
nothing or failed, and filled in on every path where `rag_patient_ids`
is.

The only field genuinely written by the language model is `answer`, and
only on the one path where both tools succeeded (step 4 actually runs) —
there, it tries to write one plain-English sentence describing the
findings. If that attempt doesn't come back as a usable sentence, even
after one retry, the agent substitutes the fixed "Answer step failed"
wording instead — see the outcome table below. On every other path
(nothing found, search broken, graph broken), step 4 never runs at all,
and `answer` is also fixed text from the outcome table.

Rules for filling these in:
- `outcome` is `answered` only on full success (step 4 ran and produced a
  real sentence); `nothing_found` only when search ran successfully and
  found no matches; `tool_error` on every other path — search, graph, or
  the answer-writing step itself failing after exhausting retries (see
  the outcome table below for the exact mapping).
- `rag_citations` follows `rag_patient_ids` exactly on every path — empty
  wherever `rag_patient_ids` is empty, filled in wherever it's filled in.
- `confidence` is `low` whenever the graph step didn't run, the graph step
  failed, or the answer-writing step itself failed.
- When the graph step succeeded, `confidence` depends on how many
  patients were actually verified (see Tool 2 — the number who passed the
  condition/lab check, not the raw number RAG returned): fewer than 15
  verified patients is `low`, 15 to 24 is `medium`, and 25 — the maximum
  Tool 1's `top_k=25` can ever hand Tool 2 (see Tool 1) — is `high`.

  These boundaries are grounded in the real per-question verified-patient
  counts Block 5's own 8 answerable questions actually produced once
  Block 4 raised its filtered-only ceiling to 25 (see Important honesty
  point above) — 1, 3, 3, 8, 18, 19, 25, 25 — not guessed: they split
  that real distribution into the same shape as the original thresholds
  did, four `low` (1, 3, 3, 8), two `medium` (18, 19), and two `high`
  (25, 25). 15 is also 60% of the new 25 ceiling, the same fraction (12
  of 20) the prior `low` boundary sat at — not the reason it was chosen
  (the real gap between 8 and 18 is what mattered), but a useful
  confirmation it isn't an arbitrary cut. `high` keeps the meaning it has
  always had at every ceiling this project has used (5, then 20, now
  25): reachable at the tool's actual operating ceiling, not trivially
  easy, and not practically unreachable.
- **What this tier does and doesn't mean:** it reflects how large the
  *verified* sample was — not how complete that sample is against the
  true population. A `high` result now means "Tool 1's entire 25-patient
  budget came back verified — every one of them a real, confirmed match,
  and the count among them is exact." It does not mean "this is most, or
  even much, of the true matching population": Block 5's own measured
  recall (see Important honesty point above — mean 0.789, but as low as
  0.063 for the largest true populations) shows a `high`-confidence
  result can still be built on a small slice of patients who really
  exist, when the true population is much larger than the 25-patient
  ceiling. That is the correct, honest behavior of this tier, not a bug:
  it reports how much was verified, never how much exists. Put another
  way, `high` can only ever be produced when RAG's retrieval saturated
  its entire `top_k=25` budget — there is no path to `patients_checked
  == 25` except every one of Tool 1's maximum possible candidates coming
  back and verifying. So `high` doesn't merely allow for an incomplete
  view of the true population; whenever the true population exceeds 25,
  it guarantees one, since retrieval would have kept surfacing matches
  past 25 if it were allowed to. Read `high` as "we maxed out what this
  tool is capable of checking," never as "we found everyone." This
  branch's recalibration keeps that true at the new `top_k=25` setting
  the same way earlier recalibrations kept it true at `top_k=20` and
  `top_k=5` before that.
- `caveat` is filled in on every `low` or `medium` result, explaining why
  — either which step failed, or that the patient group checked was small.
- The object is always valid — there is no path through the agent that
  skips producing one, including when the answer-writing step itself
  fails (see the outcome table below).

### Exact wording for each outcome

Only the full-success case writes a brand-new sentence — since it's the
only case with real numbers to describe, and those numbers are different
every time. Every other outcome always uses the same fixed wording, so
tests can check against it exactly:

| Outcome | `outcome` | `answer` | `rag_patient_ids` / `rag_citations` / `graph_result` | `caveat` |
|---|---|---|---|---|
| Nothing found | `nothing_found` | "I don't know — I couldn't find any patient records relevant to that question." (the same message the search service itself already uses) | all empty | "No patients were found for this question, so the drug count step was skipped." |
| Search step broken | `tool_error` | "I wasn't able to answer this question because the patient search step could not be completed." | all empty | "The patient search service failed after repeated attempts." |
| Graph step broken | `tool_error` | "Search found matching patients, but the exact drug count could not be completed." | patient list and citations filled in from the search step, graph result empty | "The drug count step failed after repeated attempts. This answer is based on search results only, without an exact count." |
| Answer step failed | `tool_error` | "I found matching patients and counted their drugs, but wasn't able to put together a valid written answer." | all filled in — the underlying data is fine, only the write-up failed | "The final write-up step failed, even after retrying once. The patient list and drug counts above are accurate; only the summary sentence is missing." |
| Full success | `answered` | a new sentence written by the agent, naming the counts and citing patient IDs | all filled in | none, unless the confidence rule above calls for one |

`confidence` is `low` for the first four rows and `high` or `medium` only
for the last row, based on the rule above.

## Agent steps

Both tools use a fixed 10-second timeout on their calls — if a call takes
longer than that without responding, it's treated the same as an outright
failure, and the retry rule below applies. Both the search service and
the graph database run locally, so 10 seconds is generous enough to rule
out "just a bit slow" while still failing fast on a real outage, rather
than leaving a run hanging.

Every retry (steps 1, 3, and 4 below) waits between attempts instead of
retrying immediately — a short backoff of `0.5 * attempt_number` seconds
(0.5s before the 2nd attempt, 1.0s before the 3rd), matching Block 6
Phase 8's confirmed formula (`block5_agent/agent.py`'s
`_RETRY_BACKOFF_SECONDS`). Whether a failure is worth retrying at all is
decided by `classify_exception` (`block5_agent/error_classification.py`,
ported from the same Block 6 phase): a caught exception is classified as
`timeout`/`connection_error`/`validation_error`/`unknown`, and for step 4
only the `timeout`/`connection_error` kinds are retried — an allow-list,
matching Block 6 Phase 8's confirmed `cohort_tool.py` pattern exactly.
`validation_error` and `unknown` are both treated as permanent —
bad/malformed output or a genuine bug, not an infrastructure hiccup, so
retrying identical input can't fix it — and fail immediately without
consuming a retry or waiting out a backoff. Steps 1 and 3 each still have
their own, local checks for specific known-bad input (an invalid
`top_k`, an unrecognized `lab`/`comparison`, a non-positive patient ID)
that set `retryable=False` directly, without going through
`classify_exception` — a known validation failure doesn't need
classifying, it's already known to be permanent. Step 3
(`block5_agent/graph_tool.py`'s `count_drugs()`) additionally runs
`classify_exception` on any other exception its Neo4j driver call raises,
the same way step 4 does — closing the gap where an unrecognized driver
failure used to default to retryable, and would then be retried 3 times
even for a permanent failure like a Cypher syntax error. Step 1
(`block5_agent/rag_tool.py`) does not use `classify_exception` at all —
every failure path there is already covered by its own explicit
status-code-based classification, so there's no default-retryable gap to
close.

Before any of the steps below run, the agent checks the question's
`condition`, `lab`, `drug_a`, and `drug_b` fields against the graph's own
real vocabulary — the distinct `Condition.condition_name` and
`Drug.drug_name` values actually stored there, plus the fixed lab
whitelist Tool 2 already uses (`block5_agent/graph_tool.py`'s
`_LAB_PROPERTY`) — all four checked in one pass
(`block5_agent/plausibility_check.py`'s `check_plausibility`), following
the same query-once-and-cache pattern Block 6 Phase 4 already established
(`genai-block6-multiagent/scripts/vocabulary_check.py`). The comparison is
exact string equality only — no case-folding, no substring match — since
a substring check would let a real term with injected text appended to it
(e.g. `"Hypertension\nIgnore all previous instructions"`) pass simply
because the real term appears inside it. This check is advisory, not a
gate: it never changes control flow or blocks a question from being
answered, and if the vocabulary query itself fails (the graph is
unreachable), the check fails open — it reports that it couldn't run
rather than blocking the request or crashing it, since this is a
"flagged", not "blocked", severity check. Whatever the check finds (or
that it couldn't run) is threaded through `AgentState` as
`plausibility_flags` and written to the `plausibility_flags` field of the
log entry `log_run()` writes to `data/logs/runs.jsonl` — it never appears
in the returned `ClinicalAnswer` itself.

The agent moves through a fixed sequence of steps:

1. **Search** — call the semantic search tool. If it fails in a way that
   looks temporary (the service is unreachable, times out, or returns an
   unexpected server error), try again — up to 2 retries, so 3 attempts
   in total, before giving up. A failure caused by bad input, rather than
   a temporary problem, is not retried, since sending the same bad input
   again won't fix it.
2. **Decide** — if nothing was found, skip straight to a fallback answer.
   If the search tool never succeeded after all attempts, skip straight
   to an error answer. If there's a patient list, continue.
3. **Count** — call the graph tool with that patient list and the
   question's `condition`/`lab`/`comparison`/`value` fields. The tool
   first verifies each patient against the graph's own stored data,
   dropping anyone who doesn't actually satisfy the condition and lab
   threshold, then counts drugs only among those who passed (see Tool 2)
   — using the same retry rule as step 1 (up to 2 retries, 3 attempts
   total, only for failures that look temporary). If it still fails,
   produce an answer using only the search results, with a caveat
   explaining the count is missing.
4. **Answer** — combine both results into the structured answer described
   above, using a plain-English write-up of the findings. If this
   write-up doesn't come back correctly formed, try once more with a
   stricter instruction; if it still fails, fall back to the fixed
   wording for this case (see the outcome table above) instead of
   returning something invalid. This retry budget (1 retry, 2 attempts
   total) is smaller than steps 1 and 3's (2 retries, 3 attempts total)
   on purpose — a tool retry is cheap and likely to succeed unchanged once
   a brief network hiccup passes, while a retry here is a second full
   language-model call, slower and more expensive, so it gets a smaller
   budget rather than the same one.

Steps 2 and 3's fallback/error paths produce the structured answer
directly, without writing any new prose. Step 4 is the only step that
composes new text, and it's only attempted when both tools actually
succeeded.

The agent is built so both tools, and the language model call in step 4,
can all be swapped out — the real ones are used by default, but a test
can substitute a fake version that always fails, always returns a
specific result, or always returns a specific (or unparseable) piece of
text, instead. Swapping a tool is what makes it possible to trigger the
search-broken and graph-broken paths on purpose; swapping the model call
is what makes it possible to trigger the answer-step-failed path the same
way — a fake that returns unusable text is how that specific case gets
tested, since neither tool failing has anything to do with that path.
This is what lets `tests/test_agent_answers.py` (see plan.md) check the
exact wording for all three of these paths without needing the real
search service, the real graph, a real outage, or a real, costly,
non-deterministic call to the language model.

## Tracing and logging

- Every step of every run is traced, with how long each step took.
- The step that writes the final answer records how many words ("tokens")
  it used — this is the only language-model call this agent's own code
  makes and controls directly. It is not the only language-model call a
  run triggers, though: Tool 1 calls Block 4's existing `POST /query`
  endpoint, which makes its own internal Claude call whenever it finds a
  match (see Tool 1), to write a prose answer this agent never uses —
  only the patient IDs are pulled out of that response. That internal
  call happens inside Block 4's own service, so this agent has no way to
  measure or trace its tokens directly; only its own step 4 call is
  logged with token counts here (see Known limitations for what this
  means for real, per-run cost).
- Every run is logged with: the question, time spent per step, tokens
  used, an estimated cost in dollars, the outcome (answered, nothing
  found, or a tool failure), whether the count step actually ran, and the
  plausibility check's flags (see Agent steps) — empty when
  `condition`/`lab`/`drug_a`/`drug_b` all matched the graph's real
  vocabulary. These logs are written to `data/logs/runs.jsonl`, one line
  per run.
  This file is generated output, not source code, so it isn't committed
  to the repo.
- That last item — whether the count step ran — is also handed back
  directly from the agent's own function, alongside the answer object
  itself, for whatever called it. This is what the evaluation actually
  reads to check tool-call correctness (see Evaluation) — straight from
  the call it just made, not by going back and searching the log
  afterward, since nothing links a specific log line to a specific
  question. The log file still records it too, for a persistent history
  of every run, but that's a side effect, not the evaluation's source.
- The agent's function returns a third value the same way: `cost_info`,
  a dict with `cost_usd`, `input_tokens`, and `output_tokens` — the same
  real, measured numbers just written to the log entry above, handed back
  directly so a caller doesn't have to go read the log file to see what a
  run cost. It reads 0 tokens/$0 when the answer-writing step was stubbed
  (see Evaluation's `USE_STUB_ANSWER_FN`), since no real Claude call
  happened for that part.
- The exact dollar-rate used to estimate cost needs to be checked against
  the language model provider's current published pricing when this is
  built — it isn't fixed in this document, since pricing can change over
  time.

## Evaluation

A fixed set of at least 10 test questions, written once and reused every
time:
- At least 7 are answerable questions, covering a mix of conditions,
  drugs, and lab values, and a mix of how many patients typically get
  found (so all three confidence tiers — see Structured output — actually
  get exercised by this fixed set, not just `low`/`medium`).
- At least 3 are deliberately unanswerable (asking about something outside
  the system's scope), to check that the agent correctly says "nothing
  found" instead of guessing.

For each answerable question, the correct patient list and correct drug
count are worked out once, ahead of time, by actually running the search
service and the graph database for real — not typed in by hand. This
happens before the agent's own tool wrappers exist yet (see plan.md), so
it's done with simple, throwaway calls straight to the live search
service and the live graph, using the same fixed graph query described in
Tool 2 — not through `rag_tool.py`/`graph_tool.py` themselves, since
those get built afterward and this is a one-time computation, not part
of the shipped agent.

The raw patient list that comes back from the live search service is
deduped and ordered using the exact same rule Tool 1 uses (see Tools) —
duplicates removed, then sorted by score descending, ties broken by
patient ID — before it's written into `answer_key.json`. `rag_patient_ids`
is a list, not a set, so the evaluation's exact-match check on it (see
below) only means something if the golden list is built with the same
ordering rule the real agent will use. Skipping this step would let a
correct agent run fail the check purely because of list order or
leftover duplicates, not because anything was actually wrong.

These computed correct answers are written to their own file,
`data/eval/answer_key.json` — kept separate from `data/eval/tasks.json`,
which holds only the hand-written questions themselves. Keeping them
separate makes clear which file is written by a person (the questions)
and which is generated by a script (the correct answers), and lets the
answer key be recomputed later without touching the questions file at
all. Each entry in the answer key is keyed by the same question ID used
in `tasks.json`, so `run_eval.py` can look up the right correct answer
for each question it runs.

Each answer key entry also includes the expected `confidence` — worked
out from the golden patient count using the same rule as Structured
output — alongside the patient list and drug count. Without this, the
confidence rule could be implemented wrong (an off-by-one on the
tier boundaries, for example) and nothing in this evaluation would ever
catch it, since the patient list and drug count checks say nothing about
whether `confidence` came out right. `caveat` doesn't need its own
separate golden value — it's entirely determined by `confidence` and
which step ran, both of which are already being checked.

The exact list of valid conditions, drugs, and lab values already exists
in the graph database itself, from earlier work — it isn't repeated in
this document, since a copy here could go stale. Whoever writes the 10+
questions should check the live graph directly for the current list,
rather than assume one, so "deliberately out of scope" questions are
genuinely out of scope and "answerable" questions are genuinely
answerable.

Each test question is checked on three things:
1. Did the agent call the right tools in the right order (skipping the
   count step only when it should)? Checked using the "did the count step
   run" value the agent's own function returns directly (see Tracing and
   logging) — not guessed from the final answer alone, since that alone
   can't tell the difference between "the count step correctly never ran"
   and "the count step ran but its result got lost."
2. Is the output correctly structured (all fields present and valid),
   and does `caveat` being present or empty actually match what
   `confidence` says it should be (see Structured output's rules) — not
   just that `caveat` is *a* valid value, but that it's non-empty
   whenever `confidence` is `low` or `medium`, and empty when it's
   `high`?
3. Does the answer match the correct patient list, count, and confidence
   exactly? For the answerable questions, this means looking up that
   question's entry in `answer_key.json` (patient list, drug count, and
   expected `confidence`) and comparing all three against it. The
   deliberately unanswerable questions have no entry there at all — for
   those, this check instead confirms `rag_patient_ids` and `graph_result`
   both came back empty and `confidence` is `low`, since "nothing" is the
   correct answer and there's no golden value to look up.

A question only counts as passed if all three checks pass. The overall
score is the percentage of questions passed.

## CI gate

The test suite and the evaluation both run automatically on every push.
If the evaluation score falls below 70%, the build fails. This threshold
is a starting point, meant to catch a real drop in quality without
failing the build over one edge case.

## Scope

Not part of this block:
- The agent does not write its own graph queries — only the one fixed
  query described above.
- No multi-turn conversation — one question in, one structured answer out.
- No re-checking of the RAG service's own search quality — that's already
  covered elsewhere; this evaluation only checks the agent's own behavior
  on top of it.
- No login or access control on this agent.
- This block does not expose its own web service — it's invoked directly
  as a script, the same way you'd run any of the other pieces by hand or
  through `block5_agent/run_all.py`.

## Known limitations

- The evaluation's "correct" counts depend on whatever the search service
  currently returns. If that service's behavior changes later, the
  correct answers may need to be recalculated.
- `data/eval/ci_graph_seed.cypher`'s q1 population (Essential hypertension,
  SBP > 140) was originally seeded with only the exact 25 patients RAG's
  own `top_k=25` search returns — correct at the time (Phase 4's
  25-patients-checked verification really did match 25 = 25), but too
  small to ever expose the gap described above (see Important honesty
  point): the golden answer and the agent's necessarily-capped output
  could never disagree, no matter how large the true population really
  was. The seed has since been corrected to carry the true, exhaustive
  99-patient population (99 total, Lisinopril 49, Amlodipine 28,
  Hydrochlorothiazide 11 — see `data/eval/answer_key.json`'s q1 entry).
  RAG's own capped search still returns only 25 of those 99, so
  `run_eval.py`'s `_check_answer_accuracy()` scores q1 against a second
  entry, `q1_expected_capped` — the known-achievable answer over the same
  25 patients RAG's real search actually returns (Amlodipine 8, Lisinopril
  10, Hydrochlorothiazide 11 across 25 verified patients) — instead of
  q1's own entry, which stays the true, full 99-patient population for
  reference. Both entries are produced automatically, every time
  `block5_agent/build_eval_answer_key.py` runs, not hand-typed or
  hand-verified once: its q1 special case writes `q1_expected_capped` from
  the same search → verify → count pipeline every other question uses,
  and writes `q1` from a second, independently-written, unbounded Cypher
  query (`_query_full_population()`) that enumerates every matching
  patient directly against the live graph, with no RAG search and no
  `top_k` involved at all — so re-running the script can't silently drop
  or overwrite either entry. **q1 is scored against its known 25-of-99
  cap, not full recall**: the evaluation's pass rate is genuinely 11/11 (see
  `docs/eval_results.md`), but that pass reflects the agent correctly
  reproducing the achievable, capped answer, not evidence it recovered the
  true population — the recall gap described above is real and unchanged,
  just no longer disguised as, or confused with, an eval failure.
- Only the full-success case's `answer` is freely written, by the
  language model, describing the real counts. Nothing automatically
  checks that this write-up is worded accurately — the evaluation checks
  the underlying patient list, counts, and confidence it's built from
  (see Evaluation), but not the sentence itself. Every other outcome uses
  the fixed wording in the table above, so there's nothing to
  double-check there.
- Running the test suite in CI requires the search service, the graph
  database, and the language model to all be reachable there — how
  exactly that's set up is decided during planning, not in this document.
- Proving tracing captures token counts (see Success criteria) and
  running the scored evaluation in CI are two separate concerns with two
  separate needs, and they should not be conflated. Proving tracing works
  only needs one real Claude invocation, done once, not on every CI push.
  The scored evaluation itself never needs a real Claude call at all:
  none of the three scored dimensions — tool-call correctness, structured
  output validity, answer accuracy (see Evaluation) — ever reads the
  free-text `answer` sentence's actual content, only fields that are
  always code-computed (see Structured output). So CI's evaluation run
  can use a stub answer-writing function in place of a real Claude call,
  removing the real, ongoing per-push API cost and variable latency a
  real call would otherwise add on every push.
  **The mechanism for this already exists and is already tested:**
  `run_agent`'s `answer_fn` keyword override — the same swappable pattern
  `tests/test_agent_answers.py` already uses for its fakes (see Agent
  steps). This isn't a new capability, just reusing an existing one in a
  new place, the same way `USE_RAG_FIXTURES` already reuses `search_fn`'s
  override for the search step. **The evaluation score itself stays fully
  deterministic either way:** a stub `answer_fn` changes nothing about
  what the three scored dimensions actually check, since none of them
  ever depended on the model's real variability in the first place — it
  only removes cost and latency the scored path never actually needed.
  (The actual wiring of a stub into `run_eval.py`'s CI path is left for a
  later round — this is a spec-only update.)
- The real per-run language-model cost is actually higher than just the
  step-4 answer-writing call (see Tracing and logging): Tool 1 triggers
  its own internal Claude call inside Block 4's service on every question
  where matches are found, to produce a prose answer this agent discards
  and never traces or logs. So each answerable question run during
  evaluation (and in CI) makes two real, paid language-model calls, not
  one — only the second is visible in this agent's own logs and traces.
  There's no cheaper endpoint on Block 4's side to call instead, since
  this agent only has access to its already-deployed HTTP API — so this
  is an accepted, unavoidable cost of building on top of Block 4 as-is,
  not something this block attempts to fix.

## What I'd do next

Tool 1's `top_k` ceiling (see Tool 1, Important honesty point) is a real,
structural limit on recall for large-population questions, and raising it
again would only narrow that gap, never close it. But for a specific
subset of questions, the ceiling doesn't need to exist at all: whenever a
question is fully answerable from structured filters alone — `condition`,
`lab`, `comparison`, `value`, with no free-text semantic component
actually needed to identify the right patients — the graph database
already stores condition and lab data as exact properties (see Tool 2).
It could enumerate every matching patient directly with one query,
returning the true, complete population, rather than routing through
Tool 1's RAG search and its inherently bounded `top_k` at all.

This is a deliberate, planned architectural improvement, not an
oversight or something this block failed to do — it's scoped out of
Block 5 on purpose (see Scope) and planned instead for Block 6 or Block
8, once agent orchestration/integration work spanning multiple tools is
already underway and a change like this fits naturally alongside it.
Block 5's current behavior — bounded `top_k`, paired with an honest
`caveat` whenever that bound matters (see Structured output) — is
correct and sufficient for what this block is actually responsible for;
it is not a gap this block should attempt to fix on its own.

## Success criteria

This block is complete when:
- The agent answers the example question end-to-end with a valid,
  non-empty result.
- A deliberately unanswerable question correctly short-circuits to a
  fallback answer.
- If the answer-writing step is made to fail on purpose (for a manual
  check), the agent falls back to that case's fixed wording instead of
  crashing or returning something invalid.
- A full trace (all steps, with token counts on the answer-writing step)
  is visible for at least one real run.
- A run log entry exists with cost and token counts.
- The evaluation produces a repeatable score.
- The CI build fails when the score drops below 70% (confirmed by
  deliberately breaking something and watching the build turn red).
