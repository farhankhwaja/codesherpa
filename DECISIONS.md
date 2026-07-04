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
`codesherpa.retrieve:build_eval_retriever` (Phase 3 must provide it — proposed
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
sherpa is for (returning the right *function*). Measured under file-level
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

## D27 — Rerank stage redesigned for robustness on vocabulary-mismatch queries (Phase 3 integration)
Integrating the real store + hardened gold set exposed three defects in the
naive "CE rescores the fused top-N" design, each fixed and unit-tested:
(a) **Candidate pool = union of channel heads**, not fused-top-N. BM25
stopword floods pushed a vector-rank-4 chunk (q26, auth.ts) to fused rank 26
— beyond any reasonable rerank window, so the CE never saw it. The pool now
takes the head of each channel (8 vector, 8 BM25, 4 symbol) then fills from
fused order up to `rerank_top`.
(b) **Query-focused CE passages** (retrieve/passages.py). cAST chunks are
frequently whole files; head-truncation at the CE char cap hid definitions
deeper in the file. Passages are now the code window with maximal distinct
query-term coverage (identifier-split, deterministic, head-tiebreak).
Also cut p95 370 -> 184 ms (shorter average sequences).
(c) **CE order is rank-fused with the vector order** (weighted RRF, CE=1,
vector=`rerank_blend_vector_weight`), not a score overwrite. ms-marco-MiniLM
is web-trained and demotes correct code chunks on paraphrase queries where
the embedder is strong; conversely it rescues q32 (its rank 1 vs vector rank
6). Weight grid on the hardened set (internal symbol-aware relevance):

| w_vec | 1.0 | 1.5 | 2.0 | 2.5 | 3.0 | **4.0** | 6.0 |
|---|---|---|---|---|---|---|---|
| recall@5 | .914 | .914 | .914 | .914 | .943 | **.971** | .971 |
| MRR | .858 | .859 | .864 | .862 | .844 | **.844** | .845 |

w=4 chosen (start of the recall plateau; CE keeps lift power). Pure-CE mode
remains via `rerank_blend_vector=False`. Rerank depth is 20 with 700-char
passages (D26 latency reasoning; depth 30 measured p95 519 ms on real
whole-file chunks vs the <500 ms gate; depth 20 measures ~180 ms).
Official gate (eval/run_eval.py, file-level hits): hybrid 0.971/0.877
vs bm25 0.771 and vector 0.829 — GATE: PASS, sole miss q28.

## D28 — Embedding model benchmark re-run on REAL cAST chunks + hardened gold set (Phase 3 integration)
Real pipeline (gitlayer sync -> cAST whole-file-ish chunks with real
breadcrumbs), 34 chunks, 35 gold queries, vector-only channel, symbol-aware
relevance:

| model | vec recall@5 | vec MRR | embed 34 chunks | note |
|---|---|---|---|---|
| nomic-ai/nomic-embed-text-v1.5 | 0.94 | 0.830 | 13.6 s | **winner** (only §6 candidate that runs on our stack) |
| jinaai/jina-embeddings-v2-base-code | 0.97 | 0.847 | 11.8 s | still disqualified: loads only under transformers<5 (D25) |
| sentence-transformers/all-MiniLM-L6-v2 | 0.94 | 0.845 | 5.0 s | §9 fallback; parity with nomic on this fixture |

The §7.4 choice is between the two §6 candidates; jina remains runtime-
disqualified, so nomic stands. Observation for users/Phase 5: MiniLM reaches
parity on this small fixture at 7x the speed with no trust_remote_code —
worth re-benchmarking on real external repos before ship (`embed_model` is
config). The full pipeline passes the official gate with nomic (D27).

## D29 — Verifier findings: runtime deps restored; expired serve probe replaced (Phase 3, verifier FAIL round)
Final-verification FAIL had two mechanical causes, both fixed:
(a) **`sentence-transformers` + `einops` were missing from pyproject.toml.**
They were present on this branch pre-rebase; the third rebase's conflict
resolution script string-matched against main's OLD dependency-list text and
silently no-opped, dropping both lines while the comment referencing einops
survived. Clean installs then failed the eval gates and `sherpa serve`
died with a raw ModuleNotFoundError. Both are §6-sanctioned (D25 recorded
the einops justification); now actually declared. Lesson recorded: verify
conflict-resolution string replacements actually matched.
(b) **`test_serve_reports_missing_retrieval_pipeline` retired** (§2.1, D5
precedent). Its premise — "the retrieval pipeline does not exist yet, serve
must explain that and exit 2" — expired the moment this branch provided
`codesherpa.retrieve.build_retriever`; at commit 150a801 `serve .` genuinely
serves, so the probe failed in every configuration (and, per the verifier's
advisory, a passing real-serve run would have embedded the host repo from
inside the test suite: ~10 MB index + minutes of CPU). Replaced by
`test_serve_refuses_non_repository`: same fail-loudly/never-serve-fake-data
intent, asserted against the nearest remaining bad input (non-git dir,
nonzero exit, no .sherpa created), no server launch, no repo mutation.
Real serving is covered by the MCP stdio integration test. EVAL_LOG's
"273 passed at this commit" line was also stale (the suite run predated the
`build_retriever` commit); corrected in place with a note.

## D30 — Embedding computation moved out of server startup into init/sync (Phase 5)
Observed in the Phase 4 human smoke: `build_retriever` synced AND embedded the
whole repo before the MCP handshake, so a first `search_code` stalled ~1.5 min
(lazy model load) and a cold init embedded for ~2.5 min in silence. New
ownership: `sherpa init`/`sherpa sync` run the embedding pass
(codesherpa/retrieve/warm.py, with progress output — \r on a TTY, 10 % lines
otherwise); the production `build_retriever` only OPENS the existing index
(no sync, no embed, no model import) and raises `IndexNotBuiltError` when
there is none, so `sherpa serve` exits 2 with "run `sherpa init`"
instead of building an index as a side effect. While embeddings are missing
the server still serves (BM25 + symbol + router channels) and every
`search_code`/`index_status` response carries a `warming` field with the
missing-embedding count and a "run `sherpa sync`" hint — the amendment's
"warming status" option, chosen over in-server async embedding to keep the
serving process single-writer (the store connection is not thread-safe and
embedding contends for the same SQLite file the server reads).
Related choices:
(a) quiet syncs (= git hooks) embed incrementally but pass
`require_cached_model=True`: a hook never downloads a model; first downloads
belong to a foreground init/sync. Hook cost when models are cached: one model
load (~2–8 s) only when new chunks actually exist, else zero.
(b) Embeddings are invalidated by an `embed_tag` = model name + text version
recorded in `meta`: switching `embed_model` (or bumping EMBED_TEXT_VERSION)
wipes the old vectors and the vec0 dim pin instead of silently mixing vector
spaces in one KNN table (previously a dim mismatch raised at put time; a
same-dim model switch would have gone completely undetected).
(c) `sentence_transformers` loads pass `local_files_only=True` whenever the
model directory already has a snapshot in ~/.cache/sherpa/models (checked
against installed ST 5.6.0 signatures): warm starts perform zero network
calls (§3f).
(d) `sherpa search` implemented (it needs exactly this read-only wiring;
required for Phase 5 external-repo transcripts); the CLI
unimplemented-command probe retargeted `search` → `bench` per the D5
precedent — assertions unchanged.

## D31 — Router token regex stays ASCII-only (Phase 5 §3d decision)
`_TOKEN_RE = [A-Za-z_][A-Za-z0-9_]{2,}` deliberately does not use `\w`.
Reasons: (1) the router is a *precision* device — it bypasses dense retrieval
entirely, so a false identifier match costs an entire query's quality, while
a miss only costs the <50 ms fast path (the query still gets full hybrid
retrieval, including FTS5, which handles non-ASCII text fine); (2) the §7.2
target languages (Py/TS/JS/TSX) overwhelmingly use ASCII identifiers in
public code, and the symbol table lookup is exact-match, so widening only
helps repos with non-ASCII *definitions* — rare enough that we have no
corpus to validate against; (3) `\w` in Python matches digits/marks across
every script, which would promote ordinary words of non-English prose
queries to identifier candidates and re-open the "connect" hijack class D21
guarded against, now in scripts where the `_looks_like_identifier`
morphology heuristics (camelCase, snake_case) do not apply. Revisit on a
real user report with a concrete repo; the change would be a one-line regex
widening plus morphology rules per script. Exploratory check: emoji/CJK
identifiers index and retrieve via FTS/vector paths without crashing (Phase
2 verifier attack + this phase's external-repo runs).

## D32 — q28 fix attempt: docstring-weighted embedding text REJECTED (Phase 5 §3c)
q28 ("avoid asking the backend twice for the same person's details" →
pyserver/cache.py MemoCache) is the sole official-gate miss. Two variants
measured against the current text (breadcrumb + code), nomic, vector-only
ranking over the fixture's 34 real chunks, 35 gold queries:

| variant | recall@5 | MRR@5 | q28 rank | side effects |
|---|---|---|---|---|
| A current (ship) | 0.943 | 0.824 | 17 | — |
| B doc lines prepended to text | 0.943 | 0.795 | 17 | q32 rank 5→9 |
| C dual vectors (full + breadcrumb/doc summary), max-pool | 0.914 | 0.836 | 6 | q26→6, q32→8: net recall DOWN |

Diagnosis: the chunk's breadcrumb already contains the module docstring line
("Tiny in-memory TTL cache used for hot lookups (e.g. users by id)"), and a
doc-only summary vector still scores 0.572 vs the winner's 0.597 on q28 —
the miss is an embedder-semantics ceiling ("asking twice" ↛ "TTL cache"),
not a text-shaping problem, and every reshaping that helps q28 pushes other
nl_hard queries out of their top-5. Kept EMBED_TEXT_VERSION=1 / the D25 text
unchanged; q28 stays the documented honest limitation (README, EVAL_LOG).
Infrastructure kept from the attempt: the embed-tag invalidation (D30b)
makes any future text-version change safe to ship.

## D33 — Embedding model re-benchmark on real external repos: nomic stays default (Phase 5 §3a)
Fixture parity (D28) demanded a real-repo rematch. eval/external/bench_external.py
on flask (616 chunks, 14 gold queries) and sizly (216 chunks, 12 queries),
file-level hits, CPU:

| repo | model | vector-only r@5 / MRR | **hybrid r@5 / MRR** | embed time |
|---|---|---|---|---|
| flask | nomic-embed-text-v1.5 | 0.357 / 0.310 | **0.857 / 0.768** | 237.7 s |
| flask | all-MiniLM-L6-v2 | 0.786 / 0.583 | 0.786 / 0.649 | 6.4 s |
| sizly | nomic-embed-text-v1.5 | 0.417 / 0.361 | **0.833 / 0.674** | 75.4 s |
| sizly | all-MiniLM-L6-v2 | 0.833 / 0.688 | 0.833 / 0.632 | 1.7 s |

Two honest surprises: (1) nomic's ISOLATED vector channel is far weaker than
MiniLM's on real repos (0.36–0.42 vs 0.79–0.83) — the opposite of the
fixture ranking (D25/D28); (2) the FULL pipeline still ranks nomic first on
both repos (flask +0.071 recall / +0.119 MRR; sizly tie recall, +0.042 MRR):
the D27 channel-union + CE/vector rank blend compensates for weak isolated
dense rankings, and nomic's vectors still contribute more useful *candidates*
to the union than they lose in ordering. Decision: **ship nomic as default**
(§15 priority: retrieval quality over install friction) — the user-visible
metric is the hybrid, and it is strictly better or equal everywhere measured.
MiniLM stays one config line away (`embed_model`; embed-tag invalidation D30b
makes switching safe) for CPU-frugal users: 30–40× faster embedding at
0–7 pts hybrid recall cost. Recorded verbatim even though it complicates the
D25 story — the fixture benchmark overstated nomic's dense-channel edge.

## D34 — Graph expansion stays ON: flask/sizly delta measured (Phase 5 §3b)
The fixture delta (0.000) was uninformative. External measurement (same runs
as D33, shipping pipeline): recall@5 delta 0.000 on BOTH repos (flask
0.857→0.857, sizly 0.833→0.833); MRR: flask 0.821 (OFF) → 0.768 (ON)
= −0.054, sizly 0.660 (OFF) → 0.674 (ON) = +0.014. The §13 gate binds
recall (non-decreasing ✓). Mechanism of the flask MRR dip: expansion
attaches discounted (×0.6) neighbors of top hits, which can outrank a
lower-scored relevant chunk inside the top-5 without evicting it. Kept ON:
recall is gate-protected, the MRR effect is small and sign-mixed, and
expansion is the feature that surfaces callers/callees context agents
actually use (Phase 4 smoke). Config flag remains for A/B.

## D35 — A/B benchmark: execution choices and the target-miss handling (Phase 5)
Choices made before any run: model `sonnet` in both arms (identical-settings
rule; sized like real agent deployments); max-turns 40 + 20-min wall cap
(the cap converts a runaway session into an honest unsolved row — arm A hit
it once, 107 tool calls without an answer); `tokens_total` counts all input
variants incl. cache reads plus output (the CLI's cumulative session usage —
the harness's "input + output"), with fresh-token and billing-cost columns
reported alongside so no framing hides the raw number. Grading: programmatic
key-symbol/path match over the final answer, manual review of every row, and
one pre-declared judgment call applied symmetrically (an "…my earlier answer
stands" final message counts iff the key was stated earlier in-session;
happened once per arm). Ground-truth stripping is code, not discipline:
parse_tasks() removes HTML comments and was asserted against the leak
keywords before arm A ran.
Result: the §13 ≥50 % token-reduction target was missed (fixture −69.8 %,
sizly +2.2 %) while the solve-rate guardrail passed with B strictly better
(21/21 vs 19/21). Handling per the governing texts: numbers recorded
verbatim in EVAL_LOG (§10 Phase 5 "record honestly whatever the numbers
are"), the gap filed as BLOCKED.md B3 (§13), zero post-measurement reruns
or tuning (ab_harness honesty rules), and the phase proceeded to merge under
the human's explicit Phase 5 amendment "Record whatever the numbers are — no
cherry-picking" — read as pre-authorizing honest-miss-and-continue rather
than halting the mandated Phase 5+6 execution. The README's benchmark
section reports the miss in plain language and claims only what held up:
higher solve rate, fewer tool calls/file reads, cost parity.

## D36 — recent_changes: bare ISO dates pinned to UTC midnight (Phase 5)
The pre-merge full-suite run failed `test_since_iso_date` at 19:53 IST after
passing all day: git's approxidate reads a bare `--since=2024-01-07` as that
date at the CURRENT wall-clock time, so `get_recent_changes("2024-01-07")`
silently excluded same-day commits depending on when/where it ran — a
correctness bug in the code (its contract says "commits on or after the
date"), not in the test (§2.1: code fixed, test untouched). Bare dates are
now normalized to `<date>T00:00:00Z`; full ISO datetimes pass through
verbatim. UTC (not local) midnight so the same query returns the same
commits on every machine.

## D37 — Project renamed repograph → sherpa/codesherpa (human instruction, post-Phase-5)
Explicit human instruction (two messages, the second amending the first).
Final naming split and why: **PyPI distribution `codesherpa`**
(PyPI-unique) and **Python package/imports `codesherpa`** (the existing
PyPI `sherpa` package owns the `import sherpa` namespace — a top-level
module collision is unacceptable), while everything user-facing is
**`sherpa`**: console script / CLI command, MCP server name, index dir
`.sherpa/`, ignore file `.sherpaignore`, model cache `~/.cache/sherpa/`.
So: `pip install codesherpa` → run `sherpa init` → `import codesherpa`.
Scope decisions:
(a) `codesherpa/contracts/` files' import lines changed with the package
name — a §2.2-frozen surface touched ONLY under this explicit human
instruction; interfaces/signatures are byte-identical otherwise.
(b) Historical records keep the old name verbatim: EVAL_LOG.md (append-only
by its own charter), verification/ reports and A/B transcripts (they
describe runs of the artifact as it was then named). CLAUDE.md (the human's
governing spec) is also untouched; the mapping is recorded here and in
PROGRESS.md for fresh sessions: read CLAUDE.md's "repograph" as this
project — package now `codesherpa`, command now `sherpa`.
(c) Mechanical gotcha for posterity: a single-pass sed chain double-applied
(`sherpa.retrieve` matched inside freshly-written `codesherpa.retrieve` →
`codecodesherpa`); caught by import failure, fixed, and the final audit
greps for both stale module refs and nested artifacts.
(d) Local model cache moved (`mv ~/.cache/repograph ~/.cache/sherpa`), no
re-download. Suite green in-tree after each stage and from a clean
checkout (verified before merge).

## D38 — Embedding memory blowup on single-line mega-chunks (Phase 6 hardening finding)
Found dogfooding the ship flow: `sherpa sync` on a clone of THIS repo hung
with runaway memory (14–17 GB RSS, 61 min CPU; reproduced twice, killed by
the human). Diagnosis chain, with an isolated guarded repro:
(1) The repo's committed A/B transcript files (verification/ab/fixture/
*.stream.jsonl) are single-line files of 54–288 KB — under the 2 MiB
whole-file guard, not in any junk dir, so correctly indexed. (2) The
line-window fallback chunker had NO byte cap: a single-line file is one
window, so one 287 KB chunk. (3) The embedder's tokenizer truncates each
text to the model's max_seq_len (8192 for nomic) — ONE mega-chunk encodes
fine (measured 4.6 s / 1.8 GB RSS) — but sentence-transformers sorts by
length, so ALL the mega-chunks land in the same batch of 32; attention
memory is batch × heads × seq², measured 2.6 GB at batch 2 and extrapolating
to ~25 GB at batch 32 — the observed pathology. The ignore rules were NOT at
fault (sync itself: 142 files in 0.25 s; .venv untracked and also in
SKIP_DIR_COMPONENTS).
Fixes, each with a regression test:
(a) fallback chunker: hard `MAX_CHUNK_BYTES = 16384` — oversized windows are
split into contiguous byte slices (single-line 2 MB file → capped chunks,
full coverage, deterministic);
(b) engine: `ENCODER_MAX_CHARS = 8192` head-truncation of every text fed to
the encoder (chunk text AND query) — the engine-level bound that holds for
any input; no legitimate cAST chunk comes near it, so no cached vector
changes (no embed-tag bump);
(c) `.cache` added to SKIP_DIR_COMPONENTS (the one junk dir missing —
.venv/venv/node_modules/dist/build were already there);
(d) `sherpa sync` prints `indexing files done/total` progress (non-quiet,
>20 files) so long first syncs are distinguishable from hangs;
(e) batches already stream to the DB per batch (warm.embed_index →
engine.embed_chunks writes each vector immediately); RAM was transformer
activations, not accumulation — documented, not changed.
Related cleanup found during the same investigation: the rename sed turned
.gitignore's `.repograph/` into `.sherpa/`, so the legacy `.repograph/`
index dir became unignored and the rename commit accidentally tracked
7.5 MB+ of index binaries. Removed from tracking; `.repograph/` re-ignored
permanently; `sherpa init` now warns when a legacy `.repograph/` dir exists.

## D38-final — Corrected diagnosis: token-level clamp closes the memory hole (Phase 6)
D38's first fix (byte-cap fallback chunks + CHAR-cap encoder input) did not
close the hole: a clean-clone `sherpa init` still ran away (10–15.5 GB RSS,
reproduced live). Named-culprit instrumentation on the real engine path
(per encode call: chunk ids, paths, byte length, TOKENIZED length, current
RSS via ps before/after) identified the mechanism exactly:

- The char cap held (max 8,209 chars/text) but dense JSON tokenizes at
  ~2.6 chars/token, so texts reached **3,093 tokens**; ONE batch of 32 such
  texts took RSS 1.6 → 10.1 GB in a single forward pass (attention =
  batch × heads × seq²). A character cap is the WRONG UNIT.
- Verified independently on the trust_remote_code path: after clamping,
  `model.tokenize` of 8,192 chars of dense JSON returns exactly 1,024 input
  ids — nomic honors ST's max_seq_length; no tokenize-first workaround
  needed.
- Accumulation ruled out: 12 consecutive short-text batches hold current
  RSS flat at 1.45 GB (results stream to SQLite per batch; ST encode runs
  under no_grad; nothing retained across calls). The worst real batch peaks
  4.3 GB and falls back to 3.9 GB.

Fix: `ENCODER_MAX_TOKENS = 1024` — the engine clamps the loaded model's
max_seq_length (typical cAST code chunks are ~450 BPE tokens, so no cached
vector changes; only pathological data chunks are tail-truncated). The char
cap stays as a cheap pre-tokenization guard, and the D38 chunker byte cap
stays as defense in depth. Regression tests written failing-first:
max_seq_length clamp asserted on the load path, plus a REAL-nomic subprocess
test that embeds 16 dense-JSON texts and asserts peak ru_maxrss < 6 GB
(tests/test_embed_memory.py).

Proof on the reproducing case: clean-clone `sherpa init` on this repo now
completes 535/535 chunks in 137 s with **peak RSS 4.06 GB**
(/usr/bin/time -l). Note for the record: one "the fix failed" observation
during this investigation was a stale PRE-fix init process that had kept
running and was killed at 10.5 GB — the timed post-fix runs are the ones
above. The Phase 6 verifier's exploratory attacks must include a clean-clone
`sherpa init` with a memory ceiling.

## D39 — Compact-first search_code (human's B3 decision, Phase 6)
The human resolved BLOCKED B3: ship the token-diet as a product change and
re-measure. `search_code` now defaults to a **1500-token budget** and
returns **signature/breadcrumb + expand_id rows with no code bodies**
(`include_code=true` restores full rows); the tool description steers the
agent to expand() only the 1–2 hits that matter. Response-envelope trimming
(D18) unchanged and now binds at 1500. The frozen Retriever contract is
untouched (its search() default stays 4000 — this is MCP-layer presentation).
Measured in the A/B v2 rerun on the same 21 frozen tasks (EVAL_LOG; v1 entry
untouched per the harness honesty rules).

## D40 — B3 resolved by the human: SHIP with the measured v2 profile (post-Phase-6)
Final human decision on BLOCKED B3: ship. The §13 ≥50 % raw-token-reduction
threshold is NOT lowered and stays recorded as **MISSED** in EVAL_LOG and
the README (language unchanged, per instruction). Rationale for the record:
`tokens_total` in headless mode is dominated by client-side cache re-reads
and mismeasures real cost; the operative measures are billing-weighted cost
(−52.7 % on sizly, v2), whole-file reads (−55/−61 %), and solve rate
(20/21 vs 19/21) — all favorable with the D39 compact-first responses. A
≥50 % raw-token reduction remains an open target, to be re-measured on
large-repo benchmarks where navigation dominates harder (roadmap item).
BLOCKED.md is deleted per its own charter (it exists only while something
needs the human); B3's full history stays in git, EVAL_LOG (v1+v2 entries),
verification/ab/ab-results*.md, and D35/D39/this entry.

## D41 — CI latency gates: hardware calibration, not a threshold reduction (post-ship)
First CI run on GitHub's 2-core hosted ubuntu runner failed
`test_p95_warm_latency_reranker_on`: p95 = 1,764 ms vs the §13 500 ms gate.
Not a regression — the identical commit measures p95 178 ms on the machine
the §13 latency thresholds are defined on (Apple M-series; every EVAL_LOG
latency entry names that hardware). Human decision: latency gates are
hardware-relative; correctness gates are not. Implemented exactly that,
nothing broader:
- `SHERPA_LATENCY_BUDGET_SCALE` env var (default 1.0) applied ONLY to the
  two latency assertions in tests/test_eval_gate.py (500 ms warm, 200 ms
  router). All recall/MRR/memory/golden assertions remain unconditional
  and unscaled.
- ci.yml sets SHERPA_LATENCY_BUDGET_SCALE=4 on the suite step with an
  inline comment citing the 2-core-runner calibration and the measured
  1,764 ms. A future ~10x regression still fails CI even at scale 4.
- Both latency tests PRINT the measured p95 and the effective budget pass
  or fail, so CI logs surface latency drift on the runner over time.
- The unscaled gate remains enforced for every local/verifier run. §13
  thresholds themselves are untouched.
Also observed on that run and reported, not hidden: 1 skip ('...s...')
where the suite historically had zero — tests/test_embed_memory.py::
test_dense_json_batch_embeds_with_bounded_rss. Its skipif evaluates
`model_is_cached(nomic)` at COLLECTION time; on a cold-cache Linux runner
the model only downloads mid-suite (inside the eval gates), so the
real-model RSS regression test skips on that first pass. It executes
everywhere the cache is warm: all local runs, and CI runs after the first
green run saves the model cache (actions/cache saves only on success).
The max_seq_length clamp unit test beside it runs unconditionally.
Pre-declared flake policy (decided now so future sessions don't drift):
scale 4 = a 2,000 ms budget vs the measured 1,764 ms — only ~12 % margin on
a shared runner with noisy neighbors. If the latency gate flakes ONCE with
no code change, bump the scale to 5 in a one-line commit citing that run,
and STOP there — 2,500 ms still fails hard on any genuine ~3x regression.
No further bumps without a new DECISIONS entry explaining why the runner
class itself changed.

## D42 — Relicense MIT → Apache-2.0 + DCO contribution policy (human instruction, pre-public)
Relicense executed before the repo goes public. Clean because the sole-
copyright-holder assumption was VERIFIED, not assumed: `git log` authorship
and committer identity are 100 % Farhan Khwaja <farhan.khwaja@gmail.com>
(50/50 commits, no second identity, no co-author trailers) — nothing to
flag. Changes: full standard Apache-2.0 text in LICENSE (appendix
boilerplate filled: Copyright 2026 Farhan Khwaja); NOTICE file per Apache
convention; pyproject moves to a PEP 639 SPDX expression
(`license = "Apache-2.0"`, license-files incl. NOTICE; build-system bumped
to setuptools>=77 which introduced PEP 639 support — verified: built
metadata emits `License-Expression: Apache-2.0`); README license section
updated. CONTRIBUTING gains "Sign-off required (DCO 1.1, git commit -s,
developercertificate.org)" — provenance stays clean and the project keeps
the ability to make future licensing decisions (commercial licensing or
hosted services are explicitly possible); contributors retain copyright,
no CLA; maintainer commits predate the policy. Note: the user-referenced
"test asserting LICENSE exists" did not exist — added
tests/test_licensing.py so the legal posture is now pinned by the suite.
Historical records (CLAUDE.md §10's "LICENSE (MIT)" checklist line, past
verifier reports, EVAL_LOG) intentionally keep the old wording; PROGRESS
records "MIT at ship; relicensed Apache-2.0".

## D43 — Go language support (Phase A, feature/go-support)
Go joins Py/TS/JS/TSX following the "a language = a LanguageSpec + a query
file" architecture, with four Go-specific choices:
(a) **Receiver-scoped breadcrumbs.** Go methods are TOP-LEVEL declarations
(not nested like class methods), so recursion never hands them a scope;
cast.py surfaces the receiver instead: `path :: (Store) :: func (s *Store)
Save(...)` (pointer stripped). The same rule feeds `_node_name` when an
oversized method recurses.
(b) **Receiver-typed call resolution, evidence-authoritative.** go.scm emits
`@call.recv` (selector operand) and `@bind.name/@bind.type` (params — incl.
method receivers — `var x T`, `x := T{...}`, `x := &T{...}`). When a call's
receiver has a locally evident type, resolution consults ONLY that type's
methods; no match (interface value, external type) -> the edge is DROPPED —
type evidence is never overridden by name guessing. Pinned by a two-types-
one-method-name disambiguation test and an interface-parameter negative
test. Without evidence the ordinary §7.3 ladder applies, so a call through
a struct FIELD typed as an interface may still resolve by package-unique
name — documented best-effort, same as every other language; **interface-
satisfaction resolution is explicitly out of scope** (requires type
checking).
(c) **Package imports resolve to a representative file.** Go imports name a
package (module-qualified); the resolver suffix-matches progressively
shorter tails of the import path against project directories and represents
the package by its lexicographically first .go file (imports are
module-to-module edges, so any stable representative works). Aliased
imports bind the alias. Stdlib/external imports resolve to None.
(d) **Router morphology gained code-context shapes.** Go exported symbols
are single-capital PascalCase (`Flush`) — no snake/camel morphology — so the
Go stack-trace gold query missed the router fast path (measured 216 ms vs
the 200 ms gate). Tokens that appear call-shaped (`Flush(`), dot-prefixed
(`.Flush`), or receiver-shaped (`(*Archive)`) IN THE QUERY are now
identifier candidates regardless of casing; prose never uses those shapes,
preserving the D21 anti-hijack property (asserted by a new sentence-case
negative test).
Also: `String/Error/Len/Close/Write/Read` join the generic-name stoplist
(ubiquitous Go interface methods; receiver-typed and same-file/import
resolution still apply). Fixture v3 adds goexport/gorunner as APPEND-ONLY
commit 8 (earlier SHAs unchanged; FIXTURE_VERSION 2->3); history-anchored
recent-changes/MCP tests shifted to the 8-commit history (v2 precedent,
assertions equivalent). Gold set 35 -> 39 (additive; nl_hard ratchet
holds). Official gate on the extended set: hybrid 0.974/0.869 vs bm25
0.744 / vector 0.795, sole miss still q28 — GATE: PASS, thresholds
untouched.
