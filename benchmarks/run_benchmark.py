"""EndpointIQ Industry-Standard Benchmark Suite

Multi-repo benchmark that measures:
  1. Token Efficiency  — full-dump tokens vs MRC-extracted tokens
  2. Recall            — % of ground-truth files found by MRC
  3. Precision         — % of MRC-selected files that are in ground truth
  4. Performance       — indexing throughput + extraction latency
  5. LLM Quality       — actual Groq API calls comparing analysis with/without EIQ

Runs across 3 codebases (demo-api, realworld-express, express-boilerplate)
and generates a publishable BENCHMARK_REPORT.md with statistical aggregates.

Usage:
    uv run python benchmarks/run_benchmark.py           # offline only
    uv run python benchmarks/run_benchmark.py --llm      # offline + LLM comparison
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Ensure project root is on sys.path ──────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import tiktoken

from endpointiq.context.extractor import GoalType, MRCExtractor
from endpointiq.core.config import load_config
from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.observation.indexer import ProjectIndexer


# ── Token counting ──────────────────────────────────────

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken cl100k_base encoding."""
    if not text:
        return 0
    return len(_get_encoder().encode(text))


# ── Full repo dump (baseline) ──────────────────────────

SOURCE_EXTENSIONS = {".ts", ".js", ".py", ".tsx", ".jsx", ".mjs", ".cjs"}
IGNORE_DIRS = {
    "node_modules", ".git", ".endpointiq", "dist", "build",
    "__pycache__", ".venv", "coverage", ".next",
}


def collect_full_source(project_root: Path) -> tuple[str, int]:
    """Collect all source files into one string (the 'naive baseline').

    Returns:
        (concatenated_source, file_count)
    """
    parts: list[str] = []
    file_count = 0
    for file_path in sorted(project_root.rglob("*")):
        if file_path.is_dir():
            continue
        if any(ignored in file_path.parts for ignored in IGNORE_DIRS):
            continue
        if file_path.suffix not in SOURCE_EXTENSIONS:
            continue
        try:
            content = file_path.read_text(errors="replace")
            rel = file_path.relative_to(project_root)
            parts.append(f"// === FILE: {rel} ===\n{content}")
            file_count += 1
        except OSError:
            continue
    return "\n\n".join(parts), file_count


# ── Data classes ────────────────────────────────────────


@dataclass
class EndpointResult:
    """Result for a single endpoint benchmark."""

    repo_name: str
    endpoint_name: str
    full_dump_tokens: int
    mrc_tokens: int
    token_reduction_pct: float
    nodes_in_graph: int
    nodes_selected: int
    extraction_time_ms: int
    mrc_files: list[str]  # files MRC selected
    # Ground-truth metrics (if available)
    recall: float | None = None
    precision: float | None = None
    f1: float | None = None
    has_ground_truth: bool = False


@dataclass
class RepoResult:
    """Aggregated result for one repository."""

    repo_name: str
    language: str
    total_loc: int
    total_files: int
    total_source_tokens: int
    endpoints_discovered: int
    indexing_time_ms: int
    indexing_throughput: float  # files/sec
    graph_nodes: int
    graph_edges: int
    endpoint_results: list[EndpointResult] = field(default_factory=list)


@dataclass
class LLMComparisonResult:
    """Result of comparing LLM analysis with/without EndpointIQ."""

    repo_name: str
    endpoint_name: str
    # Without EIQ
    without_prompt_tokens: int = 0
    without_completion_tokens: int = 0
    without_total_tokens: int = 0
    without_latency_ms: int = 0
    without_cost_usd: float = 0.0
    without_findings_count: int = 0
    without_failed: bool = False
    without_error: str = ""
    # With EIQ
    with_prompt_tokens: int = 0
    with_completion_tokens: int = 0
    with_total_tokens: int = 0
    with_latency_ms: int = 0
    with_cost_usd: float = 0.0
    with_findings_count: int = 0
    # Savings
    token_savings_pct: float = 0.0
    cost_savings_pct: float = 0.0
    latency_savings_pct: float = 0.0


@dataclass
class BenchmarkSuite:
    """Full benchmark suite results."""

    repos: list[RepoResult] = field(default_factory=list)
    llm_comparisons: list[LLMComparisonResult] = field(default_factory=list)
    timestamp: str = ""
    total_endpoints: int = 0


# ── Ground truth loading ────────────────────────────────


def load_ground_truth() -> dict:
    """Load the hand-labeled ground truth file."""
    gt_path = Path(__file__).parent / "ground_truth.json"
    if not gt_path.exists():
        print(f"  ⚠️  No ground truth file at {gt_path}")
        return {}
    return json.loads(gt_path.read_text())


