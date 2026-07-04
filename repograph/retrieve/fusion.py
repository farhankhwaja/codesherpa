"""Reciprocal Rank Fusion (Cormack et al., 2009; CLAUDE.md §7.5.3).

``score(d) = sum_i 1 / (k + rank_i(d))`` with k = 60 and 1-based ranks,
summed over every ranked list the document appears in.
"""

from __future__ import annotations

from collections.abc import Sequence


def rrf_fuse(
    rank_lists: Sequence[Sequence[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse ranked id lists into ``[(id, rrf_score)]``, best first.

    Each inner list is ordered best-to-worst; ids may appear in any number of
    lists. Ties break lexicographically by id so output is deterministic.
    """
    if k <= 0:
        raise ValueError(f"rrf k must be positive, got {k}")
    scores: dict[str, float] = {}
    for ranked in rank_lists:
        seen: set[str] = set()
        for rank, doc_id in enumerate(ranked, start=1):
            if doc_id in seen:  # ignore duplicates within one list
                continue
            seen.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
