"""Deterministic token-count estimation for budget packing.

We deliberately avoid a tokenizer dependency (none is on the approved stack,
CLAUDE.md §6). Code averages roughly 3.5-4 characters per token across common
BPE vocabularies; we use ceil(len/4) plus a small per-line overhead so the
estimate errs slightly high — the packer must NEVER exceed the caller's
budget, so over-estimating is the safe direction. See DECISIONS.md D5.

TODO(upgrade): swap in exact token counting if a tokenizer dependency is
ever added to the approved stack.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimated token cost of ``text``. Deterministic, always >= 1."""
    if not text:
        return 1
    # ceil(len/4) + one token per newline (newlines are usually own tokens)
    return max(1, -(-len(text) // 4) + text.count("\n") // 4)


def result_token_cost(breadcrumb: str, code: str) -> int:
    """Token cost of one packed result: breadcrumb header + raw code."""
    return estimate_tokens(breadcrumb) + estimate_tokens(code)
