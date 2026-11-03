"""Offline-only static gates for registered-response-bank V1; launches no vendor tools."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_DIR = ROOT / "deployment/hardware/z100_2026/registered_response_bank_v1"
BASE = ROOT / "build/v12p_d46da432/rtl/z100_feature_banks_pingpong_writepipe_v7.sv"
CANDIDATE = CANDIDATE_DIR / "z100_feature_banks_pingpong_writepipe_v7.sv"
MANIFEST = CANDIDATE_DIR / "source_manifest_v1.json"
MITER = CANDIDATE_DIR / "tb_z100_registered_response_bank_miter_v1.sv"
RUNNER = ROOT / "tools/run_z100_registered_response_bank_v2.py"
QUEUE = ROOT / "tools/queue_z100_registered_response_bank_v2.py"
SOURCE_REVIEW = ROOT / "validation/board_z100/response_bank_primary_source_review/20261027T134126.399751Z/result.json"
BOOLEAN_REVIEW = ROOT / "validation/board_z100/response_bank_primary_boolean_review/20261027T133834.407679Z/result.json"
EXPECTED_BASE = "70719780ff5428755dc562684fedd9c793a9375eeebd93959df11aafb9232662"
EXPECTED_CANDIDATE = "fd90b026c3992b49819ead401e705eda599a8b3528547fba00da34dafbff5c04"


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok: bool, text: str) -> None:
    if not ok:
        raise ValueError(text)


def load(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()
    require(re.fullmatch(r"[0-9]{8}T[0-9]{6}Z_[a-f0-9]{6}", args.run_id) is not None,
            "invalid run-id")
    output = ROOT / "validation/board_z100/registered_response_bank_v1_static_v2" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "z100-registered-response-bank-static-check/1",
              "run_id": args.run_id, "status": "RUNNING", "vendor_invoked": False,
              "rtl_simulation_invoked": False, "checks": [], "bindings": {}}
    path = output / "result.json"
    try:
        require(sha(BASE) == EXPECTED_BASE and sha(CANDIDATE) == EXPECTED_CANDIDATE,
                "base/candidate hash mismatch")
        base_text = BASE.read_text(encoding="utf-8")
        candidate_text = CANDIDATE.read_text(encoding="utf-8")
        old = "wire response_bank=read_pending ? response_bank_q : req_bank;"
        new = "wire response_bank=response_bank_q;"
        require(base_text.count(old) == 1 and candidate_text == base_text.replace(old, new, 1),
                "candidate is not the exact one-expression change")
        require("assign out_valid=enabled&&read_pending&&ovalid[response_bank];" in base_text and
                "if(request_fire&&!read_pending)response_bank_q<=req_bank;" in base_text,
                "valid-domain response owner invariant source changed")
        manifest = load(MANIFEST)
        require(len(manifest.get("sources", [])) == 28 and manifest.get("top") ==
                "z100_native_row20_shared_pool_address_shared_local_control_v12" and
                manifest.get("part") == "xc7z100ffg900-2" and
                manifest.get("clock") == {"name": "row_clk", "period_ns": 10.0} and
                manifest.get("expected_dsp48e1") == 2016,
                "source manifest identity mismatch")
        names = set()
        for source in manifest["sources"]:
            p = ROOT / source["path"]
            require(p.is_file() and sha(p) == source["sha256"],
                    f"frozen RTL source mismatch: {source['path']}")
            names.add(source["name"])
        require(len(names) == 28 and "z100_feature_banks_pingpong_writepipe_v7.sv" in names,
                "manifest source names are not unique or bank RTL absent")

        source_review = load(SOURCE_REVIEW)
        boolean = load(BOOLEAN_REVIEW)
        require(source_review.get("status") == "PASS_EXACT_SINGLE_EXPRESSION_CHANGE_ONLY" and
                source_review.get("rtl_miter_passed") is False and
                source_review.get("fullcore_numeric_passed") is False,
                "primary source review must remain explicitly pre-simulation")
        require(boolean.get("status") == "PASS_BOUNDED_BOOLEAN_VALID_DOMAIN_ONLY" and
                boolean.get("cases") == 256 and boolean.get("valid_cases") == 32 and
                boolean.get("invalid_selection_differences") == 64,
                "primary bounded host proof scope/result changed")

        tb = MITER.read_text(encoding="utf-8")
        for token in ("REGISTERED_RESPONSE_BANK_MITER_PASS", "old_out_valid!==new_out_valid",
                      "old_out_epoch!==new_out_epoch || old_out_data!==new_out_data",
                      "byte_value(bank,0,0)", "fill_bank(1);", "simultaneous_same_bank_retire_and_request",
                      "reset_pending_response();", "issue_bad_epoch();", "retire_read();"):
            require(token in tb, f"directed testbench coverage marker missing: {token}")
        require("if (!old_out_valid)" in tb or "if(!old_out_valid)" in tb,
                "valid-domain data comparison rule missing")
        require("for(integer lane=2;lane<256;lane=lane+1)" in tb,
                "directed byte-mask oracle missing")

        runner_text = RUNNER.read_text(encoding="utf-8")
        queue_text = QUEUE.read_text(encoding="utf-8")
        compile(RUNNER.read_text(encoding="utf-8"), str(RUNNER), "exec")
        compile(QUEUE.read_text(encoding="utf-8"), str(QUEUE), "exec")
        require("set_false_path" not in runner_text and "set_multicycle_path" not in runner_text and
                "create_pblock" not in runner_text and "resize_pblock" not in runner_text and
                "report_timing -unconstrained" not in runner_text,
                "runner contains a forbidden constraint/unsupported report command")
        require("wait_phase1" in queue_text and "review_z100_A_default_physopt_route_v1.py" in queue_text and
                "LEGAL_ROUTE_SETUP_TIMING_FAILED" in queue_text and
                "PHASE1_TIMING_PASS_STAGE2_IMPLEMENTATION_SKIPPED" in queue_text,
                "conditional phase-1 review gate missing")

        module_spec = importlib.util.spec_from_file_location("z100_response_runner_static", RUNNER)
        require(module_spec is not None and module_spec.loader is not None,
                "cannot load route Tcl generator")
        runner = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(runner)
        external = Path("C:/appload/2026.1/Vivado/bin/xvlog.bat")
        external_binding = runner.rel(external)
        require(external_binding == "external/C/appload/2026.1/Vivado/bin/xvlog.bat" and
                runner.resolve_binding(external_binding) == external.resolve(),
                "external/C path binding does not round-trip")
        require(runner.LOCK_NAME == "Local\\Z100_Vivado_Implementation",
                "runner does not use the project-wide Vivado serialization mutex")
        with tempfile.TemporaryDirectory(prefix="response_bank_tcl_static_") as tmp:
            tmp_path = Path(tmp)
            miter_sources, miter_top = runner.stage_miter(tmp_path / "miter_build", {}, {})
            miter_names = [p.name for p in miter_sources]
            require(miter_top == "tb_z100_registered_response_bank_miter_v1" and
                    "z100_feature_banks_writepipe_4k_v5.sv" in miter_names and
                    "z100_feature_banks_4read_writepipe_4k_v5.sv" in miter_names and
                    len(miter_sources) == 5,
                    "miter compile closure omits a required RAM leaf or has wrong source count")
            leaf_text = next(p for p in miter_sources if p.name == "z100_feature_banks_writepipe_4k_v5.sv").read_text(encoding="utf-8")
            child_text = next(p for p in miter_sources if p.name == "z100_feature_banks_4read_writepipe_4k_v5.sv").read_text(encoding="utf-8")
            require("module z100_feature_banks_writepipe_4k_v5" in leaf_text and
                    "z100_feature_banks_writepipe_4k_v5 #" in child_text,
                    "miter module dependency closure is incomplete")
            tcl = runner.create_route_tcl(ROOT / "build/v12p_d46da432/rtl", tmp_path, manifest)
            tcl_text = tcl.read_text(encoding="utf-8")
            expected_sequence = ["synth_design -top", "create_clock -name row_clk -period 10",
                                 "opt_design", "place_design -directive Default",
                                 "phys_opt_design\n", "phys_opt_design -hold_fix",
                                 "route_design -directive Default"]
            positions = [tcl_text.index(item) for item in expected_sequence]
            require(positions == sorted(positions), "fresh route Tcl phase order changed")
            for checkpoint, marker in (("post_synth.dcp", "z100_identity synth_opt 2"),
                                       ("post_place.dcp", "z100_identity placed 8"),
                                       ("post_default_physopt.dcp", "z100_identity default_physopt 8"),
                                       ("post_hold_fix.dcp", "z100_identity hold_fix 8"),
                                       ("post_route.dcp", "z100_identity routed 8")):
                require(tcl_text.index(checkpoint) < tcl_text.index(marker),
                        f"checkpoint is not saved before its stage report: {checkpoint}")
            for forbidden in ("set_false_path", "set_multicycle_path", "create_pblock", "route_design -unconstrained"):
                require(forbidden not in tcl_text, f"forbidden flow command: {forbidden}")
            result["generated_tcl_sha256"] = sha(tcl)
        for p in (BASE, CANDIDATE, MANIFEST, MITER, RUNNER, QUEUE,
                  SOURCE_REVIEW, BOOLEAN_REVIEW):
            result["bindings"][p.relative_to(ROOT).as_posix()] = sha(p)
        result["checks"] = [
            {"check": "exact_one_line_rtl_diff", "status": "PASS"},
            {"check": "28_source_manifest_hashes", "status": "PASS"},
            {"check": "primary_boolean_and_source_review_bindings", "status": "PASS"},
            {"check": "directed_miter_static_coverage", "status": "PASS"},
            {"check": "python_runner_queue_syntax", "status": "PASS"},
            {"check": "external_path_roundtrip_shared_mutex_and_miter_leaf_closure", "status": "PASS"},
            {"check": "conditional_fresh_route_tcl_and_checkpoint_order", "status": "PASS"},
        ]
        result["status"] = "PASS_STATIC_OFFLINE_ONLY"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": path.relative_to(ROOT).as_posix(),
                      "checks": result["checks"], "error": result.get("error")}))
    return 0 if result["status"] == "PASS_STATIC_OFFLINE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
