#!/usr/bin/env python3
"""Validate and replay the frozen, portable RTL component regressions."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PACKAGE_ROOT / "sim" / "rtl" / "portable_cases.json"
REFERENCE_PATH = PACKAGE_ROOT / "sim" / "rtl" / "reference_results.json"
VIVADO_GLBL = "$VIVADO_GLBL$"
LOCK_NAME = r"Local\Z100_Vivado_Implementation"
CASE_IDS = (
    "control01",
    "fault_diagnostics01",
    "id_fault01",
    "mixed01",
    "mixed_diagnostics01",
    "pool_control01",
    "pool_fault01",
    "tail01",
    "unit01",
)
TOOLS = ("xvlog", "xelab", "xsim")
VERSION_PATTERN = re.compile(r"(?<!\d)2026\.1(?!\d)")
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_VIVADO = 4
EXIT_RUN = 5
EXIT_MARKER = 6
EXIT_LOCK = 7


class RunnerError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_output_path(raw: str, package_root: Path) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.exists() or candidate.is_symlink():
        raise RunnerError(EXIT_USAGE, "output directory already exists; choose a new path")
    candidate = candidate.resolve()
    package_root = package_root.resolve()
    if is_within(candidate, package_root):
        raise RunnerError(EXIT_USAGE, "output directory must be outside the package")
    parent = candidate.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.is_dir():
        raise RunnerError(EXIT_USAGE, "output directory has a non-directory parent")
    if is_within(parent.resolve(), package_root):
        raise RunnerError(EXIT_USAGE, "output parent resolves inside the package")
    return candidate


def read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerError(EXIT_INPUT, f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunnerError(EXIT_INPUT, f"{label} must contain a JSON object")
    return value


def validate_reference_results(reference: dict) -> dict[str, dict]:
    if reference.get("historical") is not True or reference.get("new_simulation_run") is not False:
        raise RunnerError(EXIT_INPUT, "reference_results.json must remain historical and not claim a fresh run")
    rows = reference.get("cases")
    if not isinstance(rows, list):
        raise RunnerError(EXIT_INPUT, "reference_results.json has no cases list")
    by_id: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in by_id:
            raise RunnerError(EXIT_INPUT, "reference_results.json contains an invalid or duplicate case")
        by_id[row["id"]] = row
    if set(by_id) != set(CASE_IDS):
        raise RunnerError(EXIT_INPUT, "reference_results.json must describe the nine portable cases")
    return by_id


def validate_manifest(manifest: dict, reference: dict, package_root: Path) -> list[dict]:
    if manifest.get("schema") != "z100-portable-rtl-cases-v1":
        raise RunnerError(EXIT_INPUT, "unsupported portable case manifest schema")
    if manifest.get("vivado_version") != "2026.1":
        raise RunnerError(EXIT_INPUT, "portable cases require Vivado 2026.1")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != len(CASE_IDS):
        raise RunnerError(EXIT_INPUT, "portable case manifest must contain exactly nine cases")

    reference_by_id = validate_reference_results(reference)
    by_id: dict[str, dict] = {}
    package_root = package_root.resolve()
    for case in rows:
        if not isinstance(case, dict):
            raise RunnerError(EXIT_INPUT, "portable manifest contains a non-object case")
        case_id = case.get("id")
        if case_id not in CASE_IDS or case_id in by_id:
            raise RunnerError(EXIT_INPUT, f"unknown or duplicate case id: {case_id!r}")
        files = case.get("files")
        if not isinstance(files, list) or not files:
            raise RunnerError(EXIT_INPUT, f"{case_id}: files must be a non-empty list")
        staged: dict[str, dict] = {}
        for entry in files:
            if not isinstance(entry, dict):
                raise RunnerError(EXIT_INPUT, f"{case_id}: invalid file entry")
            name = entry.get("staged_name")
            source = entry.get("path")
            expected_hash = entry.get("sha256")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in (".", ".."):
                raise RunnerError(EXIT_INPUT, f"{case_id}: unsafe staged_name {name!r}")
            folded = name.casefold()
            if folded in staged:
                raise RunnerError(EXIT_INPUT, f"{case_id}: duplicate staged_name {name!r}")
            if not isinstance(source, str):
                raise RunnerError(EXIT_INPUT, f"{case_id}: invalid source path for {name}")
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise RunnerError(EXIT_INPUT, f"{case_id}: invalid SHA-256 for {name}")
            if source == VIVADO_GLBL:
                resolved = None
            else:
                posix = PurePosixPath(source)
                if (
                    not re.fullmatch(r"[A-Za-z0-9_./-]+", source)
                    or posix.is_absolute()
                    or "\\" in source
                    or any(part in ("", ".", "..") for part in posix.parts)
                ):
                    raise RunnerError(EXIT_INPUT, f"{case_id}: unsafe package input path {source!r}")
                resolved = (package_root / Path(*posix.parts)).resolve()
                if not is_within(resolved, package_root):
                    raise RunnerError(EXIT_INPUT, f"{case_id}: input escapes package: {source}")
                if not resolved.is_file():
                    raise RunnerError(EXIT_INPUT, f"{case_id}: missing input {source}")
                actual_hash = sha256_file(resolved)
                if actual_hash != expected_hash:
                    raise RunnerError(EXIT_INPUT, f"{case_id}: SHA-256 mismatch for {source}")
            staged[folded] = {
                "staged_name": name,
                "path": source,
                "sha256": expected_hash,
                "resolved_path": str(resolved) if resolved else None,
            }

        commands = case.get("commands")
        if not isinstance(commands, list) or len(commands) != len(TOOLS):
            raise RunnerError(EXIT_INPUT, f"{case_id}: expected xvlog, xelab, xsim commands")
        for index, command in enumerate(commands):
            if not isinstance(command, list) or not command or command[0] != TOOLS[index]:
                raise RunnerError(EXIT_INPUT, f"{case_id}: command sequence must be xvlog, xelab, xsim")
            for arg in command[1:]:
                if not isinstance(arg, str) or not arg or not re.fullmatch(r"[A-Za-z0-9_.+,:=-]+", arg):
                    raise RunnerError(EXIT_INPUT, f"{case_id}: unsafe command argument {arg!r}")
                if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", arg):
                    raise RunnerError(EXIT_INPUT, f"{case_id}: absolute command path is not portable: {arg}")
        compile_inputs = [arg.casefold() for arg in commands[0][1:] if not arg.startswith("-")]
        staged_names = set(staged)
        if not compile_inputs or any(name not in staged_names for name in compile_inputs):
            raise RunnerError(EXIT_INPUT, f"{case_id}: xvlog command references an unstaged source")
        if "-runall" not in commands[2]:
            raise RunnerError(EXIT_INPUT, f"{case_id}: xsim must use -runall")
        marker = case.get("pass_marker")
        historical_hash = case.get("historical_result_sha256")
        reference_row = reference_by_id.get(case_id, {})
        if not isinstance(marker, str) or not marker:
            raise RunnerError(EXIT_INPUT, f"{case_id}: pass_marker is missing")
        if historical_hash != reference_row.get("original_result_sha256"):
            raise RunnerError(EXIT_INPUT, f"{case_id}: historical result hash disagrees with reference_results.json")
        if case.get("historical_status") != reference_row.get("status"):
            raise RunnerError(EXIT_INPUT, f"{case_id}: historical status disagrees with reference_results.json")
        if marker != reference_row.get("pass_marker"):
            raise RunnerError(EXIT_INPUT, f"{case_id}: historical marker disagrees with reference_results.json")

        case["_validated_files"] = list(staged.values())
        by_id[case_id] = case

    if set(by_id) != set(CASE_IDS):
        raise RunnerError(EXIT_INPUT, "portable case manifest must describe all nine expected cases")
    return [by_id[case_id] for case_id in CASE_IDS]


def resolve_vivado_bin(raw: str | None, expected_version: str) -> tuple[Path | None, dict | None]:
    if raw is None:
        return None, None
    candidate = Path(raw).expanduser().resolve()
    if expected_version != "2026.1":
        raise RunnerError(EXIT_VIVADO, f"unsupported Vivado version: {expected_version}")
    if not candidate.is_dir():
        raise RunnerError(EXIT_VIVADO, f"Vivado bin directory does not exist: {candidate}")
    if re.search(r"[%&|<>^!\"\r\n]", str(candidate)):
        raise RunnerError(EXIT_VIVADO, "Vivado bin path contains characters unsafe for Windows command invocation")
    names = [f"{tool}.bat" for tool in TOOLS]
    bin_path = candidate
    if not all((bin_path / name).is_file() for name in names) and all(
        (candidate / "bin" / name).is_file() for name in names
    ):
        bin_path = candidate / "bin"
    tools: dict[str, Path] = {}
    for name in TOOLS:
        bat = bin_path / f"{name}.bat"
        native = bin_path / name
        if bat.is_file():
            tools[name] = bat.resolve()
        elif native.is_file():
            tools[name] = native.resolve()
        else:
            raise RunnerError(EXIT_VIVADO, f"Vivado tool not found: {name} in {bin_path}")
    glbl = bin_path.parent / "data" / "verilog" / "src" / "glbl.v"
    if not glbl.is_file():
        raise RunnerError(EXIT_VIVADO, f"Vivado global module not found: {glbl}")
    glbl_hash = sha256_file(glbl)
    expected_glbl_hashes = {
        entry["sha256"]
        for case in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["cases"]
        for entry in case["files"]
        if entry.get("path") == VIVADO_GLBL
    }
    if expected_glbl_hashes != {glbl_hash}:
        raise RunnerError(EXIT_VIVADO, f"Vivado glbl.v SHA-256 mismatch: {glbl}")
    return bin_path, {"tools": tools, "glbl_path": glbl.resolve(), "glbl_sha256": glbl_hash}


@contextlib.contextmanager
def implementation_lock():
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
        kernel32.ReleaseMutex.restype = ctypes.c_bool
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool
        handle = kernel32.CreateMutexW(None, False, LOCK_NAME)
        if not handle:
            raise RunnerError(EXIT_LOCK, f"cannot create Vivado mutex (Windows error {ctypes.get_last_error()})")
        acquired = kernel32.WaitForSingleObject(handle, 0) in (0, 0x80)
        try:
            if not acquired:
                raise RunnerError(EXIT_LOCK, f"Vivado implementation mutex is busy: {LOCK_NAME}")
            yield
        finally:
            if acquired:
                kernel32.ReleaseMutex(handle)
            kernel32.CloseHandle(handle)
        return

    lock_path = Path(tempfile.gettempdir()) / "Z100_Vivado_Implementation.lock"
    lock_stream = lock_path.open("a+b")
    try:
        try:
            import fcntl

            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, BlockingIOError) as exc:
            raise RunnerError(EXIT_LOCK, "Vivado implementation lock is busy or unsupported") from exc
        yield
    finally:
        try:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        except (ImportError, UnboundLocalError):
            pass
        lock_stream.close()


def write_json(path: Path, data: dict) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp_path.replace(path)


def stage_case(case: dict, case_dir: Path, vivado_info: dict) -> list[dict]:
    staged = []
    for entry in case["_validated_files"]:
        source = Path(entry["resolved_path"]) if entry["resolved_path"] else vivado_info["glbl_path"]
        target = case_dir / entry["staged_name"]
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            raise RunnerError(EXIT_INPUT, f"{case['id']}: cannot stage {entry['staged_name']}: {exc}") from exc
        actual_hash = sha256_file(target)
        if actual_hash != entry["sha256"]:
            raise RunnerError(EXIT_INPUT, f"{case['id']}: staged copy hash mismatch for {entry['staged_name']}")
        staged.append({
            "staged_name": entry["staged_name"],
            "source_path": entry["path"],
            "sha256": actual_hash,
            "bytes": target.stat().st_size,
        })
    return staged


def semantic_command(tool_path: Path, command: list[str]) -> list[str]:
    return [str(tool_path), *command[1:]]


def process_command(tool_path: Path, command: list[str]) -> list[str]:
    semantic = semantic_command(tool_path, command)
    if os.name == "nt" and tool_path.suffix.lower() in (".bat", ".cmd"):
        comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        invocation = "call " + subprocess.list2cmdline(semantic)
        return [comspec, "/d", "/c", invocation]
    return semantic


def run_one_process(argv: list[str], cwd: Path, log_path: Path) -> tuple[int, float]:
    started = time.monotonic()
    with log_path.open("wb") as log_stream:
        try:
            completed = subprocess.run(argv, cwd=cwd, stdout=log_stream, stderr=subprocess.STDOUT, check=False)
        except OSError as exc:
            log_stream.write(f"\nRunner could not start process: {exc}\n".encode("utf-8", errors="replace"))
            return 127, time.monotonic() - started
    return completed.returncode, time.monotonic() - started


def query_tool_version(label: str, tool_path: Path, output_dir: Path) -> dict:
    log_path = output_dir / f"{label}_version.log"
    command = [label, "-version"]
    argv = process_command(tool_path, command)
    return_code, elapsed = run_one_process(argv, output_dir, log_path)
    output = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    match = VERSION_PATTERN.search(output)
    return {
        "tool": label,
        "argv": semantic_command(tool_path, command),
        "launcher_argv": argv,
        "cwd": str(output_dir),
        "log": log_path.name,
        "log_sha256": sha256_file(log_path) if log_path.exists() else None,
        "return_code": return_code,
        "elapsed_seconds": round(elapsed, 3),
        "reported_version": match.group(0) if match else None,
        "output": output.strip(),
    }


def build_case_plan(case: dict, case_dir: Path, vivado_info: dict) -> dict:
    commands = []
    for command in case["commands"]:
        tool_path = vivado_info["tools"][command[0]]
        commands.append({
            "argv": semantic_command(tool_path, command),
            "launcher_argv": process_command(tool_path, command),
            "cwd": str(case_dir),
            "log": f"{command[0]}.log",
        })
    return {"id": case["id"], "output_dir": str(case_dir), "commands": commands}


def create_plan(output_dir: Path, cases: list[dict], bin_path: Path, vivado_info: dict) -> dict:
    planned_cases = []
    for case in cases:
        case_dir = output_dir / case["id"]
        case_dir.mkdir()
        staged = stage_case(case, case_dir, vivado_info)
        planned_cases.append({
            **build_case_plan(case, case_dir, vivado_info),
            "inputs": staged,
            "historical_reference": {
                "status": case["historical_status"],
                "result_sha256": case["historical_result_sha256"],
            },
            "pass_marker": case["pass_marker"],
        })
    return {
        "schema": "z100-portable-rtl-run-v1",
        "status": "prepared_only_not_run",
        "created_utc": utc_now(),
        "vivado_bin": str(bin_path),
        "vivado_expected_version": "2026.1",
        "vivado_version": None,
        "glbl": {"path": str(vivado_info["glbl_path"]), "sha256": vivado_info["glbl_sha256"]},
        "package_manifest_sha256": sha256_file(MANIFEST_PATH),
        "cases": planned_cases,
    }


def run_cases(output_dir: Path, cases: list[dict], bin_path: Path, vivado_info: dict) -> dict:
    report = {
        "schema": "z100-portable-rtl-run-v1",
        "status": "running",
        "started_utc": utc_now(),
        "finished_utc": None,
        "vivado_bin": str(bin_path),
        "vivado_version": None,
        "simulator_version": None,
        "tool_version_probes": [],
        "notes": [],
        "glbl": {"path": str(vivado_info["glbl_path"]), "sha256": vivado_info["glbl_sha256"]},
        "package_manifest_sha256": sha256_file(MANIFEST_PATH),
        "cases": [],
    }
    report_path = output_dir / "run_report.json"
    write_json(report_path, report)

    try:
        vivado = bin_path / "vivado.bat"
        if not vivado.is_file():
            vivado = bin_path / "vivado"
        if vivado.is_file():
            vivado_probe = query_tool_version("vivado", vivado, output_dir)
            report["tool_version_probes"].append(vivado_probe)
            report["vivado_version"] = vivado_probe["reported_version"]
            if vivado_probe["return_code"] != 0:
                report["notes"].append(
                    "Vivado full CLI version probe returned nonzero; the XSim tool version probes below are the simulation eligibility checks."
                )
            write_json(report_path, report)
        for tool_name in TOOLS:
            probe = query_tool_version(tool_name, vivado_info["tools"][tool_name], output_dir)
            report["tool_version_probes"].append(probe)
            write_json(report_path, report)
            if probe["return_code"] != 0 or probe["reported_version"] != "2026.1":
                raise RunnerError(
                    EXIT_VIVADO,
                    f"{tool_name} version probe exited {probe['return_code']} or did not report 2026.1; see {probe['log']}",
                )
        report["simulator_version"] = "2026.1"
        write_json(report_path, report)
    except RunnerError as exc:
        report["status"] = "FAIL"
        report["finished_utc"] = utc_now()
        report["error"] = str(exc)
        write_json(report_path, report)
        raise
    failure: RunnerError | None = None
    for case in cases:
        case_dir = output_dir / case["id"]
        case_dir.mkdir()
        case_report = {
            **build_case_plan(case, case_dir, vivado_info),
            "status": "running",
            "inputs": [],
            "commands": [],
            "pass_marker": case["pass_marker"],
            "historical_reference": {
                "status": case["historical_status"],
                "result_sha256": case["historical_result_sha256"],
            },
        }
        report["cases"].append(case_report)
        try:
            case_report["inputs"] = stage_case(case, case_dir, vivado_info)
            for index, command in enumerate(case["commands"]):
                print(f"RUN {case['id']}: {command[0]}", flush=True)
                tool_path = vivado_info["tools"][command[0]]
                argv = process_command(tool_path, command)
                log_path = case_dir / f"{command[0]}.log"
                return_code, elapsed = run_one_process(argv, case_dir, log_path)
                case_report["commands"].append({
                    "argv": semantic_command(tool_path, command),
                    "launcher_argv": argv,
                    "cwd": str(case_dir),
                    "log": log_path.name,
                    "log_sha256": sha256_file(log_path),
                    "return_code": return_code,
                    "elapsed_seconds": round(elapsed, 3),
                })
                write_json(report_path, report)
                if return_code != 0:
                    raise RunnerError(EXIT_RUN, f"{case['id']}: {command[0]} exited {return_code}; see {log_path}")
                if index == 2:
                    output = log_path.read_text(encoding="utf-8", errors="replace")
                    if re.search(r"\b(?:FATAL|ERROR)\b", output, flags=re.IGNORECASE):
                        raise RunnerError(EXIT_RUN, f"{case['id']}: xsim log contains FATAL or ERROR; see {log_path}")
                    if case["pass_marker"] not in output:
                        raise RunnerError(EXIT_MARKER, f"{case['id']}: xsim pass marker is absent; see {log_path}")
                print(f"PASS {case['id']}: {command[0]}", flush=True)
            case_report["status"] = "PASS_FRESH_COMPONENT_TEST"
        except RunnerError as exc:
            case_report["status"] = "FAIL"
            case_report["error"] = str(exc)
            failure = exc
            write_json(report_path, report)
            break
        write_json(report_path, report)
    report["finished_utc"] = utc_now()
    report["status"] = "PASS_FRESH_SELECTED_COMPONENT_TESTS" if failure is None else "FAIL"
    write_json(report_path, report)
    if failure is not None:
        raise failure
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="validate packaged inputs only (default)")
    modes.add_argument("--prepare", action="store_true", help="stage selected cases and write commands without running tools")
    modes.add_argument("--run", action="store_true", help="run selected RTL regressions")
    parser.add_argument("--case", choices=(*CASE_IDS, "all"), help="case to prepare or run")
    parser.add_argument("--vivado-bin", help="path to Vivado 2026.1 bin directory")
    parser.add_argument("--output-dir", help="new output directory outside the package")
    args = parser.parse_args(argv)
    active_mode = "run" if args.run else "prepare" if args.prepare else "check"
    if active_mode == "check":
        if args.case or args.output_dir:
            parser.error("--case and --output-dir require --prepare or --run")
    else:
        if not args.case or not args.output_dir or not args.vivado_bin:
            parser.error("--prepare and --run require --case, --vivado-bin, and --output-dir")
    args.mode = active_mode
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        manifest = read_json(MANIFEST_PATH, "portable_cases.json")
        reference = read_json(REFERENCE_PATH, "reference_results.json")
        cases = validate_manifest(manifest, reference, PACKAGE_ROOT)
        if args.mode == "check":
            if args.vivado_bin:
                bin_path, vivado_info = resolve_vivado_bin(args.vivado_bin, manifest["vivado_version"])
                print(f"PASS: 9 case manifests and package inputs validated; glbl.v checked at {vivado_info['glbl_path']}")
            else:
                print("PASS: 9 case manifests and package inputs validated; external Vivado glbl.v was not checked")
            print("Historical results remain historical; no simulation was run.")
            return 0

        selected = cases if args.case == "all" else [case for case in cases if case["id"] == args.case]
        if not selected:
            raise RunnerError(EXIT_USAGE, f"unknown case: {args.case}")
        output_dir = validate_output_path(args.output_dir, PACKAGE_ROOT)
        bin_path, vivado_info = resolve_vivado_bin(args.vivado_bin, manifest["vivado_version"])
        assert bin_path is not None and vivado_info is not None
        if args.mode == "prepare":
            output_dir.mkdir(parents=True, exist_ok=False)
            plan = create_plan(output_dir, selected, bin_path, vivado_info)
            write_json(output_dir / "plan.json", plan)
            print(f"PREPARED ONLY: staged {len(selected)} case(s) at {output_dir}; no simulation tools were run")
            return 0

        with implementation_lock():
            output_dir.mkdir(parents=True, exist_ok=False)
            report = run_cases(output_dir, selected, bin_path, vivado_info)
        print(f"PASS: {len(report['cases'])} fresh component/core case(s); report: {output_dir / 'run_report.json'}")
        return 0
    except RunnerError as exc:
        print(f"ERROR[{exc.code}]: {exc}", file=sys.stderr)
        return exc.code
    except OSError as exc:
        print(f"ERROR[{EXIT_RUN}]: file or process operation failed: {exc}", file=sys.stderr)
        return EXIT_RUN


if __name__ == "__main__":
    raise SystemExit(main())
