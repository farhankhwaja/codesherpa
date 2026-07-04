"""HybridRetriever tests: router fast path, hybrid pipeline, expansion,
structural lookups, packing (Phase 3 criteria).

Runs against the real SQLiteIndexStore (FTS5, embeddings table) populated
through the store's public API with a hand-built scenario. A Spy subclass
counts vector/FTS calls — in tests only (§2.5) — so the router criterion
"vector path NOT invoked for exact-symbol queries" is asserted, not assumed.
"""

from __future__ import annotations

import time

import pytest

from codesherpa.contracts.types import (
    Chunk,
    Edge,
    EdgeKind,
    RetrievalSource,
    SymbolKind,
    SymbolNode,
)
from codesherpa.embed.engine import EmbeddingEngine
from codesherpa.retrieve.config import RetrievalConfig
from codesherpa.retrieve.rerank import CrossEncoderReranker
from codesherpa.retrieve.retriever import HybridRetriever
from codesherpa.retrieve.router import split_identifier
from codesherpa.store.sqlite_store import SQLiteIndexStore

BLOB_HTTP = "a" * 40
BLOB_ROUTES = "b" * 40
BLOB_API = "c" * 40


class SpyStore(SQLiteIndexStore):
    """Real store that records which query paths were touched (tests only)."""

    def __init__(self, db_path) -> None:
        super().__init__(db_path)
        self.vector_calls = 0
        self.fts_calls = 0

    def vector_search(self, vector, limit=100):
        self.vector_calls += 1
        return super().vector_search(vector, limit)

    def fts_search(self, query, limit=100):
        self.fts_calls += 1
        return super().fts_search(query, limit)


