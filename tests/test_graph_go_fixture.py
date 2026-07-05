"""Phase A: known-edge spot checks for the fixture's Go package, over the
REAL sync pipeline (store built by gitlayer -> chunker -> graph). Mirrors
the §10 Phase 4 standard ("spot-check tests assert >=N known edges exist")
for the goexport/gorunner package added in fixture v3.
"""

from __future__ import annotations

from codesherpa.contracts.types import EdgeKind, SymbolKind
from codesherpa.store.sqlite_store import SQLiteIndexStore

import pytest


@pytest.fixture(scope="module")
def store(synced_miniproject):
    _repo, db = synced_miniproject
    s = SQLiteIndexStore(db)
    yield s
    s.close()


def _defs(store, symbol):
    return store.get_definitions(symbol)


def _one_def(store, symbol, path):
    nodes = [n for n in _defs(store, symbol) if n.file_path == path]
    assert nodes, f"{symbol} not defined in {path}"
    return nodes[0]


def _incoming(store, node, kind):
    return {e.src for e in store.get_edges(node.node_id, kind=kind, incoming=True)}


def _node_ids(store, symbol, path):
    return {n.node_id for n in _defs(store, symbol) if n.file_path == path}


def test_go_definitions_present_with_kinds(store):
    assert _one_def(store, "Archive", "goexport/archive.go").kind is SymbolKind.CLASS
    assert _one_def(store, "Sink", "goexport/sink.go").kind is SymbolKind.CLASS
    assert _one_def(store, "NewArchive", "goexport/archive.go").kind is SymbolKind.FUNCTION
    assert _one_def(store, "Flush", "goexport/archive.go").kind is SymbolKind.METHOD
    assert _one_def(store, "Deliver", "goexport/sink.go").kind is SymbolKind.METHOD
    assert _one_def(store, "MaxBatch", "goexport/archive.go").kind in (
        SymbolKind.VARIABLE,
        SymbolKind.CONST,
    )


# -------- eight known edges (Phase A requirement: >=8 spot-checked) --------


def test_edge_1_drain_calls_newarchive_cross_package_via_alias(store):
    new_archive = _one_def(store, "NewArchive", "goexport/archive.go")
    drain = _one_def(store, "drain", "gorunner/main.go")
    assert drain.node_id in _incoming(store, new_archive, EdgeKind.CALLS)


def test_edge_2_drain_calls_newprintsink(store):
    target = _one_def(store, "NewPrintSink", "goexport/sink.go")
    drain = _one_def(store, "drain", "gorunner/main.go")
    assert drain.node_id in _incoming(store, target, EdgeKind.CALLS)


def test_edge_3_drain_calls_add_receiver_typed(store):
    add = _one_def(store, "Add", "goexport/archive.go")
    drain = _one_def(store, "drain", "gorunner/main.go")
    assert drain.node_id in _incoming(store, add, EdgeKind.CALLS)


def test_edge_4_drain_calls_flush_receiver_typed(store):
    flush = _one_def(store, "Flush", "goexport/archive.go")
    drain = _one_def(store, "drain", "gorunner/main.go")
    assert drain.node_id in _incoming(store, flush, EdgeKind.CALLS)


def test_edge_5_add_calls_flush_via_receiver_binding(store):
    flush = _one_def(store, "Flush", "goexport/archive.go")
    add = _one_def(store, "Add", "goexport/archive.go")
    assert add.node_id in _incoming(store, flush, EdgeKind.CALLS)


def test_edge_6_flush_calls_compactrows_same_package_cross_file(store):
    compact = _one_def(store, "CompactRows", "goexport/compact.go")
    flush = _one_def(store, "Flush", "goexport/archive.go")
    assert flush.node_id in _incoming(store, compact, EdgeKind.CALLS)


def test_edge_7_gorunner_imports_goexport_aliased(store):
    main_module = _one_def(store, "gorunner/main", "gorunner/main.go")
    imported = {
        e.dst
        for e in store.get_edges(main_module.node_id, kind=EdgeKind.IMPORTS, incoming=False)
    }
    assert any("goexport/" in dst for dst in imported), imported


def test_edge_8_module_defines_archive_type(store):
    archive = _one_def(store, "Archive", "goexport/archive.go")
    module = _one_def(store, "goexport/archive", "goexport/archive.go")
    assert module.node_id in _incoming(store, archive, EdgeKind.DEFINES)


def test_edge_9_newarchive_references_archive_type(store):
    archive_ids = _node_ids(store, "Archive", "goexport/archive.go")
    new_archive = _one_def(store, "NewArchive", "goexport/archive.go")
    referenced = {
        e.dst
        for e in store.get_edges(new_archive.node_id, kind=EdgeKind.REFERENCES, incoming=False)
    }
    assert referenced & archive_ids


def test_interface_field_call_follows_name_ladder_not_type_checking(store):
    """Flush calls a.sink.Deliver(...) through a STRUCT FIELD typed as the
    Sink interface. The field's type is not locally evident (that would need
    type checking), so the §7.3 name ladder applies and — Deliver being
    package-unique — an edge lands on the only in-package implementation.
    This is the documented best-effort semantics shared by every language;
    the true negative (an interface-typed value with locally EVIDENT type
    produces NO edge) is pinned by
    tests/test_graph_extract_go.py::test_interface_satisfaction_is_not_resolved.
    """
    deliver_impl = _one_def(store, "Deliver", "goexport/sink.go")
    flush = _one_def(store, "Flush", "goexport/archive.go")
    assert flush.node_id in _incoming(store, deliver_impl, EdgeKind.CALLS)


def test_get_callers_ranked_with_rationale_for_go(store):
    """§7.3 for Go: get_callers returns RANKED results with rationale."""
    from codesherpa.graph.gitio import last_change_dates
    from codesherpa.graph.view import SymbolGraph

    graph = SymbolGraph(store)
    results = graph.get_callers("Flush")
    assert results, "no callers found for Flush"
    paths = [r.chunk.file_path for r in results]
    assert "goexport/archive.go" in paths or "gorunner/main.go" in paths
    for r in results:
        assert r.rationale and "Flush" in r.rationale
    # same-package caller (Add) must rank at or above the cross-package one
    if len(results) >= 2:
        same_pkg = [i for i, p in enumerate(paths) if p.startswith("goexport/")]
        cross_pkg = [i for i, p in enumerate(paths) if p.startswith("gorunner/")]
        if same_pkg and cross_pkg:
            assert min(same_pkg) < min(cross_pkg)
