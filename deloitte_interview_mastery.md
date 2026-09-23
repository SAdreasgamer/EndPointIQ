# EndpointIQ — Deloitte Technology Analyst Interview Mastery Guide

> **Target Role**: Technology Analyst / Tech Consulting Analyst @ Deloitte  
> **Project on Resume**: `EndpointIQ — Developer Tool for API Analysis`  
> **Tech Stack Listed**: `Python, FastAPI, REST APIs, VS Code API`  
> **Key Metrics**: 78% token reduction, 93 automated unit tests, cross-file call tracing (`Route → Middleware → Controller → Service`)

---

## 📌 Table of Contents
1. [The 60-Second Elevator Pitch](#1-the-60-second-elevator-pitch)
2. [Category 1: Project Architecture & Dataflow](#2-category-1-project-architecture--dataflow)
3. [Category 2: The Core Engineering & The 78% Metric](#3-category-2-the-core-engineering--the-78-metric)
4. [Category 3: Real Bugs Caught & Security Checks](#4-category-3-real-bugs-caught--security-checks)
5. [Category 4: The Hardest Challenge / "War Story"](#5-category-4-the-hardest-challenge--war-story)
6. [Category 5: Testing & Quality Assurance (The 93 Tests)](#6-category-5-testing--quality-assurance-the-93-tests)
7. [Category 6: Deloitte Consulting & Business Value](#7-category-6-deloitte-consulting--business-value)
8. [Category 7: Quick-Fire Technical Basics (APIs & Python)](#8-category-7-quick-fire-technical-basics-apis--python)
9. [Interview Day Traps & Golden Rules](#9-interview-day-traps--golden-rules)

---

## 1. The 60-Second Elevator Pitch

### Q: "Tell me about this project, EndpointIQ."

> **Your Answer:**  
> *"When development teams use AI to review code, they usually face two major problems:*  
> *1. Either the AI inspects only a single file, which misses shared middleware, controllers, and services.*  
> *2. Or the tool dumps the entire codebase—thousands of lines of code—into the prompt, which is slow, expensive, and leads to hallucinations.*  
>  
> *I built **EndpointIQ** to solve that problem for backend REST APIs.*  
>  
> *First, it uses static code analysis in Python to trace where an API route actually goes across files—mapping the full path from the route definition, through the middleware, into the controller and database service.*  
>  
> *Second, when a developer analyzes an endpoint, the tool extracts only the specific code files that route executes. In our benchmarks across 3 open-source codebases, this cut prompt token size by **78%** compared to sending the whole repository.*  
>  
> *Finally, it feeds that focused code into automated checks to flag cross-file bugs—such as unverified authentication tokens in middleware. I packaged the entire tool into a **VS Code extension** and backed it with **93 automated unit tests**."*

---

## 2. Category 1: Project Architecture & Dataflow

### Q1: "Can you walk me through the architecture of EndpointIQ?"

> **Your Answer:**  
> *"The project is built on a clean, 3-layer architecture:*  
>  
> *1. **The Presentation Layer (UI)**: A lightweight **VS Code extension** written in TypeScript. It provides a sidebar tree view listing all discovered endpoints and opens an interactive HTML dashboard beside the code.*  
> *2. **The Server Layer (Bridge)**: A local **FastAPI daemon** in Python running on `localhost:8421`. It exposes REST endpoints like `GET /api/endpoints` and `POST /api/analysis` so the VS Code extension can communicate with our backend.*  
> *3. **The Core Analysis Engine (Python)**: This contains the parser that scans files into an in-memory dependency graph, the context extractor that isolates relevant code, and the reviewer that evaluates the code for security and quality issues.*  
>  
> *I deliberately separated it this way for clean separation of concerns: heavy code analysis stays in Python, while the developer enjoys a native UI inside their IDE."*

---

### Q2: "What happens under the hood when a developer clicks 'Analyze' on an endpoint?"

> **Your Answer (The 4-Step Dataflow):**  
> *"1. **UI Trigger**: In VS Code, the developer clicks 'Analyze' on an endpoint (e.g. `POST /login`). The extension sends an HTTP POST request to our FastAPI server with the endpoint name.*  
> *2. **Targeted Extraction**: The server calls our Python extractor. Instead of opening all 50 files in the repo, the extractor looks up `POST /login` in our dependency graph and traverses the connected arrows to pull only the route handler, the auth middleware, the auth controller, and the user service.*  
> *3. **Code Review**: The engine takes that focused snippet (~3,900 tokens instead of 27,000) and runs checks for missing input validation or broken token logic using an LLM prompt.*  
> *4. **Report Rendering**: The server packages the findings into a JSON response with file paths and line numbers. The VS Code extension receives this JSON and renders an interactive, color-coded HTML panel right beside the code."*

---

### Q3: "Why did you use FastAPI instead of Flask or Django?"

> **Your Answer:**  
> *"FastAPI was the ideal choice for three reasons:*  
> *1. **Performance & Async**: FastAPI is built on Starlette and ASGI, giving high-performance asynchronous request handling, which is great when waiting for code analysis.*  
> *2. **Automatic Type Validation**: It uses Pydantic models for request and response validation, preventing runtime data errors.*  
> *3. **Lightweight**: Unlike Django, which brings heavy ORM and admin baggage we didn't need, FastAPI is minimal and perfect for a local developer daemon."*

---

## 3. Category 2: The Core Engineering & The 78% Metric

### Q1: "How did you measure the '78% token reduction' claim?"

> **Your Answer:**  
> *"I built an automated benchmark script (`benchmarks/run_benchmark.py`) that evaluated 36 endpoints across 3 different open-source repositories (a microservice, a RealWorld Conduit backend, and a production boilerplate):*  
>  
> *1. **Baseline**: I measured the token count of dumping the entire repository source into the prompt using the standard `tiktoken` tokenizer.*  
> *2. **EndpointIQ**: I measured the token count of only the code snippets our tool extracted for that specific endpoint.*  
> *3. **The Formula**: `(1 - Extracted Tokens / Full Repo Tokens) * 100`.*  
>  
> *In `express-boilerplate` (50 files), the full repo was **27,165 tokens**. For `POST /register`, our tool extracted only the 5 required files, totaling **3,977 tokens**—an **85.4% reduction**. Across all 36 endpoints, the average reduction was **78.8%**."*

---

### Q2: "How does the tool trace routes across different files?"

> **Your Answer:**  
> *"It works in two phases:*  
> *1. **Local Parsing**: It parses each file into a syntax tree to find route definitions (`router.post('/login', ...)`), function declarations, and import/require statements (`const authController = require('./controllers/auth.controller')`).*  
> *2. **Cross-File Linkage**: If a route handler or middleware is imported from another file, the indexer resolves the relative import path, finds the target file, and connects them with a directed edge in memory (`Route → Middleware → Controller → Service`)."*

---

### Q3: "What is an Abstract Syntax Tree (AST) in simple words?"

> **Your Answer:**  
> *"An AST is a tree representation of the structure of source code. Instead of seeing code as just raw strings or lines of text, an AST breaks code down into grammatical nodes—like `FunctionDeclaration`, `CallExpression`, or `ImportStatement`. This allows us to programmatically inspect what a function is calling without having to execute the code or rely on fragile regex."*

---

## 4. Category 3: Real Bugs Caught & Security Checks

### Q1: "What kind of bugs does EndpointIQ actually catch?"

> **Your Answer:**  
> *"It specializes in **cross-file API issues** that single-file linters miss:*  
> *1. **Missing Authentication on Mutation Routes**: A `DELETE /api/users/:id` endpoint that has no authentication middleware attached.*  
> *2. **Incomplete / Unverified Auth Middleware**: A route that appears secure because it uses `authMiddleware`, but inspecting the middleware file reveals the JWT signature verification is missing or commented out.*  
> *3. **Missing Input Validation**: `POST` or `PUT` endpoints that take request bodies without schema validation middleware.*  
> *4. **Performance Gaps**: Endpoints returning large database lists without pagination parameters (limit/offset)."*

---

### Q2: "Can you give a concrete example of a bug you found in testing?"

> **Your Answer (The `auth.ts` Example):**  
> *"Yes! In our test codebase `demo-api`, there is an endpoint `POST /` to create users.*  
> *Looking only at the route file (`userRoutes.ts`), everything looks fine because `authMiddleware` is attached.*  
> *However, because our tool traces cross-file dependencies, it pulled in `src/middleware/auth.ts`. Inside `auth.ts`, the middleware extracted the Bearer token header, but had a comment `// TODO: validate token` and never actually verified the signature.*  
> *Our review engine caught this immediately: **'Authentication Middleware Does Not Validate Tokens (Critical)'**, alerting developers that anyone could pass an arbitrary string and gain full access. A single-file tool would have completely missed that."*

---

## 5. Category 4: The Hardest Challenge / "War Story"

### Q: "Tell me about the most difficult bug or technical challenge you faced in this project."

> **Your Answer (The Multi-Dot Path Resolution Bug):**  
> *"The hardest challenge was handling **cross-file path resolution on real-world codebases**.*  
>  
> *When I first tested our tool on `realworld-express` (a 39-file production codebase), our resolver kept throwing file-not-found errors on files like `article.service.ts`.*  
>  
> *When debugging, I discovered that Python’s `pathlib.Path.with_suffix('.ts')` treats any dot in a filename as a file extension. So calling `Path('article.service').with_suffix('.ts')` stripped `.service` and looked for `article.ts`! Real-world codebases use multi-dot filenames everywhere—like `auth.controller.js` or `user.validation.ts`.*  
>  
> *I fixed this by replacing `with_suffix()` with explicit string path concatenation (`Path(str(base) + ext)`). On top of that, I added support for **CommonJS barrel re-exports**, where a file like `services/index.js` re-exports methods from `services/auth.service.js`.*  
>  
> *Resolving that single issue unlocked **54 cross-file edges** in `realworld-express` and brought our dependency recall to **100%** across all test codebases."*

---

## 6. Category 5: Testing & Quality Assurance (The 93 Tests)

### Q1: "You mentioned 93 automated unit tests. What do they cover?"

> **Your Answer:**  
> *"I used `pytest` to build a comprehensive test suite across 4 main areas:*  
> *1. **AST Route Parsing**: Testing that `GET`, `POST`, `PUT`, `DELETE` routes, parameters, and middleware are accurately extracted from different code patterns.*  
> *2. **Dependency Graph Logic**: Testing that nodes and edges are properly created, updated when files change, and pruned when routes are removed.*  
> *3. **Context Extraction**: Testing that the extraction algorithm grabs only the connected subgraphs for an endpoint and stays within the token budget.*  
> *4. **FastAPI Endpoints**: Integration tests verifying that our REST API endpoints (`/api/health`, `/api/endpoints`, `/api/analysis`) return the correct JSON status codes and schemas.*  
>  
> *All 93 tests pass in about 4.5 seconds."*

---

### Q2: "How did you ensure you didn't break existing functionality when adding new features?"

> **Your Answer:**  
> *"I followed regression testing principles. Whenever I added a new feature—like CommonJS barrel re-exports or chained router methods—I ran the full 93-test suite (`pytest`). If any test failed, I caught the regression before merging. I also set up automated GitHub Actions CI that runs the tests and linter on every commit."*

---

## 7. Category 6: Deloitte Consulting & Business Value

### Q1: "Why would a client care about this? What is the business ROI?"

> **Your Answer:**  
> *"In enterprise development, two major pain points are **cloud AI costs** and **developer velocity**:*  
> *1. **Direct Cost Savings**: If a team of 50 developers runs AI code reviews on every pull request, sending 25,000 tokens per file review racks up huge LLM API bills. Trimming that context down by **78%** directly cuts inference costs by nearly 4x.*  
> *2. **Security Risk Reduction**: Finding security oversights (like unverified tokens or missing authorization checks) early in the IDE during development is drastically cheaper than fixing a breach in production.*  
> *3. **Less Noise & Higher Adoption**: Developers ignore tools that spam them with false positives. By feeding the AI only the exact code executed by an endpoint, findings are precise and actionable."*

---

### Q2: "How would you explain EndpointIQ to a non-technical project manager or client?"

> **Your Answer:**  
> *"I would use an analogy:*  
> *'Imagine taking your car to a mechanic because the brakes are squeaking. A bad mechanic takes apart the entire car—the radio, the air conditioning, the trunk—which takes hours and costs a fortune.*  
> *A good mechanic opens only the brake system, inspects the pads, and fixes the issue quickly.*  
>  
> *EndpointIQ is that smart mechanic for APIs. When a developer wants to review a specific login route, our tool isolates only the login path and its security checks, ignoring the rest of the app. It saves time, cuts costs, and finds the exact issue quickly.'"*

---

### Q3: "What would you do if a client has a massive 5,000-file repository?"

> **Your Answer:**  
> *"Because EndpointIQ uses an in-memory graph and only extracts the local 3-to-4 hop neighborhood of an endpoint, its extraction speed is independent of total codebase size. Even in a 5,000-file codebase, a single API route typically only touches 5 to 15 files. The extraction will still take ~10 to 15ms because it only walks the connected nodes for that route."*

---

## 8. Category 7: Quick-Fire Technical Basics (APIs & Python)

Be ready to answer these in 10 seconds:

| Question | Short, Flawless Answer |
|:---|:---|
| **What is an API?** | *"Application Programming Interface—a standardized set of rules and protocols that allows two software programs to communicate."* |
| **What is a REST API?** | *"An architectural style for web services using HTTP methods (`GET`, `POST`, `PUT`, `DELETE`) to operate on resources formatted as JSON."* |
| **Difference between `PUT` and `PATCH`?** | *"PUT replaces the entire resource; PATCH updates only the specific fields sent in the request."* |
| **Difference between 401 and 403?** | *"401 Unauthorized means authentication is missing or invalid. 403 Forbidden means the user is authenticated, but lacks permissions."* |
| **List vs Tuple in Python?** | *"Lists are mutable `[]`; Tuples are immutable `()` and faster."* |
| **What is a Python Decorator?** | *"A function that wraps another function to extend its behavior without modifying its source code (e.g. `@app.get` in FastAPI)."* |
| **What is JSON?** | *"JavaScript Object Notation—a lightweight, human-readable text format for data interchange across systems."* |

---

## 9. Interview Day Traps & Golden Rules

### 🚫 The 3 Traps to AVOID:
1. **Don't use unprompted buzzwords**: Don't say *"heterogeneous knowledge graph"* or *"Personalized PageRank teleportation vectors"*. Say *"in-memory dependency graph"* and *"tracing connected files"*.
2. **Don't claim you built a compiler**: You built a **code review tool** that uses an open-source parser to extract routes.
3. **Don't panic if you don't know a syntax**: Say: *"I don't recall the exact syntax off the top of my head, but conceptually the way it works is..."* Deloitte interviewers love candidates who understand concepts rather than memorizing syntax.

### ✅ The 3 Golden Rules to WIN:
1. **Focus on Business Value**: Mention cost savings (78% token reduction) and early bug detection.
2. **Emphasize Quality**: Mention your **93 automated unit tests** and multi-repo benchmarking.
3. **Be Structured**: Use 1-2-3 points (e.g. *"There are three reasons I chose FastAPI..."*). It shows consulting-ready communication!
