# EndpointIQ Benchmark Report

**Generated**: 2026-09-21 21:00:09 UTC
**Total Repositories**: 3
**Total Endpoints Benchmarked**: 36

## 1. Benchmark Corpus

| Repository | Language | Files | LOC | Source Tokens | Endpoints |
|-----------|----------|-------|-----|---------------|-----------|
| demo-api | TypeScript | 5 | 88 | 577 | 9 |
| realworld-express | TypeScript | 39 | 2,489 | 13,702 | 20 |
| express-boilerplate | JavaScript | 50 | 3,856 | 27,165 | 10 |

## 2. Indexing Performance

| Repository | Files Indexed | Graph Nodes | Graph Edges | Time (ms) | Throughput (files/sec) |
|-----------|--------------|-------------|-------------|-----------|----------------------|
| demo-api | 5 | 29 | 18 | 16 | 312.5 |
| realworld-express | 39 | 150 | 209 | 78 | 500.0 |
| express-boilerplate | 50 | 260 | 396 | 144 | 347.2 |

## 3. Token Efficiency (Primary Metric)

*Compares 'full repo dump' tokens vs EndpointIQ's MRC-extracted tokens.*

| Repository | Baseline Tokens | MRC Tokens (mean) | MRC Tokens (median) | Reduction % (mean) | Reduction % (median) |
|-----------|----------------|-------------------|--------------------|--------------------|---------------------|
| demo-api | 577 | 118 | 56 | 79.5% | 90.3% |
| realworld-express | 13,702 | 3,579 | 3,998 | 73.9% | 70.8% |
| express-boilerplate | 27,165 | 3,195 | 3,987 | 88.2% | 85.3% |

## 4. Recall, Precision & F1 (Ground-Truth Validated)

*Measured against hand-traced call chains. See `ground_truth.json`.*

| Repository | Labeled Endpoints | Recall (mean) | Precision (mean) | F1 (mean) |
|-----------|------------------|---------------|-----------------|-----------|
| demo-api | 5 | 1.00 | 0.93 | 0.96 |
| realworld-express | 8 | 1.00 | 0.47 | 0.63 |
| express-boilerplate | 5 | 1.00 | 0.26 | 0.41 |

## 5. Extraction Latency

| Repository | Endpoints | Mean (ms) | Median (ms) | P95 (ms) | Std Dev (ms) |
|-----------|-----------|-----------|-------------|----------|-------------|
| demo-api | 6 | 35 | 1 | 205 | 83.3 |
| realworld-express | 20 | 9 | 10 | 11 | 2.9 |
| express-boilerplate | 10 | 7 | 8 | 9 | 2.8 |

## 6. Per-Endpoint Detail

