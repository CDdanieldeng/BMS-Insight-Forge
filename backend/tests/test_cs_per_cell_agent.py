"""Tests for Customer Segmentation per-cell planner and agent helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.customer_segmentation.agent import (  # noqa: E402
    CS_RERANK_TOP_K,
    CS_RECALL_TOP_K,
    CustomerSegmentationAgent,
    _parse_single_cell_response,
    is_generic_segment_placeholder,
    plan_cell_tasks,
)
from modules.customer_segmentation.slides.slide1 import (  # noqa: E402
    NOT_FOUND_CELL_TEXT,
    row_definition_for_index,
)


class TestGenericSegmentPlaceholder(unittest.TestCase):
    def test_detects_segment_n_labels(self) -> None:
        self.assertTrue(is_generic_segment_placeholder("Segment 4"))
        self.assertTrue(is_generic_segment_placeholder("segment 12"))
        self.assertTrue(is_generic_segment_placeholder("  Segment 1  "))
        self.assertFalse(is_generic_segment_placeholder("Tier 1 (Major Metros)"))
        self.assertFalse(is_generic_segment_placeholder("Segment A"))


class TestPlanCellTasks(unittest.TestCase):
    def test_cartesian_count_and_row_major_order(self) -> None:
        segments = ["A", "B", "C"]
        indexes = ["R0", "R1"]
        tasks = plan_cell_tasks(segments, indexes)
        self.assertEqual(len(tasks), 6)
        expected = [
            (0, 0, "A", "R0"),
            (0, 1, "B", "R0"),
            (0, 2, "C", "R0"),
            (1, 0, "A", "R1"),
            (1, 1, "B", "R1"),
            (1, 2, "C", "R1"),
        ]
        for i, t in enumerate(tasks):
            er, ec, es, el = expected[i]
            self.assertEqual(t.row_idx, er)
            self.assertEqual(t.col_idx, ec)
            self.assertEqual(t.segment_name, es)
            self.assertEqual(t.row_label, el)
            self.assertIn(es, t.raw_query)
            self.assertIn(el, t.raw_query)

    def test_skips_generic_segment_placeholders(self) -> None:
        segments = ["Tier 1", "Tier 2", "Segment 3"]
        indexes = ["R0", "R1"]
        tasks = plan_cell_tasks(segments, indexes)
        self.assertEqual(len(tasks), 4)
        self.assertTrue(all(t.segment_name != "Segment 3" for t in tasks))
        self.assertEqual({t.col_idx for t in tasks}, {0, 1})


class TestRowDefinition(unittest.TestCase):
    def test_known_row_matches_demographics(self) -> None:
        ix = ["Demographics", "OtherRow"]
        d0 = row_definition_for_index(ix, 0)
        self.assertIn("Demographics", d0)
        self.assertIn("age", d0.lower())


class TestParseSingleCellResponse(unittest.TestCase):
    def test_json_cell(self) -> None:
        raw = '{"cell": "Hello world."}'
        self.assertEqual(
            _parse_single_cell_response(raw, NOT_FOUND_CELL_TEXT),
            "Hello world.",
        )

    def test_json_in_fence(self) -> None:
        raw = '```json\n{"cell": "x"}\n```'
        self.assertEqual(_parse_single_cell_response(raw, NOT_FOUND_CELL_TEXT), "x")

    def test_invalid_returns_not_found(self) -> None:
        self.assertEqual(
            _parse_single_cell_response("not json", NOT_FOUND_CELL_TEXT),
            NOT_FOUND_CELL_TEXT,
        )


class TestCustomerSegmentationAgentConcurrentMock(unittest.TestCase):
    def test_fill_assembly_from_mocks(self) -> None:
        agent = CustomerSegmentationAgent.__new__(CustomerSegmentationAgent)
        segments = ["Seg1", "Seg2"]
        indexes = ["Demographics", "Drivers"]

        def fake_pipeline(*_a, **_k):
            return "## Document 1: f\n\nstub", {}

        def fake_invoke(_inp):
            msg = MagicMock()
            msg.content = '{"cell": "filled"}'
            return msg

        agent._cell_chain = MagicMock(invoke=fake_invoke)

        with patch(
            "retriever.orchestration.build_indexed_retrieval_corpus",
            return_value=MagicMock(merged_docs=[{"file_id": "fid"}], all_chunks=[]),
        ), patch(
            "retriever.orchestration.run_retrieval_pipeline",
            side_effect=fake_pipeline,
        ):
            table = agent._fill_table_concurrent(
                segments,
                indexes,
                file_ids=["fid"],
                module="customer segmentation",
                methodology=None,
                session_upload_docs=None,
                trace_capture=None,
                session_dir=None,
            )

        self.assertEqual(table, [["filled", "filled"], ["filled", "filled"]])

    def test_fill_skips_generic_segment_columns(self) -> None:
        agent = CustomerSegmentationAgent.__new__(CustomerSegmentationAgent)
        segments = ["A", "Segment 2", "B"]
        indexes = ["Demographics"]

        def fake_pipeline(*_a, **_k):
            return "## Document 1: f\n\nstub", {}

        invoke_count = 0

        def fake_invoke(_inp):
            nonlocal invoke_count
            invoke_count += 1
            msg = MagicMock()
            msg.content = '{"cell": "filled"}'
            return msg

        agent._cell_chain = MagicMock(invoke=fake_invoke)

        with patch(
            "retriever.orchestration.build_indexed_retrieval_corpus",
            return_value=MagicMock(merged_docs=[{"file_id": "fid"}], all_chunks=[]),
        ), patch(
            "retriever.orchestration.run_retrieval_pipeline",
            side_effect=fake_pipeline,
        ):
            table = agent._fill_table_concurrent(
                segments,
                indexes,
                file_ids=["fid"],
                module="customer segmentation",
                methodology=None,
                session_upload_docs=None,
                trace_capture=None,
                session_dir=None,
            )

        self.assertEqual(invoke_count, 2)
        self.assertEqual(
            table,
            [
                ["filled", NOT_FOUND_CELL_TEXT, "filled"],
            ],
        )

    def test_run_uses_pipeline_top_k_constants(self) -> None:
        self.assertEqual(CS_RECALL_TOP_K, 48)
        self.assertEqual(CS_RERANK_TOP_K, 16)


class TestOrchestratorCsGuard(unittest.TestCase):
    def test_run_fill_cs_placeholders_extracts_when_no_cowork_or_cache(self) -> None:
        from generation.orchestrator import run_fill

        fake_agent = MagicMock()
        fake_agent.run.return_value = {
            "segment_names": ["FromAgent"],
            "table_data": [["cell"]],
            "maturity": "test",
        }
        fake_provider = MagicMock()
        fake_provider.get_table_fill_agent.return_value = fake_agent

        with patch("generation.orchestrator.get_segment_names", return_value=None):
            with patch(
                "generation.orchestrator.get_full_markdown_context",
                return_value="markdown context",
            ):
                with patch(
                    "generation.orchestrator.extract_segment_names",
                    return_value=["Extracted"],
                ) as ext:
                    with patch(
                        "modules._registry.get_module",
                        return_value=fake_provider,
                    ):
                        with patch("generation.orchestrator.set_segment_names"):
                            with patch("generation.orchestrator.set_slide_table"):
                                with patch("generation.orchestrator.write_fill_trace"):
                                    result = run_fill(
                                        slide_idx=1,
                                        module="Customer Segmentation",
                                        file_ids=["f1"],
                                        table_structure={
                                            "columns": ["", "Segment 1"],
                                            "indexes": ["A"],
                                        },
                                    )
        ext.assert_called_once()
        fake_agent.run.assert_called_once()
        self.assertEqual(result["column_headers"], ["FromAgent"])
        self.assertEqual(result["table_data"], [["cell"]])


if __name__ == "__main__":
    unittest.main()
