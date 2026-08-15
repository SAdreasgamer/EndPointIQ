"""Minimal Relevant Context (MRC) extractor.

The core innovation of EndpointIQ: given an endpoint and an analysis goal,
extracts only the minimal set of relevant source code from the knowledge graph
using Personalized PageRank + goal-specific edge filtering + budget-constrained
greedy selection.

Pipeline:
1. BFS subgraph extraction from endpoint node (filtered by goal type)
2. Personalized PageRank for relevance scoring
3. Goal-specific node boosting
4. Budget-constrained greedy selection
5. Source code extraction for selected nodes
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import networkx as nx

from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.models.graph import EdgeType, NodeType

logger = logging.getLogger(__name__)


class GoalType(StrEnum):
    """Analysis goal types that determine which graph paths to follow."""

    SECURITY = "security"
    PERFORMANCE = "performance"
    ARCHITECTURE = "architecture"
    FULL = "full"


# Edge types relevant to each goal
GOAL_EDGE_FILTER: dict[GoalType, set[EdgeType]] = {
    GoalType.SECURITY: {
        EdgeType.SECURED_BY, EdgeType.VALIDATES, EdgeType.CALLS,
        EdgeType.CONFIGURED_BY, EdgeType.DEPENDS_ON, EdgeType.BELONGS_TO,
    },
    GoalType.PERFORMANCE: {
        EdgeType.QUERIES, EdgeType.CACHED_BY, EdgeType.CALLS,
        EdgeType.USES, EdgeType.DEPENDS_ON, EdgeType.BELONGS_TO,
    },
    GoalType.ARCHITECTURE: {
        EdgeType.CALLS, EdgeType.DEPENDS_ON, EdgeType.BELONGS_TO,
        EdgeType.IMPLEMENTS, EdgeType.USES,
    },
    GoalType.FULL: set(EdgeType),  # All edge types
}

# Node type boost multipliers per goal (higher = more relevant)
GOAL_NODE_BOOST: dict[GoalType, dict[NodeType, float]] = {
    GoalType.SECURITY: {
        NodeType.MIDDLEWARE: 2.5,
        NodeType.VALIDATOR: 2.5,
        NodeType.CONFIG: 2.0,
        NodeType.CONTROLLER: 1.5,
        NodeType.ENDPOINT: 3.0,
    },
    GoalType.PERFORMANCE: {
        NodeType.REPOSITORY: 3.0,
        NodeType.ENTITY: 2.5,
        NodeType.SERVICE: 2.0,
        NodeType.CONTROLLER: 1.5,
        NodeType.ENDPOINT: 2.0,
    },
    GoalType.ARCHITECTURE: {
        NodeType.CONTROLLER: 2.0,
        NodeType.SERVICE: 2.0,
        NodeType.REPOSITORY: 2.0,
        NodeType.MODULE: 1.5,
        NodeType.ENDPOINT: 2.0,
    },
    GoalType.FULL: {
        NodeType.ENDPOINT: 2.0,
        NodeType.CONTROLLER: 1.5,
        NodeType.SERVICE: 1.5,
        NodeType.REPOSITORY: 1.5,
    },
}


@dataclass
class ContextSnippet:
    """A single code snippet extracted for context."""

    node_id: str
    node_type: str
    qualified_name: str
    file_path: str
    line_start: int
    line_end: int
    source_code: str
    relevance_score: float
    token_count: int = 0


@dataclass
class MRCResult:
    """Result of MRC extraction."""

    endpoint_name: str
    goal: GoalType
    snippets: list[ContextSnippet] = field(default_factory=list)
    total_tokens: int = 0
    total_nodes_in_graph: int = 0
    nodes_selected: int = 0
    extraction_time_ms: int = 0
    metadata: dict = field(default_factory=dict)

    @property
    def compression_ratio(self) -> float:
        """How much context was reduced (higher = more reduction)."""
        if self.total_nodes_in_graph == 0:
            return 0.0
        return 1.0 - (self.nodes_selected / self.total_nodes_in_graph)

    @property
    def combined_context(self) -> str:
        """All snippets joined into a single context string."""
        parts = []
        for snippet in self.snippets:
            header = (
                f"// === {snippet.qualified_name} "
                f"({snippet.node_type}) — {snippet.file_path}"
                f":{snippet.line_start}-{snippet.line_end} ==="
            )
            parts.append(header)
            parts.append(snippet.source_code)
            parts.append("")
        return "\n".join(parts)


class MRCExtractor:
    """Minimal Relevant Context extractor.

    Given an endpoint and analysis goal, extracts only the minimal
    set of code needed for the LLM to perform analysis.

    Usage:
        extractor = MRCExtractor(knowledge_graph, project_root)
        result = extractor.extract("GET /api/users", GoalType.SECURITY, token_budget=4000)
    """

    def __init__(
        self,
        graph: KnowledgeGraph,
        project_root: Path,
        max_depth: int = 5,
        damping_factor: float = 0.85,
    ):
        self.graph = graph
        self.project_root = project_root
        self.max_depth = max_depth
        self.damping_factor = damping_factor

    def extract(
        self,
        endpoint_name: str,
        goal: GoalType,
        token_budget: int = 4000,
    ) -> MRCResult:
        """Extract minimal relevant context for an endpoint + goal.

        Steps:
        1. Find the endpoint node in the graph
        2. BFS to extract a goal-filtered subgraph
        3. Run Personalized PageRank for relevance scoring
        4. Apply goal-specific node boosting
        5. Greedily select nodes within token budget
        6. Read source code for selected nodes

        Args:
            endpoint_name: Display name like "GET /api/users".
            goal: The analysis goal type.
            token_budget: Maximum tokens allowed in the context.

        Returns:
            MRCResult with selected code snippets.
        """
        start = time.monotonic()

        result = MRCResult(
            endpoint_name=endpoint_name,
            goal=goal,
            total_nodes_in_graph=self.graph.node_count,
        )

        # 1. Find endpoint node
        endpoint_id = self.graph.lookup_endpoint(endpoint_name)
        if not endpoint_id:
            logger.warning(f"Endpoint not found: {endpoint_name}")
            result.extraction_time_ms = int((time.monotonic() - start) * 1000)
            return result

        # 2. BFS subgraph extraction (goal-filtered)
        subgraph_ids = self._extract_subgraph(endpoint_id, goal)
        if not subgraph_ids:
            result.extraction_time_ms = int((time.monotonic() - start) * 1000)
            return result

        # 3. Personalized PageRank on subgraph
        scores = self._compute_relevance(subgraph_ids, endpoint_id)

        # 4. Apply goal-specific boosting
        boosted_scores = self._apply_boosting(scores, goal)

        # 5. Budget-constrained greedy selection
        selected = self._greedy_select(boosted_scores, token_budget)

        # 6. Build result
        result.snippets = selected
        result.nodes_selected = len(selected)
        result.total_tokens = sum(s.token_count for s in selected)
        result.extraction_time_ms = int((time.monotonic() - start) * 1000)
        result.metadata = {
            "subgraph_size": len(subgraph_ids),
            "max_depth": self.max_depth,
            "damping_factor": self.damping_factor,
        }

        logger.info(
            f"MRC extracted: {result.nodes_selected} nodes, "
            f"{result.total_tokens} tokens, "
            f"{result.compression_ratio:.1%} reduction "
            f"in {result.extraction_time_ms}ms"
        )

        return result

    def _extract_subgraph(self, endpoint_id: str, goal: GoalType) -> set[str]:
        """BFS from endpoint node, following only goal-relevant edges.

        Returns set of node IDs in the extracted subgraph.
        """
        allowed_edges = GOAL_EDGE_FILTER.get(goal, set(EdgeType))
        nx_graph = self.graph.graph

        visited: set[str] = {endpoint_id}
        current_layer = {endpoint_id}

        for _ in range(self.max_depth):
            next_layer: set[str] = set()
            for node_id in current_layer:
                # Follow outgoing edges
                for _, target, attrs in nx_graph.out_edges(node_id, data=True):
                    edge_type_str = attrs.get("type", "")
                    try:
                        edge_type = EdgeType(edge_type_str)
                    except ValueError:
                        continue
                    if edge_type in allowed_edges and target not in visited:
                        next_layer.add(target)

                # Also follow incoming edges (reverse traversal)
                for source, _, attrs in nx_graph.in_edges(node_id, data=True):
                    edge_type_str = attrs.get("type", "")
                    try:
                        edge_type = EdgeType(edge_type_str)
                    except ValueError:
                        continue
                    if edge_type in allowed_edges and source not in visited:
                        next_layer.add(source)

            visited.update(next_layer)
            current_layer = next_layer
            if not next_layer:
                break

        return visited

    def _compute_relevance(
        self, subgraph_ids: set[str], endpoint_id: str
    ) -> dict[str, float]:
        """Run Personalized PageRank on the subgraph.

        Personalization: all probability on the endpoint node.
        """
        nx_graph = self.graph.graph
        subgraph = nx_graph.subgraph(subgraph_ids)

        if len(subgraph) == 0:
            return {}

        # Personalization vector: all weight on endpoint
        personalization = {nid: 0.0 for nid in subgraph.nodes()}
        if endpoint_id in personalization:
            personalization[endpoint_id] = 1.0
        else:
            # Uniform if endpoint not in subgraph (shouldn't happen)
            for nid in personalization:
                personalization[nid] = 1.0 / len(personalization)

        try:
            scores = nx.pagerank(
                subgraph,
                alpha=self.damping_factor,
                personalization=personalization,
                max_iter=100,
                tol=1e-6,
            )
            return {str(k): float(v) for k, v in scores.items()}
        except nx.PowerIterationFailedConvergence:
            logger.warning("PageRank did not converge, using uniform scores")
            uniform = 1.0 / len(subgraph_ids)
            return {nid: uniform for nid in subgraph_ids}

    def _apply_boosting(
        self, scores: dict[str, float], goal: GoalType
    ) -> dict[str, float]:
        """Apply goal-specific boost multipliers to node scores."""
        boosts = GOAL_NODE_BOOST.get(goal, {})
        boosted = {}

        for node_id, score in scores.items():
            attrs = self.graph.get_node(node_id)
            if not attrs:
                boosted[node_id] = score
                continue

            node_type_str = attrs.get("type", "")
            try:
                node_type = NodeType(node_type_str)
                multiplier = boosts.get(node_type, 1.0)
                boosted[node_id] = score * multiplier
            except ValueError:
                boosted[node_id] = score

        return boosted

    def _greedy_select(
        self, scores: dict[str, float], token_budget: int
    ) -> list[ContextSnippet]:
        """Greedily select nodes by relevance until token budget is reached.

        For each selected node, reads the source code from disk and
        counts tokens.
        """
        from endpointiq.context.compression import count_tokens

        sorted_nodes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected: list[ContextSnippet] = []
        tokens_used = 0

        for node_id, relevance in sorted_nodes:
            attrs = self.graph.get_node(node_id)
            if not attrs:
                continue

            file_path = attrs.get("file_path", "")
            line_start = attrs.get("line_start", 1)
            line_end = attrs.get("line_end", 1)
            qualified_name = attrs.get("qualified_name", "")
            node_type = attrs.get("type", "unknown")

            # Skip FILE nodes (we extract specific symbols, not whole files)
            if node_type == NodeType.FILE.value:
                continue

            # Read source code
            source = self._read_source(file_path, line_start, line_end)
            if not source:
                continue

            token_count = count_tokens(source)

            # Check budget
            if tokens_used + token_count > token_budget:
                # If we have no snippets yet, force-include (truncated)
                if not selected:
                    remaining = token_budget - tokens_used
                    source = self._truncate_to_tokens(source, remaining)
                    token_count = count_tokens(source)
                else:
                    continue

            snippet = ContextSnippet(
                node_id=node_id,
                node_type=node_type,
                qualified_name=qualified_name,
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                source_code=source,
                relevance_score=relevance,
                token_count=token_count,
            )
            selected.append(snippet)
            tokens_used += token_count

        return selected

    def _read_source(self, file_path: str, line_start: int, line_end: int) -> str:
        """Read source code lines from a file."""
        abs_path = self.project_root / file_path
        if not abs_path.exists():
            return ""

        try:
            lines = abs_path.read_text(errors="replace").split("\n")
            # Adjust for 1-indexed lines
            start = max(0, line_start - 1)
            end = min(len(lines), line_end)
            return "\n".join(lines[start:end])
        except OSError:
            return ""

    @staticmethod
    def _truncate_to_tokens(source: str, max_tokens: int) -> str:
        """Truncate source code to fit within a token budget."""
        from endpointiq.context.compression import count_tokens

        lines = source.split("\n")
        result_lines: list[str] = []
        tokens = 0
        for line in lines:
            line_tokens = count_tokens(line)
            if tokens + line_tokens > max_tokens:
                break
            result_lines.append(line)
            tokens += line_tokens
        return "\n".join(result_lines)