| Repository | Endpoint | Baseline Tokens | MRC Tokens | Reduction % | Nodes Selected | Latency (ms) | Recall | Precision | F1 |
|-----------|----------|----------------|------------|-------------|---------------|-------------|--------|-----------|-----|
| demo-api | `GET /health` | 577 | 44 | 92.4% | 2 | 205 | — | — | — |
| demo-api | `GET /` | 577 | 46 | 92.0% | 2 | 1 | 1.00 | 1.00 | 1.00 |
| demo-api | `GET /:id` | 577 | 56 | 90.3% | 2 | 1 | 1.00 | 1.00 | 1.00 |
| demo-api | `POST /` | 577 | 254 | 56.0% | 6 | 1 | 1.00 | 0.67 | 0.80 |
| demo-api | `PUT /:id` | 577 | 254 | 56.0% | 6 | 1 | 1.00 | 1.00 | 1.00 |
| demo-api | `DELETE /:id` | 577 | 56 | 90.3% | 2 | 1 | 1.00 | 1.00 | 1.00 |
| realworld-express | `GET /articles` | 13,702 | 3,998 | 70.8% | 45 | 10 | 1.00 | 0.50 | 0.67 |
| realworld-express | `GET /articles/feed` | 13,702 | 3,999 | 70.8% | 46 | 11 | — | — | — |
| realworld-express | `POST /articles` | 13,702 | 3,999 | 70.8% | 46 | 11 | 1.00 | 0.50 | 0.67 |
| realworld-express | `GET /articles/:slug` | 13,702 | 3,998 | 70.8% | 45 | 10 | — | — | — |
| realworld-express | `PUT /articles/:slug` | 13,702 | 3,999 | 70.8% | 46 | 10 | — | — | — |
| realworld-express | `DELETE /articles/:slug` | 13,702 | 3,999 | 70.8% | 38 | 10 | 1.00 | 0.60 | 0.75 |
| realworld-express | `GET /articles/:slug/comments` | 13,702 | 3,997 | 70.8% | 41 | 9 | — | — | — |
| realworld-express | `POST /articles/:slug/comments` | 13,702 | 3,995 | 70.8% | 40 | 10 | — | — | — |
| realworld-express | `DELETE /articles/:slug/comments/:id` | 13,702 | 3,997 | 70.8% | 38 | 10 | — | — | — |
| realworld-express | `POST /articles/:slug/favorite` | 13,702 | 4,000 | 70.8% | 48 | 10 | — | — | — |
| realworld-express | `DELETE /articles/:slug/favorite` | 13,702 | 3,999 | 70.8% | 48 | 10 | — | — | — |
| realworld-express | `POST /users` | 13,702 | 1,787 | 87.0% | 28 | 3 | 1.00 | 0.60 | 0.75 |
| realworld-express | `POST /users/login` | 13,702 | 1,760 | 87.2% | 25 | 3 | 1.00 | 0.60 | 0.75 |
| realworld-express | `GET /user` | 13,702 | 3,999 | 70.8% | 43 | 11 | 1.00 | 0.38 | 0.55 |
| realworld-express | `PUT /user` | 13,702 | 3,999 | 70.8% | 44 | 11 | — | — | — |
| realworld-express | `GET /profiles/:username` | 13,702 | 3,999 | 70.8% | 39 | 9 | 1.00 | 0.38 | 0.55 |
| realworld-express | `POST /profiles/:username/follow` | 13,702 | 3,995 | 70.8% | 49 | 10 | — | — | — |
| realworld-express | `DELETE /profiles/:username/follow` | 13,702 | 3,996 | 70.8% | 49 | 9 | — | — | — |
| realworld-express | `GET /tags` | 13,702 | 4,000 | 70.8% | 41 | 8 | 1.00 | 0.25 | 0.40 |
| realworld-express | `GET /` | 13,702 | 64 | 99.5% | 2 | 1 | — | — | — |
| express-boilerplate | `OPTIONS *` | 27,165 | 9 | 100.0% | 2 | 2 | — | — | — |
| express-boilerplate | `POST /register` | 27,165 | 3,977 | 85.4% | 86 | 8 | 1.00 | 0.33 | 0.50 |
| express-boilerplate | `POST /login` | 27,165 | 3,991 | 85.3% | 89 | 8 | 1.00 | 0.25 | 0.40 |
| express-boilerplate | `POST /logout` | 27,165 | 3,983 | 85.3% | 87 | 8 | — | — | — |
| express-boilerplate | `POST /refresh-tokens` | 27,165 | 3,989 | 85.3% | 88 | 8 | — | — | — |
| express-boilerplate | `POST /forgot-password` | 27,165 | 3,985 | 85.3% | 84 | 7 | 1.00 | 0.25 | 0.40 |
| express-boilerplate | `POST /reset-password` | 27,165 | 3,989 | 85.3% | 88 | 8 | 1.00 | 0.25 | 0.40 |
| express-boilerplate | `POST /send-verification-email` | 27,165 | 3,999 | 85.3% | 90 | 9 | 1.00 | 0.21 | 0.35 |
| express-boilerplate | `POST /verify-email` | 27,165 | 3,989 | 85.3% | 88 | 8 | — | — | — |
| express-boilerplate | `GET /` | 27,165 | 42 | 99.8% | 2 | 1 | — | — | — |

## 7. Aggregate Statistics (Across All Repos)

| Metric | Mean | Median | P95 | Std Dev | Min | Max |
|--------|------|--------|-----|---------|-----|-----|
| Token Reduction % | 78.80 | 70.84 | 99.85 | 11.40 | 55.98 | 99.97 |
| Extraction Latency (ms) | 12.58 | 8.50 | 11.00 | 33.19 | 1.00 | 205.00 |
| Recall | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 |
| Precision | 0.54 | 0.50 | 1.00 | 0.29 | 0.21 | 1.00 |
| F1 Score | 0.66 | 0.67 | 1.00 | 0.23 | 0.35 | 1.00 |

## 8. Methodology

### Baseline
- **Full Repo Dump**: All source files (`.ts`, `.js`, `.py`) concatenated into a single string
- Token count measured with `tiktoken` (cl100k_base encoding, used by GPT-4/Llama-class models)
- Directories excluded: `node_modules`, `.git`, `dist`, `build`, `__pycache__`

### EndpointIQ (MRC Extraction)
- `ProjectIndexer.full_index()` → builds the full knowledge graph
- `MRCExtractor.extract(endpoint, GoalType.FULL, token_budget=4000)`
- Pipeline: BFS subgraph → Personalized PageRank → Goal boosting → Greedy selection

### Ground Truth
- Hand-labeled call chains for selected endpoints across all 3 repositories
- Recall = |expected ∩ selected| / |expected|
- Precision = |expected ∩ selected| / |selected|
- F1 = 2 × (Precision × Recall) / (Precision + Recall)

### Statistical Reporting
- All metrics reported with Mean, Median, P95, Std Dev
- P95 = 95th percentile (near-worst-case performance)
