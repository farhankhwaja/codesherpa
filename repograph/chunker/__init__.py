"""repograph.chunker — structure-aware chunking (CLAUDE.md §7.2)."""

from repograph.chunker.dispatch import chunk_blob, detect_language

__all__ = ["chunk_blob", "detect_language"]
