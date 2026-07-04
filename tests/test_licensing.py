"""Licensing/governance artifacts (relicense MIT -> Apache-2.0, 2026-07-05).

No test guarded the LICENSE before the relicense; these pin the Apache-2.0
posture so a stray edit can't silently change the project's legal terms.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_license_is_apache_2_0():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text
    assert "Version 2.0, January 2004" in text
    assert "Copyright 2026 Farhan Khwaja" in text
    assert "MIT License" not in text


def test_notice_file_present_with_copyright():
    text = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert text.splitlines()[0].strip() == "codesherpa"
    assert "Copyright 2026 Farhan Khwaja" in text


def test_pyproject_declares_spdx_apache_2_0():
    import tomllib

    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["license"] == "Apache-2.0"  # PEP 639 SPDX expression
    assert "LICENSE" in meta["project"]["license-files"]
    assert "NOTICE" in meta["project"]["license-files"]


def test_contributing_documents_dco_and_licensing():
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "Signed-off-by" in text
    assert "developercertificate.org" in text
    assert "Apache-2.0" in text
