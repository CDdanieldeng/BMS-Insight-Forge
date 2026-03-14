import unittest
from unittest.mock import patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generation.orchestrator import run_fill


class TestEnhancerIntegration(unittest.TestCase):
    def test_run_fill_uses_resolved_segment_headers_for_query_enhancement(self):
        with patch(
            "generation.orchestrator._full_markdown_context",
            return_value="full content for segment extraction",
        ), patch(
            "generation.orchestrator.extract_segment_names",
            return_value=["Value Seekers"],
        ), patch(
            "generation.orchestrator.enhance_query",
            return_value="seed query",
        ) as mock_enhance, patch(
            "generation.orchestrator._get_context_content",
            return_value="evidence context",
        ) as mock_context, patch(
            "generation.orchestrator.generate_table_content",
            return_value=[["ok"]],
        ):
            res = run_fill(
                slide_idx=1,
                module="Customer Segmentation",
                file_ids=["f1"],
                table_structure={"columns": ["", "Segment 1"], "indexes": ["Preferences"]},
            )
        self.assertIn("table_data", res)
        mock_enhance.assert_called_once()
        enhance_args, _ = mock_enhance.call_args
        self.assertEqual(enhance_args[0], "Customer Segmentation")
        self.assertEqual(
            enhance_args[1],
            {"columns": ["", "Value Seekers"], "indexes": ["Preferences"]},
        )
        context_args, context_kwargs = mock_context.call_args
        self.assertEqual(context_args[0], ["f1"])
        self.assertEqual(context_args[1], "seed query")
        self.assertEqual(context_kwargs.get("module"), "Customer Segmentation")


if __name__ == "__main__":
    unittest.main()
