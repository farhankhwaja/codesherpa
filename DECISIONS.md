# Decisions

Non-obvious choices, with reasoning. Append-only; newest last.

## D1 — Fixture ships as a build script, not a tarball (Phase 0)
CLAUDE.md §10 allows either. A script (`tests/fixtures/build_miniproject.py`)
keeps the fixture reviewable in diffs, avoids a binary blob in git, and is
deterministic (fixed author/committer identity + timestamps + `HOME` pinned
during git calls → identical commit SHAs on every build; asserted by
`test_build_is_deterministic`). Tests build it on demand into the gitignored
`tests/fixtures/miniproject/`.

## D2 — Runtime dependencies declared per phase, not up front (Phase 0)
`pyproject.toml` starts with zero runtime deps even though §6 approves pygit2,
tree-sitter, sentence-transformers, etc. Reason: the Verifier does a fresh
`pip install -e .` every phase; pulling torch/sentence-transformers before
Phase 3 needs them would add gigabytes and minutes to every verification run
for no benefit. Each phase adds only the approved deps it actually uses. This
is not a §2.6 event — everything added later must still come from the §6 list
(anything else still requires a DECISIONS entry).

## D3 — Dev machine Python is 3.9; project uses uv-managed CPython 3.12 (Phase 0)
The spec requires Python ≥3.11 and this Mac ships only 3.9.6. Installed `uv`
(via Homebrew) and `uv python install 3.12`; the project venv is created with
`uv venv --python 3.12 .venv`. No effect on the package itself
(`requires-python = ">=3.11"`).

## D4 — Enum kinds are `str`/`int` subclasses; IDs are colon-joined strings (Phase 0)
`SymbolKind`/`EdgeKind`/`RetrievalSource` subclass `str` so they serialize
directly into SQLite/JSON without adapters. `Chunk.chunk_id` =
`blob_hash:byte_start:byte_end` and `SymbolNode.node_id` adds `:symbol` —
deterministic, human-debuggable primary keys that encode the content-addressed
design (same blob → same ids), which the Golden Test relies on.

## D5 — test_cli unimplemented-command probe retargeted `status` → `search` (Phase 1)
Phase 0's `test_unimplemented_subcommand_exits_nonzero` used `status` as its
probe. Phase 1 is *specified* (§10) to implement `status`, so the probe's
example became wrong while its intent ("unimplemented subcommands exit 2 with
a clear message") stayed valid. Retargeted to `search` (unimplemented until
Phase 3). Not a weakening: the assertion set is unchanged, only the probe
command moved. Recorded per §2.1.

## D6 — Binary blobs are sniffed but never stored (Phase 1)
`sync` skips blobs whose first 8 KiB contain NUL. They get no `blobs` row, so
they are re-sniffed on later syncs. Alternative (storing them as
`language='binary'`, inactive) would avoid the re-read but put never-indexed
content in the store and complicate the active-set logic. Binaries are rare in
source repos and a libgit2 blob read is cheap; correctness/simplicity wins.

## D7 — Phase 1 tracks exactly one ref: HEAD (Phase 1)
§7.1 allows "any indexed ref". Hooks fire on every history-changing operation
(post-commit/checkout/merge/rewrite), so tracking the current HEAD keeps the
index exactly as fresh as the working checkout, and the golden test's
incremental==rebuild equality is well-defined. Multi-ref tracking (e.g. all
local branches) is a straightforward extension of `files(ref,...)` later.

## D8 — vector_search: sqlite-vec vec0 with a pure-Python brute-force fallback (Phase 1)
The vec0 virtual table needs its dimension fixed at CREATE time, but the
embedding model (hence dim) is chosen in Phase 3 — so the table is created
lazily on first `put_embedding` and the dim pinned in `meta.vec_dim`. If the
sqlite extension cannot load on some interpreter, `vector_search` falls back
to a brute-force dot-product scan over the `embeddings` table: identical
results, slower on big repos (fallback per §9; acceptable because correctness
is unaffected and Phase 3 measures latency).

