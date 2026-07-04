# CLAUDE.md — repograph

> **Read this entire file before doing anything. Every session, every subagent, every time.**

## 1. Mission

Build **repograph**: an open-source, local-first, git-native codebase index that any LLM agent can use via MCP to retrieve exactly the code context it needs — cutting token usage 60–90% on navigation-heavy tasks (debugging, triage, feature work) while improving answer quality.

One-line pitch: *A git-native, self-updating structural memory for your codebase. Index once, stay fresh forever, spend far fewer tokens on context.*

Reference points (study, then beat): Aider's repo-map, codebase-memory-mcp, Unblocked (closed-source SaaS — we are the open, local alternative), Headroom (compression layer — complementary, not a competitor).

## 2. Non-Negotiable Rules

1. **Tests are a ratchet.** Never delete, skip, weaken, or `xfail` an existing test to make progress. If a test seems wrong, fix the code first; only change the test if you can prove in `DECISIONS.md` why the test itself was incorrect.
2. **Interface contracts are frozen.** Files in `repograph/contracts/` may not be modified by any session or subagent. If a contract is genuinely blocking, write the problem to `BLOCKED.md`, commit, and stop that phase.
3. **The Golden Test is sacred.** `tests/test_golden.py` (incremental index == full rebuild) must exist before the indexer is written and must pass before every merge to main. A stale index is worse than no index.
4. **Commit at every green milestone.** Small commits, descriptive messages, conventional-commit style (`feat:`, `fix:`, `test:`, `perf:`).
5. **No mock data in production paths.** Mocks live only in `tests/`. Never fake an embedding, search result, or index entry to make something "work."
6. **No new runtime dependencies** beyond the approved list (§6) without recording justification in `DECISIONS.md`.
7. **Update `PROGRESS.md` continuously** (§12). A fresh session must be able to resume from CLAUDE.md + PROGRESS.md alone.

## 3. Autonomy, Loops, and When to Stop

You operate autonomously, including merging to main, under this protocol:

### 3.1 The Work Loop (applies to every task)

```
LOOP:
  1. Read the task's Success Criteria (§10).
  2. Implement the smallest slice that could satisfy one criterion.
  3. Run the relevant tests + linters.
  4. If green → commit → next criterion.
  5. If red → diagnose → fix → back to 3.
  6. When ALL criteria for the phase are green → invoke the Verifier (§11).
  7. Verifier PASS → merge protocol (§3.3). Verifier FAIL → treat findings as new red tests, back to 2.
```

### 3.2 The Confusion Protocol

If the same error persists or you are uncertain how something works:

- **Attempts 1–3:** Re-think from first principles. Re-read the relevant spec section here. Add a minimal reproduction test. Try a different approach.
- **Attempts 4–5:** STOP guessing. Research the internet: official docs for the library (tree-sitter, sqlite-vec, sentence-transformers, MCP SDK), GitHub issues, the reference papers in §14. Cite what you found in `DECISIONS.md`.
- **After 5 failed attempts:** Simplify. Implement the most conservative fallback listed for that component (§9 fallback column), record the downgrade in `DECISIONS.md` with a `TODO(upgrade)` marker, and move on. Never silently ship a broken component.

Never hallucinate an API. If you have not verified a function signature against installed package source or official docs, verify it before using it.

### 3.3 Autonomous Merge Protocol

You MAY merge a phase branch/worktree into `main` without human review **only if ALL of these are true**:

- [ ] Full test suite passes from a clean checkout: `pytest -x -q`
- [ ] Golden Test passes: `pytest tests/test_golden.py -q`
- [ ] Eval thresholds for the current phase are met (§13) and scores are appended to `EVAL_LOG.md`
- [ ] Verifier agent returned PASS (§11) and its report is committed to `verification/phase-N-report.md`
- [ ] No files under `repograph/contracts/` were modified
- [ ] `PROGRESS.md` and `DECISIONS.md` are updated

If any box is unchecked, do NOT merge. Write `BLOCKED.md` with a precise description and stop that line of work. Merge order when multiple worktrees are ready: `core-index` → `graph-mcp` → `retrieval` (schema owner merges first); rebase later branches onto main before merging.

