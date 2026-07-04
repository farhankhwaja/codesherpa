"""Phase 5 §3e regression tests: MCP startup is instant, offline, model-free.

Observed in the Phase 4 human smoke test: the first search_code took ~1.5
minutes because server startup lazily synced + embedded + loaded models.
These tests pin the fix:

- with a fully-built index, a COLD subprocess MCP initialize handshake
  completes in < 5 s;
- router-path tools (index_status, exact-symbol search_code, get_definition,
  get_callers, expand) respond in that same offline process, where any model
  load or network access would fail loudly (empty HOME model cache +
  HF_HUB_OFFLINE);
- build_retriever never syncs or embeds;
- a missing/absent index yields a friendly exit-2 message, and tools report
  a clear warming status while embeddings are missing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session
from repograph.embed.engine import EmbeddingEngine
from repograph.gitlayer.repo import NotARepositoryError
from repograph.gitlayer.sync import default_db_path, sync
from repograph.graph.gitio import last_change_dates
from repograph.graph.view import SymbolGraph
from repograph.mcp_server import create_server
from repograph.retrieve import IndexNotBuiltError, build_retriever
from repograph.retrieve.warm import embed_index, missing_embeddings
from repograph.store.sqlite_store import SQLiteIndexStore
from simple_retriever import SimpleRetriever

HANDSHAKE_BUDGET_S = 5.0


def _sha_encoder(texts: list[str]) -> list[list[float]]:
    return [
        [float(b) + 1.0 for b in hashlib.sha256(t.encode()).digest()[:16]]
        for t in texts
    ]


@pytest.fixture(scope="module")
def warmed_repo(miniproject, tmp_path_factory) -> Path:
    """Fixture clone with a FULLY built index at the production db path
    (chunks + graph + stub embeddings for every active chunk)."""
    tmp = tmp_path_factory.mktemp("warmed-repo")
    repo = tmp / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".repograph", ignore_errors=True)
    sync(repo)
    store = SQLiteIndexStore(default_db_path(repo))
    try:
        engine = EmbeddingEngine(store, "startup-stub", encoder=_sha_encoder)
        embed_index(store, engine=engine)
        assert missing_embeddings(store) == 0
    finally:
        store.close()
    return repo


def _offline_env(fake_home: Path) -> dict[str, str]:
    """Environment in which ANY model load or hub call fails loudly: the
    default model cache (under HOME) is empty and the HF hub is offline."""
    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    return env


def _payload(result) -> dict:
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


def test_cold_handshake_under_5s_and_router_tools_need_no_model(
    warmed_repo: Path, tmp_path: Path
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "repograph.mcp_server", str(warmed_repo)],
        env=_offline_env(fake_home),
    )

    async def go():
        started = time.perf_counter()
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                handshake = time.perf_counter() - started
                assert handshake < HANDSHAKE_BUDGET_S, (
                    f"cold MCP handshake took {handshake:.1f}s "
                    f"(budget {HANDSHAKE_BUDGET_S}s) — startup must not sync/"
                    "embed/load models (Phase 5 §3e)"
                )

                status = _payload(await session.call_tool("index_status", {}))
                assert status["missing_embeddings"] == 0
                assert status["warming"] is False

                # router path: exact-symbol query — no embedder, no reranker
                payload = _payload(
                    await session.call_tool("search_code", {"query": "validate_title"})
                )
                assert payload["results"][0]["path"] == "pyserver/validators.py"
                assert payload["results"][0]["why"] == "symbol"

                payload = _payload(
                    await session.call_tool("get_definition", {"symbol": "TaskStore"})
                )
                assert payload["results"][0]["path"] == "webclient/src/store.ts"

                payload = _payload(
                    await session.call_tool("get_callers", {"symbol": "retry_request"})
                )
                assert payload["results"]

                expand_id = payload["results"][0]["expand_id"]
                payload = _payload(await session.call_tool("expand", {"expand_id": expand_id}))
                assert payload["code"]

    anyio.run(go)


def test_build_retriever_never_syncs_or_embeds(miniproject, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".repograph", ignore_errors=True)
    sync(repo)

    # move the working tree ahead of the index: a syncing build_retriever
    # would pick this commit up
    (repo / "newfile.py").write_text("def brand_new():\n    return 42\n")
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )
    subprocess.run(["git", "add", "newfile.py"], cwd=repo, check=True, env=env, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "ahead of index"],
        cwd=repo,
        check=True,
        env=env,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    retriever, store = build_retriever(str(repo))
    try:
        assert store.get_meta("last_sync_head") != head  # no sync happened
        count = store.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert count == 0  # no embedding pass happened
    finally:
        store.close()


def test_build_retriever_friendly_failures(miniproject, tmp_path: Path) -> None:
    with pytest.raises(NotARepositoryError):
        build_retriever(str(tmp_path))  # not a git repo

    repo = tmp_path / "noindex"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".repograph", ignore_errors=True)
    with pytest.raises(IndexNotBuiltError, match="repograph init"):
        build_retriever(str(repo))


def test_serve_without_index_exits_2_with_hint(miniproject, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".repograph", ignore_errors=True)
    result = subprocess.run(
        [sys.executable, "-m", "repograph.cli", "serve", str(repo)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "repograph init" in result.stderr


# ------------------------------------------------ warming status (in-memory)


def test_tools_report_warming_while_embeddings_missing(synced_miniproject) -> None:
    repo, db = synced_miniproject  # session fixture: synced, never embedded
    store = SQLiteIndexStore(db)
    try:
        graph = SymbolGraph(store, recency=last_change_dates(repo))
        server = create_server(SimpleRetriever(store, graph), repo, store=store)

        async def go():
            async with create_connected_server_and_client_session(server) as session:
                status = _payload(await session.call_tool("index_status", {}))
                assert status["missing_embeddings"] > 0
                assert status["warming"] is True
                assert "repograph sync" in status["hint"]

                payload = _payload(
                    await session.call_tool(
                        "search_code", {"query": "retry logic for http requests"}
                    )
                )
                assert payload["warming"]["missing_embeddings"] > 0
                assert "repograph sync" in payload["warming"]["hint"]

        anyio.run(go)
    finally:
        store.close()
