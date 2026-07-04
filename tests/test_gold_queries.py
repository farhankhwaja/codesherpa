"""Phase 0: the gold query set is well-formed and grounded in the fixture."""

from __future__ import annotations

import json
from pathlib import Path

GOLD_PATH = Path(__file__).parent.parent / "eval" / "gold_queries.jsonl"

REQUIRED_KEYS = {"id", "type", "query", "expected_files", "expected_symbols"}
VALID_TYPES = {"nl", "symbol", "stacktrace"}


def _entries() -> list[dict]:
    lines = GOLD_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_at_least_twenty_entries() -> None:
    assert len(_entries()) >= 20


def test_schema_and_unique_ids() -> None:
    entries = _entries()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate query ids"
    for entry in entries:
        assert REQUIRED_KEYS <= set(entry), entry
        assert entry["type"] in VALID_TYPES, entry
        assert isinstance(entry["query"], str) and entry["query"].strip()
        assert entry["expected_files"] and isinstance(entry["expected_files"], list)
        assert entry["expected_symbols"] and isinstance(entry["expected_symbols"], list)


def test_query_type_mix() -> None:
    types = {e["type"] for e in _entries()}
    assert types == VALID_TYPES, f"gold set must mix all query styles, got {types}"


def test_expected_files_exist_in_fixture(miniproject: Path) -> None:
    for entry in _entries():
        for rel in entry["expected_files"]:
            assert (miniproject / rel).is_file(), f"{entry['id']}: missing {rel}"


def test_expected_symbols_appear_in_expected_files(miniproject: Path) -> None:
    for entry in _entries():
        blob = "".join(
            (miniproject / rel).read_text(encoding="utf-8") for rel in entry["expected_files"]
        )
        for symbol in entry["expected_symbols"]:
            assert symbol in blob, f"{entry['id']}: symbol {symbol} not found"
