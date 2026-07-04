"""Selective-retrieval router (Repoformer-inspired; CLAUDE.md §7.5.1).

Extract identifier-like tokens from the query. If any token exactly matches a
symbol definition, the retriever answers from the symbol graph directly (< 50
ms, no dense search). To avoid hijacking natural-language queries whose plain
English words happen to collide with a symbol name (e.g. "connect"), a token
only qualifies as identifier-like when it carries identifier morphology:
snake_case, camelCase/PascalCase, a digit — or when it is the entire query.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_CAMEL_RE = re.compile(r"[a-z][A-Z]|[A-Z][a-z0-9]*[A-Z]")


def _looks_like_identifier(token: str) -> bool:
    """Identifier morphology: snake_case, camelCase/PascalCase, or digits."""
    if "_" in token:
        return True
    if any(ch.isdigit() for ch in token):
        return True
    return bool(_CAMEL_RE.search(token))


def extract_identifier_tokens(query: str) -> list[str]:
    """Identifier-like tokens from ``query``, in order, deduplicated.

    A bare single-word query (e.g. ``slugify``) is always treated as a
    candidate identifier even without snake/camel morphology, because a
    one-token query is almost certainly a symbol lookup.
    """
    tokens = _TOKEN_RE.findall(query)
    stripped = query.strip()
    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        if tok in seen:
            continue
        if _looks_like_identifier(tok) or tok == stripped:
            seen.add(tok)
            out.append(tok)
    return out


def split_identifier(token: str) -> list[str]:
    """Split an identifier into lowercase words (camelCase/snake_case aware).

    Used for query preprocessing on the dense/lexical path, e.g.
    ``fetchWithRetry`` -> ``["fetch", "with", "retry"]``.
    """
    parts = re.split(r"[_\W]+", token)
    words: list[str] = []
    for part in parts:
        if not part:
            continue
        # split camelCase / PascalCase / ALLCAPS runs
        for m in re.finditer(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", part):
            words.append(m.group(0).lower())
    return words
