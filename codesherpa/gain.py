"""`sherpa gain` — local-only usage analytics with an honest-measurement design.

Two classes of numbers, never mixed (README "Measuring what sherpa saves"):

* **Facts** — counted directly from recorded tool calls: queries, latency,
  tokens actually served, expand rate.
* **Counterfactual estimate** — "context avoided" compares tokens served
  against the full-file token size of every distinct file the served chunks
  came from (the cheapest thing an agent without sherpa would have read).
  It is an estimate and every rendering MUST label it as such — the word
  "estimated" appears adjacent to the number in all outputs, terminal and
  HTML. Token sizes use the repo-wide len/4 heuristic
  (:func:`codesherpa.graph.textutil.estimate_tokens` applied to blob byte
  size) — no tokenizer dependency, documented in the README.

PRIVACY INVARIANTS (test-pinned in tests/test_gain.py):

* never store raw query text — only ``sha256(query)``;
* never store code or file contents;
* never store file PATHS — only a distinct-path count and their summed
  full-file token estimate. Paths of a proprietary repo are sensitive.

The ``usage`` table is observational, not index state: it is excluded from
golden projections (a rebuilt index has no history of who queried it) and
never synced anywhere. Recording is best-effort: a failure logs a warning
and NEVER fails the query (enforced at the MCP dispatch wrapper).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

logger = logging.getLogger(__name__)

#: tools whose responses answer from the symbol graph
_GRAPH_TOOLS = {"get_definition", "get_callers", "get_references"}

#: chars-per-token heuristic shared with graph.textutil.estimate_tokens
_CHARS_PER_TOKEN = 4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def query_hash(text: str) -> str:
    """sha256 hex of the primary query argument — the ONLY trace of it kept."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _primary_text(kwargs: dict) -> str:
    for key in ("query", "symbol", "since", "expand_id"):
        value = kwargs.get(key)
        if isinstance(value, str):
            return value
    return ""


def _blob_token_sizes(conn: sqlite3.Connection, blob_hashes: list[str]) -> int:
    """Sum of full-file token estimates (size_bytes/4) for ``blob_hashes``."""
    total = 0
    for start in range(0, len(blob_hashes), 500):
        batch = blob_hashes[start : start + 500]
        marks = ",".join("?" * len(batch))
        rows = conn.execute(
            f"SELECT size_bytes FROM blobs WHERE blob_hash IN ({marks})", batch
        ).fetchall()
        total += sum(row[0] for row in rows)
    return total // _CHARS_PER_TOKEN


def record_call(
    store,
    retriever,
    tool: str,
    kwargs: dict,
    response_text: str,
    latency_ms: float,
) -> None:
    """Insert one ``usage`` row for a completed MCP tool call.

    Called from the single dispatch wrapper in mcp_server.server — never from
    individual tools. May raise; the wrapper is responsible for catching.
    """
    from codesherpa.graph.textutil import estimate_tokens

    payload = json.loads(response_text)

    # results + the distinct files they span (paths are looked up, counted,
    # summed — and immediately discarded; only aggregates are stored)
    results = payload.get("results")
    if isinstance(results, list):
        results_count = len(results)
        paths = {r["path"] for r in results if isinstance(r, dict) and "path" in r}
    elif tool == "expand" and "path" in payload:
        results_count = 1
        paths = {payload["path"]}
    elif tool == "get_recent_changes":
        # commits are history, not served file context — no file accounting
        results_count = len(payload.get("commits") or [])
        paths = set()
    else:
        results_count = 0
        paths = set()

    files_spanned_tokens = 0
    if paths:
        head_files = store.files_for_ref("HEAD")
        blob_hashes = [head_files[p] for p in paths if p in head_files]
        files_spanned_tokens = _blob_token_sizes(store.conn, blob_hashes)

    if tool == "search_code":
        path_taken = getattr(retriever, "last_search_path", None)
    elif tool in _GRAPH_TOOLS:
        path_taken = "graph"
    else:
        path_taken = None  # expand / index_status / recent_changes: n/a

    store.conn.execute(
        "INSERT INTO usage (ts, tool, query_hash, path_taken, tokens_returned,"
        " budget_tokens, latency_ms, results_count, files_count,"
        " files_spanned_tokens, expanded) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            _utc_now_iso(),
            tool,
            query_hash(_primary_text(kwargs)),
            path_taken,
            estimate_tokens(response_text),
            kwargs.get("budget_tokens"),
            round(latency_ms, 3),
            results_count,
            len(paths),
            files_spanned_tokens,
            1 if tool == "expand" else 0,
        ),
    )
    store.conn.commit()


# --------------------------------------------------------------- reporting


