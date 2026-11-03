import importlib.util,json,tempfile,unittest
from pathlib import Path
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('adapter',HERE/'adapt_acceptance_runs.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def row(start,end,status='pass'):
 return {'sequence':1,'task':'pcb','status':status,'started_at_utc':start,'finished_at_utc':end}
def run(root,name,start,end,request):
 (root/name).write_text(json.dumps({'status':'failed' if request['status']=='error' else 'complete','dry_run':False,'started_at_utc':start,'finished_at_utc':end,'planned_count':1,'requests_completed':1,'batch_acceptance_pass':request['status']=='pass','requests':[request]}))
class AdapterTests(unittest.TestCase):
 def test_real_failed_and_diagnostic_runs_keep_distinct_chronology(self):
  root=HERE.parent/'examples'/'08_dma_cross_run_failure'/'inputs';x=m.adapt(root);self.assertEqual(x['status'],'review_required');self.assertEqual(x['run_count'],2)
  ordered=x['chronological_recorded_events'];self.assertEqual(ordered[0]['run_id'],'later_diagnostic_acceptance.json');self.assertIn('failed_run_acceptance.json',{e['run_id'] for e in ordered});self.assertNotIn('root_cause',x);self.assertIn('failed_run.log',x['runs'][0]['companion_materials']);self.assertTrue(x['unassociated_logs'])
 def test_single_run_extracts_timed_requests(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);run(r,'one_acceptance.json','2026-01-01T00:00:00+00:00','2026-01-01T00:00:02+00:00',row('2026-01-01T00:00:00.1+00:00','2026-01-01T00:00:01+00:00'))
   x=m.adapt(r);self.assertEqual(x['status'],'single_run_extracted');self.assertEqual(len(x['runs'][0]['events']),4)
 def test_multiple_runs_never_merge_and_sequence_conflict_flagged(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);run(r,'a_acceptance.json','2026-01-01T00:00:00+00:00','2026-01-01T00:00:02+00:00',row('2026-01-01T00:00:00.1+00:00','2026-01-01T00:00:01+00:00'));run(r,'b_acceptance.json','2026-01-01T00:00:03+00:00','2026-01-01T00:00:04+00:00',row('2026-01-01T00:00:03.1+00:00','2026-01-01T00:00:03.9+00:00'))
   x=m.adapt(r);self.assertEqual(x['run_count'],2);self.assertEqual(len({e['run_id'] for e in x['chronological_recorded_events']}),2)
 def test_summary_count_conflict_requires_review(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);run(r,'x_acceptance.json','2026-01-01T00:00:00+00:00','2026-01-01T00:00:02+00:00',row('2026-01-01T00:00:01+00:00','2026-01-01T00:00:01.5+00:00'))
   p=r/'x_acceptance.json';d=json.loads(p.read_text());d['planned_count']=4;p.write_text(json.dumps(d))
   x=m.adapt(r);self.assertEqual(x['status'],'review_required');self.assertIn('planned_count disagrees',x['problems'][0]['problem'])
 def test_empty_or_untimed_run_requires_review(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);(r/'empty_acceptance.json').write_text(json.dumps({'planned_count':0,'requests_completed':0,'requests':[]}))
   x=m.adapt(r);self.assertEqual(x['status'],'review_required');self.assertTrue(x['problems'])
 def test_output_inside_scan_root_is_refused(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);run(r,'a_acceptance.json','2026-01-01T00:00:00+00:00','2026-01-01T00:00:02+00:00',row('2026-01-01T00:00:01+00:00','2026-01-01T00:00:01.5+00:00'))
   import subprocess,sys
   with self.assertRaises(subprocess.CalledProcessError):subprocess.run([sys.executable,'-B',str(HERE/'adapt_acceptance_runs.py'),str(r),'--output',str(r/'overwrite.json')],check=True,capture_output=True)
   self.assertFalse((r/'overwrite.json').exists())
 def test_naive_timestamp_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);run(r,'x_acceptance.json','2026-01-01T00:00:00','2026-01-01T00:00:02+00:00',row('2026-01-01T00:00:01+00:00','2026-01-01T00:00:01.5+00:00'))
   with self.assertRaises(ValueError):m.adapt(r)
if __name__=='__main__':unittest.main()
