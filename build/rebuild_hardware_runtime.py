"""Shared Windows vendor-tool admission controls for hardware build scripts."""

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


MUTEX_NAME = r"Local\Z100_Vivado_Implementation"
MIN_FREE_RAM = 8 * 1024**3
MIN_FREE_DISK = 20 * 1024**3
BUSY_PROCESS_NAMES = {
    "vivado.exe",
    "vivado_lab.exe",
    "xelab.exe",
    "xsim.exe",
    "xvlog.exe",
    "xsct.exe",
    "xsdb.exe",
    "hw_server.exe",
    "bootgen.exe",
    "impact.exe",
}


class MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class SharedMutex:
    def __init__(self) -> None:
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        self.kernel.CreateMutexW.restype = ctypes.c_void_p
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.kernel.WaitForSingleObject.restype = ctypes.c_ulong
        self.kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.CreateMutexW(None, False, MUTEX_NAME)
        if not self.handle:
            raise OSError(f"CreateMutexW failed: {ctypes.get_last_error()}")
        status = int(self.kernel.WaitForSingleObject(self.handle, 0))
        if status not in (0, 0x80):
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError("The shared Vivado/board mutex is held")

    def close(self) -> None:
        if self.handle:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def process_inventory() -> list[dict[str, Any]]:
    blocked = ",".join(f"'{name}'" for name in sorted(BUSY_PROCESS_NAMES))
    script = (
        f"$blocked=@({blocked}); @(Get-CimInstance Win32_Process | Where-Object {{"
        "$blocked -contains $_.Name.ToLowerInvariant() -or "
        "($_.Name -ieq 'cmd.exe' -and $_.CommandLine -match '(?i)vivado(_lab)?\\.bat')"
        "} | Select-Object ProcessId,Name,CreationDate,CommandLine) | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    output = completed.stdout.strip()
    if not output:
        return []
    parsed = json.loads(output)
    return parsed if isinstance(parsed, list) else [parsed]


def resource_status() -> tuple[float, float]:
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Hardware resource checks require Windows")
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    root = Path(__file__).resolve().anchor
    free_disk = shutil.disk_usage(root).free
    free_ram_gib = status.ullAvailPhys / 1024**3
    free_disk_gib = free_disk / 1024**3
    if status.ullAvailPhys < MIN_FREE_RAM:
        raise RuntimeError(f"Only {free_ram_gib:.2f} GiB RAM is free; need 8 GiB")
    if free_disk < MIN_FREE_DISK:
        raise RuntimeError(f"Only {free_disk_gib:.2f} GiB disk is free; need 20 GiB")
    return free_ram_gib, free_disk_gib
