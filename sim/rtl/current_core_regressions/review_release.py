"""Primary exact-source and executed-regression gate for counter publication fix."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
OLD = Path('C:/z100v13/gpt_acp_phase_counters01/overrides/rtl')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
roles = ['unit', 'fault_diagnostics', 'mixed_diagnostics', 'control', 'tail',
         'pool_control', 'mixed', 'pool_fault', 'id_fault']

def main():
    batch = json.loads((ROOT / 'regression_result.json').read_text())
    assert batch['status'] == 'PASS_EIGHT_REGRESSIONS_PRIMARY_REVIEW_PENDING'
    overrides = {p.name: sha(p) for p in (ROOT / 'rtl').glob('*.sv')}
    assert len(overrides) == 8
    changed = [name for name in overrides if sha(OLD / name) != overrides[name]]
    assert changed == ['z100_native_event_counters_v1.sv'], changed
    counter = (ROOT / 'rtl' / changed[0]).read_text()
    assert counter.index('end else if (event_start)') < counter.index('end else if (fault_publish_pending_q)') < counter.index('end else if (event_open_q)')
    assert "snapshot_valid<=success_terminal;" in counter
    assert "fault_publish_pending_q<=!success_terminal;" in counter
    assert counter.count("fault_publish_pending_q<=1'b0;") == 3
    assert 'snapshot_q[k]<=counter_next[k];' in counter
    tests = {}
    for role in roles:
        path = ROOT / 'validation' / (role + '01') / 'result.json'
        value = json.loads(path.read_text())
        assert value['status'].startswith('PASS_') and value['pass_line'], role
        assert len(value['commands']) == 3 and all(x['returncode'] == 0 for x in value['commands']), role
        for name, digest in value['staged_inputs_sha256'].items():
            assert sha(path.parent / name) == digest, (role, name)
        for name in value['sources']:
            source = Path(name)
            assert source.read_bytes() == (path.parent / source.name).read_bytes(), (role, name)
        text = (path.parent / 'xsim_stdout.log').read_text(errors='replace')
        assert value['pass_line'] in text
        assert not re.search(r'(?im)^\s*(ERROR:|Fatal:|FATAL:|FAIL(?:_|\b))', text)
        if role == 'unit':
            assert 'FAULT_PUBLICATION_T_PLUS_ONE_PASS terminal_counts_unchanged=1 reset_priority=1 event_priority=1' in text
        if role == 'fault_diagnostics':
            assert 'COUNTER_PHYSICAL_FAULT_PASS cases=15 rid=7 bid=7 cancel=1' in text
            boundaries = re.findall(r'FAULT_SNAPSHOT_BOUNDARIES case=(\d+) legacy_first=(\d+) diagnostic_drained=(\d+)', text)
            assert len(boundaries) == 15
            for case, legacy, diagnostic in boundaries:
                case, legacy, diagnostic = int(case), int(legacy), int(diagnostic)
                assert legacy == (2 if case == 14 else 0)
                assert diagnostic == (3 if case < 7 else 4 if case < 14 else 2)
        tests[role] = {'path': str(path), 'sha256': sha(path), 'pass_line': value['pass_line'],
                       'log_sha256': sha(path.parent / 'xsim_stdout.log')}
    for name, digest in overrides.items():
        assert any(json.loads(Path(t['path']).read_text())['staged_inputs_sha256'].get(name) == digest
                   for t in tests.values()), name
    result = {
        'status': 'PASS_PRIMARY_COUNTER_RTL_AND_TEST_REVIEW',
        'override_sha256': overrides, 'tests': tests,
        'counter_fix_patch_sha256': sha(ROOT / 'counter_fix.patch'),
        'review_script_sha256': sha(Path(__file__)),
        'regression_result_sha256': sha(ROOT / 'regression_result.json'),
        'changed_from_prior_overlay': changed,
        'review': [
            'The seven existing-module diagnostic overlays remain byte-identical to their prior regression inputs; no datapath/handshake/legacy register changes.',
            'New passive module adds only pending fault publication. Counters close/freeze at original terminal T; fault code and valid publish T+1; success unchanged.',
            'Reset and event_start precede pending publication and clear it, preventing stale validity; unit executes both cases.',
            'Strict physical test confirms old first-edge code0 for RID/BID, diagnostic T+1 code3/4, cancel2, exact bus counts, stable snapshots and no pending/new-command overlap.',
            'Unit includes terminal-edge overflow and transfer, immutable snapshots and no extra T+1 event cycles.',
        ],
        'preserved_failures': [
            'C:/z100v13/gpt_acp_counter_integration01/validation/counter_id_fault_diagnostics02/result.json',
            'C:/z100v13/gpt_acp_counter_integration01/validation/counter_id_fault_diagnostics03/result.json',
        ],
        'contract': 'For fault/cancel, snapshot code is backend code sampled one clock after original terminal, not legacy first-observed code or a universal root cause.',
        'remaining': ['Full platform setup/hold/route/DRC', 'Matching diagnostic firmware and guarded new-bit launch', 'Real 66-event capture/full HEADS/IRQ', 'Measured performance'],
        'board_access': False, 'fps_claimed': False,
    }
    with (ROOT / 'primary_review.json').open('x') as f:
        json.dump(result, f, indent=2)
    print(result['status'])

if __name__ == '__main__':
    main()
