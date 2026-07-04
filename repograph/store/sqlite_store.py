"""SQLite implementation of the frozen ``IndexStore`` contract.

One database file (``.repograph/index.db``) holds blobs, file mappings,
chunks (+ FTS5), symbols, edges, the embedding cache, and metadata — all
keyed by git blob hash. See ``schema.sql`` for the table documentation.

Concurrency: cross-process write serialization is the sync lockfile's job
(``gitlayer.sync``); this class additionally runs WAL mode with a generous
busy timeout so overlapping readers/writers never corrupt the file.
"""

from __future__ import annotations

import re
import sqlite3
import struct
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Optional

from repograph.contracts.index_contract import IndexStore
from repograph.contracts.types import Chunk, Edge, EdgeKind, SymbolNode

SCHEMA_VERSION = "1"

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_SQLITE_MAX_VARS = 500  # stay well under SQLITE_MAX_VARIABLE_NUMBER

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _batched(items: list, size: int = _SQLITE_MAX_VARS):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _pack_vector(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack_vector(blob: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"<{dim}f", blob))


class SQLiteIndexStore(IndexStore):
    """The concrete store. Everything else depends on the ABC, not this."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._vec_enabled = self._try_load_sqlite_vec()
        self._apply_schema()

    # ------------------------------------------------------------- lifecycle

    def _try_load_sqlite_vec(self) -> bool:
        try:
            import sqlite_vec

            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            return True
        except Exception:
            # Brute-force vector_search fallback keeps behavior correct
            # (slower on big repos). See CLAUDE.md §9 fallback ladder.
            return False

    def _apply_schema(self) -> None:
        with self.conn:
            self.conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
            self.conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                (SCHEMA_VERSION,),
            )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "SQLiteIndexStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ blobs

    def add_blob(self, blob_hash: str, language: str, size_bytes: int) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO blobs(blob_hash, language, size_bytes, active)
                VALUES(?, ?, ?, 1)
                ON CONFLICT(blob_hash) DO UPDATE SET active = 1
                """,
                (blob_hash, language, size_bytes),
            )

    def has_blob(self, blob_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM blobs WHERE blob_hash = ?", (blob_hash,)
        ).fetchone()
        return row is not None

    def active_blobs(self) -> set[str]:
        rows = self.conn.execute("SELECT blob_hash FROM blobs WHERE active = 1")
        return {row[0] for row in rows}

    def set_blobs_active(self, blob_hashes: Iterable[str], active: bool) -> None:
        hashes = list(blob_hashes)
        with self.conn:
            for batch in _batched(hashes):
                placeholders = ",".join("?" * len(batch))
                self.conn.execute(
                    f"UPDATE blobs SET active = ? WHERE blob_hash IN ({placeholders})",
                    [1 if active else 0, *batch],
                )

    # ------------------------------------------------------------------ files

    def map_files(self, ref: str, path_to_blob: dict[str, str]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM files WHERE ref = ?", (ref,))
            self.conn.executemany(
                "INSERT INTO files(ref, path, blob_hash) VALUES(?, ?, ?)",
                [(ref, path, blob) for path, blob in path_to_blob.items()],
            )

    def files_for_ref(self, ref: str) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT path, blob_hash FROM files WHERE ref = ?", (ref,)
        )
        return {row[0]: row[1] for row in rows}

    # ----------------------------------------------------------------- chunks

    def add_chunks(self, chunks: Sequence[Chunk]) -> None:
        with self.conn:
            for chunk in chunks:
                cur = self.conn.execute(
                    """
                    INSERT OR IGNORE INTO chunks
                        (chunk_id, blob_hash, byte_start, byte_end,
                         file_path, language, code, breadcrumb)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.blob_hash,
                        chunk.byte_start,
                        chunk.byte_end,
                        chunk.file_path,
                        chunk.language,
                        chunk.code,
                        chunk.breadcrumb,
                    ),
                )
                if cur.rowcount:  # only brand-new chunks get an FTS row
                    self.conn.execute(
                        "INSERT INTO chunks_fts(chunk_id, breadcrumb, code) VALUES(?, ?, ?)",
                        (chunk.chunk_id, chunk.breadcrumb, chunk.code),
                    )

    def _row_to_chunk(self, row: sqlite3.Row) -> Chunk:
        return Chunk(
            blob_hash=row["blob_hash"],
            byte_start=row["byte_start"],
            byte_end=row["byte_end"],
            file_path=row["file_path"],
            language=row["language"],
            code=row["code"],
            breadcrumb=row["breadcrumb"],
        )

    def get_chunk(self, chunk_id: str) -> Optional[Chunk]:
        row = self.conn.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        return self._row_to_chunk(row) if row else None

    def chunks_for_blob(self, blob_hash: str) -> list[Chunk]:
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE blob_hash = ? ORDER BY byte_start, byte_end",
            (blob_hash,),
        )
        return [self._row_to_chunk(row) for row in rows]

    # ---------------------------------------------------------------- symbols

    def add_symbols(self, symbols: Sequence[SymbolNode]) -> None:
        with self.conn:
            self.conn.executemany(
                """
                INSERT OR IGNORE INTO symbols
                    (node_id, symbol, kind, blob_hash, byte_start, byte_end,
                     file_path, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s.node_id,
                        s.symbol,
                        s.kind.value,
                        s.blob_hash,
                        s.byte_start,
                        s.byte_end,
                        s.file_path,
                        s.signature,
                    )
                    for s in symbols
                ],
            )

    def add_edges(self, edges: Sequence[Edge]) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO edges(src, dst, kind) VALUES(?, ?, ?)",
                [(e.src, e.dst, e.kind.value) for e in edges],
            )

    def _row_to_symbol(self, row: sqlite3.Row) -> SymbolNode:
        from repograph.contracts.types import SymbolKind

        return SymbolNode(
            symbol=row["symbol"],
            kind=SymbolKind(row["kind"]),
            blob_hash=row["blob_hash"],
            byte_start=row["byte_start"],
            byte_end=row["byte_end"],
            file_path=row["file_path"],
            signature=row["signature"],
        )

    def get_definitions(self, symbol: str) -> list[SymbolNode]:
        rows = self.conn.execute(
            """
            SELECT s.* FROM symbols s
            JOIN blobs b ON b.blob_hash = s.blob_hash AND b.active = 1
            WHERE s.symbol = ?
            ORDER BY s.file_path, s.byte_start
            """,
            (symbol,),
        )
        return [self._row_to_symbol(row) for row in rows]

    def get_edges(
        self,
        node_id: str,
        kind: Optional[EdgeKind] = None,
        incoming: bool = False,
    ) -> list[Edge]:
        column = "dst" if incoming else "src"
        sql = f"SELECT src, dst, kind FROM edges WHERE {column} = ?"
        params: list = [node_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        sql += " ORDER BY src, dst, kind"
        rows = self.conn.execute(sql, params)
        return [Edge(src=r["src"], dst=r["dst"], kind=EdgeKind(r["kind"])) for r in rows]

    # ------------------------------------------------------------- embeddings

    def get_embedding(self, chunk_id: str) -> Optional[list[float]]:
        row = self.conn.execute(
            "SELECT dim, vector FROM embeddings WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            return None
        return _unpack_vector(row["vector"], row["dim"])

    def _ensure_vec_table(self, dim: int) -> bool:
        """Create the vec0 KNN table on first use; returns availability."""
        if not self._vec_enabled:
            return False
        stored = self.get_meta("vec_dim")
        if stored is None:
            with self.conn:
                self.conn.execute(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                        chunk_id TEXT PRIMARY KEY,
                        embedding float[{dim}] distance_metric=cosine
                    )
                    """
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('vec_dim', ?)",
                    (str(dim),),
                )
            return True
        if int(stored) != dim:
            raise ValueError(
                f"embedding dim {dim} != index dim {stored}; "
                "re-init the index to change embedding models"
            )
        return True

    def put_embedding(self, chunk_id: str, vector: Sequence[float], model: str) -> None:
        vector = list(vector)
        packed = _pack_vector(vector)
        use_vec = self._ensure_vec_table(len(vector))
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO embeddings(chunk_id, model, dim, vector)
                VALUES (?, ?, ?, ?)
                """,
                (chunk_id, model, len(vector), packed),
            )
            if use_vec:
                self.conn.execute(
                    "DELETE FROM vec_chunks WHERE chunk_id = ?", (chunk_id,)
                )
                self.conn.execute(
                    "INSERT INTO vec_chunks(chunk_id, embedding) VALUES(?, ?)",
                    (chunk_id, packed),
                )

    # ---------------------------------------------------------------- queries

    def _active_chunk_ids(self, chunk_ids: Iterable[str]) -> set[str]:
        ids = list(chunk_ids)
        active: set[str] = set()
        for batch in _batched(ids):
            placeholders = ",".join("?" * len(batch))
            rows = self.conn.execute(
                f"""
                SELECT c.chunk_id FROM chunks c
                JOIN blobs b ON b.blob_hash = c.blob_hash AND b.active = 1
                WHERE c.chunk_id IN ({placeholders})
                """,
                batch,
            )
            active.update(row[0] for row in rows)
        return active

    def fts_search(self, query: str, limit: int = 100) -> list[tuple[str, float]]:
        tokens = _TOKEN_RE.findall(query)
        if not tokens:
            return []
        # Quote every token: user queries must never hit FTS5 syntax errors.
        match = " OR ".join(f'"{t}"' for t in tokens)
        rows = self.conn.execute(
            """
            SELECT f.chunk_id, bm25(chunks_fts) AS rank
            FROM chunks_fts f
            JOIN chunks c ON c.chunk_id = f.chunk_id
            JOIN blobs b ON b.blob_hash = c.blob_hash AND b.active = 1
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, limit),
        )
        # bm25() is smaller-is-better; negate so higher is better.
        return [(row[0], -row[1]) for row in rows]

    def vector_search(self, vector: Sequence[float], limit: int = 100) -> list[tuple[str, float]]:
        vector = list(vector)
        if self._vec_enabled and self.get_meta("vec_dim") is not None:
            return self._vector_search_vec0(vector, limit)
        return self._vector_search_bruteforce(vector, limit)

    def _vector_search_vec0(self, vector: list[float], limit: int) -> list[tuple[str, float]]:
        # Over-fetch, then restrict to active blobs (vec0 KNN can't join).
        k = limit * 4
        rows = self.conn.execute(
            """
            SELECT chunk_id, distance FROM vec_chunks
            WHERE embedding MATCH ? AND k = ?
            ORDER BY distance
            """,
            (_pack_vector(vector), k),
        ).fetchall()
        active = self._active_chunk_ids(row[0] for row in rows)
        results = [
            (row[0], 1.0 - row[1])  # cosine distance -> similarity
            for row in rows
            if row[0] in active
        ]
        return results[:limit]

    def _vector_search_bruteforce(self, vector: list[float], limit: int) -> list[tuple[str, float]]:
        rows = self.conn.execute(
            """
            SELECT e.chunk_id, e.dim, e.vector FROM embeddings e
            JOIN chunks c ON c.chunk_id = e.chunk_id
            JOIN blobs b ON b.blob_hash = c.blob_hash AND b.active = 1
            """
        ).fetchall()
        scored = []
        for row in rows:
            other = _unpack_vector(row["vector"], row["dim"])
            if len(other) != len(vector):
                continue
            score = sum(a * b for a, b in zip(vector, other))
            scored.append((row["chunk_id"], score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:limit]

    def symbol_search(self, name: str, limit: int = 20) -> list[SymbolNode]:
        needle = name.lower()
        if not needle:
            return []
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.conn.execute(
            r"""
            SELECT s.* FROM symbols s
            JOIN blobs b ON b.blob_hash = s.blob_hash AND b.active = 1
            WHERE LOWER(s.symbol) LIKE '%' || ? || '%' ESCAPE '\'
            """,
            (escaped,),
        ).fetchall()

        def score(row: sqlite3.Row) -> tuple:
            sym = row["symbol"].lower()
            return (
                0 if sym == needle else 1 if sym.startswith(needle) else 2,
                len(sym),
                row["symbol"],
                row["file_path"],
            )

        return [self._row_to_symbol(row) for row in sorted(rows, key=score)[:limit]]

    # ------------------------------------------------------------------- meta

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                (key, value),
            )
