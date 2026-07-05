"""Protocol Buffers support (Phase B follow-on, human instruction: the
large-repo target is a gRPC monorepo with .proto files).

proto files get cAST chunks (message/service/enum scopes) and symbol-graph
definitions (messages/enums/services as types, rpcs as methods), proto->proto
imports and type references. proto is its own family: no cross-language
edges to generated bindings (that would be guesswork, same principle as the
Go interface non-goal in D43).
"""

from __future__ import annotations

from codesherpa.chunker import chunk_blob, detect_language
from codesherpa.chunker.cast import chunk_ast
from codesherpa.contracts.types import EdgeKind, SymbolKind
from codesherpa.graph.extract import SourceFile, extract_project

BLOB = "d" * 40

QUOTE_PROTO = b"""syntax = "proto3";

package demo.v1;

import "demo/errors.proto";

enum Status {
  STATUS_UNSPECIFIED = 0;
  STATUS_ACTIVE = 1;
}

message GetQuoteRequest {
  string quote_id = 1;
}

message Quote {
  string id = 1;
  Status status = 2;
}

service QuoteApi {
  rpc GetQuote(GetQuoteRequest) returns (Quote);
}
"""

ERRORS_PROTO = b"""syntax = "proto3";

package demo.v1;

message ApiError {
  string code = 1;
}
"""


def test_detected_and_chunked():
    assert detect_language("demo/quote.proto") == "proto"
    chunks = chunk_blob(BLOB, QUOTE_PROTO, "demo/quote.proto", "proto")
    assert chunks and all(c.language == "proto" for c in chunks)
    joined = b"".join(QUOTE_PROTO[c.byte_start : c.byte_end] for c in chunks)
    assert joined == QUOTE_PROTO  # byte-exact


def test_service_scope_breadcrumb_when_split():
    body = b"".join(
        b"  rpc Get%d(GetQuoteRequest) returns (Quote);\n" % i for i in range(60)
    )
    src = b'syntax = "proto3";\n\nservice BigApi {\n' + body + b"}\n"
    chunks = chunk_ast(BLOB, src, "demo/big.proto", "proto", max_chunk=400)
    assert chunks is not None and len(chunks) > 1
    interior = [c for c in chunks if "rpc Get" in c.code and c.byte_start > 0]
    assert any(":: BigApi ::" in c.breadcrumb for c in interior)
    assert b"".join(src[c.byte_start : c.byte_end] for c in chunks) == src


def test_broken_proto_falls_back():
    broken = b"message {{{ not proto ]]\n" * 4
    chunks = chunk_blob(BLOB, broken, "x/broken.proto", "proto")
    assert chunks and chunks[0].breadcrumb.startswith("// x/broken.proto :: L1-")


def test_symbols_imports_and_references():
    symbols, edges = extract_project(
        [
            SourceFile("demo/quote.proto", "a" * 40, "proto", QUOTE_PROTO),
            SourceFile("demo/errors.proto", "b" * 40, "proto", ERRORS_PROTO),
        ]
    )
    kinds = {s.symbol: s.kind for s in symbols if s.kind is not SymbolKind.MODULE}
    assert kinds["Quote"] is SymbolKind.CLASS
    assert kinds["GetQuoteRequest"] is SymbolKind.CLASS
    assert kinds["Status"] is SymbolKind.CLASS
    assert kinds["QuoteApi"] is SymbolKind.CLASS
    assert kinds["GetQuote"] is SymbolKind.METHOD
    assert kinds["ApiError"] is SymbolKind.CLASS

    by_id = {s.node_id: s for s in symbols}
    imports = {
        (by_id[e.src].file_path, by_id[e.dst].file_path)
        for e in edges
        if e.kind is EdgeKind.IMPORTS
    }
    assert ("demo/quote.proto", "demo/errors.proto") in imports

    refs = {
        (by_id[e.src].symbol, by_id[e.dst].symbol)
        for e in edges
        if e.kind is EdgeKind.REFERENCES and e.src in by_id and e.dst in by_id
    }
    # the rpc references its request/response messages; Quote references Status
    assert ("GetQuote", "GetQuoteRequest") in refs or ("QuoteApi", "GetQuoteRequest") in refs
    assert ("Quote", "Status") in refs


def test_proto_is_its_own_family_no_cross_language_edges():
    go_src = b"""package quotes

type Quote struct{ ID string }

func Use(q Quote) string { return q.ID }
"""
    symbols, edges = extract_project(
        [
            SourceFile("demo/quote.proto", "a" * 40, "proto", QUOTE_PROTO),
            SourceFile("quotes/quote.go", "c" * 40, "go", go_src),
        ]
    )
    by_id = {s.node_id: s for s in symbols}
    cross = [
        e
        for e in edges
        if e.src in by_id
        and e.dst in by_id
        and by_id[e.src].file_path.endswith(".go") != by_id[e.dst].file_path.endswith(".go")
    ]
    assert cross == [], cross  # Go `Quote` never links to the proto `Quote`
