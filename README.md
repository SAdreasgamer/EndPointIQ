<p align="center">
  <img src="https://img.shields.io/badge/EndpointIQ-API%20Intelligence-blueviolet?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Tests-93%20Passing-brightgreen?style=for-the-badge&logo=pytest&logoColor=white" />
  <img src="https://img.shields.io/badge/Token%20Reduction-78.8%25%20Mean-success?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Latency-11ms%20P95-informational?style=for-the-badge" />
</p>

<h1 align="center">🛡️ EndpointIQ</h1>

<p align="center">
  <strong>Cross-File API Code Analysis & Intelligence Platform</strong><br/>
  Traces full request lifecycles (<code>Route → Middleware → Controller → Service</code>) to extract minimal relevant context, slashing LLM prompt tokens by 78.8% in under 11ms.
</p>

<p align="center">
  <a href="#-the-problem">The Problem</a> •
  <a href="#-key-highlights">Highlights</a> •
  <a href="#-benchmark-results">Benchmarks</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-vs-code-extension">VS Code Extension</a> •
  <a href="#-tech-stack">Tech Stack</a>
</p>

---

## 🤔 The Problem

When developers use AI to audit or review backend code, existing tools face an unavoidable trade-off:

1. **Single-File Isolation**: The AI only sees the open route file (`routes/user.ts`), completely missing shared authentication middleware (`middleware/auth.ts`) and service-layer logic.
2. **Naive Repository Dumps**: The tool dumps the entire codebase (25,000–100,000+ tokens) into the prompt. This causes **context window overflow**, inflates API inference costs, and triggers the **"Lost-in-the-Middle"** problem where models hallucinate or miss critical bugs amidst thousands of lines of unrelated code.

```
❌ Naive Approach:
📦 Entire Codebase (25K-100K+ tokens) ──→ 🤖 LLM ──→ 💸 High Cost / Context Overflow / Hallucinations
```

**EndpointIQ solves this with static call-graph tracing.** It parses the Abstract Syntax Tree (AST) of your backend, traces where each route actually executes across files, and extracts only the minimal code path needed for analysis:

```
✅ EndpointIQ Approach:
📦 Codebase ──→ 🧠 AST Call Graph ──→ 🎯 Focused Context (~3.9K tokens) ──→ 🤖 LLM ──→ 🎯 Deep, Exact Findings
```

---

## ✨ Key Highlights

| Feature | Description |
|:---|:---|
| 🌐 **Cross-File Call Graph** | Traces execution paths across files (`Route → Middleware → Controller → Service → Model`) with CommonJS barrel re-export support. |
| 🎯 **Targeted Context Extraction** | Graph traversal isolates only the code an endpoint touches, achieving a **78.8% mean token reduction** in **11ms P95**. |
| 🔍 **100% Dependency Recall** | Verified against human-traced ground-truth call chains across 18 endpoints in 3 open-source codebases with zero false negatives. |
| 🔒 **Security & Quality Engines** | Automated checks flag unverified authentication tokens in middleware, missing input validation, rate-limiting gaps, and unindexed queries. |
| 🤖 **Multi-Agent Evaluation Loop** | Optional 4-node LangGraph StateGraph (Planner → Executor → Evaluator → Reporter) with confidence routing to eliminate low-quality findings. |
| 🖥️ **3 Developer Interfaces** | Interactive terminal CLI (`Typer` + `Rich`), local background daemon (`FastAPI`), and native **VS Code Extension** (`TypeScript`). |
| 🧪 **93 Automated Tests** | Comprehensive test suite covering parsers, graph builders, extraction algorithms, and REST APIs with zero regressions. |

---

## 📊 Benchmark Results

EndpointIQ includes an automated, reproducible multi-repo benchmark suite ([`benchmarks/run_benchmark.py`](benchmarks/run_benchmark.py)) evaluated against human-verified ground truth ([`benchmarks/ground_truth.json`](benchmarks/ground_truth.json)).

### Headline Metrics (36 Endpoints across 3 Repositories)

| Metric | Mean | Median | P95 |
|:---|:---:|:---:|:---:|
| **Recall (18 Ground-Truth Endpoints)** | **1.00 (100%)** | **1.00** | **1.00** |
| **Token Reduction %** | **78.8%** | **70.8%** | **99.9%** |
| **Extraction Latency** | **12.6ms** | **8.5ms** | **11.0ms** |
| **F1 Score** | **0.66** | **0.67** | **1.00** |
| **Indexing Throughput** | **300–500 files/sec** | — | — |

