"""repograph command-line interface.

Phase 0 ships the argument surface only; subcommands are implemented in later
phases (init/sync: Phase 1, search: Phase 3, serve: Phase 4, bench: Phase 5).
"""

from __future__ import annotations

import argparse
import sys

from repograph import __version__

_PHASE_OF = {
    "init": 1,
    "sync": 1,
    "status": 1,
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    phase = _PHASE_OF[args.command]
    print(
        f"repograph {args.command}: not implemented yet (arrives in Phase {phase}).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
