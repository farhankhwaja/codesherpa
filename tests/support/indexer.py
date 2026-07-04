"""Test-support SYMBOL/EDGE populator for retrieval tests (Phase 3).

Blobs, chunks, and FTS rows now come from the real gitlayer/chunker/store
pipeline (Phases 1-2). Symbol-graph extraction is Phase 4's job (graph-mcp
worktree), so until it merges, retrieval tests populate the real store's
``symbols``/``edges`` tables with this best-effort extractor (stdlib ``ast``
for Python, a top-level-declaration regex scan for TS/TSX/JS). Test-only,
per CLAUDE.md §8 ("against contracts, mocked ... until merge") and §2.5.

Extraction approximates §7.3: definitions (functions, classes, methods,
consts, module), CALLS / REFERENCES from def bodies, IMPORTS from module
imports, all by name resolution against known definitions.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from repograph.contracts.index_contract import IndexStore
from repograph.contracts.types import Edge, EdgeKind, SymbolKind, SymbolNode

_TS_DECL_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(function|class|const|let|interface|type|enum)\s+([A-Za-z_$][\w$]*)",
)
_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")

_PY_SUFFIXES = {".py"}
_TS_SUFFIXES = {".ts", ".tsx", ".js"}


class _PyFile:
    """Byte-offset helpers over one python source file."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.line_offsets = [0]
        for line in text.splitlines(keepends=True):
            self.line_offsets.append(self.line_offsets[-1] + len(line.encode()))

    def byte_of(self, lineno: int, col: int) -> int:
        # ast cols are utf-8 byte offsets already
        return self.line_offsets[lineno - 1] + col

    def node_span(self, node: ast.AST) -> tuple[int, int]:
        start_line = node.lineno
        decorators = getattr(node, "decorator_list", [])
        if decorators:
            start_line = min(d.lineno for d in decorators)
        start = self.byte_of(start_line, 0)  # include indentation
        end = self.byte_of(node.end_lineno, node.end_col_offset)
        return start, end


def _py_signature(node: ast.AST, text: str, pf: _PyFile) -> str:
    start = pf.byte_of(node.lineno, node.col_offset)
    encoded = text.encode()
    line_end = encoded.find(b"\n", start)
    raw = encoded[start : line_end if line_end != -1 else None]
    return raw.decode(errors="replace").strip().rstrip(":")


def _extract_python(
    path: str, blob_hash: str, content: bytes
) -> tuple[list[SymbolNode], list[tuple[SymbolNode, ast.AST]], ast.Module]:
    """-> (symbols, [(enclosing def symbol, fn node)] for edge pass, tree)."""
    text = content.decode()
    pf = _PyFile(text)
    tree = ast.parse(text)
    symbols: list[SymbolNode] = []
    def_bodies: list[tuple[SymbolNode, ast.AST]] = []

    def add(name: str, kind: SymbolKind, start: int, end: int, sig: str) -> SymbolNode:
        node = SymbolNode(name, kind, blob_hash, start, end, path, sig)
        symbols.append(node)
        return node

    add(Path(path).stem, SymbolKind.MODULE, 0, len(content), f"module {path}")

    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start, end = pf.node_span(top)
            sym = add(top.name, SymbolKind.FUNCTION, start, end, _py_signature(top, text, pf))
            def_bodies.append((sym, top))
        elif isinstance(top, ast.ClassDef):
            start, end = pf.node_span(top)
            add(top.name, SymbolKind.CLASS, start, end, _py_signature(top, text, pf))
            for m in top.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_start, m_end = pf.node_span(m)
                    msym = add(m.name, SymbolKind.METHOD, m_start, m_end,
                               _py_signature(m, text, pf))
                    def_bodies.append((msym, m))
        elif isinstance(top, ast.Assign):
            for target in top.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    s, e = pf.node_span(top)
                    add(target.id, SymbolKind.CONST, s, e,
                        text.splitlines()[top.lineno - 1].strip())
    return symbols, def_bodies, tree


def _python_edges(
    store: IndexStore,
    module_sym: SymbolNode,
    def_bodies: list[tuple[SymbolNode, ast.AST]],
    tree: ast.Module,
) -> list[Edge]:
    edges: list[Edge] = []
    for sym, fn_node in def_bodies:
        seen: set[tuple[str, str]] = set()
        for inner in ast.walk(fn_node):
            if isinstance(inner, ast.Call):
                name = None
                if isinstance(inner.func, ast.Name):
                    name = inner.func.id
                elif isinstance(inner.func, ast.Attribute):
                    name = inner.func.attr
                if name and name != sym.symbol:
                    seen.add((name, "call"))
            elif isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load):
                if inner.id != sym.symbol:
                    seen.add((inner.id, "ref"))
        for name, how in seen:
            for target in store.get_definitions(name):
                if target.node_id == sym.node_id:
                    continue
                kind = EdgeKind.CALLS if how == "call" else EdgeKind.REFERENCES
                edges.append(Edge(sym.node_id, target.node_id, kind))
    for top in tree.body:
        if isinstance(top, (ast.Import, ast.ImportFrom)):
            for alias in top.names:
                for target in store.get_definitions(alias.name.split(".")[-1]):
                    edges.append(Edge(module_sym.node_id, target.node_id, EdgeKind.IMPORTS))
    return edges


