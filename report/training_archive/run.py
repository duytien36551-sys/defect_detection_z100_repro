"""Train or evaluate one independent model; complete durable per-epoch checkpoints."""
import argparse
import copy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
os.environ['YOLO_CONFIG_DIR'] = str(ROOT / '.ultralytics')
import numpy as np
import torch
from ultralytics import YOLO
from ultralytics.models.yolo.detect import DetectionValidator
from train_experiment import DurableTrainer, write_json


def now():
    return datetime.now().astimezone().isoformat()


class DomainValidator(DetectionValidator):
    domain = 'pin'
    baseline = False
    latest = None

    def __call__(self, trainer=None, model=None):
        self.stage_epoch = trainer.epoch + 1 if trainer is not None else 'best'
        if trainer is not None:
            write_json(self.save_dir / 'progress.json', dict(state='validating', epoch=self.stage_epoch,
                                                           epochs=trainer.epochs, validation_images=0, updated_at=now()))
        return super().__call__(trainer=trainer, model=model)

    def plot_val_samples(self, batch, ni):
        if self.baseline and self.domain == 'pin':
            batch = dict(batch)
            batch['cls'] = batch['cls'] + 9
        return super().plot_val_samples(batch, ni)

    def init_metrics(self, model):
        super().init_metrics(model)
        self.rows = []
        self.input_shapes = set()
        DomainValidator.latest = self

    def update_metrics(self, preds, batch):
        self.input_shapes.add(tuple(batch['img'].shape[1:]))
        if self.baseline and self.domain == 'pin':
            batch = dict(batch)
            batch['cls'] = batch['cls'] + 9
        for si, pred in enumerate(preds):
            target = self._prepare_batch(si, batch)
            pred = self._prepare_pred(pred)
            selected = pred['conf'] >= .25
            fixed = {k: v[selected] for k, v in pred.items()}
            tp = self._process_batch(fixed, target)['tp'][:, 0]
            self.rows.append(dict(image=Path(target['im_file']).name,
                                  target_cls=target['cls'].cpu().numpy().astype(int).tolist(),
                                  pred_cls=fixed['cls'].cpu().numpy().astype(int).tolist(),
                                  tp=tp.tolist(), tp_count=int(tp.sum()),
                                  pred_count=int(selected.sum()), normal=len(target['cls']) == 0))
        super().update_metrics(preds, batch)
        if self.training and len(self.rows) % 160 == 0:
            write_json(self.save_dir / 'progress.json', dict(state='validating', epoch=self.stage_epoch,
                                                           epochs=self.args.epochs, validation_images=len(self.rows),
                                                           validation_total=len(self.dataloader.dataset), updated_at=now()))

    def get_stats(self):
        result = super().get_stats()
        offset = 9 if self.baseline and self.domain == 'pin' else 0
        classes = list(range(offset, offset + 9))
        indices = {int(c): i for i, c in enumerate(self.metrics.box.ap_class_index)}
        per_class = []
        for cid in classes:
            support = sum(r['target_cls'].count(cid) for r in self.rows)
            tp = sum(sum(bool(ok) and c == cid for c, ok in zip(r['pred_cls'], r['tp'])) for r in self.rows)
            predicted = sum(r['pred_cls'].count(cid) for r in self.rows)
            ap = self.metrics.box.all_ap[indices[cid]] if cid in indices else np.zeros(10)
            per_class.append(dict(class_id=cid - offset, name=self.names[cid], targets=support,
                                  ap50=float(ap[0]), ap50_95=float(np.mean(ap)),
                                  tp=tp, fp=predicted - tp, fn=support - tp,
                                  precision=tp / predicted if predicted else 0., recall=tp / support if support else None))
        tp = sum(r['tp_count'] for r in self.rows)
        predictions = sum(r['pred_count'] for r in self.rows)
        targets = sum(len(r['target_cls']) for r in self.rows)
        normals = [r for r in self.rows if r['normal']]
        false_normal = sum(r['pred_count'] > 0 for r in normals)
        self.report = dict(domain=self.domain, baseline_joint18=self.baseline, images=len(self.rows),
                           normal_images=len(normals), targets=targets,
                           ap50=float(np.mean([c['ap50'] for c in per_class])),
                           ap50_95=float(np.mean([c['ap50_95'] for c in per_class])), per_class=per_class,
                           fixed_point=dict(confidence=.25, nms_iou=.45, match_iou=.5, max_det=300,
                                            matching='Installed Ultralytics same-class IoU greedy one-to-one matching, recomputed after confidence filtering',
                                            classes_filtered=False, tp=tp, fp=predictions - tp, fn=targets - tp,
                                            precision=tp / predictions if predictions else 0., recall=tp / targets if targets else None,
                                            f1=2 * tp / (predictions + targets) if predictions + targets else 0.,
                                            cross_domain_false_predictions=sum(sum(c not in classes for c in r['pred_cls']) for r in self.rows),
                                            normal_false_images=false_normal,
                                            normal_false_image_rate=false_normal / len(normals) if normals else None),
                           evaluation=dict(imgsz=640, actual_input_shapes=sorted(self.input_shapes), batch=16, rect=True, conf=.001, nms_iou=.45, max_det=300),
                           test_used=False)
        return result