## 4. What We Are Building (Architecture)

```
                    ┌────────────────────────────┐
                    │        MCP Server           │
                    │ search_code · get_definition│
                    │ get_callers · get_references│
                    │ get_recent_changes · expand │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │     Retrieval Pipeline      │
                    │ selective-retrieval router  │
                    │ BM25 ∥ vector ∥ symbol      │
                    │ → RRF → cross-enc rerank    │
                    │ → 1-hop graph expansion     │
                    │ → budget-aware packing      │
                    └─────────────┬──────────────┘
                                  │
      ┌───────────────────────────┼───────────────────────────┐
      │                           │                           │
┌─────▼──────┐            ┌───────▼───────┐           ┌───────▼───────┐
│ Lexical    │            │ Vector index  │           │ Symbol graph  │
│ (FTS5/BM25)│            │ (sqlite-vec)  │           │ (defs/refs/   │
│            │            │               │           │  calls/imports)│
└─────┬──────┘            └───────┬───────┘           └───────┬───────┘
      └───────────────────────────┼───────────────────────────┘
                                  │  one SQLite file: .repograph/index.db
                    ┌─────────────▼──────────────┐
                    │  cAST Chunker (tree-sitter) │
                    └─────────────┬──────────────┘
                    ┌─────────────▼──────────────┐
                    │  Git Layer (blob-hash keyed)│
                    │  hooks + lazy sync diff     │
                    └────────────────────────────┘
```

**The core insight (do not lose this):** every index entry is keyed by **git blob hash**. Blobs are content-addressed, so pulls, rebases, and branch switches cost almost nothing — only genuinely new blobs get parsed/embedded. This is our differentiator. Design every table and cache around it.

## 5. Repository Layout

```
repograph/
├── CLAUDE.md                  # this file
├── PROGRESS.md                # living status — every session updates it
├── DECISIONS.md               # every non-obvious choice, with reasoning
├── EVAL_LOG.md                # append-only eval scores per commit
├── BLOCKED.md                 # only exists when something needs the human
├── pyproject.toml             # single package, pip-installable, console script `repograph`
├── README.md                  # written last (Phase 6), with real benchmark numbers
├── repograph/
│   ├── contracts/             # FROZEN interfaces (Phase 0 writes, no one edits)
│   │   ├── index_contract.py
│   │   ├── retrieval_contract.py
│   │   └── types.py
│   ├── gitlayer/              # blob tracking, hooks, sync
│   ├── chunker/               # tree-sitter + cAST
│   ├── graph/                 # symbol extraction, edges
│   ├── embed/                 # embedding engine + cache
│   ├── store/                 # SQLite schema, FTS5, sqlite-vec
│   ├── retrieve/              # router, fusion, rerank, expand, pack
│   ├── mcp_server/            # MCP stdio server
│   └── cli.py                 # init / sync / search / status / serve / bench
├── tests/
│   ├── test_golden.py         # THE golden test
│   ├── fixtures/miniproject/  # small mixed Py+TS git repo used by tests & eval
│   └── ...
├── eval/
│   ├── gold_queries.jsonl     # ≥20 query → expected file/symbol pairs
│   ├── run_eval.py            # recall@5, MRR, latency; exits nonzero below thresholds
│   └── ab_harness.md          # protocol for Claude Code A/B token benchmark
└── verification/              # verifier reports per phase
```

## 6. Approved Stack

| Concern | Choice | Fallback (record in DECISIONS.md) |
|---|---|---|
| Language | Python ≥3.11 | — |
| Git access | `pygit2` | subprocess `git` plumbing |
| Parsing | `tree-sitter` + `tree-sitter-language-pack` | per-language grammar wheels |
| Storage | SQLite (stdlib) + `sqlite-vec` + FTS5 | FAISS flat index file if sqlite-vec fails |
| Embeddings | `sentence-transformers` with `nomic-ai/nomic-embed-text-v1.5` or `jinaai/jina-embeddings-v2-base-code` (pick by benchmark on fixture, record) | `all-MiniLM-L6-v2` (small, always works) |
| Reranker | `BAAI/bge-reranker-v2-m3` via sentence-transformers CrossEncoder | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| MCP | official `mcp` Python SDK, stdio transport | — |
| FS watch (optional, Phase 5) | `watchdog` | hooks-only |
| Tests | `pytest`, `hypothesis` for the golden test | — |

