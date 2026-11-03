#!/usr/bin/env python3
"""Prepare, but do not execute, the guard-v3 local-control first-Conv golden.

This stages the frozen original numeric fixture and makes a build-local copy of
the frozen MMIO testbench. It records an exact Icarus compile/run command for a
later, separately authorized run. This script never invokes a compiler,
simulator, Vivado, or board tooling.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TARGET_BUILD = ROOT / "deployment/build/guard_v3_local_control/20261027T004231.613549Z_e921f0"
TARGET_MANIFEST = TARGET_BUILD / "source_manifest.json"
TARGET_COMPILE_PLAN = TARGET_BUILD / "compile_plan.json"
BASE_MANIFEST = ROOT / "deployment/build/z100_native_conv_backend_v3_review/20261026T063511.355431Z/source_manifest.json"
GUARD_MANIFEST = ROOT / "deployment/hardware/z100_2026/native_conv_backend_v3_resident_guard_v3/source_manifest_guard_v3.json"
LOCAL_CONTROL_BASE_MANIFEST = ROOT / "deployment/build/native_mmio_local_control_platform_v2/20261026T172223.926133Z_d47494/source_manifest.json"
GUARD_LOADER_RESULT = ROOT / "validation/board_z100/guard_v3_loader_integration/20261027T002327.500626Z/result.json"
FIXTURE_RESULT = ROOT / "validation/board_z100/native_conv_first_event_v2/20261026T064115.441661Z/result.json"
FIXTURE_BUILD = ROOT / "deployment/build/native_conv_first_event_v2/20261026T064115.441661Z"
MMIO_TB = ROOT / "deployment/simulation/native_conv_mmio_first_event_v1/tb_z100_native_conv_mmio_first_event_v1.sv"
OLD_MMIO_WRAPPER = ROOT / "deployment/hardware/z100_2026/native_conv_mmio_backend_v1/z100_native_conv_mmio_backend_v1.sv"
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64"
VENDOR = Path("C:/appload/2026.1/data/verilog/src")
BUILD_ROOT = ROOT / "deployment/build/guard_v3_local_numeric"
EVIDENCE_ROOT = ROOT / "validation/board_z100/guard_v3_local_numeric"

FIXTURE_ASSETS = (
    "conv_event_map.hex", "conv_tiles.hex", "directory.hex", "parameter_memory.hex",
    "input_native_DDR.hex", "expected_raw_words.hex", "expected_post_words.hex",
    "expected_packed_words.hex", "expected_native_DDR.hex",
)
FIXTURE_HASHES = {
    "conv_event_map.hex": "7f5dbedbc8b0487350ea40465b2e6ae1bc404e6c167da25b72cedf94e4dbaf85",
    "conv_tiles.hex": "8295ab50a944c6b8c61b97515d8a388919f287dd2c487c63c6da997a64c99f0c",
    "directory.hex": "41dab50f4db049ee3072cf41a7cd5927368f6f7a2b2608c1396c93b6d020ac93",
    "parameter_memory.hex": "d820670a3577e08b2cce29522f6500ae59dc32298e0eae30a7685090530d1cc2",
    "input_native_DDR.hex": "4a40ee9516e069766aa1974d02a6eef09cccafa4a7e83923b5d2653f728055ce",
    "expected_raw_words.hex": "624f4417828a755b2bc71a2d63d6afc172e9a2e13abea70c799c068ad3128c56",
    "expected_post_words.hex": "48cd3d7f3cafe8d4469c14d1ecbc2af830cd747c2d0f531ec6a6ce2f267f2271",
    "expected_packed_words.hex": "06d3cf5cd1aeae8d6da0986bb2bbd83489ab89f77f1c3948a62b28793a7fa3bb",
    "expected_native_DDR.hex": "c75f14182d94f6da45829c51213000f78e1d9a2a3de90784a42ea6840c80c662",
}
PINNED_HASHES = {
    "base_manifest": "eee8d10d1e2f12ee06580727e77e4745e7fccf3d87245b7e06709c35f319fe95",
    "guard_manifest": "a0604e781a90a89c43c246fa4c59b6164625a98fdc464a6ef868a86ea74b3351",
    "guard_loader_result": "c490c4bb626c035f7175fe3aa09fef237937de25f2b312e79164fed3be02cabc",
    "fixture_result": "ff70818979fee2a6c42d40932316f1a083154a3e61e72eb52a91824c15718799",
    "mmio_testbench": "782dfb4d640cb36e4dfc4dc77aea29fb72453105d328da6150e04815d3efaf5b",
    "old_mmio_wrapper": "cfc78bf8e21e8d1ede3915bda1675f85e21606b7637c662f78e169daf4d1181b",
}
VENDOR_HASHES = {
    "DSP48E1.v": "4060111c8de44f786fdc982de9caaa88fc0b2c44fcd6d0f0f7ec188a58793bd0",
    "MULT_MACRO.v": "d8ad46e2f5c808f52d4029025695ff7f67d6526c009bcaba0a75e84eecc27a2c",
    "glbl.v": "6270251cf35e1fce3119fc79f8fb968912f7983027e43cf030409ba68f048936",
}
SIMULATOR_HASHES = {
    "iverilog.exe": "25e1ba02e72f58d9d484bc5457d69a6b179d22d86bdf5ba5d6f9f0d4fe620bbf",
    "vvp.exe": "f0775603e1f1bcf1b2dea16dff963a4b7d71b7b33d5bbe23d2b01ff5b2304e09",
}
TOP = "tb_z100_native_conv_mmio_first_event_v1"
PASS_PREFIX = "MMIO_FIRST_EVENT_PASS "
OLD_INSTANCE = "z100_native_conv_mmio_backend_v1 #("
PARAMETER_COUNT_OLD = "directory_r_count+payload_r_count!=3712 ||"
PARAMETER_MARKER_OLD = "parameter_R=3712 output_W=204800"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def repo_path(name: str) -> Path:
    path = (ROOT / name).resolve()
    require(path.is_relative_to(ROOT.resolve()), f"Repository path escaped root: {name}")
    return path


def source_key(path: Path) -> str:
    try:
        return relative(path)
    except ValueError:
        return "external/" + path.as_posix()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def module_ports(text: str, module: str) -> list[str]:
    match = re.search(
        rf"module\s+{re.escape(module)}\s*#\s*\(.*?\)\s*\((.*?)\)\s*;",
        text,
        re.S,
    )
    require(match is not None, f"Could not read module port list: {module}")
    return re.findall(
        r"\b(?:input|output|inout)\s+(?:(?:wire|reg|logic)\s+)?(?:\[[^\]]+\]\s*)?(\w+)",
        match.group(1),
    )


def pin_file(path: Path, pins: dict[str, str], expected: str | None = None) -> str:
    require(path.is_file(), f"Missing source/artifact: {path}")
    digest = sha256(path)
    if expected is not None:
        require(digest == expected, f"SHA-256 mismatch: {path}")
    pins[source_key(path)] = digest
    return digest


def local_control_closure(pins: dict[str, str]) -> tuple[dict, list[Path], dict]:
    pin_file(TARGET_MANIFEST, pins)
    pin_file(TARGET_COMPILE_PLAN, pins)
    manifest = read_json(TARGET_MANIFEST)
    plan = read_json(TARGET_COMPILE_PLAN)
    require(manifest.get("status") == "PREPARED_SOURCE_CLOSURE_ONLY_NOT_ELABORATED",
            "Local-control source manifest is not the frozen prepared closure")
    require(plan.get("status") == "PLANNED_NOT_EXECUTED" and plan.get("executed") is False,
            "Local-control compile plan was executed or changed")
    require(manifest.get("production_top") == "z100_native_conv_mmio_local_control_resident_guard_v3",
            "Unexpected local-control production top")
    require(manifest.get("backend_top") == "z100_native_conv_backend_local_control_resident_guard_v3",
            "Unexpected local-control backend top")
    require(manifest.get("core_top") == "z100_native_row20_shared_pool_address_shared_local_control_v1",
            "Unexpected local-control compute core")
    require(manifest.get("mac_top") == "z100_window_mac_local_control_v1",
            "Unexpected local-control MAC")
    require(manifest.get("target_part") == "xc7z100ffg900-2" and
            manifest.get("core_DSP48E1_target") == 2016,
            "Target part or 2016 DSP mapping changed")
    require(manifest.get("core_route_execution_verified") is False and
            manifest.get("integrated_resource_usage_measured") is False,
            "Prepared source closure unexpectedly claims route/resource execution")
    checks = manifest.get("mapping_checks", {})
    require(checks and all(value is True for value in checks.values()),
            "A recorded source-closure mapping check did not pass")
    require(manifest.get("source_count") == 41 and manifest.get("rtl_module_count") == 38 and
            manifest.get("rom_count") == 2 and manifest.get("abi_header_count") == 1,
            "Local-control source closure cardinality changed")
    require(len(manifest.get("sources", [])) == 41, "Source manifest entry count changed")

    base_manifest_path = repo_path(manifest["base_local_control_manifest"])
    base_result_path = repo_path(manifest["base_local_control_preparation_result"])
    guard_manifest_path = repo_path(manifest["guard_v3_manifest"])
    guard_loader_path = repo_path(manifest["guard_v3_loader_evidence"])
    pin_file(base_manifest_path, pins, manifest["base_local_control_manifest_sha256"])
    pin_file(base_result_path, pins, manifest["base_local_control_preparation_result_sha256"])
    pin_file(guard_manifest_path, pins, manifest["guard_v3_manifest_sha256"])
    pin_file(guard_loader_path, pins, manifest["guard_v3_loader_evidence_sha256"])
    loader = read_json(guard_loader_path)
    require(manifest.get("guard_v3_loader_status") == "PASS_V3_REAL_LOADER_HARNESS_ONLY" and
            manifest.get("guard_v3_loader_checks") == 53 and
            loader.get("status") == "PASS_V3_REAL_LOADER_HARNESS_ONLY",
            "Guard-v3 loader prerequisite differs from the source manifest")
    require(sha256(BASE_MANIFEST) == PINNED_HASHES["base_manifest"],
            "Pinned base V3 manifest changed")
    require(sha256(GUARD_MANIFEST) == PINNED_HASHES["guard_manifest"],
            "Pinned guard-v3 manifest changed")
    require(sha256(GUARD_LOADER_RESULT) == PINNED_HASHES["guard_loader_result"],
            "Pinned guard-v3 loader evidence changed")
    require(base_manifest_path == LOCAL_CONTROL_BASE_MANIFEST and guard_manifest_path == GUARD_MANIFEST and
            guard_loader_path == GUARD_LOADER_RESULT,
            "Local-control source manifest points at different upstream evidence")
    pin_file(BASE_MANIFEST, pins, PINNED_HASHES["base_manifest"])
    pin_file(GUARD_MANIFEST, pins, PINNED_HASHES["guard_manifest"])
    pin_file(GUARD_LOADER_RESULT, pins, PINNED_HASHES["guard_loader_result"])

    records = manifest["sources"]
    rtl_sources: list[Path] = []
    source_roles: dict[str, int] = {}
    by_path: dict[str, dict] = {}
    for entry in records:
        rel = entry.get("path")
        require(isinstance(rel, str), "Malformed source manifest entry")
        path = repo_path(rel)
        pin_file(path, pins, entry.get("sha256"))
        source_roles[entry.get("role", "unknown")] = source_roles.get(entry.get("role", "unknown"), 0) + 1
        by_path[rel] = entry
        if path.suffix.lower() == ".sv":
            rtl_sources.append(path)
    require(len(rtl_sources) == 38, "Expected 38 local-control SystemVerilog sources")
    require(sum(1 for item in records if Path(item["path"]).suffix.lower() == ".hex") == 2,
            "Expected the two frozen ROM assets in the source closure")
    require(sum(1 for item in records if Path(item["path"]).suffix.lower() == ".h") == 1,
            "Expected the single frozen ABI header in the source closure")

    top_entries = [entry for entry in records if entry.get("role") == "production_top"]
    require(len(top_entries) == 1, "Could not uniquely locate the local-control MMIO wrapper")
    top_path = repo_path(top_entries[0]["path"])
    top_text = top_path.read_text(encoding="utf-8", errors="replace")
    require(re.search(rf"\bmodule\s+{re.escape(manifest['production_top'])}\b", top_text),
            "Production-top module declaration does not match source manifest")
    require(re.search(r"\bu_conv_backend\s*\(", top_text) and
            re.search(r"\bu_mmio_frontend\s*\(", top_text),
            "Local-control top does not preserve frozen testbench instance paths")

    backend_matches = []
    core_matches = []
    mac_matches = []
    for path in rtl_sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(rf"\bmodule\s+{re.escape(manifest['backend_top'])}\b", text):
            backend_matches.append((path, text))
        if re.search(rf"\bmodule\s+{re.escape(manifest['core_top'])}\b", text):
            core_matches.append((path, text))
        if re.search(rf"\bmodule\s+{re.escape(manifest['mac_top'])}\b", text):
            mac_matches.append((path, text))
    require(len(backend_matches) == len(core_matches) == len(mac_matches) == 1,
            "Could not uniquely map the local-control backend/core/MAC modules")
    backend_path, backend_text = backend_matches[0]
    require(re.search(rf"\b{re.escape(manifest['backend_top'])}\s*#\s*\(.*?\)\s*u_conv_backend\b",
                      top_text, re.S),
            "The testbench u_conv_backend hierarchy does not select the local-control backend")
    require(all(name in backend_text for name in (
        "resident_cmd_valid", "resident_cmd_ready",
        "resident_downstream_cmd_valid", "directory_ready",
    )), "Residency request/load monitor nets are absent from the selected backend")

    # The golden testbench probes many internal backend signals. Verify every
    # referenced identifier still exists textually in the selected backend.
    frozen_tb_text = MMIO_TB.read_text(encoding="utf-8", errors="replace")
    backend_refs = sorted(set(re.findall(r"\bdut\.u_conv_backend\.(\w+)", frozen_tb_text)))
    missing_backend_refs = [name for name in backend_refs
                            if not re.search(rf"\b{re.escape(name)}\b", backend_text)]
    require(not missing_backend_refs,
            "Local-control backend misses frozen TB hierarchy names: " + ", ".join(missing_backend_refs))
    return manifest, rtl_sources, {
        "source_roles": source_roles,
        "top_path": top_path,
        "top_text": top_text,
        "backend_path": backend_path,
        "backend_text": backend_text,
        "core_path": core_matches[0][0],
        "mac_path": mac_matches[0][0],
        "backend_hierarchical_reference_count": len(backend_refs),
    }


def verify_golden_inputs(pins: dict[str, str]) -> tuple[dict, dict[str, str]]:
    require(sha256(FIXTURE_RESULT) == PINNED_HASHES["fixture_result"],
            "Frozen first-event fixture result changed")
    require(sha256(MMIO_TB) == PINNED_HASHES["mmio_testbench"],
            "Frozen numerical MMIO testbench changed")
    require(sha256(OLD_MMIO_WRAPPER) == PINNED_HASHES["old_mmio_wrapper"],
            "Frozen original MMIO wrapper changed")
    pin_file(FIXTURE_RESULT, pins, PINNED_HASHES["fixture_result"])
    pin_file(MMIO_TB, pins, PINNED_HASHES["mmio_testbench"])
    pin_file(OLD_MMIO_WRAPPER, pins, PINNED_HASHES["old_mmio_wrapper"])
    fixture = read_json(FIXTURE_RESULT)
    require(fixture.get("status") == "PREPARED_LOCAL_ELABORATION_PASS_NUMERICAL_UNEXECUTED" and
            fixture.get("numerical_simulation_run") is False,
            "Frozen first-event fixture has unexpected status")
    require(fixture.get("build_dir") == relative(FIXTURE_BUILD),
            "Frozen numeric golden fixture points to a different build")
    artifact_map = fixture.get("artifact_sha256", {})
    staged: dict[str, str] = {}
    for name in FIXTURE_ASSETS:
        src = FIXTURE_BUILD / name
        expected = FIXTURE_HASHES[name]
        artifact_key = (FIXTURE_BUILD.relative_to(ROOT) / name).as_posix()
        require(src.is_file() and sha256(src) == expected and artifact_map.get(artifact_key) == expected,
                f"Original fixed golden fixture identity mismatch: {name}")
        target_asset = TARGET_BUILD / "assets" / name
        if name in ("conv_event_map.hex", "conv_tiles.hex"):
            require(target_asset.is_file() and sha256(target_asset) == expected,
                    f"Local-control build uses a different first-event ROM asset: {name}")
            pin_file(target_asset, pins, expected)
        pin_file(src, pins, expected)
        staged[name] = expected
    return fixture, staged


def generate_testbench(build: Path, top_name: str) -> tuple[Path, str, dict]:
    original = MMIO_TB.read_text(encoding="utf-8")
    require(original.count(OLD_INSTANCE) == 1, "Expected one frozen MMIO DUT instance")
    generated = original.replace(OLD_INSTANCE, top_name + " #(", 1)

    instrumentation = """
    integer resident_accepts = 0, resident_loads = 0;
    always @(posedge clk) begin
        if (!rst_n) begin resident_accepts <= 0; resident_loads <= 0; end
        else begin
            if (dut.u_conv_backend.resident_cmd_valid && dut.u_conv_backend.resident_cmd_ready)
                resident_accepts <= resident_accepts + 1;
            if (dut.u_conv_backend.resident_downstream_cmd_valid && dut.u_conv_backend.directory_ready)
                resident_loads <= resident_loads + 1;
        end
    end
