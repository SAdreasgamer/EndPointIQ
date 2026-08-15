"""Day 6 tests — CLI commands and FastAPI server.

Tests CLI via Typer's CliRunner and FastAPI via httpx.AsyncClient.
"""

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from typer.testing import CliRunner

from endpointiq.cli.app import app as cli_app
from endpointiq.cli.server import app as api_app

runner = CliRunner()


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def express_project(tmp_path: Path) -> Path:
    """Minimal Express project fixture."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test-api",
        "dependencies": {"express": "^4.18.2", "cors": "^2.8.5"},
        "devDependencies": {"typescript": "^5.0.0"},
    }))

    src = tmp_path / "src"
    src.mkdir()

    (src / "app.ts").write_text("""
import express from 'express';
import cors from 'cors';
const app = express();
app.use(cors());
app.use(express.json());
app.get('/health', (req, res) => { res.json({ status: 'ok' }); });
app.get('/api/users', (req, res) => { res.json([]); });
app.post('/api/users', (req, res) => { res.json(req.body); });
export default app;
""")

    return tmp_path


@pytest.fixture
def api_client():
    """Create an httpx async client for the FastAPI app."""
    transport = ASGITransport(app=api_app)
    return AsyncClient(transport=transport, base_url="http://test")


# ── Tests: CLI Version ────────────────────────────────


def test_cli_version():
    """eiq version should print the version."""
    result = runner.invoke(cli_app, ["version"])
    assert result.exit_code == 0
    assert "EndpointIQ" in result.output


def test_cli_help():
    """eiq --help should show all commands."""
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "endpoints" in result.output
    assert "security" in result.output
    assert "analyze" in result.output


# ── Tests: CLI Init ───────────────────────────────────


def test_cli_init(express_project: Path):
    """eiq init should index the project and print summary."""
    result = runner.invoke(cli_app, ["init", str(express_project)])
    assert result.exit_code == 0
    assert "initialized" in result.output.lower() or "✓" in result.output
    assert (express_project / ".endpointiq").exists()
    assert (express_project / ".endpointiq" / "graph.json").exists()


def test_cli_init_nonexistent():
    """eiq init on non-existent dir should fail gracefully."""
    result = runner.invoke(cli_app, ["init", "/nonexistent/path"])
    # Should error but not crash
    assert result.exit_code != 0 or "error" in result.output.lower() or "not" in result.output.lower()


# ── Tests: CLI Endpoints ──────────────────────────────


def test_cli_endpoints(express_project: Path):
    """eiq endpoints should list discovered endpoints."""
    # Init first
    runner.invoke(cli_app, ["init", str(express_project)])

    result = runner.invoke(cli_app, ["endpoints", str(express_project)])
    assert result.exit_code == 0


def test_cli_endpoints_json(express_project: Path):
    """eiq endpoints --format json should output JSON."""
    runner.invoke(cli_app, ["init", str(express_project)])

    result = runner.invoke(cli_app, ["endpoints", str(express_project), "--format", "json"])
    assert result.exit_code == 0


# ── Tests: CLI Security ──────────────────────────────


def test_cli_security(express_project: Path):
    """eiq security should run security analysis."""
    runner.invoke(cli_app, ["init", str(express_project)])

    result = runner.invoke(cli_app, [
        "security", "GET /health",
        "--project-dir", str(express_project),
    ])
    assert result.exit_code == 0


def test_cli_security_json(express_project: Path):
    """eiq security --format json should output JSON."""
    runner.invoke(cli_app, ["init", str(express_project)])

    result = runner.invoke(cli_app, [
        "security", "POST /api/users",
        "--project-dir", str(express_project),
        "--format", "json",
    ])
    assert result.exit_code == 0


# ── Tests: CLI Performance ───────────────────────────


def test_cli_performance(express_project: Path):
    """eiq performance should run performance analysis."""
    runner.invoke(cli_app, ["init", str(express_project)])

    result = runner.invoke(cli_app, [
        "performance", "GET /api/users",
        "--project-dir", str(express_project),
    ])
    assert result.exit_code == 0


# ── Tests: CLI Analyze ───────────────────────────────


def test_cli_analyze(express_project: Path):
    """eiq analyze should run full analysis."""
    runner.invoke(cli_app, ["init", str(express_project)])

    result = runner.invoke(cli_app, [
        "analyze", "GET /health",
        "--project-dir", str(express_project),
    ])
    assert result.exit_code == 0


# ── Tests: CLI Graph ─────────────────────────────────


def test_cli_graph(express_project: Path):
    """eiq graph should show dependency tree."""
    runner.invoke(cli_app, ["init", str(express_project)])

    result = runner.invoke(cli_app, [
        "graph", "GET /health",
        "--project-dir", str(express_project),
    ])
    assert result.exit_code == 0


def test_cli_graph_not_found(express_project: Path):
    """eiq graph with invalid endpoint should fail."""
    runner.invoke(cli_app, ["init", str(express_project)])

    result = runner.invoke(cli_app, [
        "graph", "GET /nonexistent",
        "--project-dir", str(express_project),
    ])
    assert result.exit_code != 0


# ── Tests: FastAPI Health ─────────────────────────────


@pytest.mark.asyncio
async def test_api_health(api_client: AsyncClient):
    """GET /api/health should return ok."""
    async with api_client as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


# ── Tests: FastAPI Projects ───────────────────────────


@pytest.mark.asyncio
async def test_api_create_project(api_client: AsyncClient, express_project: Path):
    """POST /api/projects should register and index a project."""
    async with api_client as client:
        resp = await client.post("/api/projects", json={
            "path": str(express_project),
            "name": "test-api",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["name"] == "test-api"
    assert data["endpoints_count"] >= 1


@pytest.mark.asyncio
async def test_api_create_project_invalid_path(api_client: AsyncClient):
    """POST /api/projects with bad path should return 400."""
    async with api_client as client:
        resp = await client.post("/api/projects", json={
            "path": "/nonexistent/path",
        })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_api_get_project(api_client: AsyncClient, express_project: Path):
    """GET /api/projects/{id} should return project info."""
    async with api_client as client:
        create_resp = await client.post("/api/projects", json={
            "path": str(express_project),
        })
        project_id = create_resp.json()["id"]

        resp = await client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_api_get_project_not_found(api_client: AsyncClient):
    """GET /api/projects/{id} for unknown ID should return 404."""
    async with api_client as client:
        resp = await client.get("/api/projects/nonexistent")
    assert resp.status_code == 404


# ── Tests: FastAPI Endpoints ──────────────────────────


@pytest.mark.asyncio
async def test_api_list_endpoints(api_client: AsyncClient, express_project: Path):
    """GET /api/endpoints should list endpoints for a project."""
    async with api_client as client:
        create_resp = await client.post("/api/projects", json={
            "path": str(express_project),
        })
        project_id = create_resp.json()["id"]

        resp = await client.get(f"/api/endpoints?project_id={project_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


# ── Tests: FastAPI Analysis ───────────────────────────


@pytest.mark.asyncio
async def test_api_run_analysis(api_client: AsyncClient, express_project: Path):
    """POST /api/analysis should run analysis and return report."""
    async with api_client as client:
        create_resp = await client.post("/api/projects", json={
            "path": str(express_project),
        })
        project_id = create_resp.json()["id"]

        resp = await client.post("/api/analysis", json={
            "project_id": project_id,
            "endpoint": "GET /health",
            "goal_type": "security",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["endpoint"] == "GET /health"
    assert data["findings_count"] >= 0
    assert "id" in data


@pytest.mark.asyncio
async def test_api_get_report(api_client: AsyncClient, express_project: Path):
    """GET /api/analysis/{id} should retrieve a stored report."""
    async with api_client as client:
        create_resp = await client.post("/api/projects", json={
            "path": str(express_project),
        })
        project_id = create_resp.json()["id"]

        analysis_resp = await client.post("/api/analysis", json={
            "project_id": project_id,
            "endpoint": "GET /health",
            "goal_type": "full",
        })
        report_id = analysis_resp.json()["id"]

        resp = await client.get(f"/api/analysis/{report_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == report_id


@pytest.mark.asyncio
async def test_api_full_flow(api_client: AsyncClient, express_project: Path):
    """Full API flow: create project → list endpoints → analyze → get report."""
    async with api_client as client:
        # 1. Register project
        create_resp = await client.post("/api/projects", json={
            "path": str(express_project),
        })
        assert create_resp.status_code == 200
        project_id = create_resp.json()["id"]

        # 2. Get project status
        proj_resp = await client.get(f"/api/projects/{project_id}")
        assert proj_resp.json()["status"] == "ready"

        # 3. List endpoints
        ep_resp = await client.get(f"/api/endpoints?project_id={project_id}")
        endpoints = ep_resp.json()
        assert len(endpoints) >= 1

        # 4. Analyze first endpoint
        ep_name = endpoints[0]["name"]
        analysis_resp = await client.post("/api/analysis", json={
            "project_id": project_id,
            "endpoint": ep_name,
            "goal_type": "security",
        })
        assert analysis_resp.status_code == 200
        report = analysis_resp.json()
        assert report["status"] == "completed"

        # 5. Retrieve report
        get_resp = await client.get(f"/api/analysis/{report['id']}")
        assert get_resp.status_code == 200
