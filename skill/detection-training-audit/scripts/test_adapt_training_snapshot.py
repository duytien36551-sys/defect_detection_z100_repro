import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
FIXTURE = SKILL / "examples" / "09_training_finish200" / "inputs"
spec = importlib.util.spec_from_file_location("adapt_training_snapshot", HERE / "adapt_training_snapshot.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TrainingSnapshotAdapterTests(unittest.TestCase):
    def test_real_archived_snapshot_adapts_without_reselecting(self):
        result = module.adapt(
            FIXTURE / "final_report.json", FIXTURE / "final_acceptance.json",
            FIXTURE / "split_manifest.json", FIXTURE / "results.csv")
        self.assertEqual(result["status"], "computed_with_limitations")
        self.assertTrue(result["selection_and_integrity_checks"]["csv_max_agrees_with_declared_best"])
        self.assertEqual(result["selection_and_integrity_checks"]["declared_best_epoch"], 200)
        self.assertEqual(result["quality_report_audit"]["status"], "incomplete")
        self.assertEqual(len(result["quality_report_input"]["evaluations"][0]["classes"]), 9)
        self.assertIn("normal_images=0", " ".join(result["missing_or_unverified"]))

    def test_best_epoch_conflict_is_reported_not_reselected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = json.loads((FIXTURE / "final_report.json").read_text(encoding="utf-8"))
            acceptance = json.loads((FIXTURE / "final_acceptance.json").read_text(encoding="utf-8"))
            report["completion"]["best_epoch"] = 199
            acceptance["best_epoch"] = 199
            (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
            (root / "acceptance.json").write_text(json.dumps(acceptance), encoding="utf-8")
            result = module.adapt(root / "report.json", root / "acceptance.json",
                                  FIXTURE / "split_manifest.json", FIXTURE / "results.csv")
            self.assertEqual(result["status"], "source_consistency_issue")
            self.assertIn("csv_max_agrees_with_declared_best", result["issues"])
            self.assertEqual(result["selection_and_integrity_checks"]["declared_best_epoch"], 199)

    def test_malformed_per_class_metrics_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = json.loads((FIXTURE / "final_report.json").read_text(encoding="utf-8"))
            report["validation"]["per_class"][0]["tp"] = -1
            altered = root / "report.json"
            altered.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nonnegative integer"):
                module.adapt(altered, FIXTURE / "final_acceptance.json",
                             FIXTURE / "split_manifest.json", FIXTURE / "results.csv")

    def test_missing_selection_rule_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = json.loads((FIXTURE / "final_report.json").read_text(encoding="utf-8"))
            report["completion"].pop("best_selection")
            altered = root / "report.json"
            altered.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen selection rule"):
                module.adapt(altered, FIXTURE / "final_acceptance.json",
                             FIXTURE / "split_manifest.json", FIXTURE / "results.csv")

    def test_cli_refuses_to_overwrite_any_input(self):
        report = FIXTURE / "final_report.json"
        before = hashlib.sha256(report.read_bytes()).hexdigest()
        result = subprocess.run([
            sys.executable, "-B", str(HERE / "adapt_training_snapshot.py"),
            "--report", str(report), "--acceptance", str(FIXTURE / "final_acceptance.json"),
            "--split-manifest", str(FIXTURE / "split_manifest.json"),
            "--results-csv", str(FIXTURE / "results.csv"), "--output", str(report)],
            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must not overwrite", result.stdout)
        self.assertEqual(hashlib.sha256(report.read_bytes()).hexdigest(), before)

    def test_corrupt_or_noncontiguous_csv_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            csv_path = Path(temp) / "results.csv"
            csv_path.write_text("epoch,metrics/mAP50-95(B)\n1,0.5\n3,0.6\n", encoding="utf-8")
            result = module.adapt(FIXTURE / "final_report.json", FIXTURE / "final_acceptance.json",
                                  FIXTURE / "split_manifest.json", csv_path)
            self.assertEqual(result["status"], "source_consistency_issue")
            self.assertFalse(result["selection_and_integrity_checks"]["epochs_contiguous_1_to_n"])


if __name__ == "__main__":
    unittest.main()
