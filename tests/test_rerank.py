"""Cross-encoder reranker wrapper tests (stub scorer; toggling is exercised
end-to-end in test_retriever.py)."""

from __future__ import annotations

import pytest

from codesherpa.retrieve.rerank import CrossEncoderReranker


def make_reranker(scores_by_text):
    def scorer(pairs):
        return [scores_by_text[text] for _, text in pairs]

    return CrossEncoderReranker("stub-reranker", scorer=scorer)


def test_reorders_by_score_descending():
    rr = make_reranker({"weak": -2.0, "strong": 3.0, "mid": 0.5})
    out = rr.rerank("q", [("a", "weak"), ("b", "strong"), ("c", "mid")])
    assert [pid for pid, _ in out] == ["b", "c", "a"]


def test_scores_are_sigmoid_normalized():
    rr = make_reranker({"neg": -100.0, "zero": 0.0, "pos": 100.0})
    out = dict(rr.rerank("q", [("a", "neg"), ("b", "zero"), ("c", "pos")]))
    assert out["a"] == pytest.approx(0.0, abs=1e-6)
    assert out["b"] == pytest.approx(0.5)
    assert out["c"] == pytest.approx(1.0, abs=1e-6)
    assert all(0.0 <= s <= 1.0 for s in out.values())


def test_truncates_passages_to_max_chars():
    seen = []

    def scorer(pairs):
        seen.extend(pairs)
        return [0.0] * len(pairs)

    rr = CrossEncoderReranker("stub", max_chars=10, scorer=scorer)
    rr.rerank("q", [("a", "x" * 100)])
    assert seen[0][1] == "x" * 10


def test_empty_input():
    called = []

    def scorer(pairs):  # pragma: no cover - must not be called
        called.append(pairs)
        return []

    rr = CrossEncoderReranker("stub", scorer=scorer)
    assert rr.rerank("q", []) == []
    assert called == []


def test_score_count_mismatch_raises():
    rr = CrossEncoderReranker("stub", scorer=lambda pairs: [0.0])
    with pytest.raises(RuntimeError):
        rr.rerank("q", [("a", "t1"), ("b", "t2")])


def test_deterministic_tie_break_by_id():
    rr = make_reranker({"same": 1.0})
    out = rr.rerank("q", [("b", "same"), ("a", "same")])
    assert [pid for pid, _ in out] == ["a", "b"]
