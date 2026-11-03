# Identity review — 02_identity_missing_runtime_derived

## Conclusion

**Target-board runtime identity: NOT CONFIRMED.** The fixture supports a build candidate and XSA metadata checks, not physical programming or execution identity. No hardware was operated.

## Supported by the supplied files

- Build manifest time: `2026-10-18T13:16:26.190455+08:00`. Model SHA-256, package SHA-256 and manifest-declared `sd_root/MODEL.V8P` SHA-256 agree: `f5394b31cf55502d6b3bc458b212db2c3422f8fe30dbdb509742f5c085a8d9b3`. `MODEL.V8P` bytes are absent, so this is declaration cross-check only.
- The manifest declares `BOOT.BIN`, FSBL ELF, board ELF, `tile64.bit`, and `tile64.xsa`. The actual artifacts are absent. The included `build_report.json` hash was recomputed and matches the manifest entry.
- `arm_link=PASS` and XSA metadata/interface checks are recorded as pass; report lists AXI DMA width 20 bits. It explicitly says physical board not verified and `physical_board_dma_width_verified=false`. Manifest has `physical_latency_seconds=null`.
- No runtime probe or run log reports the loaded model, executing ELF, board identity or programmed PL image. Category order and complete input/preprocessing identity also are not established by these two files.

## Minimum next check

After authorization for a read-only target check, capture board ID, protocol/input/preprocessing and ordered class identity, loaded model SHA-256, executing ELF SHA-256, and physical PL design/bitstream identity, then compare with the actual artifact bytes. Until then, do not claim deployment, compatibility or optimality.

JSON pointers and source line references are in `report.json`.
