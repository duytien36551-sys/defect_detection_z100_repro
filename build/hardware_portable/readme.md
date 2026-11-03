# Historical Portable Export Template

This directory retains the post-route physopt/export Tcl and provenance from an earlier checkpoint-based export. Its Vivado checkpoint is intentionally not included in the project package. The template is not the default rebuild path and cannot run by itself without a compatible external routed checkpoint.

For the complete hardware rebuild from the packaged 53 RTL/ROM sources, block design, and constraints, use `build/rebuild_hardware_source.py --build` (or the compatibility alias `build/rebuild_hardware.py --build`). That flow does not require or reuse a historical checkpoint.

The earlier portable run was performed outside the package. Its actual checkpoint, generated outputs, acceptance, and logs remain in the external task evidence directory; they are not inputs to a teammate's source rebuild.

The separate 2026-11-03 source rebuild was stopped at the user's request before final route acceptance and bit/XSA export. It produced no new board image. See [the hardware status report](../../report/reproduction_hardware.md); the retained package bitstream and XSA remain historical board artifacts, not outputs of this template or that stopped source build.
