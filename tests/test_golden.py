"""THE Golden Test (CLAUDE.md §2.3, §10 Phase 1).

Incremental index == full rebuild. From the miniproject fixture, perform a
random (hypothesis-driven) sequence of >=10 git operations — commit new file,
modify, delete, branch, switch, merge, revert — running ``repograph sync``
after each. The final incremental DB state (active blobs, files mapping,
chunks of active blobs, FTS rows of active blobs) must be IDENTICAL to a
from-scratch rebuild at the same HEAD.

This file must exist before the indexer is written and must pass before every
merge to main. It may never be deleted, skipped, or weakened.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# The Phase-1 public API the golden test pins down. Importing at module level
# is deliberate: the test is red until the indexer exists.
from repograph.gitlayer.sync import sync
from repograph.store.sqlite_store import SQLiteIndexStore

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Golden Bot",
    "GIT_AUTHOR_EMAIL": "golden@example.com",
    "GIT_COMMITTER_NAME": "Golden Bot",
    "GIT_COMMITTER_EMAIL": "golden@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}

# Files the ops must never delete so the repo always stays non-trivial.
_MIN_TRACKED_FILES = 3


class RepoDriver:
    """Applies golden-test operations to a scratch clone of the fixture."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.counter = 0

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            env={**os.environ, **_GIT_ENV},
            capture_output=True,
            text=True,
            check=check,
        )

    # ------------------------------------------------------------- helpers

    def tracked_text_files(self) -> list[str]:
        out = self.git("ls-files").stdout.splitlines()
        return sorted(
            p for p in out if p.endswith((".py", ".ts", ".tsx", ".md")) and not p.startswith(".")
        )

    def current_branch(self) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def branches(self) -> list[str]:
        out = self.git("for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
        return sorted(out.splitlines())

    def commit_all(self, message: str) -> None:
        self.git("add", "-A")
        # --allow-empty keeps op application total (some ops may be no-ops).
        self.git("commit", "--allow-empty", "-m", message)

    # ------------------------------------------------------------------ ops

    def op_add(self, flavor: int, seed: int) -> None:
        self.counter += 1
        n = self.counter
        if flavor % 2 == 0:
            rel = f"pyserver/gen_mod_{n}.py"
            body = (
                f'"""Generated module {n} (seed {seed})."""\n\n\n'
                f"def gen_func_{n}(x: int) -> int:\n"
                f'    """Return x shifted by the seed."""\n'
                f"    return x + {seed % 97}\n"
            )
        else:
            rel = f"webapp/src/gen_mod_{n}.ts"
            body = (
                f"// Generated module {n} (seed {seed})\n"
                f"export function genFunc{n}(x: number): number {{\n"
                f"  return x + {seed % 97};\n"
                f"}}\n"
            )
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        self.commit_all(f"add {rel}")

    def op_modify(self, seed: int) -> None:
        files = self.tracked_text_files()
        if not files:
            return
        rel = files[seed % len(files)]
        self.counter += 1
        marker = f"golden edit {self.counter} (seed {seed})"
        comment = f"# {marker}\n" if rel.endswith((".py", ".md")) else f"// {marker}\n"
        target = self.path / rel
        target.write_text(target.read_text(encoding="utf-8") + comment, encoding="utf-8")
        self.commit_all(f"modify {rel}")

    def op_delete(self, seed: int) -> None:
        files = self.tracked_text_files()
        if len(files) <= _MIN_TRACKED_FILES:
            return
        rel = files[seed % len(files)]
        self.git("rm", "-q", rel)
        self.commit_all(f"delete {rel}")

    def op_branch(self, seed: int) -> None:
        name = f"feature-{seed % 4}"
        if name in self.branches():
            self.git("checkout", "-q", name)
        else:
            self.git("checkout", "-q", "-b", name)

    def op_switch_main(self) -> None:
        self.git("checkout", "-q", "main")

    def op_merge(self, seed: int) -> None:
        current = self.current_branch()
        others = [b for b in self.branches() if b != current]
        if not others:
            return
        victim = others[seed % len(others)]
        # -s ours always succeeds (no conflicts) while still creating a merge
        # commit; tree churn is exercised by the other ops.
        self.git("merge", "-q", "-s", "ours", "--no-edit", victim)

    def op_revert(self) -> None:
        # Only revert simple (non-merge) commits; abort on any conflict so the
        # op is total.
        parents = self.git("rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
        if len(parents) != 2:  # commit hash + exactly one parent
            return
        result = self.git("revert", "--no-edit", "HEAD", check=False)
        if result.returncode != 0:
            self.git("revert", "--abort", check=False)

    def apply(self, op: tuple) -> None:
        kind = op[0]
        if kind == "add":
            self.op_add(op[1], op[2])
        elif kind == "modify":
            self.op_modify(op[1])
        elif kind == "delete":
            self.op_delete(op[1])
        elif kind == "branch":
            self.op_branch(op[1])
        elif kind == "switch":
            self.op_switch_main()
        elif kind == "merge":
            self.op_merge(op[1])
        elif kind == "revert":
            self.op_revert()
        else:  # pragma: no cover - strategy and interpreter must stay in sync
            raise AssertionError(f"unknown op {op!r}")


def golden_state(db_path: Path) -> dict:
    """The comparable 'active' projection of an index DB.

    Incremental DBs legitimately retain INACTIVE rows (soft deactivation is
    the design), so equality is defined over the active projection only:
    active blob set, HEAD file mapping, chunk identity+code per active blob,
    and which active chunks are present in FTS.
    """
    store = SQLiteIndexStore(db_path)
    try:
        active = store.active_blobs()
        files = store.files_for_ref("HEAD")
        chunks = {}
        for blob in sorted(active):
            chunks[blob] = [(c.chunk_id, c.code) for c in store.chunks_for_blob(blob)]
    finally:
        store.close()

    with sqlite3.connect(db_path) as conn:
        fts_ids = {row[0] for row in conn.execute("SELECT chunk_id FROM chunks_fts")}
    active_chunk_ids = {cid for per_blob in chunks.values() for cid, _ in per_blob}
    return {
        "active_blobs": active,
        "files": files,
        "chunks": chunks,
        "fts_active": fts_ids & active_chunk_ids,
        "fts_covers_active": active_chunk_ids <= fts_ids,
    }


def _fresh_clone(miniproject: Path, dest: Path) -> RepoDriver:
    shutil.copytree(miniproject, dest)
    shutil.rmtree(dest / ".repograph", ignore_errors=True)
    return RepoDriver(dest)


_OPS = st.one_of(
    st.tuples(st.just("add"), st.integers(0, 3), st.integers(0, 1000)),
    st.tuples(st.just("modify"), st.integers(0, 1000)),
    st.tuples(st.just("delete"), st.integers(0, 1000)),
    st.tuples(st.just("branch"), st.integers(0, 1000)),
    st.tuples(st.just("switch")),
    st.tuples(st.just("merge"), st.integers(0, 1000)),
    st.tuples(st.just("revert")),
)


@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    derandomize=True,  # CI-time bound (<120 s) requires a fixed example set
)
@given(ops=st.lists(_OPS, min_size=10, max_size=16))
def test_golden_incremental_equals_rebuild(ops, miniproject, tmp_path_factory) -> None:
    tmp = tmp_path_factory.mktemp("golden")
    driver = _fresh_clone(miniproject, tmp / "repo")

    inc_db = tmp / "incremental.db"
    sync(driver.path, inc_db)  # initial full index
    for op in ops:
        driver.apply(op)
        sync(driver.path, inc_db)

    rebuild_db = tmp / "rebuild.db"
    sync(driver.path, rebuild_db)  # from-scratch rebuild at the same HEAD

    incremental = golden_state(inc_db)
    rebuild = golden_state(rebuild_db)

    assert incremental["active_blobs"] == rebuild["active_blobs"]
    assert incremental["files"] == rebuild["files"]
    assert incremental["chunks"] == rebuild["chunks"]
    assert incremental["fts_active"] == rebuild["fts_active"]
    assert incremental["fts_covers_active"] and rebuild["fts_covers_active"]
