"""20-site packed-feedback row integration, explicit completed epoch200 arithmetic fixture.

Checks original OIHW convolution, binary64 requant golden, SiLU and scatter pack.
Epoch200 first-row arithmetic is checked here; full graph, model quality and physical deployment remain separate.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, importlib.util, json, re, sys

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT/'deployment/hardware/z100_2026'
OWN = HW/'native_row20_v1'
WINDOW_PROOF = ROOT/'validation/board_z100/fw20_bankv4/20261024T095701.283135Z/result.json'
BANK_PROOF = ROOT/'validation/board_z100/feature_banks_4read_v4/20261024T095451.504289Z_f1d680b0/result.json'
MAC_PROOF = ROOT/'validation/board_z100/mac20/20261024T082551.568385Z/result.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def resolve(name):
    parts = Path(name).parts
    return Path(parts[1]+':/', *parts[2:]) if parts[0] == 'external' else ROOT/name


def proof(path, status):
    value = json.loads(path.read_text())
    require(value['status'] == status, 'Prerequisite status: '+str(path))
    require(value['source_sha256_before'] == value['source_sha256_after'], 'Prerequisite source drift')
    for name, digest in value['source_sha256_after'].items():
        require(sha(resolve(name)) == digest, 'Current prerequisite source drift: '+name)
    for name, digest in value['artifact_sha256'].items():
        require(sha(resolve(name)) == digest, 'Prerequisite artifact drift: '+name)
    return dict(path=str(path.relative_to(ROOT)), sha256=sha(path), status=status)


def metadata_clone_checks():
    req = (HW/'requant_partition_v2/z100_requant_vector.sv').read_text()
    req = req.replace('[3:0] in_site', '[4:0] in_site').replace('[3:0] out_site', '[4:0] out_site')
    req = req.replace('[3:0] site_q', '[4:0] site_q').replace('in_site >= 12', 'in_site >= 20')
    require(req == (OWN/'z100_requant_vector.sv').read_text(), 'Requant arithmetic/search delta')
    pack = (HW/'native_output_packer_v2/z100_native_output_packer.sv').read_text()
    pack = pack.replace('parameter integer SITES = 12', 'parameter integer SITES = 20')
    pack = pack.replace('[3:0]    in_site', '[4:0]    in_site').replace('[3:0] site_index_q', '[4:0] site_index_q')
    pack = pack.replace("site_index_q <= 4'b0", "site_index_q <= 5'b0")
    pack = pack.replace('(SITES != 12))', '(SITES != 12) && (SITES != 20))')
    pack = pack.replace('SITES must be 4, 8, or 12', 'SITES must be 4, 8, 12, or 20')
    require(pack == (OWN/'z100_native_output_packer.sv').read_text(), 'Packer transpose/addressing delta')
    row = (OWN/'z100_native_row20.sv').read_text()
    require('committed_groups-11\'d1' in row and '[4:0] side_site' in row and
            '[639:0] window_out_data' in row and '[79:0] response_mask' in row,
            'Dynamic group / widened sideband / complete20site window contract')
    return dict(requant_search_and_numeric_unchanged=True, packer_only_site_field_and_admission_widened=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    h = load('row20_packed_helper', ROOT/'tools/validate_z100_window_mac_packed.py')
    f = load('row20_golden', ROOT/'tools/validate_z100_native_row_pipeline.py')
    pipeline = ROOT/'deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/pipeline'
    f.PACKAGE = pipeline/'package/MODEL.V8P'
    f.HEADER = pipeline/'package/v8_generated_model.h'
    f.GRAPH = pipeline/'model/graph.json'
    native = ROOT/'deployment/build/z100_native_window_weights/20261024T083854.673009Z_1c07bcbe'
    f.NATIVE_WEIGHTS = native/'weights_group4x32.bin'
    f.NATIVE_BIASES = native/'biases_int32x32.bin'
    f.NATIVE_MANIFEST = native/'manifest.json'
    table = ROOT/'deployment/build/z100_current_requant_tables/20261024T083915.921693Z_fd95e48a'
    f.CHANNEL_INDEX = table/'channel_index.json'
    f.THRESHOLDS = table/'thresholds_254_i64.bin'
    f.PACKED_TREES = table/'trees_255_i33_le5.bin'
    f.TABLE_REPORT = ROOT/'validation/board_z100/current_requant_tables/20261024T083915.921693Z_fd95e48a/result.json'
    pointwise = ROOT/'deployment/build/z100_pointwise_tables_v1/20261024T083915.917081Z_084be595'
    f.SILU_NODE1 = pointwise/'node_001_silu_input_0.bin'
    f.POINTWISE_MANIFEST = pointwise/'tables_manifest.json'
    f.POINTWISE_REPORT = ROOT/'validation/board_z100/pointwise_tables_v1/20261024T083915.917081Z_084be595/result.json'
    assets = [ROOT/'validation/board_z100/native_window_weights/20261024T083854.673009Z_1c07bcbe/result.json',
              f.TABLE_REPORT, f.POINTWISE_REPORT]
    for asset in assets:
        saved = json.loads(asset.read_text())
        require(saved['status'].startswith('PASS_'), 'Epoch200 asset preparation failed')
        for name, digest in {**saved.get('source_sha256_after', saved['source_sha256']), **saved['artifact_sha256']}.items():
            require(sha(resolve(name)) == digest, 'Epoch200 asset source/artifact drift '+name)
    # Same selected RGB fixture and quantized input scale; no old model outputs are reused.
    current_quant = json.loads((pipeline/'quantization/quantization.json').read_text())
    old_quant = json.loads((ROOT/'deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/quantization/quantization.json').read_text())
    require(current_quant['scales']['-1'] == old_quant['scales']['-1'] == 1/127,
            'Reused NCHW input requires unchanged input scaling')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = ROOT/'validation/board_z100/native_row20_epoch200_bankv4'/stamp
    build = ROOT/'build'/('row20_'+stamp)
    out.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    rtl = [HW/'feature_banks_addressed_v1/z100_feature_banks_addressed.sv',
           HW/'feature_banks_4read_v4/z100_feature_banks_4read.sv',
           HW/'feature_window20_v1/z100_feature_window20.sv',
           HW/'int8_pair_packing_v3/z100_int8_pair_packing.sv',
           HW/'accum33_dsp_v2/z100_accum33_dsp.sv',
           HW/'window_mac20_v1/z100_window_mac.sv',
           OWN/'z100_requant_vector.sv', HW/'unary32_v1/z100_unary32.sv',
           OWN/'z100_native_output_packer.sv', OWN/'z100_native_row20.sv']
    tb = OWN/'tb_z100_native_row20.sv'
    paths = tuple(dict.fromkeys([*f.source_paths().values(), *f.dependency_paths().values(),
                                *rtl, tb, BANK_PROOF, *assets, pipeline/'quantization/quantization.json', WINDOW_PROOF, MAC_PROOF, Path(__file__),
                                ROOT/'tools/validate_z100_window_mac_packed.py', h.GLBL]))
    before = {}
    d = dict(status='RUNNING', board_access=False, production_integrated=False,
             model_scope='User-selected completed epoch200 PIN640 first-convolution row; no fullgraph/accuracy/board acceptance',
             full_pipeline_30fps_accepted=False, commands=[])
    report = out/'result.json'
    try:
        d['prerequisites'] = [proof(WINDOW_PROOF, 'PASS_PRIVATE_20SITE_WINDOW_BANKV3_XSIM_ONLY'),
                             proof(BANK_PROOF, 'PASS_PRIVATE_FOUR_READ_FEATURE_BANK_XSIM_OOC_ONLY'),
                             proof(MAC_PROOF, 'PASS_PRIVATE_20SITE_MAC_XSIM_OOC_ONLY')]
        before = {h.rel(p): sha(p) for p in paths}
        d['metadata_clone_checks'] = metadata_clone_checks()
        h.snapshot(paths, out/'src')
        f.SITES = 20
        f.RUNS = 16
        f.WINDOW_REQUESTS = 144
        original_writer = f.write_hex

        def writer(path, words, digits):
            if path.name == 'expected_windows.hex': digits = 160
            if path.name == 'expected_window_masks.hex': digits = 20
            original_writer(path, words, digits)

        f.write_hex = writer
        fixture = f.prepare_fixture(build)
        fixture['geometry'].pop('runs_with_12_sites')
        fixture['geometry'].update(runs_with_20_sites=16, tail_sites=20)
        require(len((build/'expected_windows.hex').read_text().splitlines()) == 144 and
                len((build/'expected_windows.hex').read_text().splitlines()[0]) == 160,
                '20site independent window fixture shape')
        d['fixture'] = fixture
        d['status'] = 'PASS_EPOCH200_ROW20_BANKV4_HOST_ONLY'
        if args.execute:
            h.run('xvlog', [h.VIVADO/'xvlog.bat', '-sv', *rtl, tb, h.GLBL], build, out, d)
            h.run('xelab', [h.VIVADO/'xelab.bat', '-mt', '2', '-L', 'unimacro_ver', '-L',
                           'unisims_ver', 'tb_z100_native_row20', 'glbl', '-s', 'row20_sim'], build, out, d)
            text = h.run('xsim', [h.VIVADO/'xsim.bat', 'row20_sim', '-runall'], build, out, d)
            rows = re.findall(r'^NATIVE_ROW20_PASS ([^\r\n]+)$', text, re.M)
            require(len(rows) == 1, 'Exactly one integrated numeric PASS marker required')
            values = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', rows[0])}
            expected = dict(runs=16, requests=144, responses=144, window_bytes=11520, masks=144,
                            raw_beats=320, raw_lanes=10240, raw_flags=10240, post_beats=320,
                            active_bytes=5120, tail_bytes=5120, packed_words=80, packed_bytes=5120,
                            feature_loads=80, weight_groups=9, bias_loads=1, req_words=255,
                            unary_bytes=256, full_buffers=1, done=1, max_runsites=20, tail_sites=20)
            require(all(values.get(k) == v for k, v in expected.items()), 'Complete20site row counts')
            require(all(values[k] > 0 for k in ['packed_stall', 'req_stall', 'unary_stall']) and
                    values['packed_hold_checks'] >= 4, 'Natural packer/requant/unary backpressure')
            d.update(status='PASS_EPOCH200_ROW20_BANKV4_COMPLETE_NUMERIC_XSIM_ONLY', simulation=values,
                     routed_clock_or_throughput_accepted=False)
    except Exception as exc:
        d.update(status='FAILED_CLOSED', error=f'{type(exc).__name__}: {exc}')
    finally:
        d['source_sha256_before'] = before
        d['source_sha256_after'] = {h.rel(p): sha(p) for p in paths if p.exists()}
        if before and before != d['source_sha256_after']:
            d.update(status='FAILED_SOURCE_INTEGRITY', error='Source/dependency drift')
        d['artifact_sha256'] = {h.rel(p): sha(p) for base in (out, build) for p in base.rglob('*')
                                if p.is_file() and p != report}
        report.write_text(json.dumps(d, indent=2)+'\n')
    print(json.dumps(dict(status=d['status'], report=str(report), error=d.get('error'))))
    return 1 if d['status'].startswith('FAILED') else 0


if __name__ == '__main__':
    raise SystemExit(main())
