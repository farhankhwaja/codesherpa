"""FROZEN shared types for repograph (CLAUDE.md §2.2 — do not edit after Phase 0).

Every index entry is keyed by git blob hash (content-addressed), so pulls,
rebases, and branch switches only pay for genuinely new blobs. Chunk identity
is ``(blob_hash, byte_start, byte_end)`` and must be deterministic: the same
blob always yields the same chunk set.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SymbolKind(str, Enum):
    """Kind of a definition node in the symbol graph."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    CONST = "const"
    VARIABLE = "variable"
    MODULE = "module"


class EdgeKind(str, Enum):
    """Kind of an edge in the symbol graph (CLAUDE.md §7.3)."""

    CALLS = "calls"
    IMPORTS = "imports"
    REFERENCES = "references"
    DEFINES = "defines"


class RetrievalSource(str, Enum):
    """Why a chunk was included in a search response (CLAUDE.md §7.5.6)."""

    BM25 = "bm25"
    VECTOR = "vector"
    SYMBOL = "symbol"
    EXPANSION = "expansion"


@dataclass(frozen=True)
class Chunk:
    """A structure-aware chunk of one file blob.

    ``code`` is the exact byte slice ``blob[byte_start:byte_end]`` decoded as
    UTF-8 (errors replaced); reassembling all chunks of a blob in byte order
    must reproduce the original bytes. ``breadcrumb`` is the header prepended
    for embedding/display (``path :: enclosing scope :: signature``) and is
    stored separately from the raw code.
    """

    blob_hash: str
    """Git blob SHA-1/SHA-256 hex of the file content this chunk came from."""

    byte_start: int
    """Inclusive byte offset of the chunk within the blob."""

    byte_end: int
    """Exclusive byte offset of the chunk within the blob."""

    file_path: str
    """A repo-relative path this blob is reachable at (display / breadcrumbs)."""

    language: str
    """Language identifier, e.g. ``python``, ``typescript``, ``javascript``, ``tsx``."""

    code: str
    """Raw chunk text: exactly the blob bytes in [byte_start, byte_end)."""

    breadcrumb: str
    """Header used for embedding and display, never part of ``code``."""

    @property
    def chunk_id(self) -> str:
        """Stable identity: ``blob_hash:byte_start:byte_end``."""
        return f"{self.blob_hash}:{self.byte_start}:{self.byte_end}"


@dataclass(frozen=True)
class SymbolNode:
    """A definition (or reference site) in the symbol graph (CLAUDE.md §7.3)."""

    symbol: str
    """Bare symbol name, e.g. ``retry_request`` or ``TaskStore``."""

    kind: SymbolKind

    blob_hash: str
    """Blob the node lives in (content-addressed, like chunks)."""

    byte_start: int
    byte_end: int

    file_path: str
    """Repo-relative path the blob is reachable at."""

    signature: Optional[str] = None
    """Best-effort signature line, e.g. ``def retry_request(url, attempts=3)``."""

    @property
    def node_id(self) -> str:
        """Stable identity: ``blob_hash:byte_start:byte_end:symbol``."""
        return f"{self.blob_hash}:{self.byte_start}:{self.byte_end}:{self.symbol}"


@dataclass(frozen=True)
class Edge:
    """A directed edge between two symbol nodes.

    ``src`` and ``dst`` are ``SymbolNode.node_id`` values. Call edges use
    best-effort name resolution only (same file -> same package -> imports);
    no type inference.
    """

    src: str
    dst: str
    kind: EdgeKind


@dataclass(frozen=True)
class SearchResult:
    """One scored chunk in a retrieval response."""

    chunk: Chunk

    score: float
    """Final score after fusion/rerank/expansion discounts. Higher is better."""

    source: RetrievalSource
    """Why this chunk was included (bm25 | vector | symbol | expansion)."""

    expand_id: str
    """Opaque handle usable with ``Retriever.expand`` / the MCP ``expand`` tool."""

    token_count: int
    """Estimated token cost of this result as packed (breadcrumb + code)."""

    rationale: Optional[str] = None
    """Optional human/agent-readable ranking rationale (e.g. for get_callers)."""


@dataclass(frozen=True)
class PackedContext:
    """Budget-aware packed response for a search query (CLAUDE.md §7.5.6).

    ``total_tokens`` must never exceed ``budget_tokens``. Results are ordered
    by descending usefulness (greedy score / token_count packing), already
    deduplicated across overlapping byte ranges and same-symbol chunks.
    """

    query: str
    budget_tokens: int
    total_tokens: int
    results: tuple[SearchResult, ...]
