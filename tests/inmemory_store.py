"""In-memory IndexStore test double + fixture population helper.

Lives in tests/ per CLAUDE.md §2.5 (mocks never ship in production paths) and
§8 (graph-mcp builds against the contracts with a mocked index until the real
SQLite store from core-index merges). It is a faithful, if naive,
implementation of the contract: it only ever returns what was stored.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional, Sequence

from repograph.contracts.index_contract import IndexStore
from repograph.contracts.types import Chunk, Edge, EdgeKind, SymbolKind, SymbolNode
from repograph.graph.extract import SourceFile, extract_project
from repograph.graph.gitio import source_files_at_rev

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


class InMemoryIndexStore(IndexStore):
    def __init__(self) -> None:
        self._blobs: dict[str, dict] = {}
        self._files: dict[str, dict[str, str]] = {}
        self._chunks: dict[str, Chunk] = {}
        self._chunks_by_blob: dict[str, list[Chunk]] = defaultdict(list)
        self._symbols: dict[str, SymbolNode] = {}
        self._by_name: dict[str, list[str]] = defaultdict(list)
        self._edges: dict[tuple[str, str, EdgeKind], Edge] = {}
        self._embeddings: dict[str, tuple[list[float], str]] = {}
        self._meta: dict[str, str] = {}

    # blobs
    def add_blob(self, blob_hash: str, language: str, size_bytes: int) -> None:
        self._blobs.setdefault(
            blob_hash, {"language": language, "size": size_bytes, "active": True}
        )["active"] = True

    def has_blob(self, blob_hash: str) -> bool:
        return blob_hash in self._blobs

    def active_blobs(self) -> set[str]:
        return {b for b, row in self._blobs.items() if row["active"]}

    def set_blobs_active(self, blob_hashes: Iterable[str], active: bool) -> None:
        for blob in blob_hashes:
            if blob in self._blobs:
                self._blobs[blob]["active"] = active

    # files
    def map_files(self, ref: str, path_to_blob: dict[str, str]) -> None:
        self._files[ref] = dict(path_to_blob)

    def files_for_ref(self, ref: str) -> dict[str, str]:
        return dict(self._files.get(ref, {}))

    # chunks
    def add_chunks(self, chunks: Sequence[Chunk]) -> None:
        for chunk in chunks:
            if chunk.chunk_id not in self._chunks:
                self._chunks[chunk.chunk_id] = chunk
                self._chunks_by_blob[chunk.blob_hash].append(chunk)

    def get_chunk(self, chunk_id: str) -> Optional[Chunk]:
        return self._chunks.get(chunk_id)

    def chunks_for_blob(self, blob_hash: str) -> list[Chunk]:
        return sorted(self._chunks_by_blob.get(blob_hash, []), key=lambda c: c.byte_start)

    # symbols
    def add_symbols(self, symbols: Sequence[SymbolNode]) -> None:
        for node in symbols:
            if node.node_id not in self._symbols:
                self._symbols[node.node_id] = node
                self._by_name[node.symbol].append(node.node_id)

    def add_edges(self, edges: Sequence[Edge]) -> None:
        for edge in edges:
            self._edges.setdefault((edge.src, edge.dst, edge.kind), edge)

    def get_definitions(self, symbol: str) -> list[SymbolNode]:
        active = self.active_blobs()
        return [
            self._symbols[node_id]
            for node_id in self._by_name.get(symbol, [])
            if self._symbols[node_id].blob_hash in active
        ]

    def get_edges(
        self, node_id: str, kind: Optional[EdgeKind] = None, incoming: bool = False
    ) -> list[Edge]:
        found = []
        for (src, dst, edge_kind), edge in sorted(self._edges.items()):
            if kind is not None and edge_kind is not kind:
                continue
            if (dst if incoming else src) == node_id:
                found.append(edge)
        return found

    # embeddings
    def get_embedding(self, chunk_id: str) -> Optional[list[float]]:
        row = self._embeddings.get(chunk_id)
        return row[0] if row else None

    def put_embedding(self, chunk_id: str, vector: Sequence[float], model: str) -> None:
        self._embeddings[chunk_id] = (list(vector), model)

    # queries
    def fts_search(self, query: str, limit: int = 100) -> list[tuple[str, float]]:
        terms = [t.lower() for t in _TOKEN_RE.findall(query)]
        active = self.active_blobs()
        scored = []
        for chunk_id, chunk in self._chunks.items():
            if chunk.blob_hash not in active:
                continue
            text = f"{chunk.breadcrumb}\n{chunk.code}".lower()
            score = float(sum(text.count(term) for term in terms))
            if score > 0:
                scored.append((chunk_id, score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:limit]

    def vector_search(self, vector: Sequence[float], limit: int = 100) -> list[tuple[str, float]]:
        active = self.active_blobs()
        scored = []
        for chunk_id, (stored, _model) in self._embeddings.items():
            chunk = self._chunks.get(chunk_id)
            if chunk is None or chunk.blob_hash not in active:
                continue
            score = sum(a * b for a, b in zip(vector, stored))
            scored.append((chunk_id, float(score)))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:limit]

    def symbol_search(self, name: str, limit: int = 20) -> list[SymbolNode]:
        lowered = name.lower()
        active = self.active_blobs()
        scored = []
        for symbol, node_ids in self._by_name.items():
            candidate = symbol.lower()
            if candidate == lowered:
                score = 3.0
            elif candidate.startswith(lowered) or lowered.startswith(candidate):
                score = 2.0
            elif lowered in candidate or candidate in lowered:
                score = 1.0
            else:
                continue
            for node_id in node_ids:
                node = self._symbols[node_id]
                if node.blob_hash in active:
                    scored.append((score, node))
        scored.sort(key=lambda item: (-item[0], item[1].file_path, item[1].byte_start))
        return [node for _score, node in scored[:limit]]

    # meta
    def get_meta(self, key: str) -> Optional[str]:
        return self._meta.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self._meta[key] = value


def _breadcrumb(source_path: str, node: SymbolNode, container: Optional[SymbolNode]) -> str:
    scope = container.symbol if container is not None else source_path
    return f"# {source_path} :: {scope} :: {node.signature or node.symbol}"


def populate_store(store: InMemoryIndexStore, repo_path: Path, ref: str = "HEAD") -> None:
    """Index a fixture repo into the store: blobs, per-definition chunks,

    symbols, and edges — everything the graph and MCP layers need.
    """
    files = source_files_at_rev(repo_path, ref)
    symbols, edges = extract_project(files)
    store.map_files(ref, {f.path: f.blob_hash for f in files})

    by_blob: dict[str, list[SymbolNode]] = defaultdict(list)
    for node in symbols:
        by_blob[node.blob_hash].append(node)

    for source in files:
        store.add_blob(source.blob_hash, source.language, len(source.data))
        chunks = []
        defs = [n for n in by_blob[source.blob_hash] if n.kind is not SymbolKind.MODULE]
        for node in defs:
            container = None
            for other in defs:
                if other is node:
                    continue
                if other.byte_start <= node.byte_start and node.byte_end <= other.byte_end:
                    if container is None or (other.byte_end - other.byte_start) < (
                        container.byte_end - container.byte_start
                    ):
                        container = other
            chunks.append(
                Chunk(
                    blob_hash=source.blob_hash,
                    byte_start=node.byte_start,
                    byte_end=node.byte_end,
                    file_path=source.path,
                    language=source.language,
                    code=source.data[node.byte_start : node.byte_end].decode(
                        "utf-8", errors="replace"
                    ),
                    breadcrumb=_breadcrumb(source.path, node, container),
                )
            )
        if not defs:  # e.g. docstring-only __init__.py: whole-file chunk
            chunks.append(
                Chunk(
                    blob_hash=source.blob_hash,
                    byte_start=0,
                    byte_end=len(source.data),
                    file_path=source.path,
                    language=source.language,
                    code=source.data.decode("utf-8", errors="replace"),
                    breadcrumb=f"# {source.path}",
                )
            )
        store.add_chunks(chunks)

    store.add_symbols(symbols)
    store.add_edges(edges)
    store.set_meta("last_sync_ref", ref)
