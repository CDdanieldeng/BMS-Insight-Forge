"""
Integration test for retriever pipeline: facet, chunking, embedding, recall, and rerank.

Pipelines:
  1. facet.classify_document_facet(text) → {file_type, summary}
  2. chunking.chunk_text(text, facet) → chunks
  3. embedding.embed(chunk texts) → vectors
  4. recall.recall(query_embedding, ...) → candidate chunks
  5. rerank.rerank(query, candidates, top_k) → reordered chunks

Mocks:
  - LLM call in facet (shared.llm_client.complete) to avoid API usage
  - Embedder to avoid loading sentence-transformers model
  - DashScope API in rerank to avoid external calls
"""

from __future__ import annotations

import os
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
    recall,
    rerank,
)
from retriever.recall import CosineSimilarityRecaller, get_default_recaller


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


# ---------------------------------------------------------------------------
# Recall tests
# ---------------------------------------------------------------------------

class TestRecall(unittest.TestCase):
    """Test recall: index chunks + embeddings, retrieve by query similarity."""

    def test_recall_top_k_by_cosine_similarity(self) -> None:
        """CosineSimilarityRecaller returns top-k chunks by similarity score."""
        # Synthetic vectors: [1,0,0..] and [0.9,0.1,0..] are similar; [0,1,0..] is not.
        dim = 384
        chunks = [
            {"text": "chunk A (battery)", "file_id": "f1", "facet": "technical"},
            {"text": "chunk B (weather)", "file_id": "f2", "facet": "news"},
            {"text": "chunk C (EV battery)", "file_id": "f1", "facet": "technical"},
        ]
        embeddings = [
            [1.0] + [0.0] * (dim - 1),
            [0.0, 1.0] + [0.0] * (dim - 2),
            [0.9] + [0.1] + [0.0] * (dim - 2),
        ]
        query_vec = [1.0] + [0.0] * (dim - 1)

        recaller = CosineSimilarityRecaller()
        recaller.index(chunks, embeddings)

        results = recaller.recall(query_vec, top_k=2)
        self.assertEqual(len(results), 2)
        self.assertTrue(all("score" in r for r in results))
        self.assertGreaterEqual(results[0]["score"], results[1]["score"])
        self.assertGreater(results[0]["score"], 0.5)
        # Chunk A and C should be retrieved (both similar to query)
        texts = [r["text"] for r in results]
        self.assertIn("chunk A (battery)", texts)
        self.assertIn("chunk C (EV battery)", texts)

    def test_recall_filter_by_file_ids(self) -> None:
        """Recall respects file_ids filter."""
        dim = 384
        chunks = [
            {"text": "chunk A", "file_id": "f1"},
            {"text": "chunk B", "file_id": "f2"},
            {"text": "chunk C", "file_id": "f1"},
        ]
        embeddings = _mock_embed([c["text"] for c in chunks])

        recaller = CosineSimilarityRecaller()
        recaller.index(chunks, embeddings)
        query_vec = embeddings[0]  # same as chunk A

        results = recaller.recall(query_vec, file_ids=["f1"], top_k=5)
        self.assertTrue(all(r.get("file_id") == "f1" for r in results))
        self.assertEqual(len(results), 2)  # only f1 chunks

    def test_recall_filter_by_facet(self) -> None:
        """Recall respects facet filter."""
        dim = 384
        chunks = [
            {"text": "technical chunk", "file_id": "f1", "facet": "technical"},
            {"text": "news chunk", "file_id": "f2", "facet": "news"},
            {"text": "another technical", "file_id": "f1", "facet": "technical"},
        ]
        embeddings = _mock_embed([c["text"] for c in chunks])

        recaller = CosineSimilarityRecaller()
        recaller.index(chunks, embeddings)
        query_vec = embeddings[0]

        results = recaller.recall(query_vec, facet="technical", top_k=5)
        self.assertTrue(all(r.get("facet") == "technical" for r in results))
        self.assertEqual(len(results), 2)

    def test_recall_via_module_with_mocked_embedder(self) -> None:
        """recall() and recall_by_query_text via default recaller (needs index)."""
        from retriever.recall import recall_by_query_text

        chunks = [
            {"text": "Battery management for EVs", "file_id": "f1", "facet": "technical"},
            {"text": "Weather report", "file_id": "f2", "facet": "news"},
        ]
        embeddings = _mock_embed([c["text"] for c in chunks])

        recaller = get_default_recaller()
        recaller.clear()
        recaller.index(chunks, embeddings)

        with patch("retriever.embedding._default_embedder") as mock_emb:
            mock_emb.embed.side_effect = _mock_embed
            results = recall_by_query_text("electric vehicle battery", top_k=2)

        self.assertLessEqual(len(results), 2)
        self.assertTrue(all("score" in r for r in results))
        recaller.clear()


