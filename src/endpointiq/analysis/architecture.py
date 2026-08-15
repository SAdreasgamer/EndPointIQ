"""Architecture analysis engine.

Detects architectural issues using NetworkX graph analysis:
- Layer violations (controller directly calling repository)
- Circular dependencies (networkx.simple_cycles)
- High coupling (nodes with >10 outbound edges)
- God classes (classes with >15 methods or >500 lines)
"""

from __future__ import annotations

import logging
from pathlib import Path

import networkx as nx

from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.models.analysis import Finding, Severity
from endpointiq.models.graph import EdgeType, NodeType

logger = logging.getLogger(__name__)

# Layer hierarchy: lower index = higher layer (closer to HTTP)
LAYER_ORDER = {
    NodeType.ENDPOINT: 0,
    NodeType.MIDDLEWARE: 1,
    NodeType.CONTROLLER: 2,
    NodeType.SERVICE: 3,
    NodeType.REPOSITORY: 4,
    NodeType.ENTITY: 5,
}


class ArchitectureEngine:
    """Static architecture analysis engine.

    Uses NetworkX graph algorithms to detect structural issues.

    Usage:
        engine = ArchitectureEngine(knowledge_graph, project_root)
        findings = engine.analyze()
    """

    def __init__(self, graph: KnowledgeGraph, project_root: Path):
        self.graph = graph
        self.project_root = project_root

    def analyze(self) -> list[Finding]:
        """Run all architecture checks on the entire project."""
        findings: list[Finding] = []

        findings.extend(self._check_layer_violations())
        findings.extend(self._check_circular_dependencies())
        findings.extend(self._check_high_coupling())
        findings.extend(self._check_god_classes())

        findings.sort(key=lambda f: f.severity_rank)
        return findings

    def analyze_endpoint(self, endpoint_name: str) -> list[Finding]:
        """Run architecture checks scoped to a specific endpoint's subgraph."""
        findings: list[Finding] = []

        endpoint_id = self.graph.lookup_endpoint(endpoint_name)
        if not endpoint_id:
            return findings

        # Get the endpoint's reachable subgraph
        reachable = self.graph.get_neighbors(endpoint_id, depth=5)
        reachable_set = set(reachable) | {endpoint_id}

        findings.extend(self._check_layer_violations(scope=reachable_set))
        findings.extend(self._check_high_coupling(scope=reachable_set))

        findings.sort(key=lambda f: f.severity_rank)
        return findings

    def _check_layer_violations(self, scope: set[str] | None = None) -> list[Finding]:
        """Detect layer violations: higher layers calling lower layers directly.

        E.g., a Controller directly calling a Repository (skipping Service layer).
        """
        findings: list[Finding] = []
        nx_graph = self.graph.graph

        for source, target, attrs in nx_graph.edges(data=True):
            edge_type = attrs.get("type", "")
            if edge_type != EdgeType.CALLS.value:
                continue

            if scope and source not in scope:
                continue

            src_attrs = nx_graph.nodes.get(source, {})
            tgt_attrs = nx_graph.nodes.get(target, {})

            src_type_str = src_attrs.get("type", "")
            tgt_type_str = tgt_attrs.get("type", "")

            try:
                src_type = NodeType(src_type_str)
                tgt_type = NodeType(tgt_type_str)
            except ValueError:
                continue

            src_layer = LAYER_ORDER.get(src_type)
            tgt_layer = LAYER_ORDER.get(tgt_type)

            if src_layer is None or tgt_layer is None:
                continue

            # Violation: skipping a layer (e.g., controller→repository, gap > 1)
            if tgt_layer - src_layer > 1:
                findings.append(Finding(
                    severity=Severity.HIGH,
                    title="Layer Violation Detected",
                    description=(
                        f"{src_type.value.title()} '{src_attrs.get('qualified_name', '')}' "
                        f"directly calls {tgt_type.value.title()} "
                        f"'{tgt_attrs.get('qualified_name', '')}', "
                        f"skipping the intermediate layer. "
                        f"This violates the layered architecture pattern."
                    ),
                    file_path=src_attrs.get("file_path", ""),
                    line_number=src_attrs.get("line_start", 0),
                    recommendation=(
                        f"Add a {NodeType.SERVICE.value.title()} layer between "
                        f"{src_type.value.title()} and {tgt_type.value.title()}."
                    ),
                ))

        return findings

    def _check_circular_dependencies(self) -> list[Finding]:
        """Detect circular dependencies using NetworkX cycle detection.

        Only checks FILE-level DEPENDS_ON edges to find circular imports.
        """
        findings: list[Finding] = []
        nx_graph = self.graph.graph

        # Build a subgraph of only DEPENDS_ON edges between FILE nodes
        dep_graph = nx.DiGraph()
        for source, target, attrs in nx_graph.edges(data=True):
            if attrs.get("type") != EdgeType.DEPENDS_ON.value:
                continue
            src_attrs = nx_graph.nodes.get(source, {})
            tgt_attrs = nx_graph.nodes.get(target, {})
            if (src_attrs.get("type") == NodeType.FILE.value and
                    tgt_attrs.get("type") == NodeType.FILE.value):
                src_name = src_attrs.get("qualified_name", source)
                tgt_name = tgt_attrs.get("qualified_name", target)
                dep_graph.add_edge(src_name, tgt_name)

        # Find cycles
        try:
            cycles = list(nx.simple_cycles(dep_graph))
        except nx.NetworkXError:
            return findings

        for cycle in cycles[:5]:  # Limit to 5 cycles to avoid noise
            cycle_str = " → ".join(cycle) + " → " + cycle[0]
            findings.append(Finding(
                severity=Severity.MEDIUM,
                title="Circular Dependency Detected",
                description=(
                    f"Circular import dependency found: {cycle_str}. "
                    "Circular dependencies make the code harder to maintain, "
                    "test, and can cause runtime import errors."
                ),
                file_path=cycle[0] if cycle else "",
                line_number=0,
                recommendation=(
                    "Break the cycle by extracting shared types/interfaces into "
                    "a separate module, or use dependency injection."
                ),
            ))

        return findings

    def _check_high_coupling(self, scope: set[str] | None = None) -> list[Finding]:
        """Detect highly coupled nodes (>10 outbound edges)."""
        findings: list[Finding] = []
        nx_graph = self.graph.graph
        coupling_threshold = 10

        for node_id, attrs in nx_graph.nodes(data=True):
            if scope and node_id not in scope:
                continue

            node_type = attrs.get("type", "")
            if node_type == NodeType.FILE.value:
                continue  # Skip file nodes

            out_degree = nx_graph.out_degree(node_id)
            if out_degree > coupling_threshold:
                findings.append(Finding(
                    severity=Severity.MEDIUM,
                    title="High Coupling Detected",
                    description=(
                        f"{node_type.title()} '{attrs.get('qualified_name', '')}' "
                        f"has {out_degree} outbound dependencies (threshold: {coupling_threshold}). "
                        "High coupling makes the module hard to change and test independently."
                    ),
                    file_path=attrs.get("file_path", ""),
                    line_number=attrs.get("line_start", 0),
                    recommendation=(
                        "Consider splitting this module into smaller, focused units "
                        "or using the Facade pattern to reduce coupling."
                    ),
                ))

        return findings

    def _check_god_classes(self) -> list[Finding]:
        """Detect god classes (>15 methods or >500 lines)."""
        findings: list[Finding] = []
        nx_graph = self.graph.graph

        method_threshold = 15
        line_threshold = 500

        # Count methods per class
        class_methods: dict[str, int] = {}
        class_attrs: dict[str, dict] = {}

        for node_id, attrs in nx_graph.nodes(data=True):
            node_type = attrs.get("type", "")
            meta = attrs.get("metadata", {})
            kind = meta.get("kind", "") if isinstance(meta, dict) else ""

            if node_type in (NodeType.CONTROLLER.value, NodeType.SERVICE.value,
                             NodeType.REPOSITORY.value, NodeType.CLASS.value):
                class_attrs[node_id] = dict(attrs)
                line_start = attrs.get("line_start", 0)
                line_end = attrs.get("line_end", 0)
                line_count = line_end - line_start if line_end > line_start else 0

                if line_count > line_threshold:
                    findings.append(Finding(
                        severity=Severity.LOW,
                        title="God Class: Excessive Size",
                        description=(
                            f"Class '{attrs.get('qualified_name', '')}' has {line_count} lines "
                            f"(threshold: {line_threshold}). Large classes are hard to understand and maintain."
                        ),
                        file_path=attrs.get("file_path", ""),
                        line_number=line_start,
                        recommendation="Split into smaller classes with single responsibilities.",
                    ))

            if kind == "method":
                # Find parent class by looking at qualified name
                qname = attrs.get("qualified_name", "")
                class_name = qname.rsplit(".", 1)[0] if "." in qname else ""
                if class_name:
                    class_methods[class_name] = class_methods.get(class_name, 0) + 1

        for class_name, method_count in class_methods.items():
            if method_count > method_threshold:
                findings.append(Finding(
                    severity=Severity.LOW,
                    title="God Class: Too Many Methods",
                    description=(
                        f"Class '{class_name}' has {method_count} methods "
                        f"(threshold: {method_threshold}). This suggests the class has too many responsibilities."
                    ),
                    recommendation="Apply the Single Responsibility Principle and extract helper classes.",
                ))

        return findings
