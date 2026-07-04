"""Test-support indexer: miniproject fixture -> InMemoryIndexStore.

This is NOT the production indexer (Phases 1-2, core-index worktree own that).
It exists so the retrieval pipeline can be exercised and eval-gated against
the fixture before core-index merges (CLAUDE.md §8). It approximates the cAST
contract that matters to retrieval:

- chunk identity = (git blob hash, byte_start, byte_end), contiguous coverage
- breadcrumbs: ``path :: enclosing scope :: signature`` + first docstring line
- symbols for defs (functions, classes, methods, consts) with byte ranges
- best-effort CALLS / REFERENCES / IMPORTS edges by name resolution

Python is parsed with stdlib ``ast``; TS/TSX with a top-level-declaration
regex scan. Oversized classes are split at method boundaries (cAST-style
recurse-into-children).
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from repograph.contracts.types import Chunk, Edge, EdgeKind, SymbolKind, SymbolNode
from tests.support.memstore import InMemoryIndexStore

MAX_CHUNK_CHARS = 1600

_LANGUAGES = {".py": "python", ".ts": "typescript", ".tsx": "tsx"}

_TS_DECL_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(function|class|const|let|interface|type|enum)\s+([A-Za-z_$][\w$]*)",
)
_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")


def git_blob_hash(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def _first_doc_line(doc: str | None) -> str:
    if not doc:
        return ""
    return doc.strip().splitlines()[0].strip()


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
    line_end = text.encode().find(b"\n", start)
    raw = text.encode()[start : line_end if line_end != -1 else None]
    return raw.decode(errors="replace").strip().rstrip(":")


def _index_python(path: str, content: bytes, store: InMemoryIndexStore) -> str:
    text = content.decode()
    blob = git_blob_hash(content)
    pf = _PyFile(text)
    tree = ast.parse(text)
    module_name = Path(path).stem

    chunks: list[Chunk] = []
    symbols: list[SymbolNode] = []
    calls: list[tuple[SymbolNode, ast.AST]] = []  # (enclosing def node, body)

    def add_chunk(start: int, end: int, scope: str, sig: str, doc: str = "") -> None:
        code = content[start:end].decode(errors="replace")
        if not code.strip():
            return
        breadcrumb = f"{path} :: {scope} :: {sig}" + (f" — {doc}" if doc else "")
        chunks.append(
            Chunk(
                blob_hash=blob, byte_start=start, byte_end=end,
                file_path=path, language="python", code=code, breadcrumb=breadcrumb,
            )
        )

    def add_symbol(name: str, kind: SymbolKind, start: int, end: int, sig: str) -> SymbolNode:
        node = SymbolNode(name, kind, blob, start, end, path, sig)
        symbols.append(node)
        return node

    # module symbol spans the whole file (import-edge source)
    module_sym = add_symbol(module_name, SymbolKind.MODULE, 0, len(content), f"module {path}")

    cut_done = 0  # bytes consumed so far (interstitial text -> module chunks)

    def flush_interstitial(upto: int) -> None:
        nonlocal cut_done
        if upto > cut_done:
            add_chunk(cut_done, upto, "module", f"module {module_name}",
                      _first_doc_line(ast.get_docstring(tree)) if cut_done == 0 else "")
        cut_done = max(cut_done, upto)

    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start, end = pf.node_span(top)
            flush_interstitial(start)
            sig = _py_signature(top, text, pf)
            sym = add_symbol(top.name, SymbolKind.FUNCTION, start, end, sig)
            add_chunk(start, end, "module", sig, _first_doc_line(ast.get_docstring(top)))
            calls.append((sym, top))
            cut_done = end
        elif isinstance(top, ast.ClassDef):
            start, end = pf.node_span(top)
            flush_interstitial(start)
            sig = _py_signature(top, text, pf)
            add_symbol(top.name, SymbolKind.CLASS, start, end, sig)
            class_doc = _first_doc_line(ast.get_docstring(top))
            methods = [
                m for m in top.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if end - start <= MAX_CHUNK_CHARS or not methods:
                add_chunk(start, end, "module", sig, class_doc)
                for m in methods:
                    m_start, m_end = pf.node_span(m)
                    m_sig = _py_signature(m, text, pf)
                    msym = add_symbol(m.name, SymbolKind.METHOD, m_start, m_end, m_sig)
                    calls.append((msym, m))
            else:
                # cAST-style: recurse into methods; header stays with class
                pos = start
                for m in methods:
                    m_start, m_end = pf.node_span(m)
                    if m_start > pos:
                        add_chunk(pos, m_start, top.name, sig, class_doc)
                        class_doc = ""
                    m_sig = _py_signature(m, text, pf)
                    msym = add_symbol(m.name, SymbolKind.METHOD, m_start, m_end, m_sig)
                    add_chunk(m_start, m_end, top.name, m_sig,
                              _first_doc_line(ast.get_docstring(m)))
                    calls.append((msym, m))
                    pos = m_end
                if end > pos:
                    add_chunk(pos, end, top.name, sig)
            cut_done = end
        elif isinstance(top, ast.Assign):
            for target in top.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    s, e = pf.node_span(top)
                    add_symbol(target.id, SymbolKind.CONST, s, e,
                               text.splitlines()[top.lineno - 1].strip())
    flush_interstitial(len(content))

    store.add_blob(blob, "python", len(content))
    store.add_chunks(chunks)
    store.add_symbols(symbols)

    # ---- edges: calls/references from each def body; imports from module
    edges: list[Edge] = []
    for sym, fn_node in calls:
        seen_names: set[tuple[str, str]] = set()
        for inner in ast.walk(fn_node):
            if isinstance(inner, ast.Call):
                name = None
                if isinstance(inner.func, ast.Name):
                    name = inner.func.id
                elif isinstance(inner.func, ast.Attribute):
                    name = inner.func.attr
                if name and name != sym.symbol:
                    seen_names.add((name, "call"))
            elif isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load):
                if inner.id != sym.symbol:
                    seen_names.add((inner.id, "ref"))
        for name, how in seen_names:
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
    store.add_edges(edges)
    return blob


def _index_typescript(path: str, content: bytes, store: InMemoryIndexStore) -> str:
    text = content.decode()
    blob = git_blob_hash(content)
    language = _LANGUAGES[Path(path).suffix]
    module_name = Path(path).stem

    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode()))

    # top-level decl cut points
    decls: list[tuple[int, str, str, str]] = []  # (byte, kindword, name, sigline)
    for i, line in enumerate(lines):
        m = _TS_DECL_RE.match(line)
        if m:
            decls.append((offsets[i], m.group(1), m.group(2), line.strip().rstrip("{ ").strip()))

    chunks: list[Chunk] = []
    symbols: list[SymbolNode] = []

    def add_chunk(start: int, end: int, scope: str, sig: str) -> None:
        code = content[start:end].decode(errors="replace")
        if not code.strip():
            return
        chunks.append(
            Chunk(
                blob_hash=blob, byte_start=start, byte_end=end,
                file_path=path, language=language, code=code,
                breadcrumb=f"{path} :: {scope} :: {sig}",
            )
        )

    module_sym = SymbolNode(module_name, SymbolKind.MODULE, blob, 0, len(content),
                            path, f"module {path}")
    symbols.append(module_sym)

    kind_map = {
        "function": SymbolKind.FUNCTION,
        "class": SymbolKind.CLASS,
        "interface": SymbolKind.CLASS,
        "type": SymbolKind.CLASS,
        "enum": SymbolKind.CONST,
    }
    bounds = [d[0] for d in decls] + [len(content)]
    if decls:
        add_chunk(0, bounds[0], "module", f"module {module_name}")
    else:
        add_chunk(0, len(content), "module", f"module {module_name}")
    seg_syms: list[tuple[SymbolNode, int, int]] = []
    for (start, kindword, name, sig), end in zip(decls, bounds[1:]):
        if kindword in ("const", "let"):
            seg = text.encode()[start:end].decode(errors="replace")
            is_fn = "=>" in seg.split("\n", 3)[0] or re.search(r"=\s*(async\s*)?\(", seg.split("\n", 1)[0]) is not None
            kind = SymbolKind.FUNCTION if is_fn else SymbolKind.CONST
        else:
            kind = kind_map[kindword]
        sym = SymbolNode(name, kind, blob, start, end, path, sig)
        symbols.append(sym)
        seg_syms.append((sym, start, end))
        add_chunk(start, end, "module", sig)

    store.add_blob(blob, language, len(content))
    store.add_chunks(chunks)
    store.add_symbols(symbols)

    # ---- best-effort edges by identifier occurrence within each segment
    edges: list[Edge] = []
    for sym, start, end in seg_syms:
        seg = content[start:end].decode(errors="replace")
        seen: set[tuple[str, str]] = set()
        for m in _IDENT_RE.finditer(seg):
            name = m.group(0)
            if name == sym.symbol:
                continue
            rest = seg[m.end() : m.end() + 1]
            seen.add((name, "call" if rest == "(" else "ref"))
        for name, how in seen:
            for target in store.get_definitions(name):
                if target.node_id == sym.node_id or target.blob_hash == blob and target.kind is SymbolKind.MODULE:
                    continue
                kind = EdgeKind.CALLS if how == "call" else EdgeKind.REFERENCES
                edges.append(Edge(sym.node_id, target.node_id, kind))
    # import lines -> IMPORTS edges from the module symbol
    for line in text.splitlines():
        if line.startswith("import "):
            for name in _IDENT_RE.findall(line.split(" from ")[0]):
                for target in store.get_definitions(name):
                    if target.node_id != module_sym.node_id:
                        edges.append(Edge(module_sym.node_id, target.node_id, EdgeKind.IMPORTS))
    store.add_edges(edges)
    return blob


def index_miniproject(root: Path, store: InMemoryIndexStore | None = None) -> InMemoryIndexStore:
    """Index every Py/TS/TSX file under ``root`` into an in-memory store.

    Two passes so cross-file name resolution sees all definitions.
    """
    store = store or InMemoryIndexStore()
    files = sorted(
        p for p in root.rglob("*")
        if p.suffix in _LANGUAGES and p.is_file() and ".git" not in p.parts
    )
    # pass 1: blobs, chunks, symbols (no edges yet — collect thunks)
    contents = {p: p.read_bytes() for p in files}
    path_to_blob: dict[str, str] = {}

    # first pass registers symbols only, by indexing with edge resolution
    # against an incrementally-filled store; a second identical pass re-runs
    # edge extraction now that every definition exists (add_* are idempotent).
    for _pass in (1, 2):
        for p in files:
            rel = p.relative_to(root).as_posix()
            content = contents[p]
            if not content.strip():
                path_to_blob[rel] = git_blob_hash(content)
                continue
            if p.suffix == ".py":
                path_to_blob[rel] = _index_python(rel, content, store)
            else:
                path_to_blob[rel] = _index_typescript(rel, content, store)

    store.map_files("HEAD", path_to_blob)
    store.set_meta("indexed_root", str(root))
    return store
