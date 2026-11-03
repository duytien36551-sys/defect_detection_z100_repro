"""Validate private 16-lane pointwise table lookup RTL in XSim and OOC synth."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "deployment/hardware/z100_2026/pointwise_lookup_v1"
RTL = FIXTURE / "z100_pointwise_lookup.sv"
TB = FIXTURE / "tb_z100_pointwise_lookup.sv"
SCRIPT = Path(__file__).resolve()
ASSET_BUILD = ROOT / "deployment/build/z100_pointwise_tables_v1/20261023T165100.884151Z_5e3e437d"
ASSET_MANIFEST = ASSET_BUILD / "tables_manifest.json"
ASSET_RESULT = ROOT / "validation/board_z100/pointwise_tables_v1/20261023T165100.884151Z_5e3e437d/result.json"
VIVADO = Path(r"C:\appload\2026.1\Vivado\bin\vivado.bat")
EXPECTED_MANIFEST_SHA256 = "69470ca5d7eb8a19a8f48d9002b6d63cddc5787e57e0a09b44a724711307e2fc"
EXPECTED_ASSET_STATUS = "PASS_PIN640_POINTWISE_TABLES_HOST_ONLY"
EXPECTED_UNARY_VALUES = 31_232
EXPECTED_ADD_PAIRS = 393_216
EXPECTED_ASSET_COUNTS = (128, 122, 6)
PART = "xc7z100ffg900-2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_dependencies(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, str]]:
    result = json.loads(ASSET_RESULT.read_text(encoding="utf-8"))
    if result.get("status") != EXPECTED_ASSET_STATUS:
        raise ValueError("Pinned pointwise-table evidence is not a passing C-oracle run")
    if result.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256:
        raise ValueError("Pinned pointwise-table evidence has a different manifest hash")
    if (result.get("unary_c_comparisons"), result.get("add_c_comparisons")) != (
        EXPECTED_UNARY_VALUES, EXPECTED_ADD_PAIRS
    ):
        raise ValueError("Pinned C-oracle evidence has unexpected exhaustive counts")
    if result.get("silu_exact_package_bytes_checked") != 14_592:
        raise ValueError("Pinned C-oracle evidence did not check all SiLU bytes")

    dependency_paths: dict[str, Path] = {
        "pointwise_tables_manifest": ASSET_MANIFEST,
        "pointwise_tables_evidence": ASSET_RESULT,
    }
    for key, relative in (
        ("model_package", "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/package/MODEL.V8P"),
        ("generated_model_header", "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/package/v8_generated_model.h"),
        ("model_graph", "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline/model/graph.json"),
        ("runtime_source", "deployment/candidates/pin640/firmware/v8_runtime.c"),
        ("runtime_header", "deployment/candidates/pin640/firmware/v8_runtime.h"),
        ("c_oracle", "deployment/hardware/z100_2026/pointwise_tables_v1/oracle.c"),
        ("table_preparer", "tools/prepare_z100_pointwise_tables.py"),
    ):
        dependency_paths[key] = ROOT / relative
    for path in dependency_paths.values():
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
        if sha256(dependency_paths[key]) != digest:
            raise ValueError(f"Pinned {key} source hash changed")
    for result_suffix, dep_key in (
        ("pointwise_tables_v1/oracle.c", "c_oracle"),
        ("tools/prepare_z100_pointwise_tables.py", "table_preparer"),
    ):
        source_records = {
            name.replace("\\", "/"): digest
            for name, digest in result.get("source_sha256", {}).items()
        }
        expected_hash = next((digest for name, digest in source_records.items()
                              if name.endswith(result_suffix)), None)
        if expected_hash != sha256(dependency_paths[dep_key]):
            raise ValueError(f"Pinned source does not match passing evidence: {dep_key}")
    if sha256(ASSET_MANIFEST) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("Pinned pointwise-table manifest SHA-256 mismatch")
    return dependency_paths, result


def prepare_assets(build: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    payloads = {item["file"]: item for item in manifest["payloads"]}
    tables = sorted(manifest["tables"], key=lambda item: item["asset_file"])
    table_counts = {
        "total": len(tables),
        "unary": sum(table["table_kind"] != "runtime_add" and "add" not in table["table_kind"] for table in tables),
        "add": sum(table["table_kind"] == "runtime_add" or "add" in table["table_kind"] for table in tables),
    }
    # The current manifest names ADD explicitly as runtime_add_pairwise_i8x2.
    table_counts["unary"] = sum("add" not in table["table_kind"] for table in tables)
    table_counts["add"] = len(tables) - table_counts["unary"]
    if (table_counts["total"], table_counts["unary"], table_counts["add"]) != EXPECTED_ASSET_COUNTS:
        raise ValueError(f"Unexpected table inventory: {table_counts}")
    if manifest.get("counts", {}).get("unary_tables") != EXPECTED_ASSET_COUNTS[1] or \
       manifest.get("counts", {}).get("add_tables") != EXPECTED_ASSET_COUNTS[2]:
        raise ValueError("Manifest table count summary mismatch")

    index_rows: list[str] = []
    assets: list[dict[str, Any]] = []
    total_unary = 0
    total_add = 0
    for table_number, table in enumerate(tables):
        filename = table["asset_file"]
        payload = payloads.get(filename)
        if payload is None:
            raise ValueError(f"Missing manifest payload record for {filename}")
        source = ASSET_BUILD / filename
        if not source.is_file():
            raise FileNotFoundError(source)
        binary = source.read_bytes()
        expected_size = int(table["byte_length"])
        expected_hash = table["sha256"]
        if (len(binary) != expected_size or payload.get("bytes") != expected_size or
                payload.get("sha256") != expected_hash or sha256(source) != expected_hash):
            raise ValueError(f"Table payload identity mismatch: {filename}")
        is_add = "add" in table["table_kind"]
        expected_bytes = 65_536 if is_add else 256
        if len(binary) != expected_bytes:
            raise ValueError(f"Unexpected byte length for {filename}: {len(binary)}")
        mode = 1 if is_add else 0
        if is_add:
            total_add += len(binary)
        else:
            total_unary += len(binary)
        hex_name = filename + ".hex"
        (build / hex_name).write_text("".join(f"{value:02x}\n" for value in binary), encoding="ascii")
        index_rows.append(
            f"{table_number} {mode} {len(binary)} {int(table['node_id'])} "
            f"{int(table.get('input_index', 0))} {hex_name}\n"
        )
        assets.append({
            "table_number": table_number,
            "file": filename,
            "hex_file": hex_name,
            "kind": table["table_kind"],
            "mode": "add" if is_add else "unary",
            "node_id": int(table["node_id"]),
            "input_index": int(table.get("input_index", 0)),
            "source_node_id": table.get("source_node_id"),
            "byte_length": len(binary),
            "sha256": expected_hash,
            "input_indexing": table.get("input_indexing", "signed_int8 + 128"),
        })
    if total_unary != EXPECTED_UNARY_VALUES or total_add != EXPECTED_ADD_PAIRS:
        raise ValueError(f"Unexpected table byte totals unary={total_unary} add={total_add}")
    if total_unary != EXPECTED_UNARY_VALUES:
        raise ValueError("Unary table total differs from the C-verified package")
    (build / "pointwise_tables.index").write_text("".join(index_rows), encoding="ascii")
    return {
        "tables": assets,
        "table_count": len(assets),
        "unary_tables": table_counts["unary"],
        "add_tables": table_counts["add"],
        "unary_bytes": total_unary,
        "add_bytes": total_add,
        "bytes_loaded_per_complete_epoch": total_unary + total_add,
        "index_contract": {
            "unary": "{8'd0,(input_byte ^ 8'h80)}",
            "add": "{(a ^ 8'h80),(b ^ 8'h80)}",
            "payload_index_order": "ascending transformed unsigned index; output byte is two's-complement int8",
            "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        },
    }


def tcl_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if "}" in value:
        raise ValueError(f"Tcl brace in path is unsupported: {value}")
    return "{" + value + "}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vivado", type=Path, default=VIVADO)
    parser.add_argument("--max-vivado-processes", type=int, default=2)
    args = parser.parse_args()
    if args.max_vivado_processes != 2:
        parser.error("This packet is pinned to at most two Vivado processes")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/pointwise_lookup_v1" / run_id
    build = ROOT / "deployment/build/z100_pointwise_lookup_v1" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    snapshot = evidence / "source_snapshot"
    snapshot.mkdir()

    source_paths = {"rtl": RTL, "testbench": TB, "validator": SCRIPT}
    pre_hashes = {key: sha256(path) for key, path in source_paths.items()}
    before_dependencies: dict[str, str] = {}
    result: dict[str, Any] = {
        "status": "RUNNING",
        "run_id": run_id,
        "objective": "private16-lane epoch-tagged unary/ADD lookup; XSim then one OOC synth only",
        "part": PART,
        "source_sha256_before": pre_hashes,
        "commands": [],
        "board_access": False,
        "route_attempted": False,
        "bitstream_created": False,
        "production_integrated": False,
        "synthesis_screen": {
            "ram36_equivalent_exact": 128,
            "ram36_equivalent_max": 128,
            "lut_max": 12000,
            "ff_max": 6000,
            "dsp_exact": 0,
            "latch_exact": 0,
            "blackbox_exact": 0,
        },
    }

    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"

    def run(name: str, command: list[str], cwd: Path = build) -> str:
        completed = subprocess.run(command, cwd=cwd, env=env, text=True,
                                   encoding="utf-8", errors="replace",
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
        manifest_sha = sha256(ASSET_MANIFEST)
        if manifest_sha != EXPECTED_MANIFEST_SHA256:
            raise ValueError(f"Asset manifest hash mismatch: {manifest_sha}")
        manifest = json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))
        dependency_paths, asset_result = source_dependencies(manifest)
        payload_paths = {item["file"]: ASSET_BUILD / item["file"] for item in manifest["payloads"]}
        if len(payload_paths) != 128:
            raise ValueError("Manifest payload inventory does not contain exactly128 assets")
        if any(not path.is_file() for path in payload_paths.values()):
            raise FileNotFoundError("At least one C-verified table payload is missing")
        input_paths = dict(dependency_paths)
        input_paths.update({f"payload:{name}": path for name, path in payload_paths.items()})
        before_dependencies = {key: sha256(path) for key, path in input_paths.items()}
        for role, path in source_paths.items():
            shutil.copy2(path, snapshot / path.name)
        for key, path in dependency_paths.items():
            shutil.copy2(path, snapshot / (key + path.suffix))

        table_inputs = prepare_assets(build, manifest)
        result["asset_dependency"] = {
            "source_manifest": str(ASSET_MANIFEST.relative_to(ROOT)),
            "manifest_sha256": manifest_sha,
            "source_evidence": str(ASSET_RESULT.relative_to(ROOT)),
            "source_evidence_sha256": sha256(ASSET_RESULT),
            "source_evidence_status": asset_result["status"],
            "c_oracle_unary_comparisons": asset_result["unary_c_comparisons"],
            "c_oracle_add_comparisons": asset_result["add_c_comparisons"],
            "exact_silu_bytes_from_package": asset_result["silu_exact_package_bytes_checked"],
            "payload_count": len(payload_paths),
            "payload_sha256": {name: digest for name, digest in sorted(
                (name, before_dependencies[f"payload:{name}"]) for name in payload_paths
            )},
            "source_sha256": {key: digest for key, digest in before_dependencies.items()
                              if not key.startswith("payload:")},
        }
        result["table_inputs"] = table_inputs
        (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        bindir = args.vivado.resolve().parent
        run("xvlog", [str(bindir / "xvlog.bat"), "-sv", str(RTL), str(TB)])
        run("xelab", [str(bindir / "xelab.bat"), "-mt", "2",
                      "tb_z100_pointwise_lookup", "-s", "pointwise_lookup_sim"])
        simulation = run("xsim", [str(bindir / "xsim.bat"), "pointwise_lookup_sim", "-runall"])
        if re.search(r"(?im)^\s*(?:FAIL:|FATAL:|ERROR:)", simulation):
            raise ValueError("XSim log contains a failure/error marker")
        matches = re.findall(
            r"POINTWISE_LOOKUP_PASS tables=(\d+) unary_tables=(\d+) add_tables=(\d+) "
            r"exhaustive_beats=(\d+) exhaustive_values=(\d+) responses=(\d+) "
            r"comparisons=(\d+) max_ii1=(\d+) stalls=(\d+) cfg_writes=(\d+) "
            r"overlong=(\d+) refused=(\d+) errors=(\d+) reset=1 cancel=1", simulation)
        if len(matches) != 1:
            raise ValueError("XSim coverage summary missing or repeated")
        (tables, unary, adds, beats, values, responses, comparisons, max_ii1,
         stalls, cfg_writes, overlong, refused, errors) = map(int, matches[0])
        actual = {
            "tables": tables, "unary_tables": unary, "add_tables": adds,
            "exhaustive_beats": beats, "exhaustive_values": values,
            "responses": responses, "lookup_comparisons": comparisons,
            "max_consecutive_accepts_ii1": max_ii1, "output_stall_cycles": stalls,
            "actual_bram_write_cycles": cfg_writes,
            "overlong_word_attempts_rejected": overlong,
            "invalid_requests_refused": refused, "error_events": errors,
            "metadata_stable_under_backpressure": True,
            "tail_lanes_zero": True,
            "reload_rejected_while_inflight": True,
            "input_disabled_while_loading": True,
            "reset_pending_recovery": True,
            "cancel_pending_recovery": True,
        }
        if (tables, unary, adds, beats, values) != (128, 122, 6, 26528, 424448):
            raise ValueError(f"XSim exhaustive table totals mismatch: {actual}")
        if comparisons < 424448 or max_ii1 < 4096 or stalls < 5 or \
           (cfg_writes, overlong, refused, errors) != (425223, 1, 4, 8):
            raise ValueError(f"XSim fixed behavior coverage mismatch: {actual}")
        result["simulation"] = {"status": "PASS", **actual}

        tcl = build / "synth.tcl"
        tcl.write_text("\n".join((
            "set_param general.maxThreads 2",
            'if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}',
            f"read_verilog -sv {tcl_path(RTL)}",
            f"synth_design -top z100_pointwise_lookup -part {PART} -mode out_of_context -flatten_hierarchy none",
            "create_clock -name lookup_clk -period 10.000 [get_ports clk]",
            f"report_utilization -file {tcl_path(evidence / 'utilization.rpt')}",
            f"report_utilization -hierarchical -file {tcl_path(evidence / 'utilization_hierarchical.rpt')}",
            f"report_timing_summary -delay_type min_max -report_unconstrained -file {tcl_path(evidence / 'timing_synth.rpt')}",
            f"write_checkpoint -force {tcl_path(build / 'post_synth.dcp')}",
            'set lut [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]',
            'set ff [llength [get_cells -hier -filter {REF_NAME =~ FD*}]]',
            'set ram36 [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}]]',
            'set ram18 [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}]]',
            'set dsp [llength [get_cells -hier -filter {REF_NAME =~ DSP*}]]',
            'set latch [llength [get_cells -hier -filter {REF_NAME =~ LD*}]]',
            'set blackbox [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]',
            'puts "POINTWISE_LOOKUP_SYNTH lut=$lut ff=$ff ram36=$ram36 ram18=$ram18 dsp=$dsp latch=$latch blackbox=$blackbox"',
            "exit",
            "",
        )), encoding="utf-8")

        # The owner reserved one vendor slot. Stay within two Vivado processes.
        while True:
            process_count = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "@(Get-Process vivado -ErrorAction SilentlyContinue).Count"], text=True)
            if int(process_count.strip()) < args.max_vivado_processes:
                break
            time.sleep(30)
        synthesis = run("vivado_ooc_synth", [str(args.vivado.resolve()), "-mode", "batch",
                                               "-log", str(evidence / "vivado.log"),
                                               "-journal", str(evidence / "vivado.jou"),
                                               "-source", str(tcl)])
        synth_rows = re.findall(
            r"POINTWISE_LOOKUP_SYNTH lut=(\d+) ff=(\d+) ram36=(\d+) ram18=(\d+) "
            r"dsp=(\d+) latch=(\d+) blackbox=(\d+)", synthesis)
        if len(synth_rows) != 1:
            raise ValueError("OOC synthesis resource census missing or repeated")
        lut, ff, ram36, ram18, dsp, latch, blackbox = map(int, synth_rows[0])
        bram36_eq = ram36 + ram18 / 2
        result["synthesis"] = {
            "status": "PASS_SCREEN" if (lut <= 12000 and ff <= 6000 and bram36_eq == 128 and
                                          dsp == 0 and latch == 0 and blackbox == 0) else "FAIL_SCREEN",
            "vivado_version": "2026.1",
            "part": PART,
            "lut": lut,
            "ff": ff,
            "ram36": ram36,
            "ram18": ram18,
            "bram36_equivalent": bram36_eq,
            "dsp": dsp,
            "latch": latch,
            "blackbox": blackbox,
        }
        if lut > 12000 or ff > 6000 or bram36_eq != 128 or dsp or latch or blackbox:
            raise ValueError("Actual OOC resource census failed the fixed screen")

        after_source_hashes = {key: sha256(path) for key, path in source_paths.items()}
        after_dependency_hashes = {key: sha256(path) for key, path in input_paths.items()}
        if after_source_hashes != pre_hashes or after_dependency_hashes != before_dependencies:
            raise ValueError("Bound source or verified table asset changed during the run")
        result["status"] = "PASS_PRIVATE_POINTWISE_LOOKUP_XSIM_OOC_SYNTH_ONLY"
    except Exception as exc:  # retain the first immutable evidence package on failure
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"

    result["source_sha256_after"] = {key: sha256(path) for key, path in source_paths.items()}
    if before_dependencies:
        result["dependency_sha256_after"] = {
            key: sha256(path) for key, path in input_paths.items()
        }
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
        "error": result.get("error"),
        "simulation": result.get("simulation"),
        "synthesis": result.get("synthesis"),
    }), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
