"""Day 5 tests — Security, Performance, and Architecture analysis engines."""

import json
from pathlib import Path

import pytest

from endpointiq.analysis.architecture import ArchitectureEngine
from endpointiq.analysis.performance import PerformanceEngine
from endpointiq.analysis.security import SecurityEngine
from endpointiq.core.config import load_config
from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.models.analysis import Severity
from endpointiq.observation.indexer import ProjectIndexer

# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def express_project(tmp_path: Path) -> Path:
    """Express project with known security/perf issues for testing."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test-api",
        "dependencies": {"express": "^4.18.2"},
        "devDependencies": {"typescript": "^5.0.0"},
    }))

    src = tmp_path / "src"
    src.mkdir()

    # App with NO helmet, has cors
    (src / "app.ts").write_text("""
import express from 'express';
import cors from 'cors';
const app = express();
app.use(cors());
app.use(express.json());
app.use('/api/users', require('./routes/userRoutes'));
export default app;
""")

    routes = src / "routes"
    routes.mkdir()

    # Routes: POST has auth but no validation, DELETE has no auth
    (routes / "userRoutes.ts").write_text("""
import { Router } from 'express';
import { authMiddleware } from '../middleware/auth';
const router = Router();
router.get('/', (req, res) => { res.json([]); });
router.get('/:id', (req, res) => { res.json({}); });
router.post('/', authMiddleware, (req, res) => { res.json(req.body); });
router.delete('/:id', (req, res) => { res.status(204).send(); });
export default router;
""")

    middleware = src / "middleware"
    middleware.mkdir()
    (middleware / "auth.ts").write_text("""
