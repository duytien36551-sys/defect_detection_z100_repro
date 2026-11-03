lwIP protocol core include-path placeholder (delivery notes updated 2026-11-03).

This original SDK directory contained implementation source files only. Its compiled source units are delivered separately under firmware_portable/sources and listed with compile commands in firmware_portable/manifest.json. This file preserves the original -I directory mapping; it is not a missing generated header or a separately executable module.

Use build/rebuild_firmware.py --check from the package root to verify the current source closure. For the network-fix application, use build/rebuild_sd_boot.py --check. Neither command compiles, starts the board, or establishes SD cold-boot/scoped-cache acceptance. See firmware_portable/readme.md for the actual build workflow.
