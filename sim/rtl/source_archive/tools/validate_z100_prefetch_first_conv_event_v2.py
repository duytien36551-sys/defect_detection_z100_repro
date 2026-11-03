"""Prepare or run the reviewed V2 source-bound two-bank firstConv16 regression.

The real load and tile children are the existing firstConv fixture.  The
private V2 prefetch controller owns independent load/compute bank cursors;
this validator binds its sources and keeps the original numeric goldens
unchanged.  --prepare-only does not start a simulator.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
BASE = ROOT / "validation/board_z100/directory_full_conv_tile_compute/20261025T141715.197837Z/result.json"
GOLD = ROOT / "validation/board_z100/first_conv_full_node_fixture/20261025T190809.773575Z/result.json"
CREF = ROOT / "validation/board_z100/first_conv_full_node_c_reference/20261025T190827.057066Z/result.json"
V10 = ROOT / "validation/board_z100/feature_address_shared_v10_compute/20261025T190545.372805Z/result.json"
PREFETCH_RTL = HW / "conv_prefetch_control_v2/z100_conv_prefetch_control_v2.sv"
PREFETCH_TB = HW / "conv_prefetch_control_v3/tb_z100_conv_prefetch_control_v3.sv"
PREFETCH_PROOF = ROOT / "validation/board_z100/icarus_control/20261026T011555.727758Z/result.json"
PREFETCH_REVIEW = ROOT / "validation/board_z100/conv_prefetch_control_root_review/20261026T012000.749562Z/result.json"
ROW_PLAN = ROOT / "deployment/build/z100_native_row_commands_v2/20261025T062641.961558Z/row_plan.h"
VENDOR = Path("C:/appload/2026.1/Vivado/bin")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def repo_path(name: str) -> Path:
    """Resolve workspace-relative and proof-encoded external paths safely."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("external/"):
        parts = normalized.split("/")
        require(len(parts) >= 3 and re.fullmatch(r"[A-Za-z]", parts[1]) is not None,
                f"invalid external proof path: {name}")
        path = Path(parts[1] + ":/", *parts[2:]).resolve()
    else:
        path = (ROOT / Path(normalized)).resolve()
        require(path.is_relative_to(ROOT.resolve()), f"proof path escapes workspace: {name}")
    return path


