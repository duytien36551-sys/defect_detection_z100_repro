#!/usr/bin/env python3
"""Check or explicitly rebuild the portable softpack49000 ARM firmware."""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

sys.dont_write_bytecode = True

import rebuild_bsp_sources


SCHEMA = "z100_portable_firmware_v1"
ABSOLUTE_PATH_RE = re.compile(r"(?:[a-zA-Z]:[\\/]|\\\\)")
BUSY_PROCESS_NAMES = {
    "vivado.exe",
    "vitis.exe",
    "xsct.exe",
    "xsdb.exe",
    "hw_server.exe",
    "program_flash.exe",
    "flashwriter.exe",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from walk_strings(key)
            yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)


def assert_relative_metadata(value: Any, label: str) -> None:
    for text in walk_strings(value):
        if ABSOLUTE_PATH_RE.search(text):
            raise ValueError(f"Absolute path found in portable {label}: {text}")


def safe_package_path(value: str) -> str:
    text = PurePosixPath(value.replace("\\", "/")).as_posix()
    parts = text.split("/")
    if (
        not text
        or text.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
        or not text.isascii()
        or text != text.lower()
        or re.search(r"[^a-z0-9._/+-]", text)
    ):
        raise ValueError(f"Unsafe package path: {value!r}")
    return text


def load_and_check(bundle: Path) -> dict[str, Any]:
    rebuild_bsp_sources.validate_snapshot(bundle.parent / "bsp_snapshot")
    manifest_path = bundle / "manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported firmware bundle schema")
    assert_relative_metadata(manifest, "manifest")

    listed: dict[str, dict[str, Any]] = {}
    for record in manifest.get("files", []):
        relative = safe_package_path(record["path"])
        if relative in listed:
            raise ValueError(f"Duplicate package file record: {relative}")
        listed[relative] = record
        path = bundle / PurePosixPath(relative)
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise ValueError(f"Package file changed: {relative}")

    actual = {
        safe_package_path(path.relative_to(bundle).as_posix())
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    forbidden_suffixes = {".a", ".o", ".log", ".pyc"}
    forbidden = sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.suffix.casefold() in forbidden_suffixes
    )
    if forbidden:
        raise ValueError(f"Build products are present in the portable firmware bundle: {forbidden}")
    if actual != set(listed):
        missing = sorted(actual - set(listed))
        absent = sorted(set(listed) - actual)
        raise ValueError(f"Package inventory differs; unlisted={missing}, missing={absent}")

    objects = manifest.get("objects", [])
    if len(objects) != 90 or manifest.get("compile_object_count") != 90:
        raise ValueError("Bundle must contain exactly 90 compile command records")
    object_names = set()
    for entry in objects:
        name = safe_package_path(entry["object"])
        if name in object_names:
            raise ValueError(f"Duplicate object name: {name}")
        object_names.add(name)
        source = safe_package_path(entry["source"])
        if not (bundle / PurePosixPath(source)).is_file():
            raise FileNotFoundError(bundle / PurePosixPath(source))
        if sha256(bundle / PurePosixPath(source)) != entry["source_sha256"]:
            raise ValueError(f"Compile source hash mismatch: {source}")
        command_path = safe_package_path(entry["command"])
        command = read_json(bundle / PurePosixPath(command_path))
        assert_relative_metadata(command, command_path)
        if command.get("object") != entry["object"] or command.get("source") != entry["source"]:
            raise ValueError(f"Compile command identity mismatch: {command_path}")
        if not isinstance(command.get("argv"), list) or not command["argv"]:
            raise ValueError(f"Missing argv in {command_path}")

    link_path = safe_package_path(manifest["link"]["command_file"])
    link = read_json(bundle / PurePosixPath(link_path))
    assert_relative_metadata(link, link_path)
    if len([arg for arg in link["argv"] if arg.startswith("$OUT$/obj/")]) != 90:
        raise ValueError("Link command must contain the accepted map's 90 object inputs")
    expected_libraries = [
        "$OUT$/bsp/lib/libxilstandalone.a",
        "$OUT$/bsp/lib/libxiltimer.a",
        "$OUT$/bsp/lib/libxil.a",
    ]
    if [arg for arg in link["argv"] if arg.endswith(".a")] != expected_libraries:
        raise ValueError("Link command must use BSP libraries generated in the external build directory")
    if any("$BUNDLE$/libs/bsp" in arg for arg in link["argv"]):
        raise ValueError("Link command depends on packaged prebuilt BSP libraries")
    for directory in manifest.get("include_directories", []):
        relative = safe_package_path(directory)
        if not (bundle / PurePosixPath(relative)).is_dir():
            raise FileNotFoundError(bundle / PurePosixPath(relative))

    reference = manifest.get("reference_elf", {})
    reference_path = safe_package_path(reference.get("path", ""))
    reference_record = listed.get(reference_path)
    if reference_record is None or reference_record.get("sha256") != reference.get("sha256"):
        raise ValueError("Reference ELF metadata does not match its packaged file")
    return manifest


