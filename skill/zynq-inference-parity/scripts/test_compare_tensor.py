import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("compare_tensor", HERE / "compare_tensor.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TensorCompareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.a = Path(self.temp.name) / "a.bin"
        self.b = Path(self.temp.name) / "b.bin"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, a, b):
        self.a.write_bytes(a); self.b.write_bytes(b)

    def test_float_tolerance_and_hash(self):
        self.write(struct.pack("<2f", 1.0, 2.0), struct.pack("<2f", 1.0, 2.001))
        r = module.compare(self.a, self.b, "f32", "little", [2], 0.002, 0)
        self.assertEqual(r["status"], "within_tolerance")
        self.assertEqual(len(r["reference"]["sha256"]), 64)

    def test_integer_shape_mismatch(self):
        self.write(bytes([1, 2]), bytes([1, 3]))
        r = module.compare(self.a, self.b, "u8", "little", [2], 0, 0)
        self.assertEqual(r["mismatched_elements"], 1)

    def test_declared_zero_padding(self):
        self.write(struct.pack("<f", 1) + b"\0\0", struct.pack("<f", 1) + b"\0\0")
        r = module.compare(self.a, self.b, "f32", "little", [1], 0, 0, True, 0)
        self.assertEqual(r["contract"]["padding_bytes"], 2)
        with self.assertRaises(ValueError):
            module.compare(self.a, self.b, "f32", "little", [1], 0, 0)

    def test_reject_bad_shape_short_input_and_nonzero_padding(self):
        self.write(b"\0", b"\0")
        with self.assertRaises(ValueError):
            module.compare(self.a, self.b, "u8", "little", [0], 0, 0)
        with self.assertRaises(ValueError):
            module.compare(self.a, self.b, "f32", "little", [1], 0, 0)
        self.write(struct.pack("<f", 1) + b"\1", struct.pack("<f", 1) + b"\1")
        with self.assertRaises(ValueError):
            module.compare(self.a, self.b, "f32", "little", [1], 0, 0, True, 0)

    def test_nonfinite_values_are_reported_without_invalid_json_values(self):
        self.write(struct.pack("<f", float("nan")), struct.pack("<f", float("nan")))
        r = module.compare(self.a, self.b, "f32", "little", [1], 0, 0)
        self.assertEqual(r["status"], "different")
        self.assertEqual(r["nonfinite_element_indices"], [0])
        self.assertEqual(r["first_mismatch"]["reference"], "nan")
        json.dumps(r, allow_nan=False)

    def test_finite_f64_subtraction_overflow_is_json_safe(self):
        self.write(struct.pack("<d", 1.7e308), struct.pack("<d", -1.7e308))
        r = module.compare(self.a, self.b, "f64", "little", [1], 0, 0)
        self.assertEqual(r["status"], "different")
        self.assertEqual(r["max_absolute_error"], "inf")
        json.dumps(r, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
