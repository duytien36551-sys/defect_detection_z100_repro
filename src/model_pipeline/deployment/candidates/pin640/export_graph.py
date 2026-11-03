"""Lower the actual YOLOv8 checkpoint into explicit, BN-folded primitive operations."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


def execute(node, values, weights):
    x = [values[i] for i in node['inputs']]
    op, p = node['op'], node.get('params', {})
    if op == 'conv':
        return F.conv2d(x[0], weights[node['weight']], weights[node['bias']], **p)
    if op == 'silu': return F.silu(x[0])
    if op == 'slice': return x[0][:, p['start']:p['end']]
    if op == 'concat': return torch.cat(x, 1)
    if op == 'add': return x[0] + x[1]
    if op == 'maxpool': return F.max_pool2d(x[0], **p)
    if op == 'upsample': return F.interpolate(x[0], **p)
    raise ValueError(f'Unsupported operation {op}')


class Lower:
    def __init__(self, image):
        self.nodes, self.weights = [], {}
        self.values = {-1: image}

    def emit(self, op, inputs, **kwargs):
        n = dict(id=len(self.nodes), op=op, inputs=inputs, **kwargs)
        y = execute(n, self.values, self.weights)
        n['shape'] = list(y.shape)
        self.values[n['id']] = y
        self.nodes.append(n)
        return n['id']

    def module(self, m, x):
        kind = type(m).__name__
        if kind in ('Conv', 'DWConv'):
            c = copy.deepcopy(m.conv)
            if hasattr(m, 'bn'):
                c = torch.nn.utils.fusion.fuse_conv_bn_eval(c, m.bn)
            y = self.module(c, x)
            if isinstance(m.act, nn.SiLU): return self.emit('silu', [y])
            if isinstance(m.act, nn.Identity): return y
            raise ValueError(f'Unsupported activation {m.act}')
        if isinstance(m, nn.Conv2d):
            key = f'n{len(self.nodes)}'
            self.weights[key+'_w'] = m.weight.detach().clone()
            self.weights[key+'_b'] = (m.bias.detach().clone() if m.bias is not None else torch.zeros(m.out_channels))
            return self.emit('conv', [x], weight=key+'_w', bias=key+'_b', params=dict(stride=m.stride, padding=m.padding, dilation=m.dilation, groups=m.groups))
        if isinstance(m, nn.Sequential):
            for item in m: x = self.module(item, x)
            return x
        if kind == 'Bottleneck':
            y = self.module(m.cv2, self.module(m.cv1, x))
            return self.emit('add', [x,y]) if m.add else y
        if kind == 'C2f':
            y = self.module(m.cv1,x)
            parts = [self.emit('slice',[y],params=dict(start=i*m.c,end=(i+1)*m.c)) for i in range(2)]
            for item in m.m: parts.append(self.module(item,parts[-1]))
            return self.module(m.cv2,self.emit('concat',parts))
        if kind == 'SPPF':
            parts = [self.module(m.cv1,x)]
            for _ in range(getattr(m,'n',3)):
                parts.append(self.emit('maxpool',[parts[-1]],params=dict(kernel_size=m.m.kernel_size,stride=m.m.stride,padding=m.m.padding)))
            y = self.module(m.cv2,self.emit('concat',parts))
            return self.emit('add',[x,y]) if getattr(m,'add',False) else y
        if isinstance(m,nn.Upsample):
            return self.emit('upsample',[x],params=dict(scale_factor=m.scale_factor,mode=m.mode))
        if kind == 'Concat': return self.emit('concat',x)
        raise ValueError(f'Unsupported module {kind}; no silent fallback')


def memory_plan(nodes, outputs, budget):
    last = {-1:0}
    for n in nodes:
        for source in n['inputs']: last[source] = n['id']
    for out in outputs: last[out]=len(nodes)
    # Conservative float reference / byte deployment sizes, reusable first-fit blocks.
    free, active, top, plan = [], {}, 0, []
    for n in nodes:
        for key,(offset,size) in list(active.items()):
            if last.get(key,-1)<n['id']:
                free.append((offset,size)); del active[key]
        merged=[]
        for offset,size in sorted(free):
            if merged and merged[-1][0]+merged[-1][1]==offset:
                merged[-1]=(merged[-1][0],merged[-1][1]+size)
            else: merged.append((offset,size))
        free=merged
        size=(int(np.prod(n['shape']))+63)//64*64
        slot=next((i for i,b in enumerate(free) if b[1]>=size),None)
        if slot is None: offset=top; top+=size
        else:
            offset,length=free.pop(slot)
            if length>size: free.append((offset+size,length-size))
        active[n['id']]=(offset,size)
        plan.append(dict(node=n['id'],offset=offset,bytes=size,last_use=last.get(n['id'],n['id'])))
    return dict(layout='NCHW int8; input and parameters separate',arena_bytes=top,budget_bytes=budget,
                fits_budget=top<=budget,allocations=plan)


def ordered_class_names(names, count):
    """Return checkpoint class names in local class-id order and validate them."""
    try:
        ordered = [names[i] for i in range(count)]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('Checkpoint class names must be indexed from zero') from exc
    if any(not isinstance(name, str) or not name.strip() for name in ordered):
        raise ValueError('Class names must be nonempty strings')
    if len(set(ordered)) != len(ordered):
        raise ValueError('Class names must be unique')
    return ordered


def validate_domain_class_names(names, domain):
    """Reject checkpoints whose ordered names contradict their declared task."""
    if domain == 'pcb' and (len(names) != 9 or any(not name.startswith('PCB_') for name in names)):
        raise ValueError('PCB checkpoints must have nine PCB_-prefixed class names')
    if domain == 'pin' and (len(names) != 9 or any(not isinstance(name,str) or
            not name.startswith('PIN_') or len(name)<=4 or name.strip()!=name for name in names)):
        raise ValueError('PIN checkpoints must have nine PIN_-prefixed class names')
    if domain == 'joint18':
        if (len(names) != 18 or any(not name.startswith('PCB_') for name in names[:9]) or
                any(not name.startswith('PIN_') for name in names[9:])):
            raise ValueError('joint18 checkpoints must order nine PCB_ then nine PIN_ class names')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--domain',choices=('pin',),required=True,
                   help='PIN640 supports one nine-class PIN checkpoint')
    p.add_argument('--arena-bytes',type=int,default=8388608,help='PIN640 candidate arena budget; linked memory still requires verification')
    a=p.parse_args()
    torch.set_num_threads(1)
    from ultralytics import YOLO
    a.output.mkdir(parents=True,exist_ok=False)
    # Use a complete stage checkpoint, never a live last.pt being overwritten.
    raw=a.checkpoint.read_bytes()
    snapshot=a.output/'source.pt'; snapshot.write_bytes(raw)
    model=YOLO(str(snapshot)).model.float().eval()
    class_count = int(model.model[-1].nc)
    if class_count != 9 or a.domain != 'pin':
        raise ValueError(f'PIN640 requires nine PIN classes, got {class_count}')
    domain = a.domain
    class_names = ordered_class_names(model.names, class_count)
    validate_domain_class_names(class_names, domain)
    source_class_ids = list(range(9, 18)) if domain == 'pin' else list(range(class_count))
    torch.manual_seed(42)
    image=torch.rand(1,3,640,640)
    lower=Lower(image); saved=[]; x=-1
    comparisons=[]
    with torch.no_grad():
        for m in model.model:
            sources=x if m.f==-1 else saved[m.f] if isinstance(m.f,int) else [x if i==-1 else saved[i] for i in m.f]
            if type(m).__name__=='Detect':
                if m.end2end: raise ValueError('Unsupported end2end head')
                heads=[]
                for i,s in enumerate(sources):
                    b=lower.module(m.cv2[i],s); c=lower.module(m.cv3[i],s)
                    head=lower.emit('concat',[b,c]); heads.append(head)
                    expected=torch.cat((m.cv2[i](lower.values[s]),m.cv3[i](lower.values[s])),1)
                    comparisons.append(float((expected-lower.values[head]).abs().max()))
                reg_max=m.reg_max; strides=m.stride.tolist(); break
            x=lower.module(m,sources); saved.append(x)
        # Full-network comparison against original backbone and raw head branches.
        captured=[]
        handle=model.model[-1].register_forward_pre_hook(lambda mod,args: captured.extend([v.detach() for v in args[0]]))
        model(image); handle.remove()
        full_errors=[]
        for i,h in enumerate(heads):
            expected=torch.cat((m.cv2[i](captured[i]),m.cv3[i](captured[i])),1)
            full_errors.append(float((expected-lower.values[h]).abs().max()))
    graph=dict(format='V8GRAPH',version=1,domain=domain,class_count=class_count,
               input_size=640,input_shape=[1,3,640,640],classes=class_names,
               source_class_ids=source_class_ids,
               nodes=lower.nodes,outputs=heads,reg_max=reg_max,strides=strides,decode='ARM DFL; raw regression then class logits',
               preprocessing=dict(rgb=True,padding=114,normalization='pixel/255',resize='opencv INTER_LINEAR letterbox'),
               checkpoint_sha256=hashlib.sha256(raw).hexdigest())
    np.savez(a.output/'weights_float.npz',**{k:v.numpy() for k,v in lower.weights.items()})
    (a.output/'graph.json').write_text(json.dumps(graph,ensure_ascii=False,indent=2),encoding='utf-8')
    memory=memory_plan(lower.nodes,heads,a.arena_bytes)
    (a.output/'memory_plan.json').write_text(json.dumps(memory,indent=2))
    report=dict(nodes=len(lower.nodes),head_shapes=[lower.nodes[h]['shape'] for h in heads],max_abs_raw_head_error=full_errors,
                float_tensor_check_pass=max(full_errors)<0.001,accuracy_evaluated=False,memory_fits=memory['fits_budget'])
    (a.output/'export_check.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    if not report['float_tensor_check_pass']: raise RuntimeError('Raw head equivalence failed')
    if not memory['fits_budget']: print('DEPLOYMENT BLOCK: PIN640 candidate arena budget exceeded')


if __name__=='__main__': main()
