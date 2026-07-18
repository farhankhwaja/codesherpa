"""Eval-harness wiring (codesherpa/retrieve/evalfactory.py).

Regression cover for a config-aliasing bug: SingleChannelRetriever disables
reranking/expansion to build a single-channel baseline, but did so by
mutating the RetrievalConfig it was HANDED. Callers that reuse one config
across retrievers — the natural way to write a comparison script — silently
got reranking disabled for every retriever built afterwards, which quietly
corrupts measurements rather than failing loudly.
"""

from __future__ import annotations

from codesherpa.retrieve.config import RetrievalConfig
from codesherpa.retrieve.evalfactory import SingleChannelRetriever


class _StubStore:
    """Minimal stand-in: an explicit blend weight avoids the auto-blend path,
    so no store access happens during construction."""

    def active_blobs(self):  # pragma: no cover - guard against silent auto path
        raise AssertionError("auto-blend path should not run with an explicit weight")


def _config() -> RetrievalConfig:
    # explicit weight => HybridRetriever.__init__ never calls active_blobs()
    return RetrievalConfig(rerank_blend_vector_weight=1.0)


def test_single_channel_retriever_does_not_mutate_caller_config() -> None:
    cfg = _config()
    assert cfg.rerank_enabled is True
    assert cfg.expansion_enabled is True

    SingleChannelRetriever(_StubStore(), None, "bm25", config=cfg)

    assert cfg.rerank_enabled is True, "caller's config was mutated (rerank)"
    assert cfg.expansion_enabled is True, "caller's config was mutated (expansion)"


def test_single_channel_retriever_still_disables_rerank_for_itself() -> None:
    """The baseline behaviour itself must not regress: the retriever's OWN
    config still has rerank/expansion off (§13 compares packed channels)."""
    retriever = SingleChannelRetriever(_StubStore(), None, "vector", config=_config())

    assert retriever._config.rerank_enabled is False
    assert retriever._config.expansion_enabled is False


def test_shared_config_across_retrievers_keeps_rerank_for_the_second() -> None:
    """The exact real-world shape: build a single-channel baseline, then a
    hybrid retriever from the SAME config object."""
    cfg = _config()
    SingleChannelRetriever(_StubStore(), None, "bm25", config=cfg)

    from codesherpa.retrieve.retriever import HybridRetriever

    hybrid = HybridRetriever(_StubStore(), None, config=cfg)
    assert hybrid._config.rerank_enabled is True
    assert hybrid._config.expansion_enabled is True


def test_other_config_fields_survive_the_baseline_copy() -> None:
    """Copying must preserve every other tunable, not reset to defaults."""
    cfg = RetrievalConfig(
        rerank_blend_vector_weight=2.0,
        bm25_top=17,
        default_budget_tokens=1234,
        embed_model="some/other-model",
    )
    retriever = SingleChannelRetriever(_StubStore(), None, "bm25", config=cfg)

    assert retriever._config.bm25_top == 17
    assert retriever._config.default_budget_tokens == 1234
    assert retriever._config.embed_model == "some/other-model"
    assert retriever._config.rerank_blend_vector_weight == 2.0
