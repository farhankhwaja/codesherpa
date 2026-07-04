"""Builders for contract dataclasses used across retrieval tests."""

from __future__ import annotations

from codesherpa.contracts.types import Chunk, RetrievalSource, SearchResult
from codesherpa.retrieve.tokens import result_token_cost


def make_chunk(
    blob_hash: str = "b" * 40,
    byte_start: int = 0,
    byte_end: int = 100,
    file_path: str = "src/mod.py",
    language: str = "python",
    code: str = "def foo():\n    return 1\n",
    breadcrumb: str = "src/mod.py :: module :: def foo()",
) -> Chunk:
    return Chunk(
        blob_hash=blob_hash,
        byte_start=byte_start,
        byte_end=byte_end,
        file_path=file_path,
        language=language,
        code=code,
        breadcrumb=breadcrumb,
    )


def make_result(
    chunk: Chunk | None = None,
    score: float = 1.0,
    source: RetrievalSource = RetrievalSource.BM25,
    token_count: int | None = None,
    **chunk_kwargs,
) -> SearchResult:
    if chunk is None:
        chunk = make_chunk(**chunk_kwargs)
    if token_count is None:
        token_count = result_token_cost(chunk.breadcrumb, chunk.code)
    return SearchResult(
        chunk=chunk,
        score=score,
        source=source,
        expand_id=chunk.chunk_id,
        token_count=token_count,
    )
