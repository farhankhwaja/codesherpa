"""FROZEN Retriever contract (CLAUDE.md §2.2 — do not edit after Phase 0).

Implemented by ``repograph.retrieve`` (Phase 3) and consumed by the MCP server
(Phase 4). Responses must be compact by default: return ``expand_id`` handles
instead of dumping context.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from repograph.contracts.types import PackedContext, SearchResult


class Retriever(ABC):
    """Retrieval interface over an :class:`~repograph.contracts.index_contract.IndexStore`."""

    @abstractmethod
    def search(self, query: str, budget_tokens: int = 4000) -> PackedContext:
        """Hybrid search (CLAUDE.md §7.5).

        Router first (exact symbol match -> definition + ranked 1-hop
        neighbors, < 50 ms, no dense search); otherwise BM25 || vector ||
        symbol fuzzy -> RRF -> cross-encoder rerank -> 1-hop expansion ->
        budget-aware packing. Never exceeds ``budget_tokens``.
        """

    @abstractmethod
    def get_definition(self, symbol: str) -> list[SearchResult]:
        """Definition chunk(s) for an exact symbol name, best first."""

    @abstractmethod
    def get_callers(self, symbol: str, limit: int = 10) -> list[SearchResult]:
        """Ranked callers (same-package proximity, reference count, recency).

        Never an unordered dump; each result carries a ``rationale``.
        """

    @abstractmethod
    def get_references(self, symbol: str, limit: int = 20) -> list[SearchResult]:
        """Ranked reference sites for a symbol."""

    @abstractmethod
    def expand(self, expand_id: str) -> Optional[SearchResult]:
        """Full chunk / surrounding context for a previously returned result."""
