"""
Retriever pipeline: document facet, chunking, embedding, recall, and rerank.

This module provides a semantic retrieval pipeline for Insight Forge:

1. **Document facet** — Classify documents into rough file types:
   ["transcript", "swot", "customer segmentation", "messaging strategy", "others"]
   to route each document to the appropriate chunking strategy.

2. **Chunking strategies** — Split documents into chunks by facet-specific
   configs (size, overlap, separator) for optimal retrieval.

3. **Embedding** — Convert text chunks to vectors for semantic search.

4. **Recall** — Retrieve candidate chunks from the vector store by similarity.

5. **Rerank** — Score and reorder candidates for relevance to the query.

Usage:
    from retriever import (
        DocumentFacet,
        classify_document_facet,
        get_chunking_strategy,
        chunk_text,
        embed,
        recall_by_query_text,
        rerank,
    )
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Facet
# ---------------------------------------------------------------------------
from .facet import (
    DocumentFacet,
    FACET_VALUES,
    FacetExtractionResult,
    classify_document_facet,
)

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
from .chunking import (
    BaseChunker,
    ChunkConfig,
    FACET_CHUNK_CONFIGS,
    chunk_text,
    get_chunker,
    get_chunking_strategy,
)

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------
from .embedding import (
    BaseEmbedder,
    Qwen3Embedding4BEmbedder,
    SentenceTransformerEmbedder,
    embed,
    embed_single,
    get_default_embedder,
)

# ---------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------
from .recall import (
    BaseRecaller,
    CosineSimilarityRecaller,
    get_default_recaller,
    recall,
    recall_by_query_text,
)

# ---------------------------------------------------------------------------
# Rerank
# ---------------------------------------------------------------------------
from .rerank import rerank

# ---------------------------------------------------------------------------
# Query rewrite
# ---------------------------------------------------------------------------
from .query_rewrite import (
    QWEN_TURBO,
    rewrite_for_retrieval,
    rewrite_segment_guidance,
)

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
from .orchestration import run_retrieval_pipeline

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
__all__ = [
    # Facet
    "DocumentFacet",
    "FACET_VALUES",
    "FacetExtractionResult",
    "classify_document_facet",
    # Chunking
    "BaseChunker",
    "ChunkConfig",
    "FACET_CHUNK_CONFIGS",
    "chunk_text",
    "get_chunker",
    "get_chunking_strategy",
    # Embedding
    "BaseEmbedder",
    "Qwen3Embedding4BEmbedder",
    "SentenceTransformerEmbedder",
    "embed",
    "embed_single",
    "get_default_embedder",
    # Recall
    "BaseRecaller",
    "CosineSimilarityRecaller",
    "get_default_recaller",
    "recall",
    "recall_by_query_text",
    # Rerank
    "rerank",
    # Query rewrite
    "QWEN_TURBO",
    "rewrite_for_retrieval",
    "rewrite_segment_guidance",
    # Orchestration
    "run_retrieval_pipeline",
]
