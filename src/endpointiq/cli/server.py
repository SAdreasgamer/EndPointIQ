"""FastAPI server for EndpointIQ.

Provides a REST API for project indexing, endpoint discovery,
and analysis — designed to be consumed by the VS Code extension
and other clients.

Endpoints:
  POST /api/projects          — Register and index a project
  GET  /api/projects/{id}     — Project status
  GET  /api/endpoints         — List all discovered endpoints
  POST /api/analysis          — Start an analysis (returns report)
  GET  /api/analysis/{id}     — Get a stored report
  GET  /api/graph/{endpoint}  — Endpoint subgraph as JSON
  GET  /api/health            — Health check
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────

app = FastAPI(
    title="EndpointIQ API",
    description="AI-powered API analysis and intelligence platform",
    version="0.1.0",
)

# In-memory stores (for MVP — SQLite persistence in Day 7)
_projects: dict[str, dict[str, Any]] = {}
_reports: dict[str, dict[str, Any]] = {}
_graphs: dict[str, Any] = {}  # project_id → KnowledgeGraph
_indexers: dict[str, Any] = {}  # project_id → ProjectIndexer


# ── Request/Response Models ───────────────────────────


class ProjectCreate(BaseModel):
    """Request to register a project for indexing."""

    path: str = Field(description="Absolute path to the project directory")
    name: str = Field(default="", description="Optional project name")


class ProjectResponse(BaseModel):
    """Project status response."""

    id: str
    name: str
    path: str
    status: str
    framework: str = ""
    endpoints_count: int = 0
    nodes_count: int = 0
    edges_count: int = 0


class AnalysisRequest(BaseModel):
    """Request to start an analysis."""

    project_id: str = Field(description="Project ID")
    endpoint: str = Field(description="Endpoint to analyze, e.g. 'POST /api/users'")
    goal_type: str = Field(default="full", description="Analysis type: security, performance, architecture, full")


class AnalysisResponse(BaseModel):
    """Analysis report response."""

    id: str
    endpoint: str
    goal_type: str
    status: str
    findings: list[dict[str, Any]] = []
    summary: str = ""
    findings_count: int = 0
    duration_ms: int = 0


class EndpointItem(BaseModel):
    """Single endpoint in the list response."""

    name: str
    type: str = ""
    file_path: str = ""


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    projects_count: int
    reports_count: int


# ── Routes ────────────────────────────────────────────


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check — reports system status."""
    from endpointiq import __version__

    return HealthResponse(
        status="ok",
        version=__version__,
        projects_count=len(_projects),
        reports_count=len(_reports),
    )


@app.post("/api/projects", response_model=ProjectResponse)
async def create_project(req: ProjectCreate):
    """Register a project and run initial indexing."""
    project_path = Path(req.path).resolve()
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {req.path}")

    project_id = str(uuid.uuid4())[:8]
    name = req.name or project_path.name

    # Index the project
    from endpointiq.core.config import load_config
    from endpointiq.knowledge.graph import KnowledgeGraph
    from endpointiq.observation.indexer import ProjectIndexer

    config = load_config(project_root=project_path)
    graph = KnowledgeGraph()
    indexer = ProjectIndexer(config, graph)
    stats = indexer.full_index()

    # Store
    _projects[project_id] = {
        "id": project_id,
        "name": name,
        "path": str(project_path),
        "status": "ready",
        "framework": stats.get("framework", ""),
        "stats": stats,
    }
    _graphs[project_id] = graph
    _indexers[project_id] = indexer

    return ProjectResponse(
        id=project_id,
        name=name,
        path=str(project_path),
        status="ready",
        framework=stats.get("framework", ""),
        endpoints_count=stats.get("endpoints", 0),
        nodes_count=stats.get("nodes", 0),
        edges_count=stats.get("edges", 0),
    )


@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    """Get project status."""
    if project_id not in _projects:
        raise HTTPException(status_code=404, detail="Project not found")

    proj = _projects[project_id]
    graph = _graphs.get(project_id)

    return ProjectResponse(
        id=proj["id"],
        name=proj["name"],
        path=proj["path"],
        status=proj["status"],
        framework=proj.get("framework", ""),
        endpoints_count=graph.node_count if graph else 0,
        nodes_count=graph.node_count if graph else 0,
        edges_count=graph.edge_count if graph else 0,
    )


