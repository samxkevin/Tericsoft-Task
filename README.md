# AI IT Support Assistant

A small full-stack demo application. A user asks an IT support question in a
simple web UI; a FastAPI backend searches a local SQL knowledge base for
relevant articles, sends the question **plus the retrieved context** to a free
LLM (Google **Gemini** or **Groq**), and displays the AI troubleshooting
answer in the UI. The question, the retrieved context and the AI answer are
stored as a ticket in SQLite.

## Architecture

```
frontend/ (HTML + CSS + vanilla JS, served by FastAPI)
        |
        |  POST /api/tickets  {question}
        v
backend/main.py  (FastAPI)
        |
        |-- backend/search.py           keyword relevance search (no vectors)
        |        \-- knowledge_base.py  14 seeded IT problems + solutions
        |
        |-- backend/llm.py              Gemini or Groq REST call (env-configured)
        |
        \-- backend/database.py         SQLAlchemy + SQLite
                 \-- tables: knowledge_base, tickets
```

Everything runs in one process: FastAPI serves both the API and the static UI,
so there are no CORS or port configuration issues.

## Project structure

```
backend/
    main.py            FastAPI app: routes, validation, error handling
    config.py          loads .env, exposes settings
    database.py        engine, session, init_db()
    models.py          ORM models (knowledge_base, tickets)
    schemas.py         Pydantic request/response schemas
    knowledge_base.py  seed data + DB helpers
    search.py          keyword relevance search
    llm.py             Gemini / Groq integration
frontend/
    index.html         single-page UI
    style.css          minimal styling
    app.js             fetch calls, loading/error states
tests/                 pytest suite (optional, dev-only)
requirements.txt       runtime dependencies
requirements-dev.txt   adds pytest
.env.example           environment variable placeholders (no real keys)
```

## Requirements

- Python 3.10+
- A **free** API key from [Google AI Studio](https://aistudio.google.com/apikey)
  (Gemini) **or** [Groq](https://console.groq.com/keys). No paid services.

## Installation

```bash
git clone <repository-url>
cd <repository-folder>

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
# now edit .env and paste your API key
```

## Environment variables

| Variable              | Default                  | Purpose                                       |
| --------------------- | ------------------------ | --------------------------------------------- |
| `LLM_PROVIDER`        | `gemini`                 | `gemini` or `groq`                            |
| `GEMINI_API_KEY`      | -                        | required when `LLM_PROVIDER=gemini`           |
| `GROQ_API_KEY`        | -                        | required when `LLM_PROVIDER=groq`             |
| `GEMINI_MODEL`        | `gemini-2.5-flash`       | Gemini model override                         |
| `GROQ_MODEL`          | `llama-3.3-70b-versatile`| Groq model override                           |
| `LLM_TIMEOUT_SECONDS` | `30`                     | timeout for the LLM HTTP call                 |
| `DATABASE_URL`        | `sqlite:///<root>/it_support.db` | database location                      |

Keys are read only from the environment / `.env` (git-ignored). They are sent
to the provider in an authorization header and never logged.

## Running the application

From the **project root**:

```bash
uvicorn backend.main:app --reload
```

Then open <http://127.0.0.1:8000> in your browser.
(Alternative: `python -m backend.main`.)

On startup the app creates `it_support.db` and seeds the knowledge base
(only if the table is empty). Interactive API docs: <http://127.0.0.1:8000/docs>.

## API endpoints

| Method | Path                   | Description                                                        |
| ------ | ---------------------- | ------------------------------------------------------------------ |
| POST   | `/api/tickets`         | Validate question -> search KB -> call LLM -> store & return ticket |
| GET    | `/api/tickets/{id}`    | Retrieve a stored ticket (404 if unknown)                          |
| GET    | `/api/tickets`         | List recent tickets (`?limit=20`, max 100)                         |
| GET    | `/api/knowledge-base`  | List all knowledge-base articles                                   |
| GET    | `/api/health`          | Status incl. whether the LLM is configured                         |

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/tickets \
  -H "Content-Type: application/json" \
  -d '{"question": "My laptop keeps disconnecting from the office Wi-Fi"}'
```

Status codes: `201` created, `422` invalid input, `404` unknown ticket,
`503` LLM not configured, `502`/`504` LLM provider error/timeout, `500` DB error.

## Input validation

`POST /api/tickets` rejects (HTTP 422 with a clear message):
- empty or whitespace-only questions
- questions shorter than 3 characters
- questions longer than 1000 characters

## How the knowledge-base search works

Plain keyword scoring — no embeddings, easy to explain:

1. **Normalize**: lower-case, split into alphanumeric tokens; hyphenated words
   are indexed both split and joined (`wi-fi` matches `wifi`).
2. **Stop words** ("the", "my", "not", ...) are removed.
3. **Light stemming** strips common suffixes (`printing`/`prints` -> `print`,
   `crashes` -> `crash`, `slowly` -> `slow`), and prefix matching catches the
   rest (`print` vs `printer`).
4. Each remaining query term scores points per matched field:
   **title +3, keywords +2, description +1, solution +1** (prefix match +1).
5. Articles with score >= 2 are ranked by score; the **top 3** are returned.
6. **Fallback**: if nothing scores >= 2, the context is empty and the LLM is
   explicitly told that no knowledge-base articles were found.

## LLM integration

- Provider and key come from environment variables (`.env`), never hard-coded.
- The prompt contains the system rules, the retrieved knowledge-base context
  and the user question. The model is instructed to give practical numbered
  steps, **not to invent facts**, and to clearly say when the context is
  insufficient.
- Failures are honest and explicit: missing key -> `503` with instructions;
  rejected key / provider error -> `502`; timeout -> `504`. No answer is ever
  faked or cached as if it came from the API.

## Database schema (SQLite)

```sql
knowledge_base (id, title, description, solution, keywords)  -- 14 seeded articles
tickets         (id, question, retrieved_context, ai_response, created_at)
                -- retrieved_context = JSON of matched articles incl. search score
```

## Testing

Automated tests (optional, dev dependency):

```bash
pip install -r requirements-dev.txt
pytest
```

The tests cover validation, search relevance/fallback, both LLM provider
clients (against a local mock server — no network, no real keys) and the full
API flow including persistence.

Quick manual checks with `curl` are shown in the API section above.

## Limitations

- Keyword search, not semantic (embeddings/vector search would improve recall).
- SQLite is single-writer; fine for a demo, not a multi-user production service.
- No authentication, no streaming responses, no Docker (by design for this MVP).
