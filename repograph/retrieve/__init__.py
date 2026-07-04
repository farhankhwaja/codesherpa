"""repograph.retrieve — hybrid retrieval pipeline (Phase 3, CLAUDE.md §7.5).

Public surface for the MCP server (Phase 4) and CLI:

    from repograph.retrieve import HybridRetriever, RetrievalConfig
"""

from repograph.retrieve.config import RetrievalConfig
from repograph.retrieve.fusion import rrf_fuse
from repograph.retrieve.pack import pack_results
from repograph.retrieve.rerank import CrossEncoderReranker
from repograph.retrieve.retriever import HybridRetriever

__all__ = [
    "CrossEncoderReranker",
    "HybridRetriever",
    "RetrievalConfig",
    "pack_results",
    "rrf_fuse",
]
