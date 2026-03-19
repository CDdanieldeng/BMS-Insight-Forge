"""
Integration test for retriever pipeline: facet classification, chunking, and embedding.

Pipelines:
  1. facet.classify_document_facet(text) → {file_type, summary}
  2. chunking.chunk_text(text, facet) → chunks
  3. embedding.embed(chunk texts) → vectors

Mocks:
  - LLM call in facet (shared.llm_client.complete) to avoid API usage
  - Embedder to avoid loading sentence-transformers model
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

# Ensure backend is on path
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retriever import (
    DocumentFacet,
    chunk_text,
    classify_document_facet,
    embed,
)


# ---------------------------------------------------------------------------
# Mock text inputs by facet type
# ---------------------------------------------------------------------------

MOCK_TEXTS = {
    "transcript": """
问题Q1. 你的典型客户是谁？
答案：我们主要服务二线城市的中型医院。

问题Q2. 最大的挑战是什么？
答案：价格敏感度和竞品对比。

问题Q3. 你们的产品差异化优势？
答案：本地化服务和灵活的定制方案。
""",
    "swot": """Strengths
- Strong brand recognition
- Established distribution network
- Skilled workforce

Weaknesses
- Limited R&D budget
- High dependency on key clients

Opportunities
- Emerging markets expansion
- Digital transformation

Threats
- Intense competition
- Regulatory changes
""",
    "customer segmentation": """
## Customer Segments Overview

### Segment 1: Enterprise
High-value accounts with complex needs. Focus on tailored solutions.

### Segment 2: SMB
Mid-market with budget constraints. Self-serve and standard packages.

### Segment 3: Startup
Early-stage needs. Quick onboarding and flexible pricing.
""",
    "messaging strategy": """
## Messaging Framework

**Headline:** Innovate with confidence.

**Value propositions:**
- Reliability and uptime
- Cost efficiency
- Ease of integration

**Proof points:** Case studies, benchmarks, testimonials.
""",
    "others": """
This is a generic document with no specific structure.

It contains multiple paragraphs of text that will be chunked
using the default separator-based strategy.