def compute_recall_precision(
    mrc_files: list[str], expected_files: list[str]
) -> tuple[float, float, float]:
    """Compute recall, precision, F1 between MRC output and ground truth.

    Uses fuzzy file matching — matches if the ground-truth path is a
    suffix of any MRC-selected file path (handles relative path differences).
    """
    if not expected_files:
        return 1.0, 1.0, 1.0

    # Normalize: extract just the filename for matching since paths may differ
    def normalize(p: str) -> str:
        """Get the last 2 parts of a path for matching."""
        parts = Path(p).parts
        return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1] if parts else p

    expected_normalized = {normalize(f) for f in expected_files}
    selected_normalized = {normalize(f) for f in mrc_files}

    # Also try matching on just filename
    expected_basenames = {Path(f).name for f in expected_files}
    selected_basenames = {Path(f).name for f in mrc_files}

    # Use the more generous matching (path-suffix OR basename)
    hits_by_path = expected_normalized & selected_normalized
    hits_by_name = expected_basenames & selected_basenames

    true_positives = max(len(hits_by_path), len(hits_by_name))

    recall = true_positives / len(expected_files) if expected_files else 1.0
    precision = true_positives / len(mrc_files) if mrc_files else 0.0

    if precision + recall > 0:
        f1 = 2 * (precision * recall) / (precision + recall)
    else:
        f1 = 0.0

    return recall, precision, f1


# ── Core benchmark logic ───────────────────────────────


def benchmark_repo(
    repo_name: str,
    project_root: Path,
    ground_truth: dict,
) -> RepoResult:
    """Run the full benchmark on a single repository."""

    print(f"\n{'═' * 60}")
    print(f"  📦 Benchmarking: {repo_name}")
    print(f"  📂 Path: {project_root}")
    print(f"{'═' * 60}")

    # 1. Collect full source (baseline)
    print("\n  ⏳ Collecting full source (baseline)...")
    full_source, source_file_count = collect_full_source(project_root)
    full_dump_tokens = count_tokens(full_source)
    total_loc = full_source.count("\n")
    print(f"  ✅ {source_file_count} files, {total_loc:,} lines, {full_dump_tokens:,} tokens")

    # 2. Index with EndpointIQ
    print("\n  ⏳ Indexing with EndpointIQ...")
    config = load_config(project_root=project_root)
    graph = KnowledgeGraph()
    indexer = ProjectIndexer(config, graph)

    index_start = time.monotonic()
    stats = indexer.full_index()
    indexing_time_ms = int((time.monotonic() - index_start) * 1000)

    indexing_throughput = stats["files"] / (indexing_time_ms / 1000) if indexing_time_ms > 0 else 0

    # Detect language from stats
    language = "TypeScript" if stats.get("framework") == "express" else "JavaScript"
    if any(str(f).endswith(".ts") for f in project_root.rglob("*.ts")):
        language = "TypeScript"
    elif any(str(f).endswith(".js") for f in project_root.rglob("*.js")):
        language = "JavaScript"

    print(f"  ✅ Indexed {stats['files']} files → {stats['nodes']} nodes, {stats['edges']} edges")
    print(f"     Framework: {stats['framework']} (confidence: {stats['confidence']:.0%})")
    print(f"     Indexing time: {indexing_time_ms}ms ({indexing_throughput:.1f} files/sec)")
    print(f"     Endpoints discovered: {stats['endpoints']}")

    repo_result = RepoResult(
        repo_name=repo_name,
        language=language,
        total_loc=total_loc,
        total_files=source_file_count,
        total_source_tokens=full_dump_tokens,
        endpoints_discovered=stats["endpoints"],
        indexing_time_ms=indexing_time_ms,
        indexing_throughput=indexing_throughput,
        graph_nodes=stats["nodes"],
        graph_edges=stats["edges"],
    )

    # 3. Get ground truth for this repo
    repo_gt = ground_truth.get(repo_name, {}).get("endpoints", {})

    # 4. List discovered endpoints
    discovered = graph.list_endpoints()
    if not discovered:
        print("  ⚠️  No endpoints discovered — skipping MRC extraction")
        return repo_result

    print(f"\n  📋 Discovered endpoints ({len(discovered)}):")
    for ep in discovered:
        gt_marker = " 🎯" if ep["display_name"] in repo_gt else ""
        print(f"     • {ep['display_name']}{gt_marker}")

    # 5. MRC extraction for each endpoint
    extractor = MRCExtractor(graph, project_root)

    print(f"\n  ⏳ Running MRC extraction on {len(discovered)} endpoints...")

    for ep in discovered:
        ep_name = ep["display_name"]

        extract_start = time.monotonic()
        mrc_result = extractor.extract(ep_name, GoalType.FULL, token_budget=4000)
        extraction_time_ms = int((time.monotonic() - extract_start) * 1000)

        mrc_tokens = mrc_result.total_tokens
        mrc_files = list({s.file_path for s in mrc_result.snippets})

        reduction_pct = (
            (1 - mrc_tokens / full_dump_tokens) * 100
            if full_dump_tokens > 0
            else 0
        )

        ep_result = EndpointResult(
            repo_name=repo_name,
            endpoint_name=ep_name,
            full_dump_tokens=full_dump_tokens,
            mrc_tokens=mrc_tokens,
            token_reduction_pct=reduction_pct,
            nodes_in_graph=mrc_result.total_nodes_in_graph,
            nodes_selected=mrc_result.nodes_selected,
            extraction_time_ms=extraction_time_ms,
            mrc_files=mrc_files,
        )

        # Check ground truth
        if ep_name in repo_gt:
            expected = repo_gt[ep_name]["expected_files"]
            recall, precision, f1 = compute_recall_precision(mrc_files, expected)
            ep_result.recall = recall
            ep_result.precision = precision
            ep_result.f1 = f1
            ep_result.has_ground_truth = True

        repo_result.endpoint_results.append(ep_result)

    # Print summary for this repo
    results = repo_result.endpoint_results
    reductions = [r.token_reduction_pct for r in results if r.mrc_tokens > 0]
    latencies = [r.extraction_time_ms for r in results]
    gt_results = [r for r in results if r.has_ground_truth]

    print(f"\n  {'─' * 50}")
    print(f"  📊 {repo_name} Summary:")
    if reductions:
        print(f"     Token reduction: mean={statistics.mean(reductions):.1f}%, median={statistics.median(reductions):.1f}%")
    if latencies:
        sorted_lat = sorted(latencies)
        p95_idx = min(int(len(sorted_lat) * 0.95), len(sorted_lat) - 1)
        print(f"     Extraction latency: median={statistics.median(latencies):.0f}ms, P95={sorted_lat[p95_idx]}ms")
    if gt_results:
        recalls = [r.recall for r in gt_results if r.recall is not None]
        precisions = [r.precision for r in gt_results if r.precision is not None]
        f1s = [r.f1 for r in gt_results if r.f1 is not None]
        if recalls:
            print(f"     Recall: mean={statistics.mean(recalls):.2f}")
        if precisions:
            print(f"     Precision: mean={statistics.mean(precisions):.2f}")
        if f1s:
            print(f"     F1 Score: mean={statistics.mean(f1s):.2f}")

    return repo_result


