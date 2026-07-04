"""Tests for the line-window fallback chunker and the dispatcher (Phase 1)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from codesherpa.chunker import chunk_blob, detect_language
from codesherpa.chunker.fallback import OVERLAP_LINES, WINDOW_LINES, chunk_lines

BLOB = "f" * 40


def _lines(n: int) -> bytes:
    return b"".join(f"line {i}\n".encode() for i in range(n))


def test_detect_language() -> None:
    assert detect_language("pyserver/db.py") == "python"
    assert detect_language("webapp/src/api.ts") == "typescript"
    assert detect_language("webapp/src/App.tsx") == "tsx"
    assert detect_language("scripts/build.js") == "javascript"
    assert detect_language("README.md") == "text"
    assert detect_language("Makefile") == "text"


def test_small_file_is_one_chunk() -> None:
    data = _lines(10)
    chunks = chunk_lines(BLOB, data, "a.py", "python")
    assert len(chunks) == 1
    (chunk,) = chunks
    assert (chunk.byte_start, chunk.byte_end) == (0, len(data))
    assert chunk.code == data.decode()
    assert chunk.breadcrumb == "# a.py :: L1-10"


def test_empty_file_has_no_chunks() -> None:
    assert chunk_lines(BLOB, b"", "a.py", "python") == []


def test_windows_and_overlap() -> None:
    data = _lines(300)
    chunks = chunk_lines(BLOB, data, "a.py", "python")
    # 300 lines -> windows starting at lines 0, 100, 200: [0,120), [100,220), [200,300)
    assert len(chunks) == 3
    spans = [(c.code.splitlines()[0], len(c.code.splitlines())) for c in chunks]
    assert spans == [("line 0", WINDOW_LINES), ("line 100", WINDOW_LINES), ("line 200", 100)]
    # consecutive windows share exactly OVERLAP_LINES lines
    first = chunks[0].code.splitlines()
    second = chunks[1].code.splitlines()
    assert first[-OVERLAP_LINES:] == second[:OVERLAP_LINES]


def test_chunks_cover_all_bytes() -> None:
    for n in (1, 119, 120, 121, 240, 301):
        data = _lines(n)
        chunks = chunk_lines(BLOB, data, "a.py", "python")
        covered = set()
        for c in chunks:
            covered.update(range(c.byte_start, c.byte_end))
            assert c.code == data[c.byte_start : c.byte_end].decode()
        assert covered == set(range(len(data)))


def test_no_trailing_newline() -> None:
    data = b"a\nb\nc"  # 3 lines, no final newline
    (chunk,) = chunk_lines(BLOB, data, "a.py", "python")
    assert chunk.byte_end == len(data)
    assert chunk.code.endswith("c")
    assert chunk.breadcrumb.endswith("L1-3")


def test_invalid_utf8_does_not_crash() -> None:
    data = b"def f():\n    return b'\xff\xfe'\n"
    (chunk,) = chunk_lines(BLOB, data, "a.py", "python")
    assert "�" in chunk.code  # replacement char, no exception


def test_breadcrumb_uses_language_comment_marker() -> None:
    (py,) = chunk_lines(BLOB, b"x\n", "a.py", "python")
    (ts,) = chunk_lines(BLOB, b"x\n", "a.ts", "typescript")
    assert py.breadcrumb.startswith("# ")
    assert ts.breadcrumb.startswith("// ")


def test_dispatcher_detects_language_and_delegates() -> None:
    data = _lines(5)
    chunks = chunk_blob(BLOB, data, "pyserver/db.py")
    assert len(chunks) == 1
    assert chunks[0].language == "python"


@given(st.binary(max_size=8000))
def test_determinism_and_coverage_property(data: bytes) -> None:
    a = chunk_blob(BLOB, data, "any/file.py")
    b = chunk_blob(BLOB, data, "any/file.py")
    assert a == b
    if data:
        covered = set()
        for c in a:
            assert 0 <= c.byte_start < c.byte_end <= len(data)
            covered.update(range(c.byte_start, c.byte_end))
        assert covered == set(range(len(data)))
    else:
        assert a == []


def test_single_line_mega_file_is_byte_capped() -> None:
    """D38 regression: a single-line file (large JSONL rows, minified data)
    must never emit an unbounded chunk — a 287 KB single-line chunk reaching
    a length-sorted embedding batch measured >14 GB RSS."""
    from codesherpa.chunker.fallback import MAX_CHUNK_BYTES, chunk_lines

    data = (b'{"x":"' + b"a" * (2 * 1024 * 1024) + b'"}')  # 2 MB, one line
    chunks = chunk_lines("f" * 40, data, "trace.jsonl", "text")
    assert len(chunks) > 1
    assert all(c.byte_end - c.byte_start <= MAX_CHUNK_BYTES for c in chunks)
    # contiguous full coverage, byte-exact
    assert chunks[0].byte_start == 0 and chunks[-1].byte_end == len(data)
    for a, b in zip(chunks, chunks[1:]):
        assert b.byte_start == a.byte_end
    # deterministic
    again = chunk_lines("f" * 40, data, "trace.jsonl", "text")
    assert [(c.byte_start, c.byte_end) for c in again] == [
        (c.byte_start, c.byte_end) for c in chunks
    ]


def test_multi_line_windows_also_respect_byte_cap() -> None:
    from codesherpa.chunker.fallback import MAX_CHUNK_BYTES, chunk_lines

    line = b"y" * 4000 + b"\n"  # 120-line window would be ~480 KB
    chunks = chunk_lines("e" * 40, line * 300, "big.txt", "text")
    assert all(c.byte_end - c.byte_start <= MAX_CHUNK_BYTES for c in chunks)
