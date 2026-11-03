"""Portable entry point for rebuilding the SD network-fix image."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(PROJECT_ROOT / "build"))

from rebuild_sd_boot import main


if __name__ == "__main__":
    raise SystemExit(main())
