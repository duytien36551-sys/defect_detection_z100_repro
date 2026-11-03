"""Hand-counted activation-cache validity, spill, burst, and tail tests."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from z100_wholegraph_memory_trace import (  # noqa: E402
    ActivationCache,
    BurstCounter,
    iter_full_storage_lines,
    iter_line_addresses,
)


class WholeGraphMemoryTraceTests(unittest.TestCase):
    def test_hand_counted_lru_dirty_spill_read_after_spill_and_output_flush(self):
        cache = ActivationCache(64)
        cache.prime_external(-1, [0])

        cache.read_line(-1, 0, 0)  # input line 0 becomes clean resident
        cache.write_full_line(1, 1, 64)  # clean input is evicted, output line is dirty
        cache.write_full_line(1, 1, 128)  # dirty line 64 spills
        expected = cache.expected[1][64]
        self.assertEqual(cache.backing[64], expected)

        # The spilled value must be fetched and match the current output generation.
        self.assertEqual(cache.read_line(1, 2, 64), expected)
        cache.write_full_line(1, 2, 192)
        cache.flush_retained([1])

        self.assertEqual(cache.backing[64], expected)
        self.assertEqual(cache.counters["dirty_spill_lines"], 2)  # lines 64 and 128
        self.assertEqual(cache.counters["final_flush_lines"], 1)  # line 192
        self.assertEqual(cache.counters["ddr_read_lines"], 2)  # initial input + read-after-spill
        self.assertEqual(cache.counters["ddr_write_lines"], 3)  # two spills + retained-output flush
        self.assertEqual(cache.counters["read_cache_hits"], 0)
        profiles = cache.finish()["burst_accounting_by_profile"]
        candidate = profiles["hypothetical_64bit_max16beat_candidate"]
        active_stub = profiles["generated_stub_hp0_32bit_max16beat"]
        self.assertEqual(candidate["burst_transactions"], {"read": 2, "write": 2})
        self.assertEqual(candidate["burst_beat_histogram"]["read"], {"8": 2})
        self.assertEqual(active_stub["burst_transactions"], {"read": 2, "write": 3})
        self.assertEqual(active_stub["max_burst_bytes"], 64)

    def test_last_consumer_discards_dirty_line_without_spilling(self):
        cache = ActivationCache(64)
        cache.write_full_line(7, 7, 0)
        self.assertTrue(cache.lines[0]["dirty"])
        cache.release_tensor(7)
        self.assertNotIn(0, cache.lines)
        self.assertNotIn(0, cache.backing)
        self.assertEqual(cache.counters["dirty_lifetime_discard_lines"], 1)
        self.assertEqual(cache.counters["ddr_write_lines"], 0)

    def test_4k_boundary_splits_bursts_and_tail_spans_use_full_lines(self):
        counter = BurstCounter(beat_bytes=8, max_beats=16,
                               profile_name="hypothetical_64bit_max16beat_candidate")
        # The 4KiB boundary splits FC0 -> 1000; the 16-beat limit splits
        # 1040 -> 1080 after the two-line 1000/1040 candidate burst.
        for address in (0x0FC0, 0x1000, 0x1040, 0x1080):
            counter.add("read", address)
        counter.add("write", 0x2000)
        counter.add("write", 0x2040)
        counter.add("write", 0x2080)
        burst = counter.finish()
        self.assertEqual(burst["burst_transactions"], {"read": 3, "write": 2})
        self.assertEqual(burst["contiguous_4k_page_splits"], {"read": 1})
        self.assertEqual(burst["max_length_splits_not_due_to_4k"], {"read": 1, "write": 1})
        self.assertEqual(burst["burst_line_histogram"]["read"], {"1": 2, "2": 1})
        self.assertEqual(burst["burst_beat_histogram"]["read"], {"8": 2, "16": 1})
        self.assertEqual(burst["burst_line_histogram"]["write"], {"1": 1, "2": 1})
        self.assertEqual(burst["burst_beat_histogram"]["write"], {"8": 1, "16": 1})
        self.assertEqual(burst["max_beats"], 16)
        self.assertEqual(burst["max_burst_bytes"], 128)

        self.assertEqual(list(iter_line_addresses(0x3000, 65)), [0x3000, 0x3040])
        self.assertEqual(list(iter_full_storage_lines(0x4000, 65)), [0x4000, 0x4040])
        self.assertEqual(sum(1 for _ in iter_full_storage_lines(0x4000, 65)) * 64, 128)

    def test_generated_stub_profile_is_32bit_16beat_and_one_cache_line(self):
        counter = BurstCounter(beat_bytes=4, max_beats=16,
                               profile_name="generated_stub_hp0_32bit_max16beat")
        for address in (0x0FC0, 0x1000, 0x1040):
            counter.add("read", address)
        burst = counter.finish()
        self.assertEqual(burst["data_width_bits"], 32)
        self.assertEqual(burst["max_beats"], 16)
        self.assertEqual(burst["max_burst_bytes"], 64)
        self.assertEqual(burst["max_burst_lines"], 1)
        self.assertEqual(burst["burst_transactions"], {"read": 3})
        self.assertEqual(burst["contiguous_4k_page_splits"], {"read": 1})
        self.assertEqual(burst["max_length_splits_not_due_to_4k"], {"read": 1})

    def test_unproduced_or_retired_activation_read_is_rejected(self):
        cache = ActivationCache(128)
        with self.assertRaisesRegex(ValueError, "unproduced/retired"):
            cache.read_line(3, 4, 0)

        cache.prime_external(-1, [0])
        cache.read_line(-1, 0, 0)
        cache.release_tensor(-1)
        with self.assertRaisesRegex(ValueError, "unproduced/retired"):
            cache.read_line(-1, 1, 0)

    def test_cache_geometry_and_address_alignment_are_checked(self):
        with self.assertRaisesRegex(ValueError, "whole number of cache lines"):
            ActivationCache(65)
        with self.assertRaisesRegex(ValueError, "line aligned"):
            list(iter_full_storage_lines(1, 64))
        with self.assertRaisesRegex(ValueError, "misaligned"):
            ActivationCache(64).read_line(1, 0, 1)
        with self.assertRaisesRegex(ValueError, "invalid burst geometry"):
            BurstCounter(beat_bytes=8, max_beats=1)


if __name__ == "__main__":
    unittest.main()
