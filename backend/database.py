"""Database engine, session factory and helpers (SQLite via SQLAlchemy)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    """Base class for all ORM models."""


engine = create_engine(
    DATABASE_URL,
    # SQLite requires this flag because FastAPI may use several threads.
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency that yields one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables if they do not exist yet (called on startup)."""
    from . import models  # noqa: F401  (importing registers the models on Base)

    Base.metadata.create_all(bind=engine)
