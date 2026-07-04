"""Incremental sync: diff the HEAD tree against indexed blobs (CLAUDE.md §7.1).

The core loop of the whole product. Blobs are content-addressed, so only
genuinely new blobs are read/chunked; blobs no longer reachable from the
indexed ref are soft-deactivated (never deleted — switching back is free).
Idempotent, and safe to run concurrently thanks to the lockfile.

A from-scratch rebuild is just ``sync`` into a fresh database file; the
Golden Test holds the two paths to identical active state.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from repograph.chunker import chunk_blob, detect_language
from repograph.gitlayer.ignore import IgnoreRules, looks_binary
from repograph.gitlayer.lock import FileLock
from repograph.gitlayer.repo import (
    blob_size,
    head_commit_hex,
    head_tree_blobs,
    open_repo,
    read_blob,
    repo_root,
)
from repograph.store.sqlite_store import SQLiteIndexStore

# The single ref Phase 1 tracks: whatever HEAD points at right now. Hooks
# fire on every history-changing operation, so the index follows checkouts.
INDEXED_REF = "HEAD"


@dataclass
class SyncStats:
    head: str | None = None
    blobs_indexed: int = 0
    blobs_reactivated: int = 0
    blobs_deactivated: int = 0
    chunks_added: int = 0
    files_mapped: int = 0
    paths_skipped: int = 0
    binary_blobs_skipped: int = 0
    lines_indexed: int = 0
    seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)


def default_db_path(root: Path) -> Path:
    return root / ".repograph" / "index.db"


def sync(
    repo_path: Path | str,
    db_path: Path | str | None = None,
    quiet: bool = True,
) -> SyncStats:
    """Bring the index at ``db_path`` up to date with the repo's HEAD."""
    started = time.perf_counter()
    repo = open_repo(Path(repo_path))
    root = repo_root(repo)
    db = Path(db_path) if db_path is not None else default_db_path(root)
    db.parent.mkdir(parents=True, exist_ok=True)

    stats = SyncStats(head=head_commit_hex(repo))
    lock = FileLock(db.with_name(db.name + ".lock"))
    with lock:
        store = SQLiteIndexStore(db)
        try:
            _sync_locked(repo, root, store, stats)
        finally:
            store.close()
    stats.seconds = time.perf_counter() - started

    if not quiet:
        print(
            f"repograph sync: {stats.blobs_indexed} new blobs, "
            f"{stats.blobs_reactivated} reactivated, "
            f"{stats.blobs_deactivated} deactivated, "
            f"{stats.files_mapped} files @ {stats.head or 'unborn HEAD'} "
            f"({stats.seconds:.2f}s)",
            file=sys.stderr,
        )
        for warning in stats.warnings:
            print(f"repograph sync: warning: {warning}", file=sys.stderr)
    return stats


def _sync_locked(repo, root: Path, store: SQLiteIndexStore, stats: SyncStats) -> None:
    ignore = IgnoreRules.load(root)
    tree = head_tree_blobs(repo)

    candidates: dict[str, str] = {}  # path -> blob
    for path, blob_hash in tree.items():
        if ignore.skip_path(path, blob_size(repo, blob_hash)):
            stats.paths_skipped += 1
        else:
            candidates[path] = blob_hash

    # One blob may live at several paths; index it once under the first path
    # in sorted order so incremental and rebuild agree deterministically.
    blob_to_path: dict[str, str] = {}
    for path in sorted(candidates):
        blob_to_path.setdefault(candidates[path], path)

    already_active = store.active_blobs()
    known_before = {b for b in blob_to_path if store.has_blob(b)}
    binary_blobs: set[str] = set()

    for blob_hash, path in sorted(blob_to_path.items()):
        if store.has_blob(blob_hash):
            continue  # content-addressed cache hit: nothing to do, ever
        data = read_blob(repo, blob_hash)
        if looks_binary(data):
            binary_blobs.add(blob_hash)
            stats.binary_blobs_skipped += 1
            continue
        language = detect_language(path)
        chunks = chunk_blob(blob_hash, data, path, language)
        store.add_blob(blob_hash, language, len(data))
        store.add_chunks(chunks)
        stats.blobs_indexed += 1
        stats.chunks_added += len(chunks)
        stats.lines_indexed += data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)

    # Binary blobs are never stored, so drop them from this sync's world view
    # (they get re-sniffed next sync; cheap, and keeps the store pure).
    desired_active = {b for b in blob_to_path if b not in binary_blobs}
    file_map = {p: b for p, b in candidates.items() if b not in binary_blobs}

    to_deactivate = already_active - desired_active
    to_reactivate = desired_active - already_active
    # add_blob() above already activated brand-new blobs; set_blobs_active is
    # a no-op for them and reactivates previously-known ones.
    store.set_blobs_active(to_deactivate, active=False)
    store.set_blobs_active(to_reactivate, active=True)
    stats.blobs_deactivated = len(to_deactivate)
    stats.blobs_reactivated = len(to_reactivate & known_before)

    store.map_files(INDEXED_REF, file_map)
    stats.files_mapped = len(file_map)

    store.set_meta("last_sync", datetime.now(timezone.utc).isoformat())
    store.set_meta("last_sync_head", stats.head or "")
