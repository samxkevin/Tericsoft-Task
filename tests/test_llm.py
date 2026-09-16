"""Tests for the LLM integration.

The HTTP layer is exercised against a tiny local mock server, so no network
access and no real API keys are needed. The mock server also records the
authorization header it received, proving the key is sent securely.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend import llm
from backend.llm import LLMError, build_messages, generate_answer, llm_status

CONTEXT = [
    {
        "id": 1,
        "title": "Wi-Fi not connecting",
        "description": "Cannot connect to Wi-Fi.",
        "solution": "1. Restart the router.",
        "score": 8,
    }
]


class MockLLMHandler(BaseHTTPRequestHandler):
    received_headers = {}
    received_body = {}

    def do_POST(self):  # noqa: N802 (http.server naming)
        MockLLMHandler.received_headers = dict(self.headers)
        length = int(self.headers.get("Content-Length", 0))
        MockLLMHandler.received_body = json.loads(self.rfile.read(length) or b"{}")

        if self.path.endswith("/error"):
            self.send_response(500)
            body = json.dumps({"error": "boom"}).encode()
        elif "generateContent" in self.path:  # Gemini-shaped response
            self.send_response(200)
            body = json.dumps(
                {"candidates": [{"content": {"parts": [{"text": "Gemini mock answer."}]}}]}
            ).encode()
        else:  # Groq-shaped response
            self.send_response(200)
            body = json.dumps(
                {"choices": [{"message": {"content": "Groq mock answer."}}]}
            ).encode()

        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence request logging
        pass


@pytest.fixture()
def mock_llm_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockLLMHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


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


def test_missing_key_raises_503(monkeypatch):
    monkeypatch.setattr(llm, "GROQ_URL", "http://127.0.0.1:1")  # guard against calls
    with pytest.raises(LLMError) as excinfo:
        generate_answer("any question", [])
    assert "GEMINI_API_KEY" in str(excinfo.value)
    assert excinfo.value.status_code == 503


def test_groq_call_uses_bearer_header_and_parses_response(mock_llm_server, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(llm, "GROQ_URL", f"{mock_llm_server}/chat/completions")

    answer = generate_answer("My printer is offline", CONTEXT)

    assert answer == "Groq mock answer."
    assert MockLLMHandler.received_headers.get("Authorization") == "Bearer test-groq-key"
    body = MockLLMHandler.received_body
    assert body["model"] == llm.DEFAULT_GROQ_MODEL
    assert any("printer" in m["content"] for m in body["messages"])


def test_gemini_call_uses_api_key_header_and_parses_response(mock_llm_server, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(
        llm, "GEMINI_URL", f"{mock_llm_server}/models/{{model}}:generateContent"
    )

    answer = generate_answer("My printer is offline", CONTEXT)

    assert answer == "Gemini mock answer."
    assert MockLLMHandler.received_headers.get("x-goog-api-key") == "test-gemini-key"
    assert "printer" in MockLLMHandler.received_body["contents"][0]["parts"][0]["text"]


def test_provider_error_becomes_llm_error_502(mock_llm_server, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(llm, "GROQ_URL", f"{mock_llm_server}/error")

    with pytest.raises(LLMError) as excinfo:
        generate_answer("any question", [])
    assert excinfo.value.status_code == 502
    assert "500" in str(excinfo.value)


def test_llm_status_reports_unconfigured():
    status = llm_status()
    assert status["configured"] is False
    assert status["provider"] == "gemini"
    assert status["message"]
