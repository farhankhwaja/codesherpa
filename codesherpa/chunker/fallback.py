"""Line-window fallback chunker (CLAUDE.md §7.2, last resort path).

Used for unparseable/unknown files so weird content never crashes the
indexer: fixed windows of 120 lines with 20 lines of overlap. Deterministic:
same bytes always produce the same chunk set.
"""

from __future__ import annotations

from codesherpa.contracts.types import Chunk

WINDOW_LINES = 120
OVERLAP_LINES = 20
_STEP = WINDOW_LINES - OVERLAP_LINES

_COMMENT_MARKER = {
    "python": "#",
    "text": "#",
    "javascript": "//",
    "typescript": "//",
    "tsx": "//",
}


def breadcrumb_marker(language: str) -> str:
    return _COMMENT_MARKER.get(language, "#")


def _line_offsets(data: bytes) -> list[int]:
    """Byte offset of each line start (a final newline opens no new line)."""
    offsets = [0]
    pos = data.find(b"\n")
    while pos != -1:
        if pos + 1 < len(data):
            offsets.append(pos + 1)
        pos = data.find(b"\n", pos + 1)
    return offsets


def chunk_lines(blob_hash: str, data: bytes, file_path: str, language: str) -> list[Chunk]:
    """Split ``data`` into overlapping line windows."""
    if not data:
        return []
    offsets = _line_offsets(data)
    n_lines = len(offsets)
    marker = breadcrumb_marker(language)

    chunks: list[Chunk] = []
    start_line = 0
    while start_line < n_lines:
        end_line = min(start_line + WINDOW_LINES, n_lines)  # exclusive
        byte_start = offsets[start_line]
        byte_end = offsets[end_line] if end_line < n_lines else len(data)
        chunks.append(
            Chunk(
                blob_hash=blob_hash,
                byte_start=byte_start,
                byte_end=byte_end,
                file_path=file_path,
                language=language,
                code=data[byte_start:byte_end].decode("utf-8", errors="replace"),
                breadcrumb=f"{marker} {file_path} :: L{start_line + 1}-{end_line}",
            )
        )
        if end_line == n_lines:
            break
        start_line += _STEP
    return chunks
