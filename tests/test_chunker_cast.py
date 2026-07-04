"""Phase 2 tests: cAST split-then-merge chunker (CLAUDE.md §7.2/§10)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from codesherpa.chunker import chunk_blob, detect_language
from codesherpa.chunker.cast import MAX_CHUNK_NONWS, chunk_ast, _nonws
from codesherpa.contracts.types import Chunk

BLOB = "c" * 40


def _reassemble(chunks: list[Chunk], data: bytes) -> None:
    """Assert chunks partition the blob byte-exactly, in order."""
    assert chunks, "no chunks produced"
    assert chunks[0].byte_start == 0
    assert chunks[-1].byte_end == len(data)
    for prev, cur in zip(chunks, chunks[1:]):
        assert prev.byte_end == cur.byte_start, "gap or overlap between chunks"
    for c in chunks:
        assert c.code == data[c.byte_start : c.byte_end].decode("utf-8", errors="replace")


def _method(cls_i: int, i: int, body_lines: int = 30) -> str:
    lines = "\n".join(f"        total += {j}  # step {j}" for j in range(body_lines))
    return (
        f"    def method_{i}(self, value: int) -> int:\n"
        f'        """Method {i} of class {cls_i}."""\n'
        f"        total = value\n{lines}\n"
        f"        return total\n"
    )


def _big_class(i: int = 0, n_methods: int = 12) -> str:
    return (
        f"class BigService{i}:\n"
        f'    """A service class far larger than one chunk."""\n\n'
        + "\n".join(_method(i, j) for j in range(n_methods))
    )


# ------------------------------------------------------------ split behavior


def test_oversized_class_recursed_into_methods() -> None:
    src = _big_class().encode()
    assert _nonws(src, 0, len(src)) > MAX_CHUNK_NONWS
    chunks = chunk_ast(BLOB, src, "svc.py", "python")
    assert chunks is not None
    assert len(chunks) > 1, "oversized class must be split"
    for c in chunks:
        assert _nonws(src, c.byte_start, c.byte_end) <= MAX_CHUNK_NONWS
    _reassemble(chunks, src)
    # methods (after the first header chunk) carry the class in the breadcrumb
    assert any("BigService0" in c.breadcrumb and "def method_" in c.breadcrumb for c in chunks)


def test_small_siblings_merged() -> None:
    src = b"".join(
        f"def tiny_{i}(x):\n    return x + {i}\n\n\n".encode() for i in range(5)
    )
    chunks = chunk_ast(BLOB, src, "tiny.py", "python")
    assert chunks is not None
    assert len(chunks) == 1, "five tiny siblings fit one chunk and must merge"
    _reassemble(chunks, src)


def test_interstitial_text_preserved_byte_exact() -> None:
    src = (
        b"# leading comment\n\n"
        + _big_class(0).encode()
        + b"\n\n# interstitial commentary between the classes\n# more notes\n\n"
        + _big_class(1).encode()
        + b"\n\n# trailing remark\n"
    )
    chunks = chunk_ast(BLOB, src, "two.py", "python")
    assert chunks is not None
    _reassemble(chunks, src)  # nothing between siblings may be lost
    joined = b"".join(
        src[c.byte_start : c.byte_end] for c in sorted(chunks, key=lambda c: c.byte_start)
    )
    assert joined == src


def test_same_blob_same_chunks_property() -> None:
    src = _big_class().encode()
    a = chunk_ast(BLOB, src, "svc.py", "python")
    b = chunk_ast(BLOB, src, "svc.py", "python")
    assert a == b


def test_giant_single_line_hard_split() -> None:
    src = b"DATA = '" + b"x" * 10_000 + b"'\n"
    chunks = chunk_ast(BLOB, src, "data.py", "python")
    assert chunks is not None
    for c in chunks:
        assert _nonws(src, c.byte_start, c.byte_end) <= MAX_CHUNK_NONWS
    _reassemble(chunks, src)


def test_deeply_nested_ast_does_not_crash() -> None:
    """Verifier Phase 2 finding 2: chained binary operators build an AST one
    level deep per operator; an oversized node of that shape must not blow the
    interpreter stack (generated/concatenated JS is exactly this)."""
    src = b"var x=" + b"1+" * 20_000 + b"1;"
    chunks = chunk_blob(BLOB, src, "app.js")  # full dispatch path, no exception
    assert chunks
    for c in chunks:
        assert _nonws(src, c.byte_start, c.byte_end) <= MAX_CHUNK_NONWS
    _reassemble(chunks, src)
    # determinism holds on the depth-capped path too
    assert chunks == chunk_blob(BLOB, src, "app.js")


def test_deeply_nested_oversized_python_does_not_crash() -> None:
    src = b"x = " + b"(" * 4_000 + b"1" + b")" * 4_000 + b"\n" + b"y = 2\n" * 800
    chunks = chunk_blob(BLOB, src, "gen.py")
    assert chunks
    _reassemble(chunks, src)


def test_javascript_class_chunks_and_breadcrumbs() -> None:
    methods = "\n".join(
        f"  method{i}(x) {{\n"
        + "\n".join(f"    x += {j}; // step" for j in range(60))
        + "\n    return x;\n  }\n"
        for i in range(8)
    )
    src = f"class Gadget {{\n{methods}}}\n\nfunction helper(a) {{ return a; }}\n".encode()
    chunks = chunk_ast(BLOB, src, "scripts/gadget.js", "javascript")
    assert chunks is not None
    assert len(chunks) > 1
    _reassemble(chunks, src)
    method_chunks = [c for c in chunks if c.code.lstrip().startswith("method")]
    assert method_chunks
    assert method_chunks[0].breadcrumb.startswith("// scripts/gadget.js :: Gadget :: method")


# -------------------------------------------------------------- breadcrumbs


def test_breadcrumb_method_in_class() -> None:
    src = _big_class().encode()
    chunks = chunk_ast(BLOB, src, "pyserver/svc.py", "python")
    assert chunks is not None
    method_chunks = [c for c in chunks if c.code.lstrip().startswith("def method_")]
    assert method_chunks, "expected standalone method chunks from the big class"
    crumb = method_chunks[0].breadcrumb
    assert crumb.startswith("# pyserver/svc.py :: BigService0 :: def method_")
    assert "(self, value: int) -> int:" in crumb
    assert "Method" in crumb  # docstring first line appended


def test_breadcrumb_module_level_function() -> None:
    src = b'def solo(a, b):\n    """Adds things."""\n    return a + b\n'
    chunks = chunk_ast(BLOB, src, "pyserver/util.py", "python")
    assert chunks is not None and len(chunks) == 1
    crumb = chunks[0].breadcrumb
    assert crumb.startswith("# pyserver/util.py :: util :: def solo(a, b):")
    assert "Adds things." in crumb


def test_breadcrumb_typescript_method() -> None:
    methods = "\n".join(
        f"  method{i}(x: number): number {{\n"
        + "\n".join(f"    x += {j}; // step" for j in range(60))
        + "\n    return x;\n  }\n"
        for i in range(8)
    )
    src = f"export class Widget {{\n{methods}}}\n".encode()
    chunks = chunk_ast(BLOB, src, "webapp/src/widget.ts", "typescript")
    assert chunks is not None
    assert len(chunks) > 1
    _reassemble(chunks, src)
    method_chunks = [c for c in chunks if c.code.lstrip().startswith("method")]
    assert method_chunks
    assert method_chunks[0].breadcrumb.startswith("// webapp/src/widget.ts :: Widget :: method")


# ------------------------------------------------------- fallback + dispatch


def test_broken_file_falls_back_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    src = b"def broken(:::\n    what\n"
    with caplog.at_level(logging.WARNING, logger="codesherpa.chunker.cast"):
        chunks = chunk_blob(BLOB, src, "broken.py")
    assert chunks, "fallback must still produce chunks"
    assert any("falling back to line windows" in r.message for r in caplog.records)
    assert chunks[0].breadcrumb.endswith("L1-2")  # line-window breadcrumb shape


def test_unknown_language_uses_line_windows() -> None:
    chunks = chunk_blob(BLOB, b"# just some text\nmore\n", "README.md")
    assert len(chunks) == 1
    assert "L1-2" in chunks[0].breadcrumb


def test_empty_parsed_file() -> None:
    assert chunk_ast(BLOB, b"", "empty.py", "python") == []


# --------------------------------------------------- fixture-wide invariants


@pytest.mark.parametrize("suffixes", [(".py",), (".ts", ".tsx")])
def test_fixture_files_parse_without_fallback(
    miniproject: Path, suffixes: tuple[str, ...], caplog: pytest.LogCaptureFixture
) -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=miniproject, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    paths = [p for p in tracked if p.endswith(suffixes)]
    assert len(paths) >= 10
    with caplog.at_level(logging.WARNING, logger="codesherpa.chunker.cast"):
        for rel in paths:
            data = (miniproject / rel).read_bytes()
            chunks = chunk_blob(BLOB, data, rel)
            if data:
                _reassemble(chunks, data)
                lang = detect_language(rel)
                assert all(c.language == lang for c in chunks)
    assert not caplog.records, f"fixture files must parse cleanly: {caplog.records}"


PY_SNIPPETS = st.lists(
    st.sampled_from(
        [
            "def f(a, b):\n    return a + b\n",
            "class K:\n    x = 1\n\n    def m(self):\n        return self.x\n",
            "# a comment\n",
            "\n\n",
            "CONST = {'k': [1, 2, 3]}\n",
            "import os\n",
            "if True:\n    print('hi')\n",
            '"""module docstring."""\n',
        ]
    ),
    min_size=0,
    max_size=40,
)


@settings(max_examples=40, deadline=None)
@given(parts=PY_SNIPPETS)
def test_property_valid_python_byte_exact_and_deterministic(parts: list[str]) -> None:
    data = "".join(parts).encode()
    a = chunk_blob(BLOB, data, "gen.py")
    b = chunk_blob(BLOB, data, "gen.py")
    assert a == b
    if data:
        _reassemble(a, data)
    else:
        assert a == []
