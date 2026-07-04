"""Write-side graph indexing, called from ``gitlayer.sync`` (CLAUDE.md §7.3).

Symbols and edges are a *global* function of the active file mapping: adding
one file can change how another file's calls resolve (same-package and
uniqueness rules), and module names/packages derive from paths. Appending
rows per new blob therefore can never keep incremental == rebuild. Instead,
the graph tables are recomputed from the full active set and REPLACED on
every sync — a pure function of (path -> blob -> bytes), so the Golden Test
holds by construction (DECISIONS.md D19).

Cost: one tree-sitter reparse of the active set per sync (~150k LOC/s per
EVAL_LOG Phase 2 numbers), while chunking and the embedding cache — the
expensive per-blob work — stay fully incremental. TODO(upgrade): persist
per-blob extraction facts (defs/sites/imports are path-independent) so only
the cross-file resolution pass reruns per sync.

Ownership note: this module is the write side of the indexing pipeline and
is invoked only by ``gitlayer.sync``, which is already bound to the concrete
:class:`SQLiteIndexStore` (it constructs it). The two ``DELETE`` statements
here are the only concrete-store access in ``repograph/graph``; every query
path (SymbolGraph, MCP, retrieval) depends on the frozen ABC only.
"""

from __future__ import annotations

from repograph.graph.extract import SourceFile, extract_project
from repograph.graph.languages import language_for_path
from repograph.store.sqlite_store import SQLiteIndexStore

__all__ = ["sync_graph"]


def sync_graph(
    store: SQLiteIndexStore,
    file_map: dict[str, str],
    blob_data: dict[str, bytes],
) -> tuple[int, int]:
    """Recompute symbols/edges for the active mapping; returns (n_sym, n_edge).

    ``file_map`` is the active path -> blob mapping being synced;
    ``blob_data`` must contain the bytes of every graph-supported blob in it.
    Deterministic: identical inputs produce identical tables.
    """
    files = []
    for path in sorted(file_map):
        language = language_for_path(path)
        if language is None:
            continue
        blob_hash = file_map[path]
        if blob_hash not in blob_data:
            continue
        files.append(
            SourceFile(
                path=path, blob_hash=blob_hash, language=language, data=blob_data[blob_hash]
            )
        )

    symbols, edges = extract_project(files)

    with store.conn:  # one transaction: replace-all, like map_files does per ref
        store.conn.execute("DELETE FROM symbols")
        store.conn.execute("DELETE FROM edges")
    store.add_symbols(symbols)
    store.add_edges(edges)
    return len(symbols), len(edges)
