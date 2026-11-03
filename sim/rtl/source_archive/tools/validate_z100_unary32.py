"""Validate private 32-lane exact unary table stream in XSim and OOC synthesis."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "deployment/hardware/z100_2026/unary32_v1"
RTL = FIXTURE / "z100_unary32.sv"
TB = FIXTURE / "tb_z100_unary32.sv"
SCRIPT = Path(__file__).resolve()
ASSET_BUILD = ROOT / "deployment/build/z100_pointwise_tables_v1/20261023T165100.884151Z_5e3e437d"
ASSET_MANIFEST = ASSET_BUILD / "tables_manifest.json"
ASSET_RESULT = ROOT / "validation/board_z100/pointwise_tables_v1/20261023T165100.884151Z_5e3e437d/result.json"
VIVADO = Path(r"C:\appload\2026.1\Vivado\bin\vivado.bat")
EXPECTED_MANIFEST_SHA256 = "69470ca5d7eb8a19a8f48d9002b6d63cddc5787e57e0a09b44a724711307e2fc"
EXPECTED_ASSET_STATUS = "PASS_PIN640_POINTWISE_TABLES_HOST_ONLY"
EXPECTED_C_UNARY_VALUES = 31_232
EXPECTED_C_ADD_PAIRS = 393_216
EXPECTED_SILU_BYTES = 14_592
EXPECTED_TABLES = 57
PART = "xc7z100ffg900-2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_dependencies(asset_result: dict[str, Any]) -> dict[str, Path]:
    dependencies: dict[str, Path] = {
        "pointwise_tables_manifest": ASSET_MANIFEST,
        "pointwise_tables_evidence": ASSET_RESULT,
        "model_package": ROOT / "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/package/MODEL.V8P",
        "generated_model_header": ROOT / "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/package/v8_generated_model.h",
        "model_graph": ROOT / "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/model/graph.json",
        "runtime_source": ROOT / "deployment/candidates/pin640/firmware/v8_runtime.c",
        "runtime_header": ROOT / "deployment/candidates/pin640/firmware/v8_runtime.h",
        "c_oracle": ROOT / "deployment/hardware/z100_2026/pointwise_tables_v1/oracle.c",
        "table_preparer": ROOT / "tools/prepare_z100_pointwise_tables.py",
    }
    for path in dependencies.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    expected = {
        "model_package": "96211aa416da6b23955a8b62cca594275daaa4db3e3954632960707c0ec0d44f",
        "generated_model_header": "eb01437b8a70254472c6b06f4798b378644d61789aa72fd516c4c329dea953b5",
        "model_graph": "6ad39858999c9d7bc57b44887ad487f38a1a678d32e887a1c5c89fdcdd34e0b8",
        "runtime_source": "ac79eee54505c5ad2214bb0eb4b66f5303b7c3b936b40a74a5e7a4d34ae8f380",
        "runtime_header": "75884963030018375fd604e9976096433ba857b3916a0d63636bda8940873533",
    }
    for key, digest in expected.items():
        if sha256(dependencies[key]) != digest:
            raise ValueError(f"Pinned {key} source hash changed")

    source_records = {
        name.replace("\\", "/"): digest
        for name, digest in asset_result.get("source_sha256", {}).items()
    }
    for suffix, key in (
        ("pointwise_tables_v1/oracle.c", "c_oracle"),
        ("tools/prepare_z100_pointwise_tables.py", "table_preparer"),
    ):
        expected_digest = next((digest for name, digest in source_records.items()
                                if name.endswith(suffix)), None)
        if expected_digest != sha256(dependencies[key]):
            raise ValueError(f"Pinned C-verified evidence does not bind {key}")
    if sha256(ASSET_MANIFEST) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("Pinned pointwise-table manifest SHA-256 mismatch")
    return dependencies


def prepare_silu_assets(build: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Path]]:
    payloads = {item["file"]: item for item in manifest["payloads"]}
    tables = sorted(
        (item for item in manifest["tables"] if item.get("table_kind") == "packaged_silu_lut"),
        key=lambda item: item["asset_file"],
    )
    if len(tables) != EXPECTED_TABLES or manifest.get("counts", {}).get("silu_tables") != EXPECTED_TABLES:
        raise ValueError(f"Expected exactly {EXPECTED_TABLES} packaged SiLU maps")

    combined = bytearray()
    table_records: list[dict[str, Any]] = []
    payload_paths: dict[str, Path] = {}
    for table_number, table in enumerate(tables):
        filename = table["asset_file"]
        payload = payloads.get(filename)
        source = ASSET_BUILD / filename
        if payload is None or not source.is_file():
            raise FileNotFoundError(f"Missing manifest or binary record for {filename}")
        binary = source.read_bytes()
        expected_hash = table["sha256"]
        if (table.get("operator") != "silu" or table.get("input_indexing") != "signed_int8 + 128" or
                table.get("byte_length") != 256 or len(binary) != 256 or
                payload.get("bytes") != 256 or payload.get("sha256") != expected_hash or
                sha256(source) != expected_hash):
            raise ValueError(f"SiLU table identity/shape/indexing mismatch: {filename}")
        combined.extend(binary)
        payload_paths[filename] = source
        table_records.append({
            "table_number": table_number,
            "asset_file": filename,
            "sha256": expected_hash,
            "byte_length": len(binary),
            "node_id": int(table["node_id"]),
            "source_node_id": int(table["source_node_id"]),
            "input_index": int(table["input_index"]),
            "operator": table["operator"],
            "input_indexing": table["input_indexing"],
            "input_shape_nchw": table["input_shape_nchw"],
            "output_shape_nchw": table["output_shape_nchw"],
        })
    if len(combined) != EXPECTED_SILU_BYTES:
        raise ValueError(f"Unexpected packaged SiLU payload total: {len(combined)}")

    (build / "unary32_tables.hex").write_text(
        "".join(f"{value:02x}\n" for value in combined), encoding="ascii"
    )
    (build / "unary32_tables.json").write_text(
        json.dumps({
            "manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "table_count": len(table_records),
            "byte_count": len(combined),
            "payload_order": "ascending asset_file; bytes in ascending transformed signed-int8 index",
            "tables": table_records,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "table_count": len(table_records),
        "bytes": len(combined),
        "tables": table_records,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "indexing": "input_address = raw_signed_int8_byte XOR 0x80; table payload is ascending index 0..255",
        "test_vector": "for table t, beat b, lane l: index=(b+7*l+13*t) mod 256; raw byte=index XOR 0x80",
    }, payload_paths


def tcl_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if "}" in value:
        raise ValueError(f"Tcl brace in path is unsupported: {value}")
    return "{" + value + "}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vivado", type=Path, default=VIVADO)
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/unary32_v1" / run_id
    build = ROOT / "deployment/build/z100_unary32_v1" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    snapshot = evidence / "source_snapshot"
    snapshot.mkdir()

    source_paths = {"rtl": RTL, "testbench": TB, "validator": SCRIPT}
    before_source_hashes = {key: sha256(path) for key, path in source_paths.items()}
    result: dict[str, Any] = {
        "status": "RUNNING",
        "run_id": run_id,
        "objective": "private 32-lane exact unary SiLU stream; XSim then one OOC synthesis only",
        "part": PART,
        "source_sha256_before": before_source_hashes,
        "commands": [],
        "vendor_attempts": {"xsim_flows": 0, "ooc_synthesis_flows": 0, "retry_count": 0},
        "limits": {
            "lut_max": 3000,
            "ff_max": 1500,
            "bram_exact": 0,
            "dsp_exact": 0,
            "latch_exact": 0,
            "blackbox_exact": 0,
            "vivado_threads_max": 2,
            "numerical_threads": 1,
        },
        "board_access": False,
        "route_attempted": False,
        "bitstream_created": False,
        "production_integrated": False,
    }
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"

    dependencies: dict[str, Path] = {}
    payload_paths: dict[str, Path] = {}
    before_dependencies: dict[str, str] = {}
    stage = "preflight"

    def run(name: str, command: list[str], cwd: Path = build) -> str:
        completed = subprocess.run(
            command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        (evidence / f"{name}.log").write_text(completed.stdout, encoding="utf-8")
        result["commands"].append({
            "name": name,
            "args": list(map(str, command)),
            "cwd": str(cwd.resolve()),
            "return_code": completed.returncode,
        })
        if completed.returncode:
            raise RuntimeError(f"{name} returned {completed.returncode}")
        return completed.stdout

    try:
        for tool in ("xvlog.bat", "xelab.bat", "xsim.bat"):
            path = args.vivado.resolve().parent / tool
            if not path.is_file():
                raise FileNotFoundError(f"Required XSim 2026.1 tool unavailable: {path}")
        if not args.vivado.is_file():
            raise FileNotFoundError(f"Vivado launcher unavailable: {args.vivado}")
        if not ASSET_MANIFEST.is_file() or not ASSET_RESULT.is_file():
            raise FileNotFoundError("Pinned C-verified pointwise-table manifest/evidence unavailable")
        if sha256(ASSET_MANIFEST) != EXPECTED_MANIFEST_SHA256:
            raise ValueError("Pinned SiLU manifest hash mismatch")

        asset_result = json.loads(ASSET_RESULT.read_text(encoding="utf-8"))
        if asset_result.get("status") != EXPECTED_ASSET_STATUS:
            raise ValueError("Pinned pointwise-table C-oracle evidence is not passing")
        if asset_result.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256:
            raise ValueError("C-oracle evidence uses a different manifest")
        if (asset_result.get("unary_c_comparisons"), asset_result.get("add_c_comparisons")) != (
            EXPECTED_C_UNARY_VALUES, EXPECTED_C_ADD_PAIRS
        ):
            raise ValueError("Pinned independent C-oracle comparison counts changed")
        if asset_result.get("silu_exact_package_bytes_checked") != EXPECTED_SILU_BYTES:
            raise ValueError("Pinned C-oracle evidence did not check every packaged SiLU byte")

        manifest = json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))
        dependencies = source_dependencies(asset_result)
        table_inputs, payload_paths = prepare_silu_assets(build, manifest)
        input_paths = dict(dependencies)
        input_paths.update({f"silu_payload:{name}": path for name, path in payload_paths.items()})
        before_dependencies = {key: sha256(path) for key, path in input_paths.items()}

        snapshot_assets = snapshot / "table_payloads"
        snapshot_assets.mkdir()
        for role, path in source_paths.items():
            shutil.copy2(path, snapshot / path.name)
        for key, path in dependencies.items():
            shutil.copy2(path, snapshot / (key + path.suffix))
        for name, path in payload_paths.items():
            shutil.copy2(path, snapshot_assets / name)

        result["asset_dependency"] = {
            "manifest": str(ASSET_MANIFEST.relative_to(ROOT)),
            "manifest_sha256": sha256(ASSET_MANIFEST),
            "source_evidence": str(ASSET_RESULT.relative_to(ROOT)),
            "source_evidence_sha256": sha256(ASSET_RESULT),
            "source_evidence_status": asset_result["status"],
            "c_oracle_unary_comparisons": asset_result["unary_c_comparisons"],
            "c_oracle_add_comparisons": asset_result["add_c_comparisons"],
            "silu_exact_package_bytes_checked_by_c": asset_result["silu_exact_package_bytes_checked"],
            "table_count": table_inputs["table_count"],
            "table_bytes": table_inputs["bytes"],
            "table_sha256": {row["asset_file"]: row["sha256"] for row in table_inputs["tables"]},
            "source_sha256": before_dependencies,
        }
        result["table_inputs"] = table_inputs
        (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        bindir = args.vivado.resolve().parent
        stage = "xsim"
        result["vendor_attempts"]["xsim_flows"] = 1
        run("xvlog", [str(bindir / "xvlog.bat"), "-sv", str(RTL), str(TB)])
        run("xelab", [str(bindir / "xelab.bat"), "-mt", "2", "tb_z100_unary32", "-s", "unary32_sim"])
        simulation = run("xsim", [str(bindir / "xsim.bat"), "unary32_sim", "-runall"])
        if re.search(r"(?im)^\s*(?:FAIL:|FATAL:|ERROR:)", simulation):
            raise ValueError("XSim log contains a failure/error marker")
        summary = re.findall(
            r"UNARY32_PASS tables=(\d+) exhaustive_beats=(\d+) exhaustive_values=(\d+) "
            r"responses=(\d+) active_byte_comparisons=(\d+) max_ii1=(\d+) stalls=(\d+) "
            r"cfg_writes=(\d+) overlong=(\d+) refused=(\d+) errors=(\d+) "
            r"partial=1,15,16,17,31 reset=1 cancel=1 reload_busy=1 load_input_disabled=1", simulation
        )
        if len(summary) != 1:
            raise ValueError("XSim coverage summary missing or repeated")
        (tables, beats, values, responses, active_bytes, max_ii1, stalls,
         cfg_writes, overlong, refused, errors) = map(int, summary[0])
        simulation_counts = {
            "tables": tables,
            "exhaustive_beats": beats,
            "exhaustive_active_bytes": values,
            "responses": responses,
            "all_active_byte_comparisons": active_bytes,
            "max_consecutive_accepts_ii1": max_ii1,
            "output_stall_cycles": stalls,
            "accepted_cfg_writes": cfg_writes,
            "overlong_cfg_words_rejected": overlong,
            "invalid_requests_refused": refused,
            "error_events": errors,
            "all_32_lanes_saw_all_256_indices_per_table": True,
            "partial_lane_counts": [1, 15, 16, 17, 31],
            "metadata_stable_under_backpressure": True,
            "tail_lanes_zero": True,
            "reload_rejected_while_inflight": True,
            "input_disabled_while_loading": True,
            "reset_pending_recovery": True,
            "cancel_pending_recovery": True,
        }
        if (tables, beats, values) != (EXPECTED_TABLES, EXPECTED_TABLES*256, EXPECTED_TABLES*256*32):
            raise ValueError(f"Exhaustive table totals mismatch: {simulation_counts}")
        if (responses, active_bytes) != (14_600, 467_120):
            raise ValueError(f"Response/active-byte totals mismatch: {simulation_counts}")
        if max_ii1 < 256 or stalls < 10 or cfg_writes != 16_135 or \
                (overlong, refused, errors) != (1, 3, 6):
            raise ValueError(f"Fixed protocol/throughput coverage mismatch: {simulation_counts}")
        result["simulation"] = {"status": "PASS", **simulation_counts}

        synth_tcl = build / "synth.tcl"
        synth_tcl.write_text("\n".join((
            "set_param general.maxThreads 2",
            'if {![string match 2026.1* [version -short]]} {error "Requires Vivado 2026.1"}',
            f"read_verilog -sv {tcl_path(RTL)}",
            f"synth_design -top z100_unary32 -part {PART} -mode out_of_context -flatten_hierarchy none",
            "create_clock -name unary_clk -period 10.000 [get_ports clk]",
            f"report_utilization -file {tcl_path(evidence / 'utilization.rpt')}",
            f"report_utilization -hierarchical -file {tcl_path(evidence / 'utilization_hierarchical.rpt')}",
            f"report_timing_summary -delay_type min_max -report_unconstrained -file {tcl_path(evidence / 'timing_synth.rpt')}",
            f"write_checkpoint -force {tcl_path(build / 'post_synth.dcp')}",
            'set ff [llength [get_cells -hier -filter {REF_NAME =~ FD*}]]',
            'set ram36 [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}]]',
            'set ram18 [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}]]',
            'set dsp [llength [get_cells -hier -filter {REF_NAME =~ DSP*}]]',
            'set latch [llength [get_cells -hier -filter {REF_NAME =~ LD*}]]',
            'set blackbox [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]',
            'puts "UNARY32_SYNTH_CENSUS ff=$ff ram36=$ram36 ram18=$ram18 dsp=$dsp latch=$latch blackbox=$blackbox"',
            "exit",
            "",
        )), encoding="utf-8")

        stage = "ooc_synthesis"
        result["vendor_attempts"]["ooc_synthesis_flows"] = 1
        synthesis = run("vivado_ooc_synth", [
            str(args.vivado.resolve()), "-mode", "batch",
            "-log", str(evidence / "vivado.log"),
            "-journal", str(evidence / "vivado.jou"),
            "-source", str(synth_tcl),
        ])
        census = re.findall(
            r"UNARY32_SYNTH_CENSUS ff=(\d+) ram36=(\d+) ram18=(\d+) dsp=(\d+) latch=(\d+) blackbox=(\d+)",
            synthesis,
        )
        if len(census) != 1:
            raise ValueError("OOC synthesis cell census missing or repeated")
        utilization = (evidence / "utilization.rpt").read_text(encoding="utf-8", errors="replace")
        lut_rows = re.findall(r"(?im)^\|\s*Slice LUTs\*?\s*\|\s*(\d+)\s*\|", utilization)
        if len(lut_rows) != 1:
            raise ValueError("Cannot parse the exact Slice LUT count from OOC utilization report")
        lut = int(lut_rows[0])
        ff, ram36, ram18, dsp, latch, blackbox = map(int, census[0])
        bram36_eq = ram36 + ram18 / 2
        synthesis_result = {
            "status": "PASS_SCREEN" if lut <= 3000 and ff <= 1500 and bram36_eq == 0 and
                      dsp == 0 and latch == 0 and blackbox == 0 else "FAIL_SCREEN",
            "vivado_version": "2026.1",
            "part": PART,
            "lut_slice_count_including_distributed_memory": lut,
            "ff": ff,
            "ram36": ram36,
            "ram18": ram18,
            "bram36_equivalent": bram36_eq,
            "dsp": dsp,
            "latch": latch,
            "blackbox": blackbox,
        }
        result["synthesis"] = synthesis_result
        if lut > 3000 or ff > 1500 or bram36_eq != 0 or dsp or latch or blackbox:
            raise ValueError(f"Actual OOC resource census failed the fixed screen: {synthesis_result}")

        after_source_hashes = {key: sha256(path) for key, path in source_paths.items()}
        after_dependencies = {key: sha256(path) for key, path in input_paths.items()}
        if after_source_hashes != before_source_hashes or after_dependencies != before_dependencies:
            raise ValueError("Bound source or verified SiLU payload changed during the run")
        result["source_sha256_after"] = after_source_hashes
        result["dependency_sha256_after"] = after_dependencies
        result["status"] = "PASS_PRIVATE_UNARY32_XSIM_OOC_SYNTH_ONLY"
        stage = "complete"
    except Exception as exc:  # retain exact attempt evidence, never retry in this validator
        result["status"] = "FAILED_CLOSED"
        result["failure_stage"] = stage
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["source_sha256_after"] = {
            key: sha256(path) for key, path in source_paths.items() if path.is_file()
        }
        if dependencies:
            result["dependency_sha256_after"] = {
                key: sha256(path) for key, path in dependencies.items() if path.is_file()
            }
        for name, path in payload_paths.items():
            if path.is_file():
                result.setdefault("dependency_sha256_after", {})[f"silu_payload:{name}"] = sha256(path)

    result["artifact_sha256"] = {
        str(path.relative_to(ROOT)): sha256(path)
        for folder in (build, evidence)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "result.json"
    }
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "report": str((evidence / "result.json").relative_to(ROOT)),
        "failure_stage": result.get("failure_stage"),
        "error": result.get("error"),
        "simulation": result.get("simulation"),
        "synthesis": result.get("synthesis"),
    }), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
