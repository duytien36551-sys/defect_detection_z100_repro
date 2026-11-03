"""Private AXI3 64-bit sequential write adapter: host and bounded OOC checks."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / 'deployment/hardware/z100_2026/native_axi64_writer_v1'
RTL = DIR / 'z100_native_axi64_writer.sv'
TB = DIR / 'tb_z100_native_axi64_writer.sv'
VENDOR = Path('C:/appload/2026.1/Vivado/bin')
DDR_BASE = 0x10000000


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan(address, count, epoch=1):
    require(0 < epoch < 2**32, 'Epoch must be nonzero uint32')
    require(0 <= address < 2**32 and address % 64 == 0, 'Base must be aligned uint32')
    require(1 <= count <= 8192, 'Word count outside [1,8192]')
    end = address + count * 64
    require(end <= 2**32, 'Exclusive address end exceeds 2^32')
    bursts = []
    cursor = address
    remaining = count
    while remaining:
        page_words = (4096 - cursor % 4096) // 64
        burst_words = min(2, remaining, page_words)
        require(burst_words in (1, 2), 'Burst geometry is not 1 or 2 complete 512-bit words')
        bursts.append((cursor, burst_words, burst_words * 8 - 1))
        cursor += burst_words * 64
        remaining -= burst_words
    return bursts


def host_preflight():
    descriptors = 0
    bursts_checked = 0
    bytes_checked = 0
    page_offsets = list(range(0, 4096, 64))
    for offset in page_offsets:
        for count in (1, 2, 63, 64, 65, 8192):
            base = DDR_BASE + offset
            bursts = plan(base, count)
            cursor = base
            words_seen = 0
            for address, words, awlen in bursts:
                require(address == cursor, 'Burst sequence has a gap or overlap')
                require(words in (1, 2) and awlen == words * 8 - 1, 'AWLEN mismatch')
                require(address % 64 == 0, 'Burst address lost 64-byte alignment')
                require(address // 4096 == (address + words * 64 - 1) // 4096,
                        'Burst crosses 4KiB page')
                require(words <= 2, 'Burst exceeds two-word prebuffer')
                cursor += words * 64
                words_seen += words
                bursts_checked += 1
            require(words_seen == count and cursor == base + count * 64,
                    'Burst sequence does not cover command exactly')
            descriptors += 1
            bytes_checked += count * 64

    boundary_cases = []
    for count in (1, 2, 16, 64, 8192):
        base = 2**32 - count * 64
        burst_list = plan(base, count)
        require(sum(words for _, words, _ in burst_list) == count, 'Address-end boundary lost words')
        boundary_cases.append(dict(base=f'0x{base:08x}', words=count))

    invalid = [
        (DDR_BASE, 1, 0),
        (DDR_BASE + 1, 1, 1),
        (DDR_BASE, 0, 1),
        (DDR_BASE, 8193, 1),
        (0xFFFFFFC0, 2, 1),
        (2**32, 1, 1),
    ]
    for address, count, epoch in invalid:
        try:
            plan(address, count, epoch)
        except (ValueError, AssertionError):
            pass
        else:
            raise ValueError(f'Invalid command accepted by host geometry: {address:#x}/{count}/{epoch}')

    return dict(
        status='PASS_HOST_GEOMETRY_ONLY',
        descriptors=descriptors,
        all_64_byte_offsets_per_4KiB_page=len(page_offsets),
        lengths_words=[1, 2, 63, 64, 65, 8192],
        bursts_checked=bursts_checked,
        bytes_covered_across_all_descriptors=bytes_checked,
        exact_end_boundary_cases=boundary_cases,
        invalid_descriptors_rejected=len(invalid),
        burst_words_min=1,
        burst_words_max=2,
        awlen_for_512_bit_words='8*burst_words-1',
        page_crossings=0,
        axi_or_ddr_qualification=False,
    )


def run_command(name, argv, cwd, evidence, env, result):
    completed = subprocess.run(
        list(map(str, argv)), cwd=cwd, env=env, text=True, encoding='utf-8',
        errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    (evidence / f'{name}.log').write_text(completed.stdout, encoding='utf-8')
    result['commands'].append(dict(name=name, argv=list(map(str, argv)),
                                   return_code=completed.returncode))
    require(completed.returncode == 0, f'{name} returned {completed.returncode}')
    require(not re.search(r'^\s*(?:Fatal:|ERROR:)', completed.stdout, re.MULTILINE),
            f'{name} emitted a fatal/error diagnostic')
    return completed.stdout


def run_vendor(evidence, build, result):
    env = dict(os.environ)
    for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                'NUMEXPR_NUM_THREADS', 'NUMBA_NUM_THREADS'):
        env[key] = '1'

    run_command('xvlog', [VENDOR / 'xvlog.bat', '-sv', RTL, TB], build, evidence, env, result)
    run_command('xelab', [VENDOR / 'xelab.bat', '-mt', '2', 'tb_z100_native_axi64_writer',
                          '-s', 'native_axi64_writer_sim'], build, evidence, env, result)
    simulation = run_command('xsim', [VENDOR / 'xsim.bat', 'native_axi64_writer_sim', '-runall'],
                             build, evidence, env, result)
    marker = (r'^NATIVE_AXI64_WRITER_PASS bytes=(\d+) words=(\d+) aw=(\d+) w=(\d+) b=(\d+) '
              r'invalid=(\d+) stream_faults=(\d+) cancel=(\d+) timeout=(\d+) bid=(\d+) '
              r'bresp=(\d+) blocked=(\d+) max_w_streak=(\d+) aw_hold=(\d+) w_hold=(\d+) '
              r'done=(\d+) capacity_words=(\d+)\s*$')
    rows = re.findall(marker, simulation, re.MULTILINE)
    require(len(rows) == 1, 'Missing or duplicate anchored native AXI writer PASS marker')
    values = list(map(int, rows[0]))
    (byte_count, word_count, aw_count, w_count, b_count, invalid, stream_faults,
     cancels, timeouts, bid_faults, bresp_faults, blocked, max_w, aw_hold,
     w_hold, done_count, capacity) = values
    require((byte_count, word_count, aw_count, w_count, b_count, invalid, stream_faults,
             cancels, timeouts, bid_faults, bresp_faults, done_count, capacity) ==
             (524288, 8192, 4106, 65672, 4106, 5, 4, 4, 1, 1, 1, 3, 8192),
            'XSim transaction, error, boundary, or recovery coverage totals differ')
    require(blocked >= 800 and max_w >= 16 and aw_hold > 0 and w_hold > 0,
            'XSim stall/backpressure coverage below fixed floor')
    result['simulation'] = dict(
        status='PASS_INDEPENDENT_BYTE_SCOREBOARD_AND_RECOVERY',
        capacity_words=capacity,
        full_readback_bytes=byte_count,
        full_transfer_words=word_count,
        total_accepted_aw=aw_count,
        total_accepted_w_beats=w_count,
        total_accepted_b=b_count,
        invalid_commands=invalid,
        malformed_stream_probes=stream_faults,
        cancellation_scenarios=cancels,
        timeout_scenarios=timeouts,
        wrong_bid_scenarios=bid_faults,
        error_bresp_scenarios=bresp_faults,
        blocked_clear_reload_polls=blocked,
        max_consecutive_w_accepts=max_w,
        aw_stability_checks=aw_hold,
        w_stability_checks=w_hold,
        successful_done_pulses=done_count,
        actual_ddr_or_bandwidth_qualification=False,
    )

    tcl = evidence / 'synth.tcl'
    tcl.write_text(f'''set_param general.maxThreads 2
if {{![string match 2026.1* [version -short]]}} {{error "Requires Vivado 2026.1"}}
read_verilog -sv {{{RTL.as_posix()}}}
synth_design -top z100_native_axi64_writer -part xc7z100ffg900-2 -mode out_of_context
create_clock -period 10 [get_ports clk]
report_utilization -file {{{(evidence / 'utilization.rpt').as_posix()}}}
set leaf [get_cells -hier -filter {{IS_PRIMITIVE == 1}}]
foreach {{kind pattern}} {{LUT LUT* FF FD* RAM36 RAMB36* RAM18 RAMB18* DSP DSP* LATCH LD*}} {{
    puts "NATIVE_AXI64_WRITER_CENSUS $kind [llength [filter $leaf REF_NAME=~$pattern]]"
}}
puts "NATIVE_AXI64_WRITER_CENSUS BLACKBOX [llength [get_cells -hier -filter {{IS_BLACKBOX == 1}}]]"
write_checkpoint -force {{{(build / 'post_synth.dcp').as_posix()}}}
''', encoding='utf-8')
    synth = run_command('vivado_ooc', [VENDOR / 'vivado.bat', '-mode', 'batch', '-source', tcl,
                                      '-log', evidence / 'vivado.log', '-journal', evidence / 'vivado.jou'],
                        build, evidence, env, result)
    counts = {key: int(value) for key, value in re.findall(
        r'^NATIVE_AXI64_WRITER_CENSUS (\w+) (\d+)\s*$', synth, re.MULTILINE)}
    require(set(counts) == {'LUT', 'FF', 'RAM36', 'RAM18', 'DSP', 'LATCH', 'BLACKBOX'},
            'Primitive census incomplete')
    require(counts['DSP'] == 0 and counts['RAM36'] == 0 and counts['RAM18'] == 0 and
            counts['LATCH'] == 0 and counts['BLACKBOX'] == 0 and
            counts['LUT'] <= 4000 and counts['FF'] <= 2500,
            f'Fixed private writer OOC resource screen failed: {counts}')
    result['synthesis'] = dict(status='PASS_PRIVATE_OOC_RESOURCE_SCREEN_ONLY',
                               primitive_counts=counts, routed_timing_or_DDR_qualified=False)
    result['status'] = 'PASS_PRIVATE_AXI64_WRITER_XSIM_OOC_ONLY'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='After host preflight, run the single authorized XSim→OOC validation flow')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence = ROOT / 'validation/board_z100/native_axi64_writer_v1' / stamp
    build = ROOT / 'deployment/build/z100_native_axi64_writer_v1' / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    sources = (RTL, TB, Path(__file__).resolve())
    before = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    result = dict(
        status='RUNNING',
        source_sha256_before=before,
        commands=[],
        architecture_scope='private_single_outstanding_AXI3_64bit_to_512bit_sequential_writer',
        max_prefetch_words=2,
        coordinated_platform_axi_reset_required=True,
        private_uncommitted_DDR_region_ownership_required=True,
        production_dma_or_board_access=False,
        full_pipeline_or_bandwidth_claim=False,
    )
    report = evidence / 'result.json'
    try:
        for source in sources:
            snapshot = evidence / 'source_snapshot' / source.relative_to(ROOT)
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, snapshot)
        result['host_preflight'] = host_preflight()
        result['status'] = 'PASS_HOST_PREFLIGHT_ONLY'
        if args.execute:
            run_vendor(evidence, build, result)
    except Exception as exc:
        result.update(status='FAILED_CLOSED', error=f'{type(exc).__name__}: {exc}')
    finally:
        result['source_sha256_after'] = {str(path.relative_to(ROOT)): sha(path) for path in sources}
        if result['source_sha256_after'] != before:
            result.update(status='FAILED_SOURCE_INTEGRITY', error='A bound source changed during validation')
        result['source_snapshot_sha256'] = {
            str(path.relative_to(ROOT)): sha(evidence / 'source_snapshot' / path.relative_to(ROOT))
            for path in sources
        }
        result['artifact_sha256'] = {
            str(path.relative_to(ROOT)): sha(path)
            for base in (evidence, build)
            for path in base.rglob('*')
            if path.is_file() and path != report
        }
        report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=result['status'], report=str(report), error=result.get('error')),
                     indent=2))
    return 0 if result['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    raise SystemExit(main())
