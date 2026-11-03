set_param general.maxThreads 8
if {![info exists ::env(Z100_HARDWARE_OUTPUT)]} { error "Z100_HARDWARE_OUTPUT is required" }
if {![info exists ::env(Z100_HARDWARE_INPUT_DCP)]} { error "Z100_HARDWARE_INPUT_DCP must name this run's routed checkpoint" }
set ::output_root [file normalize $::env(Z100_HARDWARE_OUTPUT)]
set ::input_dcp [file normalize $::env(Z100_HARDWARE_INPUT_DCP)]
set ::input_dcp_label [file tail $::input_dcp]
if {[info exists ::env(Z100_HARDWARE_INPUT_LABEL)]} { set ::input_dcp_label $::env(Z100_HARDWARE_INPUT_LABEL) }
set ::out [file join $::output_root physopt]
file mkdir $::out
set ::expected_part xc7z100ffg900-2
set ::expected_dsp 1252
set ::expected_period_ns 10.0

if {![string match *2026.1* [version -short]]} { error "Vivado 2026.1 is required" }

proc require {condition message} {
    if {!$condition} { error $message }
}

proc verify_identity {stage} {
    global expected_part expected_dsp expected_period_ns
    set part [get_property PART [current_design]]
    set dsp_count [llength [get_cells -hier -filter {REF_NAME == DSP48E1}]]
    set clocks [get_clocks -quiet *]
    set clock_names [get_property NAME $clocks]
    require [expr {$part eq $expected_part}] "Unexpected part at $stage: $part"
    require [expr {$dsp_count == $expected_dsp}] "Unexpected DSP count at $stage: $dsp_count"
    require [expr {[llength $clocks] == 1 && [llength $clock_names] == 1 && [lindex $clock_names 0] eq "clk_fpga_0"}] "Expected exactly one clk_fpga_0 at $stage"
    set period [get_property PERIOD $clocks]
    require [expr {abs(double($period)-$expected_period_ns) < 0.000001}] "Unexpected clock period at $stage: $period"
    puts "Z100_POST_ROUTE_IDENTITY stage=$stage part=$part dsp=$dsp_count clocks=$clock_names period_ns=$period"
    return $period
}

