"""
Integration test for retriever pipeline: facet, chunking, embedding, recall, and rerank.

Pipelines:
  1. facet.classify_document_facet(text) → {file_type, summary, filename, topics}
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
        mock_complete.return_value = (
            '{"file_type": "transcript", "summary": "Sales interview", '
            '"topics": ["interviews", "hospitals"]}'
        )

        # 1. Facet
        result = classify_document_facet(text, filename="call.md")
        self.assertEqual(result["file_type"], "transcript")
        self.assertIn("summary", result)
        self.assertEqual(result["filename"], "call.md")
        self.assertEqual(result["topics"], ["interviews", "hospitals"])

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

    def test_transcript_chunking_preserves_qa_structure(self) -> None:
        """Transcript chunking must not cut Q&A pairs; supports 问题 Q1 format."""
        # HCP-style transcript with space between 问题 and Q (real format)
        text = """问题 Q1. 请您简单介绍一下您的执业背景
答案：我在天津三甲医院，主任医师，从业时间较长。

问题 Q3. 您如何理解中重度银屑病的严重性和长期影响
答案：银屑病重要，但我不会把它看得过于"需要激进管理"。

问题 Q4. 您在临床上如何区分轻/中/重度
答案：我主要还是凭经验和临床观察判断严重度。"""
        chunks = chunk_text(text, DocumentFacet.TRANSCRIPT)
        self.assertGreaterEqual(len(chunks), 3, "Should get at least 3 Q&A chunks")
        # Each chunk must contain both 问题 and 答案 (full Q&A pair)
        for c in chunks:
            txt = c["text"]
            if txt.strip().startswith("问题") or "问题 Q" in txt or "问题Q" in txt:
                self.assertIn("答案", txt, "Q&A chunk must include answer")
        # First Q&A chunk must start with 问题 Q1 (not just Q1)
        first_qa = next((c for c in chunks if "问题 Q1" in c["text"] or "Q1." in c["text"]), None)
        self.assertIsNotNone(first_qa)
        self.assertIn("答案", first_qa["text"], "First Q&A chunk must have question + answer")

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


# ---------------------------------------------------------------------------
# Orchestration and retrieval pipeline integration tests
# ---------------------------------------------------------------------------


class TestOrchestration(unittest.TestCase):
    """Test run_retrieval_pipeline: query rewrite, source merge, recall/rerank counts."""

    @patch("retriever.query_rewrite.complete")
    @patch("retriever.facet.complete")
    @patch("retriever.embedding._default_embedder")
    @patch("retriever.orchestration.get_document_text")
    @patch("retriever.orchestration.get_document_meta")
    def test_run_retrieval_pipeline_summary_only_query_rewrite(
        self,
        mock_meta: MagicMock,
        mock_text: MagicMock,
        mock_emb: MagicMock,
        mock_facet: MagicMock,
        mock_qw: MagicMock,
    ) -> None:
        """Query rewrite uses cowork summary as input (summary_only)."""
        from retriever.orchestration import run_retrieval_pipeline

        mock_qw.return_value = "HCP city tier segmentation evidence"
        mock_facet.return_value = '{"file_type": "others", "summary": "test"}'
        mock_text.return_value = "Sample document about city tier segmentation for HCPs."
        mock_meta.return_value = {"filename": "doc1.pdf"}
        mock_emb.embed.side_effect = _mock_embed

        content, meta = run_retrieval_pipeline(
            raw_query="Business Objective: city tier.\nSegmentation Lens: city tier.",
            file_ids=[],
            session_upload_docs=[{"filename": "up.pdf", "markdown_content": "City tier HCP evidence."}],
            recall_top_k=5,
            rerank_top_k=2,
        )
        self.assertGreater(meta["query_len"], 0)
        self.assertIn("recalled_count", meta)
        self.assertIn("reranked_count", meta)

    @patch("retriever.query_rewrite.complete")
    @patch("retriever.facet.complete")
    @patch("retriever.embedding._default_embedder")
    def test_run_retrieval_pipeline_both_source_merge(
        self,
        mock_emb: MagicMock,
        mock_facet: MagicMock,
        mock_qw: MagicMock,
    ) -> None:
        """Both session_upload_docs and ingested file_ids are merged."""
        from generation.document_store import _store, _doc_meta_store
        from retriever.orchestration import run_retrieval_pipeline

        mock_qw.return_value = "evidence"
        mock_facet.return_value = '{"file_type": "others", "summary": "test"}'
        mock_emb.embed.side_effect = _mock_embed

        fid = "ingested_123"
        orig_store = dict(_store)
        orig_meta = dict(_doc_meta_store)
        try:
            _store[fid] = "Ingested document content for retrieval."
            _doc_meta_store[fid] = {"filename": "ingested.pdf"}
            content, meta = run_retrieval_pipeline(
                raw_query="Test summary.",
                file_ids=[fid],
                session_upload_docs=[{"filename": "session.pdf", "markdown_content": "Session upload content."}],
                recall_top_k=5,
                rerank_top_k=3,
            )
            self.assertGreater(meta["recalled_count"], 0)
            self.assertGreater(meta["reranked_count"], 0)
        finally:
            _store.clear()
            _store.update(orig_store)
            _doc_meta_store.clear()
            _doc_meta_store.update(orig_meta)

    def test_run_retrieval_pipeline_empty_summary_returns_empty(self) -> None:
        """Empty raw_query returns empty content and zero counts."""
        from retriever.orchestration import run_retrieval_pipeline

        content, meta = run_retrieval_pipeline(
            raw_query="",
            file_ids=[],
        )
        self.assertEqual(content, "")
        self.assertEqual(meta["recalled_count"], 0)
        self.assertEqual(meta["reranked_count"], 0)

    @patch("retriever.query_rewrite.complete")
    @patch("retriever.facet.complete")
    @patch("retriever.embedding._default_embedder")
    def test_run_retrieval_pipeline_recall_rerank_counts(
        self,
        mock_emb: MagicMock,
        mock_facet: MagicMock,
        mock_qw: MagicMock,
    ) -> None:
        """Metadata includes recalled_count and reranked_count for observability."""
        from retriever.orchestration import run_retrieval_pipeline

        mock_qw.return_value = "query"
        mock_facet.return_value = '{"file_type": "others", "summary": "test"}'
        mock_emb.embed.side_effect = _mock_embed

        content, meta = run_retrieval_pipeline(
            raw_query="Summary",
            file_ids=[],
            session_upload_docs=[
                {"filename": "a.pdf", "markdown_content": "Chunk one content here for retrieval test."},
                {"filename": "b.pdf", "markdown_content": "Chunk two different content for retrieval."},
            ],
            recall_top_k=10,
            rerank_top_k=2,
        )
        self.assertIn("recalled_count", meta)
        self.assertIn("reranked_count", meta)
        self.assertLessEqual(meta["reranked_count"], 2)


class TestGetRetrievalContextFallback(unittest.TestCase):
    """Test get_retrieval_context fallback to full markdown on empty/error."""

    def test_get_retrieval_context_fallback_on_empty_summary(self) -> None:
        """Empty raw_query triggers fallback; with no docs run_retrieval returns empty."""
        from generation.document_store import _store, _doc_meta_store
        from generation.context_provider import get_retrieval_context

        fid = "fallback_test_1"
        orig_store = dict(_store)
        orig_meta = dict(_doc_meta_store)
        try:
            _store[fid] = "Fallback document."
            _doc_meta_store[fid] = {"filename": "fallback.pdf"}
            content, meta = get_retrieval_context(
                file_ids=[fid],
                raw_query="",
                correlation_key="test",
            )
            # Empty raw_query causes run_retrieval_pipeline to return "" immediately.
            # Then we fallback to full markdown, so we get the stored content.
            self.assertIn("Fallback document.", content)
            self.assertTrue(meta.get("fallback_used", False) or meta["recalled_count"] == 0)
        finally:
            _store.clear()
            _store.update(orig_store)
            _doc_meta_store.clear()
            _doc_meta_store.update(orig_meta)


if __name__ == "__main__":
    unittest.main()
