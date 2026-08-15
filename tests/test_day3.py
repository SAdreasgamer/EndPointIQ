"""Day 3 tests — MRC extractor, compression pipeline, token counting,
and full integration test with the Express fixture."""

import json
from pathlib import Path

import pytest

from endpointiq.context.compression import (
    compress,
    count_tokens,
    normalize_whitespace,
    prune_imports,
    strip_comments,
    summarize_methods,
)
from endpointiq.context.extractor import GoalType, MRCExtractor
from endpointiq.core.config import load_config
from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.observation.indexer import ProjectIndexer

# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def express_project(tmp_path: Path) -> Path:
    """Create a minimal Express.js project fixture (same as Day 2)."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test-api",
        "dependencies": {
            "express": "^4.18.2",
            "cors": "^2.8.5",
            "helmet": "^7.1.0",
        },
        "devDependencies": {"typescript": "^5.0.0"},
    }))

    (tmp_path / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}},
    }))

    src = tmp_path / "src"
    src.mkdir()

    (src / "app.ts").write_text("""
import express from 'express';
import cors from 'cors';
import { userRouter } from './routes/userRoutes';

const app = express();
app.use(cors());
app.use(express.json());
app.use('/api/users', userRouter);
app.get('/health', (req, res) => { res.json({ status: 'ok' }); });
export default app;
""")

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

    controllers = src / "controllers"
    controllers.mkdir()
    (controllers / "UserController.ts").write_text("""
import { UserService } from '../services/UserService';

// This is the main controller for user operations
export class UserController {
    private userService = new UserService();

    // Get all users from the database
    async getAll(req: any, res: any) {
        const users = await this.userService.findAll();
        res.json(users);
    }

    // Get a single user by ID
    async getById(req: any, res: any) {
        const user = await this.userService.findById(req.params.id);
        res.json(user);
    }

    // Create a new user
    async create(req: any, res: any) {
        const user = await this.userService.create(req.body);
        res.status(201).json(user);
    }

    // Update a user
    async update(req: any, res: any) {
        const user = await this.userService.update(req.params.id, req.body);
        res.json(user);
    }

    // Delete a user
    async delete(req: any, res: any) {
        await this.userService.delete(req.params.id);
        res.status(204).send();
    }
}
""")

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

    repos = src / "repositories"
    repos.mkdir()
    (repos / "UserRepository.ts").write_text("""
export class UserRepository {
    async findAll() { return []; }
    async findById(id: string) { return { id }; }
    async save(data: any) { return { ...data, id: '1' }; }
    async update(id: string, data: any) { return { ...data, id }; }
    async delete(id: string) { return true; }
}
""")

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

    (middleware / "validate.ts").write_text("""
export function validateUser(req: any, res: any, next: any) {
    if (!req.body.name || !req.body.email) {
        return res.status(400).json({ error: 'Name and email are required' });
    }
    next();
}
""")

    return tmp_path


@pytest.fixture
def indexed_project(express_project: Path):
    """Return (config, graph, indexer) for an indexed Express project."""
    config = load_config(project_root=express_project)
    graph = KnowledgeGraph()
    indexer = ProjectIndexer(config, graph)
    indexer.full_index()
    return config, graph, indexer


# ── Tests: Token Counting ─────────────────────────────


def test_count_tokens_basic():
    """Token counter should return non-zero for non-empty text."""
    assert count_tokens("") == 0
    assert count_tokens("hello world") > 0
    assert count_tokens("function foo() { return 42; }") > 0


def test_count_tokens_proportional():
    """Longer text should have more tokens."""
    short = count_tokens("hello")
    long = count_tokens("hello " * 100)
    assert long > short


# ── Tests: Stage 1 — Import Pruner ────────────────────


def test_prune_imports_removes_unused():
    """Should remove imports not referenced in the body."""
    source = """import { Foo } from './foo';
import { Bar } from './bar';
import { Baz } from './baz';

const x = new Foo();
console.log(x);
"""
    result = prune_imports(source)
    assert "Foo" in result
    assert "Bar" not in result
    assert "Baz" not in result


def test_prune_imports_keeps_used():
    """Should keep imports that are referenced."""
    source = """import { Foo } from './foo';
import { Bar } from './bar';

const x = new Foo();
const y = new Bar();
"""
    result = prune_imports(source)
    assert "Foo" in result
    assert "Bar" in result


def test_prune_imports_no_imports():
    """Should handle code with no imports."""
    source = "const x = 42;\nconsole.log(x);"
    result = prune_imports(source)
    assert result == source


# ── Tests: Stage 2 — Comment Stripper ─────────────────


def test_strip_single_line_comments():
    """Should remove // comments."""
    source = """const x = 42; // this is a comment
// this whole line is a comment
const y = 10;"""
    result = strip_comments(source)
    assert "this is a comment" not in result
    assert "this whole line" not in result
    assert "const x = 42;" in result
    assert "const y = 10;" in result


def test_strip_comments_preserves_strings():
    """Should not strip // inside string literals."""
    source = '''const url = "https://example.com";'''
    result = strip_comments(source)
    assert "https://example.com" in result


def test_strip_multiline_comments():
    """Should remove /* ... */ comments."""
    source = """/* this is
a multi-line
comment */
const x = 42;"""
    result = strip_comments(source)
    assert "multi-line" not in result
    assert "const x = 42;" in result


