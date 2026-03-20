import unittest
from unittest.mock import patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generation.orchestrator import run_fill


class TestEnhancerIntegration(unittest.TestCase):
    def test_run_fill_passes_resolved_headers_to_context_loader(self):
        # Use SWOT (not Customer Segmentation): CS slide 1 with placeholders uses
        # the per-cell agent instead of this placeholder-resolution path.
        with patch(
            "generation.orchestrator.get_full_markdown_context",
            return_value="full content for segment extraction",
        ), patch(
            "generation.orchestrator.extract_segment_names",
            return_value=["Value Seekers"],
        ), patch(
            "generation.orchestrator.get_context_content",
            return_value="evidence context",
        ) as mock_context, patch(
            "generation.orchestrator.generate_table_content",
            return_value=[["ok"]],
        ):
            res = run_fill(
                slide_idx=1,
                module="SWOT Analysis",
                file_ids=["f1"],
                table_structure={"columns": ["", "Segment 1"], "indexes": ["Preferences"]},
            )
        self.assertIn("table_data", res)
        mock_context.assert_called_once()
        ca = mock_context.call_args
        self.assertEqual(ca.args[0], ["f1"])
        self.assertEqual(ca.args[1] if len(ca.args) > 1 else ca.kwargs.get("query", ""), "")
        self.assertEqual(ca.kwargs.get("module"), "SWOT Analysis")
        self.assertEqual(
            ca.kwargs.get("table_structure"),
            {"columns": ["", "Value Seekers"], "indexes": ["Preferences"]},
        )


if __name__ == "__main__":
    unittest.main()
