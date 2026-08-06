"""Tests for the exact drug count tool.

TDD: written before block5_agent/graph_tool.py exists - these tests define the
contract count_drugs() must satisfy. All should fail with an ImportError
until Phase 3 implements it. The Neo4j driver is faked throughout, so none
of this needs a real graph database running.
"""
import pytest
from neo4j import Query
from neo4j.exceptions import Neo4jError

from block5_agent.graph_tool import (
    GRAPH_QUERY_TIMEOUT,
    VERIFY_PATIENTS_QUERY_TEMPLATE,
    GraphServiceError,
    count_drugs,
)

_CONDITION = "Essential hypertension"
_LAB = "SBP"
_COMPARISON = "above"
_VALUE = 140


def _make_client_error(code: str, message: str = "boom"):
    # Neo4jError._hydrate_neo4j is the driver's own real construction path
    # (used internally when the server returns an error) - this builds a
    # real ClientError/CypherSyntaxError/etc instance with a real .code,
    # not a hand-rolled duck-typed fake. Matches
    # tests/test_error_classification.py's own helper of the same name,
    # since classify_exception (see block5_agent/error_classification.py)
    # is what count_drugs() now uses to decide retryable, and that
    # decision depends on .code actually being set correctly.
    return Neo4jError._hydrate_neo4j(code=code, message=message)