### Per-Repository Summary

| Repository | Stack | Files / LOC | Full Repo Tokens | Extracted Tokens | Mean Reduction | Recall |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **`demo-api`** | TypeScript (Express) | 5 files / 88 LOC | 577 | 44 – 254 | **79.5%** | **1.00** |
| **`realworld-express`** | TypeScript (Conduit API) | 39 files / 2,489 LOC | 13,702 | 1,760 – 4,000 | **73.9%** | **1.00** |
| **`express-boilerplate`** | JavaScript (Production REST) | 50 files / 3,856 LOC | 27,165 | ~3,900 – 4,000 | **88.2%** | **1.00** |

> Read the complete breakdown in [`benchmarks/BENCHMARK_REPORT.md`](benchmarks/BENCHMARK_REPORT.md).

### Reproduce the Benchmarks

```bash
# Run the offline benchmark suite (auto-clones external benchmark repos)
uv run python benchmarks/run_benchmark.py

# Run with live LLM comparison (requires GROQ_API_KEY)
uv run python benchmarks/run_benchmark.py --llm
```

---

## 🎬 Real Finding Example: Cross-File Vulnerability Discovery

When analyzing `POST /` in `examples/demo-api`:
- **The Route** (`src/routes/userRoutes.ts`): Appears secure because `authMiddleware` is attached.
- **The Middleware** (`src/middleware/auth.ts`): Contains an unverified token implementation (`// TODO: validate token`).

Single-file analyzers reviewing only `userRoutes.ts` miss this bug completely. EndpointIQ traces the cross-file dependency into the context window, enabling the model to surface:

```
[CRITICAL] Authentication Middleware Does Not Validate Tokens
File: src/middleware/auth.ts:9-12
Detail: authMiddleware extracts Bearer tokens but does not verify signature or validity (marked with TODO),
        allowing attackers to bypass authentication with arbitrary token strings.
Recommendation: Implement cryptographic verification using jwt.verify() before setting req.user.
```

---

## 🏗️ Architecture

EndpointIQ is structured in three modular layers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        1. PRESENTATION LAYER                           │
│     CLI (Typer + Rich)   │   VS Code Extension (TypeScript UI)         │
├────────────────────────────────────────────────────────────────────────┤
│                        2. LOCAL SERVICE LAYER                          │
│     FastAPI Daemon (localhost:8421)   │   REST API (/api/endpoints)    │
├────────────────────────────────────────────────────────────────────────┤
│                        3. CORE ANALYSIS ENGINE                         │
│                                                                        │
│   ┌───────────────────────┐         ┌──────────────────────────────┐   │
│   │ Observation Pipeline  │         │ Knowledge Graph (NetworkX)   │   │
│   │ • tree-sitter Parser  │────────▶│ • Typed Nodes & Edges        │   │
│   │ • Cross-File Resolver │         │ • Route → Service Traversal  │   │
│   └───────────────────────┘         └──────────────┬───────────────┘   │
│                                                    │                   │
│                                                    ▼                   │
│   ┌───────────────────────┐         ┌──────────────────────────────┐   │
│   │ Analysis & LLM Agents │◀────────│ Context Extractor (MRC)      │   │
│   │ • Rule-Based Audits   │         │ • Subgraph Traversal         │   │
│   │ • LangGraph Pipeline  │         │ • 78.8% Token Pruning (11ms) │   │
│   └───────────────────────┘         └──────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Observation & Parsing**: `tree-sitter` parses source files into Abstract Syntax Trees. The indexer discovers routes, middleware, controllers, and import statements, resolving cross-file references and CommonJS barrel re-exports.
2. **In-Memory Knowledge Graph**: Components become typed nodes (`endpoint`, `middleware`, `controller`, `service`), connected by typed edges (`CALLS`, `SECURED_BY`, `DEPENDS_ON`, `VALIDATES`).
3. **Context Extraction (MRC)**: When an endpoint is analyzed, the extractor walks the graph starting from that endpoint node, isolating only the reachable execution path within a token budget.
4. **Analysis & Reporting**: Rule-based checks and an optional LangGraph agent audit the focused context, returning structured JSON reports with file paths, line numbers, and remediation guidance.

