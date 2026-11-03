proc require {condition message} {
    if {!$condition} { error $message }
}

proc clean_messages {directory phase} {
    foreach {severity suffix} {ERROR errors {CRITICAL WARNING} critical} {
        set path [file join $directory ${phase}_${suffix}.rpt]
        write_messages -severity [list $severity] -force $path
        set f [open $path r]
        set content [read $f]
        close $f
        foreach line [split $content \n] {
            set trimmed [string trim $line]
            if {$trimmed ne "" && ![string match "#*" $trimmed]} {
                error "$phase has $severity messages: $trimmed"
            }
        }
    }
}

proc check_fixture {directory phase period_ns} {
    set clocks [get_clocks -quiet]
    require [expr {[llength $clocks] == 1}] "Expected exactly one propagated clock"
    require [expr {[get_property NAME $clocks] eq "core_clk"}] "Unexpected clock name"
    require [expr {abs([get_property PERIOD $clocks]-$period_ns) < 0.00001}] "Unexpected clock period"

    set buf_cells [get_cells -quiet -hier -filter {REF_NAME == BUFG}]
    require [expr {[llength $buf_cells] == 1}] "Expected exactly one physical BUFG"
    set buf_out [get_pins -quiet -of_objects $buf_cells -filter {REF_PIN_NAME == O}]
    set buf_nets [get_nets -quiet -of_objects $buf_out]
    set core_clk_pin [get_pins -quiet core/clk]
    set core_clk_nets [get_nets -quiet -of_objects $core_clk_pin]
    require [expr {[llength $buf_out] == 1 && [llength $buf_nets] == 1}] "BUFG output is not uniquely connected"
    require [expr {[llength $core_clk_nets] == 1 && [get_property NAME [lindex $buf_nets 0]] eq [get_property NAME [lindex $core_clk_nets 0]]}] "Native MAC clock is not driven by the fixture BUFG"

    set reset_cells [get_cells -quiet -hier -filter {ASYNC_REG == TRUE}]
    require [expr {[llength $reset_cells] == 2}] "Expected exactly two sampled-reset ASYNC_REG flops"
    set reset_first_q [get_pins -quiet -hier -filter {NAME =~ *reset_meta_reg/Q}]
    set reset_second_d [get_pins -quiet -hier -filter {NAME =~ *reset_local_reg/D}]
    set reset_second_q [get_pins -quiet -hier -filter {NAME =~ *reset_local_reg/Q}]
    require [expr {[llength $reset_first_q] == 1 && [llength $reset_second_d] == 1 && [llength $reset_second_q] == 1}] "Unable to identify the two-flop sampled-reset boundary"
    set first_q_net [get_nets -quiet -of_objects $reset_first_q]
    set second_d_net [get_nets -quiet -of_objects $reset_second_d]
    require [expr {[llength $first_q_net] == 1 && [llength $second_d_net] == 1 && [get_property NAME [lindex $first_q_net 0]] eq [get_property NAME [lindex $second_d_net 0]]}] "Reset synchronizer stages are not directly connected"

    set regs [all_registers -clock core_clk]
    set f [open [file join $directory ${phase}_clock_reset_topology.txt] w]
    puts $f "CLOCK core_clk PERIOD_NS $period_ns SOURCE [get_property SOURCE_PINS [lindex $clocks 0]]"
    puts $f "BUFG_COUNT [llength $buf_cells]"
    foreach c $buf_cells { puts $f "BUFG [get_property NAME $c] REF [get_property REF_NAME $c]" }
    puts $f "REGISTER_COUNT [llength $regs]"
    puts $f "RESET_ASYNC_REG_COUNT [llength $reset_cells]"
    foreach c $reset_cells { puts $f "RESET_ASYNC_REG [get_property NAME $c]" }
    puts $f "RESET_STAGE_NET [get_property NAME [lindex $first_q_net 0]]"
    puts $f "CORE_CLOCK_NET [get_property NAME [lindex $core_clk_nets 0]]"
    close $f

    set checked [check_timing -verbose -return_string]
    set f [open [file join $directory check_timing_${phase}.rpt] w]
    puts $f $checked
    close $f
    foreach category {no_clock constant_clock pulse_width_clock unconstrained_internal_endpoints no_input_delay no_output_delay multiple_clock generated_clocks loops partial_input_delay partial_output_delay latch_loops} {
        set pattern [format {checking\s+%s\s+\(([0-9]+)\)} $category]
        require [regexp $pattern $checked ignored count] "Missing check_timing category $category"
        require [expr {$count == 0}] "Nonzero check_timing $category: $count"
    }
    clean_messages $directory $phase
    puts "NATIVE_MAC_CHECK phase=$phase clock=$period_ns bufg=1 reset_flops=2 check_categories=12 status=PASS"
}

