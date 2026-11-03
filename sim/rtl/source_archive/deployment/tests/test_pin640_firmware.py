"""Host-side bounds and ABI checks for the isolated PIN640 firmware."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = PROJECT_ROOT / "deployment" / "candidates" / "pin640" / "firmware"
HARNESS = PROJECT_ROOT / "deployment" / "candidates" / "pin640" / "tests" / "runtime_guards.c"


class Pin640FirmwareTests(unittest.TestCase):
    def test_package_pipeline_buffers_and_dma_limits(self) -> None:
        compiler = os.environ.get("CC") or shutil.which("gcc") or r"C:\cbian\mingw64\bin\gcc.exe"
        if not Path(compiler).is_file() and shutil.which(compiler) is None:
            self.fail("GCC is required for the PIN640 firmware guard harness")

        with tempfile.TemporaryDirectory(prefix="pin640-fw-") as directory:
            executable = Path(directory) / "runtime_guards.exe"
            command = [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                "-I",
                str(FIRMWARE),
                str(HARNESS),
                str(FIRMWARE / "v8_runtime.c"),
                str(FIRMWARE / "v8_pipeline.c"),
                str(FIRMWARE / "v8_decode.c"),
                str(FIRMWARE / "v8_tile_abi.c"),
                "-lm",
                "-o",
                str(executable),
            ]
            compiled = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            completed = subprocess.run(
                [str(executable)], capture_output=True, text=True
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

        self.assertIn(
            "PIN640 runtime bounds, heads, package, and DMA contracts: PASS",
            completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
