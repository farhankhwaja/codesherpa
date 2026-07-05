"""`sherpa gain` — usage recording, privacy invariants, reporting, HTML.

The privacy tests are the product contract: queries may contain proprietary
code and paths, so the usage table must never contain raw query text, code,
or file paths — only hashes, counts, and token sums. Every column of a
populated row is inspected.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import anyio
import pytest

from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from codesherpa import gain
from codesherpa.mcp_server import create_server
from codesherpa.retrieve.config import RetrievalConfig
from codesherpa.retrieve.retriever import HybridRetriever
from codesherpa.store.sqlite_store import SQLiteIndexStore
from codesherpa.embed.engine import EmbeddingEngine

# Distinctive markers: if ANY of these ever shows up in the usage table,
# privacy is broken. They flow through a real query below.
SECRET_QUERY = "SECRET_zebraTango99 where is the proprietary billing retry logic"
SECRET_SYMBOL = "retry_request"


def _retriever_over(db_path: Path, analytics: bool = True):
    store = SQLiteIndexStore(db_path)
    config = RetrievalConfig()
    config.rerank_enabled = False
    config.analytics = analytics
    engine = EmbeddingEngine(store, "stub", encoder=lambda texts: [[1.0, 0.0]] * len(texts))
    return HybridRetriever(store, engine, config=config), store


def _call_tools(server, calls: list[tuple[str, dict]]):
    """Drive tools over the SDK's in-memory session; return list of texts."""

    async def run():
        out = []
        async with create_connected_server_and_client_session(
            server._mcp_server
        ) as session:
            for tool, arguments in calls:
                result = await session.call_tool(tool, arguments)
                assert not result.isError, result.content
                out.append(result.content[0].text)
        return out

    return anyio.run(run)


@pytest.fixture()
def gain_env(synced_miniproject, tmp_path):
    """Private COPY of the synced fixture DB (usage writes mutate it)."""
    import shutil

    repo, db = synced_miniproject
    my_db = tmp_path / "gain.db"
    shutil.copy(db, my_db)
    retriever, store = _retriever_over(my_db)
    server = create_server(retriever, repo, store=store)
    yield repo, store, retriever, server
    store.close()


def _usage_rows(store):
    return store.conn.execute("SELECT * FROM usage ORDER BY id").fetchall()


# ------------------------------------------------------------- recording


def test_every_tool_call_records_one_row(gain_env):
    repo, store, _retriever, server = gain_env
    _call_tools(
        server,
        [
            ("search_code", {"query": SECRET_QUERY, "budget_tokens": 900}),
            ("get_definition", {"symbol": SECRET_SYMBOL}),
            ("get_callers", {"symbol": SECRET_SYMBOL}),
            ("get_references", {"symbol": SECRET_SYMBOL, "limit": 5}),
            ("get_recent_changes", {"since": "HEAD~2"}),
            ("index_status", {}),
        ],
    )
    rows = _usage_rows(store)
    assert [r["tool"] for r in rows] == [
        "search_code",
        "get_definition",
        "get_callers",
        "get_references",
        "get_recent_changes",
        "index_status",
    ]
    search_row = rows[0]
    assert search_row["budget_tokens"] == 900
    assert search_row["tokens_returned"] > 0
    assert search_row["latency_ms"] >= 0
    assert search_row["results_count"] > 0
    assert search_row["files_count"] > 0
    # full-file equivalent must be at least what a whole file costs
    assert search_row["files_spanned_tokens"] > 0
    assert search_row["path_taken"] in ("router", "dense")
    graph_row = rows[1]
    assert graph_row["path_taken"] == "graph"
    assert rows[5]["path_taken"] is None  # index_status: n/a


def test_expand_records_expanded_flag(gain_env):
    repo, store, _retriever, server = gain_env
    (search_text,) = _call_tools(
        server, [("search_code", {"query": SECRET_SYMBOL, "budget_tokens": 1200})]
    )
    expand_id = json.loads(search_text)["results"][0]["expand_id"]
    _call_tools(server, [("expand", {"expand_id": expand_id})])
    rows = _usage_rows(store)
    expand_row = rows[-1]
    assert expand_row["tool"] == "expand"
    assert expand_row["expanded"] == 1
    assert expand_row["files_count"] == 1
    assert all(r["expanded"] == 0 for r in rows[:-1])


