"""Phase 0: the miniproject fixture is a real git repo with the required shape."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def test_is_a_real_git_repo(miniproject: Path) -> None:
    assert (miniproject / ".git").is_dir()
    assert _git(miniproject, "status", "--porcelain") == ""  # clean tree


def test_at_least_five_commits(miniproject: Path) -> None:
    count = int(_git(miniproject, "rev-list", "--count", "HEAD").strip())
    assert count >= 5


def test_file_counts(miniproject: Path) -> None:
    tracked = _git(miniproject, "ls-files").splitlines()
    py = [f for f in tracked if f.endswith(".py")]
    ts = [f for f in tracked if f.endswith((".ts", ".tsx"))]
    py_substantial = [f for f in py if not f.endswith("__init__.py")]
    assert len(py) >= 15, py
    assert len(py_substantial) >= 15, py_substantial
    assert len(ts) >= 10, ts
    assert any(f.endswith(".tsx") for f in ts), "need TSX coverage"


def test_cross_file_imports_and_calls(miniproject: Path) -> None:
    notifications = (miniproject / "pyserver/services/notifications.py").read_text()
    assert "from pyserver.http_client import HttpClient" in notifications
    assert "retry_request(" in notifications  # cross-file call

    routes = (miniproject / "pyserver/routes/tasks.py").read_text()
    assert "from pyserver.models.task import" in routes
    assert "from pyserver.validators import validate_title" in routes

    store = (miniproject / "webclient/src/store.ts").read_text()
    assert "from './api'" in store
    assert "fetchTasks(" in store  # cross-file call

    tasklist = (miniproject / "webclient/src/components/TaskList.tsx").read_text()
    assert "from './TaskItem'" in tasklist


def test_javascript_file_present(miniproject: Path) -> None:
    # added for Phase 2 verifier info-finding: direct JS coverage in the fixture
    tracked = _git(miniproject, "ls-files").splitlines()
    js = [f for f in tracked if f.endswith(".js")]
    assert js, "fixture needs at least one plain .js file"
    source = (miniproject / "webclient/scripts/export_tasks.js").read_text()
    assert "class TaskExporter" in source
    assert "function formatTaskRow(" in source
    assert "module.exports" in source  # cross-file-callable exports


def test_history_includes_modification_and_deletion(miniproject: Path) -> None:
    # validators.py was modified after its introduction (bugfix commit)
    touches = _git(miniproject, "log", "--oneline", "--follow", "--", "pyserver/validators.py")
    assert len(touches.splitlines()) >= 2

    # legacy.py existed and was deleted; it is gone at HEAD
    log = _git(miniproject, "log", "--diff-filter=D", "--name-only", "--pretty=format:")
    assert "pyserver/legacy.py" in log
    assert not (miniproject / "pyserver/legacy.py").exists()


def test_build_is_deterministic(miniproject: Path, tmp_path: Path) -> None:
    import sys

    fixtures_dir = Path(__file__).parent / "fixtures"
    sys.path.insert(0, str(fixtures_dir))
    try:
        import build_miniproject
    finally:
        sys.path.pop(0)

    rebuilt = build_miniproject.build(tmp_path / "miniproject-copy")
    assert _git(rebuilt, "rev-parse", "HEAD") == _git(miniproject, "rev-parse", "HEAD")
