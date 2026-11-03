"""Durable 30-epoch joint18 experiment. All artifacts stay beside this script."""
import argparse
import copy
import json
import os
from pathlib import Path
import random
import time

ROOT = Path(__file__).resolve().parent
os.environ['YOLO_CONFIG_DIR'] = str(ROOT / '.ultralytics')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
import numpy as np
import torch
from ultralytics import YOLO
from ultralytics.models.yolo.detect import DetectionTrainer, DetectionValidator
from ultralytics.utils.torch_utils import unwrap_model


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


class JointValidator(DetectionValidator):
    def __call__(self, trainer=None, model=None):
        self.stage_epoch = trainer.epoch + 1 if trainer is not None else 'best'
        self.example_counts = {}
        return super().__call__(trainer=trainer, model=model)

    def init_metrics(self, model):
        super().init_metrics(model)
        self.task_stats = {'PCB': [], 'PIN': []}

    def update_metrics(self, preds, batch):
        for si, pred in enumerate(preds):
            prepared = self._prepare_batch(si, batch)
            task = 'PCB' if Path(prepared['im_file']).stem.startswith('pcb_') else 'PIN'
            self.task_stats[task].append({
                **self._process_batch(pred, prepared),
                'conf': pred['conf'].cpu().numpy(),
                'pred_cls': pred['cls'].cpu().numpy(),
                'target_cls': prepared['cls'].cpu().numpy(),
                'target_img': np.unique(prepared['cls'].cpu().numpy()),
                'im_name': Path(prepared['im_file']).name,
            })
            if self.stage_epoch in (5, 10, 20, 30, 'best'):
                self.save_failure_example(task, pred, prepared, batch['img'][si])
        super().update_metrics(preds, batch)

    def save_failure_example(self, task, pred, target, image):
        from ultralytics.utils.metrics import box_iou
        from PIL import Image, ImageDraw
        chosen = pred['conf'] >= .25
        boxes, classes = pred['bboxes'][chosen], pred['cls'][chosen]
        targets = target['bboxes']
        overlaps = box_iou(targets, boxes) if len(boxes) and len(targets) else torch.zeros((len(targets), len(boxes)), device=boxes.device)
        matched = (overlaps >= .5) & (target['cls'][:, None] == classes[None, :])
        flags = {'miss': len(targets) > 0 and not bool(matched.any(1).all()),
                 'false_positive': len(boxes) > 0 and not bool(matched.any(0).all())}
        for kind, exists in flags.items():
            key = (task, kind)
            if not exists or self.example_counts.get(key, 0) >= 3:
                continue
            self.example_counts[key] = self.example_counts.get(key, 0) + 1
            canvas = Image.fromarray((image.cpu().permute(1, 2, 0).numpy() * 255).clip(0, 255).astype('uint8'))
            draw = ImageDraw.Draw(canvas)
            for box, cid in zip(targets.tolist(), target['cls'].tolist()):
                draw.rectangle(box, outline='lime', width=2)
                draw.text((box[0], box[1]), f'GT {int(cid)}', fill='lime')
            for box, cid, score in zip(boxes.tolist(), classes.tolist(), pred['conf'][chosen].tolist()):
                draw.rectangle(box, outline='red', width=2)
                draw.text((box[0], box[3]), f'{int(cid)} {score:.2f}', fill='red')
            label = f'{self.stage_epoch:02d}' if isinstance(self.stage_epoch, int) else self.stage_epoch
            dst = self.save_dir / f'stage_{label}_examples'
            dst.mkdir(exist_ok=True)
            canvas.save(dst / f'{task}_{kind}_{Path(target["im_file"]).stem}.jpg')


