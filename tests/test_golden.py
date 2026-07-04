"""THE Golden Test (CLAUDE.md §2.3, §10 Phase 1).

Incremental index == full rebuild. From the miniproject fixture, perform a
random (hypothesis-driven) sequence of >=10 git operations — commit new file,
modify, delete, branch, switch, merge (both a tree-changing merge and the
degenerate `-s ours` flavor), revert — running ``sherpa sync`` after each.
The final incremental DB state (active blobs, files mapping, chunks of active
blobs, FTS rows of active blobs) must be IDENTICAL to a from-scratch rebuild
at the same HEAD.

Deep mode: ``GOLDEN_DEEP=1`` disables example derandomization and raises
max_examples to 25 for a longer randomized soak. The default (fast,
derandomized) run keeps CI inside the <120 s budget; **deep mode must pass at
least once before the Phase 5 merge** (record the run in EVAL_LOG.md).

This file must exist before the indexer is written and must pass before every
merge to main. It may never be deleted, skipped, or weakened.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

# The Phase-1 public API the golden test pins down. Importing at module level
# is deliberate: the test is red until the indexer exists.
from codesherpa.gitlayer.sync import sync
from codesherpa.store.sqlite_store import SQLiteIndexStore

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
            p
            for p in out
            if p.endswith((".py", ".ts", ".tsx", ".js", ".md")) and not p.startswith(".")
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
        # commit; this is the degenerate flavor — op_merge_change below is the
        # one that makes merges actually move the tree.
        self.git("merge", "-q", "-s", "ours", "--no-edit", victim)

    def op_merge_change(self, seed: int) -> None:
        """The real post-merge/git-pull scenario: a side branch adds a new
        file (never conflicts) and is merged back with the default strategy,
        so the merge itself introduces new blobs that sync must pick up."""
        base = self.current_branch()
        self.counter += 1
        n = self.counter
        side = f"golden-side-{n}"
        self.git("checkout", "-q", "-b", side)
        rel = f"pyserver/merged_mod_{n}.py"
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f'"""Module merged from a side branch (seed {seed})."""\n\n\n'
            f"def merged_func_{n}() -> int:\n"
            f"    return {seed % 89}\n",
            encoding="utf-8",
        )
        self.commit_all(f"side work {n}")
        self.git("checkout", "-q", base)
        # --no-ff forces a true merge commit; the new file cannot conflict,
        # but abort cleanly if anything unexpected happens (op stays total).
        result = self.git("merge", "-q", "--no-ff", "--no-edit", side, check=False)
        if result.returncode != 0:
            self.git("merge", "--abort", check=False)

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
        elif kind == "merge_change":
            self.op_merge_change(op[1])
        elif kind == "revert":
            self.op_revert()
        else:  # pragma: no cover - strategy and interpreter must stay in sync
            raise AssertionError(f"unknown op {op!r}")


def _project_active_blobs(store: SQLiteIndexStore) -> set[str]:
    return store.active_blobs()


def _project_files_head(store: SQLiteIndexStore) -> dict[str, str]:
    return store.files_for_ref("HEAD")


def _project_chunks(store: SQLiteIndexStore) -> dict[str, list[tuple[str, str]]]:
    return {
        blob: [(c.chunk_id, c.code) for c in store.chunks_for_blob(blob)]
        for blob in sorted(store.active_blobs())
    }


def _project_fts(store: SQLiteIndexStore) -> tuple[frozenset[str], tuple[str, ...]]:
    """(active chunk ids present in FTS, active chunk ids MISSING from FTS).

    The second element must be empty — asserted explicitly by the test — so
    FTS coverage failures name the exact chunks instead of a bare bool.
    """
    fts_ids = {
        row[0] for row in store.conn.execute("SELECT chunk_id FROM chunks_fts")
    }
    active_ids = {
        row[0]
        for row in store.conn.execute(
            """
            SELECT c.chunk_id FROM chunks c
            JOIN blobs b ON b.blob_hash = c.blob_hash AND b.active = 1
            """
        )
    }
    return frozenset(fts_ids & active_ids), tuple(sorted(active_ids - fts_ids))


def _project_symbols(store: SQLiteIndexStore) -> tuple[tuple, ...]:
    """Phase 4 extractor (ownership exception per the note below / D14).

    Graph tables are recomputed from the active mapping and replaced on every
    sync (sherpa/graph/index.py, DECISIONS D19), so the WHOLE table —
    including file_path — must match between incremental and rebuild; no
    active-blob filtering is needed or wanted here.
    """
    rows = store.conn.execute(
        """
        SELECT node_id, symbol, kind, blob_hash, byte_start, byte_end,
               file_path, signature
        FROM symbols ORDER BY node_id
        """
    ).fetchall()
    return tuple(tuple(row) for row in rows)


def _project_edges(store: SQLiteIndexStore) -> tuple[tuple, ...]:
    """Phase 4 extractor (ownership exception; see _project_symbols)."""
    rows = store.conn.execute(
        "SELECT src, dst, kind FROM edges ORDER BY src, dst, kind"
    ).fetchall()
    return tuple(tuple(row) for row in rows)


def _project_embeddings(store: SQLiteIndexStore) -> dict[str, list[tuple[str, int, str]]]:
    """Phase 3 extension (ownership exception per the note below / D14).

    Per active blob: (chunk_id, dim, sha256 of the packed vector bytes) of
    every cached embedding — i.e. presence, dimension, and exact bytes.
    Exact-byte comparison is valid because the golden flows embed through the
    permanent cache with a deterministic encoder (the cache guarantees a
    chunk is embedded at most once, and identical chunk text must yield an
    identical cached vector); the hash only keeps assertion diffs readable.
    If a future golden flow ever uses a nondeterministic encoder, hash
    presence/dim still hold — bytes would then need relaxing, recorded here.
    """
    rows = store.conn.execute(
        """
        SELECT c.blob_hash, e.chunk_id, e.dim, e.vector
        FROM embeddings e
        JOIN chunks c ON c.chunk_id = e.chunk_id
        JOIN blobs b ON b.blob_hash = c.blob_hash AND b.active = 1
        ORDER BY c.blob_hash, e.chunk_id
        """
    ).fetchall()
    out: dict[str, list[tuple[str, int, str]]] = {}
    for row in rows:
        out.setdefault(row["blob_hash"], []).append(
            (row["chunk_id"], row["dim"], hashlib.sha256(row["vector"]).hexdigest())
        )
    return out


# The compared projection, one extractor per logical table. Golden equality is
# defined over the ACTIVE rows only: incremental DBs legitimately retain
# inactive rows (soft deactivation is the design).
#
# NOTE FOR LATER PHASES: Phase 3 MUST extend this projection with an
# embeddings extractor (Phase 4 added symbols + edges below), so the Golden
# Test covers their tables too. Those phases are
# granted an ownership exception to edit GOLDEN_PROJECTION / add their
# extractor functions here — for their tables only; nothing else in this
# file may be touched by other worktrees.
GOLDEN_PROJECTION: dict[str, callable] = {
    "active_blobs": _project_active_blobs,
    "files_head": _project_files_head,
    "chunks_of_active_blobs": _project_chunks,
    "fts_of_active_chunks": _project_fts,
    "symbols": _project_symbols,
    "edges": _project_edges,
    # Phase 3 (retrieval worktree, ownership exception): embeddings of active
    # blobs' chunks. Exercised non-vacuously by tests/test_golden_embeddings.py.
    "embeddings_of_active_blobs": _project_embeddings,
}


def golden_state(db_path: Path) -> dict:
    """The comparable 'active' projection of an index DB."""
    store = SQLiteIndexStore(db_path)
    try:
        return {name: extract(store) for name, extract in GOLDEN_PROJECTION.items()}
    finally:
        store.close()


def _fresh_clone(miniproject: Path, dest: Path) -> RepoDriver:
    shutil.copytree(miniproject, dest)
    shutil.rmtree(dest / ".sherpa", ignore_errors=True)
    return RepoDriver(dest)


_OPS = st.one_of(
    st.tuples(st.just("add"), st.integers(0, 3), st.integers(0, 1000)),
    st.tuples(st.just("modify"), st.integers(0, 1000)),
    st.tuples(st.just("delete"), st.integers(0, 1000)),
    st.tuples(st.just("branch"), st.integers(0, 1000)),
    st.tuples(st.just("switch")),
    st.tuples(st.just("merge"), st.integers(0, 1000)),
    st.tuples(st.just("merge_change"), st.integers(0, 1000)),
    st.tuples(st.just("revert")),
)

# GOLDEN_DEEP=1: longer randomized soak (25 fresh examples). Must pass at
# least once before the Phase 5 merge. Default stays fast + derandomized.
_DEEP = os.environ.get("GOLDEN_DEEP") == "1"


@settings(
    max_examples=25 if _DEEP else 6,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    derandomize=not _DEEP,  # CI-time bound (<120 s) requires a fixed example set
)
@given(ops=st.lists(_OPS, min_size=10, max_size=16))
@example(  # pinned: every op kind at least once, in a history-churning order
    ops=[
        ("add", 0, 7),
        ("modify", 3),
        ("branch", 1),
        ("add", 1, 11),
        ("switch",),
        ("merge", 0),
        ("merge_change", 5),
        ("modify", 5),
        ("delete", 2),
        ("revert",),
        ("branch", 1),
        ("add", 0, 13),
        ("merge_change", 17),
        ("switch",),
    ]
)
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

    for name in GOLDEN_PROJECTION:
        assert incremental[name] == rebuild[name], f"projection {name!r} diverged"
    # FTS must cover every active chunk on both sides (missing-id tuple empty)
    assert incremental["fts_of_active_chunks"][1] == ()
    assert rebuild["fts_of_active_chunks"][1] == ()
