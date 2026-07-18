"""Partial-AST salvage: degrade at DECLARATION granularity, not file granularity.

A single unparseable expression inside one function body used to discard the
whole file's structure (cAST returned ``None`` on ``root.has_error`` and the
dispatcher line-windowed everything). These tests pin the salvage path:
clean top-level declarations keep real cAST chunks with breadcrumbs, only the
error-tainted extents degrade to line windows, and the byte-exact partition
invariant still holds across the mixed chunk set (CLAUDE.md §7.2, DECISIONS D47).
"""

from __future__ import annotations

import logging

import pytest

from codesherpa.chunker import chunk_blob
from codesherpa.chunker.cast import MAX_TAINTED_DECL_FRACTION, chunk_ast
from codesherpa.contracts.types import Chunk

BLOB = "s" * 40


def _reassemble(chunks: list[Chunk], data: bytes) -> None:
    """Assert chunks partition the blob byte-exactly, in order (no gap/overlap)."""
    assert chunks, "no chunks produced"
    assert chunks[0].byte_start == 0
    assert chunks[-1].byte_end == len(data)
    for prev, cur in zip(chunks, chunks[1:]):
        assert prev.byte_end == cur.byte_start, "gap or overlap between chunks"
    for c in chunks:
        assert c.code == data[c.byte_start : c.byte_end].decode("utf-8", errors="replace")
    joined = b"".join(data[c.byte_start : c.byte_end] for c in chunks)
    assert joined == data


# The real shape that motivated this (grafana/grafana): the repo shadows Go's
# builtin `new` with `func new[T any](v T) *T`, but the tree-sitter Go grammar
# hard-codes `new(` as taking a TYPE, so every `new(<expression>)` call becomes
# an ERROR node nested inside a function body.
GO_MIXED = b"""package svc

import "fmt"

// CleanOne adds one.
func CleanOne(a int) int {
	return a + 1
}

func Tainted(v string) *string {
	x := new(v + "suffix")
	return x
}

type Store struct {
	name string
}

// Save persists the store.
func (s *Store) Save(ctx int) error {
	fmt.Println(s.name, ctx)
	return nil
}
"""


def _pad(n: int) -> str:
    """Body lines that push a declaration past MAX_CHUNK_NONWS so it becomes its
    own chunk instead of merging with its neighbours."""
    return "\n".join(f"\tsum += {j} // accumulate step {j}" for j in range(n))


# Same shape as GO_MIXED but with declaration bodies large enough that the
# greedy sibling merge cannot glue them together — this is what real repo code
# looks like, and it lets us assert on per-declaration breadcrumbs.
GO_MIXED_BIG = f"""package svc

import "fmt"

// CleanOne accumulates.
func CleanOne(a int) int {{
	sum := a
{_pad(120)}
	return sum
}}

func Tainted(v string) *string {{
	x := new(v + "suffix")
{_pad(40)}
	return x
}}

type Store struct {{
	name string
}}

// Save persists the store.
func (s *Store) Save(ctx int) error {{
	sum := ctx
{_pad(120)}
	fmt.Println(s.name, sum)
	return nil
}}
""".encode()


def test_salvage_keeps_clean_go_declarations_with_breadcrumbs() -> None:
    chunks = chunk_ast(BLOB, GO_MIXED_BIG, "pkg/svc/store.go", "go")
    assert chunks is not None, "a file with one tainted body must not be discarded wholesale"

    crumbs = [c.breadcrumb for c in chunks]
    # the clean declarations produce real cAST breadcrumbs, not line windows
    assert any(":: CleanOne ::" in c and "syntax errors" not in c for c in crumbs), crumbs
    # the Go receiver scope (D45) survives salvage for the method after the
    # tainted declaration
    assert any(":: (svc.Store) ::" in c and "syntax errors" not in c for c in crumbs), crumbs

    # the tainted declaration is covered by fallback chunks, flagged as such
    tainted = [c for c in chunks if "syntax errors" in c.breadcrumb]
    assert tainted, crumbs
    covered = b"".join(GO_MIXED_BIG[c.byte_start : c.byte_end] for c in tainted)
    assert b'new(v + "suffix")' in covered
    # ...and the tainted region did NOT swallow the clean declarations
    assert b"func CleanOne" not in covered
    assert b"func (s *Store) Save" not in covered
    _reassemble(chunks, GO_MIXED_BIG)


