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
