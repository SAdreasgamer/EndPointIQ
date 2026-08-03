"""EndpointIQ configuration system.

Configuration is loaded from (in order of priority):
1. Environment variables (prefixed with EIQ_)
2. .env file
3. .endpointiq.toml file
4. Default values
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EndpointIQConfig(BaseSettings):
    """Main configuration for EndpointIQ."""

    model_config = SettingsConfigDict(
        env_prefix="EIQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Project ────────────────────────────────────────
    project_root: Path = Field(default=Path("."))

    # ── Watcher ────────────────────────────────────────
    watch_debounce_seconds: float = 0.3
    watch_ignore_patterns: list[str] = Field(
        default_factory=lambda: [
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            ".endpointiq",
            "*.pyc",
            "*.lock",
            "dist",
            "build",
            ".next",
            "coverage",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ]
    )

    # ── Parser ─────────────────────────────────────────
    parser_cache_size: int = 500

    # ── Knowledge Graph ────────────────────────────────
    graph_backend: str = "networkx"  # "networkx" | "neo4j"
    graph_persist_path: Path = Field(default=Path(".endpointiq/graph.json"))

    # ── Database ───────────────────────────────────────
    db_path: Path = Field(default=Path(".endpointiq/endpointiq.db"))

    # ── Agent ──────────────────────────────────────────
    agent_max_iterations: int = 3
    agent_confidence_threshold: float = 0.7
    agent_max_token_budget: int = 8000

    # ── LLM (Groq) ────────────────────────────────────
    groq_api_key: str = ""
    llm_model: str = "llama-3.1-8b-instant"
    llm_temperature: float = 0.0

    # ── Server ─────────────────────────────────────────
    server_host: str = "127.0.0.1"
    server_port: int = 8421

    # ── Logging ────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "console"  # "console" | "json"

    def ensure_dirs(self) -> None:
        """Create necessary directories if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.graph_persist_path.parent.mkdir(parents=True, exist_ok=True)


def load_config(**overrides) -> EndpointIQConfig:
    """Load configuration with optional overrides.

    Usage:
        config = load_config()  # loads from env/.env/.toml
        config = load_config(project_root=Path("/path/to/project"))
    """
    return EndpointIQConfig(**overrides)
