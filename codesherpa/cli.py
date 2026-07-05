"""sherpa command-line interface.

init/sync/status (Phase 1), serve (Phase 4), search (Phase 5) are live;
bench remains a roadmap wrapper over tests/bench_indexing.py.
"""

from __future__ import annotations

import argparse
import sys

from codesherpa import __version__

_PHASE_OF = {
    "bench": 6,  # roadmap: a user-facing wrapper over tests/bench_indexing.py
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sherpa",
        description=(
            "A git-native, self-updating structural memory for your codebase. "
            "Index once, stay fresh forever, spend far fewer tokens on context."
        ),
    )
    parser.add_argument("--version", action="version", version=f"sherpa {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Install git hooks, create .sherpa/, run first full index.")
    p_init.add_argument("path", nargs="?", default=".", help="Repository root (default: cwd).")
    p_init.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip the embedding pass (semantic search stays cold until `sherpa sync`).",
    )

    p_sync = sub.add_parser("sync", help="Incrementally index new blobs; deactivate unreachable ones.")
    p_sync.add_argument("--quiet", action="store_true", help="Suppress non-error output (used by hooks).")
    p_sync.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip the embedding pass for this sync.",
    )

    p_search = sub.add_parser("search", help="Hybrid search over the index.")
    p_search.add_argument("query", help="Natural-language, symbol, or stack-trace query.")
    p_search.add_argument("--budget-tokens", type=int, default=4000, help="Token budget for packed results.")

    sub.add_parser("status", help="Index freshness, counts, last sync.")

    p_serve = sub.add_parser("serve", help="Run the MCP stdio server.")
    p_serve.add_argument("path", nargs="?", default=".", help="Repository root (default: cwd).")

    sub.add_parser("bench", help="Run indexing/retrieval benchmarks.")

    p_gain = sub.add_parser(
        "gain",
        help="Local usage analytics: what sherpa served, and an honest "
        "estimate of the context it avoided.",
    )
    p_gain.add_argument("--since", help="Only count usage since this ISO date (YYYY-MM-DD).")
    p_gain.add_argument("--days", type=int, help="Only count the last N days.")
    p_gain.add_argument(
        "--html",
        action="store_true",
        help="Write a self-contained HTML report (default .sherpa/gain.html) and print its path.",
    )
    p_gain.add_argument("--out", help="Output path for --html (default: .sherpa/gain.html).")

    return parser


def _embed_progress_printer(stream=None):
    """progress(done, total) callback: \\r updates on a TTY, 10% steps otherwise.

    Cold first runs used to embed for minutes in silence — users assumed a
    hang (Phase 5 §3f). Every embedding pass now narrates itself.
    """
    out = stream if stream is not None else sys.stderr
    tty = getattr(out, "isatty", lambda: False)()
    last_step = -1

    def progress(done: int, total: int) -> None:
        nonlocal last_step
        if total <= 0:
            return
        pct = done * 100 // total
        if tty:
            end = "\n" if done >= total else ""
            print(f"\rsherpa: embedding chunks {done}/{total} ({pct}%)", end=end, file=out, flush=True)
        else:
            step = pct // 10
            if step > last_step or done >= total:
                last_step = step
                print(f"sherpa: embedding chunks {done}/{total} ({pct}%)", file=out, flush=True)

    return progress


def _embed_pass(root, *, quiet: bool, hook_safe: bool = False) -> int:
    """Embed missing chunks for the index at ``root``; returns computed count.

    ``hook_safe=True`` (quiet/hook syncs) never downloads a model — first
    downloads belong to a foreground ``sherpa init``/``sync``.
    """
    from codesherpa.gitlayer.sync import default_db_path
    from codesherpa.retrieve import RetrievalConfig
    from codesherpa.retrieve.warm import missing_embeddings
    from codesherpa.retrieve.warm import embed_index
    from codesherpa.embed.engine import model_is_cached
    from codesherpa.store.sqlite_store import SQLiteIndexStore

    from codesherpa.retrieve.warm import invalidation_pending

    store = SQLiteIndexStore(default_db_path(root))
    try:
        config = RetrievalConfig()
        if not quiet and invalidation_pending(store, config.embed_model):
            # one-time full re-embed must announce itself BEFORE the pass —
            # a silent long sync after a routine pull reads as a hang
            # (D30/D45 plan review, adjustment 2)
            from codesherpa.retrieve.warm import EMBED_TEXT_VERSION, active_chunks

            print(
                f"sherpa: embed text format changed (v{EMBED_TEXT_VERSION}): "
                f"re-embedding {len(active_chunks(store))} chunks, one time",
                file=sys.stderr,
                flush=True,
            )
        missing = missing_embeddings(store)
        if missing and not quiet:
            if not model_is_cached(config.model_cache_dir, config.embed_model):
                print(
                    f"sherpa: downloading embedding model {config.embed_model} "
                    f"(one-time, ~0.5 GB) to {config.model_cache_dir} …",
                    file=sys.stderr,
                    flush=True,
                )
            print(
                f"sherpa: embedding {missing} chunks (CPU; incremental — "
                "only new chunks are ever re-embedded)",
                file=sys.stderr,
                flush=True,
            )
        return embed_index(
            store,
            config=config,
            progress=None if quiet else _embed_progress_printer(),
            require_cached_model=hook_safe,
            defer_invalidation=hook_safe,  # hooks never absorb a full re-embed
        )
    finally:
        store.close()