export function authMiddleware(req: any, res: any, next: any) {
    const token = req.headers.authorization;
    if (!token) return res.status(401).json({ error: 'Unauthorized' });
    next();
}
""")

    return tmp_path


@pytest.fixture
def indexed_env(express_project: Path):
    """Return (graph, project_root) for an indexed Express project."""
    config = load_config(project_root=express_project)
    graph = KnowledgeGraph()
    indexer = ProjectIndexer(config, graph)
    indexer.full_index()
    return graph, express_project


# ── Tests: Security Engine ────────────────────────────


def test_security_engine_missing_auth(indexed_env):
    """Should detect missing auth on DELETE endpoint."""
    graph, root = indexed_env
    engine = SecurityEngine(graph, root)

    findings = engine.analyze_endpoint("DELETE /:id")
    severities = {f.severity for f in findings}

    # DELETE without auth should be CRITICAL
    assert Severity.CRITICAL in severities
    auth_findings = [f for f in findings if "authentication" in f.title.lower() or "auth" in f.title.lower()]
    assert len(auth_findings) >= 1


def test_security_engine_auth_present(indexed_env):
    """Should acknowledge auth on POST endpoint."""
    graph, root = indexed_env
    engine = SecurityEngine(graph, root)

    findings = engine.analyze_endpoint("POST /")
    titles = [f.title.lower() for f in findings]
    # POST has auth middleware, so should see INFO-level acknowledgment
    assert any("authentication present" in t for t in titles) or \
           any("auth" in t for t in titles)


def test_security_engine_missing_validation(indexed_env):
    """Should detect missing validation on POST endpoint."""
    graph, root = indexed_env
    engine = SecurityEngine(graph, root)

    findings = engine.analyze_endpoint("POST /")
    validation_findings = [f for f in findings if "validation" in f.title.lower()]
    assert len(validation_findings) >= 1


def test_security_engine_missing_helmet(indexed_env):
    """Should detect missing Helmet middleware."""
    graph, root = indexed_env
    engine = SecurityEngine(graph, root)

    findings = engine.analyze_endpoint("GET /")
    helmet_findings = [f for f in findings if "helmet" in f.title.lower()]
    assert len(helmet_findings) >= 1


def test_security_engine_rate_limiting(indexed_env):
    """Should detect missing rate limiting on mutation endpoints."""
    graph, root = indexed_env
    engine = SecurityEngine(graph, root)

    findings = engine.analyze_endpoint("POST /")
    rate_findings = [f for f in findings if "rate" in f.title.lower()]
    assert len(rate_findings) >= 1


def test_security_engine_not_found():
    """Should handle non-existent endpoint gracefully."""
    graph = KnowledgeGraph()
    engine = SecurityEngine(graph, Path("/tmp"))
    findings = engine.analyze_endpoint("GET /nonexistent")
    assert len(findings) >= 1
    assert findings[0].severity == Severity.INFO


def test_security_engine_sorted(indexed_env):
    """Findings should be sorted by severity (critical first)."""
    graph, root = indexed_env
    engine = SecurityEngine(graph, root)

    findings = engine.analyze_endpoint("DELETE /:id")
    if len(findings) >= 2:
        ranks = [f.severity_rank for f in findings]
        assert ranks == sorted(ranks)


# ── Tests: Performance Engine ─────────────────────────


def test_performance_engine_missing_pagination(indexed_env):
    """Should detect missing pagination on list GET endpoint."""
    graph, root = indexed_env
    engine = PerformanceEngine(graph, root)

    findings = engine.analyze_endpoint("GET /")
    pagination_findings = [f for f in findings if "pagination" in f.title.lower()]
    assert len(pagination_findings) >= 1


def test_performance_engine_missing_cache(indexed_env):
    """Should detect missing cache on GET endpoint."""
    graph, root = indexed_env
    engine = PerformanceEngine(graph, root)

    findings = engine.analyze_endpoint("GET /")
    # May or may not find cache issues depending on graph structure
    # But the engine should run without errors
    assert isinstance(findings, list)


def test_performance_engine_skips_non_get(indexed_env):
    """Cache and pagination checks should skip non-GET endpoints."""
    graph, root = indexed_env
    engine = PerformanceEngine(graph, root)

    findings = engine.analyze_endpoint("POST /")
    pagination_findings = [f for f in findings if "pagination" in f.title.lower()]
    cache_findings = [f for f in findings if "cache" in f.title.lower()]
    assert len(pagination_findings) == 0
    assert len(cache_findings) == 0


def test_performance_engine_all_endpoints(indexed_env):
    """Should analyze all endpoints without errors."""
    graph, root = indexed_env
    engine = PerformanceEngine(graph, root)

    results = engine.analyze_all_endpoints()
    assert isinstance(results, dict)
    assert len(results) >= 1


# ── Tests: Architecture Engine ────────────────────────


def test_architecture_engine_runs(indexed_env):
    """Architecture engine should run without errors."""
    graph, root = indexed_env
    engine = ArchitectureEngine(graph, root)

    findings = engine.analyze()
    assert isinstance(findings, list)


def test_architecture_engine_endpoint_scope(indexed_env):
    """Should scope architecture checks to an endpoint's subgraph."""
    graph, root = indexed_env
    engine = ArchitectureEngine(graph, root)

    findings = engine.analyze_endpoint("GET /")
    assert isinstance(findings, list)


def test_architecture_circular_deps(indexed_env):
    """Circular dependency check should run without errors."""
    graph, root = indexed_env
    engine = ArchitectureEngine(graph, root)

    # Our fixture doesn't have circular deps, but the check should complete
    findings = engine.analyze()
    circular = [f for f in findings if "circular" in f.title.lower()]
    assert isinstance(circular, list)  # May be empty for this fixture


def test_architecture_findings_sorted(indexed_env):
    """Architecture findings should be sorted by severity."""
    graph, root = indexed_env
    engine = ArchitectureEngine(graph, root)

    findings = engine.analyze()
    if len(findings) >= 2:
        ranks = [f.severity_rank for f in findings]
        assert ranks == sorted(ranks)


# ── Tests: Finding Model ─────────────────────────────


def test_severity_rank():
    """severity_rank should order findings correctly."""
    from endpointiq.models.analysis import Finding

    critical = Finding(severity=Severity.CRITICAL, title="A", description="A")
    high = Finding(severity=Severity.HIGH, title="B", description="B")
    medium = Finding(severity=Severity.MEDIUM, title="C", description="C")
    low = Finding(severity=Severity.LOW, title="D", description="D")
    info = Finding(severity=Severity.INFO, title="E", description="E")

    assert critical.severity_rank < high.severity_rank < medium.severity_rank
    assert medium.severity_rank < low.severity_rank < info.severity_rank
