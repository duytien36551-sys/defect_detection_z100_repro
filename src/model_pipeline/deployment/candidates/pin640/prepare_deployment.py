"""Reproducibly prepare an isolated checkpoint for deployment, without touching training."""
import argparse,subprocess,sys,json
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True,
                   help='Explicit train/validation manifest used for calibration and optional evaluation')
    p.add_argument('--domain',choices=('pin',),required=True,
                   help='PIN640 checkpoint/data domain')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--per-task',type=int,default=256)
    p.add_argument('--evaluate',action='store_true',help='Run full fixed validation comparison')
    a=p.parse_args();out=a.output.resolve()
    if ROOT not in out.parents:raise ValueError('Output must stay under deployment')
    if a.checkpoint.name in ('last.pt','best.pt','resume.pt'):
        raise ValueError('Use an immutable stage checkpoint or frozen final copy, not a live training checkpoint')
    out.mkdir(parents=True,exist_ok=False)
    def run(script,*args):subprocess.run([sys.executable,str(ROOT/script),*map(str,args)],check=True)
    run('export_graph.py','--checkpoint',a.checkpoint,'--domain',a.domain,'--output',out/'model')
    run('quantize.py','--model',out/'model','--manifest',a.manifest,'--domain',a.domain,
        '--per-task',a.per_task,'--output',out/'quantization')
    run('pack_model.py','--model',out/'model','--quant',out/'quantization',
        '--output',out/'package','--manifest',a.manifest)
    if a.evaluate:
        run('evaluate_deployment.py','--model',out/'model','--quant',out/'quantization',
            '--manifest',a.manifest,'--domain',a.domain,'--output',out/'validation.json')
    graph=json.loads((out/'model'/'graph.json').read_text(encoding='utf-8'))
    status={'package_created':True,'domain':graph['domain'],'class_count':graph['class_count'],
            'accuracy_evaluated':a.evaluate,'accuracy_accepted':False,
            'firmware_instruction':'Rebuild ARM with this generated header and exact MODEL.V8P; deploy only matching V8 bitstream.'}
    (out/'status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')

if __name__=='__main__':main()