class DomainTrainer(DurableTrainer):
    def get_validator(self):
        self.loss_names = ('box_loss', 'cls_loss', 'dfl_loss')
        return DomainValidator(self.test_loader, save_dir=self.save_dir,
                               args=copy.copy(self.args), _callbacks=self.callbacks)


class ScratchTrainer(DomainTrainer):
    def check_resume(self, overrides):
        super().check_resume(overrides)
        plan = json.loads((HERE / 'plan.json').read_text(encoding='utf-8'))
        domain = Path(self.args.name).name
        self.args.epochs = plan['domains'][domain].get('epochs', plan['epochs_per_model'])

    def get_model(self, cfg=None, weights=None, verbose=True):
        fresh = not self.args.resume
        if fresh:
            assert weights is None, 'Random initialization cannot accept transferred weights'
            assert self.args.pretrained is False
        model = super().get_model(cfg=cfg, weights=weights, verbose=verbose)
        if fresh:
            assert model.model[-1].nc == 9
            fingerprint = hashlib.sha256()
            state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            for key, value in state.items():
                fingerprint.update(key.encode('utf-8'))
                fingerprint.update(value.numpy().tobytes())
            record = dict(initialization='RANDOM_FROM_ARCHITECTURE_ONLY', pretrained=False,
                          weights_argument_was_none=True, loaded_checkpoint_paths=[],
                          seed=self.args.seed, nc=9, created_at=now(),
                          parameter_count=sum(p.numel() for p in model.parameters()),
                          initial_state_sha256=fingerprint.hexdigest(),
                          architecture_yaml=str(self.args.model))
            path = self.save_dir / 'initial_random_state.pt'
            assert not path.exists(), 'Refusing to overwrite original random initialization evidence'
            torch.save(dict(state_dict=state, provenance=record), path)
            write_json(self.save_dir / 'initialization.json', record)
        return model


def epoch_start(t):
    t._durable_epoch_start = time.monotonic()
    t._domain_batch = 0
    write_json(t.save_dir / 'progress.json', dict(state='training', epoch=t.epoch + 1, epochs=t.epochs,
                                                batch=0, batches=len(t.train_loader), updated_at=now()))


def batch_end(t):
    t._domain_batch += 1
    if t._domain_batch % 20 == 0 or t._domain_batch == len(t.train_loader):
        write_json(t.save_dir / 'progress.json', dict(state='training', epoch=t.epoch + 1, epochs=t.epochs,
                                                    batch=t._domain_batch, batches=len(t.train_loader), updated_at=now()))


