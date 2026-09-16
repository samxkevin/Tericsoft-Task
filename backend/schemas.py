"""Pydantic schemas: request validation and API response models."""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

MIN_QUESTION_LENGTH = 3
MAX_QUESTION_LENGTH = 1000


class QuestionRequest(BaseModel):
    """Request body for POST /api/tickets."""

    question: str

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be empty or whitespace-only.")
        if len(value) < MIN_QUESTION_LENGTH:
            raise ValueError(
                f"Question is too short; use at least {MIN_QUESTION_LENGTH} characters."
            )
        if len(value) > MAX_QUESTION_LENGTH:
            raise ValueError(
                f"Question is too long; use at most {MAX_QUESTION_LENGTH} characters."
            )
        return value


class ArticleOut(BaseModel):
    """A knowledge-base article as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    solution: str
    keywords: str


class ContextItem(BaseModel):
    """One knowledge-base article attached to a ticket (with search score)."""

    id: int
    title: str
    description: str
    solution: str
    score: int = 0


class TicketResponse(BaseModel):
    """Full ticket returned by POST /api/tickets and GET /api/tickets/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    ai_response: str
    created_at: datetime
    retrieved_context: list[ContextItem]

    @field_validator("retrieved_context", mode="before")
    @classmethod
    def _parse_stored_context(cls, value: Any) -> Any:
        """The database stores the context as a JSON string; parse it back."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = []
        return value or []


class TicketSummary(BaseModel):
    """Compact ticket info for the list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    created_at: datetime


class HealthResponse(BaseModel):
    """Service status for GET /api/health."""

    status: str
    llm_provider: str
    llm_configured: bool
    llm_model: str
    knowledge_base_articles: int
