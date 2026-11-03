"""Validate the private native AXI64 writer/shared-memory/reader seam with XSim only."""
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
HW = ROOT / 'deployment/hardware/z100_2026'
WRITER = HW / 'native_axi64_writer_v1/z100_native_axi64_writer.sv'
READER = HW / 'native_axi64_reader_v1/z100_native_axi64_reader.sv'
TB = HW / 'native_transport_loopback_v1/tb_z100_native_transport_loopback.sv'
WRITER_REPORT = ROOT / 'validation/board_z100/native_axi64_writer_v1/20261024T043403.794941Z/result.json'
READER_REPORT = ROOT / 'validation/board_z100/native_axi64_reader_v1/20261024T042036.611208Z/result.json'
WRITER_SHA = '7711550bc3f1d52616929ad74cfb7e7ed05e1b0da8fcebec000d2a7497fa4bab'
READER_SHA = 'd63bb0e8d28b334b8557c5675c68a8b10342776e09b27968d626410cfcbff4fa'
VENDOR = Path('C:/appload/2026.1/Vivado/bin')
DDR_BASE = 0x10000000
MEM_BYTES = 1_048_576


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bursts(address, words):
    require(0 <= address < 2**32 and address % 64 == 0, 'Unaligned/out-of-range AXI address')
    require(0 < words <= 8192, 'AXI transaction length outside [1,8192]')
    require(address + words * 64 <= 2**32, 'AXI transaction wraps uint32 address space')
    result = []
    while words:
        page_words = (4096 - address % 4096) // 64
        burst_words = min(2, words, page_words)
        require(burst_words in (1, 2), 'Illegal private 512-bit burst size')
        require((address // 4096) == ((address + burst_words * 64 - 1) // 4096),
                'Burst crosses a 4KiB boundary')
        result.append((address, burst_words, burst_words * 8 - 1))
        address += burst_words * 64
        words -= burst_words
    return result


def check_component(report_path, expected_status, source_path, expected_source_sha):
    report = json.loads(report_path.read_text(encoding='utf-8'))
    require(report.get('status') == expected_status,
            f'Bound component report has unexpected status: {report_path}')
    source_key = str(source_path.relative_to(ROOT)).replace('/', '\\')
    require(report.get('source_sha256_after', {}).get(source_key) == expected_source_sha,
            f'Component report does not bind the required RTL: {source_path}')
    require(sha(source_path) == expected_source_sha,
            f'Frozen component RTL hash changed: {source_path}')
    private_board_scope = (report.get('production_integrated') is False and
                           report.get('board_access') is False) or (
                           report.get('production_dma_or_board_access') is False)
    private_perf_scope = (report.get('full_pipeline_30fps_accepted') is False or
                          report.get('full_pipeline_or_bandwidth_claim') is False)
    require(private_board_scope and private_perf_scope,
            f'Component report exceeds private validation scope: {report_path}')
    return report


def traffic_plan():
    # Each row is (base, complete 512-bit words actually sent to the writer).
    writer_transactions = [
        (DDR_BASE, 8192),
        (0x100A0000, 65),
        (0x10080000, 1),
        (0x10080FC0, 2),
        (0x10081000, 63),
        (0x10082000, 64),
        (0x10083000, 65),
        (0x100A0000, 2),   # First burst of the 3-word update, followed by cancel.
        (0x100A0000, 3),   # Complete recovery write.
        (0x100B0000, 2),   # Complete AXI write, rejected BID; caller does not commit.
        (0x100B0000, 2),   # Recovery write.
    ]
    reader_transactions = [
        (DDR_BASE, 8192), (0x100A0000, 65),
        (0x10080000, 1), (0x10080FC0, 2), (0x10081000, 63),
        (0x10082000, 64), (0x10083000, 65),
        (0x100A0000, 3), (0x100B0000, 2),
        (DDR_BASE, 2), (DDR_BASE, 2),  # RRESP drain, then successful recovery.
    ]

    def summarize(transactions):
        per_transaction = []
        burst_list = []
        for base, count in transactions:
            tx_bursts = bursts(base, count)
            burst_list.extend(tx_bursts)
            per_transaction.append(dict(
                base=f'0x{base:08x}', words=count, bursts=len(tx_bursts),
                beats=sum(awlen + 1 for _, _, awlen in tx_bursts),
                len16=sum(1 for _, _, awlen in tx_bursts if awlen == 15),
            ))
        return dict(
            transactions=len(transactions),
            words=sum(count for _, count in transactions),
            bytes=sum(count for _, count in transactions) * 64,
            bursts=len(burst_list),
            beats=sum((awlen + 1) for _, _, awlen in burst_list),
            len16=sum(1 for _, _, awlen in burst_list if awlen == 15),
            transaction_geometry=per_transaction,
            page_split_examples=[
                [f'0x{address:08x}', words, awlen]
                for address, words, awlen in bursts(0x10080FC0, 2)
            ],
        )

    writer = summarize(writer_transactions)
    reader = summarize(reader_transactions)
    # The writer's faulted/aborted payloads are sent and mutate uncommitted ranges;
    # the read RRESP fault is drained but deliberately creates no private output.
    require(writer['words'] == 8461 and writer['bursts'] == 4234 and writer['beats'] == 67688,
            'Internal writer coverage plan changed')
    require(reader['words'] == 8461 and reader['bursts'] == 4234 and reader['beats'] == 67688,
            'Internal reader coverage plan changed')
    require(writer['len16'] == reader['len16'] == 4227, 'Unexpected 16-beat burst plan')
    require(DDR_BASE + 8192 * 64 == 0x10080000, 'Full region A must occupy exactly 512 KiB')
    require(0x100A0000 >= DDR_BASE + 8192 * 64, 'Concurrent A/B regions overlap')
    require(0x10080000 + 65 * 64 < 0x100A0000, 'Small transfer range overlaps region B')
    require(0x100A0000 + 65 * 64 < 0x100B0000, 'B and C ranges overlap')
    require(0x100B0000 + 2 * 64 < DDR_BASE + MEM_BYTES,
            'Test addresses exceed shared byte-array capacity')
    return dict(writer=writer, reader=reader,
                successful_writer_inputs=8461,
                stored_writer_bytes=writer['bytes'],
                successful_reader_output_words=8459,
                successful_reader_output_bytes=8459 * 64,
                reader_fault_drain_bytes=2 * 64)


def host_preflight():
    writer_report = check_component(
        WRITER_REPORT, 'PASS_PRIVATE_AXI64_WRITER_XSIM_OOC_ONLY', WRITER, WRITER_SHA)
    reader_report = check_component(
        READER_REPORT, 'PASS_PRIVATE_AXI64_READER_XSIM_OOC_ONLY', READER, READER_SHA)
    require(writer_report.get('simulation', {}).get('capacity_words') == 8192 and
            reader_report.get('simulation', {}).get('capacity_words') == 8192,
            'Component reports do not cover the required 8192-word capacity')

    # The stimulus and result oracle use separate expressions for the original
    # byte source and expected bytes. Prove their intended all-byte agreement.
    epochs = (0xA1, 0xB1, 0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xB2, 0xB3, 0xD1, 0xD2)
    formula_checks = 0
    for epoch in epochs:
        for word_index in range(8192):
            source_word = word_index * 31 + (word_index >> 4)
            oracle_word = word_index * 31 + ((word_index & 0x1ff0) >> 4)
            require(source_word == oracle_word, 'Source and independent byte oracle indexing differ')
            for byte_index in range(64):
                source = (source_word + byte_index * 17 + epoch * 9) & 0xff
                oracle = (byte_index * 17 + epoch * 9 + oracle_word) & 0xff
                require(source == oracle, 'Source/golden byte formula mismatch')
                formula_checks += 1
    plan = traffic_plan()
    return dict(
        status='PASS_HOST_BINDING_AND_TRAFFIC_GEOMETRY_ONLY',
        frozen_components={
            'writer_report': str(WRITER_REPORT.relative_to(ROOT)),
            'writer_report_sha256': sha(WRITER_REPORT),
            'writer_rtl_sha256': sha(WRITER),
            'reader_report': str(READER_REPORT.relative_to(ROOT)),
            'reader_report_sha256': sha(READER_REPORT),
            'reader_rtl_sha256': sha(READER),
        },
        traffic=plan,
        independent_source_oracle_byte_formula_checks=formula_checks,
        all_data_in_simulation_generated_from_independent_original_source_formula=True,
        actual_ddr_or_bandwidth_qualification=False,
    )


def run_command(name, argv, cwd, evidence, env, result):
    completed = subprocess.run(
        list(map(str, argv)), cwd=cwd, env=env, text=True,
        encoding='utf-8', errors='replace', stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (evidence / f'{name}.log').write_text(completed.stdout, encoding='utf-8')
    result['commands'].append(dict(name=name, argv=list(map(str, argv)),
                                   return_code=completed.returncode))
    require(completed.returncode == 0, f'{name} returned {completed.returncode}')
    require(not re.search(r'^\s*(?:Fatal:|ERROR:)', completed.stdout, re.MULTILINE),
            f'{name} emitted a fatal/error diagnostic')
    return completed.stdout


def run_xsim(evidence, build, result):
    env = dict(os.environ)
    for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                'NUMEXPR_NUM_THREADS', 'NUMBA_NUM_THREADS'):
        env[key] = '1'
    run_command('xvlog', [VENDOR / 'xvlog.bat', '-sv', WRITER, READER, TB],
                build, evidence, env, result)
    run_command('xelab', [VENDOR / 'xelab.bat', '-mt', '2',
                          'tb_z100_native_transport_loopback',
                          '-s', 'native_transport_loopback_sim'],
                build, evidence, env, result)
    simulation = run_command('xsim', [VENDOR / 'xsim.bat', 'native_transport_loopback_sim', '-runall'],
                             build, evidence, env, result)
    marker = (
        r'^NATIVE_TRANSPORT_LOOPBACK_PASS capacity_words=(\d+) full_bytes=(\d+) '
        r'input_words=(\d+) memory_write_bytes=(\d+) w_aw=(\d+) w_beats=(\d+) w_b=(\d+) '
        r'r_ar=(\d+) r_beats=(\d+) output_words=(\d+) w_len16=(\d+) r_len16=(\d+) '
        r'concurrent_cycles=(\d+) blocked_probes=(\d+) forbidden_ar=(\d+) w_done=(\d+) '
        r'r_done=(\d+) writer_faults=(\d+) reader_faults=(\d+) drain_beats=(\d+) '
        r'golden_output_bytes=(\d+) aw_hold=(\d+) w_hold=(\d+) ar_hold=(\d+) r_hold=(\d+) '
        r'out_hold=(\d+) input_hold=(\d+) max_w_streak=(\d+) max_r_streak=(\d+)\s*$'
    )
    rows = re.findall(marker, simulation, re.MULTILINE)
    require(len(rows) == 1, 'Missing or duplicate anchored native transport loopback PASS marker')
    values = list(map(int, rows[0]))
    keys = ('capacity_words', 'full_bytes', 'input_words', 'memory_write_bytes', 'w_aw',
            'w_beats', 'w_b', 'r_ar', 'r_beats', 'output_words', 'w_len16', 'r_len16',
            'concurrent_cycles', 'blocked_probes', 'forbidden_ar', 'w_done', 'r_done',
            'writer_faults', 'reader_faults', 'drain_beats', 'golden_output_bytes',
            'aw_hold', 'w_hold', 'ar_hold', 'r_hold', 'out_hold', 'input_hold',
            'max_w_streak', 'max_r_streak')
    values = dict(zip(keys, values))
    exact = {
        'capacity_words': 8192, 'full_bytes': 524288, 'input_words': 8461,
        'memory_write_bytes': 541504, 'w_aw': 4234, 'w_beats': 67688, 'w_b': 4234,
        'r_ar': 4234, 'r_beats': 67688, 'output_words': 8459, 'w_len16': 4227,
        'r_len16': 4227, 'blocked_probes': 16, 'forbidden_ar': 0,
        'w_done': 9, 'r_done': 10, 'writer_faults': 2, 'reader_faults': 1,
        'drain_beats': 15, 'golden_output_bytes': 541376,
    }
    require({key: values[key] for key in exact} == exact,
            f'XSim transfer/oracle/barrier totals differ: {values}')
    require(values['concurrent_cycles'] > 0, 'No concurrent disjoint A-read/B-write activity')
    require(values['max_w_streak'] >= 16 and values['max_r_streak'] >= 16,
            'Sixteen-consecutive-beat burst coverage missing')
    for key in ('aw_hold', 'w_hold', 'ar_hold', 'r_hold', 'out_hold', 'input_hold'):
        require(values[key] > 0, f'No {key} backpressure/stability observations')
    result['simulation'] = dict(
        status='PASS_PRIVATE_PAIRED_ADAPTER_SHARED_BYTE_MEMORY_XSIM_ONLY',
        coverage=values,
        shared_memory_bytes=MEM_BYTES,
        full_region_a_bytes=524288,
        successful_reader_output_bytes=values['golden_output_bytes'],
        reader_error_drain_bytes=128,
        caller_commit_barrier='reader host command is gated on a fully successful writer done pulse; abort/BID-fault probes remain uncommitted',
        concurrent_activity='one committed region is read while a disjoint region is written; no throughput claim',
        actual_ddr_or_bandwidth_qualification=False,
    )
    result['status'] = 'PASS_PRIVATE_NATIVE_TRANSPORT_LOOPBACK_XSIM_ONLY'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Run the single authorized paired-adapter XSim flow after host preflight')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence = ROOT / 'validation/board_z100/native_transport_loopback_v1' / stamp
    build = ROOT / 'deployment/build/z100_native_transport_loopback_v1' / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    script = Path(__file__).resolve()
    component_reports = (WRITER_REPORT, READER_REPORT)
    sources = (WRITER, READER, TB, script, *component_reports)
    before = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    result = dict(
        status='RUNNING', source_sha256_before=before, commands=[],
        architecture_scope='paired_private_AXI3_64bit_writer_shared_byte_memory_AXI3_64bit_reader',
        capacity_words=8192, shared_memory_bytes=MEM_BYTES,
        writer_and_reader_rtl_frozen=True, production_integrated=False,
        board_access=False, DDR_or_bandwidth_claim=False,
    )
    report = evidence / 'result.json'
    try:
        for source in sources:
            destination = evidence / 'source_snapshot' / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        result['host_preflight'] = host_preflight()
        result['status'] = 'PASS_HOST_PREFLIGHT_ONLY'
        if args.execute:
            run_xsim(evidence, build, result)
    except Exception as exc:
        result.update(status='FAILED_CLOSED', error=f'{type(exc).__name__}: {exc}')
    finally:
        result['source_sha256_after'] = {str(path.relative_to(ROOT)): sha(path) for path in sources}
        if result['source_sha256_after'] != before:
            result.update(status='FAILED_SOURCE_INTEGRITY',
                          error='A bound source or component report changed during validation')
        result['source_snapshot_sha256'] = {
            str(path.relative_to(ROOT)): sha(evidence / 'source_snapshot' / path.relative_to(ROOT))
            for path in sources
        }
        result['artifact_sha256'] = {
            str(path.relative_to(ROOT)): sha(path)
            for base in (evidence, build)
            for path in base.rglob('*') if path.is_file() and path != report
        }
        report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=result['status'], report=str(report),
                          error=result.get('error')), indent=2))
    return 0 if result['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    raise SystemExit(main())
