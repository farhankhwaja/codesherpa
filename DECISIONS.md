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
