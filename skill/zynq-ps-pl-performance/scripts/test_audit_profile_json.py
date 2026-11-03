import json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));import audit_profile_json as m
class ProfileAuditTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.p=Path(self.t.name)/"profile.json";self.doc={"status":"ACTUAL_SINGLE_FRAME_OPERATOR_AGGREGATION_NOT_FPS","phase_milliseconds":{"preprocess_ticks":1,"graph_ticks":8,"dequantization_ticks":1,"decode_ticks":1,"total_ticks":11},"nested_counter_milliseconds":{"dma":3,"graph":7},"inputs":{"frame":"0"*64},"timer_hz":100}
  self.p.write_text(json.dumps(self.doc))
 def tearDown(self):self.t.cleanup()
 def test_single_frame_no_p95_and_no_nested_sum(self):
  r=m.audit(self.p);self.assertIsNone(r["p95_ms"]);self.assertIsNone(r["nested_counter_sum_ms"]);self.assertEqual(r["phase_sum_ms"],11);self.assertIsNone(r["unique_input_count"])
 def test_missing_phase_rejected(self):
  d=dict(self.doc);d.pop("phase_milliseconds");self.p.write_text(json.dumps(d))
  with self.assertRaisesRegex(ValueError,"phase_milliseconds"):m.audit(self.p)
 def test_unique_input_count_stays_unknown_without_explicit_field(self):
  d=dict(self.doc);d["status"]="profile";self.p.write_text(json.dumps(d))
  self.assertIsNone(m.audit(self.p)["unique_input_count"])
 def test_invalid_nested_value_rejected(self):
  self.doc["nested_counter_milliseconds"]["dma"]=float("nan");self.p.write_text(json.dumps(self.doc))
  with self.assertRaisesRegex(ValueError,"nested counter"):m.audit(self.p)
if __name__=="__main__":unittest.main()
