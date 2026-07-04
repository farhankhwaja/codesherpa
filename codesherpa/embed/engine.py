"""Embedding engine with a permanent per-chunk cache (CLAUDE.md §7.4).

Embeds ``breadcrumb + "\\n" + code`` per chunk, batched (>= 32) and
L2-normalized. The cache is keyed by chunk identity
(``blob_hash:byte_start:byte_end``) and lives in the IndexStore, so an
embedding is computed at most once per unique chunk ever.

``sentence-transformers`` is imported lazily; tests inject a stub encoder.
Model downloads are cached under ~/.cache/sherpa/models (CLAUDE.md §6).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Optional

from codesherpa.contracts.index_contract import IndexStore
from codesherpa.contracts.types import Chunk


def default_cache_dir() -> Path:
    """Model cache location (CLAUDE.md §6: cache under ~/.cache/sherpa/).

    Lives here (not in retrieve.config) so embed/ never imports retrieve/ —
    retrieve depends on embed, and the reverse edge would be circular.
    """
    return Path.home() / ".cache" / "sherpa" / "models"


def model_is_cached(cache_dir: Path, model_name: str) -> bool:
    """True when ``model_name`` has a snapshot in the huggingface-style cache.

    Used to pass ``local_files_only=True`` on every load after the first
    download: a warm start must never touch the network (Phase 5 §3f).
    """
    snapshots = cache_dir / f"models--{model_name.replace('/', '--')}" / "snapshots"
    try:
        return snapshots.is_dir() and any(snapshots.iterdir())
    except OSError:
        return False

# Per-model input decoration. nomic-embed-text-v1.5 requires task prefixes;
# jina-embeddings-v2-base-code and MiniLM take raw text.
_MODEL_PREFIXES: dict[str, tuple[str, str]] = {
    # model name -> (document prefix, query prefix)
    "nomic-ai/nomic-embed-text-v1.5": ("search_document: ", "search_query: "),
}

Encoder = Callable[[list[str]], list[list[float]]]
"""Batch text -> vectors. Injected in tests; real one wraps SentenceTransformer."""

ENCODER_MAX_CHARS = 8192
"""Pre-truncation cap on characters per text (keeps tokenization cheap).

NOT the memory bound — dense JSON tokenizes at ~2.6 chars/token, so 8192
chars can still be >3k tokens (D38-revised). The real bound is
:data:`ENCODER_MAX_TOKENS`."""

ENCODER_MAX_TOKENS = 1024
"""Hard clamp on the model's max sequence length (D38-revised).

Attention memory is batch x heads x seq^2: an instrumented run measured ONE
batch of 32 char-capped dense-JSON texts (3,093 tokens each) taking RSS from
1.6 GB to 10.1 GB; the same batch clamped to 1024 tokens completes in 6.7 s
at 4.0 GB total. Typical cAST code chunks are ~450 BPE tokens, far below the
clamp, so their vectors are unchanged; only pathological data-file chunks
are tail-truncated."""


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return list(vector)
    return [v / norm for v in vector]


class EmbeddingEngine:
    """Cache-first chunk/query embedder over an :class:`IndexStore`."""

    def __init__(
        self,
        store: IndexStore,
        model_name: str,
        *,
        batch_size: int = 32,
        cache_dir: Optional[Path] = None,
        encoder: Optional[Encoder] = None,
        trust_remote_code: bool = False,
    ) -> None:
        if batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got {batch_size}")
        self._store = store
        self.model_name = model_name
        self.batch_size = batch_size
        self._cache_dir = cache_dir or default_cache_dir()
        self._encoder = encoder
        self._trust_remote_code = trust_remote_code
        self._model_for_tests = None
        """The loaded SentenceTransformer, exposed so tests can assert the
        max_seq_length clamp (D38-revised); None with an injected encoder."""
        self.computed_count = 0
        """Number of embeddings actually computed (cache misses) this session."""

    # ------------------------------------------------------------------ model

    def has_local_encoder(self) -> bool:
        """True when embedding can proceed without any network access."""
        return self._encoder is not None or model_is_cached(
            self._cache_dir, self.model_name
        )

    def _load_encoder(self) -> Encoder:
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer  # lazy

            model = SentenceTransformer(
                self.model_name,
                cache_folder=str(self._cache_dir),
                trust_remote_code=self._trust_remote_code,
                device="cpu",
                # after the first download the load is fully offline — a warm
                # start must not stall on hub HTTP checks (Phase 5 §3f)
                local_files_only=model_is_cached(self._cache_dir, self.model_name),
            )
            # memory bound (D38-revised): attention is batch x heads x seq^2,
            # and a char cap alone admits >3k-token dense-JSON texts
            try:
                current = int(model.max_seq_length or ENCODER_MAX_TOKENS)
            except (TypeError, ValueError):
                current = ENCODER_MAX_TOKENS
            model.max_seq_length = min(current, ENCODER_MAX_TOKENS)
            self._model_for_tests = model

            def encode(texts: list[str]) -> list[list[float]]:
                return model.encode(
                    texts,
                    batch_size=self.batch_size,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                ).tolist()

            self._encoder = encode
        return self._encoder

    def _prefixes(self) -> tuple[str, str]:
        return _MODEL_PREFIXES.get(self.model_name, ("", ""))

    @staticmethod
    def chunk_text(chunk: Chunk) -> str:
        """The exact text embedded for a chunk: breadcrumb + newline + code,
        head-truncated to :data:`ENCODER_MAX_CHARS` (memory bound, D38)."""
        return f"{chunk.breadcrumb}\n{chunk.code}"[:ENCODER_MAX_CHARS]

    # ------------------------------------------------------------------ embed

    def embed_chunks(self, chunks: Sequence[Chunk]) -> dict[str, list[float]]:
        """Embeddings for ``chunks``, computing only cache misses.

        Returns ``{chunk_id: normalized_vector}`` for every input chunk.
        """
        out: dict[str, list[float]] = {}
        misses: list[Chunk] = []
        seen_miss_ids: set[str] = set()
        for chunk in chunks:
            cached = self._store.get_embedding(chunk.chunk_id)
            if cached is not None:
                out[chunk.chunk_id] = cached
            elif chunk.chunk_id not in seen_miss_ids:
                seen_miss_ids.add(chunk.chunk_id)
                misses.append(chunk)

        if not misses:
            return out

        encode = self._load_encoder()
        doc_prefix, _ = self._prefixes()
        for batch_start in range(0, len(misses), self.batch_size):
            batch = misses[batch_start : batch_start + self.batch_size]
            texts = [doc_prefix + self.chunk_text(c) for c in batch]
            vectors = encode(texts)
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"encoder returned {len(vectors)} vectors for {len(batch)} texts"
                )
            for chunk, vector in zip(batch, vectors):
                normalized = _normalize(vector)
                self._store.put_embedding(chunk.chunk_id, normalized, self.model_name)
                out[chunk.chunk_id] = normalized
                self.computed_count += 1
        return out

    def embed_query(self, query: str) -> list[float]:
        """Normalized embedding for a search query (never cached)."""
        encode = self._load_encoder()
        _, query_prefix = self._prefixes()
        vectors = encode([(query_prefix + query)[:ENCODER_MAX_CHARS]])
        return _normalize(vectors[0])
