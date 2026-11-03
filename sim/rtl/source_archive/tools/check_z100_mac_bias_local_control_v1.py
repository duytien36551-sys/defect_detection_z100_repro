from __future__ import annotations

import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "build/v12p_d46da432/rtl/z100_window_mac.sv"
CANDIDATE = ROOT / "deployment/hardware/z100_2026/mac_bias_local_control_v1/z100_window_mac.sv"
TB = ROOT / "deployment/hardware/z100_2026/mac_bias_local_control_v1/tb_z100_mac_bias_local_control_v1.sv"
OUT = CANDIDATE.parent
ROUTE_REPORT = ROOT / "validation/board_z100/v12_A_default_physopt_route/20261027t212850z_default_physopt/setup_paths_routed.rpt"
STAGE1_REPORT = ROOT / "validation/board_z100/timing_first_stage1_supplement/20261027T143133.391619Z/result.json"
BASE_SHA256 = "f573c82fab313161d4097eedafcb7669026dbf6e4c29efa313f0a575fe29e474"
ROUTE_SHA256 = "4c91200c5d2288fdef41a75e8b985db114b80d92cf038f06310b143b6e655c38"
STAGE1_SHA256 = "5863e6bd43ce98e0cd3c4f7a96723bccb1876bd1177375ccd1e3bf196b09b2b5"

INSERTION = '''    // Four local config-state replicas drive four independent 256-bit bias banks.
    // The state machines intentionally mirror the frozen config FSM in the same
    // cycle; keep is a synthesis intent, not proof that Vivado retains replicas.
    genvar bias_group, bias_lane;
    generate for(bias_group=0;bias_group<4;bias_group=bias_group+1) begin : gen_bias_local_control
        (* keep="true" *) reg local_loading_q;
        (* keep="true" *) reg local_bias_loaded_q;
        wire local_bias_write = rst_n && !cancel && cfg_bias_valid &&
                                local_loading_q && !cfg_begin && !cfg_commit &&
                                !local_bias_loaded_q;
        always @(posedge clk) begin
            if(!rst_n || cancel) begin
                local_loading_q<=1'b0;
                local_bias_loaded_q<=1'b0;
            end else if(cfg_begin && cfg_begin_ready) begin
                local_bias_loaded_q<=1'b0;
                if(cfg_epoch==0 || cfg_groups==0 || cfg_groups>1024 ||
                   cfg_weight_valid || cfg_bias_valid || cfg_commit)
                    local_loading_q<=1'b0;
                else
                    local_loading_q<=1'b1;
            end else if(local_loading_q) begin
                if(cfg_commit && cfg_commit_ready) begin
                    local_loading_q<=1'b0;
                end else begin
                    if(cfg_weight_valid && cfg_weight_ready &&
                       written_groups>=expected_groups)
                        local_loading_q<=1'b0;
                    if(cfg_bias_valid && cfg_bias_ready) begin
                        if(local_bias_loaded_q)
                            local_loading_q<=1'b0;
                        else
                            local_bias_loaded_q<=1'b1;
                    end
                end
            end
        end
        for(bias_lane=0;bias_lane<8;bias_lane=bias_lane+1) begin : gen_bias_lane
            always @(posedge clk) begin
                if(local_bias_write)
                    bias[bias_group*8+bias_lane] <=
                        cfg_bias[(bias_group*8+bias_lane)*32 +: 32];
            end
        end
    end endgenerate
'''


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_candidate(base_text: str) -> str:
    payload = """                            for(l=0;l<32;l=l+1) bias[l]<=cfg_bias[l*32+:32];
                            bias_loaded<=1;"""
    if base_text.count(payload) != 1:
        raise ValueError("Frozen source payload write anchor did not match exactly once")
    text = base_text.replace(payload, "                            bias_loaded<=1;", 1)
    anchor = "    integer s,l,t,g;\n"
    if text.count(anchor) != 1:
        raise ValueError("Frozen source generate insertion anchor did not match exactly once")
    return text.replace(anchor, INSERTION + anchor, 1)


def original_step(loading: bool, bias_loaded: bool, inp: dict[str, bool]) -> tuple[bool, bool, bool]:
    rst_n = inp["rst_n"]
    cancel = inp["cancel"]
    begin = inp["cfg_begin"]
    commit = inp["cfg_commit"]
    weight_valid = inp["cfg_weight_valid"]
    bias_valid = inp["cfg_bias_valid"]
    idle = inp["idle"]
    bad_epoch = inp["bad_epoch"]
    bad_groups = inp["bad_groups"]
    overflow = inp["weight_overflow"]
    begin_ready = rst_n and idle and not loading and not cancel
    weight_ready = rst_n and loading and not begin and not commit and not cancel
    bias_ready = weight_ready
    commit_ready = rst_n and loading and not begin and not cancel

    next_loading, next_bias_loaded = loading, bias_loaded
    if not rst_n or cancel:
        next_loading, next_bias_loaded = False, False
    elif begin and begin_ready:
        next_bias_loaded = False
        invalid_begin = bad_epoch or bad_groups or weight_valid or bias_valid or commit
        next_loading = not invalid_begin
    elif loading:
        if commit and commit_ready:
            next_loading = False
        else:
            if weight_valid and weight_ready and overflow:
                next_loading = False
            if bias_valid and bias_ready:
                if bias_loaded:
                    next_loading = False
                else:
                    next_bias_loaded = True
    payload_write = bias_valid and bias_ready and not bias_loaded
    return next_loading, next_bias_loaded, payload_write