def _extract_typescript(
    path: str, blob_hash: str, content: bytes
) -> tuple[list[SymbolNode], list[tuple[SymbolNode, int, int]]]:
    text = content.decode()
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode()))

    decls: list[tuple[int, str, str, str]] = []
    for i, line in enumerate(lines):
        m = _TS_DECL_RE.match(line)
        if m:
            decls.append((offsets[i], m.group(1), m.group(2),
                          line.strip().rstrip("{ ").strip()))

    symbols: list[SymbolNode] = []
    module_sym = SymbolNode(Path(path).stem, SymbolKind.MODULE, blob_hash, 0,
                            len(content), path, f"module {path}")
    symbols.append(module_sym)

    kind_map = {
        "function": SymbolKind.FUNCTION,
        "class": SymbolKind.CLASS,
        "interface": SymbolKind.CLASS,
        "type": SymbolKind.CLASS,
        "enum": SymbolKind.CONST,
    }
    bounds = [d[0] for d in decls] + [len(content)]
    seg_syms: list[tuple[SymbolNode, int, int]] = []
    for (start, kindword, name, sig), end in zip(decls, bounds[1:]):
        if kindword in ("const", "let"):
            first_line = text.encode()[start:end].decode(errors="replace").split("\n", 1)[0]
            is_fn = "=>" in first_line or re.search(r"=\s*(async\s*)?\(", first_line) is not None
            kind = SymbolKind.FUNCTION if is_fn else SymbolKind.CONST
        else:
            kind = kind_map[kindword]
        sym = SymbolNode(name, kind, blob_hash, start, end, path, sig)
        symbols.append(sym)
        seg_syms.append((sym, start, end))
    return symbols, seg_syms


def _typescript_edges(
    store: IndexStore,
    content: bytes,
    module_sym: SymbolNode,
    seg_syms: list[tuple[SymbolNode, int, int]],
) -> list[Edge]:
    text = content.decode()
    edges: list[Edge] = []
    for sym, start, end in seg_syms:
        seg = content[start:end].decode(errors="replace")
        seen: set[tuple[str, str]] = set()
        for m in _IDENT_RE.finditer(seg):
            name = m.group(0)
            if name == sym.symbol:
                continue
            called = seg[m.end() : m.end() + 1] == "("
            seen.add((name, "call" if called else "ref"))
        for name, how in seen:
            for target in store.get_definitions(name):
                if target.node_id == sym.node_id or (
                    target.blob_hash == sym.blob_hash and target.kind is SymbolKind.MODULE
                ):
                    continue
                kind = EdgeKind.CALLS if how == "call" else EdgeKind.REFERENCES
                edges.append(Edge(sym.node_id, target.node_id, kind))
    for line in text.splitlines():
        if line.startswith("import "):
            for name in _IDENT_RE.findall(line.split(" from ")[0]):
                for target in store.get_definitions(name):
                    if target.node_id != module_sym.node_id:
                        edges.append(Edge(module_sym.node_id, target.node_id, EdgeKind.IMPORTS))
    return edges


def populate_symbols_and_edges(store: IndexStore, root: Path, ref: str = "HEAD") -> None:
    """Fill the store's symbols/edges tables from the repo at ``root``.

    Uses the store's own ``files_for_ref`` mapping (populated by the real
    gitlayer sync) so symbol blob hashes match the indexed blobs exactly.
    The working tree must be at ``ref`` (true for a fresh clone at HEAD).
    Idempotent: add_symbols/add_edges dedupe on primary keys.
    """
    files = store.files_for_ref(ref)
    parsed: list[tuple] = []  # per-file context for the edge pass

    for path, blob_hash in sorted(files.items()):
        suffix = Path(path).suffix
        file_on_disk = root / path
        if not file_on_disk.is_file():
            continue
        content = file_on_disk.read_bytes()
        if not content.strip():
            continue
        if suffix in _PY_SUFFIXES:
            try:
                symbols, def_bodies, tree = _extract_python(path, blob_hash, content)
            except SyntaxError:
                continue
            store.add_symbols(symbols)
            parsed.append(("py", symbols[0], def_bodies, tree, content))
        elif suffix in _TS_SUFFIXES:
            symbols, seg_syms = _extract_typescript(path, blob_hash, content)
            store.add_symbols(symbols)
            parsed.append(("ts", symbols[0], seg_syms, None, content))

    # second pass: edges, now that every definition is registered
    for lang, module_sym, bodies, tree, content in parsed:
        if lang == "py":
            store.add_edges(_python_edges(store, module_sym, bodies, tree))
        else:
            store.add_edges(_typescript_edges(store, content, module_sym, bodies))
