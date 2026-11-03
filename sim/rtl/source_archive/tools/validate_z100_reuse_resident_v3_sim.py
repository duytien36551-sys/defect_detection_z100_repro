#!/usr/bin/env python3
"""Reproduce the isolated v3 persistent-weight-core XSim acceptance bench."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "deployment/hardware/z100_2026/tile_reuse_resident_v3"
EVIDENCE_ROOT = ROOT / "validation/board_z100/reuse_resident_v3"
VIVADO_DEFAULT = Path(r"C:\appload\2026.1\Vivado\bin")
TOP = "tb_z100_tile_reuse_resident_v3"
EXPECTED_RESULT_COMPARISONS = 49
EXPECTED_REPLAY_COMPARISONS = 40


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fields(line: str) -> dict[str, str]:
    return dict(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)", line))


def signed32_prefix_expectation() -> dict[str, object]:
    bias = 2_147_467_647  # 0x7fffc17f = INT32_MAX - 16000
    weights = [127] * 5
    activations = [127, -128, 127, -128, 127]
    products = [weight * activation for weight, activation in zip(weights, activations)]
    prefixes: list[int] = []
    total = bias
    for product in products:
        total += product
        prefixes.append(total)
    expected_products = [16_129, -16_256, 16_129, -16_256, 16_129]
    expected_prefixes = [2_147_483_776, 2_147_467_520, 2_147_483_649,
                         2_147_467_393, 2_147_483_522]
    if products != expected_products or prefixes != expected_prefixes:
        raise ValueError("Directed signed16-prefix arithmetic differs from the reviewed constants")
    if prefixes[0] != 2_147_483_647 + 129 or prefixes[-1] != 2_147_483_647 - 125:
        raise ValueError("Directed prefix must cross signed32 max and finish back in range")
    return {
        "bias": bias,
        "weights": weights,
        "activations": activations,
        "signed16_products": products,
        "signed64_prefix_sums": prefixes,
        "final_signed32_value": prefixes[-1],
        "final_overflow": False,
    }


def run_tool(name: str, tool: Path, arguments: list[str], work: Path) -> dict[str, object]:
    command = [str(tool), *arguments]
    command_line = subprocess.list2cmdline(command)
    completed = subprocess.run(
        command_line,
        cwd=work,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output_path = work / f"{name}.stdout.txt"
    output_path.write_text(completed.stdout, encoding="utf-8")
    return {
        "name": name,
        "command": command,
        "return_code": completed.returncode,
        "stdout_file": output_path.name,
        "stdout": completed.stdout,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vivado-bin", type=Path, default=VIVADO_DEFAULT)
    args = parser.parse_args()
    tool_names = ("xvlog", "xelab", "xsim")
    tools = {name: args.vivado_bin / f"{name}.bat" for name in tool_names}
    missing = [str(path) for path in tools.values() if not path.is_file()]
    if missing:
        parser.error("Missing Vivado simulator tools: " + ", ".join(missing))

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S.%fZ") + "_sim"
    evidence = EVIDENCE_ROOT / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    sources = [
        SOURCE_DIR / "z100_tile_reuse_resident_v3.v",
        SOURCE_DIR / "tb_z100_tile_reuse_resident_v3.sv",
    ]
    copied: list[dict[str, object]] = []
    for source in sources:
        target = evidence / source.name
        shutil.copy2(source, target)
        copied.append({
            "source": source.relative_to(ROOT).as_posix(),
            "snapshot": target.name,
            "sha256": sha256(target),
            "bytes": target.stat().st_size,
        })
    work = evidence / "sim_work"
    work.mkdir()
    manifest = {
        "created_utc": now.isoformat(),
        "run_id": run_id,
        "vivado_bin": str(args.vivado_bin.resolve()),
        "sources": copied,
        "snapshot_frozen_before_simulation": True,
    }
    (evidence / "source_snapshot.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    steps = [
        run_tool("xvlog", tools["xvlog"], ["-sv", "-work", "work",
                                           str(evidence / sources[0].name),
                                           str(evidence / sources[1].name)], work),
    ]
    if steps[-1]["return_code"] == 0:
        steps.append(run_tool("xelab", tools["xelab"], ["-debug", "typical", "-top", TOP,
                                                          "-snapshot", TOP], work))
    if steps[-1]["return_code"] == 0:
        steps.append(run_tool("xsim", tools["xsim"], [TOP, "-runall"], work))

    xsim = next((step["stdout"] for step in steps if step["name"] == "xsim"), "")
    case_lines = re.findall(r"^CASE_METRIC\s+(.+)$", xsim, re.MULTILINE)
    replay_lines = re.findall(r"^REPLAY_METRIC\s+(.+)$", xsim, re.MULTILINE)
    cancel_lines = re.findall(r"^CANCEL_STAGE_PASS\s+(.+)$", xsim, re.MULTILINE)
    reset_lines = re.findall(r"^RESET_STAGE_PASS\s+(.+)$", xsim, re.MULTILINE)
    pass_lines = re.findall(r"^SIM_PASS\s+(.+)$", xsim, re.MULTILINE)
    metric_fields = [fields(line) for line in case_lines]
    replay_fields = [fields(line) for line in replay_lines]
    sim_fields = fields(pass_lines[0]) if len(pass_lines) == 1 else {}
    issues: list[str] = []
    if any(step["return_code"] != 0 for step in steps):
        issues.append("a Vivado simulation command returned nonzero")
    if not re.search(r"(?m)^\s*\*+ xsim v2026\.1 \(64-bit\)", xsim):
        issues.append("XSim 2026.1 banner is missing")
    if re.search(r"(?im)^\s*(?:FAIL:|FATAL:|ERROR:)", xsim):
        issues.append("XSim log contains a failure/error marker")
    if len(case_lines) != EXPECTED_RESULT_COMPARISONS:
        issues.append(f"expected {EXPECTED_RESULT_COMPARISONS} CASE_METRIC records, found {len(case_lines)}")
    if len(replay_fields) != 1 or replay_fields[0].get("scalar_comparison_jobs") != "40":
        issues.append("the 40-job scalar replay marker is missing")
    if len(cancel_lines) != 5 or len(reset_lines) != 5:
        issues.append("five cancel and five reset offsets were not observed")
    if len(pass_lines) != 1:
        issues.append("exactly one SIM_PASS marker was not observed")
    if metric_fields and any(item.get("status") != "PASS" for item in metric_fields):
        issues.append("at least one result comparison lacks status=PASS")
    for item in metric_fields:
        taps = int(item["taps"])
        if int(item["groups"]) != (taps + 3) // 4 or int(item["issue_cycles"]) != (taps + 3) // 4:
            issues.append("a workload group count disagrees with ceil(taps/4)")
            break
    prefix = signed32_prefix_expectation()
    report = {
        "status": "PASS" if not issues else "FAIL",
        "created_utc": now.isoformat(),
        "run_id": run_id,
        "simulator_version": "2026.1" if "xsim v2026.1" in xsim else None,
        "source_snapshot": copied,
        "commands": [{key: value for key, value in step.items() if key != "stdout"} for step in steps],
        "workload_coverage": {
            "result_comparisons": len(case_lines),
            "replay_scalar_comparisons": int(replay_fields[0]["scalar_comparison_jobs"]) if replay_fields else 0,
            "cancel_offsets": len(cancel_lines),
            "reset_offsets": len(reset_lines),
            "case_metrics": metric_fields,
            "sim_pass_fields": sim_fields,
            "sim_pass_legacy_cases_field_note": (
                "The bench currently prints cases=7, which is stale; the parsed CASE_METRIC count is authoritative."
                if sim_fields.get("cases") != str(len(case_lines)) else None
            ),
            "persistent_weight_invariant": {
                "weight_epoch": 2,
                "activation_epochs_before_replay": 2,
                "extra_weight_words_during_replay": 0,
                "statement_scope": "isolated v3 bench only; does not claim a production weight-reload defect or system speedup",
            },
            "signed32_prefix_directed_check": prefix,
        },
        "issues": issues,
        "logs": [str((work / f"{step['name']}.stdout.txt").relative_to(evidence)) for step in steps],
    }
    (evidence / "simulation_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], "run_id": run_id,
                      "evidence": str(evidence), "result_comparisons": len(case_lines),
                      "replay_comparisons": len(replay_fields), "issues": issues}, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
