"""Two-pass symbol and edge extraction over tree-sitter ASTs (CLAUDE.md §7.3).

Pass 1 (per file): run the language's ``queries/*.scm`` captures to collect
definitions, imports, call sites, and identifier references.

Pass 2 (project): resolve names best-effort — same file -> same package ->
import-based -> globally-unique — and emit :class:`Edge` rows. No type
inference; unresolvable names are dropped rather than guessed.

Deterministic: the same set of (blob, path, language) inputs always yields
the same symbols and edges, in the same order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Iterable, Optional

from tree_sitter import Language, Parser, Query, QueryCursor
from tree_sitter_language_pack import get_language

from codesherpa.contracts.types import Edge, EdgeKind, SymbolKind, SymbolNode
from codesherpa.graph.languages import REGISTRY, LanguageSpec, language_for_path

__all__ = ["SourceFile", "extract_project", "extract_file", "language_for_path"]

_CONST_NAME_RE = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
_MAX_SIGNATURE_CHARS = 200

# Language families: a name may only resolve across files within its family
# (Python identifiers never resolve to TypeScript definitions, etc.).
_FAMILY = {
    "python": "python",
    "typescript": "ecma",
    "tsx": "ecma",
    "javascript": "ecma",
    "go": "go",
    "proto": "proto",
}

# Method names of ubiquitous builtin types (dict, list, str, os.environ,
# Array, Promise, localStorage, console, ...). The *globally-unique* fallback
# skips these: `payload.get(...)` must not resolve to some project `get`
# method just because exactly one exists. Same-file / same-package / import
# resolution still applies to them. See DECISIONS.md.
_GENERIC_NAMES = frozenset(
    """
    get set items keys values append extend insert pop remove read write open
    split rsplit join strip lstrip rstrip lower upper format match sub search
    findall encode decode dumps loads sleep urlopen fetchall fetchone
    push shift unshift filter map reduce slice splice concat indexOf includes
    find findIndex forEach trim replace toString json getItem setItem
    removeItem getTime floor ceil round max min stringify parse log info warn
    error then catch finally resolve reject setTimeout
    String Error Len Close Write Read
    """.split()
    # the last row is Go: ubiquitous fmt.Stringer/error/io method names that
    # must not resolve via the globally-unique fallback (receiver-typed and
    # same-file/import resolution still apply to them)
)

# Order matters when two query patterns capture the same node span.
_KIND_PRIORITY = {
    SymbolKind.METHOD: 3,
    SymbolKind.FUNCTION: 3,
    SymbolKind.CLASS: 2,
    SymbolKind.VARIABLE: 1,
    SymbolKind.CONST: 1,
}

_DEF_CAPTURE_KINDS = {
    "def.function": SymbolKind.FUNCTION,
    "def.class": SymbolKind.CLASS,
    "def.method": SymbolKind.METHOD,
    "def.variable": SymbolKind.VARIABLE,
}


@dataclass(frozen=True)
class SourceFile:
    """One file to index: repo-relative path, git blob hash, and content."""

    path: str
    blob_hash: str
    language: str
    data: bytes


@dataclass(frozen=True)
class _Import:
    module_text: str
    name: Optional[str]  # imported symbol name (from-import / named import)
    alias: Optional[str]


@dataclass(frozen=True)
class _Site:
    name: str
    offset: int
    recv: Optional[str] = None  # Go: selector operand (`x` in `x.Foo()`)


@dataclass
class _FileFacts:
    source: SourceFile
    spec: LanguageSpec
    module: SymbolNode
    defs: list[SymbolNode] = field(default_factory=list)
    imports: list[_Import] = field(default_factory=list)
    calls: list[_Site] = field(default_factory=list)
    refs: list[_Site] = field(default_factory=list)
    local_types: dict[str, str] = field(default_factory=dict)
    """Go: variable name -> locally-evident type (params, `x := T{...}`,
    `var x T`). File-level best-effort, earliest binding wins."""
    method_receiver: dict[int, str] = field(default_factory=dict)
    """Go: method def byte_start -> bare receiver type (`Store`)."""


@lru_cache(maxsize=None)
def _query_source(query_file: str) -> str:
    return (resources.files("codesherpa.graph") / "queries" / query_file).read_text(
        encoding="utf-8"
    )


@lru_cache(maxsize=None)
def _compiled(language_name: str) -> tuple[Language, Query]:
    spec = REGISTRY[language_name]
    language = get_language(language_name)  # type: ignore[arg-type]
    return language, Query(language, _query_source(spec.query_file))


def _text(node, data: bytes) -> str:
    return data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _signature(node, data: bytes) -> str:
    first_line = _text(node, data).split("\n", 1)[0].strip()
    return first_line[:_MAX_SIGNATURE_CHARS]


def _extract_file(source: SourceFile) -> _FileFacts:
    spec = REGISTRY[source.language]
    language, query = _compiled(source.language)
    tree = Parser(language).parse(source.data)

    module = SymbolNode(
        symbol=spec.module_name(source.path),
        kind=SymbolKind.MODULE,
        blob_hash=source.blob_hash,
        byte_start=0,
        byte_end=len(source.data),
        file_path=source.path,
    )
    facts = _FileFacts(source=source, spec=spec, module=module)

    # span -> (kind, name, name_offset); best kind wins on duplicate captures
    raw_defs: dict[tuple[int, int], tuple[SymbolKind, str, int]] = {}
    import_spans: list[tuple[int, int]] = []
    claimed_offsets: set[int] = set()  # def names, call names: not plain refs
    raw_refs: dict[int, str] = {}

    raw_calls: dict[int, _Site] = {}  # name offset -> site; recv-bearing wins
    raw_binds: list[tuple[int, str, str]] = []  # (offset, name, type)

    for _pattern, caps in QueryCursor(query).matches(tree.root_node):
        def_key = next((k for k in _DEF_CAPTURE_KINDS if k in caps), None)
        if def_key is not None:
            def_node = caps[def_key][0]
            name_node = caps["name"][0]
            span = (def_node.start_byte, def_node.end_byte)
            kind = _DEF_CAPTURE_KINDS[def_key]
            existing = raw_defs.get(span)
            if existing is None or _KIND_PRIORITY[kind] > _KIND_PRIORITY[existing[0]]:
                raw_defs[span] = (kind, _text(name_node, source.data), name_node.start_byte)
            claimed_offsets.add(name_node.start_byte)
            recv_nodes = caps.get("method.receiver")
            if recv_nodes:  # Go: methods are keyed with their receiver type
                facts.method_receiver[span[0]] = _text(recv_nodes[0], source.data)
        elif "bind.name" in caps and "bind.type" in caps:
            bind_name = caps["bind.name"][0]
            raw_binds.append(
                (
                    bind_name.start_byte,
                    _text(bind_name, source.data),
                    _text(caps["bind.type"][0], source.data),
                )
            )
        elif "import" in caps:
            node = caps["import"][0]
            import_spans.append((node.start_byte, node.end_byte))
            module_nodes = caps.get("import.module")
            if module_nodes:
                name_nodes = caps.get("import.name")
                alias_nodes = caps.get("import.alias")
                facts.imports.append(
                    _Import(
                        module_text=_text(module_nodes[0], source.data),
                        name=_text(name_nodes[0], source.data) if name_nodes else None,
                        alias=_text(alias_nodes[0], source.data) if alias_nodes else None,
                    )
                )
        elif "call" in caps:
            name_node = caps["call.name"][0]
            recv_nodes = caps.get("call.recv")
            site = _Site(
                _text(name_node, source.data),
                name_node.start_byte,
                recv=_text(recv_nodes[0], source.data) if recv_nodes else None,
            )
            # selector calls match both the recv-bearing and the generic
            # pattern: keep one site per offset, preferring the recv version
            existing_site = raw_calls.get(site.offset)
            if existing_site is None or (site.recv and not existing_site.recv):
                raw_calls[site.offset] = site
            claimed_offsets.add(name_node.start_byte)
        elif "ref" in caps:
            node = caps["ref"][0]
            raw_refs.setdefault(node.start_byte, _text(node, source.data))

    facts.calls.extend(raw_calls[o] for o in sorted(raw_calls))
    for _offset, bind_name, bind_type in sorted(raw_binds):
        facts.local_types.setdefault(bind_name, bind_type.lstrip("*"))

    # Materialize definitions; reclassify functions nested in a class as
    # methods, and SHOUTY top-level variables as consts.
    spans_sorted = sorted(raw_defs, key=lambda s: (s[0], -s[1]))

    def _smallest_container(span: tuple[int, int]) -> Optional[tuple[int, int]]:
        best: Optional[tuple[int, int]] = None
        for other in spans_sorted:
            if other == span:
                continue
            if other[0] <= span[0] and span[1] <= other[1]:
                if best is None or (other[1] - other[0]) < (best[1] - best[0]):
                    best = other
        return best

    for span in spans_sorted:
        kind, name, _offset = raw_defs[span]
        container = _smallest_container(span)
        if kind is SymbolKind.FUNCTION and container is not None:
            if raw_defs[container][0] is SymbolKind.CLASS:
                kind = SymbolKind.METHOD
        if kind is SymbolKind.VARIABLE and _CONST_NAME_RE.match(name):
            kind = SymbolKind.CONST
        node = tree.root_node.descendant_for_byte_range(span[0], span[1])
        facts.defs.append(
            SymbolNode(
                symbol=name,
                kind=kind,
                blob_hash=source.blob_hash,
                byte_start=span[0],
                byte_end=span[1],
                file_path=source.path,
                signature=_signature(node, source.data) if node is not None else None,
            )
        )

    # Keep only references that are not definition names, call sites, or
    # inside import statements; name-vs-definition filtering happens in pass 2.
    for offset in sorted(raw_refs):
        if offset in claimed_offsets:
            continue
        if any(start <= offset < end for start, end in import_spans):
            continue
        facts.refs.append(_Site(raw_refs[offset], offset))

    return facts


# ---------------------------------------------------------------- pass 2


class _Resolver:
    """Best-effort name resolution: same file -> package -> imports -> unique."""

    def __init__(self, all_facts: list[_FileFacts], project_paths: frozenset[str]):
        self.modules: dict[str, SymbolNode] = {f.source.path: f.module for f in all_facts}
        self.by_file: dict[str, dict[str, list[SymbolNode]]] = {}
        self.by_package: dict[tuple[str, str], list[SymbolNode]] = {}
        self.by_name: dict[str, list[SymbolNode]] = {}
        self.project_paths = project_paths
        self.family_by_path: dict[str, str] = {
            f.source.path: _FAMILY[f.source.language] for f in all_facts
        }
        self.by_receiver: dict[tuple[str, str, str], list[SymbolNode]] = {}
        """(family, receiver_type, method_name) -> method defs (Go)."""
        for facts in all_facts:
            per_file = self.by_file.setdefault(facts.source.path, {})
            package = facts.source.path.rpartition("/")[0]
            family = _FAMILY[facts.source.language]
            for node in facts.defs:
                per_file.setdefault(node.symbol, []).append(node)
                self.by_package.setdefault((package, node.symbol), []).append(node)
                self.by_name.setdefault(node.symbol, []).append(node)
                receiver = facts.method_receiver.get(node.byte_start)
                if receiver:
                    self.by_receiver.setdefault(
                        (family, receiver.lstrip("*"), node.symbol), []
                    ).append(node)

    @staticmethod
    def _best(candidates: list[SymbolNode]) -> SymbolNode:
        return min(
            candidates,
            key=lambda n: (n.kind is SymbolKind.METHOD, n.file_path, n.byte_start),
        )

    def resolve_method(
        self, family: str, receiver_type: str, name: str
    ) -> Optional[SymbolNode]:
        """Receiver-typed method resolution (Go): `x.Foo()` where x's type is
        locally evident resolves to the Foo defined on that type. NO
        interface-satisfaction resolution — that needs type checking
        (DECISIONS.md)."""
        candidates = self.by_receiver.get((family, receiver_type, name))
        return self._best(candidates) if candidates else None

    def target_def_in_file(self, path: str, name: str) -> Optional[SymbolNode]:
        candidates = self.by_file.get(path, {}).get(name)
        return self._best(candidates) if candidates else None

    def resolve(
        self, name: str, facts: _FileFacts, bindings: dict[str, SymbolNode]
    ) -> Optional[SymbolNode]:
        local = self.by_file.get(facts.source.path, {}).get(name)
        if local:
            return self._best(local)
        if name in bindings:
            bound = bindings[name]
            if bound.kind is not SymbolKind.MODULE:
                return bound
        if name in _GENERIC_NAMES:
            return None  # too common to resolve without a same-file def or import
        family = _FAMILY[facts.source.language]
        package = facts.source.path.rpartition("/")[0]
        in_package = self.by_package.get((package, name))
        if in_package:
            others = [
                n
                for n in in_package
                if n.file_path != facts.source.path
                and self.family_by_path.get(n.file_path) == family
            ]
            if others:
                return self._best(others)
        everywhere = [
            n
            for n in self.by_name.get(name, [])
            if self.family_by_path.get(n.file_path) == family
        ]
        if len({(n.file_path, n.byte_start) for n in everywhere}) == 1:
            return everywhere[0]
        return None  # ambiguous or unknown: drop, never guess


def _import_bindings(
    facts: _FileFacts, resolver: _Resolver
) -> tuple[dict[str, SymbolNode], list[Edge]]:
    bindings: dict[str, SymbolNode] = {}
    edges: list[Edge] = []
    for imp in facts.imports:
        target_path = facts.spec.resolve_import(
            imp.module_text, facts.source.path, resolver.project_paths
        )
        if target_path is None or target_path not in resolver.modules:
            continue
        target: SymbolNode = resolver.modules[target_path]
        if imp.name is not None:
            named = resolver.target_def_in_file(target_path, imp.name)
            if named is not None:
                target = named
            else:
                # `from pkg import submodule`: the name may be a module itself
                joiner = "" if imp.module_text.endswith(".") else "."
                sub_path = facts.spec.resolve_import(
                    f"{imp.module_text}{joiner}{imp.name}",
                    facts.source.path,
                    resolver.project_paths,
                )
                if sub_path is not None and sub_path in resolver.modules:
                    target = resolver.modules[sub_path]
        if target.node_id != facts.module.node_id:
            edges.append(
                Edge(src=facts.module.node_id, dst=target.node_id, kind=EdgeKind.IMPORTS)
            )
        local_name = imp.alias or imp.name
        if local_name is not None:
            bindings[local_name] = target
    return bindings, edges


def _container(facts: _FileFacts, node: SymbolNode) -> SymbolNode:
    """Smallest definition strictly containing ``node``, else the module."""
    best: Optional[SymbolNode] = None
    for other in facts.defs:
        if (other.byte_start, other.byte_end) == (node.byte_start, node.byte_end):
            continue
        if other.byte_start <= node.byte_start and node.byte_end <= other.byte_end:
            if best is None or (other.byte_end - other.byte_start) < (
                best.byte_end - best.byte_start
            ):
                best = other
    return best if best is not None else facts.module


def _enclosing(facts: _FileFacts, offset: int) -> SymbolNode:
    best: Optional[SymbolNode] = None
    for node in facts.defs:
        if node.byte_start <= offset < node.byte_end:
            if best is None or (node.byte_end - node.byte_start) < (
                best.byte_end - best.byte_start
            ):
                best = node
    return best if best is not None else facts.module


def extract_project(files: Iterable[SourceFile]) -> tuple[list[SymbolNode], list[Edge]]:
    """Extract all symbol nodes and edges for a set of project files.

    Files with unsupported languages are ignored. Returns symbols sorted by
    (path, start, name) and edges sorted by (kind, src, dst), deduplicated.
    """
    sources = sorted(files, key=lambda f: f.path)
    all_facts = [_extract_file(f) for f in sources if f.language in REGISTRY]
    project_paths = frozenset(f.path for f in sources)
    resolver = _Resolver(all_facts, project_paths)

    symbols: list[SymbolNode] = []
    edge_set: dict[tuple[str, str, EdgeKind], Edge] = {}

    def _add_edge(src: SymbolNode, dst: SymbolNode, kind: EdgeKind) -> None:
        if src.node_id == dst.node_id:
            return
        key = (src.node_id, dst.node_id, kind)
        edge_set.setdefault(key, Edge(src=src.node_id, dst=dst.node_id, kind=kind))

    for facts in all_facts:
        symbols.append(facts.module)
        symbols.extend(facts.defs)
        for node in facts.defs:
            _add_edge(_container(facts, node), node, EdgeKind.DEFINES)

        bindings, import_edges = _import_bindings(facts, resolver)
        for edge in import_edges:
            edge_set.setdefault((edge.src, edge.dst, edge.kind), edge)

        for site in facts.calls:
            recv_type = (
                facts.local_types.get(site.recv) if site.recv is not None else None
            )
            if recv_type is not None:
                # The receiver's type is locally evident: resolve against that
                # type's methods ONLY. No match (interface value, external
                # type) -> DROP — type evidence must never be overridden by
                # name guessing (no interface-satisfaction resolution; see
                # DECISIONS.md).
                target = resolver.resolve_method(
                    _FAMILY[facts.source.language], recv_type, site.name
                )
            else:
                target = resolver.resolve(site.name, facts, bindings)
            if target is not None:
                _add_edge(_enclosing(facts, site.offset), target, EdgeKind.CALLS)
        for site in facts.refs:
            target = resolver.resolve(site.name, facts, bindings)
            if target is not None:
                _add_edge(_enclosing(facts, site.offset), target, EdgeKind.REFERENCES)

    symbols.sort(key=lambda n: (n.file_path, n.byte_start, n.symbol))
    edges = sorted(edge_set.values(), key=lambda e: (e.kind, e.src, e.dst))
    return symbols, edges


def extract_file(source: SourceFile) -> list[SymbolNode]:
    """Definitions (plus the module node) for a single file, sorted by start.

    Used by recent-changes symbol diffing; no cross-file resolution.
    """
    if source.language not in REGISTRY:
        return []
    facts = _extract_file(source)
    return sorted([facts.module, *facts.defs], key=lambda n: (n.byte_start, n.symbol))
