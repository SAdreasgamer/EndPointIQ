"""Performance analysis engine.

Detects performance issues in API endpoints:
- N+1 Query patterns (loop containing DB calls)
- Missing caching on GET endpoints
- Large payloads without pagination
- Inefficient query patterns (SELECT *, missing WHERE)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.models.analysis import Finding, Severity
from endpointiq.models.graph import EdgeType, NodeType

logger = logging.getLogger(__name__)


class PerformanceEngine:
    """Static performance analysis engine.

    Usage:
        engine = PerformanceEngine(knowledge_graph, project_root)
        findings = engine.analyze_endpoint("GET /api/users")
    """

    def __init__(self, graph: KnowledgeGraph, project_root: Path):
        self.graph = graph
        self.project_root = project_root

    def analyze_endpoint(self, endpoint_name: str) -> list[Finding]:
        """Run all performance checks on a single endpoint."""
        findings: list[Finding] = []

        endpoint_id = self.graph.lookup_endpoint(endpoint_name)
        if not endpoint_id:
            return findings

        attrs = self.graph.get_node(endpoint_id) or {}
        file_path = attrs.get("file_path", "")
        line_start = attrs.get("line_start", 0)
        metadata = attrs.get("metadata", {})
        method = metadata.get("method", "GET") if isinstance(metadata, dict) else "GET"
        path = metadata.get("path", endpoint_name) if isinstance(metadata, dict) else endpoint_name

        findings.extend(self._check_n_plus_one(endpoint_id, method, path))
        findings.extend(self._check_missing_cache(endpoint_id, method, path, file_path, line_start))
        findings.extend(self._check_pagination(endpoint_id, method, path, file_path, line_start))
        findings.extend(self._check_query_patterns(endpoint_id))

        findings.sort(key=lambda f: f.severity_rank)
        return findings

    def analyze_all_endpoints(self) -> dict[str, list[Finding]]:
        """Run performance checks on all discovered endpoints."""
        results: dict[str, list[Finding]] = {}
        for ep in self.graph.list_endpoints():
            name = ep.get("display_name", "")
            if name:
                results[name] = self.analyze_endpoint(name)
        return results

    def _check_n_plus_one(
        self, endpoint_id: str, method: str, path: str
    ) -> list[Finding]:
        """Detect N+1 query patterns.

        Looks for patterns where a loop iterates over items and makes
        a DB call for each one (e.g., for user in users: user.posts).
        """
        findings: list[Finding] = []
        reachable = self.graph.get_neighbors(endpoint_id, depth=4)

        for nid in reachable:
            n_attrs = self.graph.get_node(nid)
            if not n_attrs:
                continue

            node_type = n_attrs.get("type", "")
            if node_type not in (NodeType.SERVICE.value, NodeType.REPOSITORY.value):
                continue

            n_file = n_attrs.get("file_path", "")
            n_line = n_attrs.get("line_start", 0)
            source = self._read_source(n_file, n_line, n_attrs.get("line_end", n_line + 30))
            if not source:
                continue

            # Pattern: for/forEach/map containing .find/.query/.get
            loop_with_query = re.search(
                r'(?:for\s*\(|\.forEach\s*\(|\.map\s*\().*?'
                r'(?:\.find|\.query|\.get|\.fetch|\.select)',
                source, re.DOTALL
            )
            if loop_with_query:
                findings.append(Finding(
                    severity=Severity.HIGH,
                    title="N+1 Query Pattern Detected",
                    description=(
                        f"Database call inside a loop detected in {n_file}. "
                        "This results in N+1 queries: 1 query to fetch the list, "
                        "then N individual queries for each item. "
                        f"Affects endpoint {method} {path}."
                    ),
                    file_path=n_file,
                    line_number=n_line,
                    recommendation=(
                        "Use batch loading (e.g., WHERE id IN (...)), eager loading, "
                        "or a DataLoader pattern to fetch related data in a single query."
                    ),
                ))

        return findings

    def _check_missing_cache(
        self, endpoint_id: str, method: str, path: str,
        file_path: str, line_start: int
    ) -> list[Finding]:
        """Check if GET endpoints hitting DB have caching."""
        findings: list[Finding] = []

        if method != "GET":
            return findings

        # Check if endpoint has cache middleware
        neighbors = self.graph.get_neighbors(endpoint_id, edge_types=[EdgeType.SECURED_BY])
        has_cache = False
        for nid in neighbors:
            n_attrs = self.graph.get_node(nid)
            if n_attrs:
                name = n_attrs.get("qualified_name", "").lower()
                if "cache" in name or "redis" in name or "memo" in name:
                    has_cache = True
                    break

        # Check if endpoint reaches a repository (DB layer)
        reachable = self.graph.get_neighbors(endpoint_id, depth=4)
        hits_db = any(
            self.graph.get_node(nid) and
            self.graph.get_node(nid).get("type") == NodeType.REPOSITORY.value  # type: ignore[union-attr]
            for nid in reachable
        )

        if hits_db and not has_cache:
            findings.append(Finding(
                severity=Severity.MEDIUM,
                title="Missing Cache on DB-Backed GET Endpoint",
                description=(
                    f"Endpoint {method} {path} reads from the database but has no "
                    "caching middleware. Repeated identical requests will hit the DB every time."
                ),
                file_path=file_path,
                line_number=line_start,
                recommendation=(
                    "Add caching middleware (e.g., Redis, in-memory cache) for GET endpoints "
                    "with appropriate TTL and cache invalidation strategy."
                ),
            ))

        return findings

    def _check_pagination(
        self, endpoint_id: str, method: str, path: str,
        file_path: str, line_start: int
    ) -> list[Finding]:
        """Check if list endpoints have pagination."""
        findings: list[Finding] = []

        if method != "GET":
            return findings

        # List endpoints typically end with / or have no path params
        is_list_endpoint = not re.search(r'/:[\w]+', path) or path.endswith("/")

        if not is_list_endpoint:
            return findings

        # Check handler source for pagination patterns
        reachable = self.graph.get_neighbors(endpoint_id, depth=3)
        has_pagination = False

        for nid in reachable:
            n_attrs = self.graph.get_node(nid)
            if not n_attrs:
                continue
            n_file = n_attrs.get("file_path", "")
            n_line = n_attrs.get("line_start", 0)
            source = self._read_source(n_file, n_line, n_attrs.get("line_end", n_line + 20))
            if source and re.search(r'(?:limit|offset|page|skip|take|cursor)', source, re.IGNORECASE):
                has_pagination = True
                break

        if not has_pagination:
            findings.append(Finding(
                severity=Severity.MEDIUM,
                title="Missing Pagination on List Endpoint",
                description=(
                    f"Endpoint {method} {path} appears to return a collection "
                    "but has no pagination. Without limits, large datasets will "
                    "cause high memory usage and slow responses."
                ),
                file_path=file_path,
                line_number=line_start,
                recommendation="Add pagination using limit/offset or cursor-based pagination.",
            ))

        return findings

    def _check_query_patterns(self, endpoint_id: str) -> list[Finding]:
        """Check for inefficient query patterns."""
        findings: list[Finding] = []
        reachable = self.graph.get_neighbors(endpoint_id, depth=4)

        for nid in reachable:
            n_attrs = self.graph.get_node(nid)
            if not n_attrs:
                continue

            if n_attrs.get("type") != NodeType.REPOSITORY.value:
                continue

            n_file = n_attrs.get("file_path", "")
            n_line = n_attrs.get("line_start", 0)
            source = self._read_source(n_file, n_line, n_attrs.get("line_end", n_line + 30))
            if not source:
                continue

            # SELECT * pattern
            if re.search(r'SELECT\s+\*', source, re.IGNORECASE):
                findings.append(Finding(
                    severity=Severity.MEDIUM,
                    title="SELECT * Query Pattern",
                    description=f"SELECT * detected in {n_file}. Fetching all columns wastes bandwidth and memory.",
                    file_path=n_file,
                    line_number=n_line,
                    recommendation="Select only the columns you need to reduce payload size and improve query performance.",
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
