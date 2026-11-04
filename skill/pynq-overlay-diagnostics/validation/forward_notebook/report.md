# PYNQ Notebook Static Inspection Report

## Request and scope

Notebook: `examples/public_resizer/resizer_source_only.ipynb`

Purpose: review overlay loading and DMA operations before any hardware run. This was a static inspection only. The notebook and hardware were not run.

## Run record

- Working directory: `SKILL_ROOT`
- Command: `python -B scripts/inspect_notebook.py --notebook examples/public_resizer/resizer_source_only.ipynb --out VALIDATION_WORKSPACE/forward_notebook/notebook_audit.json`
- Exit code: `0`
- Inspector status: `STATIC_INSPECTION_COMPLETE`
- Notebook SHA-256: `ad2efb34f6c3968559c2ce462cdd1db42de612064884c262c430cda3a4dea411`
- Audit JSON SHA-256: `1555956168b6aa375ef301065c111cfd15fe68c40d45b5b6f6ec1ca745218801`
- Audit JSON: `VALIDATION_WORKSPACE/forward_notebook/notebook_audit.json`

The inspector reports `hardware_execution: false` and `saved_outputs_used_as_evidence: false`. Saved cell outputs and execution counts are not treated as evidence of a current run.

## Files used

- Input notebook: `examples/public_resizer/resizer_source_only.ipynb`
- Inspector: `scripts/inspect_notebook.py`
- Skill instructions: `SKILL.md`
- Report template: `assets/report_template.md`
- Machine-readable result: `VALIDATION_WORKSPACE/forward_notebook/notebook_audit.json`

## Observed notebook operations

The inspector found these imports in cell 0: `PIL.Image`, `numpy`, `matplotlib.pyplot`, and `pynq.allocate` / `pynq.Overlay`.

| Cell and line | Operation | Recorded arguments |
| --- | --- | --- |
| 1:1 | `Overlay` | `'resizer.bit'` |
| 6:1 | `allocate` | `shape=(old_height, old_width, 3)`, `dtype=np.uint8`, `cacheable=1` |
| 6:3 | `allocate` | `shape=(new_height, new_width, 3)`, `dtype=np.uint8`, `cacheable=1` |
| 8:2 | `dma.sendchannel.transfer` | `in_buffer` |
| 8:3 | `dma.recvchannel.transfer` | `out_buffer` |
| 8:5 | `dma.sendchannel.wait` | no arguments |
| 8:6 | `dma.recvchannel.wait` | no arguments |

## Findings and checks to make

- The `Overlay('resizer.bit')` call may program the PL. Before executing that cell, confirm the resolved bitstream and matching hardware metadata belong to the intended resizer design and board state. This inspection did not check those files or the live device.
- Both buffers are allocated as three-channel `uint8` arrays with `cacheable=1`. Compare the shapes and pixel layout with the accelerator's actual input/output contract. Confirm the required cache maintenance for this PYNQ version and driver: input data must be visible to the device before transfer, and output data must be made visible to the CPU after completion. The static call list alone does not establish whether other code handles this.
- The notebook starts the send transfer, then the receive transfer, then waits on send and receive. Confirm that this order matches the DMA/IP handshake and that the receive path is armed in time for the accelerator's output.
- Both `wait()` calls have no timeout argument. The inspector flags `WAIT_BOUND_NOT_PROVEN`: these calls may poll indefinitely, and the source does not establish a bounded recovery path, correct `TLAST`, or successful completion.
- The inspector also reports magic/shell lines in cells 0 and 12 as excluded from AST inspection. Review those lines manually before any run if they affect setup or data handling.

## Limits

This result is a syntactic AST inspection, not symbolic execution. Aliases, dynamically built calls, register writes, call behavior hidden in helpers, and magic/shell lines may require manual review. It does not verify call order at runtime, buffer ownership, `TLAST`, cache maintenance, DMA completion, output correctness, bitstream identity, or hardware state. No hardware acceptance is implied.

## Next minimal steps

1. Statically identify the intended `.bit` and matching `.hwh` artifacts and confirm the accelerator IP and DMA configuration against the notebook's dimensions, channel layout, and transfer sizes.
2. Review the complete DMA setup and data path for receive/send ordering, cache maintenance, bounded completion/error handling, and frame-end signaling.
3. Only after those checks, prepare a separately authorized controlled hardware run with observable timeout and output checks.
