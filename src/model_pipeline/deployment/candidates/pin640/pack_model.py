"""Generate a CRC-bound V8 parameter package and matching C graph descriptor."""
import argparse
import json
from pathlib import Path
import struct
import zlib
import hashlib
import numpy as np
if __package__:
    from .export_graph import memory_plan, validate_domain_class_names
else:
    from export_graph import memory_plan, validate_domain_class_names
if __package__:
    from .quantize import (_sha256, load_dataset_manifest, materialize_manifest_record,
                          validate_quantization_metadata, verify_selected_image)
else:
    from quantize import (_sha256, load_dataset_manifest, materialize_manifest_record,
                          validate_quantization_metadata, verify_selected_image)

OPS={'conv':0,'silu':1,'slice':2,'concat':3,'add':4,'maxpool':5,'upsample':6}
DOMAIN_SOURCE_IDS={'pcb':list(range(9)),'pin':list(range(9,18)),
                   'joint18':list(range(18))}


def pair(value):
    if isinstance(value,(tuple,list)):
        if len(value)!=2 or value[0]!=value[1]: raise ValueError('Only square spatial operations supported')
        return value[0]
    return value


def validate_calibration_provenance(q, domain, class_count, source_class_ids, classes,
                                    manifest_override=None, quant_dir=None):
    if q.get('calibration_split') != 'train':
        raise ValueError('Calibration must use the train split')
    manifest_hash = q.get('calibration_manifest_sha256')
    manifest_path = q.get('calibration_manifest')
    if class_count == 9 and (not manifest_hash or not manifest_path):
        raise ValueError('Nine-class package requires explicit calibration manifest metadata')
    if not manifest_hash and not manifest_path:
        # Historic 18-class V8Q packages predate manifest provenance fields.
        return
    if not manifest_hash or not manifest_path:
        raise ValueError('Calibration manifest path and hash must be recorded together')
    stored_manifest_path = Path(manifest_path).expanduser()
    if manifest_override is not None:
        manifest_path = Path(manifest_override).expanduser().resolve()
    elif stored_manifest_path.is_absolute():
        manifest_path = stored_manifest_path
    else:
        candidates = []
        if quant_dir is not None:
            candidates.append(Path(quant_dir).resolve() / stored_manifest_path)
        candidates.append(Path(__file__).resolve().parents[3] / stored_manifest_path)
        candidates.append(Path.cwd() / stored_manifest_path)
        manifest_path = next((candidate.resolve() for candidate in candidates if candidate.is_file()),
                             candidates[0] if candidates else stored_manifest_path)
    if not manifest_path.is_file() or _sha256(manifest_path) != manifest_hash:
        raise ValueError('Calibration manifest is missing or its SHA-256 has changed')
    rows, manifest_names = load_dataset_manifest(manifest_path, splits={'train'})
    if manifest_names is not None:
        expected_names = [manifest_names[class_id] for class_id in source_class_ids]
        if expected_names != classes:
            raise ValueError('Calibration manifest class names/order do not match package domain')
    selected_ids = q.get('calibration_ids')
    if (not isinstance(selected_ids, list) or not selected_ids or
            any(not isinstance(record_id, str) or not record_id for record_id in selected_ids) or
            len(set(selected_ids)) != len(selected_ids)):
        raise ValueError('Calibration IDs must be a nonempty unique list')
    by_id = {row['id']: row for row in rows}
    if any(record_id not in by_id for record_id in selected_ids):
        raise ValueError('Calibration IDs must resolve to manifest train records')
    selected = [materialize_manifest_record(by_id[record_id]) for record_id in selected_ids]
    for row in selected:
        verify_selected_image(row)
    expected_domains = ['pcb', 'pin'] if domain == 'joint18' else [domain]
    actual_domains = sorted({row['domain'] for row in selected})
    if actual_domains != expected_domains or q.get('calibration_domains') != expected_domains:
        raise ValueError('Calibration rows contain an unexpected domain set')
    allowed_ids = set(source_class_ids)
    covered = {class_id for row in selected for class_id in row['source_class_ids']}
    if not covered.issubset(allowed_ids):
        raise ValueError('Calibration rows contain a source/global class ID outside the package domain')
    if q.get('source_global_class_ids_covered') != sorted(covered):
        raise ValueError('Calibration class coverage does not match the train manifest')
    source_to_local = {source_id: local_id for local_id, source_id in enumerate(source_class_ids)}
    local_covered = sorted(source_to_local[class_id] for class_id in covered)
    if q.get('classes_covered') != local_covered:
        raise ValueError('Calibration local class coverage does not match source/global IDs')
    if class_count == 9:
        if q.get('calibration_domains') != expected_domains:
            raise ValueError('Nine-class calibration domains do not match package domain')
        if q.get('calibration_split') != 'train':
            raise ValueError('Nine-class calibration split must be train')


