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
every matching patient in the system. This is not a hypothetical
gap — measured directly against the graph's true patient counts (not
estimated, and not borrowed from Block 4's own, separate eval set) at the
agent's actual setting (`top_k=5`), real recall across Block 5's own 8
answerable questions is **0.000**. Concretely: "Essential hypertension,
SBP > 140" has 99 real matching patients in the graph, and search returns
zero of them.

Raising `top_k` was investigated as a possible mitigation, and ruled out
with evidence rather than assumed: Block 4's API hard-rejects any `top_k`
above 20 (HTTP 422, confirmed by a live call), so 20 is a real ceiling,
not a setting this project simply chose not to raise. Even at that
ceiling, mean recall only reaches 0.059, with 5 of the 8 questions still
finding zero real matches at any setting tested.

This was also spot-checked by hand for confidence, not just trusted from
the measurement script: confirmed directly against the graph that exactly
1 of 117 real Atrial fibrillation patients has SBP > 150, matching the
measured result exactly — so this is a real property of the data, not a
bug in how it was measured.

The Tool 2 verification step (see Tool 2) guarantees the count is
accurate over whichever few patients are found — but it does not, and
cannot, fix this. It's a Block 4 retrieval-quality limitation, out of
Block 5's scope to fix (see Scope). The agent must say so whenever that
matters (see Structured output, `caveat` field).

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
| Input | a question, and how many results to return (1–20, default 5) |
| Output (match) | a short prose answer, a list of matching patients, how many were found |
| Output (no match) | an explicit "nothing found" result — not an error |
| Output (failure) | a clear error, distinguishing "service down" from "bad input" |

The question this tool receives is built directly from the `condition`,
`lab`, `comparison`, and `value` fields (see What the agent does) —
never the assembled full question string, and never including
`drug_a`/`drug_b`. This text is built by one shared function (see
`scripts/schemas.py` in plan.md), not reimplemented separately anywhere
it's needed — `rag_tool.py` and `build_eval_answer_key.py` (see
Evaluation) both call it, so they always send RAG the exact same text
for the same fields. Two independently written versions of this
formatting logic could drift in wording while both still technically
follow this rule, and since RAG's matching is semantic, that drift could
silently change which patients come back — which is exactly the kind of
mismatch the golden answer key is supposed to catch, not cause.

The agent always calls this tool at its default of 5 results; it never
overrides that number. This isn't optional: the confidence tiers (see
Structured output) are calibrated specifically against 5 being the
normal number of patients found, so a different number here would
silently throw off what "high confidence" is supposed to mean.

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
| `graph_result` | the exact count result from the graph step |
| `confidence` | `high`, `medium`, or `low` |
| `caveat` | a short note on anything that limits trust in the answer, or nothing if there's no caveat |

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
and `graph_result` are always filled in directly by the agent's own code,
copied straight from what steps 1–3 already found — the language model
never generates these. `confidence` is also always computed directly by
code, from the patient-count rule below — it's a fixed, number-based
decision, not something that benefits from the model's judgment, so it's
never left up to it. `caveat` works the same way as `confidence`: it's
always fixed template text, chosen by code, based on which step failed or
how many patients were checked — never freely written either.

The only field genuinely written by the language model is `answer`, and
only on the one path where both tools succeeded (step 4 actually runs) —
there, it tries to write one plain-English sentence describing the
findings. If that attempt doesn't come back as a usable sentence, even
after one retry, the agent substitutes the fixed "Answer step failed"
wording instead — see the outcome table below. On every other path
(nothing found, search broken, graph broken), step 4 never runs at all,
and `answer` is also fixed text from the outcome table.

Rules for filling these in:
- `confidence` is `low` whenever the graph step didn't run, the graph step
  failed, or the answer-writing step itself failed.
- When the graph step succeeded, `confidence` depends on how many
  patients were actually verified (see Tool 2 — the number who passed the
  condition/lab check, not the raw number RAG returned): fewer than 3
  verified patients is `low` (too small a group to trust), 3 or 4 is
  `medium`, and 5 or more is `high`. These thresholds are unchanged from
  before the Tool 2 verification fix and are still deliberately set
  against the search tool's default of 5 results per question (see Tool
  1) — a boundary like "10 or more" would make `high` confidence
  unreachable at the default setting, which defeats the point of having
  the tier at all. They now simply attach to a stronger, verified claim
  instead of a raw, unverified one.
- **What this tier does and doesn't mean:** it reflects how large the
  *verified* sample was — not how complete that sample is against the
  true population. A `high` result means "5 or more patients were
  confirmed to genuinely match, and the count among them is exact." It
  does not mean "this is most, or even much, of the true matching
  population." Given the real recall numbers measured directly against
  the graph (see "Important honesty point" above — 0.000 at the agent's
  actual `top_k=5` setting, and only 0.059 even at Block 4's hard
  `top_k=20` ceiling), real runs will rarely reach `high` confidence
  anymore. That is the correct, honest behavior of this tier, not a bug:
  a small verified sample is exactly what a low-recall retrieval step
  should produce, and this tier is supposed to say so plainly rather than
  paper over it.
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

| Outcome | `answer` | `rag_patient_ids` / `graph_result` | `caveat` |
|---|---|---|---|
| Nothing found | "I don't know — I couldn't find any patient records relevant to that question." (the same message the search service itself already uses) | both empty | "No patients were found for this question, so the drug count step was skipped." |
| Search step broken | "I wasn't able to answer this question because the patient search step could not be completed." | both empty | "The patient search service failed after repeated attempts." |
| Graph step broken | "Search found matching patients, but the exact drug count could not be completed." | patient list filled in from the search step, graph result empty | "The drug count step failed after repeated attempts. This answer is based on search results only, without an exact count." |
| Answer step failed | "I found matching patients and counted their drugs, but wasn't able to put together a valid written answer." | both filled in — the underlying data is fine, only the write-up failed | "The final write-up step failed, even after retrying once. The patient list and drug counts above are accurate; only the summary sentence is missing." |
| Full success | a new sentence written by the agent, naming the counts and citing patient IDs | both filled in | none, unless the confidence rule above calls for one |

`confidence` is `low` for the first four rows and `high` or `medium` only
for the last row, based on the rule above.

## Agent steps

Both tools use a fixed 10-second timeout on their calls — if a call takes
longer than that without responding, it's treated the same as an outright
failure, and the retry rule below applies. Both the search service and
the graph database run locally, so 10 seconds is generous enough to rule
out "just a bit slow" while still failing fast on a real outage, rather
than leaving a run hanging.

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
  found, or a tool failure), and whether the count step actually ran.
  These logs are written to `data/logs/runs.jsonl`, one line per run.
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
  through `scripts/run_all.py`.

## Known limitations

- The evaluation's "correct" counts depend on whatever the search service
  currently returns. If that service's behavior changes later, the
  correct answers may need to be recalculated.
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
- Because the evaluation calls the real language model (see Evaluation),
  every CI run that reaches the evaluation step makes real, paid calls to
  it for each answerable question — this is a real, ongoing cost of
  running CI on every push, not a one-time setup cost, and it also adds
  real, variable latency to every run. This is an accepted tradeoff, made
  necessary by needing the real, whole agent to run (see Notes on build
  order in plan.md) — not something this spec attempts to eliminate.
  **The evaluation score itself stays fully deterministic despite this:**
  none of the three scored dimensions ever look at the model's free-text
  `answer` sentence, only at fields that are always code-computed (see
  Structured output) — and any failed attempt at that sentence falls back
  to fixed, valid wording rather than producing something broken. So the
  model's real variability affects cost and speed, never the score.
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
