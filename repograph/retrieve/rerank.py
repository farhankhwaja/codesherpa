"""Cross-encoder reranking (CLAUDE.md §7.5.4). Toggleable via config.

Scores are passed through a sigmoid so downstream packing sees positive
(0, 1) scores regardless of the cross-encoder's logit range.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from repograph.retrieve.config import default_cache_dir

PairScorer = Callable[[list[tuple[str, str]]], list[float]]
"""Batch (query, passage) pairs -> raw scores. Injected in tests."""


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


class CrossEncoderReranker:
    """Lazy-loading CrossEncoder wrapper returning sigmoid-normalized scores."""

    def __init__(
        self,
        model_name: str,
        *,
        max_chars: int = 2000,
        cache_dir: Optional[Path] = None,
        scorer: Optional[PairScorer] = None,
    ) -> None:
        self.model_name = model_name
        self.max_chars = max_chars
        self._cache_dir = cache_dir or default_cache_dir()
        self._scorer = scorer

    def _load_scorer(self) -> PairScorer:
        if self._scorer is None:
            from sentence_transformers import CrossEncoder  # lazy

            model = CrossEncoder(
                self.model_name,
                cache_folder=str(self._cache_dir),
                device="cpu",
            )

            def score(pairs: list[tuple[str, str]]) -> list[float]:
                return [
                    float(s)
                    for s in model.predict(pairs, batch_size=64, show_progress_bar=False)
                ]

            self._scorer = score
        return self._scorer

    def rerank(
        self,
        query: str,
        passages: list[tuple[str, str]],
    ) -> list[tuple[str, float]]:
        """Rerank ``(id, text)`` passages -> ``[(id, score)]``, best first.

        Passage text is truncated to ``max_chars`` before scoring (latency
        guard); ties break by id for determinism.
        """
        if not passages:
            return []
        scorer = self._load_scorer()
        pairs = [(query, text[: self.max_chars]) for _, text in passages]
        raw = scorer(pairs)
        if len(raw) != len(passages):
            raise RuntimeError(
                f"reranker returned {len(raw)} scores for {len(passages)} passages"
            )
        scored = [(pid, _sigmoid(s)) for (pid, _), s in zip(passages, raw)]
        return sorted(scored, key=lambda item: (-item[1], item[0]))
