"""Per-blob graph extraction cache (D47).

The cache replays tree-sitter pass 1 from a persisted payload instead of
reparsing. The whole risk is that a replayed payload differs in ANY way from a
fresh parse — so these tests pin equivalence directly, on top of the Golden
Test's end-to-end incremental-vs-rebuild guarantee.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codesherpa.gitlayer.sync import sync
from codesherpa.graph.extract import (
    CachedFile,
    SourceFile,
    decode_facts,
    encode_facts,
    extract_project,
    extract_project_cached,
    extraction_tag,
)
from codesherpa.store.sqlite_store import SQLiteIndexStore

PY_A = b'''\
"""Module a."""
import b

MAX_TRIES = 3


class Client:
    """A client."""

    def send(self, payload):
        return b.encode_body(payload)

    def retry(self, payload):
        for _ in range(MAX_TRIES):
            self.send(payload)
'''

PY_B = b'''\
def encode_body(payload):
    return str(payload)


def unused_helper(x):
    return x
'''

TS_C = b"""\
export function rank(items: number[]): number[] {
  return items.sort();
}

export class Cache {
  put(k: string): void {}
}
"""


def _sources() -> list[SourceFile]:
    return [
        SourceFile("pkg/a.py", "a" * 40, "python", PY_A),
        SourceFile("pkg/b.py", "b" * 40, "python", PY_B),
        SourceFile("web/c.ts", "c" * 40, "typescript", TS_C),
    ]


def _cached(sources: list[SourceFile]) -> list[CachedFile]:
    return [
        CachedFile(s.path, s.blob_hash, s.language, encode_facts(s)) for s in sources
    ]


def test_cached_extraction_equals_fresh_extraction() -> None:
    """The load-bearing invariant: replayed facts produce identical output."""
    sources = _sources()
    assert extract_project_cached(_cached(sources)) == extract_project(sources)


def test_payload_is_path_independent() -> None:
    """One cached row must serve a blob at any path — that is why the cache is
    keyed by (blob, language) and not by path."""
    data = PY_A
    at_one = encode_facts(SourceFile("pkg/a.py", "a" * 40, "python", data))
    at_other = encode_facts(SourceFile("vendor/deep/nested/a.py", "a" * 40, "python", data))
    assert at_one == at_other


def test_decode_rebuilds_path_dependent_fields() -> None:
    source = SourceFile("pkg/a.py", "a" * 40, "python", PY_A)
    facts = decode_facts(encode_facts(source), "other/z.py", "z" * 40, "python")
    assert facts.path == "other/z.py"
    assert facts.module.file_path == "other/z.py"
    assert facts.module.blob_hash == "z" * 40
    assert facts.module.byte_end == len(PY_A)
    assert all(d.file_path == "other/z.py" for d in facts.defs)
    assert all(d.blob_hash == "z" * 40 for d in facts.defs)


def test_payload_is_deterministic_and_json() -> None:
    source = SourceFile("pkg/a.py", "a" * 40, "python", PY_A)
    first = encode_facts(source)
    assert first == encode_facts(source)
    payload = json.loads(first)
    assert payload["size"] == len(PY_A)
    assert {d[0] for d in payload["defs"]} >= {"Client", "send", "retry", "MAX_TRIES"}


def test_extraction_tag_covers_queries_and_grammar() -> None:
    tag = extraction_tag()
    assert tag.startswith("v")
    assert "q=" in tag
    assert "tree-sitter-language-pack=" in tag
    assert extraction_tag() == tag  # stable within a version


# ------------------------------------------------------------ end-to-end

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(repo: Path, *args: str) -> None:
    import os

    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_bytes(PY_A)
    (root / "pkg" / "b.py").write_bytes(PY_B)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _graph_state(db: Path) -> tuple:
    store = SQLiteIndexStore(db)
    try:
        symbols = store.conn.execute(
            "SELECT node_id, symbol, kind, file_path, signature FROM symbols ORDER BY node_id"
        ).fetchall()
        edges = store.conn.execute(
            "SELECT src, dst, kind FROM edges ORDER BY src, dst, kind"
        ).fetchall()
        return ([tuple(r) for r in symbols], [tuple(r) for r in edges])
    finally:
        store.close()


def test_sync_populates_and_reuses_the_cache(repo: Path, tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    sync(repo, db)

    store = SQLiteIndexStore(db)
    try:
        rows = store.conn.execute(
            "SELECT blob_hash, language FROM graph_facts"
        ).fetchall()
        assert len(rows) == 2  # both python files cached
        assert store.get_meta("graph_facts_tag") == extraction_tag()
    finally:
        store.close()

    before = _graph_state(db)
    sync(repo, db)  # second sync: everything served from cache
    assert _graph_state(db) == before


def test_resync_parses_nothing_when_nothing_changed(repo: Path, tmp_path: Path) -> None:
    """The performance claim, asserted rather than assumed: a no-op sync must
    not read a single blob for graph extraction."""
    db = tmp_path / "index.db"
    sync(repo, db)

    from codesherpa.graph import index as graph_index

    calls: list[str] = []
    real = graph_index.encode_facts

    def counting(source):
        calls.append(source.blob_hash)
        return real(source)

    graph_index.encode_facts = counting
    try:
        sync(repo, db)
    finally:
        graph_index.encode_facts = real
    assert calls == []


def test_only_changed_blobs_are_reparsed(repo: Path, tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    sync(repo, db)

    (repo / "pkg" / "b.py").write_bytes(PY_B + b"\n\ndef added():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change b")

    from codesherpa.graph import index as graph_index

    calls: list[str] = []
    real = graph_index.encode_facts

    def counting(source):
        calls.append(source.path)
        return real(source)

    graph_index.encode_facts = counting
    try:
        sync(repo, db)
    finally:
        graph_index.encode_facts = real

    assert calls == ["pkg/b.py"]  # a.py served from cache
    symbols = [row[1] for row in _graph_state(db)[0]]
    assert "added" in symbols


def test_stale_tag_wipes_the_cache(repo: Path, tmp_path: Path) -> None:
    """A changed extractor identity must invalidate every cached payload —
    replaying them would silently produce wrong symbols."""
    db = tmp_path / "index.db"
    sync(repo, db)

    store = SQLiteIndexStore(db)
    try:
        store.set_meta("graph_facts_tag", "v0|q=stale|tree-sitter=0")
        store.conn.execute(
            "UPDATE graph_facts SET facts = ?",
            (json.dumps({"size": 1, "defs": [], "imports": [], "calls": [],
                         "refs": [], "local_types": [], "method_receiver": []}),),
        )
        store.conn.commit()
    finally:
        store.close()

    sync(repo, db)

    store = SQLiteIndexStore(db)
    try:
        assert store.get_meta("graph_facts_tag") == extraction_tag()
        payloads = [
            json.loads(r[0])
            for r in store.conn.execute("SELECT facts FROM graph_facts").fetchall()
        ]
        assert payloads and all(p["defs"] for p in payloads)  # re-extracted, not the stub
    finally:
        store.close()

    # and the graph itself recovered
    symbols = {row[1] for row in _graph_state(db)[0]}
    assert {"Client", "send", "encode_body"} <= symbols


def test_incremental_matches_rebuild_after_edits(repo: Path, tmp_path: Path) -> None:
    """A focused Golden-Test echo aimed squarely at the cache: an index grown
    incrementally across edits must equal a from-scratch rebuild at the same
    HEAD, including the symbols/edges the cache feeds."""
    incremental = tmp_path / "incremental.db"
    sync(repo, incremental)

    (repo / "pkg" / "c.py").write_bytes(b"from a import Client\n\n\ndef go():\n    Client().send(1)\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add c")
    sync(repo, incremental)

    (repo / "pkg" / "b.py").write_bytes(PY_B + b"\n\ndef extra():\n    return 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "edit b")
    sync(repo, incremental)

    rebuild = tmp_path / "rebuild.db"
    sync(repo, rebuild)

    assert _graph_state(incremental) == _graph_state(rebuild)
