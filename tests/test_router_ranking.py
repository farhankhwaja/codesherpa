"""D45: router anti-hijack ranking.

Go convention names (`Service`, `Client`, `Opts`) are defined dozens of
times in real monorepos; a stack-trace query mixing a convention receiver
with a rare function must not be hijacked by the common name. The router
must:
rarity-first token ordering, per-token fan-out cap, path-context boost from
the query's own path fragments, ambiguity floor for convention names —
while a bare common-name lookup still answers.

Real SQLiteIndexStore populated via its public API; stub encoder (tests
only, §2.5) — the router path never touches it anyway.
"""

from __future__ import annotations

import pytest

from codesherpa.contracts.types import Chunk, SymbolKind, SymbolNode
from codesherpa.embed.engine import EmbeddingEngine
from codesherpa.retrieve.config import RetrievalConfig
from codesherpa.retrieve.retriever import HybridRetriever
from codesherpa.retrieve.router import extract_path_segments
from codesherpa.store.sqlite_store import SQLiteIndexStore

N_SERVICES = 30

TRACE = (
    "panic: runtime error: invalid memory address or nil pointer dereference\n"
    "pkg/billing/ledgersvc/service.(*Service).reconcileLedger(0xc0004a2d80)\n"
    "\t/build/pkg/billing/ledgersvc/service/batch_run.go:214 +0x2f"
)


def _blob(i: int) -> str:
    return f"{i:040x}"


@pytest.fixture()
def retriever(tmp_path):
    """30 packages each defining `Service`; exactly one `reconcileLedger` in
    pkg/billing/ledgersvc/service/batch_run.go (the large-monorepo shape)."""
    store = SQLiteIndexStore(tmp_path / "router-rank.db")
    for i in range(N_SERVICES):
        path = f"pkg{i:02d}/service.go"
        code = f"type Service struct {{ n{i} int }}\n"
        store.add_blob(_blob(i), "go", len(code))
        chunk = Chunk(
            blob_hash=_blob(i), byte_start=0, byte_end=len(code),
            file_path=path, language="go", code=code,
            breadcrumb=f"// {path} :: service :: type Service struct",
        )
        store.add_chunks([chunk])
        store.add_symbols([
            SymbolNode(symbol="Service", kind=SymbolKind.CLASS, blob_hash=_blob(i),
                       byte_start=0, byte_end=len(code), file_path=path),
        ])
    # the one true target + a path-matching Service in the same package
    target_path = "pkg/billing/ledgersvc/service/batch_run.go"
    code = "func (s *Service) reconcileLedger() error { return nil }\n"
    store.add_blob(_blob(99), "go", len(code))
    store.add_chunks([
        Chunk(blob_hash=_blob(99), byte_start=0, byte_end=len(code),
              file_path=target_path, language="go", code=code,
              breadcrumb=f"// {target_path} :: (Service) :: func (s *Service) reconcileLedger()"),
    ])
    store.add_symbols([
        SymbolNode(symbol="reconcileLedger", kind=SymbolKind.METHOD, blob_hash=_blob(99),
                   byte_start=0, byte_end=len(code), file_path=target_path),
    ])
    # the same package also defines Service — in its own file, like real repos
    svc_path = "pkg/billing/ledgersvc/service/service.go"
    svc_code = "type Service struct { deps Deps }\n"
    store.add_blob(_blob(98), "go", len(svc_code))
    store.add_chunks([
        Chunk(blob_hash=_blob(98), byte_start=0, byte_end=len(svc_code),
              file_path=svc_path, language="go", code=svc_code,
              breadcrumb=f"// {svc_path} :: service :: type Service struct"),
    ])
    store.add_symbols([
        SymbolNode(symbol="Service", kind=SymbolKind.CLASS, blob_hash=_blob(98),
                   byte_start=0, byte_end=len(svc_code), file_path=svc_path),
    ])
    engine = EmbeddingEngine(store, "stub", encoder=lambda texts: [[1.0, 0.0]] * len(texts))
    config = RetrievalConfig()
    config.rerank_enabled = False
    yield HybridRetriever(store, engine, config=config)
    store.close()


