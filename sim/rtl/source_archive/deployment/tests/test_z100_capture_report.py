import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('capture',ROOT/'tools/z100_capture_report.py')
capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)


def fixture():
    return dict(schema='z100-frame-capture-v1',provenance='synthetic',part='xc7z100ffg900-2',batch=1,
        artifacts_sha256={k:'0'*64 for k in ('hardware','firmware','model','classes')},
        window_start_ns=1_000_000_000,window_end_ns=2_000_000_000,queue_bound=8,
        offered_frames=30,dropped_frames=0,frames=[dict(id=str(i),submitted_ns=1_000_000_000+i*30_000_000,
        completed_ns=1_100_000_000+i*30_000_000,status='ok',warmup=False,queue_depth=4) for i in range(30)])


class CaptureTests(unittest.TestCase):
    def test_throughput_not_latency_reciprocal(self):
        r=capture.analyze(fixture());self.assertEqual(r['steady_window_fps'],30)
        self.assertEqual(r['end_to_end_ms_p95'],100)
        self.assertTrue(r['numerical_30fps_no_drop_condition']);self.assertFalse(r['release_eligible'])

    def test_duplicate_rejected(self):
        f=fixture();f['frames'][1]['id']='0'
        with self.assertRaisesRegex(ValueError,'duplicate'):capture.analyze(f)

    def test_lost_frame_accounting_rejected(self):
        f=fixture();f['offered_frames']=31
        with self.assertRaisesRegex(ValueError,'accounting'):capture.analyze(f)

    def test_drop_and_failure_do_not_pass(self):
        f=fixture();f['offered_frames']=31;f['dropped_frames']=1
        self.assertFalse(capture.analyze(f)['numerical_30fps_no_drop_condition'])
        f=fixture();f['frames'][0]['status']='failed'
        self.assertFalse(capture.analyze(f)['numerical_30fps_no_drop_condition'])

    def test_warmup_and_bad_timestamps_rejected(self):
        f=fixture();f['frames'][0]['warmup']=True
        with self.assertRaisesRegex(ValueError,'warmup'):capture.analyze(f)
        f=fixture();f['frames'][0]['completed_ns']=0
        with self.assertRaisesRegex(ValueError,'precedes'):capture.analyze(f)

    def test_queue_and_identity_rejected(self):
        f=fixture();f['frames'][0]['queue_depth']=9
        with self.assertRaisesRegex(ValueError,'queue'):capture.analyze(f)
        f=fixture();f['artifacts_sha256']['model']='fixture'
        with self.assertRaisesRegex(ValueError,'identity'):capture.analyze(f)

    def test_boolean_batch_rejected(self):
        f=fixture();f['batch']=True
        with self.assertRaisesRegex(ValueError,'batch'):capture.analyze(f)


if __name__=='__main__':unittest.main()