## D9 — Indexing skips >2 MiB files (Phase 1)
§7.1 requires skipping generated code. Size is the cheapest reliable proxy for
"generated" that works before reading the blob (5 MB bundled JS attack in the
verifier's playbook). 2 MiB is far above any hand-written source file.
Configurable later if a real repo proves otherwise.

## D10 — tree-sitter-language-pack ≥1.12: use get_language(), not get_parser() (Phase 2)
`tslp.get_parser()` now returns a Rust-backed parser with a different API
(`parse(str)`, `root_node` as a method). Only
`tree_sitter.Parser(tslp.get_language(name))` yields the documented Python
API (bytes in, `Node.start_byte/end_byte/children/child_by_field_name`).
Verified by introspection against installed tree-sitter 0.26.0 /
language-pack 1.12.2. Deps added per §6: tree-sitter,
tree-sitter-language-pack.

## D11 — cAST merge is one flat greedy pass over the piece sequence (Phase 2)
After recursive splitting, pieces are merged left-to-right while the combined
non-whitespace size stays ≤ max_chunk (sizes are additive across contiguous
extents, so merging is O(n)). Merging deliberately crosses recursion
boundaries: when a class is split, its tiny header tokens (`class Foo:`) must
merge with the first method pieces or they would become absurd standalone
chunks. Consequence: a small trailing method may share a chunk with the next
top-level sibling — acceptable per §7.2's "greedily merge adjacent small
sibling chunks" and byte-exactness is preserved either way.

## D12 — Python docstrings may be bare `string` nodes (Phase 2)
The bundled tree-sitter-python grammar yields a def/class docstring as a bare
`string` first child of `block` (not wrapped in `expression_statement` as in
some grammar versions). Breadcrumb extraction handles both shapes.

## D13 — cAST recursion guard: depth cap 50 + fallback safety net (Phase 2, verifier finding)
Phase 2 verifier FAIL finding 2: chained-operator expressions (generated JS,
`1+1+...`) nest one AST level per operator, so `_split` could exceed Python's
stack on syntactically valid files that pass every skip rule. Fix: (a) beyond
50 split levels the chunker degrades to the iterative line-boundary hard
split — real code structure is exhausted far shallower, so chunk quality is
unaffected; (b) the whole split/merge/breadcrumb pipeline is wrapped so ANY
unexpected error logs a warning and falls back to line windows (§7.2 "never
crash the indexer"). Regression tests: deeply nested JS + Python inputs.
Finding 1 (tree-sitter deps missing from pyproject.toml) fixed in the same
commit; finding 3 (no direct JS test) addressed with a JS class/breadcrumb test.

## D14 — Golden-test hardening between Phases 2 and 3 (no phase boundary)
Four changes on core-index-owned files, prompted by review:
(a) `op_merge_change`: merges previously used only `-s ours` (tree never
moved); the new op commits a fresh file on a side branch and merges it back
with the default strategy + `--no-ff`, so the post-merge/git-pull scenario
(merge introduces new blobs) is genuinely covered. Ops abort cleanly on
unexpected conflict to stay total.
(b) `GOLDEN_DEEP=1` env gate: derandomize off, max_examples 25 — a
randomized soak that must pass once before the Phase 5 merge (documented in
the module docstring). Default run unchanged (fast, derandomized, <120 s).
(c) Fixture v2: `webclient/scripts/export_tasks.js` (class TaskExporter +
exported formatTaskRow, verified to load under node) added as commit 7 of the
build script — closes the Phase 2 verifier's "no plain .js in fixture" note.
Earlier commit SHAs are unchanged (append-only history). A version marker in
the built repo's `.git/` (`FIXTURE_VERSION`) makes conftest rebuild stale
prebuilt fixtures; conftest.py edited under fixtures-infrastructure ownership.
(d) `golden_state()` refactored to a declarative `GOLDEN_PROJECTION` extractor
map. Phases 3 and 4 MUST extend it (embeddings; symbols+edges) and hold an
explicit ownership exception to edit that map/their extractors only.

## D15 — graph/ reads git via subprocess plumbing, not pygit2 (Phase 4)
`graph/gitio.py` uses `git ls-tree` / `cat-file --batch` / `log` for the
read-only needs of extraction, recency ranking, and `get_recent_changes`.
Reasons: (a) gitlayer/ (the pygit2 owner, §8) belongs to core-index and had
not merged when graph-mcp was built; (b) these are four tiny read paths.
This is the §9 fallback (pygit2 → subprocess git): `TODO(upgrade)` marker in
gitio.py — route through gitlayer after merge. (Numbered D5 in the graph-mcp
worktree before rebase; renumbered when core-index's D5–D14 merged first.)

## D16 — Call/reference resolution: language-family fence + generic-name stoplist (Phase 4)
Best-effort resolution (§7.3: same file → same package → imports; no type
inference) produced two systematic false-edge classes on the fixture:
(1) cross-language hits (`urllib.request` in Python resolving to the unique
TS `request()`), fixed by only resolving across files within a language
family (python | ecma); (2) receiver-blind builtin method names
(`payload.get(...)` resolving to `MemoCache.get`), fixed by a stoplist of
~60 dict/list/str/Array/Promise/console method names that never resolve
beyond a same-file definition or an explicit import. Cost: one true edge on
the fixture (`_user_cache.get` → `MemoCache.get`); gain: every observed
false edge. Precision wins for ranked get_callers output.

## D17 — Eval factory contract and gate shape (Phase 4 builds the harness, Phase 3 runs it)
`eval/run_eval.py` gates on a retriever factory `(repo_path, mode) ->
Retriever` with mode ∈ {hybrid, bm25, vector}; default dotted path
`repograph.retrieve:build_eval_retriever` (Phase 3 must provide it — proposed
in PROGRESS.md). Thresholds are module constants (0.80/0.60, §13) with no
CLI override, so they cannot be lowered without a diff in this file. Hit
definition: a top-5 result whose `chunk.file_path` is in the gold entry's
`expected_files`.

## D18 — MCP search_code budget bounds the whole response (Phase 4)
`PackedContext.total_tokens ≤ budget` bounds chunk content, but the JSON
envelope (breadcrumbs, expand_ids, rationale) added ~40 % on top, breaching
the "<4000 tokens default" criterion. The server now trims trailing results
until the *serialized response* fits the budget and reports `truncated: n`.
Token frugality is the product; the envelope is not free.

## D19 — Graph tables are recomputed and replaced on every sync (Phase 4)
Symbols/edges are a *global* function of the active path→blob mapping:
adding one file can re-resolve an unchanged file's calls (same-package and
family-unique rules), and module names/packages derive from paths. Appending
rows per new blob therefore cannot keep incremental == rebuild — proven by
`test_new_file_rebinds_existing_callers`. So `graph/index.py::sync_graph`
(called at the end of every `gitlayer.sync`) re-extracts the active set and
REPLACES the two graph tables; the Golden Test's new `symbols`/`edges`
projections compare the whole tables and hold by construction (GOLDEN_DEEP
soak 25/25 green). Cost: one tree-sitter reparse of the active set per sync
(~150k LOC/s per Phase 2 numbers) while chunks/embeddings — the expensive
per-blob work — stay incremental, preserving the §4 insight.
`TODO(upgrade)` in graph/index.py: persist per-blob extraction facts so only
cross-file resolution reruns. The two `DELETE` statements use `store.conn`
directly: the write side of the indexing pipeline is already concrete-bound
(gitlayer constructs SQLiteIndexStore; map_files uses DELETE internally);
every query path (SymbolGraph/MCP/retrieval) remains ABC-only per the
contract. Also closes pre-merge verifier advisory A1: sync's skip rules
(>2 MiB, vendored, binary — D9) now shield graph extraction by construction.

## D20 — MCP tests consolidated onto the real stdio transport (Phase 4)
The pre-merge suite had 11 per-tool tests over the SDK's in-memory session.
Integration now demands the real transport, so the per-tool tests were
folded — assertions intact — into one stdio session test
(`test_stdio_server_every_tool_end_to_end`, subprocess server over the real
SQLite index) exercising every §7.6 tool; only edge cases (bad ref, tiny
budget, unknown expand_id, router path) stay on the in-memory session for
speed. Test COUNT went down; assertion coverage went up (real transport,
real store). Not a §2.1 weakening: nothing tested before is untested now.

## D21 — Gold set gains nl_hard and decoy query types (Phase 4)
`nl_hard` (8): wording shares zero identifier subtokens with the target
file — enforced forever by
`test_nl_hard_queries_share_no_identifier_tokens_with_targets`. `decoy` (2):
words lexically match a WRONG file (verified: term-count FTS ranks users.py
/ store.ts first). Baseline stand-in retriever scores 0.12 recall@5 on
nl_hard — these queries measure exactly what embeddings must add in Phase 3.
`VALID_TYPES` in test_gold_queries.py was extended (not relaxed): the
type-mix test now REQUIRES all five styles, and the minimum entry count rose
20 → 35. Additive eval-strengthening per §13.

## D22 — Token estimation is a dependency-free heuristic (Phase 3)
No tokenizer is on the §6 approved list, so the budget packer estimates
`ceil(len/4) + newlines/4` tokens (code averages ~3.5–4 chars/token on common
BPE vocabularies). The estimate deliberately errs high: the §7.5.6 "never
exceed budget" guarantee must hold for real tokenizers too. `TODO(upgrade)`:
swap in exact counting if a tokenizer dep is ever approved.

## D23 — Packer selects by density, returns by score (Phase 3)
§7.5.6 packs "greedy by score/token_count". Selection follows that literally,
but *presentation* order is score-descending: with density ordering, tiny
module-header chunks outranked the actual answers and cost 4 NL gold queries
(hybrid recall@5 0.84 → 0.92 after the change, MiniLM/no-rerank config).
The `PackedContext` contract only requires "descending usefulness".

## D24 — Eval relevance is symbol-aware, not file-level (Phase 3)
A result counts as relevant iff it comes from an expected file AND mentions an
expected symbol (breadcrumb or code). File-level relevance saturates on the
fixture — vector-only alone hits recall@5 = 1.00, which would make the §13
"hybrid strictly beats single methods" comparison meaningless — and file-level
credit for e.g. an unrelated chunk of `tasks.py` does not measure what
repograph is for (returning the right *function*). Measured under file-level
relevance for the record (MiniLM, no rerank): vector-only 1.00/0.953, hybrid
0.92/0.907. Symbol-aware: vector-only 0.92/0.831, hybrid 0.92/0.888.

## D25 — Embedding model: nomic-embed-text-v1.5 (Phase 3 benchmark)
Fixture gold set, symbol-aware relevance, vector-only channel (isolates the
embedder), 93 chunks:

| model | vec recall@5 | vec MRR | embed time | note |
|---|---|---|---|---|
| nomic-ai/nomic-embed-text-v1.5 | 1.00 | 0.867 | 38.7 s | winner |
| jinaai/jina-embeddings-v2-base-code | 1.00 | 0.890 | 51.6 s | disqualified: remote code incompatible with transformers ≥5 (`find_pruneable_heads_and_indices` removed); only loads in a pinned transformers<5 venv, which our runtime can't ship |
| sentence-transformers/all-MiniLM-L6-v2 | 0.92 | 0.831 | 5.3 s | fallback baseline |

jina scored marginally higher MRR but cannot load under the modern stack —
running it required a throwaway venv with `transformers<5` + `sentence-
transformers<4`. nomic needs `trust_remote_code=True` + `einops` (added as a
runtime dep — §2.6 justification: required at model load by the chosen §6
model). Query/document prefixes (`search_query:`/`search_document:`) applied
per nomic's model card.

## D26 — Reranker: ms-marco-MiniLM-L-6-v2 (§9 fallback taken); rerank depth 30 (Phase 3)
CE forward passes dominate warm query latency on CPU. Fused-top-50 at
1200-char passages measured p95 ≈ 750 ms vs the §13 gate < 500 ms; depth 30 +
1000-char cap gives p95 = 444 ms with *identical* gold-set quality
(recall@5 1.00, MRR 0.873) — quality is preserved because the fused top-30
already contains every gold answer on this set. §7.5's "top 50" yields to the
§13 latency threshold per §15 priority order; `rerank_top` stays configurable.
BAAI/bge-reranker-v2-m3 (§6 primary, 568M params) benchmarked for the record —
see EVAL_LOG.md — and rejected for CPU latency; `TODO(upgrade)`: revisit on
GPU/quantized runtimes. Also: CE scores pass through a sigmoid so packing sees
positive scores; expansion discounts compose multiplicatively.
