"""Phase 0: the package installs and `repograph --help` runs."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest


def test_module_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "repograph.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "repograph" in result.stdout
    for command in ("init", "sync", "search", "status", "serve", "bench"):
        assert command in result.stdout


def test_console_script_help_runs() -> None:
    exe = shutil.which("repograph")
    if exe is None:
        pytest.fail("console script `repograph` not on PATH — was the package pip-installed?")
    result = subprocess.run([exe, "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "repograph" in result.stdout


def test_unimplemented_subcommand_exits_nonzero() -> None:
    # `bench` is the remaining not-yet-implemented command (Phase 0 probed
    # `status`, Phases 1–4 probed `search`; Phase 5 implemented search — see
    # DECISIONS.md D5 precedent: the probe moves, the assertions never weaken).
    result = subprocess.run(
        [sys.executable, "-m", "repograph.cli", "bench"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "not implemented" in result.stderr


def test_serve_refuses_non_repository(tmp_path) -> None:
    """`serve` must fail — never serve fake or accidental data — when pointed
    at a directory that is not a git repository.

    Replaces the retired Phase-3-missing probe (see DECISIONS.md D29, D5
    precedent): the retrieval pipeline now exists, so `serve <valid repo>`
    genuinely serves (covered by the MCP stdio integration test); the
    fail-loudly intent is preserved against the nearest remaining bad input.
    This also keeps the suite free of a real server launch: the failure
    happens before any model load or repo mutation."""
    result = subprocess.run(
        [sys.executable, "-m", "repograph.cli", "serve", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert not (tmp_path / ".repograph" / "index.db").exists()


def test_init_runs_embedding_pass_and_no_embed_skips_it(miniproject, tmp_path, monkeypatch) -> None:
    """Phase 5 §3f: `repograph init` owns the embedding pass (with progress);
    `--no-embed` skips it. The pass itself is stubbed — model behavior is
    covered by tests/test_warm.py."""
    import repograph.cli as cli

    calls: list[dict] = []
    monkeypatch.setattr(
        cli, "_embed_pass", lambda root, *, quiet, hook_safe=False: calls.append(
            {"root": root, "quiet": quiet, "hook_safe": hook_safe}
        ) or 0
    )

    repo = tmp_path / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".repograph", ignore_errors=True)

    assert cli.main(["init", str(repo)]) == 0
    assert len(calls) == 1
    assert calls[0]["quiet"] is False and calls[0]["hook_safe"] is False

    calls.clear()
    assert cli.main(["init", str(repo), "--no-embed"]) == 0
    assert calls == []


def test_sync_embeds_hook_safely_when_quiet(miniproject, tmp_path, monkeypatch) -> None:
    """Quiet syncs come from git hooks: they embed incrementally but must
    never download a model (require_cached_model)."""
    import repograph.cli as cli

    calls: list[dict] = []
    monkeypatch.setattr(
        cli, "_embed_pass", lambda root, *, quiet, hook_safe=False: calls.append(
            {"quiet": quiet, "hook_safe": hook_safe}
        ) or 0
    )

    repo = tmp_path / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".repograph", ignore_errors=True)
    monkeypatch.chdir(repo)

    assert cli.main(["sync", "--quiet"]) == 0
    assert calls == [{"quiet": True, "hook_safe": True}]

    calls.clear()
    assert cli.main(["sync", "--no-embed"]) == 0
    assert calls == []


def test_version_flag() -> None:
    from repograph import __version__

    result = subprocess.run(
        [sys.executable, "-m", "repograph.cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout
