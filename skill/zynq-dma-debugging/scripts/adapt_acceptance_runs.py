#!/usr/bin/env python3
"""Extract recorded per-request events from this project's acceptance JSON files."""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,re,sys
from pathlib import Path

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stamp(raw,where):
 if not isinstance(raw,str):raise ValueError(where+' missing ISO timestamp')
 try:v=dt.datetime.fromisoformat(raw.replace('Z','+00:00'))
 except ValueError:raise ValueError(where+' invalid ISO timestamp')
 if v.tzinfo is None:raise ValueError(where+' timestamp must carry timezone')
 return v

def adapt(root):
 root=root.resolve()
 if not root.is_dir():raise ValueError('root must be a directory')
 files=sorted(root.rglob('*_acceptance.json'))
 if not files:raise ValueError('no *_acceptance.json found')
 all_runs=[]; global_events=[]; problems=[]; associated_paths=set()
 for p in files:
  try:d=json.loads(p.read_text(encoding='utf-8-sig'))
  except (UnicodeError,json.JSONDecodeError) as exc:raise ValueError('invalid JSON {}: {}'.format(p,exc))
  if not isinstance(d,dict) or not isinstance(d.get('requests'),list):raise ValueError('expected acceptance object with requests array: '+str(p))
  rel=p.relative_to(root).as_posix(); run_id=rel
  events=[]
  for key,name in [('started_at_utc','run_started'),('identity_probe_at_utc','identity_probe'),('updated_at_utc','status_updated'),('finished_at_utc','run_finished')]:
   if d.get(key) is not None:
    t=stamp(d[key],rel+'.'+key);events.append({'run_id':run_id,'timestamp':t.isoformat(),'event':name,'source_field':key})
  seen=set()
  if not d['requests']:problems.append({'run_id':run_id,'problem':'acceptance contains no per-request records'})
  for i,row in enumerate(d['requests']):
   if not isinstance(row,dict):raise ValueError('{} requests[{}] must be object'.format(rel,i))
   seq=row.get('sequence')
   if type(seq) is not int or seq<0:problems.append({'run_id':run_id,'index':i,'problem':'sequence missing or invalid'})
   elif seq in seen:problems.append({'run_id':run_id,'index':i,'problem':'duplicate request sequence','sequence':seq})
   else:seen.add(seq)
   for key,name in [('started_at_utc','request_started'),('finished_at_utc','request_finished')]:
    if row.get(key) is not None:
     t=stamp(row[key],rel+'.requests[{}].{}'.format(i,key));events.append({'run_id':run_id,'timestamp':t.isoformat(),'event':name,'sequence':seq,'status':row.get('status'),'task':row.get('task'),'source_field':key})
   if row.get('started_at_utc') and row.get('finished_at_utc') and stamp(row['finished_at_utc'],rel)<stamp(row['started_at_utc'],rel):problems.append({'run_id':run_id,'index':i,'problem':'request finished before start','sequence':seq})
  events.sort(key=lambda e:(stamp(e['timestamp'],e['run_id']), e['event']))
  declared=d.get('planned_count')
  if type(declared) is not int or declared != len(d['requests']):problems.append({'run_id':run_id,'problem':'planned_count disagrees with recorded request count','planned_count':declared,'recorded_count':len(d['requests'])})
  completed=d.get('requests_completed')
  if type(completed) is not int or completed > len(d['requests']):problems.append({'run_id':run_id,'problem':'requests_completed is missing, invalid, or exceeds recorded rows','requests_completed':completed,'recorded_count':len(d['requests'])})
  if not events or not any(e['event'] in ('request_started','request_finished') for e in events):problems.append({'run_id':run_id,'problem':'no timed request events; run cannot be chronologically assessed'})
  stem=p.name[:-len('_acceptance.json')]
  companion={}
  log_names=[stem+'.log' if stem=='failed_run' else stem+'_run.log'] if stem!='batch' else ['batch_log.log']
  if stem=='batch':log_names.append('requests.jsonl')
  for log_name in log_names:
   lp=p.parent/log_name
   if not lp.is_file():continue
   raw=lp.read_bytes(); item={'path':lp.relative_to(root).as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
   if lp.suffix=='.jsonl':
    rows=[]
    for line_no,line in enumerate(raw.decode('utf-8-sig').splitlines(),1):
     try:row=json.loads(line)
     except json.JSONDecodeError as exc:raise ValueError('{} line {} invalid JSON: {}'.format(lp,line_no,exc))
     if not isinstance(row,dict):raise ValueError('{} line {} must be object'.format(lp,line_no))
     rows.append({'line':line_no,'sequence':row.get('sequence'),'task':row.get('task'),'status':row.get('status'),'started_at_utc':row.get('started_at_utc'),'finished_at_utc':row.get('finished_at_utc')})
    item['record_count']=len(rows);item['records']=rows
   else:
    decoded=raw.decode('utf-8-sig',errors='replace');item['line_count']=len(decoded.splitlines())
    item['request_lines']=[{'line':i,'text':line} for i,line in enumerate(decoded.splitlines(),1) if re.match(r'^REQUEST\s+\d+/',line)]
    item['timestamps_present']=False
   companion[log_name]=item;associated_paths.add(lp.resolve())
  all_runs.append({'run_id':run_id,'source_sha256':digest(p),'status':d.get('status'),'dry_run':d.get('dry_run'),'batch_acceptance_pass':d.get('batch_acceptance_pass'),'model_sha256':(d.get('model') or {}).get('sha256') if isinstance(d.get('model'),dict) else None,'classes_sha256':d.get('classes_sha256'),'requests_declared':d.get('planned_count'),'requests_recorded':len(d['requests']),'requests_completed':d.get('requests_completed'),'companion_materials':companion,'events':events,'missing_fields':[k for k in ['started_at_utc','finished_at_utc','requests_completed','batch_acceptance_pass'] if k not in d]})
  global_events.extend(events)
 global_events.sort(key=lambda e:stamp(e['timestamp'],e['run_id']))
 unassociated_logs=[]
 for lp in sorted(root.rglob('*.log')):
  if lp.resolve() in associated_paths:continue
  raw=lp.read_bytes();txt=raw.decode('utf-8-sig',errors='replace')
  unassociated_logs.append({'path':lp.relative_to(root).as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'line_count':len(txt.splitlines()),'timestamp_events_added':False})
 status='review_required' if len(all_runs)>1 or problems else 'single_run_extracted'
 return {'schema_version':1,'status':status,'run_count':len(all_runs),'runs':all_runs,'chronological_recorded_events':global_events,'unassociated_logs':unassociated_logs,'problems':problems,'interpretation':'Events come only from saved acceptance JSON fields. Different files are separate recorded runs; chronological order does not establish causal relation or failure-time register state. This adapter does not interpret DMA register bits, infer TLAST, or identify root cause.'}

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('root',type=Path);ap.add_argument('--output',type=Path);a=ap.parse_args()
 try:
  x=adapt(a.root);payload=json.dumps(x,ensure_ascii=False,indent=2)+'\n'
  if a.output:
   target=a.output.resolve();scan=a.root.resolve()
   if target==scan or target.is_relative_to(scan):raise ValueError('--output must be outside the scanned material directory')
   a.output.write_text(payload,encoding='utf-8')
  else:print(payload,end='')
 except (OSError,ValueError) as exc:print(json.dumps({'schema_version':1,'status':'error','error':str(exc)},ensure_ascii=False));return 2
 return 1 if x['status']=='review_required' else 0
if __name__=='__main__':raise SystemExit(main())
