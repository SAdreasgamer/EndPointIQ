"""Unit tests for models, config, events, logging, db, watcher, and parser."""

from pathlib import Path

import pytest

from endpointiq.core.config import load_config
from endpointiq.core.events import EventBus, Events
from endpointiq.db.models import DatabaseManager, Project, now_timestamp
from endpointiq.models.analysis import Finding, Severity
from endpointiq.models.endpoint import EndpointDefinition, HttpMethod
from endpointiq.models.graph import EdgeType, GraphEdge, GraphNode, NodeType
from endpointiq.observation.parser import ASTParser
from endpointiq.observation.watcher import FileFilter


def test_models_instantiation():
    ep = EndpointDefinition(
        method=HttpMethod.POST,
        path="/api/users",
        handler="UserController.create",
        file_path="src/controllers/user.ts",
        line_start=10,
        line_end=25,
        framework="express",
    )
    assert ep.display_name == "POST /api/users"
    assert len(ep.id) == 16

    node = GraphNode(
        id="node1",
        type=NodeType.CONTROLLER,
        qualified_name="UserController",
        file_path="src/controllers/user.ts",
        line_start=1,
        line_end=50,
    )
    assert node.display_name == "UserController"

    edge = GraphEdge(
        source="node1",
        target="node2",
        type=EdgeType.CALLS,
    )
    assert edge.weight == 1.0

    finding = Finding(
        severity=Severity.HIGH,
        title="Missing Auth",
        description="Endpoint is missing auth middleware",
    )
    assert finding.severity == Severity.HIGH


def test_config_loading(tmp_path: Path):
    cfg = load_config(project_root=tmp_path)
    assert cfg.project_root == tmp_path
    assert cfg.watch_debounce_seconds == 0.3


@pytest.mark.asyncio
async def test_event_bus():
    bus = EventBus()
    received = []

    async def sample_handler(**kwargs):
        received.append(kwargs.get("data"))

    bus.on(Events.ENDPOINT_DISCOVERED, sample_handler)
    await bus.emit(Events.ENDPOINT_DISCOVERED, data="test_endpoint")

    assert len(received) == 1
    assert received[0] == "test_endpoint"
    assert bus.total_emits == 1


def test_db_manager(tmp_path: Path):
    db_file = tmp_path / "test.db"
    db = DatabaseManager(str(db_file))
    db.create_tables()

    with db.session() as session:
        proj = Project(
            id="p1",
            name="TestProject",
            root_path=str(tmp_path),
            created_at=now_timestamp(),
            updated_at=now_timestamp(),
        )
        session.add(proj)
        session.commit()

        fetched = session.query(Project).filter_by(id="p1").first()
        assert fetched is not None
        assert fetched.name == "TestProject"

    db.close()


def test_file_filter():
    ff = FileFilter(ignore_patterns=[".git", "node_modules"])
    assert ff.should_include("src/index.ts") is True
    assert ff.should_include(".git/HEAD") is False
    assert ff.should_include("node_modules/express/index.js") is False
    assert ff.should_include("image.png") is False


def test_ast_parser():
    parser = ASTParser()
    code = """
    class UserController {
        async create(req: any, res: any) {
            return res.json({ status: "ok" });
        }
    }
    """
    res = parser.parse(code, "typescript", "test.ts")
    assert res.language == "typescript"
    assert len(res.symbols) > 0
    class_syms = [s for s in res.symbols if s.kind == "class"]
    assert len(class_syms) == 1
    assert class_syms[0].name == "UserController"
