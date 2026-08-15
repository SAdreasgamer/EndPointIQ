"""LangChain tools for the EndpointIQ agent.

Each tool wraps a core capability (MRC extraction, graph queries,
endpoint info) as a LangChain-compatible tool that the LangGraph
agent can invoke during analysis.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Tool Input/Output Schemas ─────────────────────────


class ExtractContextInput(BaseModel):
    """Input for the extract_context tool."""

    endpoint_name: str = Field(description="Endpoint display name, e.g. 'GET /api/users'")
    goal_type: str = Field(description="Analysis goal: 'security', 'performance', 'architecture', or 'full'")
    token_budget: int = Field(default=4000, description="Maximum tokens for the context")


class EndpointInfoInput(BaseModel):
    """Input for the get_endpoint_info tool."""

    endpoint_name: str = Field(description="Endpoint display name, e.g. 'GET /api/users'")


class GraphQueryInput(BaseModel):
    """Input for the query_knowledge_graph tool."""

    node_id: str = Field(description="Node ID to query")
    depth: int = Field(default=2, description="Traversal depth")


# ── Tool Registry ─────────────────────────────────────

# These globals are set by the agent system before tools are invoked.
# This is the standard pattern for LangChain tools that need shared state.
_tool_context: dict[str, Any] = {}


def set_tool_context(
    graph: Any = None,
    extractor: Any = None,
    project_root: Any = None,
) -> None:
    """Set the shared context that tools use to access the knowledge graph and MRC."""
    if graph is not None:
        _tool_context["graph"] = graph
    if extractor is not None:
        _tool_context["extractor"] = extractor
    if project_root is not None:
        _tool_context["project_root"] = project_root


# ── LangChain Tools ──────────────────────────────────


@tool("extract_context", args_schema=ExtractContextInput)
def extract_context(endpoint_name: str, goal_type: str, token_budget: int = 4000) -> str:
    """Extract minimal relevant code context for an endpoint using the MRC algorithm.

    Uses Personalized PageRank on the knowledge graph to find only the
    code snippets relevant to the analysis goal, compressed to fit the token budget.
    """
    from endpointiq.context.extractor import GoalType, MRCExtractor

    extractor = _tool_context.get("extractor")
    if not extractor:
        graph = _tool_context.get("graph")
        project_root = _tool_context.get("project_root")
        if not graph or not project_root:
            return json.dumps({"error": "Tool context not initialized"})
        extractor = MRCExtractor(graph, project_root)

    try:
        goal = GoalType(goal_type)
    except ValueError:
        goal = GoalType.FULL

    result = extractor.extract(endpoint_name, goal, token_budget)

    return json.dumps({
        "endpoint": endpoint_name,
        "goal": goal_type,
        "context": result.combined_context,
        "tokens_used": result.total_tokens,
        "nodes_selected": result.nodes_selected,
        "total_nodes": result.total_nodes_in_graph,
        "compression_ratio": f"{result.compression_ratio:.1%}",
        "extraction_time_ms": result.extraction_time_ms,
    })


@tool("get_endpoint_info", args_schema=EndpointInfoInput)
def get_endpoint_info(endpoint_name: str) -> str:
    """Look up endpoint details from the knowledge graph registry.

    Returns the endpoint's method, path, handler, file location,
    middleware, and connected graph neighbors.
    """
    graph = _tool_context.get("graph")
    if not graph:
        return json.dumps({"error": "Graph not available"})

    node_id = graph.lookup_endpoint(endpoint_name)
    if not node_id:
        return json.dumps({"error": f"Endpoint '{endpoint_name}' not found"})

    attrs = graph.get_node(node_id)
    neighbors = graph.get_neighbors(node_id, depth=2)
    neighbor_details = []
    for nid in neighbors:
        n_attrs = graph.get_node(nid)
        if n_attrs:
            neighbor_details.append({
                "id": nid,
                "type": n_attrs.get("type", "unknown"),
                "name": n_attrs.get("qualified_name", ""),
                "file": n_attrs.get("file_path", ""),
            })

    return json.dumps({
        "endpoint": endpoint_name,
        "node_id": node_id,
        "attributes": attrs,
        "neighbors": neighbor_details,
    }, default=str)


@tool("query_knowledge_graph", args_schema=GraphQueryInput)
def query_knowledge_graph(node_id: str, depth: int = 2) -> str:
    """Query the knowledge graph for a node and its neighbors.

    Returns the node's attributes and all connected nodes up to
    the specified depth.
    """
    graph = _tool_context.get("graph")
    if not graph:
        return json.dumps({"error": "Graph not available"})

    attrs = graph.get_node(node_id)
    if not attrs:
        return json.dumps({"error": f"Node '{node_id}' not found"})

    neighbors = graph.get_neighbors(node_id, depth=depth)
    neighbor_details = []
    for nid in neighbors:
        n_attrs = graph.get_node(nid)
        if n_attrs:
            neighbor_details.append({
                "id": nid,
                "type": n_attrs.get("type", "unknown"),
                "name": n_attrs.get("qualified_name", ""),
            })

    return json.dumps({
        "node_id": node_id,
        "attributes": attrs,
        "neighbors": neighbor_details,
    }, default=str)


@tool("list_endpoints")
def list_endpoints() -> str:
    """List all discovered API endpoints in the indexed project."""
    graph = _tool_context.get("graph")
    if not graph:
        return json.dumps({"error": "Graph not available"})

    endpoints = graph.list_endpoints()
    return json.dumps({
        "count": len(endpoints),
        "endpoints": [
            {"name": ep.get("display_name", ""), "type": ep.get("type", "")}
            for ep in endpoints
        ],
    })


# All tools available to the agent
ALL_TOOLS = [extract_context, get_endpoint_info, query_knowledge_graph, list_endpoints]
