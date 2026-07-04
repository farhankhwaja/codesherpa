"""Test-only Retriever implementing the frozen contract over the in-memory
store + SymbolGraph.

Stands in for the Phase 3 pipeline (retrieval worktree) so the MCP server
and eval harness can be integration-tested before merge (CLAUDE.md §8). It
is contract-faithful — router path, budget packing, expand handles — just
without embeddings or reranking.
"""

from __future__ import annotations

import re
from typing import Optional

from inmemory_store import InMemoryIndexStore
from repograph.contracts.retrieval_contract import Retriever
from repograph.contracts.types import PackedContext, RetrievalSource, SearchResult
from repograph.graph.textutil import estimate_tokens
from repograph.graph.view import SymbolGraph

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


class SimpleRetriever(Retriever):
    def __init__(self, store: InMemoryIndexStore, graph: SymbolGraph) -> None:
        self._store = store
        self._graph = graph

    def search(self, query: str, budget_tokens: int = 4000) -> PackedContext:
        candidates: list[SearchResult] = []
        for token in dict.fromkeys(_IDENTIFIER_RE.findall(query)):
            if self._store.get_definitions(token):
                # router path: definition + ranked 1-hop neighbors, no dense search
                candidates = self._graph.get_definition(token) + self._graph.neighbors(token)
                break
        else:
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