proc screen_resources {directory phase} {
    set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
    set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
    set dsp [llength [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]]
    set dsp_all [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]]
    set ram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
    set ram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
    set bufg [llength [get_cells -quiet -hier -filter {REF_NAME == BUFG}]]
    set bram [expr {$ram36 + $ram18 / 2.0}]
    set latches [llength [get_cells -quiet -hier -filter {REF_NAME =~ LD*}]]
    set blackboxes [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]
    set f [open [file join $directory resources_${phase}.txt] w]
    puts $f "RESOURCES phase=$phase lut=$lut ff=$ff dsp48e1=$dsp dsp_total=$dsp_all ramb36=$ram36 ramb18=$ram18 bram36_equivalent=$bram bufg=$bufg latches=$latches blackboxes=[llength $blackboxes]"
    close $f
    report_utilization -file [file join $directory utilization_${phase}.rpt]
    report_utilization -hierarchical -hierarchical_depth 4 -file [file join $directory utilization_hierarchical_${phase}.rpt]
    require [expr {$lut <= 40000}] "$phase LUT screen exceeded: $lut"
    require [expr {$ff <= 25000}] "$phase FF screen exceeded: $ff"
    require [expr {$bram >= 28.0 && $bram <= 40.0}] "$phase BRAM36-equivalent screen outside 28..40: $bram"
    require [expr {$latches == 0}] "$phase contains inferred latch cells: $latches"
    require [expr {[llength $blackboxes] == 0}] "$phase contains black-box cells"
    return [list $lut $ff $dsp $dsp_all $bram $bufg $latches [llength $blackboxes]]
}

proc write_dsp_census {directory phase} {
    set cells [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]
    array set counts {}
    set f [open [file join $directory dsp48e1_${phase}.tsv] w]
    puts $f "cell\tUSE_MULT\tUSE_SIMD\tAREG\tBREG\tADREG\tMREG\tPREG"
    foreach cell $cells {
        set name [get_property NAME $cell]
        set use_mult [get_property -quiet USE_MULT $cell]
        set use_simd [get_property -quiet USE_SIMD $cell]
        if {$use_mult eq ""} { set use_mult UNAVAILABLE }
        if {$use_simd eq ""} { set use_simd UNAVAILABLE }
        if {![info exists counts($use_mult)]} { set counts($use_mult) 0 }
        incr counts($use_mult)
        set values {}
        foreach property {AREG BREG ADREG MREG PREG} {
            set value [get_property -quiet $property $cell]
            if {$value eq ""} { set value UNAVAILABLE }
            lappend values $value
        }
        puts $f "$name\t$use_mult\t$use_simd\t[join $values \t]"
    }
    close $f
    set mult 0
    set none 0
    if {[info exists counts(MULTIPLY)]} { set mult $counts(MULTIPLY) }
    if {[info exists counts(NONE)]} { set none $counts(NONE) }
    set total [llength $cells]
    set other [expr {$total - $mult - $none}]
    set f [open [file join $directory dsp48e1_${phase}_summary.txt] w]
    puts $f "DSP48E1_TOTAL $total"
    puts $f "USE_MULT_MULTIPLY $mult"
    puts $f "USE_MULT_NONE $none"
    puts $f "USE_MULT_OTHER $other"
    foreach mode [lsort [array names counts]] { puts $f "USE_MULT_MODE $mode $counts($mode)" }
    close $f
    require [expr {$total == 640 && $mult == 512 && $none == 128 && $other == 0}] "$phase DSP census changed: total=$total MULTIPLY=$mult NONE=$none other=$other"
    return [list $total $mult $none $other]
}