@app.get("/api/endpoints", response_model=list[EndpointItem])
async def list_endpoints(project_id: str):
    """List all discovered endpoints for a project."""
    if project_id not in _graphs:
        raise HTTPException(status_code=404, detail="Project not found")

    graph = _graphs[project_id]
    ep_list = graph.list_endpoints()

    return [
        EndpointItem(
            name=ep.get("display_name", ""),
            type=ep.get("type", ""),
            file_path=ep.get("file_path", ""),
        )
        for ep in ep_list
    ]


@app.post("/api/analysis", response_model=AnalysisResponse)
async def run_analysis(req: AnalysisRequest):
    """Run analysis on an endpoint."""
    if req.project_id not in _graphs:
        raise HTTPException(status_code=404, detail="Project not found")

    graph = _graphs[req.project_id]
    proj = _projects[req.project_id]
    project_root = Path(proj["path"])

    start = time.monotonic()
    report_id = str(uuid.uuid4())[:8]

    all_findings: list[dict[str, Any]] = []

    # Run requested engines
    if req.goal_type in ("security", "full"):
        from endpointiq.analysis.security import SecurityEngine
        sec_engine = SecurityEngine(graph, project_root)
        sec_findings = sec_engine.analyze_endpoint(req.endpoint)
        for f in sec_findings:
            all_findings.append({**f.model_dump(), "engine": "security"})

    if req.goal_type in ("performance", "full"):
        from endpointiq.analysis.performance import PerformanceEngine
        perf_engine = PerformanceEngine(graph, project_root)
        perf_findings = perf_engine.analyze_endpoint(req.endpoint)
        for f in perf_findings:
            all_findings.append({**f.model_dump(), "engine": "performance"})

    if req.goal_type in ("architecture", "full"):
        from endpointiq.analysis.architecture import ArchitectureEngine
        arch_engine = ArchitectureEngine(graph, project_root)
        arch_findings = arch_engine.analyze_endpoint(req.endpoint)
        for f in arch_findings:
            all_findings.append({**f.model_dump(), "engine": "architecture"})

    duration_ms = int((time.monotonic() - start) * 1000)

    # Build summary
    severity_counts: dict[str, int] = {}
    for finding_dict in all_findings:
        sev = finding_dict.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    summary = (
        f"{req.goal_type.title()} analysis of {req.endpoint}: "
        f"{len(all_findings)} findings "
        f"({', '.join(f'{c} {s.upper()}' for s, c in severity_counts.items())})"
    )

    response = AnalysisResponse(
        id=report_id,
        endpoint=req.endpoint,
        goal_type=req.goal_type,
        status="completed",
        findings=all_findings,
        summary=summary,
        findings_count=len(all_findings),
        duration_ms=duration_ms,
    )

    # Store report
    _reports[report_id] = response.model_dump()

    return response


@app.get("/api/analysis/{report_id}", response_model=AnalysisResponse)
async def get_report(report_id: str):
    """Get a stored analysis report."""
    if report_id not in _reports:
        raise HTTPException(status_code=404, detail="Report not found")

    return AnalysisResponse(**_reports[report_id])


@app.get("/api/graph/{endpoint}")
async def get_endpoint_graph(endpoint: str, project_id: str, depth: int = 3):
    """Get the subgraph for an endpoint as JSON."""
    if project_id not in _graphs:
        raise HTTPException(status_code=404, detail="Project not found")

    graph = _graphs[project_id]
    endpoint_id = graph.lookup_endpoint(endpoint)
    if not endpoint_id:
        raise HTTPException(status_code=404, detail=f"Endpoint '{endpoint}' not found")

    # Build subgraph
    neighbors = graph.get_neighbors(endpoint_id, depth=depth)
    all_ids = [endpoint_id, *neighbors]

    nodes = []
    for nid in all_ids:
        attrs = graph.get_node(nid)
        if attrs:
            nodes.append({"id": nid, **attrs})

    edges = []
    nx_graph = graph.graph
    for source in all_ids:
        for _, target, attrs in nx_graph.out_edges(source, data=True):
            if target in all_ids:
                edges.append({"source": source, "target": target, **attrs})

    return {
        "endpoint": endpoint,
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
