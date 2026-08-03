"""SQLAlchemy ORM models for EndpointIQ metadata storage.

These models store project metadata, discovered endpoints,
analysis reports, and token usage logs. The knowledge graph
itself lives in NetworkX — these models handle everything else.
"""

from __future__ import annotations

import time

from sqlalchemy import Column, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Project(Base):
    """A project being analyzed by EndpointIQ."""

    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    root_path = Column(String, nullable=False, unique=True)
    framework = Column(String, default="")
    framework_confidence = Column(Float, default=0.0)
    language = Column(String, default="")
    config = Column(Text, default="{}")  # JSON
    index_status = Column(String, default="pending")  # pending | indexing | ready | error
    files_count = Column(Integer, default=0)
    endpoints_count = Column(Integer, default=0)
    graph_nodes = Column(Integer, default=0)
    graph_edges = Column(Integer, default=0)
    last_indexed_at = Column(Integer, default=0)
    created_at = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)


class Endpoint(Base):
    """A discovered API endpoint."""

    __tablename__ = "endpoints"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    method = Column(String, nullable=False)
    path = Column(String, nullable=False)
    handler = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=False)
    framework = Column(String, default="")
    middleware = Column(Text, default="[]")  # JSON list
    decorators = Column(Text, default="[]")  # JSON list
    metadata_ = Column("metadata", Text, default="{}")  # JSON
    status = Column(String, default="active")
    last_analyzed_at = Column(Integer, default=0)
    created_at = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)


class FileIndex(Base):
    """Index of all parsed files in the project."""

    __tablename__ = "file_index"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)
    language = Column(String, default="")
    symbols_count = Column(Integer, default=0)
    imports_count = Column(Integer, default=0)
    line_count = Column(Integer, default=0)
    last_parsed_at = Column(Integer, default=0)
    created_at = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)


class AnalysisReportRecord(Base):
    """Stored analysis report."""

    __tablename__ = "analysis_reports"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    endpoint_id = Column(String, default="")
    type = Column(String, nullable=False)  # security | performance | architecture | full
    goal = Column(Text, default="{}")  # JSON
    plan = Column(Text, default="{}")  # JSON
    results = Column(Text, default="{}")  # JSON
    report = Column(Text, default="{}")  # JSON
    confidence = Column(Float, default=0.0)
    token_usage = Column(Text, default="{}")  # JSON
    latency_ms = Column(Integer, default=0)
    iterations = Column(Integer, default=1)
    status = Column(String, default="running")  # running | completed | failed
    created_at = Column(Integer, nullable=False)
    completed_at = Column(Integer, default=0)


class TokenUsageLog(Base):
    """Log of token usage for each LLM call."""

    __tablename__ = "token_usage_log"

    id = Column(String, primary_key=True)
    report_id = Column(String, default="")
    provider = Column(String, nullable=False, default="groq")
    model = Column(String, nullable=False, default="llama-3.1-8b-instant")
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Float, default=0.0)
    context_size_bytes = Column(Integer, default=0)
    compressed_size_bytes = Column(Integer, default=0)
    compression_ratio = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    created_at = Column(Integer, nullable=False)


# ── Session Management ────────────────────────────────


class DatabaseManager:
    """Manages SQLite database connection and sessions.

    Usage:
        db = DatabaseManager("path/to/db.sqlite")
        db.create_tables()

        with db.session() as session:
            session.add(Project(...))
    """

    def __init__(self, db_path: str = ".endpointiq/endpointiq.db"):
        self.db_path = db_path
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        self._session_factory = sessionmaker(bind=self.engine)

    def create_tables(self) -> None:
        """Create all tables if they don't exist."""
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        """Create a new database session."""
        return self._session_factory()

    def close(self) -> None:
        """Close the database engine."""
        self.engine.dispose()


def now_timestamp() -> int:
    """Current Unix timestamp as integer."""
    return int(time.time())
