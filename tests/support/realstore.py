"""Build a REAL index of the miniproject fixture for retrieval tests.

Pipeline: copy the fixture -> real gitlayer ``sync`` (real pygit2 blob diff,
real cAST chunker, real SQLite store with FTS5/sqlite-vec) -> test-support
symbol/edge population (Phase 4 dependency, see indexer.py).

Import the ``real_index`` fixture into a test module to get a session-scoped
(store, repo_root) pair:

    from tests.support.realstore import real_index  # noqa: F401
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import NamedTuple

import pytest

from repograph.gitlayer.sync import sync
from repograph.store.sqlite_store import SQLiteIndexStore
from tests.support.indexer import populate_symbols_and_edges


class RealIndex(NamedTuple):
    store: SQLiteIndexStore
    repo_root: Path
    db_path: Path


def build_real_index(miniproject: Path, work_dir: Path) -> RealIndex:
    """Clone the fixture into ``work_dir`` and index it for real."""
    repo_root = work_dir / "repo"
    shutil.copytree(miniproject, repo_root)
    shutil.rmtree(repo_root / ".repograph", ignore_errors=True)
    db_path = work_dir / "index.db"
    sync(repo_root, db_path)
    store = SQLiteIndexStore(db_path)
    populate_symbols_and_edges(store, repo_root)
    return RealIndex(store=store, repo_root=repo_root, db_path=db_path)


@pytest.fixture(scope="session")
def real_index(miniproject, tmp_path_factory) -> RealIndex:
    idx = build_real_index(miniproject, tmp_path_factory.mktemp("realindex"))
    yield idx
    idx.store.close()