def expand_tokens(argv: list[str], bundle: Path, output: Path, toolchain: Path) -> list[str]:
    substitutions = {
        "$BUNDLE$": str(bundle),
        "$OUT$": str(output),
        "$TOOLCHAIN$": str(toolchain),
    }
    expanded = []
    for argument in argv:
        value = argument
        for token, replacement in substitutions.items():
            value = value.replace(token, replacement)
        if "$BUNDLE$" in value or "$OUT$" in value or "$TOOLCHAIN$" in value:
            raise ValueError(f"Unexpanded command token: {argument}")
        expanded.append(value)
    return expanded


def add_prefix_maps(argv: list[str], roots: list[Path]) -> list[str]:
    mapped = [argv[0]]
    for root in roots:
        value = root.resolve().as_posix()
        mapped.extend(
            (
                f"-fmacro-prefix-map={value}=.",
                f"-fdebug-prefix-map={value}=.",
            )
        )
    mapped.extend(argv[1:])
    return mapped


def validate_toolchain(toolchain: Path, manifest: dict[str, Any]) -> Path:
    toolchain = toolchain.resolve()
    if not toolchain.is_dir():
        raise FileNotFoundError(toolchain)
    expected = manifest["toolchain"]["compiler"]
    compiler_rel = safe_package_path(expected["path"])
    compiler = toolchain / PurePosixPath(compiler_rel)
    if not compiler.is_file():
        raise FileNotFoundError(compiler)
    if sha256(compiler) != expected["sha256"]:
        raise ValueError("ARM GCC hash does not match the packaged Xilinx 2026.1 host snapshot")
    for record in manifest["toolchain"].get("linker_runtime_files", []):
        relative = safe_package_path(record["path"])
        path = toolchain / PurePosixPath(relative)
        if not path.is_file():
            raise FileNotFoundError(path)
        if sha256(path) != record["sha256"]:
            raise ValueError(f"ARM runtime input hash mismatch: {relative}")
    return compiler


def acquire_build_mutex():
    if os.name != "nt":
        raise RuntimeError("--build requires Windows for the firmware build mutex")
    return acquire_named_mutex(r"Local\Z100_ARM_GCC_Build")


def acquire_vendor_mutex():
    if os.name != "nt":
        raise RuntimeError("Bootgen requires Windows for the shared vendor-tool mutex")
    return acquire_named_mutex(r"Local\Z100_Vivado_Implementation")


def acquire_named_mutex(name: str):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
    kernel32.ReleaseMutex.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle(handle)
        raise RuntimeError(f"The {name} mutex is already held")
    return kernel32, handle


def assert_vendor_idle() -> None:
    completed = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError("Could not verify that the Xilinx/board tool processes are idle")
    active = set()
    for row in csv.reader(completed.stdout.splitlines()):
        if row and row[0].casefold() in BUSY_PROCESS_NAMES:
            active.add(row[0])
    if active:
        raise RuntimeError("Xilinx/board tool process is active: " + ", ".join(sorted(active)))


