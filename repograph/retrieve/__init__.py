"""repograph.retrieve — hybrid retrieval pipeline (Phase 3, CLAUDE.md §7.5).

Public surface for the MCP server (Phase 4), the CLI, and the eval harness:

    from repograph.retrieve import HybridRetriever, RetrievalConfig
    # eval/run_eval.py default factory (DECISIONS D17):
    from repograph.retrieve import build_eval_retriever
"""

from repograph.retrieve.config import RetrievalConfig
from repograph.retrieve.evalfactory import build_eval_retriever, build_retriever
from repograph.retrieve.fusion import rrf_fuse
from repograph.retrieve.pack import pack_results
from repograph.retrieve.rerank import CrossEncoderReranker
from repograph.retrieve.retriever import HybridRetriever

__all__ = [
    "CrossEncoderReranker",
    "HybridRetriever",
    "RetrievalConfig",
    "build_eval_retriever",
    "build_retriever",
    "pack_results",
    "rrf_fuse",
]
