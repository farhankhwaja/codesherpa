"""cAST chunker: split-then-merge over the tree-sitter AST (CLAUDE.md §7.2).

Algorithm (cAST, arXiv 2506.15655):

1. Parse the blob. Walk the tree top-down carrying byte *extents*: a node's
   extent runs from its own start to the next sibling's start, so interstitial
   text (blank lines, comments between siblings) stays with the preceding
   node and reassembling all chunks reproduces the blob byte-exactly.
2. A node whose extent holds <= ``max_chunk`` non-whitespace chars is one
   candidate piece.
3. An oversized node is recursed into its children; an oversized leaf (giant
   string / minified line) is hard-split at line boundaries.
4. One greedy left-to-right merge pass glues adjacent small pieces while the
   combined non-whitespace size stays <= ``max_chunk``. Non-whitespace size
   is additive across contiguous extents, so merging never re-scans.
5. Every chunk gets a breadcrumb ``<marker> path :: scope :: signature`` plus
   the first docstring line when the chunk starts at a Python def/class.

6. When the parse contains errors, degrade at DECLARATION granularity rather
   than file granularity (partial-AST salvage, D47): top-level declarations
   whose subtree is error-free keep normal cAST chunks and breadcrumbs, while
   error-tainted extents become non-overlapping line windows flagged
   ``(syntax errors)``. The mixed chunk set is still a byte-exact partition.

Deterministic by construction: pure function of (blob bytes, path, language).
Returns ``None`` when the language has no grammar, the parse blows up, or the
file's structure is too damaged to salvage — the dispatcher then falls back to
line windows for the whole file (§7.2: never crash the indexer).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional

import tree_sitter
import tree_sitter_language_pack as tslp
from tree_sitter import Node

from codesherpa.chunker.fallback import MAX_CHUNK_BYTES, WINDOW_LINES, breadcrumb_marker
from codesherpa.chunker.languages import LANGUAGES, LanguageSpec
from codesherpa.contracts.types import Chunk

logger = logging.getLogger(__name__)

MAX_CHUNK_NONWS = 1600  # non-whitespace chars per chunk (§7.2 default)

MAX_TAINTED_DECL_FRACTION = 0.5
"""Partial-AST salvage gives up past this share of error-tainted top-level nodes.

A single unparseable expression must not cost a file its structure (D47), but a
file whose declaration boundaries are broadly unreliable has nothing worth
salvaging — past this fraction we take the honest wholesale line-window fallback
rather than advertising breadcrumbs derived from a guessed parse.

