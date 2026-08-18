<p align="center">
  <img src="https://img.shields.io/badge/EndpointIQ-AI%20Powered-blueviolet?style=for-the-badge&logo=openai&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-Agentic%20AI-ff6f00?style=for-the-badge&logo=langchain&logoColor=white" />
  <img src="https://img.shields.io/badge/Tests-93%20Passing-brightgreen?style=for-the-badge&logo=pytest&logoColor=white" />
  <img src="https://img.shields.io/badge/Token%20Savings-74.5%25-success?style=for-the-badge" />
</p>

<h1 align="center">🛡️ EndpointIQ</h1>

<p align="center">
  <strong>AI-Powered API Intelligence Platform</strong><br/>
  Autonomous endpoint analysis with knowledge graph reasoning & 74.5% token optimization
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-benchmark-results">Benchmarks</a> •
  <a href="#-demo">Demo</a> •
  <a href="#-tech-stack">Tech Stack</a> •
  <a href="#-vs-code-extension">VS Code Extension</a>
</p>

---

## 🤔 The Problem

Every LLM-powered code analysis tool today does the same thing:

```
📦 Your entire codebase (100K+ tokens) ──→ 🤖 LLM ──→ 💸 $$$
```

**EndpointIQ flips this entirely.** Instead of dumping your whole repo into an LLM, it builds a **knowledge graph** of your API, extracts only the **minimal relevant context** using Personalized PageRank, and sends **74.5% fewer tokens** — producing **deeper, more accurate findings**.

```
📦 Your codebase ──→ 🧠 Knowledge Graph ──→ 🎯 MRC (2KB) ──→ 🤖 LLM ──→ ✅ Precise findings
```

---

## ✨ Key Highlights

| Feature | What It Does |
|---|---|
| 🧠 **4-Agent LangGraph Pipeline** | Planner → Executor → Evaluator → Reporter with confidence-based re-planning |
| 🎯 **MRC Algorithm** | Personalized PageRank + 4-stage compression = 74.5% fewer tokens |
| 🌐 **Knowledge Graph** | NetworkX DAG mapping endpoints → controllers → services → DB layer |
| 🔒 **Security Engine** | Catches missing auth, IDOR, injection, rate limiting, broken access control |
| ⚡ **Performance Engine** | Detects N+1 queries, missing pagination, cache gaps, SELECT * |
| 🏛️ **Architecture Engine** | Flags layer violations, circular deps, god classes, high coupling |
| 🖥️ **3 Interfaces** | CLI (Typer + Rich) · REST API (FastAPI) · VS Code Extension |
| 🧪 **93 Tests Passing** | Full coverage with mypy + ruff, zero errors |

---

## 🎬 Demo

### CLI — Security Analysis

```bash
$ eiq security "DELETE /:id" --project-dir examples/demo-api
```

```
╭──────────────── 🔒 Security Analysis: DELETE /:id ─────────────────╮
│ ┏━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓│
│ ┃     ┃ Severity   ┃ Title                     ┃ File            ┃│
│ ┡━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩│
│ │ 🔴  │ CRITICAL   │ Missing Authentication    │ userRoutes.ts   ││
│ │ 🟡  │ MEDIUM     │ Missing Rate Limiting     │ userRoutes.ts   ││
│ │ 🔵  │ LOW        │ Missing Security Headers  │                 ││
│ └─────┴────────────┴───────────────────────────┴─────────────────┘│
╰───────────────────────────────────────────────────────────────────╯
  Total: 3 findings — 1 CRITICAL · 1 MEDIUM · 1 LOW
```

### LLM Agent — Deep Semantic Analysis (via Groq)

When connected to an LLM, the agent finds vulnerabilities that static analysis can't:

```
📋 Report: 7 findings (3 CRITICAL, 1 HIGH, 2 MEDIUM, 1 INFO)

   🔴 [CRITICAL] Missing Authentication and Authorization Checks
   🔴 [CRITICAL] Insecure Direct Object Reference (IDOR)
   🔴 [CRITICAL] Broken Access Control
   🟠 [HIGH]     SQL/NoSQL Injection via Unsanitized Route Parameter
   🟡 [MEDIUM]   Missing Input Validation & Type Checking
   🟡 [MEDIUM]   Unhandled Database Errors & Information Leakage
```

### Endpoint Discovery

```bash
$ eiq endpoints examples/demo-api
```

