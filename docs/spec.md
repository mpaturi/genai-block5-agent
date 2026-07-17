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
- When the graph step didn't run (nothing found, or a failure), or when
  very few patients were checked, `confidence` is `low` and `caveat`
  explains why.
- `confidence` is only `high` when the graph step succeeded and checked a
  reasonably sized patient group.
- The object is always valid — there is no path through the agent that
  skips producing one.

### Exact wording for each outcome

Only the full-success case writes a brand-new sentence — since it's the
only case with real numbers to describe, and those numbers are different
every time. The other three outcomes always use the same fixed wording,
so tests can check against it exactly:

| Outcome | `answer` | `rag_patient_ids` / `graph_result` | `caveat` |
|---|---|---|---|
| Nothing found | "I don't know — I couldn't find any patient records relevant to that question." (the same message the search service itself already uses) | both empty | "No patients were found for this question, so the drug count step was skipped." |
| Search step broken | "I wasn't able to answer this question because the patient search step could not be completed." | both empty | "The patient search service failed after repeated attempts." |
| Graph step broken | "Search found matching patients, but the exact drug count could not be completed." | patient list filled in from the search step, graph result empty | "The drug count step failed after repeated attempts. This answer is based on search results only, without an exact count." |
| Full success | a new sentence written by the agent, naming the counts and citing patient IDs | both filled in | none, unless very few patients were checked (see rules above) |

`confidence` is `low` for the first three rows and only `high`/`medium`
for the last row.

## Agent steps

The agent moves through a fixed sequence of steps:

1. **Search** — call the semantic search tool. On a temporary failure, try
   again (up to twice) before giving up.
2. **Decide** — if nothing was found, skip straight to a fallback answer.
   If the search tool failed twice, skip straight to an error answer. If
   there's a patient list, continue.
3. **Count** — call the graph tool with that patient list. On a temporary
   failure, try again (up to twice) before giving up. If it still fails,
   produce an answer using only the search results, with a caveat
   explaining the count is missing.
4. **Answer** — combine both results into the structured answer described
   above, using a plain-English write-up of the findings.

Steps 2 and 3's fallback/error paths produce the structured answer
directly, without writing any new prose — only step 4 needs to compose
new text, and only when both tools actually succeeded.

## Tracing and logging

- Every step of every run is traced, with how long each step took.
- The step that writes the final answer also records how many words
  ("tokens") it used, since it's the only step that uses a language model.
- Every run is logged with: the question, time spent per step, tokens
  used, an estimated cost in dollars, and the outcome (answered, nothing
  found, or a tool failure).

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

## Known limitations

- The evaluation's "correct" counts depend on whatever the search service
  currently returns. If that service's behavior changes later, the
  correct answers may need to be recalculated.
- The `caveat` field is written by the language model — nothing
  automatically double-checks that its wording is accurate, only that it
  exists when it's supposed to.
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
