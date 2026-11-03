"""Safety tests for capturing a current PIN640 best checkpoint provisionally."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import finalize_pin640 as finalizer  # noqa: E402
import prepare_pin640_provisional as provisional  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def epoch_record(epoch: int, score: float) -> dict:
    return {
        "epoch": epoch,
        "test_used": False,
        "metrics": {"metrics/mAP50-95(B)": round(score, 5)},
        "validation": {
            "domain": "pin", "imgsz": 640, "images": 800, "targets": 20,
            "ap50": min(1.0, score + 0.1), "ap50_95": score,
            "evaluation": {"imgsz": 640},
            "per_class": [], "fixed_point": {"precision": 0.9, "recall": 0.8},
        },
    }


def training_args(run_root: Path) -> dict:
    return {
        "imgsz": 640, "epochs": 300, "batch": 16, "pretrained": False,
        "optimizer": "SGD", "data": str(run_root / "data" / "data.yaml"),
    }


def metadata(run_root: Path, epoch: int, score: float, **overrides) -> dict:
    value = {
        "epoch": epoch,
        "map50_95": score,
        "classes": list(finalizer.PIN_CLASSES),
        "train_args": training_args(run_root),
        "stripped": False,
    }
    value.update(overrides)
    return value


def prepare_run(root: Path, *, score: float = 0.4) -> Path:
    run = root / "runs" / "pin"
    (run / "weights").mkdir(parents=True)
    write_json(root / "status.json", {"state": "running", "stage": "training"})
    write_json(run / "progress.json", {"state": "training", "epoch": 1, "epochs": 300, "batch": 10})
    write_json(run / "epoch_001.json", epoch_record(1, score))
    (run / "weights" / "best.pt").write_bytes(b"checkpoint epoch one")
    (root / "data").mkdir()
    return run


class Pin640ProvisionalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run_root = self.root / "training"
        prepare_run(self.run_root)
        self.manifest = self.root / "canonical_manifest.json"
        self.manifest.write_text("{\"test_used\": false}\n", encoding="utf-8")
        self.manifest_sha = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.model_root = self.root / "deployment" / "candidates" / "pin640" / "provisional_models"
        self.report_root = self.root / "validation" / "board_z100" / "pin640_provisional"
        self.python = Path(sys.executable)

    def tearDown(self):
        self.temporary.cleanup()

    def capture(self, *, candidate_id="candidate", **kwargs):
        with mock.patch.object(provisional, "MANIFEST_SHA256", self.manifest_sha):
            return provisional.capture_provisional(
                self.run_root, python=self.python, candidate_id=candidate_id,
                model_root=self.model_root, report_root=self.report_root,
                manifest_path=self.manifest, retry_delay=0, **kwargs,
            )

    def test_best_selection_uses_highest_full_precision_validation_ap(self):
        records = {
            1: {"score": 0.41234},
            2: {"score": 0.51234},
            3: {"score": 0.51234},
            4: {"score": 0.50001},
        }
        self.assertEqual(provisional.select_best_record(records), (2, 0.51234, [2, 3]))

    def test_copy_race_retries_before_committing_any_candidate(self):
        real_copier = provisional.copy_checkpoint_once
        calls = 0

        def raced_copier(source, destination, *, copy_stream):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise provisional.SnapshotRace("simulated checkpoint replacement during copy")
            return real_copier(source, destination, copy_stream=copy_stream)

        result = self.capture(
            candidate_id="copy_race",
            checkpoint_copier=raced_copier,
            metadata_reader=lambda copied, _python: metadata(self.run_root, 0, 0.4),
        )
        self.assertEqual(calls, 2)
        self.assertEqual(result["race_retries"], 1)
        self.assertTrue(Path(result["checkpoint_path"]).is_file())
        self.assertEqual(result["best_epoch"], 1)

    def test_best_replaced_after_copy_is_detected_before_commit(self):
        real_copier = provisional.copy_checkpoint_once
        calls = 0

        def replace_after_copy(source, destination, *, copy_stream):
            nonlocal calls
            calls += 1
            copied = real_copier(source, destination, copy_stream=copy_stream)
            if calls == 1:
                source.write_bytes(b"new best after old bytes were copied")
            return copied

        result = self.capture(
            candidate_id="post_copy_race",
            checkpoint_copier=replace_after_copy,
            metadata_reader=lambda copied, _python: metadata(self.run_root, 0, 0.4),
        )
        self.assertEqual(result["race_retries"], 1)
        self.assertEqual(Path(result["checkpoint_path"]).read_bytes(),
                         b"new best after old bytes were copied")

    def test_new_record_between_copy_and_review_retries_then_binds_new_checkpoint(self):
        real_copier = provisional.copy_checkpoint_once
        calls = 0

        def record_checkpoint_race(source, destination, *, copy_stream):
            nonlocal calls
            if calls == 0:
                # Model an epoch record becoming visible just before the
                # trainer replaces best.pt for that epoch.
                run = self.run_root / "runs" / "pin"
                write_json(run / "epoch_002.json", epoch_record(2, 0.6))
                write_json(run / "progress.json", {"state": "training", "epoch": 2,
                                                     "epochs": 300, "batch": 3})
            elif calls == 1:
                source.write_bytes(b"checkpoint epoch two")
            calls += 1
            copied = real_copier(source, destination, copy_stream=copy_stream)
            return copied

        metadata_calls = 0

        def inspect_snapshot(copied, _python):
            nonlocal metadata_calls
            metadata_calls += 1
            return metadata(self.run_root, metadata_calls - 1,
                            0.4 if metadata_calls == 1 else 0.6)

        result = self.capture(candidate_id="record_race", checkpoint_copier=record_checkpoint_race,
                              metadata_reader=inspect_snapshot)
        self.assertEqual(result["race_retries"], 1)
        self.assertEqual(result["best_epoch"], 2)
        self.assertEqual(result["best_validation_metrics"]["ap50_95"], 0.6)
        self.assertEqual(hashlib.sha256(Path(result["checkpoint_path"]).read_bytes()).hexdigest(),
                         result["checkpoint_sha256"])
        self.assertEqual(Path(result["checkpoint_path"]).read_bytes(), b"checkpoint epoch two")

    def test_checkpoint_metric_matches_recorded_rounding_and_full_precision_selection(self):
        score = 0.423456
        write_json(self.run_root / "runs" / "pin" / "epoch_001.json", epoch_record(1, score))
        result = self.capture(
            candidate_id="rounded_metric",
            metadata_reader=lambda _p, _py: metadata(self.run_root, 0, round(score, 5)),
        )
        self.assertAlmostEqual(result["best_validation_metrics"]["ap50_95"], score, places=9)
        self.assertEqual(result["checkpoint_record_mAP50_95"], round(score, 5))

    def test_stable_identity_mismatches_fail_closed_without_retry(self):
        mismatches = (
            ("epoch", {"epoch": 1}),
            ("metric", {"map50_95": 0.39}),
            ("classes", {"classes": list(reversed(finalizer.PIN_CLASSES))}),
            ("trainargs", {"train_args": {**training_args(self.run_root), "imgsz": 416}}),
        )
        for name, change in mismatches:
            with self.subTest(name=name):
                base = metadata(self.run_root, 0, 0.4)
                base.update(change)
                with self.assertRaises(ValueError):
                    self.capture(candidate_id=f"bad_{name}", metadata_reader=lambda _p, _py, value=base: value)
                self.assertFalse((self.model_root / f"bad_{name}").exists())

    def test_success_report_is_provisional_and_contains_review_commands_only(self):
        result = self.capture(metadata_reader=lambda _p, _py: metadata(self.run_root, 0, 0.4))
        self.assertFalse(result["release_accepted"])
        self.assertFalse(result["formal_model"])
        self.assertFalse(result["int8_calibration_performed"])
        self.assertFalse(result["full_validation_performed"])
        self.assertFalse(result["test_used"])
        self.assertTrue(result["provisional_workflow_commands"]["not_executed"])
        manifest = json.loads(Path(result["candidate_manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["authorization"], "USER_AUTHORIZED_CURRENT_BEST_PROVISIONAL")
        self.assertIsNone(manifest["checkpoint_source_sha256"])
        self.assertFalse(manifest["checkpoint_source_hash_or_load_performed"])


if __name__ == "__main__":
    unittest.main()
