"""Phase 0 (+4): the gold query set is well-formed and grounded in the fixture.

Phase 4 adds two harder styles (additive eval-strengthening per §13):
``nl_hard`` — natural-language queries sharing no identifier tokens with the
target code (pure vocabulary mismatch); ``decoy`` — queries whose words
lexically match a WRONG file, so only semantic retrieval finds the target.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

GOLD_PATH = Path(__file__).parent.parent / "eval" / "gold_queries.jsonl"

REQUIRED_KEYS = {"id", "type", "query", "expected_files", "expected_symbols"}
VALID_TYPES = {"nl", "symbol", "stacktrace", "nl_hard", "decoy"}


def _entries() -> list[dict]:
    lines = GOLD_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_at_least_twenty_entries() -> None:
    assert len(_entries()) >= 35  # 25 (Phase 0) + 10 hardening (Phase 4)


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


def test_expected_symbols_are_definitions(miniproject: Path) -> None:
    """Each expected symbol must be a real definition (not a mere mention)
    in at least one expected file."""
    from repograph.graph.extract import SourceFile, extract_file
    from repograph.graph.languages import language_for_path

    for entry in _entries():
        defined: set[str] = set()
        for rel in entry["expected_files"]:
            language = language_for_path(rel)
            if language is None:
                continue
            data = (miniproject / rel).read_bytes()
            defined |= {
                n.symbol for n in extract_file(SourceFile(rel, "0" * 40, language, data))
            }
        for symbol in entry["expected_symbols"]:
            assert symbol in defined, (
                f"{entry['id']}: {symbol} is not defined in {entry['expected_files']}"
            )


_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QUERY_STOPWORDS = {"a", "an", "the", "of", "in", "on", "for", "we", "i", "is", "it"}


def _identifier_subtokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for identifier in _IDENTIFIER_RE.findall(text):
        for part in re.split(r"_+", identifier):
            for sub in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", part):
                tokens.add(sub.lower())
    return tokens


def test_nl_hard_queries_share_no_identifier_tokens_with_targets(miniproject: Path) -> None:
    """The vocabulary-mismatch property is a ratchet: if a target file ever
    gains an identifier that leaks into one of these queries, rewrite the
    query — never rely on the lexical match."""
    for entry in _entries():
        if entry["type"] != "nl_hard":
            continue
        words = {
            w.lower().strip("'") for w in re.findall(r"[A-Za-z']+", entry["query"])
        } - _QUERY_STOPWORDS
        for rel in entry["expected_files"]:
            code = (miniproject / rel).read_text(encoding="utf-8")
            overlap = words & _identifier_subtokens(code)
            assert not overlap, (
                f"{entry['id']}: query words {sorted(overlap)} appear as "
                f"identifier tokens in {rel}"
            )
