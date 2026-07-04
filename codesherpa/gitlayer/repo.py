"""pygit2 access layer: repo discovery, HEAD tree walking, blob reads, hooks."""

from __future__ import annotations

import stat
from pathlib import Path

import pygit2

HOOK_NAMES = ("post-merge", "post-checkout", "post-rewrite", "post-commit")

# The hook must NEVER break a git operation: no sherpa on PATH -> no-op,
# sync failure -> swallowed (sync itself logs).
_HOOK_MARKER = "# installed by sherpa"
_HOOK_BODY = f"""#!/bin/sh
{_HOOK_MARKER} — keeps .sherpa/index.db fresh after history changes
command -v sherpa >/dev/null 2>&1 && sherpa sync --quiet || true
"""


class NotARepositoryError(RuntimeError):
    pass


def open_repo(path: Path | str) -> pygit2.Repository:
    found = pygit2.discover_repository(str(path))
    if found is None:
        raise NotARepositoryError(f"not inside a git repository: {path}")
    return pygit2.Repository(found)


def repo_root(repo: pygit2.Repository) -> Path:
    if repo.is_bare:
        return Path(repo.path)
    return Path(repo.workdir)


def head_commit_hex(repo: pygit2.Repository) -> str | None:
    if repo.head_is_unborn:
        return None
    return str(repo.head.target)


def head_tree_blobs(repo: pygit2.Repository) -> dict[str, str]:
    """path -> blob hash for every regular-file blob in the HEAD tree.

    Symlinks (mode 120000) and submodules (commit entries) are excluded; an
    unborn HEAD (fresh repo, no commits) yields an empty mapping.
    """
    if repo.head_is_unborn:
        return {}
    result: dict[str, str] = {}

    def walk(tree: pygit2.Tree, prefix: str) -> None:
        for entry in tree:
            path = f"{prefix}{entry.name}"
            if entry.type_str == "tree":
                walk(repo[entry.id], f"{path}/")
            elif entry.type_str == "blob" and not stat.S_ISLNK(entry.filemode):
                result[path] = str(entry.id)

    walk(repo[repo.head.target].tree, "")
    return result


def read_blob(repo: pygit2.Repository, blob_hash: str) -> bytes:
    return repo[blob_hash].data


def blob_size(repo: pygit2.Repository, blob_hash: str) -> int:
    return repo[blob_hash].size


# --------------------------------------------------------------------- hooks


def hooks_dir(repo: pygit2.Repository) -> Path:
    return Path(repo.path) / "hooks"


def install_hooks(repo: pygit2.Repository) -> list[str]:
    """Install (or extend) the four sync hooks; returns the ones touched.

    A hook we already installed is left alone. A pre-existing foreign hook is
    preserved: our command is appended rather than overwriting the file.
    """
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    touched: list[str] = []
    for name in HOOK_NAMES:
        hook = directory / name
        if not hook.exists():
            hook.write_text(_HOOK_BODY, encoding="utf-8")
        else:
            existing = hook.read_text(encoding="utf-8", errors="replace")
            if _HOOK_MARKER in existing or "sherpa sync" in existing:
                continue
            addition = (
                f"\n{_HOOK_MARKER} — appended to existing hook\n"
                "command -v sherpa >/dev/null 2>&1 && sherpa sync --quiet || true\n"
            )
            hook.write_text(existing + addition, encoding="utf-8")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        touched.append(name)
    return touched
