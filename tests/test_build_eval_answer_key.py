"""Tests for build_eval_answer_key.py's q1 special case.

TDD: written before build_answer_key()/_query_full_population() exist -
these tests define the contract the q1 special case must satisfy. Should
fail with an ImportError/AttributeError until implemented.

RAG's top_k=25 ceiling means q1's real search can only ever return a
capped candidate list, never the true population - so q1 needs two
independently-computed golden entries: "q1_expected_capped" (what the
normal search -> verify -> count pipeline actually produces, same as
every other question) and "q1" (the true, full population, found by
querying the graph directly with no RAG involved at all - see
_query_full_population). The Neo4j driver is faked throughout, so none of
this needs a real graph database or a real search service running.
"""
from block5_agent.build_eval_answer_key import build_answer_key

_Q1_TASK = {
    "id": "q1",
    "answerable": True,
    "condition": "Essential hypertension",
    "lab": "SBP",
    "comparison": "above",
    "value": 140,
    "drug_a": "Lisinopril",
    "drug_b": "Amlodipine",
}
_Q2_TASK = {
    "id": "q2",
    "answerable": True,
    "condition": "Osteoporosis",
    "lab": "BMI",
    "comparison": "below",
    "value": 22,
    "drug_a": "Alendronic acid",
    "drug_b": "Naproxen",
}
_UNANSWERABLE_TASK = {
    "id": "q9",
    "answerable": False,
    "condition": "lung cancer",
    "lab": "SBP",
    "comparison": "above",
    "value": 220,
    "drug_a": "Chemo",
    "drug_b": "Radiation",
}


class _FakeResult:
    """Stands in for a Neo4j Result - supports both .single() (used by the
    verify and full-population queries) and iteration (used by the
    drug-count query), same shape as tests/test_graph_tool.py's fake."""

    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Dispatches on the query text - the three queries this module runs
    (verify, full-population, drug-count) are each distinguishable by
    their RETURN alias / bound parameters, same dispatch style as
    tests/test_graph_tool.py's _FakeSession."""

    def __init__(self, verified_ids, full_population_ids, drug_counts_by_ids):
        self._verified_ids = verified_ids
        self._full_population_ids = full_population_ids
        self._drug_counts_by_ids = drug_counts_by_ids

    def run(self, query, **params):
        if "matched_ids" in query:
            return _FakeResult([{"matched_ids": self._full_population_ids}])
        if "verified_ids" in query:
            return _FakeResult([{"verified_ids": self._verified_ids}])
        key = tuple(sorted(params["person_ids"]))
        rows = self._drug_counts_by_ids.get(key, [])
        return _FakeResult(rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeDriver:
    def __init__(self, verified_ids=None, full_population_ids=None, drug_counts_by_ids=None):
        self._verified_ids = verified_ids or []
        self._full_population_ids = full_population_ids or []
        self._drug_counts_by_ids = drug_counts_by_ids or {}

    def session(self, database=None):
        return _FakeSession(
            self._verified_ids, self._full_population_ids, self._drug_counts_by_ids
        )


def test_q1_writes_both_the_capped_and_full_population_entries():
    # RAG's real search only ever returns these 3 (stand-in for its real
    # top_k=25 candidate list) - all 3 pass verification.
    fake_search_fn = lambda question: [7253, 8737, 6700]
    driver = _FakeDriver(
        verified_ids=[7253, 8737, 6700],
        # The true population is bigger than what RAG returns - this is
        # the whole point of the fix.
        full_population_ids=[6700, 7253, 8737, 9001, 9002],
        drug_counts_by_ids={
            (6700, 7253, 8737): [{"drug": "Lisinopril", "patient_count": 2}],
            (6700, 7253, 8737, 9001, 9002): [
                {"drug": "Lisinopril", "patient_count": 3},
                {"drug": "Amlodipine", "patient_count": 2},
            ],
        },
    )

    answer_key = build_answer_key([_Q1_TASK], driver, search_fn=fake_search_fn)

    assert answer_key["q1_expected_capped"] == {
        "rag_patient_ids": [7253, 8737, 6700],
        "graph_result": {"Lisinopril": 2},
        "patients_checked": 3,
        "confidence": "low",
    }
    assert answer_key["q1"] == {
        "rag_patient_ids": [6700, 7253, 8737, 9001, 9002],
        "graph_result": {"Lisinopril": 3, "Amlodipine": 2},
        "patients_checked": 5,
        "confidence": "low",
    }
    # The two entries must genuinely differ - proves "q1" isn't just a
    # second copy of the capped result.
    assert answer_key["q1"] != answer_key["q1_expected_capped"]


def test_q1_full_entry_comes_from_the_unbounded_query_not_verified_search_ids():
    # verified_ids (what the capped search->verify pipeline produces) and
    # full_population_ids (what the unbounded query produces) are
    # deliberately different here, even though search_fn's raw result
    # happens to overlap - proves q1's full entry is read from the
    # unbounded query's result, not reused from the capped pipeline.
    driver = _FakeDriver(
        verified_ids=[1, 2],
        full_population_ids=[1, 2, 3],
        drug_counts_by_ids={
            (1, 2): [{"drug": "Lisinopril", "patient_count": 1}],
            (1, 2, 3): [{"drug": "Lisinopril", "patient_count": 2}],
        },
    )

    answer_key = build_answer_key([_Q1_TASK], driver, search_fn=lambda question: [1, 2, 3])

    assert answer_key["q1"]["rag_patient_ids"] == [1, 2, 3]
    assert answer_key["q1"]["graph_result"] == {"Lisinopril": 2}
    assert answer_key["q1_expected_capped"]["rag_patient_ids"] == [1, 2, 3]
    assert answer_key["q1_expected_capped"]["graph_result"] == {"Lisinopril": 1}


def test_non_q1_answerable_task_still_writes_directly_to_its_own_entry():
    fake_search_fn = lambda question: [10328, 2116]
    driver = _FakeDriver(
        verified_ids=[10328, 2116],
        drug_counts_by_ids={(2116, 10328): [{"drug": "Alendronic acid", "patient_count": 2}]},
    )

    answer_key = build_answer_key([_Q2_TASK], driver, search_fn=fake_search_fn)

    assert answer_key == {
        "q2": {
            "rag_patient_ids": [10328, 2116],
            "graph_result": {"Alendronic acid": 2},
            "patients_checked": 2,
            "confidence": "low",
        }
    }
    assert "q1" not in answer_key
    assert "q1_expected_capped" not in answer_key


def test_unanswerable_task_is_skipped_same_as_today():
    driver = _FakeDriver()

    answer_key = build_answer_key([_UNANSWERABLE_TASK], driver, search_fn=lambda q: [])

    assert answer_key == {}
