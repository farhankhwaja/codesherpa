"""Hybrid retriever implementing the frozen Retriever contract (CLAUDE.md §7.5).

search() order of operations:
1. Selective-retrieval router: identifier-like query tokens that exactly match
   a symbol definition answer from the graph directly (< 50 ms, no embedder,
   no vector search).
2. Otherwise BM25 (top 100) || vector (top 100) || fuzzy symbol (top 20).
3. Reciprocal Rank Fusion, k = 60.
4. Cross-encoder rerank of the fused top 50 (config-toggleable).
5. 1-hop graph expansion of the top 10 with a x0.6 score discount
   (config-toggleable).
6. Budget-aware packing (never exceeds budget_tokens).
"""

from __future__ import annotations

import re
from typing import Optional

from codesherpa.contracts.index_contract import IndexStore
from codesherpa.contracts.retrieval_contract import Retriever
from codesherpa.contracts.types import (
    Chunk,
    EdgeKind,
    PackedContext,
    RetrievalSource,
    SearchResult,
    SymbolNode,
)
from codesherpa.embed.engine import EmbeddingEngine
from codesherpa.retrieve.config import RetrievalConfig
from codesherpa.retrieve.fusion import rrf_fuse
from codesherpa.retrieve.pack import pack_results
from codesherpa.retrieve.passages import focus_passage, query_terms
from codesherpa.retrieve.rerank import CrossEncoderReranker
from codesherpa.retrieve.router import (
    extract_identifier_tokens,
    extract_path_segments,
    split_identifier,
)
from codesherpa.retrieve.tokens import result_token_cost


def _parse_node_id(node_id: str) -> tuple[str, int, int, str]:
    """``blob:start:end:symbol`` -> parts (symbol may not contain ':')."""
    blob, start, end, symbol = node_id.split(":", 3)
    return blob, int(start), int(end), symbol


def _package_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


