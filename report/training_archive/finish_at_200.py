"""Autonomous epoch-200 boundary controller; keeps the original 300-epoch LR schedule."""
import argparse
import csv
import ctypes
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUN = HERE / 'runs/pin'
TARGET = 200
CONTROL = HERE / 'finish200_status.json'


def now():
    return datetime.now().astimezone().isoformat()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state(stage, **fields):
    write(CONTROL, dict(state=stage, controller_pid=os.getpid(), target_epoch=TARGET,
                        updated_at=now(), **fields))


def training_processes():
    allowed = {str((HERE / name).resolve()).casefold()
               for name in ('run.py', 'background.py', 'supervise.py')}
    result = []
    for process in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
        try:
            if 'python' not in (process.info['name'] or '').lower():
                continue
            tokens = process.info['cmdline'] or []
            if any(str(Path(token).resolve()).casefold() in allowed
                   for token in tokens if token.lower().endswith('.py')):
                result.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError):
            continue
    return result


def checkpoint_audit(path):
    import torch
    torch.set_num_threads(1)
    checkpoint = torch.load(path, map_location='cpu', weights_only=False)
    assert checkpoint['epoch'] == TARGET - 1, 'Checkpoint must be exactly completed epoch 200'
    for key in ('optimizer', 'scheduler', 'live_state', 'ema', 'rng_python', 'rng_numpy', 'rng_torch'):
        assert checkpoint.get(key) is not None, f'Missing durable checkpoint field: {key}'
    assert checkpoint['optimizer']['state'], 'Optimizer state is empty'
    assert checkpoint['scheduler']['last_epoch'] == TARGET - 1
    return dict(epoch0=checkpoint['epoch'], optimizer_states=len(checkpoint['optimizer']['state']),
                scheduler_last_epoch=checkpoint['scheduler']['last_epoch'],
                live_state_present=True, ema_present=True, rng_present=True,
                checkpoint_sha256=digest(path))