def candidate_step(local_loading: bool, local_bias_loaded: bool,
                   global_loading: bool, inp: dict[str, bool]) -> tuple[bool, bool, bool]:
    rst_n = inp["rst_n"]
    cancel = inp["cancel"]
    begin = inp["cfg_begin"]
    commit = inp["cfg_commit"]
    weight_valid = inp["cfg_weight_valid"]
    bias_valid = inp["cfg_bias_valid"]
    idle = inp["idle"]
    bad_epoch = inp["bad_epoch"]
    bad_groups = inp["bad_groups"]
    overflow = inp["weight_overflow"]
    begin_ready = rst_n and idle and not global_loading and not cancel
    weight_ready = rst_n and global_loading and not begin and not commit and not cancel
    bias_ready = weight_ready
    commit_ready = rst_n and global_loading and not begin and not cancel

    next_loading, next_bias_loaded = local_loading, local_bias_loaded
    if not rst_n or cancel:
        next_loading, next_bias_loaded = False, False
    elif begin and begin_ready:
        next_bias_loaded = False
        invalid_begin = bad_epoch or bad_groups or weight_valid or bias_valid or commit
        next_loading = not invalid_begin
    elif local_loading:
        if commit and commit_ready:
            next_loading = False
        else:
            if weight_valid and weight_ready and overflow:
                next_loading = False
            if bias_valid and bias_ready:
                if local_bias_loaded:
                    next_loading = False
                else:
                    next_bias_loaded = True
    payload_write = (rst_n and not cancel and bias_valid and local_loading and
                     not begin and not commit and not local_bias_loaded)
    return next_loading, next_bias_loaded, payload_write


def finite_state_check() -> dict[str, int | str]:
    names = ("rst_n", "cancel", "idle", "cfg_begin", "cfg_commit",
             "cfg_weight_valid", "cfg_bias_valid", "bad_epoch", "bad_groups",
             "weight_overflow")
    transitions = 0
    captures = 0
    simultaneous_overflow_bias = 0
    for loading, bias_loaded in itertools.product((False, True), repeat=2):
        for values in itertools.product((False, True), repeat=len(names)):
            inp = dict(zip(names, values))
            expected = original_step(loading, bias_loaded, inp)
            actual = candidate_step(loading, bias_loaded, loading, inp)
            if actual != expected:
                raise AssertionError({"state": (loading, bias_loaded), "inputs": inp,
                                      "original": expected, "candidate": actual})
            transitions += 1
            if expected[2]:
                captures += 1
            if (inp["cfg_weight_valid"] and inp["cfg_bias_valid"] and
                    inp["weight_overflow"] and loading and not inp["cfg_begin"] and
                    not inp["cfg_commit"] and not inp["cancel"] and inp["rst_n"] and
                    not bias_loaded):
                simultaneous_overflow_bias += 1
    if transitions != 4096 or captures == 0 or simultaneous_overflow_bias == 0:
        raise AssertionError("Finite-state space or required NBA corner was not exercised")
    return {"status": "PASS_FINITE_BOOLEAN_TRANSITION_MODEL", "transitions_checked": transitions,
            "accepted_first_bias_capture_cases": captures,
            "weight_overflow_and_first_bias_same_edge_cases": simultaneous_overflow_bias,
            "meaning": "one-step lockstep over all 2-state inputs and four loading/bias_loaded states; not RTL formal"}


