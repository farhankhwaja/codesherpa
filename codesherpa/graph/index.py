"""Write-side graph indexing, called from ``gitlayer.sync`` (CLAUDE.md §7.3).

Symbols and edges are a *global* function of the active file mapping: adding
one file can change how another file's calls resolve (same-package and
uniqueness rules), and module names/packages derive from paths. Appending
rows per new blob therefore can never keep incremental == rebuild. Instead,
the graph tables are recomputed from the full active set and REPLACED on
every sync — a pure function of (path -> blob -> bytes), so the Golden Test
holds by construction (DECISIONS.md D19).

What IS cacheable is tree-sitter pass 1. Definitions, call/reference sites and
imports are a pure function of (blob bytes, language) — path-independent — so
they are persisted per blob in ``graph_facts`` and replayed on later syncs
(D47). Only genuinely new blobs are read and parsed; the cross-file resolution
pass still runs over the full active set, which is what preserves correctness.
The cache is invalidated wholesale when ``extraction_tag()`` changes (payload
version, query-file edit, or grammar upgrade), mirroring ``embed_tag``.

Ownership note: this module is the write side of the indexing pipeline and
is invoked only by ``gitlayer.sync``, which is already bound to the concrete
:class:`SQLiteIndexStore` (it constructs it). The concrete-store access here
is the only such access in ``codesherpa/graph``; every query path (SymbolGraph,
MCP, retrieval) depends on the frozen ABC only.
"""

from __future__ import annotations

from typing import Callable

from codesherpa.graph.extract import (
    CachedFile,
    SourceFile,
    encode_facts,
    extract_project_cached,
    extraction_tag,
)
from codesherpa.graph.languages import language_for_path
from codesherpa.store.sqlite_store import SQLiteIndexStore

__all__ = ["sync_graph"]

_TAG_KEY = "graph_facts_tag"


def _ensure_facts_compat(store: SQLiteIndexStore) -> bool:
    """Drop cached facts when the extractor identity changed; True if wiped.

    A tag change means the persisted payloads were produced by a different
    extractor (payload version, query files, or grammar) — replaying them would
    silently yield symbols/edges that a rebuild would not produce.
    """
    tag = extraction_tag()
    if store.get_meta(_TAG_KEY) == tag:
        return False
    wiped = store.get_meta(_TAG_KEY) is not None
    with store.conn:
        store.conn.execute("DELETE FROM graph_facts")
    store.set_meta(_TAG_KEY, tag)
    return wiped


def sync_graph(
    store: SQLiteIndexStore,
    file_map: dict[str, str],
    read_blob: Callable[[str], bytes],
) -> tuple[int, int]:
    """Recompute symbols/edges for the active mapping; returns (n_sym, n_edge).

    ``file_map`` is the active path -> blob mapping being synced. ``read_blob``
    fetches a blob's bytes and is called ONLY for blobs whose extraction facts
    are not cached yet — that is the whole point: an unchanged repo re-syncs
    without reading or parsing a single file.

    Deterministic: identical inputs produce identical tables, whether the facts
    came from the cache or from a fresh parse.
    """
    _ensure_facts_compat(store)

    entries: list[CachedFile] = []
    fresh: list[tuple[str, str, str]] = []  # (blob_hash, language, payload)
    seen: dict[tuple[str, str], str] = {}  # (blob, language) -> payload

    for path in sorted(file_map):
        language = language_for_path(path)
        if language is None:
            continue
        blob_hash = file_map[path]
        key = (blob_hash, language)
        payload = seen.get(key)
        if payload is None:
            row = store.conn.execute(
                "SELECT facts FROM graph_facts WHERE blob_hash = ? AND language = ?",
                (blob_hash, language),
            ).fetchone()
            if row is not None:
                payload = row[0]
            else:
                payload = encode_facts(
                    SourceFile(
                        path=path,
                        blob_hash=blob_hash,
                        language=language,
                        data=read_blob(blob_hash),
                    )
                )
                fresh.append((blob_hash, language, payload))
            seen[key] = payload
        entries.append(
            CachedFile(
                path=path, blob_hash=blob_hash, language=language, payload=payload
            )
        )

    symbols, edges = extract_project_cached(entries)

    with store.conn:  # one transaction: replace-all, like map_files does per ref
        if fresh:
            store.conn.executemany(
                "INSERT OR REPLACE INTO graph_facts (blob_hash, language, facts) "
                "VALUES (?, ?, ?)",
                fresh,
            )
        store.conn.execute("DELETE FROM symbols")
        store.conn.execute("DELETE FROM edges")
    store.add_symbols(symbols)
    store.add_edges(edges)
    return len(symbols), len(edges)
