"""Phase A: Go symbol/edge extraction (feature/go-support).

Covers: definitions (functions, receiver-keyed methods, types, package-level
consts/vars), aliased imports, best-effort calls through the existing
resolution ladder, receiver-typed disambiguation for `x.Foo()` with locally
evident types, and the documented NON-goal: interface-satisfaction
resolution is never attempted.
"""

from __future__ import annotations

from codesherpa.contracts.types import EdgeKind, SymbolKind
from codesherpa.graph.extract import SourceFile, extract_project

CACHE_GO = b"""package storage

type Cache struct{ n int }

func (c *Cache) Flush() int {
\tc.n = 0
\treturn 0
}

type Journal struct{ n int }

func (j *Journal) Flush() int {
\tj.n = 1
\treturn 1
}
"""

USER_GO = b"""package storage

func UseCache() int {
\tc := Cache{}
\treturn c.Flush()
}

func UseJournal() int {
\tj := &Journal{}
\treturn j.Flush()
}

func UseParam(j *Journal) int {
\treturn j.Flush()
}
"""

IFACE_GO = b"""package storage

type Flusher interface {
\tFlush() int
}

func UseIface(f Flusher) int {
\treturn f.Flush()
}
"""


def _project(*files):
    return extract_project([SourceFile(p, f"{i:040x}", "go", d) for i, (p, d) in enumerate(files)])


def _edge_pairs(symbols, edges, kind):
    by_id = {s.node_id: s for s in symbols}
    return {
        (by_id[e.src].symbol, by_id[e.dst].symbol, by_id[e.dst].file_path, by_id[e.dst].byte_start)
        for e in edges
        if e.kind is kind and e.src in by_id and e.dst in by_id
    }


def test_definition_kinds():
    symbols, _ = _project(("storage/cache.go", CACHE_GO))
    kinds = {s.symbol: s.kind for s in symbols if s.kind is not SymbolKind.MODULE}
    assert kinds["Cache"] is SymbolKind.CLASS
    assert kinds["Journal"] is SymbolKind.CLASS
    assert kinds["Flush"] is SymbolKind.METHOD


def test_receiver_typed_call_disambiguation():
    """Two types share `Flush`; each call site must resolve to the method of
    the LOCALLY EVIDENT receiver type (composite literal, &literal, param)."""
    symbols, edges = _project(
        ("storage/cache.go", CACHE_GO), ("storage/use.go", USER_GO)
    )
    flush_by_receiver = {}
    for s in symbols:
        if s.symbol == "Flush":
            # Cache.Flush appears before Journal.Flush in the file
            flush_by_receiver["Cache" if len(flush_by_receiver) == 0 else "Journal"] = s
    calls = _edge_pairs(symbols, edges, EdgeKind.CALLS)
    cache_flush = next(s for s in symbols if s.symbol == "Flush" and s.byte_start < 100)
    journal_flush = next(s for s in symbols if s.symbol == "Flush" and s.byte_start > 100)
    assert ("UseCache", "Flush", "storage/cache.go", cache_flush.byte_start) in calls
    assert ("UseJournal", "Flush", "storage/cache.go", journal_flush.byte_start) in calls
    assert ("UseParam", "Flush", "storage/cache.go", journal_flush.byte_start) in calls
    # and never cross-wired
    assert ("UseCache", "Flush", "storage/cache.go", journal_flush.byte_start) not in calls
    assert ("UseJournal", "Flush", "storage/cache.go", cache_flush.byte_start) not in calls


def test_interface_satisfaction_is_not_resolved():
    """`f.Flush()` through an interface value must produce NO call edge to any
    concrete implementation — that would require type checking (DECISIONS)."""
    symbols, edges = _project(
        ("storage/cache.go", CACHE_GO), ("storage/iface.go", IFACE_GO)
    )
    calls = _edge_pairs(symbols, edges, EdgeKind.CALLS)
    assert not any(src == "UseIface" for src, *_ in calls), calls


def test_aliased_import_produces_module_edge_and_cross_package_call():
    lib = b"""package lib

func Helper() int { return 1 }
"""
    app = b"""package app

import l9 "example.com/proj/lib"

func Main() int { return l9.Helper() }
"""
    symbols, edges = _project(("lib/lib.go", lib), ("app/main.go", app))
    by_id = {s.node_id: s for s in symbols}
    imports = {
        (by_id[e.src].file_path, by_id[e.dst].file_path)
        for e in edges
        if e.kind is EdgeKind.IMPORTS
    }
    assert ("app/main.go", "lib/lib.go") in imports
    calls = _edge_pairs(symbols, edges, EdgeKind.CALLS)
    assert any(src == "Main" and dst == "Helper" for src, dst, *_ in calls)


def test_package_level_consts_and_vars_only():
    src = b"""package cfg

const RetryLimit = 9

var registry = 1

func f() {
\tlocal := 2
\t_ = local
}
"""
    symbols, _ = _project(("cfg/cfg.go", src))
    names = {s.symbol for s in symbols}
    assert "RetryLimit" in names and "registry" in names
    assert "local" not in names  # block-local vars are noise, not symbols


def test_stdlib_imports_resolve_to_nothing():
    src = b"""package x

import "fmt"

func F() { fmt.Println("hi") }
"""
    symbols, edges = _project(("x/x.go", src))
    assert not [e for e in edges if e.kind is EdgeKind.IMPORTS]
    # fmt.Println must not resolve to anything in-project either
    calls = _edge_pairs(symbols, edges, EdgeKind.CALLS)
    assert not any(dst == "Println" for _, dst, *_ in calls)
