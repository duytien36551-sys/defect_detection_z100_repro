"""Validate autonomous scheduler-to-complete-row20 control with epoch200 assets.

The host phase builds independent NCHW/OIHW/binary64 fixtures and binds every
source and input. The xsim phase consumes that immutable host result and runs
one XSim only. This is a private first-convolution-row component check; it does
not claim full-graph accuracy, physical timing, board operation, or throughput.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import uuid

for _key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"):
    os.environ[_key] = "1"

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
OWN = HW / "native_scheduled_row20_v1"
SCRIPT = Path(__file__).resolve()
TB = OWN / "tb_z100_native_scheduled_row20.sv"
SCHEDULER = HW / "native_row_scheduler20_v1/z100_native_row_scheduler20.sv"
ROW = HW / "native_row20_v1/z100_native_row20.sv"
EVIDENCE_ROOT = ROOT / "validation/board_z100/native_scheduled_row20"
BUILD_ROOT = ROOT / "build"

FULL_ROW_PROOF = ROOT / "validation/board_z100/native_row20_epoch200/20261024T084245.002117Z/result.json"
SCHEDULER_PROOF = ROOT / "validation/board_z100/native_row_scheduler20/20261024T092200.055205Z_a331d2b3/result.json"
WINDOW_PROOF = ROOT / "validation/board_z100/fw20_ooc/20261024T082714.870335Z/result.json"
MAC_PROOF = ROOT / "validation/board_z100/mac20/20261024T082551.568385Z/result.json"
BANK4READ_PROOF = ROOT / "validation/board_z100/feature_banks_4read_v2/20261024T080718.029842Z_2f7e5938/result.json"

EPOCH200_RUN = "20261024T083031.921745Z"
PIPELINE = ROOT / "deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/pipeline"
CHECKPOINT = ROOT / "deployment/candidates/pin640/completed_models/epoch200_20261024T083031.921745Z/source.pt"
NATIVE_RUN = ROOT / "deployment/build/z100_native_window_weights/20261024T083854.673009Z_1c07bcbe"
TABLE_RUN = ROOT / "deployment/build/z100_current_requant_tables/20261024T083915.921693Z_fd95e48a"
TABLE_REPORT = ROOT / "validation/board_z100/current_requant_tables/20261024T083915.921693Z_fd95e48a/result.json"
POINTWISE_RUN = ROOT / "deployment/build/z100_pointwise_tables_v1/20261024T083915.917081Z_084be595"
POINTWISE_REPORT = ROOT / "validation/board_z100/pointwise_tables_v1/20261024T083915.917081Z_084be595/result.json"
NATIVE_REPORT = ROOT / "validation/board_z100/native_window_weights/20261024T083854.673009Z_1c07bcbe/result.json"
INPUT = ROOT / "validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_nchw_int8.bin"

SITES = 20
RUNS = 16
GROUPS = 9
ROW_WIDTH = 320
WINDOWS = RUNS * GROUPS
TAG_BASE = 0x53000000
TOKEN_BASE = 4100
EPOCH = 77
EXPECTED_CHECKPOINT_SHA256 = "2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6"

RTL = [
    HW / "feature_banks_addressed_v1/z100_feature_banks_addressed.sv",
    HW / "feature_banks_4read_v2/z100_feature_banks_4read.sv",
    HW / "feature_window20_v1/z100_feature_window20.sv",
    HW / "int8_pair_packing_v3/z100_int8_pair_packing.sv",
    HW / "accum33_dsp_v2/z100_accum33_dsp.sv",
    HW / "window_mac20_v1/z100_window_mac.sv",
    HW / "native_row20_v1/z100_requant_vector.sv",
    HW / "unary32_v1/z100_unary32.sv",
    HW / "native_row20_v1/z100_native_output_packer.sv",
    ROW,
    SCHEDULER,
    TB,
]


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def resolve_report_path(name: str) -> Path:
    normalized = str(name).replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if parts and parts[0] == "external":
        if len(parts) < 3:
            raise ValueError(f"malformed external path {name}")
        return Path(parts[1] + ":/") / Path(*parts[2:])
    return ROOT / Path(*parts)


def verify_bound_report(path: Path, expected_status: str) -> dict:
    require(path.is_file(), f"missing prerequisite report: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    require(data.get("status") == expected_status,
            f"prerequisite status changed: {path}: {data.get('status')}")
    before = data.get("source_sha256_before", {})
    after = data.get("source_sha256_after", {})
    require(before == after, f"prerequisite source hash drift is recorded: {path}")
    def digest_value(value):
        return value.get("sha256") if isinstance(value, dict) else value
    for name, recorded in after.items():
        digest = digest_value(recorded)
        source = resolve_report_path(name)
        require(isinstance(digest, str) and source.is_file() and sha(source) == digest,
                f"prerequisite source identity changed: {name}")
    for name, recorded in data.get("artifact_sha256", {}).items():
        digest = digest_value(recorded)
        artifact = resolve_report_path(name)
        require(isinstance(digest, str) and artifact.is_file() and sha(artifact) == digest,
                f"prerequisite artifact identity changed: {name}")
    return {"path": path.relative_to(ROOT).as_posix(), "status": expected_status,
            "report_sha256": sha(path), "bound_sources": len(after),
            "bound_artifacts": len(data.get("artifact_sha256", {}))}


def configure_epoch200_fixture(golden):
    pipeline = PIPELINE
    golden.PACKAGE = pipeline / "package/MODEL.V8P"
    golden.HEADER = pipeline / "package/v8_generated_model.h"
    golden.GRAPH = pipeline / "model/graph.json"
    golden.INPUT = INPUT
    golden.NATIVE_WEIGHTS = NATIVE_RUN / "weights_group4x32.bin"
    golden.NATIVE_BIASES = NATIVE_RUN / "biases_int32x32.bin"
    golden.NATIVE_MANIFEST = NATIVE_RUN / "manifest.json"
    golden.CHANNEL_INDEX = TABLE_RUN / "channel_index.json"
    golden.THRESHOLDS = TABLE_RUN / "thresholds_254_i64.bin"
    golden.PACKED_TREES = TABLE_RUN / "trees_255_i33_le5.bin"
    golden.TABLE_REPORT = TABLE_REPORT
    golden.SILU_NODE1 = POINTWISE_RUN / "node_001_silu_input_0.bin"
    golden.POINTWISE_MANIFEST = POINTWISE_RUN / "tables_manifest.json"
    golden.POINTWISE_REPORT = POINTWISE_REPORT
    golden.SITES = SITES
    golden.RUNS = RUNS
    golden.WINDOW_REQUESTS = WINDOWS
    golden.TB = TB
    golden.SCRIPT = SCRIPT


def generated_oracle() -> dict:
    descriptors = []
    runs = []
    for run in range(RUNS):
        output_x = run * SITES
        runs.append({"index": run, "epoch": EPOCH, "token": TOKEN_BASE + run,
                     "lanes": 16, "sites": SITES, "output_x": output_x})
        for group in range(GROUPS):
            ky, kx = divmod(group, 3)
            input_y = ky - 1
            descriptors.append({
                "index": run * GROUPS + group,
                "run": run,
                "group": group,
                "epoch": EPOCH,
                "tag": TAG_BASE + run * GROUPS + group,
                "row_address": (0, 0, 40)[ky],
                "first_x": output_x * 2 + kx - 1,
                "input_width": 640,
                "output_remaining": ROW_WIDTH - output_x,
                "sites": SITES,
                "channel_mask": 7,
                "stride_two": True,
                "y_valid": 0 <= input_y < 2,
            })
    require(len(runs) == 16 and len(descriptors) == 144,
            "independent scheduler oracle geometry")
    require([d["tag"] for d in descriptors] == list(range(TAG_BASE, TAG_BASE + WINDOWS)),
            "independent sequential descriptor tags")
    require(descriptors[71]["run"] == 7 and descriptors[71]["tag"] == TAG_BASE + 71 and
            descriptors[72]["run"] == 8 and descriptors[72]["tag"] == TAG_BASE + 72 and
            descriptors[71]["sites"] == descriptors[72]["sites"] == 20,
            "independent run7/run8 boundary oracle")
    return {"command": {"epoch": EPOCH, "token_base": TOKEN_BASE, "tag_base": TAG_BASE,
                        "channels": 3, "input_width": 640, "output_width": ROW_WIDTH,
                        "kernel": 3, "stride": 2, "padding": 1, "lanes": 16,
                        "bank_words": 80, "channel_plane_stride": 80,
                        "ky_row_bases": [0, 0, 40], "y_valid_bits": "110"},
            "runs": runs, "descriptors": descriptors,
            "descriptor_tag_rule": "tag_base + run*9 + group; scheduler increments once per accepted descriptor",
            "run_sites_rule": "min(20, output_width-output_x); all 16 runs in this 320-wide row carry20",
            "post_done_rule": "row post_valid && post_ready && post_last; epoch/token from accepted row post beat"}


def source_paths(golden, epoch_tool, packed_helper) -> tuple[Path, ...]:
    values = list(golden.source_paths().values())
    values.extend(RTL)
    values.extend([
        SCRIPT, TB, SCHEDULER, ROW,
        epoch_tool.__file__, packed_helper.__file__,
        FULL_ROW_PROOF, SCHEDULER_PROOF, WINDOW_PROOF, MAC_PROOF, BANK4READ_PROOF,
        NATIVE_REPORT, TABLE_REPORT, POINTWISE_REPORT,
        CHECKPOINT, PIPELINE / "package/MODEL.V8P", PIPELINE / "package/v8_generated_model.h",
        PIPELINE / "model/graph.json", PIPELINE / "quantization/quantization.json",
        INPUT, NATIVE_RUN / "weights_group4x32.bin", NATIVE_RUN / "biases_int32x32.bin",
        NATIVE_RUN / "manifest.json", TABLE_RUN / "channel_index.json",
        TABLE_RUN / "thresholds_254_i64.bin", TABLE_RUN / "trees_255_i33_le5.bin",
        POINTWISE_RUN / "node_001_silu_input_0.bin", POINTWISE_RUN / "tables_manifest.json",
    ])
    return tuple(dict.fromkeys(Path(path).resolve() for path in values))


def host_preflight() -> Path:
    import hashlib as _hashlib
    import json as _json
    from datetime import datetime, timezone
    import uuid as _uuid

    helper = load("scheduled_row20_packed_helper", ROOT / "tools/validate_z100_window_mac_packed.py")
    golden = load("scheduled_row20_independent_golden", ROOT / "tools/validate_z100_native_row_pipeline.py")
    epoch_tool = load("scheduled_row20_epoch_tool", ROOT / "tools/validate_z100_native_row20_epoch200.py")
    configure_epoch200_fixture(golden)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + _uuid.uuid4().hex[:8]
    out = EVIDENCE_ROOT / stamp
    build = BUILD_ROOT / ("srow20_" + _uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report_path = out / "result.json"
    result = {
        "status": "HOST_RUNNING",
        "scope": "private first-convolution row of selected completed epoch200 PIN640 model",
        "full_graph_validated": False, "model_accuracy_accepted": False,
        "board_access": False, "production_integrated": False,
        "physical_timing_accepted": False, "throughput_or_fps_accepted": False,
        "vivado_threads_requested": 2, "numerical_threads": 1,
        "historical_scheduler_xelab_thread_cap_explicit": False,
        "commands": [], "build_dir": build.relative_to(ROOT).as_posix(),
    }
    try:
        require(sha(CHECKPOINT) == EXPECTED_CHECKPOINT_SHA256,
                "selected epoch200 checkpoint identity mismatch")
        proof_rows = [
            verify_bound_report(FULL_ROW_PROOF, "PASS_EPOCH200_ROW20_COMPLETE_NUMERIC_XSIM_ONLY"),
            verify_bound_report(SCHEDULER_PROOF, "PASS_PRIVATE_NATIVE_ROW_SCHEDULER20_XSIM_OOC_SYNTH_ONLY"),
            verify_bound_report(WINDOW_PROOF, "PASS_PRIVATE_20SITE_WINDOW_XSIM_BOUND_OOC_ONLY"),
            verify_bound_report(MAC_PROOF, "PASS_PRIVATE_20SITE_MAC_XSIM_OOC_ONLY"),
            verify_bound_report(BANK4READ_PROOF, "PASS_PRIVATE_FOUR_READ_FEATURE_BANK_XSIM_OOC_ONLY"),
        ]
        result["prerequisites"] = proof_rows

        asset_reports = [NATIVE_REPORT, TABLE_REPORT, POINTWISE_REPORT]
        for asset_report in asset_reports:
            saved = json.loads(asset_report.read_text(encoding="utf-8"))
            require(str(saved.get("status", "")).startswith("PASS_"),
                    f"epoch200 asset generation did not pass: {asset_report}")
            hashes = {**saved.get("source_sha256_after", saved.get("source_sha256", {})),
                      **saved.get("artifact_sha256", {})}
            for name, digest in hashes.items():
                path = resolve_report_path(name)
                require(path.is_file() and sha(path) == digest,
                        f"epoch200 asset source/artifact drift: {name}")

        quant = json.loads((PIPELINE / "quantization/quantization.json").read_text(encoding="utf-8"))
        older_pipeline = ROOT / "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline"
        older_quant = json.loads((older_pipeline / "quantization/quantization.json").read_text(encoding="utf-8"))
        require(quant["scales"]["-1"] == older_quant["scales"]["-1"] == 1 / 127,
                "frozen RGB input fixture has changed quantization scale")
        require(sha(INPUT) == "0d458d68cf3e419e238245193cd5415c75b2931eb011a695c7b5a5765a1718b6",
                "frozen NCHW input fixture identity mismatch")
        result["input_fixture"] = {"path": INPUT.relative_to(ROOT).as_posix(),
                                   "sha256": sha(INPUT),
                                   "quant_scale_minus_one": quant["scales"]["-1"],
                                   "current_selected_model_output_reused": False}
        result["model_identity"] = {"checkpoint": CHECKPOINT.relative_to(ROOT).as_posix(),
                                    "checkpoint_sha256": sha(CHECKPOINT),
                                    "package_sha256": sha(PIPELINE / "package/MODEL.V8P"),
                                    "graph_sha256": sha(PIPELINE / "model/graph.json"),
                                    "weights_sha256": sha(NATIVE_RUN / "weights_group4x32.bin"),
                                    "biases_sha256": sha(NATIVE_RUN / "biases_int32x32.bin"),
                                    "requant_thresholds_sha256": sha(TABLE_RUN / "thresholds_254_i64.bin"),
                                    "silu_lut_sha256": sha(POINTWISE_RUN / "node_001_silu_input_0.bin")}

        result["metadata_clone_checks"] = epoch_tool.metadata_clone_checks()
        golden.SITES, golden.RUNS, golden.WINDOW_REQUESTS = SITES, RUNS, WINDOWS
        original_writer = golden.write_hex
        def writer(path, words, digits):
            if path.name == "expected_windows.hex": digits = 160
            if path.name == "expected_window_masks.hex": digits = 20
            original_writer(path, words, digits)
        golden.write_hex = writer

        source_list = source_paths(golden, epoch_tool, helper)
        for path in source_list:
            require(path.is_file(), f"missing bound source/dependency: {path}")
        before = {helper.rel(path): sha(path) for path in source_list}
        helper.snapshot(source_list, out / "src")
        fixture = golden.prepare_fixture(build)
        fixture["geometry"].pop("runs_with_12_sites", None)
        fixture["geometry"].update(runs_with_20_sites=RUNS, tail_sites=SITES)
        require(fixture["geometry"].get("output_row_shape") == [1, 16, 1, ROW_WIDTH] and
                fixture["geometry"].get("sites") == SITES and
                fixture["geometry"].get("runs") == RUNS,
                "epoch200 arithmetic fixture geometry mismatch")
        require(len((build / "expected_windows.hex").read_text(encoding="ascii").splitlines()) == WINDOWS and
                len((build / "expected_windows.hex").read_text(encoding="ascii").splitlines()[0]) == 160 and
                len((build / "expected_window_masks.hex").read_text(encoding="ascii").splitlines()) == WINDOWS,
                "20-site independent window fixture shape")
        oracle = generated_oracle()
        (build / "expected_scheduler_oracle.json").write_text(
            json.dumps(oracle, indent=2) + "\n", encoding="utf-8", newline="\n")
        result["fixture"] = fixture
        result["oracle"] = {"command": oracle["command"], "runs": len(oracle["runs"]),
                            "descriptors": len(oracle["descriptors"]),
                            "tags_first_last": [oracle["descriptors"][0]["tag"],
                                                oracle["descriptors"][-1]["tag"]],
                            "run7_run8_boundary": [oracle["descriptors"][71], oracle["descriptors"][72]],
                            "stalled_descriptor_expectations": "all outputs compared each stalled cycle and accepted handshake in RTL testbench"}
        result["source_sha256_before"] = before
        after = {helper.rel(path): sha(path) for path in source_list}
        require(before == after, "host preflight source changed while generating fixtures")
        result["source_sha256_after"] = after
        result["fixture_sha256"] = {helper.rel(path): sha(path)
                                    for path in sorted(build.glob("*")) if path.is_file()}
        result["source_snapshot_sha256"] = {helper.rel(path): sha(out / "src" / helper.rel(path))
                                            for path in source_list}
        result["status"] = "PASS_EPOCH200_SCHEDULED_ROW20_HOST_ONLY"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["source_sha256_after"] = result.get("source_sha256_before", {})
    finally:
        helper = sys.modules.get("scheduled_row20_packed_helper")
        if helper is not None:
            result["artifact_sha256"] = {str(path.relative_to(ROOT).as_posix()): sha(path)
                                         for base in (out, build) for path in base.rglob("*")
                                         if path.is_file() and path != report_path}
        report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "report": str(report_path),
                      "build": str(build), "error": result.get("error")}))
    if result["status"] != "PASS_EPOCH200_SCHEDULED_ROW20_HOST_ONLY":
        raise SystemExit(1)
    return report_path


def xsim_from_host(host_report_path: Path) -> None:
    host_report_path = host_report_path.resolve()
    require(host_report_path.is_file(), f"host preflight report is missing: {host_report_path}")
    data = json.loads(host_report_path.read_text(encoding="utf-8"))
    require(data.get("status") == "PASS_EPOCH200_SCHEDULED_ROW20_HOST_ONLY",
            "XSim requires a passing host-only preflight")
    require(not data.get("commands"), "host result already contains vendor commands")
    out = host_report_path.parent
    build = ROOT / Path(*PurePosixPath(data["build_dir"]).parts)
    report_path = host_report_path
    before = data["source_sha256_before"]
    for name, digest in before.items():
        path = resolve_report_path(name)
        require(path.is_file() and sha(path) == digest, f"source changed since host preflight: {name}")
    for name, digest in data["fixture_sha256"].items():
        path = resolve_report_path(name)
        require(path.is_file() and sha(path) == digest, f"host fixture changed before XSim: {name}")
    for tool in ("xvlog.bat", "xelab.bat", "xsim.bat"):
        require((Path("C:/appload/2026.1/Vivado/bin") / tool).is_file(),
                f"Vivado 2026.1 XSim executable missing: {tool}")
    require(build.is_dir(), f"host fixture build directory missing: {build}")
    require(data["model_identity"]["checkpoint_sha256"] == EXPECTED_CHECKPOINT_SHA256,
            "host result does not bind selected epoch200 checkpoint")

    helper = load("scheduled_row20_packed_helper_xsim", ROOT / "tools/validate_z100_window_mac_packed.py")
    xsim_rtl = list(RTL)
    command_start = len(data["commands"])
    data["status"] = "XSIM_RUNNING"
    data["execution"] = {"phase": "one XSim only; no OOC or route",
                          "testbench": TB.relative_to(ROOT).as_posix(),
                          "scheduler": SCHEDULER.relative_to(ROOT).as_posix(),
                          "row": ROW.relative_to(ROOT).as_posix(),
                          "compiled_rtl": [p.relative_to(ROOT).as_posix() for p in xsim_rtl],
                          "post_done_source": "post_valid && post_ready && post_last",
                          "xelab_max_threads_explicit": 2}
    report_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    try:
        helper.run("xvlog", [helper.VIVADO / "xvlog.bat", "-sv", *xsim_rtl, helper.GLBL], build, out, data)
        helper.run("xelab", [helper.VIVADO / "xelab.bat", "-mt", "2", "-L", "unimacro_ver",
                              "-L", "unisims_ver", "tb_z100_native_scheduled_row20", "glbl",
                              "-s", "scheduled_row20_sim"], build, out, data)
        text = helper.run("xsim", [helper.VIVADO / "xsim.bat", "scheduled_row20_sim", "-runall"],
                          build, out, data)
        markers = re.findall(r"^NATIVE_SCHEDULED_ROW20_PASS ([^\r\n]+)$", text, re.M)
        require(len(markers) == 1, "expected exactly one scheduled-row numeric PASS marker")
        values = {key: int(value) for key, value in re.findall(r"([a-zA-Z0-9_]+)=(\d+)", markers[0])}
        exact = {
            "commands": 1, "runs": RUNS, "requests": WINDOWS, "responses": WINDOWS,
            "window_bytes": WINDOWS * 80, "masks": WINDOWS,
            "raw_beats": ROW_WIDTH, "raw_lanes": ROW_WIDTH * 32, "raw_flags": ROW_WIDTH * 32,
            "post_beats": ROW_WIDTH, "active_bytes": ROW_WIDTH * 16, "tail_bytes": ROW_WIDTH * 16,
            "packed_words": 80, "packed_bytes": 80 * 64,
            "feature_loads": 80, "weight_groups": GROUPS, "bias_loads": 1,
            "req_words": 255, "unary_bytes": 256, "full_buffers": 1,
            "packed_hold_checks": 4, "done": 1, "post_done": RUNS, "scheduler_done": 1,
            "scheduler_faults": 0, "scheduler_aborts": 0, "boundary_descriptors": 2,
            "raw_site15": RUNS, "raw_site16": RUNS, "post_site15": RUNS, "post_site16": RUNS,
            "max_runsites": SITES, "tail_sites": SITES,
        }
        for key, expected in exact.items():
            require(values.get(key) == expected,
                    f"XSim count {key}={values.get(key)!r}; expected {expected}")
        for key in ("packed_stall", "req_stall", "unary_stall", "response_stalls"):
            require(values.get(key, 0) > 0, f"required natural backpressure missing: {key}")
        require(values.get("packed_hold_checks", 0) >= 4,
                "output packer held metadata stability checks missing")
        require(len(data["commands"]) - command_start == 3 and
                [item["name"] for item in data["commands"][command_start:]] == ["xvlog", "xelab", "xsim"],
                "expected one compile/elaboration and exactly one XSim command")
        data.update(status="PASS_EPOCH200_SCHEDULED_ROW20_COMPLETE_NUMERIC_XSIM_ONLY",
                    observed_counts=values,
                    acceptance_limits={"full_graph": False, "model_quality": False,
                                       "physical_timing": False, "board": False,
                                       "throughput_or_fps": False},
                    performance_claims_made=False)
    except Exception as exc:
        data["status"] = "FAILED_CLOSED"
        data["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        after = {name: sha(resolve_report_path(name)) for name in before}
        data["source_sha256_after"] = after
        if after != before:
            data["status"] = "FAILED_SOURCE_INTEGRITY"
            data["error"] = "source/dependency changed during scheduled row XSim"
        data["artifact_sha256"] = {str(path.relative_to(ROOT).as_posix()): sha(path)
                                   for base in (out, build) for path in base.rglob("*")
                                   if path.is_file() and path != report_path}
        report_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": data["status"], "report": str(report_path),
                      "error": data.get("error"), "observed_counts": data.get("observed_counts")}))
    if data["status"] != "PASS_EPOCH200_SCHEDULED_ROW20_COMPLETE_NUMERIC_XSIM_ONLY":
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("host", "xsim"), required=True)
    parser.add_argument("--host-result", type=Path)
    args = parser.parse_args()
    if args.phase == "host":
        require(args.host_result is None, "--host-result is only for --phase xsim")
        host_preflight()
    else:
        require(args.host_result is not None, "--phase xsim requires --host-result")
        xsim_from_host(args.host_result)


if __name__ == "__main__":
    main()