def pack(model,quant,output,budget=8388608,manifest_override=None):
    g=json.loads((model/'graph.json').read_text(encoding='utf-8'))
    q=json.loads((quant/'quantization.json').read_text())
    if g['checkpoint_sha256']!=q['model_sha256']: raise ValueError('Quantization/model mismatch')
    classes=g.get('classes')
    class_count=g.get('class_count',len(classes) if isinstance(classes,list) else None)
    if class_count not in (9,18) or not isinstance(classes,list) or len(classes)!=class_count:
        raise ValueError('Graph must declare exactly 9 or 18 ordered class names')
    if any(not isinstance(name,str) or not name.strip() for name in classes) or len(set(classes))!=class_count:
        raise ValueError('Graph class names must be unique nonempty strings')
    domain=g.get('domain','joint18' if class_count==18 else None)
    if domain not in DOMAIN_SOURCE_IDS or (class_count==9 and domain not in ('pcb','pin')) or (class_count==18 and domain!='joint18'):
        raise ValueError('Graph class domain is inconsistent with its class count')
    if domain != 'pin' or class_count != 9:
        raise ValueError('PIN640 package requires exactly nine PIN classes')
    validate_domain_class_names(classes,domain)
    source_class_ids=g.get('source_class_ids',DOMAIN_SOURCE_IDS[domain])
    if source_class_ids!=DOMAIN_SOURCE_IDS[domain]: raise ValueError('Graph source/global class mapping is inconsistent')
    reg_max=g.get('reg_max')
    input_shape=g.get('input_shape')
    input_size=g.get('input_size')
    if type(reg_max) is not int or reg_max!=16: raise ValueError('PIN640 graph reg_max must be 16')
    if input_shape!=[1,3,640,640] or input_size!=640: raise ValueError('Only batch-one 640x640 graphs are supported')
    metadata = dict(domain=domain, class_count=class_count, classes=classes,
                    source_class_ids=source_class_ids, reg_max=reg_max,
                    input_shape=input_shape, input_size=input_size)
    validate_quantization_metadata(q, metadata)
    validate_calibration_provenance(q,domain,class_count,source_class_ids,classes,
                                    manifest_override=manifest_override, quant_dir=quant)
    memory=memory_plan(g['nodes'],g['outputs'],budget)
    if not memory['fits_budget']: raise ValueError('PIN640 candidate activation arena budget exceeded')
    weights=np.load(quant/'weights_int8.npz',allow_pickle=False)
    payload=bytearray(); descriptors=[]; scales=q['scales']
    def put(data):
        payload.extend(bytes((-len(payload))%8)); offset=len(payload); payload.extend(data); return offset
    max_scratch=0
    for node,allocation in zip(g['nodes'],memory['allocations']):
        if len(node['inputs'])>8: raise ValueError('Too many inputs')
        _,c,h,w=node['shape']; p=node.get('params',{})
        d=dict(op=OPS[node['op']],c=c,h=h,w=w,offset=allocation['offset'],bytes=c*h*w,
               count=len(node['inputs']),kernel=0,stride=0,padding=0,groups=1,slice_start=p.get('start',0),
               weight=0,bias=0,multiplier=0,lut=0,scale=scales[str(node['id'])])
        if node['op']=='conv':
            arr=weights[node['weight']]
            d.update(kernel=arr.shape[-1],stride=pair(p['stride']),padding=pair(p['padding']),groups=p['groups'])
            if pair(p['dilation'])!=1 or p['groups']!=1: raise ValueError('Unsupported convolution')
            d['weight']=put(arr.astype('i1').tobytes())
            d['bias']=put(weights[node['bias']].astype('<i4').tobytes())
            mult=scales[str(node['inputs'][0])]*weights[node['weight']+'_scale']/d['scale']
            d['multiplier']=put(mult.astype('<f8').tobytes())
            max_scratch=max(max_scratch,c*h*w)
        elif node['op']=='silu': d['lut']=put(weights['lut_'+str(node['id'])].astype('i1').tobytes())
        elif node['op']=='maxpool': d.update(kernel=pair(p['kernel_size']),stride=pair(p['stride']),padding=pair(p['padding']))
        elif node['op']=='upsample':
            if p['mode']!='nearest' or pair(p['scale_factor'])!=2: raise ValueError('Unsupported resize')
        descriptors.append((d,node['inputs']))
    crc=zlib.crc32(payload)
    header=struct.pack('<4s7I',b'V8PK',1,len(payload),crc,len(descriptors),memory['arena_bytes'],class_count,input_size)
    output.mkdir(parents=True,exist_ok=False)
    (output/'MODEL.V8P').write_bytes(header+payload)
    lines=['/* Generated from graph.json; parameters bound by CRC. */','#ifndef V8_GENERATED_MODEL_H','#define V8_GENERATED_MODEL_H','#include "v8_runtime.h"',f'static const V8Node v8_nodes[{len(descriptors)}] = {{']
    for d,inputs in descriptors:
        fields=[f'.{k}={repr(v) if k=="scale" else v}' for k,v in d.items()]
        fields.append('.inputs={'+','.join(map(str,inputs))+'}')
        lines.append('  {'+','.join(fields)+'},')
    class_hash=hashlib.sha256(json.dumps(g['classes'],ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    head_elements=sum(int(np.prod(g['nodes'][i]['shape'])) for i in g['outputs'])
    lines.extend(['};',f'#define V8_CLASS_DOMAIN "{domain}"',
                  f'#define V8_CLASS_COUNT {class_count}u',f'#define V8_REG_MAX {reg_max}u',
                  f'#define V8_INPUT_SIZE {input_size}u',f'#define V8_SCRATCH_COUNT {max_scratch}u',
                  f'#define V8_PACKAGE_BYTES {len(payload)+32}u',f'#define V8_ARENA_BYTES {memory["arena_bytes"]}u',
                  f'#define V8_HEAD_ELEMENTS {head_elements}u',f'#define V8_CLASSES_SHA256 "{class_hash}"',
                  'static const V8Graph v8_graph = {v8_nodes,'+f'{len(descriptors)},{memory["arena_bytes"]},{len(payload)},{crc}u,'+'{'+','.join(map(str,g['outputs']))+'},'+repr(scales['-1'])+
                  f',.classes={class_count}u,.reg_max={reg_max}u,.input_size={input_size}u'+'};','#endif'])
    (output/'v8_generated_model.h').write_text('\n'.join(lines)+'\n')
    report=dict(format='V8PK',version=1,domain=domain,class_count=class_count,
                reg_max=reg_max,input_shape=input_shape,input_size=input_size,
                source_class_ids=source_class_ids,model_sha256=g['checkpoint_sha256'],parameter_bytes=len(payload),
                arena_bytes=memory['arena_bytes'],input_bytes=3*640*640,scratch_bytes=max_scratch*4,
                total_runtime_buffers=memory['arena_bytes']+2*3*640*640+max_scratch*4+4*sum(int(np.prod(g['nodes'][i]['shape'])) for i in g['outputs']),
                rgb_input_bytes=3*640*640,nchw_input_bytes=3*640*640,
                float_head_bytes=4*sum(int(np.prod(g['nodes'][i]['shape'])) for i in g['outputs']),
                protocol='pin9-v8/2-input640',
                classes=classes,node_count=len(descriptors),parameter_crc32=crc,
                accuracy_accepted=False,
                note='Activation arena fits the PIN640 candidate budget. Total linked DDR including weights/scratch requires linker check; no board-ready claim.')
    (output/'package.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'classes.json').write_text(json.dumps(dict(names=classes,domain=domain,
        protocol='pin9-v8/2-input640',classes_sha256=class_hash),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='classes'}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('model','quant','output'): p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--arena-bytes',type=int,default=8388608)
    p.add_argument('--manifest',type=Path,
                   help='Optional relocated calibration manifest; its content hash must match quantization.json')
    a=p.parse_args();pack(a.model,a.quant,a.output,a.arena_bytes,a.manifest)
