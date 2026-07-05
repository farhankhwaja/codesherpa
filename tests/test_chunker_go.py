"""Phase A: Go cAST chunking (feature/go-support).

Same standard as the other languages: split-then-merge, byte-exact
reassembly, deterministic chunk sets, receiver-scoped method breadcrumbs
(`path :: (ReceiverType) :: func signature`), and line-window fallback on
unparseable Go — never a crash.
"""

from __future__ import annotations

import logging

from hypothesis import given, settings
from hypothesis import strategies as st

from codesherpa.chunker import chunk_blob, detect_language
from codesherpa.chunker.cast import chunk_ast

BLOB = "c0ffee" + "0" * 34

GO_SOURCE = b"""package goservice

import "fmt"

const MaxRetries = 3

// Store keeps named payloads in memory.
type Store struct {
\tname    string
\tentries map[string]string
}

// Notifier is anything that can receive a message.
type Notifier interface {
\tNotify(msg string) error
}

func NewStore(name string) *Store {
\treturn &Store{name: name, entries: map[string]string{}}
}

func (s *Store) Save(key, value string) error {
\tif key == "" {
\t\treturn fmt.Errorf("empty key")
\t}
\ts.entries[key] = value
\treturn nil
}

func (s *Store) Lookup(key string) (string, bool) {
\tvalue, ok := s.entries[key]
\treturn value, ok
}

func Describe(s *Store) string {
\treturn fmt.Sprintf("store %s: %d entries", s.name, len(s.entries))
}
"""


def test_go_detected_and_chunked():
    assert detect_language("pkg/store.go") == "go"
    chunks = chunk_blob(BLOB, GO_SOURCE, "pkg/store.go", "go")
    assert chunks, "Go source produced no chunks"
    assert all(c.language == "go" for c in chunks)


def test_reassembly_is_byte_exact():
    chunks = chunk_ast(BLOB, GO_SOURCE, "pkg/store.go", "go", max_chunk=80)
    assert chunks is not None and len(chunks) > 3
    joined = b"".join(
        GO_SOURCE[c.byte_start : c.byte_end] for c in chunks
    )
    assert joined == GO_SOURCE
    for a, b in zip(chunks, chunks[1:]):
        assert b.byte_start == a.byte_end  # contiguous, no gaps or overlaps


def test_method_breadcrumb_carries_receiver_type():
    # small max_chunk forces one chunk per declaration
    chunks = chunk_ast(BLOB, GO_SOURCE, "pkg/store.go", "go", max_chunk=120)
    crumbs = [c.breadcrumb for c in chunks]
    save = next(c for c in crumbs if "func (s *Store) Save" in c)
    # pointer stripped, receiver surfaced, package-qualified (D45)
    assert ":: (pkg.Store) ::" in save, save
    assert save.startswith("// pkg/store.go :: (pkg.Store) :: func (s *Store) Save")
    lookup = next(c for c in crumbs if "Lookup" in c)
    assert ":: (pkg.Store) ::" in lookup
    # plain functions do NOT get a receiver scope
    describe = next(c for c in crumbs if "func Describe" in c)
    assert "Store)" not in describe.split("::")[1]


def test_oversized_struct_recurses_under_type_name():
    fields = "".join(f"\tfield_{i:03d} string // padding padding\n" for i in range(120))
    source = ("package big\n\ntype Wide struct {\n" + fields + "}\n").encode()
    chunks = chunk_ast(BLOB, source, "pkg/big.go", "go", max_chunk=400)
    assert chunks is not None and len(chunks) > 1
    # interior chunks of the recursed struct carry the type name as scope
    interior = [c for c in chunks if c.byte_start > 0 and "field_" in c.code]
    assert interior
    assert any(":: Wide ::" in c.breadcrumb for c in interior)
    assert b"".join(source[c.byte_start : c.byte_end] for c in chunks) == source


def test_const_and_var_blocks_chunk_cleanly():
    lines = "".join(f'\tName{i:03d} = "v{i}"\n' for i in range(80))
    source = ("package cfg\n\nconst (\n" + lines + ")\n\nvar Registry = map[string]string{}\n").encode()
    chunks = chunk_ast(BLOB, source, "pkg/cfg.go", "go", max_chunk=300)
    assert chunks is not None
    assert b"".join(source[c.byte_start : c.byte_end] for c in chunks) == source


def test_same_blob_same_chunks_property():
    a = chunk_ast(BLOB, GO_SOURCE, "pkg/store.go", "go", max_chunk=100)
    b = chunk_ast(BLOB, GO_SOURCE, "pkg/store.go", "go", max_chunk=100)
    assert [(c.byte_start, c.byte_end, c.breadcrumb) for c in a] == [
        (c.byte_start, c.byte_end, c.breadcrumb) for c in b
    ]


@settings(max_examples=25, deadline=None)
@given(st.binary(min_size=1, max_size=4000))
def test_arbitrary_bytes_never_crash_and_cover(data: bytes):
    """chunk_blob on arbitrary bytes as .go: valid parse -> byte-exact cAST;
    anything else -> line-window fallback. Either way: full coverage, no
    exception."""
    chunks = chunk_blob(BLOB, data, "x/fuzz.go", "go")
    assert chunks
    assert chunks[0].byte_start == 0
    assert chunks[-1].byte_end == len(data)


def test_broken_go_falls_back_to_line_windows(caplog):
    broken = b"package x\n\nfunc ( {{{ not go at all\n" * 3
    with caplog.at_level(logging.WARNING):
        assert chunk_ast(BLOB, broken, "x/broken.go", "go") is None  # cAST declines
        chunks = chunk_blob(BLOB, broken, "x/broken.go", "go")  # dispatcher falls back
    assert chunks and chunks[0].breadcrumb.startswith("// x/broken.go :: L1-")
    assert any("falling back to line windows" in r.message for r in caplog.records)
