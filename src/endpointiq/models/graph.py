"""Knowledge graph node and edge models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class NodeType(StrEnum):
    """Types of nodes in the knowledge graph."""

    ENDPOINT = "endpoint"
    CONTROLLER = "controller"
    SERVICE = "service"
    REPOSITORY = "repository"
    ENTITY = "entity"
    DTO = "dto"
    CONFIG = "config"
    SECURITY_RULE = "security_rule"
    DATABASE_TABLE = "database_table"
    CACHE = "cache"
    KAFKA_TOPIC = "kafka_topic"
    EXTERNAL_API = "external_api"
    TEST = "test"
    MIDDLEWARE = "middleware"
    VALIDATOR = "validator"
    ERROR_HANDLER = "error_handler"
    MODULE = "module"
    FUNCTION = "function"
    CLASS = "class"
    FILE = "file"


class EdgeType(StrEnum):
    """Types of relationships between nodes in the knowledge graph."""

    CALLS = "calls"
    DEPENDS_ON = "depends_on"
    QUERIES = "queries"
    PUBLISHES = "publishes"
    SUBSCRIBES = "subscribes"
    SECURED_BY = "secured_by"
    VALIDATES = "validates"
    USES = "uses"
    TESTED_BY = "tested_by"
    CONFIGURED_BY = "configured_by"
    CACHED_BY = "cached_by"
    MAPS_TO = "maps_to"
    ACCEPTS = "accepts"
    RETURNS = "returns"
    BELONGS_TO = "belongs_to"
    IMPORTS = "imports"
    EXPORTS = "exports"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"


@dataclass
class GraphNode:
    """A node in the knowledge graph representing a code entity.

    Every class, function, endpoint, middleware, config, etc. becomes a node.
    """

    id: str  # deterministic hash
    type: NodeType
    qualified_name: str  # e.g. "UserController.create"
    file_path: str
    line_start: int
    line_end: int
    metadata: dict = field(default_factory=dict)
    provenance: str = ""  # which file created this node (for incremental pruning)

    @property
    def display_name(self) -> str:
        """Short display name, e.g. 'UserController' from 'src/controllers/UserController'."""
        return self.qualified_name.split(".")[-1] if "." in self.qualified_name else self.qualified_name


@dataclass
class GraphEdge:
    """An edge (relationship) between two nodes in the knowledge graph.

    Edges have types and weights — different analysis goals
    traverse different edge types with different weights.
    """

    source: str  # source node ID
    target: str  # target node ID
    type: EdgeType
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)
    provenance: str = ""  # which file created this edge