# ── Report generation ───────────────────────────────────


def generate_report(suite: BenchmarkSuite) -> str:
    """Generate a markdown benchmark report."""

    lines: list[str] = []
    lines.append("# EndpointIQ Benchmark Report")
    lines.append("")
    lines.append(f"**Generated**: {suite.timestamp}")
    lines.append(f"**Total Repositories**: {len(suite.repos)}")
    lines.append(f"**Total Endpoints Benchmarked**: {suite.total_endpoints}")
    lines.append("")

    # ── Corpus Overview ──
    lines.append("## 1. Benchmark Corpus")
    lines.append("")
    lines.append("| Repository | Language | Files | LOC | Source Tokens | Endpoints |")
    lines.append("|-----------|----------|-------|-----|---------------|-----------|")
    for repo in suite.repos:
        lines.append(
            f"| {repo.repo_name} | {repo.language} | {repo.total_files} | "
            f"{repo.total_loc:,} | {repo.total_source_tokens:,} | {repo.endpoints_discovered} |"
        )
    lines.append("")

    # ── Indexing Performance ──
    lines.append("## 2. Indexing Performance")
    lines.append("")
    lines.append("| Repository | Files Indexed | Graph Nodes | Graph Edges | Time (ms) | Throughput (files/sec) |")
    lines.append("|-----------|--------------|-------------|-------------|-----------|----------------------|")
    for repo in suite.repos:
        lines.append(
            f"| {repo.repo_name} | {repo.total_files} | {repo.graph_nodes} | "
            f"{repo.graph_edges} | {repo.indexing_time_ms} | {repo.indexing_throughput:.1f} |"
        )
    lines.append("")

    # ── Token Efficiency (per-repo aggregate) ──
    lines.append("## 3. Token Efficiency (Primary Metric)")
    lines.append("")
    lines.append("*Compares 'full repo dump' tokens vs EndpointIQ's MRC-extracted tokens.*")
    lines.append("")
    lines.append("| Repository | Baseline Tokens | MRC Tokens (mean) | MRC Tokens (median) | Reduction % (mean) | Reduction % (median) |")
    lines.append("|-----------|----------------|-------------------|--------------------|--------------------|---------------------|")
    for repo in suite.repos:
        results = repo.endpoint_results
        mrc_tokens_list = [r.mrc_tokens for r in results if r.mrc_tokens > 0]
        reductions = [r.token_reduction_pct for r in results if r.mrc_tokens > 0]
        if mrc_tokens_list:
            lines.append(
                f"| {repo.repo_name} | {repo.total_source_tokens:,} | "
                f"{statistics.mean(mrc_tokens_list):,.0f} | {statistics.median(mrc_tokens_list):,.0f} | "
                f"{statistics.mean(reductions):.1f}% | {statistics.median(reductions):.1f}% |"
            )
        else:
            lines.append(f"| {repo.repo_name} | {repo.total_source_tokens:,} | N/A | N/A | N/A | N/A |")
    lines.append("")

    # ── Recall / Precision / F1 ──
    lines.append("## 4. Recall, Precision & F1 (Ground-Truth Validated)")
    lines.append("")
    lines.append("*Measured against hand-traced call chains. See `ground_truth.json`.*")
    lines.append("")
    lines.append("| Repository | Labeled Endpoints | Recall (mean) | Precision (mean) | F1 (mean) |")
    lines.append("|-----------|------------------|---------------|-----------------|-----------|")
    for repo in suite.repos:
        gt_results = [r for r in repo.endpoint_results if r.has_ground_truth]
        if gt_results:
            recalls = [r.recall for r in gt_results if r.recall is not None]
            precisions = [r.precision for r in gt_results if r.precision is not None]
            f1s = [r.f1 for r in gt_results if r.f1 is not None]
            lines.append(
                f"| {repo.repo_name} | {len(gt_results)} | "
                f"{statistics.mean(recalls):.2f} | {statistics.mean(precisions):.2f} | "
                f"{statistics.mean(f1s):.2f} |"
            )
        else:
            lines.append(f"| {repo.repo_name} | 0 | N/A | N/A | N/A |")
    lines.append("")

    # ── Extraction Latency ──
    lines.append("## 5. Extraction Latency")
    lines.append("")
    lines.append("| Repository | Endpoints | Mean (ms) | Median (ms) | P95 (ms) | Std Dev (ms) |")
    lines.append("|-----------|-----------|-----------|-------------|----------|-------------|")
    for repo in suite.repos:
        latencies = [r.extraction_time_ms for r in repo.endpoint_results]
        if latencies:
            sorted_lat = sorted(latencies)
            p95_idx = min(int(len(sorted_lat) * 0.95), len(sorted_lat) - 1)
            std_dev = statistics.stdev(latencies) if len(latencies) > 1 else 0
            lines.append(
                f"| {repo.repo_name} | {len(latencies)} | "
                f"{statistics.mean(latencies):.0f} | {statistics.median(latencies):.0f} | "
                f"{sorted_lat[p95_idx]} | {std_dev:.1f} |"
            )
    lines.append("")

    # ── Per-Endpoint Detail Table ──
    lines.append("## 6. Per-Endpoint Detail")
    lines.append("")
    lines.append("| Repository | Endpoint | Baseline Tokens | MRC Tokens | Reduction % | Nodes Selected | Latency (ms) | Recall | Precision | F1 |")
    lines.append("|-----------|----------|----------------|------------|-------------|---------------|-------------|--------|-----------|-----|")
    for repo in suite.repos:
        for ep in repo.endpoint_results:
            recall_str = f"{ep.recall:.2f}" if ep.recall is not None else "—"
            prec_str = f"{ep.precision:.2f}" if ep.precision is not None else "—"
            f1_str = f"{ep.f1:.2f}" if ep.f1 is not None else "—"
            lines.append(
                f"| {repo.repo_name} | `{ep.endpoint_name}` | {ep.full_dump_tokens:,} | "
                f"{ep.mrc_tokens:,} | {ep.token_reduction_pct:.1f}% | {ep.nodes_selected} | "
                f"{ep.extraction_time_ms} | {recall_str} | {prec_str} | {f1_str} |"
            )
    lines.append("")

    # ── Aggregate Statistics ──
    lines.append("## 7. Aggregate Statistics (Across All Repos)")
    lines.append("")
    all_reductions = [
        r.token_reduction_pct
        for repo in suite.repos
        for r in repo.endpoint_results
        if r.mrc_tokens > 0
    ]
    all_latencies = [
        r.extraction_time_ms
        for repo in suite.repos
        for r in repo.endpoint_results
    ]
    all_recalls = [
        r.recall
        for repo in suite.repos
        for r in repo.endpoint_results
        if r.recall is not None
    ]
    all_precisions = [
        r.precision
        for repo in suite.repos
        for r in repo.endpoint_results
        if r.precision is not None
    ]
    all_f1s = [
        r.f1
        for repo in suite.repos
        for r in repo.endpoint_results
        if r.f1 is not None
    ]

    lines.append("| Metric | Mean | Median | P95 | Std Dev | Min | Max |")
    lines.append("|--------|------|--------|-----|---------|-----|-----|")

    def stat_row(name: str, values: list[float]) -> str:
        if not values:
            return f"| {name} | N/A | N/A | N/A | N/A | N/A | N/A |"
        sorted_v = sorted(values)
        p95_idx = min(int(len(sorted_v) * 0.95), len(sorted_v) - 1)
        std = statistics.stdev(values) if len(values) > 1 else 0
        return (
            f"| {name} | {statistics.mean(values):.2f} | {statistics.median(values):.2f} | "
            f"{sorted_v[p95_idx]:.2f} | {std:.2f} | {min(values):.2f} | {max(values):.2f} |"
        )

    lines.append(stat_row("Token Reduction %", all_reductions))
    lines.append(stat_row("Extraction Latency (ms)", all_latencies))
    lines.append(stat_row("Recall", all_recalls))
    lines.append(stat_row("Precision", all_precisions))
    lines.append(stat_row("F1 Score", all_f1s))
    lines.append("")

    # ── Methodology ──
    lines.append("## 8. Methodology")
    lines.append("")
    lines.append("### Baseline")
    lines.append("- **Full Repo Dump**: All source files (`.ts`, `.js`, `.py`) concatenated into a single string")
    lines.append("- Token count measured with `tiktoken` (cl100k_base encoding, used by GPT-4/Llama-class models)")
    lines.append("- Directories excluded: `node_modules`, `.git`, `dist`, `build`, `__pycache__`")
    lines.append("")
    lines.append("### EndpointIQ (MRC Extraction)")
    lines.append("- `ProjectIndexer.full_index()` → builds the full knowledge graph")
    lines.append("- `MRCExtractor.extract(endpoint, GoalType.FULL, token_budget=4000)`")
    lines.append("- Pipeline: BFS subgraph → Personalized PageRank → Goal boosting → Greedy selection")
    lines.append("")
    lines.append("### Ground Truth")
    lines.append("- Hand-labeled call chains for selected endpoints across all 3 repositories")
    lines.append("- Recall = |expected ∩ selected| / |expected|")
    lines.append("- Precision = |expected ∩ selected| / |selected|")
    lines.append("- F1 = 2 × (Precision × Recall) / (Precision + Recall)")
    lines.append("")
    lines.append("### Statistical Reporting")
    lines.append("- All metrics reported with Mean, Median, P95, Std Dev")
    lines.append("- P95 = 95th percentile (near-worst-case performance)")
    lines.append("")

    return "\n".join(lines)


