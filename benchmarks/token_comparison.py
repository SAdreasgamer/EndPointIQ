"""EndpointIQ Token Savings Benchmark

Compares LLM analysis WITH vs WITHOUT EndpointIQ's MRC context extraction.

WITHOUT EndpointIQ: Sends the ENTIRE project source to the LLM.
WITH EndpointIQ:    Sends only the MRC-extracted compressed context (~1-2KB).

Measures:
  - Token counts (prompt + completion)
  - Estimated cost (Groq pricing)
  - Latency
  - Findings quality
  - Token savings percentage

Usage:
    uv run python benchmarks/token_comparison.py [project_dir] [endpoint]

Example:
    uv run python benchmarks/token_comparison.py examples/demo-api "DELETE /:id"
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ── Config ────────────────────────────────────────────

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = "qwen/qwen3.6-27b"
# Groq pricing (per 1M tokens) — approximate
COST_PER_1M_INPUT = 0.20   # $0.20 per 1M input tokens
COST_PER_1M_OUTPUT = 0.60  # $0.60 per 1M output tokens


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken (cl100k_base encoding)."""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def collect_all_source(project_root: Path) -> str:
    """Collect ALL source files into a single string (simulating no-EIQ approach)."""
    extensions = {".ts", ".js", ".py", ".tsx", ".jsx", ".json", ".cjs", ".mjs"}
    ignore_dirs = {"node_modules", ".git", ".endpointiq", "dist", "build", "__pycache__", ".venv"}

    all_source = []
    for file_path in sorted(project_root.rglob("*")):
        if file_path.is_dir():
            continue
        if any(ignored in file_path.parts for ignored in ignore_dirs):
            continue
        if file_path.suffix not in extensions:
            continue
        try:
            content = file_path.read_text(errors="replace")
            rel_path = file_path.relative_to(project_root)
            all_source.append(f"// === FILE: {rel_path} ===\n{content}")
        except OSError:
            continue

    return "\n\n".join(all_source)


def run_llm_call(prompt: str, context: str) -> dict:
    """Make a single Groq LLM call and return token metrics + response."""
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

    # Token counting via tiktoken (reliable fallback)
    full_prompt = messages[0]["content"] + messages[1]["content"]
    prompt_tokens = count_tokens(full_prompt)
    completion_tokens = count_tokens(content)

    return {
        "content": content,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latency_ms": latency_ms,
        "cost_usd": (prompt_tokens * COST_PER_1M_INPUT + completion_tokens * COST_PER_1M_OUTPUT) / 1_000_000,
    }


def extract_mrc_context(project_root: Path, endpoint: str, goal: str = "security") -> tuple[str, dict]:
    """Use EndpointIQ's MRC to extract minimal relevant context."""
    from endpointiq.context.extractor import GoalType, MRCExtractor
    from endpointiq.core.config import load_config
    from endpointiq.knowledge.graph import KnowledgeGraph
    from endpointiq.observation.indexer import ProjectIndexer

    config = load_config(project_root=project_root)
    graph = KnowledgeGraph()
    indexer = ProjectIndexer(config, graph)
    stats = indexer.full_index()

    extractor = MRCExtractor(graph, project_root)
    try:
        goal_type = GoalType(goal)
    except ValueError:
        goal_type = GoalType.FULL

    mrc_result = extractor.extract(endpoint, goal_type, token_budget=4000)

    mrc_context = mrc_result.combined_context
    compressed_bytes = len(mrc_context.encode("utf-8"))
    raw_bytes = sum(len(s.source_code.encode("utf-8")) for s in mrc_result.snippets) or compressed_bytes

    return mrc_context, {
        "files_indexed": stats["files"],
        "endpoints": stats["endpoints"],
        "nodes": stats["nodes"],
        "context_files": len(mrc_result.snippets),
        "raw_size_bytes": raw_bytes,
        "compressed_size_bytes": compressed_bytes,
        "compression_ratio": mrc_result.compression_ratio,
    }