proc check_timing_slack {directory phase} {
    set setup [get_timing_paths -quiet -delay_type max -max_paths 1]
    set hold [get_timing_paths -quiet -delay_type min -max_paths 1]
    require [expr {[llength $setup] == 1 && [llength $hold] == 1}] "Missing routed setup or hold path"
    set setup_slack [get_property SLACK [lindex $setup 0]]
    set hold_slack [get_property SLACK [lindex $hold 0]]
    require [expr {$setup_slack >= 0.0}] "$phase setup slack is negative: $setup_slack ns"
    require [expr {$hold_slack >= 0.0}] "$phase hold slack is negative: $hold_slack ns"
    report_timing -delay_type max -max_paths 50 -path_type full_clock_expanded -file [file join $directory all_setup_max_${phase}.rpt]
    report_timing -delay_type min -max_paths 50 -path_type full_clock_expanded -file [file join $directory all_hold_min_${phase}.rpt]
    set pulse_path [file join $directory pulse_width_${phase}.rpt]
    report_pulse_width -file $pulse_path
    set f [open $pulse_path r]
    set pulse_text [read $f]
    close $f
    set pulse_checks 0
    foreach line [split $pulse_text \n] {
        if {[regexp {^\s*(Min Period|Low Pulse Width|High Pulse Width)\s+.*\s+(-?[0-9]+\.[0-9]+)\s+\S+\s+\S+\s*$} $line ignored check_type slack]} {
            incr pulse_checks
            require [expr {$slack >= 0.0}] "$phase $check_type slack is negative: $slack ns"
        }
    }
    require [expr {$pulse_checks >= 3}] "$phase pulse-width report lacks min-period/low/high checks"
    set f [open [file join $directory timing_slack_${phase}.txt] w]
    puts $f "TIMING phase=$phase setup_slack_ns=$setup_slack hold_slack_ns=$hold_slack pulse_checks=$pulse_checks pulse_min_slack_nonnegative=1"
    close $f
    return [list $setup_slack $hold_slack $pulse_checks]
}

