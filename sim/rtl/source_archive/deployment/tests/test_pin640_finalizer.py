"""Safety and acceptance gates for the explicit PIN640 model finalizer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import finalize_pin640 as finalizer  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def metric_report():
    modes = {}
    scores = {"official": (0.60, 0.40), "float": (0.5995, 0.3995), "int8": (0.58, 0.38)}
    for mode, (ap50, ap95) in scores.items():
        modes[mode] = {
            "ap50": ap50,
            "ap50_95": ap95,
            "per_class": {
                name: {"class_id": class_id, "ap50": ap50, "ap50_95": ap95,
                       "ground_truth_count": 1}
                for class_id, name in enumerate(finalizer.PIN_CLASSES)
            },
        }
    return {"domain": "pin", "class_count": 9, "classes": finalizer.PIN_CLASSES,
            "full_validation": True, "images": 800,
            "checkpoint_sha256": "a" * 64, "metrics": modes}


class Pin640FinalizerTests(unittest.TestCase):
    def setUp(self):
        self.original_frozen_root=finalizer.FROZEN_ROOT

    def tearDown(self):
        finalizer.FROZEN_ROOT=self.original_frozen_root

    def test_stripped_checkpoint_keeps_epoch_unknown_and_requires_training_identity(self):
        metadata=dict(epoch=-1,map50_95=.42,stripped=True,classes=finalizer.PIN_CLASSES,
                      train_args=dict(imgsz=640,epochs=300,pretrained=False))
        result=finalizer.verify_checkpoint_metric_identity(metadata,best_epoch=18,
                    best_ap50_95=.42,tied_best_epochs=[18,19])
        self.assertFalse(result['checkpoint_epoch_known'])
        self.assertIsNone(result['checkpoint_epoch_one_based'])
        metadata['train_args']['imgsz']=416
        with self.assertRaisesRegex(ValueError,'training identity'):
            finalizer.verify_checkpoint_metric_identity(metadata,best_epoch=18,best_ap50_95=.42)

    def test_float_lowering_uses_stricter_existing_evaluator_gate(self):
        report=metric_report();report['metrics']['float']['ap50']=.598
        with self.assertRaisesRegex(ValueError,'float.*exceeds'):
            finalizer.validate_accuracy_report(report,checkpoint_sha256='a'*64)
    def test_incomplete_live_run_uses_status_only_and_does_not_hash_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "runs" / "pin"
            run.mkdir(parents=True)
            write_json(root / "status.json", {"state": "running", "stage": "training"})
            write_json(run / "progress.json", {"state": "training", "epoch": 32, "epochs": 300})
            (run / "weights").mkdir()
            (run / "weights" / "best.pt").write_bytes(b"checkpoint changes during training")
            with mock.patch.object(finalizer.readiness, "audit_run", side_effect=AssertionError("must not hash live weights")):
                report = finalizer.audit_or_block(root)
        self.assertEqual(report["readiness_state"], "training_incomplete")
        self.assertFalse(report["checkpoint"]["hashed"])
        self.assertFalse(report["checkpoint"]["copied"])
        self.assertEqual(report["training"]["progress"]["epoch"], 32)
        self.assertFalse(report["evaluation"]["performed"])

    def test_checkpoint_identity_must_match_metric_best_epoch_and_score(self):
        finalizer.verify_checkpoint_metric_identity(
            {"epoch": 17, "map50_95": 0.42},
            best_epoch=18, best_ap50_95=0.42)
        with self.assertRaisesRegex(ValueError, "epoch"):
            finalizer.verify_checkpoint_metric_identity(
                {"epoch": 16, "map50_95": 0.42},
                best_epoch=18, best_ap50_95=0.42)
        with self.assertRaisesRegex(ValueError, "mAP50-95"):
            finalizer.verify_checkpoint_metric_identity(
                {"epoch": 17, "map50_95": 0.39},
                best_epoch=18, best_ap50_95=0.42)

    def test_atomic_freeze_binds_exact_checkpoint_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            finalizer.FROZEN_ROOT = base / "final_models"
            source = base / "best.pt"
            source.write_bytes(b"stable completed checkpoint")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            destination = finalizer.FROZEN_ROOT / "route"
            copied = finalizer._copy_frozen_checkpoint(
                source, destination, expected_sha256=digest,
                frozen_metadata={"route": "unit-test", "best_epoch": 4})
            self.assertEqual(copied["checkpoint_sha256"], digest)
            self.assertEqual(hashlib.sha256((destination / "source.pt").read_bytes()).hexdigest(), digest)
            frozen = json.loads((destination / "frozen_model.json").read_text(encoding="utf-8"))
            self.assertTrue(frozen["immutable"])
            self.assertFalse(frozen["test_predictions_performed"])
            with self.assertRaises(FileExistsError):
                finalizer._copy_frozen_checkpoint(
                    source, destination, expected_sha256=digest,
                    frozen_metadata={"route": "unit-test"})

    def test_frozen_copy_rejects_source_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            finalizer.FROZEN_ROOT = base / "final_models"
            source = base / "best.pt"
            source.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "hash changed"):
                finalizer._copy_frozen_checkpoint(
                    source, finalizer.FROZEN_ROOT / "route", expected_sha256="0" * 64,
                    frozen_metadata={})

    def test_accuracy_gate_requires_full_val_all_classes_and_two_point_losses(self):
        report = metric_report()
        result = finalizer.validate_accuracy_report(report, checkpoint_sha256="a" * 64)
        self.assertTrue(result["passed"])
        self.assertEqual(result["class_metrics_present"]["int8"], 9)
        report["metrics"]["float"]["per_class"].pop(finalizer.PIN_CLASSES[-1])
        with self.assertRaisesRegex(ValueError, "all nine"):
            finalizer.validate_accuracy_report(report, checkpoint_sha256="a" * 64)

    def test_accuracy_gate_rejects_bad_identity_missing_metric_or_excess_loss(self):
        report = metric_report()
        with self.assertRaisesRegex(ValueError, "checkpoint identity"):
            finalizer.validate_accuracy_report(report, checkpoint_sha256="b" * 64)
        report = metric_report()
        report["metrics"]["int8"]["ap50_95"] = 0.379
        with self.assertRaisesRegex(ValueError, "exceeds"):
            finalizer.validate_accuracy_report(report, checkpoint_sha256="a" * 64)
        report = metric_report()
        report["metrics"]["official"]["per_class"][finalizer.PIN_CLASSES[0]]["ap50"] = None
        with self.assertRaisesRegex(ValueError, "missing or non-finite"):
            finalizer.validate_accuracy_report(report, checkpoint_sha256="a" * 64)

    def test_accuracy_gate_rejects_test_prediction_and_partial_validation(self):
        report = metric_report()
        report["test_predictions_performed"] = True
        with self.assertRaisesRegex(ValueError, "Test predictions"):
            finalizer.validate_accuracy_report(report, checkpoint_sha256="a" * 64)
        report = metric_report()
        report["images"] = 799
        with self.assertRaisesRegex(ValueError, "all 800"):
            finalizer.validate_accuracy_report(report, checkpoint_sha256="a" * 64)


if __name__ == "__main__":
    unittest.main()
