"""Phase 4: symbols/edges flow through the REAL store during real sync."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codesherpa.contracts.types import EdgeKind, SymbolKind
from codesherpa.gitlayer.sync import sync
from codesherpa.store.sqlite_store import SQLiteIndexStore


@pytest.fixture()
def synced(miniproject: Path, tmp_path: Path):
    repo = tmp_path / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".sherpa", ignore_errors=True)
    db = tmp_path / "index.db"
    stats = sync(repo, db)
    store = SQLiteIndexStore(db)
    yield repo, db, store, stats
    store.close()


def _table_dump(store: SQLiteIndexStore) -> tuple[list, list]:
    symbols = store.conn.execute("SELECT * FROM symbols ORDER BY node_id").fetchall()
    edges = store.conn.execute("SELECT * FROM edges ORDER BY src, dst, kind").fetchall()
    return [tuple(r) for r in symbols], [tuple(r) for r in edges]


def test_sync_populates_symbols_and_edges(synced):
    _repo, _db, store, stats = synced
    assert stats.symbols_indexed > 100
    assert stats.edges_indexed > 200
    defs = store.get_definitions("validate_title")
    assert [d.file_path for d in defs] == ["pyserver/validators.py"]
    callers = store.get_edges(defs[0].node_id, kind=EdgeKind.CALLS, incoming=True)
    assert callers, "create_task -> validate_title must survive the real store"
    assert any("create_task" in e.src for e in callers)


def test_resync_is_idempotent_for_graph_tables(synced):
    repo, db, store, _stats = synced
    before = _table_dump(store)
    sync(repo, db)
    assert _table_dump(store) == before


def test_graph_follows_head_changes(synced):
    """Deleting a file removes its symbols and the edges into them."""
    repo, db, store, _stats = synced
    target = store.get_definitions("validate_title")[0]
    assert store.get_edges(target.node_id, kind=EdgeKind.CALLS, incoming=True)

    subprocess.run(["git", "-C", str(repo), "rm", "-q", "pyserver/validators.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@e.co",
         "commit", "-q", "-m", "drop validators"],
        check=True,
    )
    sync(repo, db)
    assert store.get_definitions("validate_title") == []
    # no dangling edges: every endpoint resolves to a stored symbol
    dangling = store.conn.execute(
        """
        SELECT COUNT(*) FROM edges e
        WHERE NOT EXISTS (SELECT 1 FROM symbols s WHERE s.node_id = e.src)
           OR NOT EXISTS (SELECT 1 FROM symbols s WHERE s.node_id = e.dst)
        """
    ).fetchone()[0]
    assert dangling == 0


def test_new_file_rebinds_existing_callers(synced):
    """The scenario append-only writes can't handle: a NEW file changes how
    an OLD (unchanged) file's call resolves."""
    repo, db, store, _stats = synced
    # unique_helper doesn't exist yet; caller file references it unresolved
    caller = repo / "pyserver" / "wants_helper.py"
    caller.write_text("def use_it():\n    return unique_helper_fn(1)\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@e.co",
         "commit", "-q", "-m", "caller first"],
        check=True,
    )
    sync(repo, db)
    assert store.get_definitions("unique_helper_fn") == []

    helper = repo / "pyserver" / "the_helper.py"
    helper.write_text("def unique_helper_fn(x):\n    return x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@e.co",
         "commit", "-q", "-m", "helper second"],
        check=True,
    )
    sync(repo, db)  # caller blob unchanged — edge must appear anyway
    target = store.get_definitions("unique_helper_fn")[0]
    callers = store.get_edges(target.node_id, kind=EdgeKind.CALLS, incoming=True)
    assert any("use_it" in e.src for e in callers)


def test_module_nodes_are_stored(synced):
    _repo, _db, store, _stats = synced
    modules = store.get_definitions("pyserver.validators")
    assert len(modules) == 1 and modules[0].kind is SymbolKind.MODULE
