#!/usr/bin/env python3
"""Golden Test against a REAL repository's history (CLAUDE.md §10 Phase 5).

Replays the last N commits of an external repo (first-parent order): checkout
each commit oldest→newest and `sync` incrementally into one database, then
rebuild a second database from scratch at the final HEAD. The full golden
projection (active blobs, files, chunks, FTS, symbols, edges, embeddings)
must be identical — a stale index is worse than no index.

Usage:
    python eval/golden_replay.py /path/to/repo-clone [--commits 30]

The repo is cloned to a temp dir first, so the argument repo is never touched.
Exit 0 = projections identical; exit 1 = divergence (printed).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from codesherpa.gitlayer.sync import sync  # noqa: E402
from test_golden import GOLDEN_PROJECTION, golden_state  # noqa: E402


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "advice.detachedHead=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="Path to the repo to replay (cloned, not modified).")
    parser.add_argument("--commits", type=int, default=30)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="golden-replay-") as tmp:
        work = Path(tmp) / "repo"
        subprocess.run(
            ["git", "clone", "--quiet", str(Path(args.repo).resolve()), str(work)],
            check=True,
        )
        commits = _git(
            work, "rev-list", "--first-parent", f"--max-count={args.commits}", "HEAD"
        ).split()
        commits.reverse()  # oldest first
        print(f"replaying {len(commits)} commits of {args.repo}")

        inc_db = Path(tmp) / "incremental.db"
        started = time.perf_counter()
        for i, commit in enumerate(commits):
            _git(work, "checkout", "--quiet", commit)
            stats = sync(work, inc_db)
            print(
                f"  [{i + 1:2}/{len(commits)}] {commit[:10]} "
                f"+{stats.blobs_indexed} blobs / -{stats.blobs_deactivated} "
                f"({stats.seconds:.2f}s)"
            )
        replay_seconds = time.perf_counter() - started

        rebuild_db = Path(tmp) / "rebuild.db"
        rebuild_stats = sync(work, rebuild_db)
        print(
            f"rebuild at final HEAD: {rebuild_stats.blobs_indexed} blobs "
            f"({rebuild_stats.seconds:.2f}s); incremental replay total "
            f"{replay_seconds:.2f}s"
        )

        incremental = golden_state(inc_db)
        rebuild = golden_state(rebuild_db)
        failed = [
            name for name in GOLDEN_PROJECTION if incremental[name] != rebuild[name]
        ]
        if failed:
            print(f"GOLDEN REPLAY: FAIL — diverged projections: {failed}")
            return 1
        print(
            "GOLDEN REPLAY: PASS — incremental == rebuild across "
            f"{len(GOLDEN_PROJECTION)} projections"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