def proof_snapshot(path: Path, bound: dict[str, str], label: str) -> dict:
    require(path.is_file(), f"missing {label} proof: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    require(str(report.get("status", "")).startswith("PASS"), f"{label} proof is not PASS")
    before = report.get("source_sha256_before")
    after = report.get("source_sha256_after")
    artifacts = report.get("artifact_sha256")
    require(isinstance(before, dict) and before and before == after,
            f"{label} proof source integrity is not closed")
    require(isinstance(artifacts, dict) and artifacts, f"{label} proof artifact hashes missing")
    for name, expected in {**after, **artifacts}.items():
        require(isinstance(name, str) and re.fullmatch(r"[0-9a-f]{64}", str(expected)) is not None,
                f"invalid {label} digest entry: {name}")
        file_path = repo_path(name)
        require(file_path.is_file(), f"missing {label} bound file: {name}")
        actual = sha256(file_path)
        require(actual == expected, f"{label} proof hash mismatch: {name}")
        add_bound(bound, name, actual, label)
    report_name = str(path.relative_to(ROOT)).replace("\\", "/")
    add_bound(bound, report_name, sha256(path), label)
    return report


def add_bound(bound: dict[str, str], name: str, digest: str, label: str) -> None:
    previous = bound.get(name)
    require(previous is None or previous == digest,
            f"conflicting {label} proof hash for {name}: {previous} != {digest}")
    bound[name] = digest


def verify_prefetch_proof(bound: dict[str, str]) -> dict:
    review = json.loads(PREFETCH_REVIEW.read_text(encoding="utf-8"))
    require(review.get("status") == "ROOT_REVIEWED_ICARUS_TWO_BANK_PREFETCH_CONTROL_C_PLAN_AND_FAILURE_GATES_NOT_PIXELS",
            "two-bank controller root review status")
    require(review.get("numerical_pixel_integration_accepted") is False,
            "controller-only review must not claim numeric integration")
    proof_name = str(review.get("proof", ""))
    proof_path = repo_path(proof_name)
    require(sha256(proof_path) == review.get("proof_sha256"), "two-bank controller proof review hash")
    proof = proof_snapshot(proof_path, bound, "two-bank controller")
    require(proof.get("status") == "PASS_PROJECT_LOCAL_ICARUS_SOURCE_BOUND_CONTROL_TB_ONLY",
            "two-bank Icarus control proof status")
    require(proof.get("top") == "tb_z100_conv_prefetch_control_v3",
            "V3 controller testbench was not the proved top")
    require(proof.get("marker") == "CONV_PREFETCH_CONTROL_PASS", "controller proof marker")
    required = {str(PREFETCH_RTL.relative_to(ROOT)).replace("\\", "/"),
                str(PREFETCH_TB.relative_to(ROOT)).replace("\\", "/")}
    source_map = proof.get("source_sha256_after", {})
    require(required.issubset({name.replace("\\", "/") for name in source_map}),
            "controller proof does not bind both V2 RTL and V3 TB")
    add_bound(bound, str(PREFETCH_REVIEW.relative_to(ROOT)).replace("\\", "/"), sha256(PREFETCH_REVIEW), "controller review")
    return review


def verify_generic_numeric(path: Path, bound: dict[str, str]) -> dict:
    proof = proof_snapshot(path, bound, "generic firstConv numeric")
    require(proof.get("status") ==
            "PASS_PRIVATE_GENERIC_FIRST_CONV_EVENT16_TILES_FULL_NATIVE_DDR_OIHW_C_PARITY_NOT_FULLGRAPH",
            "completed full generic firstConv16 numeric proof required")
    simulation = proof.get("simulation", {})
    require(simulation.get("tiles") == 16 and simulation.get("raw_records") == 102400 and
            simulation.get("post_records") == 102400 and simulation.get("packed_words") == 25600,
            "generic firstConv numeric coverage is incomplete")
    return proof


def replace_source(source: str, old: str, new: str, reason: str) -> str:
    require(old in source, f"Missing source seam for {reason}: {old}")
    return source.replace(old, new)


def read_first_conv_rows(build: Path) -> list[list[int]]:
    text = ROW_PLAN.read_text(encoding="utf-8")
    match = re.search(r"z100_halos\[189\]\s*=\s*\{(.*?)\};", text, re.S)
    require(match is not None, "C row-plan does not contain z100_halos[189]")
    rows = [[int(value) for value in row.split(",")]
            for row in re.findall(r"\{([0-9,]+)\}", match.group(1))][:16]
    require(len(rows) == 16 and all(len(row) == 13 for row in rows),
            "C firstConv descriptor cardinality/width")
    require(all(row[:3] == [3, 640, 640] and row[6:] == [20, 320, 320, 16, 3, 2, 1]
                for row in rows), "C firstConv descriptor geometry")
    halos = [value for row in rows for value in row[3:7]]
    (build / "event_halos.hex").write_text("".join(f"{value:03x}\n" for value in halos), encoding="ascii")
    return rows


def event_rtl() -> str:
    return r'''
wire event_quiet=!pf_active_control&&!pf_reader_busy&&!pf_codec_active&&!wb_pending&&!wb_active&&!wb_wbusy&&!wb_awowned&&!wb_bvalid&&wb_bdelay==0&&!pp_active&&!pp_rbusy&&!pd_active&&!pd_busy&&!shared_active&&!shared_mem_active&&!ft_active&&!ft_scheduler_active;
wire event_load_quiet=!pf_active_control&&!pf_reader_busy&&!pf_codec_active;
wire event_write_quiet=!wb_pending&&!wb_active&&!wb_wbusy&&!wb_awowned&&!wb_bvalid&&wb_bdelay==0;
z100_conv_prefetch_control_v2 prefetch_event_control(.clk(clk),.rst_n(rst_n),.cancel(cancel),.recover(1'b0),.recovery_drained(1'b0),
 .cmd_valid(event_start),.cmd_ready(event_ready),.cmd_epoch(EPOCH),.cmd_job_base(32'd1),.cmd_token_base(TOKEN_BASE),.cmd_tag_base(32'h53000000),
 .cmd_tiles(8'd16),.cmd_output_height(10'd320),.cmd_first_bank(1'b0),
 .source_leased(lease_valid&&!lease_mode),.destination_reserved(1'b1),
 .descriptor_valid(1'b1),.descriptor_ready(event_descriptor_ready),.descriptor_epoch(event_epoch),.descriptor_index(event_index),
 .descriptor_input_y(event_halos[event_index*4]),.descriptor_input_rows(event_halos[event_index*4+1]),
 .descriptor_output_y(event_halos[event_index*4+2]),.descriptor_output_rows(event_halos[event_index*4+3]),
 .descriptor_runs(32'd320),.descriptor_windows(32'd2880),.next_descriptor(event_index),
.load_valid(load_valid),.load_ready(pf_command_ready),.load_bank(load_bank),.load_job_tag(load_job),
 .load_input_y(load_input_y),.load_input_rows(load_input_rows),
 .load_done(pf_done),.load_committed(pf_result),.load_fault(pf_fault||pf_reader_fault||pf_codec_error),.load_epoch(pf_epoch),.load_done_bank(active_load_bank),
 .tile_valid(tile_valid),.tile_ready(ft_command_ready),.tile_bank(tile_bank),.tile_job_tag(event_job),.tile_token_base(event_token),.tile_tag_base(event_tag),
 .tile_input_y(event_iy),.tile_input_rows(event_ir),.tile_output_y(event_oy),.tile_output_rows(event_or),
 .tile_done(ft_done),.tile_fault(ft_fault||ft_scheduler_fault||wb_fault),.tile_done_epoch(ft_epoch),.tile_done_job(ft_job),.tile_done_bank(tile_bank),
 .load_quiet(event_load_quiet),.tile_write_quiet(event_write_quiet),.all_io_quiet(event_quiet),
 .epoch(event_epoch),.child_cancel(event_cancel),.active(event_active),.needs_drain(event_drain),.done(event_done),.fault(event_fault),.fault_code(event_code),.committed_tiles(event_tiles));
assign ft_command=tile_valid;
integer event_loads=0,event_tile_starts=0,event_completed=0,node_commits=0;
integer prefetch_compute_overlap_cycles=0,prefetch_compute_write_cycles=0;
integer observed_event_active_cycles=0,observed_loader_active_cycles=0,observed_loader_reader_cycles=0;
integer observed_tile_active_cycles=0,observed_conv_owned_cycles=0,observed_load_conv_busy_cycles=0;
integer observed_load_words_while_conv=0,observed_raw_stall_cycles=0,observed_post_stall_cycles=0;
integer observed_writeback_active_cycles=0,observed_writeback_busy_cycles=0;
reg [1:0] event_load_bank_seen=0,event_tile_bank_seen=0,event_published_banks=0,bank_published=0;
reg active_load_bank=0;
wire [1:0] feature_bank_store_valid=dut.feature_window.store.bank_store_valid;
wire [31:0] feature_bank0_epoch=dut.feature_window.store.gen_bank[0].unit.active_epoch;
wire [31:0] feature_bank1_epoch=dut.feature_window.store.gen_bank[1].unit.active_epoch;
always @(posedge clk) if(rst_n) begin
 if(event_active)observed_event_active_cycles=observed_event_active_cycles+1;
 if(pf_active_control)observed_loader_active_cycles=observed_loader_active_cycles+1;
 if(pf_reader_busy)observed_loader_reader_cycles=observed_loader_reader_cycles+1;
 if(ft_active)observed_tile_active_cycles=observed_tile_active_cycles+1;
 if(dut.conv_owned)observed_conv_owned_cycles=observed_conv_owned_cycles+1;
 if(pf_active_control&&pf_reader_busy&&dut.conv_owned)observed_load_conv_busy_cycles=observed_load_conv_busy_cycles+1;
 if(pf_active&&pf_v&&pf_ready&&dut.conv_owned)observed_load_words_while_conv=observed_load_words_while_conv+1;
 if(raw_valid&&!raw_ready)observed_raw_stall_cycles=observed_raw_stall_cycles+1;
 if(post_valid&&!post_ready)observed_post_stall_cycles=observed_post_stall_cycles+1;
 if(wb_active)observed_writeback_active_cycles=observed_writeback_active_cycles+1;
 if(wb_wbusy)observed_writeback_busy_cycles=observed_writeback_busy_cycles+1;
 if(event_fault)$fatal(1,"Two-bank first producer event fault code=%d",event_code);
 if(event_start&&event_ready)event_completed=0;
 if(event_descriptor_ready)begin
  if(event_index>=16||event_epoch!=EPOCH)$fatal(1,"Descriptor identity/epoch");
  if(event_halos[event_index*4+2]!=event_index*20||event_halos[event_index*4+3]!=20)$fatal(1,"Descriptor output geometry");
 end
 if(load_valid&&pf_command_ready)begin
  node_load_ar=0;node_load_base=PF_BASE+load_input_y*2560;
  if(load_job!=event_loads+1||load_input_y!=event_loads*40-(event_loads!=0?1:0)||load_input_rows!=(event_loads==0?40:41)||load_bank!=(event_loads%2))$fatal(1,"Load descriptor/bank progression");
  if(bank_published[load_bank])bank_published[load_bank]=0;
  active_load_bank=load_bank;
  event_load_bank_seen[load_bank]=1'b1;event_loads=event_loads+1;
 end
 if(pf_done)begin
  if(!pf_result||pf_epoch!=EPOCH||pf_generation!=32'd6901||active_load_bank!=load_bank||pf_reader_busy||pf_codec_active)$fatal(1,"Load result not committed/drained for selected bank/source generation");
  if(!feature_bank_store_valid[active_load_bank]||
     (active_load_bank?feature_bank1_epoch:feature_bank0_epoch)!=EPOCH||
     dut.feature_window.load_owner_valid)$fatal(1,"Selected feature bank was not published after its real commit");
  bank_published[active_load_bank]=1'b1;event_published_banks[active_load_bank]=1'b1;
 end
 if(tile_valid&&ft_command_ready)begin
  if(!bank_published[tile_bank]||!feature_bank_store_valid[tile_bank]||
     (tile_bank?feature_bank1_epoch:feature_bank0_epoch)!=EPOCH||
     (dut.feature_window.load_owner_valid&&dut.feature_window.load_owner_bank==tile_bank))$fatal(1,"Compute before selected bank publication or during same-bank load");
  if(event_job!=event_tile_starts+1||event_oy!=event_tile_starts*20||event_or!=20||event_iy!=event_tile_starts*40-(event_tile_starts!=0?1:0)||event_ir!=(event_tile_starts==0?40:41)||tile_bank!=(event_tile_starts%2))$fatal(1,"Tile descriptor/bank progression");
  ft_seen<=0;event_tile_bank_seen[tile_bank]=1'b1;event_tile_starts=event_tile_starts+1;
 end
 if(pf_active_control&&pf_reader_busy&&dut.conv_owned)begin
  if(pf_bank_pin==dut.source_bank_q)$fatal(1,"Overlapping prefetch targeted compute-owned bank");
  prefetch_compute_overlap_cycles=prefetch_compute_overlap_cycles+1;
 end
 if(pf_active&&pf_v&&pf_ready&&dut.conv_owned)begin
  if(!dut.feature_window.load_owner_valid||dut.feature_window.load_owner_bank==dut.source_bank_q)$fatal(1,"Feature writes overlapped compute on the same bank");
  prefetch_compute_write_cycles=prefetch_compute_write_cycles+1;
 end
 if(ft_done)begin
  if(ft_seen!=={1600{1'b1}}||ft_job!=node_commits+1)$fatal(1,"Tile incomplete or identity reordered");
  node_commits=node_commits+1;
  $display("FIRST_CONV_PREFETCH_TILE_DONE tile=%0d cycles=%0d",node_commits,ft_cycle);
 end
 if(event_done)begin
  if(event_tiles!=16||node_commits!=16||!event_quiet)$fatal(1,"Producer published before all tile writes/drain");event_completed=event_completed+1;
 end
end
reg[511:0] expected_ddr[0:25599];
initial begin
 $readmemh("expected_raw_words.hex",expected_raw_words);$readmemh("expected_post_words.hex",expected_post_words);
 $readmemh("expected_packed_words.hex",expected_packed_words);$readmemh("expected_ddr_words.hex",expected_ddr);
 for(fi=0;fi<262144;fi=fi+1)wb_memory[fi]=64'h5a1bc43df609728e;
 #250;repeat(5)@(negedge clk);rst_n=1;
 @(negedge clk);pf_active=1;old_load_bank=0;acquire_load_lease(0);
 @(negedge clk);event_start=1;#1;if(!event_ready)$fatal(1,"First two-bank event not admitted");@(posedge clk);#1;@(negedge clk);event_start=0;
 wait(event_done);repeat(3)@(negedge clk);
 if(event_completed!=1||event_loads!=16||event_tile_starts!=16||node_commits!=16||ft_done_count!=16||ft_rows!=320||ft_param_completions!=16||ft_pack_configs!=16||
    run_count!=5120||window_request_count!=46080||raw_beats!=102400||post_beats!=102400||packed_beats!=25600||
    pf_loaded!=26200||pf_commands!=16||pf_ars!=13100||pf_rbeats!=209600||
    wb_completed!=16||wb_scheduled!=16||wb_packed!=25600||wb_aws!=12800||wb_ws!=204800||wb_bs!=12800||
    pp_configs!=4608||pp_commands!=64||pp_ars!=240||pp_beats!=3712||pd_requests!=16||pd_forwards!=16||
    shared_ars!=13340||shared_rs!=213312||shared_owner0!=209600||shared_owner1!=3712||!event_quiet||
    event_load_bank_seen!=2'b11||event_tile_bank_seen!=2'b11||event_published_banks!=2'b11||
    prefetch_compute_overlap_cycles==0||prefetch_compute_write_cycles==0)$fatal(1,"Full two-bank firstConv execution coverage/overlap");
 for(fi=0;fi<25600;fi=fi+1)for(fj=0;fj<8;fj=fj+1)begin
  if(wb_memory[fi*8+fj]!==expected_ddr[fi][fj*64+:64])$fatal(1,"Full firstConv native tensor word=%d beat=%d",fi,fj);ft_checked=ft_checked+1;
 end
 for(fi=204800;fi<262144;fi=fi+1)begin if(wb_memory[fi]!==64'h5a1bc43df609728e)$fatal(1,"Full producer reserved guard modified");ft_guards=ft_guards+1;end
 release_load_lease();@(negedge clk);pf_active=0;
 if(lease_valid)$fatal(1,"Reader lease not drained/released");
 $display("FIRST_CONV_PREFETCH_PASS tiles=16 rows=320 runs=5120 descriptors=46080 raw_records=102400 post_records=102400 packed_words=25600 input_R=209600 parameter_directory_R=3712 output_W=204800 output_B=12800 guards=57344 load_banks=%0d compute_banks=%0d published_banks=%0d overlap_cycles=%0d overlap_feature_writes=%0d event_active_cycles=%0d loader_active_cycles=%0d loader_reader_cycles=%0d tile_active_cycles=%0d conv_owned_cycles=%0d load_conv_busy_cycles=%0d load_words_while_conv=%0d raw_stall_cycles=%0d post_stall_cycles=%0d writeback_active_cycles=%0d writeback_busy_cycles=%0d",
   event_load_bank_seen,event_tile_bank_seen,event_published_banks,prefetch_compute_overlap_cycles,prefetch_compute_write_cycles,
   observed_event_active_cycles,observed_loader_active_cycles,observed_loader_reader_cycles,observed_tile_active_cycles,observed_conv_owned_cycles,
   observed_load_conv_busy_cycles,observed_load_words_while_conv,observed_raw_stall_cycles,observed_post_stall_cycles,
   observed_writeback_active_cycles,observed_writeback_busy_cycles);
 $finish;
end
initial begin #400000000;$fatal(1,"Whole two-bank firstConv producer watchdog");end
'''


def prepare_build(build: Path, bound: dict[str, str]) -> tuple[list[Path], Path, list[Path], dict[str, str], dict[str, str]]:
    base = proof_snapshot(BASE, bound, "single-tile numerical")
    golden = proof_snapshot(GOLD, bound, "firstConv golden")
    cref = proof_snapshot(CREF, bound, "C reference")
    feature = proof_snapshot(V10, bound, "address-shared feature")
    require(cref.get("raw_values") == 1638400 and cref.get("post_bytes") == 1638400,
            "complete unchanged C reference")

    rows = read_first_conv_rows(build)
    oldtb = next((Path(name) for name in base["commands"][0]["args"]
                  if Path(name).name == "tb_z100_first_conv_full_tile.sv"), None)
    require(oldtb is not None and oldtb.is_file(), "source-bound full-tile testbench missing")
    copied: list[Path] = []
    for source in oldtb.parent.iterdir():
        if source.suffix.lower() in (".hex", ".vh"):
            destination = build / source.name
            shutil.copyfile(source, destination)
            copied.append(source)

    fixture = repo_path(golden["fixture"])
    golden_assets = {
        "expected_raw_words.hex": "expected_raw_words.hex",
        "expected_post_words.hex": "expected_post_words.hex",
        "expected_packed_words.hex": "expected_packed_words.hex",
        "input_native_DDR.hex": "feature_DDR.hex",
        "expected_native_DDR.hex": "expected_ddr_words.hex",
    }
    golden_hashes: dict[str, str] = {}
    for source_name, target_name in golden_assets.items():
        source = fixture / source_name
        require(source.is_file(), f"missing original firstConv golden: {source_name}")
        source_hash = sha256(source)
        relative_name = str(source.relative_to(ROOT)).replace("\\", "/")
        expected = next((digest for name, digest in golden.get("artifact_sha256", {}).items()
                         if name.replace("\\", "/") == relative_name), None)
        require(expected == source_hash, f"firstConv golden does not match its proof: {source_name}")
        shutil.copyfile(source, build / target_name)
        require(sha256(build / target_name) == source_hash, f"copied firstConv golden changed: {target_name}")
        copied.append(source)
        golden_hashes[source_name] = source_hash

    tb_text = oldtb.read_text(encoding="utf-8")
    tb_text = replace_source(tb_text, "module tb_z100_first_conv_full_tile;",
                             "module tb_z100_first_conv_prefetch_event;", "testbench module")
    tb_text = replace_source(tb_text, "expected_raw_words [0:6399]",
                             "expected_raw_words [0:102399]", "full-node raw golden extent")
    tb_text = replace_source(tb_text, "expected_post_words [0:6399]",
                             "expected_post_words [0:102399]", "full-node post golden extent")
    tb_text = replace_source(tb_text, "expected_packed_words [0:1599]",
                             "expected_packed_words [0:25599]", "full-node packed golden extent")
    top_wires = r'''
integer node_load_ar=0;reg[31:0] node_load_base=0;reg event_start=0;
wire event_ready,event_done,event_fault,event_cancel,event_active,event_drain;
wire[3:0] event_code;wire[7:0] event_tiles,event_index;wire event_descriptor_ready;
reg[9:0] event_halos[0:63];initial $readmemh("event_halos.hex",event_halos);
wire[31:0] event_epoch,event_load_job,event_job,event_token,event_tag;
wire[9:0] load_input_y,load_input_rows,event_iy,event_ir,event_oy,event_or;
wire load_valid,load_bank,tile_valid,tile_bank;wire[31:0] load_job;
'''
    tb_text = tb_text.replace("module tb_z100_first_conv_prefetch_event;",
                              "module tb_z100_first_conv_prefetch_event;\n" + top_wires)
    tb_path = build / "tb_z100_first_conv_prefetch_event.sv"
    tb_path.write_text(tb_text, encoding="utf-8")

    compute_body = (oldtb.parent / "full_tile_compute_body.vh").read_text(encoding="utf-8")
    require("task load_full_tile_DDR;" in compute_body, "full-tile initial/task seam missing")
    body = compute_body.split("task load_full_tile_DDR;", 1)[0]
    body = replace_source(body, "reg ft_command=0;", "wire ft_command;", "tile command ownership")
    body = replace_source(body, ".cmd_token_base(TOKEN_BASE)", ".cmd_token_base(event_token)", "per-tile token base")
    body = replace_source(body, ".cmd_tag_base(32'h53000000)", ".cmd_tag_base(event_tag)", "per-tile tag base")
    body = replace_source(body, ".cmd_job_tag(32'd1)", ".cmd_job_tag(event_job)", "per-tile job identity")
    body = replace_source(body, ".cmd_input_y(10'd0)", ".cmd_input_y(event_iy)", "load input y")
    body = replace_source(body, ".cmd_input_rows(10'd40)", ".cmd_input_rows(event_ir)", "load input rows")
    body = replace_source(body, ".cmd_output_y(10'd0)", ".cmd_output_y(event_oy)", "tile output y")
    body = replace_source(body, ".cmd_output_rows(10'd20)", ".cmd_output_rows(event_or)", "tile output rows")
    body = replace_source(body, "TOKEN_BASE+run_count", "event_token+(run_count%320)", "tile-local run token")
    body = replace_source(body, "run_count>=320", "run_count>=5120", "whole-node run count")
    body = replace_source(body, "fi>=2880", "fi>=46080", "whole-node window count")
    body = replace_source(body,
                          "fi=window_request_count;fy=fi/144;fg=fi%9;fsegment=(fi/9)%16;fsy=fy*2-1+fg/3;",
                          "fi=window_request_count;fy=(fi%2880)/144;fg=fi%9;fsegment=((fi%2880)/9)%16;fsy=event_oy*2+fy*2-1+fg/3;",
                          "tile-local window geometry")
    body = replace_source(body, "32'h53000000+fi", "event_tag+(fi%2880)", "per-tile window tag")
    body = replace_source(body, "((fsy>=0&&fsy<40)?fsy*40:0)",
                          "((fsy>=0&&fsy<640)?(fsy-event_iy)*40:0)", "tile-local halo row address")
    body = replace_source(body, "fsy<40", "fsy<640", "full input y range")
    body = replace_source(body, "fi>=6400", "fi>=102400", "whole-node numeric records")
    body = replace_source(body, "TOKEN_BASE+fi/20", "event_token+(fi%6400)/20", "tile-local numeric token")
    body = replace_source(body, "packed_beats>=1600", "packed_beats>=25600", "whole-node packed words")
    body = replace_source(body, "packed_beats==1599", "packed_beats%1600==1599", "per-tile packed LAST")
    body = replace_source(body, "expected_packed_words[packed_address]",
                          "expected_packed_words[(packed_address/400)*6400+(event_oy+(packed_address%400)/20)*20+packed_address%20]",
                          "full-node packed golden address")
    (build / "full_tile_compute_body.vh").write_text(body + event_rtl(), encoding="utf-8")

    prefetch_support = build / "hybrid_prefetch_support.vh"
    support = prefetch_support.read_text(encoding="utf-8")
    support = replace_source(support,
        "reg pf_active=0,pf_command_valid=0,pf_bank_pin=1,old_load_bank=0,compute_source_bank=0,pf_completed=0;",
        "reg pf_active=0,old_load_bank=0,pf_completed=0;\nwire pf_command_valid,pf_bank_pin,compute_source_bank;\nassign pf_command_valid=load_valid;assign pf_bank_pin=load_bank;assign compute_source_bank=tile_bank;",
        "independent prefetch and compute bank pins")
    support = replace_source(support, ".cmd_source_generation(32'd6901)",
                             ".cmd_source_generation(32'd6901)", "held input-source generation")
    support = replace_source(support, ".cmd_full_height(10'd40)", ".cmd_full_height(10'd640)", "full input height")
    support = replace_source(support, ".cmd_first_row(10'd0)", ".cmd_first_row(load_input_y)", "per-load input start")
    support = replace_source(support, ".cmd_height(10'd40)", ".cmd_height(load_input_rows)", "per-load halo height")
    support = replace_source(support, "pf_memory[0:1599]", "pf_memory[0:25599]", "full input DDR model")
    support = replace_source(support, "PF_BASE+pf_ars*128", "node_load_base+node_load_ar*128", "per-halo DDR address check")
    support = replace_source(support, "pf_ars=pf_ars+1;", "pf_ars=pf_ars+1;node_load_ar=node_load_ar+1;", "per-halo DDR burst index")
    support = replace_source(support,
        "if(pf_active&&pf_v&&pf_ready)begin\n            pf_loaded=pf_loaded+1;\n            if(dut.feature_window.load_owner_bank!==0)$fatal(1,\"prefetch overwrote computation bank\");\n            if(pf_bank_pin==0)pf_bank_latch_probes=pf_bank_latch_probes+1;\n            if(dut.conv_owned)begin\n                pf_overlap_loads=pf_overlap_loads+1;\n                if(stream_valid&&stream_ready)pf_simultaneous=pf_simultaneous+1;\n            end\n        end",
        "if(pf_active&&pf_v&&pf_ready)begin\n            pf_loaded=pf_loaded+1;\n            if(dut.feature_window.load_owner_bank!==pf_bank_pin)$fatal(1,\"prefetch load-bank ownership changed\");\n            if(dut.conv_owned)begin\n                if(dut.feature_window.load_owner_bank===dut.source_bank_q)$fatal(1,\"prefetch overwrote compute bank\");\n                pf_overlap_loads=pf_overlap_loads+1;\n                if(stream_valid&&stream_ready)pf_simultaneous=pf_simultaneous+1;\n            end\n        end",
        "per-bank feature store ownership counters")
    support = replace_source(support,
        "if(pf_active&&lease_valid&&!lease_mode&&dut.conv_owned&&pf_reader_busy)begin\n            pf_overlap_cycles=pf_overlap_cycles+1;\n            if(dut.source_bank_q!==0||feature_active_epoch!=EPOCH)$fatal(1,\"prefetch changed live Conv source bank/epoch\");\n        end",
        "if(pf_active_control&&lease_valid&&!lease_mode&&dut.conv_owned&&pf_reader_busy)begin\n            if(pf_bank_pin==dut.source_bank_q)$fatal(1,\"prefetch DDR read overlaps the compute-owned bank\");\n            pf_overlap_cycles=pf_overlap_cycles+1;\n        end",
        "real alternate-bank DDR overlap")
    prefetch_support.write_text(support, encoding="utf-8")

    shared_read = build / "compute_shared_read_support_v4.vh"
    shared_text = replace_source(shared_read.read_text(encoding="utf-8"), "PF_BASE+102400", "PF_BASE+1638400", "full input DDR source range")
    shared_read.write_text(shared_text, encoding="utf-8")
    write_support = build / "compute_write_support.vh"
    write_text = write_support.read_text(encoding="utf-8")
    for old, new, reason in [
        ("33'h80000", "33'h200000", "full node write reservation"),
        (".cmd_full_height(wb_height_q)", ".cmd_full_height(10'd320)", "full output height"),
        (".cmd_first_row(10'd0)", ".cmd_first_row(event_oy)", "per-tile output row start"),
        ("wb_memory[0:65535]", "wb_memory[0:262143]", "full node output DDR model"),
        ("wb_address_q<=WB_BASE+wb_scheduled*131072", "wb_address_q<=WB_BASE", "per-tile output base"),
        ("WB_BASE+524288", "WB_BASE+2097152", "full node output range"),
    ]:
        write_text = replace_source(write_text, old, new, reason)
    write_support.write_text(write_text, encoding="utf-8")
    directory_support = build / "full_tile_directory_support.vh"
    directory_text = directory_support.read_text(encoding="utf-8")
    directory_text = replace_source(directory_text, ".cmd_tag(32'd1)", ".cmd_tag(event_job)", "per-tile parameter directory tag")
    directory_text = replace_source(directory_text, "pd_descriptor_tag!=1", "pd_descriptor_tag!=event_job", "per-tile parameter directory identity")
    directory_support.write_text(directory_text, encoding="utf-8")

    substitutions = {
        "z100_feature_window20_payload_v8.sv": HW / "feature_address_shared_v10/z100_feature_window20_address_shared_v10.sv",
        "z100_native_row20_shared_pool_payload_v8.sv": HW / "feature_address_shared_v10/z100_native_row20_shared_pool_address_shared_v10.sv",
        "z100_maxpool_window20_rowbase_v2.sv": HW / "pool_tapxy_v9/z100_maxpool_window20_tapxy_v3.sv",
    }
    rtl = [substitutions.get(Path(name).name, Path(name))
           for name in base["commands"][0]["args"][2:] if Path(name) != oldtb]
    rtl.extend([PREFETCH_RTL, tb_path])
    sources: list[Path] = [Path(__file__).resolve(), ROW_PLAN, BASE, GOLD, CREF, V10,
                           PREFETCH_RTL, PREFETCH_TB, PREFETCH_PROOF, PREFETCH_REVIEW, oldtb]
    sources.extend(copied)
    sources.extend(rtl)
    before: dict[str, str] = {}
    for source in sources:
        require(source.is_file(), f"missing source-bound RTL/fixture: {source}")
        name = (str(source.relative_to(ROOT)).replace("\\", "/") if source.is_relative_to(ROOT)
                else "external/" + source.as_posix().replace(":", ""))
        add_bound(bound, name, sha256(source), "firstConv integration")
        before[name] = sha256(source)

    integration = {
        "reviewed_version": 2,
        "numeric_top": "tb_z100_first_conv_prefetch_event",
        "numeric_pass_marker_expected": "FIRST_CONV_PREFETCH_PASS",
        "controller_module": "z100_conv_prefetch_control_v2",
        "controller_top_proved": "tb_z100_conv_prefetch_control_v3",
        "controller_pass_marker_proved": "CONV_PREFETCH_CONTROL_PASS",
        "controller": str(PREFETCH_RTL.relative_to(ROOT)).replace("\\", "/"),
        "controller_control_proof": str(PREFETCH_PROOF.relative_to(ROOT)).replace("\\", "/"),
        "generic_controller_tb": str(PREFETCH_TB.relative_to(ROOT)).replace("\\", "/"),
        "load_bank_pin": "pf_bank_pin=load_bank",
        "compute_bank_pin": "compute_source_bank=tile_bank",
        "tile_load_overlap": "required from pf_reader_busy and dut.conv_owned with distinct physical banks",
        "descriptor_index_connection": "next_descriptor(event_index)",
        "feature_store_valid_hierarchy": (
            "dut.feature_window.store.bank_store_valid is the two-bit output of the physical "
            "z100_feature_banks_pingpong_writepipe_v7 store instance"
        ),
        "feature_epoch_hierarchy": (
            "dut.feature_window.store.gen_bank[bank].unit.active_epoch is the selected "
            "z100_feature_banks_4read_writepipe_4k_v5 bank output"
        ),
        "feature_publication": (
            "per-bank bank_store_valid and bank-specific active_epoch checked before tile admission; "
            "admission blocks only when a live load owner targets the compute bank"
        ),
        "held_source_generation": "6901 for every halo from the event-leased committed input source",
        "load_job_identity": "load_job is checked independently against ordered firstConv tile jobs",
        "review_corrections": [
            "connect next_descriptor to event_index",
            "permit simultaneous opposite-bank feature loading during tile admission",
            "preserve committed input source_generation 6901 across all halos",
        ],
        "descriptor_rows": rows,
        "golden_sha256": golden_hashes,
    }
    return rtl, tb_path, copied, integration, dict(bound)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true",
                        help="bind sources and generate the two-bank numerical test without simulation")
    parser.add_argument("--generic-proof", type=Path,
                        help="completed full generic firstConv16 numerical result required before RTL execution")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = ROOT / "validation/board_z100/prefetch_first_conv_event_v2" / stamp
    build = ROOT / "build" / f"pfce2_{stamp[-14:]}"
    output.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report_path = output / "result.json"
    result: dict = {
        "status": "RUNNING",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "build_dir": str(build.relative_to(ROOT)),
        "commands": [],
        "board_access": False,
        "fullgraph_execution_accepted": False,
        "full_pipeline_30fps_accepted": False,
        "scope": (
            "Numerical firstConv16 integration using the selected epoch200 PIN640 INT8 fixture, the C-derived "
            "sixteen 20-row descriptors, actual DDR halo loads, both published feature banks, actual tile "
            "compute/write children, unchanged full raw/post/packed/native-DDR goldens and the frozen C reference. "
            "The V2 controller owns independent load and tile cursors. The RTL fixture reserves and commits output "
            "through its TB write path; it does not prove graph-slot publication, later consumers, PS/HP/MMIO, "
            "whole-model execution or board correctness. Counters report simulated cycles under the existing "
            "fixture-injected stalls and are not physical FPS measurements."
        ),
    }
    bound: dict[str, str] = {}
    source_before: dict[str, str] = {}
    try:
        verify_prefetch_proof(bound)
        numeric_proof = None
        generic_path: Path | None = None
        if args.generic_proof is not None:
            generic_path = args.generic_proof.resolve()
            require(generic_path.is_relative_to(ROOT.resolve()), "generic firstConv proof must be inside workspace")
            numeric_proof = verify_generic_numeric(generic_path, bound)
        if not args.prepare_only:
            require(numeric_proof is not None,
                    "RTL execution gated on an explicitly supplied completed generic firstConv numeric proof")
            for tool in ("xvlog.bat", "xelab.bat", "xsim.bat"):
                require((VENDOR / tool).is_file(), f"required Vivado tool missing: {VENDOR / tool}")

        rtl, tb_path, copied, integration, source_before = prepare_build(build, bound)
        result.update(
            prefetch_control_review=str(PREFETCH_REVIEW.relative_to(ROOT)).replace("\\", "/"),
            prefetch_control_proof=str(PREFETCH_PROOF.relative_to(ROOT)).replace("\\", "/"),
            generic_numeric_proof=str(generic_path.relative_to(ROOT)).replace("\\", "/") if numeric_proof else None,
            integration=integration,
            source_sha256_before=source_before,
        )
        report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        if args.prepare_only:
            result["status"] = "PREPARED_TWO_BANK_PREFETCH_FIRST_CONV16_V2_NOT_RTL_EXECUTED"
        else:
            def run(label: str, argv: list[Path | str]) -> str:
                command = list(map(str, argv))
                process = subprocess.run(
                    command,
                    cwd=build,
                    env=dict(os.environ, XILINX_LOCAL_USER_DATA="no"),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                (output / f"{label}.log").write_text(process.stdout, encoding="utf-8", errors="replace")
                result["commands"].append({"label": label, "args": command, "return_code": process.returncode})
                require(process.returncode == 0 and not re.search(r"^\s*(?:ERROR:|Fatal:)", process.stdout, re.M),
                        f"strict actual {label} failed")
                return process.stdout

            run("xvlog", [VENDOR / "xvlog.bat", "-sv", *rtl])
            run("xelab", [VENDOR / "xelab.bat", "-mt", "2", "-L", "unimacro_ver", "-L", "unisims_ver",
                           "tb_z100_first_conv_prefetch_event", "glbl", "-s", "prefetch_first_conv_sim"])
            simulation_log = run("xsim", [VENDOR / "xsim.bat", "prefetch_first_conv_sim", "-runall"])
            marker = re.findall(r"^FIRST_CONV_PREFETCH_PASS (.+)$", simulation_log, re.M)
            tile_markers = [int(value) for value in re.findall(r"^FIRST_CONV_PREFETCH_TILE_DONE tile=(\d+)", simulation_log, re.M)]
            require(len(marker) == 1, "complete two-bank numerical marker missing or duplicated")
            require(tile_markers == list(range(1, 17)), "all sixteen real tile completions")
            simulation = {key: int(value) for key, value in re.findall(r"([A-Za-z_]+)=(\d+)", marker[0])}
            require(simulation.get("tiles") == 16 and simulation.get("raw_records") == 102400 and
                    simulation.get("post_records") == 102400 and simulation.get("packed_words") == 25600,
                    "full unchanged firstConv numeric coverage")
            require(simulation.get("load_banks") == 3 and simulation.get("compute_banks") == 3 and
                    simulation.get("published_banks") == 3 and simulation.get("overlap_cycles", 0) > 0 and
                    simulation.get("overlap_feature_writes", 0) > 0,
                    "both banks and real compute/prefetch overlap were not observed")
            result.update(status="PASS_PRIVATE_TWO_BANK_PREFETCH_FIRST_CONV16_NUMERIC_NOT_FULLGRAPH",
                          simulation=simulation)
    except Exception as exc:  # Fail closed and leave a reviewable report.
        result.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")

    if not source_before:
        source_before = dict(bound)
    source_after = {name: sha256(repo_path(name)) for name in source_before}
    result["source_sha256_before"] = source_before
    result["source_sha256_after"] = source_after
    if source_before and source_after != source_before:
        result.update(status="FAILED_SOURCE_INTEGRITY", error="bound source/artifact changed during validation")
    result["artifact_sha256"] = {
        str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
        for folder in (output, build)
        for path in folder.rglob("*")
        if path.is_file() and path != report_path
    }
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
                      "error": result.get("error")}))
    return int(result["status"].startswith("FAILED"))


if __name__ == "__main__":
    raise SystemExit(main())
