"""Capture private mirror state around the frozen 4-read wrong-epoch failure.

This is a diagnosis-only XSim runner. It reuses the exact fixtures from the
preserved failed run, compiles the frozen RTL with a diagnostic TB copy, and
does not perform synthesis or claim acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIVADO_BIN = Path("C:/appload/2026.1/Vivado/bin")
FAIL_RUN_ID = "20261024T051747.374990Z_9fe23b3f"
FAIL_RESULT = ROOT / f"validation/board_z100/feature_banks_4read_v1/{FAIL_RUN_ID}/result.json"
FAIL_BUILD = ROOT / f"deployment/build/z100_feature_banks_4read_v1/{FAIL_RUN_ID}"
FAIL_RESULT_SHA256 = "e8adab661ef2261774ef40dab7321b6ec857ecdea7da3c5a8ab98e1caf117581"

CHILD = ROOT / "deployment/hardware/z100_2026/feature_banks_addressed_v1/z100_feature_banks_addressed.sv"
WRAPPER = ROOT / "deployment/hardware/z100_2026/feature_banks_4read_v1/z100_feature_banks_4read.sv"
ORIGINAL_TB = ROOT / "deployment/hardware/z100_2026/feature_banks_4read_v1/tb_z100_feature_banks_4read.sv"
DIAG_TB = ROOT / "deployment/hardware/z100_2026/feature_banks_4read_diag_v1/tb_z100_feature_banks_4read_diag.sv"
ORIGINAL_VALIDATOR = ROOT / "tools/validate_z100_feature_banks_4read.py"
LAYOUT = ROOT / "tools/z100_feature_window_layout.py"
BANK_RESULT = ROOT / "validation/board_z100/feature_banks_addressed_v1/20261023T183839.445577Z_9c859c25/result.json"
ROOT_REVIEW = ROOT / "validation/board_z100/acceleration_resource_review/20261023T184429.878019Z/addressed_reuse_review.json"

EXPECTED_SOURCES = {
    "tools\\validate_z100_feature_banks_4read.py": "56a2fff05734b04259e13284e2f851390e27ea1bf2384013722502ed690a2a3b",
    "deployment\\hardware\\z100_2026\\feature_banks_4read_v1\\z100_feature_banks_4read.sv": "a39aa15ddc256a796e78a54b1c71abee12801617a07e440738658f2a49e072bc",
    "deployment\\hardware\\z100_2026\\feature_banks_4read_v1\\tb_z100_feature_banks_4read.sv": "580d7c9e2778ec88ffed9f30819f6242de90a02bac440ccd620737bea9894d69",
    "deployment\\hardware\\z100_2026\\feature_banks_addressed_v1\\z100_feature_banks_addressed.sv": "62c30b0487a54edd6125affa492b3d79c2987203f8cba992fae6560051df656a",
    "tools\\z100_feature_window_layout.py": "54ec4f90867ec9f043fae52270e3b46dc8caf996655abd546c9630333048231a",
    "validation\\board_z100\\feature_banks_addressed_v1\\20261023T183839.445577Z_9c859c25\\result.json": "bf120ba4c98115fef893dc3bc93e5ea65cc612784887a141fd067dc1c7a0996b",
    "validation\\board_z100\\acceleration_resource_review\\20261023T184429.878019Z\\addressed_reuse_review.json": "06fb18a31d98de9699fea8bb07dcbee1201c11b4cbd1c6f7ccf3729d957a7eb7",
    "validation\\board_z100\\feature_banks_4read_v1\\20261024T051747.374990Z_9fe23b3f\\result.json": FAIL_RESULT_SHA256,
}
FIXTURE_NAMES = (
    "feature_banks_4read_cases.hex",
    "feature_banks_4read_load_words.hex",
    "feature_banks_4read_load_addresses.hex",
    "feature_banks_4read_expected_words.hex",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("/", "\\")


def inventory(paths: tuple[Path, ...]) -> dict[str, str]:
    return {rel(path): sha(path) for path in paths}


def snapshot(paths: tuple[Path, ...], target: Path) -> dict[str, str]:
    target.mkdir(parents=True, exist_ok=False)
    copied: dict[str, str] = {}
    for source in paths:
        destination = target / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied[rel(source)] = sha(destination)
    return copied


def run_logged(name: str, argv: list[str], cwd: Path, evidence: Path,
               commands: list[dict[str, object]], env: dict[str, str]) -> str:
    proc = subprocess.run(argv, cwd=cwd, env=env, text=True,
                          encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log_path = evidence / f"{name}.stdout.log"
    log_path.write_text(proc.stdout, encoding="utf-8")
    commands.append({"name": name, "argv": argv, "cwd": str(cwd),
                     "return_code": proc.returncode,
                     "stdout_log": str(log_path)})
    if proc.returncode != 0:
        raise RuntimeError(f"{name} returned {proc.returncode}")
    return proc.stdout


def main() -> int:
    sources = (CHILD, WRAPPER, ORIGINAL_TB, DIAG_TB, ORIGINAL_VALIDATOR,
               LAYOUT, BANK_RESULT, ROOT_REVIEW, FAIL_RESULT,
               Path(__file__).resolve())
    for path in (*sources, *(FAIL_BUILD / name for name in FIXTURE_NAMES)):
        if not path.is_file():
            raise FileNotFoundError(path)

    if sha(FAIL_RESULT) != FAIL_RESULT_SHA256:
        raise ValueError("preserved prior failure report hash changed")
    prior = json.loads(FAIL_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "FAILED_CLOSED" or prior.get("phase") != "XSIM_THEN_ONE_OOC_SYNTH":
        raise ValueError("prior report does not identify the authorized failed XSim run")
    source_before = inventory(sources[:-1])
    if source_before != EXPECTED_SOURCES | {
        rel(DIAG_TB): sha(DIAG_TB),
    }:
        raise ValueError("frozen source binding mismatch against preserved failure")

    prior_fixtures = prior.get("fixtures", {}).get("fixture_sha256", {})
    fixture_sha: dict[str, str] = {}
    for name in FIXTURE_NAMES:
        key = f"deployment\\build\\z100_feature_banks_4read_v1\\{FAIL_RUN_ID}\\{name}"
        expected_hash = prior_fixtures.get(name)
        if not expected_hash or prior.get("artifact_sha256", {}).get(key) != expected_hash:
            raise ValueError(f"prior report does not bind fixture {name}")
        if sha(FAIL_BUILD / name) != expected_hash:
            raise ValueError(f"preserved fixture hash mismatch: {name}")
        fixture_sha[name] = expected_hash

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/feature_banks_4read_diag_v1" / run_id
    build = ROOT / "deployment/build/z100_feature_banks_4read_diag_v1" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    for name in FIXTURE_NAMES:
        shutil.copy2(FAIL_BUILD / name, build / name)
    copied_fixture_sha = {name: sha(build / name) for name in FIXTURE_NAMES}
    if copied_fixture_sha != fixture_sha:
        raise ValueError("copied fixtures do not match the preserved failed run")

    snap_hashes = snapshot(sources, evidence / "source_snapshot")
    result: dict[str, object] = {
        "status": "RUNNING_DIAGNOSIS_ONLY",
        "run_id": run_id,
        "prior_failure_run_id": FAIL_RUN_ID,
        "prior_failure_report_sha256": FAIL_RESULT_SHA256,
        "scope": "diagnostic XSim only; frozen RTL; no OOC or acceptance claim",
        "board_access": False,
        "routing_attempted": False,
        "bitstream_created": False,
        "production_integrated": False,
        "fps_claim": False,
        "observation_window_ns": [323000, 323100],
        "target_request_epoch": 7012,
        "expected_error_code": 7,
        "source_sha256_before": source_before,
        "source_snapshot_sha256": snap_hashes,
        "fixture_sha256_source_failure": fixture_sha,
        "fixture_sha256_diagnostic_build": copied_fixture_sha,
        "fixtures": prior["fixtures"],
        "host_preflight": {"status": "PASS", "bound_to_prior_failed_91_case_run": True},
        "commands": [],
        "diagnostic_snapshots": [],
    }
    commands = result["commands"]
    assert isinstance(commands, list)
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"

    try:
        for executable in ("xvlog.bat", "xelab.bat", "xsim.bat"):
            if not (VIVADO_BIN / executable).is_file():
                raise FileNotFoundError(VIVADO_BIN / executable)
        run_logged("xvlog", [str(VIVADO_BIN / "xvlog.bat"), "-sv",
                              str(CHILD), str(WRAPPER), str(DIAG_TB)],
                   build, evidence, commands, env)
        run_logged("xelab", [str(VIVADO_BIN / "xelab.bat"), "-mt", "2",
                              "tb_z100_feature_banks_4read", "-s",
                              "feature_banks_4read_diag_sim"],
                   build, evidence, commands, env)
        xsim_stdout = run_logged("xsim", [str(VIVADO_BIN / "xsim.bat"),
                                           "feature_banks_4read_diag_sim", "-runall"],
                                 build, evidence, commands, env)
        internal_log = build / "xsim.log"
        internal_text = internal_log.read_text(encoding="utf-8", errors="replace") if internal_log.exists() else ""
        combined = internal_text + "\n" + xsim_stdout
        (evidence / "xsim.internal.log").write_text(internal_text, encoding="utf-8")
        lines = list(dict.fromkeys(line for line in combined.splitlines() if "MIRROR_DIAG" in line))
        result["diagnostic_snapshots"] = lines
        pre = any("phase=PREEDGE" in line for line in lines)
        post = any("phase=POSTEDGE" in line for line in lines)
        fatal = re.search(r"Fatal: error mismatch expected=7 got=1/8", combined)
        result["xsim_observation"] = {
            "preedge_snapshot_seen": pre,
            "postedge_snapshot_seen": post,
            "expected7_actual8_failure_seen": bool(fatal),
            "process_return_code": next((c["return_code"] for c in commands if c["name"] == "xsim"), None),
            "xsim_internal_log": str(internal_log),
        }
        if not (pre and post):
            result["status"] = "FAILED_DIAGNOSTIC_CAPTURE"
            result["error"] = "XSim did not emit both pre-edge and post-edge state snapshots"
        elif fatal:
            result["status"] = "CAPTURED_POST_WRONG_EPOCH_DIVERGENCE"
        else:
            result["status"] = "CAPTURED_DIAGNOSTIC_STATE_NO_EXPECTED_FATAL"
        result["phase"] = "XSIM_DIAGNOSTIC_CAPTURE_COMPLETE"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED_DIAG_ONLY"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["phase"] = "DIAGNOSTIC_FAILED"
    finally:
        result["source_sha256_after"] = inventory(sources[:-1])
        result["artifact_sha256"] = {
            str(path.relative_to(ROOT)).replace("/", "\\"): sha(path)
            for path in (build / name for name in FIXTURE_NAMES)
        }
        result_path = evidence / "result.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (evidence / "launch.json").write_text(json.dumps({
            "run_id": run_id,
            "commands": result["commands"],
            "status": result["status"],
            "result": str(result_path),
        }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(result_path),
                      "snapshots": len(result.get("diagnostic_snapshots", []))}, sort_keys=True))
    return 0 if result["status"].startswith("CAPTURED_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
