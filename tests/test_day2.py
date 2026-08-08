"""Day 2 tests — Express detection, endpoint extraction, knowledge graph,
dependency/call graph builders, and project indexer (full + incremental)."""

import json
from pathlib import Path

import pytest

from endpointiq.core.config import load_config
from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.models.graph import EdgeType, GraphEdge, GraphNode, NodeType
from endpointiq.observation.builders import (
    classify_role,
)
from endpointiq.observation.indexer import ProjectIndexer
from endpointiq.observation.plugins.base import PluginManager
from endpointiq.observation.plugins.express_plugin import ExpressPlugin

# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def express_project(tmp_path: Path) -> Path:
    """Create a minimal Express.js project fixture."""

    # package.json
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test-api",
        "version": "1.0.0",
        "dependencies": {
            "express": "^4.18.2",
            "cors": "^2.8.5",
            "helmet": "^7.1.0",
        },
        "devDependencies": {
            "typescript": "^5.0.0",
        },
    }))

    # tsconfig.json
    (tmp_path / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {
                "@/*": ["src/*"],
            },
        },
    }))

    # src/app.ts
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.ts").write_text("""
import express from 'express';
import cors from 'cors';
import { userRouter } from './routes/userRoutes';
import { authMiddleware } from './middleware/auth';

const app = express();

app.use(cors());
app.use(express.json());
app.use('/api/users', userRouter);

app.get('/health', (req, res) => {
    res.json({ status: 'ok' });
});

export default app;
""")

    # src/routes/userRoutes.ts
    routes = src / "routes"
    routes.mkdir()
    (routes / "userRoutes.ts").write_text("""
import { Router } from 'express';
import { UserController } from '../controllers/UserController';
import { validateUser } from '../middleware/validate';
import { authMiddleware } from '../middleware/auth';

const router = Router();
const userController = new UserController();

router.get('/', userController.getAll);
router.get('/:id', userController.getById);
router.post('/', authMiddleware, validateUser, userController.create);
router.put('/:id', authMiddleware, userController.update);
router.delete('/:id', authMiddleware, userController.delete);

export { router as userRouter };
""")

    # src/controllers/UserController.ts
    controllers = src / "controllers"
    controllers.mkdir()
    (controllers / "UserController.ts").write_text("""
import { UserService } from '../services/UserService';

export class UserController {
    private userService = new UserService();

    async getAll(req: any, res: any) {
        const users = await this.userService.findAll();
        res.json(users);
    }

    async getById(req: any, res: any) {
        const user = await this.userService.findById(req.params.id);
        res.json(user);
    }

    async create(req: any, res: any) {
        const user = await this.userService.create(req.body);
        res.status(201).json(user);
    }

    async update(req: any, res: any) {
        const user = await this.userService.update(req.params.id, req.body);
        res.json(user);
    }

    async delete(req: any, res: any) {
        await this.userService.delete(req.params.id);
        res.status(204).send();
    }
}
""")

    # src/services/UserService.ts
    services = src / "services"
    services.mkdir()
    (services / "UserService.ts").write_text("""
import { UserRepository } from '../repositories/UserRepository';

export class UserService {
    private userRepository = new UserRepository();

    async findAll() {
        return this.userRepository.findAll();
    }

    async findById(id: string) {
        return this.userRepository.findById(id);
    }

    async create(data: any) {
        return this.userRepository.save(data);
    }

    async update(id: string, data: any) {
        return this.userRepository.update(id, data);
    }

    async delete(id: string) {
        return this.userRepository.delete(id);
    }
}
""")

    # src/repositories/UserRepository.ts
    repos = src / "repositories"
    repos.mkdir()
    (repos / "UserRepository.ts").write_text("""
export class UserRepository {
    async findAll() {
        return [];
    }

    async findById(id: string) {
        return { id };
    }

    async save(data: any) {
        return { ...data, id: '1' };
    }

    async update(id: string, data: any) {
        return { ...data, id };
    }

    async delete(id: string) {
        return true;
    }
}
""")

    # src/middleware/auth.ts
    middleware = src / "middleware"
    middleware.mkdir()
    (middleware / "auth.ts").write_text("""
export function authMiddleware(req: any, res: any, next: any) {
    const token = req.headers.authorization;
    if (!token) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    next();
}
""")

    # src/middleware/validate.ts
    (middleware / "validate.ts").write_text("""
