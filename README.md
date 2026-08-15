# EndpointIQ

> **AI-powered API intelligence platform** — autonomous endpoint analysis with 99% token optimization.

EndpointIQ scans your codebase, builds a knowledge graph of your API endpoints, and uses LLM-powered agents to detect security vulnerabilities, performance issues, and architectural problems — sending only the **minimal relevant context** to the LLM instead of your entire repo.

## ✨ What Makes EndpointIQ Different

| Traditional Tools | EndpointIQ |
|---|---|
| Send entire repo to LLM (100K+ tokens) | **MRC algorithm** extracts only relevant code (~2K tokens) |
| Generic pattern matching | **Knowledge graph** understands your architecture |
| Single-pass analysis | **Multi-agent loop** with confidence scoring and re-planning |
| Manual setup per project | **Auto-detects** framework, endpoints, and middleware |

**Result:** 99% token savings, faster analysis, more relevant findings.

---

## 🚀 Quick Start

### Installation

```bash
# Clone the repo
git clone https://github.com/SAdreasgamer/EndPointIQ.git
cd EndPointIQ

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Usage

```bash
# 1. Initialize your Express.js project
eiq init /path/to/your/express-project

# 2. See all discovered endpoints
eiq endpoints

# 3. Run security analysis
eiq security "POST /api/users"

# 4. Run performance analysis
eiq performance "GET /api/users"

# 5. Full analysis (security + performance + architecture)
eiq analyze "DELETE /api/users/:id"

# 6. View dependency graph
eiq graph "POST /api/users"

# 7. Start the API server (for VS Code extension)
eiq serve
```

### Try the Demo

```bash
# Run against the included example project
eiq init examples/demo-api
eiq endpoints examples/demo-api
eiq security "DELETE /:id" --project-dir examples/demo-api
eiq analyze "POST /" --project-dir examples/demo-api
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│                   CLI / API / VS Code           │
├──────────┬──────────┬──────────┬────────────────┤
│ Security │  Perf    │  Arch    │   LangGraph    │
│ Engine   │  Engine  │  Engine  │   Agent System │
├──────────┴──────────┴──────────┴────────────────┤
│              Context Engine (MRC)                │
│        Personalized PageRank + Compression       │
├─────────────────────────────────────────────────┤
│           Knowledge Graph (NetworkX)             │
│     Endpoints → Controllers → Services → DB     │
├──────────┬──────────────────────────────────────┤
│ Express  │     Observation Pipeline              │
│ Plugin   │  File Watcher → AST Parser → Indexer  │
├──────────┴──────────────────────────────────────┤
│              Core (Config, Events, DB)           │
└─────────────────────────────────────────────────┘
```

### How It Works

1. **Observation Pipeline** — Scans your project, detects Express.js (more frameworks coming), discovers endpoints, middleware, controllers, services, and repositories using tree-sitter AST parsing.

2. **Knowledge Graph** — Builds a directed graph (NetworkX) connecting endpoints to their handlers, middleware, and data layer. Edges represent `CALLS`, `SECURED_BY`, `DEPENDS_ON` relationships.

3. **Context Engine (MRC)** — When you ask "analyze POST /api/users for security", it extracts only the relevant subgraph using Personalized PageRank, then compresses the source code with a 4-stage pipeline (import pruning → comment stripping → whitespace normalization → method summarization).

4. **Agent System** — A LangGraph StateGraph with 4 specialized nodes:
   - **Planner** — decomposes your goal into sub-tasks
   - **Executor** — runs analysis tools with MRC-extracted context
   - **Evaluator** — scores confidence, identifies gaps
   - **Reporter** — compiles findings into a structured report
   - If confidence < 0.7, the agent **re-plans** and tries again (up to 3 iterations).

5. **Analysis Engines** — Three specialized engines:
   - 🔒 **Security** — missing auth, input validation, injection patterns, rate limiting, security headers
   - ⚡ **Performance** — N+1 queries, missing cache, no pagination, SELECT * patterns
   - 🏛️ **Architecture** — layer violations, circular dependencies, high coupling, god classes

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| AI Agent | LangGraph + LangChain |
| LLM | Groq Cloud (Llama 3.1 8B Instant) |
| AST Parsing | tree-sitter |
| Knowledge Graph | NetworkX |
| Token Counting | tiktoken |
| CLI | Typer + Rich |
| API Server | FastAPI + Uvicorn |
| Data Models | Pydantic v2 |
| Database | SQLAlchemy (SQLite) |
| VS Code Extension | TypeScript |
| Testing | pytest (93 tests) |
| Linting | ruff + mypy |
| Package Manager | uv |

---

## 📋 CLI Commands

| Command | Description |
|---------|-------------|
| `eiq init <dir>` | Initialize project, run first index |
| `eiq index <dir>` | Re-run full index |
| `eiq endpoints <dir>` | List all discovered endpoints |
| `eiq security <endpoint>` | Security analysis |
| `eiq performance <endpoint>` | Performance analysis |
| `eiq analyze <endpoint>` | Full analysis (all engines) |
| `eiq graph <endpoint>` | Dependency tree visualization |
| `eiq serve` | Start FastAPI server (port 8421) |
| `eiq version` | Print version |

All analysis commands support `--format json` for CI/CD integration.

---

## 🔌 REST API

Start the server: `eiq serve`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/projects` | Register and index a project |
| `GET` | `/api/projects/{id}` | Project status |
| `GET` | `/api/endpoints` | List discovered endpoints |
| `POST` | `/api/analysis` | Run analysis |
| `GET` | `/api/analysis/{id}` | Get stored report |
| `GET` | `/api/graph/{endpoint}` | Endpoint subgraph as JSON |