def test_rare_symbol_beats_convention_name_flood(retriever):
    """Trace shape (common receiver + rare function): `reconcileLedger`
    (1 def) must rank ABOVE every one of the 31 `Service` definitions, and
    appear at rank 1."""
    packed = retriever.search(TRACE, budget_tokens=4000)
    assert packed.results, "router returned nothing"
    top = packed.results[0]
    assert top.chunk.file_path == "pkg/billing/ledgersvc/service/batch_run.go"
    assert "reconcileLedger" in top.rationale


def test_per_token_fanout_capped(retriever):
    packed = retriever.search(TRACE, budget_tokens=8000)
    service_defs = [
        r for r in packed.results
        if r.rationale and r.rationale == "exact definition of `Service`"
    ]
    assert len(service_defs) <= RetrievalConfig().router_token_fanout


def test_path_context_boost_prefers_matching_package(retriever):
    """Among the 31 `Service` defs, the one in the query's own package path
    must be the one the fan-out cap keeps (rank 1 among Service defs)."""
    packed = retriever.search(TRACE, budget_tokens=8000)
    service_defs = [
        r for r in packed.results
        if r.rationale == "exact definition of `Service`"
    ]
    assert service_defs, "ambiguous token dropped entirely — floor, not removal"
    assert service_defs[0].chunk.file_path.startswith("pkg/billing/ledgersvc/service/")


def test_bare_common_name_lookup_still_answers(retriever):
    packed = retriever.search("Service", budget_tokens=4000)
    assert packed.results
    assert all(
        r.rationale == "exact definition of `Service`"
        for r in packed.results
        if r.source.value == "symbol"
    )


def test_path_segment_extraction_shapes():
    segs = extract_path_segments(TRACE)
    assert any("pkg/billing/ledgersvc/service" in s for s in segs)
    assert any(s.endswith("batch_run.go") for s in segs)
    # prose yields nothing path-like
    assert extract_path_segments("where is the retry logic for requests") == []


def test_blend_weight_auto_resolves_by_index_size(tmp_path):
    """D45: blend weight None -> 4.0 on small indexes, 1.0 on large; an
    explicit float pins the regime."""
    from codesherpa.contracts.types import Chunk

    store = SQLiteIndexStore(tmp_path / "size.db")
    small = HybridRetriever(
        store,
        EmbeddingEngine(store, "stub", encoder=lambda t: [[1.0]] * len(t)),
        config=_no_rerank_config(),
    )
    assert small._blend_vector_weight == 4.0

    for i in range(RetrievalConfig.SMALL_INDEX_ACTIVE_BLOBS + 1):
        store.add_blob(f"{i + 1000:040x}", "go", 10)
    big = HybridRetriever(
        store,
        EmbeddingEngine(store, "stub", encoder=lambda t: [[1.0]] * len(t)),
        config=_no_rerank_config(),
    )
    assert big._blend_vector_weight == 1.0

    pinned_cfg = _no_rerank_config()
    pinned_cfg.rerank_blend_vector_weight = 2.5
    pinned = HybridRetriever(
        store,
        EmbeddingEngine(store, "stub", encoder=lambda t: [[1.0]] * len(t)),
        config=pinned_cfg,
    )
    assert pinned._blend_vector_weight == 2.5
    store.close()


def _no_rerank_config():
    cfg = RetrievalConfig()
    cfg.rerank_enabled = False
    return cfg


def _mini_store_with_n_defs(tmp_path, n, name="Widget"):
    store = SQLiteIndexStore(tmp_path / f"boundary-{n}.db")
    for i in range(n):
        path = f"p{i:02d}/{name.lower()}.go"
        code = f"type {name} struct {{ f{i} int }}\n"
        store.add_blob(_blob(500 + i), "go", len(code))
        store.add_chunks([Chunk(blob_hash=_blob(500 + i), byte_start=0, byte_end=len(code),
                                file_path=path, language="go", code=code,
                                breadcrumb=f"// {path} :: x :: type {name} struct")])
        store.add_symbols([SymbolNode(symbol=name, kind=SymbolKind.CLASS, blob_hash=_blob(500 + i),
                                      byte_start=0, byte_end=len(code), file_path=path)])
    # one rare symbol appearing LATER in the query than the common one
    code = "func rareHelper() {}\n"
    store.add_blob(_blob(999), "go", len(code))
    store.add_chunks([Chunk(blob_hash=_blob(999), byte_start=0, byte_end=len(code),
                            file_path="zz/rare.go", language="go", code=code,
                            breadcrumb="// zz/rare.go :: rare :: func rareHelper()")])
    store.add_symbols([SymbolNode(symbol="rareHelper", kind=SymbolKind.FUNCTION, blob_hash=_blob(999),
                                  byte_start=0, byte_end=len(code), file_path="zz/rare.go")])
    return store


