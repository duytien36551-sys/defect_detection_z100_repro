"""One-shot post-freeze TEST-split evaluation of the frozen epoch200 head_concat package.

Purpose: independent accuracy evidence for the technical report. The model, quantization
and package are frozen (2026-10-24); this run is NOT used for model selection, threshold
tuning or calibration. Run it once; a second run refuses if a previous result exists.

It reuses deployment/candidates/pin640/evaluate_deployment.py unchanged. The only
in-memory change: rows of split 'test' are loaded and relabelled 'val' so the
existing evaluator (which is hard-wired to 'val') consumes them. The original split
is preserved in the report. Metric code = tools/evaluate_pin640_final.summarize_complete
(same as the 800-image validation review).
"""
import hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODEL = ROOT / 'deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/pipeline/model'
CAND = ROOT / 'deployment/candidates/pin640/quant_candidates/epoch200_head_concat_20261024T103836.103919Z'
QUANT = CAND / 'quantization'
MANIFEST = ROOT / 'validation/board_z100/model_readiness_completion/pin_paperstyle_manifest_adapter/canonical_manifest.json'
OUT_ROOT = ROOT / 'validation/board_z100/epoch200_test_once'
EXPECT = {  # frozen identities from epoch200_head_concat_review/20261024T105726.857325Z/result.json
    'package/MODEL.V8P': '65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c',
}
EXPECT_CHECKPOINT = '2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6'


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def frozen_hashes():
    files = [MODEL / 'source.pt', MODEL / 'graph.json', MODEL / 'weights_float.npz',
             QUANT / 'quantization.json', QUANT / 'weights_int8.npz', CAND / 'package/MODEL.V8P', MANIFEST]
    return {str(p.relative_to(ROOT)): sha(p) for p in files}


MIN_FREE_GB = 4.0  # leave headroom for a concurrent Vivado run


def free_mem_gb():
    """Available physical memory on Windows (None elsewhere)."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        m = MS(); m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullAvailPhys / 2**30
    except Exception:
        return None


def peak_rss_gb():
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
        c = PMC(); c.cb = ctypes.sizeof(PMC)
        h = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        return c.PeakWorkingSetSize / 2**30
    except Exception:
        return None


def main():
    free = free_mem_gb()
    if free is not None and free < MIN_FREE_GB:
        print(f'REFUSED: only {free:.1f} GB free physical memory (< {MIN_FREE_GB} GB). '
              'Wait for the running Vivado job to finish, then retry.')
        return 2
    if OUT_ROOT.exists() and any(OUT_ROOT.glob('*/test_metrics.json')):
        print('REFUSED: a test-split result already exists under', OUT_ROOT)
        return 2
    for rel, want in EXPECT.items():
        if sha(CAND / rel) != want:
            print('REFUSED: frozen package hash mismatch', rel)
            return 2
    if sha(MODEL / 'source.pt') != EXPECT_CHECKPOINT:
        print('REFUSED: checkpoint hash mismatch')
        return 2
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = OUT_ROOT / stamp
    out.mkdir(parents=True, exist_ok=False)
    before = frozen_hashes()

    from deployment.candidates.pin640 import evaluate_deployment as ev
    from tools.evaluate_pin640_final import summarize_complete
    from tools.data_relocation_paths import relocate_records
    original_loader = ev.load_dataset_manifest
    seen = {}

    def test_loader(path, splits=None):
        if splits != {'val'}:
            raise RuntimeError('unexpected loader call')
        rows, names = original_loader(path, splits={'test'})
        if not rows or any(r['split'] != 'test' for r in rows):
            raise RuntimeError('test split not isolated')
        seen['test_rows'] = len(rows)
        seen['relocated_image_paths'] = relocate_records(rows, ROOT)
        for r in rows:
            r['split'] = 'val'  # in-memory relabel only, so the val-only evaluator consumes them
        return rows, names

    ev.load_dataset_manifest = test_loader
    ev.summarize_single_domain = summarize_complete
    metrics_path = out / 'test_metrics.json'
    argv = sys.argv
    t0 = time.monotonic()
    report = dict(purpose='one-shot post-freeze test-split evaluation for the report; not used for selection',
                  split='test', started_utc=stamp, frozen_before=before)
    try:
        sys.argv = ['evaluate_deployment.py', '--model', str(MODEL), '--quant', str(QUANT),
                    '--manifest', str(MANIFEST), '--calibration-manifest', str(MANIFEST),
                    '--domain', 'pin', '--output', str(metrics_path)]
        with (out / 'evaluation.log').open('w', encoding='utf-8') as log:
            so, se = sys.stdout, sys.stderr

            class Tee:  # log file + live progress in the console window
                def write(self, s):
                    log.write(s); log.flush()
                    try:
                        so.write(s); so.flush()
                    except Exception:
                        pass

                def flush(self):
                    log.flush()

            sys.stdout = sys.stderr = Tee()
            print('evaluating 800 test images (official / float / int8); progress every 50 images ...', flush=True)
            try:
                ev.main()
            finally:
                sys.stdout, sys.stderr = so, se
        res = json.loads(metrics_path.read_text(encoding='utf-8'))
        m = res['metrics']
        report.update(status='PASS_EVALUATED', images=res['images'], test_rows_loaded=seen.get('test_rows'),
                      relocated_image_paths=seen.get('relocated_image_paths'),
                      official=dict(ap50=m['official']['ap50'], ap50_95=m['official']['ap50_95']),
                      float=dict(ap50=m['float']['ap50'], ap50_95=m['float']['ap50_95']),
                      int8=dict(ap50=m['int8']['ap50'], ap50_95=m['int8']['ap50_95']),
                      int8_loss_pp={k: 100 * (m['official'][k] - m['int8'][k]) for k in ('ap50', 'ap50_95')},
                      test_metrics_sha256=sha(metrics_path))
    except Exception as exc:
        report.update(status='FAILED', error=f'{type(exc).__name__}: {exc}')
    finally:
        sys.argv = argv
        report['elapsed_seconds'] = time.monotonic() - t0
        report['free_mem_gb_at_start'] = free
        report['peak_working_set_gb'] = peak_rss_gb()
        report['frozen_after'] = frozen_hashes()
        if report['frozen_after'] != before:
            report['status'] = 'FAILED_FROZEN_INPUTS_CHANGED'
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report.get(k) for k in ('status', 'images', 'official', 'int8', 'int8_loss_pp', 'error')},
                     ensure_ascii=False))
    print('report:', out / 'report.json')
    return 0 if report['status'] == 'PASS_EVALUATED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
