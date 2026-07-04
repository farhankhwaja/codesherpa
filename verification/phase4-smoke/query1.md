Query: Use the repograph MCP tool search_code to answer: how does sync decide which blobs are new?

I'll use the repograph search_code tool to find how sync determines new blobs.

  Called repograph 2 times

That's the module header; the decision logic lives in _sync_locked. Let me pull it.

  Called repograph 2 times

One more expand for the first half of _sync_locked, which builds the candidate set.

  Called repograph

sync decides "new" with a single content-addressed membership check: a blob is new if and only if its git blob SHA is not already a row in the index's blobs table — store.has_blob(blob_hash). Path, branch, and history are irrelevant; only content identity matters.

The full flow in repograph/gitlayer/sync.py (_sync_locked, under a lockfile):

1. Enumerate HEAD. head_tree_blobs(repo) yields the complete path → blob hash mapping for the current HEAD tree (hooks fire on checkout/merge/rewrite, so HEAD is always the tracked ref).
2. Filter. IgnoreRules.skip_path(path, size) drops ignored/oversized paths before any content is read.
3. Dedupe by content. The map is inverted to blob → first sorted path, so a blob living at several paths is considered (and indexed) exactly once — deterministically, so incremental and rebuild agree.
4. The newness test. Iterating blobs in sorted order: if store.has_blob(blob_hash): continue — the comment calls it out: "content-addressed cache hit: nothing to do, ever." Only blobs failing this check get read, binary-sniffed (binaries are skipped and never stored), chunked, and inserted via add_blob + add_chunks.
5. Activation is separate set arithmetic, not deletion: to_deactivate = already_active − desired_active and to_reactivate = desired_active − already_active. Blobs that vanish from HEAD are soft-deactivated, so switching back to an old branch reactivates rows instead of re-indexing — that's the cheap-branch-switch property.

One nuance: chunks and embeddings stay incremental per this blob-hash key, but symbols/edges are recomputed wholesale from the active file mapping every sync (sync_graph), because call resolution is a global function of the file set — appending per-blob couldn't keep incremental == rebuild (DECISIONS.md D19).

**COOKED FOR 1m 27s**