Counted in DECLARATIONS, not bytes: one 3000-line tainted test function can be
90% of a file's bytes while the 47 declarations around it parse perfectly
(measured on grafana/grafana — see DECISIONS D47). Declaration share measures how
much *structure* the parser lost, which is what salvage actually depends on."""

# Recursion guard: chained-operator expressions (generated/concatenated JS)
# nest one AST level per operator, so an oversized node can be thousands of
# levels deep. Real code structure is exhausted long before this depth; past
# it we degrade to the iterative line-boundary hard split.
MAX_SPLIT_DEPTH = 50

_WHITESPACE = b" \t\r\n\x0b\x0c"

_QUOTE_PREFIX_RE = re.compile(r"^[rbuRBU]{0,3}(\"\"\"|'''|\"|')")
_QUOTE_SUFFIX_RE = re.compile(r"(\"\"\"|'''|\"|')$")

_parsers: dict[str, tree_sitter.Parser] = {}


def _parser_for(grammar: str) -> tree_sitter.Parser:
    parser = _parsers.get(grammar)
    if parser is None:
        # NOTE: tslp.get_parser() returns a Rust-API parser in >=1.12; only
        # get_language() composes with the standard tree_sitter.Parser API.
        parser = tree_sitter.Parser(tslp.get_language(grammar))
        _parsers[grammar] = parser
    return parser


def _nonws(data: bytes, start: int, end: int) -> int:
    return len(data[start:end].translate(None, _WHITESPACE))


@dataclass
class _Piece:
    """A contiguous byte extent plus breadcrumb context. Sizes are additive:
    merging two adjacent pieces costs no re-scan."""

    start: int
    end: int
    size: int  # non-whitespace chars in [start, end)
    scope: tuple[str, ...]
    head: Optional[Node]  # first AST node in the piece, for signature/docstring
    tainted: bool = False
    """This extent sits inside a subtree containing ERROR/MISSING nodes, so its
    parse is untrustworthy: it is line-windowed and breadcrumbed as such."""


def _receiver_type(method_node: Node) -> Optional[str]:
    """Bare receiver type of a Go ``method_declaration`` (pointer stripped):
    ``func (s *Store) Save(...)`` -> ``Store``."""
    receiver = method_node.child_by_field_name("receiver")
    if receiver is None:
        return None
    for param in receiver.children:
        if param.type != "parameter_declaration":
            continue
        type_node = param.child_by_field_name("type")
        if type_node is None or type_node.text is None:
            continue
        text = type_node.text.decode("utf-8", errors="replace").lstrip("*").strip()
        return text.split("[", 1)[0].strip()  # Pair[K, V] -> Pair
    return None


def _node_name(node: Node) -> str:
    if node.type == "method_declaration":  # Go: breadcrumb scope is the receiver
        receiver = _receiver_type(node)
        if receiver:
            return f"({receiver})"
    name = node.child_by_field_name("name")
    if name is not None and name.text is not None:
        return name.text.decode("utf-8", errors="replace")
    # grammars without name FIELDS (proto: message_name/service_name/enum_name
    # children) — take the first *_name child's text
    for child in node.children:
        if child.type.endswith("_name") and child.text is not None:
            return child.text.decode("utf-8", errors="replace")
    return node.type


def _split(
    node: Node,
    start: int,
    end: int,
    scope: tuple[str, ...],
    data: bytes,
    spec: LanguageSpec,
    max_chunk: int,
    depth: int = 0,
) -> list[_Piece]:
    size = _nonws(data, start, end)
    if size <= max_chunk:
        return [_Piece(start, end, size, scope, node)]

    children = node.children
    if not children or depth >= MAX_SPLIT_DEPTH:
        return _hard_split(node, start, end, scope, data, max_chunk)

    child_scope = scope
    if node.type in spec.scope_types:
        child_scope = scope + (_node_name(node),)

    # Extents: child i runs to child i+1's start; interstitial text stays
    # with the preceding child. First child inherits leading trivia, last
    # child inherits trailing trivia.
    pieces: list[_Piece] = []
    for i, child in enumerate(children):
        ext_start = start if i == 0 else children[i].start_byte
        ext_end = children[i + 1].start_byte if i + 1 < len(children) else end
        if ext_start >= ext_end:
            continue  # zero-width token extent swallowed by a neighbor
        pieces.extend(
            _split(child, ext_start, ext_end, child_scope, data, spec, max_chunk, depth + 1)
        )
    return pieces


def _hard_split(
    node: Node,
    start: int,
    end: int,
    scope: tuple[str, ...],
    data: bytes,
    max_chunk: int,
) -> list[_Piece]:
    """Oversized leaf (giant string, minified line): split at line starts,
    and as a last resort mid-line every ``max_chunk`` bytes (a byte run of
    length N has at most N non-whitespace chars)."""
    boundaries: list[int] = [start]
    pos = data.find(b"\n", start, end)
    while pos != -1 and pos + 1 < end:
        boundaries.append(pos + 1)
        pos = data.find(b"\n", pos + 1, end)
    boundaries.append(end)

    pieces: list[_Piece] = []
    for i in range(len(boundaries) - 1):
        seg_start, seg_end = boundaries[i], boundaries[i + 1]
        while seg_end - seg_start > max_chunk:
            cut = seg_start + max_chunk
            pieces.append(_Piece(seg_start, cut, _nonws(data, seg_start, cut), scope, node))
            seg_start = cut
        if seg_start < seg_end:
            pieces.append(_Piece(seg_start, seg_end, _nonws(data, seg_start, seg_end), scope, node))
    return pieces


def _merge(pieces: list[_Piece], max_chunk: int) -> list[_Piece]:
    merged: list[_Piece] = []
    for piece in pieces:
        last = merged[-1] if merged else None
        if (
            last is not None
            and last.end == piece.start
            and last.size + piece.size <= max_chunk
            # never glue a trustworthy chunk to an error-tainted one: the
            # merged chunk would inherit one of the two breadcrumbs and lie
            # about the other half's provenance
            and not last.tainted
            and not piece.tainted
        ):
            last.end = piece.end
            last.size += piece.size
        else:
            merged.append(
                _Piece(
                    piece.start, piece.end, piece.size, piece.scope, piece.head, piece.tainted
                )
            )
    return merged


def _line_window_pieces(
    start: int,
    end: int,
    scope: tuple[str, ...],
    data: bytes,
) -> list[_Piece]:
    """Cover ``[start, end)`` with line-window pieces, as the fallback chunker
    does — but as a strict PARTITION.

    ``fallback.chunk_lines`` overlaps its windows by ``OVERLAP_LINES``, which is
    fine when it owns the whole blob. Here the windows are interleaved with real
    cAST chunks, and §7.2's reassembly invariant (chunks of a blob rejoin into
    the original bytes) requires contiguous, non-overlapping extents — so the
    salvage path drops the overlap. Windows are additionally capped at
    ``MAX_CHUNK_BYTES`` so one enormous line cannot reach the embedder (D38)."""
    boundaries: list[int] = [start]
    pos = data.find(b"\n", start, end)
    while pos != -1 and pos + 1 < end:
        boundaries.append(pos + 1)
        pos = data.find(b"\n", pos + 1, end)
    boundaries.append(end)

    pieces: list[_Piece] = []
    for i in range(0, len(boundaries) - 1, WINDOW_LINES):
        win_start = boundaries[i]
        win_end = boundaries[min(i + WINDOW_LINES, len(boundaries) - 1)]
        for seg_start in range(win_start, win_end, MAX_CHUNK_BYTES):
            seg_end = min(seg_start + MAX_CHUNK_BYTES, win_end)
            pieces.append(
                _Piece(
                    seg_start,
                    seg_end,
                    _nonws(data, seg_start, seg_end),
                    scope,
                    None,
                    tainted=True,
                )
            )
    return pieces


def _child_extents(node: Node, start: int, end: int) -> list[tuple[Node, int, int]]:
    """``node``'s children paired with their byte extents, using the same rule
    as ``_split``: child *i* runs to child *i+1*'s start, so interstitial text
    stays with the preceding child and the extents partition ``[start, end)``."""
    children = node.children
    extents: list[tuple[Node, int, int]] = []
    for i, child in enumerate(children):
        ext_start = start if i == 0 else children[i].start_byte
        ext_end = children[i + 1].start_byte if i + 1 < len(children) else end
        if ext_start < ext_end:
            extents.append((child, ext_start, ext_end))
    return extents


def _salvage(
    root: Node,
    data: bytes,
    spec: LanguageSpec,
    max_chunk: int,
) -> Optional[list[_Piece]]:
    """Partial-AST salvage for a file whose parse contains errors (D47).

    Degrades at DECLARATION granularity instead of file granularity: top-level
    declarations whose subtree is error-free keep normal cAST chunking, while
    error-tainted extents become line windows. Returns ``None`` when the file is
    genuinely hopeless and the caller should fall back wholesale."""
    extents = _child_extents(root, 0, len(data))
    if not extents:
        return None

    # An ERROR/MISSING node directly under root means the top-level structure
    # itself did not parse: the declaration boundaries we would salvage against
    # are not trustworthy. (Measured on grafana/grafana: this never happens for
    # the nested-expression grammar gaps this feature targets.)
    if any(child.is_error or child.is_missing for child, _, _ in extents):
        return None

    tainted = sum(1 for child, _, _ in extents if child.has_error)
    if tainted / len(extents) > MAX_TAINTED_DECL_FRACTION:
        return None
    # nothing structural left to keep
    if not any(
        not child.has_error and child.type in spec.definition_types for child, _, _ in extents
    ):
        return None

    pieces: list[_Piece] = []
    for child, ext_start, ext_end in extents:
        if child.has_error:
            scope = (_node_name(child),) if child.type in spec.scope_types else ()
            pieces.extend(_line_window_pieces(ext_start, ext_end, scope, data))
        else:
            pieces.extend(_split(child, ext_start, ext_end, (), data, spec, max_chunk))
    return pieces


def _descend_to_definition(head: Node, spec: LanguageSpec) -> Node:
    """A merged chunk's head may be a container (module, block, export) whose
    extent starts exactly at a definition — descend to it for the docstring."""
    node = head
    while node.type not in spec.definition_types:
        child = next((c for c in node.children if c.start_byte == node.start_byte), None)
        if child is None:
            break
        node = child
    return node


def _first_docstring_line(head: Node, spec: LanguageSpec) -> Optional[str]:
    """First line of a Python def/class docstring, if the chunk starts there."""
    if head is None:
        return None
    head = _descend_to_definition(head, spec)
    if head.type not in ("class_definition", "function_definition"):
        return None
    body = head.child_by_field_name("body")
    if body is None or not body.children:
        return None
    stmt = body.children[0]
    # docstrings appear as a bare `string` or wrapped in `expression_statement`,
    # depending on grammar version
    if stmt.type == "expression_statement" and stmt.children:
        stmt = stmt.children[0]
    literal = stmt
    if literal.type != "string" or literal.text is None:
        return None
    text = literal.text.decode("utf-8", errors="replace")
    text = _QUOTE_PREFIX_RE.sub("", text)
    text = _QUOTE_SUFFIX_RE.sub("", text)
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _tainted_breadcrumb(piece: _Piece, data: bytes, file_path: str, language: str) -> str:
    """Line-window-shaped breadcrumb for a salvaged file's unparseable extent.
    Says so explicitly: a consumer must not read it as a verified signature."""
    marker = breadcrumb_marker(language)
    scope = ".".join(piece.scope) if piece.scope else PurePosixPath(file_path).stem
    first = data.count(b"\n", 0, piece.start) + 1
    last = data.count(b"\n", 0, max(piece.start, piece.end - 1)) + 1
    return f"{marker} {file_path} :: {scope} :: L{first}-{last} (syntax errors)"


def _breadcrumb(
    piece: _Piece,
    code: str,
    file_path: str,
    language: str,
    spec: LanguageSpec,
) -> str:
    marker = breadcrumb_marker(language)

    def _qualify(label: str) -> str:
        """Go receiver labels carry the package (D45): `(Store)` is the same
        label in every package of a big monorepo — convention receivers
        repeat dozens of times; `(goexport.Store)` disambiguates the
        lexical/dense signal."""
        if language != "go" or not (label.startswith("(") and label.endswith(")")):
            return label
        package = PurePosixPath(file_path).parent.name
        inner = label[1:-1]
        if not package or "." in inner:
            return label
        return f"({package}.{inner})"

    scope = (
        ".".join(_qualify(part) for part in piece.scope)
        if piece.scope
        else PurePosixPath(file_path).stem
    )
    if not piece.scope and piece.head is not None:
        # Go methods are TOP-LEVEL declarations (unlike class methods, which
        # inherit a scope by recursion), so a small method chunk would carry
        # only the file stem — surface the receiver instead:
        # `path :: (pkg.ReceiverType) :: func (s *ReceiverType) Name(...)`
        head = _descend_to_definition(piece.head, spec)
        if head.type == "method_declaration":
            receiver = _receiver_type(head)
            if receiver:
                scope = _qualify(f"({receiver})")
    signature = next((ln.strip() for ln in code.splitlines() if ln.strip()), "")
    if len(signature) > 120:
        signature = signature[:117] + "..."
    crumb = f"{marker} {file_path} :: {scope} :: {signature}"
    doc = _first_docstring_line(piece.head, spec) if piece.head is not None else None
    if doc and doc not in signature:
        crumb += f" — {doc}"
    return crumb


def chunk_ast(
    blob_hash: str,
    data: bytes,
    file_path: str,
    language: str,
    max_chunk: int = MAX_CHUNK_NONWS,
) -> Optional[list[Chunk]]:
    """cAST-chunk one blob; ``None`` means "use the line-window fallback"."""
    spec = LANGUAGES.get(language)
    if spec is None or not data:
        return None if spec is None else []
    try:
        tree = _parser_for(spec.grammar).parse(data)
    except Exception as exc:  # grammar load/parse blow-up: never crash the indexer
        logger.warning("cAST parse failed for %s (%s): %r", file_path, language, exc)
        return None
    root = tree.root_node

    try:
        if root.has_error:
            # Partial-AST salvage (D47): keep the declarations that DID parse
            # instead of throwing the whole file's structure away.
            raw = _salvage(root, data, spec, max_chunk)
            if raw is None:
                logger.warning(
                    "cAST: syntax errors in %s (%s); falling back to line windows",
                    file_path,
                    language,
                )
                return None
            logger.warning(
                "cAST: syntax errors in %s (%s); salvaged %d/%d top-level declarations",
                file_path,
                language,
                sum(1 for c, _, _ in _child_extents(root, 0, len(data)) if not c.has_error),
                len(_child_extents(root, 0, len(data))),
            )
        else:
            raw = _split(root, 0, len(data), (), data, spec, max_chunk)

        pieces = _merge(raw, max_chunk)
        chunks: list[Chunk] = []
        for piece in pieces:
            code = data[piece.start : piece.end].decode("utf-8", errors="replace")
            crumb = (
                _tainted_breadcrumb(piece, data, file_path, language)
                if piece.tainted
                else _breadcrumb(piece, code, file_path, language, spec)
            )
            chunks.append(
                Chunk(
                    blob_hash=blob_hash,
                    byte_start=piece.start,
                    byte_end=piece.end,
                    file_path=file_path,
                    language=language,
                    code=code,
                    breadcrumb=crumb,
                )
            )
        return chunks
    except Exception as exc:  # §7.2: never crash the indexer on a weird file
        logger.warning(
            "cAST chunking failed for %s (%s): %r; falling back to line windows",
            file_path,
            language,
            exc,
        )
        return None
