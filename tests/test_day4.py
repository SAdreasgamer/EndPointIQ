"""Day 4 tests — LangGraph agent system.

Tests the full agent pipeline: planner → executor → evaluator → reporter,
including re-plan loop, checkpointing, and static analysis fallback.
"""

import json
from pathlib import Path

import pytest

from endpointiq.agent.graph import (
    AgentState,
    build_agent_graph,
    create_agent,
    evaluator_node,
    planner_node,
    reporter_node,
    should_replan,
)
from endpointiq.agent.prompts import (
    EVALUATOR_PROMPT,
    EXECUTOR_PROMPT,
    PLANNER_PROMPT,
    REPORTER_PROMPT,
)
from endpointiq.agent.tools import (
    ALL_TOOLS,
    set_tool_context,
)
from endpointiq.core.config import load_config
from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.observation.indexer import ProjectIndexer

# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def express_project(tmp_path: Path) -> Path:
    """Create a minimal Express.js project fixture."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test-api",
        "dependencies": {"express": "^4.18.2", "cors": "^2.8.5"},
        "devDependencies": {"typescript": "^5.0.0"},
    }))

    (tmp_path / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}},
    }))

    src = tmp_path / "src"
    src.mkdir()

    (src / "app.ts").write_text("""
import express from 'express';
import { userRouter } from './routes/userRoutes';

const app = express();
app.use(express.json());
app.use('/api/users', userRouter);
app.get('/health', (req, res) => { res.json({ status: 'ok' }); });
export default app;
""")

    routes = src / "routes"
    routes.mkdir()
    (routes / "userRoutes.ts").write_text("""
