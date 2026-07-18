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

The agent needs to be told how to reach three things, kept out of the
codebase itself, in a local, git-ignored settings file:

| What | Purpose |
|---|---|
| Search service address | where to send questions for semantic search |
| Graph database address, username, password | where to run the exact drug count |
| Language model key | authenticates the answer-writing step |

A template file listing these (with no real values filled in) is
committed to the repo, so anyone can see what's needed without seeing the
actual secrets.

## What the agent does

**Question pattern:** "Of patients with `{condition}` and `{lab} {above/
below} {value}`, how many are on `{drug A}` vs. `{drug B}`?"

**Example:** "Of patients with hypertension and SBP > 140, how many are on
Lisinopril vs. Amlodipine?"

Three steps:
1. Send the question to the RAG service. It returns a list of matching
   patients.
2. Send that patient list to the graph. It returns an exact count of how
   many of those patients are on each drug.
3. Combine both results into one structured answer, with a plain-English
   summary and a note on how much to trust the count.

**Important honesty point:** the RAG service does not find every matching
patient — it only returns a handful of likely matches. So the graph's
count is exact, but only over the patients RAG happened to find, not
every matching patient in the system. The agent must say so whenever that
matters (see Structured output, `caveat` field).

**Picking out the two named drugs:** the graph step always returns a
count for every drug the checked patients are on, not just the two named
in the question. Matching "Lisinopril" and "Amlodipine" (or whichever two
drugs the question named) against that full list happens during the
answer-writing step — it reads the original question and picks out the
matching rows by name. A patient can be on both named drugs, on neither,
or on some other drug entirely, so the two counts are not guaranteed to
add up to the total number of patients checked — the write-up should not
assume they do.

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

The agent does not retry inside the tool itself — retries happen at the
agent level (see Agent steps).

The list of matching patients used in later steps (`rag_patient_ids`) is
built by taking the patient IDs from this result, removing duplicates (a
patient can show up more than once if several of their records matched),
and ordering them by match score, highest first — ties broken by patient
ID. This makes the order the same every time, given the same input.

### Tool 2 — exact drug count

Runs one fixed graph query: given a list of patient IDs, count how many
of them are on each drug. It never runs an arbitrary, agent-written query
— only this one fixed question, answered exactly. This keeps the tool
simple, predictable, and safe (no risk of a malformed or unsafe query
being generated on the fly). It only ever reads from the graph — it never
changes it.

| | |
|---|---|
| Input | a list of patient IDs |
| Output | a count of patients on each drug, and how many patients were checked |
| Output (empty input) | returns immediately with nothing to count — no query is run |
| Output (failure) | a clear error naming what went wrong |

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

Rules for filling these in:
- `confidence` is `low` whenever the graph step didn't run, the graph step
  failed, or the answer-writing step itself failed.
- When the graph step succeeded, `confidence` depends on how many
  patients were actually checked: fewer than 3 patients is still `low`
  (too small a group to trust), 3 to 9 patients is `medium`, and 10 or
  more patients is `high`.
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
3. **Count** — call the graph tool with that patient list, using the same
   retry rule as step 1 (up to 2 retries, 3 attempts total, only for
   failures that look temporary). If it still fails, produce an answer
   using only the search results, with a caveat explaining the count is
   missing.
4. **Answer** — combine both results into the structured answer described
   above, using a plain-English write-up of the findings. If this
   write-up doesn't come back correctly formed, try once more with a
   stricter instruction; if it still fails, fall back to the fixed
   wording for this case (see the outcome table above) instead of
   returning something invalid.

Steps 2 and 3's fallback/error paths produce the structured answer
directly, without writing any new prose. Step 4 is the only step that
composes new text, and it's only attempted when both tools actually
succeeded.

## Tracing and logging

- Every step of every run is traced, with how long each step took.
- The step that writes the final answer also records how many words
  ("tokens") it used, since it's the only step that uses a language model.
- Every run is logged with: the question, time spent per step, tokens
  used, an estimated cost in dollars, and the outcome (answered, nothing
  found, or a tool failure). These logs are written to `data/logs/runs.jsonl`,
  one line per run. This file is generated output, not source code, so it
  isn't committed to the repo.
- The exact dollar-rate used to estimate cost needs to be checked against
  the language model provider's current published pricing when this is
  built — it isn't fixed in this document, since pricing can change over
  time.

## Evaluation

A fixed set of at least 10 test questions, written once and reused every
time:
- At least 7 are answerable questions, covering a mix of conditions,
  drugs, and lab values.
- At least 3 are deliberately unanswerable (asking about something outside
  the system's scope), to check that the agent correctly says "nothing
  found" instead of guessing.

For each answerable question, the correct patient list and correct drug
count are worked out once, ahead of time, by actually running the two
tools for real — not typed in by hand.

The exact list of valid conditions, drugs, and lab values already exists
in the graph database itself, from earlier work — it isn't repeated in
this document, since a copy here could go stale. Whoever writes the 10+
questions should check the live graph directly for the current list,
rather than assume one, so "deliberately out of scope" questions are
genuinely out of scope and "answerable" questions are genuinely
answerable.

Each test question is checked on three things:
1. Did the agent call the right tools in the right order (skipping the
   count step only when it should)?
2. Is the output correctly structured (all fields present and valid)?
3. Does the answer match the correct patient list and count exactly?

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
  checks that this write-up is worded accurately — the evaluation only
  checks the underlying patient list and counts it's built from, not the
  sentence itself. Every other outcome uses the fixed wording in the
  table above, so there's nothing to double-check there.
- Running the test suite in CI requires both the search service and the
  graph database to be reachable there — how exactly that's set up is
  decided during planning, not in this document.

## Success criteria

This block is complete when:
- The agent answers the example question end-to-end with a valid,
  non-empty result.
- A deliberately unanswerable question correctly short-circuits to a
  fallback answer.
- A full trace (all steps, with token counts on the answer-writing step)
  is visible for at least one real run.
- A run log entry exists with cost and token counts.
- The evaluation produces a repeatable score.
- The CI build fails when the score drops below 70% (confirmed by
  deliberately breaking something and watching the build turn red).
