import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from audit_identity import audit


class IdentityAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "model.bin").write_bytes(b"model")
        self.manifest = self.root / "manifest.json"

    def tearDown(self):
        self.temp.cleanup()

    def run_manifest(self, obj):
        self.manifest.write_text(json.dumps(obj), encoding="utf-8")
        return audit(self.manifest)

    def test_recomputes_matching_hash(self):
        digest = hashlib.sha256(b"model").hexdigest()
        result, code = self.run_manifest({"schema_version": 1, "artifacts": [{"name": "model", "path": "model.bin", "declared_sha256": digest}]})
        self.assertEqual(code, 0)
        self.assertEqual(result["artifacts"][0]["actual_sha256"], digest)

    def test_required_missing_is_incomplete(self):
        result, code = self.run_manifest({"schema_version": 1, "artifacts": [{"name": "bitstream", "path": "missing.bit"}]})
        self.assertEqual((result["status"], code), ("incomplete", 3))

    def test_mismatch_and_optional_missing(self):
        result, code = self.run_manifest({"schema_version": 1, "artifacts": [
            {"name": "model", "path": "model.bin", "declared_sha256": "0" * 64},
            {"name": "optional", "path": "none", "required": False}]})
        self.assertEqual((result["status"], code), ("mismatch", 1))

    def test_hash_without_declaration_is_hashed_only(self):
        result, code = self.run_manifest({"schema_version": 1, "artifacts": [{"name": "model", "path": "model.bin"}]})
        self.assertEqual(code, 0)
        self.assertEqual(result["artifacts"][0]["status"], "hashed_only")

    def test_rejects_empty_artifact_list_and_duplicate_names(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            self.run_manifest({"schema_version": 1, "artifacts": []})
        with self.assertRaisesRegex(ValueError, "duplicates"):
            self.run_manifest({"schema_version": 1, "artifacts": [
                {"name": "ELF", "path": "model.bin"}, {"name": " elf ", "path": "model.bin"}]})

    def test_rejects_path_escape_and_wrong_types(self):
        for artifact in ({"name": "x", "path": "../secret"}, {"name": "x", "path": ["x"]}, {"name": "x", "path": "x", "required": "yes"}):
            with self.subTest(artifact=artifact), self.assertRaises(ValueError):
                self.run_manifest({"schema_version": 1, "artifacts": [artifact]})


if __name__ == "__main__":
    unittest.main()