@dataclass
class GainReport:
    """Aggregates over the usage table for one time window."""

    since_label: str
    total: int = 0
    by_tool: dict = field(default_factory=dict)
    by_path: dict = field(default_factory=dict)
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    tokens_served: int = 0
    budget_offered: int = 0
    searches: int = 0
    expands: int = 0
    files_spanned_tokens: int = 0
    daily: list = field(default_factory=list)  # [(date, count)] ascending

    @property
    def estimated_avoided(self) -> int:
        return max(0, self.files_spanned_tokens - self.tokens_served)

    @property
    def expand_rate(self) -> float:
        return self.expands / self.searches if self.searches else 0.0


def since_expression(since: Optional[str], days: Optional[int]) -> tuple[Optional[str], str]:
    """(ISO cutoff or None, human label) from --since/--days."""
    if since:
        return f"{since}T00:00:00Z" if len(since) == 10 else since, f"since {since}"
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"), f"last {days} days"
    return None, "all time"


def usage_report(conn: sqlite3.Connection, since: Optional[str], label: str) -> GainReport:
    where, params = ("WHERE ts >= ?", (since,)) if since else ("", ())
    rows = conn.execute(
        f"SELECT tool, path_taken, tokens_returned, budget_tokens, latency_ms,"
        f" expanded, files_spanned_tokens, ts FROM usage {where} ORDER BY ts",
        params,
    ).fetchall()

    report = GainReport(since_label=label, total=len(rows))
    if not rows:
        return report

    latencies = sorted(float(r[4]) for r in rows)
    report.avg_latency_ms = sum(latencies) / len(latencies)
    report.p95_latency_ms = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]

    daily: dict[str, int] = {}
    for tool, path_taken, tokens, budget, _lat, expanded, spanned, ts in rows:
        report.by_tool[tool] = report.by_tool.get(tool, 0) + 1
        bucket = path_taken or "n/a"
        report.by_path[bucket] = report.by_path.get(bucket, 0) + 1
        report.tokens_served += tokens
        report.budget_offered += budget or 0
        report.files_spanned_tokens += spanned
        if tool == "search_code":
            report.searches += 1
        if expanded:
            report.expands += 1
        day = ts[:10]
        daily[day] = daily.get(day, 0) + 1
    report.daily = sorted(daily.items())
    return report


