"""Ranked structural queries over an :class:`IndexStore` (CLAUDE.md §7.3).

``get_callers`` (and friends) never return an unordered dump: results are
ranked by same-package proximity, reference count, and recency of last
change, and every result carries a human/agent-readable ``rationale``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Optional

from repograph.contracts.index_contract import IndexStore
from repograph.contracts.types import (
    Chunk,
    EdgeKind,
    RetrievalSource,
    SearchResult,
    SymbolKind,
    SymbolNode,
)
from repograph.graph.textutil import estimate_tokens

__all__ = ["SymbolGraph"]

_KIND_ORDER = {
    SymbolKind.CLASS: 0,
    SymbolKind.FUNCTION: 0,
    SymbolKind.METHOD: 0,
    SymbolKind.CONST: 1,
    SymbolKind.VARIABLE: 1,
    SymbolKind.MODULE: 2,
}

_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _package(path: str) -> str:
    return path.rpartition("/")[0]


def _date_fraction(iso_date: Optional[str]) -> float:
    """Map an ISO date to (0, 1): newer -> closer to 1. 0.0 if unknown."""
    if not iso_date:
        return 0.0
    try:
        moment = datetime.fromisoformat(iso_date)
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    days = max(0.0, (moment - _EPOCH).total_seconds() / 86400.0)
    return min(days / 36500.0, 0.999)  # ~100-year horizon keeps it in (0, 1)


class SymbolGraph:
    """Graph queries backed by any IndexStore implementation.

    ``recency`` maps file paths to the ISO date of their last change (see
    :func:`repograph.graph.gitio.last_change_dates`); it only affects
    ranking, never membership.
    """

    def __init__(self, store: IndexStore, recency: Optional[Mapping[str, str]] = None):
        self._store = store
        self._recency: Mapping[str, str] = recency or {}

    # ------------------------------------------------------------- lookups

    def _node_from_id(self, node_id: str) -> Optional[SymbolNode]:
        parts = node_id.split(":", 3)
        if len(parts) != 4:
            return None
        for node in self._store.get_definitions(parts[3]):
            if node.node_id == node_id:
                return node
        return None

    def _chunk_for(self, node: SymbolNode) -> Optional[Chunk]:
        """Best stored chunk for a node: the smallest chunk containing its
        whole byte range, else the chunk with the largest overlap."""
        containing: Optional[Chunk] = None
        overlapping: Optional[Chunk] = None
        best_overlap = 0
        for chunk in self._store.chunks_for_blob(node.blob_hash):
            overlap = min(chunk.byte_end, node.byte_end) - max(chunk.byte_start, node.byte_start)
            if overlap <= 0:
                continue
            if chunk.byte_start <= node.byte_start and node.byte_end <= chunk.byte_end:
                if containing is None or (chunk.byte_end - chunk.byte_start) < (
                    containing.byte_end - containing.byte_start
                ):
                    containing = chunk
            elif overlap > best_overlap:
                best_overlap = overlap
                overlapping = chunk
        return containing if containing is not None else overlapping

    def _inbound_count(self, node: SymbolNode) -> int:
        calls = self._store.get_edges(node.node_id, kind=EdgeKind.CALLS, incoming=True)
        refs = self._store.get_edges(node.node_id, kind=EdgeKind.REFERENCES, incoming=True)
        return len(calls) + len(refs)

    def _result(
        self,
        node: SymbolNode,
        score: float,
        rationale: str,
        source: RetrievalSource = RetrievalSource.SYMBOL,
    ) -> Optional[SearchResult]:
        chunk = self._chunk_for(node)
        if chunk is None:
            return None  # blob not chunk-indexed (yet); skip rather than fake it
        return SearchResult(
            chunk=chunk,
            score=score,
            source=source,
            expand_id=chunk.chunk_id,
            token_count=estimate_tokens(f"{chunk.breadcrumb}\n{chunk.code}"),
            rationale=rationale,
        )

    # ------------------------------------------------------------- ranking

    def _rank_related(
        self,
        targets: list[SymbolNode],
        node_ids: list[tuple[SymbolNode, str, str]],  # (target, other_node_id, relation)
        limit: int,
        source: RetrievalSource = RetrievalSource.SYMBOL,
    ) -> list[SearchResult]:
        """Score (relation partner) nodes against their target definitions."""
        seen: set[str] = set()
        scored: list[tuple[float, SymbolNode, str]] = []
        for target, other_id, relation in node_ids:
            if other_id in seen:
                continue
            seen.add(other_id)
            other = self._node_from_id(other_id)
            if other is None:
                continue
            if other.file_path == target.file_path:
                proximity, where = 2, "same file"
            elif _package(other.file_path) == _package(target.file_path):
                proximity, where = 1, "same package"
            else:
                proximity, where = 0, "different package"
            inbound = self._inbound_count(other)
            changed = self._recency.get(other.file_path)
            score = proximity * 1000 + min(inbound, 99) * 10 + _date_fraction(changed)
            rationale = (
                f"{relation} {target.symbol} ({target.file_path}); {where}; "
                f"{inbound} inbound refs"
            )
            if changed:
                rationale += f"; last changed {changed[:10]}"
            scored.append((score, other, rationale))
        scored.sort(key=lambda item: (-item[0], item[1].file_path, item[1].byte_start))
        results = []
        for score, node, rationale in scored:
            result = self._result(node, score, rationale, source)
            if result is not None:
                results.append(result)
            if len(results) >= limit:
                break
        return results

    # -------------------------------------------------------------- public

    def get_definition(self, symbol: str) -> list[SearchResult]:
        """Definition chunk(s) for an exact symbol name, best first."""
        nodes = sorted(
            self._store.get_definitions(symbol),
            key=lambda n: (_KIND_ORDER.get(n.kind, 3), n.file_path, n.byte_start),
        )
        results = []
        for node in nodes:
            rationale = f"{node.kind.value} definition in {node.file_path}"
            if node.signature:
                rationale += f": {node.signature}"
            result = self._result(node, 1.0, rationale)
            if result is not None:
                results.append(result)
        return results

    def get_callers(self, symbol: str, limit: int = 10) -> list[SearchResult]:
        """Ranked callers of ``symbol`` — never an unordered dump."""
        pairs = []
        for target in self._store.get_definitions(symbol):
            for edge in self._store.get_edges(
                target.node_id, kind=EdgeKind.CALLS, incoming=True
            ):
                pairs.append((target, edge.src, "calls"))
        return self._rank_related(
            self._store.get_definitions(symbol), pairs, limit
        )

    def get_references(self, symbol: str, limit: int = 20) -> list[SearchResult]:
        """Ranked reference sites (references, calls, imports) for a symbol."""
        pairs = []
        for target in self._store.get_definitions(symbol):
            for kind, relation in (
                (EdgeKind.REFERENCES, "references"),
                (EdgeKind.CALLS, "calls"),
                (EdgeKind.IMPORTS, "imports"),
            ):
                for edge in self._store.get_edges(target.node_id, kind=kind, incoming=True):
                    pairs.append((target, edge.src, relation))
        return self._rank_related(
            self._store.get_definitions(symbol), pairs, limit
        )

    def neighbors(self, symbol: str, limit: int = 10) -> list[SearchResult]:
        """Ranked 1-hop neighborhood of a symbol, for graph expansion (§7.5.5).

        Outgoing calls/references/imports plus incoming calls, marked with
        ``RetrievalSource.EXPANSION`` so the retrieval pipeline can apply its
        score discount.
        """
        pairs = []
        for target in self._store.get_definitions(symbol):
            for kind, relation in (
                (EdgeKind.CALLS, "called by"),
                (EdgeKind.REFERENCES, "referenced by"),
                (EdgeKind.IMPORTS, "imported by"),
            ):
                for edge in self._store.get_edges(target.node_id, kind=kind, incoming=False):
                    pairs.append((target, edge.dst, relation))
            for edge in self._store.get_edges(
                target.node_id, kind=EdgeKind.CALLS, incoming=True
            ):
                pairs.append((target, edge.src, "calls"))
        return self._rank_related(
            self._store.get_definitions(symbol), pairs, limit, RetrievalSource.EXPANSION
        )