# ── LLM Comparison Mode ────────────────────────────────

# Groq config
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = "qwen/qwen3.8-27b"
COST_PER_1M_INPUT = 0.20
COST_PER_1M_OUTPUT = 0.60


def run_llm_call(prompt: str, context: str) -> dict:
    """Make a single Groq LLM call and return metrics + response."""
    from langchain_groq import ChatGroq
    from pydantic import SecretStr

    llm = ChatGroq(
        model=MODEL,
        temperature=0.0,
        api_key=SecretStr(GROQ_API_KEY),
    )

    messages = [
        {"role": "system", "content": (
            "You are a security analyst. Analyze the provided code for security vulnerabilities. "
            "Return a JSON array of findings. Each finding must have: severity (critical/high/medium/low/info), "
            "title, description, file_path (if known), recommendation."
        )},
        {"role": "user", "content": f"{prompt}\n\nCode context:\n```\n{context}\n```"},
    ]

    start = time.monotonic()
    response = llm.invoke(messages)
    latency_ms = int((time.monotonic() - start) * 1000)

    content = response.content if isinstance(response.content, str) else str(response.content)

    full_prompt = messages[0]["content"] + messages[1]["content"]
    prompt_tokens = count_tokens(full_prompt)
    completion_tokens = count_tokens(content)

    # Try to count findings
    findings_count = 0
    try:
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            findings = json.loads(json_match.group())
            findings_count = len(findings)
    except (json.JSONDecodeError, AttributeError):
        # Count by looking for severity markers
        findings_count = len(re.findall(r'"severity"', content, re.IGNORECASE))

    return {
        "content": content,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latency_ms": latency_ms,
        "cost_usd": (prompt_tokens * COST_PER_1M_INPUT + completion_tokens * COST_PER_1M_OUTPUT) / 1_000_000,
        "findings_count": findings_count,
    }


