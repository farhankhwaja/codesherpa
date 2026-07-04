"""Phase 4: MCP server integration tests with the real MCP SDK client.

CLAUDE.md §10 Phase 4: "MCP server passes an integration test using the MCP
client from the SDK: every tool callable, schemas valid, responses < 4000
tokens default."

The primary test drives the server over the REAL stdio transport (subprocess
via ``tests/mcp_stdio_entry.py``) against the REAL SQLite store built by the
real sync pipeline, exercising every tool in one session. Edge-case tests
reuse the SDK's in-memory session (same ClientSession, no subprocess) to
keep the suite fast.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio
import pytest

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session
from codesherpa.graph.gitio import last_change_dates
from codesherpa.graph.textutil import estimate_tokens
from codesherpa.graph.view import SymbolGraph
from codesherpa.mcp_server import create_server
from codesherpa.store.sqlite_store import SQLiteIndexStore
from simple_retriever import SimpleRetriever

EXPECTED_TOOLS = {
    "search_code",
    "get_definition",
    "get_callers",
    "get_references",
    "get_recent_changes",
    "expand",
    "index_status",
}

ENTRY = Path(__file__).parent / "mcp_stdio_entry.py"


def _text(result) -> str:
    assert not result.isError, result.content
    assert len(result.content) == 1 and result.content[0].type == "text"
    return result.content[0].text


def _payload(result) -> dict:
    return json.loads(_text(result))


# --------------------------------------------------------------- stdio


def test_stdio_server_every_tool_end_to_end(synced_miniproject: tuple[Path, Path]):
    """One real stdio session; every §7.6 tool called and checked."""
    repo, db = synced_miniproject
    params = StdioServerParameters(
        command=sys.executable, args=[str(ENTRY), str(repo), str(db)]
    )

    async def go():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = (await session.list_tools()).tools
                assert {t.name for t in tools} == EXPECTED_TOOLS
                by_name = {t.name: t for t in tools}
                for tool in tools:
                    assert tool.description and len(tool.description) > 40, tool.name
                    assert tool.inputSchema["type"] == "object"
                    assert isinstance(tool.inputSchema.get("properties", {}), dict)
                # descriptions must sell the tool over grep/file-reading (§7.6)
                assert "grep" in by_name["search_code"].description
                assert "query" in by_name["search_code"].inputSchema["properties"]
                assert "symbol" in by_name["get_callers"].inputSchema["properties"]

                # search_code — compact-first (D39): 1500-token default budget
                # bounds the whole response; rows are signature/breadcrumb +
                # expand_id handles, no code bodies unless include_code
                result = await session.call_tool(
                    "search_code", {"query": "where is the retry logic for http requests"}
                )
                payload = _payload(result)
                assert payload["results"]
                assert payload["total_tokens"] <= payload["budget_tokens"] == 1500
                assert estimate_tokens(_text(result)) < 1500
                for row in payload["results"]:
                    assert row["expand_id"]
                    assert row["breadcrumb"]
                    assert "code" not in row  # compact-first: bodies via expand()
                    assert row["why"] in {"bm25", "vector", "symbol", "expansion"}

                # include_code=true restores full-body rows on demand
                verbose = _payload(
                    await session.call_tool(
                        "search_code",
                        {"query": "where is the retry logic for http requests",
                         "include_code": True},
                    )
                )
                assert any("code" in row for row in verbose["results"])

                # get_definition
                payload = _payload(
                    await session.call_tool("get_definition", {"symbol": "TaskStore"})
                )
                assert payload["results"][0]["path"] == "webclient/src/store.ts"
                assert "class TaskStore" in payload["results"][0]["code"]

                # get_callers — ranked, rationale, compact
                payload = _payload(
                    await session.call_tool("get_callers", {"symbol": "retry_request"})
                )
                rows = payload["results"]
                assert len(rows) >= 2
                assert rows[0]["path"] == "pyserver/http_client.py"
                for row in rows:
                    assert "calls retry_request" in row["rationale"]
                    assert "code" not in row

                # get_references
                payload = _payload(
                    await session.call_tool("get_references", {"symbol": "Task", "limit": 5})
                )
                assert 0 < len(payload["results"]) <= 5

                # get_recent_changes
                payload = _payload(
                    await session.call_tool("get_recent_changes", {"since": "HEAD~2"})
                )
                assert len(payload["commits"]) == 2
                auth = payload["commits"][1]
                changed = {
                    (s["path"], s["symbol"]): s["change"] for s in auth["changed_symbols"]
                }
                assert changed[("pyserver/auth.py", "hash_password")] == "added"

                # expand — round trip from a definition's handle
                definition = _payload(
                    await session.call_tool("get_definition", {"symbol": "validate_title"})
                )
                expand_id = definition["results"][0]["expand_id"]
                payload = _payload(await session.call_tool("expand", {"expand_id": expand_id}))
                assert payload["path"] == "pyserver/validators.py"
                assert "def validate_title" in payload["code"]

                # index_status
                payload = _payload(await session.call_tool("index_status", {}))
                assert payload["active_blobs"] >= 30
                assert payload["indexed_files"] >= 25
                assert payload["last_sync"] and payload["last_sync_head"]
                assert payload["head"] == payload["last_sync_head"]

    anyio.run(go)


# ------------------------------------------------- in-memory edge cases


@pytest.fixture(scope="module")
def server(synced_miniproject: tuple[Path, Path]):
    repo, db = synced_miniproject
    store = SQLiteIndexStore(db)
    graph = SymbolGraph(store, recency=last_change_dates(repo))
    yield create_server(SimpleRetriever(store, graph), repo, store=store)
    store.close()


def _call(server, tool: str, arguments: dict):
    async def go():
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool(tool, arguments)

    return anyio.run(go)


def test_search_code_router_path_for_exact_symbol(server):
    payload = _payload(_call(server, "search_code", {"query": "validate_title"}))
    assert payload["results"][0]["path"] == "pyserver/validators.py"
    assert payload["results"][0]["why"] == "symbol"


def test_search_code_tiny_budget_still_fits(server):
    result = _call(
        server, "search_code", {"query": "retry logic for http", "budget_tokens": 300}
    )
    payload = _payload(result)
    assert payload["total_tokens"] <= 300
    assert estimate_tokens(_text(result)) <= 300


def test_expand_unknown_id(server):
    payload = _payload(_call(server, "expand", {"expand_id": "bogus:0:0"}))
    assert payload["error"] == "unknown expand_id"


def test_bad_ref_is_a_tool_error_not_a_crash(server):
    result = _call(server, "get_recent_changes", {"since": "no-such-ref"})
    assert result.isError
    assert "unknown ref" in result.content[0].text
