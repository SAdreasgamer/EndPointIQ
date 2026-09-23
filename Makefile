.PHONY: help start serve test benchmark endpoints security analyze

# Default target when just typing 'make'
start:
	@echo "🚀 Starting EndpointIQ server at http://127.0.0.1:8421 ..."
	@echo "📖 Swagger API docs available at: http://localhost:8421/docs"
	uv run eiq serve

serve: start

help:
	@echo "EndpointIQ — Available Commands:"
	@echo "  make start       Start local FastAPI server (connects to VS Code extension)"
	@echo "  make serve       Alias for make start"
	@echo "  make test        Run all 93 automated unit tests"
	@echo "  make benchmark   Run the multi-repo benchmark suite"
	@echo "  make endpoints   List discovered API routes in demo-api"
	@echo "  make security    Run security analysis on DELETE /:id"
	@echo "  make analyze     Run full analysis on POST /"

test:
	uv run pytest tests/ -v

benchmark:
	uv run python benchmarks/run_benchmark.py

endpoints:
	uv run eiq endpoints examples/demo-api

security:
	uv run eiq security "DELETE /:id" --project-dir examples/demo-api

analyze:
	uv run eiq analyze "POST /" --project-dir examples/demo-api
