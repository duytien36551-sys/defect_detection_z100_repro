# Single cold transition, volatile state only, no graph retry.
if {[catch {exec py -B {hardware_workspace/gpt_softpack_build_plan01/prepare_transition.py} --verify {hardware_workspace/gpt_softpack_launch02}} e]} {puts stderr $e;exit 2}
source {hardware_workspace/gpt_acp_transport02/acp_handoff_xsdb_v1.tcl}
proc regval {name} {
    set text [rrd $name]
    if {![regexp {:[[:space:]]*([0-9a-fA-F]+)} $text -> hex]} {error "Cannot parse register $name"}
    scan $hex %x value
    return [expr {$value & 0xffffffff}]
}
proc read_word {address} {
    set value [lindex [mrd -value $address 1] 0]
    if {[string is integer -strict $value]} {return [expr {$value & 0xffffffff}]}
    if {[regexp -nocase {^0x([0-9a-f]+)$} $value -> hex]} {scan $hex %x parsed; return $parsed}
    error "Invalid MMIO response at $address: $value"
}
proc read_sctlr {} {
    set text [rrd cp15 1 sctlr]
    if {![regexp {:[[:space:]]*([0-9a-fA-F]+)} $text -> hex]} {error "Cannot parse SCTLR"}
    scan $hex %x value
    return [expr {$value & 0xffffffff}]
}
proc stop_target {id} {
    targets -set $id
    if {[catch {stop} error] && ![string match {*Already stopped*} $error]} {error $error}
}
proc find_targets {} {
    set fpga {}; set cpu0 {}; set cpu1 {}
    foreach properties [targets -target-properties] {
        if {[catch {dict get $properties target_id} id] || [catch {dict get $properties name} name]} {continue}
        set lower [string tolower $name]
        if {[string match {*xc7z100*} $lower]} {lappend fpga [list $id $name]}
        if {[string match {*cortex-a9*#0*} $lower]} {lappend cpu0 [list $id $name]}
        if {[string match {*cortex-a9*#1*} $lower]} {lappend cpu1 [list $id $name]}
    }
    if {[llength $fpga] != 1 || [llength $cpu0] != 1 || [llength $cpu1] != 1} {
        error "Expected unique xc7z100 and Cortex-A9 #0/#1 targets"
    }
    set ids [list [lindex [lindex $fpga 0] 0] [lindex [lindex $cpu0 0] 0] [lindex [lindex $cpu1 0] 0]]
    if {[llength [lsort -unique $ids]] != 3} {error "FPGA and CPU target IDs must be distinct"}
    puts "TARGETS $fpga $cpu0 $cpu1"
    return $ids
}
set cpu0_id {}
set cpu1_id {}
proc with_owned_breakpoint {breakpoint label body} {
    set code [catch {uplevel 1 $body} result options]
    if {[catch {bpremove $breakpoint} cleanup_error]} {
        set cleanup_message "cleanup of $label breakpoint $breakpoint failed; breakpoint state unknown: $cleanup_error"
        if {$code} {append result "; $cleanup_message"; return -options $options $result}
        error $cleanup_message
    }
    if {$code} {return -options $options $result}
}

proc wait_for_fsbl_loop {cpu0_id loop_begin loop_end} {
    set fsbl_bp [bpadd -addr $loop_begin -type hw]
    with_owned_breakpoint $fsbl_bp {FSBL Loop} {
        con
        after 3000
        stop_target $cpu0_id
        set fsbl_pc [regval pc]
        if {$fsbl_pc < $loop_begin || $fsbl_pc >= $loop_end} {error "Matched FSBL did not stop in its byte-reviewed Loop"}
    }
}

proc capture_pl {cpu0} {
    targets -set $cpu0
    rwr cpsr [expr {([regval cpsr] | 0xc0) & ~0x20}]
    rwr pc 0x28000
    con
    after 100
    stop_target $cpu0
    if {[regval pc] != 0x2805c} {error "Capture did not reach hold"}
    return [mrd -value 0x21000 26]
}



proc run_batch {} {
 global cpu0_id cpu1_id
 connect
 after 1500
 lassign [find_targets] fpga_id cpu0_id cpu1_id
 stop_target $cpu1_id
 stop_target $cpu0_id
 puts "BEFORE_RESET_CPU0 [rrd]"
 set old [mrd -value 0x5000c0 18]
 puts "BEFORE_RESET_BOARD $old"
 if {[lindex $old 0]!=1 || [lindex $old 1]!=8 || [lindex $old 6]!=42044 || [lindex $old 16]!=44 || [lindex $old 17]!=0 || [read_word 0x774280]!=0 || [read_word 0x1debf4]!=42000} {error "Expected healthy idle source graph"}
 if {([read_word 0xf800025c]&15)!=0 || ([read_word 0xf8000910]&15)!=8} {error "JTAG/OCM changed"}
    if {[read_word 0x28000] != 0xf10c00c0} {error "OCM capture changed"}
    if {[read_word 0x28004] != 0xe59f0054} {error "OCM capture changed"}
    if {[read_word 0x28008] != 0xe3a01a21} {error "OCM capture changed"}
    if {[read_word 0x2800c] != 0xe3a02010} {error "OCM capture changed"}
    if {[read_word 0x28010] != 0xe4903004} {error "OCM capture changed"}
    if {[read_word 0x28014] != 0xe4813004} {error "OCM capture changed"}
    if {[read_word 0x28018] != 0xe2522001} {error "OCM capture changed"}
    if {[read_word 0x2801c] != 0x1afffffb} {error "OCM capture changed"}
    if {[read_word 0x28020] != 0xe59f003c} {error "OCM capture changed"}
    if {[read_word 0x28024] != 0xe3a0200a} {error "OCM capture changed"}
    if {[read_word 0x28028] != 0xe4903004} {error "OCM capture changed"}
    if {[read_word 0x2802c] != 0xe4813004} {error "OCM capture changed"}
    if {[read_word 0x28030] != 0xe2522001} {error "OCM capture changed"}
    if {[read_word 0x28034] != 0x1afffffb} {error "OCM capture changed"}
    if {[read_word 0x28038] != 0xee113f10} {error "OCM capture changed"}
    if {[read_word 0x2803c] != 0xe5813000} {error "OCM capture changed"}
    if {[read_word 0x28040] != 0xe3a00a21} {error "OCM capture changed"}
    if {[read_word 0x28044] != 0xe3a02004} {error "OCM capture changed"}
    if {[read_word 0x28048] != 0xee070f3a} {error "OCM capture changed"}
    if {[read_word 0x2804c] != 0xe2800020} {error "OCM capture changed"}
    if {[read_word 0x28050] != 0xe2522001} {error "OCM capture changed"}
    if {[read_word 0x28054] != 0x1afffffb} {error "OCM capture changed"}
    if {[read_word 0x28058] != 0xf57ff04f} {error "OCM capture changed"}
    if {[read_word 0x2805c] != 0xeafffffe} {error "OCM capture changed"}
    if {[read_word 0x28060] != 0x43c20000} {error "OCM capture changed"}
    if {[read_word 0x28064] != 0x43c20100} {error "OCM capture changed"}



 set first [capture_pl $cpu0_id]
 after 50
 set second [capture_pl $cpu0_id]
 puts "PRE_RESET_PL_FIRST $first"
 puts "PRE_RESET_PL_SECOND $second"
 if {$first ne $second || [lindex $second 0]!=0x5a4e4331 || [lindex $second 4]!=0x81 || [lindex $second 5]!=0 || [lindex $second 6]!=0} {error "PL not quiet"}
    rst -system -stop
    after 1000
    lassign [find_targets] fpga_id cpu0_id cpu1_id
    stop_target $cpu1_id
    stop_target $cpu0_id
    puts "AFTER_SYSTEM_RESET [rrd]"
    if {([read_word 0xf800025c]&15) != 0 || ([read_word 0xf8000910]&15) != 8 || ([read_sctlr]&0x1005) != 0} {error "Reset state unexpected"}
    set tx [::acp_handoff_v1::open_transaction]
    ::acp_handoff_v1::note_external_preflight_complete $tx
    targets -set $fpga_id
    fpga -file {hardware_workspace/gpt_ctrp_phys01/export_01/artifacts/z100_platform.bit}
    ::acp_handoff_v1::note_bit_programmed $tx
    targets -set $cpu0_id
    dow {hardware_workspace/gpt_acp01/compat_epoch30000/fsbl.elf}
    wait_for_fsbl_loop $cpu0_id 0xfe80 0xfe88
    stop_target $cpu1_id
    stop_target $cpu0_id
    if {([read_sctlr]&0x1005) != 0} {error "FSBL caches/MMU enabled"}
    ::acp_handoff_v1::note_ps_initialized $tx
    dow {hardware_workspace/gpt_mmio_fault_capture_build01/capture.elf}
    set initialized [capture_pl $cpu0_id]
    puts "INITIALIZED_PL $initialized"
    if {[lindex $initialized 0] != 0x5a4e4331 || [lindex $initialized 4] != 0x81 || [lindex $initialized 5] != 0 || [lindex $initialized 6] != 0} {error "New PL not ready"}



 dow {hardware_workspace/gpt_softpack_build_plan01/build_output/native_board_pool.elf}
 dow -data {hardware_workspace/gpt_perf_o2_irq02/irq_guard.bin} 0x1abb480
 ::acp_handoff_v1::note_elf_downloaded $tx
 set observed_bp [bpadd -addr 0x122590 -type hw]
 with_owned_breakpoint $observed_bp boot-observed {
  set handoff [::acp_handoff_v1::handoff $tx $cpu0_id {ARM Cortex-A9 MPCore #0} 0x100000 ARM 0x14763c ARM 1 5000]
  after 500
  stop_target $cpu0_id
  if {[regval pc]!=0x122590} {error "Boot observation not reached"}
  set boot [mrd -value 0x7742c0 16]
  puts "BOOT_RECEIPT $boot"
  if {[lindex $boot 0]!=0x41504344 || [lindex $boot 2]!=1 || [lindex $boot 3]!=0 || [lindex $boot 6]!=1 || [lindex $boot 7]!=1 || [lindex $boot 8]!=1 || [lindex $boot 4]!=[dict get $handoff receipt_lo] || [lindex $boot 5]!=[dict get $handoff receipt_hi]} {error "Scoped qualification handoff rejected"}
  mrd -bin -file {hardware_workspace/gpt_softpack_launch02/board_once01/boot.bin} 0x7742c0 16
 }
 con
 after 7000
 stop_target $cpu0_id
 set board [mrd -value 0x5000c0 18]
 puts "NEW_BOARD $board"
 if {[lindex $board 0]!=1 || [lindex $board 1]!=8 || [lindex $board 6]!=49000 || [lindex $board 16]!=0 || [lindex $board 17]!=0 || [read_word 0x774280]!=0 || [read_word 0x1debe4]!=49000} {error "Scoped graph did not reach healthy LISTENING"}
 con
 puts {ACP_SCOPED49000_LISTENING_FOR_QUALIFICATION_NO_RETRY}
}
if {[catch {run_batch} e options]} {
 puts stderr "ACP_SCOPED_LAUNCH_FAILED: $e"
 foreach id [list $cpu0_id $cpu1_id] {if {$id ne {}} {catch {stop_target $id}}}
 exit 1
}
exit 0
