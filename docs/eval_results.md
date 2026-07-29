# Eval Results

This file is produced by `block5_agent/run_eval.py`, run against the real graph, recorded RAG fixtures, not the real search service, and a stub answer-writing function, not the real language model, per `docs/spec.md`'s Evaluation section.

**Task success rate: 0.909 (10/11)** — CI gate threshold is 0.70 (see `docs/spec.md`'s CI gate).

| Question | Answerable | Tool-call correctness | Structured output validity | Answer accuracy | Passed |
|---|---|---|---|---|---|
| q1 | True | PASS | PASS | FAIL | FAIL |
| q2 | True | PASS | PASS | PASS | PASS |
| q3 | True | PASS | PASS | PASS | PASS |
| q4 | True | PASS | PASS | PASS | PASS |
| q5 | True | PASS | PASS | PASS | PASS |
| q6 | True | PASS | PASS | PASS | PASS |
| q7 | True | PASS | PASS | PASS | PASS |
| q8 | True | PASS | PASS | PASS | PASS |
| q9 | False | PASS | PASS | PASS | PASS |
| q10 | False | PASS | PASS | PASS | PASS |
| q11 | False | PASS | PASS | PASS | PASS |
