"""Compare real PCB and PIN validation images with the C integer graph."""
import json
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quantize import preprocess, qround, run_integer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=ROOT / 'model/stage28')
    parser.add_argument('--quant', type=Path, default=ROOT / 'quantization/stage28_cal512_p9995')
    parser.add_argument('--package', type=Path, default=ROOT / 'packages/stage28_p9995_integrated')
    parser.add_argument('--report', type=Path, default=ROOT / 'validation/stage4/runtime_parity_both.json')
    args = parser.parse_args()
    model_dir = args.model.resolve()
    quant_dir = args.quant.resolve()
    package = args.package.resolve()
    report_path = args.report.resolve()
    for path in (model_dir, quant_dir, package, report_path.parent):
        if ROOT.resolve() not in path.parents:
            parser.error(f'all input and output paths must be under {ROOT}')
    torch.set_num_threads(1)
    graph = json.loads((model_dir / 'graph.json').read_text(encoding='utf-8'))
    spec = json.loads((quant_dir / 'quantization.json').read_text())
    if spec['model_sha256'] != graph['checkpoint_sha256']:
        raise ValueError('quantization does not match model checkpoint')
    with np.load(quant_dir / 'weights_int8.npz', allow_pickle=False) as z:
        params = {key: torch.from_numpy(z[key].copy()) for key in z.files}
    exe = ROOT / 'tests/runtime_graph_both.exe'
    subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    '-I', str(ROOT / 'firmware'), '-I', str(package),
                    str(ROOT / 'tests/runtime_graph.c'), str(ROOT / 'firmware/v8_runtime.c'),
                    '-lm', '-o', str(exe)], check=True)
    results = []
    output_ids = graph['outputs']
    for task in ('pcb_', 'pin_'):
        image_path = next((ROOT.parent / 'datasets/joint18/images/val').glob(task + '*.jpg'))
        image = preprocess(image_path)
        expected = {}
        started = time.monotonic()
        run_integer(graph, params, spec, image,
                    observe=lambda i, y: expected.update({i: y.detach().cpu().numpy().astype(np.int8)}) if i in output_ids else None)
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            inp, out = temp / 'input.bin', temp / 'heads.bin'
            qround(image.double() / spec['scales']['-1']).numpy().astype(np.int8).tofile(inp)
            run = subprocess.run([str(exe), str(package / 'MODEL.V8P'), str(inp), str(out)],
                                 capture_output=True, text=True, check=True)
            actual = np.fromfile(out, dtype=np.int8)
        sizes = [expected[i].size for i in output_ids]
        if actual.size != sum(sizes):
            raise AssertionError((task, actual.size, sizes))
        errors = []
        offset = 0
        for i, size in zip(output_ids, sizes):
            errors.append(int(np.max(np.abs(actual[offset:offset+size].astype(np.int16) -
                                            expected[i].ravel().astype(np.int16)))))
            offset += size
        result = {'task': task[:-1], 'image': str(image_path), 'head_max_int8_errors': errors,
                  'seconds': round(time.monotonic() - started, 3), 'c_stdout': run.stdout.strip()}
        results.append(result)
        if any(errors):
            raise AssertionError(result)
    report = {'model': str(model_dir.relative_to(ROOT)), 'quant': str(quant_dir.relative_to(ROOT)),
              'package': str(package.relative_to(ROOT)), 'nodes': len(graph['nodes']),
              'host_integer_reference_pass': True, 'cases': results}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
