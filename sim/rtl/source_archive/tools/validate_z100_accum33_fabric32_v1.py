"""Source-bound, serialized component miter; preparation never starts vendor tools."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import re
import shutil
import sys

import check_z100_accum33_fabric32_v1 as offline
import run_z100_registered_response_bank_v2 as vendor

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "deployment/hardware/z100_2026/accum33_fabric32_v1"
BIN = Path("C:/appload/2026.1/Vivado/bin")
GLBL = BIN.parent / "data/verilog/src/glbl.v"
TOP = "tb_z100_accum33_fabric32_miter"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resources_ready(resources):
    return resources["available_ram_gib"] >= 8 and resources["c_free_gib"] >= 20


def verify_bindings(bindings):
    for name, digest in bindings.items():
        require(sha(vendor.resolve_binding(name)) == digest, "Source drift: " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"))
    args = parser.parse_args()
    require(re.fullmatch(r"[A-Za-z0-9_.-]{8,80}", args.run_id), "Invalid run ID")
    out = ROOT / "validation/board_z100/accum33_fabric32_v1" / args.run_id
    build = ROOT / "build/accum33_fabric32_v1" / args.run_id
    require(not out.exists() and not build.exists(), "Run already exists")
    out.mkdir(parents=True)
    build.mkdir(parents=True)
    result_path = out / "validation_result.json"
    report = {"status": "PREPARING", "commands": [], "board_access": False,
              "mapping_timing_or_fps_accepted": False, "prepare_only": args.prepare_only,
              "runner_sha256": sha(Path(__file__)), "source_bindings": {},
              "staged_bindings": {}, "artifacts": {}}

    def save():
        vendor.atomic_json(result_path, report)

    try:
        offline.read_all()
        report["integer_model"] = offline.run_integer_vectors()
        sources = [offline.ORIGINAL_ACCUM, PKG / "z100_accum33_fabric32_v1.sv",
                   PKG / "tb_z100_accum33_fabric32_miter.sv", GLBL]
        tools = [BIN / (name + ".bat") for name in ("xvlog", "xelab", "xsim")]
        for path in sources + tools + [PKG / "manifest.json", Path(offline.__file__), Path(vendor.__file__)]:
            require(path.is_file(), "Missing input: " + str(path))
            report["source_bindings"][vendor.rel(path)] = sha(path)
        staged = []
        for source in sources:
            target = build / source.name
            shutil.copyfile(source, target)
            require(sha(target) == sha(source), "Copy mismatch")
            report["staged_bindings"][vendor.rel(target)] = sha(target)
            staged.append(target)
        argv = [[str(tools[0]), "-sv", *map(str, staged)],
                [str(tools[1]), "-mt", "2", "-L", "unisims_ver", "glbl", TOP, "-s", "fabric33_miter"],
                [str(tools[2]), "fabric33_miter", "-runall"]]
        report["planned_commands"] = argv
        report["resources_observed"] = vendor.system_resources()
        report["vendor_inventory_observed"] = vendor.vendor_inventory()
        report["runtime_admissible_now"] = (resources_ready(report["resources_observed"]) and
                                             not report["vendor_inventory_observed"])
        if args.prepare_only:
            report["status"] = "PREPARED_ONLY_VENDOR_NOT_EXECUTED"
            save()
            print(json.dumps({"report": vendor.rel(result_path), "status": report["status"]}))
            return 0
        require(report["runtime_admissible_now"], "Vendor busy or insufficient runtime resources")
        with vendor.NamedMutex(timeout_ms=0):
            require(not vendor.vendor_inventory(), "Vendor became active after lock")
            require(resources_ready(vendor.system_resources()), "Runtime resources changed")
            verify_bindings(report["source_bindings"])
            verify_bindings(report["staged_bindings"])
            logs = []
            for label, command in zip(("xvlog", "xelab", "xsim"), argv):
                logs.append(vendor.run_tool(label, command, build, out / (label + ".log"), result_path, report))
            rows = re.findall(r"(?m)^ACCUM33_FABRIC32_MITER_PASS (.+)$", logs[-1])
            require(len(rows) == 1, "Missing or repeated miter marker")
            counts = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", rows[0])}
            minima = {"checks": 17000, "loads": 64, "updates": 17000,
                      "holds": 1024, "flushes": 10, "max_streak": 8192}
            require(all(counts.get(k, -1) >= v for k, v in minima.items()), "Miter coverage incomplete")
            verify_bindings(report["source_bindings"])
            verify_bindings(report["staged_bindings"])
            report["measured_counts"] = counts
            report["artifacts"] = {vendor.rel(out / (name + ".log")): sha(out / (name + ".log"))
                                   for name in ("xvlog", "xelab", "xsim")}
            report["status"] = "PASS_COMPONENT_DSP_FABRIC_MITER_NOT_CORE_MAPPING_OR_TIMING"
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
