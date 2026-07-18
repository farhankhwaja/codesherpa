# Verification Report — branch `fix/partial-ast-salvage` (partial-AST salvage, D47/D47a)

Verdict: **PASS**
Date / commit verified: 2026-07-18 / 38b8b2b (fe02e07 + 38b8b2b atop 5c7fe3d main)

Verifier: adversarial QA agent (CLAUDE.md §11), fresh clone + fresh uv venv
(Python 3.12), `uv pip install -e ".[dev]"`, venv bin on PATH for all runs.

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 1 | Fresh clone + venv installs | PASS | install completed cleanly |
| 2 | Full suite (claim: 366 passed) | PASS | `PATH=.venv/bin:$PATH .venv/bin/python -m pytest -q` → 366 dots, 100%, exit 0, zero F/E/skip/xfail markers |
| 3 | Golden Test | PASS | `pytest tests/test_golden.py -q` → `. [100%]`, exit 0 |
| 4 | Deep Golden Test | PASS | `GOLDEN_DEEP=1 pytest tests/test_golden.py -q` → `. [100%]`, exit 0 |
| 5 | Eval gate (claim 0.974/0.869) | PASS | exit 0; verbatim: `hybrid 0.974 0.869 p95 411.0` / `bm25 0.744 0.611` / `vector 0.795 0.714` / `GATE: PASS`; secondary table `hybrid+rerank 0.97/0.869 p95 210`; hybrid strictly beats bm25-only and vector-only on recall@5; thresholds untouched |
| 6 | p95 latency (flake protocol) | PASS, no re-run needed | `[latency] warm p95 = 210.5 ms; budget = 500 ms`; router `0.2 ms; budget 200 ms` — comfortably inside, observed directly |
| 7 | New salvage tests | PASS | `pytest tests/test_chunker_salvage.py -q` → 15 passed |
| 8 | Salvage claims by direct experiment | PASS | see below |
| 9 | Standing attack (D38-final): `sherpa init` on clean clone under `/usr/bin/time -l` | PASS | peak RSS 4,081,401,856 B ≈ **3.80 GiB < 6 GB**; embedding **871/871 (100%)**; 229.98 s real; exit 0; all four hooks installed; 0 `(syntax errors)` chunks on this repo's own clean files |

## Cheating hunt

1. `git diff origin/main...HEAD --name-only` → exactly 4 files:
   DECISIONS.md, PROGRESS.md, `codesherpa/chunker/cast.py`,
   `tests/test_chunker_salvage.py`.
2. `codesherpa/contracts/` diff vs main: **empty**. Contracts frozen.
3. `eval/` diff vs main: **empty**. No threshold edits.
4. Tests diff vs main: only `A tests/test_chunker_salvage.py`; zero
   `-def test_` lines; no skip/xfail anywhere in the new file. No test
   existing on main was touched.
5. **Deleted-test audit:** `test_root_level_error_still_falls_back_wholesale`
   was added in fe02e07 and deleted in 38b8b2b. Verified NOT on main
   (`git ls-tree origin/main -- tests/test_chunker_salvage.py` is empty —
   the whole file is new to this branch). DECISIONS.md D47a records the
   deletion honestly: superseded by an explicit owner decision reversing
   the conservative rule, not weakened to pass a failing build.
   `test_unterminated_declaration_at_eof_salvages_the_rest` re-pins the
   deleted test's exact input (`func ((( broken`) asserting the inverse
   decided behavior plus byte-exactness and determinism. Net suite
   351 → 366. Ratchet intact.
6. Mock/fixture grep of the `codesherpa/` diff
   (`mock|monkeypatch|fixtures|miniproject`) → no matches.
7. Both commits authored by Farhan Khwaja, no co-author trailers.

None found.

## Direct experiments (chunk_ast, Go grammar, in-venv)

- **Case A — clean funcs + nested `new(<expr>)` error:** salvaged 3/4
  declarations; clean funcs in real cAST chunks, tainted region
  line-windowed with `(syntax errors)` breadcrumbs; strict byte-exact
  partition (0→EOF, no gap/overlap, rejoins to original); deterministic.
- **Case B — root-level ERROR (stray `}` between clean funcs), the
  38b8b2b behavior:** salvaged 3/4; `func Before` and `func After` both
  survive; byte-exact.
- **Case C — hopeless file (1 clean, 8 tainted, >50%):** `chunk_ast` →
  `None` (wholesale), dispatcher still chunks without crashing.
- **Control:** the same Case-A file *without* the error yields the
  byte-identical merged-chunk breadcrumb shape, confirming salvage
  matches the pre-existing clean-path merge convention (see finding 1).

## Exploratory attacks

- Only-errors-after-`package` file: no crash; `None` from cAST
  (no-clean-declaration guard); dispatcher covers all bytes.
- 20,375-byte single broken function: no crash; salvaged 4/5; byte-exact;
  every tainted window ≤ `MAX_CHUNK_BYTES` (D38 cap holds inside salvage).
- Empty `.go` file: no crash; `[]`.
- Dispatcher-level (`codesherpa.chunker.dispatch.chunk_blob`) on all
  inputs: no crashes, full byte coverage.
- Standing attack: as in criterion 9 — 3.80 GiB peak, 100% embedded.

## Findings

1. *(Informational, no action required)* In salvaged small files, a clean
   declaration that greedily merges with the preceding `package` clause
   carries the merged head's breadcrumb (`:: package main`) rather than
   its own signature. A control run on the identical error-free file
   behaves byte-identically — this is main's pre-existing merge
   convention, not introduced by this branch; the `GO_MIXED_BIG` test
   correctly pins per-declaration breadcrumbs where merge cannot occur.
2. *(Pre-existing open risk, correctly attributed elsewhere)*
   D47a/PROGRESS.md record the §13 p95 exceedance on real repos (grafana
   614 ms) and the under-load fixture flake (502.5 ms). In this
   verification the gate passed comfortably (210.5 ms). The branch's
   ruling-out argument is sound and corroborated: the fixture has no
   broken files and this repo's own index contains 0 salvaged chunks, so
   this branch's chunk sets are identical to main's on both.

No FAIL-level findings. A fresh session could merge this branch per §3.3
(via the required PR flow) without hesitation.
