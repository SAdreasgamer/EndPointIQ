"""Analysis goal, finding, and report models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field


class GoalType(StrEnum):
    """Types of analysis goals the agent can pursue."""

    SECURITY = "security"
    PERFORMANCE = "performance"
    ARCHITECTURE = "architecture"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    FULL = "full"


class Severity(StrEnum):
    """Severity levels for analysis findings, ordered from most to least severe."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class AgentGoal:
    """A goal for the autonomous agent to pursue.

    The agent decomposes goals into sub-goals, selects tools,
    and executes analysis in the plan→execute→evaluate loop.
    """

    type: GoalType
    endpoint_id: str
    endpoint_display: str  # e.g. "POST /api/users"
    max_iterations: int = 3
    confidence_threshold: float = 0.7
    token_budget: int = 8000
    depth: int = 5  # max graph traversal depth
    metadata: dict = field(default_factory=dict)


class Finding(BaseModel):
    """A single finding from an analysis engine.

    Findings are the core output — each one represents
    a specific issue, observation, or recommendation.
    """

    severity: Severity
    title: str
    description: str
    file_path: str | None = None
    line_number: int | None = None
    recommendation: str = ""
    evidence: str | None = None
    engine: str = ""  # which engine produced this finding
    rule_id: str | None = None  # e.g. "OWASP-A01" for traceability

    @property
    def severity_rank(self) -> int:
        """Numeric rank for sorting (lower = more severe)."""
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        return order.get(self.severity.value, 5)


class TokenUsage(BaseModel):
    """Token usage tracking for a single LLM call."""

    provider: str = "groq"
    model: str = "llama-3.1-8b-instant"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    context_size_bytes: int = 0
    compressed_size_bytes: int = 0
    compression_ratio: float = 0.0
    latency_ms: int = 0


class AnalysisReport(BaseModel):
    """Complete analysis report produced by the agent.

    This is the final output — what the user sees in the CLI,
    VS Code extension, or dashboard.
    """

    id: str = ""
    endpoint: str  # e.g. "POST /api/users"
    goal_type: GoalType
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    tokens_without_eiq: int = 0  # estimated tokens if we sent the full repo
    token_savings_percent: float = 0.0
    cost_savings_percent: float = 0.0
    latency_ms: int = 0
    confidence: float = 0.0
    iterations: int = 1
    status: str = "completed"

    @property
    def critical_count(self) -> int:
        """Number of critical findings."""
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        """Number of high-severity findings."""
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    @property
    def pass_count(self) -> int:
        """Number of info/pass findings."""
        return sum(1 for f in self.findings if f.severity == Severity.INFO)
