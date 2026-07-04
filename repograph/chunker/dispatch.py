"""Chunker entry point: language detection + strategy dispatch.

Phase 1 routes everything through the line-window fallback. Phase 2 adds the
cAST (tree-sitter split-then-merge) path for Python/TypeScript/JavaScript/TSX;
adding a language after that should mean adding a tree-sitter queries file,
nothing else. Any parse failure must fall back to line windows — the indexer
never crashes on a weird file.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from repograph.chunker.fallback import chunk_lines
from repograph.contracts.types import Chunk

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
    # Phase 2 will insert the cAST path here for the four parsed languages.
    return chunk_lines(blob_hash, data, file_path, lang)
