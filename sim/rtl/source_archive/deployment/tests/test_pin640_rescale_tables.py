"""Coverage, arithmetic-order, and serialization tests for PIN640 rescale LUTs."""

from pathlib import Path
import struct
import unittest

from tools import z100_pin640_nonconv_tables as nonconv
from tools import z100_pin640_rescale_tables as rescale


REPO_ROOT = Path(__file__).resolve().parents[2]


class Pin640RescaleTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = nonconv.load_project(REPO_ROOT)
        cls.edges = rescale.enumerate_rescale_edges(cls.project)
        cls.payload, cls.rows = rescale.build_python_payload(cls.edges)
        cls.sources = rescale._ordered_sources(
            cls.project, Path(nonconv.__file__).resolve())
        cls.container, cls.layout = rescale.serialize_container(
            cls.sources, cls.payload, cls.rows)

    def test_runtime_rounding_half_ties_and_saturation(self):
        cases = {
            0.5: 0,
            1.5: 2,
            2.5: 2,
            -0.5: 0,
            -1.5: -2,
            -2.5: -2,
            127.5: 127,
            -127.5: -127,
            10000.0: 127,
            -10000.0: -127,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(nonconv.runtime_quant(value), expected)

    def test_runtime_multiply_then_divide_order_is_preserved(self):
        code = -51
        source_scale = 0.000396438290558251
        output_scale = 0.0014976557643311705
        runtime_order = (float(code) * source_scale) / output_scale
        ratio_first = code * (source_scale / output_scale)
        self.assertEqual(nonconv.runtime_quant(runtime_order), -13)
        self.assertEqual(nonconv.runtime_quant(ratio_first), -14)
        table = rescale.make_rescale_table(source_scale, output_scale)
        self.assertEqual(struct.unpack("b", table[code + 128:code + 129])[0], -13)

    def test_full_runtime_edge_mapping_has_no_omissions_or_merges(self):
        expected = []
        for node in self.project["all_graph_nodes"]:
            if node["op"] == "concat":
                expected.extend((node["id"], node["op"], index, input_id)
                                for index, input_id in enumerate(node["inputs"]))
            elif node["op"] in ("slice", "upsample", "maxpool"):
                self.assertEqual(len(node["inputs"]), 1)
                expected.append((node["id"], node["op"], 0, node["inputs"][0]))
        actual = [(row["node_id"], row["op"], row["input_index"], row["input_node_id"])
                  for row in self.edges]
        self.assertEqual(actual, expected)
        self.assertEqual(len(self.edges), 65)
        self.assertEqual(len({row["edge_id"] for row in self.edges}), 65)
        self.assertEqual(self.project["other_rescale_counts"], {
            "concat_input_edges": 44,
            "slice_nodes": 16,
            "upsample_nodes": 2,
            "maxpool_nodes": 3,
            "total_256_entry_builds_per_full_graph_run": 65,
        })
        pool_rows = [row for row in self.rows if row["op"] == "maxpool"]
        self.assertEqual(len(pool_rows), 3)
        self.assertTrue(all("max_in_original_int8_code_domain" in row["semantic_boundary"]
                            for row in pool_rows))

    def test_every_table_covers_the_full_signed_int8_domain(self):
        self.assertEqual(len(self.rows), 65)
        self.assertEqual(len(self.payload), 65 * 256)
        for row in self.rows:
            self.assertEqual(row["payload_bytes"], 256)
            table = self.payload[row["payload_offset"]:row["payload_offset"] + 256]
            self.assertEqual(len(table), 256)
            self.assertEqual(row["index_rule"], "input_code + 128")

    def test_container_embeds_source_hashes_index_and_aligned_payload(self):
        values = rescale.HEADER.unpack_from(self.container)
        magic, version, record_size, source_count, table_count = values[:5]
        metadata_bytes, payload_offset, payload_bytes, input_min, input_max = values[5:10]
        self.assertEqual(magic, rescale.MAGIC)
        self.assertEqual(version, 1)
        self.assertEqual(record_size, rescale.NODE_RECORD.size)
        self.assertEqual(source_count, len(self.sources))
        self.assertEqual(table_count, 65)
        self.assertEqual(metadata_bytes, 576)
        self.assertEqual(payload_offset % 64, 0)
        self.assertEqual(payload_bytes, 16640)
        self.assertEqual((input_min, input_max), (-128, 127))
        self.assertEqual(self.container[payload_offset:], self.payload)
        self.assertEqual(len(self.container), self.layout["container_total_bytes"])
        self.assertEqual(self.layout["metadata_alignment_padding_bytes"], 32)
        self.assertEqual(self.layout["payload_inter_table_padding_bytes"], 0)
        source_start = rescale.HEADER.size
        for index, source in enumerate(self.sources):
            digest = self.container[source_start + index * 32:source_start + (index + 1) * 32]
            self.assertEqual(digest.hex(), source["sha256"])
        first = rescale.NODE_RECORD.unpack_from(self.container, metadata_bytes)
        self.assertEqual(first[0], 0)
        self.assertEqual(first[1], self.rows[0]["node_id"])
        self.assertEqual(first[4], self.rows[0]["input_node_id"])


if __name__ == "__main__":
    unittest.main()
