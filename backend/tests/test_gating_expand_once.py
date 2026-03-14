import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generation.evidence_pipeline import run_evidence_pipeline
from generation.pipeline_config import PipelineConfig
from retriever.models import ChunkRecord
from retriever.router import _chunk_store


class TestGatingExpandOnce(unittest.TestCase):
    def test_empty_gating_expands_once(self):
        file_id = "file-expand-test"
        _chunk_store[file_id] = [
            ChunkRecord(
                chunk_id="c1",
                doc_id=file_id,
                source_type="md",
                text="Generic background information with little direct signal.",
                token_length=25,
                metadata={"heading_title": "Overview"},
                table_flag=False,
                segment_hint=[],
                noise_flag=False,
            )
        ]
        cfg = PipelineConfig(
            max_candidates=50,
            max_facet_new_per_request=10,
            max_chunks_agent_read=5,
            max_to_compress=5,
            max_iterations_expand=1,
            max_agent_steps=3,
        )
        result = run_evidence_pipeline(
            file_ids=[file_id],
            module="Customer Segmentation",
            table_structure={"columns": ["", "Safe Player"], "indexes": ["Preferences"]},
            seed_query="wechat channel preferences for safe player",
            config=cfg,
            top_k_fallback=5,
        )
        self.assertIn("gating_expanded_once", result.metrics)
        self.assertTrue(result.metrics["gating_expanded_once"])


if __name__ == "__main__":
    unittest.main()
