import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("summarize_timings", HERE / "summarize_timings.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TimingSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "timings.csv"

    def tearDown(self):
        self.temp.cleanup()

    def put(self, text):
        self.path.write_text(text, encoding="utf-8")

    def test_percentiles_and_identity(self):
        self.put("duration_ms\n1\n2\n3\n4\n5\n")
        r = module.summarize(self.path, "run-1", "request start to response", "model-A/board-B")
        self.assertEqual(r["sample_count"], 5)
        self.assertEqual(r["median"], 3)
        self.assertEqual(r["p95_nearest_rank"], 5)
        self.assertIn("nearest rank", r["percentile_method"])

    def test_single_sample(self):
        self.put("duration_ms\n7.5\n")
        r = module.summarize(self.path, "one", "single request", "build-x")
        self.assertEqual(r["p50_nearest_rank"], 7.5)
        self.assertIsNone(r["p95_nearest_rank"])
        self.assertTrue(r["limitations"])

    def test_embedded_run_metadata_is_checked(self):
        self.put("duration_ms,run_id,identity,timing_scope\n1,run-a,build-a,scope-a\n")
        self.assertEqual(module.summarize(self.path, "run-a", "scope-a", "build-a")["sample_count"], 1)
        self.put("duration_ms,run_id\n1,run-a\n2,run-b\n")
        with self.assertRaisesRegex(ValueError, "run_id column disagrees"):
            module.summarize(self.path, "run-a", "scope", "identity")

    def test_empty_or_invalid_samples_and_identity(self):
        for content in ("duration_ms\n", "duration_ms\nNaN\n", "duration_ms\n-1\n", "duration_ms\nabc\n", "time\n1\n"):
            self.put(content)
            with self.assertRaises(ValueError):
                module.summarize(self.path, "run", "scope", "identity")
        self.put("duration_ms\n1\n")
        with self.assertRaises(ValueError):
            module.summarize(self.path, "", "scope", "identity")


if __name__ == "__main__":
    unittest.main()