class DurableTrainer(DetectionTrainer):
    def get_validator(self):
        self.loss_names = ('box_loss', 'cls_loss', 'dfl_loss')
        return JointValidator(self.test_loader, save_dir=self.save_dir,
                              args=copy.copy(self.args), _callbacks=self.callbacks)

    def save_model(self):
        # Native last/best remain inference-compatible. resume.pt additionally keeps
        # exact live FP32 parameters, optimizer and scheduler rather than EMA/fp16.
        ok = super().save_model()
        if not ok:
            return ok
        ckpt = torch.load(self.last, map_location='cpu', weights_only=False)
        ckpt.update(live_state=copy.deepcopy(unwrap_model(self.model).state_dict()),
                    optimizer=copy.deepcopy(self.optimizer.state_dict()),
                    scheduler=copy.deepcopy(self.scheduler.state_dict()),
                    rng_python=random.getstate(), rng_numpy=np.random.get_state(),
                    rng_torch=torch.get_rng_state(),
                    rng_cuda=torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
                    durable_version=1)
        # Retain full precision EMA for continuation.
        ckpt['ema'] = copy.deepcopy(self.ema.ema).float().cpu()
        for key, value in ckpt['live_state'].items():
            ckpt['live_state'][key] = value.cpu()
        dst = self.wdir / 'resume.pt'
        tmp = self.wdir / 'resume.tmp.pt'
        torch.save(ckpt, tmp)
        os.replace(tmp, dst)
        if self.epoch + 1 in (5, 10, 20, 30):
            import shutil
            shutil.copy2(dst, self.wdir / f'stage_{self.epoch + 1:02d}_resume.pt')
            shutil.copy2(self.last, self.wdir / f'stage_{self.epoch + 1:02d}.pt')
        return ok

    def resume_training(self, ckpt):
        super().resume_training(ckpt)
        if self.resume and ckpt and 'live_state' in ckpt:
            unwrap_model(self.model).load_state_dict(ckpt['live_state'], strict=True)
            self.scheduler.load_state_dict(ckpt['scheduler'])
            random.setstate(ckpt['rng_python'])
            np.random.set_state(ckpt['rng_numpy'])
            torch.set_rng_state(ckpt['rng_torch'])
            if ckpt.get('rng_cuda') and torch.cuda.is_available():
                torch.cuda.set_rng_state_all(ckpt['rng_cuda'])
            write_json(self.save_dir / 'resume_verification.json', {
                'start_epoch': self.start_epoch + 1,
                'optimizer_state_count': len(self.optimizer.state),
                'lr': [g['lr'] for g in self.optimizer.param_groups],
                'scheduler_restored': self.scheduler.state_dict() == ckpt['scheduler'],
                'live_state_restored': all(torch.equal(v.cpu(), ckpt['live_state'][k])
                    for k, v in unwrap_model(self.model).state_dict().items()),
            })


def epoch_start(trainer):
    trainer._durable_epoch_start = time.monotonic()


def epoch_end(trainer):
    if not hasattr(trainer, '_durable_epoch_start'):
        return
    epoch = trainer.epoch + 1
    # final_eval invokes this callback again; do not overwrite training evidence.
    marker = trainer.save_dir / f'epoch_{epoch:02d}.json'
    if marker.exists():
        return
    from unified_metrics import summarize_from_images
    images = [dict(item, task=task.lower()) for task, items in trainer.validator.task_stats.items() for item in items]
    raw_tasks = summarize_from_images(images, trainer.data['names'])
    tasks = {k.upper(): v for k, v in raw_tasks.items()}
    elapsed = time.monotonic() - trainer._durable_epoch_start
    previous = [json.loads(p.read_text(encoding='utf-8')) for p in trainer.save_dir.glob('epoch_*.json')]
    report = {'epoch': epoch, 'seconds': elapsed,
              'cumulative_seconds': sum(x['seconds'] for x in previous) + elapsed,
              'post_warmup': epoch > trainer.args.warmup_epochs,
              'lr': trainer.lr, 'tasks': tasks, 'metrics': trainer.metrics}
    write_json(marker, report)
    write_json(trainer.save_dir / 'progress.json', report)
    from experiment_reporting import stage_decision
    stage_decision(trainer, report)
    if epoch in (5, 10, 20, 30):
        # Evaluation evidence and examples are generated from the stage EMA.
        write_json(trainer.save_dir / f'stage_{epoch:02d}_metrics.json', report)


def training_end(trainer):
    from experiment_reporting import final_report
    final_report(trainer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--name', default='joint18_v8n_30e_416')
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--threads', type=int, default=6)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    run = ROOT / 'runs/train' / args.name
    if run.exists() and not args.resume:
        raise FileExistsError(run)
    model = YOLO(str(args.resume or ROOT / 'weights/yolov8n.pt'))
    model.add_callback('on_train_epoch_start', epoch_start)
    model.add_callback('on_fit_epoch_end', epoch_end)
    model.add_callback('on_train_end', training_end)
    import ultralytics
    write_json(ROOT / 'experiment_environment.json', {
        'torch': torch.__version__, 'ultralytics': ultralytics.__version__,
        'cuda_available': torch.cuda.is_available(), 'threads': args.threads,
        'resume_command': f'.venv/Scripts/python.exe train_experiment.py --resume runs/train/{args.name}/weights/resume.pt',
    })
    model.train(trainer=DurableTrainer, resume=str(args.resume) if args.resume else False,
                data=str(ROOT / 'datasets/joint18/data.yaml'), epochs=30, imgsz=416,
                batch=args.batch, device='0' if torch.cuda.is_available() else 'cpu',
                workers=0, seed=20261008, deterministic=True, cache=False,
                optimizer='SGD', lr0=.01, cos_lr=True, patience=30,
                conf=.001, iou=.45, max_det=300, save=True, save_period=-1,
                project=str(ROOT / 'runs/train'), name=args.name, exist_ok=bool(args.resume),
                plots=True, amp=False)


if __name__ == '__main__':
    main()
