import importlib.util,json,hashlib,tempfile,unittest
from pathlib import Path
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('adapter',HERE/'adapt_build_materials.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class AdapterTests(unittest.TestCase):
 def test_manifest_and_existing_artifact_match(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);blob=root/'model.bin';blob.write_bytes(b'weights')
   digest=hashlib.sha256(b'weights').hexdigest();(root/'build_manifest.json').write_text(json.dumps({'schema':'v1','model_sha256':digest,'files':{'model.bin':{'sha256':digest,'bytes':7}}}))
   x=m.audit(root);self.assertEqual(x['status'],'checked');self.assertTrue(all(c['status']=='match' for c in x['reports'][0]['checks']))
 def test_missing_declared_artifacts_are_incomplete(self):
  root=HERE.parent/'examples'/'01_identity_normal'/'inputs';x=m.audit(root);self.assertEqual(x['status'],'incomplete');self.assertGreater(len(x['missing_declared_artifacts']),0);self.assertEqual(x['scanned_file_count'],3)
 def test_existing_path_hash_conflict_is_not_hidden(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'model.bin').write_bytes(b'actual');(root/'build_report.json').write_text(json.dumps({'files':{'model.bin':{'sha256':'0'*64}}}))
   x=m.audit(root);self.assertEqual(x['status'],'conflict');self.assertEqual(x['conflicts'][0]['actual_sha256'],hashlib.sha256(b'actual').hexdigest())
 def test_empty_supported_build_report_is_not_green(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'build_report.json').write_text('{}')
   self.assertEqual(m.audit(root)['status'],'unsupported')
 def test_output_inside_scan_root_is_refused(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'build_report.json').write_text(json.dumps({'model_sha256':'1'*64}))
   target=root/'out.json'
   with self.assertRaises(Exception):
    import subprocess,sys
    subprocess.run([sys.executable,'-B',str(HERE/'adapt_build_materials.py'),str(root),'--output',str(target)],check=True,capture_output=True)
   self.assertFalse(target.exists())
 def test_unknown_schema_scan_fails_closed(self):
  with tempfile.TemporaryDirectory() as t:
   (Path(t)/'other.json').write_text('{}')
   with self.assertRaises(ValueError):m.audit(Path(t))
if __name__=='__main__':unittest.main()
