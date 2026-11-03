#!/usr/bin/env python3
"""Validate and rebuild the packaged Zynq BSP and FSBL source snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any


BUILD_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BUILD_ROOT.parent
SNAPSHOT = BUILD_ROOT / "bsp_snapshot"
PLATFORM_BSP = SNAPSHOT / "ps7_cortexa9_0" / "dom" / "bsp"
FSBL_SOURCE = SNAPSHOT / "zynq_fsbl"
MANIFEST_SCHEMA = "z100_bsp_fsbl_source_snapshot_v1"
PLATFORM_LIBRARIES = ("libxil.a", "libxilstandalone.a", "libxiltimer.a")
FSBL_LIBRARIES = (
    "libxil.a",
    "libxilstandalone.a",
    "libxiltimer.a",
    "libxilffs.a",
)
RSA_DISABLED_BUILD_GUARD = """# The packaged FSBL source snapshot omits the SDK-only librsa.a.
foreach(_rsa_definition IN LISTS USER_COMPILE_DEFINITIONS)
    if ("${_rsa_definition}" MATCHES "^(-D[ ]*)?RSA_SUPPORT($|=)")
        message(FATAL_ERROR "RSA_SUPPORT is enabled, but the packaged source rebuild omits librsa.a")
    endif()
endforeach()
if (" ${CMAKE_C_FLAGS} ${USER_COMPILE_OPTIONS} " MATCHES " -D[ ]*RSA_SUPPORT($|[ =;])")
    message(FATAL_ERROR "RSA_SUPPORT is enabled, but the packaged source rebuild omits librsa.a")