export function validateUser(req: any, res: any, next: any) {
    if (!req.body.name || !req.body.email) {
        return res.status(400).json({ error: 'Name and email are required' });
    }
    next();
}
""")

    return tmp_path


# ── Tests: Express Plugin ─────────────────────────────


def test_express_detection(express_project: Path):
    """Express plugin should detect Express with high confidence."""
    plugin = ExpressPlugin()
    result = plugin.detect(express_project)

    assert result.framework == "express"
    assert result.confidence == 0.95
    assert result.language == "typescript"
    assert result.version == "^4.18.2"


def test_express_detection_no_package_json(tmp_path: Path):
    """Should return 0 confidence when no package.json exists."""
    plugin = ExpressPlugin()
    result = plugin.detect(tmp_path)
    assert result.confidence == 0.0


def test_express_endpoint_extraction(express_project: Path):
    """Should extract all endpoints from route files."""
    plugin = ExpressPlugin()

    # Extract from routes file
    routes_file = express_project / "src" / "routes" / "userRoutes.ts"
    source = routes_file.read_bytes()
    result = plugin.extract_endpoints(
        express_project, "src/routes/userRoutes.ts", source
    )

    assert len(result.endpoints) == 5

    methods = {ep.method.value for ep in result.endpoints}
    assert "GET" in methods
    assert "POST" in methods
    assert "PUT" in methods
    assert "DELETE" in methods

    paths = {ep.path for ep in result.endpoints}
    assert "/" in paths
    assert "/:id" in paths

    # POST should have middleware
    post_ep = next(ep for ep in result.endpoints if ep.method.value == "POST")
    assert len(post_ep.middleware) >= 1


def test_express_app_routes(express_project: Path):
    """Should extract routes from app.ts (health endpoint)."""
    plugin = ExpressPlugin()
    app_file = express_project / "src" / "app.ts"
    source = app_file.read_bytes()
    result = plugin.extract_endpoints(express_project, "src/app.ts", source)

    assert len(result.endpoints) >= 1
    health = [ep for ep in result.endpoints if ep.path == "/health"]
    assert len(health) == 1
    assert health[0].method.value == "GET"


def test_express_middleware_extraction(express_project: Path):
    """Should extract global middleware from app.use() calls."""
    plugin = ExpressPlugin()
    app_file = express_project / "src" / "app.ts"
    source = app_file.read_bytes()
    result = plugin.extract_endpoints(express_project, "src/app.ts", source)

    assert "cors" in result.middleware


# ── Tests: Plugin Manager ─────────────────────────────


def test_plugin_manager_detection(express_project: Path):
    """Plugin manager should detect Express via registered plugins."""
    manager = PluginManager()
    manager.register(ExpressPlugin())
    result = manager.detect_framework(express_project)

    assert result is not None
    assert result.framework == "express"
    assert result.confidence > 0.9


# ── Tests: Role Classification ─────────────────────────


def test_role_classification():
    """Should classify symbols by naming patterns."""
    assert classify_role("UserController") == NodeType.CONTROLLER
    assert classify_role("AuthService") == NodeType.SERVICE
    assert classify_role("UserRepository") == NodeType.REPOSITORY
    assert classify_role("validateUser") == NodeType.VALIDATOR
    assert classify_role("authMiddleware") == NodeType.MIDDLEWARE
    assert classify_role("DatabaseConfig") == NodeType.CONFIG
    assert classify_role("SomeRandomClass") == NodeType.CLASS


# ── Tests: Knowledge Graph ────────────────────────────


def test_knowledge_graph_upsert():
    """Should add and retrieve nodes and edges."""
    graph = KnowledgeGraph()

    node1 = GraphNode(
        id="n1", type=NodeType.ENDPOINT,
        qualified_name="GET /api/users",
        file_path="routes.ts", line_start=1, line_end=5,
        provenance="routes.ts",
    )
    node2 = GraphNode(
        id="n2", type=NodeType.CONTROLLER,
        qualified_name="UserController",
        file_path="controller.ts", line_start=1, line_end=50,
        provenance="controller.ts",
    )
    edge = GraphEdge(
        source="n1", target="n2",
        type=EdgeType.CALLS,
        provenance="routes.ts",
    )

    graph.upsert_subgraph([node1, node2], [edge])

    assert graph.node_count == 2
    assert graph.edge_count == 1
    assert graph.lookup_endpoint("GET /api/users") == "n1"


def test_knowledge_graph_prune():
    """Pruning should remove all nodes from a specific file."""
    graph = KnowledgeGraph()

    nodes = [
        GraphNode(id="n1", type=NodeType.ENDPOINT,
                  qualified_name="GET /api/users", file_path="a.ts",
                  line_start=1, line_end=5, provenance="a.ts"),
        GraphNode(id="n2", type=NodeType.CONTROLLER,
                  qualified_name="UserCtrl", file_path="a.ts",
                  line_start=10, line_end=50, provenance="a.ts"),
        GraphNode(id="n3", type=NodeType.SERVICE,
                  qualified_name="UserService", file_path="b.ts",
                  line_start=1, line_end=30, provenance="b.ts"),
    ]
    graph.upsert_nodes(nodes)
    assert graph.node_count == 3

    pruned = graph.prune_by_provenance("a.ts")
    assert pruned == 2
    assert graph.node_count == 1
    assert graph.get_node("n3") is not None


def test_knowledge_graph_save_load(tmp_path: Path):
    """Graph should serialize to JSON and reload correctly."""
    graph = KnowledgeGraph()
    graph.upsert_node(GraphNode(
        id="n1", type=NodeType.ENDPOINT,
        qualified_name="POST /api/users", file_path="routes.ts",
        line_start=1, line_end=5, provenance="routes.ts",
    ))
    graph.upsert_edge(GraphEdge(
        source="n1", target="n1", type=EdgeType.CALLS, provenance="routes.ts",
    ))

    save_path = tmp_path / "graph.json"
    graph.save(save_path)
    assert save_path.exists()

    # Load into fresh graph
    graph2 = KnowledgeGraph()
    loaded = graph2.load(save_path)
    assert loaded is True
    assert graph2.node_count == 1
    assert graph2.edge_count == 1
    assert graph2.lookup_endpoint("POST /api/users") == "n1"


def test_knowledge_graph_neighbors():
    """Should return neighbors filtered by edge type."""
    graph = KnowledgeGraph()
    graph.upsert_nodes([
        GraphNode(id="ep", type=NodeType.ENDPOINT, qualified_name="GET /",
                  file_path="a.ts", line_start=1, line_end=1, provenance="a.ts"),
        GraphNode(id="ctrl", type=NodeType.CONTROLLER, qualified_name="Ctrl",
                  file_path="a.ts", line_start=1, line_end=1, provenance="a.ts"),
        GraphNode(id="mw", type=NodeType.MIDDLEWARE, qualified_name="auth",
                  file_path="a.ts", line_start=1, line_end=1, provenance="a.ts"),
    ])
    graph.upsert_edges([
        GraphEdge(source="ep", target="ctrl", type=EdgeType.CALLS, provenance="a.ts"),
        GraphEdge(source="ep", target="mw", type=EdgeType.SECURED_BY, provenance="a.ts"),
    ])

    # All neighbors
    all_n = graph.get_neighbors("ep")
    assert len(all_n) == 2

    # Filtered by CALLS only
    calls = graph.get_neighbors("ep", edge_types=[EdgeType.CALLS])
    assert calls == ["ctrl"]

    # Filtered by SECURED_BY only
    secured = graph.get_neighbors("ep", edge_types=[EdgeType.SECURED_BY])
    assert secured == ["mw"]


# ── Tests: Project Indexer ────────────────────────────


def test_full_index(express_project: Path):
    """Full index should detect Express, find endpoints, and build graph."""
    config = load_config(project_root=express_project)
    graph = KnowledgeGraph()
    indexer = ProjectIndexer(config, graph)

    stats = indexer.full_index()

    assert stats["framework"] == "express"
    assert stats["confidence"] == 0.95
    assert stats["files"] >= 5  # at least app, routes, controller, service, repo
    assert stats["endpoints"] >= 5  # 5 route endpoints + 1 health
    assert stats["nodes"] > 10  # nodes for files, classes, functions, endpoints
    assert stats["edges"] > 5  # dependency + call edges
    assert stats["duration_ms"] < 5000  # should be fast


def test_incremental_index(express_project: Path):
    """Incremental index should update graph when files change."""
    config = load_config(project_root=express_project)
    graph = KnowledgeGraph()
    indexer = ProjectIndexer(config, graph)

    # Full index first
    indexer.full_index()
    original_endpoints = len(indexer.endpoints)

    # Simulate adding a new route
    routes_file = express_project / "src" / "routes" / "userRoutes.ts"
    content = routes_file.read_text()
    content += "\nrouter.patch('/:id/status', userController.updateStatus);\n"
    routes_file.write_text(content)

    # Run incremental update
    from endpointiq.observation.watcher import FileChangeEvent
    changes = [
        FileChangeEvent(type="modified", path="src/routes/userRoutes.ts"),
    ]
    stats = indexer.handle_changes(changes)

    assert stats["files_updated"] == 1
    assert len(indexer.endpoints) >= original_endpoints


def test_incremental_delete(express_project: Path):
    """Deleting a file should prune its nodes from the graph."""
    config = load_config(project_root=express_project)
    graph = KnowledgeGraph()
    indexer = ProjectIndexer(config, graph)

    indexer.full_index()
    nodes_before = graph.node_count

    # Simulate deleting the service file
    from endpointiq.observation.watcher import FileChangeEvent
    changes = [
        FileChangeEvent(type="deleted", path="src/services/UserService.ts"),
    ]
    stats = indexer.handle_changes(changes)

    assert stats["files_deleted"] == 1
    assert graph.node_count < nodes_before