import { Router } from 'express';
const router = Router();
router.get('/', (req, res) => { res.json([]); });
router.post('/', (req, res) => { res.json(req.body); });
export { router as userRouter };
""")

    return tmp_path


@pytest.fixture
def indexed_graph(express_project: Path) -> tuple[KnowledgeGraph, Path]:
    """Index an Express project and return (graph, project_root)."""
    config = load_config(project_root=express_project)
    graph = KnowledgeGraph()
    indexer = ProjectIndexer(config, graph)
    indexer.full_index()
    return graph, express_project


# ── Tests: Prompt Templates ───────────────────────────


def test_prompt_templates_format():
    """All prompt templates should format without errors."""
    planner_msgs = PLANNER_PROMPT.format_messages(
        endpoint_name="GET /api/users",
        goal_type="security",
        token_budget=4000,
        iteration=1,
        re_plan_context="",
    )
    assert len(planner_msgs) == 2  # system + human

    executor_msgs = EXECUTOR_PROMPT.format_messages(
        endpoint_name="GET /api/users",
        goal_type="security",
        check_type="auth_check",
        code_context="const app = express();",
    )
    assert len(executor_msgs) == 2

    evaluator_msgs = EVALUATOR_PROMPT.format_messages(
        endpoint_name="GET /api/users",
        goal_type="security",
        planned_steps="3 steps",
        results_summary="2 findings",
        iteration=1,
    )
    assert len(evaluator_msgs) == 2

    reporter_msgs = REPORTER_PROMPT.format_messages(
        endpoint_name="GET /api/users",
        goal_type="security",
        confidence=0.85,
        iterations=1,
        raw_findings="[]",
        token_usage="{}",
    )
    assert len(reporter_msgs) == 2


# ── Tests: Tool Registration ─────────────────────────


def test_tools_registered():
    """All expected tools should be registered."""
    tool_names = {t.name for t in ALL_TOOLS}
    assert "extract_context" in tool_names
    assert "get_endpoint_info" in tool_names
    assert "query_knowledge_graph" in tool_names
    assert "list_endpoints" in tool_names


def test_tool_context_setup(indexed_graph):
    """Setting tool context should make graph available to tools."""
    graph, project_root = indexed_graph
    set_tool_context(graph=graph, project_root=project_root)

    from endpointiq.agent.tools import _tool_context
    assert _tool_context.get("graph") is graph
    assert _tool_context.get("project_root") == project_root


# ── Tests: Planner Node ──────────────────────────────


def test_planner_security():
    """Planner should create security-specific steps."""
    state: AgentState = {
        "endpoint_name": "POST /api/users",
        "goal_type": "security",
        "iteration": 1,
    }
    result = planner_node(state)

    assert "plan" in result
    assert "planned_steps" in result
    assert len(result["planned_steps"]) >= 3
    checks = {s["check"] for s in result["planned_steps"]}
    assert "auth_check" in checks
    assert "input_validation" in checks


def test_planner_performance():
    """Planner should create performance-specific steps."""
    state: AgentState = {
        "endpoint_name": "GET /api/users",
        "goal_type": "performance",
        "iteration": 1,
    }
    result = planner_node(state)
    checks = {s["check"] for s in result["planned_steps"]}
    assert "query_analysis" in checks


def test_planner_replan_adds_gap_steps():
    """Re-planning should add steps to address identified gaps."""
    state: AgentState = {
        "endpoint_name": "POST /api/users",
        "goal_type": "security",
        "iteration": 2,
        "gaps": ["Missing rate limiting analysis"],
    }
    result = planner_node(state)
    descriptions = [s["description"] for s in result["planned_steps"]]
    assert any("Missing rate limiting" in d for d in descriptions)


# ── Tests: Evaluator Node ────────────────────────────


def test_evaluator_high_confidence():
    """Evaluator should give high confidence for complete results."""
    state: AgentState = {
        "planned_steps": [{"check": "auth"}, {"check": "validation"}],
        "results": [
            {
                "check": "auth",
                "findings": [{"title": "Auth OK", "file_path": "app.ts", "recommendation": "Keep it"}],
                "summary": "Good",
            },
            {
                "check": "validation",
                "findings": [{"title": "Valid", "file_path": "routes.ts", "recommendation": "Add schema"}],
                "summary": "Good",
            },
        ],
    }
    result = evaluator_node(state)
    assert result["confidence"] >= 0.7
    assert len(result["gaps"]) == 0


def test_evaluator_low_confidence():
    """Evaluator should give low confidence for incomplete results."""
    state: AgentState = {
        "planned_steps": [{"check": "auth"}, {"check": "validation"}],
        "results": [
            {
                "check": "auth",
                "findings": [],
                "summary": "",
            },
        ],
    }
    result = evaluator_node(state)
    assert result["confidence"] < 0.7
    assert len(result["gaps"]) > 0


# ── Tests: Routing Logic ─────────────────────────────


def test_should_replan_low_confidence():
    """Should re-plan when confidence is low and iterations remain."""
    state: AgentState = {"confidence": 0.5, "iteration": 1, "max_iterations": 3}
    assert should_replan(state) == "replan"


def test_should_report_high_confidence():
    """Should report when confidence is high enough."""
    state: AgentState = {"confidence": 0.85, "iteration": 1, "max_iterations": 3}
    assert should_replan(state) == "report"


def test_should_report_max_iterations():
    """Should report when max iterations reached, even with low confidence."""
    state: AgentState = {"confidence": 0.3, "iteration": 3, "max_iterations": 3}
    assert should_replan(state) == "report"


# ── Tests: Reporter Node ─────────────────────────────


def test_reporter_produces_report():
    """Reporter should compile a structured report."""
    state: AgentState = {
        "endpoint_name": "POST /api/users",
        "goal_type": "security",
        "confidence": 0.85,
        "iteration": 1,
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 50},
        "results": [
            {
                "check": "auth",
                "findings": [
                    {"severity": "HIGH", "title": "Missing Auth", "description": "No auth", "recommendation": "Add auth"},
                    {"severity": "LOW", "title": "Info Log", "description": "OK", "recommendation": ""},
                ],
            },
            {
                "check": "validation",
                "findings": [
                    {"severity": "MEDIUM", "title": "No Validation", "description": "Bad", "recommendation": "Add validation"},
                ],
            },
        ],
    }
    result = reporter_node(state)
    report = result["report"]

    assert "summary" in report
    assert report["findings_count"] == 3
    assert report["confidence"] == 0.85
    # Findings should be sorted by severity
    assert report["findings"][0]["severity"] == "HIGH"
    assert report["findings"][1]["severity"] == "MEDIUM"
    assert len(report["recommendations"]) >= 2


def test_reporter_deduplicates():
    """Reporter should deduplicate findings with the same title."""
    state: AgentState = {
        "endpoint_name": "GET /",
        "goal_type": "security",
        "confidence": 0.8,
        "iteration": 1,
        "token_usage": {},
        "results": [
            {"check": "a", "findings": [{"severity": "HIGH", "title": "Dup", "description": "A"}]},
            {"check": "b", "findings": [{"severity": "HIGH", "title": "Dup", "description": "B"}]},
        ],
    }
    result = reporter_node(state)
    assert result["report"]["findings_count"] == 1


# ── Tests: Full Graph ─────────────────────────────────


def test_graph_builds():
    """Agent graph should compile without errors."""
    compiled = build_agent_graph()
    assert compiled is not None


def test_graph_with_checkpointing():
    """Agent graph should compile with MemorySaver checkpointing."""
    agent, checkpointer = create_agent(with_checkpointing=True)
    assert agent is not None
    assert checkpointer is not None


def test_full_agent_flow(indexed_graph):
    """Full agent flow: planner → executor → evaluator → reporter."""
    graph, project_root = indexed_graph

    from endpointiq.context.extractor import MRCExtractor
    extractor = MRCExtractor(graph, project_root)
    set_tool_context(graph=graph, extractor=extractor, project_root=project_root)

    agent, _checkpointer = create_agent(with_checkpointing=True)

    initial_state: AgentState = {
        "endpoint_name": "POST /",
        "goal_type": "security",
        "token_budget": 4000,
        "iteration": 1,
        "max_iterations": 2,
    }

    config = {"configurable": {"thread_id": "test-run-1"}}
    result = agent.invoke(initial_state, config=config)

    assert "report" in result
    report = result["report"]
    assert "summary" in report
    assert "findings" in report
    assert report["findings_count"] >= 1
    assert report["confidence"] > 0
    assert report["goal_type"] == "security"


def test_full_agent_performance_flow(indexed_graph):
    """Full agent flow for performance analysis."""
    graph, project_root = indexed_graph

    from endpointiq.context.extractor import MRCExtractor
    extractor = MRCExtractor(graph, project_root)
    set_tool_context(graph=graph, extractor=extractor, project_root=project_root)

    agent, _ = create_agent(with_checkpointing=True)

    initial_state: AgentState = {
        "endpoint_name": "GET /",
        "goal_type": "performance",
        "token_budget": 4000,
        "iteration": 1,
        "max_iterations": 2,
    }

    config = {"configurable": {"thread_id": "test-perf-1"}}
    result = agent.invoke(initial_state, config=config)

    assert "report" in result
    assert result["report"]["goal_type"] == "performance"
    assert result["report"]["findings_count"] >= 1
