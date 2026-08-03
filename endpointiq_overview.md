# EndpointIQ — Development Overview & Tech Stack

---

## What Is EndpointIQ?

EndpointIQ is an **AI-powered API intelligence platform** that acts as an autonomous engineering agent for backend codebases.

**The one-sentence pitch:**
> It continuously watches your codebase, builds a live map of your architecture, and when you ask it to analyze an endpoint, it already knows the answer — using 97% fewer AI tokens than tools that scan your whole repo.

**What it is NOT:**
- ❌ A chatbot
- ❌ A code completion tool (like Copilot)
- ❌ A prompt wrapper around ChatGPT

**What it IS:**
- ✅ An autonomous agent that **understands** your backend
- ✅ A knowledge graph of your entire application architecture
- ✅ A specialized analysis platform for API endpoints
- ✅ A tool that does security, performance, and architecture reviews **automatically**

---

## How It Works — The Big Picture

### The Analogy

Imagine you hire a senior engineer to review your codebase. There are two ways they could work:

**The Copilot Way (today's AI tools):**
> Every time you ask a question, the engineer opens every file in the project, reads through everything, and *then* answers. Next question? Opens everything again from scratch. Slow, expensive, often misses context buried deep in the code.

**The EndpointIQ Way:**
> The engineer spends the first day building a **mental map** of the entire project — who calls what, how data flows, where security is enforced. After that, when you ask "is this endpoint secure?", they already know the answer. They pull up *only* the 5-6 relevant files and give you a precise review.

### The Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     YOUR CODEBASE                               │
│  Express / NestJS / Spring Boot / FastAPI / Django              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                    ① OBSERVE (continuous, background)
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   OBSERVATION PIPELINE                           │
│                                                                  │
│  File Watcher ──→ AST Parser ──→ Framework Detector             │
│                                        │                         │
│                              Dependency Graph Builder            │
│                              Call Graph Builder                  │
│                                        │                         │
│                                        ▼                         │
│                              ┌─────────────────┐                │
│                              │ KNOWLEDGE GRAPH  │                │
│                              │                  │                │
│                              │  Endpoints       │                │
│                              │  Controllers     │                │
│                              │  Services        │                │
│                              │  Repositories    │                │
│                              │  Entities        │                │
│                              │  Middleware      │                │
│                              │  Security Rules  │                │
│                              │  ... and more    │                │
│                              └────────┬────────┘                │
│                                       │                          │
└───────────────────────────────────────┼──────────────────────────┘
                                        │
                    ② ANALYZE (on-demand, when you ask)
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT SYSTEM                                │
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ PLANNER  │───→│ EXECUTOR │───→│EVALUATOR │───→│ REPORTER │  │
│  │          │    │          │    │          │    │          │  │
│  │ "What    │    │ Runs the │    │ "Is this │    │ Produces │  │
│  │  tools   │    │ selected │    │  answer  │    │ the final│  │
│  │  do we   │    │ analysis │    │  good    │    │ report"  │  │
│  │  need?"  │    │ engines" │    │  enough?"│    │          │  │
│  └──────────┘    └──────────┘    └─────┬────┘    └──────────┘  │
│       ▲                                │                        │
│       │            ③ RE-PLAN           │                        │
│       └────────────(if not confident)──┘                        │
└─────────────────────────────────────────────────────────────────┘
                                        │
                    ④ DELIVER
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     YOU SEE THE RESULTS                          │
│                                                                  │
│  VS Code Extension  │  CLI  │  Web Dashboard  │  JSON API       │
└─────────────────────────────────────────────────────────────────┘
```

### What Happens Step by Step

| Step | What Happens | When |
|------|-------------|------|
| **① Observe** | EndpointIQ watches your files. When you save a file, it re-parses *only that file*, detects what changed, and updates its knowledge graph. | Continuously, in background |
| **② Analyze** | You trigger an action: "Security review of POST /api/users". The agent plans which tools to run, extracts *only* the relevant code from the knowledge graph, compresses it, and sends it to the LLM. | On demand |
| **③ Re-plan** | The agent checks if it's confident in the result. If not (e.g., it found an auth middleware it didn't trace fully), it re-plans and gathers more context. Max 3 iterations. | Automatic |
| **④ Deliver** | A structured report with findings, severity levels, code references, and actionable recommendations. | Immediate |

---

## The Exact Tech Stack

### Why TypeScript?

The entire project is built in **TypeScript**. Here's why:

- The VS Code extension *must* be TypeScript — so we'd need it anyway
- Tree-sitter has excellent Node.js bindings
- TypeScript's type system lets us define strict interfaces for the plugin system
- One language across the entire monorepo = simpler builds, shared types, easier hiring

### Every Technology We're Using

#### 🏗️ Project Infrastructure

| Tool | What It Does | Why This One |
|------|-------------|-------------|
| **pnpm** | Package manager | 2-3x faster than npm. Hard-links packages instead of copying = saves disk space. Strict dependency resolution prevents phantom deps. |
| **Turborepo** | Monorepo build system | Runs builds/tests across packages in parallel. Caches results — if a package hasn't changed, it skips rebuilding. |
| **TypeScript 5.5+** | Language | Static types, interfaces for plugin system, shared type definitions across packages. |
| **ESLint + Prettier** | Code quality | Consistent code style. Auto-fixable. |
| **GitHub Actions** | CI/CD | Lint → typecheck → test → build on every PR. |

#### 🔍 Code Parsing & Analysis

| Tool | What It Does | Why This One |
|------|-------------|-------------|
| **tree-sitter** | AST parsing | The industry standard for code intelligence. Used by GitHub, Neovim, Zed. Key feature: **incremental parsing** — when you edit line 50, it re-parses only the affected nodes, not the whole file. Also parses broken/incomplete code without crashing. |
| **tree-sitter-typescript** | TypeScript grammar | Parses TS/JS into syntax trees. |
| **tree-sitter-python** | Python grammar | For FastAPI/Django support. |
| **tree-sitter-java** | Java grammar | For Spring Boot support. |
| **ts-morph** | TypeScript Compiler API wrapper | For deep type analysis where tree-sitter's syntax-only parsing isn't enough (e.g., resolving complex generic types, DI bindings). Used as a supplement, not primary parser. |
| **simple-git** | Git operations | Read git history, blame, diffs — all programmatically without shelling out to `git` CLI. |

#### 💾 Data Storage

| Tool | What It Does | Why This One |
|------|-------------|-------------|
| **better-sqlite3** | SQLite driver | Stores metadata: project info, endpoint list, analysis reports, token usage logs. SQLite is embedded (no server needed), ACID-compliant, and synchronous reads are *fast*. Perfect for local-first dev tools. |
| **FalkorDB** | Graph database | Stores the knowledge graph (nodes = code entities, edges = relationships). Supports OpenCypher queries for multi-hop traversal (e.g., "what services does this endpoint depend on?"). Runs as a Redis module = lightweight. |
| **SQLite adjacency list** | Graph fallback | For users who don't want to run Docker. The knowledge graph works with just SQLite — no external dependencies needed. Slower for complex queries, but zero-setup. |

> **Why not Neo4j?** Neo4j is the gold standard for graph DBs, but it's a heavy JVM-based server. EndpointIQ is a *local dev tool* — we need something lightweight. FalkorDB runs as a Redis module with much lower overhead. For enterprise/server deployments, Neo4j could be added as an alternative driver later.

#### 🌐 Server & API

| Tool | What It Does | Why This One |
|------|-------------|-------------|
| **Fastify 5** | HTTP server | 2x faster than Express. Built-in schema validation (we'll use it with Zod). Plugin architecture aligns with ours. |
| **ws** | WebSocket server | Lightweight, production-grade WebSocket library. Used for real-time events: index status updates, analysis progress. |
| **Zod** | Schema validation | Runtime type validation that *infers* TypeScript types. Validate API requests, config files, LLM outputs — one library for all. |

#### 🤖 AI / LLM Integration

| Tool | What It Does | Why This One |
|------|-------------|-------------|
| **OpenAI SDK** | OpenAI API client | GPT-4o, GPT-4o-mini for analysis reasoning. |
| **Anthropic SDK** | Claude API client | Claude for long-context analysis, detailed documentation generation. |
| **Google GenAI SDK** | Gemini API client | Gemini for cost-effective analysis. |
| **Ollama** | Local LLM runner | Run models locally — no API keys, no data leaves your machine. Critical for enterprise privacy. |
| **tiktoken** | Token counter | Accurately count tokens *before* sending to the LLM. Essential for staying within budget and estimating cost. |
| **Handlebars** | Prompt templates | Structured prompt templates with variables. Precompiled for performance. No logic in templates = predictable prompts. |

> **Why not LangChain?** LangChain adds a massive dependency tree and abstraction layer we don't need. Our LLM integration is focused: send compressed context, get structured output. A clean provider interface (50 lines) is simpler and more maintainable than pulling in LangChain's 200+ packages.

#### 🖥️ VS Code Extension

| Tool | What It Does | Why This One |
|------|-------------|-------------|
| **VS Code Extension API** | Extension framework | Native VS Code integration. |
| **vscode-jsonrpc** | Communication | JSON-RPC protocol for extension ↔ engine communication. |
| **D3.js** | Graph visualization | Renders interactive dependency graphs in webview panels. Force-directed layouts for exploring endpoint relationships. |
| **dagre** | Graph layout | Hierarchical graph layout algorithm. Used alongside D3 for clean, layered dependency views. |

#### 📊 Web Dashboard

| Tool | What It Does | Why This One |
|------|-------------|-------------|
| **Next.js 15** | React framework | Server-side rendering, API routes, App Router. |
| **Cytoscape.js** | Graph visualization | Enterprise-grade interactive graph library. Better than D3 for large graphs with many nodes. |
| **Recharts** | Charts | Token usage charts, analysis history, performance metrics. |

#### 🧪 Testing

| Tool | What It Does | Why This One |
|------|-------------|-------------|
| **Vitest** | Unit & integration testing | 10-20x faster than Jest. Native ESM support. Compatible with Jest API (easy migration). Built-in coverage. |
| **@vscode/test-electron** | VS Code E2E testing | Official testing framework for VS Code extensions. |
| **Playwright** | Browser E2E testing | Cross-browser testing for the dashboard. Trace viewer for debugging. |

#### 📦 CLI

| Tool | What It Does | Why This One |
|------|-------------|-------------|
| **Commander.js** | CLI framework | The standard for Node.js CLIs. Subcommands, options, help generation. |
| **ora** | Spinners | "Indexing project..." spinner for long operations. |
| **cli-table3** | Table output | Pretty-printed tables for endpoint listings and reports. |
| **chalk** | Colored output | Severity-colored findings (🔴 Critical, 🟡 Warning, etc.) |

---

## The Development Journey

Here's what we build and when — explained as a story, not a task list.

### Phase 0: The Skeleton (Weeks 1–3)

**What we're building:** The bare bones.

```
EndpointIQ/
├── packages/
│   ├── core/          ← Main engine (empty shell)
│   ├── cli/           ← CLI tool (empty shell)
│   ├── vscode-ext/    ← VS Code extension (empty shell)
│   └── shared/        ← Shared types
├── plugins/           ← Plugin directory
├── turbo.json
└── pnpm-workspace.yaml
```

**What works at the end:**
- ✅ Monorepo builds with one command (`pnpm turbo build`)
- ✅ File watcher detects when you save a file
- ✅ AST parser turns source code into a syntax tree
- ✅ SQLite stores project metadata
- ✅ Internal event bus connects components
- ✅ CI runs on every push

**What it can't do yet:** Nothing useful to a user. It's plumbing.

---

### Phase 1: "It Sees Your Code" (Weeks 4–7)

**What we're building:** The observation pipeline. The system can now *understand* an Express.js project.

```
You point it at an Express project
        │
        ▼
"I see Express.js (confidence: 95%)"
        │
        ▼
"I found 12 endpoints:"
  GET    /api/users
  POST   /api/users
  GET    /api/users/:id
  PUT    /api/users/:id
  DELETE /api/users/:id
  ...
        │
        ▼
"I built the dependency graph:"
  UserController ──calls──→ UserService ──uses──→ UserRepository
                                                       │
                                                  queries
                                                       │
                                                       ▼
                                                  User (entity)
```

**What works at the end:**
- ✅ Detects Express as the framework
- ✅ Discovers all API endpoints automatically
- ✅ Builds a knowledge graph with controllers, services, repositories, entities
- ✅ When you edit a file, the graph updates in **<200ms** (no full re-scan)
- ✅ When you delete a file, its nodes are pruned from the graph

**What it can't do yet:** No AI analysis. It understands your code but can't reason about it.

---

### Phase 2: "It Knows What Matters" (Weeks 8–11)

**What we're building:** The context engine — the core innovation.

**The before/after:**

```
WITHOUT EndpointIQ (traditional approach):
  "Analyze POST /api/users for security"
  → Sends entire repo to LLM: 487,000 tokens
  → Cost: ~$4.87 per analysis
  → Latency: 45 seconds
  → Accuracy: mediocre (LLM drowns in irrelevant context)

WITH EndpointIQ:
  "Analyze POST /api/users for security"
  → Knowledge graph traversal: finds 6 relevant files
  → MRC extraction: 8,200 tokens
  → After compression: 3,400 tokens
  → Cost: ~$0.03 per analysis
  → Latency: 3 seconds
  → Accuracy: high (LLM gets only relevant, structured context)
```

**What works at the end:**
- ✅ Extracts only the relevant code for a given endpoint + goal
- ✅ Ranks code by relevance using Personalized PageRank
- ✅ Compresses context (removes unused imports, comments, dead code)
- ✅ Achieves **>60% compression** beyond the already-minimal extraction
- ✅ Accurately estimates token count before sending to LLM

**What it can't do yet:** No LLM integration yet. It prepares the perfect context package, but doesn't send it anywhere.

---

### Phase 3: "It Thinks For Itself" (Weeks 12–16)

**What we're building:** The autonomous agent.

```
You say: "Security review of POST /api/users"

Agent thinks:
  ┌─ PLAN ────────────────────────────────────────────┐
  │ Goal: security_review                              │
  │ Sub-goals:                                         │
  │   1. Authentication analysis     (priority: HIGH)  │
  │   2. Authorization analysis      (priority: HIGH)  │
  │   3. Input validation            (priority: HIGH)  │
  │   4. Injection detection         (depends on #3)   │
  │   5. Rate limiting check         (priority: LOW)   │
  │ Token budget: 8,000 tokens                         │
  │ Estimated latency: 8 seconds                       │
  └────────────────────────────────────────────────────┘
        │
        ▼ Execute steps 1, 2, 3 in PARALLEL (they're independent)
        ▼ Then step 4 (depends on step 3's output)
        ▼ Then step 5 (optional, if budget allows)
        │
  ┌─ EVALUATE ─────────────────────────────────────────┐
  │ Confidence: 0.82 (≥ 0.7 threshold)                │
  │ Status: SUFFICIENT ✅                               │
  └────────────────────────────────────────────────────┘
        │
        ▼
  ┌─ REPORT ───────────────────────────────────────────┐
  │ Security Review: POST /api/users                    │
  │                                                     │
  │ 🔴 CRITICAL: No rate limiting on user creation     │
  │ 🟡 WARNING: Password field not validated for       │
  │             minimum complexity                      │
  │ 🟢 PASS: JWT authentication verified               │
  │ 🟢 PASS: Input sanitized against SQL injection     │
  │                                                     │
  │ Token usage: 3,847 (saved ~483,000 vs full scan)   │
  │ Cost: $0.038                                        │
  └────────────────────────────────────────────────────┘
```

**What works at the end:**
- ✅ Agent receives a goal and plans what to do
- ✅ Selects the right analysis tools (not all of them — only relevant ones)
- ✅ Executes in parallel where possible (independent sub-goals)
- ✅ If confidence is low, automatically re-plans and gathers more context
- ✅ Produces structured reports with severity-ranked findings
- ✅ LLM integration working (OpenAI first)

---

### Phase 4: "It's Actually Useful" (Weeks 17–22)

**What we're building:** The analysis engines that produce real findings.

| Engine | What It Catches | Example Finding |
|--------|----------------|-----------------|
| **Security** | Missing auth, injection, XSS, CORS issues, OWASP Top 10 | "POST /api/users has no rate limiting — vulnerable to brute force" |
| **Performance** | N+1 queries, missing cache, large payloads, slow loops | "GET /api/orders triggers 47 DB queries (N+1 pattern in OrderService)" |
| **Architecture** | Layer violations, circular deps, high coupling | "UserController directly calls UserRepository, bypassing the service layer" |
| **Documentation** | Missing docs, generates OpenAPI specs | Produces complete OpenAPI 3.0 spec from your endpoint graph |
| **Testing** | Missing test coverage, low-quality tests | "3 of 12 endpoints have no test coverage" |

**What works at the end:**
- ✅ Five analysis engines producing real, actionable findings
- ✅ Each engine uses the MRC algorithm (minimal context, maximum insight)
- ✅ Full agent loop working end-to-end for all analysis types

---

### Phase 5: "People Can Use It" (Weeks 23–28)

**What we're building:** The interfaces people actually interact with.

#### VS Code Extension
```
┌─ SIDEBAR ──────────────────────────────────────────┐
│ 📡 ENDPOINTS                                       │
│ ├── GET    /api/users          [Analyze] [Secure]  │
│ ├── POST   /api/users          [Analyze] [Secure]  │
│ ├── GET    /api/users/:id      [Analyze] [Secure]  │
│ ├── PUT    /api/users/:id      [Analyze] [Secure]  │
│ ├── DELETE /api/users/:id      [Analyze] [Secure]  │
│ └── GET    /api/products       [Analyze] [Secure]  │
│                                                     │
│ Status: ● Indexed (12 endpoints, 47 nodes)         │
└─────────────────────────────────────────────────────┘
```

#### CLI
```bash
$ eiq endpoints
┌────────┬──────────────────────┬─────────────────────────┐
│ Method │ Path                 │ Handler                 │
├────────┼──────────────────────┼─────────────────────────┤
│ GET    │ /api/users           │ UserController.getAll   │
│ POST   │ /api/users           │ UserController.create   │
│ GET    │ /api/users/:id       │ UserController.getById  │
└────────┴──────────────────────┴─────────────────────────┘

$ eiq security "POST /api/users"
🔴 CRITICAL: No rate limiting on user creation endpoint
🟡 WARNING:  Password complexity not validated
🟢 PASS:     JWT authentication verified
🟢 PASS:     SQL injection protection in place
```

#### Web Dashboard
- Endpoint explorer with search
- Interactive dependency graph (click nodes to explore)
- Report history with charts
- Token usage analytics

---

### Phase 6: "It Works With Everything" (Weeks 29–34)

**What we're building:** Support for more frameworks and LLM providers.

**Framework Plugins:**
| Plugin | Language | What It Detects |
|--------|----------|----------------|
| Express | TypeScript/JS | `app.get()`, `router.post()`, middleware |
| NestJS | TypeScript | `@Controller`, `@Get`, `@UseGuards`, `@Injectable` |
| FastAPI | Python | `@app.get()`, Pydantic models, `Depends()` |
| Spring Boot | Java | `@RestController`, `@GetMapping`, `@Autowired`, JPA |

**LLM Providers:**
| Provider | Use Case |
|----------|----------|
| OpenAI (GPT-4o) | General analysis, best accuracy |
| Claude | Long-context analysis, documentation |
| Gemini | Cost-effective analysis |
| Ollama (local) | Privacy-sensitive / air-gapped environments |
| Mistral | European data residency requirements |

---

### Phase 7: "It's Proven" (Weeks 35–40)

**What we're building:** Benchmarks, hardening, documentation, release.

**The benchmarks we'll publish:**

```
Token Efficiency (POST /api/users analysis):
  ┌─────────────────────────────────┬──────────┬───────┐
  │ Strategy                        │ Tokens   │ Cost  │
  ├─────────────────────────────────┼──────────┼───────┤
  │ A) Full repo dump (baseline)    │ 487,000  │ $4.87 │
  │ B) Naive file inclusion         │  52,000  │ $0.52 │
  │ C) EndpointIQ MRC               │   8,200  │ $0.08 │
  │ D) EndpointIQ MRC + compression │   3,400  │ $0.03 │
  └─────────────────────────────────┴──────────┴───────┘
  
  Reduction: 97% fewer tokens, 99% lower cost
