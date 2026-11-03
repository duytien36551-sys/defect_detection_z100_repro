import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import z100_model_readiness_manifest as adapter
from tools import z100_model_readiness_manifest_verify as verifier


PIN_NAMES = [
    "PIN_破损", "PIN_裂痕", "PIN_击穿", "PIN_薄膜破损", "PIN_电极缺失",
    "PIN_异物", "PIN_有机物污染", "PIN_部分缺失", "PIN_冗余",
]
PCB_NAMES = ["PCB_SH", "PCB_SP", "PCB_SC", "PCB_OP", "PCB_MB", "PCB_HB", "PCB_CS", "PCB_CFO", "PCB_BMFO"]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class Z100ModelReadinessManifestVerifyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"
        self.validation_root = self.root / "validation" / "board_z100" / "model_readiness_completion"
        self.validation_root.mkdir(parents=True)
        (self.root / "deployment").mkdir()
        (self.root / "deployment" / "quantize.py").write_text(
            "DOMAIN_CLASS_IDS = {'pcb': tuple(range(9)), 'pin': tuple(range(9, 18)), 'joint18': tuple(range(18))}\n",
            encoding="utf-8",
        )
        self.class_names = PCB_NAMES + PIN_NAMES
        self.class_map = self.root / "examples" / "interface_manifest.json"
        self.class_map.parent.mkdir()
        self.class_map.write_text(json.dumps({"class_names": self.class_names}, ensure_ascii=False), encoding="utf-8")
        self.run_root = self.root / "external" / adapter.ROUTE_DIR
        self.data_dir = self.run_root / "data"
        self.rows = []
        images_by_split = {split: [] for split in ("train", "val", "test")}
        source_root = self.root / "external" / "sources"
        source_root.mkdir(parents=True)
        for index, split in enumerate(("train", "val", "test")):
            image_bytes = f"image {index}".encode()
            image_sha = _sha(image_bytes)
            image_dir = self.data_dir / "images" / split
            label_dir = self.data_dir / "labels" / split
            image_dir.mkdir(parents=True)
            label_dir.mkdir(parents=True)
            image = image_dir / f"{image_sha}.jpg"
            label = label_dir / f"{image_sha}.txt"
            image.write_bytes(image_bytes)
            label_content = f"{index} 0.5 0.5 0.2 0.2\n".encode()
            label.write_bytes(label_content)
            source_bytes = f"source {index}".encode()
            source = source_root / f"source-{index}.bin"
            source.write_bytes(source_bytes)
            self.rows.append({
                "split": split, "group_id": f"group-{index}", "image": str(image), "label": str(label),
                "source": str(source), "source_sha256": _sha(source_bytes),
                "label_sha256": _sha(label_content), "role": "original",
            })
            images_by_split[split].append(str(image))
        data_doc = {"path": str(self.data_dir), "train": "train.txt", "val": "val.txt", "test": "test.txt",
                    "names": PIN_NAMES}
        self.data_yaml = self.data_dir / "data.yaml"
        self.data_yaml.write_text(json.dumps(data_doc, ensure_ascii=False), encoding="utf-8")
        for split, paths in images_by_split.items():
            (self.data_dir / f"{split}.txt").write_text("\n".join(paths) + "\n", encoding="utf-8")
        self.split_path = self.run_root / "split_manifest.json"
        self.split_path.write_text(json.dumps(self.rows, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report_path = self.run_root / "split_report.json"
        self.report_path.write_text(json.dumps({"group_overlap": 0, "exact_file_overlap": 0,
                                               "sealed_test_read": False}), encoding="utf-8")
        (self.run_root / "prepare.py").write_text("# source-preserving prepare\n", encoding="utf-8")
        (self.run_root.parent / "augment_pin_8000_20261021.py").write_text(
            "label.write_text(' '.join([*(f'{v:.10f}' for v in box)]))\n", encoding="utf-8"
        )
        plan = {"epochs_per_model": 300, "imgsz": 640, "split_manifest_sha256": _sha(self.split_path.read_bytes()),
                "domains": {"pin": {"epochs": 300, "data": str(self.data_yaml),
                                     "data_sha256": _sha(self.data_yaml.read_bytes()), "names": PIN_NAMES}}}
        (self.run_root / "plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        (self.run_root / "status.json").write_text(json.dumps({"state": "running"}), encoding="utf-8")

        with patch.object(adapter, "EXPECTED_COUNTS", {"train": 1, "val": 1, "test": 1}), \
             patch.object(adapter, "_validate_official_manifest", side_effect=self._fake_strict_loader):
            result = adapter.convert_manifest(
                route=adapter.ROUTE_ID, run_root=self.run_root, source_roots=[source_root],
                class_map_path=self.class_map, output_parent=self.validation_root, repo_root=self.root,
            )
        self.manifest_path = Path(result["manifest"])
        self.audit_path = Path(result["source_label_audit"])
        self.provenance_path = Path(result["provenance"])

    def _fake_strict_loader(self, manifest_path, expected_manifest=None):
        document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        records = document["records"]
        counts = {split: sum(row["split"] == split for row in records) for split in ("train", "val", "test")}
        return {"passed": True, "record_count": len(records), "box_count": sum(len(row["boxes"]) for row in records),
                "split_counts": counts, "loader": "test-stub", "all_image_hashes_verified": True,
                "model_evaluation_performed": False}

    def _verify(self):
        return verifier.verify_candidate(
            self.manifest_path, self.audit_path, self.provenance_path,
            expected_counts={"train": 1, "val": 1, "test": 1}, allowed_output_root=self.validation_root,
        )

    def _fake_verify_loader(self, manifest_path):
        document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        return ([{"id": row["id"], "domain": row["domain"], "split": row["split"],
                  "image_path": Path(row["image"]), "boxes": row["boxes"]}
                 for row in document["records"]], document["class_names"])

    def _rewrite_provenance_hash(self, key, path):
        provenance = json.loads(self.provenance_path.read_text(encoding="utf-8"))
        provenance[key] = _sha(path.read_bytes())
        self.provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_replays_source_transform_and_validates_all_identity(self):
        with patch.object(verifier, "_load_strict_records", side_effect=self._fake_verify_loader):
            result = self._verify()
        self.assertTrue(result["passed"])
        self.assertEqual(result["records"], 3)
        self.assertEqual(result["boxes"], 3)
        self.assertEqual(result["split_counts"], {"train": 1, "val": 1, "test": 1})
        self.assertTrue(result["test_read_for_integrity_only"])
        self.assertFalse(result["model_evaluation_performed"])

    def test_rejects_manifest_transform_tampering_even_if_digest_is_rewritten(self):
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["records"][0]["boxes"][0]["xyxy"][2] = 0.7
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self._rewrite_provenance_hash("canonical_manifest_sha256", self.manifest_path)
        with patch.object(verifier, "_load_strict_records", side_effect=self._fake_verify_loader):
            with self.assertRaisesRegex(verifier.VerificationError, "Coordinate transform changed"):
                self._verify()

    def test_rejects_audit_tampering_even_if_digest_is_rewritten(self):
        audit = json.loads(self.audit_path.read_text(encoding="utf-8"))
        audit["records"][0]["lines"][0]["original_tokens"][1] = "0.4"
        self.audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        self._rewrite_provenance_hash("source_label_audit_sha256", self.audit_path)
        with patch.object(verifier, "_load_strict_records", side_effect=self._fake_verify_loader):
            with self.assertRaisesRegex(verifier.VerificationError, "line audit does not reproduce"):
                self._verify()

    def test_rejects_original_label_tampering(self):
        label = Path(self.rows[0]["label"])
        label.write_text(label.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with patch.object(verifier, "_load_strict_records", side_effect=self._fake_verify_loader):
            with self.assertRaisesRegex(verifier.VerificationError, "SHA-256 mismatch for route source label"):
                self._verify()


if __name__ == "__main__":
    unittest.main()
