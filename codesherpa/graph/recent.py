"""Recent-changes queries: commits, files, and changed symbols since a ref
or ISO date (CLAUDE.md §7.6 — the triage superpower behind
``get_recent_changes``).

Symbol-level diffing reuses :func:`codesherpa.graph.extract.extract_file` on
the old and new blob of each touched file: a symbol is *added*, *removed*,
or *modified* (same name+kind, different source text).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from codesherpa.contracts.types import SymbolKind
from codesherpa.graph.extract import SourceFile, extract_file
from codesherpa.graph.gitio import git_output
from codesherpa.graph.languages import language_for_path

__all__ = ["ChangedSymbol", "CommitChange", "recent_changes"]

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_MAX_SYMBOLS_PER_COMMIT = 50

_FIELD_SEP = "\x02"
_COMMIT_MARK = "\x01"


@dataclass(frozen=True)
class ChangedSymbol:
    path: str
    symbol: str
    kind: str
    change: str  # added | removed | modified

    def to_dict(self) -> dict:
        return {"path": self.path, "symbol": self.symbol, "kind": self.kind, "change": self.change}


@dataclass(frozen=True)
class CommitChange:
    sha: str
    date: str
    author: str
    message: str
    files: tuple[str, ...]
    symbols: tuple[ChangedSymbol, ...] = field(default=())

    def to_dict(self) -> dict:
        return {
            "sha": self.sha[:12],
            "date": self.date,
            "author": self.author,
            "message": self.message,
            "files": list(self.files),
            "changed_symbols": [s.to_dict() for s in self.symbols],
        }


def _defs_at(repo: Union[str, Path], sha_path: str, path: str) -> dict[tuple[str, str], str]:
    """(symbol, kind) -> source text for definitions in ``<sha>:<path>``."""
    language = language_for_path(path)
    if language is None:
        return {}
    try:
        data = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-p", sha_path],
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return {}  # path absent at that revision
    nodes = extract_file(SourceFile(path=path, blob_hash="0" * 40, language=language, data=data))
    return {
        (node.symbol, node.kind.value): data[node.byte_start : node.byte_end].decode(
            "utf-8", errors="replace"
        )
        for node in nodes
        if node.kind is not SymbolKind.MODULE
    }


def _symbol_diff(repo: Union[str, Path], sha: str, path: str, status: str) -> list[ChangedSymbol]:
    old = {} if status == "A" else _defs_at(repo, f"{sha}^:{path}", path)
    new = {} if status == "D" else _defs_at(repo, f"{sha}:{path}", path)
    changes = []
    for symbol, kind in sorted(new.keys() - old.keys()):
        changes.append(ChangedSymbol(path, symbol, kind, "added"))
    for symbol, kind in sorted(old.keys() - new.keys()):
        changes.append(ChangedSymbol(path, symbol, kind, "removed"))
    for symbol, kind in sorted(old.keys() & new.keys()):
        if old[(symbol, kind)] != new[(symbol, kind)]:
            changes.append(ChangedSymbol(path, symbol, kind, "modified"))
    return changes


def recent_changes(
    repo: Union[str, Path], since: str, limit: int = 20
) -> list[CommitChange]:
    """Commits (newest first) since a git ref or ISO date, with symbol diffs.

    ``since`` is either a ref (``HEAD~5``, a branch, a SHA — commits in
    ``since..HEAD``) or an ISO date (``2024-01-06`` — commits from UTC
    midnight of that date; a full ISO datetime is passed through verbatim).
    Raises ValueError for a ref git does not know.
    """
    log_args = [
        "log",
        f"--format={_COMMIT_MARK}%H{_FIELD_SEP}%aI{_FIELD_SEP}%an{_FIELD_SEP}%s",
        "--name-status",
        "--no-renames",
    ]
    if _ISO_DATE_RE.match(since):
        # a BARE date is pinned to UTC midnight: git's approxidate would
        # otherwise read "2024-01-07" as that date at the CURRENT time of
        # day, silently dropping same-day commits depending on when (and in
        # which timezone) the query runs — found as a time-of-day-dependent
        # test failure in Phase 5
        value = f"{since}T00:00:00Z" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", since) else since
        log_args += [f"--since={value}", "HEAD"]
    else:
        log_args += [f"{since}..HEAD"]
    try:
        out = git_output(repo, *log_args)
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"unknown ref or bad --since value: {since!r}") from exc

    commits: list[CommitChange] = []
    current: Optional[dict] = None

    def _flush() -> None:
        if current is None:
            return
        symbols: list[ChangedSymbol] = []
        for status, path in current["files"]:
            if len(symbols) >= _MAX_SYMBOLS_PER_COMMIT:
                break
            symbols.extend(_symbol_diff(repo, current["sha"], path, status))
        commits.append(
            CommitChange(
                sha=current["sha"],
                date=current["date"],
                author=current["author"],
                message=current["message"],
                files=tuple(path for _status, path in current["files"]),
                symbols=tuple(symbols[:_MAX_SYMBOLS_PER_COMMIT]),
            )
        )

    for line in out.splitlines():
        if line.startswith(_COMMIT_MARK):
            _flush()
            if len(commits) >= limit:
                current = None
                break
            sha, date, author, message = line[1:].split(_FIELD_SEP, 3)
            current = {"sha": sha, "date": date, "author": author, "message": message, "files": []}
        elif line and current is not None:
            status, _tab, path = line.partition("\t")
            if status and path:
                current["files"].append((status[0], path))
    _flush()
    return commits[:limit]
