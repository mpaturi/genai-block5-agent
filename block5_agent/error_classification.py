"""classify_exception - agent.py's retry loops use this to tell a genuine
temporary failure apart from a permanent one (see docs/spec.md's Agent
steps).

Ported from Block 6 Phase 8's confirmed pattern (genai-block6-multiagent/
scripts/error_classification.py) so both projects classify the same way.

neo4j.exceptions.ServiceUnavailable can mean either a genuine timeout or a
plain connection refusal, and the exception itself carries no separate
flag for which - the only signal available is its own message text, so
that's what this checks for a timeout-indicating substring.
"""
import asyncio

import httpx
from neo4j.exceptions import ClientError, ServiceUnavailable, SessionExpired, TransientError
from pydantic import ValidationError

# Case-insensitive substrings that mean "this ServiceUnavailable was
# actually a timeout", not a plain connection refusal.
_TIMEOUT_MESSAGE_KEYWORDS = ["timed out", "timeout"]

# The one ClientError code this classifier treats as a timeout - a real
# Query(timeout=...) expiring server-side surfaces as this specific code,
# not a ServiceUnavailable (the driver only raises ServiceUnavailable for
# transport-level failures).
_CLIENT_ERROR_TIMEOUT_CODE = "Neo.ClientError.Transaction.TransactionTimedOut"


def classify_exception(exc: Exception) -> str:
    """Return one of "timeout"/"connection_error"/"validation_error"/"unknown"."""
    # A real supervisory timeout always lands here first.
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"

    # ServiceUnavailable is ambiguous by itself - check its message text
    # for a timeout-indicating substring before falling back to a plain
    # connection_error classification.
    if isinstance(exc, ServiceUnavailable):
        message = str(exc).lower()
        if any(keyword in message for keyword in _TIMEOUT_MESSAGE_KEYWORDS):
            return "timeout"
        return "connection_error"

    # A real Query(timeout=...) expiring raises this specific ClientError
    # code - not every ClientError is a timeout (a syntax error is a real
    # bug, not worth retrying), so only this one code counts.
    if isinstance(exc, ClientError) and exc.code == _CLIENT_ERROR_TIMEOUT_CODE:
        return "timeout"

    # A transient database condition (leader switch, deadlock, momentarily
    # unavailable) - retrying later plausibly helps, same bucket as timeout.
    if isinstance(exc, TransientError):
        return "timeout"

    # The session itself is no longer usable (e.g. after a dropped
    # connection) - a fresh session/connection is what's needed, not a
    # retry of the same one, so this is a connection problem.
    if isinstance(exc, SessionExpired):
        return "connection_error"

    # Any other flavor of "couldn't connect" - a plain refused connection,
    # or httpx's own connect-failure exception.
    if isinstance(exc, (ConnectionError, httpx.ConnectError)):
        return "connection_error"

    # A schema/shape problem, not an infrastructure problem.
    if isinstance(exc, ValidationError):
        return "validation_error"

    return "unknown"
