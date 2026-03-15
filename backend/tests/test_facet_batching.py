import unittest
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retriever.evidence_pipeline import run_evidence_pipeline
from retriever.pipeline_config import PipelineConfig
from retriever.models import ChunkRecord
from retriever.router import _chunk_store


class TestFacetBatching(unittest.TestCase):
    def test_batch_calls_reduce_round_trips(self):
        run_id = uuid.uuid4().hex[:8]
        file_id = f"file-batch-test-{run_id}"
        _chunk_store[file_id] = [
            ChunkRecord(
                chunk_id=f"b{run_id}-{i}",
                doc_id=file_id,
                source_type="md",
                text=f"Safe player channel preference sample {i} with 20 patients per month",
                token_length=25,
                metadata={},
                table_flag=False,
                segment_hint=["safe player"],
                noise_flag=False,
            )
            for i in range(5)
        ]
        cfg = PipelineConfig(
            max_candidates=20,
            max_facet_new_per_request=5,
            facet_batch_size=2,
            max_chunks_agent_read=5,
            max_to_compress=5,
            max_iterations_expand=1,
            max_agent_steps=3,
        )

        def fake_batch(chunks):
            return {
                c.chunk_id: {
                    "segments": c.segment_hint,
                    "topics": ["preferences"],
                    "channels": ["wechat"],
                    "numbers": ["20 patients per month"],
                    "noise_flag": False,
                }
                for c in chunks
            }

        with patch("retriever.evidence_pipeline.extract_facets_batch", side_effect=fake_batch):
            result = run_evidence_pipeline(
                file_ids=[file_id],
                module="Customer Segmentation",
                table_structure={"columns": ["", "Safe Player"], "indexes": ["Preferences"]},
                seed_query="safe player wechat preference",
                config=cfg,
                top_k_fallback=5,
            )
        self.assertEqual(result.metrics["facet_new_generated"], 5)
        self.assertEqual(result.metrics["facet_batch_calls"], 3)


if __name__ == "__main__":
    unittest.main()
