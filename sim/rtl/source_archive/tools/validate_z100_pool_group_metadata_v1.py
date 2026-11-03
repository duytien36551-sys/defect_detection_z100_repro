"""Prepare or serially run the real old/new Pool metadata component miter."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import re
import shutil
import sys

import prepare_z100_pool_group_metadata_v1 as candidate
import run_z100_registered_response_bank_v2 as vendor

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "deployment/hardware/z100_2026/pool_group_metadata_v1"
CANDIDATE_DIR = PACKAGE / "20261028T001823.171645Z"
TB = PACKAGE / "tb_pool_group_metadata_miter_v1.sv"
AUTHORING = ROOT / "validation/board_z100/pool_group_metadata_authoring_review/20261028T002123.037380Z/result.json"
BASE = ROOT / "build/v12p_d46da432/rtl"
BIN = Path("C:/appload/2026.1/Vivado/bin")
TOP = "tb_pool_group_metadata_miter_v1"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ready():
    resources = vendor.system_resources()
    require(resources["available_ram_gib"] >= 8 and resources["c_free_gib"] >= 20,
            "Insufficient memory/disk for validation")
    require(not vendor.vendor_inventory(), "Another vendor task is active")
    return resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"))
    args = parser.parse_args()
    require(re.fullmatch(r"[A-Za-z0-9_.-]{8,80}", args.run_id), "Invalid run id")
    run = ROOT / "validation/board_z100/pool_group_metadata_miter_v1" / args.run_id
    build = ROOT / "build/pool_meta_miter" / args.run_id
    require(not run.exists() and not build.exists(), "Run already exists")
    run.mkdir(parents=True)
    build.mkdir(parents=True)
    report_path = run / "result.json"
    report = {"status": "PREPARING", "commands": [], "source_before": {}, "staged": {},
              "runner_sha256": sha(Path(__file__)), "prepare_only": args.prepare_only,
              "full_core_mapping_timing_platform_or_fps_accepted": False}

    def save():
        vendor.atomic_json(report_path, report)

    try:
        audit = json.loads(AUTHORING.read_text())
        new = CANDIDATE_DIR / candidate.BASE.name
        require(audit["status"] == "PASS_OFFLINE_SOURCE_TRANSFORM_PORT_MAP_AND_INTEGER_MODEL_MITER_AUTHORED_NOT_RUN",
                "Authoring evidence changed")
        require(sha(TB) == audit["testbench_sha256"] and sha(new) == audit["candidate_sha256"] and
                sha(candidate.BASE) == candidate.BASE_SHA == audit["source_sha256"], "Bound candidate/source drift")
        require(new.read_text() == candidate.transform(candidate.BASE.read_text()), "Unexpected RTL transformation")
        sources = [candidate.BASE, new, BASE / "z100_maxpool_vector.sv", BASE / "z100_maxpool_collect32.sv",
                   BASE / "z100_native_output_packer.sv", TB, BIN.parent / "data/verilog/src/glbl.v"]
        tools = [BIN / (name + ".bat") for name in ("xvlog", "xelab", "xsim")]
        bindings = report["source_before"]
        for path in sources + tools + [AUTHORING, Path(candidate.__file__), Path(vendor.__file__)]:
            require(path.is_file(), "Missing source/tool: " + str(path))
            bindings[vendor.rel(path)] = sha(path)
        staged = []
        for index, source in enumerate(sources):
            target = build / ("baseline_pool.sv" if index == 0 else source.name)
            if index == 0:
                original = source.read_text()
                before = "module z100_maxpool_window20_tapxy_v3 ("
                require(original.count(before) == 1, "Baseline rename anchor changed")
                target.write_text(original.replace(before, "module z100_maxpool_window20_tapxy_v3_baseline (", 1),
                                  encoding="utf-8", newline="\n")
            else:
                shutil.copyfile(source, target)
                require(sha(target) == sha(source), "Source copy changed")
            report["staged"][vendor.rel(target)] = sha(target)
            staged.append(target)
        argv = [[str(tools[0]), "-sv", *map(str, staged)],
                [str(tools[1]), "-mt", "2", "-L", "unisims_ver", "glbl", TOP, "-s", "pool_metadata_miter"],
                [str(tools[2]), "pool_metadata_miter", "-runall"]]
        report["planned_commands"] = argv
        report["host_model"] = candidate.arithmetic_model()
        report["resource_snapshot"] = vendor.system_resources()
        report["vendor_snapshot"] = vendor.vendor_inventory()
        if args.prepare_only:
            report["status"] = "PREPARED_ONLY_VENDOR_NOT_EXECUTED"
            save()
            print(json.dumps({"report": vendor.rel(report_path), "status": report["status"]}))
            return 0
        ready()
        with vendor.NamedMutex(timeout_ms=0):
            report["locked_admission"] = ready()
            for bindings_to_check in (bindings, report["staged"]):
                for name, digest in bindings_to_check.items():
                    require(sha(vendor.resolve_binding(name)) == digest, "Source drift: " + name)
            logs = []
            for label, command in zip(("xvlog", "xelab", "xsim"), argv):
                logs.append(vendor.run_tool(label, command, build, run / (label + ".log"), report_path, report))
            rows = re.findall(r"(?m)^POOL_GROUP_METADATA_MITER_PASS (.+)$", logs[-1])
            require(len(rows) == 1, "Miter did not complete once")
            counts = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", rows[0])}
            expected = {"jobs": 133, "tail_masks": 15, "cancel_cases": 1, "fault_cases": 1, "reset_cases": 1}
            require(all(counts.get(key) == value for key, value in expected.items()), "Directed coverage incomplete")
            require(all(counts.get(key, 0) > 0 for key in ("requests", "responses", "packed_words", "stalled_outputs")),
                    "Missing real data/backpressure exercise")
            report["source_after"] = {name: sha(vendor.resolve_binding(name)) for name in bindings}
            require(report["source_after"] == bindings, "Input changed during validation")
            for name, digest in report["staged"].items():
                require(sha(vendor.resolve_binding(name)) == digest, "Staged source changed")
            report["measured_counts"] = counts
            report["log_sha256"] = {label: sha(run / (label + ".log")) for label in ("xvlog", "xelab", "xsim")}
            report["status"] = "PASS_POOL_COMPONENT_MITER_ONLY_SHARED_CORE_GOLDEN_AND_TIMING_PENDING"
            save()
        return 0
    except Exception as exc:
        report["status"] = "FAILED_CLOSED"
        report["error"] = str(exc)
        save()
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
