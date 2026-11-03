"""Exactness and layout tests for the PIN640 non-convolution table generator."""

import hashlib
from pathlib import Path
import struct
import unittest

from tools import z100_pin640_nonconv_tables as tables


REPO_ROOT = Path(__file__).resolve().parents[2]


class Pin640NonconvTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = tables.load_project(REPO_ROOT)
        cls.payload, cls.rows = tables.build_python_payload(cls.project)
        cls.container, cls.layout = tables.serialize_container(
            cls.project, cls.payload, cls.rows)

    def test_complete_graph_inventory_and_rescale_scope(self):
        self.assertEqual(len(self.project["all_graph_nodes"]), 163)
        self.assertEqual(self.project["op_counts"], tables.EXPECTED_OP_COUNTS)
        self.assertEqual(sum(row["op"] == "silu" for row in self.rows), 57)
        self.assertEqual(sum(row["op"] == "add" for row in self.rows), 6)
        self.assertEqual(len(self.payload), 407808)
        self.assertEqual(self.project["other_rescale_counts"], {
            "concat_input_edges": 44,
            "slice_nodes": 16,
            "upsample_nodes": 2,
            "maxpool_nodes": 3,
            "total_256_entry_builds_per_full_graph_run": 65,
        })

    def test_runtime_ties_even_and_saturation(self):
        cases = {
            0.5: 0,
            1.5: 2,
            2.5: 2,
            -0.5: 0,
            -1.5: -2,
            -2.5: -2,
            1000.0: 127,
            -1000.0: -127,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(tables.runtime_quant(value), expected)

    def test_add_table_rounds_once_after_joint_scaled_sum(self):
        table = tables.make_add_table(0.51, 0.51, 1.0)
        joint_index = (1 + 128) * 256 + (1 + 128)
        joint = struct.unpack("b", table[joint_index:joint_index + 1])[0]
        rounded_separately = (tables.runtime_quant(1 * 0.51) +
                              tables.runtime_quant(1 * 0.51))
        self.assertEqual(joint, 1)
        self.assertEqual(rounded_separately, 2)
        self.assertNotEqual(joint, rounded_separately)

    def test_all_silu_tables_byte_match_runtime_package_luts(self):
        package = self.project["package"]
        count = 0
        for row in self.rows:
            if row["op"] != "silu":
                continue
            payload_table = self.payload[row["payload_offset"]:
                                          row["payload_offset"] + row["payload_bytes"]]
            lut_offset = 32 + row["lut_offset"]
            package_table = package[lut_offset:lut_offset + 256]
            with self.subTest(node_id=row["node_id"]):
                self.assertEqual(len(payload_table), 256)
                self.assertEqual(payload_table, package_table)
            count += len(payload_table)
        self.assertEqual(count, 57 * 256)

    def test_container_indices_hashes_and_alignment(self):
        values = tables.HEADER.unpack_from(self.container)
        magic, version, record_bytes, source_count, node_count = values[:5]
        header_bytes, payload_offset, payload_bytes, min_code, max_code = values[5:10]
        schema_sha = values[10]
        self.assertEqual(magic, tables.MAGIC)
        self.assertEqual(version, 1)
        self.assertEqual(record_bytes, tables.NODE_RECORD.size)
        self.assertEqual(source_count, len(self.project["sources"]))
        self.assertEqual(node_count, 63)
        self.assertEqual(header_bytes, tables.HEADER.size + source_count * 32)
        self.assertEqual(payload_offset, header_bytes + node_count * record_bytes)
        self.assertEqual(payload_offset % 64, 0)
        self.assertEqual(payload_bytes, len(self.payload))
        self.assertEqual((min_code, max_code), (-128, 127))
        self.assertEqual(schema_sha, tables.SCHEMA_SHA256)
        self.assertEqual(self.container[payload_offset:], self.payload)
        self.assertEqual(len(self.container), self.layout["container_total_bytes"])
        self.assertEqual(self.layout["alignment_padding_bytes"], 0)
        first = tables.NODE_RECORD.unpack_from(self.container, header_bytes)
        last = tables.NODE_RECORD.unpack_from(
            self.container, header_bytes + (node_count - 1) * record_bytes)
        self.assertEqual(first[0], self.rows[0]["node_id"])
        self.assertEqual(last[0], self.rows[-1]["node_id"])
        source_sha_start = tables.HEADER.size
        for index, source in enumerate(self.project["sources"]):
            embedded = self.container[source_sha_start + index * 32:
                                      source_sha_start + (index + 1) * 32]
            self.assertEqual(embedded.hex(), source["sha256"])
        self.assertEqual(hashlib.sha256(self.payload).hexdigest(),
                         tables.sha256_bytes(self.container[payload_offset:]))


if __name__ == "__main__":
    unittest.main()
