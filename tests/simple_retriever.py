"""Test-only Retriever implementing the frozen contract over any IndexStore.

Stands in for the Phase 3 pipeline (retrieval worktree) so the MCP server,
eval harness, and graph-expansion delta can be integration-tested before
Phase 3 merges (CLAUDE.md §8). Contract-faithful — router path, budget
packing, expand handles, and the §7.5.5 one-hop graph expansion behind a
config flag — just without embeddings or reranking.
"""

from __future__ import annotations

import re
from typing import Optional

from repograph.contracts.index_contract import IndexStore
from repograph.contracts.retrieval_contract import Retriever
from repograph.contracts.types import PackedContext, RetrievalSource, SearchResult
from repograph.graph.textutil import estimate_tokens
from repograph.graph.view import SymbolGraph

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

_EXPANSION_DISCOUNT = 0.6  # §7.5.5
_EXPANSION_TOP_N = 10


class SimpleRetriever(Retriever):
    def __init__(
        self, store: IndexStore, graph: SymbolGraph, expansion: bool = False
    ) -> None:
        self._store = store
        self._graph = graph
        self._expansion = expansion

    def _fts_candidates(self, query: str) -> list[SearchResult]:
        candidates = []
        for chunk_id, score in self._store.fts_search(query, limit=50):
            chunk = self._store.get_chunk(chunk_id)
            if chunk is None:
                continue
            candidates.append(
                SearchResult(
                    chunk=chunk,
                    score=score,
                    source=RetrievalSource.BM25,
                    expand_id=chunk.chunk_id,
                    token_count=estimate_tokens(f"{chunk.breadcrumb}\n{chunk.code}"),
                )
            )
        candidates.sort(key=lambda r: (-r.score, r.chunk.chunk_id))
        return candidates

    def _expand_candidates(self, ranked: list[SearchResult]) -> list[SearchResult]:
        """§7.5.5: attach 1-hop neighbors of the top results, score × 0.6.

        Anchor symbols are recovered from result breadcrumbs (path :: scope
        :: signature), which name the enclosing definitions.
        """
        additions: list[SearchResult] = []
        for parent in ranked[:_EXPANSION_TOP_N]:
            for token in dict.fromkeys(_IDENTIFIER_RE.findall(parent.chunk.breadcrumb)):
                if not self._store.get_definitions(token):
                    continue
                for neighbor in self._graph.neighbors(token, limit=5):
                    additions.append(
                        SearchResult(
                            chunk=neighbor.chunk,
                            score=parent.score * _EXPANSION_DISCOUNT,
                            source=RetrievalSource.EXPANSION,
                            expand_id=neighbor.expand_id,
                            token_count=neighbor.token_count,
                            rationale=neighbor.rationale,
                        )
                    )
                break  # one anchor symbol per parent is enough for the stand-in
        return additions

    def search(self, query: str, budget_tokens: int = 4000) -> PackedContext:
        candidates: list[SearchResult] = []
        for token in dict.fromkeys(_IDENTIFIER_RE.findall(query)):
            if self._store.get_definitions(token):
                # router path: definition + ranked 1-hop neighbors, no dense search
                candidates = self._graph.get_definition(token) + self._graph.neighbors(token)
                break
        else:
            candidates = self._fts_candidates(query)
            if self._expansion:
                candidates = candidates + self._expand_candidates(candidates)

        packed: list[SearchResult] = []
        seen: set[str] = set()
        total = 0
        for result in candidates:
            if result.chunk.chunk_id in seen:
                continue
            if total + result.token_count > budget_tokens:
                continue
            packed.append(result)
            seen.add(result.chunk.chunk_id)
            total += result.token_count
        return PackedContext(
            query=query,
            budget_tokens=budget_tokens,
            total_tokens=total,
            results=tuple(packed),
        )

    def get_definition(self, symbol: str) -> list[SearchResult]:
        return self._graph.get_definition(symbol)

    def get_callers(self, symbol: str, limit: int = 10) -> list[SearchResult]:
        return self._graph.get_callers(symbol, limit=limit)

    def get_references(self, symbol: str, limit: int = 20) -> list[SearchResult]:
        return self._graph.get_references(symbol, limit=limit)

    def expand(self, expand_id: str) -> Optional[SearchResult]:
        chunk = self._store.get_chunk(expand_id)
        if chunk is None:
            return None
        return SearchResult(
            chunk=chunk,
            score=1.0,
            source=RetrievalSource.SYMBOL,
            expand_id=chunk.chunk_id,
            token_count=estimate_tokens(f"{chunk.breadcrumb}\n{chunk.code}"),
        )
