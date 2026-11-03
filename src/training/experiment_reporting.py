"""Live stage decisions and final artifact assembly for the v8 experiment."""
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def stage_decision(trainer, report):
    from train_experiment import write_json
    history = sorted((read(p) for p in trainer.save_dir.glob('epoch_*.json')), key=lambda x: x['epoch'])
    if report['epoch'] in (5, 10, 20, 30):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        for task in ('PCB', 'PIN'):
            for ax, metric in zip(axes, ('ap50', 'ap50_95')):
                ax.plot([r['epoch'] for r in history], [r['tasks'][task][metric] * 100 for r in history], label=task)
                ax.set(xlabel='Epoch', ylabel=f'{metric} (%)', ylim=(0, 100))
                ax.legend()
                ax.grid(alpha=.25)
        fig.tight_layout()
        fig.savefig(trainer.save_dir / 'task_curves.png', dpi=150)
        plt.close(fig)
    baseline = ROOT / 'baseline/baseline_summary.json'
    if report['epoch'] < 10 or not baseline.exists():
        return
    tasks = read(baseline)['tasks']
    current = report['tasks']
    delta = {k: {metric: current[k][metric] - tasks[k][metric] for metric in ('ap50', 'ap50_95')} for k in ('PCB','PIN')}
    significant = lambda row: all(row['tasks'][k]['ap50'] >= tasks[k]['ap50'] + .05 and
                                   row['tasks'][k]['ap50_95'] >= tasks[k]['ap50_95'] for k in ('PCB','PIN'))
    last_five = history[-5:]
    plateau = len(last_five) == 5 and all(max(r['tasks'][k]['ap50'] for r in last_five) - last_five[0]['tasks'][k]['ap50'] < .005 for k in ('PCB','PIN'))
    behind = any(current[k]['ap50'] < tasks[k]['ap50'] - .05 for k in ('PCB','PIN'))
    decision = 'continue'
    if len(history) >= 2 and significant(report) and significant(history[-2]):
        # Confirm at another checkpoint after epoch ten rather than the first hit.
        if report['epoch'] >= 11:
            decision = 'early_selection_complete'
            trainer.stop = True
    elif behind and plateau:
        decision = 'pause_for_diagnosis'
        trainer.stop = True
    elif (delta['PCB']['ap50'] > 0) != (delta['PIN']['ap50'] > 0):
        decision = 'mixed_task_result_continue_review'
    write_json(trainer.save_dir / 'decision.json', {'epoch': report['epoch'], 'action': decision,
               'delta_vs_v3': delta, 'plateau_window_epochs': [r['epoch'] for r in last_five],
               'reference_only_not_significance_test': True})


def final_report(trainer):
    from train_experiment import write_json, JointValidator
    from unified_metrics import summarize_from_images
    from ultralytics import YOLO
    model = YOLO(str(trainer.best))
    validator = JointValidator(args=dict(data=str(ROOT / 'datasets/joint18/data.yaml'),
              imgsz=416, batch=8, device=str(trainer.device), workers=0, conf=.001,
              iou=.45, max_det=300, plots=True, project=str(trainer.save_dir), name='best_validation'))
    validator(model=model.model)
    images = [dict(item, task=task.lower()) for task, rows in validator.task_stats.items() for item in rows]
    tasks = {k.upper(): v for k, v in summarize_from_images(images, trainer.data['names']).items()}
    history = sorted((read(p) for p in trainer.save_dir.glob('epoch_*.json')), key=lambda x: x['epoch'])
    report = {'completed_epochs': trainer.epoch + 1, 'total_training_and_epoch_validation_seconds': sum(r['seconds'] for r in history),
              'post_warmup_mean_epoch_seconds': sum(r['seconds'] for r in history if r['post_warmup']) / max(1,sum(r['post_warmup'] for r in history)),
              'best_weights': str(trainer.best), 'resume_checkpoint': str(trainer.wdir / 'resume.pt'),
              'tasks': tasks, 'decision': read(trainer.save_dir / 'decision.json') if (trainer.save_dir / 'decision.json').exists() else None,
              'baseline': read(ROOT / 'baseline/baseline_summary.json') if (ROOT / 'baseline/baseline_summary.json').exists() else None,
              'test_used': False}
    write_json(trainer.save_dir / 'final_report.json', report)
    lines = ['# YOLOv8n 联合十八类实验', '', f'已完成 {report["completed_epochs"]} 轮；训练与每轮验证共 {report["total_training_and_epoch_validation_seconds"]/3600:.2f} 小时。', '',
             '|任务|AP50|AP50:95|', '|---|---:|---:|']
    for task, m in tasks.items():
        lines.append(f'|{task}|{m["ap50"]*100:.2f}%|{m["ap50_95"]*100:.2f}%|')
    lines += ['', '逐类指标、基线和决策详见 final_report.json。最佳权重为 weights/best.pt，可恢复文件为 weights/resume.pt。',
              '仅使用固定验证集，未使用封存测试集。COCO 预训练、普通混合采样、增强和优化器与 V3 存在差异，不将收益单独归因于结构。']
    (trainer.save_dir / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
