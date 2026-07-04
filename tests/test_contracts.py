"""Phase 0: the frozen contracts exist, are fully typed, and are abstract."""

from __future__ import annotations

import dataclasses
import inspect
import typing

import pytest

from repograph.contracts.index_contract import IndexStore
from repograph.contracts.retrieval_contract import Retriever
from repograph.contracts.types import (
    Chunk,
    Edge,
    EdgeKind,
    PackedContext,
    RetrievalSource,
    SearchResult,
    SymbolKind,
    SymbolNode,
)

ALL_DATACLASSES = [Chunk, SymbolNode, Edge, SearchResult, PackedContext]


@pytest.mark.parametrize("cls", ALL_DATACLASSES)
def test_types_are_frozen_dataclasses(cls) -> None:
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen


@pytest.mark.parametrize("cls", ALL_DATACLASSES)
def test_types_are_fully_typed(cls) -> None:
    hints = typing.get_type_hints(cls)
    for field in dataclasses.fields(cls):
        assert field.name in hints, f"{cls.__name__}.{field.name} lacks a type annotation"


def _chunk() -> Chunk:
    return Chunk(
        blob_hash="a" * 40,
        byte_start=0,
        byte_end=10,
        file_path="pyserver/app.py",
        language="python",
        code="def run():",
        breadcrumb="pyserver/app.py :: module :: def run()",
    )


def test_chunk_identity() -> None:
    chunk = _chunk()
    assert chunk.chunk_id == f"{'a' * 40}:0:10"
    with pytest.raises(dataclasses.FrozenInstanceError):
        chunk.byte_start = 5  # type: ignore[misc]


def test_symbol_node_and_edge() -> None:
    node = SymbolNode(
        symbol="run",
        kind=SymbolKind.FUNCTION,
        blob_hash="b" * 40,
        byte_start=0,
        byte_end=20,
        file_path="pyserver/app.py",
        signature="def run() -> None",
    )
    assert node.node_id.endswith(":run")
    edge = Edge(src=node.node_id, dst=node.node_id, kind=EdgeKind.CALLS)
    assert edge.kind is EdgeKind.CALLS


def test_packed_context_shape() -> None:
    result = SearchResult(
        chunk=_chunk(),
        score=1.0,
        source=RetrievalSource.BM25,
        expand_id="x1",
        token_count=12,
    )
    packed = PackedContext(query="q", budget_tokens=4000, total_tokens=12, results=(result,))
    assert packed.total_tokens <= packed.budget_tokens
    assert packed.results[0].source is RetrievalSource.BM25


@pytest.mark.parametrize("abc_cls", [IndexStore, Retriever])
def test_contracts_are_abstract(abc_cls) -> None:
    assert inspect.isabstract(abc_cls)
    with pytest.raises(TypeError):
        abc_cls()  # type: ignore[abstract]


def test_index_store_surface() -> None:
    expected = {
        "add_blob", "has_blob", "active_blobs", "set_blobs_active",
        "map_files", "files_for_ref",
        "add_chunks", "get_chunk", "chunks_for_blob",
        "add_symbols", "add_edges", "get_definitions", "get_edges",
        "get_embedding", "put_embedding",
        "fts_search", "vector_search", "symbol_search",
        "get_meta", "set_meta",
    }
    assert expected <= set(IndexStore.__abstractmethods__)


def test_retriever_surface_and_defaults() -> None:
    expected = {"search", "get_definition", "get_callers", "get_references", "expand"}
    assert expected <= set(Retriever.__abstractmethods__)
    assert inspect.signature(Retriever.search).parameters["budget_tokens"].default == 4000
    assert inspect.signature(Retriever.get_callers).parameters["limit"].default == 10
    assert inspect.signature(Retriever.get_references).parameters["limit"].default == 20