class HybridRetriever(Retriever):
    """Retriever over an :class:`IndexStore` + :class:`EmbeddingEngine`."""

    def __init__(
        self,
        store: IndexStore,
        embedder: EmbeddingEngine,
        *,
        config: Optional[RetrievalConfig] = None,
        reranker: Optional[CrossEncoderReranker] = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._config = config or RetrievalConfig()
        self._reranker = reranker
        weight = self._config.rerank_blend_vector_weight
        if weight is None:  # size-aware auto (D45)
            small = len(store.active_blobs()) <= RetrievalConfig.SMALL_INDEX_ACTIVE_BLOBS
            weight = 4.0 if small else 1.0
        self._blend_vector_weight = float(weight)
        if self._config.rerank_enabled and self._reranker is None:
            self._reranker = CrossEncoderReranker(
                self._config.reranker_model,
                max_chars=self._config.rerank_max_chars,
                cache_dir=self._config.model_cache_dir,
            )
        self.last_search_path: Optional[str] = None
        """'router' or 'dense' — which path answered the most recent
        ``search()`` call. Observational only (read by the usage-analytics
        wrapper in mcp_server); never feeds back into retrieval."""

    # --------------------------------------------------------------- helpers

    def _chunk_for_symbol(self, node: SymbolNode) -> Optional[Chunk]:
        """The chunk of the symbol's blob with maximal overlap of its range."""
        best: Optional[Chunk] = None
        best_overlap = 0
        for chunk in self._store.chunks_for_blob(node.blob_hash):
            overlap = min(chunk.byte_end, node.byte_end) - max(
                chunk.byte_start, node.byte_start
            )
            if overlap > best_overlap:
                best, best_overlap = chunk, overlap
        return best

    def _result(
        self,
        chunk: Chunk,
        score: float,
        source: RetrievalSource,
        rationale: Optional[str] = None,
    ) -> SearchResult:
        return SearchResult(
            chunk=chunk,
            score=score,
            source=source,
            expand_id=chunk.chunk_id,
            token_count=result_token_cost(chunk.breadcrumb, chunk.code),
            rationale=rationale,
        )

    # ---------------------------------------------------------------- router

    def _router_results(self, query: str) -> list[SearchResult]:
        """Exact-symbol fast path: definitions + ranked 1-hop neighbors.

        Ordering (D45): tokens are processed rarest-first (fewest
        definitions = most specific), ambiguous convention names last;
        within a token, definitions whose file path matches a path-like
        fragment of the query itself (stack traces carry package paths)
        rank first; each token contributes at most ROUTER_TOKEN_FANOUT
        definitions."""
        per_token: list[tuple[str, list[SymbolNode]]] = []
        for token in extract_identifier_tokens(query):
            definitions = self._store.get_definitions(token)
            if definitions:
                per_token.append((token, definitions))
        if not per_token:
            return []

        original_order = {token: i for i, (token, _) in enumerate(per_token)}
        per_token.sort(
            key=lambda td: (
                len(td[1]) > self._config.router_ambiguous_defs,  # convention names last
                len(td[1]),  # rarest (most specific) first
                original_order[td[0]],  # stable for ties
            )
        )

        path_segments = extract_path_segments(query)

        def _path_affinity(node: SymbolNode) -> int:
            best = 0
            for segment in path_segments:
                if segment in node.file_path:
                    return 2  # full fragment match (package path)
                basename = segment.rsplit("/", 1)[-1]
                if node.file_path.endswith("/" + basename) or node.file_path == basename:
                    best = max(best, 1)  # filename match
            return best

        results: list[SearchResult] = []
        seen_chunks: set[str] = set()
        for tier, (token, definitions) in enumerate(per_token):
            if path_segments:
                definitions = sorted(
                    definitions,
                    key=lambda n: (-_path_affinity(n), n.file_path, n.byte_start),
                )
            definitions = definitions[: self._config.router_token_fanout]
            tier_score = max(0.10, 1.0 - 0.12 * tier)
            for rank, node in enumerate(definitions):
                chunk = self._chunk_for_symbol(node)
                if chunk is None or chunk.chunk_id in seen_chunks:
                    continue
                seen_chunks.add(chunk.chunk_id)
                score = max(0.05, tier_score - 0.04 * rank)
                results.append(
                    self._result(
                        chunk,
                        score=score,
                        source=RetrievalSource.SYMBOL,
                        rationale=f"exact definition of `{token}`",
                    )
                )
                # ranked 1-hop neighbors, discounted
                for neighbor, why in self._neighbors(node):
                    n_chunk = self._chunk_for_symbol(neighbor)
                    if n_chunk is None or n_chunk.chunk_id in seen_chunks:
                        continue
                    seen_chunks.add(n_chunk.chunk_id)
                    results.append(
                        self._result(
                            n_chunk,
                            score=score * self._config.expansion_discount,
                            source=RetrievalSource.EXPANSION,
                            rationale=f"{why} `{token}`",
                        )
                    )
        return results

    def _neighbors(self, node: SymbolNode) -> list[tuple[SymbolNode, str]]:
        """1-hop neighbors of a definition, ranked: callers, callees, imports."""
        ranked: list[tuple[int, SymbolNode, str]] = []
        plans = (
            # (priority, kind, incoming, how-the-neighbor-relates-to-node)
            (0, EdgeKind.CALLS, True, "calls"),
            (1, EdgeKind.CALLS, False, "called by"),
            (2, EdgeKind.IMPORTS, True, "imports"),
            (3, EdgeKind.REFERENCES, True, "references"),
        )
        for priority, kind, incoming, label in plans:
            for edge in self._store.get_edges(node.node_id, kind=kind, incoming=incoming):
                other_id = edge.src if incoming else edge.dst
                try:
                    blob, start, end, symbol = _parse_node_id(other_id)
                except ValueError:
                    continue
                for other in self._store.get_definitions(symbol):
                    if other.node_id == other_id:
                        ranked.append((priority, other, label))
                        break
        ranked.sort(key=lambda item: (item[0], item[1].node_id))
        return [(node_, why) for _, node_, why in ranked]

    # ---------------------------------------------------------------- search

    def search(self, query: str, budget_tokens: int = 4000) -> PackedContext:
        router_hits = self._router_results(query)
        if router_hits:
            self.last_search_path = "router"
            return pack_results(query, router_hits, budget_tokens)
        self.last_search_path = "dense"
        return pack_results(query, self._dense_candidates(query), budget_tokens)

    def _dense_candidates(self, query: str) -> list[SearchResult]:
        cfg = self._config

        # -- three candidate lists in rank order
        bm25 = [cid for cid, _ in self._store.fts_search(query, limit=cfg.bm25_top)]
        vector = [
            cid
            for cid, _ in self._store.vector_search(
                self._embedder.embed_query(query), limit=cfg.vector_top
            )
        ]
        symbol_ids: list[str] = []
        for token in _fuzzy_terms(query):
            for node in self._store.symbol_search(token, limit=cfg.symbol_top):
                chunk = self._chunk_for_symbol(node)
                if chunk is not None and chunk.chunk_id not in symbol_ids:
                    symbol_ids.append(chunk.chunk_id)
        symbol_ids = symbol_ids[: cfg.symbol_top]

        fused = rrf_fuse([bm25, vector, symbol_ids], k=cfg.rrf_k)

        # -- source attribution: symbol > bm25 > vector by list membership
        def source_of(cid: str) -> RetrievalSource:
            if cid in symbol_ids:
                return RetrievalSource.SYMBOL
            if cid in bm25:
                return RetrievalSource.BM25
            return RetrievalSource.VECTOR

        # -- cross-encoder rerank (toggleable). Candidates are the UNION of
        # each channel's head plus fused order (fused-only selection lets a
        # BM25 stopword flood push a vector-rank-4 chunk beyond the CE
        # window). Passages are query-focused windows, not head-truncations:
        # cAST chunks are often whole files and the relevant code may sit
        # past the CE char cap. By default the CE ordering is rank-fused
        # with the vector ordering instead of overwriting it (DECISIONS.md).
        scores: dict[str, float]
        if cfg.rerank_enabled and self._reranker is not None and fused:
            pool: list[str] = []
            head = cfg.rerank_channel_head
            for cid in (
                vector[:head]
                + bm25[:head]
                + symbol_ids[: max(1, head // 2)]
                + [cid for cid, _ in fused]
            ):
                if cid not in pool:
                    pool.append(cid)
                if len(pool) >= cfg.rerank_top:
                    break

            terms = query_terms(query)
            passages = []
            for cid in pool:
                chunk = self._store.get_chunk(cid)
                if chunk is not None:
                    passage = focus_passage(
                        terms, chunk.breadcrumb, chunk.code, cfg.rerank_max_chars
                    )
                    passages.append((cid, passage))
            ce_scored = self._reranker.rerank(query, passages)
            if cfg.rerank_blend_vector:
                ce_ranked = [cid for cid, _ in ce_scored]
                blended = rrf_fuse(
                    [ce_ranked, vector],
                    k=cfg.rrf_k,
                    weights=[1.0, self._blend_vector_weight],
                )
                in_pool = set(pool)
                scores = {cid: s for cid, s in blended if cid in in_pool}
            else:
                scores = dict(ce_scored)
        else:
            scores = dict(fused[: cfg.rerank_top])

        candidates: list[SearchResult] = []
        chunk_by_id: dict[str, Chunk] = {}
        for cid, score in scores.items():
            chunk = self._store.get_chunk(cid)
            if chunk is None:
                continue
            chunk_by_id[cid] = chunk
            candidates.append(self._result(chunk, score, source_of(cid)))

        # -- 1-hop graph expansion of the top results (toggleable)
        if cfg.expansion_enabled:
            candidates.extend(self._expansion_candidates(candidates, chunk_by_id))
        return candidates

    def _expansion_candidates(
        self,
        candidates: list[SearchResult],
        chunk_by_id: dict[str, Chunk],
    ) -> list[SearchResult]:
        cfg = self._config
        top = sorted(candidates, key=lambda r: -r.score)[: cfg.expansion_top]
        seen = set(chunk_by_id)
        extra: list[SearchResult] = []
        for res in top:
            for node in self._symbols_in_chunk(res.chunk):
                for neighbor, why in self._neighbors(node):
                    n_chunk = self._chunk_for_symbol(neighbor)
                    if n_chunk is None or n_chunk.chunk_id in seen:
                        continue
                    seen.add(n_chunk.chunk_id)
                    extra.append(
                        self._result(
                            n_chunk,
                            score=res.score * cfg.expansion_discount,
                            source=RetrievalSource.EXPANSION,
                            rationale=f"{why} `{node.symbol}`",
                        )
                    )
        return extra

    def _symbols_in_chunk(self, chunk: Chunk) -> list[SymbolNode]:
        out = []
        # case-preserving identifier tokens from the breadcrumb (definitions
        # are case-sensitive: `TaskItem` must not become `task item`)
        tokens = sorted(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", chunk.breadcrumb)))
        for token in tokens:
            for node in self._store.get_definitions(token):
                if (
                    node.blob_hash == chunk.blob_hash
                    and node.byte_start < chunk.byte_end
                    and chunk.byte_start < node.byte_end
                ):
                    out.append(node)
        # dedupe, stable
        seen: set[str] = set()
        unique = []
        for node in out:
            if node.node_id not in seen:
                seen.add(node.node_id)
                unique.append(node)
        return unique

    # ----------------------------------------------------- structural lookups

    def get_definition(self, symbol: str) -> list[SearchResult]:
        results = []
        for rank, node in enumerate(self._store.get_definitions(symbol)):
            chunk = self._chunk_for_symbol(node)
            if chunk is None:
                continue
            results.append(
                self._result(
                    chunk,
                    score=1.0 - 0.05 * rank,
                    source=RetrievalSource.SYMBOL,
                    rationale=f"definition of `{symbol}` ({node.kind.value})",
                )
            )
        return results

    def get_callers(self, symbol: str, limit: int = 10) -> list[SearchResult]:
        return self._incoming(symbol, EdgeKind.CALLS, limit, "calls")

    def get_references(self, symbol: str, limit: int = 20) -> list[SearchResult]:
        return self._incoming(symbol, EdgeKind.REFERENCES, limit, "references")

    def _incoming(
        self, symbol: str, kind: EdgeKind, limit: int, verb: str
    ) -> list[SearchResult]:
        """Ranked incoming-edge sources (§7.3: same-package proximity, then
        reference count; recency is a Phase 4 store concern — see PROGRESS)."""
        counts: dict[str, int] = {}
        sources: dict[str, SymbolNode] = {}
        def_packages: set[str] = set()
        for definition in self._store.get_definitions(symbol):
            def_packages.add(_package_of(definition.file_path))
            for edge in self._store.get_edges(definition.node_id, kind=kind, incoming=True):
                counts[edge.src] = counts.get(edge.src, 0) + 1
                if edge.src not in sources:
                    try:
                        blob, start, end, src_symbol = _parse_node_id(edge.src)
                    except ValueError:
                        continue
                    for node in self._store.get_definitions(src_symbol):
                        if node.node_id == edge.src:
                            sources[edge.src] = node
                            break

        ranked: list[tuple[tuple, SymbolNode, str]] = []
        for node_id, node in sources.items():
            same_pkg = _package_of(node.file_path) in def_packages
            count = counts[node_id]
            rationale = (
                f"{verb} `{symbol}` {count}x; "
                + ("same package" if same_pkg else "different package")
            )
            ranked.append(((0 if same_pkg else 1, -count, node_id), node, rationale))
        ranked.sort(key=lambda item: item[0])

        results = []
        for rank, (_, node, rationale) in enumerate(ranked[:limit]):
            chunk = self._chunk_for_symbol(node)
            if chunk is None:
                continue
            results.append(
                self._result(
                    chunk,
                    score=1.0 - 0.03 * rank,
                    source=RetrievalSource.SYMBOL,
                    rationale=rationale,
                )
            )
        return results

    def expand(self, expand_id: str) -> Optional[SearchResult]:
        chunk = self._store.get_chunk(expand_id)
        if chunk is None:
            return None
        return self._result(
            chunk,
            score=1.0,
            source=RetrievalSource.EXPANSION,
            rationale="expanded on request",
        )


def _fuzzy_terms(query: str) -> list[str]:
    """Terms to feed fuzzy symbol search: identifier-like tokens if any,
    else content words of the query (longest first, capped)."""
    tokens = extract_identifier_tokens(query)
    if tokens:
        return tokens[:5]
    words = sorted(set(split_identifier(query)), key=lambda w: -len(w))
    return [w for w in words if len(w) > 3][:5]