Everything must run **fully local, CPU-only** by default. First run may download models; cache them under `~/.cache/repograph/`.

## 7. Component Specs

### 7.1 Git Layer (`gitlayer/`)
- `repograph init` : install hooks (`post-merge`, `post-checkout`, `post-rewrite`, `post-commit`) that call `repograph sync --quiet`; create `.repograph/` (add to `.gitignore` automatically); run first full index.
- `repograph sync` : diff current `HEAD` tree (plus, if configured, working-tree files) against the set of blob hashes already indexed. Index new blobs; mark rows for blobs no longer reachable from any indexed ref as inactive (don't delete — cheap branch switching). Must be idempotent and safe to run concurrently (use a lockfile).
- Track per-file: path ↔ blob hash mapping per ref, language, mtime.
- Respect `.gitignore` and a `.repographignore`; skip binaries, vendored dirs, generated code (lockfiles, minified JS, `node_modules`, `dist`).

### 7.2 Chunker (`chunker/`) — implement cAST, not naive splitting
Algorithm (split-then-merge over the tree-sitter AST):
1. Parse file → AST. Walk top-level nodes.
2. If a node ≤ `max_chunk` (default 1600 non-whitespace chars): candidate chunk.
3. If a node > `max_chunk`: recurse into children; text between child boundaries stays with the preceding child.
4. Greedily merge adjacent small sibling chunks while combined size ≤ `max_chunk`.
5. Every chunk gets a **breadcrumb header** prepended *for embedding and display*: `# {repo-relative path} :: {enclosing class/module} :: {signature}` plus first docstring line if present. Store raw code and breadcrumb separately.
6. Chunk identity = `(blob_hash, byte_start, byte_end)`. Deterministic: same blob → same chunks, always.

Languages required: **Python, TypeScript, JavaScript, TSX**. Architecture must make adding a language = adding a tree-sitter queries file, nothing else. Unparseable files fall back to line-window chunks (120 lines, 20 overlap) — never crash the indexer on weird files.

### 7.3 Symbol Graph (`graph/`)
- Extract via tree-sitter queries: definitions (functions, classes, methods, consts), references, imports, and call edges (best-effort name resolution: same file → same package → import-based; do NOT attempt full type inference).
- Nodes carry `(symbol, kind, blob_hash, byte_range, file_path)`; edges carry `(src, dst, kind ∈ {calls, imports, references, defines})`.
- `get_callers(symbol)` returns **ranked** results: rank by (same-package proximity, reference count, recency of last change). Never an unordered dump.

### 7.4 Embedding Engine (`embed/`)
- Embed `breadcrumb + "\n" + code` per chunk. Batch (≥32). Normalize vectors.
- **Cache by chunk identity** — an embedding is computed at most once per unique chunk ever. Cache lives in the same SQLite DB.
- Model choice: benchmark both candidates on the fixture gold set in Phase 3; pick the winner; record numbers in `DECISIONS.md`.

### 7.5 Retrieval Pipeline (`retrieve/`)
Order of operations for `search(query, budget_tokens)`:
1. **Selective-retrieval router** (Repoformer-inspired): extract identifier-like tokens from the query (regex: `[A-Za-z_][A-Za-z0-9_]{2,}` with camelCase/snake_case awareness). If any token exactly matches a symbol definition → return definition + ranked 1-hop neighbors directly, skip dense search. This path must respond < 50 ms.
2. Otherwise run in parallel: FTS5 BM25 (top 100), vector search (top 100), symbol fuzzy match (top 20).
3. **Reciprocal Rank Fusion**: `score(d) = Σ 1/(60 + rank_i(d))` across the three lists.
4. **Cross-encoder rerank** the fused top 50 → keep scored list.
5. **1-hop graph expansion**: for the top 10, attach callers/callees/imports as candidate additions with a score discount (×0.6).
6. **Budget-aware packing**: greedy by `score / token_count`, deduplicate overlapping byte ranges and same-symbol chunks, stop at `budget_tokens` (default 4000). Return chunks with metadata: path, byte range, score, why-included (`bm25|vector|symbol|expansion`), and an `expand_id`.

### 7.6 MCP Server (`mcp_server/`)
Tools (stdio):
- `search_code(query: str, budget_tokens: int = 4000)` — main entry
- `get_definition(symbol: str)`
- `get_callers(symbol: str, limit: int = 10)`
- `get_references(symbol: str, limit: int = 20)`
- `get_recent_changes(since: str)` — commits/symbols changed since a ref or ISO date (triage superpower)
- `expand(expand_id: str)` — full chunk / surrounding context on demand
- `index_status()` — freshness, counts, last sync

Tool descriptions are marketing to the calling agent: each must state concretely when to prefer it over grep/reading files (e.g. *"Use this instead of grep + reading whole files: returns the most relevant function-level chunks across the repo under a token budget."*). Responses must be compact by default — that is the whole point of the product. Return `expand_id`s instead of dumping context.

## 8. Parallel Build Plan (worktrees)

Three named Claude Code worktree sessions after Phase 0 lands on main:

| Worktree | Owns (writable) | Builds |
|---|---|---|
| `core-index` | `gitlayer/`, `chunker/`, `store/`, `tests/test_golden.py`, fixtures | Phases 1–2 |
| `graph-mcp` | `graph/`, `mcp_server/`, `eval/` | Phase 4 pieces + eval harness (against contracts, mocked index until merge) |
| `retrieval` | `embed/`, `retrieve/` | Phase 3 pieces (against contracts, mocked store until merge) |

A session must not edit files owned by another worktree. Shared needs → propose in `PROGRESS.md`, implement only after `core-index` merges. Fresh-session rule: when context degrades, end the session; the next session reads CLAUDE.md + PROGRESS.md + `git log --oneline -20` and continues.

## 9. Fallback Ladder

If a primary approach fails after the Confusion Protocol (§3.2): pygit2→git subprocess; sqlite-vec→FAISS file; bge-reranker→MiniLM cross-encoder; call-edge resolution→references-only edges; nomic/jina→MiniLM embeddings. Every fallback taken = a `TODO(upgrade)` in code + entry in `DECISIONS.md`.

## 10. Phases, Goals, and Machine-Checkable Success Criteria

A phase is COMPLETE only when every criterion passes **from a clean checkout** and the Verifier signs off. Do not start a phase's successor in the same worktree until it is complete.

### Phase 0 — Skeleton & Contracts (main, single session, ~small)
Goal: freeze the shape so three sessions can build without colliding.
- [ ] `pyproject.toml` installs; `repograph --help` runs
- [ ] `contracts/types.py` defines `Chunk`, `SymbolNode`, `Edge`, `SearchResult`, `PackedContext` (dataclasses, fully typed)
- [ ] `contracts/index_contract.py` defines `IndexStore` ABC (add/lookup/deactivate blobs, chunk & symbol CRUD, FTS + vector query methods)
- [ ] `contracts/retrieval_contract.py` defines `Retriever` ABC (`search`, `get_definition`, `get_callers`, `get_references`, `expand`)
- [ ] `tests/fixtures/miniproject/` exists: a real git repo (created by a script, committed as a tarball or build script) with ≥15 Python + ≥10 TS files, cross-file imports and calls, ≥5 commits of history
- [ ] `eval/gold_queries.jsonl` has ≥20 entries against the fixture: mix of natural-language ("where is retry logic for http requests"), exact-symbol, and stack-trace-style queries, each with expected file(s) and symbol(s)
- [ ] Verifier PASS → merge to main → spawn worktrees

### Phase 1 — Git Layer + Store (worktree: core-index)
Goal: blob-hash-keyed SQLite store with correct incremental sync.
- [ ] `repograph init` on the fixture creates `.repograph/index.db`, installs all four hooks, updates `.gitignore`
- [ ] Schema: `blobs`, `files(ref,path,blob)`, `chunks`, `chunks_fts` (FTS5), `symbols`, `edges`, `embeddings`, `meta` — documented in `store/schema.sql`
- [ ] **Golden Test v1** (`hypothesis`-driven): from the fixture, perform a random sequence of ≥10 operations (commit new file, modify, delete, branch, switch, merge, revert); after each, `repograph sync`; final incremental DB state (active blobs, chunks, FTS rows) is **identical** to a from-scratch rebuild at the same HEAD. Runs in CI-time (<120 s).
- [ ] Sync is idempotent: running it twice changes zero rows
- [ ] Concurrent-safety test: two simultaneous syncs don't corrupt (lockfile)
- [ ] Indexing throughput measured and logged to `EVAL_LOG.md` (target ≥2000 LOC/s parse+store on fixture-class code, CPU)

### Phase 2 — cAST Chunker (worktree: core-index)
Goal: structure-aware chunks, deterministic, four languages.
- [ ] Split-then-merge implemented exactly as §7.2; unit tests cover: oversized class → recursed methods; small siblings merged; interstitial text preserved byte-exact (reassembling all chunks of a blob == original bytes)
- [ ] Same blob always yields identical chunk set (property test)
- [ ] Py/TS/JS/TSX parse on the fixture with 0 crashes; a deliberately-broken file falls back to line windows with a logged warning
- [ ] Breadcrumbs correct: chunk of a method inside a class carries `path :: ClassName :: def method(sig)`
- [ ] Golden Test still green (now covering chunks)
- [ ] **Merge core-index → main** per §3.3

### Phase 3 — Embeddings + Retrieval (worktree: retrieval)
Goal: hybrid retrieval that beats each single method.
- [ ] Embedding cache: re-indexing an unchanged fixture computes 0 new embeddings (assert via counter)
- [ ] Both candidate models benchmarked on gold set; winner chosen; numbers in `DECISIONS.md`
- [ ] RRF fusion implemented with tests on hand-built rank lists
- [ ] Reranker wired; toggleable via config
- [ ] Selective-retrieval router: exact-symbol queries answered <50 ms without touching vector search (test asserts the vector path was not called)
- [ ] Budget packer: never exceeds budget; deduplicates overlapping ranges (tests)
- [ ] **Eval gate:** on `eval/run_eval.py`: hybrid+rerank achieves `recall@5 ≥ 0.80` and `MRR ≥ 0.60` on the gold set, AND beats BM25-only and vector-only on recall@5 (print the table). If below threshold after the Confusion Protocol, improve chunk breadcrumbs / query preprocessing — do not lower the threshold.
- [ ] p95 query latency < 500 ms warm (reranker on), < 200 ms for router path
- [ ] Rebase on main, integrate real store, all green → **merge**

### Phase 4 — Symbol Graph + MCP (worktree: graph-mcp)
Goal: structural queries + agent-facing server.
- [ ] Definitions/references/imports/calls extracted for Py+TS on fixture; spot-check tests assert ≥10 known edges exist (e.g. `main.py:run → utils.py:retry`)
- [ ] `get_callers` returns ranked results with rationale fields
- [ ] `get_recent_changes(since)` correct against fixture history
- [ ] MCP server passes an integration test using the MCP client from the SDK: every tool callable, schemas valid, responses < 4000 tokens default
- [ ] Graph expansion wired into the retrieval pipeline (behind config flag) and eval re-run: expansion must not reduce recall@5; log delta
- [ ] Manual smoke documented in PROGRESS.md: connect to Claude Code via `claude mcp add`, run 3 real queries on this very repo, paste transcripts into `verification/`
- [ ] Rebase, integrate, all green → **merge**

### Phase 5 — Hardening + Full Benchmarks (main, single session)
Goal: prove the claims.
- [ ] `repograph init` end-to-end on **two real external repos** (clone e.g. `pallets/flask` and a mid-size TS repo): no crashes, index built, 5 sample queries return sensible results (store transcripts)
- [ ] Cold-index time and index-size-vs-repo-size logged for both
- [ ] Golden test run against one real repo's recent history (last 30 commits replayed)
- [ ] `eval/ab_harness.md` executed: same 10 tasks (5 debugging, 5 feature-location) on the fixture+one real repo, Claude Code **with** MCP vs **without**; record tokens per solved task, tool calls, file reads, fallback rate. Target: ≥50% token reduction on solved tasks with no drop in solve rate. Record honestly whatever the numbers are in `EVAL_LOG.md` — do not cherry-pick.
- [ ] Optional if time remains: `watchdog` fs-watcher for uncommitted edits (config-gated)

### Phase 6 — Ship (main)
- [ ] README: what/why, 3-command quickstart, architecture diagram, **real benchmark table from EVAL_LOG.md**, comparison paragraph vs Aider repo-map / codebase-memory-mcp / Unblocked, roadmap (connectors, Rust port, reranker upgrades)
- [ ] `pip install -e .` → `repograph init` → `claude mcp add` flow verified from a clean venv, documented exactly
- [ ] LICENSE (MIT), CONTRIBUTING.md, `.github/workflows/ci.yml` running the full suite
- [ ] Final Verifier PASS on the whole repo

## 11. The Verifier

Create `.claude/agents/verifier.md` in Phase 0 with `isolation: worktree`. The Verifier is adversarial QA, invoked at the end of every phase, and MUST NOT fix anything — only report.

Verifier procedure:
1. Fresh clean checkout of the branch. `pip install -e .` in a new venv.
2. Run the full test suite and the phase's specific criteria **literally as written in §10**, checking each box.
3. Hunt for cheating: grep for skipped/deleted tests vs previous phase (`git diff main -- tests/`), mock objects imported in non-test code, hardcoded fixture paths in `repograph/`, thresholds edited in `eval/`.
4. Run one exploratory attack: e.g. index a file with emoji identifiers, a 5 MB generated JS file, a symlink loop, an empty repo.
5. Write `verification/phase-N-report.md`: PASS or FAIL with a numbered findings list.

The implementing session treats every FAIL finding as a red test. A phase without a committed Verifier PASS report is not complete, and merging it is a violation of §3.3.

## 12. PROGRESS.md Protocol

Keep it under ~150 lines (prune completed detail into git history). Structure:

```markdown
# Progress
## Current phase & worktree
## Done (one line each, with commit hash)
## In progress (what, and the next concrete step)
## Blocked / open questions
## Notes for the next session (gotchas, key file locations, decisions pending)
```

Update it before every commit that ends a work session, and whenever you learn something a fresh session would need.

## 13. Eval Thresholds (summary)

| Gate | Metric | Threshold |
|---|---|---|
| Phase 3 | recall@5 (hybrid+rerank, gold set) | ≥ 0.80 |
| Phase 3 | MRR | ≥ 0.60 |
| Phase 3 | beats BM25-only & vector-only | recall@5 strictly greater |
| Phase 3/4 | p95 warm query latency | < 500 ms (< 200 ms router path) |
| Phase 4 | graph expansion | recall@5 non-decreasing |
| Phase 5 | A/B token reduction on solved tasks | ≥ 50% (report actual) |
| All | Golden Test | always green |

Thresholds may never be edited downward. If a threshold proves unreachable after honest effort, document why in `BLOCKED.md` and stop for human input.

## 14. Reference Material (research before implementing, cite in DECISIONS.md)

- cAST: *Enhancing Code RAG with Structural Chunking via AST* (arXiv 2506.15655) — the chunking algorithm
- Reciprocal Rank Fusion (Cormack et al., 2009)
- Repoformer (selective retrieval), RepoCoder (iterative retrieval), RepoGraph (repo structure graphs) — design inspiration
- Aider repo-map source (ranking ideas), codebase-memory-mcp (MCP tool-design comparison)
- sqlite-vec docs, tree-sitter query syntax docs, MCP Python SDK docs

## 15. Spirit Clause

Where this spec is silent, choose the option that best serves: (1) index freshness/correctness, (2) retrieval quality, (3) token frugality of responses, (4) zero-friction local install — in that order. You are encouraged to improve on this spec (better ranking features, smarter breadcrumbs, cleverer packing) **as long as every rule in §2 and every gate in §10/§13 still holds**, and each improvement is recorded in `DECISIONS.md` with before/after eval numbers. Make it worth using.