def test_router_vs_dense_path_taken(gain_env):
    repo, store, _retriever, server = gain_env
    _call_tools(
        server,
        [
            ("search_code", {"query": SECRET_SYMBOL}),  # exact symbol → router
            ("search_code", {"query": "how are tasks stored on disk"}),  # NL → dense
        ],
    )
    rows = _usage_rows(store)
    assert rows[0]["path_taken"] == "router"
    assert rows[1]["path_taken"] == "dense"


# --------------------------------------------------------------- privacy


def test_privacy_no_query_text_paths_or_code_in_any_column(gain_env):
    """Inspect EVERY column of every populated row for leaked content."""
    repo, store, _retriever, server = gain_env
    _call_tools(
        server,
        [
            ("search_code", {"query": SECRET_QUERY, "budget_tokens": 800}),
            ("get_definition", {"symbol": SECRET_SYMBOL}),
        ],
    )
    rows = _usage_rows(store)
    assert rows, "no usage rows recorded"

    # every real indexed path is forbidden in the table
    head_paths = set(store.files_for_ref("HEAD"))
    assert head_paths, "fixture has no HEAD files"
    forbidden = {SECRET_QUERY, "SECRET_zebraTango99", SECRET_SYMBOL} | head_paths

    for row in rows:
        for key in row.keys():
            value = str(row[key])
            for needle in forbidden:
                assert needle not in value, (
                    f"privacy leak: {needle!r} found in usage.{key} = {value!r}"
                )

    # the hash is exactly sha256(query) — nothing fancier, nothing reversible
    assert rows[0]["query_hash"] == hashlib.sha256(SECRET_QUERY.encode()).hexdigest()
    assert rows[1]["query_hash"] == hashlib.sha256(SECRET_SYMBOL.encode()).hexdigest()


def test_analytics_flag_off_records_nothing(synced_miniproject, tmp_path):
    import shutil

    repo, db = synced_miniproject
    my_db = tmp_path / "off.db"
    shutil.copy(db, my_db)
    retriever, store = _retriever_over(my_db, analytics=False)
    server = create_server(retriever, repo, store=store)
    try:
        _call_tools(server, [("search_code", {"query": SECRET_SYMBOL})])
        assert _usage_rows(store) == []
    finally:
        store.close()


def test_recording_failure_never_fails_the_query(gain_env, monkeypatch, caplog):
    repo, store, _retriever, server = gain_env

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(gain, "record_call", boom)
    import logging

    with caplog.at_level(logging.WARNING):
        (text,) = _call_tools(server, [("search_code", {"query": SECRET_SYMBOL})])
    assert json.loads(text)["results"], "query itself must succeed"
    assert any("usage recording failed" in r.message for r in caplog.records)
    assert _usage_rows(store) == []


# ---------------------------------------------------------------- golden


def test_usage_rows_do_not_perturb_golden_projections(synced_miniproject, tmp_path):
    """usage is observational — golden projections must not see it."""
    import shutil

    from test_golden import golden_state

    _repo, db = synced_miniproject
    my_db = tmp_path / "golden-usage.db"
    shutil.copy(db, my_db)

    before = golden_state(my_db)
    store = SQLiteIndexStore(my_db)
    store.conn.execute(
        "INSERT INTO usage (ts, tool, query_hash, tokens_returned, latency_ms,"
        " results_count) VALUES ('2026-07-05T00:00:00Z','search_code','h',10,1.0,1)"
    )
    store.conn.commit()
    store.close()
    after = golden_state(my_db)
    assert before == after


# -------------------------------------------------------------- reporting


def _populated_report(store) -> gain.GainReport:
    return gain.usage_report(store.conn, None, "all time")


def test_terminal_report_facts_and_labeled_estimate(gain_env):
    repo, store, _retriever, server = gain_env
    (search_text,) = _call_tools(
        server, [("search_code", {"query": SECRET_SYMBOL, "budget_tokens": 1200})]
    )
    expand_id = json.loads(search_text)["results"][0]["expand_id"]
    _call_tools(server, [("expand", {"expand_id": expand_id})])

    text = gain.render_terminal(_populated_report(store))
    assert "sherpa gain" in text
    assert re.search(r"queries:\s+2", text)
    assert "router" in text or "dense" in text
    assert "1 expands / 1 searches" in text
    # the hard rule: "estimated" adjacent to the avoided number
    m = re.search(
        r"estimated context avoided: [\d,]+ tokens \(estimate — see README methodology\)",
        text,
    )
    assert m, text


