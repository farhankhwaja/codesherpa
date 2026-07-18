-- sherpa SQLite schema (CLAUDE.md §10 Phase 1).
--
-- One database file at .sherpa/index.db holds everything. Every table is
-- keyed (directly or transitively) by git blob hash: blobs are
-- content-addressed, so branch switches / pulls / rebases only ever pay for
-- genuinely new blobs. Rows are soft-deactivated (blobs.active = 0), never
-- deleted, so switching back to an old branch is free.
--
-- Applied idempotently on every connect (CREATE ... IF NOT EXISTS only).

-- schema_version / last_sync / vec_dim / embedding_model / ... live here.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per unique file blob ever indexed. active=1 iff the blob is
-- reachable from an indexed ref (Phase 1: the current HEAD).
CREATE TABLE IF NOT EXISTS blobs (
    blob_hash  TEXT PRIMARY KEY,
    language   TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_blobs_active ON blobs(active);

-- path <-> blob mapping per ref. mtime is recorded for working-tree files
-- (NULL for blobs coming straight from a commit tree).
CREATE TABLE IF NOT EXISTS files (
    ref       TEXT NOT NULL,
    path      TEXT NOT NULL,
    blob_hash TEXT NOT NULL,
    mtime     REAL,
    PRIMARY KEY (ref, path)
);

CREATE INDEX IF NOT EXISTS idx_files_blob ON files(blob_hash);

-- Chunk identity is (blob_hash, byte_start, byte_end); chunk_id is the
-- colon-joined form. code is the exact blob byte slice (UTF-8, errors
-- replaced); breadcrumb is stored separately and never part of code.
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id   TEXT PRIMARY KEY,
    blob_hash  TEXT NOT NULL,
    byte_start INTEGER NOT NULL,
    byte_end   INTEGER NOT NULL,
    file_path  TEXT NOT NULL,
    language   TEXT NOT NULL,
    code       TEXT NOT NULL,
    breadcrumb TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_blob ON chunks(blob_hash, byte_start);

-- Full-text index over chunk text. One row per chunks row; queries join back
-- through chunks -> blobs to restrict to active blobs. '_' is a token
-- character so snake_case identifiers survive tokenization.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    breadcrumb,
    code,
    tokenize = "unicode61 tokenchars '_'"
);

-- Symbol DEFINITIONS (functions, classes, methods, consts). Reference sites
-- are represented as edges, not rows here.
CREATE TABLE IF NOT EXISTS symbols (
    node_id    TEXT PRIMARY KEY,
    symbol     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    blob_hash  TEXT NOT NULL,
    byte_start INTEGER NOT NULL,
    byte_end   INTEGER NOT NULL,
    file_path  TEXT NOT NULL,
    signature  TEXT
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(symbol);
CREATE INDEX IF NOT EXISTS idx_symbols_blob ON symbols(blob_hash);

-- Directed graph edges between symbol node_ids.
CREATE TABLE IF NOT EXISTS edges (
    src  TEXT NOT NULL,
    dst  TEXT NOT NULL,
    kind TEXT NOT NULL,
    PRIMARY KEY (src, dst, kind)
);

CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);

-- Per-blob symbol-extraction cache (D48). Symbols and edges themselves are a
-- GLOBAL function of the active file mapping and are still recomputed and
-- REPLACED every sync (D19) — but tree-sitter pass 1 (definitions, call/ref
-- sites, imports) is path-independent, so its output is cached per blob and
-- replayed instead of reparsing the whole active set. Only the cross-file
-- resolution pass reruns, which is what preserves incremental == rebuild.
--
-- Keyed by (blob_hash, language): one blob may be reachable at paths with
-- different extensions, and the language selects the tree-sitter grammar and
-- query file. facts is the JSON payload from graph.extract.encode_facts.
--
-- INVALIDATION: meta['graph_facts_tag'] holds graph.extract.extraction_tag()
-- (payload version + queries digest + grammar versions). When it changes, the
-- whole table is dropped on the next sync — same contract as embed_tag for
-- the embedding cache. Rows are never otherwise pruned: blobs are never
-- deleted, so a blob that becomes active again reuses its cached facts free.
CREATE TABLE IF NOT EXISTS graph_facts (
    blob_hash TEXT NOT NULL,
    language  TEXT NOT NULL,
    facts     TEXT NOT NULL,
    PRIMARY KEY (blob_hash, language)
);

-- Permanent embedding cache: an embedding is computed at most once per unique
-- chunk_id, ever. vector is little-endian float32, dim floats.
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id TEXT PRIMARY KEY,
    model    TEXT NOT NULL,
    dim      INTEGER NOT NULL,
    vector   BLOB NOT NULL
);

-- NOTE: the sqlite-vec virtual table (vec_chunks) is created lazily by the
-- store on the first put_embedding, because vec0 tables need the embedding
-- dimension fixed at creation time and the model (hence dim) is chosen in
-- Phase 3. See SQLiteIndexStore._ensure_vec_table.

-- Local-only usage analytics for `sherpa gain`. OBSERVATIONAL, not index
-- state: excluded from golden projections (a rebuilt index legitimately has
-- no memory of who queried it) and from sync entirely. PRIVACY: never store
-- query text (sha256 hash only), never code, never file paths — only a
-- distinct-path count and their summed full-file token estimate.
CREATE TABLE IF NOT EXISTS usage (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                   TEXT NOT NULL,     -- UTC ISO-8601
    tool                 TEXT NOT NULL,     -- MCP tool name
    query_hash           TEXT NOT NULL,     -- sha256 hex of the query arg
    path_taken           TEXT,              -- router | dense | graph | NULL
    tokens_returned      INTEGER NOT NULL,
    budget_tokens        INTEGER,
    latency_ms           REAL NOT NULL,
    results_count        INTEGER NOT NULL,
    files_count          INTEGER NOT NULL DEFAULT 0,
    files_spanned_tokens INTEGER NOT NULL DEFAULT 0,  -- size_bytes/4 estimate
    expanded             INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
