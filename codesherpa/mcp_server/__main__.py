"""``python -m codesherpa.mcp_server [repo_path]`` — run the stdio server.

Startup is deliberately cheap (Phase 5 §3e): it opens the EXISTING index and
serves immediately. No sync, no embedding, no model download ever happens
inside the MCP handshake — ``sherpa init``/``sync`` own those. If the
index has missing embeddings the server still serves (lexical + symbol
channels) and reports a warming status from its tools.
"""

from __future__ import annotations

import sys
from pathlib import Path

from codesherpa.mcp_server.server import create_server


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    repo = Path(args[0]).resolve() if args else Path.cwd()

    from codesherpa.gitlayer.repo import NotARepositoryError
    from codesherpa.retrieve import IndexNotBuiltError, build_retriever

    try:
        retriever, store = build_retriever(str(repo))
    except NotARepositoryError as exc:
        print(
            f"sherpa serve: {exc}\n"
            "sherpa serve: point it at a git repository "
            "(or run `git init` there first).",
            file=sys.stderr,
        )
        return 2
    except IndexNotBuiltError as exc:
        print(f"sherpa serve: {exc}", file=sys.stderr)
        return 2
    create_server(retriever, repo, store=store).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
