"""LLM integration: Cohere V2 Chat API with primary/fallback failover.

Configuration comes from environment variables (see .env.example):

    COHERE_API_KEY_PRIMARY    primary API key
    COHERE_PRIMARY_MODEL      primary model   (default command-a-plus-05-2026)
    COHERE_API_KEY_FALLBACK   fallback API key (optional)
    COHERE_FALLBACK_MODEL     fallback model  (default command-a-03-2025)

Behaviour:
1. Call the primary key with the primary model.
2. If that attempt fails for any provider-side reason (authentication, rate
   limiting, provider failure, timeout, network error, unusable response),
   call the fallback key with the fallback model once. Keys are not tied to
   models - either key may serve either model.
3. Never more than two attempts in total (no infinite retries).
4. If all attempts fail, raise one clear LLMError for the API layer.

API keys are read from the environment only (never hard-coded), sent as a
Bearer token, never logged and never included in error messages.

LLMError status codes surfaced to the API layer:
- 503: no API key configured at all (action needed by the operator)
- 502: provider rejected the request or returned an unusable response
- 504: provider timed out
"""

import os

import httpx

from . import config  # noqa: F401  (importing config loads the .env file)

COHERE_URL = "https://api.cohere.com/v2/chat"

DEFAULT_PRIMARY_MODEL = "command-a-plus-05-2026"
DEFAULT_FALLBACK_MODEL = "command-a-03-2025"
DEFAULT_TIMEOUT_SECONDS = 30.0

SYSTEM_PROMPT = """You are an experienced IT support technician. A user asks you a technical support question.

Rules:
- Answer with clear, practical troubleshooting steps the user can follow.
- Use the knowledge-base context below when it is relevant; do not contradict it.
- Do not invent error codes, URLs, commands or policies that are not in the context and are not standard IT practice.
- If the context is empty or does not cover the question, say explicitly that the knowledge base does not cover this issue, then give only safe, general guidance.
- Keep the answer concise (under ~300 words) and use short numbered steps."""


