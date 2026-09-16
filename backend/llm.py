"""LLM integration: Google Gemini or Groq, configured via environment variables.

Only free-tier-friendly providers are supported (Google Gemini and Groq). The
API key is read from the environment (never hard-coded, never logged) and is
sent in an authorization header, not in the URL.

All failures raise LLMError carrying an HTTP status code the API layer can
return directly:

- 503: provider/key not configured (action needed by the operator)
- 502: provider rejected the request or returned an unusable response
- 504: provider timed out
"""

import os

import httpx

from . import config  # noqa: F401  (importing config loads the .env file)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_PROVIDER = "gemini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
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


def _default_model(provider: str) -> str:
    return DEFAULT_GEMINI_MODEL if provider == "gemini" else DEFAULT_GROQ_MODEL


def _get_config() -> dict[str, str]:
    """Read and validate the LLM configuration from environment variables."""
    provider = (os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if provider not in ("gemini", "groq"):
        raise LLMError(
            f"Invalid LLM_PROVIDER '{provider}'. Use 'gemini' or 'groq' in your .env file.",
            status_code=503,
        )

    key_var = "GEMINI_API_KEY" if provider == "gemini" else "GROQ_API_KEY"
    model_var = "GEMINI_MODEL" if provider == "gemini" else "GROQ_MODEL"
    api_key = (os.getenv(key_var) or "").strip()
    model = (os.getenv(model_var) or "").strip() or _default_model(provider)

    if not api_key:
        hint = ""
        other_var = "GROQ_API_KEY" if provider == "gemini" else "GEMINI_API_KEY"
        if (os.getenv(other_var) or "").strip():
            other_provider = "groq" if provider == "gemini" else "gemini"
            hint = f" (A {other_var} is set - you can set LLM_PROVIDER={other_provider} to use it.)"
        raise LLMError(
            f"The LLM is not configured: {key_var} is missing. Add your free API key "
            f"to the .env file (see .env.example).{hint}",
            status_code=503,
        )

    return {"provider": provider, "api_key": api_key, "model": model}


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


def _request_json(
    url: str, headers: dict[str, str], payload: dict, timeout: float, provider: str
) -> dict:
    """POST the payload and return the parsed JSON body, with clear LLMErrors."""
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.TimeoutException:
        raise LLMError(
            f"The {provider} API did not respond within {timeout:.0f} seconds. "
            "Please try again.",
            status_code=504,
        )
    except httpx.HTTPError as exc:
        raise LLMError(
            f"Could not reach the {provider} API ({exc.__class__.__name__}). "
            "Check your network connection.",
            status_code=502,
        )

    if response.status_code in (401, 403):
        raise LLMError(
            f"The {provider} API rejected the API key (HTTP {response.status_code}). "
            "Check the key in your .env file.",
            status_code=502,
        )
    if response.status_code != 200:
        raise LLMError(
            f"The {provider} API returned HTTP {response.status_code}: "
            f"{_snippet(response.text)}",
            status_code=502,
        )
    try:
        return response.json()
    except ValueError:
        raise LLMError(
            f"The {provider} API returned a non-JSON response.", status_code=502
        )


def _call_gemini(cfg: dict, messages: list[dict], timeout: float) -> str:
    """Call Google Gemini's generateContent REST endpoint."""
    prompt = f"{messages[0]['content']}\n\n---\n\n{messages[1]['content']}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    url = GEMINI_URL.format(model=cfg["model"])
    headers = {
        "Content-Type": "application/json",
        # The key goes in a header, never in the URL.
        "x-goog-api-key": cfg["api_key"],
    }
    data = _request_json(url, headers, payload, timeout, "Gemini")
    try:
        parts = data["candidates"][0]["content"]["parts"]
        # Thinking models may return several parts; keep the real text ones.
        text = "\n".join(
            part["text"]
            for part in parts
            if isinstance(part, dict) and part.get("text") and not part.get("thought")
        )
    except (KeyError, IndexError, TypeError):
        raise LLMError(
            "Gemini returned an unexpected response (possibly empty or blocked).",
            status_code=502,
        )
    if not text.strip():
        raise LLMError("Gemini returned an empty response.", status_code=502)
    return text.strip()


def _call_groq(cfg: dict, messages: list[dict], timeout: float) -> str:
    """Call Groq's OpenAI-compatible chat-completions endpoint."""
    payload = {"model": cfg["model"], "messages": messages, "temperature": 0.2}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    }
    data = _request_json(GROQ_URL, headers, payload, timeout, "Groq")
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("Groq returned an unexpected response.", status_code=502)
    if not text or not text.strip():
        raise LLMError("Groq returned an empty response.", status_code=502)
    return text.strip()


def generate_answer(question: str, context_items: list[dict]) -> str:
    """Generate a troubleshooting answer for `question` using the retrieved context."""
    cfg = _get_config()
    messages = build_messages(question, context_items)
    timeout = _timeout()
    if cfg["provider"] == "gemini":
        return _call_gemini(cfg, messages, timeout)
    return _call_groq(cfg, messages, timeout)


def llm_status() -> dict:
    """Non-raising configuration status, used by GET /api/health."""
    provider = (os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    try:
        cfg = _get_config()
        return {
            "provider": cfg["provider"],
            "model": cfg["model"],
            "configured": True,
            "message": None,
        }
    except LLMError as exc:
        model = _default_model(provider) if provider in ("gemini", "groq") else ""
        return {
            "provider": provider,
            "model": model,
            "configured": False,
            "message": str(exc),
        }