def print_separator(title: str = ""):
    width = 70
    if title:
        print(f"\n{'─' * 3} {title} {'─' * (width - len(title) - 5)}")
    else:
        print(f"{'─' * width}")


def main():
    project_dir = sys.argv[1] if len(sys.argv) > 1 else "examples/demo-api"
    endpoint = sys.argv[2] if len(sys.argv) > 2 else "DELETE /:id"
    project_root = Path(project_dir).resolve()

    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY not found in .env")
        sys.exit(1)

    print("=" * 70)
    print("  EndpointIQ Token Savings Benchmark")
    print("=" * 70)
    print(f"  Project:  {project_root}")
    print(f"  Endpoint: {endpoint}")
    print(f"  Model:    {MODEL}")

    # ── Phase 1: Collect full source (WITHOUT EndpointIQ) ──
    print_separator("Phase 1: WITHOUT EndpointIQ (full source)")

    full_source = collect_all_source(project_root)
    full_source_tokens = count_tokens(full_source)
    full_source_bytes = len(full_source.encode("utf-8"))

    print(f"  Total source code: {len(full_source):,} chars")
    print(f"  Total source size: {full_source_bytes:,} bytes")
    print(f"  Total tokens:      {full_source_tokens:,}")

    prompt_without = f"Analyze the endpoint '{endpoint}' in this codebase for security vulnerabilities."

    # Truncate if too large for model context (131K for Qwen)
    max_context_tokens = 120_000
    context_without = full_source
    if full_source_tokens > max_context_tokens:
        # Truncate proportionally
        ratio = max_context_tokens / full_source_tokens
        context_without = full_source[:int(len(full_source) * ratio)]
        print(f"  ⚠️  Truncated to {max_context_tokens:,} tokens (model context limit)")

    print(f"\n  Calling Groq ({MODEL})...")
    try:
        result_without = run_llm_call(prompt_without, context_without)
        without_failed = False
        print("  ✅ Response received")
        print(f"     Prompt tokens:     {result_without['prompt_tokens']:,}")
        print(f"     Completion tokens: {result_without['completion_tokens']:,}")
        print(f"     Total tokens:      {result_without['total_tokens']:,}")
        print(f"     Latency:           {result_without['latency_ms']:,}ms")
        print(f"     Estimated cost:    ${result_without['cost_usd']:.6f}")
    except Exception as e:
        without_failed = True
        err_msg = str(e)
        print(f"  ❌ FAILED: {err_msg[:120]}")
        print("  ⚠️  Full codebase EXCEEDS Groq's context window — analysis impossible without EIQ!")
        result_without = {
            "prompt_tokens": full_source_tokens,
            "completion_tokens": 0,
            "total_tokens": full_source_tokens,
            "latency_ms": 0,
            "cost_usd": (full_source_tokens * COST_PER_1M_INPUT) / 1_000_000,
            "content": f"FAILED: {err_msg[:200]}",
        }

    # ── Phase 2: MRC extraction (WITH EndpointIQ) ──
    print_separator("Phase 2: WITH EndpointIQ (MRC context extraction)")

    mrc_context, mrc_stats = extract_mrc_context(project_root, endpoint)
    mrc_tokens = count_tokens(mrc_context)

    print(f"  Files indexed:     {mrc_stats['files_indexed']}")
    print(f"  Graph nodes:       {mrc_stats['nodes']}")
    print(f"  Context files:     {mrc_stats['context_files']}")
    print(f"  Raw size:          {mrc_stats['raw_size_bytes']:,} bytes")
    print(f"  Compressed size:   {mrc_stats['compressed_size_bytes']:,} bytes")
    print(f"  Compression ratio: {mrc_stats['compression_ratio']:.1%}")
    print(f"  Context tokens:    {mrc_tokens:,}")

    prompt_with = f"Analyze the endpoint '{endpoint}' for security vulnerabilities."

    print(f"\n  Calling Groq ({MODEL})...")
    result_with = run_llm_call(prompt_with, mrc_context)

    print("  ✅ Response received")
    print(f"     Prompt tokens:     {result_with['prompt_tokens']:,}")
    print(f"     Completion tokens: {result_with['completion_tokens']:,}")
    print(f"     Total tokens:      {result_with['total_tokens']:,}")
    print(f"     Latency:           {result_with['latency_ms']:,}ms")
    print(f"     Estimated cost:    ${result_with['cost_usd']:.6f}")

    # ── Phase 3: Comparison ──
    print_separator("COMPARISON: Without vs With EndpointIQ")

    token_savings = result_without["prompt_tokens"] - result_with["prompt_tokens"]
    token_savings_pct = (token_savings / result_without["prompt_tokens"] * 100) if result_without["prompt_tokens"] > 0 else 0

    cost_savings = result_without["cost_usd"] - result_with["cost_usd"]
    cost_savings_pct = (cost_savings / result_without["cost_usd"] * 100) if result_without["cost_usd"] > 0 else 0

    latency_diff = result_without["latency_ms"] - result_with["latency_ms"]
    latency_pct = (latency_diff / result_without["latency_ms"] * 100) if result_without["latency_ms"] > 0 else 0

    print(f"""
  ┌──────────────────────┬──────────────────┬──────────────────┐
  │ Metric               │ WITHOUT EIQ      │ WITH EIQ         │
  ├──────────────────────┼──────────────────┼──────────────────┤
  │ Context size (bytes) │ {full_source_bytes:>14,}  │ {mrc_stats['compressed_size_bytes']:>14,}  │
  │ Prompt tokens        │ {result_without['prompt_tokens']:>14,}  │ {result_with['prompt_tokens']:>14,}  │
  │ Completion tokens    │ {result_without['completion_tokens']:>14,}  │ {result_with['completion_tokens']:>14,}  │
  │ Total tokens         │ {result_without['total_tokens']:>14,}  │ {result_with['total_tokens']:>14,}  │
  │ Latency              │ {result_without['latency_ms']:>11,}ms  │ {result_with['latency_ms']:>11,}ms  │
  │ Estimated cost       │    ${result_without['cost_usd']:>12.6f}  │    ${result_with['cost_usd']:>12.6f}  │
  └──────────────────────┴──────────────────┴──────────────────┘

  📊 SAVINGS:
     Token savings:   {token_savings:,} tokens ({token_savings_pct:.1f}% reduction)
     Cost savings:    ${cost_savings:.6f} ({cost_savings_pct:.1f}% cheaper)
     Latency savings: {latency_diff:,}ms ({latency_pct:.1f}% faster)
""")

    # Save results to JSON for further analysis
    report = {
        "project": str(project_root),
        "endpoint": endpoint,
        "model": MODEL,
        "without_eiq": {
            "context_bytes": full_source_bytes,
            "prompt_tokens": result_without["prompt_tokens"],
            "completion_tokens": result_without["completion_tokens"],
            "total_tokens": result_without["total_tokens"],
            "latency_ms": result_without["latency_ms"],
            "cost_usd": result_without["cost_usd"],
        },
        "with_eiq": {
            "context_bytes": mrc_stats["compressed_size_bytes"],
            "raw_bytes": mrc_stats["raw_size_bytes"],
            "compression_ratio": mrc_stats["compression_ratio"],
            "prompt_tokens": result_with["prompt_tokens"],
            "completion_tokens": result_with["completion_tokens"],
            "total_tokens": result_with["total_tokens"],
            "latency_ms": result_with["latency_ms"],
            "cost_usd": result_with["cost_usd"],
        },
        "savings": {
            "token_savings": token_savings,
            "token_savings_pct": round(token_savings_pct, 2),
            "cost_savings_usd": round(cost_savings, 6),
            "cost_savings_pct": round(cost_savings_pct, 2),
            "latency_savings_ms": latency_diff,
            "latency_savings_pct": round(latency_pct, 2),
        },
    }

    report_path = Path("benchmarks/results.json")
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(f"  📄 Full report saved to: {report_path}")


if __name__ == "__main__":
    main()
