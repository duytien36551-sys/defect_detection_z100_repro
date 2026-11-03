# Isolated OOC measurement. Optional fourth argument is a synth checkpoint for
# a cheap constraints-only preflight; no place/route occurs in that mode.
proc require {condition message} { if {!$condition} { error $message } }

proc clean_messages {directory phase} {
    foreach {severity suffix} {ERROR errors {CRITICAL WARNING} critical} {
        set path [file join $directory ${phase}_${suffix}.rpt]
        write_messages -severity [list $severity] -force $path
        set f [open $path r]; set content [read $f]; close $f
        foreach line [split $content \n] {
            if {[string trim $line] ne "" && ![string match "#*" [string trim $line]]} {
                error "$phase has $severity messages: $line"
            }
        }
    }
}

proc checked_constraints {directory phase period_ns} {
    set clocks [get_clocks -quiet]
    require [expr {[llength $clocks] == 1}] "Expected one clock"
    require [expr {[get_property NAME $clocks] eq "core_clk"}] "Wrong clock name"
    require [expr {abs([get_property PERIOD $clocks]-$period_ns) < 0.00001}] "Wrong clock period"
    set ins [get_ports -filter {DIRECTION == IN && NAME != clk}]
    set outs [get_ports -filter {DIRECTION == OUT}]
    require [expr {[llength $ins] == 1370 && [llength $outs] == 1072}] "OOC boundary bit count changed"
    set f [open [file join $directory ${phase}_ports.txt] w]
    puts $f "CLOCK core_clk PERIOD_NS $period_ns"
    foreach p $ins { puts $f "INPUT [get_property NAME $p] MIN_NS 0.100 MAX_NS 0.500" }
    foreach p $outs { puts $f "OUTPUT [get_property NAME $p] MIN_NS 0.000 MAX_NS 0.500" }
    close $f
    write_xdc -force [file join $directory ${phase}_effective.xdc]
    set checked [check_timing -verbose -return_string]
    set f [open [file join $directory check_timing_${phase}.rpt] w]; puts $f $checked; close $f
    set f [open [file join $directory unconstrained_internal_${phase}.rpt] w]; puts $f $checked; close $f
    foreach category {no_clock constant_clock pulse_width_clock unconstrained_internal_endpoints no_input_delay no_output_delay multiple_clock generated_clocks loops partial_input_delay partial_output_delay latch_loops} {
        set pattern [format {checking\s+%s\s+\(([0-9]+)\)} $category]
        require [regexp $pattern $checked ignored count] "Missing check_timing category $category"
        require [expr {$count == 0}] "Nonzero check_timing $category: $count"
    }
    clean_messages $directory $phase
    puts "REUSE_CONSTRAINT_PREFLIGHT phase=$phase inputs=[llength $ins] outputs=[llength $outs] period_ns=$period_ns check_categories=12 status=PASS"
}

proc screen_resources {directory phase} {
    set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
    set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]]
    set ram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
    set ram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
    set bram [expr {$ram36 + $ram18/2.0}]
    puts "REUSE_RESOURCES phase=$phase lut=$lut dsp=$dsp bram36_equivalent=$bram"
    require [expr {$lut <= 100000 && $dsp <= 1024 && $bram <= 256}] "Resource screen exceeded"
    report_utilization -file [file join $directory utilization_${phase}.rpt]
}

proc main {frequency_mhz build_dir evidence_dir {checkpoint ""}} {
    set script_dir [file dirname [file normalize [info script]]]
    set part xc7z100ffg900-2
    require [expr {[string first "2026.1" [version -short]] == 0}] "Requires Vivado2026.1"
    require [expr {$frequency_mhz in {100 200}}] "Frequency must be100 or200MHz"
    set period_ns [expr {1000.0 / double($frequency_mhz)}]
    set_param general.maxThreads 2
    file mkdir $build_dir
    file mkdir $evidence_dir
    if {$checkpoint ne ""} {
        open_checkpoint $checkpoint
    } else {
        create_project -force reuse_ooc [file join $build_dir project] -part $part
        read_verilog [file join $script_dir z100_tile_reuse_core.v]
        read_verilog [file join $script_dir z100_tile_reuse_core_ooc_top.v]
        synth_design -top z100_tile_reuse_core_ooc_top -part $part -mode out_of_context -flatten_hierarchy none
        write_checkpoint -force [file join $build_dir post_synth_unconstrained.dcp]
    }
    puts "REUSE_OOC_VERSION [version -short] DEVICE $part DEFAULT_SYNTHESIS_MAPPING=1"
    require [expr {[llength [get_sites -quiet BUFGCTRL_X0Y0]] == 1}] "Missing exploratory clock-source site"
    set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
    puts "REUSE_OOC_CLOCK_SOURCE_ASSUMPTION BUFGCTRL_X0Y0 (exploratory boundary, not board clock qualification)"
    create_clock -name core_clk -period $period_ns [get_ports clk]
    read_xdc [file join $script_dir ooc_constraints.xdc]
    checked_constraints $evidence_dir synth $period_ns
    screen_resources $evidence_dir synth
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence_dir timing_synth.rpt]
    write_checkpoint -force [file join $build_dir post_synth.dcp]
    if {$checkpoint ne ""} {
        puts "REUSE_PREFLIGHT_ONLY_COMPLETE"
        close_design
        return
    }
    opt_design
    place_design
    screen_resources $evidence_dir placed
    write_checkpoint -force [file join $build_dir post_place.dcp]
    phys_opt_design
    route_design
    report_route_status -file [file join $evidence_dir route_status.rpt]
    screen_resources $evidence_dir routed
    checked_constraints $evidence_dir routed $period_ns
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence_dir timing_routed.rpt]
    report_timing -delay_type max -max_paths 30 -file [file join $evidence_dir paths_routed.rpt]
    report_timing -delay_type max -from [all_registers -clock core_clk] -to [all_registers -clock core_clk] -max_paths 20 -file [file join $evidence_dir paths_internal.rpt]
    report_timing -delay_type max -from [all_inputs] -max_paths 20 -file [file join $evidence_dir paths_input.rpt]
    report_timing -delay_type max -to [all_outputs] -max_paths 20 -file [file join $evidence_dir paths_output.rpt]
    report_drc -file [file join $evidence_dir drc_routed.rpt]
    write_checkpoint -force [file join $build_dir routed.dcp]
    set setup [get_timing_paths -quiet -delay_type max -max_paths 1]
    set hold [get_timing_paths -quiet -delay_type min -max_paths 1]
    require [expr {[llength $setup] == 1 && [llength $hold] == 1}] "Missing setup/hold timing paths"
    # Route completion is deliberately left for the driver to verify from the
    # actual report counts. A terminal marker alone is not route qualification.
    puts "REUSE_OOC_RESULT frequency_mhz=$frequency_mhz setup_slack_ns=[get_property SLACK $setup] hold_slack_ns=[get_property SLACK $hold] route=report_pending_validation part=$part"
    close_project
}

if {[catch {main {*}$argv} message options]} {
    puts stderr "REUSE_OOC_FAIL $message"
    if {[dict exists $options -errorinfo]} { puts stderr [dict get $options -errorinfo] }
    exit 1
}
exit 0
