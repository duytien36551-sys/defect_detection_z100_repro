#!/usr/bin/env python3
"""Audit a capture JSON/comparison report and their explicitly named output files."""
import argparse
import hashlib
import re
import json
import sys
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""): h.update(block)
    return h.hexdigest()


def audit(capture_path, comparison_path, observed_path, reference_path, acceptance_path=None):
    capture_file, comparison_file = Path(capture_path), Path(comparison_path)
    observed, reference = Path(observed_path), Path(reference_path)
    paths=[capture_file,comparison_file,observed,reference]
    capture=json.loads(capture_file.read_text(encoding="utf-8-sig"))
    comparison=json.loads(comparison_file.read_text(encoding="utf-8-sig"))
    acceptance_file=Path(acceptance_path) if acceptance_path else None
    acceptance=json.loads(acceptance_file.read_text(encoding="utf-8-sig")) if acceptance_file else None
    if acceptance_file: paths.append(acceptance_file)
    if not isinstance(capture,dict) or not isinstance(comparison,dict): raise ValueError("capture and comparison roots must be JSON objects")
    if acceptance is not None and not isinstance(acceptance,dict): raise ValueError("acceptance root must be a JSON object")
    observed_meta, reference_meta = comparison.get("observed"), comparison.get("reference")
    if not isinstance(observed_meta,dict) or not isinstance(reference_meta,dict): raise ValueError("comparison must contain observed and reference objects")
    elements=capture.get("head_elements")
    if type(elements) is not int or elements<=0: raise ValueError("capture head_elements must be a positive integer")
    contract=comparison.get("scope","")
    if not isinstance(contract,str) or "float32" not in contract or "little-endian" not in contract:
        raise ValueError("comparison scope must explicitly declare little-endian float32")
    logical_bytes=elements*4
    sizes=[observed.stat().st_size,reference.stat().st_size]
    hashes=[sha(observed),sha(reference)]
    declared=[capture.get("actual_heads_sha256"),observed_meta.get("sha256"),reference_meta.get("sha256")]
    if any(not isinstance(x,str) or not re.fullmatch(r"[0-9a-fA-F]{64}",x) for x in declared): raise ValueError("capture/comparison metadata requires valid 64-character SHA-256 values")
    if any(x.lower()!=hashes[0] for x in declared): raise ValueError("observed output hash conflicts with capture/comparison metadata")
    if hashes[0]!=hashes[1]: raise ValueError("observed and reference output bytes differ")
    if sizes!=[logical_bytes,logical_bytes]: raise ValueError("binary byte length does not match head_elements * 4")
    if acceptance_file is not None:
        for key in ("checkpoint_sha256","model_package_sha256"):
            left,right=capture.get(key),acceptance.get(key)
            if not isinstance(left,str) or not re.fullmatch(r"[0-9a-fA-F]{64}",left) or not isinstance(right,str) or not re.fullmatch(r"[0-9a-fA-F]{64}",right): raise ValueError("capture and acceptance require valid identity SHA-256 fields: "+key)
            if left.lower()!=right.lower(): raise ValueError("capture and acceptance identity mismatch: "+key)
    return {"schema_version":1,"status":"historical_output_files_equal","sources":[{"role":"capture_metadata","path":str(paths[0]),"sha256":sha(paths[0])},{"role":"comparison_metadata","path":str(paths[1]),"sha256":sha(paths[1])},{"role":"observed_output","path":str(observed),"sha256":hashes[0],"bytes":sizes[0]},{"role":"reference_output","path":str(reference),"sha256":hashes[1],"bytes":sizes[1]}],"field_mapping":{"elements":"capture.head_elements","observed_sha256":"capture.actual_heads_sha256 and comparison.observed.sha256","reference_sha256":"comparison.reference.sha256","dtype_byte_order":"comparison.scope explicit declaration"},"contract":{"dtype":"float32","byte_order":"little","elements":elements,"logical_bytes":logical_bytes},"byte_equal":True,"reference_updated_after_capture":capture.get("reference_updated_after_capture",comparison.get("reference_updated_after_capture")),
    "reference_revision_status":"declared_true" if capture.get("reference_updated_after_capture",comparison.get("reference_updated_after_capture")) is True else "declared_false" if capture.get("reference_updated_after_capture",comparison.get("reference_updated_after_capture")) is False else "unknown_missing","acceptance_metadata_checked":acceptance_file is not None,"limitations":["Verifies saved files and declarations only; does not establish that the captured output came from a particular hardware run beyond supplied records.","Reference correction after capture limits contemporaneous parity claims.","Byte equality does not assess detection quality."]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("capture_json");p.add_argument("comparison_json");p.add_argument("observed_binary");p.add_argument("reference_binary");p.add_argument("--acceptance-json")
    args=p.parse_args()
    try: result=audit(args.capture_json,args.comparison_json,args.observed_binary,args.reference_binary,args.acceptance_json)
    except (OSError,UnicodeError,json.JSONDecodeError,ValueError,TypeError) as exc:
        print(json.dumps({"schema_version":1,"status":"error","error":str(exc)},ensure_ascii=False,indent=2));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0

if __name__=="__main__":sys.exit(main())
