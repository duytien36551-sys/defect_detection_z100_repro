"""Failure-only diagnostics; no reset, no graph command, no source-cache maintenance."""
from pathlib import Path
import hashlib,json,struct,sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,'hardware_workspace\\gpt_acp_output_preserve01');from prepare_launch import sha,require,q
sys.path.insert(0,'hardware_workspace/gpt_acp01')
from review_guarded_elf import elf32_symbols,elf32_symbol_bytes,one
if '--verify' in sys.argv:
    for p,h in json.loads((ROOT/'capture_manifest.json').read_text())['files'].items():require(sha(Path(p))==h,p)
    print('CAPTURE_FILES_VERIFIED');sys.exit(0)
elf=Path('hardware_workspace\\gpt_softpack_build_plan01\\build_output\\native_board_pool.elf');syms=elf32_symbols(elf);addr=lambda n:one(syms,n)['value']
require(addr('board')==5243072 and addr('MMUTable')==5111808,'snapshot fixed identity')
snap=ROOT/'snapshot_scoped.bin';binary=snap.read_bytes()
require(len(binary)==204 and struct.unpack_from('<I',binary,172)[0]==0xeafffffe,'snapshot binary')
require(struct.unpack_from('<I',binary,0xb8)[0]==addr('MMUTable') and struct.unpack_from('<I',binary,0xc8)[0]==addr('board'),'snapshot exact literals')
helper=elf32_symbol_bytes(elf,'Xil_L1ICacheInvalidate',24)
require(helper.hex()=='0130a0e3103f40ee0030a0e3153f07ee4ff07ff51eff2fe1','L1I helper')
s=Path('hardware_workspace/gpt_acp_output_preserve01/launch.tcl').read_text();helpers=s[s.index('proc regval'):s.index('proc wait_for_fsbl_loop')]
capture=s[s.index('proc capture_pl'):s.index('proc run_batch')]
capchecks=s[s.index('    if {[read_word 0x28000]'):s.index('    set first [capture_pl')]
checks='\n'.join(f'    if {{[read_word {addr("Xil_L1ICacheInvalidate")+i:#x}] != {v:#x}}} {{error "L1I helper changed"}}' for i,(v,) in zip(range(0,24,4),struct.iter_unpack('<I',helper)))
snapchecks='\n'.join(f'    if {{[read_word {0x28100+i:#x}] != {v:#x}}} {{error "Snapshot code changed"}}' for i,(v,) in zip(range(0,len(binary),4),struct.iter_unpack('<I',binary)))
out=ROOT/'failure_capture01'
tcl=f'''# Failure diagnostics only. Bind the current epoch49000 ELF and retained OCM.
if {{[catch {{exec py -B {q(Path(__file__))} --verify}} e]}} {{puts stderr $e;exit 2}}
{helpers}
{capture}
proc save_failure {{}} {{
 global cpu0_id cpu1_id
 connect
 lassign [find_targets] fpga_id cpu0_id cpu1_id
 stop_target $cpu1_id
 puts "CPU1_REGISTERS [rrd]"
 stop_target $cpu0_id
 puts "CPU0_REGISTERS_BEFORE [rrd]"
 puts "CPU0_CP15_1 [rrd cp15 1]"
 puts "CPU0_CP15_2 [rrd cp15 2]"
 puts "STOP [mrd -value {addr('zn_native_board_main_stop_code_v2'):#x} 1]"
 if {{[read_word {addr('zn_native_board_configuration_v2')+52:#x}] != 49000}} {{error "Wrong firmware"}}
 if {{([read_word 0xf8000910]&15) != 8 || [read_sctlr] != 0x08c5187d}} {{error "Unexpected memory/cache mapping"}}
 mrd -bin -file {q(out/'board_prefix_dap.bin')} {addr('board'):#x} 32768
 mrd -bin -file {q(out/'irq_guard.bin')} {addr('_irq_stack_end'):#x} 1024
{capchecks}
 set pl [capture_pl $cpu0_id]
 puts "FAILURE_PL $pl"
 mrd -bin -file {q(out/'pl.bin')} 0x21000 27
{checks}
 dow -data {q(snap)} 0x28100
{snapchecks}
 rwr lr 0x2805c
 rwr pc {addr('Xil_L1ICacheInvalidate'):#x}
 con
 after 100
 stop_target $cpu0_id
 if {{[regval pc] != 0x2805c}} {{error "L1I helper return failed"}}
 rwr pc 0x28100
 con
 after 100
 stop_target $cpu0_id
 if {{[regval pc] != 0x281ac || [regval r12] != 0}} {{error "CPU snapshot failed mapping validation"}}
 mrd -bin -file {q(out/'cpu_prefix.bin')} 0x22000 2304
 rwr pc 0x2805c
 stop_target $cpu1_id
 stop_target $cpu0_id
 puts {{FIRST_FAILURE_CAPTURED_NO_RESET_NO_RETRY_NO_SOURCE_MAINTENANCE}}
}}
if {{[catch {{save_failure}} e options]}} {{
 puts stderr "CAPTURE_FAILED: $e"
 foreach id [list $cpu0_id $cpu1_id] {{if {{$id ne {{}}}} {{catch {{stop_target $id}}}}}}
 exit 1
}}
exit 0
'''
(ROOT/'capture_failure.tcl').write_text(tcl,encoding='ascii')
files=[Path(__file__),ROOT/'capture_failure.tcl',elf,snap,Path('hardware_workspace/gpt_acp_cpu_snapshot01/snapshot.elf'),Path('hardware_workspace/gpt_mmio_fault_capture_build01/capture.elf')]
(ROOT/'capture_manifest.json').write_text(json.dumps({'status':'PREPARED_NOT_EXECUTED','files':{str(p):sha(p) for p in files}},indent=2))
print('CAPTURE_PREPARED')
