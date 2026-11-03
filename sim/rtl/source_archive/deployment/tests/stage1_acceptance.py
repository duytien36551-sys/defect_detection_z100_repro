"""Actual package rejection tests and ARM link-layout reservation check."""
import ctypes
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
FW=ROOT/'firmware'
ARM=Path(r'C:\appload\Vivado\Vitis\2020.2\gnu\aarch32\nt\gcc-arm-none-eabi\bin\arm-none-eabi-gcc.exe')

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--package',type=Path,default=ROOT/'packages/stage28_p9995_integrated')
parser.add_argument('--model',type=Path,default=ROOT/'model/stage28')
parser.add_argument('--output',type=Path,default=ROOT/'validation/stage1')
parser.add_argument('--link-script',type=Path,
                    default=ROOT.parent/'resources/bsp/legacy_lscript.ld')
args=parser.parse_args()
PKG=args.package.resolve(); MODEL=args.model.resolve(); OUT=args.output.resolve(); LINK=args.link_script.resolve()
for path in (PKG,MODEL,OUT):
    if ROOT.resolve() not in path.parents:
        parser.error(f'package, model and output must be under {ROOT}')
OUT.mkdir(parents=True,exist_ok=True)

def command(args):
    p=subprocess.run(list(map(str,args)),capture_output=True,text=True)
    if p.returncode: raise RuntimeError(p.stdout+p.stderr)
    return p.stdout

shim=OUT/'package_shim.c'
shim.write_text('#include "v8_runtime.h"\n#include "v8_generated_model.h"\nint check(const unsigned char*b,size_t n){const unsigned char*p=(const unsigned char*)1;int r=v8_package_open(b,n,&v8_graph,&p);return r ? (p==0 ? r : 999) : (p==b+32 ? 0 : 998);}\n')
dll=OUT/'loader.dll'
command(['gcc','-shared','-std=c11','-Wall','-Wextra','-Werror','-O2','-I',FW,'-I',PKG,shim,FW/'v8_runtime.c','-o',dll])
lib=ctypes.CDLL(str(dll));lib.check.argtypes=[ctypes.c_void_p,ctypes.c_size_t];lib.check.restype=ctypes.c_int
raw=(PKG/'MODEL.V8P').read_bytes();cases={'valid':raw,'empty':b'','short_header':raw[:31],'truncated':raw[:-1],'trailing_bytes':raw+b'x'}
for name,offset in [('magic',0),('version',4),('length',8),('crc_header',12),('nodes',16),('arena',20),('classes',24),('input_size',28),('corrupt_payload',64)]:
    b=bytearray(raw);b[offset]^=1;cases[name]=bytes(b)
results={}
for name,b in cases.items():
    buf=ctypes.create_string_buffer(b);rc=lib.check(buf,len(b));assert rc==0 if name=='valid' else rc<0,(name,rc)
    results[name]={'return_code':rc,'pass':True}
assert lib.check(None,0)<0
results['null_input']={'pass':True}
report=json.loads((PKG/'package.json').read_text(encoding='utf-8'))
graph=json.loads((MODEL/'graph.json').read_text(encoding='utf-8'))
heads=sum(graph['nodes'][i]['shape'][1]*graph['nodes'][i]['shape'][2]*graph['nodes'][i]['shape'][3] for i in graph['outputs'])
# ARM ABI Candidate: 5 floats, int, size_t -> 28 bytes. decoder allocates all multi-label candidates.
candidates=(52*52+26*26+13*13)*18*28+300*4
heap=4*1024*1024;stack=32768
assert candidates<heap
reservations={'model_package':len(raw),'activation_arena':report['arena_bytes'],'input_nchw':519168,'input_rgb':519168,
              'conv_accumulators':report['scratch_bytes'],'dequant_heads':heads*4,'detections':300*24,
              'protocol_response':1048576,'protocol_request':4096,'graph_metadata_reserve':65536,'network_bsp_reserve':8*1024*1024}
source=OUT/'memory_reservation.c'
source.write_text('\n'.join('unsigned char '+k+'['+str(v)+'] __attribute__((aligned(64)));' for k,v in reservations.items())+'\nvoid _vector_table(void){for(;;){}}\n')
local_link=OUT/'lscript.ld';shutil.copy2(LINK,local_link)
elf=OUT/'memory_reservation.elf';mapfile=OUT/'memory_reservation.map'
command([ARM,'-mcpu=cortex-a9','-mfloat-abi=hard','-mfpu=vfpv3','-nostdlib',source,'-Wl,-T,'+str(local_link),'-Wl,-Map,'+str(mapfile),'-Wl,--defsym,_HEAP_SIZE='+str(heap),'-Wl,--defsym,_STACK_SIZE='+str(stack),'-o',elf])
nm=ARM.with_name('arm-none-eabi-nm.exe');symbols=command([nm,'-n',elf]);(OUT/'symbols.txt').write_text(symbols)
text=local_link.read_text();match=re.search(r'ps7_ddr_0\s*:\s*ORIGIN\s*=\s*(0x[\da-fA-F]+),\s*LENGTH\s*=\s*(0x[\da-fA-F]+)',text)
origin,length=map(lambda x:int(x,16),match.groups())
addresses=[int(line.split()[0],16) for line in symbols.splitlines() if len(line.split())>=3 and line.split()[1].upper() in ('B','T','D')]
assert min(addresses)>=origin and max(addresses)<origin+length
for file in ('v8_runtime.c','v8_decode.c','v8_pipeline.c','v8_service.c','v8_sha256.c'):
    command([ARM,'-std=c11','-Wall','-Wextra','-Werror','-mcpu=cortex-a9','-mfloat-abi=hard','-mfpu=vfpv3','-I',FW,'-c',FW/file,'-o',OUT/(file+'.o')])
summary={'package_tests':results,'package_test_count':len(results),'memory_reservations':reservations,'decoder_peak_heap_bytes':candidates,
         'heap_bytes':heap,'stack_bytes':stack,'total_reserved_with_heap_stack':sum(reservations.values())+heap+stack+6144,
         'ddr_origin':hex(origin),'ddr_length':length,'link_script_sha256':hashlib.sha256(LINK.read_bytes()).hexdigest(),
         'arm_reservation_link':'PASS','arm_modules_compile':'PASS','actual_final_firmware_link':False,'note':'Reservation ELF checks declared buffers plus 8MiB BSP/network allowance, not final lwIP/PL firmware. Final firmware map must be checked again.'}
(OUT/'report.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