```
                          Discovered Endpoints
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ Endpoint              ┃ Type     ┃ File                     ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ GET /health           │ endpoint │ src/app.ts               │
│ 2   │ GET /                 │ endpoint │ src/routes/userRoutes.ts │
│ 3   │ POST /                │ endpoint │ src/routes/userRoutes.ts │
│ 4   │ PUT /:id              │ endpoint │ src/routes/userRoutes.ts │
│ 5   │ DELETE /:id           │ endpoint │ src/routes/userRoutes.ts │
│ 6   │ GET /                 │ endpoint │ src/routes/productRoutes │
└─────┴───────────────────────┴──────────┴──────────────────────────┘
  Total: 6 endpoints
```

---

## 📊 Benchmark Results

### 1. Real-World Production App: CerviLens Medical Backend (33 files, 32 endpoints, 162 nodes)

Measured on the **CerviLens HIPAA-compliant medical backend** analyzing `DELETE /:id` via Groq (Qwen 3.6 27B):

```
┌──────────────────────┬──────────────────┬──────────────────┐
│ Metric               │ WITHOUT EIQ      │ WITH EIQ         │
├──────────────────────┼──────────────────┼──────────────────┤
│ Context size (bytes) │        354,982   │          2,276   │
│ Prompt tokens        │        121,858   │            581   │
│ Total tokens         │        121,858   │          2,581   │
│ Analysis status      │ ❌ OVERFLOW (400)│ ✅ COMPLETED     │
│ Estimated cost       │       $0.02437   │       $0.00131   │
└──────────────────────┴──────────────────┴──────────────────┘

📊 PRODUCTION IMPACT:
   Token savings:   121,277 tokens (99.5% reduction)
   Cost savings:    94.6% cheaper per request
   Feasibility:     WITHOUT EIQ fails due to context limits; WITH EIQ finishes in ~4.9s
```

### 2. Microservice App: Demo API (5 files, 6 endpoints, 37 nodes)

Measured on `examples/demo-api` analyzing `DELETE /:id`:

```
┌──────────────────────┬──────────────────┬──────────────────┐
│ Metric               │ WITHOUT EIQ      │ WITH EIQ         │
├──────────────────────┼──────────────────┼──────────────────┤
│ Context size (bytes) │          2,531   │            403   │
│ Prompt tokens        │            726   │            185   │
│ Total tokens         │          2,707   │          2,142   │
│ Latency              │        9,755ms   │        7,270ms   │
│ Estimated cost       │      $0.001334   │      $0.001211   │
└──────────────────────┴──────────────────┴──────────────────┘

📊 SAVINGS:
   Token savings:   541 tokens (74.5% reduction)
   Cost savings:    9.2% cheaper per request
   Latency savings: 2,485ms (25.5% faster)
```

Run benchmarks on any project:
```bash
uv run python benchmarks/token_comparison.py cervical-screening-client/backend "DELETE /:id"
```

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    DELIVERY LAYER                                │
│     CLI (Typer + Rich)  │  FastAPI Server  │  VS Code Extension  │
├──────────────────────────────────────────────────────────────────┤
│                    ANALYSIS LAYER                                │
│    ┌──────────┐    ┌──────────┐    ┌──────────────┐             │
│    │ Security │    │  Perf    │    │ Architecture │             │
│    │ Engine   │    │  Engine  │    │   Engine     │             │
│    └──────────┘    └──────────┘    └──────────────┘             │
├──────────────────────────────────────────────────────────────────┤
│                    AGENT LAYER (LangGraph)                       │
│                                                                  │
│    ┌──────────┐    ┌──────────┐    ┌───────────┐   ┌──────────┐ │
│    │ Planner  │───▶│ Executor │───▶│ Evaluator │──▶│ Reporter │ │
│    └──────────┘    └──────────┘    └───────────┘   └──────────┘ │
│         ▲                               │                        │
│         └──── re-plan (confidence < 0.7)┘                        │
├──────────────────────────────────────────────────────────────────┤
│                    CONTEXT ENGINE                                │
│    Personalized PageRank  →  4-Stage Compression Pipeline        │
│    (Import Pruning → Comment Strip → Whitespace → Summarize)    │
├──────────────────────────────────────────────────────────────────┤
│                    KNOWLEDGE GRAPH (NetworkX)                    │
│    Endpoints → Controllers → Services → Repositories → DB       │
│    Edge types: CALLS, SECURED_BY, DEPENDS_ON, VALIDATES         │
├──────────────────────────────────────────────────────────────────┤
│                    OBSERVATION PIPELINE                          │
│    File Watcher → tree-sitter AST Parser → Incremental Indexer  │
│    Framework Plugins: Express.js (more coming)                   │
├──────────────────────────────────────────────────────────────────┤
│                    CORE                                          │
│    Config (Pydantic) │ SQLite (SQLAlchemy) │ Event Bus │ Models  │
└──────────────────────────────────────────────────────────────────┘
```

### How It Works

1. **🔍 Observation** — tree-sitter parses your AST, auto-detects Express.js, discovers every endpoint, middleware, controller, and service.

2. **🌐 Knowledge Graph** — Builds a directed graph connecting `POST /api/users` → `authMiddleware` → `UserController.create()` → `UserRepository.save()` with typed edges.

3. **🎯 MRC Extraction** — When you ask "analyze DELETE /:id for security", Personalized PageRank walks the graph from that endpoint, scores every node by relevance, and extracts only the top-K nodes. Then a 4-stage compression pipeline strips comments, prunes unused imports, normalizes whitespace, and summarizes large methods.

4. **🧠 Agent Reasoning** — The Planner decomposes the goal into sub-checks. The Executor runs each check with MRC context. The Evaluator scores confidence (0-1) and identifies gaps. If confidence < 0.7, it **re-plans and retries** (up to 3 iterations).

5. **📋 Delivery** — Findings are deduplicated, severity-ranked, and delivered via CLI tables, JSON API, or VS Code webview panels.

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/SAdreasgamer/EndPointIQ.git
cd EndPointIQ
uv sync    # or: pip install -e .
```