def test_salvage_small_file_still_chunks_clean_regions() -> None:
    """Even when every declaration is small enough to merge, the clean regions
    stay cAST chunks (breadcrumbed from real signatures) and only the tainted
    extent is line-windowed."""
    chunks = chunk_ast(BLOB, GO_MIXED, "pkg/svc/store.go", "go")
    assert chunks is not None
    clean = [c for c in chunks if "syntax errors" not in c.breadcrumb]
    tainted = [c for c in chunks if "syntax errors" in c.breadcrumb]
    assert clean and tainted
    clean_code = b"".join(GO_MIXED[c.byte_start : c.byte_end] for c in clean)
    assert b"func CleanOne" in clean_code
    assert b"func (s *Store) Save" in clean_code
    assert b'new(v + "suffix")' not in clean_code


def test_salvage_is_byte_exact() -> None:
    _reassemble(chunk_blob(BLOB, GO_MIXED, "pkg/svc/store.go"), GO_MIXED)


def test_salvage_is_deterministic() -> None:
    a = chunk_blob(BLOB, GO_MIXED, "pkg/svc/store.go")
    b = chunk_blob(BLOB, GO_MIXED, "pkg/svc/store.go")
    assert a == b


def test_salvage_logs_what_it_salvaged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="codesherpa.chunker.cast"):
        chunk_blob(BLOB, GO_MIXED, "pkg/svc/store.go")
    assert any("salvag" in r.message for r in caplog.records), caplog.records
    assert not any("falling back to line windows" in r.message for r in caplog.records)


# ------------------------------------------------------- wholesale thresholds


def test_mostly_tainted_file_falls_back_wholesale() -> None:
    """Past MAX_TAINTED_DECL_FRACTION the declaration boundaries themselves are
    unreliable: salvaging a sliver of structure out of a mostly-unparsed file is
    worse than honest line windows."""
    tainted = "\n\n".join(
        f'func Tainted{i}(v string) *string {{\n\treturn new(v + "{i}")\n}}' for i in range(6)
    )
    src = f"package svc\n\nfunc Clean() int {{\n\treturn 1\n}}\n\n{tainted}\n".encode()
    assert chunk_ast(BLOB, src, "pkg/svc/big.go", "go") is None
    # ...but the dispatcher still returns chunks, never crashes
    assert chunk_blob(BLOB, src, "pkg/svc/big.go")


def test_one_huge_tainted_function_does_not_sink_its_clean_siblings() -> None:
    """The threshold counts DECLARATIONS, not bytes. A single enormous tainted
    test function is most of a file's bytes yet leaves the surrounding
    declarations perfectly parsed — that file must still be salvaged."""
    huge = "\n".join(f'\tfmt.Println("line {j}", v)' for j in range(2000))
    src = (
        "package svc\n\nimport \"fmt\"\n\n"
        f'func Tainted(v string) {{\n\tx := new(v + "s")\n{huge}\n\tfmt.Println(x)\n}}\n\n'
        + "\n\n".join(f"func Clean{i}() int {{\n\treturn {i}\n}}" for i in range(6))
        + "\n"
    ).encode()
    chunks = chunk_ast(BLOB, src, "pkg/svc/huge.go", "go")
    assert chunks is not None, "byte-share must not decide the fallback"
    clean = [c for c in chunks if "syntax errors" not in c.breadcrumb]
    clean_code = "".join(c.code for c in clean)
    assert "func Clean0" in clean_code and "func Clean5" in clean_code
    assert any("func Clean0() int {" in c.breadcrumb for c in clean)
    _reassemble(chunks, src)


def test_threshold_is_a_named_constant() -> None:
    assert 0.0 < MAX_TAINTED_DECL_FRACTION < 1.0


def test_no_clean_declaration_falls_back_wholesale() -> None:
    src = b'package svc\n\nfunc Only(v string) *string {\n\treturn new(v + "x")\n}\n'
    assert chunk_ast(BLOB, src, "pkg/svc/only.go", "go") is None


# --------------------------------------------------------- python generalisation


def test_salvage_generalises_to_python() -> None:
    """Not Go-specific: any grammar gap nested in one body keeps the rest."""
    src = (
        b'def clean_one(a, b):\n    """Adds."""\n    return a + b\n\n\n'
        b"def tainted(x):\n    y = 1 +* 2\n    return y\n\n\n"
        b"def clean_two(c):\n    return c * 2\n"
    )
    chunks = chunk_ast(BLOB, src, "pkg/util.py", "python")
    assert chunks is not None
    _reassemble(chunks, src)
    crumbs = [c.breadcrumb for c in chunks]
    assert any("def clean_one(a, b):" in c for c in crumbs), crumbs
    assert any("def clean_two(c):" in c for c in crumbs), crumbs
    assert any("syntax errors" in c for c in crumbs), crumbs


# ------------------------------------------- root-level ERROR (D47 relaxation)

