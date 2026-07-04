"""``python -m repograph.mcp_server [repo_path]`` — run the stdio server.

Wiring depends on the real store (Phase 1) and retrieval pipeline (Phase 3);
until those merge, this entry point reports exactly what is missing instead
of serving mock data (CLAUDE.md §2.5).
"""

from __future__ import annotations

import sys
from pathlib import Path

from repograph.mcp_server.server import create_server


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    repo = Path(args[0]).resolve() if args else Path.cwd()
    try:
        from repograph.retrieve import build_retriever  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        print(
            "repograph-mcp: the retrieval pipeline (repograph.retrieve.build_retriever) "
            "is not available yet — it lands with Phase 3. The MCP server itself is "
            "ready; wire it via repograph.mcp_server.create_server(retriever, repo).",
            file=sys.stderr,
        )
        return 2
    retriever, store = build_retriever(str(repo))
    create_server(retriever, repo, store=store).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
