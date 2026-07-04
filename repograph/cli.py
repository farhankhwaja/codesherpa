"""repograph command-line interface.

init/sync/status are live (Phase 1); search arrives in Phase 3, serve in
Phase 4, bench in Phase 5.
"""

from __future__ import annotations

import argparse
import sys

from repograph import __version__

_PHASE_OF = {
    "search": 3,
    "serve": 4,
    "bench": 5,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repograph",
        description=(
            "A git-native, self-updating structural memory for your codebase. "
            "Index once, stay fresh forever, spend far fewer tokens on context."
        ),
    )
    parser.add_argument("--version", action="version", version=f"repograph {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Install git hooks, create .repograph/, run first full index.")
    p_init.add_argument("path", nargs="?", default=".", help="Repository root (default: cwd).")

    p_sync = sub.add_parser("sync", help="Incrementally index new blobs; deactivate unreachable ones.")
    p_sync.add_argument("--quiet", action="store_true", help="Suppress non-error output (used by hooks).")

    p_search = sub.add_parser("search", help="Hybrid search over the index.")
    p_search.add_argument("query", help="Natural-language, symbol, or stack-trace query.")
    p_search.add_argument("--budget-tokens", type=int, default=4000, help="Token budget for packed results.")

    sub.add_parser("status", help="Index freshness, counts, last sync.")
    sub.add_parser("serve", help="Run the MCP stdio server.")
    sub.add_parser("bench", help="Run indexing/retrieval benchmarks.")

    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    from repograph.gitlayer.initialize import init
    from repograph.gitlayer.repo import NotARepositoryError

    try:
        init(args.path, quiet=False)
    except NotARepositoryError as exc:
        print(f"repograph init: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    from repograph.gitlayer.repo import NotARepositoryError
    from repograph.gitlayer.sync import sync

    try:
        sync(".", quiet=args.quiet)
    except NotARepositoryError as exc:
        if not args.quiet:
            print(f"repograph sync: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    from repograph.gitlayer.repo import NotARepositoryError, open_repo, repo_root
    from repograph.gitlayer.sync import default_db_path
    from repograph.store.sqlite_store import SQLiteIndexStore

    try:
        root = repo_root(open_repo("."))
    except NotARepositoryError as exc:
        print(f"repograph status: {exc}", file=sys.stderr)
        return 1
    db = default_db_path(root)
    if not db.exists():
        print("repograph status: no index found — run `repograph init` first.", file=sys.stderr)
        return 1
    store = SQLiteIndexStore(db)
    try:
        counts = {
            table: store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("blobs", "chunks", "symbols", "edges", "embeddings")
        }
        active = len(store.active_blobs())
        files = len(store.files_for_ref("HEAD"))
        print(f"index:      {db}")
        print(f"last sync:  {store.get_meta('last_sync') or 'never'}")
        print(f"head:       {store.get_meta('last_sync_head') or 'unknown'}")
        print(f"files@HEAD: {files}")
        print(f"blobs:      {active} active / {counts['blobs']} total")
        print(f"chunks:     {counts['chunks']}")
        print(f"symbols:    {counts['symbols']}  edges: {counts['edges']}")
        print(f"embeddings: {counts['embeddings']}")
    finally:
        store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "sync":
        return _cmd_sync(args)
    if args.command == "status":
        return _cmd_status(args)

    phase = _PHASE_OF[args.command]
    print(
        f"repograph {args.command}: not implemented yet (arrives in Phase {phase}).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