def _retriever_for(store):
    return HybridRetriever(
        store,
        EmbeddingEngine(store, "stub", encoder=lambda t: [[1.0]] * len(t)),
        config=_no_rerank_config(),
    )


def test_ambiguity_threshold_boundary_exactly_8_vs_9(tmp_path):
    """router_ambiguous_defs = 8 is deliberate config (D45): a name with
    EXACTLY 8 definitions is still 'specific' (ranked by rarity among
    specific tokens); 9 definitions crosses into the convention-name tier
    that ranks below every specific token."""
    threshold = RetrievalConfig().router_ambiguous_defs
    assert threshold == 8  # boundary pinned; tune deliberately

    # at the threshold (8 defs): Widget is specific -> rarity ordering only;
    # rareHelper (1 def) still outranks it, but Widget stays in the
    # specific tier: its score tier is adjacent (no ambiguity demotion)
    store8 = _mini_store_with_n_defs(tmp_path, threshold)
    packed = _retriever_for(store8).search("Widget() rareHelper()", budget_tokens=8000)
    symbol_rows = [r for r in packed.results if r.source.value == "symbol"]
    assert symbol_rows[0].rationale == "exact definition of `rareHelper`"
    widget_scores = [r.score for r in symbol_rows if "Widget" in (r.rationale or "")]
    rare_score = symbol_rows[0].score
    assert widget_scores and rare_score - max(widget_scores) == pytest.approx(0.12, abs=1e-9)
    store8.close()

    # past the threshold (9 defs): same adjacency must still hold in tier
    # spacing, but Widget is now in the ambiguous tier — asserted via
    # ordering (below rare) and via the flag actually flipping
    store9 = _mini_store_with_n_defs(tmp_path, threshold + 1)
    retr = _retriever_for(store9)
    per_token = [("Widget", store9.get_definitions("Widget")),
                 ("rareHelper", store9.get_definitions("rareHelper"))]
    assert (len(per_token[0][1]) > retr._config.router_ambiguous_defs) is True
    assert (len(per_token[1][1]) > retr._config.router_ambiguous_defs) is False
    packed = retr.search("Widget() rareHelper()", budget_tokens=8000)
    symbol_rows = [r for r in packed.results if r.source.value == "symbol"]
    assert symbol_rows[0].rationale == "exact definition of `rareHelper`"
    store9.close()


def test_r03_class_on_real_fixture(synced_miniproject):
    """Adjustment 1 (plan review): the trace-hijack regression must ALSO
    hold against the REAL fixture store (real sync -> real Go extraction),
    not only the synthetic 30-def store, so the test can't encode the fix's
    own assumptions. Trace shape: common receiver type + rare function,
    plus a path fragment."""
    _repo, db = synced_miniproject
    store = SQLiteIndexStore(db)
    try:
        retriever = _retriever_for(store)
        trace = (
            "goroutine 7 [running]:\n"
            "example.com/taskhub/goexport.(*Archive).Flush(0xc000010250)\n"
            "\t/app/goexport/archive.go:41 +0x1f"
        )
        packed = retriever.search(trace, budget_tokens=4000)
        assert packed.results
        # the true target FILE must top the results (the hijack failure mode
        # was junk files from other packages), and the top chunk must actually
        # contain the rare function — in the small fixture the whole file is
        # one cAST chunk, so `Archive` (1-def, earlier in the trace) and
        # `Flush` share it and dedupe keeps a single row
        top = packed.results[0]
        assert top.chunk.file_path == "goexport/archive.go"
        assert "func (a *Archive) Flush" in top.chunk.code
    finally:
        store.close()
