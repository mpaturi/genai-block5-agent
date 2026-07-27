"""Writes one log entry per agent run to data/logs/runs.jsonl (see
docs/spec.md's Tracing and logging).

This log file is generated output, not source code - it isn't committed
(see .gitignore).
"""
import json
import time
import uuid
from pathlib import Path

LOG_PATH = Path("data/logs/runs.jsonl")

# Per-token rates for claude-sonnet-4-6 (see docs/spec.md's Technology).
# This is not the source of truth for pricing - confirm against Anthropic's
# current published rates before trusting cost_usd for anything real.
_INPUT_RATE_PER_TOKEN = 3.00 / 1_000_000
_OUTPUT_RATE_PER_TOKEN = 15.00 / 1_000_000


def _compute_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * _INPUT_RATE_PER_TOKEN + output_tokens * _OUTPUT_RATE_PER_TOKEN


def log_run(
    *,
    question: str,
    node_latency_ms: dict,
    claude_input_tokens: int,
    claude_output_tokens: int,
    outcome: str,
) -> dict:
    """Append one JSON line for this run and return the entry that was written."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "run_id": str(uuid.uuid4()),
        "question": question,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "node_latency_ms": node_latency_ms,
        "claude_input_tokens": claude_input_tokens,
        "claude_output_tokens": claude_output_tokens,
        "cost_usd": round(_compute_cost_usd(claude_input_tokens, claude_output_tokens), 6),
        "total_latency_ms": round(sum(node_latency_ms.values()), 2),
        "outcome": outcome,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry
