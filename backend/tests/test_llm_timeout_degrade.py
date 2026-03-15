import unittest
from unittest.mock import patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retriever.evidence_pipeline import run_evidence_pipeline
from retriever.pipeline_config import PipelineConfig
from retriever.models import ChunkRecord
from retriever.router import _chunk_store


class TestLLMTimeoutDegrade(unittest.TestCase):
    def test_facet_timeout_triggers_degrade(self):
        file_id = "file-timeout-test"
        _chunk_store[file_id] = [
            ChunkRecord(
                chunk_id="timeout-c1",
                doc_id=file_id,
                source_type="md",
                text="Safe player prefers WeChat and sees 34 patients per month.",
                token_length=18,
                metadata={"heading_title": "Preferences"},
                table_flag=False,
                segment_hint=["safe player"],
                noise_flag=False,
            )
        ]
        cfg = PipelineConfig()
        with patch("retriever.evidence_pipeline.extract_facets_batch", side_effect=TimeoutError("llm timeout")):
            result = run_evidence_pipeline(
                file_ids=[file_id],
                module="Customer Segmentation",
                table_structure={"columns": ["", "Safe Player"], "indexes": ["Preferences"]},
                seed_query="safe player preferences channel",
                config=cfg,
                top_k_fallback=3,
            )
        self.assertTrue(result.degraded)
        self.assertTrue(result.context_text.strip())


if __name__ == "__main__":
    unittest.main()
