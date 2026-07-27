"""Tests for the semantic patient search tool.

TDD: written before block5_agent/rag_tool.py exists - these tests define the
contract search_patients() must satisfy. All should fail with an
ImportError until Phase 3 implements it. HTTP is mocked throughout, so
none of this needs the real search service running.
"""
import requests

from block5_agent.rag_tool import RAGServiceError, search_patients


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_search_patients_returns_deduped_ordered_ids_on_a_hit(monkeypatch):
    body = {
        "answer": "Two patients match.",
        "sources": [
            {"person_id": 5, "chunk_id": "5_chunk0", "score": 0.5, "chunk_text": "Patient 5, chunk 0 text."},
            {"person_id": 2, "chunk_id": "2_chunk0", "score": 0.9, "chunk_text": "Patient 2, chunk 0 text."},
            # A repeat of patient 5 with a higher score - dedupe should
            # keep the higher score, not the first-seen one.
            {"person_id": 5, "chunk_id": "5_chunk1", "score": 0.7, "chunk_text": "Patient 5, chunk 1 text."},
            # Same score as patient 2 - tie broken by patient ID.
            {"person_id": 1, "chunk_id": "1_chunk0", "score": 0.9, "chunk_text": "Patient 1, chunk 0 text."},
        ],
        "retrieved_count": 3,
    }
    captured_calls = []

    def _fake_post(*args, **kwargs):
        captured_calls.append((args, kwargs))
        return _FakeResponse(200, body)

    monkeypatch.setattr("block5_agent.rag_tool.requests.post", _fake_post)

    result = search_patients(
        "patients with hypertension and SBP above 140",
        "hypertension",
        "SBP",
        "above",
        140,
        top_k=20,
    )

    assert result["answer"] == "Two patients match."
    assert result["retrieved_count"] == 3
    # Score descending; patient 1 and 2 tie at 0.9, so ID breaks the tie.
    assert result["patient_ids"] == [1, 2, 5]
    # Same dedupe/order as patient_ids, but carrying each winning chunk's
    # ID and text under the patient_id name, not Block 4's person_id.
    assert result["citations"] == [
        {"patient_id": 1, "chunk_id": "1_chunk0", "snippet": "Patient 1, chunk 0 text."},
        {"patient_id": 2, "chunk_id": "2_chunk0", "snippet": "Patient 2, chunk 0 text."},
        {"patient_id": 5, "chunk_id": "5_chunk1", "snippet": "Patient 5, chunk 1 text."},
    ]

    # condition/lab/comparison/value must be sent as structured metadata
    # filter fields alongside the free-text query and top_k, not dropped.
    sent_json = captured_calls[0][1]["json"]
    assert sent_json == {
        "question": "patients with hypertension and SBP above 140",
        "top_k": 20,
        "condition": "hypertension",
        "lab": "SBP",
        "comparison": "above",
        "value": 140,
    }


def test_search_patients_handles_a_miss_as_success_not_an_error(monkeypatch):
    body = {
        "answer": "I don't know — I couldn't find any patient records relevant to that question.",
        "sources": [],
        "retrieved_count": 0,
    }
    monkeypatch.setattr(
        "block5_agent.rag_tool.requests.post",
        lambda *a, **k: _FakeResponse(200, body),
    )

    result = search_patients(
        "patients with a made-up condition", "made-up condition", "SBP", "above", 140, top_k=20
    )

    assert result["retrieved_count"] == 0
    assert result["patient_ids"] == []
    assert result["citations"] == []


def test_search_patients_raises_on_upstream_502(monkeypatch):
    body = {"error": "Retrieval service unavailable. Please try again shortly.", "detail": "pinecone_timeout"}
    monkeypatch.setattr(
        "block5_agent.rag_tool.requests.post",
        lambda *a, **k: _FakeResponse(502, body),
    )

    try:
        search_patients(
            "patients with hypertension and SBP above 140",
            "hypertension",
            "SBP",
            "above",
            140,
            top_k=20,
        )
        assert False, "expected RAGServiceError"
    except RAGServiceError as exc:
        assert exc.detail == "pinecone_timeout"
        assert exc.retryable is True


def test_search_patients_raises_on_connection_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("block5_agent.rag_tool.requests.post", _raise)

    try:
        search_patients(
            "patients with hypertension and SBP above 140",
            "hypertension",
            "SBP",
            "above",
            140,
            top_k=20,
        )
        assert False, "expected RAGServiceError"
    except RAGServiceError as exc:
        assert exc.detail == "connection_error"
        assert exc.retryable is True


def test_search_patients_raises_on_unexpected_status(monkeypatch):
    monkeypatch.setattr(
        "block5_agent.rag_tool.requests.post",
        lambda *a, **k: _FakeResponse(500, {}),
    )

    try:
        search_patients(
            "patients with hypertension and SBP above 140",
            "hypertension",
            "SBP",
            "above",
            140,
            top_k=20,
        )
        assert False, "expected RAGServiceError"
    except RAGServiceError as exc:
        assert exc.detail == "unexpected_status_500"


def test_search_patients_raises_on_invalid_filter_422(monkeypatch):
    # FastAPI's default 422 body is a list of validation error objects,
    # not a plain string - unlike the 502 branch, nothing here should be
    # read out of it.
    body = {
        "detail": [
            {
                "type": "missing",
                "loc": ["body", "comparison"],
                "msg": "Field required",
            }
        ]
    }
    monkeypatch.setattr(
        "block5_agent.rag_tool.requests.post",
        lambda *a, **k: _FakeResponse(422, body),
    )

    try:
        search_patients(
            "patients with hypertension and SBP above 140",
            "hypertension",
            "SBP",
            "above",
            140,
            top_k=20,
        )
        assert False, "expected RAGServiceError"
    except RAGServiceError as exc:
        assert exc.detail == "invalid_filter_request"
        # Bad input, not a temporary problem - retrying won't fix it.
        assert exc.retryable is False


def test_search_patients_rejects_bad_top_k_before_any_http_call(monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not make an HTTP call for invalid top_k")

    monkeypatch.setattr("block5_agent.rag_tool.requests.post", _fail_if_called)

    try:
        search_patients(
            "patients with hypertension and SBP above 140",
            "hypertension",
            "SBP",
            "above",
            140,
            top_k=26,
        )
        assert False, "expected RAGServiceError"
    except RAGServiceError as exc:
        assert exc.detail == "invalid_top_k"
        # Bad input, not a temporary problem - retrying won't fix it.
        assert exc.retryable is False
