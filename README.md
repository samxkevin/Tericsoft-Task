# AI IT Support Assistant

A small full-stack demo application. A user asks an IT support question in a
simple web UI; a FastAPI backend searches a local SQL knowledge base for
relevant articles, sends the question **plus the retrieved context** to
**Cohere's V2 Chat API** (with primary/fallback keys), and displays the AI
troubleshooting answer in the UI. The question, the retrieved context and the
AI answer are stored as a ticket in SQLite.

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
        |-- backend/llm.py              Cohere V2 chat call (primary + fallback)
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
    llm.py             Cohere V2 chat integration (primary + fallback)
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
- A Cohere API key (primary, plus optionally a fallback key) from
  <https://dashboard.cohere.com/api-keys>

## Installation

```bash
git clone <repository-url>
cd <repository-folder>

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
# now edit .env and paste your API key(s)
```

## Environment variables

| Variable                  | Default                  | Purpose                              |
| ------------------------- | ------------------------ | ------------------------------------ |
| `COHERE_API_KEY_PRIMARY`  | -                        | primary API key (required)           |
| `COHERE_PRIMARY_MODEL`    | `command-a-plus-05-2026` | model used with the primary key      |
| `COHERE_API_KEY_FALLBACK` | -                        | fallback API key (optional)          |
| `COHERE_FALLBACK_MODEL`   | `command-a-03-2025`      | model used with the fallback key     |
| `LLM_TIMEOUT_SECONDS`     | `30`                     | timeout per LLM HTTP call            |
| `DATABASE_URL`            | `sqlite:///<root>/it_support.db` | database location            |

Keys are read only from the environment / `.env` (git-ignored). They are sent
to Cohere as a `Bearer` token and never logged.

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

## LLM integration (Cohere V2, primary + fallback)

- Endpoint: `POST https://api.cohere.com/v2/chat` with
  `Authorization: Bearer <key>`, `Content-Type: application/json`,
  `stream: false`, and `messages` with system/user roles.
- Configuration comes from environment variables only (`.env`), never
  hard-coded.
- **Failover**: the primary key + primary model is tried first. If that
  request fails for any provider-side reason (authentication, rate limiting,
  timeout, network error, provider failure), the fallback key + fallback
  model is tried once. Keys are not tied to models - either key may serve
  either model. There are never more than two attempts; if both fail, one
  clear error summarising both failures is returned.
- The prompt contains the system rules, the retrieved knowledge-base context
  and the user question. The model is instructed to give practical numbered
  steps, **not to invent facts**, and to clearly say when the context is
  insufficient.
- Failures are honest and explicit: no key at all -> `503` with instructions;
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

The tests cover validation, search relevance/fallback, the Cohere V2 client
including primary/fallback failover (against a local mock server — no network,
no real keys) and the full API flow including persistence.

Quick manual checks with `curl` are shown in the API section above.

## Limitations

- Keyword search, not semantic (embeddings/vector search would improve recall).
- SQLite is single-writer; fine for a demo, not a multi-user production service.
- LLM failover is one level deep (primary -> fallback) with no further retries.
- No authentication, no streaming responses (`stream: false` by design), no Docker.