def run_llm_comparison(
    repo_name: str,
    project_root: Path,
    endpoint_name: str,
    full_source: str,
    mrc_context: str,
) -> LLMComparisonResult:
    """Compare LLM analysis with full dump vs MRC context."""

    result = LLMComparisonResult(
        repo_name=repo_name,
        endpoint_name=endpoint_name,
    )

    prompt = f"Analyze the endpoint '{endpoint_name}' for security vulnerabilities."

    # ── Without EIQ (full dump) ──
    print(f"     ⏳ Calling Groq WITHOUT EndpointIQ (full source)...")
    full_tokens = count_tokens(full_source)

    # Truncate if needed (Groq context limit ~131K)
    max_context = 120_000
    context_without = full_source
    if full_tokens > max_context:
        ratio = max_context / full_tokens
        context_without = full_source[:int(len(full_source) * ratio)]
        print(f"     ⚠️  Truncated to ~{max_context:,} tokens")

    try:
        without_result = run_llm_call(prompt, context_without)
        result.without_prompt_tokens = without_result["prompt_tokens"]
        result.without_completion_tokens = without_result["completion_tokens"]
        result.without_total_tokens = without_result["total_tokens"]
        result.without_latency_ms = without_result["latency_ms"]
        result.without_cost_usd = without_result["cost_usd"]
        result.without_findings_count = without_result["findings_count"]
        print(f"     ✅ {without_result['total_tokens']:,} tokens, {without_result['latency_ms']:,}ms, {without_result['findings_count']} findings")
    except Exception as e:
        result.without_failed = True
        result.without_error = str(e)[:200]
        result.without_prompt_tokens = full_tokens
        result.without_cost_usd = (full_tokens * COST_PER_1M_INPUT) / 1_000_000
        print(f"     ❌ FAILED: {str(e)[:100]}")
        print(f"     ⚠️  Full codebase exceeds Groq context window!")

    # ── With EIQ (MRC context) ──
    print(f"     ⏳ Calling Groq WITH EndpointIQ (MRC context)...")
    try:
        with_result = run_llm_call(prompt, mrc_context)
        result.with_prompt_tokens = with_result["prompt_tokens"]
        result.with_completion_tokens = with_result["completion_tokens"]
        result.with_total_tokens = with_result["total_tokens"]
        result.with_latency_ms = with_result["latency_ms"]
        result.with_cost_usd = with_result["cost_usd"]
        result.with_findings_count = with_result["findings_count"]
        print(f"     ✅ {with_result['total_tokens']:,} tokens, {with_result['latency_ms']:,}ms, {with_result['findings_count']} findings")
    except Exception as e:
        print(f"     ❌ WITH EIQ also failed: {e}")

    # ── Compute savings ──
    if result.without_prompt_tokens > 0:
        result.token_savings_pct = (
            (result.without_prompt_tokens - result.with_prompt_tokens)
            / result.without_prompt_tokens * 100
        )
    if result.without_cost_usd > 0:
        result.cost_savings_pct = (
            (result.without_cost_usd - result.with_cost_usd)
            / result.without_cost_usd * 100
        )
    if result.without_latency_ms > 0:
        result.latency_savings_pct = (
            (result.without_latency_ms - result.with_latency_ms)
            / result.without_latency_ms * 100
        )

    return result


