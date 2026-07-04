"""Skip rules for indexing (CLAUDE.md §7.1).

Committed files already passed .gitignore, so HEAD-tree indexing only needs
the extra layers: vendored/generated/binary skips and the user's
``.sherpaignore``.

``.sherpaignore`` supports a pragmatic gitignore subset (documented in
``SherpaIgnore``): comments, blank lines, ``dir/`` prefixes, ``/``-anchored
patterns, and ``fnmatch`` globs against both the full path and the basename.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

IGNORE_FILENAME = ".sherpaignore"

# Directory components that are always vendored/generated noise.
SKIP_DIR_COMPONENTS = {
    ".sherpa",
    "node_modules",
    "bower_components",
    "vendor",
    "vendored",
    "third_party",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
}

# Generated single files (lockfiles etc.).
SKIP_BASENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
}

# Minified / bundled artifacts.
SKIP_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".map")

# Anything bigger than this is generated with near-certainty and would only
# bloat the index (the 5 MB generated-JS verifier attack lands here).
MAX_FILE_BYTES = 2 * 1024 * 1024


def looks_binary(data: bytes) -> bool:
    """Cheap binary sniff: a NUL byte in the first 8 KiB."""
    return b"\x00" in data[:8192]


class SherpaIgnore:
    """Patterns from ``.sherpaignore`` (empty rule set if absent)."""

    def __init__(self, patterns: list[str]) -> None:
        self.dir_prefixes: list[str] = []
        self.anchored: list[str] = []
        self.globs: list[str] = []
        for raw in patterns:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith("/"):
                self.dir_prefixes.append(line.strip("/"))
            elif line.startswith("/"):
                self.anchored.append(line.lstrip("/"))
            else:
                self.globs.append(line)

    @classmethod
    def load(cls, repo_root: Path) -> "SherpaIgnore":
        path = repo_root / IGNORE_FILENAME
        if path.is_file():
            return cls(path.read_text(encoding="utf-8", errors="replace").splitlines())
        return cls([])

    def matches(self, rel_path: str) -> bool:
        posix = PurePosixPath(rel_path)
        parts = posix.parts
        for prefix in self.dir_prefixes:
            if prefix in parts[:-1]:
                return True
        for pattern in self.anchored:
            if fnmatchcase(rel_path, pattern):
                return True
        basename = posix.name
        for pattern in self.globs:
            if fnmatchcase(rel_path, pattern) or fnmatchcase(basename, pattern):
                return True
        return False


class IgnoreRules:
    """Combined built-in + user skip rules, decided from path and size only.

    Content-based skipping (binary sniff) happens separately at blob-read
    time via :func:`looks_binary`.
    """

    def __init__(self, user_rules: SherpaIgnore) -> None:
        self.user_rules = user_rules

    @classmethod
    def load(cls, repo_root: Path) -> "IgnoreRules":
        return cls(SherpaIgnore.load(repo_root))

    def skip_path(self, rel_path: str, size_bytes: int) -> bool:
        posix = PurePosixPath(rel_path)
        if size_bytes > MAX_FILE_BYTES:
            return True
        if any(part in SKIP_DIR_COMPONENTS for part in posix.parts[:-1]):
            return True
        if posix.name in SKIP_BASENAMES:
            return True
        if rel_path.endswith(SKIP_SUFFIXES):
            return True
        return self.user_rules.matches(rel_path)
