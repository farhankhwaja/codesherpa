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
    result = subprocess.run(
        [sys.executable, "-m", "repograph.cli", "status"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "not implemented" in result.stderr


def test_version_flag() -> None:
    from repograph import __version__

    result = subprocess.run(
        [sys.executable, "-m", "repograph.cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout
