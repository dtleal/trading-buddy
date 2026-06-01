"""API-level tests for the Q&A routes.

Exercises the full FastAPI stack (validation, status codes, serialization)
with the persistence layer swapped for an in-memory fake via a dependency
override — no Postgres required.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes.qa import _qa_repository
from tests.fakes import FakeQARepository


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    repo = FakeQARepository()
    app.dependency_overrides[_qa_repository] = lambda: repo
    with TestClient(app) as test_client:
        yield test_client


def test_list_starts_empty(client: TestClient) -> None:
    resp = client.get("/api/qa")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_then_list(client: TestClient) -> None:
    resp = client.post(
        "/api/qa",
        json={"question": "Operar lateralidade?", "answer": "Depende.", "tags": ["Bollinger"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] >= 1
    assert body["question"] == "Operar lateralidade?"
    assert body["tags"] == ["bollinger"]  # normalised

    listed = client.get("/api/qa").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]


def test_create_rejects_blank_question(client: TestClient) -> None:
    # Pydantic min_length=1 rejects empty string with 422 before our use case.
    resp = client.post("/api/qa", json={"question": "", "answer": "x", "tags": []})
    assert resp.status_code == 422


def test_create_rejects_whitespace_only_question(client: TestClient) -> None:
    # Passes Pydantic length check but trips the use-case validation → 400.
    resp = client.post("/api/qa", json={"question": "   ", "answer": "x", "tags": []})
    assert resp.status_code == 400


def test_update_existing_entry(client: TestClient) -> None:
    created = client.post("/api/qa", json={"question": "Q", "answer": "A", "tags": []}).json()

    resp = client.put(
        f"/api/qa/{created['id']}",
        json={"question": "Q editada", "answer": "A2", "tags": ["x"]},
    )
    assert resp.status_code == 200
    assert resp.json()["question"] == "Q editada"
    assert resp.json()["tags"] == ["x"]


def test_update_missing_entry_is_404(client: TestClient) -> None:
    resp = client.put("/api/qa/999", json={"question": "Q", "answer": "A", "tags": []})
    assert resp.status_code == 404


def test_delete_existing_then_missing(client: TestClient) -> None:
    created = client.post("/api/qa", json={"question": "Q", "answer": "A", "tags": []}).json()

    assert client.delete(f"/api/qa/{created['id']}").status_code == 204
    assert client.delete(f"/api/qa/{created['id']}").status_code == 404
    assert client.get("/api/qa").json() == []
