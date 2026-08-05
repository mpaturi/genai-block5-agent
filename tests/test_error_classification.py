"""Tests for block5_agent/error_classification.py.

TDD: written before block5_agent/error_classification.py exists -
classify_exception isn't implemented yet, so every test here should fail
with an ImportError until it is.

Ported from Block 6 Phase 8's confirmed contract (genai-block6-multiagent/
tests/test_error_classification.py) - see docs/spec.md's Agent steps
section for why Block 5 now needs the same four-kind classification.
neo4j.exceptions.ServiceUnavailable can mean either a genuine timeout or a
plain connection refusal, and the exception itself carries no separate
flag for which - the only signal available is its own message text, so
classify_exception must look for a "timeout"-indicating substring (e.g.
"timed out"/"timeout"), case-insensitively, and classify accordingly.
"""
import asyncio

import anthropic
import httpx
import pytest
# Not exported at anthropic's top level (see
# block5_agent/error_classification.py's import comment) - imported from
# the private _exceptions submodule the same way that module does.
from anthropic._exceptions import ServiceUnavailableError as AnthropicServiceUnavailableError
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired, TransientError
from pydantic import BaseModel, ValidationError

from block5_agent.error_classification import classify_exception


def _make_anthropic_request() -> httpx.Request:
    # anthropic's own exception constructors require a real httpx.Request
    # (some also a httpx.Response) - never actually sent, just the shape
    # these exceptions carry.
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _make_anthropic_timeout_error() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(request=_make_anthropic_request())


def _make_anthropic_status_error(error_cls, status_code: int, message: str = "boom"):
    request = _make_anthropic_request()
    response = httpx.Response(status_code, request=request, json={"error": {"message": message}})
    return error_cls(message, response=response, body={"error": {"message": message}})


class _OneIntField(BaseModel):
    x: int


def _make_validation_error() -> ValidationError:
    try:
        _OneIntField(x="not an int")
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


def _make_client_error(code: str, message: str = "boom"):
    # Neo4jError._hydrate_neo4j is the driver's own real construction path
    # (used internally when the server returns an error) - this builds a
    # real ClientError/TransientError/etc instance with a real .code, not
    # a hand-rolled duck-typed fake.
    return Neo4jError._hydrate_neo4j(code=code, message=message)


def test_asyncio_timeout_error_classifies_as_timeout():
    assert classify_exception(asyncio.TimeoutError()) == "timeout"


def test_anthropic_api_timeout_error_classifies_as_timeout():
    # The answer-writing step's sole language-model call is to Anthropic
    # (see agent.py's synthesize_node) - a real request timeout there must
    # be retryable, not silently fall through to "unknown".
    assert classify_exception(_make_anthropic_timeout_error()) == "timeout"


def test_anthropic_rate_limit_error_classifies_as_timeout():
    # A 429 - the connection succeeded, the server just wants a slower
    # pace. Waiting out the same backoff a real timeout gets is the
    # correct response, so this shares the "timeout" bucket, not
    # "connection_error" (nothing about the connection is broken).
    exc = _make_anthropic_status_error(anthropic.RateLimitError, 429)
    assert classify_exception(exc) == "timeout"


def test_anthropic_internal_server_error_classifies_as_connection_error():
    # A generic 5xx on Anthropic's own side - a real infra problem on
    # their end, not this agent's input.
    exc = _make_anthropic_status_error(anthropic.InternalServerError, 500)
    assert classify_exception(exc) == "connection_error"


def test_anthropic_overloaded_error_classifies_as_connection_error():
    # A 529 - Anthropic itself is overloaded, a real sibling of
    # InternalServerError under APIStatusError, not a subclass of it (see
    # block5_agent/error_classification.py's comment) - same
    # "connection_error" bucket either way, since both mean the server
    # can't handle this right now, not that this agent's connection broke.
    exc = _make_anthropic_status_error(anthropic.OverloadedError, 529)
    assert classify_exception(exc) == "connection_error"


def test_anthropic_service_unavailable_error_classifies_as_connection_error():
    # A 503 - same bucket as OverloadedError/InternalServerError above.
    # ServiceUnavailableError isn't exported at anthropic's top level in
    # the installed version, so it's built directly from the private
    # _exceptions submodule here, the same way
    # block5_agent/error_classification.py imports it.
    exc = _make_anthropic_status_error(AnthropicServiceUnavailableError, 503)
    assert classify_exception(exc) == "connection_error"


def test_service_unavailable_with_timeout_message_classifies_as_timeout():
    exc = ServiceUnavailable("Connection timed out after 10s")
    assert classify_exception(exc) == "timeout"


def test_service_unavailable_with_refused_message_classifies_as_connection_error():
    exc = ServiceUnavailable("Connection refused")
    assert classify_exception(exc) == "connection_error"


def test_bare_connection_error_classifies_as_connection_error():
    assert classify_exception(ConnectionError("refused")) == "connection_error"


def test_httpx_connect_error_classifies_as_connection_error():
    assert classify_exception(httpx.ConnectError("connection refused")) == "connection_error"


def test_pydantic_validation_error_classifies_as_validation_error():
    assert classify_exception(_make_validation_error()) == "validation_error"


def test_client_error_with_transaction_timed_out_code_classifies_as_timeout():
    # A real Query(timeout=...) expiring server-side surfaces as this
    # specific ClientError code, not a ServiceUnavailable - the driver
    # only raises ServiceUnavailable for transport-level failures, so a
    # server-enforced query/transaction timeout needs its own check.
    exc = _make_client_error(
        "Neo.ClientError.Transaction.TransactionTimedOut",
        "The transaction has been terminated",
    )
    assert classify_exception(exc) == "timeout"


def test_client_error_with_an_unrelated_code_classifies_as_unknown():
    # Not every ClientError is a timeout - only the specific code above
    # is. A syntax error, for instance, is a real bug, not a transient
    # failure worth retrying.
    exc = _make_client_error("Neo.ClientError.Statement.SyntaxError", "bad cypher")
    assert classify_exception(exc) == "unknown"


def test_transient_error_classifies_as_timeout():
    # A transient database condition (leader switch, deadlock, momentarily
    # unavailable) - retrying later plausibly helps, same bucket as timeout.
    assert classify_exception(TransientError("deadlock detected")) == "timeout"


def test_session_expired_classifies_as_connection_error():
    # The session itself is no longer usable - a fresh session/connection
    # is what's needed, not a retry of the same one, so this is a
    # connection problem, not a timeout.
    assert classify_exception(SessionExpired("session no longer usable")) == "connection_error"


def test_unrelated_exception_classifies_as_unknown():
    assert classify_exception(RuntimeError("boom")) == "unknown"


def test_value_error_classifies_as_unknown():
    assert classify_exception(ValueError("bad value")) == "unknown"


@pytest.mark.parametrize(
    "kind", ["timeout", "connection_error", "validation_error", "unknown"]
)
def test_return_value_is_always_one_of_the_four_literal_kinds(kind):
    # Cheap guard against a typo'd literal string slipping into the
    # implementation - every case above must land on exactly one of these.
    exceptions_by_kind = {
        "timeout": asyncio.TimeoutError(),
        "connection_error": ConnectionError("refused"),
        "validation_error": _make_validation_error(),
        "unknown": RuntimeError("boom"),
    }
    assert classify_exception(exceptions_by_kind[kind]) == kind
