"""Reproduce frozen detections using package inputs; write results outside this package."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    model = load(ROOT / 'report/current_model_manifest.json')
    # Check the exact export/quantization inputs as well as the deployment V8P.
    paths = [r['path'] for r in model['files']]
    paths += ['data/float_export/graph.json', 'data/quantization/quantization.json',
              'data/quantization/weights_int8.npz', 'data/provenance/canonical_manifest.json',
              'report/selected_sample_predictions.json', 'data/dataset/selected_manifest.json']
    sealed = {r['path']: r for r in load(ROOT / 'report/submission_sha256.json')['files']}
    hashes = {}
    for rel in sorted(set(paths)):
        path = (ROOT / rel).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError(f'Missing package input: {rel}')
        digest = sha(path)
        if digest != sealed[rel]['sha256']:
            raise ValueError(f'Input SHA256 mismatch: {rel}')
        hashes[rel] = digest
    rows = load(ROOT / 'data/dataset/selected_manifest.json')['images']
    references = {r['id']: r['predictions'] for r in
                  load(ROOT / 'report/selected_sample_predictions.json')['rows']}
    if len(rows) != 300 or len({r['id'] for r in rows}) != 300 or set(references) != {r['id'] for r in rows}:
        raise ValueError('Expected exactly 300 unique paired examples and references')
    for row in rows:
        for kind in ('image', 'label'):
            path = (ROOT / 'data/dataset' / row[kind]).resolve()
            if not path.is_relative_to(ROOT / 'data/dataset') or sha(path) != row[kind + '_sha256']:
                raise ValueError(f'Sample SHA256 mismatch: {row["id"]}/{kind}')
    return rows, references, hashes


def compare(actual, expected, atol):
    """Match by class and coordinates without depending on tied-score ordering."""
    remaining = list(expected)
    max_error = 0.0
    if len(actual) != len(remaining):
        return False, None
    for item in actual:
        candidates = []
        for index, ref in enumerate(remaining):
            if item['class_id'] == ref['class_id']:
                error = max(abs(item['confidence'] - ref['confidence']),
                            *(abs(a - b) for a, b in zip(item['xyxy'], ref['xyxy'])))
                candidates.append((error, index))
        if not candidates:
            return False, None
        error, index = min(candidates)
        if not math.isfinite(error) or error > atol:
            return False, error
        max_error = max(max_error, error)
        remaining.pop(index)
    return True, max_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Input hashes only; no inference/network/dependencies')
    parser.add_argument('--backend', choices=('reference', 'board'), default='reference')
    parser.add_argument('--output-dir', type=Path, help='Required for inference; new directory outside package')
    parser.add_argument('--limit', type=int, default=0, help='0=all 300; positive value=explicit partial smoke run')
    parser.add_argument('--host', default='192.168.10.2')
    parser.add_argument('--port', type=int, default=5001)
    parser.add_argument('--local-address')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--atol', type=float, default=None, help='Max absolute normalized-box/score error; reference=1e-5, board=1e-3')
    args = parser.parse_args()
    if not 0 <= args.limit <= 300 or (args.atol is not None and (not math.isfinite(args.atol) or args.atol < 0)):
        parser.error('Invalid limit or tolerance')
    rows, references, hashes = inputs()
    if args.check:
        print(json.dumps(dict(status='PASS_DETECTION_INPUTS', samples=300, hashes=hashes,
                              inference_run=False, board_access=False), indent=2))
        return 0
    if args.output_dir is None:
        parser.error('--output-dir is required for inference')
    output = args.output_dir.resolve()
    if output == ROOT or output.is_relative_to(ROOT) or output.exists():
        parser.error('--output-dir must be new and outside the package')
    output.mkdir(parents=True)
    for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[key] = '1'
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    sys.path.insert(0, str(ROOT))
    import numpy as np
    from src.desktop.preprocess import prepare_image, ImageMapping
    if args.backend == 'reference':
        import torch
        sys.path.insert(0, str(ROOT / 'src/model_pipeline/deployment/candidates/pin640'))
        from quantize import _graph_metadata, run_integer, validate_quantization_metadata
        from reference.v8_decode import decode_raw_heads
        torch.set_num_threads(1)
        graph = load(ROOT / 'data/float_export/graph.json')
        qspec = load(ROOT / 'data/quantization/quantization.json')
        validate_quantization_metadata(qspec, _graph_metadata(graph, 'pin'))
        if qspec['model_sha256'] != graph['checkpoint_sha256'] or qspec['calibration_manifest_sha256'] != hashes['data/provenance/canonical_manifest.json']:
            raise ValueError('Frozen graph/quantization provenance mismatch')
        with np.load(ROOT / 'data/quantization/weights_int8.npz', allow_pickle=False) as archive:
            params = {key: torch.from_numpy(archive[key].copy()) for key in archive.files}

        def infer(payload):
            image = np.frombuffer(payload, dtype=np.uint8).copy().reshape(640, 640, 3)
            tensor = torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0).float() / 255
            with torch.inference_mode():
                heads = run_integer(graph, params, qspec, tensor)
            detections = decode_raw_heads([h.numpy() for h in heads], strides=graph['strides'],
                input_width=640, input_height=640, classes=9, reg_max=16,
                confidence=0.25, iou=0.45, max_detections=300)
            return [dict(class_id=d.class_id, confidence=d.score, xyxy=[d.x1,d.y1,d.x2,d.y2]) for d in detections]
    else:
        from src.desktop.protocol import BoardClient
        client = BoardClient(args.host, args.port,
            model_sha256=hashes['data/pin_epoch200_int8.v8p'],
            class_names=load(ROOT / 'data/model/classes.json')['names'],
            timeout=args.timeout, local_address=args.local_address, allow_host_reference=False)

        def infer(payload):
            # Identity mapping keeps comparisons in normalized model-input space.
            results = client.infer(payload, ImageMapping(640,640,1,0,0,640,640), task='pin')
            return [dict(class_id=d['class_id'], confidence=d['score'], xyxy=[v / 640 for v in d['xyxy']]) for d in results]

    selected = rows[:args.limit] if args.limit else rows
    atol = args.atol if args.atol is not None else (1e-5 if args.backend == 'reference' else 1e-3)
    started = time.monotonic()
    results = []
    for index, row in enumerate(selected, 1):
        _, payload, _ = prepare_image(ROOT / 'data/dataset' / row['image'])
        predictions = infer(payload)
        passed, error = compare(predictions, references[row['id']], atol)
        results.append(dict(id=row['id'], passed=passed, max_absolute_error=error, predictions=predictions))
        if index == 1 or index % 25 == 0 or index == len(selected):
            print(f'{args.backend}: {index}/{len(selected)}, mismatches={sum(not r["passed"] for r in results)}', flush=True)
    failures = [r['id'] for r in results if not r['passed']]
    result = dict(status='FAIL_DETECTION_COMPARISON' if failures else ('PASS_DETECTION_300' if len(results) == 300 else 'PASS_PARTIAL_DETECTION'),
        backend=args.backend, board_access=args.backend == 'board', images=len(results), tolerance=atol,
        elapsed_seconds=time.monotonic()-started, failures=failures, input_hashes=hashes,
        scope='Fixed-model output reproduction against offline integer references; curated showcase, not representative accuracy or throughput.', rows=results)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','input_hashes')}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
