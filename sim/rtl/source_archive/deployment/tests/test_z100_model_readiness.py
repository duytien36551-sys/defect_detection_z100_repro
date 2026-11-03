"""Meaningful unit coverage for the fail-closed offline model audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import z100_model_readiness as readiness  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class Z100ModelReadinessTests(unittest.TestCase):
    def make_run(self, root: Path) -> Path:
        run = root / "runs" / "pin"
        run.mkdir(parents=True)
        data = root / "data.yaml"
        data.write_text("dataset identity\n", encoding="utf-8")
        architecture = root / "yolov8n_scratch9.yaml"
        architecture.write_text("nc: 9\n", encoding="utf-8")
        manifest = root / "split_manifest.json"
        write_json(manifest, [{"split": "train", "id": "train-1"}])
        write_json(root / "plan.json", {
            "epochs_per_model": 3,
            "classes_per_model": 9,
            "initialization": "RANDOM_FROM_ARCHITECTURE_ONLY",
            "pretrained": False,
            "trained_weights_loaded_for_initialization": False,
            "test_used": False,
            "split_manifest": str(manifest),
            "split_manifest_sha256": sha256(manifest),
            "domains": {
                "pin": {
                    "epochs": 3,
                    "names": [f"class-{index}" for index in range(9)],
                    "data": str(data),
                    "data_sha256": sha256(data),
                    "architecture_yaml": str(architecture),
                    "architecture_yaml_sha256": sha256(architecture),
                }
            },
        })
        write_json(root / "status.json", {"state": "completed", "domain": "pin", "completed_epochs": 3})
        (run / "args.yaml").write_text("epochs: 3\n", encoding="utf-8")
        write_json(run / "initialization.json", {
            "initialization": "RANDOM_FROM_ARCHITECTURE_ONLY",
            "pretrained": False,
            "weights_argument_was_none": True,
            "loaded_checkpoint_paths": [],
            "nc": 9,
            "initial_state_sha256": "a" * 64,
        })
        write_json(run / "completion.json", {"completed_epochs": 3, "best_epoch": 2, "test_used": False})
        write_json(run / "progress.json", {"state": "epoch_completed", "epoch": 3, "epochs": 3})
        for epoch, score in ((1, 0.1), (2, 0.3), (3, 0.2)):
            write_json(run / f"epoch_{epoch:03}.json", {
                "epoch": epoch,
                "metrics": {"metrics/mAP50-95(B)": score},
                "test_used": False,
            })
        (run / "results.csv").write_text("epoch,metric\n1,0.1\n2,0.3\n3,0.2\n", encoding="utf-8")
        weights = run / "weights" / "best.pt"
        weights.parent.mkdir(parents=True)
        weights.write_bytes(b"synthetic checkpoint for identity-gate tests")
        return run

    def audit(self, root: Path, target: int = 3) -> dict:
        return readiness.audit_run(route="pin-test-route", run_root=root, domain="pin", target_epochs=target)

    def test_complete_random_initialized_run_is_only_ready_for_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "training"
            self.make_run(root)
            report = self.audit(root)
        self.assertEqual(report["readiness_state"], "ready_for_offline_validation")
        self.assertEqual(report["checkpoint"]["artifact_kind"], "training_candidate")
        self.assertTrue(report["checkpoint"]["stable_snapshot"])
        self.assertFalse(report["selection"]["final_model_selected"])
        self.assertFalse(report["selection"]["selection_allowed_by_this_report"])
        self.assertFalse(report["evaluation"]["package_created"])

    def test_target_must_be_explicitly_consistent_with_plan_and_run_args(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "training"
            self.make_run(root)
            report = self.audit(root, target=100)
        codes = {item["code"] for item in report["blocked_reasons"]}
        self.assertIn("DECLARED_EPOCH_TARGET_MISMATCH", codes)
        self.assertIn("RUN_ARGS_EPOCH_TARGET_MISMATCH", codes)
        self.assertEqual(report["readiness_state"], "blocked")

    def test_missing_completion_record_blocks_otherwise_complete_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "training"
            run = self.make_run(root)
            (run / "completion.json").unlink()
            report = self.audit(root)
        codes = {item["code"] for item in report["blocked_reasons"]}
        self.assertIn("COMPLETION_MISSING_OR_INVALID", codes)
        self.assertEqual(report["readiness_state"], "blocked")

    def test_stale_progress_and_stopped_root_invalidate_stale_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "training"
            run = self.make_run(root)
            write_json(run / "progress.json", {"state": "training", "epoch": 2, "epochs": 3})
            write_json(root / "status.json", {"state": "stopped_by_user", "domain": "pin", "completed_epochs": 3})
            (root / "stop").write_text("user stop\n", encoding="utf-8")
            report = self.audit(root)
        codes = {item["code"] for item in report["blocked_reasons"]}
        self.assertIn("ROOT_STOP_OR_FAILURE_INVALIDATES_RUN", codes)
        self.assertIn("STOP_MARKER_PRESENT", codes)
        self.assertIn("PROGRESS_NOT_AT_COMPLETED_TARGET", codes)
        self.assertIn("COMPLETION_PROGRESS_CONTRADICTION", codes)

    def test_manifest_or_architecture_identity_mismatch_blocks_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "training"
            self.make_run(root)
            (root / "data.yaml").write_text("changed dataset identity\n", encoding="utf-8")
            report = self.audit(root)
        self.assertIn("SOURCE_HASH_MISMATCH", {item["code"] for item in report["blocked_reasons"]})

    def test_test_split_must_be_explicitly_excluded_from_training_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "training"
            run = self.make_run(root)
            write_json(run / "epoch_001.json", {
                "epoch": 1,
                "metrics": {"metrics/mAP50-95(B)": 0.1},
            })
            report = self.audit(root)
        codes = {item["code"] for item in report["blocked_reasons"]}
        self.assertIn("TEST_USAGE_NOT_EXCLUDED_IN_EPOCH_RECORD", codes)

    def test_fixture_checkpoint_path_is_never_admissible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "deployment" / "validation" / "model_packet" / "training"
            self.make_run(root)
            report = self.audit(root)
        codes = {item["code"] for item in report["blocked_reasons"]}
        self.assertIn("FIXTURE_CHECKPOINT_REJECTED", codes)
        self.assertTrue(report["checkpoint"]["is_fixture"])

    def test_report_output_cannot_escape_owned_validation_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                readiness._write_report(Path(temporary) / "outside.json", {"schema_version": 1})

    def test_best_epoch_must_match_validation_history_and_test_stays_unused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "training"
            run = self.make_run(root)
            write_json(run / "completion.json", {"completed_epochs": 3, "best_epoch": 3, "test_used": False})
            write_json(run / "epoch_002.json", {
                "epoch": 2,
                "metrics": {"metrics/mAP50-95(B)": 0.3},
                "test_used": True,
            })
            report = self.audit(root)
        codes = {item["code"] for item in report["blocked_reasons"]}
        self.assertIn("BEST_EPOCH_METRIC_CONTRADICTION", codes)
        self.assertIn("TEST_USAGE_NOT_EXCLUDED_IN_EPOCH_RECORD", codes)


if __name__ == "__main__":
    unittest.main()
