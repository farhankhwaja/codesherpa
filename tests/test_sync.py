"""Phase 1 gitlayer tests: init, sync semantics, idempotency, concurrency."""

from __future__ import annotations

import multiprocessing
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from repograph.gitlayer.initialize import init
from repograph.gitlayer.repo import HOOK_NAMES, NotARepositoryError, open_repo
from repograph.gitlayer.sync import default_db_path, sync
from repograph.store.sqlite_store import SQLiteIndexStore

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Sync Bot",
    "GIT_AUTHOR_EMAIL": "sync@example.com",
    "GIT_COMMITTER_NAME": "Sync Bot",
    "GIT_COMMITTER_EMAIL": "sync@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture()
def repo(miniproject: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(miniproject, dest)
    shutil.rmtree(dest / ".repograph", ignore_errors=True)
    # keep the index out of the tests' own `git add -A` commits — real users
    # get this from `repograph init` (ensure_gitignore), which some of these
    # tests deliberately bypass to exercise raw sync
    from repograph.gitlayer.initialize import ensure_gitignore

    if ensure_gitignore(dest):
        _git(dest, "add", ".gitignore")
        _git(dest, "-c", "commit.gpgsign=false", "commit", "-qm", "gitignore .repograph")
    return dest


# ------------------------------------------------------------------- init


def test_init_creates_db_hooks_gitignore(repo: Path) -> None:
    result = init(repo, quiet=True)

    assert result.db_path == repo / ".repograph" / "index.db"
    assert result.db_path.is_file()

    hooks_dir = repo / ".git" / "hooks"
    for name in HOOK_NAMES:
        hook = hooks_dir / name
        assert hook.is_file(), f"missing hook {name}"
        assert os.access(hook, os.X_OK), f"hook {name} not executable"
        assert "repograph sync --quiet" in hook.read_text()

    gitignore = (repo / ".gitignore").read_text()
    assert ".repograph/" in gitignore

    assert result.stats.blobs_indexed > 20  # the fixture has 25+ source files
    assert result.stats.files_mapped > 20


def test_init_is_idempotent_and_preserves_foreign_hooks(repo: Path) -> None:
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    foreign = hooks_dir / "post-commit"
    foreign.write_text("#!/bin/sh\necho existing-hook\n")

    init(repo, quiet=True)
    first = {name: (hooks_dir / name).read_text() for name in HOOK_NAMES}
    assert "echo existing-hook" in first["post-commit"]  # preserved
    assert "repograph sync --quiet" in first["post-commit"]  # appended

    init(repo, quiet=True)
    second = {name: (hooks_dir / name).read_text() for name in HOOK_NAMES}
    assert first == second  # no duplicate appends

    gitignore = (repo / ".gitignore").read_text()
    assert gitignore.count(".repograph/") == 1


def test_init_outside_repo_fails(tmp_path: Path) -> None:
    with pytest.raises(NotARepositoryError):
        init(tmp_path / "not-a-repo-anywhere")


# ------------------------------------------------------------------- sync


def _db_state(db: Path) -> tuple:
    """Full comparable dump of an index DB (for exact idempotency checks)."""
    conn = sqlite3.connect(db)
    try:
        tables = ("meta", "blobs", "files", "chunks", "symbols", "edges", "embeddings")
        state = []
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            if table == "meta":  # last_sync timestamp legitimately changes
                rows = [r for r in rows if r[0] not in ("last_sync",)]
            state.append((table, rows))
        fts = conn.execute("SELECT chunk_id FROM chunks_fts ORDER BY 1").fetchall()
        state.append(("chunks_fts", fts))
        return tuple(state)
    finally:
        conn.close()


def test_sync_is_idempotent(repo: Path) -> None:
    stats1 = sync(repo)
    db = default_db_path(repo)
    before = _db_state(db)

    stats2 = sync(repo)
    after = _db_state(db)

    assert stats1.blobs_indexed > 0
    assert stats2.blobs_indexed == 0
    assert stats2.chunks_added == 0
    assert stats2.blobs_deactivated == 0
    assert stats2.blobs_reactivated == 0
    assert before == after


def test_sync_reindexes_only_new_blobs_on_modify(repo: Path) -> None:
    sync(repo)
    target = repo / "pyserver" / "config.py"
    target.write_text(target.read_text() + "\n# touched\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "touch config")

    stats = sync(repo)
    assert stats.blobs_indexed == 1  # only the new config.py blob
    assert stats.blobs_deactivated == 1  # the old config.py blob


def test_branch_switch_costs_nothing_new(repo: Path) -> None:
    sync(repo)
    _git(repo, "checkout", "-qb", "feature")
    (repo / "pyserver" / "feature_mod.py").write_text("def feature():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "feature work")
    stats_feature = sync(repo)
    assert stats_feature.blobs_indexed == 1

    _git(repo, "checkout", "-q", "main")
    stats_main = sync(repo)
    # back on main: nothing new to parse, feature blob deactivated
    assert stats_main.blobs_indexed == 0
    assert stats_main.blobs_deactivated == 1

    _git(repo, "checkout", "-q", "feature")
    stats_back = sync(repo)
    # switching back is pure reactivation — the differentiator
    assert stats_back.blobs_indexed == 0
    assert stats_back.blobs_reactivated == 1


def test_deleted_file_deactivated_not_deleted(repo: Path) -> None:
    sync(repo)
    db = default_db_path(repo)
    store = SQLiteIndexStore(db)
    try:
        files = store.files_for_ref("HEAD")
        victim = "pyserver/config.py"
        victim_blob = files[victim]
    finally:
        store.close()

    _git(repo, "rm", "-q", victim)
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "remove config")
    sync(repo)

    store = SQLiteIndexStore(db)
    try:
        assert victim_blob not in store.active_blobs()
        assert store.has_blob(victim_blob)  # soft: row retained
        assert store.chunks_for_blob(victim_blob)  # chunks retained too
        assert victim not in store.files_for_ref("HEAD")
    finally:
        store.close()


def test_sync_skips_binary_and_vendored_and_repographignore(repo: Path) -> None:
    (repo / "assets").mkdir()
    (repo / "assets" / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    (repo / "node_modules" / "dep").mkdir(parents=True)
    (repo / "node_modules" / "dep" / "index.js").write_text("module.exports = 1;\n")
    (repo / "yarn.lock").write_text("# lockfile\n")
    (repo / "app.min.js").write_text("var a=1;\n")
    (repo / "secret").mkdir()
    (repo / "secret" / "keys.py").write_text("KEY = 'x'\n")
    (repo / ".repographignore").write_text("secret/\n")
    _git(repo, "add", "-Af")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "junk files")

    sync(repo)
    store = SQLiteIndexStore(default_db_path(repo))
    try:
        files = store.files_for_ref("HEAD")
        assert "assets/logo.png" not in files
        assert "node_modules/dep/index.js" not in files
        assert "yarn.lock" not in files
        assert "app.min.js" not in files
        assert "secret/keys.py" not in files
        assert ".repographignore" in files  # the ignore file itself is fine
    finally:
        store.close()


def test_sync_on_empty_repo(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    _git(empty, "init", "-q")
    stats = sync(empty)  # unborn HEAD: no crash, empty index
    assert stats.head is None
    assert stats.blobs_indexed == 0


def test_duplicate_content_indexed_once(repo: Path) -> None:
    sync(repo)  # baseline index so only the duplicates are new below
    body = "def duplicated():\n    return 42\n"
    (repo / "pyserver" / "copy_a.py").write_text(body)
    (repo / "pyserver" / "copy_b.py").write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "duplicates")

    stats = sync(repo)
    assert stats.blobs_indexed == 1  # one blob, two paths
    store = SQLiteIndexStore(default_db_path(repo))
    try:
        files = store.files_for_ref("HEAD")
        assert files["pyserver/copy_a.py"] == files["pyserver/copy_b.py"]
    finally:
        store.close()


# ------------------------------------------------------------- concurrency


def _sync_worker(repo_str: str, results: multiprocessing.Queue) -> None:
    try:
        sync(repo_str)
        results.put("ok")
    except Exception as exc:  # pragma: no cover - failure reporting
        results.put(f"error: {exc!r}")


def test_concurrent_syncs_do_not_corrupt(repo: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    results: multiprocessing.Queue = ctx.Queue()
    workers = [ctx.Process(target=_sync_worker, args=(str(repo), results)) for _ in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=120)
        assert not w.is_alive()
    outcomes = [results.get(timeout=5) for _ in workers]
    assert outcomes == ["ok", "ok"], outcomes

    db = default_db_path(repo)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()

    # and the result equals a fresh rebuild (no lost updates)
    rebuild = repo / "rebuild.db"
    sync(repo, rebuild)
    s_inc = SQLiteIndexStore(db)
    s_reb = SQLiteIndexStore(rebuild)
    try:
        assert s_inc.active_blobs() == s_reb.active_blobs()
        assert s_inc.files_for_ref("HEAD") == s_reb.files_for_ref("HEAD")
    finally:
        s_inc.close()
        s_reb.close()

    # no leftover lockfile
    assert not (db.parent / (db.name + ".lock")).exists()
