"""FROZEN IndexStore contract (CLAUDE.md §2.2 — do not edit after Phase 0).

The store is one SQLite file at ``.sherpa/index.db`` holding blobs, file
mappings, chunks (+ FTS5), symbols, edges, and the embedding cache. Everything
is keyed by git blob hash. Deactivation is soft: rows for blobs no longer
reachable from any indexed ref are marked inactive, never deleted, so branch
switching stays cheap.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from typing import Optional

from codesherpa.contracts.types import Chunk, Edge, EdgeKind, SymbolNode


class IndexStore(ABC):
    """Storage interface implemented by ``codesherpa.store`` (Phase 1).

    Retrieval (Phase 3) and graph/MCP (Phase 4) code must depend on this ABC,
    never on the concrete SQLite implementation.
    """

    # ------------------------------------------------------------------ blobs

    @abstractmethod
    def add_blob(self, blob_hash: str, language: str, size_bytes: int) -> None:
        """Register a blob as indexed and active. Idempotent."""

    @abstractmethod
    def has_blob(self, blob_hash: str) -> bool:
        """True if the blob has ever been indexed (active or not)."""

    @abstractmethod
    def active_blobs(self) -> set[str]:
        """All blob hashes currently marked active."""

    @abstractmethod
    def set_blobs_active(self, blob_hashes: Iterable[str], active: bool) -> None:
        """Soft-activate / soft-deactivate blobs. Never deletes rows."""

    # ------------------------------------------------------------------ files

    @abstractmethod
    def map_files(self, ref: str, path_to_blob: dict[str, str]) -> None:
        """Replace the path -> blob mapping for ``ref`` (e.g. ``HEAD``)."""

    @abstractmethod
    def files_for_ref(self, ref: str) -> dict[str, str]:
        """Current path -> blob mapping recorded for ``ref``."""

    # ----------------------------------------------------------------- chunks

    @abstractmethod
    def add_chunks(self, chunks: Sequence[Chunk]) -> None:
        """Store chunks (and their FTS5 rows). Idempotent per chunk_id."""

    @abstractmethod
    def get_chunk(self, chunk_id: str) -> Optional[Chunk]:
        """Look up one chunk by ``blob_hash:byte_start:byte_end``."""

    @abstractmethod
    def chunks_for_blob(self, blob_hash: str) -> list[Chunk]:
        """All chunks of a blob, ordered by byte_start."""

    # ---------------------------------------------------------------- symbols

    @abstractmethod
    def add_symbols(self, symbols: Sequence[SymbolNode]) -> None:
        """Store symbol nodes. Idempotent per node_id."""

    @abstractmethod
    def add_edges(self, edges: Sequence[Edge]) -> None:
        """Store graph edges. Idempotent per (src, dst, kind)."""

    @abstractmethod
    def get_definitions(self, symbol: str) -> list[SymbolNode]:
        """Exact-name definition lookup across active blobs."""

    @abstractmethod
    def get_edges(
        self,
        node_id: str,
        kind: Optional[EdgeKind] = None,
        incoming: bool = False,
    ) -> list[Edge]:
        """Edges touching ``node_id``; outgoing by default, filtered by kind."""

    # ------------------------------------------------------------- embeddings

    @abstractmethod
    def get_embedding(self, chunk_id: str) -> Optional[list[float]]:
        """Cached embedding for a chunk, if ever computed (cache is permanent)."""

    @abstractmethod
    def put_embedding(self, chunk_id: str, vector: Sequence[float], model: str) -> None:
        """Cache a normalized embedding vector for a chunk."""

    # ---------------------------------------------------------------- queries

    @abstractmethod
    def fts_search(self, query: str, limit: int = 100) -> list[tuple[str, float]]:
        """FTS5/BM25 over active chunks -> [(chunk_id, score)] descending."""

    @abstractmethod
    def vector_search(self, vector: Sequence[float], limit: int = 100) -> list[tuple[str, float]]:
        """Dense similarity over active chunks -> [(chunk_id, score)] descending."""

    @abstractmethod
    def symbol_search(self, name: str, limit: int = 20) -> list[SymbolNode]:
        """Fuzzy symbol-name match over active blobs, best first."""

    # ------------------------------------------------------------------- meta

    @abstractmethod
    def get_meta(self, key: str) -> Optional[str]:
        """Read a metadata value (schema version, last sync, model name, ...)."""

    @abstractmethod
    def set_meta(self, key: str, value: str) -> None:
        """Write a metadata value."""
