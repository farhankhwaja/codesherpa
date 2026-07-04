#!/usr/bin/env python3
"""A/B token-benchmark runner (eval/ab_harness.md, executed in Phase 5).

Runs each task from a task file through headless Claude Code (`claude -p`)
in one of two arms:

  A (control):   normal tools only (Read/Grep/Glob; no sherpa)
  B (treatment): same + the sherpa MCP server attached via --mcp-config

The agent sees ONLY the task text — ground-truth HTML comments are stripped
here, before the prompt is built (amendment 2b). One fresh session per task
per arm; identical prompt, model, and settings across arms.

Outputs, per task: <out>/<task_id>-<arm>.stream.jsonl (full tool trace) and
one line in <out>/summary-<arm>.jsonl with token usage + tool counts.
Grading solved/unsolved happens afterwards, against the ground-truth
comments, by a grader who never edits these outputs.

Usage:
  python eval/external/ab_runner.py --repo <path> --tasks eval/ab_tasks_sizly.md \
      --arm B --out verification/ab/sizly --serve-python <venv-python> [--only D1 F2]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

PROMPT_TEMPLATE = """You are investigating the repository in the current working directory (read-only task — do not modify files).

{task}

Answer with:
1. The file path(s) and specific function(s)/symbol(s) responsible (or that must change).
2. A short explanation of the mechanism / the fix or change plan.
Be precise about paths and symbol names; if the change spans multiple places, name all of them."""

_SECTION_RE = re.compile(r"^### (\S+)", re.M)


def parse_tasks(md_path: Path) -> dict[str, str]:
    """{task_id: task_text} with ground-truth comments stripped."""
    text = md_path.read_text(encoding="utf-8")
    tasks: dict[str, str] = {}
    sections = list(_SECTION_RE.finditer(text))
    for i, match in enumerate(sections):
        end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        body = text[match.end() : end]
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)  # NEVER ship ground truth
        body = re.sub(r"^---\s*$", "", body, flags=re.M)
        body = re.sub(r"^## .*$", "", body, flags=re.M)  # trailing section headers
        tasks[match.group(1)] = body.strip()
    return tasks


def run_task(
    task_id: str,
    prompt: str,
    repo: Path,
    arm: str,
    out_dir: Path,
    model: str,
    max_turns: int,
    mcp_config: Path | None,
) -> dict:
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--max-turns",
        str(max_turns),
    ]
    if arm == "B":
        assert mcp_config is not None
        # headless MCP tools need an explicit allow; this only grants the
        # sherpa server's tools — arm A has no analogous restriction lifted
        cmd += [
            "--mcp-config", str(mcp_config), "--strict-mcp-config",
            "--allowedTools", "mcp__sherpa",
        ]

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=1200
        )
        stdout, stderr, returncode = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        # a hung/slow session is DATA (recorded as unsolved), never a crash
        stdout = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = "TIMEOUT after 1200s"
        returncode = -1
    wall = time.perf_counter() - started

    stream_path = out_dir / f"{task_id}-{arm}.stream.jsonl"
    stream_path.write_text(stdout, encoding="utf-8")
    proc_stdout, proc_stderr = stdout, stderr

    tool_calls = 0
    file_reads = 0
    mcp_calls = 0
    fallback_after_mcp = False
    saw_mcp = False
    usage: dict = {}
    result_text = ""
    for line in proc_stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    tool_calls += 1
                    if name.startswith("mcp__sherpa__"):
                        mcp_calls += 1
                        saw_mcp = True
                    elif name == "Read":
                        file_reads += 1
                        if saw_mcp:
                            fallback_after_mcp = True
                    elif name in ("Grep", "Glob") and saw_mcp:
                        fallback_after_mcp = True
        elif event.get("type") == "result":
            usage = event.get("usage", {}) or {}
            result_text = event.get("result", "") or ""
            usage["total_cost_usd"] = event.get("total_cost_usd")
            usage["num_turns"] = event.get("num_turns")

    tokens_total = (
        usage.get("input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("output_tokens", 0)
    )
    row = {
        "task": task_id,
        "arm": arm,
        "exit": returncode,
        "wall_s": round(wall, 1),
        "tokens_total": tokens_total,
        "input_tokens": usage.get("input_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cost_usd": usage.get("total_cost_usd"),
        "num_turns": usage.get("num_turns"),
        "tool_calls": tool_calls,
        "file_reads": file_reads,
        "mcp_calls": mcp_calls,
        "fallback_after_mcp": fallback_after_mcp,
        "answer": result_text,
    }
    if returncode != 0:
        row["stderr_tail"] = proc_stderr[-500:]
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--arm", required=True, choices=["A", "B"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--serve-python", default=sys.executable,
                        help="Python used to launch the sherpa MCP server (arm B).")
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = parse_tasks(Path(args.tasks))
    if args.only:
        tasks = {k: v for k, v in tasks.items() if k in set(args.only)}

    mcp_config = None
    if args.arm == "B":
        mcp_config = out_dir / "mcp-config.json"
        mcp_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "sherpa": {
                            "command": args.serve_python,
                            "args": ["-m", "codesherpa.mcp_server", str(repo)],
                        }
                    }
                }
            )
        )

    summary_path = out_dir / f"summary-{args.arm}.jsonl"
    with summary_path.open("a", encoding="utf-8") as summary:
        for task_id, task_text in tasks.items():
            prompt = PROMPT_TEMPLATE.format(task=task_text)
            print(f"[{args.arm}] {task_id} …", flush=True)
            row = run_task(
                task_id, prompt, repo, args.arm, out_dir,
                args.model, args.max_turns, mcp_config,
            )
            summary.write(json.dumps(row) + "\n")
            summary.flush()
            print(
                f"[{args.arm}] {task_id}: exit={row['exit']} tokens={row['tokens_total']} "
                f"tools={row['tool_calls']} reads={row['file_reads']} mcp={row['mcp_calls']} "
                f"({row['wall_s']}s)",
                flush=True,
            )
    print(f"wrote {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
