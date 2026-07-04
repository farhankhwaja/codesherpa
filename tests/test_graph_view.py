"""Phase 4: ranked graph queries (get_callers / get_references / definition).

CLAUDE.md §10 Phase 4: "get_callers returns ranked results with rationale
fields" (§7.3 ranking: same-package proximity, reference count, recency).
Runs against the REAL SQLite store populated by the real sync pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repograph.contracts.types import (
    Chunk,
    Edge,
    EdgeKind,
    RetrievalSource,
    SymbolKind,
    SymbolNode,
)
from repograph.graph.gitio import last_change_dates
from repograph.graph.view import SymbolGraph
from repograph.store.sqlite_store import SQLiteIndexStore


@pytest.fixture(scope="module")
def graph(synced_miniproject: tuple[Path, Path]):
    repo, db = synced_miniproject
    store = SQLiteIndexStore(db)
    yield SymbolGraph(store, recency=last_change_dates(repo))
    store.close()


def _paths(results):
    return [r.chunk.file_path for r in results]


def test_get_callers_finds_known_callers(graph: SymbolGraph):
    results = graph.get_callers("validate_title")
    assert results, "validate_title has a known caller (create_task)"
    assert "pyserver/routes/tasks.py" in _paths(results)


def test_get_callers_is_ranked_with_rationale(graph: SymbolGraph):
    results = graph.get_callers("retry_request")
    assert len(results) >= 2
    # fetch_json calls retry_request from the same file -> outranks the
    # cross-package caller send_task_notification
    assert results[0].chunk.file_path == "pyserver/http_client.py"
    assert "pyserver/services/notifications.py" in _paths(results)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    for result in results:
        assert result.rationale, "every caller carries a rationale"
        assert "calls retry_request" in result.rationale
        assert "inbound refs" in result.rationale
        assert "last changed" in result.rationale  # recency wired from git
        assert result.expand_id == result.chunk.chunk_id
        assert result.token_count > 0
        assert result.source is RetrievalSource.SYMBOL


def test_get_callers_respects_limit(graph: SymbolGraph):
    everything = graph.get_callers("execute", limit=10)
    assert len(everything) >= 3  # create_task, complete_task, create_user, ...
    assert len(graph.get_callers("execute", limit=2)) == 2


def test_get_callers_unknown_symbol_is_empty(graph: SymbolGraph):
    assert graph.get_callers("no_such_symbol_anywhere") == []


def test_get_references_spans_kinds_and_languages(graph: SymbolGraph):
    results = graph.get_references("Task")
    paths = _paths(results)
    assert "webclient/src/api.ts" in paths  # TS type reference
    assert "pyserver/services/notifications.py" in paths  # Python import/reference
    rationales = " | ".join(r.rationale or "" for r in results)
    assert "references Task" in rationales
    assert "imports Task" in rationales


def test_get_definition_prefers_code_over_module(graph: SymbolGraph):
    results = graph.get_definition("Database")
    assert results
    assert results[0].chunk.file_path == "pyserver/db.py"
    assert "class definition" in (results[0].rationale or "")
    assert "class Database" in results[0].chunk.code


def test_neighbors_expansion(graph: SymbolGraph):
    results = graph.neighbors("create_task")
    assert results
    paths = _paths(results)
    assert "pyserver/validators.py" in paths  # called-by target
    for result in results:
        assert result.source is RetrievalSource.EXPANSION


def _tiny_store(db_path: Path) -> SQLiteIndexStore:
    """Synthetic three-node graph on the REAL store implementation."""
    store = SQLiteIndexStore(db_path)
    blob = {"t": "a" * 40, "old": "b" * 40, "new": "c" * 40}
    target = SymbolNode("t_func", SymbolKind.FUNCTION, blob["t"], 0, 10, "pkg/t.py")
    old_caller = SymbolNode("old_caller", SymbolKind.FUNCTION, blob["old"], 0, 10, "pkg/old.py")
    new_caller = SymbolNode("new_caller", SymbolKind.FUNCTION, blob["new"], 0, 10, "pkg/new.py")
    for node in (target, old_caller, new_caller):
        store.add_blob(node.blob_hash, "python", 10)
        store.add_chunks(
            [
                Chunk(
                    blob_hash=node.blob_hash,
                    byte_start=0,
                    byte_end=10,
                    file_path=node.file_path,
                    language="python",
                    code="def x(): 1",
                    breadcrumb=f"# {node.file_path}",
                )
            ]
        )
    store.add_symbols([target, old_caller, new_caller])
    store.add_edges(
        [
            Edge(old_caller.node_id, target.node_id, EdgeKind.CALLS),
            Edge(new_caller.node_id, target.node_id, EdgeKind.CALLS),
        ]
    )
    return store


def test_recency_breaks_ties(tmp_path: Path):
    """Two callers identical except recency: the newer file ranks first."""
    store = _tiny_store(tmp_path / "tiny.db")
    try:
        graph = SymbolGraph(
            store, recency={"pkg/old.py": "2023-01-01", "pkg/new.py": "2024-06-01"}
        )
        results = graph.get_callers("t_func")
        assert _paths(results) == ["pkg/new.py", "pkg/old.py"]
        assert "last changed 2024-06-01" in (results[0].rationale or "")
    finally:
        store.close()


def test_deactivated_blobs_disappear_from_queries(tmp_path: Path):
    store = _tiny_store(tmp_path / "tiny.db")
    try:
        view = SymbolGraph(store)
        assert view.get_definition("t_func")
        target_blob = view.get_definition("t_func")[0].chunk.blob_hash
        store.set_blobs_active([target_blob], False)
        assert view.get_definition("t_func") == []
    finally:
        store.close()
