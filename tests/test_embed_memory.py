"""D38-revised: embedding memory must be bounded in TOKENS, not characters.

Instrumented reproduction (ship2 index, 2026-07-04): a single batch of 32
char-capped (8192) dense-JSON texts tokenized to up to 3,093 tokens each and
one encoder forward pass took RSS from 1.6 GB to 10.1 GB — attention memory
is batch x heads x seq^2, and a character cap admits pathological token
counts (dense JSON ~2.6 chars/token vs ~4 for code). The engine must clamp
the model's max sequence length to ENCODER_MAX_TOKENS.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

from codesherpa.embed.engine import (
    ENCODER_MAX_CHARS,
    ENCODER_MAX_TOKENS,
    EmbeddingEngine,
)
from codesherpa.embed.engine import model_is_cached, default_cache_dir
from codesherpa.store.sqlite_store import SQLiteIndexStore


def test_engine_clamps_model_max_seq_length(tmp_path, monkeypatch):
    """The real-encoder load path must set max_seq_length <= ENCODER_MAX_TOKENS
    (nomic ships 8192; 32 x 8192-token attention is tens of GB on CPU)."""

    class FakeModel:
        def __init__(self, *a, **k):
            self.max_seq_length = 8192  # what nomic-embed ships

        def encode(self, texts, **kwargs):
            class _A(list):
                def tolist(self):
                    return list(self)
            return _A([[1.0, 0.0] for _ in texts])

    fake_st = types.SimpleNamespace(SentenceTransformer=FakeModel)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)

    store = SQLiteIndexStore(tmp_path / "m.db")
    try:
        engine = EmbeddingEngine(store, "any/model")
        engine.embed_query("hello")  # forces _load_encoder
        model = engine._model_for_tests
        assert model is not None
        assert model.max_seq_length <= ENCODER_MAX_TOKENS
    finally:
        store.close()


@pytest.mark.skipif(
    not model_is_cached(default_cache_dir(), "nomic-ai/nomic-embed-text-v1.5"),
    reason="nomic model not cached; the eval gates download it first",
)
def test_dense_json_batch_embeds_with_bounded_rss(tmp_path):
    """End-to-end memory bound with the REAL default model, in a fresh
    subprocess so ru_maxrss is meaningful: 16 char-capped dense-JSON texts
    measured ~8+ GB before the token clamp; must stay well under 6 GB."""
    program = f"""
import json, resource, sys
from codesherpa.embed.engine import EmbeddingEngine, ENCODER_MAX_CHARS
from codesherpa.store.sqlite_store import SQLiteIndexStore
from codesherpa.contracts.types import Chunk

store = SQLiteIndexStore({json.dumps(str(tmp_path / "rss.db"))})
chunks = []
row = json.dumps({{"k": ["tok", 1.5, True] * 220}})  # dense JSON, ~2.6 chars/token
for i in range(16):
    code = (row * 40)[: ENCODER_MAX_CHARS + 100]
    chunks.append(Chunk(blob_hash=f"{{i:040x}}", byte_start=0, byte_end=len(code),
                        file_path=f"t{{i}}.jsonl", language="text", code=code,
                        breadcrumb=f"t{{i}}.jsonl :: L1-1"))
    store.add_blob(chunks[-1].blob_hash, "text", len(code))
    store.add_chunks([chunks[-1]])
engine = EmbeddingEngine(store, "nomic-ai/nomic-embed-text-v1.5",
                         trust_remote_code=True, batch_size=16)
engine.embed_chunks(chunks)
print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=600,
        cwd="/",
    )
    assert result.returncode == 0, result.stderr[-2000:]
    peak_bytes = int(result.stdout.strip().splitlines()[-1])
    peak_gb = peak_bytes / 1e9
    assert peak_gb < 6.0, f"embedding peak RSS {peak_gb:.2f} GB — token cap regressed"
