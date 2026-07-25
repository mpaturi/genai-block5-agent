"""Tests for the exact drug count tool.

TDD: written before scripts/graph_tool.py exists - these tests define the
contract count_drugs() must satisfy. All should fail with an ImportError
until Phase 3 implements it. The Neo4j driver is faked throughout, so none
of this needs a real graph database running.
"""
from neo4j import Query
from neo4j.exceptions import ClientError

from scripts.graph_tool import GRAPH_QUERY_TIMEOUT, GraphServiceError, count_drugs

_CONDITION = "Essential hypertension"
_LAB = "SBP"
_COMPARISON = "above"
_VALUE = 140


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
    def __init__(self, verified_ids=None, count_rows=None, raise_exc=None):
        self._verified_ids = verified_ids if verified_ids is not None else []
        self._count_rows = count_rows or []
        self._raise_exc = raise_exc

    def run(self, query, **params):
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

    def session(self, database=None):
        return _FakeSession(self._verified_ids, self._count_rows, self._raise_exc)


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
    driver = _FakeDriver(raise_exc=RuntimeError("boom"))

    try:
        _count_drugs([1, 2, 3], driver=driver)
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == "RuntimeError"
        assert exc.retryable is True


def test_count_drugs_raises_graph_service_error_on_timeout():
    # A slow query fails the same way a slow RAG call already does (see
    # docs/spec.md's "Agent steps") - a driver-raised timeout must be
    # caught by the same broad except and treated as retryable, not as
    # bad input.
    driver = _FakeDriver(
        raise_exc=ClientError(
            "Neo.ClientError.Transaction.TransactionTimedOut: "
            "The transaction has been terminated"
        )
    )

    try:
        _count_drugs([1, 2, 3], driver=driver)
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == "ClientError"
        assert exc.retryable is True


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
