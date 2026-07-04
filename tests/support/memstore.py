"""In-memory IndexStore for retrieval tests (CLAUDE.md §8: mocked store until
core-index merges; §2.5: mocks live only in tests/).

Implements the full frozen contract with a pure-Python Okapi BM25 for
``fts_search``, brute-force cosine for ``vector_search``, and difflib-based
fuzzy matching for ``symbol_search``. Small and slow but faithful: results
only cover chunks/symbols of *active* blobs, mirroring the real store.
"""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Iterable, Sequence
from typing import Optional

from repograph.contracts.index_contract import IndexStore
from repograph.contracts.types import Chunk, Edge, EdgeKind, SymbolNode
from repograph.retrieve.router import split_identifier

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")

# BM25 constants (standard Okapi defaults)
_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> list[str]:
    """Code-aware tokens: each identifier plus its snake/camel word parts."""
    out: list[str] = []
    for raw in _WORD_RE.findall(text):
        lower = raw.lower()
        out.append(lower)
        parts = split_identifier(raw)
        if len(parts) > 1:
            out.extend(parts)
    return out


class InMemoryIndexStore(IndexStore):
    def __init__(self) -> None:
        self._blobs: dict[str, dict] = {}  # hash -> {language, size, active}
        self._files: dict[str, dict[str, str]] = {}  # ref -> {path: blob}
        self._chunks: dict[str, Chunk] = {}
        self._chunks_by_blob: dict[str, list[str]] = {}
        self._symbols: dict[str, SymbolNode] = {}
        self._symbols_by_name: dict[str, list[str]] = {}
        self._edges: list[Edge] = []
        self._edge_keys: set[tuple[str, str, EdgeKind]] = set()
        self._embeddings: dict[str, tuple[list[float], str]] = {}
        self._meta: dict[str, str] = {}

    # ------------------------------------------------------------------ blobs

    def add_blob(self, blob_hash: str, language: str, size_bytes: int) -> None:
        self._blobs[blob_hash] = {
            "language": language,
            "size": size_bytes,
            "active": True,
        }

    def has_blob(self, blob_hash: str) -> bool:
        return blob_hash in self._blobs

    def active_blobs(self) -> set[str]:
        return {h for h, row in self._blobs.items() if row["active"]}

    def set_blobs_active(self, blob_hashes: Iterable[str], active: bool) -> None:
        for h in blob_hashes:
            if h in self._blobs:
                self._blobs[h]["active"] = active

    def _is_active(self, blob_hash: str) -> bool:
        row = self._blobs.get(blob_hash)
        return bool(row and row["active"])

    # ------------------------------------------------------------------ files

    def map_files(self, ref: str, path_to_blob: dict[str, str]) -> None:
        self._files[ref] = dict(path_to_blob)

    def files_for_ref(self, ref: str) -> dict[str, str]:
        return dict(self._files.get(ref, {}))

    # ----------------------------------------------------------------- chunks

    def add_chunks(self, chunks: Sequence[Chunk]) -> None:
        for chunk in chunks:
            if chunk.chunk_id in self._chunks:
                continue
            self._chunks[chunk.chunk_id] = chunk
            self._chunks_by_blob.setdefault(chunk.blob_hash, []).append(chunk.chunk_id)

    def get_chunk(self, chunk_id: str) -> Optional[Chunk]:
        return self._chunks.get(chunk_id)

    def chunks_for_blob(self, blob_hash: str) -> list[Chunk]:
        ids = self._chunks_by_blob.get(blob_hash, [])
        return sorted((self._chunks[i] for i in ids), key=lambda c: c.byte_start)

    def _active_chunks(self) -> list[Chunk]:
        return [c for c in self._chunks.values() if self._is_active(c.blob_hash)]

    # ---------------------------------------------------------------- symbols

    def add_symbols(self, symbols: Sequence[SymbolNode]) -> None:
        for node in symbols:
            if node.node_id in self._symbols:
                continue
            self._symbols[node.node_id] = node
            self._symbols_by_name.setdefault(node.symbol, []).append(node.node_id)

    def add_edges(self, edges: Sequence[Edge]) -> None:
        for edge in edges:
            key = (edge.src, edge.dst, edge.kind)
            if key in self._edge_keys:
                continue
            self._edge_keys.add(key)
            self._edges.append(edge)

    def get_definitions(self, symbol: str) -> list[SymbolNode]:
        nodes = [self._symbols[i] for i in self._symbols_by_name.get(symbol, [])]
        return [n for n in nodes if self._is_active(n.blob_hash)]

    def get_edges(
        self,
        node_id: str,
        kind: Optional[EdgeKind] = None,
        incoming: bool = False,
    ) -> list[Edge]:
        out: list[Edge] = []
        for edge in self._edges:
            end = edge.dst if incoming else edge.src
            if end != node_id:
                continue
            if kind is not None and edge.kind is not kind:
                continue
            out.append(edge)
        return out

    def all_symbols(self) -> list[SymbolNode]:
        """Test helper (not part of the contract)."""
        return list(self._symbols.values())

    # ------------------------------------------------------------- embeddings

    def get_embedding(self, chunk_id: str) -> Optional[list[float]]:
        row = self._embeddings.get(chunk_id)
        return list(row[0]) if row else None

    def put_embedding(self, chunk_id: str, vector: Sequence[float], model: str) -> None:
        self._embeddings[chunk_id] = (list(vector), model)

    # ---------------------------------------------------------------- queries

    def fts_search(self, query: str, limit: int = 100) -> list[tuple[str, float]]:
        docs = {c.chunk_id: tokenize(f"{c.breadcrumb}\n{c.code}") for c in self._active_chunks()}
        if not docs:
            return []
        n_docs = len(docs)
        avg_len = sum(len(t) for t in docs.values()) / n_docs
        # document frequency per term
        df: dict[str, int] = {}
        for tokens in docs.values():
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1

        scores: dict[str, float] = {}
        query_terms = tokenize(query)
        for chunk_id, tokens in docs.items():
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for term in query_terms:
                f = tf.get(term)
                if not f:
                    continue
                idf = math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1.0)
                denom = f + _K1 * (1 - _B + _B * len(tokens) / avg_len)
                score += idf * f * (_K1 + 1) / denom
            if score > 0:
                scores[chunk_id] = score
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:limit]

    def vector_search(self, vector: Sequence[float], limit: int = 100) -> list[tuple[str, float]]:
        query = list(vector)
        scored: list[tuple[str, float]] = []
        for chunk in self._active_chunks():
            row = self._embeddings.get(chunk.chunk_id)
            if row is None:
                continue
            emb = row[0]
            if len(emb) != len(query):
                continue
            scored.append((chunk.chunk_id, sum(a * b for a, b in zip(query, emb))))
        scored.sort(key=lambda kv: (-kv[1], kv[0]))
        return scored[:limit]

    def symbol_search(self, name: str, limit: int = 20) -> list[SymbolNode]:
        lowered = name.lower()
        scored: list[tuple[float, str, SymbolNode]] = []
        for sym_name, node_ids in self._symbols_by_name.items():
            ratio = difflib.SequenceMatcher(None, lowered, sym_name.lower()).ratio()
            if lowered and lowered in sym_name.lower():
                ratio = max(ratio, 0.9 if sym_name.lower() != lowered else 1.0)
            if ratio < 0.5:
                continue
            for node_id in node_ids:
                node = self._symbols[node_id]
                if self._is_active(node.blob_hash):
                    scored.append((ratio, node_id, node))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [node for _, _, node in scored[:limit]]

    # ------------------------------------------------------------------- meta

    def get_meta(self, key: str) -> Optional[str]:
        return self._meta.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self._meta[key] = value
