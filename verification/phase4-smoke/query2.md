Query: Use the repograph tool get_callers on the symbol sync_graph

sync_graph has exactly one caller in the index: _sync_locked in repograph/gitlayer/sync.py (the chunk at bytes 3896–5936 we expanded earlier). It calls it once, cross-package (gitlayer → graph), as the final step of every sync:

stats.symbols_indexed, stats.edges_indexed = sync_graph(store, file_map, graph_blobs)

So the symbol-graph recompute has a single production entry point — it's never invoked from the CLI, MCP server, or retrieval code directly, only as part of the sync pipeline. That makes it a safe signature to change as long as _sync_locked is updated in step (tests that exercise it do so through sync()).

**Sauteed for 27s**