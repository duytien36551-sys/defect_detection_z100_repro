# Failure diagnostics only. Bind the current epoch49000 ELF and retained OCM.
if {[catch {exec py -B {hardware_workspace/gpt_softpack_launch02/prepare_capture.py} --verify} e]} {puts stderr $e;exit 2}
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

proc save_failure {} {
 global cpu0_id cpu1_id
 connect
 lassign [find_targets] fpga_id cpu0_id cpu1_id
 stop_target $cpu1_id
 puts "CPU1_REGISTERS [rrd]"
 stop_target $cpu0_id
 puts "CPU0_REGISTERS_BEFORE [rrd]"
 puts "CPU0_CP15_1 [rrd cp15 1]"
 puts "CPU0_CP15_2 [rrd cp15 2]"
 puts "STOP [mrd -value 0x774280 1]"
 if {[read_word 0x1debe4] != 49000} {error "Wrong firmware"}
 if {([read_word 0xf8000910]&15) != 8 || [read_sctlr] != 0x08c5187d} {error "Unexpected memory/cache mapping"}
 mrd -bin -file {hardware_workspace/gpt_softpack_launch02/failure_capture01/board_prefix_dap.bin} 0x5000c0 32768
 mrd -bin -file {hardware_workspace/gpt_softpack_launch02/failure_capture01/irq_guard.bin} 0x1abb480 1024
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

 set pl [capture_pl $cpu0_id]
 puts "FAILURE_PL $pl"
 mrd -bin -file {hardware_workspace/gpt_softpack_launch02/failure_capture01/pl.bin} 0x21000 27
    if {[read_word 0x13a4b0] != 0xe3a03001} {error "L1I helper changed"}
    if {[read_word 0x13a4b4] != 0xee403f10} {error "L1I helper changed"}
    if {[read_word 0x13a4b8] != 0xe3a03000} {error "L1I helper changed"}
    if {[read_word 0x13a4bc] != 0xee073f15} {error "L1I helper changed"}
    if {[read_word 0x13a4c0] != 0xf57ff04f} {error "L1I helper changed"}
    if {[read_word 0x13a4c4] != 0xe12fff1e} {error "L1I helper changed"}
 dow -data {hardware_workspace/gpt_softpack_launch02/snapshot_scoped.bin} 0x28100
    if {[read_word 0x28100] != 0xf10c00c0} {error "Snapshot code changed"}
    if {[read_word 0x28104] != 0xf57ff04f} {error "Snapshot code changed"}
    if {[read_word 0x28108] != 0xf57ff06f} {error "Snapshot code changed"}
    if {[read_word 0x2810c] != 0xe3a0c001} {error "Snapshot code changed"}
    if {[read_word 0x28110] != 0xee120f50} {error "Snapshot code changed"}
    if {[read_word 0x28114] != 0xe3500000} {error "Snapshot code changed"}
    if {[read_word 0x28118] != 0x1a000024} {error "Snapshot code changed"}
    if {[read_word 0x2811c] != 0xee120f10} {error "Snapshot code changed"}
    if {[read_word 0x28120] != 0xe59f108c} {error "Snapshot code changed"}
    if {[read_word 0x28124] != 0xe0000001} {error "Snapshot code changed"}
    if {[read_word 0x28128] != 0xe59f1088} {error "Snapshot code changed"}
    if {[read_word 0x2812c] != 0xe1500001} {error "Snapshot code changed"}
    if {[read_word 0x28130] != 0x1a00001e} {error "Snapshot code changed"}
    if {[read_word 0x28134] != 0xe3a0c002} {error "Snapshot code changed"}
    if {[read_word 0x28138] != 0xe5902000} {error "Snapshot code changed"}
    if {[read_word 0x2813c] != 0xe59f3078} {error "Snapshot code changed"}
    if {[read_word 0x28140] != 0xe1520003} {error "Snapshot code changed"}
    if {[read_word 0x28144] != 0x1a000019} {error "Snapshot code changed"}
    if {[read_word 0x28148] != 0xe5902014} {error "Snapshot code changed"}
    if {[read_word 0x2814c] != 0xe59f306c} {error "Snapshot code changed"}
    if {[read_word 0x28150] != 0xe1520003} {error "Snapshot code changed"}
    if {[read_word 0x28154] != 0x1a000015} {error "Snapshot code changed"}
    if {[read_word 0x28158] != 0xe3a0c003} {error "Snapshot code changed"}
    if {[read_word 0x2815c] != 0xe59f0060} {error "Snapshot code changed"}
    if {[read_word 0x28160] != 0xe5901000} {error "Snapshot code changed"}
    if {[read_word 0x28164] != 0xe201100f} {error "Snapshot code changed"}
    if {[read_word 0x28168] != 0xe3510008} {error "Snapshot code changed"}
    if {[read_word 0x2816c] != 0x1a00000f} {error "Snapshot code changed"}
    if {[read_word 0x28170] != 0xe59f0050} {error "Snapshot code changed"}
    if {[read_word 0x28174] != 0xe3a01a22} {error "Snapshot code changed"}
    if {[read_word 0x28178] != 0xe3a02c09} {error "Snapshot code changed"}
    if {[read_word 0x2817c] != 0xe4903004} {error "Snapshot code changed"}
    if {[read_word 0x28180] != 0xe4813004} {error "Snapshot code changed"}
    if {[read_word 0x28184] != 0xe2522001} {error "Snapshot code changed"}
    if {[read_word 0x28188] != 0x1afffffb} {error "Snapshot code changed"}
    if {[read_word 0x2818c] != 0xe3a00a22} {error "Snapshot code changed"}
    if {[read_word 0x28190] != 0xe3a02e12} {error "Snapshot code changed"}
    if {[read_word 0x28194] != 0xee070f3a} {error "Snapshot code changed"}
    if {[read_word 0x28198] != 0xe2800020} {error "Snapshot code changed"}
    if {[read_word 0x2819c] != 0xe2522001} {error "Snapshot code changed"}
    if {[read_word 0x281a0] != 0x1afffffb} {error "Snapshot code changed"}
    if {[read_word 0x281a4] != 0xf57ff04f} {error "Snapshot code changed"}
    if {[read_word 0x281a8] != 0xe3a0c000} {error "Snapshot code changed"}
    if {[read_word 0x281ac] != 0xeafffffe} {error "Snapshot code changed"}
    if {[read_word 0x281b0] != 0xeafffffe} {error "Snapshot code changed"}
    if {[read_word 0x281b4] != 0xffffc000} {error "Snapshot code changed"}
    if {[read_word 0x281b8] != 0x4e0000} {error "Snapshot code changed"}
    if {[read_word 0x281bc] != 0x15de6} {error "Snapshot code changed"}
    if {[read_word 0x281c0] != 0x515de6} {error "Snapshot code changed"}
    if {[read_word 0x281c4] != 0xf8000910} {error "Snapshot code changed"}
    if {[read_word 0x281c8] != 0x5000c0} {error "Snapshot code changed"}
 rwr lr 0x2805c
 rwr pc 0x13a4b0
 con
 after 100
 stop_target $cpu0_id
 if {[regval pc] != 0x2805c} {error "L1I helper return failed"}
 rwr pc 0x28100
 con
 after 100
 stop_target $cpu0_id
 if {[regval pc] != 0x281ac || [regval r12] != 0} {error "CPU snapshot failed mapping validation"}
 mrd -bin -file {hardware_workspace/gpt_softpack_launch02/failure_capture01/cpu_prefix.bin} 0x22000 2304
 rwr pc 0x2805c
 stop_target $cpu1_id
 stop_target $cpu0_id
 puts {FIRST_FAILURE_CAPTURED_NO_RESET_NO_RETRY_NO_SOURCE_MAINTENANCE}
}
if {[catch {save_failure} e options]} {
 puts stderr "CAPTURE_FAILED: $e"
 foreach id [list $cpu0_id $cpu1_id] {if {$id ne {}} {catch {stop_target $id}}}
 exit 1
}
exit 0
