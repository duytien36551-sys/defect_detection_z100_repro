"""Compare official checkpoint, lowered float graph, and INT8 graph on one domain."""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
if __package__:
    from .quantize import (_graph_metadata, load_dataset_manifest, load_float,
                          materialize_manifest_record, preprocess, run_float,
                          run_integer, validate_quantization_metadata,
                          verify_selected_image)
else:
    from quantize import (_graph_metadata, load_dataset_manifest, load_float,
                          materialize_manifest_record, preprocess, run_float,
                          run_integer, validate_quantization_metadata,
                          verify_selected_image)
if __package__:
    from .pack_model import validate_calibration_provenance
else:
    from pack_model import validate_calibration_provenance
if __package__:
    from .reference.v8_decode import decode_raw_heads
else:
    from reference.v8_decode import decode_raw_heads
from ultralytics import YOLO
from ultralytics.utils.metrics import ap_per_class, box_iou

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from unified_metrics import summarize_from_images


def match(predictions, targets):
    correct = np.zeros((len(predictions), 10), dtype=bool)
    if not len(predictions) or not targets:
        return correct
    overlaps = box_iou(torch.tensor([t['xyxy'] for t in targets]),
                       torch.tensor([p['xyxy'] for p in predictions])).numpy()
    overlaps *= (np.array([t['class_id'] for t in targets])[:, None] ==
                 np.array([p['class_id'] for p in predictions])[None, :])
    used = np.zeros((len(targets), 10), dtype=bool)
    thresholds = np.linspace(.5, .95, 10)
    for j in np.flatnonzero((overlaps >= .5).any(0)):
        available = np.where(used, 0, overlaps[:, j, None])
        best = available.argmax(0)
        correct[j] = available[best, np.arange(10)] >= thresholds
        used[best, np.arange(10)] |= correct[j]
    return correct