class _FakeResult:
    """Stands in for a Neo4j Result - supports both .single() (used by the
    verify query) and iteration (used by the drug-count query)."""

    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, verified_ids=None, count_rows=None, raise_exc=None, recorded_calls=None):
        self._verified_ids = verified_ids if verified_ids is not None else []
        self._count_rows = count_rows or []
        self._raise_exc = raise_exc
        self._recorded_calls = recorded_calls

    def run(self, query, **params):
        if self._recorded_calls is not None:
            self._recorded_calls.append((query, params))
        if self._raise_exc is not None:
            raise self._raise_exc
        # The real driver has no timeout kwarg on run() - a bounded query
        # must arrive wrapped in a Query object carrying the timeout, so
        # every call this tool makes is checked against that shape here.
        assert isinstance(query, Query), "query must be wrapped in neo4j.Query"
        assert query.timeout == GRAPH_QUERY_TIMEOUT
        if "verified_ids" in query.text:
            return _FakeResult([{"verified_ids": self._verified_ids}])
        return _FakeResult(self._count_rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeDriver:
    def __init__(self, verified_ids=None, count_rows=None, raise_exc=None):
        self._verified_ids = verified_ids
        self._count_rows = count_rows
        self._raise_exc = raise_exc
        self.recorded_calls = []

    def session(self, database=None):
        return _FakeSession(
            self._verified_ids, self._count_rows, self._raise_exc, recorded_calls=self.recorded_calls
        )


class _NeverOpenedDriver:
    """A driver that fails the test if a session is ever opened on it."""

    def session(self, database=None):
        raise AssertionError("no query should run for this input")


def _count_drugs(person_ids, **kwargs):
    """count_drugs with the question fields defaulted, so tests only need
    to override what they actually care about."""
    kwargs.setdefault("condition", _CONDITION)
    kwargs.setdefault("lab", _LAB)
    kwargs.setdefault("comparison", _COMPARISON)
    kwargs.setdefault("value", _VALUE)
    return count_drugs(person_ids, **kwargs)


def test_count_drugs_returns_a_mapping_from_drug_to_count():
    driver = _FakeDriver(
        verified_ids=[1, 2, 3],
        count_rows=[
            {"drug": "Lisinopril", "patient_count": 2},
            {"drug": "Amlodipine", "patient_count": 1},
        ],
    )

    result = _count_drugs([1, 2, 3], driver=driver)

    assert result == {
        "drug_counts": {"Lisinopril": 2, "Amlodipine": 1},
        "patients_checked": 3,
    }


def test_count_drugs_a_drug_with_zero_matches_is_absent_not_zero():
    # Only Lisinopril has any matching patients among the three checked -
    # Amlodipine must not appear in drug_counts at all, not as {"Amlodipine": 0}.
    driver = _FakeDriver(
        verified_ids=[1, 2, 3], count_rows=[{"drug": "Lisinopril", "patient_count": 2}]
    )

    result = _count_drugs([1, 2, 3], driver=driver)

    assert result["drug_counts"] == {"Lisinopril": 2}
    assert "Amlodipine" not in result["drug_counts"]
    assert result["patients_checked"] == 3


def test_count_drugs_empty_input_returns_immediately_without_querying():
    result = _count_drugs([], driver=_NeverOpenedDriver())

    assert result == {"drug_counts": {}, "patients_checked": 0}


def test_count_drugs_rejects_non_positive_ids_without_querying():
    try:
        _count_drugs([1, -2, 3], driver=_NeverOpenedDriver())
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == "invalid_person_id"
        assert exc.retryable is False


def test_count_drugs_rejects_non_integer_ids_without_querying():
    try:
        _count_drugs([1, 2.5], driver=_NeverOpenedDriver())
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == "invalid_person_id"
        assert exc.retryable is False


def test_count_drugs_raises_graph_service_error_on_driver_failure():
    # A plain connection failure - classify_exception (see
    # block5_agent/error_classification.py) classifies this as
    # "connection_error", one of the two retryable kinds, so this must
    # come back retryable, and `detail` is the exception's real message
    # (str(exc)), not just its type name - matching Block 6's own
    # cohort_tool.py pattern exactly.
    exc_to_raise = ConnectionError("connection reset")
    driver = _FakeDriver(raise_exc=exc_to_raise)

    try:
        _count_drugs([1, 2, 3], driver=driver)
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == str(exc_to_raise)
        assert exc.retryable is True


def test_count_drugs_raises_graph_service_error_on_timeout():
    # A slow query fails the same way a slow RAG call already does (see
    # docs/spec.md's "Agent steps") - a driver-raised timeout must be
    # caught by the same broad except and treated as retryable, not as
    # bad input. Built via the driver's own real hydration path (see
    # _make_client_error above) so .code is genuinely set to the timeout
    # code classify_exception looks for - a bare
    # ClientError("Neo.ClientError...") string leaves .code at its
    # unrelated default and would not exercise this path at all. The
    # "ClientConfiguration" suffix is what a real Query(timeout=...)
    # expiration actually produces (verified directly against a live
    # Neo4j 5.18-community server) - see
    # error_classification.py's own two-code test for the base-code case.
    exc_to_raise = _make_client_error(
        "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
        "The transaction has been terminated",
    )
    driver = _FakeDriver(raise_exc=exc_to_raise)

    try:
        _count_drugs([1, 2, 3], driver=driver)
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == str(exc_to_raise)
        assert exc.retryable is True


def test_count_drugs_raises_graph_service_error_not_retryable_on_syntax_error():
    # Regression test for the blanket-retry bug: count_drugs()'s except
    # block used to do `raise GraphServiceError(type(exc).__name__)` with
    # no retryable= argument, and GraphServiceError defaults retryable to
    # True - so a permanent failure like a Cypher syntax error was
    # incorrectly retried 3 times instead of failing immediately. A real
    # syntax error, built the same way the timeout case above is, must
    # classify as "unknown" (see block5_agent/error_classification.py)
    # and come back non-retryable.
    exc_to_raise = _make_client_error("Neo.ClientError.Statement.SyntaxError", "bad cypher")
    driver = _FakeDriver(raise_exc=exc_to_raise)

    try:
        _count_drugs([1, 2, 3], driver=driver)
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == str(exc_to_raise)
        assert exc.retryable is False


def test_count_drugs_excludes_a_patient_who_fails_the_condition_check():
    # Patient 1 doesn't actually have the stated condition - verification
    # drops them, so they never reach the drug count at all.
    driver = _FakeDriver(
        verified_ids=[2, 3], count_rows=[{"drug": "Lisinopril", "patient_count": 2}]
    )

    result = _count_drugs([1, 2, 3], driver=driver)

    assert result == {"drug_counts": {"Lisinopril": 2}, "patients_checked": 2}


def test_count_drugs_excludes_a_patient_who_fails_the_lab_check():
    # Patient 2 has the condition but doesn't satisfy the lab threshold -
    # verification drops them the same way.
    driver = _FakeDriver(
        verified_ids=[1, 3], count_rows=[{"drug": "Amlodipine", "patient_count": 2}]
    )

    result = _count_drugs([1, 2, 3], driver=driver)

    assert result == {"drug_counts": {"Amlodipine": 2}, "patients_checked": 2}


def test_count_drugs_mix_of_passing_and_failing_only_counts_passing():
    # Of four candidates, only two pass verification - the count and
    # patients_checked must reflect only those two, not all four.
    driver = _FakeDriver(
        verified_ids=[2, 4], count_rows=[{"drug": "Metformin", "patient_count": 1}]
    )

    result = _count_drugs([1, 2, 3, 4], driver=driver)

    assert result == {"drug_counts": {"Metformin": 1}, "patients_checked": 2}


def test_count_drugs_rejects_unrecognized_lab_without_querying():
    try:
        _count_drugs([1, 2, 3], lab="Cholesterol", driver=_NeverOpenedDriver())
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == "invalid_lab_or_comparison"
        assert exc.retryable is False


def test_count_drugs_rejects_unrecognized_comparison_without_querying():
    try:
        _count_drugs([1, 2, 3], comparison="sideways", driver=_NeverOpenedDriver())
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == "invalid_lab_or_comparison"
        assert exc.retryable is False


def test_adversarial_condition_value_and_person_ids_are_bound_as_parameters_never_interpolated():
    # A value that would break out of the query text's string literal and
    # inject a second write clause, if it were ever concatenated/formatted
    # into the Cypher instead of bound as a $parameter.
    malicious_condition = "Essential hypertension'}) DETACH DELETE (p) //"
    driver = _FakeDriver(verified_ids=[1], count_rows=[])

    _count_drugs([1], condition=malicious_condition, driver=driver)

    sent_query, sent_params = driver.recorded_calls[0]
    expected_query_text = VERIFY_PATIENTS_QUERY_TEMPLATE.format(lab_property="latest_sbp", op=">")
    # The query text sent to the driver is exactly the fixed template,
    # byte-for-byte - the malicious value never touched it.
    assert sent_query.text == expected_query_text
    assert "DETACH DELETE" not in sent_query.text
    assert "//" not in sent_query.text

    # The malicious string, along with value and person_ids, reaches the
    # driver only as bound parameter values, unmodified - the one place
    # they're allowed to be, since the driver (not Python string
    # formatting) is responsible for treating them as inert data rather
    # than executable Cypher.
    assert sent_params["condition"] == malicious_condition
    assert sent_params["person_ids"] == [1]
    assert sent_params["value"] == _VALUE


def test_adversarial_lab_is_rejected_before_reaching_the_driver():
    malicious_lab = "SBP AND (p) DETACH DELETE (p) //"

    with pytest.raises(GraphServiceError) as exc_info:
        count_drugs([1], "Essential hypertension", malicious_lab, "above", 140, driver=_NeverOpenedDriver())

    assert exc_info.value.detail == "invalid_lab_or_comparison"
    assert exc_info.value.retryable is False


def test_adversarial_comparison_is_rejected_before_reaching_the_driver():
    malicious_comparison = "above'}) SET p.person_id = 0 //"

    with pytest.raises(GraphServiceError) as exc_info:
        count_drugs([1], "Essential hypertension", "SBP", malicious_comparison, 140, driver=_NeverOpenedDriver())

    assert exc_info.value.detail == "invalid_lab_or_comparison"
    assert exc_info.value.retryable is False
