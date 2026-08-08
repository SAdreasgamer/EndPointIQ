"""NetworkX-based knowledge graph for EndpointIQ.

Stores all code entities (endpoints, controllers, services, repositories,
middleware, etc.) as nodes and their relationships as edges in a directed graph.

Key features:
- Batch upsert of nodes and edges
- Provenance-based pruning (remove all nodes from a specific file)
- Endpoint registry for fast (method, path) → endpoint_id lookup
- JSON serialization for persistence
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import networkx as nx

from endpointiq.models.graph import EdgeType, GraphEdge, GraphNode, NodeType

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """In-memory knowledge graph backed by NetworkX DiGraph.

    Usage:
        graph = KnowledgeGraph()
        graph.upsert_nodes([node1, node2])
        graph.upsert_edges([edge1, edge2])
        graph.save(Path(".endpointiq/graph.json"))
    """

    def __init__(self):
        self._graph = nx.DiGraph()
        self._endpoint_registry: dict[str, str] = {}  # "GET /api/users" → node_id

    @property
    def node_count(self) -> int:
        return int(self._graph.number_of_nodes())

    @property
    def edge_count(self) -> int:
        return int(self._graph.number_of_edges())

    @property
    def graph(self) -> nx.DiGraph:
        """Access the underlying NetworkX graph."""
        return self._graph

    # ── Node Operations ───────────────────────────────

    def upsert_node(self, node: GraphNode) -> None:
        """Add or update a single node in the graph."""
        self._graph.add_node(
            node.id,
            type=node.type.value,
            qualified_name=node.qualified_name,
            file_path=node.file_path,
            line_start=node.line_start,
            line_end=node.line_end,
            provenance=node.provenance,
            metadata=node.metadata,
        )
        # Update endpoint registry if this is an endpoint node
        if node.type == NodeType.ENDPOINT:
            self._endpoint_registry[node.qualified_name] = node.id

    def upsert_nodes(self, nodes: list[GraphNode]) -> None:
        """Batch add or update nodes."""
        for node in nodes:
            self.upsert_node(node)

    def get_node(self, node_id: str) -> dict | None:
        """Get node attributes by ID."""
        if node_id in self._graph:
            return dict(self._graph.nodes[node_id])
        return None

    def get_nodes_by_type(self, node_type: NodeType) -> list[dict]:
        """Get all nodes of a specific type."""
        results = []
        for node_id, attrs in self._graph.nodes(data=True):
            if attrs.get("type") == node_type.value:
                results.append({"id": node_id, **attrs})
        return results

    # ── Edge Operations ───────────────────────────────

    def upsert_edge(self, edge: GraphEdge) -> None:
        """Add or update a single edge in the graph."""
        self._graph.add_edge(
            edge.source,
            edge.target,
            type=edge.type.value,
            weight=edge.weight,
            provenance=edge.provenance,
            metadata=edge.metadata,
        )

    def upsert_edges(self, edges: list[GraphEdge]) -> None:
        """Batch add or update edges."""
        for edge in edges:
            self.upsert_edge(edge)

    def upsert_subgraph(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        """Batch add/update both nodes and edges atomically."""
        self.upsert_nodes(nodes)
        self.upsert_edges(edges)
        logger.debug(f"Upserted {len(nodes)} nodes, {len(edges)} edges")

    # ── Pruning ───────────────────────────────────────

    def prune_by_provenance(self, file_path: str) -> int:
        """Remove all nodes and edges originating from a specific file.

        Used for incremental updates: when a file changes, prune its old
        nodes before re-extracting and inserting updated ones.

        Returns the number of nodes removed.
        """
        nodes_to_remove = [
            node_id
            for node_id, attrs in self._graph.nodes(data=True)
            if attrs.get("provenance") == file_path
        ]

        # Also clean endpoint registry
        for node_id in nodes_to_remove:
            attrs = self._graph.nodes[node_id]
            if attrs.get("type") == NodeType.ENDPOINT.value:
                name = attrs.get("qualified_name", "")
                self._endpoint_registry.pop(name, None)

        self._graph.remove_nodes_from(nodes_to_remove)
        if nodes_to_remove:
            logger.debug(f"Pruned {len(nodes_to_remove)} nodes from {file_path}")
        return len(nodes_to_remove)

    # ── Endpoint Registry ─────────────────────────────

    def lookup_endpoint(self, display_name: str) -> str | None:
        """Look up an endpoint node ID by display name (e.g. 'GET /api/users')."""
        return self._endpoint_registry.get(display_name)

    def list_endpoints(self) -> list[dict]:
        """List all discovered endpoints with their attributes."""
        results = []
        for name, node_id in self._endpoint_registry.items():
            attrs = self.get_node(node_id)
            if attrs:
                results.append({"id": node_id, "display_name": name, **attrs})
        return results

    # ── Traversal ─────────────────────────────────────

    def get_neighbors(
        self, node_id: str, edge_types: list[EdgeType] | None = None, depth: int = 1
    ) -> list[str]:
        """Get neighboring node IDs, optionally filtered by edge type."""
        if node_id not in self._graph:
            return []

        if depth == 1:
            neighbors = []
            for _, target, attrs in self._graph.out_edges(node_id, data=True):
                if edge_types is None or EdgeType(attrs.get("type", "")) in edge_types:
                    neighbors.append(target)
            return neighbors

        # BFS for multi-hop traversal
        visited: set[str] = set()
        current_layer = {node_id}
        for _ in range(depth):
            next_layer: set[str] = set()
            for nid in current_layer:
                for _, target, attrs in self._graph.out_edges(nid, data=True):
                    if target not in visited and target != node_id and (
                        edge_types is None or EdgeType(attrs.get("type", "")) in edge_types
                    ):
                        next_layer.add(target)
            visited.update(next_layer)
            current_layer = next_layer
        return list(visited)

    def get_subgraph(self, node_ids: list[str]) -> nx.DiGraph:
        """Extract a subgraph containing only the specified nodes."""
        return self._graph.subgraph(node_ids).copy()

    # ── Persistence ───────────────────────────────────

    def save(self, path: Path) -> None:
        """Serialize the graph to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        node_list: list[dict] = []
        edge_list: list[dict] = []
        for node_id, attrs in self._graph.nodes(data=True):
            node_list.append({"id": node_id, **attrs})
        for source, target, attrs in self._graph.edges(data=True):
            edge_list.append({"source": source, "target": target, **attrs})
        data = {
            "nodes": node_list,
            "edges": edge_list,
            "endpoint_registry": self._endpoint_registry,
        }

        path.write_text(json.dumps(data, indent=2, default=str))
        logger.info(
            f"Graph saved: {self.node_count} nodes, {self.edge_count} edges → {path}"
        )

    def load(self, path: Path) -> bool:
        """Load the graph from a JSON file.

        Returns True if loaded successfully, False otherwise.
        """
        if not path.exists():
            logger.debug(f"No graph file at {path}")
            return False

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load graph: {e}")
            return False

        self._graph.clear()
        self._endpoint_registry.clear()

        for node_data in data.get("nodes", []):
            node_id = node_data.pop("id")
            self._graph.add_node(node_id, **node_data)

        for edge_data in data.get("edges", []):
            source = edge_data.pop("source")
            target = edge_data.pop("target")
            self._graph.add_edge(source, target, **edge_data)

        self._endpoint_registry = data.get("endpoint_registry", {})
        logger.info(
            f"Graph loaded: {self.node_count} nodes, {self.edge_count} edges ← {path}"
        )
        return True

    def clear(self) -> None:
        """Clear the entire graph."""
        self._graph.clear()
        self._endpoint_registry.clear()
