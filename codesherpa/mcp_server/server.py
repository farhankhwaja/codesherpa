"""sherpa MCP server (stdio) — CLAUDE.md §7.6.

Seven tools over a :class:`Retriever` (frozen contract) plus git history.
Responses are compact by default — token frugality is the product. Full
context is fetched on demand via ``expand`` with the ``expand_id`` handles
returned by every other tool.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from pathlib import Path
from typing import Optional, Union

from mcp.server.fastmcp import FastMCP

from codesherpa import gain
from codesherpa.contracts.index_contract import IndexStore
from codesherpa.contracts.retrieval_contract import Retriever
from codesherpa.contracts.types import SearchResult
from codesherpa.graph.gitio import git_output
from codesherpa.graph.recent import recent_changes as _recent_changes
from codesherpa.graph.textutil import estimate_tokens

__all__ = ["create_server"]

logger = logging.getLogger(__name__)

_MAX_SNIPPET_CHARS = 700  # graph tools show a taste; expand() shows all


def _compact(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _missing_embeddings(store: Optional[IndexStore]) -> Optional[int]:
    """Active chunks without vectors, or None when it cannot be known cheaply.

    The server never *computes* embeddings (init/sync own that — Phase 5
    §3e); it only reports how far along the semantic index is so a calling
    agent understands degraded results while the index is warming.
    """
    if store is None:
        return None
    try:
        from codesherpa.retrieve.warm import missing_embeddings

        return missing_embeddings(store)
    except Exception:
        return None


def _result_row(result: SearchResult, with_code: bool = False) -> dict:
    chunk = result.chunk
    row: dict = {
        "path": chunk.file_path,
        "bytes": [chunk.byte_start, chunk.byte_end],
        "breadcrumb": chunk.breadcrumb,
        "score": round(result.score, 3),
        "why": result.source.value,
        "expand_id": result.expand_id,
        "tokens": result.token_count,
    }
    if result.rationale:
        row["rationale"] = result.rationale
    if with_code:
        code = chunk.code
        if len(code) > _MAX_SNIPPET_CHARS:
            code = code[:_MAX_SNIPPET_CHARS] + f"\n… truncated; expand({result.expand_id})"
        row["code"] = code
    return row


def create_server(
    retriever: Retriever,
    repo_path: Union[str, Path],
    store: Optional[IndexStore] = None,
) -> FastMCP:
    """Build the MCP server over an already-wired retriever and repo."""
    repo = str(repo_path)
    mcp = FastMCP(
        "sherpa",
        instructions=(
            "Git-native structural index of this repository. Prefer these tools "
            "over grep/reading whole files: they return the most relevant "
            "function-level chunks under a token budget, with expand_id handles "
            "for full context on demand."
        ),
    )

    # Usage analytics (`sherpa gain`): ONE wrapper at the dispatch point —
    # never per-tool code. Local-only, honors config.analytics, and logging
    # can NEVER fail a query: any recording error is swallowed to a warning.
    analytics_on = store is not None and bool(
        getattr(getattr(retriever, "_config", None), "analytics", True)
    )

    def _tool(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            text = fn(*args, **kwargs)
            if analytics_on:
                try:
                    gain.record_call(
                        store,
                        retriever,
                        fn.__name__,
                        kwargs,
                        text,
                        (time.perf_counter() - start) * 1000.0,
                    )
                except Exception:
                    logger.warning(
                        "sherpa gain: usage recording failed for %s (query unaffected)",
                        fn.__name__,
                        exc_info=True,
                    )
            return text

        return mcp.tool()(wrapper)

    @_tool
    def search_code(
        query: str, budget_tokens: int = 1500, include_code: bool = False
    ) -> str:
        """Hybrid code search under a token budget. Use this INSTEAD of grep +
        reading whole files: it returns the most relevant function-level
        matches across the repo (lexical + semantic + symbol-aware), already
        deduplicated. COMPACT-FIRST: each result is a signature/breadcrumb
        row with an expand_id — call expand(expand_id) for the full body of
        the hits that matter (usually 1-2), instead of paying for code you
        will not read. Set include_code=true only when you know you need
        bodies for most results."""
        packed = retriever.search(query, budget_tokens=budget_tokens)
        results = list(packed.results)
        missing = _missing_embeddings(store)
        # the budget bounds the *response*: the JSON envelope (breadcrumbs,
        # expand_ids, metadata) counts too, so trim trailing results to fit
        while True:
            payload = {
                "query": packed.query,
                "budget_tokens": packed.budget_tokens,
                "total_tokens": sum(r.token_count for r in results),
                "results": [_result_row(r, with_code=include_code) for r in results],
            }
            if missing:
                payload["warming"] = {
                    "missing_embeddings": missing,
                    "hint": (
                        "semantic index incomplete — results may be lexical/"
                        "symbol-only; run `sherpa sync` to finish embedding"
                    ),
                }
            text = _compact(payload)
            if estimate_tokens(text) <= budget_tokens or not results:
                if len(results) < len(packed.results):
                    payload["truncated"] = len(packed.results) - len(results)
                    text = _compact(payload)
                return text
            results.pop()

    @_tool
    def get_definition(symbol: str) -> str:
        """Jump straight to where a symbol (function/class/method/const) is
        defined. Faster and more precise than grep for a name you already
        know: returns the defining chunk(s) with signature and file path."""
        results = retriever.get_definition(symbol)
        return _compact({"symbol": symbol, "results": [_result_row(r, with_code=True) for r in results]})

    @_tool
    def get_callers(symbol: str, limit: int = 10) -> str:
        """Who calls this function/method? Ranked by same-package proximity,
        inbound reference count, and recency — not an unordered dump. Use
        before changing a signature or debugging 'who triggers this?'. Compact
        rows (no bodies); use expand(expand_id) for the code."""
        results = retriever.get_callers(symbol, limit=limit)
        return _compact({"symbol": symbol, "results": [_result_row(r) for r in results]})

    @_tool
    def get_references(symbol: str, limit: int = 20) -> str:
        """Everywhere a symbol is referenced, called, or imported, ranked.
        Broader than get_callers — includes type annotations, imports, and
        value references. Ideal for impact analysis before a rename."""
        results = retriever.get_references(symbol, limit=limit)
        return _compact({"symbol": symbol, "results": [_result_row(r) for r in results]})

    @_tool
    def get_recent_changes(since: str) -> str:
        """What changed since a git ref (HEAD~5, a branch, a SHA) or ISO date
        (2024-06-01)? Returns commits with files AND symbol-level diffs
        (added/removed/modified functions) — the fastest way to triage 'what
        broke recently' without reading diffs."""
        commits = _recent_changes(repo, since)
        return _compact({"since": since, "commits": [c.to_dict() for c in commits]})

    @_tool
    def expand(expand_id: str) -> str:
        """Fetch the full chunk behind an expand_id returned by any other
        tool. Use when a compact result was relevant and you need the whole
        code body — cheaper than re-reading the file."""
        result = retriever.expand(expand_id)
        if result is None:
            return _compact({"expand_id": expand_id, "error": "unknown expand_id"})
        chunk = result.chunk
        return _compact(
            {
                "path": chunk.file_path,
                "bytes": [chunk.byte_start, chunk.byte_end],
                "breadcrumb": chunk.breadcrumb,
                "language": chunk.language,
                "code": chunk.code,
            }
        )

    @_tool
    def index_status() -> str:
        """Index freshness and size: HEAD, last synced ref, active blob count.
        Check this if results look stale, then run `sherpa sync`."""
        status: dict = {"repo": repo}
        try:
            status["head"] = git_output(repo, "rev-parse", "HEAD").strip()[:12]
        except Exception:  # not a git repo / git missing — still report the rest
            status["head"] = None
        if store is not None:
            status["active_blobs"] = len(store.active_blobs())
            status["last_sync"] = store.get_meta("last_sync")
            status["last_sync_head"] = (store.get_meta("last_sync_head") or "")[:12] or None
            status["indexed_files"] = len(store.files_for_ref("HEAD"))
            missing = _missing_embeddings(store)
            if missing is not None:
                status["missing_embeddings"] = missing
                status["warming"] = missing > 0
                if missing > 0:
                    status["hint"] = "run `sherpa sync` to finish embedding"
        else:
            status["note"] = "no index store attached"
        return _compact(status)

    return mcp
