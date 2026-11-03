# Portable RTL Reproduction

The package includes nine frozen component/core regressions: `control01`, `fault_diagnostics01`, `id_fault01`, `mixed01`, `mixed_diagnostics01`, `pool_control01`, `pool_fault01`, `tail01`, and `unit01`. They are useful checks of selected RTL blocks and interfaces. They do not demonstrate full-network inference acceptance or board operation.

The runner uses Python 3.10+ and only the standard library. The packaged Verilog/SystemVerilog and fixture hashes are checked against `portable_cases.json`; Vivado's `glbl.v` is checked separately against the hash recorded there. Vivado 2026.1 is required for the external global module and XSim tools.

From the package root, validate packaged inputs:

```powershell
py -3 sim/run_rtl.py --check
py -3 sim/run_rtl.py --check --vivado-bin "C:\Xilinx\Vivado\2026.1\Vivado\bin"
```

The first command checks all packaged case sources and fixtures. The second also checks that Vivado's `data\verilog\src\glbl.v` has the expected SHA-256. Neither command runs a simulation.

Run one case or all nine with a new output directory outside the package:

```powershell
py -3 sim/run_rtl.py --run --case unit01 --vivado-bin "C:\Xilinx\Vivado\2026.1\Vivado\bin" --output-dir "D:\rtl-runs\unit01-20261103"
py -3 sim/run_rtl.py --run --case all --vivado-bin "C:\Xilinx\Vivado\2026.1\Vivado\bin" --output-dir "D:\rtl-runs\all-20261103"
```

The chosen output directory must not already exist. Each case is staged into its own subdirectory; compiler databases, logs, and waveforms stay there. Before simulation, the runner records the complete Vivado version response and probes `xvlog`, `xelab`, and `xsim`; each simulator probe must report 2026.1 and exit successfully. The runner records each full command and return code, input SHA-256 values, version-probe output and log hashes, and every case pass-marker result in `run_report.json`. It returns a nonzero exit code for invalid inputs, unsafe output paths, a busy shared implementation mutex, tool failure, or a missing pass marker. On Windows it uses `Local\Z100_Vivado_Implementation` and fails immediately when the hardware implementation flow owns the mutex.

To inspect staged inputs and commands without running XSim, use `--prepare` with the same `--case`, `--vivado-bin`, and a new external `--output-dir`. The generated `plan.json` says `prepared_only_not_run`; preparation is not a simulation result.

`reference_results.json` preserves earlier component-level results and is marked as historical. Fresh runs are recorded only in the selected external output directory. A component pass does not establish full detector accuracy, timing closure, or hardware/board acceptance.