API docs available at `http://localhost:8421/docs` when the server is running.

---

## 🧩 VS Code Extension

The extension lives in `vscode-extension/` and provides:

- **Endpoint Sidebar** — tree view of all discovered endpoints
- **Right-click Analysis** — security, performance, or full analysis
- **Report Panel** — formatted HTML webview with findings
- **Status Bar** — shows server status and endpoint count

### Setup

```bash
cd vscode-extension
npm install
npm run compile
# Press F5 in VS Code to launch in debug mode
```

Make sure the server is running: `eiq serve`

---

## 🧪 Testing

```bash
# Run all 93 tests
uv run pytest -v

# Run with coverage
uv run pytest --cov=endpointiq

# Run specific day's tests
uv run pytest tests/test_day5.py -v

# Linting
uv run ruff check .
uv run mypy src/
```

---

## 🔒 Security Analysis Checks

| Check | Severity | How |
|-------|----------|-----|
| Missing Authentication | 🔴 CRITICAL | No `SECURED_BY` edges from mutation endpoints |
| Missing Input Validation | 🟠 HIGH | No validation middleware on POST/PUT |
| SQL Injection Patterns | 🔴 CRITICAL | String interpolation in query calls |
| Missing Rate Limiting | 🟡 MEDIUM | Mutation endpoints without rate limiter |
| Missing Security Headers | 🔵 LOW | No CORS/Helmet middleware |

## ⚡ Performance Analysis Checks

| Check | Severity | How |
|-------|----------|-----|
| N+1 Queries | 🟠 HIGH | Loop containing DB calls (AST pattern) |
| Missing Cache | 🟡 MEDIUM | GET endpoints hitting DB without cache |
| No Pagination | 🟡 MEDIUM | List endpoints without limit/offset |
| SELECT * | 🟡 MEDIUM | Fetching all columns unnecessarily |

## 🏛️ Architecture Analysis Checks

| Check | Severity | How |
|-------|----------|-----|
| Layer Violations | 🟠 HIGH | Controller directly calls Repository |
| Circular Dependencies | 🟡 MEDIUM | `networkx.simple_cycles()` |
| High Coupling | 🟡 MEDIUM | Nodes with >10 outbound edges |
| God Classes | 🔵 LOW | Classes with >15 methods or >500 lines |

---

## 🗺️ Roadmap

- [ ] **FastAPI/Django/Flask plugins** — framework-agnostic analysis
- [ ] **WebSocket real-time updates** — live analysis progress
- [ ] **CI/CD GitHub Action** — run analysis on every PR
- [ ] **Custom rules** — define your own analysis checks
- [ ] **Multi-repo analysis** — analyze microservice architectures
- [ ] **VS Code inline diagnostics** — show findings as squiggly lines

---

## 📄 License

MIT

---

Built with ❤️ by [SAdreasgamer](https://github.com/SAdreasgamer)
