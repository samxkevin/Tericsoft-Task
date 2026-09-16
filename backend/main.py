"""FastAPI application for the AI IT Support Assistant.

Serves the static UI from frontend/ and exposes the JSON API:

    POST /api/tickets          create a ticket (validate -> search KB -> LLM -> store)
    GET  /api/tickets/{id}     fetch a stored ticket
    GET  /api/tickets          list recent tickets
    GET  /api/knowledge-base   list knowledge-base articles
    GET  /api/health           service status

Run from the project root:

    uvicorn backend.main:app --reload
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import knowledge_base, llm, models
from .config import BASE_DIR
from .database import SessionLocal, get_db, init_db
from .llm import LLMError
from .schemas import (
    ArticleOut,
    HealthResponse,
    QuestionRequest,
    TicketResponse,
    TicketSummary,
)
from .search import search_articles

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")
logger = logging.getLogger("it_support_assistant")

FRONTEND_DIR = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create tables and seed the knowledge base on startup (idempotent)."""
    init_db()
    with SessionLocal() as db:
        seeded = knowledge_base.seed_knowledge_base(db)
    if seeded:
        logger.info("Seeded knowledge base with %d articles.", seeded)
    yield


app = FastAPI(
    title="AI IT Support Assistant",
    description=(
        "Ask an IT support question; get an AI troubleshooting answer grounded "
        "in a local knowledge base."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# The UI is served by this same app (same origin), so CORS is not needed for
# normal operation. It is enabled for anyone who wants to serve the frontend
# from a different port during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Turn Pydantic's default 422 into one clear, human-readable message."""
    if exc.errors():
        message = exc.errors()[0].get("msg", "Invalid request.")
        message = message.split("Value error, ", 1)[-1]
    else:
        message = "Invalid request."
    return JSONResponse(
        status_code=422, content={"detail": f"Invalid input: {message}"}
    )


@app.get("/", include_in_schema=False)
def serve_ui() -> FileResponse:
    """Serve the single-page frontend."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health(db: Session = Depends(get_db)) -> HealthResponse:
    """Service status; also reports whether the LLM is configured."""
    status = llm.llm_status()
    return HealthResponse(
        status="ok",
        llm_provider=status["provider"],
        llm_configured=status["configured"],
        llm_model=status["model"] or "",
        knowledge_base_articles=knowledge_base.count_articles(db),
    )


@app.get("/api/knowledge-base", response_model=list[ArticleOut], tags=["knowledge-base"])
def list_knowledge_base(db: Session = Depends(get_db)):
    """List all knowledge-base articles."""
    return knowledge_base.get_articles(db)


@app.post("/api/tickets", response_model=TicketResponse, status_code=201, tags=["tickets"])
def create_ticket(payload: QuestionRequest, db: Session = Depends(get_db)) -> models.Ticket:
    """Create a support ticket.

    Validates the question, searches the knowledge base, asks the configured
    LLM (question + retrieved context) for a troubleshooting answer, and stores
    the question, the retrieved context and the answer in the database.
    """
    articles = knowledge_base.get_articles(db)
    matches = search_articles(payload.question, articles)

    try:
        answer = llm.generate_answer(payload.question, matches)
    except LLMError as exc:
        # Missing configuration (503) or provider failure (502/504); nothing
        # is stored and the user gets a clear, actionable message.
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    try:
        ticket = models.Ticket(
            question=payload.question,
            retrieved_context=json.dumps(matches),
            ai_response=answer,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="A database error occurred while saving the ticket.",
        )

    return ticket


@app.get("/api/tickets", response_model=list[TicketSummary], tags=["tickets"])
def list_tickets(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List the most recent tickets (newest first)."""
    stmt = select(models.Ticket).order_by(models.Ticket.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


@app.get("/api/tickets/{ticket_id}", response_model=TicketResponse, tags=["tickets"])
def get_ticket(ticket_id: int, db: Session = Depends(get_db)) -> models.Ticket:
    """Retrieve a previously created ticket by id."""
    ticket = db.get(models.Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
    return ticket


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
