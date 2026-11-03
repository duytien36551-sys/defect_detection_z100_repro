"""WMI hidden entry point, decoupled from AI terminal lifetime."""
from pathlib import Path
import os
import sys
import runpy
HERE=Path(__file__).resolve().parent
os.environ['PYTHONIOENCODING']='utf-8'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['YOLO_CONFIG_DIR']=str(HERE.parent/'.ultralytics')
with (HERE/'supervisor_stdout.log').open('a',encoding='utf-8',buffering=1) as out,(HERE/'supervisor_stderr.log').open('a',encoding='utf-8',buffering=1) as err:
    sys.stdout,sys.stderr=out,err
    sys.argv=[str(HERE/'supervise.py')]
    runpy.run_path(str(HERE/'supervise.py'),run_name='__main__')
