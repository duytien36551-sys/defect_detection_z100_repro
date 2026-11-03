"""Observe unchanged XPM storage ports during bounded faults, abort and repeated recovery."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from validate_z100_dma_integration import source_manifest, command_tokens

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'deployment/hardware/z100_2026/dma_bram_fault_tests'
BASE_SRC=ROOT/'deployment/hardware/z100_2026/dma_bram_tests'
BIN=Path(r'C:\appload\2026.1\Vivado\bin')
PHYSICAL=ROOT/'deployment/build/z100_dma_integration/s1'
LIBS=('axi_infrastructure_v1_1_0 axi_vip_v1_1_23 processing_system7_vip_v1_0_25 '
      'axi_datamover_v5_1_38 axi_sg_v4_1_21 axi_dma_v7_1_38 generic_baseblocks_v2_1_2 '
      'axi_register_slice_v2_1_37 fifo_generator_v13_2_15 axi_data_fifo_v2_1_37 '
      'axi_crossbar_v2_1_39 axi_protocol_converter_v2_1_38 proc_sys_reset_v5_0_17 '
      'xlconstant_v1_1_11 uvm xilinx_vip unisims_ver unimacro_ver secureip xpm').split()
CASES=dict(
    read_slverr=('READ_RRESP_SLVERR','PASS z100 DMA read RRESP_SLVERR'),
    read_decerr=('READ_RRESP_DECERR','PASS z100 DMA read RRESP_DECERR'),
    bresp=('FAULT_BRESP','PASS z100 DMA fault BRESP_ERROR_RECOVERED'),
    mm2s_abort=('READ_MM2S_ABORT','PASS z100 DMA read MM2S_ABORT'),
    s2mm_abort=('FAULT_TLAST_ABORT','PASS z100 DMA fault TLAST_ABORT'),
    repeated_error=('RETRY_REPEATED_ERROR','PASS z100 DMA retry REPEATED_ERROR'),
    permanent_read=('RETRY_PERMANENT_READ','PASS z100 DMA retry PERMANENT_READ_PENDING'),
    permanent_write=('FAULT_PERSISTENT','PASS z100 DMA fault PERSISTENT_PENDING'))
NEGATIVE={'permanent_read','permanent_write'}


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def mapping():
    text=subprocess.run(['subst'],capture_output=True,text=True,check=True).stdout
    m=re.search(r'^X:\\:\s*=>\s*(.+)$',text,re.M|re.I)
    return Path(m.group(1)).resolve() if m else None


def parse_observers(text,stage):
    rows=[dict(re.findall(r'(\w+)=([^\s]+)',x)) for x in text.splitlines() if x.startswith('BRAM_OBS ')]
    assert len(rows)==2 and {x['width'] for x in rows}=={'39','38'}
    for x in rows:
        channel='mm2s' if x['width']=='39' else 's2mm'
        assert f'gen_{channel}_full' in x['path'] and '.I_DATA_FIFO.blk_mem.' in x['path']
        assert x['path'].endswith('.gen_sdpram.xpm_memory_base_inst.collision_observer')
        assert x['collisions']==x['unknowns']==x['skipped_writes']=='0'
        assert x['init_skip']=='64' and int(x['cycles'])>100
        if stage not in NEGATIVE:
            assert int(x['writes'])>0 and int(x['reads'])>0 and int(x['reset_cycles'])>0
        # A permanent external stall may admit no memory traffic on one channel.
        # Its non-vacuity comes from the actual AXI stall/reset-pending oracle,
        # not from pretending both FIFO access counters were positive.
    return rows


def case_values(text,prefix):
    lines=[x for x in text.splitlines() if x.startswith(prefix)]
    assert len(lines)==1,(prefix,len(lines))
    return dict(re.findall(r'(\w+)=([^\s]+)',lines[0]))


def validate_fault(text,stage):
    if stage in ('read_slverr','read_decerr'):
        x=case_values(text,'COVERAGE read_precondition kind=RRESP_ERROR ')
        code,mask=('10',0x20) if stage=='read_slverr' else ('11',0x40)
        assert x['code']==x['hp0_resp']==x['dma_resp']==code
        assert x['hp0_error_beats']==x['dma_error_beats']=='80'
        assert int(x['tx_sr'],16)&0x770==mask and int(x['expected_mask'],16)==mask
        assert 'reload=PROBE_LOAD_RUN old_tx_poison=1 old_rx_sentinel=1' in text
    elif stage=='bresp':
        x=case_values(text,'COVERAGE bresp_error pre_reset ')
        assert x['hp0_b_handshakes']==x['dma_b_handshakes']=='1'
        assert x['hp0_bresp']==x['dma_bresp']=='10' and int(x['rx_sr'],16)&0x770==0x20
        assert 'COVERAGE fault_bresp reload=PROBE_LOAD_RUN' in text and 'reset_error_clear=1' in text
    elif stage=='mm2s_abort':
        x=case_values(text,'COVERAGE read_precondition kind=AXIS_CUT ')
        assert x['dma_axis']==x['core_axis']=='2' and x['expected_beats']=='80'
        assert x['dma_tlast']==x['core_tlast']==x['axis_ready']==x['task_finish']=='0'
        assert x['axis_valid']=='1' and 'COVERAGE read_recovery kind=0 reload=PROBE_LOAD_RUN' in text
    elif stage=='s2mm_abort':
        x=case_values(text,'COVERAGE axis_precondition scenario=CORE_S2MM_2_OF_5_NO_TLAST ')
        assert x['core_beats']==x['dma_beats']=='2'
        assert all(x[k]=='0' for k in ('core_tlasts','dma_tlasts','source_ready','source_last','dma_valid','dma_last','task_finish'))
        assert x['source_valid']=='1' and 'COVERAGE fault_tlast_abort reload=PROBE_LOAD_RUN' in text
    elif stage=='repeated_error':
        rows=[dict(re.findall(r'(\w+)=([^\s]+)',x)) for x in text.splitlines() if x.startswith('COVERAGE early_error ')]
        assert [x['episode'] for x in rows]==['0','1']
        for x in rows:
            assert all(x[k]=='4' for k in ('hp0_error_beats','dma_error_beats','hp0_r','dma_r'))
            assert x['hp0_rlast']==x['core_tlast']==x['status_error_visible']=='0'
            assert x['polls']==x['poll_limit']=='64' and x['bounded_timeout_trigger']==x['rd_active']=='1'
            assert int(x['tx_sr'],16)==0
        assert len(re.findall(r'^COVERAGE retry_probe episode=\d+.*error_code_still=10 complete=1$',text,re.M))==2
        x=case_values(text,'COVERAGE retry_recovery ')
        assert x['episodes']==x['retained_slots']=='2' and x['fault_cleared']=='1'
    elif stage=='permanent_read':
        x=case_values(text,'COVERAGE permanent_read_poll ')
        assert x['polls']==x['poll_limit']=='200' and x['abort']=='00000002'
        assert x['external_pending']==x['return_hold']=='1' and x['sr_sampled']=='0'
        assert int(x['tx_cr'],16)&4 and int(x['rx_cr'],16)&4
        assert 'COVERAGE permanent_read_expected abort_held=1 no_release=1 no_reload=1 reset_pending=1' in text
    elif stage=='permanent_write':
        x=case_values(text,'COVERAGE persistent_bounded_poll ')
        assert x['poll_count']==x['poll_limit']=='200' and x['abort']=='00000002'
        assert x['external_write_pending']==x['wvalid']=='1' and x['wready']==x['sr_sampled']=='0'
        assert int(x['tx_cr'],16)&4 and int(x['rx_cr'],16)&4
        assert 'COVERAGE persistent_pending_expected reset_bits_still_set=1 abort_held=1 no_release=1 no_reload=1' in text
    if stage not in NEGATIVE:assert 'COVERAGE reset_fence ' in text


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=list(CASES),required=True)
    args=parser.parse_args();stage=args.stage
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    build=ROOT/'deployment/build/z100_bram_fault'/run_id
    out=ROOT/'validation/board_z100/bram_fault_tests'/run_id
    build.mkdir(parents=True);out.mkdir(parents=True)
    integration=True;owned=False;cleanup=False
    commands=[];observers=[];errors=[];sources=[];snapshots=[]
    top='tb_z100_dma_bram_fault'
    files=[BASE_SRC/'bram_collision_observer.sv',SRC/(top+'.sv')]
    if integration:files.append(BASE_SRC/'bind_bram_observers.sv')
    tracked=[*files,Path(__file__),ROOT/'tools/validate_z100_dma_integration.py',
             ROOT/'tools/validate_z100_bram_collision.py',
             ROOT/'deployment/hardware/z100_2026/dma_retry_tests/tb_z100_dma_retry.sv']
    if integration:
        tracked += [Path('C:/appload/2026.1/Vivado/data/ip/xpm/xpm_memory/hdl/xpm_memory.sv'),
                    Path('C:/appload/2026.1/Vivado/data/ip/xpm/xpm_fifo/hdl/xpm_fifo.sv'),
                    Path('C:/appload/2026.1/Vivado/data/ip/xilinx/axi_datamover_v5_1/hdl/axi_datamover_v5_1_rfs.vhd')]
    before={str(p):sha(p) for p in tracked}
    for p in files+[Path(__file__)]:
        dst=out/(p.stem+'.snapshot'+p.suffix);shutil.copy2(p,dst)
        snapshots.append(dict(source=str(p),snapshot=str(dst),sha256=sha(dst)))
    env=os.environ.copy();env['RDI_DATADIR']=str(BIN.parent/'data')
    env['PATH']=str(BIN)+os.pathsep+env.get('PATH','')
    def run(name,exe,arguments):
        argv,line=command_tokens(BIN/exe,arguments);log=out/(name+'.stdout.log')
        item=dict(name=name,argv=argv,command=line,arguments=arguments,log=str(log),return_code=None,timed_out=False)
        start=time.monotonic()
        with log.open('wb') as stream:
            try:item['return_code']=subprocess.run(argv,cwd=build,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=600).returncode
            except subprocess.TimeoutExpired:item['timed_out']=True
        item.update(duration_seconds=round(time.monotonic()-start,3),log_sha256=sha(log));commands.append(item)
        if item['return_code']!=0 or item['timed_out']:raise RuntimeError('tool failed: '+name)
    try:
        if integration:
            if mapping() is not None:raise RuntimeError('X: already owned; refusing to replace mapping')
            subprocess.run(['subst','X:',str(PHYSICAL)],check=True);owned=True
            assert mapping()==PHYSICAL.resolve()
            export=Path('X:/e/xsim')
            shutil.copy2(export/'xsim.ini',build/'xsim.ini')
            sources=source_manifest(ROOT,export,PHYSICAL,files[1])
            assert all(x['exists'] for x in sources)
            run('xvlog_project','xvlog.bat',['--relax','-L','uvm','-L','axi_vip_v1_1_23','-L','processing_system7_vip_v1_0_25','-L','xilinx_vip','-prj',str(export/'vlog.prj')])
            run('xvhdl_project','xvhdl.bat',['--relax','-prj',str(export/'vhdl.prj')])
        run('xvlog_observer_tb','xvlog.bat',['--relax','-sv','-work','xil_defaultlib',*[str(p) for p in files]])
        libraries=[z for lib in (['xil_defaultlib',*LIBS] if integration else ['xil_defaultlib']) for z in ('-L',lib)]
        run('xelab','xelab.bat',['--debug','typical','--relax','--mt','2',*libraries,'--snapshot',top,'xil_defaultlib.'+top,*(['xil_defaultlib.glbl'] if integration else [])])
        run('xsim','xsim.bat',[top,*(['-testplusarg',CASES[stage][0]] if integration else []),'-runall','-log','xsim.log'])
        log=(out/'xsim.stdout.log').read_text(encoding='utf-8',errors='replace')
        marker=CASES[stage][1]
        assert marker in log and not any(x.startswith(('FAIL ','Fatal:')) for x in log.splitlines())
        observers=parse_observers(log,stage)
        validate_fault(log,stage)
    except Exception as exc:errors.append(repr(exc))
    finally:
        if owned:
            if mapping()!=PHYSICAL.resolve():errors.append('owned X: mapping changed; cleanup withheld')
            else:
                subprocess.run(['subst','X:','/D'],check=True);cleanup=mapping() is None
                if not cleanup:errors.append('mapping cleanup failed')
    unchanged=all(sha(p)==h for p,h in before.items())
    for x in sources:
        if sha(x['physical_path']).upper()!=x['sha256']:unchanged=False
    if not unchanged:errors.append('source inputs changed')
    result=dict(status='PASS' if not errors else 'FAIL',run_id=run_id,stage=stage,errors=errors,
        created_at_utc=datetime.now(timezone.utc).isoformat(),commands=commands,observers=observers,
        inputs=[dict(path=p,sha256=h) for p,h in before.items()],snapshots=snapshots,export_sources=sources,
        inputs_unchanged=unchanged,mapping_created=owned,mapping_cleaned=cleanup,mapping_active=mapping() is not None,
        production_hardware_changed=False,production_firmware_changed=False,physical_board_tested=False,
        coverage=[x for x in (out/'xsim.stdout.log').read_text(encoding='utf-8',errors='replace').splitlines() if x.startswith(('COVERAGE ','PASS ','FAIL ','BRAM_OBS '))] if (out/'xsim.stdout.log').exists() else [])
    path=out/'result.json';path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=result['status'],report=str(path),errors=errors)))
    return 0 if not errors else 1


if __name__=='__main__':raise SystemExit(main())
