"""Root read-only review of saved row scheduling and actual partitioned-row proofs."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
SCHED=ROOT/'validation/board_z100/native_row_scheduler_v1/20261024T050039.874627Z_5f9fb1f5/result.json'
PART=ROOT/'validation/board_z100/nrowp_review/20261024T045220.047881Z_bedfdf9d/review.json'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check(ok,message):
    if not ok:
        raise ValueError(message)


def main():
    out=ROOT/'validation/board_z100/acceleration_resource_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True,exist_ok=False)
    d=dict(status='RUNNING',board_access=False,production_integrated=False,
           full_pipeline_30fps_accepted=False)
    try:
        s=json.loads(SCHED.read_text())
        check(s['status']=='PASS_PRIVATE_NATIVE_ROW_SCHEDULER_XSIM_OOC_SYNTH_ONLY','Scheduler status')
        for stem in ('source','dependency'):
            before=s[stem+'_sha256_before']
            check(before==s[stem+'_sha256_after'],'Scheduler '+stem+' changed')
            for name,value in before.items():
                check(sha(ROOT/name)==value['sha256'],'Scheduler input hash '+name)
        for name,value in s['artifact_sha256'].items():
            check(sha(ROOT/name)==value,'Scheduler artifact hash '+name)
        check(s['simulation']==dict(status='PASS',aborts=3,blocked_reload_polls=200,
            commands=31,done=12,faults=22,invalid_commands=19,run_stability_checks=15,
            run_stall_cycles=16,runs=72,valid_commands=12,window_stability_checks=661,
            window_stall_cycles=663,windows=3088),'Scheduler numeric coverage')
        synth=s['synthesis']
        check(all(synth['fixed_gates'].values()) and synth['slice_luts_including_lutram']==1835
            and synth['slice_registers']==245 and synth['dsp']==0 and synth['bram36_equivalent']==0
            and synth['latch']==0 and synth['blackbox']==0,'Scheduler resource gate')
        tb=ROOT/'deployment/hardware/z100_2026/native_row_scheduler_v1/tb_z100_native_row_scheduler.sv'
        text=tb.read_text()
        check('if (!rst_n || cancel || abort_pulse)' in text and
            text.count('if (rst_n && !cancel && !abort_pulse)')==2 and
            'early post_done did not fail closed' in text and
            'mismatched post_done did not fail closed' in text and
            'unexpected idle post_done did not fail closed' in text,
            'Scheduler private abort-aware stability and fault assertions')
        p=json.loads(PART.read_text())
        check(len(p['checks'])==26 and all(p['checks'].values()),'Partition companion gates')
        check(sha(PART)=='e114e7ccef68580812b9e8fb8b2d95a3329d90ca42f295c72ed71cf099e13d3f',
            'Partition companion frozen hash')
        for name,value in p['integrity']['all_saved_artifact_sha256'].items():
            check(sha(ROOT/name)==value,'Partition saved artifact hash '+name)
        original=p['original_result']
        check(sha(ROOT/original['path'])==original['sha256_before_review'],
              'Partition original failed report altered')
        base=ROOT/'validation/board_z100/nrowpart/20261024T044106.631331Z_844a2330'
        modes=[]
        for line in (base/'dsp48e1_mode_census.tsv').read_text().splitlines()[1:]:
            cell,mode=line.replace('\\t','\t').split('\t')
            check(cell.startswith('native_mac/'),'Non-MAC DSP ownership')
            modes.append(mode)
        check(Counter(modes)==Counter(MULTIPLY=1536,NONE=383),'Partition actual DSP modes')
        counts={key:int(value) for key,value in
            (line.replace('\\t','\t').split('\t') for line in (base/'primitive_counts.tsv').read_text().splitlines())}
        check(counts==dict(LUT=71744,FF=50770,RAMB18=36,RAMB36=156,DSP=1919,LATCH=0,BLACKBOX=0),
            'Partition actual primitive census')
        check(counts['RAMB36']+counts['RAMB18']/2==174,'Partition actual BRAMeq')
        d.update(status='ROOT_ACCEPT_PRIVATE_SCHEDULER_AND_PARTITION_ROW_BOUNDED_ONLY',
            scheduler=dict(report=str(SCHED.relative_to(ROOT)),sha256=sha(SCHED),
                coverage=s['simulation'],synthesis=synth),
            partition=dict(report=str(PART.relative_to(ROOT)),sha256=sha(PART),
                exact_dsp_modes=dict(Counter(modes)),primitive_counts=counts,BRAM36eq=174,
                original_failed_report_preserved=True),
            limitations=['Scheduler remains disconnected from row/MAC/packer abort coordination',
                'Fullrow currently fixedGROUPS_PER_RUN9; no general fullgraph execution acceptance',
                'Private reset/cancel/abort can invalidate stalled metadata; normal stall stability remains required',
                'No routing/frequency/DDR/board/fullpipeline acceptance'])
    except Exception as exc:
        d.update(status='FAILED_ROOT_REVIEW_CLOSED',error=f'{type(exc).__name__}: {exc}')
    d['reviewer_sha256']=sha(__file__)
    path=out/'scheduler_partition_review.json'
    path.write_text(json.dumps(d,indent=2)+'\n')
    print(json.dumps(dict(status=d['status'],report=str(path),error=d.get('error'))))
    return 0 if d['status'].startswith('ROOT_ACCEPT_') else 1


if __name__=='__main__':
    raise SystemExit(main())
