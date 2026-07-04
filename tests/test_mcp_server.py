"""Phase 4: MCP server integration test via the SDK's in-memory client.

CLAUDE.md §10 Phase 4: "MCP server passes an integration test using the MCP
client from the SDK: every tool callable, schemas valid, responses < 4000
tokens default."
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest

from inmemory_store import InMemoryIndexStore, populate_store
from mcp.shared.memory import create_connected_server_and_client_session
from repograph.graph.gitio import last_change_dates
from repograph.graph.textutil import estimate_tokens
from repograph.graph.view import SymbolGraph
from repograph.mcp_server import create_server
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


@pytest.fixture(scope="module")
def server(miniproject: Path):
    store = InMemoryIndexStore()
    populate_store(store, miniproject)
    graph = SymbolGraph(store, recency=last_change_dates(miniproject))
    return create_server(SimpleRetriever(store, graph), miniproject, store=store)


def _call(server, tool: str, arguments: dict):
    async def go():
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool(tool, arguments)

    return anyio.run(go)


def _payload(result) -> dict:
    assert not result.isError, result.content
    assert len(result.content) == 1 and result.content[0].type == "text"
    return json.loads(result.content[0].text)


def test_all_tools_listed_with_valid_schemas(server):
    async def go():
        async with create_connected_server_and_client_session(server) as session:
            return await session.list_tools()

    tools = anyio.run(go).tools
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.description and len(tool.description) > 40, tool.name
        schema = tool.inputSchema
        assert schema["type"] == "object"
        assert isinstance(schema.get("properties", {}), dict)
    by_name = {t.name: t for t in tools}
    assert "query" in by_name["search_code"].inputSchema["properties"]
    assert "symbol" in by_name["get_callers"].inputSchema["properties"]
    # descriptions must sell the tool over grep/file-reading (§7.6)
    assert "grep" in by_name["search_code"].description


def test_search_code_respects_default_budget(server):
    result = _call(server, "search_code", {"query": "where is the retry logic for http requests"})
    payload = _payload(result)
    assert payload["results"], "search must return results on the fixture"
    assert payload["total_tokens"] <= payload["budget_tokens"] == 4000
    # the response itself must stay compact (< 4000 estimated tokens)
    assert estimate_tokens(result.content[0].text) < 4000
    for row in payload["results"]:
        assert row["expand_id"]
        assert row["why"] in {"bm25", "vector", "symbol", "expansion"}


def test_search_code_router_path_for_exact_symbol(server):
    payload = _payload(_call(server, "search_code", {"query": "validate_title"}))
    assert payload["results"][0]["path"] == "pyserver/validators.py"
    assert payload["results"][0]["why"] == "symbol"


def test_get_definition(server):
    payload = _payload(_call(server, "get_definition", {"symbol": "TaskStore"}))
    assert payload["results"]
    top = payload["results"][0]
    assert top["path"] == "webclient/src/store.ts"
    assert "class TaskStore" in top["code"]


def test_get_callers_ranked_with_rationale(server):
    payload = _payload(_call(server, "get_callers", {"symbol": "retry_request"}))
    rows = payload["results"]
    assert len(rows) >= 2
    assert rows[0]["path"] == "pyserver/http_client.py"  # same-file caller first
    for row in rows:
        assert "rationale" in row and "calls retry_request" in row["rationale"]
        assert "code" not in row, "caller rows are compact; code comes via expand"


def test_get_references(server):
    payload = _payload(_call(server, "get_references", {"symbol": "Task", "limit": 5}))
    assert 0 < len(payload["results"]) <= 5


def test_get_recent_changes(server):
    payload = _payload(_call(server, "get_recent_changes", {"since": "HEAD~1"}))
    assert len(payload["commits"]) == 1
    commit = payload["commits"][0]
    assert "pyserver/auth.py" in commit["files"]
    changed = {(s["path"], s["symbol"]): s["change"] for s in commit["changed_symbols"]}
    assert changed[("pyserver/auth.py", "hash_password")] == "added"


def test_expand_roundtrip(server):
    definition = _payload(_call(server, "get_definition", {"symbol": "validate_title"}))
    expand_id = definition["results"][0]["expand_id"]
    payload = _payload(_call(server, "expand", {"expand_id": expand_id}))
    assert payload["path"] == "pyserver/validators.py"
    assert "def validate_title" in payload["code"]


def test_expand_unknown_id(server):
    payload = _payload(_call(server, "expand", {"expand_id": "bogus:0:0"}))
    assert payload["error"] == "unknown expand_id"


def test_index_status(server):
    payload = _payload(_call(server, "index_status", {}))
    assert payload["active_blobs"] >= 30
    assert payload["last_sync_ref"] == "HEAD"
    assert payload["indexed_files"] >= 25
    assert payload["head"]


def test_bad_ref_is_a_tool_error_not_a_crash(server):
    result = _call(server, "get_recent_changes", {"since": "no-such-ref"})
    assert result.isError
    text = result.content[0].text
    assert "unknown ref" in text
