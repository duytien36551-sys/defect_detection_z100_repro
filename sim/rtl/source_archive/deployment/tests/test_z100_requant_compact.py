"""Small hand-checked tests for the lossless threshold container."""
import struct
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from z100_requant_compact import (  # noqa: E402
    DIRECTORY_ENTRY,
    DIRECTORY_ENTRY_SIZE,
    HEADER,
    HEADER_SIZE,
    INT64_MAX,
    INT64_MIN,
    MIN_THRESHOLD,
    MODE_DELTA,
    MODE_RAW_I64,
    SENTINEL_THRESHOLD,
    THRESHOLDS_PER_CHANNEL,
    ThresholdDecoder,
    pack_channels,
    pack_unsigned_bits,
    read_unsigned_bits,
)


def _two_delta_channel():
    # Values are 7, 10, 10, 13, 13, ...; adjacent deltas alternate 3 and 0.
    return [7 + ((index + 1) // 2) * 3 for index in range(THRESHOLDS_PER_CHANNEL)]


def _refresh_header_crc_and_directory_crc(blob):
    fields = list(HEADER.unpack_from(blob))
    directory_offset = fields[7]
    directory_size = fields[3] * DIRECTORY_ENTRY_SIZE
    directory = blob[directory_offset:directory_offset + directory_size]
    fields[10] = zlib.crc32(directory) & 0xFFFFFFFF
    fields[11] = 0
    zero_crc_header = HEADER.pack(*fields)
    fields[11] = zlib.crc32(zero_crc_header) & 0xFFFFFFFF
    blob[:HEADER_SIZE] = HEADER.pack(*fields)


class RequantCompactTests(unittest.TestCase):
    def test_hand_calculated_lsb_first_bitpack_and_direct_index(self):
        self.assertEqual(pack_unsigned_bits([1, 0, 3], 2), b"\x31")
        self.assertEqual([read_unsigned_bits(b"\x31", i, 2, 3) for i in range(3)], [1, 0, 3])
        with self.assertRaises(IndexError):
            read_unsigned_bits(b"\x31", 3, 2, 3)

        source = _two_delta_channel()
        packed, _info = pack_channels([source])
        decoder = ThresholdDecoder(packed)
        entry = DIRECTORY_ENTRY.unpack_from(packed, HEADER_SIZE)
        self.assertEqual(entry[4], 0)  # min adjacent delta
        self.assertEqual(entry[5], MODE_DELTA)
        self.assertEqual(entry[6], 2)  # residual max is 3, requiring two bits
        self.assertEqual(decoder.unpack_all(), [source])
        for index in (0, 1, 2, 15, 16, 17, 252, 253):
            self.assertEqual(decoder.decode(0, index), source[index])

    def test_min_sentinel_repeated_values_and_delta_2pow32(self):
        source = [MIN_THRESHOLD] * 253 + [SENTINEL_THRESHOLD]
        packed, _info = pack_channels([source])
        entry = DIRECTORY_ENTRY.unpack_from(packed, HEADER_SIZE)
        self.assertEqual(entry[4], 0)
        self.assertEqual(entry[5], MODE_DELTA)
        self.assertEqual(entry[6], 33)
        decoder = ThresholdDecoder(packed)
        self.assertEqual(decoder.unpack_all(), [source])
        self.assertEqual(decoder.decode(0, 0), -(1 << 31))
        self.assertEqual(decoder.decode(0, 252), -(1 << 31))
        self.assertEqual(decoder.decode(0, 253), 1 << 31)

    def test_arbitrary_monotonic_signed64_uses_lossless_raw_fallback(self):
        source = [INT64_MIN] * 253 + [INT64_MAX]
        packed, info = pack_channels([source])
        entry = DIRECTORY_ENTRY.unpack_from(packed, HEADER_SIZE)
        self.assertEqual(entry[5], MODE_RAW_I64)
        self.assertEqual(entry[2], THRESHOLDS_PER_CHANNEL * 8)
        self.assertEqual(info[0]["mode"], "raw_i64_fallback")
        decoder = ThresholdDecoder(packed)
        self.assertEqual(decoder.decode(0, 0), INT64_MIN)
        self.assertEqual(decoder.decode(0, 253), INT64_MAX)
        self.assertEqual(decoder.unpack_all(), [source])

    def test_rejects_nonmonotonic_wrong_length_and_signed64_overflow(self):
        source = _two_delta_channel()
        nonmonotonic = source.copy()
        nonmonotonic[100] = nonmonotonic[99] - 1
        with self.assertRaisesRegex(ValueError, "monotonic"):
            pack_channels([nonmonotonic])
        with self.assertRaisesRegex(ValueError, "254 thresholds"):
            pack_channels([source[:-1]])
        overflow = source.copy()
        overflow[-1] = INT64_MAX + 1
        with self.assertRaisesRegex(ValueError, "signed 64-bit"):
            pack_channels([overflow])

    def test_rejects_corruption_invalid_offsets_and_out_of_range_queries(self):
        source = _two_delta_channel()
        packed, _info = pack_channels([source])
        decoder = ThresholdDecoder(packed)
        with self.assertRaises(IndexError):
            decoder.decode(0, 254)
        with self.assertRaises(IndexError):
            decoder.decode(1, 0)

        damaged = bytearray(packed)
        data_offset = HEADER.unpack_from(damaged)[8]
        damaged[data_offset + 80] ^= 1
        with self.assertRaisesRegex(ValueError, "record CRC mismatch"):
            ThresholdDecoder(damaged)

        bad_offset = bytearray(packed)
        row = list(DIRECTORY_ENTRY.unpack_from(bad_offset, HEADER_SIZE))
        row[1] = len(bad_offset) + 8
        bad_offset[HEADER_SIZE:HEADER_SIZE + DIRECTORY_ENTRY_SIZE] = DIRECTORY_ENTRY.pack(*row)
        _refresh_header_crc_and_directory_crc(bad_offset)
        with self.assertRaisesRegex(ValueError, "out of bounds"):
            ThresholdDecoder(bad_offset)


if __name__ == "__main__":
    unittest.main()
