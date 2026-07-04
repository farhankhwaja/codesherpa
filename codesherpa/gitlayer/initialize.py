"""``sherpa init``: hooks + .sherpa/ + .gitignore + first full index."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from codesherpa.gitlayer.repo import install_hooks, open_repo, repo_root
from codesherpa.gitlayer.sync import SyncStats, default_db_path, sync

_GITIGNORE_LINE = ".sherpa/"


@dataclass
class InitResult:
    db_path: Path
    hooks_installed: list[str]
    gitignore_updated: bool
    stats: SyncStats


def ensure_gitignore(root: Path) -> bool:
    """Make sure ``.sherpa/`` is gitignored; returns True if we edited."""
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        lines = gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
        if any(line.strip().rstrip("/") == _GITIGNORE_LINE.rstrip("/") for line in lines):
            return False
        content = gitignore.read_text(encoding="utf-8", errors="replace")
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"\n# sherpa index (local, never commit)\n{_GITIGNORE_LINE}\n"
        gitignore.write_text(content, encoding="utf-8")
        return True
    gitignore.write_text(
        f"# sherpa index (local, never commit)\n{_GITIGNORE_LINE}\n",
        encoding="utf-8",
    )
    return True


def init(repo_path: Path | str, quiet: bool = False) -> InitResult:
    repo = open_repo(Path(repo_path))
    root = repo_root(repo)

    db_path = default_db_path(root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    gitignore_updated = ensure_gitignore(root)
    hooks = install_hooks(repo)
    if not quiet and (root / ".repograph").is_dir():
        print(
            "sherpa: found a legacy .repograph/ index directory (pre-rename); "
            "it is no longer used — safe to delete.",
            file=sys.stderr,
        )
    stats = sync(root, quiet=quiet)

    if not quiet:
        print(
            f"sherpa: initialized {db_path}\n"
            f"sherpa: hooks installed: {', '.join(hooks) if hooks else '(already present)'}\n"
            f"sherpa: .gitignore {'updated' if gitignore_updated else 'already covers .sherpa/'}\n"
            f"sherpa: first index: {stats.blobs_indexed} blobs, "
            f"{stats.chunks_added} chunks, {stats.files_mapped} files "
            f"({stats.seconds:.2f}s)",
            file=sys.stderr,
        )
    return InitResult(db_path, hooks, gitignore_updated, stats)
