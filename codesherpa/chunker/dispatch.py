"""Chunker entry point: language detection + strategy dispatch.

Python/TypeScript/JavaScript/TSX go through the cAST (tree-sitter
split-then-merge) chunker; adding a language means adding one entry to
``chunker.languages.LANGUAGES``. Everything else — and any file that fails to
parse — uses the line-window fallback: the indexer never crashes on a weird
file.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from codesherpa.chunker.cast import chunk_ast
from codesherpa.chunker.fallback import chunk_lines
from codesherpa.contracts.types import Chunk

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
}


def detect_language(path: str) -> str:
    """Language id for a repo-relative path; ``text`` when unknown."""
    return LANGUAGE_BY_EXTENSION.get(PurePosixPath(path).suffix.lower(), "text")


def chunk_blob(
    blob_hash: str,
    data: bytes,
    file_path: str,
    language: str | None = None,
) -> list[Chunk]:
    """Chunk one blob deterministically: same blob -> same chunks, always."""
    lang = language if language is not None else detect_language(file_path)
    chunks = chunk_ast(blob_hash, data, file_path, lang)
    if chunks is not None:
        return chunks
    return chunk_lines(blob_hash, data, file_path, lang)
