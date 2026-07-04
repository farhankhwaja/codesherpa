# sherpa

**A git-native, self-updating structural memory for your codebase.** Index
once, stay fresh forever, and let any LLM agent retrieve exactly the code
context it needs over MCP — function-level chunks under a token budget
instead of grep-and-read-the-whole-file.

- PyPI distribution: **`codesherpa`** · Python imports: `import codesherpa`
- Command line & MCP server: **`sherpa`** · index lives in `.sherpa/`

## Quickstart (3 commands)

```bash
pip install codesherpa
sherpa init                       # in your repo: hooks + first index + embeddings
claude mcp add sherpa -- python -m codesherpa.mcp_server "$PWD"
```

That's it. `init` installs `post-commit`/`post-checkout`/`post-merge`/
`post-rewrite` hooks that run `sherpa sync --quiet`, so the index follows
your HEAD automatically. First run downloads the embedding model (~0.5 GB,
one-time) to `~/.cache/sherpa/` and prints progress; after that everything
is fully local and offline. Try it from the shell with
`sherpa search "where is the retry logic for http requests"`.

## Why

Agents burn most of their context window navigating: grepping, opening whole
files, re-reading. sherpa gives them seven MCP tools that answer
*structurally*:

| tool | what it answers |
|---|---|
| `search_code(query, budget_tokens)` | hybrid lexical+semantic+symbol search, packed to a token budget |
| `get_definition(symbol)` | jump to a definition with signature + breadcrumb |
| `get_callers(symbol)` / `get_references(symbol)` | ranked callers / references (same-package first) |
| `get_recent_changes(since)` | commits + **symbol-level** diffs since a ref or ISO date |
| `expand(expand_id)` | full body of any compact result, on demand |
| `index_status()` | freshness, counts, warming state |

**The core idea:** every index entry is keyed by **git blob hash**. Blobs
are content-addressed, so branch switches, pulls, and rebases cost almost
nothing — only genuinely new blobs are parsed, chunked, and embedded. An
incremental index is *provably* identical to a from-scratch rebuild (the
"Golden Test" — property-tested on synthetic histories and replayed over
real Flask history).

## How it works

```
                 ┌──────────────────────────────┐
                 │       MCP server (stdio)     │  instant handshake; models
                 │ search · defs · callers ·    │  load lazily; never embeds
                 │ refs · recent · expand       │  at startup
                 └──────────────┬───────────────┘
                 ┌──────────────▼───────────────┐
                 │      Retrieval pipeline      │  router fast path <50 ms,
                 │ exact-symbol router ║ BM25 ∥ │  RRF fusion, cross-encoder
                 │ vector ∥ symbol → RRF → CE   │  rerank blended with the
                 │ rerank → 1-hop graph expand  │  dense ranking, budget-
                 │ → budget-aware packing       │  aware packing
                 └──────────────┬───────────────┘
      ┌──────────────┬──────────┴─────────┬──────────────┐
      │ FTS5 / BM25  │ vectors (sqlite-vec)│ symbol graph │  one SQLite file:
      └──────┬───────┴──────────┬─────────┴──────┬───────┘  .sherpa/index.db
             └──────────────────┼────────────────┘
                 ┌──────────────▼───────────────┐
                 │  cAST chunker (tree-sitter)  │  structure-aware chunks,
                 │  Python · TS · JS · TSX      │  byte-exact, deterministic
                 └──────────────┬───────────────┘
                 ┌──────────────▼───────────────┐
                 │  git layer (blob-hash keyed) │  hooks + incremental sync
                 └──────────────────────────────┘
```

Chunking is [cAST](https://arxiv.org/abs/2506.15655) (split-then-merge over
the AST) with breadcrumb headers (`path :: Class :: def method(...)`).
Embeddings: `nomic-embed-text-v1.5` (default; `all-MiniLM-L6-v2` is one
config line away and embeds ~30–40× faster at a small hybrid-recall cost).
Reranker: `ms-marco-MiniLM-L-6-v2` cross-encoder. Everything runs local,
CPU-only.

## Benchmarks (real numbers, no cherry-picking)

All numbers from `EVAL_LOG.md` (append-only), measured on an Apple M-series
CPU. Benchmarks were executed under this project's pre-rename name
(*repograph*); the code is identical.

