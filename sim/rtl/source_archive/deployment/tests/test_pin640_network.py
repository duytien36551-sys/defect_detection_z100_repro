"""Loopback proof that a full PIN640 frame streams through the lwIP ring."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = PROJECT_ROOT / "deployment" / "candidates" / "pin640" / "firmware"
HARNESS = PROJECT_ROOT / "deployment" / "candidates" / "pin640" / "tests" / "network_stream.c"
MOCKS = PROJECT_ROOT / "deployment" / "tests" / "network_transport_mocks"


class Pin640NetworkStreamTests(unittest.TestCase):
    def test_full_frame_wraps_ring_and_recovers_after_incomplete_fin(self) -> None:
        compiler = os.environ.get("CC") or shutil.which("gcc") or r"C:\cbian\mingw64\bin\gcc.exe"
        if not Path(compiler).is_file() and shutil.which(compiler) is None:
            self.fail("GCC is required for the PIN640 network stream harness")

        env = os.environ.copy()
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            env[name] = "1"

        with tempfile.TemporaryDirectory(prefix="pin640-net-") as directory:
            temp = Path(directory)
            # v8_sdt_compat.h includes xil_types.h; the existing mocks omit
            # this otherwise-unused standalone type header.
            (temp / "xil_types.h").write_text(
                "#ifndef PIN640_TEST_XIL_TYPES_H\n"
                "#define PIN640_TEST_XIL_TYPES_H\n"
                "#include <stdint.h>\n"
                "typedef uintptr_t UINTPTR;\n"
                "#endif\n",
                encoding="ascii",
            )
            executable = temp / "network_stream.exe"
            command = [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                "-I",
                str(temp),
                "-I",
                str(MOCKS),
                "-I",
                str(FIRMWARE),
                str(HARNESS),
                "-o",
                str(executable),
            ]
            compiled = subprocess.run(
                command, capture_output=True, text=True, env=env
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            completed = subprocess.run(
                [str(executable)], capture_output=True, text=True, env=env
            )

        self.assertEqual(
            completed.returncode,
            0,
            f"network harness exit status {completed.returncode}: {completed.stderr}",
        )
        self.assertIn("PIN640 lwIP stream PASS: bytes=1228800", completed.stdout)


if __name__ == "__main__":
    unittest.main()
