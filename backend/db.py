"""
backend/db.py
SQLAlchemy engine + session factory + User model for SQLite auth.

DATABASE_URL is read from the environment at import time:
  - Local:      sqlite:///./app.db           (relative to CWD)
  - Render:     sqlite:////var/data/app.db   (persistent disk, 4 slashes = absolute path)

Qdrant handles document embeddings — this module is auth-only.
"""
import os
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Read from environment; default to a local file so `uvicorn` works out of the box.
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# check_same_thread=False is required for SQLite when accessed from multiple
# threads (FastAPI uses a thread pool for sync route handlers).
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)


def create_tables() -> None:
    """
    Create all tables if they do not already exist.

    Uses CREATE TABLE IF NOT EXISTS semantics via SQLAlchemy — safe to call
    on every startup; never drops or truncates existing data.
    """
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yields an open Session and closes it on exit."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
