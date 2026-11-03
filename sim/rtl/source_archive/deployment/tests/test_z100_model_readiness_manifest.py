import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

from tools import z100_model_readiness_manifest as adapter


PIN_NAMES = [
    "PIN_破损", "PIN_裂痕", "PIN_击穿", "PIN_薄膜破损", "PIN_电极缺失",
    "PIN_异物", "PIN_有机物污染", "PIN_部分缺失", "PIN_冗余",
]
PCB_NAMES = ["PCB_SH", "PCB_SP", "PCB_SC", "PCB_OP", "PCB_MB", "PCB_HB", "PCB_CS", "PCB_CFO", "PCB_BMFO"]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class Z100ModelReadinessManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"
        self.repo = self.root
        self.output_parent = self.root / "validation" / "board_z100" / "model_readiness_completion"
        self.output_parent.mkdir(parents=True)
        (self.repo / "deployment").mkdir()
        (self.repo / "deployment" / "quantize.py").write_text(
            "DOMAIN_CLASS_IDS = {'pcb': tuple(range(9)), 'pin': tuple(range(9, 18)), 'joint18': tuple(range(18))}\n",
            encoding="utf-8",
        )
        self.class_map = self.root / "examples" / "interface_manifest.json"
        self.class_map.parent.mkdir()
        self.class_names = PCB_NAMES + PIN_NAMES
        self.class_map.write_text(
            json.dumps({"class_names": self.class_names, "purpose": "class identity test fixture"}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.run_root = self.root / "external" / adapter.ROUTE_DIR
        self.data_dir = self.run_root / "data"
        (self.data_dir / "images").mkdir(parents=True)
        (self.data_dir / "labels").mkdir()
        self.source_root = self.root / "external" / "sources"
        self.source_root.mkdir()
        (self.run_root.parent / "augment_pin_8000_20261021.py").write_text(
            "label.write_text(' '.join([*(f'{v:.10f}' for v in box)]))\n", encoding="utf-8"
        )
        self.rows = []
        image_lists = {"train": [], "val": [], "test": []}
        for index, split in enumerate(("train", "val", "test")):
            image_bytes = f"image bytes {index}".encode()
            image_sha = _sha(image_bytes)
            image_path = self.data_dir / "images" / f"{split}.txt"  # replaced after split dirs are created
            image_dir = self.data_dir / "images" / split
            label_dir = self.data_dir / "labels" / split
            image_dir.mkdir()
            label_dir.mkdir()
            image_path = image_dir / f"{image_sha}.jpg"
            label_path = label_dir / f"{image_sha}.txt"
            image_path.write_bytes(image_bytes)
            label_content = f"{index} 0.5 0.5 0.2 0.2\n".encode()
            label_path.write_bytes(label_content)
            source_content = f"source bytes {index}".encode()
            source_path = self.source_root / f"source-{index}.bin"
            source_path.write_bytes(source_content)
            self.rows.append({
                "split": split,
                "group_id": f"group-{index}",
                "image": str(image_path),
                "label": str(label_path),
                "source": str(source_path),
                "source_sha256": _sha(source_content),
                "label_sha256": _sha(label_content),
                "role": "original",
            })
            image_lists[split].append(str(image_path))

        data_doc = {
            "path": str(self.data_dir),
            "train": "train.txt",
            "val": "val.txt",
            "test": "test.txt",
            "names": PIN_NAMES,
        }
        self.data_yaml = self.data_dir / "data.yaml"
        self.data_yaml.write_text(json.dumps(data_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        for split, paths in image_lists.items():
            (self.data_dir / f"{split}.txt").write_text("\n".join(paths) + "\n", encoding="utf-8")
        self.split_path = self.run_root / "split_manifest.json"
        self.report_path = self.run_root / "split_report.json"
        self.plan_path = self.run_root / "plan.json"
        self._write_route_documents()
        (self.run_root / "status.json").write_text(json.dumps({"state": "running"}), encoding="utf-8")
        self.loader_patch = patch.object(adapter, "_validate_official_manifest", side_effect=self._fake_loader_check)
        self.loader_patch.start()
        self.addCleanup(self.loader_patch.stop)

    def _write_route_documents(self):
        self.split_path.write_text(json.dumps(self.rows, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report_path.write_text(json.dumps({
            "group_overlap": 0,
            "exact_file_overlap": 0,
            "sealed_test_read": False,
        }), encoding="utf-8")
        plan = {
            "epochs_per_model": 300,
            "imgsz": 640,
            "split_manifest_sha256": _sha(self.split_path.read_bytes()),
            "domains": {
                "pin": {
                    "epochs": 300,
                    "data": str(self.data_yaml),
                    "data_sha256": _sha(self.data_yaml.read_bytes()),
                    "names": PIN_NAMES,
                },
            },
        }
        self.plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    def _fake_loader_check(self, manifest_path, expected_manifest=None):
        document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(document["class_names"], self.class_names)
        records = document["records"]
        counts = {split: sum(row["split"] == split for row in records) for split in ("train", "val", "test")}
        box_count = 0
        for record in records:
            self.assertEqual(record["domain"], "pin")
            for box in record["boxes"]:
                self.assertIn(box["class_id"], range(9, 18))
                x1, y1, x2, y2 = box["xyxy"]
                self.assertTrue(0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1)
                box_count += 1
        return {"passed": True, "record_count": len(records), "box_count": box_count,
                "split_counts": counts, "loader": "test-stub", "all_image_hashes_verified": True,
                "model_evaluation_performed": False}

    def _convert(self, coordinate_policy="strict"):
        return adapter.convert_manifest(
            route=adapter.ROUTE_ID,
            run_root=self.run_root,
            source_roots=[self.source_root],
            class_map_path=self.class_map,
            output_parent=self.output_parent,
            repo_root=self.repo,
            coordinate_policy=coordinate_policy,
        )

    def test_converts_with_identity_split_order_and_no_selection_claim(self):
        with patch.object(adapter, "EXPECTED_COUNTS", {"train": 1, "val": 1, "test": 1}):
            result = self._convert()
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        provenance = json.loads(Path(result["provenance"]).read_text(encoding="utf-8"))
        records = manifest["records"]
        self.assertEqual([row["split"] for row in records], ["train", "val", "test"])
        self.assertEqual([row["group_id"] for row in records], [row["group_id"] for row in self.rows])
        self.assertEqual([row["role"] for row in records], [row["role"] for row in self.rows])
        self.assertEqual([row["source_sha256"] for row in records], [row["source_sha256"] for row in self.rows])
        self.assertEqual([row["domain"] for row in records], ["pin"] * 3)
        self.assertEqual(records[0]["boxes"], [{"class_id": 9, "xyxy": [0.4, 0.4, 0.6, 0.6]}])
        audit = json.loads(Path(result["source_label_audit"]).read_text(encoding="utf-8"))
        self.assertEqual(audit["records"][0]["lines"][0]["original_tokens"], ["0", "0.5", "0.5", "0.2", "0.2"])
        self.assertFalse(provenance["route_selected"])
        self.assertFalse(provenance["checkpoint_accepted"])
        self.assertFalse(provenance["model_evaluation_performed"])
        self.assertFalse(provenance["test_tuning_performed"])
        self.assertEqual(provenance["training_imgsz"], 640)
        self.assertEqual(provenance["deployment_input_size"], 416)
        self.assertEqual(provenance["input_resolution_compatibility"], "unresolved_training_640_deployment_416")
        self.assertEqual(provenance["strict_loader_validation"]["record_count"], 3)
        self.assertTrue(provenance["test_labels_read_for_integrity"])
        self.assertFalse(provenance["test_predictions_or_metrics_performed"])

    def test_rejects_unverified_class_order(self):
        incorrect = list(self.class_names)
        incorrect[9], incorrect[10] = incorrect[10], incorrect[9]
        self.class_map.write_text(json.dumps({"class_names": incorrect}), encoding="utf-8")
        with patch.object(adapter, "EXPECTED_COUNTS", {"train": 1, "val": 1, "test": 1}):
            with self.assertRaisesRegex(adapter.ManifestError, "Ordered PIN names disagree"):
                self._convert()
        self.assertFalse((self.output_parent / adapter.FINAL_DIR_NAME).exists())

    def test_rejects_group_leakage_across_splits(self):
        self.rows[1]["group_id"] = self.rows[0]["group_id"]
        self._write_route_documents()
        with patch.object(adapter, "EXPECTED_COUNTS", {"train": 1, "val": 1, "test": 1}):
            with self.assertRaisesRegex(adapter.ManifestError, "group_id crosses splits"):
                self._convert()

    def test_rejects_source_path_escape(self):
        outsider = self.root / "outside-source.bin"
        outsider.write_bytes(b"outside")
        self.rows[0]["source"] = str(outsider)
        self.rows[0]["source_sha256"] = _sha(outsider.read_bytes())
        self._write_route_documents()
        with patch.object(adapter, "EXPECTED_COUNTS", {"train": 1, "val": 1, "test": 1}):
            with self.assertRaisesRegex(adapter.ManifestError, "outside every explicit source root"):
                self._convert()

    def test_rejects_duplicate_image_record(self):
        self.rows[1]["split"] = "train"
        self.rows[1]["image"] = self.rows[0]["image"]
        self.rows[1]["label"] = self.rows[0]["label"]
        self.rows[1]["label_sha256"] = self.rows[0]["label_sha256"]
        self._write_route_documents()
        with patch.object(adapter, "EXPECTED_COUNTS", {"train": 2, "val": 0, "test": 1}):
            with self.assertRaisesRegex(adapter.ManifestError, "Duplicate image or local-label path"):
                self._convert()

    def test_rejects_wrong_source_digest(self):
        self.rows[0]["source_sha256"] = "0" * 64
        self._write_route_documents()
        with patch.object(adapter, "EXPECTED_COUNTS", {"train": 1, "val": 1, "test": 1}):
            with self.assertRaisesRegex(adapter.ManifestError, "SHA-256 mismatch for source image provenance"):
                self._convert()

    def test_requires_explicit_supported_route(self):
        with self.assertRaisesRegex(adapter.ManifestError, "Unsupported route"):
            adapter._preflight(
                route="pin",
                run_root=self.run_root,
                source_roots=[self.source_root],
                class_map_path=self.class_map,
                repo_root=self.repo,
                coordinate_policy="strict",
            )

    def test_default_strict_policy_rejects_excursion_and_publishes_nothing(self):
        with patch.object(adapter, "EXPECTED_COUNTS", {"train": 1, "val": 1, "test": 1}):
            original = self.rows[0]["label"]
            Path(original).write_text("0 0.0000000000 0.5000000000 0.0000000001 0.2000000000\n")
            self.rows[0]["label_sha256"] = _sha(Path(original).read_bytes())
            self._write_route_documents()
            with self.assertRaisesRegex(adapter.ManifestError, "Invalid normalized box"):
                self._convert()
        self.assertFalse((self.output_parent / adapter.FINAL_DIR_NAME).exists())

    def test_decimal_policy_clips_all_four_sides_with_exact_decimal_math(self):
        cases = [
            ("0 0.0000000000 0.5000000000 0.0000000001 0.2000000000", ["x_min"]),
            ("0 0.9999999999 0.5000000000 0.0000000003 0.2000000000", ["x_max"]),
            ("0 0.5000000000 0.0000000000 0.2000000000 0.0000000001", ["y_min"]),
            ("0 0.5000000000 0.9999999999 0.2000000000 0.0000000003", ["y_max"]),
        ]
        for text, expected_edges in cases:
            with self.subTest(edge=expected_edges[0]):
                boxes, audit = adapter._decimal_label_boxes(
                    text, path_description="synthetic.txt", coordinate_policy="decimal10-rounding-v1"
                )
                self.assertEqual(audit[0]["clipped_edges"], expected_edges)
                self.assertEqual(boxes[0]["xyxy"][0 if expected_edges[0] == "x_min" else 1 if expected_edges[0] == "y_min" else 2 if expected_edges[0] == "x_max" else 3],
                                 0.0 if expected_edges[0].endswith("min") else 1.0)
                for index, edge in enumerate(("x_min", "y_min", "x_max", "y_max")):
                    if edge not in expected_edges:
                        self.assertEqual(audit[0]["canonical_xyxy_decimal"][index],
                                         audit[0]["source_xyxy_decimal"][index])
        valid_boxes, valid_audit = adapter._decimal_label_boxes(
            "0 0.5000000000 0.5000000000 0.2000000000 0.2000000000",
            path_description="synthetic.txt", coordinate_policy="decimal10-rounding-v1"
        )
        self.assertEqual(valid_audit[0]["clipped_edges"], [])
        self.assertEqual(valid_audit[0]["source_xyxy_decimal"], valid_audit[0]["canonical_xyxy_decimal"])

    def test_rounding_bound_exact_and_exceed(self):
        # This helper-level check covers the conservative theoretical bound.
        # Decimal10 source tokens have a 5e-11 corner grid, so an outside corner
        # can reach 5e-11 and then next jump to 1e-10, but not exactly 7.5e-11.
        exact, clipped = adapter._clip_rounded_edge(
            Decimal("-0.000000000075"), lower=True, coordinate_policy="decimal10-rounding-v1"
        )
        self.assertEqual(exact, Decimal(0))
        self.assertTrue(clipped)
        with self.assertRaisesRegex(adapter.ManifestError, "Rounding excursion exceeds"):
            adapter._clip_rounded_edge(
                Decimal("-0.0000000000750000001"), lower=True, coordinate_policy="decimal10-rounding-v1"
            )
        with self.assertRaisesRegex(adapter.ManifestError, "Rounding excursion exceeds"):
            adapter._decimal_label_boxes(
                "0 0.0000000000 0.5 0.0000000002 0.2", path_description="synthetic.txt",
                coordinate_policy="decimal10-rounding-v1"
            )

    def test_decimal_policy_rejects_nonfinite_zero_area_bad_class_and_large_excursion(self):
        invalid = [
            "0 NaN 0.5 0.2 0.2",
            "0 Infinity 0.5 0.2 0.2",
            "0 0.5 0.5 0 0.2",
            "0 1.0000000001 0.5 0.2 0.2",
            "0 0.5 0.5 1.0000000001 0.2",
            "9 0.5 0.5 0.2 0.2",
            "0 0.0000000000 0.5 0.0000000004 0.2",
        ]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(adapter.ManifestError):
                adapter._decimal_label_boxes(
                    text, path_description="synthetic.txt", coordinate_policy="decimal10-rounding-v1"
                )

    def test_decimal_policy_rejects_clipped_line_without_ten_decimal_tokens(self):
        with self.assertRaisesRegex(adapter.ManifestError, "fixed-10-decimal"):
            adapter._decimal_label_boxes(
                "0 0.0 0.5 0.0000000001 0.2", path_description="synthetic.txt",
                coordinate_policy="decimal10-rounding-v1"
            )

    def test_loader_failure_keeps_output_atomic(self):
        with patch.object(adapter, "EXPECTED_COUNTS", {"train": 1, "val": 1, "test": 1}), \
             patch.object(adapter, "_validate_official_manifest", side_effect=adapter.ManifestError("loader blocked")):
            with self.assertRaisesRegex(adapter.ManifestError, "loader blocked"):
                self._convert()
        self.assertFalse((self.output_parent / adapter.FINAL_DIR_NAME).exists())


if __name__ == "__main__":
    unittest.main()
