from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MINIPROJECT_DIR = FIXTURES_DIR / "miniproject"


def _is_built(path: Path) -> bool:
    if not (path / ".git").is_dir():
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
    if not _is_built(MINIPROJECT_DIR):
        sys.path.insert(0, str(FIXTURES_DIR))
        try:
            import build_miniproject
        finally:
            sys.path.pop(0)
        build_miniproject.build(MINIPROJECT_DIR)
    return MINIPROJECT_DIR