---

## 🚀 Quick Start

### 1. Installation

```bash
git clone https://github.com/SAdreasgamer/EndPointIQ.git
cd EndPointIQ
uv sync    # or: pip install -e .
```

### 2. Discover Endpoints

```bash
# Scan a project and display discovered endpoints in a formatted table
eiq endpoints examples/demo-api
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
└─────┴───────────────────────┴──────────┴──────────────────────────┘
```

### 3. Run Security Analysis

```bash
# Run security checks on a specific route
eiq security "DELETE /:id" --project-dir examples/demo-api
```

```
╭──────────────── 🔒 Security Analysis: DELETE /:id ─────────────────╮
│ ┏━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓│
│ ┃     ┃ Severity   ┃ Title                     ┃ File            ┃│
│ ┡━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩│
│ │ 🔴  │ CRITICAL   │ Missing Authentication    │ userRoutes.ts   ││
│ │ 🟡  │ MEDIUM     │ Missing Rate Limiting     │ userRoutes.ts   ││
│ └─────┴────────────┴───────────────────────────┴─────────────────┘│
╰───────────────────────────────────────────────────────────────────╯
```

### 4. Optional: Enable LLM Reasoning

Add a free [Groq API key](https://console.groq.com/keys) to `.env`:

```bash
GROQ_API_KEY=gsk_your_key_here
```

Now `eiq analyze "POST /" --project-dir examples/demo-api` activates the multi-agent review pipeline for deep semantic vulnerability detection.

---

## 🧩 VS Code Extension

EndpointIQ includes a native TypeScript VS Code extension (`vscode-extension/`):

- **Sidebar TreeView**: Lists all API routes with HTTP-method-specific icons (`GET`, `POST`, `DELETE`).
- **Interactive Webview**: Displays side-by-side formatted reports with severity badges, line links, and recommendations.
- **Status Bar Integration**: Shows server health and indexed endpoint count in real time.

```bash
# Compile and install extension
cd vscode-extension
npm install && npm run compile
code --install-extension endpointiq-0.1.0.vsix

# Start the background daemon
eiq serve
```

---

## 🛠️ Tech Stack

| Component | Technology | Purpose |
|:---|:---|:---|
| **Language** | Python 3.12 | Core indexing engine, graph algorithms, and analysis pipeline |
| **AST Parsing** | `tree-sitter` | High-throughput multi-language syntax tree extraction |
| **Dependency Graph** | `networkx` | In-memory directed graph modeling endpoints, middleware, and services |
| **Local Daemon** | `FastAPI` + `uvicorn` | Lightweight REST API bridge for IDE and CI integrations |
| **Token Measurement** | `tiktoken` | Exact cl100k_base token counting for budget control |
| **CLI** | `typer` + `rich` | Terminal interface with formatted tables, trees, and panels |
| **Agent Pipeline** | `langgraph` + `langchain` | Cyclical StateGraph with self-reflection and confidence scoring |
| **IDE Extension** | TypeScript + VS Code API | Native editor sidebar, webviews, and command palette actions |
| **Testing** | `pytest` | 93 automated unit and integration tests |
| **Code Quality** | `ruff` + `mypy` | Strict typing and linting compliance |

---

## 🧪 Testing

```bash
# Run all 93 unit and integration tests
uv run pytest -v

# Run type checking
uv run mypy src/

# Run linter
uv run ruff check .
```

---

## 📁 Project Structure

```
EndPointIQ/
├── src/endpointiq/
│   ├── core/              # Config, DB, events, models
│   ├── observation/       # AST parser (tree-sitter), indexer, express plugin
│   ├── knowledge/         # In-memory dependency graph (NetworkX)
│   ├── context/           # Minimal Relevant Context (MRC) extractor
│   ├── agent/             # LangGraph multi-agent analysis loop
│   ├── analysis/          # Rule-based security & performance engines
│   └── cli/               # Typer CLI commands & FastAPI server
├── vscode-extension/      # TypeScript VS Code extension
├── benchmarks/            # Benchmark suite (run_benchmark.py, ground_truth.json)
├── examples/demo-api/     # Sample Express.js codebase with test vulnerabilities
└── tests/                 # 93 automated pytest suites
```

---

## 📄 License

MIT License. Built with clean architecture and reproducible benchmarks by [SAdreasgamer](https://github.com/SAdreasgamer).