# ---------------------------------------------------------------------------
# Rerank tests
# ---------------------------------------------------------------------------

class TestRerank(unittest.TestCase):
    """Test rerank: score and reorder recall candidates (mocked DashScope API)."""

    def test_rerank_empty_candidates(self) -> None:
        """Rerank with empty candidates returns []."""
        result = rerank("query", [], top_k=5)
        self.assertEqual(result, [])

    def test_rerank_fallback_no_api_key(self) -> None:
        """Rerank falls back to candidates[:top_k] when API key is missing."""
        with patch.dict("os.environ", {}, clear=False):
            # Ensure no key in env
            orig_dash = os.environ.get("DASHSCOPE_API_KEY")
            orig_qwen = os.environ.get("QWEN_API_KEY")
            try:
                if "DASHSCOPE_API_KEY" in os.environ:
                    del os.environ["DASHSCOPE_API_KEY"]
                if "QWEN_API_KEY" in os.environ:
                    del os.environ["QWEN_API_KEY"]
                candidates = [
                    {"text": "doc 1", "file_id": "f1"},
                    {"text": "doc 2", "file_id": "f1"},
                    {"text": "doc 3", "file_id": "f2"},
                ]
                result = rerank("query", candidates, top_k=2)
                self.assertEqual(len(result), 2)
                self.assertEqual(result[0]["text"], "doc 1")
                self.assertEqual(result[1]["text"], "doc 2")
            finally:
                if orig_dash is not None:
                    os.environ["DASHSCOPE_API_KEY"] = orig_dash
                if orig_qwen is not None:
                    os.environ["QWEN_API_KEY"] = orig_qwen

    @patch("retriever.rerank.dashscope.TextReRank.call")
    def test_rerank_with_mocked_api(self, mock_call: MagicMock) -> None:
        """Rerank returns reordered candidates with rerank_score when API succeeds."""
        import os
        from http import HTTPStatus

        # Ensure we don't hit "no api key" path
        with patch.dict("os.environ", {"DASHSCOPE_API_KEY": "test-key"}, clear=False):
            candidates = [
                {"text": "文本排序模型用于搜索引擎", "file_id": "f1"},
                {"text": "量子计算是前沿领域", "file_id": "f2"},
                {"text": "预训练语言模型与文本排序", "file_id": "f1"},
            ]
            query = "什么是文本排序模型"

            mock_resp = MagicMock()
            mock_resp.status_code = HTTPStatus.OK
            # API returns top_n=top_k results; with top_k=2 we get 2 results
            mock_resp.output = {
                "results": [
                    {"index": 2, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.85},
                ]
            }
            mock_call.return_value = mock_resp

            result = rerank(query, candidates, top_k=2)

            self.assertEqual(len(result), 2)
            self.assertTrue(all("rerank_score" in r for r in result))
            self.assertGreaterEqual(result[0]["rerank_score"], result[1]["rerank_score"])
            self.assertEqual(result[0]["text"], "预训练语言模型与文本排序")
            self.assertEqual(result[1]["text"], "文本排序模型用于搜索引擎")


if __name__ == "__main__":
    unittest.main()
