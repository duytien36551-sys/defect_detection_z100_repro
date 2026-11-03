"""Explicit symmetric INT8 graph calibration and executable integer reference.

Convolution uses float64 only as an exact-integer host reference: int8 products
and sums are checked within INT32. This is not a floating-point deployment claim.
"""
import argparse
import json
from pathlib import Path
import hashlib
import math
import numpy as np
import torch
from torch.nn import functional as F
if __package__:
    from .export_graph import execute, validate_domain_class_names
else:
    from export_graph import execute, validate_domain_class_names


DOMAIN_CLASS_IDS = {
    'pcb': tuple(range(9)),
    'pin': tuple(range(9, 18)),
    'joint18': tuple(range(18)),
}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(manifest_path, value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(manifest_path).resolve().parent / path
    return path.resolve()


def _verify_file_hash(path, expected, description):
    """Verify a manifest-provided SHA-256 before consuming the file contents."""
    if expected is None:
        return
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdefABCDEF' for c in expected):
        raise ValueError(f'Invalid SHA-256 metadata for {description}')
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'{description} does not exist: {path}')
    if _sha256(path) != expected.lower():
        raise ValueError(f'{description} SHA-256 mismatch: {path}')


def _read_yolo_labels(path, allowed_class_ids=None):
    """Read normalized YOLO boxes while validating their declared ID space."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'Manifest label file does not exist: {path}')
    if allowed_class_ids is None:
        allowed_class_ids = DOMAIN_CLASS_IDS['joint18']
    boxes = []
    for line_number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 5:
            raise ValueError(f'Expected YOLO class/cx/cy/w/h at {path}:{line_number}')
        try:
            class_id = int(fields[0])
            cx, cy, width, height = (float(value) for value in fields[1:])
        except ValueError as exc:
            raise ValueError(f'Invalid YOLO label at {path}:{line_number}') from exc
        if class_id not in allowed_class_ids:
            raise ValueError(f'Off-domain class ID at {path}:{line_number}')
        if (not all(math.isfinite(value) for value in (cx, cy, width, height)) or
                not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < width <= 1 and 0 < height <= 1)):
            raise ValueError(f'Invalid normalized box at {path}:{line_number}')
        if not (0 <= cx - width / 2 < cx + width / 2 <= 1 and
                0 <= cy - height / 2 < cy + height / 2 <= 1):
            raise ValueError(f'Normalized box exceeds image bounds at {path}:{line_number}')
        boxes.append({'class_id': class_id,
                      'xyxy': [cx - width / 2, cy - height / 2,
                               cx + width / 2, cy + height / 2]})
    return boxes


def _derived_local_label_path(image_path, split):
    image_path = Path(image_path)
    if image_path.parent.name != split or image_path.parent.parent.name.casefold() != 'images':
        raise ValueError(f'Cannot derive local labels path from data_manifest image: {image_path}')
    return image_path.parent.parent.parent / 'labels' / split / f'{image_path.stem}.txt'


def _boxes_equivalent(left, right, *, atol=1e-8):
    """Compare label rows as an unordered multiset after source-ID mapping."""
    if len(left) != len(right):
        return False
    unmatched = list(right)
    for source in left:
        source_xyxy = np.asarray(source['xyxy'], dtype=np.float64)
        match_index = next((index for index, candidate in enumerate(unmatched)
                            if source['class_id'] == candidate['class_id'] and
                            np.isclose(source_xyxy, candidate['xyxy'], rtol=0.0, atol=atol).all()), None)
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return not unmatched


def materialize_manifest_record(row):
    """Load and verify label data for a selected data_manifest record."""
    if 'source_label_path' not in row:
        return row
    source_path = row['source_label_path']
    _verify_file_hash(source_path, row.get('source_label_sha256'), 'Source label')
    source_ids = DOMAIN_CLASS_IDS[row['domain']]
    source_boxes = _read_yolo_labels(source_path, source_ids)
    if row.get('label_sha256') is not None:
        local_path = _derived_local_label_path(row['image_path'], row['split'])
        _verify_file_hash(local_path, row['label_sha256'], 'Local training label')
        local_boxes = _read_yolo_labels(local_path, range(9))
        offset = 9 if row['domain'] == 'pin' else 0
        mapped_local = [{'class_id': box['class_id'] + offset, 'xyxy': box['xyxy']}
                        for box in local_boxes]
        if not _boxes_equivalent(source_boxes, mapped_local):
            raise ValueError(f'Source/global and local labels disagree for {row["id"]!r}')
    row['boxes'] = source_boxes
    row['source_class_ids'] = [box['class_id'] for box in source_boxes]
    return row


def verify_selected_image(row):
    """Check a selected calibration/evaluation image without scanning other images."""
    image_path = row['image_path']
    if not image_path.is_file():
        raise ValueError(f'Selected image does not exist: {image_path}')
    _verify_file_hash(image_path, row.get('image_sha256'), 'Selected image')


def _record_domain(row):
    domain = row.get('domain')
    if domain in ('pcb', 'pin'):
        return domain
    record_id = str(row.get('id', ''))
    if record_id.startswith('pcb_'):
        return 'pcb'
    if record_id.startswith('pin_'):
        return 'pin'
    raise ValueError(f'Cannot determine dataset domain for record {record_id!r}')


def load_dataset_manifest(manifest_path, splits=None):
    """Normalize official records JSON or single_domain data_manifest lists."""
    manifest_path = Path(manifest_path).expanduser().resolve()
    if not manifest_path.is_file():
        raise ValueError(f'Dataset manifest does not exist: {manifest_path}')
    raw = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    selected_splits = None if splits is None else set(splits)
    normalized = []
    class_names = None
    if isinstance(raw, dict) and isinstance(raw.get('records'), list):
        class_names = raw.get('class_names')
        if (not isinstance(class_names, list) or len(class_names) != 18 or
                any(not isinstance(name, str) or not name.strip() for name in class_names) or
                len(set(class_names)) != 18):
            raise ValueError('Official records manifest must define 18 unique nonempty class names')
        for index, row in enumerate(raw['records']):
            if not isinstance(row, dict) or row.get('split') not in ('train', 'val', 'test'):
                raise ValueError(f'Invalid official record at index {index}')
            domain = _record_domain(row)
            if selected_splits is not None and row['split'] not in selected_splits:
                continue
            boxes = row.get('boxes')
            if not isinstance(boxes, list):
                raise ValueError(f'Official record {row.get("id")!r} has no boxes list')
            ids = []
            normalized_boxes = []
            for box in boxes:
                class_id = box.get('class_id') if isinstance(box, dict) else None
                if type(class_id) is not int or class_id not in DOMAIN_CLASS_IDS['joint18']:
                    raise ValueError(f'Invalid source/global class ID in record {row.get("id")!r}')
                ids.append(class_id)
                coords = box.get('xyxy')
                if (not isinstance(coords, list) or len(coords) != 4 or
                        not all(isinstance(value, (int, float)) and math.isfinite(value) for value in coords)):
                    raise ValueError(f'Invalid normalized xyxy box in record {row.get("id")!r}')
                x1, y1, x2, y2 = (float(value) for value in coords)
                if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
                    raise ValueError(f'Invalid normalized xyxy bounds in record {row.get("id")!r}')
                normalized_boxes.append({'class_id': class_id, 'xyxy': [x1, y1, x2, y2]})
            if any(class_id not in DOMAIN_CLASS_IDS[domain] for class_id in ids):
                raise ValueError(f'Off-domain source/global class ID in record {row.get("id")!r}')
            image_path = _manifest_path(manifest_path, row.get('image', ''))
            normalized.append(dict(id=str(row.get('id', index)), domain=domain, split=row['split'],
                                   image_path=image_path, boxes=normalized_boxes,
                                   source_class_ids=ids,
                                   image_sha256=row.get('image_sha256')))
    elif isinstance(raw, list):
        for index, row in enumerate(raw):
            if not isinstance(row, dict) or row.get('domain') not in ('pcb', 'pin'):
                raise ValueError(f'Invalid single-domain data_manifest row at index {index}')
            if row.get('split') not in ('train', 'val', 'test'):
                raise ValueError(f'Invalid split in data_manifest row at index {index}')
            if selected_splits is not None and row['split'] not in selected_splits:
                continue
            if not row.get('image') or not row.get('source_label'):
                raise ValueError(f'data_manifest row {index} requires image and source_label paths')
            image_path = _manifest_path(manifest_path, row['image'])
            label_path = _manifest_path(manifest_path, row['source_label'])
            normalized.append(dict(id=str(row.get('id') or row.get('image_sha256') or index),
                                   domain=row['domain'], split=row['split'], image_path=image_path,
                                   source_label_path=label_path,
                                   image_sha256=row.get('image_sha256'),
                                   source_label_sha256=row.get('source_label_sha256'),
                                   label_sha256=row.get('label_sha256')))
    else:
        raise ValueError('Manifest must be official records JSON or a single-domain data_manifest list')
    return normalized, class_names


def _graph_metadata(graph, domain):
    if domain != 'pin' or graph.get('domain') != 'pin' or graph.get('class_count') != 9:
        raise ValueError('PIN640 requires exactly nine PIN classes')
    names = graph.get('classes')
    count = graph.get('class_count', len(names) if isinstance(names, list) else None)
    if count not in (9, 18) or not isinstance(names, list) or len(names) != count:
        raise ValueError('Graph class metadata must describe exactly 9 or 18 ordered classes')
    if any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != count:
        raise ValueError('Graph class names must be unique nonempty strings')
    graph_domain = graph.get('domain', 'joint18' if count == 18 else None)
    if count == 9 and graph_domain not in ('pcb', 'pin'):
        raise ValueError('Nine-class graph must declare domain pcb or pin')
    if count == 18 and graph_domain != 'joint18':
        raise ValueError('Eighteen-class graph must declare the joint18 domain')
    validate_domain_class_names(names, graph_domain)
    if domain != graph_domain:
        raise ValueError(f'Calibration domain {domain!r} does not match graph domain {graph_domain!r}')
    expected_source_ids = list(DOMAIN_CLASS_IDS[graph_domain])
    source_ids = graph.get('source_class_ids', expected_source_ids)
    if source_ids != expected_source_ids:
        raise ValueError('Graph source_class_ids do not match its declared domain')
    reg_max = graph.get('reg_max')
    shape = graph.get('input_shape')
    if type(reg_max) is not int or reg_max != 16:
        raise ValueError('PIN640 graph reg_max must be 16')
    if shape != [1, 3, 640, 640] or graph.get('input_size') != 640:
        raise ValueError('Only batch-one 640x640 graphs are supported')
    return dict(domain=graph_domain, class_count=count, source_class_ids=expected_source_ids,
                classes=names, reg_max=reg_max, input_shape=shape, input_size=640)


def validate_quantization_metadata(qspec, metadata):
    """Bind quantization metadata to the graph, requiring full provenance for 9-class runs."""
    graph_keys = ('domain', 'class_count', 'classes', 'source_class_ids',
                  'reg_max', 'input_shape', 'input_size')
    provenance_keys = ('calibration_manifest', 'calibration_manifest_sha256',
                       'calibration_ids', 'calibration_domains', 'calibration_split')
    required = graph_keys + provenance_keys if metadata['class_count'] == 9 else ()
    missing = [key for key in required if key not in qspec]
    if missing:
        raise ValueError(f"Nine-class quantization metadata is missing required fields: {', '.join(missing)}")
    expected = {key: metadata[key] for key in graph_keys}
    errors = {
        'domain': 'Quantization domain/model mismatch',
        'class_count': 'Quantization class count/model mismatch',
        'classes': 'Quantization class names/order mismatch',
        'source_class_ids': 'Quantization source/global class mapping mismatch',
        'reg_max': 'Quantization reg_max/model mismatch',
        'input_shape': 'Quantization input shape/model mismatch',
        'input_size': 'Quantization input shape/model mismatch',
    }
    for key in graph_keys:
        if key in qspec and qspec[key] != expected[key]:
            raise ValueError(errors[key])


def select_calibration_records(manifest_path, domain, per_task, graph):
    if domain not in DOMAIN_CLASS_IDS:
        raise ValueError('--domain must be pcb, pin, or joint18')
    if per_task < 1:
        raise ValueError('per-task must be positive')
    metadata = _graph_metadata(graph, domain)
    records, manifest_names = load_dataset_manifest(manifest_path, splits={'train'})
    if manifest_names is not None:
        source_ids = metadata['source_class_ids']
        expected_names = [manifest_names[class_id] for class_id in source_ids]
        if expected_names != metadata['classes']:
            raise ValueError('Graph class names/order do not match selected manifest domain')
    selected = []
    for task in (('pcb', 'pin') if domain == 'joint18' else (domain,)):
        rows = [row for row in records if row['domain'] == task and row['split'] == 'train']
        if not rows:
            raise ValueError(f'Manifest has no training images for calibration domain {task}')
        rows.sort(key=lambda row: hashlib.sha256(row['id'].encode('utf-8')).hexdigest())
        chosen = []
        deferred = []
        covered = set()
        for row in rows:
            if len(chosen) >= per_task:
                break
            row = materialize_manifest_record(row)
            classes = set(row['source_class_ids'])
            if classes - covered and len(chosen) < per_task:
                chosen.append(row)
                covered.update(classes)
            else:
                deferred.append(row)
        for row in deferred:
            if len(chosen) >= per_task:
                break
            chosen.append(row)
        selected.extend(chosen)
    if not selected:
        raise ValueError(f'Manifest has no training images for domain {domain}')
    allowed_ids = set(metadata['source_class_ids'])
    for row in selected:
        verify_selected_image(row)
        if any(class_id not in allowed_ids for class_id in row['source_class_ids']):
            raise ValueError(f'Off-domain source/global class ID in calibration record {row["id"]!r}')
    return selected, metadata


def preprocess(path):
    if __package__:
        from .desktop.preprocess import prepare_image
    else:
        from desktop.preprocess import prepare_image
    _,payload,_=prepare_image(path)
    image=np.frombuffer(payload,dtype=np.uint8).copy().reshape(640,640,3)
    return torch.from_numpy(image).permute(2,0,1).unsqueeze(0).float()/255


def load_float(directory):
    directory=Path(directory)
    graph=json.loads((directory/'graph.json').read_text(encoding='utf-8'))
    with np.load(directory/'weights_float.npz',allow_pickle=False) as z:
        weights={k:torch.from_numpy(z[k].copy()) for k in z.files}
    return graph,weights


def run_float(graph,weights,image,observe=None):
    values={-1:image}
    uses={i:0 for i in [-1]+[n['id'] for n in graph['nodes']]}
    for n in graph['nodes']:
        for i in n['inputs']: uses[i]+=1
    for i in graph['outputs']: uses[i]+=1
    for n in graph['nodes']:
        y=execute(n,values,weights); values[n['id']]=y
        if observe: observe(n['id'],y)
        for i in n['inputs']:
            uses[i]-=1
            if not uses[i]: del values[i]
    return [values[i] for i in graph['outputs']]


def qround(x):
    return torch.round(x).clamp(-127,127).to(torch.int8)


def run_integer(graph,params,qspec,image,observe=None):
    scales=qspec['scales']
    values={-1:qround(image.double()/scales['-1'])}
    uses={i:0 for i in [-1]+[n['id'] for n in graph['nodes']]}
    for n in graph['nodes']:
        for i in n['inputs']: uses[i]+=1
    for i in graph['outputs']: uses[i]+=1
    for n in graph['nodes']:
        inputs=[values[i] for i in n['inputs']]; op=n['op']; sid=str(n['id'])
        src=[scales[str(i)] for i in n['inputs']]; dst=scales[sid]
        if op=='conv':
            w=params[n['weight']].double(); b=params[n['bias']].double()
            acc=F.conv2d(inputs[0].double(),w,b,**n['params'])
            if acc.abs().max()>2147483647: raise OverflowError(f'INT32 overflow node {sid}')
            y=qround(acc*(src[0]*params[n['weight']+'_scale'].double()/dst).reshape(1,-1,1,1))
        elif op=='silu':
            lut=params['lut_'+sid]
            y=lut[(inputs[0].long()+128)]
        elif op=='add': y=qround((inputs[0].double()*src[0]+inputs[1].double()*src[1])/dst)
        elif op=='concat': y=torch.cat([qround(x.double()*s/dst) for x,s in zip(inputs,src)],1)
        else:
            local={i:v.double() for i,v in zip(n['inputs'],inputs)}
            y=qround(execute(n,local,{})*src[0]/dst)
        values[n['id']]=y
        if observe: observe(n['id'],y)
        for i in n['inputs']:
            uses[i]-=1
            if not uses[i]: del values[i]
    return [values[i].float()*scales[str(i)] for i in graph['outputs']]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True,
                   help='Explicit official records JSON or single-domain data_manifest list')
    p.add_argument('--domain',choices=('pin',),required=True,
                   help='Calibration domain; must match the exported graph')
    p.add_argument('--per-task',type=int,default=256)
    p.add_argument('--activation-percentile',type=float,default=100.0,
                   help='absolute activation percentile from a deterministic 512-value-per-image sample; 100 uses exact maxima')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); torch.set_num_threads(1)
    if not 0.0<a.activation_percentile<=100.0: raise ValueError('activation-percentile must be in (0,100]')
    graph,weights=load_float(a.model)
    selected,metadata=select_calibration_records(a.manifest,a.domain,a.per_task,graph)
    ranges={'-1':1.0}; activation_samples={}
    def observe(i,y):
        if not torch.isfinite(y).all(): raise ValueError('Nonfinite activation')
        key=str(i)
        if a.activation_percentile==100.0:
            ranges[key]=max(ranges.get(key,0),float(y.abs().max()))
        else:
            flat=y.detach().abs().reshape(-1)
            if flat.numel()>512:
                indices=torch.linspace(0,flat.numel()-1,steps=512,device=flat.device).long()
                sample=flat.index_select(0,indices).cpu()
            else:
                sample=flat.cpu()
            activation_samples.setdefault(key,[]).append(sample)
    with torch.no_grad():
        for idx,r in enumerate(selected):
            verify_selected_image(r)
            image=preprocess(r['image_path'])
            run_float(graph,weights,image,observe)
            if (idx+1)%16==0: print(f'calibrated {idx+1}/{len(selected)}',flush=True)
    if a.activation_percentile<100.0:
        quantile=a.activation_percentile/100.0
        for key,chunks in activation_samples.items():
            ranges[key]=float(torch.quantile(torch.cat(chunks),quantile))
    scales={k:max(v/127,1e-9) for k,v in ranges.items()}
    params={}
    for n in graph['nodes']:
        if n['op']=='conv':
            w=weights[n['weight']].double(); ws=w.abs().flatten(1).amax(1).clamp_min(1e-9)/127
            params[n['weight']]=qround(w/ws.reshape(-1,1,1,1))
            b=torch.round(weights[n['bias']].double()/(scales[str(n['inputs'][0])]*ws))
            if b.abs().max()>2147483647: raise OverflowError('Bias INT32 overflow')
            # Worst-case bound guarantees no intermediate accumulator overflow.
            bound=params[n['weight']].long().abs().flatten(1).sum(1)*127+b.abs()
            if bound.max()>2147483647: raise OverflowError('Worst-case INT32 accumulator overflow')
            params[n['bias']]=b.to(torch.int32); params[n['weight']+'_scale']=ws
        if n['op']=='silu':
            x=torch.arange(-128,128,dtype=torch.float64)*scales[str(n['inputs'][0])]
            params['lut_'+str(n['id'])]=qround(F.silu(x)/scales[str(n['id'])])
    source_ids=metadata['source_class_ids']
    source_to_local={source_id:local_id for local_id,source_id in enumerate(source_ids)}
    classes_covered=sorted({source_to_local[class_id] for r in selected for class_id in r['source_class_ids']})
    qspec=dict(format='V8Q',version=1,domain=metadata['domain'],
               class_count=metadata['class_count'],classes=metadata['classes'],
               source_class_ids=source_ids,reg_max=metadata['reg_max'],
               input_shape=metadata['input_shape'],input_size=metadata['input_size'],
               scales=scales,encoding='symmetric signed int8 [-127,127]',
               rounding='nearest ties to even',accumulator='int32 with static worst-case bound',
               calibration_ids=[r['id'] for r in selected],calibration_split='train',
               calibration_manifest=str(Path(a.manifest).resolve()),
               calibration_manifest_sha256=_sha256(a.manifest),
               calibration_domains=sorted({r['domain'] for r in selected}),
               activation_percentile=a.activation_percentile,
               activation_sampling='deterministic evenly spaced values, at most 512 per image and node',
               classes_covered=classes_covered,
               source_global_class_ids_covered=sorted({class_id for r in selected for class_id in r['source_class_ids']}),
               model_sha256=graph['checkpoint_sha256'],accuracy_accepted=False)
    a.output.mkdir(parents=True,exist_ok=False)
    np.savez(a.output/'weights_int8.npz',**{k:v.numpy() for k,v in params.items()})
    (a.output/'quantization.json').write_text(json.dumps(qspec,indent=2))
    with torch.no_grad():
        image=preprocess(selected[0]['image_path'])
        f=run_float(graph,weights,image); q=run_integer(graph,params,qspec,image)
    report=dict(domain=metadata['domain'],calibration_images=len(selected),
                calibration_ids=[r['id'] for r in selected],
                raw_head_mean_abs_error=[float((x-y).abs().mean()) for x,y in zip(f,q)],
                raw_head_max_abs_error=[float((x-y).abs().max()) for x,y in zip(f,q)],
                accuracy_evaluated=False,note='Raw logit error is not AP acceptance')
    (a.output/'check.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report))


if __name__=='__main__': main()
