# Contributing to sherpa

Thanks for helping! A few project-specific rules keep this codebase honest.

## Setup

```bash
git clone <repo> && cd sherpa
python -m venv .venv && . .venv/bin/activate     # Python >= 3.11
pip install -e ".[dev]"
python -m pytest -q
```

The suite includes two eval gates that load real models (~750 MB downloaded
once to `~/.cache/sherpa/`) and takes ~8 minutes on a laptop CPU. CI runs
the same suite (`.github/workflows/ci.yml`).

## Non-negotiable rules (from CLAUDE.md §2)

1. **Tests are a ratchet.** Never delete, skip, weaken, or xfail an existing
   test to make progress. If a test seems wrong, fix the code; changing the
   test requires a reasoned entry in `DECISIONS.md`.
2. **`codesherpa/contracts/` is frozen.** The dataclasses and ABCs there are
   the interface every layer builds against.
3. **The Golden Test is sacred** (`tests/test_golden.py`): an incremental
   index must be byte-identical (in projection) to a from-scratch rebuild.
   Run it before every PR; run the deep soak (`GOLDEN_DEEP=1 pytest
   tests/test_golden.py`) for changes to gitlayer/store/graph.
4. **No mock data in production paths.** Mocks live in `tests/` only.
5. **Eval thresholds never go down** (`eval/run_eval.py`, CLAUDE.md §13).
   If your change moves retrieval quality, re-run
   `python eval/run_eval.py --repo <fixture> --mode all` and append numbers
   to `EVAL_LOG.md` (append-only).
6. **Record non-obvious choices in `DECISIONS.md`** — model swaps, threshold
   trade-offs, fallbacks taken, with before/after numbers.

## Adding a language

One tree-sitter grammar entry in `codesherpa/chunker/languages.py` (cAST
chunking) plus one query file under `codesherpa/graph/queries/` (symbols /
references / calls). Unparseable files already fall back to line windows —
the indexer must never crash on weird input.

## Sign-off required (DCO)

All commits in pull requests must include a `Signed-off-by` line — use
`git commit -s`. By signing off you certify the
[Developer Certificate of Origin 1.1](https://developercertificate.org/):
that you wrote the change or otherwise have the right to submit it under
the project's license. One sentence on why: DCO sign-off keeps the
provenance of every line clean and preserves the project's ability to make
future licensing decisions without chasing down untraceable contributions.

Maintainer commits made before this policy was introduced (2026-07-05)
predate the sign-off requirement; every one of them is authored by the
sole copyright holder.

## Licensing

Contributions are accepted under **Apache-2.0** with DCO sign-off — no CLA.
Contributors retain copyright to their contributions; you license them to
the project and its users under Apache-2.0 (including the Section 3 patent
grant). Be aware the project may offer commercial licensing or hosted
services in the future; the Apache-2.0 grant on your contribution is what
makes that possible without further paperwork.

## Style

Match the surrounding code. Type hints everywhere, docstrings explain *why*,
comments only for what the code cannot say. Conventional commits
(`feat:`, `fix:`, `test:`, `perf:`, `docs:`, `chore:`).
