"""Frozen, label-stratified source-family split; no model-score split selection."""
from collections import defaultdict,Counter
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
SOURCE=ROOT/'datasets/pin_aug8000_20261021'
DEST=HERE/'data'
SEED=20261021


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    assert not DEST.exists(),'Do not replace a frozen partition'
    ancestry=json.loads((SOURCE/'source_audit/parent_group_map.json').read_text(encoding='utf-8'))['image_records']
    assert len(ancestry)==8000
    # Merge exact rotation/reflection-equivalent canonical images as well as known ancestry.
    roots={r['canonical_group_id']:r for r in ancestry if r['image_role']=='original'}
    representative={};group_alias={}
    for gid,r in roots.items():
        with Image.open(r['image_path']) as im:array=np.asarray(im.convert('RGB'))
        hashes=[]
        for k in range(4):
            a=np.rot90(array,k)
            for b in (a,a[:,::-1]):
                hashes.append(hashlib.sha256(str(b.shape).encode()+np.ascontiguousarray(b).tobytes()).hexdigest())
        canonical=min(hashes)
        group_alias[gid]=representative.setdefault(canonical,gid)
    groups=defaultdict(list);counts={};weights={}
    for r in ancestry:
        gid=group_alias[r['canonical_group_id']]
        r['split_group_id']=gid
        groups[gid].append(r)
    for gid,rows in groups.items():
        c=np.zeros(9,dtype=int)
        for r in rows:
            for line in Path(r['label_path']).read_text(encoding='utf-8-sig').splitlines():
                if line.strip():c[int(line.split()[0])]+=1
        counts[gid]=c;weights[gid]=len(rows)
    total=sum(counts.values())
    rng=random.Random(SEED)

    def exact_subset(pool,target):
        order=sorted(pool);rng.shuffle(order)
        previous=[None]*(target+1);previous[0]=(-1,None)
        for gid in order:
            w=weights[gid]
            for s in range(target,w-1,-1):
                if previous[s] is None and previous[s-w] is not None:previous[s]=(s-w,gid)
            if previous[target] is not None:break
        assert previous[target] is not None,'Cannot attain exact target without splitting a family'
        result=set();s=target
        while s:
            s,gid=previous[s];result.add(gid)
        return result

    best=None
    # Choose solely by label distribution; never run or select using model AP.
    for attempt in range(96):
        val=exact_subset(groups,800);test=exact_subset(set(groups)-val,800)
        train=set(groups)-val-test
        partitions={'train':train,'val':val,'test':test}
        vectors={s:sum((counts[g] for g in ids),np.zeros(9,dtype=int)) for s,ids in partitions.items()}
        if any((v==0).any() for v in vectors.values()):continue
        score=sum(float(np.mean(((vectors[s]-total*ratio)/(total*ratio))**2)) for s,ratio in [('train',.8),('val',.1),('test',.1)])
        if best is None or score<best[0]:best=(score,partitions,vectors,attempt)
    assert best is not None,'Cannot retain all classes in three source-separated sets'
    score,partitions,vectors,attempt=best
    summary={};manifest=[]
    for split,ids in partitions.items():
        image_dir=DEST/'images'/split;label_dir=DEST/'labels'/split
        image_dir.mkdir(parents=True);label_dir.mkdir(parents=True)
        paths=[];original_paths=[];roles=Counter();hashes=set()
        for gid in sorted(ids):
            for r in groups[gid]:
                src=Path(r['image_path']);label=Path(r['label_path'])
                key=digest(src)
                dst=image_dir/(key+src.suffix.lower());dst_label=label_dir/(key+'.txt')
                assert key not in hashes
                hashes.add(key)
                try:os.link(src,dst)
                except OSError:shutil.copy2(src,dst)
                shutil.copy2(label,dst_label)
                assert digest(dst)==key and digest(dst_label)==digest(label)
                paths.append(str(dst));roles[r['image_role']]+=1
                if r['image_role']=='original':original_paths.append(str(dst))
                manifest.append(dict(split=split,group_id=gid,image=str(dst),label=str(dst_label),source=str(src),
                                     source_sha256=key,label_sha256=digest(label),role=r['image_role']))
        (DEST/f'{split}.txt').write_text('\n'.join(paths)+'\n',encoding='utf-8')
        (DEST/f'{split}_original_only.txt').write_text('\n'.join(original_paths)+'\n',encoding='utf-8')
        summary[split]=dict(images=len(paths),source_groups=len(ids),original_images=len(original_paths),
                            roles=dict(roles),targets=vectors[split].tolist(),list_sha256=digest(DEST/f'{split}.txt'))
    assert [summary[s]['images'] for s in ['train','val','test']]==[6400,800,800]
    assert not (partitions['train']&partitions['val'] or partitions['train']&partitions['test'] or partitions['val']&partitions['test'])
    hashes={s:{r['source_sha256'] for r in manifest if r['split']==s} for s in partitions}
    assert not(hashes['train']&hashes['val'] or hashes['train']&hashes['test'] or hashes['val']&hashes['test'])
    cfg=json.loads((SOURCE/'data.yaml').read_text(encoding='utf-8'))
    cfg.update(path=str(DEST),train='train.txt',val='val.txt',test='test.txt')
    (DEST/'data.yaml').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    original_cfg=dict(cfg,val='val_original_only.txt',test='test_original_only.txt')
    (DEST/'data_original_holdout.yaml').write_text(json.dumps(original_cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    evidence=dict(seed=SEED,selection='96 deterministic candidate assignments scored only on per-class label-count proportion; no model inference',
                  selected_candidate=attempt,balance_score=score,known_ancestry_groups=len(roots),
                  groups_after_exact_rotation_reflection_merge=len(groups),split=summary,
                  group_overlap=0,exact_file_overlap=0,sealed_test_read=False,
                  caveats=['Known image ancestry, not verified physical chip identity','New internal holdout contains correlated variants within each split',
                           'All8000 pool had historical training exposure; not a new independent blind test','No direct AP comparison with previous validation partition'])
    (HERE/'split_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (HERE/'split_report.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
