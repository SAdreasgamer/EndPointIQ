"""Security analysis engine.

Detects security vulnerabilities in API endpoints using a two-phase approach:
1. Static checks via knowledge graph traversal (fast, no LLM)
2. LLM-assisted deeper analysis via Groq (optional)

Checks performed:
- Missing Authentication (no SECURED_BY edges)
- Missing Input Validation (no validation middleware)
- SQL Injection Patterns (string concatenation in queries)
- Missing Rate Limiting (mutation endpoints without limiter)
- Security Headers (no CORS/helmet middleware)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.models.analysis import Finding, Severity
from endpointiq.models.graph import EdgeType, NodeType

logger = logging.getLogger(__name__)


class SecurityEngine:
    """Static security analysis engine.

    Traverses the knowledge graph to detect security issues
    without requiring LLM calls.

    Usage:
        engine = SecurityEngine(knowledge_graph, project_root)
        findings = engine.analyze_endpoint("POST /api/users")
    """

    def __init__(self, graph: KnowledgeGraph, project_root: Path):
        self.graph = graph
        self.project_root = project_root

    def analyze_endpoint(self, endpoint_name: str) -> list[Finding]:
        """Run all security checks on a single endpoint.

        Returns a list of findings sorted by severity.
        """
        findings: list[Finding] = []

        endpoint_id = self.graph.lookup_endpoint(endpoint_name)
        if not endpoint_id:
            findings.append(Finding(
                severity=Severity.INFO,
                title="Endpoint Not Found",
                description=f"Could not find endpoint '{endpoint_name}' in the knowledge graph.",
                recommendation="Run 'eiq index' to rebuild the knowledge graph.",
            ))
            return findings

        attrs = self.graph.get_node(endpoint_id) or {}
        file_path = attrs.get("file_path", "")
        line_start = attrs.get("line_start", 0)
        metadata = attrs.get("metadata", {})
        method = metadata.get("method", "GET") if isinstance(metadata, dict) else "GET"
        path = metadata.get("path", endpoint_name) if isinstance(metadata, dict) else endpoint_name

        # Run checks
        findings.extend(self._check_authentication(endpoint_id, method, path, file_path, line_start))
        findings.extend(self._check_input_validation(endpoint_id, method, path, file_path, line_start))
        findings.extend(self._check_injection_patterns(endpoint_id, file_path))
        findings.extend(self._check_rate_limiting(endpoint_id, method, path, file_path, line_start))
        findings.extend(self._check_security_headers())

        # Sort by severity
        findings.sort(key=lambda f: f.severity_rank)
        return findings

    def analyze_all_endpoints(self) -> dict[str, list[Finding]]:
        """Run security checks on all discovered endpoints."""
        results: dict[str, list[Finding]] = {}
        for ep in self.graph.list_endpoints():
            name = ep.get("display_name", "")
            if name:
                results[name] = self.analyze_endpoint(name)
        return results

    def _check_authentication(
        self, endpoint_id: str, method: str, path: str,
        file_path: str, line_start: int
    ) -> list[Finding]:
        """Check if the endpoint has authentication middleware."""
        findings: list[Finding] = []
        neighbors = self.graph.get_neighbors(endpoint_id, edge_types=[EdgeType.SECURED_BY])

        has_auth = False
        for nid in neighbors:
            n_attrs = self.graph.get_node(nid)
            if n_attrs:
                name = n_attrs.get("qualified_name", "").lower()
                if "auth" in name or "jwt" in name or "token" in name or "session" in name:
                    has_auth = True
                    break

        if not has_auth:
            # Mutation endpoints without auth are critical
            if method in ("POST", "PUT", "DELETE", "PATCH"):
                findings.append(Finding(
                    severity=Severity.CRITICAL,
                    title="Missing Authentication on Mutation Endpoint",
                    description=(
                        f"Endpoint {method} {path} has no authentication middleware. "
                        "Mutation endpoints must verify the caller's identity."
                    ),
                    file_path=file_path,
                    line_number=line_start,
                    recommendation=(
                        "Add authentication middleware (e.g., authMiddleware, JWT verification) "
                        "before the route handler."
                    ),
                ))
            else:
                findings.append(Finding(
                    severity=Severity.MEDIUM,
                    title="No Authentication on GET Endpoint",
                    description=f"Endpoint {method} {path} has no authentication middleware.",
                    file_path=file_path,
                    line_number=line_start,
                    recommendation="Consider adding authentication if this endpoint returns sensitive data.",
                ))
        else:
            findings.append(Finding(
                severity=Severity.INFO,
                title="Authentication Present",
                description=f"Endpoint {method} {path} has authentication middleware.",
                file_path=file_path,
                line_number=line_start,
                recommendation="Verify token validation logic and expiry handling.",
            ))

        return findings

    def _check_input_validation(
        self, endpoint_id: str, method: str, path: str,
        file_path: str, line_start: int
    ) -> list[Finding]:
        """Check if mutation endpoints have input validation."""
        findings: list[Finding] = []

        if method not in ("POST", "PUT", "PATCH"):
            return findings  # Only check mutation endpoints

        neighbors = self.graph.get_neighbors(endpoint_id, edge_types=[EdgeType.SECURED_BY])
        has_validation = False
        for nid in neighbors:
            n_attrs = self.graph.get_node(nid)
            if n_attrs:
                name = n_attrs.get("qualified_name", "").lower()
                if "valid" in name or "schema" in name or "dto" in name or "sanitize" in name:
                    has_validation = True
                    break

        if not has_validation:
            findings.append(Finding(
                severity=Severity.HIGH,
                title="Missing Input Validation",
                description=(
                    f"Endpoint {method} {path} accepts user input but has no "
                    "validation middleware. Unvalidated input can lead to injection "
                    "attacks, data corruption, and unexpected errors."
                ),
                file_path=file_path,
                line_number=line_start,
                recommendation=(
                    "Add request body validation using a schema validator "
                    "(e.g., Joi, Zod, class-validator) before the route handler."
                ),
            ))

        return findings

    def _check_injection_patterns(self, endpoint_id: str, file_path: str) -> list[Finding]:
        """Check for SQL injection patterns in the endpoint's call chain."""
        findings: list[Finding] = []

        # Traverse from endpoint to repository layer
        reachable = self.graph.get_neighbors(endpoint_id, depth=4)
        for nid in reachable:
            n_attrs = self.graph.get_node(nid)
            if not n_attrs:
                continue

            node_type = n_attrs.get("type", "")
            n_file = n_attrs.get("file_path", "")
            n_line = n_attrs.get("line_start", 0)

            # Check for raw query patterns in repository/service nodes
            if node_type in (NodeType.REPOSITORY.value, NodeType.SERVICE.value):
                source = self._read_source(n_file, n_line, n_attrs.get("line_end", n_line + 20))
                if source and re.search(r'query\s*\(\s*[`"\'].*?\$\{', source):
                    findings.append(Finding(
                        severity=Severity.CRITICAL,
                        title="Potential SQL Injection",
                        description=(
                            f"String interpolation detected in database query in {n_file}. "
                            "User input may be directly embedded in SQL statements."
                        ),
                        file_path=n_file,
                        line_number=n_line,
                        recommendation="Use parameterized queries or an ORM to prevent SQL injection.",
                    ))

        return findings

    def _check_rate_limiting(
        self, endpoint_id: str, method: str, path: str,
        file_path: str, line_start: int
    ) -> list[Finding]:
        """Check if mutation endpoints have rate limiting."""
        findings: list[Finding] = []

        if method not in ("POST", "PUT", "DELETE", "PATCH"):
            return findings

        # Check middleware for rate limiter
        neighbors = self.graph.get_neighbors(endpoint_id, edge_types=[EdgeType.SECURED_BY])
        has_rate_limit = False
        for nid in neighbors:
            n_attrs = self.graph.get_node(nid)
            if n_attrs:
                name = n_attrs.get("qualified_name", "").lower()
                if "rate" in name or "throttl" in name or "limit" in name:
                    has_rate_limit = True
                    break

        if not has_rate_limit:
            findings.append(Finding(
                severity=Severity.MEDIUM,
                title="Missing Rate Limiting",
                description=f"Mutation endpoint {method} {path} has no rate limiting.",
                file_path=file_path,
                line_number=line_start,
                recommendation="Add rate limiting middleware to prevent abuse and DoS attacks.",
            ))

        return findings

    def _check_security_headers(self) -> list[Finding]:
        """Check for security header middleware (CORS, Helmet)."""
        findings: list[Finding] = []
        all_nodes = self.graph.get_nodes_by_type(NodeType.MIDDLEWARE)
        middleware_names = {n.get("qualified_name", "").lower() for n in all_nodes}

        if not any("helmet" in m for m in middleware_names):
            findings.append(Finding(
                severity=Severity.LOW,
                title="Missing Security Headers (Helmet)",
                description="No Helmet middleware detected. Security headers help prevent XSS, clickjacking, and MIME sniffing.",
                recommendation="Add helmet middleware: app.use(helmet())",
            ))

        if not any("cors" in m for m in middleware_names):
            findings.append(Finding(
                severity=Severity.LOW,
                title="Missing CORS Configuration",
                description="No CORS middleware detected. Without CORS, the API may be vulnerable to cross-origin attacks.",
                recommendation="Add CORS middleware with appropriate origin restrictions.",
            ))

        return findings

    def _read_source(self, file_path: str, line_start: int, line_end: int) -> str:
        """Read source lines from a file."""
        abs_path = self.project_root / file_path
        if not abs_path.exists():
            return ""
        try:
            lines = abs_path.read_text(errors="replace").split("\n")
            start = max(0, line_start - 1)
            end = min(len(lines), line_end)
            return "\n".join(lines[start:end])
        except OSError:
            return ""
