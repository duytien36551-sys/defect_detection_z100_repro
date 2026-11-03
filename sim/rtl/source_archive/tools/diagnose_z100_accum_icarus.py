"""Capture installed DSP48E1 internal state during the original accumulator failure."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2"
PREVIOUS = ROOT / "validation/board_z100/native_primitive_refs_iverilog/20261026T012919.302313Z/result.json"
ACCUM_PROOF = ROOT / "validation/board_z100/accum33_dsp_v2/20261024T051501.085372Z/result.json"
MODULE = ROOT / "deployment/hardware/z100_2026/accum33_dsp_v2/z100_accum33_dsp.sv"
TESTBENCH = ROOT / "deployment/hardware/z100_2026/accum33_dsp_v2/tb_z100_accum33_dsp.sv"
VENDOR = Path("C:/appload/2026.1/Vivado/data/verilog/src")
DSP48E1 = VENDOR / "unisims/DSP48E1.v"
GLBL = VENDOR / "glbl.v"
ERROR_RE = re.compile(r"(?:^\s*(?:ERROR:|FATAL:)|\berror:|\bsorry:|syntax error|unable to bind)", re.I | re.M)

OBSERVER = r'''
// Passive Icarus diagnostic only. Sample the active load before the original
// task's #1 check and once after nonblocking updates have settled.
always @(posedge clk) begin
    if(load_bias) begin
        $display("DIAG_ACCUM_STATE stage=edge time=%0t rst_n=%b cancel=%b load=%b enable=%b update=%b bias=%h operand_a=%h operand_b=%h a48=%h b48=%h dsp_A=%h dsp_B=%h dsp_C=%h dsp_OPMODE=%b dsp_ALUMODE=%b dsp_CARRYINSEL=%b dsp_CEP=%b dsp_RSTP=%b opmode_in=%b alumode_in=%b a_o_mux=%h qa=%h qb=%h qc=%h qx=%h qy=%h qz=%h qopmode=%b qalumode=%b qcarryinsel=%b qcarryin=%b alu=%h qp_reg=%h qp_mux=%h p=%h",
            $time,rst_n,cancel,load_bias,enable,dut.update,bias,dut.operand_a,dut.operand_b,dut.a48,dut.b48,
            dut.feedback_adder.A,dut.feedback_adder.B,dut.feedback_adder.C,dut.feedback_adder.OPMODE,
            dut.feedback_adder.ALUMODE,dut.feedback_adder.CARRYINSEL,dut.feedback_adder.CEP,dut.feedback_adder.RSTP,
            dut.feedback_adder.opmode_in,dut.feedback_adder.alumode_in,dut.feedback_adder.a_o_mux,
            dut.feedback_adder.qa_o_mux,dut.feedback_adder.qb_o_mux,dut.feedback_adder.qc_o_mux,
            dut.feedback_adder.qx_o_mux,dut.feedback_adder.qy_o_mux,dut.feedback_adder.qz_o_mux,
            dut.feedback_adder.qopmode_o_mux,dut.feedback_adder.qalumode_o_mux,
            dut.feedback_adder.qcarryinsel_o_mux,dut.feedback_adder.qcarryin_o_mux,
            dut.feedback_adder.alu_o,dut.feedback_adder.qp_o_reg1,dut.feedback_adder.qp_o_mux,dut.p48);
        #0.1;
        $display("DIAG_ACCUM_STATE stage=settled time=%0t rst_n=%b cancel=%b load=%b enable=%b update=%b bias=%h operand_a=%h operand_b=%h a48=%h b48=%h dsp_A=%h dsp_B=%h dsp_C=%h dsp_OPMODE=%b dsp_ALUMODE=%b dsp_CARRYINSEL=%b dsp_CEP=%b dsp_RSTP=%b opmode_in=%b alumode_in=%b a_o_mux=%h qa=%h qb=%h qc=%h qx=%h qy=%h qz=%h qopmode=%b qalumode=%b qcarryinsel=%b qcarryin=%b alu=%h qp_reg=%h qp_mux=%h p=%h",
            $time,rst_n,cancel,load_bias,enable,dut.update,bias,dut.operand_a,dut.operand_b,dut.a48,dut.b48,
            dut.feedback_adder.A,dut.feedback_adder.B,dut.feedback_adder.C,dut.feedback_adder.OPMODE,
            dut.feedback_adder.ALUMODE,dut.feedback_adder.CARRYINSEL,dut.feedback_adder.CEP,dut.feedback_adder.RSTP,
            dut.feedback_adder.opmode_in,dut.feedback_adder.alumode_in,dut.feedback_adder.a_o_mux,
            dut.feedback_adder.qa_o_mux,dut.feedback_adder.qb_o_mux,dut.feedback_adder.qc_o_mux,
            dut.feedback_adder.qx_o_mux,dut.feedback_adder.qy_o_mux,dut.feedback_adder.qz_o_mux,
            dut.feedback_adder.qopmode_o_mux,dut.feedback_adder.qalumode_o_mux,
            dut.feedback_adder.qcarryinsel_o_mux,dut.feedback_adder.qcarryin_o_mux,
            dut.feedback_adder.alu_o,dut.feedback_adder.qp_o_reg1,dut.feedback_adder.qp_o_mux,dut.p48);
    end
end
'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_key(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return "external/" + path.as_posix().replace(":", "")


def resolve_source_key(name: str) -> Path:
    parts = Path(name).parts
    if parts and parts[0] == "external":
        return Path(parts[1] + ":/", *parts[2:])
    return ROOT / Path(name)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def runtime_paths() -> tuple[list[Path], dict[str, object]]:
    manifest_path = LOCAL / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "project-local-iverilog/1", "Pinned Icarus manifest")
    require(manifest.get("versions", {}).get("iverilog", "").startswith("Icarus Verilog version 13.0"), "Pinned Icarus 13.0")
    paths = [manifest_path]
    files = manifest.get("files", {})
    require(bool(files), "Pinned Icarus runtime file list")
    for relative, expected in files.items():
        path = LOCAL / Path(relative.replace("\\", "/"))
        require(path.is_file() and sha(path) == expected, f"Icarus runtime hash {relative}")
        paths.append(path)
    return paths, manifest


def startup_pulse_variant(original: str) -> str:
    port = ".A(b48[47:18])"
    anchor = "    wire [47:0] p48;\n"
    addition = (
        "    reg [29:0] diag_a_startup_pulse = 30'b0;\n"
        "    wire [29:0] diag_a_input = b48[47:18] | diag_a_startup_pulse;\n"
        "    initial begin #0.001 diag_a_startup_pulse = 30'b1; #0.001 diag_a_startup_pulse = 30'b0; end\n"
    )
    require(original.count(port) == 1 and original.count(anchor) == 1, "Unique accumulator DSP A port and insertion point")
    variant = "`timescale 1ns/1ps\n" + original.replace(anchor, anchor + addition, 1).replace(port, ".A(diag_a_input)", 1)
    normalized = variant.replace("`timescale 1ns/1ps\n", "", 1)
    normalized = normalized.replace(addition, "", 1).replace(".A(diag_a_input)", port, 1)
    require(normalized == original, "Startup-pulse variation changes only generated DSP A startup stimulus")
    return variant


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = ROOT / "validation/board_z100/accum_icarus_diagnostic" / stamp
    build = ROOT / "build" / f"aicdiag_{stamp[-14:]}"
    out.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report_path = out / "result.json"
    before: dict[str, str] = {}
    sources: list[Path] = []
    report: dict[str, object] = {
        "schema": "z100-accum-icarus-diagnostic/1",
        "status": "RUNNING",
        "commands": [],
        "board_access": False,
        "simulation_references_only": True,
        "vendor_sources": [str(DSP48E1), str(GLBL)],
        "vendor_source_modified": False,
        "force_initialization_used": False,
        "variation": "original accumulator suite with passive observer only",
        "full_pipeline_30fps_accepted": False,
    }

    try:
        previous = json.loads(PREVIOUS.read_text(encoding="utf-8"))
        require(previous.get("status") == "FAILED_CLOSED", "Bound prior failed Icarus miter report")
        require(previous.get("source_sha256_before") == previous.get("source_sha256_after"), "Prior attempt source hashes stable")
        prior_sim = previous.get("commands", [])
        require(any(item.get("name") == "accum_vvp" and item.get("return_code") == 1 for item in prior_sim),
                "Prior accumulator failure evidence")
        proof = json.loads(ACCUM_PROOF.read_text(encoding="utf-8"))
        require(proof.get("status") == "PASS_PRIVATE_SIGNED33_FEEDBACK_XSIM_ONE_DSP_OOC_ONLY", "Original XSIM proof status")
        require(proof.get("source_sha256_before") == proof.get("source_sha256_after"), "Original XSIM proof source hashes stable")
        require(proof.get("simulation", {}).get("checks") == 16754, "Original XSIM accumulator suite coverage")
        for name, expected in {**proof["source_sha256_after"], **proof.get("artifact_sha256", {})}.items():
            path = resolve_source_key(name)
            require(path.is_file() and sha(path) == expected, f"Original XSIM proof source/artifact {name}")

        original_tb = TESTBENCH.read_text(encoding="utf-8")
        require(original_tb.count("endmodule") == 1 and original_tb.count("module tb_z100_accum33_dsp;") == 1,
                "Single unchanged original accumulator testbench")
        generated_tb = original_tb.replace("endmodule", OBSERVER + "\nendmodule")
        require(generated_tb.replace(OBSERVER + "\n", "") == original_tb, "Observer-only testbench copy")
        tb_copy = build / "tb_z100_accum33_dsp_diagnostic.sv"
        tb_copy.write_text(generated_tb, encoding="utf-8")
        variant_text = startup_pulse_variant(MODULE.read_text(encoding="utf-8"))
        variant_module = build / "z100_accum33_dsp_startup_pulse_diagnostic.sv"
        variant_module.write_text(variant_text, encoding="utf-8")

        runtime, manifest = runtime_paths()
        binary = LOCAL / "ucrt64/bin"
        backend = LOCAL / "ucrt64/lib/ivl"
        iverilog = binary / "iverilog.exe"
        vvp = binary / "vvp.exe"
        require(all(path.exists() for path in (iverilog, vvp, backend, DSP48E1, GLBL)), "Installed vendor and local Icarus files")
        sources = [Path(__file__), PREVIOUS, ACCUM_PROOF, MODULE, TESTBENCH, tb_copy, variant_module, DSP48E1, GLBL, *runtime]
        before = {source_key(path): sha(path) for path in sources}
        report.update(
            source_sha256_before=dict(sorted(before.items())),
            previous_failure_report=source_key(PREVIOUS),
            original_xsim_report=source_key(ACCUM_PROOF),
            runtime_manifest=source_key(LOCAL / "manifest.json"),
            runtime_manifest_sha256=sha(LOCAL / "manifest.json"),
            simulator=manifest.get("versions"),
            generated_testbench=source_key(tb_copy),
            generated_testbench_sha256=sha(tb_copy),
            diagnostic_variant_module=source_key(variant_module),
            diagnostic_variant_module_sha256=sha(variant_module),
            diagnostic_variant_only="Generated copy ORs a 1-to-0, 2ps startup pulse into DSP A input, then restores the original b48[47:18] connection; not an acceptance run.",
            scope=(
                "Original signed33 accumulator RTL and testbench run against the unmodified installed DSP48E1 model. "
                "The generated copy adds only passive edge/settled displays for the first legal load; the original "
                "assertions remain enabled and their failure is preserved. One separate diagnostic variation "
                "adds a 2ps startup pulse on the generated DSP A input to test whether the constant-zero input "
                "fails to initialize the vendor model's event-driven A muxes."
            ),
        )
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        env = dict(os.environ)
        env["PATH"] = str(binary) + os.pathsep + env.get("PATH", "")
        env["OMP_NUM_THREADS"] = "1"
        commands: list[dict[str, object]] = report["commands"]
        args = [
            str(iverilog), "-B", str(backend), "-g2012", "-s", "tb_z100_accum33_dsp", "-s", "glbl",
            "-o", str(build / "accum_diagnostic.vvp"), str(MODULE), str(tb_copy), str(DSP48E1), str(GLBL),
        ]
        started = time.monotonic()
        compile_proc = subprocess.run(args, cwd=build, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=120)
        compile_log = compile_proc.stdout + ("\n" if compile_proc.stdout and compile_proc.stderr else "") + compile_proc.stderr
        (out / "iverilog.log").write_text(compile_log, encoding="utf-8")
        commands.append({"name": "iverilog", "argv": args, "return_code": compile_proc.returncode, "wall_seconds": round(time.monotonic() - started, 3)})
        require(compile_proc.returncode == 0 and ERROR_RE.search(compile_log) is None, "Strict Icarus diagnostic compile")

        run_args = [str(vvp), "-M", str(backend), str(build / "accum_diagnostic.vvp")]
        started = time.monotonic()
        run_proc = subprocess.run(run_args, cwd=build, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=60)
        run_log = run_proc.stdout + ("\n" if run_proc.stdout and run_proc.stderr else "") + run_proc.stderr
        (out / "vvp.log").write_text(run_log, encoding="utf-8")
        commands.append({"name": "vvp", "argv": run_args, "return_code": run_proc.returncode, "wall_seconds": round(time.monotonic() - started, 3)})

        lines = re.findall(r"^DIAG_ACCUM_STATE stage=(?:edge|settled) .*$", run_log, re.MULTILINE)
        edge = [line for line in lines if "stage=edge " in line]
        settled = [line for line in lines if "stage=settled " in line]
        require(len(edge) == 1 and len(settled) == 1, "Captured edge and settled samples at first legal load")
        fatal = re.findall(r"^FATAL:.*feedback mismatch check=2.*$", run_log, re.MULTILINE)
        require(run_proc.returncode != 0 and len(fatal) == 1, "Original first-load mismatch remains visible")
        def parse_fields(line: str) -> dict[str, str]:
            return dict(re.findall(r"(\w+)=([^ ]+)", line.split(" ", 1)[1]))
        observations = [{"stage": "edge", "line": edge[0], "fields": parse_fields(edge[0])},
                        {"stage": "settled", "line": settled[0], "fields": parse_fields(settled[0])}]
        unknown = {}
        for observation in observations:
            unknown[observation["stage"]] = [key for key, value in observation["fields"].items()
                                              if re.search(r"[xz]", value, re.IGNORECASE)]
        report.update(
            status="DIAGNOSTIC_CAPTURED_ORIGINAL_ACCUM_MISMATCH",
            simulation={"return_code": run_proc.returncode, "fatal": fatal[0]},
            observations=observations,
            unknown_fields=unknown,
            compile_warnings=len(re.findall(r"\bwarning:", compile_log, re.IGNORECASE)),
            diagnosis="Raw passive trace captured; interpret first unknown from edge/settled fields. No acceptance inferred.",
        )

        # Evidence showed A and qa first become unknown while OPMODE, ALUMODE,
        # C, B, carry controls and the signed bias path are known. Run one
        # diagnostic-only source copy with a short A transition at startup.
        variant_compile_args = [
            str(iverilog), "-B", str(backend), "-g2012", "-s", "tb_z100_accum33_dsp", "-s", "glbl",
            "-o", str(build / "accum_startup_pulse.vvp"), str(variant_module), str(tb_copy), str(DSP48E1), str(GLBL),
        ]
        started = time.monotonic()
        variant_compile = subprocess.run(variant_compile_args, cwd=build, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=120)
        variant_compile_log = variant_compile.stdout + ("\n" if variant_compile.stdout and variant_compile.stderr else "") + variant_compile.stderr
        (out / "variation_iverilog.log").write_text(variant_compile_log, encoding="utf-8")
        commands.append({"name": "variation_iverilog", "argv": variant_compile_args, "return_code": variant_compile.returncode, "wall_seconds": round(time.monotonic() - started, 3)})
        require(variant_compile.returncode == 0 and ERROR_RE.search(variant_compile_log) is None, "Strict startup-pulse diagnostic compile")

        variant_run_args = [str(vvp), "-M", str(backend), str(build / "accum_startup_pulse.vvp")]
        started = time.monotonic()
        variant_run = subprocess.run(variant_run_args, cwd=build, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=60)
        variant_run_log = variant_run.stdout + ("\n" if variant_run.stdout and variant_run.stderr else "") + variant_run.stderr
        (out / "variation_vvp.log").write_text(variant_run_log, encoding="utf-8")
        commands.append({"name": "variation_vvp", "argv": variant_run_args, "return_code": variant_run.returncode, "wall_seconds": round(time.monotonic() - started, 3)})
        variant_lines = re.findall(r"^DIAG_ACCUM_STATE stage=(?:edge|settled) .*$", variant_run_log, re.MULTILINE)
        variant_edge = next((line for line in variant_lines if "stage=edge " in line), None)
        variant_settled = next((line for line in variant_lines if "stage=settled " in line), None)
        variant_markers = re.findall(r"^ACCUM33_DSP_PASS (.+)$", variant_run_log, re.MULTILINE)
        variant_fatals = re.findall(r"^FATAL:.*$", variant_run_log, re.MULTILINE)
        report["diagnostic_variation"] = {
            "purpose": "Test whether a real startup transition initializes the installed model's event-driven A/QA mux chain.",
            "compile_return_code": variant_compile.returncode,
            "runtime_return_code": variant_run.returncode,
            "original_suite_marker": variant_markers[0] if len(variant_markers) == 1 else None,
            "original_suite_marker_count": len(variant_markers),
            "fatal_lines": variant_fatals,
            "first_load_edge": variant_edge,
            "first_load_settled": variant_settled,
            "not_an_acceptance_run": True,
        }
        if variant_edge and variant_settled:
            report["diagnostic_variation"]["first_load_unknown_fields"] = {
                "edge": [key for key, value in parse_fields(variant_edge).items() if re.search(r"[xz]", value, re.I)],
                "settled": [key for key, value in parse_fields(variant_settled).items() if re.search(r"[xz]", value, re.I)],
            }
    except Exception as exc:
        report.update(status="FAILED_DIAGNOSTIC", error=f"{type(exc).__name__}: {exc}")

    try:
        if sources:
            after = {source_key(path): sha(path) for path in sources}
            report["source_sha256_before"] = dict(sorted(before.items()))
            report["source_sha256_after"] = dict(sorted(after.items()))
            if before != after:
                report.update(status="FAILED_SOURCE_INTEGRITY", error="Bound source/vendor/runtime changed during diagnostic")
        report["artifact_sha256"] = {
            source_key(path): sha(path)
            for folder in (out, build)
            for path in folder.rglob("*")
            if path.is_file() and path != report_path
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        report.update(status="FAILED_REPORT_FINALIZATION", error=f"{type(exc).__name__}: {exc}")
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": report["status"], "report": source_key(report_path), "error": report.get("error")}))
    return 0 if report.get("status") == "DIAGNOSTIC_CAPTURED_ORIGINAL_ACCUM_MISMATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
