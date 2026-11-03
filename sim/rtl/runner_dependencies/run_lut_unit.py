"""Run the isolated LUT unit under the project's shared vendor mutex."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = Path('C:/Users/Administrator/Desktop/yolov8n_z7z100')
OWN = Path(__file__).resolve().parent
PWSH = 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
BIN = Path('C:/appload/2026.1/Vivado/bin')
sys.path.insert(0, str(ROOT / 'tools'))
from run_z100_registered_response_bank_v2 import NamedMutex


def inspect_host():
    script = r'''$ErrorActionPreference='Stop'
$os=Get-CimInstance Win32_OperatingSystem
$disk=Get-PSDrive -Name C
$tasks=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(vivado|xvlog|xelab|xsim|xsimk|xvhdl|xsc)\.exe$' } | Select-Object ProcessId,Name,CommandLine)
[pscustomobject]@{ram_gib=$os.FreePhysicalMemory*1KB/1GB; disk_gib=$disk.Free/1GB; vendor=$tasks} | ConvertTo-Json -Depth 4 -Compress
'''
    p = subprocess.run([PWSH, '-NoProfile', '-Command', script], capture_output=True,
                       text=True, encoding='utf-8', check=True)
    host = json.loads(p.stdout)
    assert host['ram_gib'] >= 8 and host['disk_gib'] >= 20, host
    assert not host['vendor'], host
    return host


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run-id', required=True)
    p.add_argument('--testbench', type=Path, required=True)
    p.add_argument('--fixtures', type=Path)
    p.add_argument('--fixture-subdir', default='')
    p.add_argument('--dut', type=Path, default=OWN / 'rtl/z100_native_view_lut16.sv')
    p.add_argument('--extra-source', type=Path, action='append', default=[])
    p.add_argument('--vendor-primitives', action='store_true',
                   help='Link the real Unisim DSP/BRAM models and glbl')
    p.add_argument('--top', required=True)
    p.add_argument('--pass-marker', required=True)
    a = p.parse_args()
    assert re.fullmatch(r'[a-zA-Z0-9_]{1,40}', a.run_id)
    out = OWN / 'validation' / a.run_id
    out.mkdir(parents=True, exist_ok=False)
    sources = [a.dut, *a.extra_source, a.testbench]
    if a.vendor_primitives:
        sources.append(Path('C:/appload/2026.1/Vivado/data/verilog/src/glbl.v'))
    assert len({s.name for s in sources}) == len(sources), 'Duplicate compilation basename'
    before = {s: s.read_bytes() for s in sources}
    fixture_paths = [s for s in a.fixtures.iterdir() if s.suffix in ('.hex', '.vh', '.mem')] if a.fixtures else []
    assert fixture_paths or a.fixtures is None
    fixture_out = (out / a.fixture_subdir).resolve()
    assert fixture_out.is_relative_to(out.resolve())
    fixture_out.mkdir(parents=True, exist_ok=True)
    for s in fixture_paths:
        (fixture_out / s.name).write_bytes(s.read_bytes())
    # Staged sources are compilation inputs, not production modifications.
    for s, data in before.items():
        (out / s.name).write_bytes(data)
    report = {'status': 'PREPARED', 'commands': [], 'sources': [str(s) for s in sources],
              'board_access': False, 'full_ingress_accepted': False, 'fps_accepted': False}
    report['staged_inputs_sha256'] = {
        str(s.relative_to(out)): hashlib.sha256(s.read_bytes()).hexdigest()
        for s in out.rglob('*') if s.is_file()
    }
    report['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    path = out / 'result.json'
    def save():
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    commands = [
        [str(BIN/'xvlog.bat'), '-sv', *[s.name for s in sources]],
        [str(BIN/'xelab.bat'), '-mt', '2',
         *(['-L', 'unisims_ver', '-L', 'unimacro_ver', 'glbl'] if a.vendor_primitives else []),
         a.top, '-s', 'lut16_unit'],
        [str(BIN/'xsim.bat'), 'lut16_unit', '-runall'],
    ]
    try:
        with NamedMutex(timeout_ms=0):
            report['admission'] = inspect_host()
            for label, argv in zip(['xvlog', 'xelab', 'xsim'], commands):
                inspect_host()
                report['status'] = label.upper() + '_RUNNING'
                row = {'argv': argv, 'started': time.time()}
                report['commands'].append(row)
                # XSim itself owns xsim.log; use a distinct stdout capture.
                with (out/(label+'_stdout.log')).open('wb') as log:
                    process = subprocess.Popen(argv, cwd=out, stdout=log, stderr=subprocess.STDOUT,
                        env=dict(os.environ, XILINX_LOCAL_USER_DATA='no', OMP_NUM_THREADS='1'),
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    row['pid'] = process.pid
                    save()
                    row['returncode'] = process.wait()
                row['seconds'] = time.time()-row['started']
                save()
                text = (out/(label+'_stdout.log')).read_text(encoding='utf-8', errors='replace')
                assert row['returncode'] == 0, f'{label} failed: {out}'
                assert not re.search(r'(?im)^\s*(ERROR:|FATAL:|Fatal:|FAIL(?:_|\b))', text), f'{label} error: {out}'
            assert text.count(a.pass_marker) == 1, 'Missing/duplicate test completion marker'
            for s, data in before.items():
                assert s.read_bytes() == data, f'Source drift: {s}'
                assert (out/s.name).read_bytes() == data
            report['pass_line'] = next(line for line in text.splitlines() if a.pass_marker in line)
            report['status'] = ('PASS_LUT_UNIT_ONLY_INTEGRATION_TIMING_BOARD_PENDING' if
                a.dut.name == 'z100_native_view_lut16.sv' else
                'PASS_COMPONENT_TEST_ONLY_PLATFORM_TIMING_BOARD_PENDING')
            inspect_host()
            save()
    except Exception as error:
        report.update(status='FAILED', error=str(error))
        save()
        raise
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
