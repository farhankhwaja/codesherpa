"""Print the Phase 3 INTERNAL eval table (symbol-aware relevance) for
EVAL_LOG.md. The official gate is ``eval/run_eval.py --mode all``.

Run:  .venv/bin/python tests/support/gate_report.py [embed_model] [reranker_model]
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tests.support.gatelib as gatelib  # noqa: E402


def main() -> None:
    if len(sys.argv) > 1:
        gatelib.EMBED_MODEL = sys.argv[1]
    if len(sys.argv) > 2:
        gatelib.RERANKER_MODEL = sys.argv[2]
    print(f"embed={gatelib.EMBED_MODEL}  reranker={gatelib.RERANKER_MODEL}")
    from tests.support.benchmark_models import ensure_fixture

    ensure_fixture()
    work = Path(tempfile.mkdtemp(prefix="rg-gate-"))
    harness = gatelib.GateHarness(ROOT / "tests" / "fixtures" / "miniproject", work)
    print(gatelib.format_table(harness.reports()))


if __name__ == "__main__":
    main()
