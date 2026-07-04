#!/usr/bin/env python3
"""Test-only stdio entry: run the sherpa MCP server over a synced index.

Usage: python tests/mcp_stdio_entry.py <repo_path> <db_path>

Launched as a subprocess by tests/test_mcp_server.py so the SDK client talks
to the server over the REAL stdio transport. Uses the tests-only
SimpleRetriever until the Phase 3 pipeline provides the production wiring
(`codesherpa.retrieve.build_retriever` -> `sherpa serve`).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for simple_retriever

from simple_retriever import SimpleRetriever

from codesherpa.graph.gitio import last_change_dates
from codesherpa.graph.view import SymbolGraph
from codesherpa.mcp_server import create_server
from codesherpa.store.sqlite_store import SQLiteIndexStore


def main() -> int:
    repo, db = Path(sys.argv[1]), Path(sys.argv[2])
    store = SQLiteIndexStore(db)
    graph = SymbolGraph(store, recency=last_change_dates(repo))
    server = create_server(SimpleRetriever(store, graph), repo, store=store)
    server.run()  # stdio transport
    return 0


if __name__ == "__main__":
    sys.exit(main())
