#!/usr/bin/env python3
"""Compatibility entry point for the checkpoint-free hardware rebuild."""

import sys

sys.dont_write_bytecode = True

from rebuild_hardware_source import main


if __name__ == "__main__":
    raise SystemExit(main())
