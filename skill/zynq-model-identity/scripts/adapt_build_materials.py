#!/usr/bin/env python3
"""Summarize known build_manifest/build_report JSON files without guessing runtime identity."""
from __future__ import annotations
import argparse, hashlib, json, os, re, sys
from pathlib import Path
HEX64=re.compile(r"^[0-9a-fA-F]{64}$")

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def audit(root):
 root=root.resolve()
 if not root.is_dir():raise ValueError('root must be a directory')
 files=[]
 for p in sorted(root.rglob('*')):
  if p.is_symlink():raise ValueError('symlink encountered; refusing ambiguous scan: '+str(p))
  if p.is_file():files.append(p)
 actual={}
 for p in files:
  actual[p.relative_to(root).as_posix()]=sha(p)
 by_hash={}
 for rel,digest in actual.items():by_hash.setdefault(digest,[]).append(rel)
 candidates=[p for p in files if p.name in ('build_manifest.json','build_report.json')]
 if not candidates: raise ValueError('no build_manifest.json or build_report.json found below root')
 reports=[]; missing=[]; conflicts=[]; unsupported=[]
 for p in candidates:
  try: doc=json.loads(p.read_text(encoding='utf-8-sig'))
  except (UnicodeError,json.JSONDecodeError) as exc:raise ValueError('invalid JSON {}: {}'.format(p.relative_to(root),exc))
  if not isinstance(doc,dict):raise ValueError('expected JSON object: '+p.name)
  mapping={'source_sha256':'source_sha256','elf_sha256':'elf_sha256','package_sha256':'package_sha256','model_sha256':'model_sha256'}
  extracted={k:doc[k] for k in mapping if k in doc}
  declared=[]
  for field,value in extracted.items():
   if field=='source_sha256' and isinstance(value,dict):
    declared.extend((field+':'+str(k),v,str(k)) for k,v in value.items())
   elif isinstance(value,str):declared.append((field,value,None))
   elif value is not None:conflicts.append({'source':p.relative_to(root).as_posix(),'field':field,'problem':'unexpected value type'})
  if isinstance(doc.get('files'),dict):
   for rel,meta in doc['files'].items():
    digest=meta.get('sha256') if isinstance(meta,dict) else None
    if digest is not None:declared.append(('files:'+str(rel),digest,str(rel)))
  checks=[]
  if not extracted and not (isinstance(doc.get('files'),dict) and doc['files']):
   unsupported.append({'source':p.relative_to(root).as_posix(),'problem':'unsupported or empty build report; no recognized identity/hash fields'})
  for label,digest,rel in declared:
   if not isinstance(digest,str) or not HEX64.fullmatch(digest):
    conflicts.append({'source':p.relative_to(root).as_posix(),'field':label,'problem':'declared digest is not 64 hex characters'});continue
   matches=[]
   if rel:
    candidate=(p.parent/Path(rel)).resolve()
    try:
     candidate.relative_to(root)
     if candidate.is_file():matches=[candidate.relative_to(root).as_posix()]
    except ValueError: conflicts.append({'source':p.relative_to(root).as_posix(),'field':label,'problem':'declared path escapes scan root'})
   else:matches=by_hash.get(digest.lower(),[])
   if not matches:
    row={'field':label,'declared_sha256':digest,'status':'declared_only','actual_sha256':None}
    missing.append({'source':p.relative_to(root).as_posix(),'field':label,'declared_sha256':digest})
   else:
    got=actual[matches[0]];row={'field':label,'path':matches[0],'declared_sha256':digest,'actual_sha256':got,'status':'match' if got.lower()==digest.lower() else 'mismatch'}
    if row['status']=='mismatch':conflicts.append({'source':p.relative_to(root).as_posix(),'field':label,'path':matches[0],'declared_sha256':digest,'actual_sha256':got})
   checks.append(row)
  reports.append({'path':p.relative_to(root).as_posix(),'sha256':actual[p.relative_to(root).as_posix()],'schema':doc.get('schema'),'generated_at':doc.get('generated_at_local',doc.get('generated_utc')),'selected_fields':extracted,'checks':checks})
 status='conflict' if conflicts else 'incomplete' if missing else 'unsupported' if unsupported else 'checked'
 return {'schema_version':1,'status':status,'scan_root_label':root.name,'scanned_file_count':len(actual),'reports':reports,'missing_declared_artifacts':missing,'conflicts':conflicts,'unsupported_reports':unsupported,'interpretation':'Only build manifest/report JSON files and files physically present below the supplied root were inspected. A matching hash does not prove that an artifact ran on the board; absent files remain unverified.'}

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('root',type=Path);ap.add_argument('--output',type=Path);a=ap.parse_args()
 try:
  result=audit(a.root);payload=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
  if a.output:
   target=a.output.resolve();scan=a.root.resolve()
   if target==scan or target.is_relative_to(scan):raise ValueError('--output must be outside the scanned material directory')
   a.output.write_text(payload,encoding='utf-8')
  else:print(payload,end='')
 except (OSError,ValueError) as exc:
  print(json.dumps({'schema_version':1,'status':'error','error':str(exc)},ensure_ascii=False));return 2
 return {'checked':0,'incomplete':1,'unsupported':1,'conflict':1}[result['status']]
if __name__=='__main__':raise SystemExit(main())
