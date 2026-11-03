import importlib.util
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("audit_quality_report.py")
SPEC = importlib.util.spec_from_file_location("audit_quality_report", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
EXAMPLE = json.loads((SCRIPT.parents[1] / "examples" / "quality_report_audit.json").read_text(encoding="utf-8"))


class AuditQualityReportTests(unittest.TestCase):
    def test_complete_report_calculates_micro_metrics_and_quantization_pp(self):
        result = MODULE.audit(EXAMPLE)
        self.assertEqual(result["status"], "audit_pass")
        micros = [x["fixed_micro"] for x in result["derived"] if "fixed_micro" in x]
        self.assertEqual((micros[0]["tp"], micros[0]["fp"], micros[0]["fn"]), (12, 2, 3))
        self.assertAlmostEqual(micros[0]["precision"], 12 / 14)
        self.assertAlmostEqual(micros[0]["recall"], 12 / 15)
        loss = [x for x in result["derived"] if "quantization_loss_ap50_95_percentage_points" in x][0]
        self.assertAlmostEqual(loss["quantization_loss_ap50_95_percentage_points"], 3.0)

    def test_missing_class_is_invalid(self):
        report = json.loads(json.dumps(EXAMPLE))
        report["evaluations"][0]["classes"].pop()
        result = MODULE.audit(report)
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any("missing required classes" in x for x in result["issues"]))

    def test_wrong_count_type_is_invalid(self):
        report = json.loads(json.dumps(EXAMPLE))
        report["evaluations"][0]["classes"][0]["tp"] = True
        self.assertEqual(MODULE.audit(report)["status"], "invalid")

    def test_zero_normal_images_is_not_evaluable(self):
        report = json.loads(json.dumps(EXAMPLE))
        report["evaluations"][0]["normal_images"] = 0
        report["evaluations"][0].pop("false_positive_normal_images")
        result = MODULE.audit(report)
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(any("not evaluable" in x for x in result["warnings"]))

    def test_zero_prediction_denominator_yields_null_precision(self):
        report = json.loads(json.dumps(EXAMPLE))
        for row in report["evaluations"][0]["classes"]:
            row.update(tp=0, fp=0, fn=row["targets"])
        result = MODULE.audit(report)
        micro = [x["fixed_micro"] for x in result["derived"] if x.get("evaluation_id") == "float-val" and "fixed_micro" in x][0]
        self.assertIsNone(micro["precision"])

    def test_quantization_comparison_requires_same_source_data_protocol_and_split(self):
        report = json.loads(json.dumps(EXAMPLE))
        report["evaluations"][1]["dataset_sha256"] = "e" * 64
        result = MODULE.audit(report)
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(any("quantization_loss_ap50_95_percentage_points" in x for x in result["derived"]))

    def test_bad_hash_is_invalid(self):
        report = json.loads(json.dumps(EXAMPLE))
        report["evaluations"][0]["dataset_sha256"] = "not-a-hash"
        self.assertEqual(MODULE.audit(report)["status"], "invalid")

    def test_quantization_backends_must_be_float_then_int8(self):
        report = json.loads(json.dumps(EXAMPLE))
        report["evaluations"][0]["backend"] = "int8-reference"
        result = MODULE.audit(report)
        self.assertEqual(result["status"], "invalid")
        self.assertFalse(any("quantization_loss_ap50_95_percentage_points" in x for x in result["derived"]))

    def test_cli_refuses_output_that_resolves_to_input(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.json"
            source.write_text(json.dumps(EXAMPLE), encoding="utf-8")
            before = source.read_bytes()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = MODULE.main([str(source), "--output", str(source)])
            self.assertEqual(code, 2)
            self.assertEqual(source.read_bytes(), before)
            self.assertIn("cannot write audit output", json.loads(stdout.getvalue())["issues"][0])

    def test_cli_reports_write_error_as_json(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.json"
            source.write_text(json.dumps(EXAMPLE), encoding="utf-8")
            target_dir = Path(temp) / "output-dir"
            target_dir.mkdir()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = MODULE.main([str(source), "--output", str(target_dir)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