def epoch_end(t):
    # Native final_eval runs this hook after incrementing trainer.epoch and
    # independently validating best.pt. It is evaluation, not epoch 101.
    if t.epoch + 1 > t.epochs or not t.validator.training:
        return
    path = t.save_dir / f'epoch_{t.epoch + 1:03d}.json'
    if path.exists():
        return
    record = dict(epoch=t.epoch + 1, seconds=time.monotonic() - t._durable_epoch_start,
                  metrics=t.metrics, lr=t.lr, validation=t.validator.report, updated_at=now(), test_used=False)
    write_json(path, record)
    write_json(t.save_dir / 'progress.json', dict(state='epoch_completed', **record))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--domain', choices=['pin', 'pcb'], required=True)
    parser.add_argument('--resume')
    parser.add_argument('--evaluate', choices=['baseline', 'best', 'best_original'])
    args = parser.parse_args()
    plan = json.loads((HERE / 'plan.json').read_text(encoding='utf-8'))
    config = plan['domains'][args.domain]
    target_epochs = config.get('epochs', plan['epochs_per_model'])
    assert hashlib.sha256(Path(config['data']).read_bytes()).hexdigest() == config['data_sha256']
    if args.evaluate == 'best_original':
        config = dict(config, data=str(HERE / 'data/data_original_holdout.yaml'))
    torch.set_num_threads(plan['threads'])
    DomainValidator.domain = args.domain
    DomainValidator.baseline = args.evaluate == 'baseline'
    run = HERE / 'runs' / args.domain
    if args.evaluate:
        weight = Path(plan['baseline_source'] if args.evaluate == 'baseline' else run / 'weights/best.pt')
        expected = plan['baseline_source_sha256'] if args.evaluate == 'baseline' else None
        digest = hashlib.sha256(weight.read_bytes()).hexdigest()
        if expected:
            assert digest == expected
        out = HERE / 'evaluation' / args.domain / args.evaluate
        YOLO(str(weight)).val(validator=DomainValidator, data=config['data'], imgsz=640, batch=plan['batch'],
                              device=plan['device'], workers=0, rect=True, conf=.001, iou=.45, max_det=300,
                              plots=True, project=str(out.parent), name=out.name, exist_ok=True)
        report = DomainValidator.latest.report
        report.update(weight=str(weight), weight_sha256=digest, evaluated_at=now(),
                      operating_threshold_selected_on_test=False, training_quality_metrics_not_evaluated=True)
        write_json(out / 'metrics.json', report)
        write_json(out / 'per_image_fixed_point.json', DomainValidator.latest.rows)
        return
    if not args.resume and (run / 'results.csv').exists():
        raise FileExistsError('Existing training run; use verified full resume checkpoint')
    if args.resume:
        assert Path(args.resume).resolve() == (run / 'weights/resume.pt').resolve(), 'Resume only this paper-style run'
        initialization = json.loads((run / 'initialization.json').read_text(encoding='utf-8'))
        assert initialization['pretrained'] is False and initialization['loaded_checkpoint_paths'] == []
    if not args.resume:
        assert plan['pretrained'] is False and plan['trained_weights_loaded_for_initialization'] is False
        assert hashlib.sha256(Path(config['architecture_yaml']).read_bytes()).hexdigest() == config['architecture_yaml_sha256']
    model = YOLO(args.resume or config['architecture_yaml'])
    if not args.resume:
        assert not model.ckpt, 'A fresh run must not load any checkpoint'
    assert model.model.model[-1].nc == 9
    model.add_callback('on_train_epoch_start', epoch_start)
    model.add_callback('on_train_batch_end', batch_end)
    model.add_callback('on_fit_epoch_end', epoch_end)
    model.train(trainer=ScratchTrainer, resume=args.resume or False, pretrained=False, data=config['data'], epochs=target_epochs,
                imgsz=640, batch=plan['batch'], device=plan['device'], workers=0, seed=plan['seed'], deterministic=True, nbs=32,
                cache=False, optimizer='SGD', lr0=plan['lr0'], lrf=plan['lrf'], cos_lr=plan['cos_lr'],
                warmup_epochs=3, warmup_bias_lr=plan['warmup_bias_lr'], mosaic=plan['mosaic'], close_mosaic=10, mixup=0., copy_paste=0.,
                scale=plan['scale'], translate=plan['translate'], degrees=0., fliplr=.5, hsv_h=.015, hsv_s=.7, hsv_v=.4,
                patience=target_epochs, conf=.001, iou=.45, max_det=300, save=True, save_period=-1,
                project=str(HERE / 'runs'), name=args.domain, exist_ok=True, plots=True, amp=False)
    history = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(run.glob('epoch_*.json'))]
    assert [r['epoch'] for r in history] == list(range(1, target_epochs + 1))
    best = max(history, key=lambda r: r['metrics']['metrics/mAP50-95(B)'])
    write_json(run / 'completion.json', dict(completed_epochs=target_epochs, best_epoch=best['epoch'],
                                            seconds=sum(r['seconds'] for r in history),
                                            completed_at=now(), test_used=False))


if __name__ == '__main__':
    main()