def evaluate(kind, weight_sha):
    out = HERE / 'evaluation/pin' / kind / 'metrics.json'
    if out.exists() and read(out).get('weight_sha256') == weight_sha:
        return read(out)
    plan = read(HERE / 'plan.json')
    state('evaluating', evaluation=kind)
    with (HERE / f'finish200_{kind}_stdout.log').open('ab') as stdout, \
         (HERE / f'finish200_{kind}_stderr.log').open('ab') as stderr:
        result = subprocess.run([plan['python'], '-u', str(HERE / 'run.py'), '--domain', 'pin',
                                 '--evaluate', kind], cwd=ROOT, stdout=stdout, stderr=stderr,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1'))
    assert result.returncode == 0, f'{kind} evaluation failed; inspect finish200 logs'
    metrics = read(out)
    assert metrics['weight_sha256'] == weight_sha, 'Evaluation checkpoint changed'
    assert metrics['images'] == (160 if kind == 'best_original' else 800)
    assert metrics['test_used'] is False
    return metrics


def finalize():
    history = [read(path) for path in sorted(RUN.glob('epoch_*.json'))]
    assert [record['epoch'] for record in history] == list(range(1, TARGET + 1)), 'Epoch records not exactly 1..200'
    with (RUN / 'results.csv').open(encoding='utf-8-sig', newline='') as source:
        csv_epochs = [int(row['epoch']) for row in csv.DictReader(source)]
    assert csv_epochs == list(range(1, TARGET + 1)), 'CSV not exactly 1..200'
    initialization = read(RUN / 'initialization.json')
    assert initialization['pretrained'] is False and initialization['loaded_checkpoint_paths'] == []
    assert (RUN / 'initial_random_state.pt').exists()
    resume = RUN / 'weights/resume.pt'
    audit = checkpoint_audit(resume)
    backup = RUN / 'weights/user_finish_epoch200_resume.pt'
    if not backup.exists():
        shutil.copy2(resume, backup)
    assert digest(backup) == audit['checkpoint_sha256']
    # The marker blocks the original 300-epoch supervisor from restarting after this cutoff.
    (HERE / 'stop').write_text('User authorized finish after completed epoch 200; do not resume 300-epoch training.\n', encoding='utf-8')
    stopped = []
    for process in training_processes():
        try:
            stopped.append(dict(pid=process.pid, command=process.cmdline(), created=process.create_time()))
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(training_processes(), timeout=15)
    assert not alive and not training_processes(), 'Experiment processes still alive; refusing competing evaluation'
    assert not (RUN / 'epoch_201.json').exists(), 'Unexpected completed epoch beyond cutoff'
    # Epoch 201 may have begun briefly; its partial batches are not counted or retained in the checkpoint.
    audit = checkpoint_audit(resume)
    best = max(history, key=lambda record: record['validation']['ap50_95'])
    weight = RUN / 'weights/best.pt'
    weight_sha = digest(weight)
    frozen_best = RUN / 'weights/user_finish_epoch200_best.pt'
    if not frozen_best.exists():
        shutil.copy2(weight, frozen_best)
    assert digest(frozen_best) == weight_sha
    completion = dict(completed_epochs=TARGET, original_schedule_epochs=300,
                      finish_reason='User requested epoch-200 cutoff; original LR and mosaic schedules preserved',
                      best_epoch=best['epoch'], best_selection='Maximum frozen validation AP50:95',
                      seconds=sum(record['seconds'] for record in history), completed_at=now(), test_used=False)
    write(RUN / 'completion.json', completion)
    write(HERE / 'reports/finish200_audit.json', dict(completion=completion, checkpoint=audit,
          initialization=initialization, csv_contiguous=True, epoch_records_contiguous=True,
          stopped_processes=stopped, frozen_best=str(frozen_best), best_sha256=weight_sha,
          partial_next_epoch_discarded=True, split_manifest_sha256=digest(HERE / 'split_manifest.json')))
    state('training_finished', completion=completion)
    full = evaluate('best', weight_sha)
    original = evaluate('best_original', weight_sha)
    assert digest(weight) == weight_sha
    report = dict(completion=completion, checkpoint=audit, best_weight=str(frozen_best),
                  best_sha256=weight_sha, validation=full, original_validation=original,
                  initialization=initialization, test_used=False, int8_evaluated=False,
                  board_evaluated=False, business_acceptance='not_evaluated',
                  caveats=['Augmented validation:800 images/160 source groups; original subset:160 images',
                           'No fair direct comparison to historical validation splits',
                           'No normal images:normal-image false-alarm rate not evaluable',
                           'Known image ancestry is not verified independent physical chips'])
    write(HERE / 'final_report.json', report)
    lines = ['# 光电200轮收尾报告', '', f'最佳轮次：{best["epoch"]}；累计完成轮次：200。',
             f'权重：{frozen_best}', f'SHA-256：{weight_sha}', '',
             '|验证集合|图片数|AP50|AP50:95|P|R|F1|TP|FP|FN|', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for label, metric in [('完整验证集', full), ('原图子集', original)]:
        fixed = metric['fixed_point']
        lines.append(f'|{label}|{metric["images"]}|{metric["ap50"]:.4%}|{metric["ap50_95"]:.4%}|'
                     f'{fixed["precision"]:.4%}|{fixed["recall"]:.4%}|{fixed["f1"]:.4%}|'
                     f'{fixed["tp"]}|{fixed["fp"]}|{fixed["fn"]}|')
    for label, metric in [('完整验证集', full), ('原图子集', original)]:
        lines.extend(['', f'## {label}逐类', '', '|类别|目标数|AP50|AP50:95|召回率|TP|FP|FN|',
                      '|---|---:|---:|---:|---:|---:|---:|---:|'])
        for row in metric['per_class']:
            lines.append(f'|{row["name"]}|{row["targets"]}|{row["ap50"]:.4%}|{row["ap50_95"]:.4%}|'
                         f'{row["recall"]:.4%}|{row["tp"]}|{row["fp"]}|{row["fn"]}|')
        lines.append('')
    lines.append('固定conf=.25/NMS=.45/匹配IoU=.5，同类一对一匹配，max_det=300，不过滤类别。正常图误报率不可评估。未运行测试集、INT8和实板验收。原学习率按300轮计划延续至200轮，未为收尾重算调度。详细证据见final_report.json及reports/finish200_audit.json。')
    (HERE / 'final_report.md').write_text('\n'.join(lines), encoding='utf-8')
    write(HERE / 'status.json', dict(state='completed', stage='finished_at_200', updated_at=now(),
                                     report=str(HERE / 'final_report.json')))
    state('completed', report=str(HERE / 'final_report.json'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        print(json.dumps(dict(target=TARGET, schedule_epochs=read(HERE / 'plan.json')['epochs_per_model'],
                              progress=read(RUN / 'progress.json'),
                              matched_training_pids=[p.pid for p in training_processes()],
                              original_val_images=len((HERE / 'data/val_original_only.txt').read_text().splitlines()),
                              test_used=False), ensure_ascii=False))
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, 'Local\\V8PinFinish200_20261021')
    if not handle or ctypes.get_last_error() == 183:
        return
    try:
        while not (RUN / 'epoch_200.json').exists():
            if (RUN / 'epoch_201.json').exists():
                raise RuntimeError('Already beyond the requested cutoff')
            progress = read(RUN / 'progress.json')
            processes = training_processes()
            state('waiting_for_epoch_200', progress_epoch=progress.get('epoch'),
                  progress_batch=progress.get('batch'), training_pids=[p.pid for p in processes],
                  schedule_epochs=300, learning_rate_schedule_changed=False)
            if not processes:
                raise RuntimeError('Training background absent before epoch 200; inspect original supervisor before recovery')
            time.sleep(.5 if progress.get('epoch', 0) >= 200 else 5)
        finalize()
    except Exception as exc:
        traceback.print_exc()
        state('needs_attention', reason=f'{type(exc).__name__}: {exc}')
        raise


if __name__ == '__main__':
    # WMI starts this entry directly, so capture controller diagnostics locally.
    if '--check' in sys.argv:
        main()
    else:
        with (HERE / 'finish200_stdout.log').open('a', encoding='utf-8', buffering=1) as out, \
             (HERE / 'finish200_stderr.log').open('a', encoding='utf-8', buffering=1) as err:
            sys.stdout, sys.stderr = out, err
            main()
