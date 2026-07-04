from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MINIPROJECT_DIR = FIXTURES_DIR / "miniproject"


def _load_builder():
    sys.path.insert(0, str(FIXTURES_DIR))
    try:
        import build_miniproject
    finally:
        sys.path.pop(0)
    return build_miniproject


def _is_built(path: Path, builder) -> bool:
    if not (path / ".git").is_dir():
        return False
    # a prebuilt fixture from an older builder version must be rebuilt
    marker = path / ".git" / builder._VERSION_MARKER
    if not marker.is_file() or marker.read_text().strip() != str(builder.FIXTURE_VERSION):
        return False
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and int(result.stdout.strip() or 0) >= 5


@pytest.fixture(scope="session")
def miniproject(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The miniproject fixture repo, built on demand at its canonical location.

    The generated repo lives at tests/fixtures/miniproject/ (gitignored in the
    outer repo); the build script is the committed source of truth.
    """
    builder = _load_builder()
    if not _is_built(MINIPROJECT_DIR, builder):
        builder.build(MINIPROJECT_DIR)
    return MINIPROJECT_DIR


@pytest.fixture(scope="session")
def synced_miniproject(
    miniproject: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path]:
    """(repo_clone, db_path): the fixture indexed by the REAL sync pipeline.

    Session-scoped and shared — treat the store as read-only; tests that
    mutate index state must sync their own clone. (Phase 4 addition.)
    """
    from codesherpa.gitlayer.sync import sync

    tmp = tmp_path_factory.mktemp("synced-miniproject")
    repo = tmp / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".sherpa", ignore_errors=True)
    db = tmp / "index.db"
    sync(repo, db)
    return repo, db
