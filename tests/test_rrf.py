"""RRF fusion tests on hand-built rank lists (Phase 3 criterion)."""

from __future__ import annotations

import pytest

from repograph.retrieve.fusion import rrf_fuse


def test_single_list_preserves_order():
    fused = rrf_fuse([["a", "b", "c"]])
    assert [d for d, _ in fused] == ["a", "b", "c"]
    assert fused[0][1] == pytest.approx(1 / 61)
    assert fused[2][1] == pytest.approx(1 / 63)


def test_doc_in_multiple_lists_beats_single_list_top():
    # "x" is rank 2 in both lists: 1/62 + 1/62 > 1/61 (rank-1 in one list)
    fused = rrf_fuse([["a", "x"], ["b", "x"]])
    assert fused[0][0] == "x"
    assert fused[0][1] == pytest.approx(2 / 62)


def test_hand_computed_scores():
    # a: rank1 in L1, rank3 in L2 -> 1/61 + 1/63
    # b: rank2 in L1, rank1 in L2 -> 1/62 + 1/61
    # c: rank3 in L1 only        -> 1/63
    fused = dict(rrf_fuse([["a", "b", "c"], ["b", "d", "a"]]))
    assert fused["a"] == pytest.approx(1 / 61 + 1 / 63)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest.approx(1 / 63)
    assert fused["d"] == pytest.approx(1 / 62)


def test_custom_k():
    fused = rrf_fuse([["a"]], k=10)
    assert fused[0][1] == pytest.approx(1 / 11)


def test_ties_break_deterministically_by_id():
    fused = rrf_fuse([["b"], ["a"]])  # both rank 1 -> equal scores
    assert [d for d, _ in fused] == ["a", "b"]


def test_duplicates_within_one_list_count_once():
    fused = dict(rrf_fuse([["a", "a", "b"]]))
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 63)  # keeps its original rank


def test_empty_input():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_invalid_k_raises():
    with pytest.raises(ValueError):
        rrf_fuse([["a"]], k=0)
