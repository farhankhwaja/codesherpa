"""Read-only git plumbing used by the symbol graph and recent-changes tools.

Deliberately subprocess-based and minimal: Phase 4 only needs to *read*
trees, blobs, and history. Full repo tracking (hooks, sync, pygit2) is the
git layer's job (``repograph/gitlayer``, Phase 1). See DECISIONS.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Union

from repograph.graph.extract import SourceFile
from repograph.graph.languages import language_for_path

__all__ = [
    "git_output",
    "files_at_rev",
    "read_blobs",
    "source_files_at_rev",
    "last_change_dates",
]


def git_output(repo: Union[str, Path], *args: str) -> str:
    """Run a read-only git command in ``repo`` and return stdout as text."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        text=False,  # blob content may not be valid UTF-8
    )
    return result.stdout.decode("utf-8", errors="replace")


def files_at_rev(repo: Union[str, Path], rev: str = "HEAD") -> dict[str, str]:
    """Repo-relative path -> blob hash for every file in ``rev``'s tree."""
    out = git_output(repo, "ls-tree", "-r", "-z", rev)
    mapping: dict[str, str] = {}
    for entry in out.split("\0"):
        if not entry:
            continue
        meta, _tab, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob":
            mapping[path] = parts[2]
    return mapping


def read_blobs(repo: Union[str, Path], blob_hashes: list[str]) -> dict[str, bytes]:
    """Batch-read blob contents via one ``git cat-file --batch`` call."""
    if not blob_hashes:
        return {}
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input="\n".join(blob_hashes).encode() + b"\n",
        capture_output=True,
        check=True,
    )
    data = result.stdout
    contents: dict[str, bytes] = {}
    pos = 0
    while pos < len(data):
        newline = data.index(b"\n", pos)
        header = data[pos:newline].decode()
        fields = header.split()
        if len(fields) == 3 and fields[1] == "blob":
            oid, _kind, size = fields[0], fields[1], int(fields[2])
            contents[oid] = data[newline + 1 : newline + 1 + size]
            pos = newline + 1 + size + 1  # trailing newline after content
        else:  # "<oid> missing"
            pos = newline + 1
    return contents


def source_files_at_rev(repo: Union[str, Path], rev: str = "HEAD") -> list[SourceFile]:
    """All graph-supported source files in ``rev``'s tree, ready to extract."""
    path_to_blob = files_at_rev(repo, rev)
    supported = {
        path: blob
        for path, blob in path_to_blob.items()
        if language_for_path(path) is not None
    }
    contents = read_blobs(repo, sorted(set(supported.values())))
    files: list[SourceFile] = []
    for path in sorted(supported):
        blob = supported[path]
        language = language_for_path(path)
        if blob in contents and language is not None:
            files.append(
                SourceFile(path=path, blob_hash=blob, language=language, data=contents[blob])
            )
    return files


def last_change_dates(repo: Union[str, Path], rev: str = "HEAD") -> dict[str, str]:
    """Path -> ISO date of the most recent commit touching it (for ranking)."""
    out = git_output(
        repo, "log", rev, "--format=%x01%aI", "--name-only", "--no-renames"
    )
    dates: dict[str, str] = {}
    current: Optional[str] = None
    for line in out.splitlines():
        if line.startswith("\x01"):
            current = line[1:]
        elif line and current is not None:
            dates.setdefault(line, current)  # first hit = most recent commit
    return dates