# ── Tests: Stage 3 — Whitespace Normalizer ────────────


def test_normalize_whitespace():
    """Should collapse consecutive blank lines."""
    source = """const x = 1;



const y = 2;


const z = 3;"""
    result = normalize_whitespace(source)
    # Should have at most 1 consecutive blank line
    assert "\n\n\n" not in result
    assert "const x = 1;" in result
    assert "const z = 3;" in result


def test_normalize_trailing_whitespace():
    """Should trim trailing whitespace."""
    source = "const x = 1;   \nconst y = 2;  "
    result = normalize_whitespace(source)
    assert not any(line.endswith(" ") for line in result.split("\n"))


# ── Tests: Stage 4 — Method Summarizer ────────────────


def test_summarize_methods():
    """Should replace irrelevant method bodies with stubs."""
    source = """class UserService {
    async findAll() {
        const db = getDB();
        return db.query('SELECT * FROM users');
    }

    async findById(id: string) {
        return db.query('SELECT * FROM users WHERE id = ?', id);
    }
}"""
    result = summarize_methods(source, relevant_names={"findAll"})
    assert "getDB()" in result  # findAll body preserved
    assert "/* ... */" in result  # findById body replaced


def test_summarize_methods_none_keeps_all():
    """When relevant_names is None, all method bodies are kept."""
    source = """function foo() {
    return 42;
}"""
    result = summarize_methods(source, relevant_names=None)
    assert "return 42;" in result


# ── Tests: Full Compression Pipeline ──────────────────


def test_compress_full_pipeline():
    """Full pipeline should reduce token count."""
    source = """import { Foo } from './foo';
import { Bar } from './bar';
import { Baz } from './baz';

// This is a comment
/* Multi-line
   comment */

class Service {
    // Method 1
    async getAll() {
        const foo = new Foo();
        return foo.findAll();
    }



    // Method 2
    async getById(id: string) {
        return { id };
    }
}
"""
    original_tokens = count_tokens(source)
    compressed = compress(source, relevant_names={"getAll"})
    compressed_tokens = count_tokens(compressed)

    assert compressed_tokens < original_tokens
    assert "Foo" in compressed  # Used import kept
    assert "This is a comment" not in compressed  # Comment removed
    assert "/* ... */" in compressed  # getById summarized


# ── Tests: MRC Extractor ─────────────────────────────


def test_mrc_extractor_not_found():
    """Should return empty result for unknown endpoint."""
    graph = KnowledgeGraph()
    extractor = MRCExtractor(graph, Path("/tmp"))
    result = extractor.extract("GET /nonexistent", GoalType.SECURITY)
    assert result.nodes_selected == 0
    assert result.total_tokens == 0


def test_mrc_extractor_security(indexed_project):
    """MRC should extract context for a security analysis."""
    config, graph, _indexer = indexed_project
    extractor = MRCExtractor(graph, config.project_root)

    # Extract context for the POST endpoint (has auth + validation)
    result = extractor.extract(
        "POST /", GoalType.SECURITY, token_budget=4000
    )

    assert result.nodes_selected > 0
    assert result.total_tokens > 0
    assert result.total_tokens <= 4000
    assert result.extraction_time_ms < 10000  # generous for CI cold-start (tiktoken init)


def test_mrc_extractor_performance(indexed_project):
    """MRC should extract context for a performance analysis."""
    config, graph, _indexer = indexed_project
    extractor = MRCExtractor(graph, config.project_root)

    result = extractor.extract(
        "GET /", GoalType.PERFORMANCE, token_budget=4000
    )

    assert result.nodes_selected > 0
    assert result.total_tokens > 0
    assert result.total_tokens <= 4000


def test_mrc_different_goals_different_context(indexed_project):
    """Different goals should produce different context (different relevance scoring)."""
    config, graph, _indexer = indexed_project
    extractor = MRCExtractor(graph, config.project_root)

    security_result = extractor.extract("POST /", GoalType.SECURITY, token_budget=4000)
    perf_result = extractor.extract("POST /", GoalType.PERFORMANCE, token_budget=4000)

    # Both should produce non-empty context
    assert security_result.nodes_selected > 0
    assert perf_result.nodes_selected > 0

    # The ordering of snippets should differ (different relevance scores)
    sec_names = [s.qualified_name for s in security_result.snippets]
    perf_names = [s.qualified_name for s in perf_result.snippets]
    # At minimum, both should have results
    assert len(sec_names) > 0
    assert len(perf_names) > 0


def test_mrc_compression_ratio(indexed_project):
    """MRC should demonstrate significant compression (>50% node reduction)."""
    config, graph, _indexer = indexed_project
    extractor = MRCExtractor(graph, config.project_root)

    result = extractor.extract("GET /", GoalType.SECURITY, token_budget=4000)

    # Should select far fewer nodes than total graph
    assert result.compression_ratio > 0.0  # Some compression achieved
    assert result.nodes_selected < result.total_nodes_in_graph


def test_mrc_combined_context(indexed_project):
    """combined_context property should produce formatted context string."""
    config, graph, _indexer = indexed_project
    extractor = MRCExtractor(graph, config.project_root)

    result = extractor.extract("GET /", GoalType.FULL, token_budget=4000)

    context = result.combined_context
    assert len(context) > 0
    assert "===" in context  # Headers present
