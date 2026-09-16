"""SQLAlchemy ORM models: knowledge_base and tickets tables."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeArticle(Base):
    """One IT problem + its solution in the searchable knowledge base."""

    __tablename__ = "knowledge_base"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    solution: Mapped[str] = mapped_column(Text, nullable=False)
    # Comma-separated extra search terms.
    keywords: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class Ticket(Base):
    """A support request: the question, the context used and the AI answer."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON string: list of matched knowledge-base articles (id/title/.../score).
    retrieved_context: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    ai_response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
