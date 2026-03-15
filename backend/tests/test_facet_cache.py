import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retriever.facet_cache import FacetCache


class TestFacetCache(unittest.TestCase):
    def test_cache_hit_and_miss(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "facet_cache.jsonl"
            cache = FacetCache(path=path)

            self.assertIsNone(cache.get("chunk-1"))
            cache.set("chunk-1", {"topics": ["preferences"], "segments": ["safe player"]})
            self.assertEqual(cache.get("chunk-1")["topics"], ["preferences"])

            # New instance reloads from disk and should still hit.
            cache2 = FacetCache(path=path)
            self.assertEqual(cache2.get("chunk-1")["segments"], ["safe player"])


if __name__ == "__main__":
    unittest.main()