def summarize_single_domain(image_stats, names):
    class_ids = tuple(range(len(names)))
    tp_parts, conf_parts, pred_parts, target_parts = [], [], [], []
    for row in image_stats:
        tp = np.asarray(row['tp'], dtype=bool).reshape(-1, 10)
        conf = np.asarray(row['conf'], dtype=np.float64).reshape(-1)
        pred = np.asarray(row['pred_cls'], dtype=np.int64).reshape(-1)
        target = np.asarray(row['target_cls'], dtype=np.int64).reshape(-1)
        if len(tp) != len(conf) or len(conf) != len(pred):
            raise ValueError('Prediction stats have inconsistent lengths')
        if np.any(~np.isin(target, class_ids)) or np.any(~np.isin(pred, class_ids)):
            raise ValueError('Single-domain result contains an out-of-range class ID')
        tp_parts.append(tp)
        conf_parts.append(conf)
        pred_parts.append(pred)
        target_parts.append(target)
    if not image_stats:
        raise ValueError('No validation images for selected domain')
    tp = np.concatenate(tp_parts)
    conf = np.concatenate(conf_parts)
    pred = np.concatenate(pred_parts)
    target = np.concatenate(target_parts)
    counts = {cid: int(np.count_nonzero(target == cid)) for cid in class_ids}
    if any(count == 0 for count in counts.values()):
        missing = [cid for cid, count in counts.items() if count == 0]
        raise ValueError(f'Missing target classes in validation: {missing}')
    *_, ap, class_index, _p_curve, _r_curve, _f1_curve, _x, _prec = ap_per_class(
        tp, conf, pred, target, plot=False, names={i: name for i, name in enumerate(names)}
    )
    by_id = {int(cid): ap[i] for i, cid in enumerate(class_index)}
    per_class = {
        names[cid]: {'class_id': cid, 'ap50': float(by_id[cid][0]),
                     'ap50_95': float(np.mean(by_id[cid])), 'ground_truth_count': counts[cid]}
        for cid in class_ids
    }
    return {
        'images': len(image_stats),
        'ap50': float(np.mean([per_class[names[cid]]['ap50'] for cid in class_ids])),
        'ap50_95': float(np.mean([per_class[names[cid]]['ap50_95'] for cid in class_ids])),
        'per_class': per_class,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path,
                        help='Explicit checkpoint when it is stored separately from the exported model')
    parser.add_argument('--quant', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True,
                        help='Explicit official records JSON or single-domain data_manifest list')
    parser.add_argument('--calibration-manifest', type=Path,
                        help='Optional relocated calibration manifest; its content hash must match quantization.json')
    parser.add_argument('--domain', choices=('pcb', 'pin', 'joint18'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--limit-per-task', type=int, default=0,
                        help='Quick balanced screen for a joint18 model')
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.limit < 0 or args.limit_per_task < 0:
        parser.error('limits must be nonnegative')
    if args.limit and args.limit_per_task:
        parser.error('choose either --limit or --limit-per-task')

    graph, weights = load_float(args.model)
    metadata = _graph_metadata(graph, args.domain)
    spec = json.loads((args.quant / 'quantization.json').read_text(encoding='utf-8'))
    if spec.get('model_sha256') != graph.get('checkpoint_sha256'):
        raise ValueError('Wrong quantized model')
    validate_quantization_metadata(spec, metadata)
    validate_calibration_provenance(spec, metadata['domain'], metadata['class_count'],
                                    metadata['source_class_ids'], metadata['classes'],
                                    manifest_override=args.calibration_manifest,
                                    quant_dir=args.quant)
    with np.load(args.quant / 'weights_int8.npz', allow_pickle=False) as archive:
        params = {key: torch.from_numpy(archive[key].copy()) for key in archive.files}
    checkpoint = args.checkpoint if args.checkpoint is not None else args.model / 'source.pt'
    model = YOLO(str(checkpoint)).model.float().eval()
    if int(model.model[-1].nc) != metadata['class_count']:
        raise ValueError('Checkpoint class count does not match exported graph')
    model_names = [model.names[index] for index in range(metadata['class_count'])]
    if model_names != metadata['classes']:
        raise ValueError('Checkpoint class order does not match exported graph')

    records, manifest_names = load_dataset_manifest(args.manifest, splits={'val'})
    if manifest_names is not None:
        expected_names = [manifest_names[cid] for cid in metadata['source_class_ids']]
        if expected_names != metadata['classes']:
            raise ValueError('Graph class names/order do not match validation manifest domain')
    evaluation_names = manifest_names if manifest_names is not None else metadata['classes']
    rows = [row for row in records if row['split'] == 'val' and
            (args.domain == 'joint18' or row['domain'] == args.domain)]
    if args.limit:
        rows = rows[:args.limit]
    if args.limit_per_task:
        if args.domain != 'joint18':
            parser.error('--limit-per-task is only valid for --domain joint18')
        all_rows = rows
        rows = [row for task in ('pcb', 'pin')
                for row in [candidate for candidate in all_rows if candidate['domain'] == task][:args.limit_per_task]]
    if not rows:
        raise ValueError(f'Manifest has no validation images for domain {args.domain}')
    if args.domain == 'joint18' and {row['domain'] for row in rows} != {'pcb', 'pin'}:
        raise ValueError('joint18 validation manifest must contain both PCB and PIN images')
    rows = [materialize_manifest_record(row) for row in rows]
    for row in rows:
        verify_selected_image(row)

    source_to_local = {source_id: local_id for local_id, source_id in enumerate(metadata['source_class_ids'])}
    stats = {mode: [] for mode in ('official', 'float', 'int8')}
    started = time.monotonic()
    with torch.inference_mode():
        for index, row in enumerate(rows):
            path = row['image_path']
            image = preprocess(path)
            import cv2
            source = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if source is None:
                raise ValueError(f'Could not decode validation image: {path}')
            height, width = source.shape[:2]
            gain = min(640 / width, 640 / height)
            left = round((640 - round(width * gain)) / 2 - .1)
            top = round((640 - round(height * gain)) / 2 - .1)
            targets = []
            for box in row['boxes']:
                source_id = box['class_id']
                if source_id not in source_to_local:
                    raise ValueError(f'Off-domain validation class ID in record {row["id"]!r}')
                x1, y1, x2, y2 = box['xyxy']
                targets.append(dict(class_id=source_to_local[source_id],
                                     xyxy=[(x1 * width * gain + left) / 640,
                                           (y1 * height * gain + top) / 640,
                                           (x2 * width * gain + left) / 640,
                                           (y2 * height * gain + top) / 640]))
            features = []
            head = model.model[-1]
            hook = head.register_forward_pre_hook(lambda module, values: features.extend(values[0]))
            model(image)
            hook.remove()
            raw = [torch.cat((head.cv2[i](feature), head.cv3[i](feature)), 1)
                   for i, feature in enumerate(features)]
            outputs = {'official': raw, 'float': run_float(graph, weights, image),
                       'int8': run_integer(graph, params, spec, image)}
            for mode, heads in outputs.items():
                detections = decode_raw_heads(
                    [tensor.numpy() for tensor in heads], strides=graph['strides'],
                    input_width=metadata['input_size'], input_height=metadata['input_size'],
                    classes=metadata['class_count'], reg_max=metadata['reg_max'],
                    confidence=.001, iou=.45, max_detections=300
                )
                predictions = [dict(class_id=item.class_id, score=item.score,
                                    xyxy=[item.x1, item.y1, item.x2, item.y2])
                               for item in detections]
                stats[mode].append(dict(task=row['domain'], tp=match(predictions, targets),
                                        conf=[item['score'] for item in predictions],
                                        pred_cls=[item['class_id'] for item in predictions],
                                        target_cls=[item['class_id'] for item in targets]))
            if (index + 1) % 50 == 0:
                print(f'evaluated {index + 1}/{len(rows)} in {time.monotonic() - started:.1f}s', flush=True)

    full_validation = not args.limit and not args.limit_per_task
    result = {'domain': args.domain, 'class_count': metadata['class_count'],
              'classes': metadata['classes'], 'images': len(rows),
              'full_validation': full_validation,
              'per_task_limit': args.limit_per_task or None,
              'elapsed_seconds': time.monotonic() - started,
              'checkpoint_sha256': graph['checkpoint_sha256'],
              'accuracy_accepted': False}
    if full_validation or args.limit_per_task:
        if metadata['class_count'] == 18:
            result['metrics'] = {mode: summarize_from_images(items, evaluation_names)
                                 for mode, items in stats.items()}
            if full_validation:
                result['float_comparison_pass'] = all(
                    result['metrics']['float'][task][key] >= result['metrics']['official'][task][key] - .001
                    for task in ('pcb', 'pin') for key in ('ap50', 'ap50_95'))
                result['int8_comparison_pass'] = all(
                    result['metrics']['int8'][task][key] >= result['metrics']['official'][task][key] - .02
                    for task in ('pcb', 'pin') for key in ('ap50', 'ap50_95'))
        else:
            result['metrics'] = {mode: summarize_single_domain(items, metadata['classes'])
                                 for mode, items in stats.items()}
            if full_validation:
                result['float_comparison_pass'] = all(
                    result['metrics']['float'][key] >= result['metrics']['official'][key] - .001
                    for key in ('ap50', 'ap50_95'))
                result['int8_comparison_pass'] = all(
                    result['metrics']['int8'][key] >= result['metrics']['official'][key] - .02
                    for key in ('ap50', 'ap50_95'))
        if not full_validation:
            result['screen_only'] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'metrics'}))


if __name__ == '__main__':
    main()