def _cmd_init(args: argparse.Namespace) -> int:
    from pathlib import Path

    from codesherpa.gitlayer.initialize import init
    from codesherpa.gitlayer.repo import NotARepositoryError

    try:
        result = init(args.path, quiet=False)
    except NotARepositoryError as exc:
        print(f"sherpa init: {exc}", file=sys.stderr)
        return 1
    if args.no_embed:
        print(
            "sherpa: --no-embed: semantic search stays cold until `sherpa sync`.",
            file=sys.stderr,
        )
        return 0
    _embed_pass(Path(result.db_path).parent.parent, quiet=False)
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    from codesherpa.gitlayer.repo import NotARepositoryError, open_repo, repo_root
    from codesherpa.gitlayer.sync import sync

    try:
        sync(".", quiet=args.quiet)
        root = repo_root(open_repo("."))
    except NotARepositoryError as exc:
        if not args.quiet:
            print(f"sherpa sync: {exc}", file=sys.stderr)
        return 1
    if not args.no_embed:
        # quiet syncs come from git hooks: embed incrementally but never
        # download a model from inside a hook (require the cache to be warm)
        _embed_pass(root, quiet=args.quiet, hook_safe=args.quiet)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    from codesherpa.gitlayer.repo import NotARepositoryError
    from codesherpa.retrieve import IndexNotBuiltError, build_retriever

    try:
        retriever, store = build_retriever(".")
    except NotARepositoryError as exc:
        print(f"sherpa search: {exc}", file=sys.stderr)
        return 1
    except IndexNotBuiltError as exc:
        print(f"sherpa search: {exc}", file=sys.stderr)
        return 1
    try:
        packed = retriever.search(args.query, budget_tokens=args.budget_tokens)
        if not packed.results:
            print("sherpa search: no results.", file=sys.stderr)
            return 0
        for result in packed.results:
            chunk = result.chunk
            print(
                f"{result.score:6.3f}  {chunk.file_path}"
                f"[{chunk.byte_start}:{chunk.byte_end}]  ({result.source.value})"
            )
            print(f"        {chunk.breadcrumb}")
            if result.rationale:
                print(f"        {result.rationale}")
        print(
            f"-- {len(packed.results)} chunks, ~{packed.total_tokens} tokens "
            f"(budget {packed.budget_tokens})"
        )
    finally:
        store.close()
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    from codesherpa.gitlayer.repo import NotARepositoryError, open_repo, repo_root
    from codesherpa.gitlayer.sync import default_db_path
    from codesherpa.store.sqlite_store import SQLiteIndexStore

    try:
        root = repo_root(open_repo("."))
    except NotARepositoryError as exc:
        print(f"sherpa status: {exc}", file=sys.stderr)
        return 1
    db = default_db_path(root)
    if not db.exists():
        print("sherpa status: no index found — run `sherpa init` first.", file=sys.stderr)
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


def _cmd_gain(args: argparse.Namespace) -> int:
    from pathlib import Path

    from codesherpa import gain
    from codesherpa.gitlayer.repo import NotARepositoryError, open_repo, repo_root
    from codesherpa.gitlayer.sync import default_db_path
    from codesherpa.store.sqlite_store import SQLiteIndexStore

    try:
        root = repo_root(open_repo("."))
    except NotARepositoryError as exc:
        print(f"sherpa gain: {exc}", file=sys.stderr)
        return 1
    db = default_db_path(root)
    if not db.exists():
        print("sherpa gain: no index found — run `sherpa init` first.", file=sys.stderr)
        return 1

    since, label = gain.since_expression(args.since, args.days)
    store = SQLiteIndexStore(db)
    try:
        report = gain.usage_report(store.conn, since, label)
        if args.html:
            out = Path(args.out) if args.out else db.parent / "gain.html"
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(gain.render_html(report), encoding="utf-8")
            except OSError as exc:
                print(f"sherpa gain: cannot write {out}: {exc}", file=sys.stderr)
                return 1
            print(str(out))
        else:
            print(gain.render_terminal(report))
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
    if args.command == "search":
        return _cmd_search(args)

    if args.command == "serve":
        from codesherpa.mcp_server.__main__ import main as serve_main

        return serve_main([args.path])

    if args.command == "gain":
        return _cmd_gain(args)

    phase = _PHASE_OF[args.command]
    print(
        f"sherpa {args.command}: not implemented yet (arrives in Phase {phase}).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
