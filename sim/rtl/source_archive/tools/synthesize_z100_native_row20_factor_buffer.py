"""One source-bound20site complete row OOC; timing and board acceptance separate."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import hashlib, json, os, re, subprocess

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT/'validation/board_z100/native_row20_factor_buffer_v1/20261024T132635.195300Z/result.json'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(ok, message):
    if not ok: raise ValueError(message)


def resolve(name):
    parts = Path(name).parts
    return Path(parts[1]+':/', *parts[2:]) if parts[0] == 'external' else ROOT/name


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = ROOT/'validation/board_z100/native_row20_factor_buffer_ooc'/stamp
    build = ROOT/'build'/('rfb_'+stamp[-14:])
    out.mkdir(parents=True, exist_ok=False); build.mkdir(parents=True, exist_ok=False)
    report = out/'result.json'
    d = dict(status='RUNNING', board_access=False, production_integrated=False,
             full_pipeline_30fps_accepted=False, route_or_frequency_accepted=False)
    before = {}
    try:
        p = json.loads(PROOF.read_text())
        check(p['status'] == 'PASS_QUALITY200_ROW20_FACTOR_BUFFER_COMPLETE_NUMERIC_XSIM_ONLY' and
              p['source_sha256_before'] == p['source_sha256_after'], 'Complete20site XSim prerequisite')
        for name, digest in {**p['source_sha256_after'], **p['artifact_sha256']}.items():
            check(sha(resolve(name)) == digest, 'Saved XSim source/artifact drift '+name)
        before = {**p['source_sha256_after'], str(PROOF.relative_to(ROOT)): sha(PROOF),
                  str(Path(__file__).relative_to(ROOT)): sha(__file__)}
        # Source list comes from the accepted actual xvlog command, omitting only TB/glbl.
        files = [resolve(name) for name in p['commands'][0]['args'][2:]
                 if Path(name).name not in ('tb_z100_native_row20_factor_buffer.sv', 'glbl.v')]
        check(len(files) == 12 and all(x.suffix == '.sv' for x in files), 'Exact12RTL module closure')
        tcl = out/'synth.tcl'
        body = 'set_param general.maxThreads 2\n'
        body += 'if {![string match 2026.1* [version -short]]} {error "Requires2026.1"}\n'
        body += 'read_verilog -sv '+' '.join('{'+x.as_posix()+'}' for x in files)+'\n'
        body += 'synth_design -top z100_native_row20_factor_buffer -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none\n'
        body += 'create_clock -name row_clk -period 10 [get_ports clk]\n'
        for name, command in [('utilization.rpt', 'report_utilization'),
                              ('hierarchical.rpt', 'report_utilization -hierarchical'),
                              ('timing_unplaced.rpt', 'report_timing_summary -delay_type min_max -report_unconstrained')]:
            body += command+' -file {'+(out/name).as_posix()+'}\n'
        body += 'write_checkpoint -force {'+(build/'post_synth.dcp').as_posix()+'}\n'
        body += '''set leaf [get_cells -hier -filter {IS_PRIMITIVE == 1}]
foreach {kind pattern} {LUT LUT* FF FD* RAM36 RAMB36* RAM18 RAMB18* DSP DSP* LATCH LD*} {
 puts "ROW20_CENSUS $kind [llength [filter $leaf REF_NAME=~$pattern]]"
}
puts "ROW20_CENSUS BLACKBOX [llength [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]]"
'''
        body += 'set f [open {'+(out/'dsp.tsv').as_posix()+'} w]\n'
        body += '''puts $f "cell\tUSE_MULT\tPREG"
foreach c [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}] {
 puts $f "[get_property NAME $c]\t[get_property USE_MULT $c]\t[get_property PREG $c]"
}
close $f
exit
'''
        tcl.write_text(body)
        env = dict(os.environ)
        for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'): env[k] = '1'
        argv = ['C:/appload/2026.1/Vivado/bin/vivado.bat', '-mode', 'batch', '-source', str(tcl),
                '-log', str(out/'vivado.log'), '-journal', str(out/'vivado.jou')]
        run = subprocess.run(argv, cwd=build, env=env, text=True, encoding='utf-8', errors='replace',
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out/'stdout.log').write_text(run.stdout)
        d['command'] = dict(argv=argv, return_code=run.returncode)
        check(run.returncode == 0 and not re.search(r'^\s*ERROR:', run.stdout, re.M), 'Vendor OOC diagnostic')
        counts = {k:int(v) for k,v in re.findall(r'^ROW20_CENSUS (\w+) (\d+)\s*$', run.stdout, re.M)}
        dsp = [row.split('\t') for row in (out/'dsp.tsv').read_text().splitlines()[1:]]
        modes = Counter(row[1] for row in dsp)
        d.update(observed_primitive_counts=counts, DSP_modes=dict(modes))
        check(counts['DSP'] == 2016 and modes == Counter(MULTIPLY=1376, NONE=640), 'Exact20site core plus96factor DSP mapping')
        mac = [row for row in dsp if 'native_mac/' in row[0]]
        factor = [row for row in dsp if 'requant/gen_lane' in row[0]]
        check(len(mac)==1920 and len(factor)==96 and len(mac)+len(factor)==len(dsp), 'DSP ownership closure')
        check(Counter(row[1] for row in mac)==Counter(MULTIPLY=1280,NONE=640), 'Frozen native compute mapping')
        check(all(row[1]=='MULTIPLY' and '.unit/p_' in row[0] for row in factor), 'Only three multipliers per factor lane')
        check(counts['RAM36'] == 284 and counts['RAM18'] == 4 and
              counts['LUT'] <= 250000 and counts['FF'] <= 120000 and
              counts['LATCH'] == counts['BLACKBOX'] == 0, 'Actual factor row resource gate')
        util = (out/'utilization.rpt').read_text()
        lut = int(re.search(r'^\|\s*Slice LUTs\*?\s*\|\s*(\d+)', util, re.M)[1])
        d.update(status='PASS_PRIVATE_COMPLETE_ROW20_FACTOR_BUFFER2016DSP_XSIM_BOUND_OOC_ONLY', Slice_LUT=lut,
                 BRAM36eq=286, synthesis_DCP_sha256=sha(build/'post_synth.dcp'),
                 model_scope=p['model_scope'], simulation=p['simulation'])
    except Exception as exc:
        d.update(status='FAILED_CLOSED', error=f'{type(exc).__name__}: {exc}')
    finally:
        d['source_sha256_before'] = before
        d['source_sha256_after'] = {name:sha(resolve(name)) for name in before}
        if before != d['source_sha256_after']:
            d.update(status='FAILED_SOURCE_INTEGRITY', error='Source drift')
        d['artifact_sha256'] = {str(p.relative_to(ROOT)):sha(p) for base in (out, build)
                                for p in base.rglob('*') if p.is_file() and p != report}
        report.write_text(json.dumps(d, indent=2)+'\n')
    print(json.dumps(dict(status=d['status'], report=str(report), error=d.get('error'))))
    return 1 if d['status'].startswith('FAILED') else 0


if __name__ == '__main__': raise SystemExit(main())