### Try It

```bash
# Initialize & scan a project
eiq init examples/demo-api

# List all endpoints
eiq endpoints examples/demo-api

# Security analysis
eiq security "DELETE /:id" --project-dir examples/demo-api

# Full analysis (security + performance + architecture)
eiq analyze "POST /" --project-dir examples/demo-api

# Dependency graph visualization
eiq graph "POST /" --project-dir examples/demo-api

# JSON output for CI/CD
eiq security "DELETE /:id" --project-dir examples/demo-api --format json

# Start REST API server
eiq serve
```

### Enable LLM Reasoning (Optional)

Create a `.env` file with your free [Groq API key](https://console.groq.com/keys):

```bash
GROQ_API_KEY=gsk_your_key_here
```

This upgrades the agent from static analysis to **deep semantic reasoning** — catching IDOR, business logic bypasses, and subtle injection patterns.

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **AI Agent** | LangGraph + LangChain | StateGraph with conditional routing, checkpointing, re-plan loops |
| **LLM** | Groq Cloud (Qwen 3.6 27B) | 500+ tokens/sec inference, free tier |
| **AST Parsing** | tree-sitter | Incremental parsing, multi-language support |
| **Knowledge Graph** | NetworkX | Directed graph with typed edges, PageRank, cycle detection |
| **Token Counting** | tiktoken | Exact token measurement for budget control |
| **CLI** | Typer + Rich | Beautiful terminal UI with panels, tables, trees |
| **API Server** | FastAPI + Uvicorn | Async REST API with auto-generated OpenAPI docs |
| **Data Models** | Pydantic v2 | Strict validation, JSON serialization |
| **Database** | SQLAlchemy + SQLite | File-level metadata, analysis history |
| **VS Code** | TypeScript | Sidebar tree, webview reports, status bar |
| **Testing** | pytest (93 tests) | Unit + integration, CLI + API coverage |
| **Quality** | ruff + mypy | Zero lint errors, full type safety |
| **Package** | uv | Fast dependency resolution, lockfile |

---

## 📋 CLI Reference

| Command | Description |
|---------|-------------|
| `eiq init <dir>` | Initialize project, run first index, display summary |
| `eiq index <dir>` | Re-run full index |
| `eiq endpoints <dir>` | List all discovered endpoints in a table |
| `eiq security <endpoint>` | Run security analysis |
| `eiq performance <endpoint>` | Run performance analysis |
| `eiq analyze <endpoint>` | Full analysis (all engines) |
| `eiq graph <endpoint>` | Dependency tree visualization |
| `eiq serve` | Start FastAPI server on port 8421 |
| `eiq version` | Print version |

All analysis commands support `--format json` for CI/CD pipelines.

---

## 🔌 REST API

Start: `eiq serve` → Docs: `http://localhost:8421/docs`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check + version |
| `POST` | `/api/projects` | Register & index a project |
| `GET` | `/api/projects/{id}` | Project status |
| `GET` | `/api/endpoints` | List discovered endpoints |
| `POST` | `/api/analysis` | Run analysis (security/performance/full) |
| `GET` | `/api/analysis/{id}` | Retrieve stored report |
| `GET` | `/api/graph/{endpoint}` | Endpoint subgraph as JSON |

---

## 🧩 VS Code Extension

The extension connects to the FastAPI server and provides:

- **🛡️ Sidebar Tree View** — All endpoints listed with HTTP method icons
- **📋 Webview Reports** — Color-coded findings with severity, file paths, recommendations
- **📊 Status Bar** — Server connection status and endpoint count
- **🖱️ Right-click Analysis** — Security, performance, or full analysis on any endpoint

```bash
# Install
cd vscode-extension && npm install && npm run compile
code --install-extension endpointiq-0.1.0.vsix

# Start backend
eiq serve
```

---

## 🔒 What It Catches

### Security Analysis

| Check | Severity | Detection Method |
|-------|----------|-----------------|
| Missing Authentication | 🔴 CRITICAL | No `SECURED_BY` edges on mutation endpoints |
| IDOR / Broken Access Control | 🔴 CRITICAL | LLM semantic analysis of route params |
| SQL/NoSQL Injection | 🔴 CRITICAL | String interpolation in query calls |
| Missing Input Validation | 🟠 HIGH | No validation middleware on POST/PUT |
| Missing Rate Limiting | 🟡 MEDIUM | Mutation endpoints without rate limiter |
| Missing Security Headers | 🔵 LOW | No Helmet/CORS middleware detected |

### Performance Analysis

| Check | Severity | Detection Method |
|-------|----------|-----------------|
| N+1 Queries | 🟠 HIGH | Loop containing DB calls (AST pattern) |
| Missing Pagination | 🟡 MEDIUM | List endpoints without limit/offset |
| Missing Cache | 🟡 MEDIUM | GET endpoints hitting DB without cache layer |
| SELECT * | 🟡 MEDIUM | Fetching all columns pattern |

### Architecture Analysis

| Check | Severity | Detection Method |
|-------|----------|-----------------|
| Layer Violations | 🟠 HIGH | Controller directly calls Repository |
| Circular Dependencies | 🟡 MEDIUM | `networkx.simple_cycles()` on dependency graph |
| High Coupling | 🟡 MEDIUM | Nodes with >10 outbound edges |
| God Classes | 🔵 LOW | Classes with >15 methods or >500 lines |

---

## 🧪 Testing

```bash
# Run all 93 tests
uv run pytest -v

# Type checking
uv run mypy src/

# Linting
uv run ruff check .

# Token savings benchmark
uv run python benchmarks/token_comparison.py examples/demo-api "DELETE /:id"
```

---

## 📁 Project Structure

```
EndPointIQ/
├── src/endpointiq/
│   ├── core/              # Config, DB, events, models
│   ├── observation/        # File watcher, AST parser, indexer, plugins
│   │   └── plugins/        # Framework-specific (Express.js)
│   ├── knowledge/          # NetworkX knowledge graph
│   ├── context/            # MRC extractor, compression pipeline
│   ├── agent/              # LangGraph agents, prompts, tools
│   ├── analysis/           # Security, performance, architecture engines
│   ├── cli/                # Typer CLI app + FastAPI server
│   └── models/             # Pydantic data models
├── vscode-extension/       # TypeScript VS Code extension
├── benchmarks/             # Token savings comparison
├── examples/demo-api/      # Sample Express.js project with vulnerabilities
└── tests/                  # 93 tests (Day 1-6)
```

---

## 🗺️ Roadmap

- [ ] **FastAPI / Django / Flask plugins** — Framework-agnostic analysis
- [ ] **WebSocket live updates** — Real-time analysis progress streaming
- [ ] **GitHub Action** — Run analysis on every PR automatically
- [ ] **Custom rules DSL** — Define your own analysis checks
- [ ] **Multi-repo analysis** — Analyze microservice architectures
- [ ] **VS Code inline diagnostics** — Findings as squiggly underlines in the editor
- [ ] **Ollama integration** — Run the full agent pipeline 100% offline

---

## 📄 License

MIT

---

<p align="center">
  Built with 🔥 by <a href="https://github.com/SAdreasgamer">SAdreasgamer</a>
</p>