"""
    counter_anchor = "    integer directory_r_count = 0, payload_r_count = 0;"
    require(generated.count(counter_anchor) == 1, "Unique residency counter insertion seam missing")
    generated = generated.replace(counter_anchor, counter_anchor + instrumentation, 1)
    require(generated.count(PARAMETER_COUNT_OLD) == 1, "Frozen parameter-beat count seam missing")
    generated = generated.replace(
        PARAMETER_COUNT_OLD,
        "directory_r_count!=8 || payload_r_count!=224 || resident_accepts!=16 || resident_loads!=1 ||",
        1,
    )
    require(generated.count(PARAMETER_MARKER_OLD) == 1, "Frozen parameter marker seam missing")
    generated = generated.replace(
        PARAMETER_MARKER_OLD,
        "parameter_R=232 directory_R=8 payload_R=224 resident_accepts=16 resident_loads=1 output_W=204800",
        1,
    )

    # Exact literal assertions establish that numerical and transaction checks
    # remain in the generated copy; only the wrapper selection and residency
    # accounting above are changed.
    preserved = {
        "raw golden comparison": "raw_data,raw_overflow}!==expected_raw[raw_count]" in generated,
        "post golden comparison": "post_data!==expected_post[post_count]" in generated,
        "packed golden comparison": "packed_data!==expected_packed[packed_global_index]" in generated,
        "native DDR golden comparison": "output_memory[i*8+j]!==expected_native_ddr[i][j*64 +: 64]" in generated,
        "output guard check": "output_memory[i]!==GUARD" in generated,
        "MMIO ACK assertion": "mmio_ack_count!=1" in generated and "MMIO ACK did not clear terminal state/grants" in generated,
        "MMIO result assertion": "mmio_read_value!==mmio_expected_results[mmio_result_index]" in generated,
        "physical output write count": "w_count!=OUTPUT_W_BEATS" in generated,
    }
    require(all(preserved.values()), "Generated testbench dropped a frozen numeric/DDR/ACK assertion")
    require(generated.count(OLD_INSTANCE) == 0 and generated.count(top_name + " #(") == 1,
            "Generated testbench did not select exactly one local-control wrapper")
    generated_path = build / "tb_z100_native_conv_mmio_first_event_local_control.sv"
    generated_path.write_text(generated, encoding="utf-8", newline="\n")
    changes = {
        "wrapper_rename": "select local-control resident guard-v3 production top",
        "instrumentation": "count 16 residency requests and 1 downstream directory/payload load",
        "parameter_beats": {"directory_R": 8, "payload_R": 224, "parameter_R": 232},
        "frozen_assertions_preserved": preserved,
        "generated_testbench_sha256": sha256(generated_path),
    }
    return generated_path, generated, changes


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    created = datetime.now(timezone.utc).isoformat()
    build = BUILD_ROOT / stamp
    evidence = EVIDENCE_ROOT / stamp
    build.mkdir(parents=True, exist_ok=False)
    evidence.mkdir(parents=True, exist_ok=False)
    report_path = evidence / "result.json"
    report: dict = {
        "schema": "z100-guard-v3-local-control-numeric-preparation/1",
        "status": "STATIC_PREFLIGHT",
        "created_utc": created,
        "board_access": False,
        "vivado_started": False,
        "compiler_executed": False,
        "simulator_executed": False,
        "numerical_simulation_run": False,
        "synthesis_run": False,
        "route_run": False,
        "physical_30fps_accepted": False,
        "full_tensor_publication_claimed": False,
        "build_dir": relative(build),
        "validation_dir": relative(evidence),
        "source_closure_build": relative(TARGET_BUILD),
        "scope": (
            "Prepare the original frozen first-Conv golden test for the guard-v3 + 2016 DSP local-control "
            "source closure. The script performs static hash, mapping and testbench-hierarchy checks, stages "
            "the original fixture and writes reproducible Icarus commands. It never compiles or simulates."
        ),
    }
    pins: dict[str, str] = {}
    try:
        require(sha256(BASE_MANIFEST) == PINNED_HASHES["base_manifest"],
                "Pinned base V3 source manifest changed")
        require(sha256(GUARD_MANIFEST) == PINNED_HASHES["guard_manifest"],
                "Pinned guard-v3 source manifest changed")
        require(sha256(GUARD_LOADER_RESULT) == PINNED_HASHES["guard_loader_result"],
                "Pinned guard-v3 loader evidence changed")
        manifest, rtl_sources, mapping = local_control_closure(pins)
        fixture, fixture_hashes = verify_golden_inputs(pins)
        pin_file(Path(__file__).resolve(), pins)

        top_name = manifest["production_top"]
        old_ports = module_ports(OLD_MMIO_WRAPPER.read_text(encoding="utf-8"), "z100_native_conv_mmio_backend_v1")
        new_ports = module_ports(mapping["top_text"], top_name)
        require(old_ports == new_ports and len(old_ports) == 50,
                "Local-control MMIO top ports differ from the frozen original MMIO wrapper")
        require(len(old_ports) == len(set(old_ports)), "MMIO wrapper port list contains duplicate names")

        generated_tb_path, generated_tb_text, tb_changes = generate_testbench(build, top_name)
        pin_file(generated_tb_path, pins)

        for name in FIXTURE_ASSETS:
            dst = build / name
            src = FIXTURE_BUILD / name
            dst.write_bytes(src.read_bytes())
            pin_file(dst, pins, FIXTURE_HASHES[name])

        vendor_paths = [
            VENDOR / "unisims/DSP48E1.v",
            VENDOR / "unimacro/MULT_MACRO.v",
            VENDOR / "glbl.v",
        ]
        for vendor_path in vendor_paths:
            pin_file(vendor_path, pins, VENDOR_HASHES[vendor_path.name])

        compiler = LOCAL / "bin/iverilog.exe"
        simulator = LOCAL / "bin/vvp.exe"
        require(compiler.is_file() and simulator.is_file(), "Pinned project-local Icarus tools are missing")
        pin_file(compiler, pins, SIMULATOR_HASHES[compiler.name])
        pin_file(simulator, pins, SIMULATOR_HASHES[simulator.name])

        image = build / "guard_v3_local_control_numeric.vvp"
        runtime_lib = LOCAL / "lib/ivl"
        compile_argv = [
            str(compiler), "-B", str(runtime_lib), "-g2012", "-Wall",
            "-s", TOP, "-s", "glbl", "-o", str(image),
            *map(str, rtl_sources), *map(str, vendor_paths), str(generated_tb_path),
        ]
        simulation_argv = [str(simulator), "-M", str(runtime_lib), str(image)]

        commands = {
            "executed": False,
            "working_directory": str(build.resolve()),
            "compile_argv": compile_argv,
            "simulation_argv": simulation_argv,
            "compile_tool": "Icarus Verilog project-local 13.0",
            "compile_and_simulation_not_invoked_by_preparer": True,
        }
        commands_path = build / "commands.json"
        commands_path.write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
        powershell_command = [
            "Set-Location -LiteralPath " + chr(39) + str(build.resolve()).replace(chr(39), chr(39)*2) + chr(39),
            "& " + " ".join((chr(39) + arg.replace(chr(39), chr(39)*2) + chr(39)) for arg in compile_argv),
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
            "& " + " ".join((chr(39) + arg.replace(chr(39), chr(39)*2) + chr(39)) for arg in simulation_argv),
            "exit $LASTEXITCODE",
        ]
        run_script = build / "run_prepared_numeric.ps1"
        run_script.write_text(
            "# Prepared command only; not executed by the validator.\n"
            "# Recheck that no guard-v3 numeric simulation or route is active before use.\n"
            + "\n".join(powershell_command) + "\n",
            encoding="utf-8",
        )
        pin_file(commands_path, pins)
        pin_file(run_script, pins)

        expected_coverage = {
            "tiles": 16,
            "raw_records": 102400,
            "post_records": 102400,
            "packed_words": 25600,
            "source_R_beats": 209600,
            "parameter_requests": 16,
            "directory_R_beats": 8,
            "payload_R_beats": 224,
            "parameter_R_beats": 232,
            "resident_physical_loads": 1,
            "output_W_beats": 204800,
            "output_AW_B_bursts": 12800,
            "output_guard_beats": 57344,
            "mmio_shadow_writes": 27,
            "mmio_start_acknowledgements": 1,
            "mmio_result_reads": 10,
        }
        report.update(
            status="PREPARED_LOCAL_CONTROL_FIRST_CONV_GOLDEN_NOT_EXECUTED",
            selected_wrapper=top_name,
            selected_backend=manifest["backend_top"],
            selected_core=manifest["core_top"],
            selected_mac=manifest["mac_top"],
            target_part=manifest["target_part"],
            core_DSP48E1_target=manifest["core_DSP48E1_target"],
            route_execution_verified=manifest["core_route_execution_verified"],
            integrated_resource_usage_measured=manifest["integrated_resource_usage_measured"],
            source_count=len(manifest["sources"]),
            rtl_source_count=len(rtl_sources),
            wrapper_port_count=len(old_ports),
            backend_hierarchical_reference_count=mapping["backend_hierarchical_reference_count"],
            source_roles=mapping["source_roles"],
            source_manifest_sha256=sha256(TARGET_MANIFEST),
            compile_plan_sha256=sha256(TARGET_COMPILE_PLAN),
            source_sha256_before=pins.copy(),
            generated_testbench=relative(generated_tb_path),
            generated_testbench_change=tb_changes,
            fixed_original_fixture_result=relative(FIXTURE_RESULT),
            frozen_fixture_status=fixture["status"],
            original_fixture_sha256=fixture_hashes,
            original_fixture_numeric_execution=fixture["numerical_simulation_run"],
            expected_coverage=expected_coverage,
            compile_and_simulation_commands=commands,
            reproducible_command_script=relative(run_script),
            expected_pass_marker=PASS_PREFIX.strip(),
            golden_scope=(
                "The fixture is structurally applicable: both local-control ROM assets match the original "
                "first-event golden hashes, the MMIO wrapper exposes the same 50 ports, and all frozen "
                "backend hierarchy names resolve in the selected local-control backend. Numerical match "
                "remains unverified until the later, separately authorized Icarus run."
            ),
        )

        source_after = {}
        for key, expected in pins.items():
            path = Path(key.removeprefix("external/")) if key.startswith("external/") else repo_path(key)
            actual = sha256(path) if path.is_file() else None
            source_after[key] = actual
            if actual != expected:
                raise ValueError(f"Source changed during static preparation: {key}")
        report["source_sha256_after"] = source_after
        report["artifact_sha256"] = {
            relative(path): sha256(path)
            for folder in (build, evidence)
            for path in folder.rglob("*")
            if path.is_file() and path != report_path
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        report.update(status="FAILED_STATIC_PREFLIGHT", error=f"{type(exc).__name__}: {exc}")
        report["source_sha256_before"] = pins
        report["source_sha256_after"] = {
            key: (
                sha256(Path(key.removeprefix("external/")))
                if key.startswith("external/") and Path(key.removeprefix("external/")).is_file()
                else sha256(repo_path(key))
                if not key.startswith("external/") and repo_path(key).is_file()
                else None
            )
            for key in pins
        }
        report["artifact_sha256"] = {
            relative(path): sha256(path)
            for folder in (build, evidence)
            for path in folder.rglob("*")
            if path.is_file() and path != report_path
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": report["status"],
        "report": relative(report_path),
        "error": report.get("error"),
        "numerical_simulation_run": report.get("numerical_simulation_run", False),
        "compile_and_simulation_executed": False,
    }, indent=2))
    return 0 if report["status"].startswith("PREPARED_") else 1


if __name__ == "__main__":
    raise SystemExit(main())



