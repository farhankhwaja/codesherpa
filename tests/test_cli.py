"""Phase 0: the package installs and `sherpa --help` runs."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest


def test_module_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codesherpa.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "sherpa" in result.stdout
    for command in ("init", "sync", "search", "status", "serve", "bench"):
        assert command in result.stdout


def test_console_script_help_runs() -> None:
    exe = shutil.which("sherpa")
    if exe is None:
        pytest.fail("console script `sherpa` not on PATH — was the package pip-installed?")
    result = subprocess.run([exe, "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "sherpa" in result.stdout


def test_unsupported_subcommand_exits_nonzero() -> None:
    # Phase 0 probed `status`, Phases 1–4 probed `search`, Phase 5 implemented
    # search and moved the probe to `bench`. `bench` is now implemented too
    # (D48), so NO unimplemented subcommand remains and the probe moves once
    # more — to an unknown subcommand, the nearest remaining "sherpa must
    # refuse a command it cannot serve" case. Same assertions, same strength:
    # exit code 2 and an explanatory stderr message, never a traceback.
    # See DECISIONS.md D5/D29/D48 precedent: the probe moves, the assertions
    # never weaken.
    result = subprocess.run(
        [sys.executable, "-m", "codesherpa.cli", "definitely-not-a-command"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert "Traceback" not in result.stderr


def test_bench_help_documents_both_benchmarks() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codesherpa.cli", "bench", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    for flag in ("--indexing", "--retrieval", "--synthetic", "--query-file"):
        assert flag in result.stdout


def test_bench_outside_repository_is_friendly(tmp_path) -> None:
    """No traceback when there is no repo — consistent with search/gain."""
    result = subprocess.run(
        [sys.executable, "-m", "codesherpa.cli", "bench"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert result.stderr.startswith("sherpa bench:")


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
        [sys.executable, "-m", "codesherpa.cli", "serve", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert not (tmp_path / ".sherpa" / "index.db").exists()


def test_init_runs_embedding_pass_and_no_embed_skips_it(miniproject, tmp_path, monkeypatch) -> None:
    """Phase 5 §3f: `sherpa init` owns the embedding pass (with progress);
    `--no-embed` skips it. The pass itself is stubbed — model behavior is
    covered by tests/test_warm.py."""
    import codesherpa.cli as cli

    calls: list[dict] = []
    monkeypatch.setattr(
        cli, "_embed_pass", lambda root, *, quiet, hook_safe=False: calls.append(
            {"root": root, "quiet": quiet, "hook_safe": hook_safe}
        ) or 0
    )

    repo = tmp_path / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".sherpa", ignore_errors=True)

    assert cli.main(["init", str(repo)]) == 0
    assert len(calls) == 1
    assert calls[0]["quiet"] is False and calls[0]["hook_safe"] is False

    calls.clear()
    assert cli.main(["init", str(repo), "--no-embed"]) == 0
    assert calls == []


def test_sync_embeds_hook_safely_when_quiet(miniproject, tmp_path, monkeypatch) -> None:
    """Quiet syncs come from git hooks: they embed incrementally but must
    never download a model (require_cached_model)."""
    import codesherpa.cli as cli

    calls: list[dict] = []
    monkeypatch.setattr(
        cli, "_embed_pass", lambda root, *, quiet, hook_safe=False: calls.append(
            {"quiet": quiet, "hook_safe": hook_safe}
        ) or 0
    )

    repo = tmp_path / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".sherpa", ignore_errors=True)
    monkeypatch.chdir(repo)

    assert cli.main(["sync", "--quiet"]) == 0
    assert calls == [{"quiet": True, "hook_safe": True}]

    calls.clear()
    assert cli.main(["sync", "--no-embed"]) == 0
    assert calls == []


def test_version_flag() -> None:
    from codesherpa import __version__

    result = subprocess.run(
        [sys.executable, "-m", "codesherpa.cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout
