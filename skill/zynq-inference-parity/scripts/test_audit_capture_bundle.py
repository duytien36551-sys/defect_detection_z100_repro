import hashlib,json,tempfile,unittest,sys
from pathlib import Path
HERE=Path(__file__).parent;sys.path.insert(0,str(HERE));import audit_capture_bundle as m
class CaptureAdapterTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.r=Path(self.t.name);self.a=self.r/"a.bin";self.b=self.r/"b.bin";self.a.write_bytes(bytes(range(8)));self.b.write_bytes(bytes(range(8)))
  h=hashlib.sha256(self.a.read_bytes()).hexdigest();self.c=self.r/"capture.json";self.c.write_text(json.dumps({"head_elements":2,"actual_heads_sha256":h,"checkpoint_sha256":"c"*64,"model_package_sha256":"d"*64,"reference_updated_after_capture":True}))
  self.q=self.r/"comparison.data";self.q.write_text(json.dumps({"scope":"little-endian float32; 2 elements","observed":{"sha256":h},"reference":{"sha256":h}}))
 def tearDown(self):self.t.cleanup()
 def test_real_shape_bundle_contract(self):
  x=m.audit(self.c,self.q,self.a,self.b);self.assertTrue(x["byte_equal"]);self.assertEqual(x["contract"]["logical_bytes"],8);self.assertTrue(x["reference_updated_after_capture"])
 def test_hash_mismatch_rejected(self):
  d=json.loads(self.c.read_text());d["actual_heads_sha256"]="0"*64;self.c.write_text(json.dumps(d))
  with self.assertRaisesRegex(ValueError,"hash conflicts"):m.audit(self.c,self.q,self.a,self.b)
 def test_truncated_binary_rejected(self):
  self.b.write_bytes(b"x")
  with self.assertRaisesRegex(ValueError,"hash conflicts|byte length|bytes differ"):m.audit(self.c,self.q,self.a,self.b)
 def test_missing_acceptance_identity_rejected(self):
  d=json.loads(self.c.read_text());d.pop("checkpoint_sha256");self.c.write_text(json.dumps(d))
  acc=self.r/"acceptance.json";acc.write_text(json.dumps({"model_package_sha256":"d"*64}))
  with self.assertRaisesRegex(ValueError,"valid identity SHA-256"):m.audit(self.c,self.q,self.a,self.b,acc)
 def test_empty_acceptance_is_not_skipped(self):
  acc=self.r/"empty.json";acc.write_text("{}")
  with self.assertRaisesRegex(ValueError,"valid identity SHA-256"):m.audit(self.c,self.q,self.a,self.b,acc)
 def test_reference_revision_missing_is_unknown(self):
  d=json.loads(self.c.read_text());d.pop("reference_updated_after_capture");self.c.write_text(json.dumps(d))
  r=m.audit(self.c,self.q,self.a,self.b);self.assertEqual(r["reference_revision_status"],"unknown_missing")
 def test_malformed_comparison_structure_rejected(self):
  self.q.write_text(json.dumps({"scope":"little-endian float32","observed":[],"reference":{}}))
  with self.assertRaisesRegex(ValueError,"observed and reference objects"):m.audit(self.c,self.q,self.a,self.b)
 def test_implicit_dtype_rejected(self):
  self.q.write_text(json.dumps({"scope":"binary equal","observed":{"sha256":"x"},"reference":{"sha256":"x"}}))
  with self.assertRaisesRegex(ValueError,"explicitly declare"):m.audit(self.c,self.q,self.a,self.b)
if __name__=="__main__":unittest.main()

