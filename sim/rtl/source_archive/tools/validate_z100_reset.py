"""Build and run an isolated synchronous-reset RTL compatibility suite."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC_RTL = ROOT / "deployment" / "hardware" / "z100_2026" / "rtl_sync_reset"
STRESS_TESTS = ROOT / "deployment" / "hardware" / "z100_2026" / "tests"
REFERENCE_RTL = STRESS_TESTS / "reference"
LEGACY_RTL = ROOT / "deployment" / "candidates" / "tile64" / "rtl"
LEGACY_TESTS = ROOT / "deployment" / "candidates" / "tile64" / "tests"
BASELINE_TESTS = ROOT / "deployment" / "hardware" / "toolchain2026" / "tests"
SIM_ROOT = ROOT / "deployment" / "build" / "z100_reset_sim"
REVIEW_ROOT = ROOT / "validation" / "board_z100" / "reset_review"

sys.path.insert(0, str(ROOT / "tools"))
from vivado2026_build import tool_paths


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def canonical_source_contract() -> dict[str, object]:
    pairs = [
        (
            LEGACY_RTL / "v8_tile64_mac.v",
            SYNC_RTL / "v8_tile64_mac.v",
            "always @(posedge clk or negedge rst_n)",
            "always @(posedge clk)",
            1,
            None,
        ),
        (
            LEGACY_RTL / "v8_tile64_axis.v",
            SYNC_RTL / "v8_tile64_axis.v",
            "always @(posedge clk or negedge rst_n)",
            "always @(posedge clk)",
            2,
            (
                "Only this register drives the MAC asynchronous reset.",
                "Only this register drives the MAC synchronous reset.",
            ),
        ),
        (
            ROOT / "deployment" / "hardware" / "z100_2026" / "yolo_accel_top.v",
            SYNC_RTL / "yolo_accel_top.v",
            "always @(posedge sclk or negedge s_rst_n)",
            "always @(posedge sclk)",
            1,
            None,
        ),
    ]
    files: list[dict[str, object]] = []
    failures: list[str] = []
    patches: list[str] = []
    for source, candidate, old_edge, new_edge, expected_count, comment in pairs:
        original_text = source.read_text(encoding="utf-8")
        candidate_text = candidate.read_text(encoding="utf-8")
        actual_count = original_text.count(old_edge)
        normalized = original_text.replace(old_edge, new_edge)
        if actual_count != expected_count:
            failures.append(
                f"{relative(source)} expected {expected_count} reset-sensitive control block(s), got {actual_count}"
            )
        if comment is not None:
            normalized = normalized.replace(comment[0], comment[1])
        if normalized != candidate_text:
            failures.append(f"{relative(candidate)} contains a change beyond the reset contract")
        if old_edge in candidate_text:
            failures.append(f"{relative(candidate)} still has asynchronous reset sensitivity")
        diff = "".join(
            difflib.unified_diff(
                original_text.splitlines(keepends=True),
                candidate_text.splitlines(keepends=True),
                fromfile=relative(source),
                tofile=relative(candidate),
            )
        )
        patches.append(diff)
        files.append({
            "source": relative(source),
            "candidate": relative(candidate),
            "source_sha256": sha256(source),
            "candidate_sha256": sha256(candidate),
            "changed_reset_sensitivity_count": actual_count,
            "normalized_source_matches_candidate": normalized == candidate_text,
        })
    reference_pairs = [
        (
            LEGACY_RTL / "v8_tile64_mac.v",
            REFERENCE_RTL / "v8_tile64_mac_legacy.v",
            "module v8_tile64_mac #(",
            "module v8_tile64_mac_legacy #(",
        ),
        (
            LEGACY_RTL / "v8_tile64_axis.v",
            REFERENCE_RTL / "v8_tile64_axis_legacy.v",
            "module v8_tile64_axis (",
            "module v8_tile64_axis_legacy (",
        ),
    ]
    reference_copies: list[dict[str, str]] = []
    for source, reference, original_name, renamed in reference_pairs:
        original_text = source.read_text(encoding="utf-8")
        reference_text = reference.read_text(encoding="utf-8")
        normalized = original_text.replace(original_name, renamed)
        if source.name == "v8_tile64_axis.v":
            normalized = normalized.replace(
                "v8_tile64_mac core (", "v8_tile64_mac_legacy core ("
            )
        if normalized != reference_text:
            failures.append(f"{relative(reference)} differs beyond module-name isolation")
        patches.append("".join(difflib.unified_diff(
            original_text.splitlines(keepends=True),
            reference_text.splitlines(keepends=True),
            fromfile=relative(source), tofile=relative(reference),
        )))
        reference_copies.append({
            "source": relative(source),
            "copy": relative(reference),
            "source_sha256": sha256(source),
            "copy_sha256": sha256(reference),
            "only_module_names_renamed": normalized == reference_text,
        })
    return {
        "files": files,
        "reference_copies": reference_copies,
        "failures": failures,
        "diff": "".join(patches),
    }


def source_inputs() -> list[Path]:
    return [
        LEGACY_RTL / "v8_tile64_mac.v",
        LEGACY_RTL / "v8_tile64_axis.v",
        ROOT / "deployment" / "hardware" / "z100_2026" / "yolo_accel_top.v",
        BASELINE_TESTS / "tb_v8_tile64_mac.v",
        BASELINE_TESTS / "tb_v8_tile64_axis.v",
        BASELINE_TESTS / "reference" / "v8_tile64_mac_reference.v",
    ]


def run_command(command: list[str], cwd: Path, log_path: Path) -> dict[str, object]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    output = log_path.read_text(encoding="utf-8", errors="replace")
    record = {
        "command": command,
        "cwd": relative(cwd),
        "returncode": result.returncode,
        "log": relative(log_path),
        "log_sha256": sha256(log_path),
        "output_tail": output.splitlines()[-20:],
    }
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}); see {log_path}")
    return record


def run_sim(
    name: str,
    top: str,
    sources: list[Path],
    required_markers: list[str],
    bin_dir: Path,
    run_dir: Path,
) -> dict[str, object]:
    out = run_dir / name
    out.mkdir(parents=True, exist_ok=True)
    commands = []
    source_args = [str(path.resolve()) for path in sources]
    commands.append(run_command(
        [str(bin_dir / "xvlog.bat"), "--work", "work", *source_args],
        out,
        out / "xvlog.log",
    ))
    snapshot = f"{name}_snapshot"
    commands.append(run_command(
        [str(bin_dir / "xelab.bat"), "--mt", "2", "--debug", "typical",
         f"work.{top}", "--snapshot", snapshot],
        out,
        out / "xelab.log",
    ))
    commands.append(run_command(
        [str(bin_dir / "xsim.bat"), snapshot, "--R"],
        out,
        out / "xsim.log",
    ))
    output = (out / "xsim.log").read_text(encoding="utf-8", errors="replace")
    missing = [marker for marker in required_markers if marker not in output]
    if missing or re.search(r"\b(FAIL|FATAL)\b", output, re.IGNORECASE):
        raise RuntimeError(f"{name}: missing PASS marker(s) {missing}; see {out / 'xsim.log'}")
    return {
        "name": name,
        "top": top,
        "status": "PASS",
        "required_markers": required_markers,
        "commands": commands,
        "xsim_log_sha256": sha256(out / "xsim.log"),
    }


def run_suite(vivado_root: Path | None = None) -> Path:
    contract = canonical_source_contract()
    if contract["failures"]:
        raise ValueError("RTL source contract failed: " + "; ".join(contract["failures"]))
    bin_dir, vivado_launcher = tool_paths(vivado_root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = SIM_ROOT / run_id
    report_dir = REVIEW_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    report_dir.mkdir(parents=True, exist_ok=False)
    before_hashes = {relative(path): sha256(path) for path in source_inputs()}

    source_report = report_dir / "source_diff.patch"
    source_report.write_text(str(contract["diff"]), encoding="utf-8")
    runs: list[dict[str, object]] = []
    runs.append(run_sim(
        "legacy_mac_reference",
        "tb_v8_tile64_mac",
        [LEGACY_RTL / "v8_tile64_mac.v",
         BASELINE_TESTS / "reference" / "v8_tile64_mac_reference.v",
         BASELINE_TESTS / "tb_v8_tile64_mac.v"],
        ["PASS v8_tile64_mac full depth, 17/33/63 tails, saturation, and invalid lane check"],
        bin_dir, run_dir,
    ))
    runs.append(run_sim(
        "sync_mac_reference",
        "tb_v8_tile64_mac",
        [SYNC_RTL / "v8_tile64_mac.v",
         BASELINE_TESTS / "reference" / "v8_tile64_mac_reference.v",
         BASELINE_TESTS / "tb_v8_tile64_mac.v"],
        ["PASS v8_tile64_mac full depth, 17/33/63 tails, saturation, and invalid lane check"],
        bin_dir, run_dir,
    ))
    runs.append(run_sim(
        "legacy_axis_reference",
        "tb_v8_tile64_axis",
        [LEGACY_RTL / "v8_tile64_mac.v", LEGACY_RTL / "v8_tile64_axis.v",
         BASELINE_TESTS / "tb_v8_tile64_axis.v"],
        ["PASS v8_tile64_axis ABI, 4096 results, max taps, tails, error/abort recovery, and backpressure"],
        bin_dir, run_dir,
    ))
    runs.append(run_sim(
        "sync_axis_reference",
        "tb_v8_tile64_axis",
        [SYNC_RTL / "v8_tile64_mac.v", SYNC_RTL / "v8_tile64_axis.v",
         BASELINE_TESTS / "tb_v8_tile64_axis.v"],
        ["PASS v8_tile64_axis ABI, 4096 results, max taps, tails, error/abort recovery, and backpressure"],
        bin_dir, run_dir,
    ))
    runs.append(run_sim(
        "differential_reset_stress",
        "tb_z100_sync_reset_stress",
        [REFERENCE_RTL / "v8_tile64_mac_legacy.v",
         REFERENCE_RTL / "v8_tile64_axis_legacy.v",
         SYNC_RTL / "v8_tile64_mac.v", SYNC_RTL / "v8_tile64_axis.v",
         STRESS_TESTS / "tb_z100_sync_reset_stress.v"],
        [
            "PASS differential normal transactions byte/cycle exact",
            "PASS cfg_abort stage=1", "PASS cfg_abort stage=4",
            "PASS cfg_abort stage=7", "PASS cfg_abort stage=8",
            "PASS cfg_abort stage=9", "PASS cfg_abort stage=11",
            "PASS synchronous reset stage=1", "PASS synchronous reset stage=4",
            "PASS synchronous reset stage=7", "PASS synchronous reset stage=8",
            "PASS synchronous reset stage=9", "PASS synchronous reset stage=11",
            "PASS z100_sync_reset_stress",
        ],
        bin_dir, run_dir,
    ))
    runs.append(run_sim(
        "wrapper_reset_stress",
        "tb_z100_sync_reset_wrapper",
        [SYNC_RTL / "v8_tile64_mac.v", SYNC_RTL / "v8_tile64_axis.v",
         SYNC_RTL / "yolo_accel_top.v", STRESS_TESTS / "tb_z100_sync_reset_wrapper.v"],
        ["PASS wrapper pending start reset clears only on active edge"],
        bin_dir, run_dir,
    ))

    after_hashes = {relative(path): sha256(path) for path in source_inputs()}
    if after_hashes != before_hashes:
        raise RuntimeError("read-only legacy RTL/TB inputs changed during validation")

    simulation_sources = sorted(set(source_inputs() + [
        SYNC_RTL / "v8_tile64_mac.v", SYNC_RTL / "v8_tile64_axis.v",
        SYNC_RTL / "yolo_accel_top.v",
        REFERENCE_RTL / "v8_tile64_mac_legacy.v",
        REFERENCE_RTL / "v8_tile64_axis_legacy.v",
        STRESS_TESTS / "tb_z100_sync_reset_stress.v",
        STRESS_TESTS / "tb_z100_sync_reset_wrapper.v",
        Path(__file__).resolve(),
    ]))
    stress_log = (run_dir / "differential_reset_stress" / "xsim.log").read_text(
        encoding="utf-8", errors="replace"
    )
    coverage = re.search(
        r"compared_cycles=(\d+) responses=(\d+) aborts=(\d+) resets=(\d+)",
        stress_log,
    )
    recovery_sequences = sorted({
        int(sequence)
        for sequence in re.findall(r"PASS recovery sequence=(\d+)", stress_log)
    })
    if coverage is None or len(recovery_sequences) != 12:
        raise RuntimeError("stress evidence is missing its cycle/recovery counters")
    report = {
        "schema_version": 1,
        "status": "PASS",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "vivado_root": str(vivado_launcher.parent.parent.resolve()),
        "build_dir": relative(run_dir),
        "validation_scope": "isolated synchronous reset candidate; no synth/implementation/Vitis/board run",
        "source_contract": contract["files"],
        "legacy_miter_copies": contract["reference_copies"],
        "source_diff": {
            "path": relative(source_report),
            "sha256": sha256(source_report),
        },
        "simulation_sources_sha256": {
            relative(path): sha256(path) for path in simulation_sources
        },
        "read_only_inputs_sha256": before_hashes,
        "read_only_inputs_unchanged": before_hashes == after_hashes,
        "differential_coverage": {
            "compared_cycles": int(coverage.group(1)),
            "response_words_checked": int(coverage.group(2)),
            "abort_stages": int(coverage.group(3)),
            "synchronous_reset_stages": int(coverage.group(4)),
            "stale_run_reject_then_full_reload_recovery_sequences": len(recovery_sequences),
            "recovery_sequence_ids": recovery_sequences,
        },
        "simulations": runs,
        "commands": [command for run in runs for command in run["commands"]],
    }
    json_path = report_dir / "reset_review.json"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Z100 synchronous reset candidate review",
        "",
        f"Status: **{report['status']}**",
        "",
        "The candidate changes reset sampling on control registers only. The memory processes, arithmetic, interfaces, and pipeline latency remain copied from the frozen legacy sources. This report covers RTL simulation only; it does not claim synthesis, BRAM inference, timing closure, physical reset behavior, or board correctness.",
        "",
        "## Simulation results",
        "",
    ]
    for run in runs:
        lines.append(f"- **{run['name']}**: PASS; {', '.join(run['required_markers'])}")
    lines += [
        "",
        f"The differential run compared {coverage.group(1)} cycles and {coverage.group(2)} response words, with six abort-stage cases and six global-reset cases. All twelve interrupted flows rejected a stale RUN, reloaded the full model, and completed a fresh RUN.",
        "",
        "All simulation source paths and SHA-256 values, exact xvlog/xelab/xsim command lines, return codes, and log hashes are recorded in the machine report.",
        "",
        f"Source diff: [`source_diff.patch`]({source_report.name}) (SHA-256 `{sha256(source_report)}`).",
        f"Machine report: [`reset_review.json`]({json_path.name}).",
        "",
    ]
    markdown = report_dir / "reset_review.md"
    markdown.write_text("\n".join(lines), encoding="utf-8")
    print(f"RESET_REVIEW_PASS report={relative(markdown)}")
    print(f"SIM_BUILD_DIR={relative(run_dir)}")
    return markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vivado-root", type=Path)
    parser.add_argument("--check-source-only", action="store_true")
    args = parser.parse_args()
    try:
        contract = canonical_source_contract()
        if contract["failures"]:
            raise ValueError("; ".join(contract["failures"]))
        if args.check_source_only:
            print("RESET_SOURCE_CONTRACT_PASS")
            return 0
        run_suite(args.vivado_root)
        return 0
    except Exception as exc:  # CLI should preserve a useful failure result.
        print(f"RESET_REVIEW_FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