# A stray closing brace at top level: tree-sitter emits a tiny ERROR node
# directly under root with perfectly-parsed declarations on BOTH sides. This is
# the shape of grafana's pkg/services/ngalert/models/testing.go, where a single
# byte of root-level ERROR used to cost all 145 clean declarations in the file.
GO_ROOT_ERROR = b"""package svc

func Before() int {
	return 1
}
}

func AfterOne() int {
	return 3
}

func AfterTwo() int {
	return 4
}
"""

# A root-level ERROR that STRADDLES several declarations (unbalanced brace
# swallows everything to EOF) — grafana's api_ruler_test.go has ~2.6 KB spans of
# this shape. Most likely case to produce a gap or overlap, so it is pinned.
GO_ROOT_ERROR_STRADDLING = b"""package svc

func Before() int {
	return 1
}

func Straddle(a int) int {
	if a > 0 {
		return 2
)

func Swallowed(b int) int {
	return b
}

func AlsoSwallowed() int {
	return 3
}
"""


def test_root_level_error_salvages_its_clean_siblings() -> None:
    """D47 relaxation (owner decision): an ERROR/MISSING node directly under
    root is just another tainted extent — it must not cost the whole file its
    structure. The clean siblings' subtrees were confirmed error-free."""
    chunks = chunk_ast(BLOB, GO_ROOT_ERROR, "pkg/svc/testing.go", "go")
    assert chunks is not None, "a stray brace must not discard the whole file"
    clean = [c for c in chunks if "syntax errors" not in c.breadcrumb]
    clean_code = "".join(c.code for c in clean)
    for name in ("func Before", "func AfterOne", "func AfterTwo"):
        assert name in clean_code, (name, [c.breadcrumb for c in chunks])
    # the stray brace itself is covered, and flagged
    tainted = [c for c in chunks if "syntax errors" in c.breadcrumb]
    assert tainted
    assert b"}" in b"".join(GO_ROOT_ERROR[c.byte_start : c.byte_end] for c in tainted)


def test_root_level_error_is_byte_exact_and_deterministic() -> None:
    for src in (GO_ROOT_ERROR, GO_ROOT_ERROR_STRADDLING):
        chunks = chunk_blob(BLOB, src, "pkg/svc/testing.go")
        _reassemble(chunks, src)
        assert chunks == chunk_blob(BLOB, src, "pkg/svc/testing.go")


def test_root_level_error_straddling_declarations_is_byte_exact() -> None:
    """The ERROR node swallows several declarations at once: its whole extent
    must be covered by line windows with no gap or overlap against the clean
    declarations before it."""
    chunks = chunk_ast(BLOB, GO_ROOT_ERROR_STRADDLING, "pkg/svc/ruler_test.go", "go")
    assert chunks is not None
    _reassemble(chunks, GO_ROOT_ERROR_STRADDLING)
    clean_code = "".join(c.code for c in chunks if "syntax errors" not in c.breadcrumb)
    assert "func Before" in clean_code
    # everything the ERROR node swallowed is line-windowed, not silently dropped
    tainted_code = "".join(c.code for c in chunks if "syntax errors" in c.breadcrumb)
    assert "func Swallowed" in tainted_code
    assert "func AlsoSwallowed" in tainted_code


def test_unterminated_declaration_at_eof_salvages_the_rest() -> None:
    """Pins the INVERSE of the behavior asserted by the test D47a removed, on
    that test's exact input: an unterminated declaration at EOF is a root-level
    ERROR, and the complete declaration before it must survive."""
    src = b"package main\n\nfunc ok() int { return 1 }\n\nfunc ((( broken\n"
    chunks = chunk_ast(BLOB, src, "bad.go", "go")
    assert chunks is not None, "the whole file must no longer be discarded"
    clean_code = "".join(c.code for c in chunks if "syntax errors" not in c.breadcrumb)
    assert "func ok() int { return 1 }" in clean_code
    tainted_code = "".join(c.code for c in chunks if "syntax errors" in c.breadcrumb)
    assert "func ((( broken" in tainted_code
    _reassemble(chunks, src)
    assert chunks == chunk_ast(BLOB, src, "bad.go", "go")


def test_root_level_error_still_falls_back_when_mostly_tainted() -> None:
    """The relaxation does not disable the threshold: a top level that is
    genuinely destroyed trips MAX_TAINTED_DECL_FRACTION anyway."""
    tainted = "\n\n".join(
        f'func Tainted{i}(v string) *string {{\n\treturn new(v + "{i}")\n}}' for i in range(6)
    )
    src = f"package svc\n\nfunc Ok() int {{\n\treturn 1\n}}\n}}\n\n{tainted}\n".encode()
    assert chunk_ast(BLOB, src, "pkg/svc/hopeless.go", "go") is None
    assert chunk_blob(BLOB, src, "pkg/svc/hopeless.go")  # never crashes