def run_build(
    bundle: Path,
    output: Path,
    toolchain: Path,
    manifest: dict[str, Any],
    cmake_path: Path | None = None,
    make_program_path: Path | None = None,
    generator_name: str | None = None,
    jobs: int = 4,
) -> int:
    output = output.resolve()
    project_root = bundle.parent.parent.resolve()
    if output == project_root or project_root in output.parents:
        raise ValueError("Build output must be outside the project package")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"Build output parent does not exist: {output.parent}")
    if output.exists():
        raise FileExistsError("Build output directory must be new")

    compiler = validate_toolchain(toolchain, manifest)
    kernel32, mutex = acquire_build_mutex()
    try:
        output.mkdir(parents=True, exist_ok=False)
        (output / "obj").mkdir(exist_ok=True)
        bsp_result = rebuild_bsp_sources.build_platform_bsp(
            toolchain=toolchain,
            spec_file=bundle / PurePosixPath(manifest["link"]["specs"]),
            output=output,
            cmake_path=cmake_path,
            make_program_path=make_program_path,
            generator_name=generator_name,
            jobs=jobs,
        )
        result = {
            "status": "BUILDING_FIRMWARE_FROM_SOURCE",
            "reference_elf_sha256": manifest["reference_elf"]["sha256"],
            "bsp": bsp_result,
            "board_access": False,
            "commands_completed": 0,
        }
        result_path = output / "result.json"
        for entry in manifest["objects"]:
            command = read_json(bundle / PurePosixPath(entry["command"]))
            argv = expand_tokens(command["argv"], bundle, output, toolchain.resolve())
            if Path(argv[0]).resolve() != compiler.resolve():
                raise ValueError("Compile command does not invoke the verified ARM GCC")
            argv = add_prefix_maps(argv, [project_root])
            completed = subprocess.run(argv, cwd=bundle, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
            (output / "obj" / f"{entry['object']}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
            result["commands_completed"] += 1
            if completed.returncode != 0:
                result.update(status="FAILED_COMPILE", failed_object=entry["object"], returncode=completed.returncode)
                write_json(result_path, result)
                return 2

        link = read_json(bundle / PurePosixPath(manifest["link"]["command_file"]))
        argv = expand_tokens(link["argv"], bundle, output, toolchain.resolve())
        if Path(argv[0]).resolve() != compiler.resolve():
            raise ValueError("Link command does not invoke the verified ARM GCC")
        completed = subprocess.run(argv, cwd=bundle, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (output / "link.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        result["commands_completed"] += 1
        if completed.returncode != 0:
            result.update(status="FAILED_LINK", returncode=completed.returncode)
            write_json(result_path, result)
            return 2

        elf = output / "native_board_pool.elf"
        if not elf.is_file():
            raise RuntimeError("ARM GCC exited successfully without producing the ELF")
        result.update(
            status="BUILT_ARM_ELF_BOARD_PENDING",
            elf="native_board_pool.elf",
            elf_bytes=elf.stat().st_size,
            elf_sha256=sha256(elf),
            matches_reference_elf=sha256(elf) == manifest["reference_elf"]["sha256"],
            board_access=False,
        )
        write_json(result_path, result)
        print(f"BUILD_COMPLETE elf_sha256={result['elf_sha256']} board_access=false")
        return 0
    finally:
        kernel32.ReleaseMutex(mutex)
        kernel32.CloseHandle(mutex)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify package files only; this is the default")
    mode.add_argument("--build", action="store_true", help="explicitly invoke ARM GCC and link into an external directory")
    parser.add_argument("--bundle-dir", type=Path, default=Path(__file__).resolve().parent / "firmware_portable")
    parser.add_argument("--toolchain", type=Path, help="Xilinx 2026.1 gcc-arm-none-eabi installation root")
    parser.add_argument("--cmake", type=Path, help="Vitis-bundled CMake executable; auto-detected by default")
    parser.add_argument("--make-program", type=Path, help="nmake, mingw32-make, or ninja executable")
    parser.add_argument("--generator", help="CMake generator for the selected build tool")
    parser.add_argument("--jobs", type=int, default=4, help="parallel CMake jobs (default: 4)")
    parser.add_argument("--output-dir", type=Path, help="new external directory for ARM objects, map, ELF, and logs")
    args = parser.parse_args()

    bundle = args.bundle_dir.resolve()
    manifest = load_and_check(bundle)
    if not args.build:
        if args.cmake or args.make_program or args.generator or args.jobs != 4:
            parser.error("--cmake, --make-program, --generator, and --jobs are only valid with --build")
        print(
            "CHECK_PASS "
            f"sources={manifest['recorded_source_counts']['total']} "
            f"objects={manifest['compile_object_count']} "
            f"bytes={manifest['packaged_bytes']} "
            f"reference_elf_sha256={manifest['reference_elf']['sha256']}"
        )
        return 0
    if args.toolchain is None or args.output_dir is None:
        parser.error("--build requires both --toolchain and --output-dir")
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return run_build(
        bundle,
        args.output_dir,
        args.toolchain,
        manifest,
        args.cmake,
        args.make_program,
        args.generator,
        args.jobs,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
