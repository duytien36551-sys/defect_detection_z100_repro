#!/usr/bin/env python3
"""Run packaged static PYNQ examples without PYNQ or hardware."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',required=True,type=Path)
    args=parser.parse_args()
    skill=Path(__file__).resolve().parents[1]
    output=args.out_dir.resolve()
    if output==skill or skill in output.parents:
        parser.error('Use an output directory outside the skill source')
    output.mkdir(parents=True,exist_ok=True)
    cases=[('rgb_tile','metadata_7020','rgb_tile.json','INCOMPLETE',4),('signal_vector','metadata_7020','signal_vector.json','INCOMPLETE',4),('oversized_frame','metadata_7020','oversized_frame.json','BLOCKED',2),('native_migration','metadata_7100','migration_probe.json','BLOCKED',2),('ip_inventory','metadata_7100','inventory.json','INCOMPLETE',4)]
    records=[]
    for label,folder,config,state,exit_code in cases:
        inputs=skill/'examples'/folder
        dest=output/(label+'.json')
        command=[sys.executable,'-B',str(skill/'scripts/audit_overlay.py'),'--hwh',str(inputs/'design_excerpt.hwh'),'--config',str(inputs/config),'--out',str(dest)]
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
        report=json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else {}
        records.append({'case':label,'command':command,'expected_status':state,'actual_status':report.get('status'),'returncode':result.returncode,'passed':report.get('status')==state and result.returncode==exit_code,'report':dest.name,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest() if dest.exists() else None})
    dest=output/'public_notebook.json'
    command=[sys.executable,'-B',str(skill/'scripts/inspect_notebook.py'),'--notebook',str(skill/'examples/public_resizer/resizer_source_only.ipynb'),'--out',str(dest)]
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
    report=json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else {}
    records.append({'case':'public_pynq_notebook','command':command,'returncode':result.returncode,'passed':result.returncode==0 and report.get('saved_outputs_used_as_evidence') is False and any(c['call']=='Overlay' for c in report.get('pynq_related_calls',[])),'report':dest.name})
    summary={'schema':'pynq-skill-static-demo-v1','status':'PASS' if all(r['passed'] for r in records) else 'FAIL','hardware_execution':False,'scope':'Six software demonstrations, not board runtime or output-correctness validation. BLOCKED/INCOMPLETE are intended honest findings.','cases':records}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':summary['status'],'cases':len(records),'summary':str(output/'summary.json'),'hardware_execution':False},ensure_ascii=False))
    return 0 if summary['status']=='PASS' else 1

if __name__=='__main__':
    sys.exit(main())
