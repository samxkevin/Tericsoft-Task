"""End-to-end API tests using FastAPI's TestClient.

`llm.generate_answer` is monkeypatched (the LLM client itself is covered by
tests/test_llm.py against a mock server), so these tests verify routing,
validation, search integration and persistence without any network access.
"""

import pytest
from fastapi.testclient import TestClient

from backend import llm
from backend.database import SessionLocal
from backend.main import app
from backend.models import Ticket


@pytest.fixture()
def client():
    with TestClient(app) as test_client:  # context manager runs startup/seeding
        yield test_client


@pytest.fixture()
def mock_llm(monkeypatch):
    """Replace the LLM call; records what it was asked."""
    calls = []

    def fake_generate_answer(question, context_items):
        calls.append({"question": question, "context": context_items})
        return "1. Mock troubleshooting step.\n2. Another step."

    monkeypatch.setattr(llm, "generate_answer", fake_generate_answer)
    return calls


def test_health_reports_unconfigured_llm_and_seeded_kb(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_configured"] is False
    assert body["knowledge_base_articles"] >= 10


def test_knowledge_base_is_seeded_with_required_fields(client):
    response = client.get("/api/knowledge-base")
    assert response.status_code == 200
    articles = response.json()
    assert len(articles) >= 10
    for article in articles:
        assert article["title"]
        assert article["description"]
        assert article["solution"]


@pytest.mark.parametrize(
    "question",
    [
        "",          # empty
        "    \n\t ", # whitespace only
        "ab",        # too short
        "x" * 1001,  # too long
    ],
)
def test_invalid_questions_are_rejected(client, question):
    response = client.post("/api/tickets", json={"question": question})
    assert response.status_code == 422
    assert "detail" in response.json()


def test_missing_question_field_is_rejected(client):
    response = client.post("/api/tickets", json={})
    assert response.status_code == 422


def test_ticket_flow_persists_question_context_and_answer(client, mock_llm):
    question = "My laptop keeps disconnecting from the office Wi-Fi"
    response = client.post("/api/tickets", json={"question": question})

    assert response.status_code == 201
    ticket = response.json()
    assert ticket["question"] == question
    assert ticket["ai_response"].startswith("1. Mock")
    assert ticket["retrieved_context"], "expected knowledge-base matches"
    assert ticket["retrieved_context"][0]["title"] == "Wi-Fi not connecting"

    # The LLM received the question plus the retrieved context.
    assert mock_llm[0]["question"] == question
    assert mock_llm[0]["context"][0]["title"] == "Wi-Fi not connecting"

    # Stored in the database.
    with SessionLocal() as db:
        row = db.get(Ticket, ticket["id"])
        assert row is not None
        assert row.question == question
        assert "Wi-Fi not connecting" in row.retrieved_context
        assert row.ai_response.startswith("1. Mock")
        assert row.created_at is not None

    # Retrievable via GET /api/tickets/{id}.
    fetched = client.get(f"/api/tickets/{ticket['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == ticket


def test_unrelated_question_gets_empty_context_but_still_answers(client, mock_llm):
    response = client.post(
        "/api/tickets", json={"question": "What is the best pizza restaurant in Rome?"}
    )
    assert response.status_code == 201
    ticket = response.json()
    assert ticket["retrieved_context"] == []
    # The LLM received an empty context; llm.build_messages (covered in
    # test_llm.py) turns that into an explicit "no articles found" note.
    assert mock_llm[0]["context"] == []


def test_llm_not_configured_returns_503_and_stores_nothing(client):
    # No monkeypatching: llm.generate_answer raises LLMError(503) because
    # conftest.py clears the API keys.
    before = client.get("/api/tickets").json()
    response = client.post("/api/tickets", json={"question": "My printer is offline"})
    assert response.status_code == 503
    assert "COHERE_API_KEY_PRIMARY" in response.json()["detail"]
    after = client.get("/api/tickets").json()
    assert len(after) == len(before), "no ticket should be stored on LLM failure"


def test_get_unknown_ticket_returns_404(client):
    response = client.get("/api/tickets/999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_list_tickets_returns_recent_first(client, mock_llm):
    ids = []
    for i in range(3):
        response = client.post(
            "/api/tickets", json={"question": f"Test question number {i} about Wi-Fi"}
        )
        ids.append(response.json()["id"])

    response = client.get("/api/tickets?limit=2")
    assert response.status_code == 200
    listed = response.json()
    assert [t["id"] for t in listed] == sorted(ids[-2:], reverse=True)
    assert set(listed[0]) == {"id", "question", "created_at"}


def test_list_tickets_limit_validation(client):
    assert client.get("/api/tickets?limit=0").status_code == 422
    assert client.get("/api/tickets?limit=101").status_code == 422
