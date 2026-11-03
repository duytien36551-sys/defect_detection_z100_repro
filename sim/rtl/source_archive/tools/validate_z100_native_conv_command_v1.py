"""Build and validate the pure native Conv V1 command encoder."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "deployment/candidates/pin640/native_dispatch"
HEADER = DISPATCH / "native_conv_mmio_v1.h"
API_HEADER = DISPATCH / "native_conv_command_v1.h"
SOURCE = DISPATCH / "native_conv_command_v1.c"
TEST_SOURCE = DISPATCH / "native_conv_command_v1_test.c"
RTL = ROOT / "deployment/hardware/z100_2026/native_conv_mmio_v2/z100_native_conv_mmio_v2.sv"
BOUNDARY_TB = ROOT / ("deployment/hardware/z100_2026/native_conv_mmio_boundary_v1/"
                      "tb_z100_native_conv_mmio_boundary_v1.sv")
BOUNDARY_REPORT = ROOT / ("validation/board_z100/native_conv_mmio_boundary_v1/"
                          "20261026T104334.500867Z_3254aa/result.json")
EXPECTED = {
    "deployment/candidates/pin640/native_dispatch/native_conv_mmio_v1.h":
        "7ab1a3dfc4c95962a873ffa549ece5d30255fd9d91c6109f6f9d9277cd590880",
    "deployment/hardware/z100_2026/native_conv_mmio_v2/z100_native_conv_mmio_v2.sv":
        "f9c2ebc336470a2de6053b066a3e09f5a020278a845dc0981016893c55ccd239",
    "deployment/hardware/z100_2026/native_conv_mmio_boundary_v1/tb_z100_native_conv_mmio_boundary_v1.sv":
        "0ee94803e8932a084df81ba3809ffbd8470b19cadb4f1ed683a594cffdcec122",
    "validation/board_z100/native_conv_mmio_boundary_v1/20261026T104334.500867Z_3254aa/result.json":
        "c48edeb545974a9d80c84f041b65c25062218fbbbc2394dea9edf7e3befafaae",
}
MODEL_CRC = 0x83F6CD55
U32_MAX = 0xFFFFFFFF
END33_LIMIT = 0x1_0000_0000
MAX_WALL_SECONDS = 60
RANDOM_SEED = 0x5A4E4331

def source_key(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)

def word_vector_valid(words: list[int]) -> bool:
    if len(words) != 27 or any(value < 0 or value > U32_MAX for value in words):
        return False
    if (words[1] == 0 or words[4] == 0 or words[5] == 0 or words[6] == 0 or
            words[2] & 0xFFFFFF00 or words[3] != MODEL_CRC or
            words[7] & ~0x7 or words[7] & 0x6 != 0x6 or
            words[9] == 0 or words[14] == 0):
        return False
    def endpoint(low_index: int, require_alignment: bool) -> int | None:
        low, high = words[low_index], words[low_index + 1]
        if high & ~1:
            return None
        value = (high << 32) | low
        if value > END33_LIMIT or (require_alignment and value & 0x3F):
            return None
        return value
    source_end = endpoint(11, True)
    destination_end = endpoint(16, True)
    # The actual V2 shadow check requires payload begin alignment only.
    payload_end = endpoint(21, False)
    if source_end is None or destination_end is None or payload_end is None:
        return False
    if (words[8] & 0x3F or words[10] & 0x3F or words[8] < words[10] or
            words[8] >= source_end or words[10] >= source_end):
        return False
    if (words[13] & 0x3F or words[15] & 0x3F or words[13] < words[15] or
            words[13] >= destination_end or words[15] >= destination_end):
        return False
    if (words[18] & 0x3F or words[19] & 0xFFFF0000 or not 1 <= words[19] <= 173 or
            words[20] & 0x3F or payload_end <= words[20]):
        return False
    directory_end = words[18] + (((words[19] + 1) >> 1) << 6)
    if directory_end > END33_LIMIT:
        return False
    return all(words[index] != 0 for index in (23, 24, 25, 26))

def default_words(rng: random.Random) -> list[int]:
    words = [0] * 27
    words[0] = rng.getrandbits(32)
    words[1] = rng.randrange(1, U32_MAX + 1)
    words[2] = rng.randrange(0x100)
    words[3] = MODEL_CRC
    words[4] = rng.randrange(1, U32_MAX + 1)
    words[5] = rng.randrange(1, U32_MAX + 1)
    words[6] = rng.randrange(1, U32_MAX + 1)
    words[7] = 0x6 | rng.randrange(2)
    for begin_index, base_index, low_index, gen_index in ((10, 8, 11, 9), (15, 13, 16, 14)):
        begin = rng.randrange(1, (U32_MAX - 0x10000) // 64) * 64
        words[begin_index] = begin
        words[base_index] = begin + 64 * rng.randrange(2)
        end = begin + 0x10000
        words[low_index] = end & U32_MAX
        words[low_index + 1] = end >> 32
        words[gen_index] = rng.randrange(1, U32_MAX + 1)
    words[18] = rng.randrange(1, (U32_MAX - 0x10000) // 64) * 64
    words[19] = rng.randrange(1, 174)
    words[20] = rng.randrange(1, (U32_MAX - 0x10000) // 64) * 64
    payload_end = words[20] + 0x1000
    words[21] = payload_end & U32_MAX
    words[22] = payload_end >> 32
    words[23:27] = [rng.randrange(1, U32_MAX + 1) for _ in range(4)]
    return words

def random_vectors() -> list[list[int]]:
    rng = random.Random(RANDOM_SEED)
    vectors = [default_words(rng) for _ in range(40)]
    vectors[0][21] += 1  # Unaligned exclusive payload end is allowed by V2.
    for _ in range(40):
        words = default_words(rng)
        field = rng.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
                            13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26])
        if field in (1, 4, 5, 6, 9, 14, 19, 23, 24, 25, 26):
            bad = 0 if field != 19 else rng.choice([0, 174, 0x100ad])
        elif field == 2:
            bad = rng.randrange(0x100, U32_MAX + 1)
        elif field == 3:
            bad = MODEL_CRC ^ 1
        elif field == 7:
            bad = rng.choice([0, 1, 3, 5, 7 | 8, U32_MAX])
        elif field in (8, 10, 13, 15, 18, 20):
            bad = (words[field] & ~0x3F) | rng.randrange(1, 64)
        elif field in (11, 16, 21):
            bad = rng.choice([words[field] | 1, words[field] & ~0x3F, 0x40])
        elif field in (12, 17, 22):
            bad = rng.choice([2, 1])
        else:
            bad = rng.getrandbits(32)
        words[field] = bad & U32_MAX
        vectors.append(words)
    vectors.extend([[rng.getrandbits(32) for _ in range(27)] for _ in range(20)])
    require(len(vectors) == 100, "Random vector count must be bounded at 100")
    return vectors

def run(argv: list[str], cwd: Path, timeout: int = MAX_WALL_SECONDS,
        stdin: str | None = None) -> tuple[subprocess.CompletedProcess[str], float]:
    start = time.monotonic()
    proc = subprocess.run(argv, cwd=cwd, input=stdin, text=True, encoding="utf-8",
                          errors="replace", capture_output=True, timeout=timeout, check=False)
    return proc, time.monotonic() - start

def main() -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:6]
    output = ROOT / "validation/board_z100/native_conv_command_v1" / run_id
    build = ROOT / "deployment/build/native_conv_command_v1" / run_id
    output.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    result_path = output / "result.json"
    report: dict[str, Any] = {
        "schema": "z100-native-conv-command-v1-validation/1",
        "status": "PREFLIGHT", "mmio_access": False, "board_access": False,
        "driver_start_or_ack": False, "fullgraph_execution_accepted": False,
        "full_pipeline_30fps_accepted": False,
        "scope": "Portable numeric shadow-word validation and encoding only; no MMIO, ownership transitions, backend execution, or DDR qualification.",
        "commands": [], "host_random_seed": f"0x{RANDOM_SEED:08x}",
        "random_oracle_vectors": 100,
    }
    source_paths = [Path(__file__).resolve(), HEADER, API_HEADER, SOURCE, TEST_SOURCE,
                    RTL, BOUNDARY_TB, BOUNDARY_REPORT]
    before: dict[str, str] = {}
    started = time.monotonic()
    try:
        require(all(path.is_file() for path in source_paths), "A required source or prior proof is missing")
        for path in source_paths:
            key = source_key(path)
            if key in EXPECTED:
                require(sha256(path) == EXPECTED[key], f"Frozen source hash mismatch: {key}")
        prior = json.loads(BOUNDARY_REPORT.read_text(encoding="utf-8"))
        require(prior.get("status") == "PASS_LOCAL_MMIO_SHADOW_BOUNDARIES_WITH_MOCK_BACKEND_NOT_INTEGRATION" and
                prior.get("simulation", {}).get("bad_fields") == 38 and
                prior.get("simulation", {}).get("unexpected_cmdvalid") == 0 and
                prior.get("simulation", {}).get("unexpected_handshakes") == 0 and
                prior.get("simulation", {}).get("exact_4g_end") == 1,
                "Prior 38-case RTL boundary proof no longer matches expected status")
        before = {source_key(path): sha256(path) for path in source_paths}
        report["source_sha256_before"] = before
        report["source_bindings"] = {key: before[key] for key in EXPECTED}

        gcc = shutil.which("gcc")
        require(gcc is not None, "A host GCC is required for the C API tests")
        version, elapsed = run([gcc, "--version"], build, timeout=10)
        version_log = output / "gcc_version.log"
        version_log.write_text(version.stdout + version.stderr, encoding="utf-8")
        require(version.returncode == 0 and "gcc" in version.stdout.lower(), "Could not identify host GCC")
        report["host_compiler"] = {"path": gcc, "version": version.stdout.splitlines()[0],
                                   "version_elapsed_seconds": round(elapsed, 3)}

        executable = build / "native_conv_command_v1_test.exe"
        compile_argv = [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2",
                        f"-I{DISPATCH}", str(SOURCE), str(TEST_SOURCE), "-o", str(executable)]
        proc, elapsed = run(compile_argv, build)
        log_path = output / "host_compile.log"
        log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        report["commands"].append({"label": "host_compile", "argv": compile_argv,
                                   "return_code": proc.returncode, "elapsed_seconds": round(elapsed, 3),
                                   "log": source_key(log_path), "log_sha256": sha256(log_path)})
        require(proc.returncode == 0, f"Host GCC compile failed; inspect {log_path}")

        proc, elapsed = run([str(executable)], build)
        log_path = output / "host_self_test.log"
        log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        report["commands"].append({"label": "host_self_test", "argv": [str(executable)],
                                   "return_code": proc.returncode, "elapsed_seconds": round(elapsed, 3),
                                   "log": source_key(log_path), "log_sha256": sha256(log_path)})
        marker = "COMMAND_C_SELFTEST_PASS bad_fields=38 exact_4g_end=1 above_4g_rejects=2 null_args=3 payload_end_unaligned=1 layout_words=27"
        require(proc.returncode == 0 and marker in proc.stdout,
                f"C API self-test failed or pass census missing; inspect {log_path}")

        vectors = random_vectors()
        batch_input = "".join(" ".join(f"{word:08x}" for word in words) + "\n" for words in vectors)
        proc, elapsed = run([str(executable), "--batch-words"], build, stdin=batch_input)
        log_path = output / "host_python_oracle_batch.log"
        log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        report["commands"].append({"label": "host_python_oracle_batch",
                                   "argv": [str(executable), "--batch-words"],
                                   "return_code": proc.returncode, "elapsed_seconds": round(elapsed, 3),
                                   "log": source_key(log_path), "log_sha256": sha256(log_path)})
        require(proc.returncode == 0, f"C batch output failed; inspect {log_path}")
        lines = proc.stdout.splitlines()
        require(len(lines) == 100, "C output count differs from the 100 seeded oracle vectors")
        python_valid_count = 0
        for index, (words, line) in enumerate(zip(vectors, lines)):
            expected_valid = word_vector_valid(words)
            if expected_valid:
                python_valid_count += 1
                parts = line.split()
                require(len(parts) == 28 and parts[0] == "VALID",
                        f"C/Python validity disagreement at vector {index}")
                emitted = [int(part, 16) for part in parts[1:]]
                require(emitted == words, f"C encoder changed word value/order at vector {index}")
            else:
                require(line == "INVALID 1", f"C/Python invalidity disagreement at vector {index}")

        cross = Path("C:/appload/2026.1/Vitis/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin/arm-linux-gnueabihf-gcc.exe")
        if cross.is_file():
            arm_object = build / "native_conv_command_v1.arm.o"
            arm_argv = [str(cross), "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                        "-c", f"-I{DISPATCH}", str(SOURCE), "-o", str(arm_object)]
            proc, elapsed = run(arm_argv, build)
            log_path = output / "matched_arm_compile.log"
            log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
            report["commands"].append({"label": "matched_arm_compile", "argv": arm_argv,
                                       "return_code": proc.returncode,
                                       "elapsed_seconds": round(elapsed, 3),
                                       "log": source_key(log_path), "log_sha256": sha256(log_path)})
            require(proc.returncode == 0 and arm_object.is_file(),
                    f"Matched Vitis ARM compile failed; inspect {log_path}")
            report["arm_cross_compiler"] = {"path": str(cross), "sha256": sha256(cross),
                                             "compile_only": True, "object": source_key(arm_object),
                                             "object_sha256": sha256(arm_object)}
        else:
            report["arm_cross_compiler"] = {"available": False, "compile_performed": False}

        report.update(
            status="PASS_COMMAND_VALIDATION_AND_ENCODING",
            api_status_tests={"invalid_shadow_fields": 38, "layout_words": 27,
                              "exact_4g_end": 1, "above_4g_rejects": 2,
                              "null_argument_cases": 3, "unaligned_payload_end_allowed": 1,
                              "random_vectors": 100,
                              "python_oracle_valid": python_valid_count},
            executable={"path": source_key(executable), "sha256": sha256(executable)},
            abi_layout_assertions="C11 assertions from the frozen ABI header, explicit member-to-word mapping, and an independent numeric expected vector passed.",
        )
    except Exception as exc:
        report.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")
    after = {source_key(path): sha256(path) for path in source_paths if path.is_file()}
    report["source_sha256_before"] = before
    report["source_sha256_after"] = after
    if before and before != after:
        report.update(status="FAILED_SOURCE_INTEGRITY", error="A bound source changed during validation")
    report["elapsed_wall_seconds"] = round(time.monotonic() - started, 3)
    report["artifact_sha256"] = {
        source_key(path): sha256(path)
        for folder in (output, build) for path in folder.rglob("*")
        if path.is_file() and path != result_path
    }
    result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": source_key(result_path),
                      "error": report.get("error")}, ensure_ascii=False))
    return 1 if report["status"].startswith("FAILED") else 0

if __name__ == "__main__":
    raise SystemExit(main())