**Retrieval quality** — 35-query gold set (incl. vocabulary-mismatch and
decoy queries) over a mixed Py+TS fixture; file-level hits:

| method | recall@5 | MRR | p95 warm |
|---|---|---|---|
| **hybrid + rerank (sherpa)** | **0.971** | **0.877** | 178 ms |
| BM25 only | 0.771 | 0.630 | 0.3 ms |
| vector only | 0.829 | 0.738 | 25 ms |

**External repos** — hand-built gold sets, full pipeline:

| repo | queries | hybrid recall@5 | MRR | p95 |
|---|---|---|---|---|
| pallets/flask (38 kLOC) | 14 | 0.857 | 0.768 | 261 ms |
| a private React+Node app (29 kLOC) | 12 | 0.833 | 0.674 | 207 ms |

**Indexing** — parse+chunk+store ~150 kLOC/s; cold `init` incl. embeddings:
flask 231 s (616 chunks, 13 MB index), the React+Node app 74 s (216 chunks,
5.9 MB). Warm re-sync with no new blobs: ~20–40 ms. Golden replay over
flask's last 30 commits: incremental ≡ rebuild across all 7 projections.

**Agent A/B** (21 tasks — debugging + feature-location — fresh headless
Claude Code session per task, with vs without sherpa; solution keys frozen
in advance): solve rate **21/21 with sherpa vs 19/21 without** (both
failures were navigation failures sherpa fixed), **39–69 % fewer whole-file
reads**, 12–48 % fewer tool calls. Honest miss: raw *token* usage per solved
task did **not** drop (−70 % on the small fixture, +2 % on the real app) —
sherpa's packed responses are token-dense and headless agents re-read
context each turn; billing-weighted cost landed within ±25 % of the control.
Details in `verification/ab/ab-results.md`.

## Honest limitations

- **Deep vocabulary-mismatch queries can still miss.** One gold query
  ("avoid asking the backend twice…" → a TTL cache class) is missed by every
  channel; docstring-weighted embedding variants didn't fix it without
  regressing other queries (DECISIONS.md D32).
- **The reranker is the CPU fallback.** BAAI/bge-reranker-v2-m3 scored
  +0.034 MRR but at 6.7 s p95 on CPU — 13× over our latency gate. We ship
  the MiniLM cross-encoder and will revisit on GPU/quantized runtimes.
- **Graph expansion is recall-neutral, not magic.** Measured Δrecall 0.000
  on flask and the React+Node app; MRR −0.054 on flask, +0.014 on the other.
  It stays on for the caller/callee context it attaches; flag to disable.
- **Token-frugality claim is nuanced.** See the A/B numbers above: fewer
  reads and better solve rates, but no raw-token reduction in headless runs.

## vs. other tools

Aider's repo-map ranks a *static summary* of the repo into the prompt —
great for one model loop, but it isn't queryable and re-ranks per prompt.
codebase-memory-mcp exposes a code index over MCP but rebuilds state rather
than keying it to git blobs, so branch switches and rebases re-pay indexing.
Unblocked is a closed SaaS with excellent context quality — sherpa is the
open, fully-local alternative: one SQLite file, no server, no code leaves
your machine. Headroom (context compression) is complementary — compress
what sherpa retrieves.

## Development

```bash
git clone <this repo> && cd sherpa
python -m venv .venv && . .venv/bin/activate   # Python ≥ 3.11
pip install -e ".[dev]"
python -m pytest -q          # full suite incl. golden + eval gates (~8 min, models download once)
```

Project governance: `CLAUDE.md` (spec), `DECISIONS.md` (every non-obvious
choice), `EVAL_LOG.md` (append-only benchmark record). See CONTRIBUTING.md.

## Roadmap

- Language connectors beyond Py/TS/JS/TSX (a language = one tree-sitter
  query file)
- bge-class rerankers on GPU/quantized runtimes (`TODO(upgrade)` markers)
- Compact-first `search_code` responses (the A/B token lever), `sherpa bench`
- Multi-ref tracking (index all local branches, not just HEAD)
- Optional `watchdog` fs-watcher for uncommitted edits

## License

MIT — see [LICENSE](LICENSE).
