"""CLI entry point for EndpointIQ using Typer and Rich.

Commands:
  eiq init              — Initialize project, run first index
  eiq index             — Re-run full index
  eiq endpoints         — Pretty table of all discovered endpoints
  eiq analyze <ep>      — Full analysis (all engines)
  eiq security <ep>     — Security review
  eiq performance <ep>  — Performance review
  eiq graph <ep>        — Dependency tree in terminal
  eiq version           — Print version
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

app = typer.Typer(
    name="eiq",
    help="EndpointIQ — AI-powered API intelligence platform",
    add_completion=True,
    no_args_is_help=True,
)
console = Console()


# ── Helpers ───────────────────────────────────────────


def _get_indexed_project(project_dir: Path):
    """Initialize and index a project, returning (config, graph, indexer)."""
    from endpointiq.core.config import load_config
    from endpointiq.knowledge.graph import KnowledgeGraph
    from endpointiq.observation.indexer import ProjectIndexer

    config = load_config(project_root=project_dir)
    graph = KnowledgeGraph()

    # Try to load saved graph
    graph_path = project_dir / ".endpointiq" / "graph.json"
    if graph_path.exists():
        graph.load(graph_path)

    indexer = ProjectIndexer(config, graph)
    return config, graph, indexer


def _severity_color(severity: str) -> str:
    """Map severity to Rich color."""
    return {
        "critical": "bold red",
        "high": "red",
        "medium": "yellow",
        "low": "cyan",
        "info": "green",
    }.get(severity.lower(), "white")


def _severity_icon(severity: str) -> str:
    """Map severity to emoji icon."""
    return {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🔵",
        "info": "🟢",
    }.get(severity.lower(), "⚪")


def _render_findings(findings, title: str = "Analysis Results") -> None:
    """Render a list of Finding objects as a Rich panel."""
    if not findings:
        console.print(Panel("[green]No issues found! ✨[/green]", title=title))
        return

    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("", width=3)
    table.add_column("Severity", width=10)
    table.add_column("Title", min_width=25)
    table.add_column("File", min_width=15)
    table.add_column("Recommendation", min_width=30)

    for f in findings:
        sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
        icon = _severity_icon(sev)
        color = _severity_color(sev)
        file_loc = ""
        if f.file_path:
            file_loc = f.file_path
            if f.line_number:
                file_loc += f":{f.line_number}"

        table.add_row(
            icon,
            f"[{color}]{sev.upper()}[/{color}]",
            f.title,
            file_loc,
            f.recommendation[:80] + "..." if len(f.recommendation) > 80 else f.recommendation,
        )

    console.print(Panel(table, title=f"[bold]{title}[/bold]", border_style="blue"))

    # Summary counts
    from collections import Counter
    counts = Counter(
        f.severity.value if hasattr(f.severity, "value") else str(f.severity)
        for f in findings
    )
    parts = []
    for sev in ["critical", "high", "medium", "low", "info"]:
        if counts.get(sev, 0) > 0:
            parts.append(f"[{_severity_color(sev)}]{counts[sev]} {sev.upper()}[/{_severity_color(sev)}]")
    console.print(f"  Total: {len(findings)} findings — " + " · ".join(parts))


# ── Commands ──────────────────────────────────────────


@app.command()
def version():
    """Print EndpointIQ version."""
    from endpointiq import __version__

    console.print(f"[bold green]EndpointIQ[/bold green] v{__version__}")


@app.command()
def init(
    project_dir: Path = typer.Argument(Path("."), help="Project directory to initialize"),
):
    """Initialize EndpointIQ for a project. Creates .endpointiq/ and runs first index."""
    project_dir = project_dir.resolve()
    eiq_dir = project_dir / ".endpointiq"
    eiq_dir.mkdir(exist_ok=True)

    console.print(f"[bold]Initializing EndpointIQ[/bold] in {project_dir}")

    _config, graph, indexer = _get_indexed_project(project_dir)

    with console.status("[bold green]Indexing project..."):
        stats = indexer.full_index()

    # Save graph
    graph.save(eiq_dir / "graph.json")

    # Display results
    console.print()
    console.print(Panel.fit(
        f"[bold green]✓ Project initialized![/bold green]\n\n"
        f"  Framework: [cyan]{stats['framework']}[/cyan] (confidence: {stats['confidence']:.0%})\n"
        f"  Files indexed: [cyan]{stats['files']}[/cyan]\n"
        f"  Endpoints found: [cyan]{stats['endpoints']}[/cyan]\n"
        f"  Graph nodes: [cyan]{stats['nodes']}[/cyan]\n"
        f"  Graph edges: [cyan]{stats['edges']}[/cyan]\n"
        f"  Duration: [cyan]{stats['duration_ms']}ms[/cyan]",
        title="[bold]EndpointIQ[/bold]",
        border_style="green",
    ))

    if stats["endpoints"] > 0:
        console.print("\n  Run [bold cyan]eiq endpoints[/bold cyan] to see all discovered endpoints.")
        console.print("  Run [bold cyan]eiq security \"GET /path\"[/bold cyan] to analyze an endpoint.")


@app.command()
def index(
    project_dir: Path = typer.Argument(Path("."), help="Project directory"),
):
    """Re-run full index of the project."""
    project_dir = project_dir.resolve()

    _config, graph, indexer = _get_indexed_project(project_dir)

    with console.status("[bold green]Re-indexing project..."):
        stats = indexer.full_index()

    # Save
    eiq_dir = project_dir / ".endpointiq"
    eiq_dir.mkdir(exist_ok=True)
    graph.save(eiq_dir / "graph.json")

    console.print(
        f"[green]✓ Indexed {stats['files']} files, "
        f"{stats['endpoints']} endpoints, "
        f"{stats['nodes']} graph nodes "
        f"in {stats['duration_ms']}ms[/green]"
    )


@app.command()
def endpoints(
    project_dir: Path = typer.Argument(Path("."), help="Project directory"),
    format: str = typer.Option("table", help="Output format: table, json"),
):
    """List all discovered API endpoints."""
    project_dir = project_dir.resolve()
    _config, graph, indexer = _get_indexed_project(project_dir)

    if graph.node_count == 0:
        indexer.full_index()

    ep_list = graph.list_endpoints()

    if format == "json":
        console.print_json(json.dumps(ep_list, default=str))
        return

    if not ep_list:
        console.print("[yellow]No endpoints discovered. Run 'eiq init' first.[/yellow]")
        return

    table = Table(title="Discovered Endpoints", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Endpoint", min_width=25)
    table.add_column("Type", width=12)
    table.add_column("File", min_width=20)

    for i, ep in enumerate(ep_list, 1):
        name = ep.get("display_name", "")
        node_type = ep.get("type", "")
        file_path = ep.get("file_path", "")
        table.add_row(str(i), f"[cyan]{name}[/cyan]", node_type, file_path)

    console.print(table)
    console.print(f"\n  Total: [bold]{len(ep_list)}[/bold] endpoints")


@app.command()
def security(
    endpoint: str = typer.Argument(..., help="Endpoint to analyze, e.g. 'POST /api/users'"),
    project_dir: Path = typer.Option(Path("."), help="Project directory"),
    format: str = typer.Option("rich", help="Output format: rich, json"),
):
    """Run security analysis on an endpoint."""
    from endpointiq.analysis.security import SecurityEngine

    project_dir = project_dir.resolve()
    _config, graph, indexer = _get_indexed_project(project_dir)

    if graph.node_count == 0:
        with console.status("[bold green]Indexing project..."):
            indexer.full_index()

    engine = SecurityEngine(graph, project_dir)

    with console.status(f"[bold green]Analyzing security: {endpoint}..."):
        findings = engine.analyze_endpoint(endpoint)

    if format == "json":
        console.print_json(json.dumps([f.model_dump() for f in findings], default=str))
    else:
        _render_findings(findings, title=f"🔒 Security Analysis: {endpoint}")


@app.command()
def performance(
    endpoint: str = typer.Argument(..., help="Endpoint to analyze"),
    project_dir: Path = typer.Option(Path("."), help="Project directory"),
    format: str = typer.Option("rich", help="Output format: rich, json"),
):
    """Run performance analysis on an endpoint."""
    from endpointiq.analysis.performance import PerformanceEngine

    project_dir = project_dir.resolve()
    _config, graph, indexer = _get_indexed_project(project_dir)

    if graph.node_count == 0:
        with console.status("[bold green]Indexing project..."):
            indexer.full_index()

    engine = PerformanceEngine(graph, project_dir)

    with console.status(f"[bold green]Analyzing performance: {endpoint}..."):
        findings = engine.analyze_endpoint(endpoint)

    if format == "json":
        console.print_json(json.dumps([f.model_dump() for f in findings], default=str))
    else:
        _render_findings(findings, title=f"⚡ Performance Analysis: {endpoint}")


@app.command()
def analyze(
    endpoint: str = typer.Argument(..., help="Endpoint to analyze"),
    project_dir: Path = typer.Option(Path("."), help="Project directory"),
    format: str = typer.Option("rich", help="Output format: rich, json"),
):
    """Run full analysis (security + performance + architecture) on an endpoint."""
    from endpointiq.analysis.architecture import ArchitectureEngine
    from endpointiq.analysis.performance import PerformanceEngine
    from endpointiq.analysis.security import SecurityEngine

    project_dir = project_dir.resolve()
    _config, graph, indexer = _get_indexed_project(project_dir)

    if graph.node_count == 0:
        with console.status("[bold green]Indexing project..."):
            indexer.full_index()

    all_findings = []

    with console.status(f"[bold green]Running full analysis: {endpoint}..."):
        sec_engine = SecurityEngine(graph, project_dir)
        sec_findings = sec_engine.analyze_endpoint(endpoint)
        for f in sec_findings:
            f.engine = "security"
        all_findings.extend(sec_findings)

        perf_engine = PerformanceEngine(graph, project_dir)
        perf_findings = perf_engine.analyze_endpoint(endpoint)
        for f in perf_findings:
            f.engine = "performance"
        all_findings.extend(perf_findings)

        arch_engine = ArchitectureEngine(graph, project_dir)
        arch_findings = arch_engine.analyze_endpoint(endpoint)
        for f in arch_findings:
            f.engine = "architecture"
        all_findings.extend(arch_findings)

    # Sort all findings by severity
    all_findings.sort(key=lambda f: f.severity_rank)

    if format == "json":
        console.print_json(json.dumps([f.model_dump() for f in all_findings], default=str))
    else:
        _render_findings(all_findings, title=f"📋 Full Analysis: {endpoint}")


@app.command(name="graph")
def show_graph(
    endpoint: str = typer.Argument(..., help="Endpoint to show dependency graph for"),
    project_dir: Path = typer.Option(Path("."), help="Project directory"),
    depth: int = typer.Option(3, help="Traversal depth"),
):
    """Show the dependency graph for an endpoint as a tree."""
    project_dir = project_dir.resolve()
    _config, graph, indexer = _get_indexed_project(project_dir)

    if graph.node_count == 0:
        with console.status("[bold green]Indexing project..."):
            indexer.full_index()

    endpoint_id = graph.lookup_endpoint(endpoint)
    if not endpoint_id:
        console.print(f"[red]Endpoint '{endpoint}' not found.[/red]")
        raise typer.Exit(1)

    attrs = graph.get_node(endpoint_id)
    tree = Tree(f"[bold cyan]{endpoint}[/bold cyan]  ({attrs.get('file_path', '')})")

    _build_tree(graph, endpoint_id, tree, depth=depth, visited=set())

    console.print(Panel(tree, title=f"[bold]Dependency Graph: {endpoint}[/bold]", border_style="blue"))


def _build_tree(graph, node_id: str, tree: Tree, depth: int, visited: set):
    """Recursively build a Rich Tree from graph neighbors."""
    if depth <= 0 or node_id in visited:
        return

    visited.add(node_id)
    nx_graph = graph.graph

    for _, target, attrs in nx_graph.out_edges(node_id, data=True):
        if target in visited:
            continue

        t_attrs = nx_graph.nodes.get(target, {})
        edge_type = attrs.get("type", "")
        node_type = t_attrs.get("type", "")
        name = t_attrs.get("qualified_name", target)
        file_path = t_attrs.get("file_path", "")

        type_color = {
            "endpoint": "bold cyan",
            "controller": "bold green",
            "service": "bold yellow",
            "repository": "bold magenta",
            "middleware": "bold red",
            "function": "blue",
            "file": "dim",
        }.get(node_type, "white")

        label = f"[{type_color}]{name}[/{type_color}]"
        if file_path:
            label += f"  [dim]{file_path}[/dim]"
        if edge_type:
            label += f"  [dim italic]({edge_type})[/dim italic]"

        branch = tree.add(label)
        _build_tree(graph, target, branch, depth - 1, visited)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8421, help="Port to bind to"),
):
    """Start the EndpointIQ API server."""
    import uvicorn

    console.print(f"[bold green]Starting EndpointIQ server[/bold green] on http://{host}:{port}")
    console.print("  API docs: [cyan]http://{host}:{port}/docs[/cyan]")
    uvicorn.run("endpointiq.cli.server:app", host=host, port=port, reload=False)


def main():
    app()


if __name__ == "__main__":
    main()