# ── Main ────────────────────────────────────────────────


def main():
    enable_llm = "--llm" in sys.argv
    print("=" * 60)
    print("  EndpointIQ Industry-Standard Benchmark Suite")
    print("=" * 60)

    # Define the repos to benchmark
    repos = {
        "demo-api": PROJECT_ROOT / "examples" / "demo-api",
        "realworld-express": PROJECT_ROOT / "benchmarks" / "repos" / "realworld-express",
        "express-boilerplate": PROJECT_ROOT / "benchmarks" / "repos" / "express-boilerplate",
    }

    # External clone URLs if repos not yet present
    repo_urls = {
        "realworld-express": "https://github.com/gothinkster/node-express-realworld-example-app.git",
        "express-boilerplate": "https://github.com/hagopj13/node-express-boilerplate.git",
    }

    # Verify all repos exist (clone external repos if missing)
    import subprocess
    for name, path in repos.items():
        if not path.exists():
            if name in repo_urls:
                print(f"  ⏳ Cloning {name} for benchmark...")
                path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "clone", "--depth", "1", repo_urls[name], str(path)], check=True)
            else:
                print(f"  ❌ Repo not found: {name} at {path}")
                sys.exit(1)
        print(f"  ✅ {name}: {path}")

    # Load ground truth
    ground_truth = load_ground_truth()
    gt_count = sum(
        len(repo_data.get("endpoints", {}))
        for repo_data in ground_truth.values()
        if isinstance(repo_data, dict)
    )
    print(f"\n  📋 Ground truth: {gt_count} labeled endpoints across {len(ground_truth)} repos")

    # Run benchmarks
    suite = BenchmarkSuite(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )

    for name, path in repos.items():
        repo_result = benchmark_repo(name, path, ground_truth)
        suite.repos.append(repo_result)

    suite.total_endpoints = sum(len(r.endpoint_results) for r in suite.repos)

    # ── LLM Comparison (if enabled) ──
    if enable_llm:
        if not GROQ_API_KEY:
            print("\n  ❌ GROQ_API_KEY not found in .env — skipping LLM comparison")
        else:
            print(f"\n{'═' * 60}")
            print("  🤖 LLM Quality Comparison (Groq API)")
            print(f"{'═' * 60}")
            print(f"  Model: {MODEL}")

            # Pick one representative endpoint per repo for LLM comparison
            llm_targets = {
                "demo-api": "DELETE /:id",
                "realworld-express": "POST /users",
                "express-boilerplate": "POST /login",
            }

            for repo in suite.repos:
                target_ep = llm_targets.get(repo.repo_name)
                if not target_ep:
                    continue

                print(f"\n  📦 {repo.repo_name} → {target_ep}")

                project_path = repos[repo.repo_name]
                full_source, _ = collect_full_source(project_path)

                # Get MRC context for this endpoint
                config = load_config(project_root=project_path)
                graph = KnowledgeGraph()
                indexer = ProjectIndexer(config, graph)
                indexer.full_index()
                extractor = MRCExtractor(graph, project_path)
                mrc_result = extractor.extract(target_ep, GoalType.FULL, token_budget=4000)
                mrc_context = mrc_result.combined_context

                llm_result = run_llm_comparison(
                    repo.repo_name, project_path, target_ep,
                    full_source, mrc_context,
                )
                suite.llm_comparisons.append(llm_result)

                print(f"     📊 Token savings: {llm_result.token_savings_pct:.1f}%")
                print(f"     📊 Cost savings: {llm_result.cost_savings_pct:.1f}%")
                if llm_result.without_latency_ms > 0:
                    print(f"     📊 Latency savings: {llm_result.latency_savings_pct:.1f}%")

    # Generate report
    print(f"\n{'═' * 60}")
    print("  📝 Generating Benchmark Report...")
    print(f"{'═' * 60}")

    report_md = generate_report(suite)

    # Add LLM comparison section if we have results
    if suite.llm_comparisons:
        report_md += generate_llm_report_section(suite.llm_comparisons)

    report_path = Path(__file__).parent / "BENCHMARK_REPORT.md"
    report_path.write_text(report_md)
    print(f"\n  ✅ Report saved to: {report_path}")

    # Also save raw JSON results
    raw_results = {
        "timestamp": suite.timestamp,
        "total_endpoints": suite.total_endpoints,
        "repos": [],
    }
    for repo in suite.repos:
        repo_data = {
            "name": repo.repo_name,
            "language": repo.language,
            "total_loc": repo.total_loc,
            "total_files": repo.total_files,
            "total_source_tokens": repo.total_source_tokens,
            "endpoints_discovered": repo.endpoints_discovered,
            "indexing_time_ms": repo.indexing_time_ms,
            "indexing_throughput": repo.indexing_throughput,
            "graph_nodes": repo.graph_nodes,
            "graph_edges": repo.graph_edges,
            "endpoints": [],
        }
        for ep in repo.endpoint_results:
            ep_data = {
                "name": ep.endpoint_name,
                "full_dump_tokens": ep.full_dump_tokens,
                "mrc_tokens": ep.mrc_tokens,
                "token_reduction_pct": round(ep.token_reduction_pct, 2),
                "nodes_selected": ep.nodes_selected,
                "extraction_time_ms": ep.extraction_time_ms,
                "mrc_files": ep.mrc_files,
                "recall": ep.recall,
                "precision": ep.precision,
                "f1": ep.f1,
            }
            repo_data["endpoints"].append(ep_data)
        raw_results["repos"].append(repo_data)

    json_path = Path(__file__).parent / "benchmark_results.json"
    json_path.write_text(json.dumps(raw_results, indent=2))
    print(f"  ✅ Raw results saved to: {json_path}")

    # Print headline numbers
    all_reductions = [
        r.token_reduction_pct
        for repo in suite.repos
        for r in repo.endpoint_results
        if r.mrc_tokens > 0
    ]
    all_f1s = [
        r.f1
        for repo in suite.repos
        for r in repo.endpoint_results
        if r.f1 is not None
    ]
    all_latencies = [
        r.extraction_time_ms
        for repo in suite.repos
        for r in repo.endpoint_results
    ]

    print(f"\n  {'═' * 50}")
    print(f"  🏆 HEADLINE RESULTS")
    print(f"  {'═' * 50}")
    if all_reductions:
        print(f"  Token Reduction:  {statistics.mean(all_reductions):.1f}% (mean across {len(all_reductions)} endpoints)")
    if all_f1s:
        print(f"  F1 Score:         {statistics.mean(all_f1s):.2f} (mean across {len(all_f1s)} labeled endpoints)")
    if all_latencies:
        sorted_lat = sorted(all_latencies)
        p95_idx = min(int(len(sorted_lat) * 0.95), len(sorted_lat) - 1)
        print(f"  Extraction P95:   {sorted_lat[p95_idx]}ms")
    print(f"  Endpoints:        {suite.total_endpoints} across {len(suite.repos)} repos")
    if suite.llm_comparisons:
        avg_token_save = statistics.mean([c.token_savings_pct for c in suite.llm_comparisons])
        avg_cost_save = statistics.mean([c.cost_savings_pct for c in suite.llm_comparisons])
        print(f"  LLM Token Save:   {avg_token_save:.1f}% (actual Groq API calls)")
        print(f"  LLM Cost Save:    {avg_cost_save:.1f}%")
    print()


