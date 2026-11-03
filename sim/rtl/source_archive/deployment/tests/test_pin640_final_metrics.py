"""Validation classes with no predictions must report AP zero, not disappear."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evaluate_pin640_final import summarize_complete


class FinalMetricsTests(unittest.TestCase):
    def test_no_predictions_reports_all_supported_classes_as_zero(self):
        names=[f'PIN_{i}' for i in range(9)]
        result=summarize_complete([dict(tp=[],conf=[],pred_cls=[],target_cls=list(range(9)))],names)
        self.assertEqual(result['ap50'],0)
        self.assertEqual(result['ap50_95'],0)
        self.assertEqual(len(result['per_class']),9)
        self.assertTrue(all(x['ground_truth_count']==1 for x in result['per_class'].values()))

    def test_missing_targets_or_nonfinite_confidence_reject(self):
        with self.assertRaises(ValueError):
            summarize_complete([dict(tp=[],conf=[],pred_cls=[],target_cls=[0])],['PIN_0','PIN_1'])
        with self.assertRaises(ValueError):
            summarize_complete([dict(tp=[[False]*10],conf=[float('nan')],pred_cls=[0],target_cls=[0])],['PIN_0'])

    def test_unpredicted_class_is_zero_when_other_class_has_a_prediction(self):
        result=summarize_complete([dict(tp=[[True]*10],conf=[.9],pred_cls=[0],target_cls=[0,1])],['PIN_0','PIN_1'])
        self.assertEqual(result['per_class']['PIN_1']['ap50'],0)
        self.assertGreater(result['per_class']['PIN_0']['ap50'],.9)


if __name__=='__main__':unittest.main()
