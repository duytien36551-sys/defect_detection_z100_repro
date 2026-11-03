"""Stage full-backend drain assertions; execute only the small monitor selftest.

Never compiles the full RTL closure, queries Vivado, or starts the full model.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import validate_z100_graph_executor_followup as g

ROOT=g.ROOT
MONITOR=ROOT/'deployment/tests/graph_followup/z100_backend_drain_monitor.sv'
TEST=MONITOR.with_name('tb_z100_backend_drain_monitor.sv')
PRIOR=ROOT/'validation/board_z100/guard_v3_numeric_residency/20261027T004725.231667Z/result.json'
LOCAL=ROOT/'deployment/build/local_tools/iverilog13_msys2/ucrt64'

INSTANCE='''
    wire [7:0] physical_drain_violations;
    z100_backend_drain_monitor physical_drain_monitor(
        .clk(clk),.rst_n(rst_n),.command_fire(backend_cmd_valid&&backend_cmd_ready),
        .cancel(dut.u_conv_backend.datapath_cancel),.all_io_quiet(all_io_quiet),
        .drain_complete(drain_complete),.producer_complete(producer_complete),
        .arvalid(m_axi_arvalid),.arready(m_axi_arready),.rvalid(m_axi_rvalid),
        .rready(m_axi_rready),.rlast(m_axi_rlast),.awvalid(m_axi_awvalid),
        .awready(m_axi_awready),.wvalid(m_axi_wvalid),.wready(m_axi_wready),
        .wlast(m_axi_wlast),.bvalid(m_axi_bvalid),.bready(m_axi_bready),
        .violations(physical_drain_violations));
    always @(posedge clk) if(rst_n && physical_drain_violations!==8'b0)
        $fatal(1,"BACKEND_PHYSICAL_DRAIN_VIOLATION flags=%h",physical_drain_violations);
'''


def main():
    out=ROOT/'validation/board_z100/guard_v3_drain_monitor'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True,exist_ok=False)
    r=dict(status='PREPARING',commands={},routing_inspected=False,board_access=False,
           full_backend_compiled=False,full_backend_executed=False,physical_drain_accepted=False,
           physical_30fps_accepted=False)
    try:
        prior=json.loads(PRIOR.read_text())
        original=ROOT/prior['build_dir']/'tb_z100_native_conv_mmio_first_event_guard_v3.sv'
        # Bind only known inputs; the old simulation was interrupted, never a pass.
        key=g.relative(original)
        g.require(g.sha256(original)==prior['artifact_sha256'][key],'numeric fixture drift')
        text=original.read_text()
        g.require(text.count('endmodule')==1,'single top seam')
        staged=out/'tb_guard_v3_numeric_with_drain_monitor.sv'
        staged.write_text(text.replace('endmodule',INSTANCE+'\nendmodule'),encoding='utf8')
        g.require(staged.read_text().replace(INSTANCE+'\n','')==text,'original numeric assertions changed')
        pins=[Path(__file__),MONITOR,TEST,PRIOR,original,staged,LOCAL/'bin/iverilog.exe',LOCAL/'bin/vvp.exe']
        r['source_sha256_before']=g.hashes(pins)
        binary=out/'monitor_selftest.vvp'
        commands=[('compile_monitor_only',[LOCAL/'bin/iverilog.exe','-B',LOCAL/'lib/ivl','-g2012','-Wall',
                    '-s','tb_z100_backend_drain_monitor','-o',binary,MONITOR,TEST]),
                  ('selftest_monitor_only',[LOCAL/'bin/vvp.exe','-M',LOCAL/'lib/ivl',binary])]
        gate=int(4.25*1024**3)
        for name,argv in commands:
            item=g.run_guarded(argv,ROOT,out/(name+'.log'),gate,timeout_seconds=30)
            r['commands'][name]=item
            g.require(item['return_code']==0 and not item['stopped_for_memory_guard'] and not item['timed_out'],name)
        log=(out/'selftest_monitor_only.log').read_text()
        g.require(log.count('DRAIN_MONITOR_SELFTEST_PASS ')==1 and 'backend=0 numerical=0 physical=0' in log,'monitor test failed')
        r['monitor_output']=log.strip()
        # Append the observer to the old source list, but never execute this plan.
        compile_plan=[str(v) for v in prior['steps'][0]['argv']]
        compile_plan=[str(staged) if v==str(original) else v for v in compile_plan]
        compile_plan[compile_plan.index('-o')+1]=str(out/'full_backend_NOT_COMPILED.vvp')
        compile_plan.append(str(MONITOR))
        r['full_backend_compile_plan_not_executed']=compile_plan
        r['source_sha256_after']=g.hashes(pins)
        g.require(r['source_sha256_before']==r['source_sha256_after'],'input drift')
        r['artifact_sha256']=g.hashes([binary,staged,out/'compile_monitor_only.log',out/'selftest_monitor_only.log'])
        r['status']='PASS_MONITOR_SELFTEST_FULL_BACKEND_ASSERTIONS_STAGED_NOT_EXECUTED'
    except Exception as exc:
        r.update(status='FAILED_CLOSED',error=repr(exc))
    (out/'result.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({key:r.get(key) for key in ['status','monitor_output','error']}))
    print(g.relative(out/'result.json'))
    return 0 if r['status'].startswith('PASS_') else 2


if __name__=='__main__':
    raise SystemExit(main())
