"""Use the existing strict serialized XSim runner in this candidate namespace."""
from pathlib import Path
import sys, ast, json, time, hashlib
sys.path.insert(0,'C:/z100v13/gpt_pl_view_ingress01')
import run_lut_unit
run_lut_unit.OWN=Path(__file__).resolve().parent
original_inspect_host=run_lut_unit.inspect_host
admission_log=run_lut_unit.OWN/'admission_wait.jsonl'
def wait_for_memory():
    """Wait only on resource admission; never repeat a tool or relax a gate."""
    deadline=time.monotonic()+300
    while True:
        try:
            return original_inspect_host()
        except AssertionError as error:
            try: host=ast.literal_eval(str(error))
            except (ValueError,SyntaxError): raise error
            if not isinstance(host,dict) or host.get('vendor') or host.get('disk_gib',0)<20 or host.get('ram_gib',8)>=8:
                raise error
            with admission_log.open('a') as out:
                out.write(json.dumps({'time':time.time(),'state':'WAITING_RAM_BEFORE_TOOL','host':host,'wrapper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})+'\n')
            if time.monotonic()>=deadline: raise error
            time.sleep(5)
run_lut_unit.inspect_host=wait_for_memory
run_lut_unit.main()
