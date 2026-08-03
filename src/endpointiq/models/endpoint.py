"""Endpoint data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class HttpMethod(StrEnum):
    """HTTP methods supported by EndpointIQ."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"


@dataclass
class EndpointDefinition:
    """Represents a discovered API endpoint in the codebase.

    This is the primary unit of analysis — everything in EndpointIQ
    revolves around endpoints.
    """

    method: HttpMethod
    path: str
    handler: str  # qualified function name, e.g. "UserController.create"
    file_path: str
    line_start: int
    line_end: int
    framework: str  # e.g. "express", "nestjs", "fastapi"
    middleware: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Human-readable endpoint identifier, e.g. 'POST /api/users'."""
        return f"{self.method} {self.path}"

    @property
    def id(self) -> str:
        """Deterministic unique identifier for this endpoint."""
        import hashlib

        raw = f"{self.method}:{self.path}:{self.handler}:{self.file_path}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