def generate_llm_report_section(comparisons: list[LLMComparisonResult]) -> str:
    """Generate the LLM comparison section for the report."""
    lines: list[str] = []
    lines.append("")
    lines.append("## 9. LLM Quality Comparison (End-to-End)")
    lines.append("")
    lines.append(f"*Actual Groq API calls comparing full-dump vs MRC context. Model: `{MODEL}`*")
    lines.append("")
    lines.append("| Repository | Endpoint | Metric | Without EIQ | With EIQ | Savings |")
    lines.append("|-----------|----------|--------|-------------|----------|---------|")

    for c in comparisons:
        failed_marker = " ❌" if c.without_failed else ""
        lines.append(
            f"| {c.repo_name} | `{c.endpoint_name}` | Prompt Tokens | "
            f"{c.without_prompt_tokens:,}{failed_marker} | {c.with_prompt_tokens:,} | "
            f"{c.token_savings_pct:.1f}% |"
        )
        lines.append(
            f"| | | Completion Tokens | "
            f"{c.without_completion_tokens:,} | {c.with_completion_tokens:,} | — |"
        )
        lines.append(
            f"| | | Latency | "
            f"{c.without_latency_ms:,}ms | {c.with_latency_ms:,}ms | "
            f"{c.latency_savings_pct:.1f}% |"
        )
        lines.append(
            f"| | | Cost | "
            f"${c.without_cost_usd:.6f} | ${c.with_cost_usd:.6f} | "
            f"{c.cost_savings_pct:.1f}% |"
        )
        lines.append(
            f"| | | Findings | "
            f"{c.without_findings_count} | {c.with_findings_count} | — |"
        )

    lines.append("")

    # Summary
    if comparisons:
        avg_token = statistics.mean([c.token_savings_pct for c in comparisons])
        avg_cost = statistics.mean([c.cost_savings_pct for c in comparisons])
        latency_values = [c.latency_savings_pct for c in comparisons if c.without_latency_ms > 0]
        avg_latency = statistics.mean(latency_values) if latency_values else 0
        lines.append("### Summary")
        lines.append("")
        lines.append(f"| Metric | Mean Savings |")
        lines.append(f"|--------|-------------|")
        lines.append(f"| Token Savings | {avg_token:.1f}% |")
        lines.append(f"| Cost Savings | {avg_cost:.1f}% |")
        if avg_latency:
            lines.append(f"| Latency Savings | {avg_latency:.1f}% |")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