Lorem ipsum dolor sit amet. More content here.
""",
}


def _mock_embed(texts: list[str], model=None) -> list[list[float]]:
    """Return deterministic fake vectors for testing (no sentence-transformers load)."""
    dim = 384
    return [[float(i + j) / 100.0 for j in range(dim)] for i in range(len(texts))]


def _print_pipeline_output(
    step_name: str,
    facet_result: dict | None = None,
    chunks: list[dict] | None = None,
    vectors: list[list[float]] | None = None,
) -> None:
    """Print output of each pipeline step for debugging/inspection."""
    print(f"\n{'='*60}")
    print(f"  {step_name}")
    print("=" * 60)
    if facet_result is not None:
        print("Step 1 - Facet classification:")
        print(f"  {facet_result}")
    if chunks is not None:
        print("\nStep 2 - Chunks:")
        for i, c in enumerate(chunks):
            text_preview = (c["text"][:80] + "...") if len(c["text"]) > 80 else c["text"]
            print(f"  [{i+1}] start={c['start']} end={c['end']} facet={c['facet']}")
            print(f"      text: {text_preview}")
    if vectors is not None:
        print("\nStep 3 - Embeddings:")
        print(f"  count={len(vectors)}, dim={len(vectors[0]) if vectors else 0}")
        for i, v in enumerate(vectors[:3]):  # show first 3 vectors
            preview = v[:5] if len(v) >= 5 else v
            print(f"  [{i+1}] sample: {preview}...")
        if len(vectors) > 3:
            print(f"  ... and {len(vectors) - 3} more")
    print()


class TestRetrieverPipeline(unittest.TestCase):
    """Test facet → chunk → embed pipeline with mocked LLM and embedder."""

    @patch("retriever.facet.complete")
    def test_pipeline_transcript(self, mock_complete: MagicMock) -> None:
        """Transcript: facet classify → chunk by Q&A → embed."""
        text = MOCK_TEXTS["transcript"]
        mock_complete.return_value = '{"file_type": "transcript", "summary": "Sales interview"}'

        # 1. Facet
        result = classify_document_facet(text)
        self.assertEqual(result["file_type"], "transcript")
        self.assertIn("summary", result)

        facet = DocumentFacet(result["file_type"])

        # 2. Chunk
        chunks = chunk_text(text, facet)
        self.assertGreater(len(chunks), 0)
        for c in chunks:
            self.assertIn("text", c)
            self.assertIn("start", c)
            self.assertIn("end", c)
            self.assertEqual(c["facet"], "transcript")

        # 3. Embed (mocked)
        chunk_texts = [c["text"] for c in chunks]
        with patch("retriever.embedding._default_embedder") as mock_emb:
            mock_emb.embed.side_effect = _mock_embed
            vectors = embed(chunk_texts)

        self.assertEqual(len(vectors), len(chunks))
        self.assertEqual(len(vectors[0]), 384)

        _print_pipeline_output(
            "test_pipeline_transcript",
            facet_result=result,
            chunks=chunks,
            vectors=vectors,
        )

    @patch("retriever.facet.complete")
    def test_pipeline_swot(self, mock_complete: MagicMock) -> None:
        """SWOT: facet → chunk by newline → embed."""
        text = MOCK_TEXTS["swot"]
        mock_complete.return_value = '{"file_type": "swot", "summary": "SWOT analysis"}'

        result = classify_document_facet(text)
        self.assertEqual(result["file_type"], "swot")

        facet = DocumentFacet(result["file_type"])
        chunks = chunk_text(text, facet)
        self.assertGreater(len(chunks), 0)

        chunk_texts = [c["text"] for c in chunks]
        with patch("retriever.embedding._default_embedder") as mock_emb:
            mock_emb.embed.side_effect = _mock_embed
            vectors = embed(chunk_texts)

        self.assertEqual(len(vectors), len(chunks))

        _print_pipeline_output(
            "test_pipeline_swot",
            facet_result=result,
            chunks=chunks,
            vectors=vectors,
        )

    @patch("retriever.facet.complete")
    def test_pipeline_customer_segmentation(self, mock_complete: MagicMock) -> None:
        """Customer segmentation facet → chunk → embed."""
        text = MOCK_TEXTS["customer segmentation"]
        mock_complete.return_value = (
            '{"file_type": "customer segmentation", "summary": "Customer segments"}'
        )

        result = classify_document_facet(text)
        self.assertEqual(result["file_type"], "customer segmentation")

        facet = DocumentFacet(result["file_type"])
        chunks = chunk_text(text, facet)
        self.assertGreater(len(chunks), 0)

        chunk_texts = [c["text"] for c in chunks]
        with patch("retriever.embedding._default_embedder") as mock_emb:
            mock_emb.embed.side_effect = _mock_embed
            vectors = embed(chunk_texts)

        self.assertEqual(len(vectors), len(chunks))

        _print_pipeline_output(
            "test_pipeline_customer_segmentation",
            facet_result=result,
            chunks=chunks,
            vectors=vectors,
        )

    @patch("retriever.facet.complete")
    def test_pipeline_others_fallback(self, mock_complete: MagicMock) -> None:
        """Others facet → default chunking → embed."""
        text = MOCK_TEXTS["others"]
        mock_complete.return_value = '{"file_type": "others", "summary": "Generic doc"}'

        result = classify_document_facet(text)
        self.assertEqual(result["file_type"], "others")

        facet = DocumentFacet(result["file_type"])
        chunks = chunk_text(text, facet)
        self.assertGreater(len(chunks), 0)

        chunk_texts = [c["text"] for c in chunks]
        with patch("retriever.embedding._default_embedder") as mock_emb:
            mock_emb.embed.side_effect = _mock_embed
            vectors = embed(chunk_texts)

        self.assertEqual(len(vectors), len(chunks))

        _print_pipeline_output(
            "test_pipeline_others_fallback",
            facet_result=result,
            chunks=chunks,
            vectors=vectors,
        )

    @patch("retriever.facet.complete")
    def test_full_pipeline_with_all_facets(self, mock_complete: MagicMock) -> None:
        """Run pipeline for each facet type with mocked text inputs."""
        facet_map = {
            "transcript": DocumentFacet.TRANSCRIPT,
            "swot": DocumentFacet.SWOT,
            "customer segmentation": DocumentFacet.CUSTOMER_SEGMENTATION,
            "messaging strategy": DocumentFacet.MESSAGING_STRATEGY,
            "others": DocumentFacet.OTHERS,
        }

        for facet_key, text in MOCK_TEXTS.items():
            mock_complete.return_value = (
                f'{{"file_type": "{facet_key}", "summary": "Test summary"}}'
            )
            result = classify_document_facet(text)
            self.assertEqual(result["file_type"], facet_key)

            facet = facet_map[facet_key]
            chunks = chunk_text(text, facet)
            self.assertGreater(len(chunks), 0, msg=f"No chunks for facet {facet_key}")

            chunk_texts = [c["text"] for c in chunks]
            with patch("retriever.embedding._default_embedder") as mock_emb:
                mock_emb.embed.side_effect = _mock_embed
                vectors = embed(chunk_texts)

            self.assertEqual(
                len(vectors),
                len(chunks),
                msg=f"Vector count mismatch for facet {facet_key}",
            )

            _print_pipeline_output(
                f"test_full_pipeline - {facet_key}",
                facet_result=result,
                chunks=chunks,
                vectors=vectors,
            )


if __name__ == "__main__":
    unittest.main()
