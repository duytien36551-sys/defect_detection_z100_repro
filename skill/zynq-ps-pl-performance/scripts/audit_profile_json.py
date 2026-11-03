#!/usr/bin/env python3
"""Normalize known historical single-frame Zynq profiling summaries without summing nested counters."""
import argparse,csv,hashlib,json,math,statistics,sys
from pathlib import Path

def sha(path):
 h=hashlib.sha256()
 with Path(path).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()

def audit(path):
 src=Path(path); d=json.loads(src.read_text(encoding="utf-8-sig"))
 if not isinstance(d,dict):raise ValueError("profile root must be a JSON object")
 phase=d.get("phase_milliseconds")
 if not isinstance(phase,dict):raise ValueError("unsupported profile: phase_milliseconds is absent")
 parsed={}
 for key in ("preprocess_ticks","graph_ticks","dequantization_ticks","decode_ticks","total_ticks"):
  val=phase.get(key)
  if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val) or val<0:raise ValueError("missing/invalid phase field: "+key)
  parsed[key.removesuffix("_ticks")]=float(val)
 total=parsed["total"]
 by_phase=sum(parsed[k] for k in ("preprocess","graph","dequantization","decode"))
 nested=d.get("nested_counter_milliseconds")
 if nested is not None:
  if not isinstance(nested,dict):raise ValueError("nested_counter_milliseconds must be an object")
  for key,val in nested.items():
   if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val) or val<0:raise ValueError("invalid nested counter: "+str(key))
 inputs=d.get("inputs",{})
 if not isinstance(inputs,dict):raise ValueError("inputs must be an object when present")
 validations=d.get("validation_images")
 unique_inputs=1 if type(validations) is int and validations==1 else None
 return {"schema_version":1,"status":"single_frame_profile_normalized","source":{"path":str(src),"sha256_recomputed":sha(src)},"field_mapping":{"phase_ms":"phase_milliseconds.{preprocess_ticks,graph_ticks,dequantization_ticks,decode_ticks,total_ticks} (unit from source schema)","nested_counters":"nested_counter_milliseconds; preserved individually, never summed","declared_input_hashes":"inputs mapping; declarations only, not rehashed unless source file is separately provided","unique_input_count":"single-frame scope; no distinct-request sequence is present"},"identity":{"timer_hz":d.get("timer_hz"),"input_hashes_declared":inputs,"runtime_identity":"not fully established by the profile summary alone"},"sample_count":1,"unique_input_count":unique_inputs,"phase_ms":parsed,"phase_sum_ms":by_phase,"total_minus_phase_sum_ms":total-by_phase,"single_observation_total_ms":total,"p50_ms":None,"p95_ms":None,"nested_counters_ms":nested,"nested_counter_sum_ms":None,"profiling_status":{"sustained_fps_measured":d.get("sustained_fps_measured"),"release_eligible":d.get("release_eligible"),"instrumentation_overhead_established":d.get("instrumentation_overhead_established")},"limitations":["One profile summary observation: no latency distribution or P95. Unique image count is reported only when explicitly present.","Nested counters overlap and must not be added to exclusive phases.","Source input paths and hashes are historical declarations; this tool hashes only the selected JSON file.","Single-frame timing does not establish sustained FPS or end-to-end behavior."]}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("profile_json");a=p.parse_args()
 try:r=audit(a.profile_json)
 except (OSError,UnicodeError,json.JSONDecodeError,ValueError,TypeError) as e:print(json.dumps({"schema_version":1,"status":"error","error":str(e)},ensure_ascii=False,indent=2));return 2
 print(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False));return 0
if __name__=="__main__":sys.exit(main())
