"""Tests for the exact drug count tool.

TDD: written before scripts/graph_tool.py exists - these tests define the
contract count_drugs() must satisfy. All should fail with an ImportError
until Phase 3 implements it. The Neo4j driver is faked throughout, so none
of this needs a real graph database running.
"""
from scripts.graph_tool import GraphServiceError, count_drugs


class _FakeSession:
    def __init__(self, rows=None, raise_exc=None):
        self._rows = rows or []
        self._raise_exc = raise_exc

    def run(self, query, **params):
        if self._raise_exc is not None:
            raise self._raise_exc
        return iter(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeDriver:
    def __init__(self, rows=None, raise_exc=None):
        self._rows = rows
        self._raise_exc = raise_exc

    def session(self, database=None):
        return _FakeSession(self._rows, self._raise_exc)


class _NeverOpenedDriver:
    """A driver that fails the test if a session is ever opened on it."""

    def session(self, database=None):
        raise AssertionError("no query should run for this input")


def test_count_drugs_returns_a_mapping_from_drug_to_count():
    driver = _FakeDriver(
        rows=[
            {"drug": "Lisinopril", "patient_count": 2},
            {"drug": "Amlodipine", "patient_count": 1},
        ]
    )

    result = count_drugs([1, 2, 3], driver=driver)

    assert result == {
        "drug_counts": {"Lisinopril": 2, "Amlodipine": 1},
        "patients_checked": 3,
    }


def test_count_drugs_a_drug_with_zero_matches_is_absent_not_zero():
    # Only Lisinopril has any matching patients among the three checked -
    # Amlodipine must not appear in drug_counts at all, not as {"Amlodipine": 0}.
    driver = _FakeDriver(rows=[{"drug": "Lisinopril", "patient_count": 2}])

    result = count_drugs([1, 2, 3], driver=driver)

    assert result["drug_counts"] == {"Lisinopril": 2}
    assert "Amlodipine" not in result["drug_counts"]
    assert result["patients_checked"] == 3


def test_count_drugs_empty_input_returns_immediately_without_querying():
    result = count_drugs([], driver=_NeverOpenedDriver())

    assert result == {"drug_counts": {}, "patients_checked": 0}


def test_count_drugs_rejects_non_positive_ids_without_querying():
    try:
        count_drugs([1, -2, 3], driver=_NeverOpenedDriver())
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == "invalid_person_id"


def test_count_drugs_rejects_non_integer_ids_without_querying():
    try:
        count_drugs([1, 2.5], driver=_NeverOpenedDriver())
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == "invalid_person_id"


def test_count_drugs_raises_graph_service_error_on_driver_failure():
    driver = _FakeDriver(raise_exc=RuntimeError("boom"))

    try:
        count_drugs([1, 2, 3], driver=driver)
        assert False, "expected GraphServiceError"
    except GraphServiceError as exc:
        assert exc.detail == "RuntimeError"
