"""LangGraph-based multi-agent analysis system.

Implements a 4-node StateGraph:
  START → Planner → Executor → Evaluator → Reporter → END
                        ↑                     |
                        └─────────────────────┘
                         (re-plan if confidence < 0.7)

Each node is a specialized agent with its own prompt and responsibility.
The graph supports checkpointing via LangGraph's MemorySaver.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)


# ── Agent State ───────────────────────────────────────


class AgentState(TypedDict, total=False):
    """State that flows through the LangGraph StateGraph.

    Each node reads from and writes to this shared state dict.
    """

    # Input
    endpoint_name: str
    goal_type: str
    token_budget: int

    # Planner output
    plan: dict[str, Any]
    planned_steps: list[dict[str, Any]]

    # Executor output
    results: list[dict[str, Any]]
    code_context: str
    token_usage: dict[str, int]

    # Evaluator output
    confidence: float
    gaps: list[str]
    evaluation_reasoning: str

    # Reporter output
    report: dict[str, Any]

    # Control flow
    iteration: int
    max_iterations: int
    error: str | None


# ── Node Functions ────────────────────────────────────


def planner_node(state: AgentState) -> dict[str, Any]:
    """Planner node: decomposes the goal into analysis sub-tasks.

    On first run: creates a fresh plan based on goal type.
    On re-plan: reads evaluator gaps and adds compensating steps.
    """
    goal_type = state.get("goal_type", "full")
    endpoint = state.get("endpoint_name", "")
    iteration = state.get("iteration", 1)
    gaps = state.get("gaps", [])

    logger.info(f"Planner: iteration={iteration}, endpoint={endpoint}, goal={goal_type}")

    # Define analysis checks based on goal type
    if goal_type == "security":
        base_steps = [
            {"check": "auth_check", "description": "Verify authentication middleware is present and correctly applied"},
            {"check": "input_validation", "description": "Check for input validation and sanitization"},
            {"check": "injection_scan", "description": "Scan for SQL injection, XSS, and command injection vulnerabilities"},
            {"check": "access_control", "description": "Verify authorization and RBAC enforcement"},
        ]
    elif goal_type == "performance":
        base_steps = [
            {"check": "query_analysis", "description": "Analyze database query patterns for N+1 issues"},
            {"check": "cache_analysis", "description": "Check for caching opportunities and missing cache layers"},
            {"check": "payload_analysis", "description": "Analyze response payload sizes and pagination"},
        ]
    elif goal_type == "architecture":
        base_steps = [
            {"check": "layer_violations", "description": "Check for architectural layer violations (controller calling repository directly)"},
            {"check": "dependency_analysis", "description": "Analyze dependency graph for circular dependencies"},
            {"check": "separation_of_concerns", "description": "Verify proper separation of concerns"},
        ]
    else:  # full
        base_steps = [
            {"check": "security_review", "description": "Comprehensive security analysis"},
            {"check": "performance_review", "description": "Performance and optimization analysis"},
            {"check": "architecture_review", "description": "Architectural quality assessment"},
        ]

    # On re-plan, add gap-filling steps
    if iteration > 1 and gaps:
        for gap in gaps:
            base_steps.append({
                "check": f"gap_fill_{iteration}",
                "description": f"Address gap: {gap}",
            })

    plan = {
        "endpoint": endpoint,
        "goal": goal_type,
        "iteration": iteration,
        "steps": base_steps,
        "total_steps": len(base_steps),
    }

    return {
        "plan": plan,
        "planned_steps": base_steps,
        "iteration": iteration,
    }


def executor_node(state: AgentState) -> dict[str, Any]:
    """Executor node: runs the planned analysis steps.

    For each step:
    1. Extracts context using MRC (via tool)
    2. Calls the LLM for analysis
    3. Collects structured findings
    """
    from endpointiq.agent.tools import _tool_context

    endpoint = state.get("endpoint_name", "")
    goal_type = state.get("goal_type", "full")
    planned_steps = state.get("planned_steps", [])
    token_budget = state.get("token_budget", 4000)

    logger.info(f"Executor: running {len(planned_steps)} steps for {endpoint}")

    results: list[dict[str, Any]] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    code_context = ""

    # Step 1: Extract context via MRC
    graph = _tool_context.get("graph")
    extractor = _tool_context.get("extractor")
    if extractor:
        from endpointiq.context.extractor import GoalType
        try:
            goal = GoalType(goal_type)
        except ValueError:
            goal = GoalType.FULL
        mrc_result = extractor.extract(endpoint, goal, token_budget)
        code_context = mrc_result.combined_context
    elif graph:
        # Fallback: get endpoint info from graph
        node_id = graph.lookup_endpoint(endpoint)
        if node_id:
            attrs = graph.get_node(node_id)
            code_context = json.dumps(attrs, default=str)

    # Step 2: Run LLM analysis for each step
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY", "")
    use_llm = bool(api_key and api_key != "gsk_your_key_here")

    for step in planned_steps:
        check_name = step.get("check", "unknown")
        description = step.get("description", "")
        start_time = time.monotonic()

        if use_llm:
            try:
                finding = _run_llm_analysis(
                    endpoint, goal_type, check_name, description,
                    code_context, api_key
                )
                prompt_tokens = finding.pop("_prompt_tokens", 0)
                completion_tokens = finding.pop("_completion_tokens", 0)
                total_prompt_tokens += prompt_tokens
                total_completion_tokens += completion_tokens
                results.append(finding)
            except Exception as e:
                logger.warning(f"LLM analysis failed for {check_name}: {e}")
                results.append(_static_analysis(check_name, description, code_context))
        else:
            # Static analysis fallback (no API key)
            results.append(_static_analysis(check_name, description, code_context))

        elapsed = int((time.monotonic() - start_time) * 1000)
        results[-1]["latency_ms"] = elapsed

    token_usage = {
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "total_tokens": total_prompt_tokens + total_completion_tokens,
    }

    return {
        "results": results,
        "code_context": code_context,
        "token_usage": token_usage,
    }


def evaluator_node(state: AgentState) -> dict[str, Any]:
    """Evaluator node: scores confidence and identifies gaps.

    Scoring criteria:
    - All planned checks returned results: +0.3
    - Findings have file paths: +0.2
    - Recommendations are present: +0.2
    - Output is well-structured: +0.2
    - No empty results: +0.1
    """
    results = state.get("results", [])
    planned_steps = state.get("planned_steps", [])

    confidence = 0.0
    gaps: list[str] = []

    # Check 1: All planned checks completed
    if len(results) >= len(planned_steps):
        confidence += 0.3
    else:
        gaps.append(f"Only {len(results)}/{len(planned_steps)} checks completed")

    # Check 2: Findings have file paths
    findings_with_paths = sum(
        1 for r in results
        if r.get("findings") and any(
            f.get("file_path") for f in r.get("findings", [])
        )
    )
    if findings_with_paths > 0:
        confidence += 0.2
    else:
        gaps.append("Findings lack specific file path references")

    # Check 3: Recommendations present
    has_recommendations = any(
        r.get("findings") and any(
            f.get("recommendation") for f in r.get("findings", [])
        )
        for r in results
    )
    if has_recommendations:
        confidence += 0.2
    else:
        gaps.append("Missing actionable recommendations")

    # Check 4: Well-structured output
    well_structured = all(
        isinstance(r, dict) and "check" in r
        for r in results
    )
    if well_structured:
        confidence += 0.2

    # Check 5: No empty results
    non_empty = all(
        r.get("findings") or r.get("summary")
        for r in results
    )
    if non_empty:
        confidence += 0.1
    else:
        gaps.append("Some checks returned empty results")

    reasoning = (
        f"Confidence: {confidence:.2f}. "
        f"{len(results)} results from {len(planned_steps)} planned steps. "
        f"Gaps: {gaps if gaps else 'none'}"
    )

    logger.info(f"Evaluator: confidence={confidence:.2f}, gaps={gaps}")

    return {
        "confidence": confidence,
        "gaps": gaps,
        "evaluation_reasoning": reasoning,
    }


def reporter_node(state: AgentState) -> dict[str, Any]:
    """Reporter node: compiles results into a final report.

    Deduplicates findings, ranks by severity, adds metrics.
    """
    results = state.get("results", [])
    endpoint = state.get("endpoint_name", "")
    goal_type = state.get("goal_type", "full")
    confidence = state.get("confidence", 0.0)
    iteration = state.get("iteration", 1)
    token_usage = state.get("token_usage", {})

    # Collect all findings
    all_findings: list[dict[str, Any]] = []
    for result in results:
        for finding in result.get("findings", []):
            all_findings.append(finding)

    # Deduplicate by title
    seen_titles: set[str] = set()
    unique_findings: list[dict[str, Any]] = []
    for f in all_findings:
        title = f.get("title", "")
        if title not in seen_titles:
            seen_titles.add(title)
            unique_findings.append(f)

    # Sort by severity
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    unique_findings.sort(
        key=lambda f: severity_order.get(f.get("severity", "INFO"), 5)
    )

    # Build summary
    severity_counts: dict[str, int] = {}
    for f in unique_findings:
        sev = f.get("severity", "INFO")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    summary = (
        f"{goal_type.title()} analysis of {endpoint}: "
        f"{len(unique_findings)} findings "
        f"({', '.join(f'{c} {s}' for s, c in severity_counts.items())}). "
        f"Confidence: {confidence:.0%}."
    )

    # Extract recommendations
    recommendations = [
        f.get("recommendation", "")
        for f in unique_findings
        if f.get("recommendation")
    ]

    report = {
        "summary": summary,
        "endpoint": endpoint,
        "goal_type": goal_type,
        "confidence": confidence,
        "iterations": iteration,
        "findings": unique_findings,
        "findings_count": len(unique_findings),
        "recommendations": recommendations,
        "severity_counts": severity_counts,
        "token_usage": token_usage,
    }

    logger.info(f"Reporter: {len(unique_findings)} findings, confidence={confidence:.2f}")

    return {"report": report}


# ── Routing Logic ─────────────────────────────────────


def should_replan(state: AgentState) -> str:
    """Conditional edge: decide whether to re-plan or report.

    Re-plans if:
    - Confidence < 0.7 AND
    - Iteration < max_iterations (default 3)
    """
    confidence = state.get("confidence", 0.0)
    iteration = state.get("iteration", 1)
    max_iter = state.get("max_iterations", 3)

    if confidence < 0.7 and iteration < max_iter:
        logger.info(f"Re-planning: confidence={confidence:.2f}, iteration={iteration}")
        return "replan"
    return "report"


def increment_iteration(state: AgentState) -> dict[str, Any]:
    """Increment the iteration counter for re-planning."""
    return {"iteration": state.get("iteration", 1) + 1}


# ── Graph Construction ────────────────────────────────


def build_agent_graph(checkpointer: Any | None = None) -> Any:
    """Build the LangGraph StateGraph for the analysis agent.

    Returns a compiled graph ready for invocation.

    Args:
        checkpointer: Optional LangGraph checkpointer (e.g. MemorySaver).
    """
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("reporter", reporter_node)
    graph.add_node("increment", increment_iteration)

    # Add edges
    graph.set_entry_point("planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "evaluator")

    # Conditional: evaluator → reporter OR evaluator → increment → planner
    graph.add_conditional_edges(
        "evaluator",
        should_replan,
        {
            "report": "reporter",
            "replan": "increment",
        },
    )
    graph.add_edge("increment", "planner")
    graph.add_edge("reporter", END)

    # Compile with optional checkpointing
    if checkpointer:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


def create_agent(with_checkpointing: bool = True) -> tuple[Any, Any | None]:
    """Create the analysis agent with optional checkpointing.

    Returns:
        Tuple of (compiled_graph, checkpointer).
    """
    checkpointer = MemorySaver() if with_checkpointing else None
    compiled = build_agent_graph(checkpointer)
    return compiled, checkpointer


# ── Helper Functions ──────────────────────────────────


def _run_llm_analysis(
    endpoint: str,
    goal_type: str,
    check_name: str,
    description: str,
    code_context: str,
    api_key: str,
) -> dict[str, Any]:
    """Run a single LLM analysis step via Groq."""
    from langchain_groq import ChatGroq
    from pydantic import SecretStr

    from endpointiq.agent.prompts import EXECUTOR_PROMPT

    llm = ChatGroq(
        model="qwen/qwen3.6-27b",
        temperature=0.0,
        api_key=SecretStr(api_key),
    )

    messages = EXECUTOR_PROMPT.format_messages(
        endpoint_name=endpoint,
        goal_type=goal_type,
        check_type=check_name,
        code_context=code_context[:3000],  # Truncate for safety
    )

    response = llm.invoke(messages)
    content = response.content if isinstance(response.content, str) else str(response.content)

    # Track token usage
    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = 0
    completion_tokens = 0
    if usage:
        prompt_tokens = getattr(usage, "input_tokens", 0) or 0
        completion_tokens = getattr(usage, "output_tokens", 0) or 0

    # Try to parse JSON from response
    findings = _parse_findings(content)

    return {
        "check": check_name,
        "description": description,
        "findings": findings,
        "summary": content[:500],
        "_prompt_tokens": prompt_tokens,
        "_completion_tokens": completion_tokens,
    }


def _static_analysis(
    check_name: str, description: str, code_context: str
) -> dict[str, Any]:
    """Fallback static analysis when LLM is not available.

    Performs basic pattern matching on the code context.
    """
    findings: list[dict[str, Any]] = []

    context_lower = code_context.lower()

    if "security" in check_name or "auth" in check_name:
        if "authMiddleware" not in code_context and "auth" not in context_lower:
            findings.append({
                "severity": "HIGH",
                "title": "Missing Authentication",
                "description": "No authentication middleware detected on this endpoint.",
                "file_path": "",
                "line_number": 0,
                "recommendation": "Add authentication middleware (e.g., authMiddleware) to protect this endpoint.",
            })
        else:
            findings.append({
                "severity": "INFO",
                "title": "Authentication Present",
                "description": "Authentication middleware detected.",
                "file_path": "",
                "line_number": 0,
                "recommendation": "Verify token validation logic is robust.",
            })

    if ("validation" in check_name or "input" in check_name) and "validate" not in context_lower:
        findings.append({
            "severity": "MEDIUM",
            "title": "Missing Input Validation",
            "description": "No input validation middleware detected.",
            "file_path": "",
            "line_number": 0,
            "recommendation": "Add request body validation using a schema validator.",
        })

    if "injection" in check_name and ("query" in context_lower or "sql" in context_lower):
        findings.append({
            "severity": "MEDIUM",
            "title": "Potential Injection Risk",
            "description": "Database query detected — verify parameterized queries.",
            "file_path": "",
            "line_number": 0,
            "recommendation": "Use parameterized queries or an ORM to prevent SQL injection.",
        })

    if ("performance" in check_name or "query" in check_name) and (
        "findAll" in code_context or "find(" in code_context
    ):
        findings.append({
            "severity": "LOW",
            "title": "Unbounded Query",
            "description": "Database query may return unbounded results.",
            "file_path": "",
            "line_number": 0,
            "recommendation": "Add pagination (limit/offset) to prevent large result sets.",
        })

    if "architecture" in check_name or "layer" in check_name:
        findings.append({
            "severity": "INFO",
            "title": "Architecture Review",
            "description": f"Reviewing architectural patterns for: {description}",
            "file_path": "",
            "line_number": 0,
            "recommendation": "Ensure controllers delegate to services, not directly to repositories.",
        })

    if not findings:
        findings.append({
            "severity": "INFO",
            "title": f"Check: {check_name}",
            "description": description,
            "file_path": "",
            "line_number": 0,
            "recommendation": "No issues detected in static analysis.",
        })

    return {
        "check": check_name,
        "description": description,
        "findings": findings,
        "summary": f"Static analysis for {check_name}: {len(findings)} findings",
    }


def _parse_findings(content: str) -> list[dict[str, Any]]:
    """Try to parse structured findings from LLM response."""
    try:
        # Try direct JSON parse
        data = json.loads(content)
        if isinstance(data, dict) and "findings" in data:
            return list(data["findings"])
        if isinstance(data, list):
            return list(data)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code block
    import re
    json_match = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', content, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data, dict) and "findings" in data:
                return list(data["findings"])
            if isinstance(data, list):
                return list(data)
        except json.JSONDecodeError:
            pass

    # Fallback: wrap the content as a single finding
    return [{
        "severity": "INFO",
        "title": "LLM Analysis Result",
        "description": content[:500],
        "file_path": "",
        "line_number": 0,
        "recommendation": "",
    }]
