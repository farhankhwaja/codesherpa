"""Query-focused passage selection for cross-encoder reranking.

cAST chunks are frequently whole files (small modules merge into one chunk),
but the cross-encoder can only afford ~700 chars on CPU (§13 latency gate).
Blind head-truncation hides code deeper in the chunk from the reranker — a
relevant function past the cap becomes invisible and the chunk is misranked.

Instead, score line-window candidates by query-term overlap and hand the CE
``breadcrumb + best window``. Deterministic and cheap: pure string ops over
at most ``rerank_top`` chunks per query. (§10 remedy: "improve chunk
breadcrumbs / query preprocessing" — see DECISIONS.md.)
"""

from __future__ import annotations

import re

from repograph.retrieve.router import split_identifier

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def query_terms(query: str) -> set[str]:
    """Lowercased content terms of a query, including identifier word-parts."""
    terms: set[str] = set()
    for token in _TOKEN_RE.findall(query):
        terms.add(token.lower())
        terms.update(split_identifier(token))
    return {t for t in terms if len(t) > 2}


def focus_passage(
    terms: set[str],
    breadcrumb: str,
    code: str,
    max_chars: int,
) -> str:
    """``breadcrumb + newline + best window of code`` within ``max_chars``.

    The window is chosen by distinct query-term hits (identifier-split,
    case-insensitive), tie-broken toward the head of the chunk (headers and
    early definitions are the best default context). If the whole chunk fits,
    it is returned unmodified.
    """
    budget = max(0, max_chars - len(breadcrumb) - 1)
    if len(code) <= budget or budget == 0:
        return f"{breadcrumb}\n{code[:budget]}"

    lines = code.splitlines(keepends=True)
    # per-line distinct-term hit sets (identifier-split, lowercase)
    line_terms: list[set[str]] = []
    for line in lines:
        found: set[str] = set()
        for token in _TOKEN_RE.findall(line):
            lower = token.lower()
            if lower in terms:
                found.add(lower)
            for part in split_identifier(token):
                if part in terms:
                    found.add(part)
        line_terms.append(found)

    best_start, best_score = 0, (-1, 0)
    n = len(lines)
    for start in range(n):
        size = 0
        covered: set[str] = set()
        end = start
        while end < n and size + len(lines[end]) <= budget:
            size += len(lines[end])
            covered |= line_terms[end]
            end += 1
        if end == start:  # single over-long line
            covered = line_terms[start]
        score = (len(covered), -start)  # more coverage, then earlier window
        if score > best_score:
            best_score, best_start = score, start

    window: list[str] = []
    size = 0
    for line in lines[best_start:]:
        if size + len(line) > budget:
            break
        window.append(line)
        size += len(line)
    if not window:  # single line longer than the budget
        window = [lines[best_start][:budget]]
    return f"{breadcrumb}\n{''.join(window)}"
