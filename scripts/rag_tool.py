"""Tool 1 - semantic patient search (see docs/spec.md's Tool 1).

Wraps Block 4's existing POST /query endpoint. Sends condition/lab/
comparison/value as structured metadata filter fields alongside the
free-text query, so Block 4 can narrow results to patients whose
graph-derived metadata actually matches (see Block 4's Phase 7 filter
work), not just patients whose record text is semantically similar. Does
not retry - retry policy lives in the agent (see docs/spec.md's Agent
steps).
"""
import os

import requests
from dotenv import load_dotenv

from scripts.schemas import dedupe_and_order_patient_ids

load_dotenv()

RAG_API_URL = os.environ.get("RAG_API_URL", "http://localhost:8000")


class RAGServiceError(Exception):
    """Raised on any search-tool failure.

    `retryable` distinguishes a temporary problem (service down, unexpected
    status) from bad input (an out-of-range top_k) - a bad-input failure
    won't be fixed by trying again, so the agent's retry loop checks this
    flag before retrying (see docs/spec.md's Agent steps).
    """

    def __init__(self, detail: str, retryable: bool = True):
        super().__init__(detail)
        self.detail = detail
        self.retryable = retryable


def search_patients(
    query_text: str,
    condition: str,
    lab: str,
    comparison: str,
    value: float,
    top_k: int = 25,
) -> dict:
    if not (1 <= top_k <= 25):
        raise RAGServiceError("invalid_top_k", retryable=False)

    try:
        response = requests.post(
            f"{RAG_API_URL}/query",
            json={
                "question": query_text,
                "top_k": top_k,
                "condition": condition,
                "lab": lab,
                "comparison": comparison,
                "value": value,
            },
            timeout=10,
        )
    except requests.exceptions.RequestException:
        raise RAGServiceError("connection_error")

    if response.status_code == 200:
        body = response.json()
        return {
            "answer": body["answer"],
            "patient_ids": dedupe_and_order_patient_ids(body["sources"]),
            "retrieved_count": body["retrieved_count"],
        }

    if response.status_code == 502:
        detail = response.json().get("detail", "unknown")
        raise RAGServiceError(detail)

    if response.status_code == 422:
        # Block 4 rejected the structured filter itself (bad lab/comparison
        # value, or a partial lab/comparison/value combo) - retrying the
        # identical request would fail identically. FastAPI's default 422
        # body is a list of validation error objects, not a plain string
        # like the 502 branch's detail field, so there's nothing useful to
        # extract here - use a fixed detail instead.
        raise RAGServiceError("invalid_filter_request", retryable=False)

    raise RAGServiceError(f"unexpected_status_{response.status_code}")
