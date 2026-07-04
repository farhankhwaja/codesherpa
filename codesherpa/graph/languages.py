"""Language registry for the symbol graph.

Adding a language = adding a ``queries/<name>.scm`` file plus one
:class:`LanguageSpec` entry here (query file, module naming, import
resolution). Nothing else in ``graph/`` is language-specific.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Callable, Optional

# (module_text, importer_path, project_paths) -> repo-relative path or None
ImportResolver = Callable[[str, str, frozenset[str]], Optional[str]]


@dataclass(frozen=True)
class LanguageSpec:
    name: str
    query_file: str
    """Filename under ``codesherpa/graph/queries/``."""

    module_name: Callable[[str], str]
    """Repo-relative file path -> symbol name of the file's MODULE node."""

    resolve_import: ImportResolver
    """Resolve an import's module text to a repo-relative file path."""


# ----------------------------------------------------------------- python

def _py_module_name(path: str) -> str:
    if path.endswith(".py"):
        path = path[: -len(".py")]
    if path.endswith("/__init__"):
        path = path[: -len("/__init__")]
    return path.replace("/", ".")


def _py_resolve_import(
    module_text: str, importer_path: str, project_paths: frozenset[str]
) -> Optional[str]:
    """Resolve ``a.b`` / ``.sibling`` / ``..pkg.mod`` to a project file."""
    if module_text.startswith("."):
        dots = len(module_text) - len(module_text.lstrip("."))
        rest = module_text[dots:]
        base_parts = importer_path.split("/")[:-1]  # importing file's package
        for _ in range(dots - 1):
            if base_parts:
                base_parts.pop()
        parts = base_parts + ([p for p in rest.split(".") if p] if rest else [])
    else:
        parts = module_text.split(".")
    if not parts:
        return None
    stem = "/".join(parts)
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if candidate in project_paths:
            return candidate
    return None


# ------------------------------------------------------- typescript / js

def _ts_module_name(path: str) -> str:
    stem, dot, _ext = path.rpartition(".")
    return stem if dot else path


_TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def _ts_resolve_import(
    module_text: str, importer_path: str, project_paths: frozenset[str]
) -> Optional[str]:
    """Resolve a relative import source like ``./http`` or ``../utils/format``."""
    if not module_text.startswith("."):
        return None  # bare specifier -> external package, out of scope
    base = posixpath.dirname(importer_path)
    stem = posixpath.normpath(posixpath.join(base, module_text))
    if stem in project_paths:
        return stem
    for suffix in _TS_SUFFIXES:
        if f"{stem}{suffix}" in project_paths:
            return f"{stem}{suffix}"
    for suffix in _TS_SUFFIXES:
        if f"{stem}/index{suffix}" in project_paths:
            return f"{stem}/index{suffix}"
    return None


# ------------------------------------------------------------------- go

def _go_module_name(path: str) -> str:
    """Per-file module symbol, like TS: path without extension."""
    return path[: -len(".go")] if path.endswith(".go") else path


def _go_resolve_import(
    module_text: str, importer_path: str, project_paths: frozenset[str]
) -> Optional[str]:
    """Resolve a Go import path to a project package DIRECTORY, represented
    by its lexicographically first .go file.

    Go imports name a package by module-qualified path
    (``example.com/mod/pkg/sub``); the in-repo directory is a SUFFIX of it.
    Try progressively shorter tails until one matches a directory that
    contains .go files. Standard-library and external imports match nothing
    and resolve to None (out of scope, same as bare TS specifiers).
    """
    text = module_text.strip().strip('"`')
    if not text:
        return None
    parts = [p for p in text.split("/") if p]
    for i in range(len(parts)):
        directory = "/".join(parts[i:])
        files = sorted(
            path
            for path in project_paths
            if path.endswith(".go") and posixpath.dirname(path) == directory
        )
        if files:
            return files[0]
    return None


REGISTRY: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        name="python",
        query_file="python.scm",
        module_name=_py_module_name,
        resolve_import=_py_resolve_import,
    ),
    "typescript": LanguageSpec(
        name="typescript",
        query_file="typescript.scm",
        module_name=_ts_module_name,
        resolve_import=_ts_resolve_import,
    ),
    "tsx": LanguageSpec(
        name="tsx",
        query_file="typescript.scm",  # tsx grammar is a TS superset; queries are shared
        module_name=_ts_module_name,
        resolve_import=_ts_resolve_import,
    ),
    "javascript": LanguageSpec(
        name="javascript",
        query_file="javascript.scm",
        module_name=_ts_module_name,
        resolve_import=_ts_resolve_import,
    ),
    "go": LanguageSpec(
        name="go",
        query_file="go.scm",
        module_name=_go_module_name,
        resolve_import=_go_resolve_import,
    ),
}

_EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
}


def language_for_path(path: str) -> Optional[str]:
    """Language name for a repo-relative path, or None if unsupported."""
    for ext, lang in _EXTENSION_TO_LANGUAGE.items():
        if path.endswith(ext):
            return lang
    return None