proc check_route_status {text} {
    set patterns [list routable_nets {# of routable nets} fully_routed_nets {# of fully routed nets} route_error_nets {# of nets with routing errors}]
    set values [dict create routable_nets -1 fully_routed_nets -1 route_error_nets -1]
    foreach {key label} $patterns {
        set pattern [format {^[ \t]*%s[. ]*:[ \t]*([0-9]+)[ \t]*:} $label]
        if {[regexp -lineanchor -- $pattern $text -> value]} { dict set values $key $value }
    }
    set complete [expr {[dict get $values routable_nets] >= 0 && [dict get $values fully_routed_nets] >= 0 && [dict get $values route_error_nets] >= 0}]
    set pass [expr {$complete && [dict get $values routable_nets] > 0 && [dict get $values fully_routed_nets] == [dict get $values routable_nets] && [dict get $values route_error_nets] == 0}]
    dict set values counts_complete $complete
    dict set values pass $pass
    return $values
}

proc parse_timing_summary {text} {
    foreach line [split $text "\n"] {
        set fields [regexp -all -inline {[^ \t]+} [string trim $line]]
        if {[llength $fields] != 12} { continue }
        set numeric 1
        foreach index {0 1 4 5 8 9} {
            if {![string is double -strict [lindex $fields $index]]} { set numeric 0 }
        }
        foreach index {2 3 6 7 10 11} {
            if {![string is integer -strict [lindex $fields $index]]} { set numeric 0 }
        }
        if {!$numeric} { continue }
        return [dict create wns [lindex $fields 0] tns [lindex $fields 1] setup_fail [lindex $fields 2] setup_total [lindex $fields 3] whs [lindex $fields 4] ths [lindex $fields 5] hold_fail [lindex $fields 6] hold_total [lindex $fields 7] wpws [lindex $fields 8] tpws [lindex $fields 9] pulse_fail [lindex $fields 10] pulse_total [lindex $fields 11]]
    }
    error "Could not parse the 12-column timing summary row"
}

proc check_timing_coverage {text} {
    set required {no_clock constant_clock pulse_width_clock unconstrained_internal_endpoints no_input_delay no_output_delay multiple_clock generated_clocks loops partial_input_delay partial_output_delay latch_loops}
    set counts [dict create]
    set occurrences [dict create]
    foreach name $required { dict set counts $name -1; dict set occurrences $name 0 }
    foreach line [split $text "\n"] {
        if {[regexp {^[ \t]*[0-9]+[.] checking ([a-z_]+)[ \t]*\(([0-9]+)\)} $line -> name value] && [dict exists $counts $name]} {
            dict incr occurrences $name
            if {[dict get $counts $name] < $value} { dict set counts $name $value }
        }
    }
    set complete 1
    set pass 1
    foreach name $required {
        if {[dict get $occurrences $name] == 0 || [dict get $counts $name] < 0} { set complete 0; set pass 0 }
        if {[dict get $counts $name] != 0} { set pass 0 }
    }
    return [dict create complete $complete pass [expr {$complete && $pass}] counts $counts]
}

proc write_result {status detail metrics} {
    set escaped [string map [list \\ \\\\ \" \\\" \n \\n \r \\r] $detail]
    set escaped_input [string map [list \\ \\\\ \" \\\" \n \\n \r \\r] $::input_dcp_label]
    set result [format {{"status":"%s","detail":"%s","metrics":%s,"input_dcp":"%s","part":"%s","period_ns":%.3f,"sites":12,"strategy":"one post-route phys_opt_design -directive Explore","rtl_changed":false,"clock_changed":false}} $status $escaped $metrics $escaped_input $::expected_part $::expected_period_ns]
    set fd [open [file join $::out acceptance.json] w]
    puts $fd $result
    close $fd
}

proc run_candidate {} {
    global input_dcp out expected_part expected_dsp expected_period_ns
    puts "Z100_POST_ROUTE_PHYSOPT_BEGIN version=[version -short] input=$::input_dcp_label"
    open_checkpoint $input_dcp
    verify_identity loaded

    set route_before [check_route_status [report_route_status -return_string]]
    require [dict get $route_before pass] "Input checkpoint is not fully routed"
    set worst_before [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
    require [expr {double($worst_before) < 0.0}] "Input checkpoint no longer has a setup violation; refusing stale experiment"
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_before.rpt]
    report_timing -delay_type max -max_paths 100 -nworst 1 -input_pins -path_type full_clock_expanded -file [file join $out setup_paths_before.rpt]
    report_utilization -file [file join $out utilization_before.rpt]

    set started [clock milliseconds]
    puts "Z100_POST_ROUTE_PHYSOPT_RUN directive=Explore threads=[get_param general.maxThreads]"
    phys_opt_design -directive Explore
    set elapsed [expr {([clock milliseconds]-$started)/1000.0}]
    puts [format "Z100_POST_ROUTE_PHYSOPT_DONE elapsed_seconds=%.3f" $elapsed]
    verify_identity after_phys_opt

    write_checkpoint -force [file join $out post_physopt.dcp]
    set summary_text [report_timing_summary -delay_type min_max -report_unconstrained -return_string]
    set summary_fd [open [file join $out timing_after.rpt] w]
    puts $summary_fd $summary_text
    close $summary_fd
    report_timing -delay_type max -max_paths 100 -nworst 1 -input_pins -path_type full_clock_expanded -file [file join $out setup_paths_after.rpt]
    report_timing -delay_type min -max_paths 50 -nworst 1 -input_pins -path_type full_clock_expanded -file [file join $out hold_paths_after.rpt]
    report_route_status -file [file join $out route_status_after.rpt]
    report_utilization -file [file join $out utilization_after.rpt]
    report_drc -file [file join $out drc_after.rpt]
    set pulse_text [report_pulse_width -return_string]
    set pulse_fd [open [file join $out pulse_width_after.rpt] w]
    puts $pulse_fd $pulse_text
    close $pulse_fd
    set timing_text [check_timing -verbose -return_string]
    set timing_fd [open [file join $out check_timing_after.rpt] w]
    puts $timing_fd $timing_text
    close $timing_fd

    set summary [parse_timing_summary $summary_text]
    set worst_setup [dict get $summary wns]
    set worst_hold [dict get $summary whs]
    set setup_fail [dict get $summary setup_fail]
    set hold_fail [dict get $summary hold_fail]
    set wpws [dict get $summary wpws]
    set tpws [dict get $summary tpws]
    set pulse_fail [dict get $summary pulse_fail]
    set route_after [check_route_status [report_route_status -return_string]]
    set coverage [check_timing_coverage $timing_text]
    set coverage_json "\{"
    set coverage_separator ""
    dict for {name value} [dict get $coverage counts] {
        append coverage_json $coverage_separator "\"$name\":" $value
        set coverage_separator ","
    }
    append coverage_json "\}"
    set drc_critical [llength [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]]
    set pass [expr {double($worst_setup) >= 0.0 && double($worst_hold) >= 0.0 && double($wpws) >= 0.0 && double($tpws) >= 0.0 && $setup_fail == 0 && $hold_fail == 0 && $pulse_fail == 0 && [dict get $route_after pass] && $drc_critical == 0 && [dict get $coverage complete] && [dict get $coverage pass]}]
    set metrics [format {{"wns_ns":%.3f,"tns_ns":%.3f,"setup_fail_endpoints":%d,"whs_ns":%.3f,"hold_fail_endpoints":%d,"wpws_ns":%.3f,"tpws_ns":%.3f,"pulse_width_fail_endpoints":%d,"timing_check_counts":%s,"routable_nets":%d,"fully_routed_nets":%d,"route_error_nets":%d,"critical_drc_count":%d,"timing_coverage_complete":%s,"timing_checks_pass":%s,"baseline_wns_ns":%.3f,"phys_opt_elapsed_seconds":%.3f,"pass":%s}} \
        $worst_setup [dict get $summary tns] $setup_fail $worst_hold $hold_fail $wpws $tpws $pulse_fail $coverage_json \
        [dict get $route_after routable_nets] [dict get $route_after fully_routed_nets] [dict get $route_after route_error_nets] $drc_critical \
        [expr {[dict get $coverage complete] ? "true" : "false"}] [expr {[dict get $coverage pass] ? "true" : "false"}] \
        $worst_before $elapsed [expr {$pass ? "true" : "false"}]]
    write_result [expr {$pass ? "TIMING_ROUTE_DRC_PASS" : "TIMING_FAIL"}] "" $metrics
    puts "Z100_POST_ROUTE_ACCEPT wns=$worst_setup whs=$worst_hold tns=[dict get $summary tns] setup_fail=$setup_fail hold_fail=$hold_fail route_err=[dict get $route_after route_error_nets] drc=$drc_critical pass=$pass"
    return $pass
}

if {[catch {set passed [run_candidate]} error options]} {
    write_result "TOOL_OR_GUARD_FAILURE_NO_RETRY" $error {{}}
    puts stderr "Z100_POST_ROUTE_FAILURE $error"
    exit 1
}
puts "Z100_POST_ROUTE_COMPLETE pass=$passed"
if {!$passed} { exit 1 }
exit 0