def main() -> int:
    for path in (BASE, CANDIDATE, TB, ROUTE_REPORT, STAGE1_REPORT):
        if not path.is_file():
            raise FileNotFoundError(path)
    hashes = {"base_rtl": sha256(BASE), "candidate_rtl": sha256(CANDIDATE),
              "directed_tb": sha256(TB), "route_report": sha256(ROUTE_REPORT),
              "stage1_supplement": sha256(STAGE1_REPORT),
              "checker": sha256(Path(__file__).resolve())}
    if hashes["base_rtl"] != BASE_SHA256:
        raise ValueError("Frozen baseline RTL SHA-256 changed")
    if hashes["route_report"] != ROUTE_SHA256 or hashes["stage1_supplement"] != STAGE1_SHA256:
        raise ValueError("Bound stage1 route evidence SHA-256 changed")

    base_text = BASE.read_text(encoding="utf-8")
    candidate_text = CANDIDATE.read_text(encoding="utf-8-sig")
    if candidate_text != expected_candidate(base_text):
        raise ValueError("Candidate is not the exact bounded transformation of frozen source")
    if "module z100_window_mac_local_control_v1 #(" not in candidate_text:
        raise ValueError("Candidate public module identity changed")
    if "(* keep=\"true\" *) reg local_loading_q;" not in candidate_text or \
       "(* keep=\"true\" *) reg local_bias_loaded_q;" not in candidate_text:
        raise ValueError("Local state replication intent missing")
    if candidate_text.lower().count("dont_touch") != base_text.lower().count("dont_touch") or \
       candidate_text.lower().count("pblock") != base_text.lower().count("pblock"):
        raise ValueError("Candidate adds or removes a global preservation/placement directive")
    if "local_bias_write" not in candidate_text or "cfg_bias_ready" in \
       candidate_text[candidate_text.index("wire local_bias_write"):candidate_text.index("always @(posedge clk)", candidate_text.index("wire local_bias_write"))]:
        raise ValueError("Bias payload CE is not driven by local replica state")

    tb_text = TB.read_text(encoding="utf-8-sig")
    required_tb = ("z100_window_mac_local_control_v1_baseline", "z100_window_mac_local_control_v1 #",
                   "old_mac.bias[i]", "new_mac.bias[i]", "Weight overflow and first bias",
                   "cfg_begin pulse while already loading", "Reset during a fresh load",
                   "Output changed under backpressure", "new_out_data[lane*32+:32]!==expected_bias[lane]",
                   "new_mac.gen_bias_local_control[0].local_loading_q !== new_mac.loading",
                   "new_mac.gen_bias_local_control[3].local_bias_loaded_q !== old_mac.bias_loaded")
    missing = [needle for needle in required_tb if needle not in tb_text]
    if missing:
        raise ValueError(f"Directed miter missing required checks/cases: {missing}")

    fsm = finite_state_check()
    report = {
        "status": "PASS_STATIC_SOURCE_AND_FINITE_STATE_MODEL_ONLY",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "offline RTL source transformation and finite boolean config-FSM model only",
        "source_sha256": hashes,
        "route_context": {
            "setup_path_report": "validation/board_z100/v12_A_default_physopt_route/20261027t212850z_default_physopt/setup_paths_routed.rpt",
            "stage1_result": "validation/board_z100/timing_first_stage1_supplement/20261027T143133.391619Z/result.json",
            "reported_path": "native_mac/loading_reg -> native_mac/bias_reg[30][14]/CE",
            "reported_data_delay_ns": 10.680, "reported_wire_share_pct": 97.107,
            "reported_enable_net_fanout": 1024,
            "source_facts_supplied_by_primary": True
        },
        "candidate_geometry_intent": {"groups": 4, "lanes_per_group": 8,
                                       "payload_bits_per_local_enable": 256,
                                       "replica_state_bits_per_group": 2,
                                       "multipliers_or_accumulators_changed": False},
        "finite_state_model": fsm,
        "directed_tb": {"status": "AUTHORED_NOT_RUN", "baseline_module_alias_required": True,
                         "vendor_simulation_required": True},
        "vivado_synthesis_route": "NOT_RUN", "board": "NOT_TESTED",
        "limitations": [
            "The finite-state checker compares an exhaustive two-state abstract model; it is not RTL formal or simulation.",
            "The directed SystemVerilog miter has not been compiled or simulated.",
            "The keep attributes express intent only; synthesis must prove four replicas survive and each local CE drives at most 256 payload bits.",
            "No timing, placement, routing, resource, throughput, or hardware performance improvement is established.",
            "The candidate is not promoted and is not combined with stage2 or other experiments."
        ]
    }
    result_path = OUT / "static_review.json"
    if result_path.exists():
        raise FileExistsError(result_path)
    result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "status": "CANDIDATE_PREPARED_STATIC_ONLY",
        "baseline": {"path": str(BASE.relative_to(ROOT)), "sha256": hashes["base_rtl"]},
        "candidate": {"path": str(CANDIDATE.relative_to(ROOT)), "sha256": hashes["candidate_rtl"]},
        "directed_tb": {"path": str(TB.relative_to(ROOT)), "sha256": hashes["directed_tb"]},
        "checker": {"path": str(Path(__file__).resolve().relative_to(ROOT)), "sha256": hashes["checker"]},
        "report": {"path": str(result_path.relative_to(ROOT)), "sha256": sha256(result_path)},
        "bound_route_evidence": {
            str(ROUTE_REPORT.relative_to(ROOT)): hashes["route_report"],
            str(STAGE1_REPORT.relative_to(ROOT)): hashes["stage1_supplement"]
        },
        "validation": {"static_exact_diff": "PASS", "finite_state_model": fsm["status"],
                       "rtl_miter": "NOT_RUN", "full_core_regression": "NOT_RUN",
                       "synthesis": "NOT_RUN", "route": "NOT_RUN", "board": "NOT_TESTED"}
    }
    manifest_path = OUT / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidate": str(CANDIDATE),
                      "report": str(result_path), "manifest": str(manifest_path),
                      "transitions_checked": fsm["transitions_checked"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise
