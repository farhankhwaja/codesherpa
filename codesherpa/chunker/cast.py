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

Deterministic by construction: pure function of (blob bytes, path, language).
Returns ``None`` when the language has no grammar or the parse errors — the
dispatcher then falls back to line windows (§7.2: never crash the indexer).
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

from codesherpa.chunker.fallback import breadcrumb_marker
from codesherpa.chunker.languages import LANGUAGES, LanguageSpec
from codesherpa.contracts.types import Chunk

logger = logging.getLogger(__name__)

MAX_CHUNK_NONWS = 1600  # non-whitespace chars per chunk (§7.2 default)

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
        if last is not None and last.end == piece.start and last.size + piece.size <= max_chunk:
            last.end = piece.end
            last.size += piece.size
        else:
            merged.append(_Piece(piece.start, piece.end, piece.size, piece.scope, piece.head))
    return merged


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


def _breadcrumb(
    piece: _Piece,
    code: str,
    file_path: str,
    language: str,
    spec: LanguageSpec,
) -> str:
    marker = breadcrumb_marker(language)
    scope = ".".join(piece.scope) if piece.scope else PurePosixPath(file_path).stem
    if not piece.scope and piece.head is not None:
        # Go methods are TOP-LEVEL declarations (unlike class methods, which
        # inherit a scope by recursion), so a small method chunk would carry
        # only the file stem — surface the receiver instead:
        # `path :: (ReceiverType) :: func (s *ReceiverType) Name(...)`
        head = _descend_to_definition(piece.head, spec)
        if head.type == "method_declaration":
            receiver = _receiver_type(head)
            if receiver:
                scope = f"({receiver})"
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
    if root.has_error:
        logger.warning(
            "cAST: syntax errors in %s (%s); falling back to line windows",
            file_path,
            language,
        )
        return None

    try:
        pieces = _merge(_split(root, 0, len(data), (), data, spec, max_chunk), max_chunk)
        chunks: list[Chunk] = []
        for piece in pieces:
            code = data[piece.start : piece.end].decode("utf-8", errors="replace")
            chunks.append(
                Chunk(
                    blob_hash=blob_hash,
                    byte_start=piece.start,
                    byte_end=piece.end,
                    file_path=file_path,
                    language=language,
                    code=code,
                    breadcrumb=_breadcrumb(piece, code, file_path, language, spec),
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
