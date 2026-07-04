"""Budget packer tests: never exceeds budget, dedups overlaps/symbols."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from codesherpa.contracts.types import RetrievalSource
from codesherpa.retrieve.pack import pack_results
from tests.support.factories import make_chunk, make_result


def test_never_exceeds_budget_exact():
    results = [
        make_result(byte_start=i * 100, byte_end=i * 100 + 50, token_count=30,
                    breadcrumb=f"f.py :: fn{i}", score=1.0)
        for i in range(10)
    ]
    packed = pack_results("q", results, budget_tokens=100)
    assert packed.total_tokens <= 100
    assert len(packed.results) == 3  # 3 * 30 = 90; a 4th would hit 120


def test_zero_budget_packs_nothing():
    packed = pack_results("q", [make_result()], budget_tokens=0)
    assert packed.results == ()
    assert packed.total_tokens == 0


def test_greedy_density_order():
    dense = make_result(byte_start=0, byte_end=10, breadcrumb="a.py :: small",
                        score=1.0, token_count=10)
    fat = make_result(byte_start=100, byte_end=900, breadcrumb="a.py :: big",
                      score=1.5, token_count=400)
    packed = pack_results("q", [fat, dense], budget_tokens=50)
    # only the dense one fits; fat is skipped, not blocking
    assert [r.chunk.breadcrumb for r in packed.results] == ["a.py :: small"]


def test_overlapping_ranges_same_blob_deduplicated():
    blob = "c" * 40
    outer = make_result(blob_hash=blob, byte_start=0, byte_end=200,
                        breadcrumb="m.py :: Class", score=2.0, token_count=50)
    inner = make_result(blob_hash=blob, byte_start=50, byte_end=150,
                        breadcrumb="m.py :: Class :: def m()", score=1.0, token_count=25)
    packed = pack_results("q", [outer, inner], budget_tokens=1000)
    assert len(packed.results) == 1
    assert packed.results[0].chunk.byte_start == 0


def test_same_ranges_different_blobs_not_deduplicated():
    a = make_result(blob_hash="a" * 40, byte_start=0, byte_end=100,
                    breadcrumb="a.py :: f", token_count=10)
    b = make_result(blob_hash="d" * 40, byte_start=0, byte_end=100,
                    breadcrumb="b.py :: g", token_count=10)
    packed = pack_results("q", [a, b], budget_tokens=1000)
    assert len(packed.results) == 2


def test_same_symbol_chunks_deduplicated():
    # same breadcrumb (same symbol) from two different blobs (e.g. two versions)
    v1 = make_result(blob_hash="e" * 40, byte_start=0, byte_end=100,
                     breadcrumb="m.py :: def f()", score=2.0, token_count=10)
    v2 = make_result(blob_hash="f" * 40, byte_start=0, byte_end=100,
                     breadcrumb="m.py :: def f()", score=1.0, token_count=10)
    packed = pack_results("q", [v1, v2], budget_tokens=1000)
    assert len(packed.results) == 1
    assert packed.results[0].score == 2.0


def test_metadata_preserved():
    r = make_result(source=RetrievalSource.VECTOR)
    packed = pack_results("my query", [r], budget_tokens=4000)
    assert packed.query == "my query"
    assert packed.budget_tokens == 4000
    assert packed.results[0].source is RetrievalSource.VECTOR
    assert packed.results[0].expand_id == r.chunk.chunk_id


def test_negative_budget_raises():
    with pytest.raises(ValueError):
        pack_results("q", [], budget_tokens=-1)


@given(
    budget=st.integers(min_value=0, max_value=500),
    items=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=50),   # start slot
            st.integers(min_value=1, max_value=200),  # token cost
            st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
        ),
        max_size=30,
    ),
)
def test_property_never_exceeds_budget(budget, items):
    results = [
        make_result(
            blob_hash="9" * 40,
            byte_start=start * 100,
            byte_end=start * 100 + 99,
            breadcrumb=f"p.py :: s{start}",
            score=score,
            token_count=cost,
        )
        for start, cost, score in items
    ]
    packed = pack_results("q", results, budget_tokens=budget)
    assert packed.total_tokens <= budget
    assert packed.total_tokens == sum(max(1, r.token_count) for r in packed.results)