class LLMError(Exception):
    """Raised when the LLM cannot be called or returns an unusable response."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _attempts() -> list[dict]:
    """Ordered (key, model) attempts built from the environment.

    Primary first, then fallback. A key that is missing/empty is skipped, so
    configuring only the fallback key works directly. Raises LLMError(503)
    when no key is configured at all.
    """
    primary_key = (os.getenv("COHERE_API_KEY_PRIMARY") or "").strip()
    fallback_key = (os.getenv("COHERE_API_KEY_FALLBACK") or "").strip()
    primary_model = (os.getenv("COHERE_PRIMARY_MODEL") or "").strip() or DEFAULT_PRIMARY_MODEL
    fallback_model = (os.getenv("COHERE_FALLBACK_MODEL") or "").strip() or DEFAULT_FALLBACK_MODEL

    attempts = []
    if primary_key:
        attempts.append({"key": primary_key, "model": primary_model, "label": "primary"})
    if fallback_key:
        attempts.append({"key": fallback_key, "model": fallback_model, "label": "fallback"})

    if not attempts:
        raise LLMError(
            "The LLM is not configured: no Cohere API key found. Add "
            "COHERE_API_KEY_PRIMARY (and optionally COHERE_API_KEY_FALLBACK) to the "
            ".env file (see .env.example).",
            status_code=503,
        )
    return attempts


def _timeout() -> float:
    raw = os.getenv("LLM_TIMEOUT_SECONDS", "")
    try:
        return max(float(raw) if raw else DEFAULT_TIMEOUT_SECONDS, 1.0)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def build_messages(question: str, context_items: list[dict]) -> list[dict[str, str]]:
    """Build the chat messages sent to the LLM (system rules + context + question)."""
    if context_items:
        blocks = []
        for index, item in enumerate(context_items, start=1):
            blocks.append(
                f"[{index}] Title: {item['title']}\n"
                f"Problem: {item['description']}\n"
                f"Solution: {item['solution']}"
            )
        context_text = "\n\n".join(blocks)
    else:
        context_text = "(No relevant knowledge-base articles were found for this question.)"

    user_content = (
        "Knowledge-base context:\n"
        f"{context_text}\n\n"
        f"User question: {question}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _snippet(text: str, limit: int = 300) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


def _parse_answer(data: dict) -> str:
    """Extract the assistant text from a Cohere V2 chat response.

    V2 returns message.content as a list of content blocks; a plain string is
    also accepted defensively.
    """
    try:
        content = data["message"]["content"]
    except (KeyError, TypeError):
        raise LLMError("returned an unexpected response shape", status_code=502)

    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        text = ""

    if not text.strip():
        raise LLMError("returned an empty response", status_code=502)
    return text.strip()


def _chat_once(attempt: dict, messages: list[dict], timeout: float) -> str:
    """Perform one Cohere V2 chat request. Raises LLMError on any failure."""
    payload = {"model": attempt["model"], "messages": messages, "stream": False}
    headers = {
        "Content-Type": "application/json",
        # The key goes in the Authorization header only - never in the URL.
        "Authorization": f"Bearer {attempt['key']}",
    }
    try:
        response = httpx.post(COHERE_URL, headers=headers, json=payload, timeout=timeout)
    except httpx.TimeoutException:
        raise LLMError(
            f"did not respond within {timeout:.0f} seconds", status_code=504
        )
    except httpx.HTTPError as exc:
        raise LLMError(
            f"could not be reached ({exc.__class__.__name__}); check the network "
            "connection",
            status_code=502,
        )

    if response.status_code in (401, 403):
        raise LLMError(
            f"the API key was rejected (HTTP {response.status_code}); check the key "
            "in the .env file",
            status_code=502,
        )
    if response.status_code == 429:
        raise LLMError("the rate limit was reached (HTTP 429)", status_code=502)
    if response.status_code != 200:
        raise LLMError(
            f"returned HTTP {response.status_code}: {_snippet(response.text)}",
            status_code=502,
        )
    try:
        data = response.json()
    except ValueError:
        raise LLMError("returned a non-JSON response", status_code=502)
    return _parse_answer(data)


def generate_answer(question: str, context_items: list[dict]) -> str:
    """Generate a troubleshooting answer, trying primary then fallback.

    At most two attempts are made (one per configured key). If all attempts
    fail, a single LLMError summarising every failure is raised; it never
    contains API keys.
    """
    attempts = _attempts()  # raises LLMError(503) when no key is configured
    messages = build_messages(question, context_items)
    timeout = _timeout()

    failures: list[str] = []
    status_code = 502
    for attempt in attempts:
        try:
            return _chat_once(attempt, messages, timeout)
        except LLMError as exc:
            failures.append(f"{attempt['label']} ({attempt['model']}): {exc}")
            status_code = exc.status_code

    summary = "; ".join(failures)
    if len(failures) == 1:
        raise LLMError(f"The Cohere chat request failed - {summary}", status_code=status_code)
    raise LLMError(f"All Cohere attempts failed - {summary}", status_code=status_code)


def llm_status() -> dict:
    """Non-raising configuration status, used by GET /api/health."""
    primary_key = (os.getenv("COHERE_API_KEY_PRIMARY") or "").strip()
    fallback_key = (os.getenv("COHERE_API_KEY_FALLBACK") or "").strip()
    primary_model = (os.getenv("COHERE_PRIMARY_MODEL") or "").strip() or DEFAULT_PRIMARY_MODEL
    fallback_model = (os.getenv("COHERE_FALLBACK_MODEL") or "").strip() or DEFAULT_FALLBACK_MODEL

    if primary_key or fallback_key:
        return {
            "provider": "cohere",
            "model": primary_model if primary_key else fallback_model,
            "configured": True,
            "message": None,
        }
    return {
        "provider": "cohere",
        "model": primary_model,
        "configured": False,
        "message": (
            "The LLM is not configured: no Cohere API key found. Add "
            "COHERE_API_KEY_PRIMARY (and optionally COHERE_API_KEY_FALLBACK) to the "
            ".env file (see .env.example)."
        ),
    }