proc main {frequency_mhz build_dir evidence_dir stage} {
    set script_dir [file dirname [file normalize [info script]]]
    set top_file [file join $script_dir z100_native_mac_timing_top.sv]
    set rtl_file [file normalize [file join $script_dir .. window_mac_v1 z100_window_mac.sv]]
    set xdc_file [file join $script_dir native_mac_timing_constraints.xdc]
    set project_dir [file join $build_dir project]
    set part xc7z100ffg900-2
    require [expr {[string first "2026.1" [version -short]] == 0}] "Requires Vivado 2026.1"
    require [expr {$frequency_mhz == 100}] "Only the reviewed 100 MHz route is in scope"
    require [expr {$stage eq "ooc" || $stage eq "route"}] "Stage must be ooc or route"
    require [file exists $top_file] "Missing native MAC timing top"
    require [file exists $rtl_file] "Missing frozen native MAC RTL"
    require [file exists $xdc_file] "Missing native MAC timing constraints"
    set period_ns [expr {1000.0 / double($frequency_mhz)}]
    set_param general.maxThreads 2
    file mkdir $build_dir
    file mkdir $evidence_dir

    create_project -force native_mac_timing_fixture $project_dir -part $part
    read_verilog -sv $rtl_file
    read_verilog -sv $top_file
    synth_design -top z100_native_mac_timing_top -part $part -flatten_hierarchy none
    read_xdc $xdc_file
    puts "NATIVE_MAC_FIXTURE_VERSION [version -short] DEVICE $part FREQUENCY_MHZ $frequency_mhz"

    check_fixture $evidence_dir synth $period_ns
    set synth_resources [screen_resources $evidence_dir synth]
    set synth_dsp [write_dsp_census $evidence_dir synth]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence_dir timing_synth.rpt]
    set f [open [file join $evidence_dir synth_observability.txt] w]
    puts $f "TOP z100_native_mac_timing_top"
    puts $f "CORE_INSTANCE core"
    puts $f "BLACKBOX_COUNT [lindex $synth_resources 7]"
    puts $f "OUTPUT_PORT_COUNT [llength [get_ports -quiet -filter {DIRECTION == OUT}]]"
    puts $f "SERIAL_DATA_WIDTH 32; SCANNED_LANES 32; CORE_DATA_WIDTH 1024"
    puts $f "SERIAL_OVERFLOW_SCANNED_LANES 32; CORE_OVERFLOW_WIDTH 32"
    puts $f "DSP_TOTAL [lindex $synth_dsp 0]; DSP_MULTIPLY [lindex $synth_dsp 1]; DSP_NONE [lindex $synth_dsp 2]"
    close $f
    write_checkpoint -force [file join $build_dir post_synth.dcp]

    if {$stage eq "ooc"} {
        puts "NATIVE_MAC_TIMING_OOC_PASS frequency_mhz=$frequency_mhz lut=[lindex $synth_resources 0] ff=[lindex $synth_resources 1] dsp_total=[lindex $synth_dsp 0] dsp_multiply=[lindex $synth_dsp 1] dsp_none=[lindex $synth_dsp 2] bram36_equivalent=[lindex $synth_resources 4] bufg=[lindex $synth_resources 5] latches=[lindex $synth_resources 6] blackboxes=[lindex $synth_resources 7]"
        close_project
        return
    }

    opt_design
    place_design
    check_fixture $evidence_dir placed $period_ns
    screen_resources $evidence_dir placed
    write_dsp_census $evidence_dir placed
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence_dir timing_placed.rpt]
    write_checkpoint -force [file join $build_dir post_place.dcp]
    phys_opt_design
    route_design

    report_route_status -file [file join $evidence_dir route_status.rpt]
    check_fixture $evidence_dir routed $period_ns
    set routed_resources [screen_resources $evidence_dir routed]
    set routed_dsp [write_dsp_census $evidence_dir routed]
    report_clock_networks -clocks [get_clocks core_clk] -file [file join $evidence_dir clock_networks.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence_dir timing_routed.rpt]
    set timing [check_timing_slack $evidence_dir routed]
    report_drc -file [file join $evidence_dir drc_routed.rpt]
    write_checkpoint -force [file join $build_dir routed.dcp]

    set route_file [open [file join $evidence_dir route_status.rpt] r]
    set route_text [read $route_file]
    close $route_file
    require [regexp {# of routable nets\.+\s*:\s*(\d+)} $route_text ignored routable] "Missing routable-net count"
    require [regexp {# of fully routed nets\.+\s*:\s*(\d+)} $route_text ignored routed] "Missing fully-routed-net count"
    require [regexp {# of nets with routing errors\.+\s*:\s*(\d+)} $route_text ignored route_errors] "Missing route-error count"
    require [expr {$routable == $routed && $route_errors == 0}] "Route incomplete: $routable/$routed route_errors=$route_errors"

    puts "NATIVE_MAC_TIMING_IMPL_PASS frequency_mhz=$frequency_mhz setup_slack_ns=[lindex $timing 0] hold_slack_ns=[lindex $timing 1] pulse_checks=[lindex $timing 2] routable=$routable routed=$routed route_errors=$route_errors lut=[lindex $routed_resources 0] ff=[lindex $routed_resources 1] dsp_total=[lindex $routed_dsp 0] dsp_multiply=[lindex $routed_dsp 1] dsp_none=[lindex $routed_dsp 2] bram36_equivalent=[lindex $routed_resources 4] bufg=[lindex $routed_resources 5]"
    close_project
}

if {[catch {main {*}$argv} message options]} {
    puts stderr "NATIVE_MAC_TIMING_FAIL $message"
    if {[dict exists $options -errorinfo]} { puts stderr [dict get $options -errorinfo] }
    exit 1
}
exit 0