endif()
"""
BSP_RELEASE_CFLAGS = "-DNDEBUG -O2 -g -Wall -Wextra -fno-tree-loop-distribute-patterns"
GENERATOR_TOOLS = {
    "NMake Makefiles": "nmake",
    "MinGW Makefiles": "mingw32-make",
    "Ninja": "ninja",
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


def create_snapshot_manifest(snapshot: Path = SNAPSHOT) -> dict[str, Any]:
    files = []
    for path in sorted(snapshot.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files.append(
            {
                "path": path.relative_to(snapshot).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return {
        "schema": MANIFEST_SCHEMA,
        "vendor": "AMD Vitis 2026.1",
        "platform_bsp": "ps7_cortexa9_0/dom/bsp",
        "fsbl": "zynq_fsbl",
        "files": files,
    }


def write_snapshot_manifest(snapshot: Path = SNAPSHOT) -> Path:
    manifest = create_snapshot_manifest(snapshot)
    path = snapshot / "manifest.json"
    write_json(path, manifest)
    return path


def _cmake_assignment(text: str, variable: str, source: Path) -> str:
    match = re.search(rf"(?is)\bset\s*\(\s*{re.escape(variable)}\b(.*?)\)", text)
    if match is None:
        raise ValueError(f"Could not verify {variable} in {source}")
    return match.group(1)


def _assert_rsa_support_disabled(source: Path) -> None:
    user_config = source / "userconfig.cmake"
    text = user_config.read_text(encoding="utf-8")
    for variable in ("USER_COMPILE_DEFINITIONS", "USER_COMPILE_OPTIONS"):
        assignment = _cmake_assignment(text, variable, user_config)
        active_lines = "\n".join(line.split("#", 1)[0] for line in assignment.splitlines())
        if re.search(r"(?<![A-Za-z0-9_])(?:-D\s*)?RSA_SUPPORT(?![A-Za-z0-9_])", active_lines):
            raise ValueError(
                f"RSA_SUPPORT is enabled in {variable}; the packaged source rebuild omits librsa.a"
            )


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"Expected one {label} CMake fragment, found {count}")
    return text.replace(old, new, 1)


def _prepare_fsbl_source_workcopy(source: Path) -> dict[str, Any]:
    _assert_rsa_support_disabled(source)

    app_cmake = source / "cmakelists.txt"
    app_text = app_cmake.read_text(encoding="utf-8")
    app_text = _replace_once(
        app_text,
        "enable_language(C ASM)\n\ncollect(PROJECT_LIB_DEPS xiltimer)\n",
        "enable_language(C ASM)\n\n" + RSA_DISABLED_BUILD_GUARD + "\n"
        "collect(PROJECT_LIB_DEPS xiltimer)\n",
        "FSBL RSA guard insertion",
    )
    app_text = _replace_once(
        app_text,
        "collect(PROJECT_LIB_DEPS xilrsa)\n",
        "",
        "FSBL xilrsa library dependency",
    )
    app_text = _replace_once(
        app_text,
        "collect(PROJECT_LIB_DEPS xilstandalone;xiltimer;xilffs;xilrsa)\n",
        "collect(PROJECT_LIB_DEPS xilstandalone;xiltimer;xilffs)\n",
        "FSBL xilrsa link dependency",
    )

    bsp_cmake = source / "zynq_fsbl_bsp" / "cmakelists.txt"
    bsp_text = bsp_cmake.read_text(encoding="utf-8")
    bsp_text = _replace_once(
        bsp_text,
        "set (BSP_LIBSRC_SUBDIRS standalone libsrc xiltimer xilffs xilrsa)",
        "# RSA_SUPPORT is disabled for this snapshot; do not configure SDK-only librsa.a.\n"
        "set (BSP_LIBSRC_SUBDIRS standalone libsrc xiltimer xilffs)",
        "FSBL BSP xilrsa target",
    )

    app_cmake.write_text(app_text, encoding="utf-8")
    bsp_cmake.write_text(bsp_text, encoding="utf-8")
    return {
        "rsa_support_enabled": False,
        "skipped_bsp_target": "xilrsa",
        "skipped_fsbl_link_dependency": "xilrsa",
        "guard": "configuration fails if RSA_SUPPORT appears in user definitions or C flags/options",
        "modified_workcopy_files": [
            "vendor_source/fsbl/cmakelists.txt",
            "vendor_source/fsbl/zynq_fsbl_bsp/cmakelists.txt",
        ],
    }


def validate_snapshot(snapshot: Path = SNAPSHOT) -> dict[str, Any]:
    manifest_path = snapshot / "manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("Unsupported BSP/FSBL source snapshot manifest")

    records: dict[str, dict[str, Any]] = {}
    for record in manifest.get("files", []):
        relative = PurePosixPath(record["path"])
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() in records
        ):
            raise ValueError(f"Unsafe or duplicate BSP snapshot path: {record['path']}")
        records[relative.as_posix()] = record
        path = snapshot / Path(*relative.parts)
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise ValueError(f"BSP/FSBL snapshot file changed: {relative.as_posix()}")
        if path.suffix.casefold() in {".a", ".o", ".log"}:
            raise ValueError(f"Build product is present in BSP/FSBL source snapshot: {relative.as_posix()}")

    actual = {
        path.relative_to(snapshot).as_posix()
        for path in snapshot.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual != set(records):
        missing = sorted(actual - set(records))
        absent = sorted(set(records) - actual)
        raise ValueError(f"BSP snapshot inventory differs; unlisted={missing}, missing={absent}")

    required = (
        PLATFORM_BSP / "libsrc" / "standalone" / "src" / "bspconfig.h.in",
        PLATFORM_BSP / "libsrc" / "xiltimer" / "src" / "xtimer_config.h.in",
        FSBL_SOURCE / "zynq_fsbl_bsp" / "libsrc" / "standalone" / "src" / "bspconfig.h.in",
        FSBL_SOURCE / "zynq_fsbl_bsp" / "libsrc" / "xiltimer" / "src" / "xtimer_config.h.in",
    )
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.relative_to(snapshot).as_posix() not in records:
            raise ValueError(f"Required CMake template is absent from BSP snapshot manifest: {path}")
    return manifest


def _resolve_executable(raw: Path | str | None, name: str) -> Path:
    if raw is not None:
        value = str(raw)
        direct = Path(value)
        if direct.is_file():
            return direct.resolve()
        found = shutil.which(value)
        if found:
            return Path(found).resolve()
        raise FileNotFoundError(f"{name} executable not found: {raw}")
    found = shutil.which(name)
    if found:
        return Path(found).resolve()
    raise FileNotFoundError(f"{name} executable not found on PATH")


def resolve_cmake(toolchain: Path, requested: Path | None = None) -> Path:
    if requested is not None:
        return _resolve_executable(requested, "CMake")
    try:
        vendor_root = toolchain.resolve().parents[3]
    except IndexError:
        vendor_root = toolchain.resolve().parent
    candidates = list((vendor_root / "tps" / "win64").glob("cmake-*/bin/cmake.exe"))
    if candidates:
        def version_key(path: Path) -> tuple[int, ...]:
            return tuple(int(value) for value in re.findall(r"\d+", path.parent.parent.name))

        return sorted(candidates, key=version_key)[-1].resolve()
    return _resolve_executable(None, "cmake")


def _infer_generator(program: Path) -> str | None:
    name = program.name.casefold()
    if name.startswith("nmake"):
        return "NMake Makefiles"
    if name.startswith("mingw32-make"):
        return "MinGW Makefiles"
    if name == "ninja.exe" or name == "ninja":
        return "Ninja"
    return None


def resolve_generator(
    requested_generator: str | None, requested_program: Path | None
) -> tuple[str, Path]:
    if requested_program is not None:
        program = _resolve_executable(requested_program, "CMake build tool")
        generator = requested_generator or _infer_generator(program)
        if generator is None:
            raise ValueError("Pass --generator when --make-program is not nmake, mingw32-make, or ninja")
        return generator, program

    generators = [requested_generator] if requested_generator else list(GENERATOR_TOOLS)
    for generator in generators:
        executable = GENERATOR_TOOLS.get(generator or "")
        if executable is None:
            raise ValueError(f"Unsupported CMake generator: {generator}")
        found = shutil.which(executable)
        if found:
            return generator, Path(found).resolve()
    raise FileNotFoundError(
        "No supported CMake build tool found; install Visual Studio Build Tools (nmake), "
        "MinGW (mingw32-make), or Ninja, or pass --make-program"
    )


def _run_logged(command: list[str], cwd: Path, env: dict[str, str], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8", newline="\n") as stream:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}); see {log}")


def _prefix_map_flags(source: Path, build: Path) -> str:
    flags = []
    for root in (source, build):
        value = root.resolve().as_posix()
        flags.extend(
            (
                f'-fmacro-prefix-map="{value}=."',
                f'-fdebug-prefix-map="{value}=."',
            )
        )
    return " ".join(flags)


def _configure_and_build(
    *,
    source: Path,
    build: Path,
    bsp_source: Path,
    toolchain_file: Path,
    spec_file: Path,
    cmake: Path,
    make_program: Path,
    generator: str,
    compiler_bin: Path,
    jobs: int,
    label: str,
    c_flags_release: str = "-DNDEBUG",
) -> dict[str, Any]:
    build.mkdir(parents=True, exist_ok=False)
    source_library_dir = bsp_source / "lib"
    source_library_dir.mkdir(parents=True, exist_ok=True)
    source_posix = source.resolve().as_posix()
    build_posix = build.resolve().as_posix()
    bsp_posix = bsp_source.resolve().as_posix()
    spec_value = spec_file.resolve().as_posix()
    env = os.environ.copy()
    search_paths = [str(compiler_bin), str(make_program.parent), env.get("PATH", "")]
    env["PATH"] = os.pathsep.join(item for item in search_paths if item)

    prefix_flags = _prefix_map_flags(source, build)
    configure = [
        str(cmake),
        "-S",
        source_posix,
        "-B",
        build_posix,
        "-G",
        generator,
        f"-DCMAKE_MAKE_PROGRAM={make_program.resolve().as_posix()}",
        f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file.resolve().as_posix()}",
        f"-DCMAKE_MODULE_PATH={bsp_posix}",
        f"-DCMAKE_INCLUDE_PATH={(bsp_source / 'include').resolve().as_posix()}",
        f"-DCMAKE_LIBRARY_PATH={source_library_dir.resolve().as_posix()}",
        f'-DCMAKE_SPECS_FILE="{spec_value}"',
        "-DSUBDIR_LIST=ALL",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        f"-DCMAKE_C_FLAGS_RELEASE={c_flags_release} {prefix_flags}",
        f"-DCMAKE_CXX_FLAGS_RELEASE=-DNDEBUG {prefix_flags}",
        f"-DCMAKE_ASM_FLAGS_RELEASE=-DNDEBUG -x assembler-with-cpp {prefix_flags}",
    ]
    configure_log = build.parent / f"{label}_configure.log"
    _run_logged(configure, source, env, configure_log)

    build_command = [str(cmake), "--build", build_posix, "--parallel", str(max(1, jobs))]
    build_log = build.parent / f"{label}_build.log"
    _run_logged(build_command, source, env, build_log)
    return {
        "generator": generator,
        "configure_log": configure_log.name,
        "build_log": build_log.name,
        "configure_command": configure,
        "build_command": build_command,
    }


def _archive_path(build: Path, bsp_source: Path, name: str) -> Path:
    preferred = bsp_source / "lib" / name
    if preferred.is_file():
        return preferred
    matches = [path for path in build.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one generated {name}, found {len(matches)} under {build}")
    return matches[0]


def _archive_records(output_dir: Path, paths: list[Path]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = {}
    for source in paths:
        destination = output_dir / source.name
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        records[source.name] = {
            "path": destination.name,
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }
    return records


def build_platform_bsp(
    *,
    toolchain: Path,
    spec_file: Path,
    output: Path,
    cmake_path: Path | None = None,
    make_program_path: Path | None = None,
    generator_name: str | None = None,
    jobs: int = 4,
) -> dict[str, Any]:
    validate_snapshot()
    cmake = resolve_cmake(toolchain, cmake_path)
    generator, make_program = resolve_generator(generator_name, make_program_path)
    vendor_source = output / "vendor_source" / "platform_bsp"
    cmake_build = output / "cmake" / "platform_bsp"
    artifact_library_dir = output / "bsp" / "lib"
    vendor_source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PLATFORM_BSP, vendor_source)
    configure = _configure_and_build(
        source=vendor_source,
        build=cmake_build,
        bsp_source=vendor_source,
        toolchain_file=vendor_source / "cortexa9_toolchain.cmake",
        spec_file=spec_file,
        cmake=cmake,
        make_program=make_program,
        generator=generator,
        compiler_bin=toolchain.resolve() / "bin",
        jobs=jobs,
        label="platform_bsp",
        c_flags_release=BSP_RELEASE_CFLAGS,
    )
    archives = [_archive_path(cmake_build, vendor_source, name) for name in PLATFORM_LIBRARIES]
    records = _archive_records(artifact_library_dir, archives)
    return {
        "source": "build/bsp_snapshot/ps7_cortexa9_0/dom/bsp",
        "build_directory": "cmake/platform_bsp",
        "library_directory": "bsp/lib",
        "libraries": records,
        "commands": configure,
    }


def build_fsbl(
    *,
    toolchain: Path,
    spec_file: Path,
    output: Path,
    cmake_path: Path | None = None,
    make_program_path: Path | None = None,
    generator_name: str | None = None,
    jobs: int = 4,
) -> dict[str, Any]:
    validate_snapshot()
    cmake = resolve_cmake(toolchain, cmake_path)
    generator, make_program = resolve_generator(generator_name, make_program_path)
    vendor_source = output / "vendor_source" / "fsbl"
    bsp_source = vendor_source / "zynq_fsbl_bsp"
    bsp_build = output / "cmake" / "fsbl_bsp"
    app_build = output / "cmake" / "fsbl_app"
    fsbl_output = output / "fsbl" / "fsbl.elf"
    vendor_source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FSBL_SOURCE, vendor_source)
    source_workcopy_adjustments = _prepare_fsbl_source_workcopy(vendor_source)

    bsp_commands = _configure_and_build(
        source=bsp_source,
        build=bsp_build,
        bsp_source=bsp_source,
        toolchain_file=bsp_source / "cortexa9_toolchain.cmake",
        spec_file=spec_file,
        cmake=cmake,
        make_program=make_program,
        generator=generator,
        compiler_bin=toolchain.resolve() / "bin",
        jobs=jobs,
        label="fsbl_bsp",
        c_flags_release=BSP_RELEASE_CFLAGS,
    )
    fsbl_library_records = _archive_records(
        bsp_source / "lib",
        [_archive_path(bsp_build, bsp_source, name) for name in FSBL_LIBRARIES],
    )
    app_commands = _configure_and_build(
        source=vendor_source,
        build=app_build,
        bsp_source=bsp_source,
        toolchain_file=bsp_source / "cortexa9_toolchain.cmake",
        spec_file=spec_file,
        cmake=cmake,
        make_program=make_program,
        generator=generator,
        compiler_bin=toolchain.resolve() / "bin",
        jobs=jobs,
        label="fsbl_app",
    )
    built_fsbl = app_build / "fsbl.elf"
    if not built_fsbl.is_file():
        raise FileNotFoundError(f"FSBL CMake build did not produce {built_fsbl}")
    fsbl_output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built_fsbl, fsbl_output)
    return {
        "source": "build/bsp_snapshot/zynq_fsbl",
        "bsp_build_directory": "cmake/fsbl_bsp",
        "app_build_directory": "cmake/fsbl_app",
        "fsbl": {
            "path": "fsbl/fsbl.elf",
            "bytes": fsbl_output.stat().st_size,
            "sha256": sha256(fsbl_output),
        },
        "bsp_libraries": fsbl_library_records,
        "source_workcopy_adjustments": source_workcopy_adjustments,
        "bsp_commands": bsp_commands,
        "app_commands": app_commands,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate snapshot hashes only; default")
    mode.add_argument("--write-snapshot-manifest", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.write_snapshot_manifest:
        path = write_snapshot_manifest()
        print(f"SNAPSHOT_MANIFEST_WRITTEN {path}")
        return 0
    manifest = validate_snapshot()
    print(f"CHECK_PASS files={len(manifest['files'])} bsp_fsbl_snapshot={manifest['schema']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
