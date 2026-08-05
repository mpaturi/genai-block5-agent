"""classify_exception - agent.py's retry loops use this to tell a genuine
temporary failure apart from a permanent one (see docs/spec.md's Agent
steps).

Ported from Block 6 Phase 8's confirmed pattern (genai-block6-multiagent/
scripts/error_classification.py) so both projects classify the same way.

neo4j.exceptions.ServiceUnavailable can mean either a genuine timeout or a
plain connection refusal, and the exception itself carries no separate
flag for which - the only signal available is its own message text, so
that's what this checks for a timeout-indicating substring.

Also recognizes the anthropic SDK's own exception types (installed
version 0.116.0 - see .venv/Lib/site-packages/anthropic/_exceptions.py
for the real hierarchy, not guessed) - this is the sole classifier for
the answer-writing step's retry decision (see agent.py's synthesize_node),
which calls Anthropic directly, so a real transient Anthropic failure
falling through to "unknown" would make it permanent by mistake.
"""
import asyncio

import anthropic
import httpx
# anthropic.ServiceUnavailableError (503) is a real class in the installed
# package (anthropic/_exceptions.py) but, unlike OverloadedError, it is
# NOT re-exported at anthropic's top level (checked anthropic/__init__.py's
# imports/__all__ directly) - so it has to be imported from the private
# _exceptions submodule instead of off the public `anthropic` namespace.
from anthropic._exceptions import ServiceUnavailableError as AnthropicServiceUnavailableError
from neo4j.exceptions import ClientError, ServiceUnavailable, SessionExpired, TransientError
from pydantic import ValidationError

# Case-insensitive substrings that mean "this ServiceUnavailable was
# actually a timeout", not a plain connection refusal.
_TIMEOUT_MESSAGE_KEYWORDS = ["timed out", "timeout"]

# The ClientError codes this classifier treats as a timeout - not a
# ServiceUnavailable (the driver only raises ServiceUnavailable for
# transport-level failures). Verified directly against a live Neo4j
# 5.18-community server (not assumed): a real Query(timeout=...) expiring
# server-side surfaces as the "ClientConfiguration" variant specifically
# - that suffix denotes a client-requested transaction timeout, distinct
# from the bare code, which is what a server-configured transaction
# timeout (dbms.transaction.timeout) surfaces as instead. Both recognized
# here since both are real, valid Neo4j timeout codes, even though this
# codebase's own Query(timeout=...) calls will only ever produce the
# ClientConfiguration variant.
_CLIENT_ERROR_TIMEOUT_CODES = {
    "Neo.ClientError.Transaction.TransactionTimedOut",
    "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
}


def classify_exception(exc: Exception) -> str:
    """Return one of "timeout"/"connection_error"/"validation_error"/"unknown"."""
    # A real supervisory timeout always lands here first.
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"

    # The Anthropic SDK's own timeout - the request never got (or lost) a
    # response in time. Checked as its own distinct type rather than
    # folded into a message-text guess, since anthropic.APITimeoutError
    # is unambiguous by construction (unlike neo4j's ServiceUnavailable
    # below).
    if isinstance(exc, anthropic.APITimeoutError):
        return "timeout"

    # Any other Anthropic connection-level failure (request never reached
    # the server, connection dropped mid-request, etc.) - checked right
    # after APITimeoutError since that's a narrower subclass of this same
    # class and must keep matching "timeout" first; order relative to the
    # RateLimitError/InternalServerError checks below doesn't matter,
    # since none of these four subclass each other. This was one of the
    # four Anthropic exception types review feedback named as a gap,
    # closed directly here.
    if isinstance(exc, anthropic.APIConnectionError):
        return "connection_error"

    # A 429 rate-limit response - the connection and request both
    # succeeded, the server is just asking to slow down. Waiting out this
    # step's backoff before retrying is exactly the right response, same
    # as a transient database condition (see TransientError below), so
    # this shares that bucket rather than "connection_error" - nothing
    # about the connection itself is broken here.
    if isinstance(exc, anthropic.RateLimitError):
        return "timeout"

    # A 5xx failure on Anthropic's own side with no more specific status
    # code subclass (a real infrastructure problem on Anthropic's end, not
    # this agent's input) - the general "something is wrong on the other
    # end" bucket, same as neo4j's ServiceUnavailable falls to below when
    # its message doesn't indicate a timeout specifically.
    if isinstance(exc, anthropic.InternalServerError):
        return "connection_error"

    # OverloadedError (529) and ServiceUnavailableError (503) are real
    # sibling classes of InternalServerError under anthropic.APIStatusError
    # - not subclasses of it - confirmed against the installed package's
    # _client.py, which builds each of the three from separate, explicit
    # status-code branches in _make_status_error(), not one falling back
    # to another. Both mean "the server itself can't handle this right
    # now" (Anthropic is overloaded, or a component it depends on is
    # unavailable) rather than a connection failure this agent caused, so
    # both share InternalServerError's "connection_error" bucket. Note:
    # _make_status_error() has no explicit 503 branch of its own in this
    # installed version - a real 503 response actually falls through to
    # the generic ">= 500" branch and surfaces as InternalServerError, not
    # ServiceUnavailableError. This check still recognizes the class
    # itself (e.g. if raised directly, or in a future SDK version that
    # does route 503 here), even though it isn't reachable from a live
    # 503 response today.
    if isinstance(exc, (anthropic.OverloadedError, AnthropicServiceUnavailableError)):
        return "connection_error"

    # ServiceUnavailable is ambiguous by itself - check its message text
    # for a timeout-indicating substring before falling back to a plain
    # connection_error classification.
    if isinstance(exc, ServiceUnavailable):
        message = str(exc).lower()
        if any(keyword in message for keyword in _TIMEOUT_MESSAGE_KEYWORDS):
            return "timeout"
        return "connection_error"

    # A real Query(timeout=...) expiring raises one of these specific
    # ClientError codes - not every ClientError is a timeout (a syntax
    # error is a real bug, not worth retrying), so only these count.
    if isinstance(exc, ClientError) and exc.code in _CLIENT_ERROR_TIMEOUT_CODES:
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
