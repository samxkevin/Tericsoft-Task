"""Tests for the Cohere V2 LLM integration (primary/fallback failover).

The HTTP layer is exercised against a tiny local mock server, so no network
access and no real API keys are needed. The mock records every request it
receives - including the Authorization header - proving that the key is sent
as a Bearer token and appears nowhere else.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from backend import llm
from backend.llm import LLMError, build_messages, generate_answer, llm_status

PRIMARY_KEY = "test-primary-key"
FALLBACK_KEY = "test-fallback-key"
PRIMARY_MODEL = llm.DEFAULT_PRIMARY_MODEL
FALLBACK_MODEL = llm.DEFAULT_FALLBACK_MODEL

CONTEXT = [
    {
        "id": 1,
        "title": "Wi-Fi not connecting",
        "description": "Cannot connect to Wi-Fi.",
        "solution": "1. Restart the router.",
        "score": 8,
    }
]


class MockCohereHandler(BaseHTTPRequestHandler):
    """Mock of POST https://api.cohere.com/v2/chat.

    Modes:
        ok            -> always 200 with a V2-shaped body
        fail_primary  -> 401 for the primary key, 200 for any other key
        fail_all      -> 500 for everything
    """

    mode = "ok"
    requests = []

    @classmethod
    def reset(cls, mode="ok"):
        cls.mode = mode
        cls.requests = []

    def do_POST(self):  # noqa: N802 (http.server naming)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        authorization = self.headers.get("Authorization", "")
        type(self).requests.append({"authorization": authorization, "body": body})

        status = 200
        if self.mode == "fail_all":
            status = 500
        elif self.mode == "fail_primary" and authorization == f"Bearer {PRIMARY_KEY}":
            status = 401

        if status == 200:
            payload = {
                "id": "mock-chat-id",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Cohere mock answer."}],
                },
                "finish_reason": "COMPLETE",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        else:
            payload = {"message": "mock error"}

        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silence request logging
        pass


@pytest.fixture()
def mock_cohere(monkeypatch):
    MockCohereHandler.reset("ok")
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockCohereHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/v2/chat"
    monkeypatch.setattr(llm, "COHERE_URL", url)
    yield url
    server.shutdown()
    server.server_close()


def use_keys(monkeypatch, primary=True, fallback=False):
    monkeypatch.setenv("COHERE_API_KEY_PRIMARY", PRIMARY_KEY if primary else "")
    monkeypatch.setenv("COHERE_API_KEY_FALLBACK", FALLBACK_KEY if fallback else "")


# ---------------------------------------------------------------- prompts

def test_build_messages_includes_context_and_question():
    messages = build_messages("How do I fix my Wi-Fi?", CONTEXT)
    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert "Wi-Fi not connecting" in user
    assert "Restart the router." in user
    assert "How do I fix my Wi-Fi?" in user


def test_build_messages_notes_missing_context():
    messages = build_messages("What is the best pizza?", [])
    assert "No relevant knowledge-base articles were found" in messages[1]["content"]


# ---------------------------------------------------------------- config

def test_missing_keys_raise_503(monkeypatch, mock_cohere):
    use_keys(monkeypatch, primary=False, fallback=False)
    with pytest.raises(LLMError) as excinfo:
        generate_answer("any question", [])
    assert excinfo.value.status_code == 503
    assert "COHERE_API_KEY_PRIMARY" in str(excinfo.value)


def test_llm_status_reports_unconfigured():
    status = llm_status()
    assert status["configured"] is False
    assert status["provider"] == "cohere"
    assert status["message"]


def test_llm_status_reports_configured(monkeypatch):
    use_keys(monkeypatch, primary=True, fallback=False)
    status = llm_status()
    assert status["configured"] is True
    assert status["model"] == PRIMARY_MODEL


def test_fallback_only_configuration_uses_fallback_directly(mock_cohere, monkeypatch):
    use_keys(monkeypatch, primary=False, fallback=True)
    answer = generate_answer("My printer is offline", CONTEXT)
    assert answer == "Cohere mock answer."
    assert len(MockCohereHandler.requests) == 1
    request = MockCohereHandler.requests[0]
    assert request["authorization"] == f"Bearer {FALLBACK_KEY}"
    assert request["body"]["model"] == FALLBACK_MODEL


# ---------------------------------------------------------------- happy path

def test_primary_success_uses_bearer_header_and_correct_payload(mock_cohere, monkeypatch):
    use_keys(monkeypatch, primary=True, fallback=True)

    answer = generate_answer("My printer is offline", CONTEXT)

    assert answer == "Cohere mock answer."
    assert len(MockCohereHandler.requests) == 1
    request = MockCohereHandler.requests[0]

    # Authorization: Bearer <primary key> - the key appears nowhere else.
    assert request["authorization"] == f"Bearer {PRIMARY_KEY}"

    body = request["body"]
    assert body["model"] == PRIMARY_MODEL
    assert body["stream"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    user_content = body["messages"][1]["content"]
    assert "My printer is offline" in user_content
    assert "Wi-Fi not connecting" in user_content  # retrieved context included


# ---------------------------------------------------------------- failover

def test_fallback_used_when_primary_key_is_rejected(mock_cohere, monkeypatch):
    MockCohereHandler.mode = "fail_primary"
    use_keys(monkeypatch, primary=True, fallback=True)

    answer = generate_answer("My printer is offline", CONTEXT)

    assert answer == "Cohere mock answer."
    assert len(MockCohereHandler.requests) == 2
    first, second = MockCohereHandler.requests
    assert first["authorization"] == f"Bearer {PRIMARY_KEY}"
    assert second["authorization"] == f"Bearer {FALLBACK_KEY}"
    assert second["body"]["model"] == FALLBACK_MODEL


def test_both_keys_failing_raises_clear_error_without_keys(mock_cohere, monkeypatch):
    MockCohereHandler.mode = "fail_all"
    use_keys(monkeypatch, primary=True, fallback=True)

    with pytest.raises(LLMError) as excinfo:
        generate_answer("any question", [])
    message = str(excinfo.value)

    assert excinfo.value.status_code == 502
    assert "primary" in message and "fallback" in message
    assert "HTTP 500" in message
    # API keys must never leak into error messages.
    assert PRIMARY_KEY not in message and FALLBACK_KEY not in message


def test_primary_only_failure_reports_single_attempt(mock_cohere, monkeypatch):
    MockCohereHandler.mode = "fail_all"
    use_keys(monkeypatch, primary=True, fallback=False)

    with pytest.raises(LLMError) as excinfo:
        generate_answer("any question", [])
    message = str(excinfo.value)

    assert len(MockCohereHandler.requests) == 1  # no fallback key -> no retry
    assert excinfo.value.status_code == 502
    assert "primary" in message and "fallback" not in message


# ---------------------------------------------------------------- error mapping

def test_timeout_tries_fallback_then_maps_to_504(monkeypatch):
    use_keys(monkeypatch, primary=True, fallback=True)

    def raise_timeout(*args, **kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(llm.httpx, "post", raise_timeout)
    with pytest.raises(LLMError) as excinfo:
        generate_answer("any question", [])
    message = str(excinfo.value)

    assert excinfo.value.status_code == 504
    assert "primary" in message and "fallback" in message  # both were tried
    assert "did not respond" in message


def test_network_error_maps_to_502(monkeypatch):
    use_keys(monkeypatch, primary=True, fallback=False)

    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(llm.httpx, "post", raise_connect_error)
    with pytest.raises(LLMError) as excinfo:
        generate_answer("any question", [])
    assert excinfo.value.status_code == 502
    assert "could not be reached" in str(excinfo.value)


# ---------------------------------------------------------------- response parsing

def test_parse_answer_accepts_string_content():
    assert llm._parse_answer({"message": {"content": "plain text"}}) == "plain text"


def test_parse_answer_accepts_multiple_text_blocks():
    data = {"message": {"content": [
        {"type": "text", "text": "step 1"},
        {"type": "text", "text": "step 2"},
    ]}}
    assert llm._parse_answer(data) == "step 1\nstep 2"


def test_parse_answer_rejects_empty_content():
    with pytest.raises(LLMError):
        llm._parse_answer({"message": {"content": []}})


def test_parse_answer_rejects_missing_message():
    with pytest.raises(LLMError):
        llm._parse_answer({"unexpected": "shape"})
