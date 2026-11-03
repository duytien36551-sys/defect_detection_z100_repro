# Zynq-7000 Hardware Rebuild

This bundle contains the 53 pinned RTL/ROM inputs, the Zynq processing-system block design, and the Tcl needed to synthesize, place, route, and export the design. The build starts from the included sources and does not require a Vivado checkpoint, generated object, or external project directory.

Current state (2026-11-03): the fresh source build was stopped at the user's request before final route acceptance and bit/XSA export. No new hardware artifact was produced or validated on a board. The packaged board image and the historical implementation report remain separate references; see [the hardware status report](../../report/reproduction_hardware.md).

Required tool: Vivado 2026.1 for `xc7z100ffg900-2`. The runner checks for at least 8 GiB free RAM, 20 GiB free disk, and competing Vivado/board tools, then acquires the shared Windows Vivado mutex. It does not access or program a board.

From the project root, verify the source inventory and Tcl hashes:

```powershell
python build/rebuild_hardware_source.py --check
```

Run the complete source build. Replace the Vivado path if it is installed elsewhere:

```powershell
python build/rebuild_hardware_source.py --build `
  --vivado "C:\Xilinx\Vivado\2026.1\bin\vivado.bat"
```

The default output is outside the project package at `.codex/engineering_package_repro_20261103/hardware/run-*`. Windows Vivado has a 260-character path limit. Before launching Vivado, the runner checks the longest generated block-design IP path, including the run ID and `.xci` filename, and rejects an overlong destination without creating a run directory. For a deep checkout, use a short external directory and a `subst` drive alias:

```powershell
New-Item -ItemType Directory -Force C:\z100_hw | Out-Null
subst R: C:\z100_hw
python build/rebuild_hardware_source.py --build `
  --vivado "C:\Xilinx\Vivado\2026.1\bin\vivado.bat" `
  --output-root R:/source_build
```

Choose a free drive letter if `R:` is already in use. The runner preserves the alias for all generated-file writes and resolves the destination only to confirm it is outside the project package. Tcl `file normalize` retains a Windows `subst` alias. The manifest pins this path policy, and `--check` verifies it. After the run, `subst R: /d` removes only the drive mapping; files remain in `C:\z100_hw`. The run directory records source hashes, Vivado version, each stage's result, complete timing/route/DRC acceptance, and bit/XSA SHA-256 values. Final files are `export/artifacts/z100_platform.bit` and `export/artifacts/z100_platform.xsa`; generated checkpoints and logs remain in the same external run directory.

The route stage exports only after the full timing, hold, pulse-width, constraint-coverage, routing, and DRC gates pass. If the routed design has only setup failures and otherwise passes its recovery gate, the runner applies one post-route `Explore` physopt pass, then runs the same final export checks. It stops on any other failure and does not retry automatically.

A fresh source build can produce a different bitstream from the existing board image because placement and routing start without a historical checkpoint. The run record reports byte identity separately; it does not claim board validation.
