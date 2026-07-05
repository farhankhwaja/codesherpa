"""Line-window fallback chunker (CLAUDE.md §7.2, last resort path).

Used for unparseable/unknown files so weird content never crashes the
indexer: fixed windows of 120 lines with 20 lines of overlap. Deterministic:
same bytes always produce the same chunk set.

Windows are additionally HARD-CAPPED in bytes: a single-line file (large
JSONL rows, minified data) previously produced one chunk per window with no
size bound — a 287 KB single-line chunk reached the embedder, and a
length-sorted batch of such chunks exploded attention memory to >14 GB RSS
(Phase 6 hardening finding, DECISIONS.md D38). Oversized windows are split
into contiguous byte slices of at most ``MAX_CHUNK_BYTES``.
"""

from __future__ import annotations

from codesherpa.contracts.types import Chunk

WINDOW_LINES = 120
OVERLAP_LINES = 20
_STEP = WINDOW_LINES - OVERLAP_LINES

MAX_CHUNK_BYTES = 16384
"""No fallback chunk may exceed this many bytes, whatever the line layout."""

_COMMENT_MARKER = {
    "python": "#",
    "text": "#",
    "javascript": "//",
    "typescript": "//",
    "tsx": "//",
    "go": "//",
    "proto": "//",
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
        # hard byte cap: slice oversized windows (e.g. one enormous line)
        # into contiguous pieces — the embedder must never see a mega-chunk
        for piece_start in range(byte_start, byte_end, MAX_CHUNK_BYTES):
            piece_end = min(piece_start + MAX_CHUNK_BYTES, byte_end)
            crumb = f"{marker} {file_path} :: L{start_line + 1}-{end_line}"
            if byte_end - byte_start > MAX_CHUNK_BYTES:
                crumb += f" :: bytes {piece_start}-{piece_end}"
            chunks.append(
                Chunk(
                    blob_hash=blob_hash,
                    byte_start=piece_start,
                    byte_end=piece_end,
                    file_path=file_path,
                    language=language,
                    code=data[piece_start:piece_end].decode("utf-8", errors="replace"),
                    breadcrumb=crumb,
                )
            )
        if end_line == n_lines:
            break
        start_line += _STEP
    return chunks
