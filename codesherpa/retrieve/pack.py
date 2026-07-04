"""Budget-aware packing (CLAUDE.md §7.5.6).

Greedy by ``score / token_count``; deduplicates overlapping byte ranges within
a blob and same-symbol chunks (same breadcrumb); never exceeds the budget.
"""

from __future__ import annotations

from collections.abc import Iterable

from codesherpa.contracts.types import PackedContext, SearchResult


def _overlaps(a: SearchResult, b: SearchResult) -> bool:
    if a.chunk.blob_hash != b.chunk.blob_hash:
        return False
    return a.chunk.byte_start < b.chunk.byte_end and b.chunk.byte_start < a.chunk.byte_end


def pack_results(
    query: str,
    candidates: Iterable[SearchResult],
    budget_tokens: int,
) -> PackedContext:
    """Pack scored candidates into a :class:`PackedContext` under the budget.

    Candidates are *selected* in descending ``score / token_count`` density
    (ties: higher score, then chunk id, for determinism) so the budget is
    filled with maximum total usefulness. A candidate is skipped when it
    would exceed the remaining budget, when its byte range overlaps an
    already-packed chunk of the same blob, or when a chunk with the same
    breadcrumb (same symbol) is already packed. The selected results are
    *returned* ordered by descending score — that is the usefulness order a
    calling agent reads top-down.
    """
    if budget_tokens < 0:
        raise ValueError(f"budget_tokens must be >= 0, got {budget_tokens}")

    ordered = sorted(
        candidates,
        key=lambda r: (
            -(r.score / max(1, r.token_count)),
            -r.score,
            r.chunk.chunk_id,
        ),
    )

    packed: list[SearchResult] = []
    seen_breadcrumbs: set[str] = set()
    total = 0
    for cand in ordered:
        cost = max(1, cand.token_count)
        if total + cost > budget_tokens:
            continue  # keep trying smaller candidates
        if cand.chunk.breadcrumb and cand.chunk.breadcrumb in seen_breadcrumbs:
            continue
        if any(_overlaps(cand, kept) for kept in packed):
            continue
        packed.append(cand)
        seen_breadcrumbs.add(cand.chunk.breadcrumb)
        total += cost

    packed.sort(key=lambda r: (-r.score, r.chunk.chunk_id))
    return PackedContext(
        query=query,
        budget_tokens=budget_tokens,
        total_tokens=total,
        results=tuple(packed),
    )
