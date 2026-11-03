import json
import tempfile
import unittest
from pathlib import Path

from audit_dma_timeline import audit


class DmaTimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "events.json"

    def tearDown(self):
        self.temp.cleanup()

    def run_events(self, events):
        self.path.write_text(json.dumps({"schema_version": 1, "events": events}), encoding="utf-8")
        return audit(self.path)

    def test_single_run_chronological(self):
        result, code = self.run_events([
            {"run_id": "r1", "timestamp": "2026-10-28T10:00:00+08:00", "event": "start"},
            {"run_id": "r1", "timestamp": "2026-10-28T10:00:01+08:00", "event": "done"}])
        self.assertEqual((result["status"], code), ("single_run_chronological", 0))

    def test_cross_run_and_timestamp_reversal(self):
        result, code = self.run_events([
            {"run_id": "a", "timestamp": "2026-10-28T10:00:02Z", "event": "later"},
            {"run_id": "b", "timestamp": "2026-10-28T10:00:00Z", "event": "other"},
            {"run_id": "a", "timestamp": "2026-10-28T10:00:01Z", "event": "earlier"}])
        self.assertEqual(code, 1)
        self.assertTrue(result["multiple_runs"])
        self.assertTrue(result["interleaved_runs"])
        self.assertEqual(result["order_anomalies"][0]["kind"], "timestamp_reversal")

    def test_contiguous_run_blocks_are_not_interleaved(self):
        result, code = self.run_events([
            {"run_id": "a", "timestamp": "2026-10-28T10:00:00Z", "event": "a1"},
            {"run_id": "a", "timestamp": "2026-10-28T10:00:01Z", "event": "a2"},
            {"run_id": "b", "timestamp": "2026-10-28T10:00:00Z", "event": "b1"},
            {"run_id": "b", "timestamp": "2026-10-28T10:00:01Z", "event": "b2"}])
        self.assertEqual(code, 1)
        self.assertTrue(result["multiple_runs"])
        self.assertFalse(result["interleaved_runs"])

    def test_rejects_empty_event_list(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            self.run_events([])

    def test_rejects_missing_fields_bad_types_and_naive_time(self):
        bad_sets = [
            [{"run_id": "x", "timestamp": "2026-10-28T00:00:00Z"}],
            [{"run_id": ["x"], "timestamp": "2026-10-28T00:00:00Z", "event": "go"}],
            [{"run_id": "x", "timestamp": "2026-10-28T00:00:00", "event": "go"}],
            ["malformed event"],
        ]
        for events in bad_sets:
            with self.subTest(events=events), self.assertRaises(ValueError):
                self.run_events(events)


if __name__ == "__main__":
    unittest.main()