class StubEncoder:
    """Bag-of-words embedding over identifier-split tokens: same words ->
    similar vectors. Deterministic; mocks live in tests only."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, texts):
        self.calls += 1
        out = []
        for text in texts:
            vec = [0.0] * 32
            for word in text.split():
                for part in split_identifier(word):
                    vec[hash(part) % 32] += 1.0
            out.append(vec)
        return out


def _chunk(blob, start, end, path, code, breadcrumb, language="python"):
    return Chunk(
        blob_hash=blob,
        byte_start=start,
        byte_end=end,
        file_path=path,
        language=language,
        code=code,
        breadcrumb=breadcrumb,
    )


def build_store(db_path):
    store = SpyStore(db_path)
    for blob, lang in ((BLOB_HTTP, "python"), (BLOB_ROUTES, "python"), (BLOB_API, "typescript")):
        store.add_blob(blob, lang, 1000)

    retry_chunk = _chunk(
        BLOB_HTTP, 0, 120, "pyserver/http_client.py",
        'def retry_request(url, attempts=3):\n'
        '    """Retry logic for http requests with backoff."""\n'
        '    for i in range(attempts):\n        pass\n',
        "# pyserver/http_client.py :: http_client :: def retry_request(url, attempts=3)",
    )
    backoff_chunk = _chunk(
        BLOB_HTTP, 120, 200, "pyserver/http_client.py",
        "def backoff_delay(i):\n    return 2 ** i\n",
        "# pyserver/http_client.py :: http_client :: def backoff_delay(i)",
    )
    create_chunk = _chunk(
        BLOB_ROUTES, 0, 150, "pyserver/routes/tasks.py",
        'def create_task(payload):\n'
        '    """Create a new task row."""\n'
        "    return retry_request('/tasks')\n",
        "# pyserver/routes/tasks.py :: tasks :: def create_task(payload)",
    )
    fetch_chunk = _chunk(
        BLOB_API, 0, 140, "webclient/src/api.ts",
        "// Fetch the task list from the api\n"
        "export function fetchTasks() {\n  return retry_request('/api/tasks');\n}\n",
        "// webclient/src/api.ts :: api :: export function fetchTasks()",
        language="typescript",
    )
    store.add_chunks([retry_chunk, backoff_chunk, create_chunk, fetch_chunk])

    retry_def = SymbolNode("retry_request", SymbolKind.FUNCTION, BLOB_HTTP, 0, 120,
                           "pyserver/http_client.py", "def retry_request(url, attempts=3)")
    backoff_def = SymbolNode("backoff_delay", SymbolKind.FUNCTION, BLOB_HTTP, 120, 200,
                             "pyserver/http_client.py", "def backoff_delay(i)")
    create_def = SymbolNode("create_task", SymbolKind.FUNCTION, BLOB_ROUTES, 0, 150,
                            "pyserver/routes/tasks.py", "def create_task(payload)")
    fetch_def = SymbolNode("fetchTasks", SymbolKind.FUNCTION, BLOB_API, 0, 140,
                           "webclient/src/api.ts", "function fetchTasks()")
    store.add_symbols([retry_def, backoff_def, create_def, fetch_def])
    store.add_edges([
        Edge(create_def.node_id, retry_def.node_id, EdgeKind.CALLS),
        Edge(fetch_def.node_id, retry_def.node_id, EdgeKind.CALLS),
        Edge(retry_def.node_id, backoff_def.node_id, EdgeKind.CALLS),
    ])
    return store, {
        "retry": retry_chunk, "backoff": backoff_chunk,
        "create": create_chunk, "fetch": fetch_chunk,
    }


@pytest.fixture()
def scenario(tmp_path):
    store, chunks = build_store(tmp_path / "scenario.db")
    yield store, chunks
    store.close()


def make_retriever(store, *, rerank=False, expansion=True, scorer=None, blend=True):
    config = RetrievalConfig(
        rerank_enabled=rerank, expansion_enabled=expansion, rerank_blend_vector=blend
    )
    encoder = StubEncoder()
    embedder = EmbeddingEngine(store, "stub-model", encoder=encoder)
    # pre-embed the corpus (mirrors indexing)
    all_chunks = []
    for blob in (BLOB_HTTP, BLOB_ROUTES, BLOB_API):
        all_chunks.extend(store.chunks_for_blob(blob))
    embedder.embed_chunks(all_chunks)
    reranker = CrossEncoderReranker("stub", scorer=scorer) if scorer else None
    return HybridRetriever(store, embedder, config=config, reranker=reranker), encoder


class TestRouterPath:
    def test_exact_symbol_skips_vector_search(self, scenario):
        """Phase 3 criterion: router path never touches the vector index."""
        store, chunks = scenario
        retriever, encoder = make_retriever(store)
        encoder.calls = 0
        store.vector_calls = 0

        packed = retriever.search("retry_request")

        assert store.vector_calls == 0, "vector path must not be called"
        assert encoder.calls == 0, "query must not be embedded on router path"
        assert packed.results[0].chunk.chunk_id == chunks["retry"].chunk_id
        assert packed.results[0].source is RetrievalSource.SYMBOL

    def test_router_returns_ranked_one_hop_neighbors(self, scenario):
        store, chunks = scenario
        retriever, _ = make_retriever(store)
        packed = retriever.search("retry_request")
        ids = [r.chunk.chunk_id for r in packed.results]
        # definition first, then callers/callees as discounted expansion
        assert ids[0] == chunks["retry"].chunk_id
        assert chunks["create"].chunk_id in ids
        assert chunks["backoff"].chunk_id in ids
        neighbor = next(r for r in packed.results if r.chunk.chunk_id == chunks["create"].chunk_id)
        assert neighbor.source is RetrievalSource.EXPANSION
        assert neighbor.score < packed.results[0].score

    def test_router_path_under_50ms(self, scenario):
        store, _ = scenario
        retriever, _ = make_retriever(store)
        retriever.search("retry_request")  # warm
        start = time.perf_counter()
        retriever.search("retry_request")
        elapsed = time.perf_counter() - start
        assert elapsed < 0.05, f"router path took {elapsed * 1000:.1f} ms"

    def test_stacktrace_query_hits_router(self, scenario):
        store, chunks = scenario
        retriever, _ = make_retriever(store)
        trace = (
            "Traceback (most recent call last):\n"
            '  File "pyserver/routes/tasks.py", in create_task\n'
            "KeyError: 'task_id'"
        )
        packed = retriever.search(trace)
        assert store.vector_calls == 0
        assert packed.results[0].chunk.chunk_id == chunks["create"].chunk_id


class TestHybridPath:
    def test_nl_query_uses_all_three_lists(self, scenario):
        store, chunks = scenario
        retriever, encoder = make_retriever(store)
        encoder.calls = 0
        packed = retriever.search("where is the retry logic for http requests")
        assert store.vector_calls == 1
        assert store.fts_calls == 1
        assert encoder.calls == 1  # query embedding
        assert packed.results, "hybrid path returned nothing"
        assert packed.results[0].chunk.chunk_id == chunks["retry"].chunk_id

    def test_budget_respected(self, scenario):
        store, _ = scenario
        retriever, _ = make_retriever(store)
        packed = retriever.search("where is the retry logic for http requests",
                                  budget_tokens=40)
        assert packed.total_tokens <= 40
        assert packed.budget_tokens == 40

    def test_rerank_disabled_does_not_call_scorer(self, scenario):
        store, _ = scenario
        called = []

        def scorer(pairs):  # pragma: no cover - must not run
            called.append(pairs)
            return [0.0] * len(pairs)

        retriever, _ = make_retriever(store, rerank=False, scorer=scorer)
        retriever.search("where is the retry logic for http requests")
        assert called == []

    def test_rerank_enabled_reorders(self, scenario):
        """Pure-CE mode (blend off): the cross-encoder fully controls order."""
        store, chunks = scenario

        def scorer(pairs):
            # rank backoff_delay above everything else
            return [10.0 if "backoff_delay" in text else -10.0 for _, text in pairs]

        retriever, _ = make_retriever(
            store, rerank=True, expansion=False, scorer=scorer, blend=False
        )
        packed = retriever.search("where is the retry logic for http requests")
        assert packed.results[0].chunk.chunk_id == chunks["backoff"].chunk_id

    def test_rerank_blend_keeps_vector_strong_chunk(self, scenario):
        """Default blended mode: a chunk the embedder loves survives a CE
        demotion (rank fusion of CE order with vector order)."""
        store, chunks = scenario

        def scorer(pairs):
            # CE hates the retry chunk, loves an unrelated one
            return [
                -10.0 if "retry_request" in text else 10.0 for _, text in pairs
            ]

        retriever, _ = make_retriever(
            store, rerank=True, expansion=False, scorer=scorer, blend=True
        )
        packed = retriever.search("where is the retry logic for http requests")
        top3 = [r.chunk.chunk_id for r in packed.results[:3]]
        assert chunks["retry"].chunk_id in top3, (
            "vector-top chunk must not be buried by a hostile CE in blend mode"
        )

    def test_rerank_pool_includes_vector_head_beyond_fused_window(self, tmp_path):
        """A chunk at vector rank 1 that BM25 never matches must still reach
        the CE pool even with a tiny rerank_top (the union-pool guarantee)."""
        store, chunks = build_store(tmp_path / "pool.db")
        try:
            seen = []

            def scorer(pairs):
                seen.extend(passage for _, passage in pairs)
                return [0.0] * len(pairs)

            config = RetrievalConfig(
                rerank_enabled=True, expansion_enabled=False, rerank_top=2,
                rerank_channel_head=2,
            )
            encoder = StubEncoder()
            embedder = EmbeddingEngine(store, "stub-model", encoder=encoder)
            all_chunks = []
            for blob in (BLOB_HTTP, BLOB_ROUTES, BLOB_API):
                all_chunks.extend(store.chunks_for_blob(blob))
            embedder.embed_chunks(all_chunks)
            retriever = HybridRetriever(
                store, embedder, config=config,
                reranker=CrossEncoderReranker("stub", scorer=scorer),
            )
            # bag-of-words stub: only the retry chunk shares 'backoff' via code
            retriever.search("backoff retries pauses growing exponentially")
            assert seen, "reranker saw no candidates"
            # vector head is in the CE pool regardless of the fused window
            vec_top = store.vector_search(
                embedder.embed_query("backoff retries pauses growing exponentially"), 1
            )[0][0]
            top_chunk = store.get_chunk(vec_top)
            assert any(top_chunk.breadcrumb in passage for passage in seen), (
                "vector-rank-1 chunk never reached the cross-encoder"
            )
        finally:
            store.close()

    def test_expansion_adds_discounted_neighbors(self, scenario):
        store, chunks = scenario
        retriever, _ = make_retriever(store, expansion=True)
        packed = retriever.search("where is the retry logic for http requests",
                                  budget_tokens=8000)
        by_id = {r.chunk.chunk_id: r for r in packed.results}
        retry = by_id[chunks["retry"].chunk_id]
        # backoff_delay is called by retry_request -> expansion candidate
        backoff = by_id.get(chunks["backoff"].chunk_id)
        expansions = [r for r in packed.results if r.source is RetrievalSource.EXPANSION]
        assert backoff is not None or expansions, "no expansion results attached"
        if backoff is not None and backoff.source is RetrievalSource.EXPANSION:
            assert backoff.score <= retry.score * 0.6 + 1e-9

    def test_expansion_disabled(self, scenario):
        store, _ = scenario
        retriever, _ = make_retriever(store, expansion=False)
        packed = retriever.search("where is the retry logic for http requests")
        assert all(r.source is not RetrievalSource.EXPANSION for r in packed.results)


class TestStructuralLookups:
    def test_get_definition(self, scenario):
        store, chunks = scenario
        retriever, _ = make_retriever(store)
        results = retriever.get_definition("retry_request")
        assert len(results) == 1
        assert results[0].chunk.chunk_id == chunks["retry"].chunk_id
        assert "definition" in results[0].rationale

    def test_get_definition_unknown_symbol(self, scenario):
        store, _ = scenario
        retriever, _ = make_retriever(store)
        assert retriever.get_definition("no_such_symbol") == []

    def test_get_callers_ranked_with_rationale(self, scenario):
        store, chunks = scenario
        retriever, _ = make_retriever(store)
        callers = retriever.get_callers("retry_request")
        ids = [r.chunk.chunk_id for r in callers]
        assert set(ids) == {chunks["create"].chunk_id, chunks["fetch"].chunk_id}
        assert all(r.rationale and "calls `retry_request`" in r.rationale for r in callers)
        # scores strictly ordered
        assert all(callers[i].score >= callers[i + 1].score for i in range(len(callers) - 1))

    def test_get_callers_respects_limit(self, scenario):
        store, _ = scenario
        retriever, _ = make_retriever(store)
        assert len(retriever.get_callers("retry_request", limit=1)) == 1

    def test_get_references_empty_when_no_reference_edges(self, scenario):
        store, _ = scenario
        retriever, _ = make_retriever(store)
        assert retriever.get_references("retry_request") == []

    def test_expand_roundtrip(self, scenario):
        store, chunks = scenario
        retriever, _ = make_retriever(store)
        packed = retriever.search("retry_request")
        expanded = retriever.expand(packed.results[0].expand_id)
        assert expanded is not None
        assert expanded.chunk.chunk_id == chunks["retry"].chunk_id
        assert expanded.chunk.code == chunks["retry"].code

    def test_expand_unknown_id_returns_none(self, scenario):
        store, _ = scenario
        retriever, _ = make_retriever(store)
        assert retriever.expand("f" * 40 + ":0:1") is None


class TestInactiveBlobs:
    def test_inactive_blob_excluded_everywhere(self, scenario):
        store, chunks = scenario
        retriever, _ = make_retriever(store)
        store.set_blobs_active([BLOB_HTTP], False)
        assert retriever.get_definition("retry_request") == []
        packed = retriever.search("where is the retry logic for http requests")
        assert chunks["retry"].chunk_id not in {r.chunk.chunk_id for r in packed.results}
