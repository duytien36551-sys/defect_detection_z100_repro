#!/usr/bin/env python3
"""Verify or explicitly rebuild the pinned Z100 SD network-fix image."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

sys.dont_write_bytecode = True

import rebuild_firmware
import rebuild_bsp_sources


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIX_ROOT = PROJECT_ROOT / "board" / "sd_network_fix_v1"
BUNDLE = PROJECT_ROOT / "build" / "firmware_portable"
SD_BUILD = PROJECT_ROOT / "build" / "sd_boot"
FIX_MANIFEST_SHA256 = "0964b5923ded02115d8d8c3c8d4832a128dc658aa8a7709f433becd70d73fddb"
BIF_SHA256 = "c31d8ea88ab736fcca4beccac5f0b601170815298ed62a1c42774fb41589d397"
OBJECT_COUNT = 90
PATCH_OBJECTS = {
    "29_v8_service.o": "v8_service.c",
    "30_native_graph_service_v2.o": "native_graph_service_v2.c",
    "36_native_graph_lwip_v2.o": "native_graph_lwip_v2.c",
    "69_xemacpsif_physpeed.o": "xemacpsif_physpeed.c",
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


def verify_file(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {label}: {path}")
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch: {path}")


def prepare_compile_argv(
    command: dict[str, Any], bundle: Path, output: Path, toolchain: Path, source: Path
) -> list[str]:
    argv = list(command["argv"])
    argv[1:1] = ["-I", str(FIX_ROOT / "src")]
    source_index = argv.index("-c") + 1
    object_index = argv.index("-o") + 1
    argv[source_index] = str(source)
    argv[object_index] = str(output / "obj" / command["object"])
    return rebuild_firmware.expand_tokens(argv, bundle, output, toolchain)


def check_patch_compile_argv_contract(portable_manifest: dict[str, Any]) -> None:
    entries = {
        entry["object"]: entry
        for entry in portable_manifest.get("objects", [])
        if entry.get("object") in PATCH_OBJECTS
    }
    if set(entries) != set(PATCH_OBJECTS):
        raise ValueError("Portable build bundle is missing a patched source command")

    bundle = BUNDLE.resolve()
    output = (SD_BUILD / "argv_contract_output").resolve()
    toolchain = (SD_BUILD / "argv_contract_toolchain").resolve()
    patch_include = str(FIX_ROOT / "src")
    for object_name, source_name in PATCH_OBJECTS.items():
        entry = entries[object_name]
        command = read_json(bundle / PurePosixPath(entry["command"]))
        if (
            command.get("object") != object_name
            or PurePosixPath(command.get("source", "")).name != source_name
        ):
            raise ValueError(f"Portable compile command identity mismatch for {object_name}")

        argv = prepare_compile_argv(
            command,
            bundle,
            output,
            toolchain,
            FIX_ROOT / "src" / source_name,
        )
        include_positions = [
            index for index, value in enumerate(argv[:-1]) if value in {"-I", "-isystem"}
        ]
        if len(include_positions) < 2 or include_positions[0] != 1:
            raise ValueError(f"Patched include directory is not first for {object_name}")
        if argv[1:3] != ["-I", patch_include]:
            raise ValueError(f"Patched include directory changed for {object_name}")

        source_index = argv.index("-c") + 1
        object_index = argv.index("-o") + 1
        if Path(argv[source_index]).resolve() != (FIX_ROOT / "src" / source_name).resolve():
            raise ValueError(f"Patched source mapping changed for {object_name}")
        if Path(argv[object_index]).resolve() != (output / "obj" / object_name).resolve():
            raise ValueError(f"Patched object mapping changed for {object_name}")


def package_input_path(raw_path: str) -> Path:
    name = PureWindowsPath(raw_path).name
    if name.endswith(".command.json"):
        raise ValueError("Command JSON is provenance only and has no package input path")
    if name.endswith(".o"):
        raise ValueError("Baseline objects are rebuilt from the packaged source commands")
    if name == "xilinx.spec":
        return BUNDLE / "specs" / name
    if name == "native_reserved.ld":
        return BUNDLE / "linker" / name
    if name in {"libxilstandalone.a", "libxiltimer.a", "libxil.a"}:
        raise ValueError("BSP libraries are rebuilt from build/bsp_snapshot")
    if name == "fsbl.elf":
        return PROJECT_ROOT / "board" / "artifacts" / name
    if name == "z100_platform.bit":
        return PROJECT_ROOT / "board" / "artifacts" / name
    if name == "boot.bif":
        return SD_BUILD / name
    raise ValueError(f"Unmapped pinned input: {raw_path}")


def check_package() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fix_manifest_path = FIX_ROOT / "build_manifest.json"
    verify_file(fix_manifest_path, FIX_MANIFEST_SHA256, "SD fix manifest")
    fix_manifest = read_json(fix_manifest_path)
    portable_manifest = rebuild_firmware.load_and_check(BUNDLE)
    check_patch_compile_argv_contract(portable_manifest)

    objects = portable_manifest.get("objects", [])
    if len(objects) != OBJECT_COUNT:
        raise ValueError("Portable firmware bundle must contain 90 source compile commands")
    if {entry["object"] for entry in objects} != {
        PureWindowsPath(path).name
        for path in fix_manifest.get("input_sha256", {})
        if PureWindowsPath(path).name.endswith(".o")
    }:
        raise ValueError("Portable source object list differs from the historical 90-object identity")
    if fix_manifest.get("baseline_elf_sha256") != portable_manifest["reference_elf"]["sha256"]:
        raise ValueError("SD fix baseline ELF does not match the portable firmware reference")

    sources = fix_manifest.get("sources", {})
    if len(sources) != 5:
        raise ValueError("Expected four patched C sources and one patched header")
    for name, expected in sources.items():
        verify_file(FIX_ROOT / "src" / name, expected, f"Patched source {name}")

    commands = fix_manifest.get("commands", [])
    if len(commands) != len(PATCH_OBJECTS):
        raise ValueError("Expected four patched object compile records")
    command_objects: dict[str, str] = {}
    for record in commands:
        object_name = record.get("object")
        source_name = record.get("source")
        if object_name not in PATCH_OBJECTS or PATCH_OBJECTS[object_name] != source_name:
            raise ValueError(f"Unexpected patched compile record: {record}")
        argv = record.get("argv", [])
        try:
            source_arg = PureWindowsPath(argv[argv.index("-c") + 1]).name
            object_arg = PureWindowsPath(argv[argv.index("-o") + 1]).name
        except (ValueError, IndexError) as error:
            raise ValueError(f"Incomplete compile command for {object_name}") from error
        if (source_arg, object_arg) != (source_name, object_name):
            raise ValueError(f"Compile command identity mismatch for {object_name}")
        command_objects[object_name] = source_name
    if command_objects != PATCH_OBJECTS:
        raise ValueError("Patched object list differs from the reviewed fix")

    input_hashes = fix_manifest.get("input_sha256", {})
    legacy_object_records = 0
    legacy_library_records = 0
    omitted_command_records = 0
    for raw_path, expected in input_hashes.items():
        name = PureWindowsPath(raw_path).name
        if name.endswith(".o"):
            legacy_object_records += 1
            continue
        if name.endswith(".a"):
            legacy_library_records += 1
            continue
        if name.endswith(".command.json"):
            omitted_command_records += 1
            continue
        verify_file(package_input_path(raw_path), expected, f"Pinned input {name}")
    if legacy_object_records != OBJECT_COUNT:
        raise ValueError(f"Expected 90 historical object records, found {legacy_object_records}")
    if legacy_library_records != 3:
        raise ValueError(f"Expected three historical BSP library records, found {legacy_library_records}")
    if omitted_command_records != len(PATCH_OBJECTS):
        raise ValueError("Expected four omitted legacy command sidecars; compile vectors are retained in build_manifest.json")

    bif = SD_BUILD / "boot.bif"
    verify_file(bif, BIF_SHA256, "Bootgen BIF")
    verification = read_json(FIX_ROOT / "evidence" / "final_verification.json")
    if verification.get("boot_header_and_partition_checksums") != "PASS":
        raise ValueError("Bootgen header and partition verification is not recorded as passing")
    if verification.get("boot_app_segments_match_tested_elf") != "PASS":
        raise ValueError("Recorded BOOT.BIN application segment does not match the tested ELF")

    tested_elf = FIX_ROOT / "native_board_pool.elf"
    tested_boot = FIX_ROOT / "boot.bin"
    verify_file(tested_elf, verification["elf_sha256"], "Tested network-fix ELF")
    verify_file(tested_boot, verification["boot_sha256"], "Tested network-fix BOOT.BIN")
    if tested_boot.stat().st_size != verification["boot_bytes"]:
        raise ValueError("Tested BOOT.BIN size differs from its verification record")
    if sha256(PROJECT_ROOT / "board" / "artifacts" / "fsbl.elf") != verification["fsbl_sha256"]:
        raise ValueError("Packaged FSBL differs from the SD fix verification record")
    if sha256(PROJECT_ROOT / "board" / "artifacts" / "z100_platform.bit") != verification["bit_sha256"]:
        raise ValueError("Packaged bitstream differs from the SD fix verification record")

    return fix_manifest, portable_manifest, verification


def compile_argv(
    command: dict[str, Any], bundle: Path, output: Path, toolchain: Path, source: Path
) -> list[str]:
    expanded = prepare_compile_argv(command, bundle, output, toolchain, source)
    compiler = rebuild_firmware.validate_toolchain(toolchain, read_json(bundle / "manifest.json"))
    if Path(expanded[0]).resolve() != compiler.resolve():
        raise ValueError("Compile command does not use the verified ARM GCC")
    return rebuild_firmware.add_prefix_maps(expanded, [PROJECT_ROOT])


def write_result(output: Path, result: dict[str, Any]) -> None:
    rebuild_firmware.write_json(output / "result.json", result)


def run_bootgen(output: Path, bootgen: Path, result: dict[str, Any]) -> int:
    bootgen = bootgen.resolve()
    if not bootgen.is_file():
        raise FileNotFoundError(f"Bootgen executable not found: {bootgen}")
    verify_file(output / "native_board_pool.elf", result["elf_sha256"], "Rebuilt ELF")
    verify_file(output / "fsbl.elf", result["selected_fsbl"]["sha256"], "Selected FSBL")
    verify_file(
        output / "z100_platform.bit",
        result["selected_bitstream"]["sha256"],
        "Selected bitstream",
    )
    verify_file(output / "boot.bif", result["bif_sha256"], "Bootgen BIF")
    if result.get("status") in {
        "FAILED_BOOTGEN",
        "BOOTGEN_PENDING_LOCK_BUSY",
        "BOOTGEN_PENDING_TOOL_BUSY",
        "BOOTGEN_COMPLETE_BOARD_PENDING",
    }:
        previous_attempt = {"status": result["status"]}
        for key in (
            "bootgen",
            "bootgen_sha256",
            "bootgen_command",
            "bootgen_exit_code",
            "returncode",
            "bootgen_error",
            "error",
        ):
            if key in result:
                previous_attempt[key] = result[key]
        result.setdefault("bootgen_attempt_history", []).append(previous_attempt)

    result["bootgen"] = str(bootgen)
    result["bootgen_sha256"] = sha256(bootgen)
    result.pop("returncode", None)
    result.pop("bootgen_exit_code", None)
    result.pop("bootgen_command", None)
    result.pop("bootgen_attempt", None)
    result.pop("bootgen_error", None)
    result.pop("error", None)

    try:
        vendor_kernel32, vendor_mutex = rebuild_firmware.acquire_vendor_mutex()
    except RuntimeError as error:
        result.update(
            status="BOOTGEN_PENDING_LOCK_BUSY",
            bootgen_error=str(error),
            board_access=False,
            sd_write=False,
        )
        write_result(output, result)
        print(json.dumps(result, indent=2))
        return 3

    try:
        try:
            rebuild_firmware.assert_vendor_idle()
        except RuntimeError as error:
            result.update(
                status="BOOTGEN_PENDING_TOOL_BUSY",
                bootgen_error=str(error),
                board_access=False,
                sd_write=False,
            )
            write_result(output, result)
            print(json.dumps(result, indent=2))
            return 3

        bootgen_args = ["-arch", "zynq", "-image", "boot.bif", "-o", "BOOT.BIN", "-w", "on"]
        bootgen_command = (
            ["cmd.exe", "/d", "/c", "call " + subprocess.list2cmdline([str(bootgen), *bootgen_args])]
            if bootgen.suffix.casefold() in {".bat", ".cmd"}
            else [str(bootgen), *bootgen_args]
        )
        generated = subprocess.run(
            bootgen_command,
            cwd=output,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        (output / "bootgen.log").write_text(generated.stdout + generated.stderr, encoding="utf-8")
        result["commands_completed"] += 1
        result["bootgen_exit_code"] = generated.returncode
        result["bootgen_command"] = bootgen_command
        result["bootgen_attempt"] = {
            "tool": result["bootgen"],
            "sha256": result["bootgen_sha256"],
            "command": bootgen_command,
            "exit_code": generated.returncode,
        }
        if generated.returncode != 0:
            result.update(
                status="FAILED_BOOTGEN",
                returncode=generated.returncode,
            )
            write_result(output, result)
            return 2

        boot = output / "BOOT.BIN"
        if not boot.is_file():
            result.update(
                status="FAILED_BOOTGEN",
                returncode=generated.returncode,
                error="Bootgen produced no BOOT.BIN",
            )
            write_result(output, result)
            return 2
        boot_hash = sha256(boot)
        result.update(
            status="BOOTGEN_COMPLETE_BOARD_PENDING",
            boot_bytes=boot.stat().st_size,
            boot_sha256=boot_hash,
            boot_byte_identical_to_tested=boot_hash == result["expected_boot_sha256"],
            returncode=generated.returncode,
            fsbl_sha256=sha256(output / "fsbl.elf"),
            bit_sha256=sha256(output / "z100_platform.bit"),
            bif_sha256=sha256(output / "boot.bif"),
            board_access=False,
            sd_write=False,
        )
        write_result(output, result)
        print(json.dumps(result, indent=2))
        return 0
    finally:
        vendor_kernel32.ReleaseMutex(vendor_mutex)
        vendor_kernel32.CloseHandle(vendor_mutex)


REUSABLE_BOOTGEN_STATUSES = {
    "BOOTGEN_COMPLETE_BOARD_PENDING",
    "ELF_REBUILT_BOOTGEN_DEFERRED",
    "BOOTGEN_PENDING_LOCK_BUSY",
    "BOOTGEN_PENDING_TOOL_BUSY",
    "FAILED_BOOTGEN",
    "ELF_REUSED_BOOTGEN_READY",
}


def prepare_reused_bootgen_build(
    reuse_build_dir: Path, bitstream_input: Path, output_dir: Path
) -> dict[str, Any]:
    source = reuse_build_dir.resolve()
    output = output_dir.resolve()
    package_root = PROJECT_ROOT.resolve()
    for label, path in (("Source build", source), ("Build output", output)):
        if path == package_root or package_root in path.parents:
            raise ValueError(f"{label} must be outside the project package")
    if source == output or source in output.parents:
        raise ValueError("Reused build output must be a separate directory")
    if not source.is_dir():
        raise FileNotFoundError(f"Reused build directory does not exist: {source}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"Build output parent does not exist: {output.parent}")
    if output.exists():
        raise FileExistsError("Build output directory must be new")

    source_result_path = source / "result.json"
    if not source_result_path.is_file():
        raise FileNotFoundError(f"Missing source build result: {source_result_path}")
    source_result = read_json(source_result_path)
    if source_result.get("status") not in REUSABLE_BOOTGEN_STATUSES:
        raise ValueError(f"Source build is not reusable: {source_result.get('status')}")

    source_elf = source / "native_board_pool.elf"
    selected_fsbl = source_result.get("selected_fsbl", {})
    source_fsbl = source / "fsbl.elf"
    source_bif = source / "boot.bif"
    bitstream = bitstream_input.resolve()
    verify_file(source_elf, source_result["elf_sha256"], "Reused ELF")
    verify_file(source_fsbl, selected_fsbl["sha256"], "Reused FSBL")
    verify_file(source_bif, source_result["bif_sha256"], "Reused Bootgen BIF")
    verify_file(
        source / "z100_platform.bit",
        source_result["selected_bitstream"]["sha256"],
        "Original selected bitstream",
    )
    if not bitstream.is_file():
        raise FileNotFoundError(f"Selected bitstream not found: {bitstream}")
    bitstream_sha256 = sha256(bitstream)
    bif_text = source_bif.read_text(encoding="utf-8")
    for required_input in ("fsbl.elf", "z100_platform.bit", "native_board_pool.elf"):
        if required_input not in bif_text:
            raise ValueError(f"Bootgen BIF does not reference {required_input}")

    source_result_sha256 = sha256(source_result_path)
    source_bitstream_sha256 = source_result["selected_bitstream"]["sha256"]
    packaged_bitstream_sha256 = sha256(PROJECT_ROOT / "board" / "artifacts" / "z100_platform.bit")
    output.mkdir()
    try:
        shutil.copy2(source_elf, output / "native_board_pool.elf")
        shutil.copy2(source_fsbl, output / "fsbl.elf")
        shutil.copy2(source_bif, output / "boot.bif")
        shutil.copy2(bitstream, output / "z100_platform.bit")
        verify_file(output / "native_board_pool.elf", source_result["elf_sha256"], "Copied ELF")
        verify_file(output / "fsbl.elf", selected_fsbl["sha256"], "Copied FSBL")
        verify_file(output / "boot.bif", source_result["bif_sha256"], "Copied Bootgen BIF")
        verify_file(output / "z100_platform.bit", bitstream_sha256, "Copied bitstream")
        result = dict(source_result)
        result["source_build_bootgen_attempt_history"] = source_result.get(
            "bootgen_attempt_history", []
        )
        result["bootgen_attempt_history"] = []
        result["reused_build"] = {
            "directory": str(source),
            "result_json_sha256": source_result_sha256,
            "status": source_result["status"],
            "elf_sha256": source_result["elf_sha256"],
            "selected_fsbl_sha256": selected_fsbl["sha256"],
            "bif_sha256": source_result["bif_sha256"],
            "replaced_bitstream_sha256": source_bitstream_sha256,
        }
        result["selected_fsbl"] = {
            "source": str(output / "fsbl.elf"),
            "sha256": selected_fsbl["sha256"],
            "matches_source_built_fsbl": selected_fsbl.get("matches_source_built_fsbl", False),
        }
        result["selected_bitstream"] = {
            "source": str(bitstream),
            "output": str(output / "z100_platform.bit"),
            "sha256": bitstream_sha256,
            "matches_packaged_reference": bitstream_sha256 == packaged_bitstream_sha256,
        }
        result["bit_sha256"] = bitstream_sha256
        result["status"] = "ELF_REUSED_BOOTGEN_READY"
        result["board_access"] = False
        result["sd_write"] = False
        for key in (
            "boot_bytes",
            "boot_sha256",
            "boot_byte_identical_to_tested",
            "bootgen",
            "bootgen_sha256",
            "bootgen_exit_code",
            "bootgen_command",
            "bootgen_attempt",
            "bootgen_error",
            "returncode",
            "error",
        ):
            result.pop(key, None)
        write_result(output, result)
    except Exception:
        shutil.rmtree(output)
        raise
    return result


def run_bootgen_only(
    bootgen: Path,
    output_dir: Path,
    reuse_build_dir: Path | None = None,
    bitstream_input: Path | None = None,
) -> int:
    if reuse_build_dir is not None:
        if bitstream_input is None:
            raise ValueError("--reuse-build requires --bitstream")
        output = output_dir.resolve()
        result = prepare_reused_bootgen_build(reuse_build_dir, bitstream_input, output)
        return run_bootgen(output, bootgen, result)

    if bitstream_input is not None:
        raise ValueError("--bitstream with --bootgen-only requires --reuse-build")
    output = output_dir.resolve()
    if PROJECT_ROOT.resolve() == output or PROJECT_ROOT.resolve() in output.parents:
        raise ValueError("Build output must be outside the project package")
    if not output.is_dir():
        raise FileNotFoundError(f"Build output directory does not exist: {output}")
    result_path = output / "result.json"
    if not result_path.is_file():
        raise FileNotFoundError(f"Missing deferred build result: {result_path}")
    result = read_json(result_path)
    pending_statuses = {
        "ELF_REBUILT_BOOTGEN_DEFERRED",
        "BOOTGEN_PENDING_LOCK_BUSY",
        "BOOTGEN_PENDING_TOOL_BUSY",
        "FAILED_BOOTGEN",
    }
    if result.get("status") not in pending_statuses:
        raise ValueError(f"Build result is not waiting for Bootgen: {result.get('status')}")
    return run_bootgen(output, bootgen, result)


def run_build(
    toolchain: Path,
    bootgen: Path,
    output_dir: Path,
    cmake_path: Path | None = None,
    make_program_path: Path | None = None,
    generator_name: str | None = None,
    jobs: int = 4,
    fsbl_input: Path | None = None,
    bitstream_input: Path | None = None,
    defer_bootgen: bool = False,
) -> int:
    fix_manifest, portable_manifest, verification = check_package()
    bundle = BUNDLE.resolve()
    toolchain = toolchain.resolve()
    bootgen = bootgen.resolve()
    output = output_dir.resolve()
    if PROJECT_ROOT.resolve() == output or PROJECT_ROOT.resolve() in output.parents:
        raise ValueError("Build output must be outside the project package")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"Build output parent does not exist: {output.parent}")
    if output.exists():
        raise FileExistsError("Build output directory must be new")
    if not bootgen.is_file():
        raise FileNotFoundError(f"Bootgen executable not found: {bootgen}")
    if fsbl_input is not None and not fsbl_input.is_file():
        raise FileNotFoundError(f"FSBL input not found: {fsbl_input}")
    if bitstream_input is not None and not bitstream_input.is_file():
        raise FileNotFoundError(f"Bitstream input not found: {bitstream_input}")
    compiler = rebuild_firmware.validate_toolchain(toolchain, portable_manifest)
    kernel32, mutex = rebuild_firmware.acquire_build_mutex()
    try:
        output.mkdir()
        (output / "obj").mkdir()

        bsp_result = rebuild_bsp_sources.build_platform_bsp(
            toolchain=toolchain,
            spec_file=BUNDLE / PurePosixPath(portable_manifest["link"]["specs"]),
            output=output,
            cmake_path=cmake_path,
            make_program_path=make_program_path,
            generator_name=generator_name,
            jobs=jobs,
        )
        fsbl_result = rebuild_bsp_sources.build_fsbl(
            toolchain=toolchain,
            spec_file=BUNDLE / PurePosixPath(portable_manifest["link"]["specs"]),
            output=output,
            cmake_path=cmake_path,
            make_program_path=make_program_path,
            generator_name=generator_name,
            jobs=jobs,
        )
        result: dict[str, Any] = {
            "status": "BUILDING_FIRMWARE_AND_FSBL_FROM_SOURCE",
            "baseline_elf_sha256": fix_manifest["baseline_elf_sha256"],
            "expected_elf_sha256": verification["elf_sha256"],
            "expected_boot_sha256": verification["boot_sha256"],
            "bsp": bsp_result,
            "fsbl_build": fsbl_result,
            "changed_objects": sorted(PATCH_OBJECTS),
            "source_object_count": OBJECT_COUNT,
            "legacy_baseline_objects_required": False,
            "commands_completed": 0,
            "compiler": str(compiler),
            "bootgen": str(bootgen),
            "board_access": False,
            "sd_write": False,
        }
        write_result(output, result)

        for entry in portable_manifest["objects"]:
            object_name = entry["object"]
            command = read_json(bundle / PurePosixPath(entry["command"]))
            if object_name in PATCH_OBJECTS:
                source = FIX_ROOT / "src" / PATCH_OBJECTS[object_name]
                argv = compile_argv(command, bundle, output, toolchain, source)
            else:
                argv = rebuild_firmware.expand_tokens(
                    command["argv"], bundle, output, toolchain
                )
                if Path(argv[0]).resolve() != compiler.resolve():
                    raise ValueError(f"Compile command does not use verified ARM GCC: {object_name}")
                argv = rebuild_firmware.add_prefix_maps(argv, [PROJECT_ROOT])
            completed = subprocess.run(
                argv,
                cwd=bundle,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            (output / f"compile_{object_name}.log").write_text(
                completed.stdout + completed.stderr, encoding="utf-8"
            )
            result["commands_completed"] += 1
            if completed.returncode != 0:
                result.update(
                    status="FAILED_COMPILE",
                    failed_object=object_name,
                    returncode=completed.returncode,
                )
                write_result(output, result)
                return 2

        link_record = read_json(bundle / PurePosixPath(portable_manifest["link"]["command_file"]))
        link_argv = rebuild_firmware.expand_tokens(link_record["argv"], bundle, output, toolchain)
        if Path(link_argv[0]).resolve() != compiler.resolve():
            raise ValueError("Link command does not use the verified ARM GCC")
        linked = subprocess.run(
            link_argv,
            cwd=bundle,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        (output / "link.log").write_text(linked.stdout + linked.stderr, encoding="utf-8")
        result["commands_completed"] += 1
        if linked.returncode != 0:
            result.update(status="FAILED_LINK", returncode=linked.returncode)
            write_result(output, result)
            return 2

        elf = output / "native_board_pool.elf"
        if not elf.is_file():
            raise RuntimeError("ARM GCC exited successfully without producing an ELF")
        elf_hash = sha256(elf)
        result.update(
            status="ELF_REBUILT",
            elf_bytes=elf.stat().st_size,
            elf_sha256=elf_hash,
            elf_byte_identical_to_tested=elf_hash == verification["elf_sha256"],
            compiled_objects=[
                {"object": entry["object"], "sha256": sha256(output / "obj" / entry["object"])}
                for entry in portable_manifest["objects"]
            ],
            board_access=False,
        )
        write_result(output, result)

    finally:
        kernel32.ReleaseMutex(mutex)
        kernel32.CloseHandle(mutex)

    built_fsbl = output / "fsbl" / "fsbl.elf"
    selected_fsbl = fsbl_input.resolve() if fsbl_input else built_fsbl
    selected_bit = (
        bitstream_input.resolve()
        if bitstream_input
        else PROJECT_ROOT / "board" / "artifacts" / "z100_platform.bit"
    )
    if not selected_fsbl.is_file():
        raise FileNotFoundError(f"FSBL input not found: {selected_fsbl}")
    if not selected_bit.is_file():
        raise FileNotFoundError(f"Bitstream input not found: {selected_bit}")
    if selected_fsbl.resolve() != (output / "fsbl.elf").resolve():
        shutil.copy2(selected_fsbl, output / "fsbl.elf")
    shutil.copy2(selected_bit, output / "z100_platform.bit")
    shutil.copy2(SD_BUILD / "boot.bif", output / "boot.bif")
    result.update(
        status="ELF_REBUILT_BOOTGEN_DEFERRED",
        selected_fsbl={
            "source": str(selected_fsbl),
            "sha256": sha256(output / "fsbl.elf"),
            "matches_source_built_fsbl": sha256(output / "fsbl.elf") == fsbl_result["fsbl"]["sha256"],
        },
        selected_bitstream={
            "source": str(selected_bit),
            "sha256": sha256(output / "z100_platform.bit"),
            "matches_packaged_reference": sha256(output / "z100_platform.bit") == verification["bit_sha256"],
        },
        bif_sha256=sha256(output / "boot.bif"),
    )
    write_result(output, result)
    if defer_bootgen:
        print(json.dumps(result, indent=2))
        return 0
    return run_bootgen(output, bootgen, result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify package hashes only; this is the default")
    mode.add_argument("--build", action="store_true", help="build BSP, FSBL, 90 source objects, ELF, and BOOT.BIN")
    mode.add_argument("--bootgen-only", action="store_true", help="run Bootgen from an external build")
    parser.add_argument("--defer-bootgen", action="store_true", help="stop after ELF and prepared Bootgen inputs")
    parser.add_argument("--toolchain", type=Path, help="Xilinx 2026.1 ARM GCC installation root")
    parser.add_argument("--cmake", type=Path, help="Vitis-bundled CMake executable; auto-detected by default")
    parser.add_argument("--make-program", type=Path, help="nmake, mingw32-make, or ninja executable")
    parser.add_argument("--generator", help="CMake generator for the selected build tool")
    parser.add_argument("--jobs", type=int, default=4, help="parallel CMake jobs (default: 4)")
    parser.add_argument("--bootgen", type=Path, help="Xilinx 2026.1 bootgen executable or batch file")
    parser.add_argument("--fsbl", type=Path, help="optional FSBL ELF to use in BOOT.BIN; defaults to the source-built FSBL")
    parser.add_argument("--bitstream", type=Path, help="optional bitstream to use in BOOT.BIN; defaults to the packaged reference bit")
    parser.add_argument("--reuse-build", type=Path, help="verified external ELF/FSBL/BIF build to reuse with --bootgen-only")
    parser.add_argument("--output-dir", type=Path, help="external output directory; new for --build or --bootgen-only --reuse-build")
    args = parser.parse_args()

    if args.bootgen_only:
        if args.bootgen is None or args.output_dir is None:
            parser.error("--bootgen-only requires --bootgen and --output-dir")
        if (
            args.toolchain or args.cmake or args.make_program or args.generator or args.fsbl
            or args.defer_bootgen or args.jobs != 4
        ):
            parser.error("compile options are not valid with --bootgen-only")
        if (args.reuse_build is None) != (args.bitstream is None):
            parser.error("--reuse-build and --bitstream must be supplied together")
        return run_bootgen_only(
            args.bootgen,
            args.output_dir,
            args.reuse_build,
            args.bitstream,
        )

    if not args.build:
        if args.toolchain or args.bootgen or args.output_dir or args.cmake or args.make_program or args.generator or args.fsbl or args.bitstream or args.reuse_build or args.jobs != 4 or args.defer_bootgen:
            parser.error("build input options are only valid with --build")
        fix_manifest, portable_manifest, verification = check_package()
        print(
            json.dumps(
                {
                    "status": "PASS_SD_BOOT_REBUILD_PACKAGE",
                    "fix_manifest_sha256": FIX_MANIFEST_SHA256,
                    "historical_object_records": OBJECT_COUNT,
                    "baseline_source_commands_checked": OBJECT_COUNT,
                    "baseline_object_files_required": False,
                    "patched_sources_checked": len(fix_manifest["sources"]),
                    "patched_argv_contract_checked": True,
                    "portable_source_objects_checked": portable_manifest["compile_object_count"],
                    "tested_elf_sha256": verification["elf_sha256"],
                    "tested_boot_sha256": verification["boot_sha256"],
                    "build_commands_executed": False,
                    "compiler_executed": False,
                    "bootgen_executed": False,
                    "board_access": False,
                    "sd_write": False,
                },
                indent=2,
            )
        )
        return 0

    if args.reuse_build is not None:
        parser.error("--reuse-build is only valid with --bootgen-only")
    if args.toolchain is None or args.bootgen is None or args.output_dir is None:
        parser.error("--build requires --toolchain, --bootgen, and --output-dir")
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return run_build(
        args.toolchain,
        args.bootgen,
        args.output_dir,
        args.cmake,
        args.make_program,
        args.generator,
        args.jobs,
        args.fsbl,
        args.bitstream,
        args.defer_bootgen,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