def test_zero_usage_is_friendly_not_an_error():
    report = gain.GainReport(since_label="all time")
    text = gain.render_terminal(report)
    assert "no usage recorded yet" in text
    assert "claude mcp add" in text


def test_since_and_days_filters(gain_env):
    repo, store, _retriever, server = gain_env
    _call_tools(server, [("search_code", {"query": SECRET_SYMBOL})])
    # a synthetic old row that every time filter must exclude
    store.conn.execute(
        "INSERT INTO usage (ts, tool, query_hash, tokens_returned, latency_ms,"
        " results_count) VALUES ('2001-01-01T00:00:00Z','search_code','old',5,1.0,0)"
    )
    store.conn.commit()

    all_time = gain.usage_report(store.conn, *gain.since_expression(None, None))
    assert all_time.total == 2

    since, label = gain.since_expression("2025-01-01", None)
    assert since == "2025-01-01T00:00:00Z" and label == "since 2025-01-01"
    recent = gain.usage_report(store.conn, since, label)
    assert recent.total == 1

    since_d, label_d = gain.since_expression(None, 7)
    assert label_d == "last 7 days"
    last_week = gain.usage_report(store.conn, since_d, label_d)
    assert last_week.total == 1


# ------------------------------------------------------------------ HTML


def test_html_report_self_contained_and_labeled(gain_env, tmp_path):
    repo, store, _retriever, server = gain_env
    _call_tools(
        server,
        [
            ("search_code", {"query": SECRET_SYMBOL}),
            ("search_code", {"query": "where is retry logic for http"}),
        ],
    )
    html = gain.render_html(_populated_report(store), generated="2026-07-05T00:00:00Z")

    # single self-contained file: no network URLs outside comments
    stripped = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert "http://" not in stripped and "https://" not in stripped
    assert "<script src" not in html and "@import" not in html and "url(" not in html

    assert "sherpa gain" in html
    assert "2026-07-05" in html  # generation date
    assert "<svg" in html  # hand-rolled charts
    # the estimated label sits on the avoided card AND in the methodology text
    assert html.count("stimated") >= 2
    assert "context avoided" in html
    # privacy: no query text or repo paths in the report either
    for needle in [SECRET_SYMBOL] + list(store.files_for_ref("HEAD")):
        assert needle not in html


def test_cli_gain_end_to_end(gain_env, tmp_path, monkeypatch, capsys):
    """`sherpa gain` + `--html --out` against a real populated index."""
    repo, store, _retriever, server = gain_env
    _call_tools(server, [("search_code", {"query": SECRET_SYMBOL})])
    store.conn.commit()

    from codesherpa.cli import main

    # point the CLI at the fixture repo whose .sherpa/index.db is our copy
    # (sqlite backup API: a plain file copy would miss WAL-resident rows)
    import sqlite3

    sherpa_dir = Path(repo) / ".sherpa"
    sherpa_dir.mkdir(exist_ok=True)
    dest = sqlite3.connect(sherpa_dir / "index.db")
    store.conn.backup(dest)
    dest.close()
    monkeypatch.chdir(repo)

    assert main(["gain"]) == 0
    out = capsys.readouterr().out
    assert "estimated context avoided:" in out

    html_out = tmp_path / "report.html"
    assert main(["gain", "--html", "--out", str(html_out)]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == str(html_out)
    assert html_out.is_file()
    assert "sherpa gain" in html_out.read_text()


def test_cli_gain_html_unwritable_out_is_friendly(gain_env, tmp_path, monkeypatch, capsys):
    """Verifier finding 1: unwritable --out must print a one-line error,
    not a raw traceback."""
    import os
    import sqlite3

    repo, store, _retriever, server = gain_env
    _call_tools(server, [("search_code", {"query": SECRET_SYMBOL})])

    sherpa_dir = Path(repo) / ".sherpa"
    sherpa_dir.mkdir(exist_ok=True)
    dest = sqlite3.connect(sherpa_dir / "index.db")
    store.conn.backup(dest)
    dest.close()
    monkeypatch.chdir(repo)

    locked = tmp_path / "locked"
    locked.mkdir()
    os.chmod(locked, 0o555)
    try:
        from codesherpa.cli import main

        rc = main(["gain", "--html", "--out", str(locked / "gain.html")])
        assert rc == 1
        err = capsys.readouterr().err
        assert "sherpa gain: cannot write" in err
    finally:
        os.chmod(locked, 0o755)
