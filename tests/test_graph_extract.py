"""Phase 4: symbol/edge extraction spot-checks on the miniproject fixture.

CLAUDE.md §10 Phase 4: "Definitions/references/imports/calls extracted for
Py+TS on fixture; spot-check tests assert ≥10 known edges exist."
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repograph.contracts.types import Edge, EdgeKind, SymbolKind, SymbolNode
from repograph.graph.extract import SourceFile, extract_file, extract_project
from repograph.graph.gitio import last_change_dates, source_files_at_rev


@pytest.fixture(scope="module")
def extraction(miniproject: Path):
    files = source_files_at_rev(miniproject)
    symbols, edges = extract_project(files)
    return files, symbols, edges, {s.node_id: s for s in symbols}


def _edge_exists(
    edges: list[Edge],
    by_id: dict[str, SymbolNode],
    kind: EdgeKind,
    src: tuple[str, str],
    dst: tuple[str, str],
) -> bool:
    for edge in edges:
        if edge.kind is not kind:
            continue
        s, d = by_id[edge.src], by_id[edge.dst]
        if (s.file_path, s.symbol) == src and (d.file_path, d.symbol) == dst:
            return True
    return False


# (kind, (src file, src symbol), (dst file, dst symbol)) — 15 cross-checked
# against the fixture builder's file contents; well over the required 10.
KNOWN_EDGES = [
    # Python calls
    (EdgeKind.CALLS, ("pyserver/routes/tasks.py", "create_task"), ("pyserver/validators.py", "validate_title")),
    (EdgeKind.CALLS, ("pyserver/routes/tasks.py", "create_task"), ("pyserver/utils/time.py", "utc_now_iso")),
    (EdgeKind.CALLS, ("pyserver/routes/tasks.py", "list_tasks"), ("pyserver/models/task.py", "task_from_row")),
    (EdgeKind.CALLS, ("pyserver/routes/users.py", "get_user"), ("pyserver/models/user.py", "user_from_row")),
    (EdgeKind.CALLS, ("pyserver/routes/users.py", "create_user"), ("pyserver/validators.py", "validate_email")),
    (EdgeKind.CALLS, ("pyserver/app.py", "create_app"), ("pyserver/config.py", "load_config")),
    (EdgeKind.CALLS, ("pyserver/app.py", "create_app"), ("pyserver/routes/__init__.py", "register_routes")),
    (EdgeKind.CALLS, ("pyserver/cli.py", "main"), ("pyserver/app.py", "run")),
    # attribute call resolved to a method definition
    (EdgeKind.CALLS, ("pyserver/services/notifications.py", "send_task_notification"), ("pyserver/http_client.py", "retry_request")),
    (EdgeKind.CALLS, ("pyserver/http_client.py", "fetch_json"), ("pyserver/http_client.py", "retry_request")),
    # TypeScript / TSX calls
    (EdgeKind.CALLS, ("webclient/src/api.ts", "fetchTasks"), ("webclient/src/http.ts", "request")),
    (EdgeKind.CALLS, ("webclient/src/store.ts", "refresh"), ("webclient/src/api.ts", "fetchTasks")),
    (EdgeKind.CALLS, ("webclient/src/auth.ts", "login"), ("webclient/src/http.ts", "fetchWithRetry")),
    (EdgeKind.CALLS, ("webclient/src/index.ts", "bootstrap"), ("webclient/src/store.ts", "TaskStore")),
    (EdgeKind.CALLS, ("webclient/src/components/TaskItem.tsx", "TaskItem"), ("webclient/src/utils/format.ts", "formatTitle")),
]

KNOWN_IMPORT_EDGES = [
    (EdgeKind.IMPORTS, ("pyserver/routes/tasks.py", "pyserver.routes.tasks"), ("pyserver/validators.py", "validate_title")),
    (EdgeKind.IMPORTS, ("pyserver/app.py", "pyserver.app"), ("pyserver/db.py", "Database")),
    (EdgeKind.IMPORTS, ("pyserver/routes/__init__.py", "pyserver.routes"), ("pyserver/routes/tasks.py", "pyserver.routes.tasks")),
    (EdgeKind.IMPORTS, ("webclient/src/api.ts", "webclient/src/api"), ("webclient/src/http.ts", "request")),
    (EdgeKind.IMPORTS, ("webclient/src/store.ts", "webclient/src/store"), ("webclient/src/types.ts", "Task")),
]

KNOWN_REFERENCE_EDGES = [
    # handlers passed (not called) in route registration
    (EdgeKind.REFERENCES, ("pyserver/routes/__init__.py", "register_routes"), ("pyserver/routes/tasks.py", "list_tasks")),
    (EdgeKind.REFERENCES, ("pyserver/routes/__init__.py", "register_routes"), ("pyserver/routes/users.py", "create_user")),
    # type annotation references
    (EdgeKind.REFERENCES, ("pyserver/routes/tasks.py", "list_tasks"), ("pyserver/db.py", "Database")),
    (EdgeKind.REFERENCES, ("webclient/src/api.ts", "fetchTasks"), ("webclient/src/types.ts", "Task")),
    # JSX component usage
    (EdgeKind.REFERENCES, ("webclient/src/components/TaskList.tsx", "TaskList"), ("webclient/src/components/TaskItem.tsx", "TaskItem")),
]

KNOWN_DEFINES_EDGES = [
    (EdgeKind.DEFINES, ("pyserver/db.py", "pyserver.db"), ("pyserver/db.py", "Database")),
    (EdgeKind.DEFINES, ("pyserver/db.py", "Database"), ("pyserver/db.py", "connect")),
    (EdgeKind.DEFINES, ("webclient/src/store.ts", "TaskStore"), ("webclient/src/store.ts", "refresh")),
]


@pytest.mark.parametrize("kind,src,dst", KNOWN_EDGES)
def test_known_call_edges(extraction, kind, src, dst):
    _files, _symbols, edges, by_id = extraction
    assert _edge_exists(edges, by_id, kind, src, dst), f"missing {kind.value}: {src} -> {dst}"


@pytest.mark.parametrize(
    "kind,src,dst", KNOWN_IMPORT_EDGES + KNOWN_REFERENCE_EDGES + KNOWN_DEFINES_EDGES
)
def test_known_structural_edges(extraction, kind, src, dst):
    _files, _symbols, edges, by_id = extraction
    assert _edge_exists(edges, by_id, kind, src, dst), f"missing {kind.value}: {src} -> {dst}"


EXPECTED_KINDS = [
    ("pyserver/db.py", "Database", SymbolKind.CLASS),
    ("pyserver/db.py", "connect", SymbolKind.METHOD),
    ("pyserver/utils/text.py", "slugify", SymbolKind.FUNCTION),
    ("pyserver/validators.py", "MAX_TITLE_LENGTH", SymbolKind.CONST),
    ("pyserver/routes/users.py", "_user_cache", SymbolKind.VARIABLE),
    ("webclient/src/store.ts", "TaskStore", SymbolKind.CLASS),
    ("webclient/src/store.ts", "refresh", SymbolKind.METHOD),
    ("webclient/src/types.ts", "Task", SymbolKind.CLASS),
    ("webclient/src/utils/format.ts", "formatTitle", SymbolKind.FUNCTION),
    ("webclient/src/api.ts", "BASE", SymbolKind.CONST),
    ("pyserver/app.py", "pyserver.app", SymbolKind.MODULE),
]


@pytest.mark.parametrize("path,name,kind", EXPECTED_KINDS)
def test_definition_kinds(extraction, path, name, kind):
    _files, symbols, _edges, _by_id = extraction
    matches = [s for s in symbols if s.file_path == path and s.symbol == name]
    assert matches, f"no definition {name} in {path}"
    assert any(s.kind is kind for s in matches), (
        f"{path}:{name} kinds {[s.kind.value for s in matches]}, wanted {kind.value}"
    )


def test_signatures_are_first_lines(extraction):
    _files, symbols, _edges, _by_id = extraction
    sig = {
        (s.file_path, s.symbol): s.signature
        for s in symbols
        if s.kind is not SymbolKind.MODULE
    }
    assert sig[("pyserver/validators.py", "validate_title")].startswith(
        "def validate_title(title: str) -> str:"
    )
    # the definition node is the declaration itself, inside the export_statement
    assert sig[("webclient/src/http.ts", "fetchWithRetry")].startswith(
        "async function fetchWithRetry<T>("
    )


def test_no_cross_language_edges(extraction):
    _files, _symbols, edges, by_id = extraction
    for edge in edges:
        s, d = by_id[edge.src], by_id[edge.dst]
        assert s.file_path.endswith(".py") == d.file_path.endswith(".py"), (
            f"cross-language edge {s.file_path} -> {d.file_path}"
        )


def test_extraction_is_deterministic(extraction):
    files, symbols, edges, _by_id = extraction
    symbols2, edges2 = extract_project(files)
    assert [s.node_id for s in symbols] == [s.node_id for s in symbols2]
    assert edges == edges2
    # shuffled input order must not change the result
    symbols3, edges3 = extract_project(list(reversed(list(files))))
    assert [s.node_id for s in symbols] == [s.node_id for s in symbols3]
    assert edges == edges3


def test_every_edge_endpoint_is_a_known_symbol(extraction):
    _files, symbols, edges, by_id = extraction
    for edge in edges:
        assert edge.src in by_id and edge.dst in by_id


def test_unparseable_file_does_not_crash():
    garbage = SourceFile(
        path="junk.py",
        blob_hash="0" * 40,
        language="python",
        data=b"\x00\xff\xfe def broken(((((\n\x9c",
    )
    symbols, edges = extract_project([garbage])
    # module node always exists; nothing else is guaranteed
    assert any(s.kind is SymbolKind.MODULE for s in symbols)


def test_unsupported_language_is_skipped():
    readme = SourceFile(path="README.md", blob_hash="1" * 40, language="markdown", data=b"# hi")
    assert extract_project([readme]) == ([], [])
    assert extract_file(readme) == []


def test_extract_file_returns_defs_and_module(extraction):
    files, _symbols, _edges, _by_id = extraction
    db = next(f for f in files if f.path == "pyserver/db.py")
    nodes = extract_file(db)
    names = {(n.symbol, n.kind) for n in nodes}
    assert ("pyserver.db", SymbolKind.MODULE) in names
    assert ("Database", SymbolKind.CLASS) in names
    assert ("connect", SymbolKind.METHOD) in names


def test_empty_repo_raises_clean_value_error(tmp_path: Path):
    """Verifier advisory A2: a repo with no commits must fail with a domain
    error, not a raw CalledProcessError."""
    import subprocess as sp

    from repograph.graph.gitio import source_files_at_rev

    sp.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    with pytest.raises(ValueError, match="cannot read tree"):
        source_files_at_rev(tmp_path)
    with pytest.raises(ValueError, match="cannot read history"):
        last_change_dates(tmp_path)


def test_last_change_dates(miniproject: Path):
    dates = last_change_dates(miniproject)
    # commit days are fixed by the fixture builder (2024-01-01 .. 2024-01-06)
    assert dates["pyserver/config.py"].startswith("2024-01-01")
    assert dates["pyserver/http_client.py"].startswith("2024-01-03")
    assert dates["pyserver/routes/users.py"].startswith("2024-01-06")
    assert dates["webclient/src/auth.ts"].startswith("2024-01-06")
