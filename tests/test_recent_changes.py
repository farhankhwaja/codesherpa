"""Phase 4: get_recent_changes(since) correct against fixture history."""

from __future__ import annotations

from pathlib import Path

import pytest

from repograph.graph.recent import recent_changes


def test_since_ref_returns_newest_first(miniproject: Path):
    commits = recent_changes(miniproject, "HEAD~2")
    assert len(commits) == 2
    assert commits[0].message == "feat: password hashing and session tokens"
    assert commits[1].message == "feat: webhook notifications, user cache, cli; drop legacy sync"
    assert commits[0].date > commits[1].date


def test_since_iso_date(miniproject: Path):
    commits = recent_changes(miniproject, "2024-01-06")
    assert [c.message for c in commits] == ["feat: password hashing and session tokens"]
    # a date before all history returns everything (6 fixture commits)
    assert len(recent_changes(miniproject, "2024-01-01")) == 6


def test_symbol_level_diffing(miniproject: Path):
    latest = recent_changes(miniproject, "HEAD~1")[0]
    assert set(latest.files) == {
        "pyserver/auth.py",
        "pyserver/routes/users.py",
        "webclient/src/auth.ts",
    }
    changes = {(s.path, s.symbol): s.change for s in latest.symbols}
    # new module -> added symbols
    assert changes[("pyserver/auth.py", "hash_password")] == "added"
    assert changes[("pyserver/auth.py", "create_session_token")] == "added"
    # create_user body changed; get_user did not
    assert changes[("pyserver/routes/users.py", "create_user")] == "modified"
    assert ("pyserver/routes/users.py", "get_user") not in changes
    # TS: clearToken added, login switched to fetchWithRetry
    assert changes[("webclient/src/auth.ts", "clearToken")] == "added"
    assert changes[("webclient/src/auth.ts", "login")] == "modified"


def test_deleted_file_symbols_are_removed(miniproject: Path):
    commits = recent_changes(miniproject, "HEAD~2")
    services = commits[1]
    changes = {(s.path, s.symbol): s.change for s in services.symbols}
    assert changes[("pyserver/legacy.py", "old_sync_tasks")] == "removed"


def test_limit_caps_commits(miniproject: Path):
    assert len(recent_changes(miniproject, "2024-01-01", limit=3)) == 3


def test_unknown_ref_raises_value_error(miniproject: Path):
    with pytest.raises(ValueError, match="unknown ref"):
        recent_changes(miniproject, "no-such-branch")


def test_to_dict_is_compact(miniproject: Path):
    payload = recent_changes(miniproject, "HEAD~1")[0].to_dict()
    assert payload["sha"] == payload["sha"][:12]
    assert {"sha", "date", "author", "message", "files", "changed_symbols"} == set(payload)
