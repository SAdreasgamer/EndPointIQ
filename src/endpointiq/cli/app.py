"""CLI entry point for EndpointIQ using Typer and Rich."""

import typer
from rich.console import Console

app = typer.Typer(
    name="eiq",
    help="EndpointIQ — AI-powered API intelligence platform",
    add_completion=True,
)
console = Console()


@app.command()
def version():
    """Print EndpointIQ version."""
    from endpointiq import __version__

    console.print(f"[bold green]EndpointIQ[/bold green] v{__version__}")


def main():
    app()


if __name__ == "__main__":
    main()
