"""Fail-closed guards for correcting vendor report parsers without rewriting evidence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import review_z100_requant_context as context
import review_z100_window_refill as window


class ContextStageReviewTests(unittest.TestCase):
    def test_utilization_labels_are_literal_and_unique(self):
        self.assertEqual(context.used('| Slice LUTs* | 320 | 0 |','Slice LUTs*'),320)
        with self.assertRaisesRegex(ValueError,'Missing/duplicate'):
            context.used('| Slice LUTss | 320 | 0 |','Slice LUTs*')
        with self.assertRaisesRegex(ValueError,'Missing/duplicate'):
            context.used('| DSPs | 0 |\n| DSPs | 1 |','DSPs')

    def assert_rejected(self,module,mutate,message):
        value=json.loads(module.ORIGIN.read_text())
        mutate(value)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'result.json';path.write_text(json.dumps(value),encoding='utf-8')
            with patch.object(module,'ORIGIN',path):
                with self.assertRaisesRegex(ValueError,message):module.review()

    def test_context_rejects_nonzero_vendor_command(self):
        self.assert_rejected(context,lambda v:v['commands'][-1].update(return_code=1),'command failed')

    def test_context_rejects_tampered_artifact(self):
        def mutate(value):
            first=next(iter(value['artifact_sha256']))
            value['artifact_sha256'][first]='0'*64
        self.assert_rejected(context,mutate,'artifact changed')

    def test_window_rejects_unrelated_failure(self):
        self.assert_rejected(window,lambda v:v.update(failure='RuntimeError: actual HDL failure'),'metadata-parser failure')

    def test_window_rejects_source_drift(self):
        def mutate(value):
            first=next(iter(value['source_sha256']))
            value['source_sha256'][first]='0'*64
        self.assert_rejected(window,mutate,'source changed')


if __name__=='__main__':unittest.main()