```

---

## Architecture — Simplified

```
┌─────────────────────────────────────────────────────────────────┐
│  CLIENTS    VS Code Extension │ CLI │ Dashboard │ REST API      │
├─────────────────────────────────────────────────────────────────┤
│  AGENT      Planner → Executor → Evaluator → Reporter          │
├─────────────────────────────────────────────────────────────────┤
│  ENGINES    Security │ Performance │ Architecture │ Docs        │
├─────────────────────────────────────────────────────────────────┤
│  CONTEXT    MRC Calculator → Compressor → Token Estimator       │
├─────────────────────────────────────────────────────────────────┤
│  KNOWLEDGE  Knowledge Graph │ Endpoint Registry │ Symbol Index  │
├─────────────────────────────────────────────────────────────────┤
│  OBSERVE    File Watcher → AST Parser → Framework Detector      │
│             → Dependency Graph → Call Graph                      │
├─────────────────────────────────────────────────────────────────┤
│  STORAGE    SQLite (metadata) │ FalkorDB (graph) │ LRU (cache) │
├─────────────────────────────────────────────────────────────────┤
│  PLUGINS    Express │ NestJS │ FastAPI │ Spring │ OpenAI │ ...  │
└─────────────────────────────────────────────────────────────────┘
```

Each layer only talks to the layer directly below it. This keeps things clean, testable, and replaceable.

---

## Tech Stack At a Glance

```
Language:       TypeScript (entire project)
Runtime:        Node.js 22 LTS
Monorepo:       pnpm + Turborepo
AST Parsing:    tree-sitter
Graph DB:       FalkorDB (or SQLite fallback)
Metadata DB:    SQLite (better-sqlite3)
HTTP Server:    Fastify 5
WebSocket:      ws
Validation:     Zod
LLM:            OpenAI / Claude / Gemini / Ollama
Token Counting: tiktoken
Prompts:        Handlebars templates
VS Code:        Extension API + D3.js webviews
CLI:            Commander.js + ora + chalk
Dashboard:      Next.js 15 + Cytoscape.js + Recharts
Testing:        Vitest + Playwright
CI/CD:          GitHub Actions
Containers:     Docker Compose (dev dependencies)
```

---

## The End Result

After 40 weeks, a developer can:

1. **Install the VS Code extension** (one click)
2. **Open their Express/NestJS/FastAPI/Spring project** (auto-detected)
3. **See all endpoints in the sidebar** (auto-discovered)
4. **Click "Analyze"** on any endpoint
5. **Get a structured security/performance/architecture report** in seconds
6. **At 97% lower cost** than sending the whole repo to an LLM
7. **With zero manual context gathering** — the system already knows the architecture

That's EndpointIQ.
