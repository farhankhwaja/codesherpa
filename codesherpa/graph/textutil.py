"""Small text helpers shared by graph queries and the MCP server."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Cheap, model-agnostic token estimate (~4 chars/token for code).

    Used for budget accounting in responses; deliberately conservative and
    deterministic — never calls a tokenizer so it stays dependency-free.
    """
    return max(1, (len(text) + 3) // 4)