def render_terminal(report: GainReport) -> str:
    """Plain-text report. The counterfactual line carries the word
    "estimated" adjacent to the number — a hard product rule."""
    if report.total == 0:
        return (
            "sherpa gain: no usage recorded yet.\n"
            "Connect the MCP server and run a few queries first:\n"
            "  claude mcp add sherpa -- python -m codesherpa.mcp_server \"$PWD\"\n"
            "then come back — every tool call is measured locally."
        )
    tools = " · ".join(f"{t} {n}" for t, n in sorted(report.by_tool.items(), key=lambda kv: -kv[1]))
    paths = " · ".join(f"{p} {n}" for p, n in sorted(report.by_path.items(), key=lambda kv: -kv[1]))
    used_pct = (
        f" ({100 * report.tokens_served / report.budget_offered:.0f}% of offered budgets)"
        if report.budget_offered
        else ""
    )
    lines = [
        f"sherpa gain — local usage analytics ({report.since_label})",
        "",
        f"  queries:         {report.total}  ({tools})",
        f"  paths:           {paths}",
        f"  latency:         avg {report.avg_latency_ms:.0f} ms · p95 {report.p95_latency_ms:.0f} ms",
        f"  tokens served:   {report.tokens_served:,}{used_pct}",
        f"  expand rate:     {report.expands} expands / {report.searches} searches"
        f" ({100 * report.expand_rate:.0f}%)",
        "",
        f"  context served:            {report.tokens_served:,} tokens",
        f"  full-file equivalent:      {report.files_spanned_tokens:,} tokens",
        f"  estimated context avoided: {report.estimated_avoided:,} tokens"
        " (estimate — see README methodology)",
        "",
        "  All numbers are local-only; disable with analytics=False.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------- HTML


_PALETTE = ["#7aa2f7", "#9ece6a", "#e0af68", "#f7768e", "#bb9af7", "#7dcfff"]


def _svg_bars(daily: list) -> str:
    """Hand-rolled daily-queries bar chart (static SVG, no libraries)."""
    if not daily:
        return "<p class='muted'>no data</p>"
    width, height, pad = 640, 160, 4
    bar = max(6, min(48, (width - 40) // len(daily) - pad))
    peak = max(n for _, n in daily)
    parts = [
        f"<svg viewBox='0 0 {width} {height + 30}' role='img' aria-label='queries per day'>"
    ]
    for i, (day, n) in enumerate(daily):
        h = max(2, round(n / peak * height))
        x = 20 + i * (bar + pad)
        parts.append(
            f"<rect x='{x}' y='{height - h}' width='{bar}' height='{h}'"
            f" fill='#7aa2f7' rx='2'><title>{escape(day)}: {n}</title></rect>"
        )
        if len(daily) <= 14 or i % max(1, len(daily) // 10) == 0:
            parts.append(
                f"<text x='{x + bar / 2}' y='{height + 16}' font-size='9'"
                f" fill='#787c99' text-anchor='middle'>{escape(day[5:])}</text>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _svg_donut(by_path: dict) -> str:
    """Path-split donut via stroke-dasharray arcs (static SVG)."""
    total = sum(by_path.values())
    if not total:
        return "<p class='muted'>no data</p>"
    r, c = 60, 2 * 3.14159265 * 60
    offset, arcs, legend = 0.0, [], []
    for i, (name, n) in enumerate(sorted(by_path.items(), key=lambda kv: -kv[1])):
        frac = n / total
        color = _PALETTE[i % len(_PALETTE)]
        arcs.append(
            f"<circle r='{r}' cx='80' cy='80' fill='none' stroke='{color}'"
            f" stroke-width='26' stroke-dasharray='{frac * c:.2f} {c:.2f}'"
            f" stroke-dashoffset='{-offset * c:.2f}'"
            f"><title>{escape(name)}: {n}</title></circle>"
        )
        legend.append(
            f"<span class='key'><i style='background:{color}'></i>"
            f"{escape(name)} · {n}</span>"
        )
        offset += frac
    return (
        "<div class='donut'><svg viewBox='0 0 160 160' role='img'"
        " aria-label='path split'><g transform='rotate(-90 80 80)'>"
        + "".join(arcs)
        + f"</g><text x='80' y='86' text-anchor='middle' font-size='22'"
        f" fill='#c0caf5'>{total}</text></svg>"
        f"<div class='legend'>{''.join(legend)}</div></div>"
    )


def render_html(report: GainReport, generated: Optional[str] = None) -> str:
    """Self-contained single-file dark-theme report. Inline CSS + static SVG
    only — no JS dependencies, no CDN, no network requests of any kind."""
    generated = generated or _utc_now_iso()
    tool_rows = "".join(
        f"<tr><td>{escape(t)}</td><td>{n}</td></tr>"
        for t, n in sorted(report.by_tool.items(), key=lambda kv: -kv[1])
    ) or "<tr><td colspan='2' class='muted'>no calls yet</td></tr>"
    cards = f"""
    <div class='cards'>
      <div class='card'><h2>{report.total}</h2><p>queries</p></div>
      <div class='card'><h2>{report.tokens_served:,}</h2><p>context served (tokens)</p></div>
      <div class='card'><h2>{report.estimated_avoided:,}</h2>
        <p><b>estimated</b> context avoided (tokens)</p></div>
      <div class='card'><h2>{report.p95_latency_ms:.0f} ms</h2><p>p95 latency</p></div>
    </div>"""
    return f"""<!DOCTYPE html>
<!-- sherpa gain report — generated locally; this file makes no network requests -->
<html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>sherpa gain</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; padding:32px; background:#1a1b26; color:#c0caf5;
         font:15px/1.5 -apple-system, 'Segoe UI', Roboto, sans-serif; }}
  header h1 {{ margin:0; font-size:26px; }} header .sub {{ color:#787c99; }}
  .cards {{ display:flex; gap:16px; flex-wrap:wrap; margin:28px 0; }}
  .card {{ background:#24283b; border-radius:10px; padding:18px 22px; min-width:150px; }}
  .card h2 {{ margin:0; font-size:26px; color:#7aa2f7; }}
  .card p {{ margin:6px 0 0; color:#a9b1d6; font-size:13px; }}
  section {{ background:#24283b; border-radius:10px; padding:20px; margin:18px 0; }}
  h3 {{ margin:0 0 12px; font-size:15px; color:#a9b1d6; }}
  table {{ border-collapse:collapse; width:100%; }}
  td {{ padding:6px 10px; border-top:1px solid #32364a; }}
  .muted {{ color:#787c99; }}
  .donut {{ display:flex; align-items:center; gap:24px; }}
  .donut svg {{ width:170px; height:170px; }}
  .legend .key {{ display:block; margin:4px 0; font-size:13px; }}
  .legend i {{ display:inline-block; width:10px; height:10px; border-radius:2px;
               margin-right:8px; }}
  footer {{ color:#787c99; font-size:12px; margin-top:26px; }}
</style></head><body>
<header><h1>🏔 sherpa gain</h1>
<p class='sub'>{escape(report.since_label)} · generated {escape(generated)} · local-only analytics</p></header>
{cards}
<section><h3>Queries per day</h3>{_svg_bars(report.daily)}</section>
<section><h3>Retrieval path split</h3>{_svg_donut(report.by_path)}</section>
<section><h3>Calls per tool</h3><table>{tool_rows}</table></section>
<section><h3>Honest measurement</h3>
<p>“Context served” counts tokens sherpa actually returned. “<b>Estimated</b>
context avoided” is a counterfactual: the full-file token size of every
distinct file the served chunks came from, minus what was served — an
estimate of what an agent without sherpa would have read instead. It is an
estimate, not a measurement; see the README methodology section.</p></section>
<footer>sherpa · analytics are local-only (no telemetry) · disable with
analytics=False</footer>
</body></html>
"""
