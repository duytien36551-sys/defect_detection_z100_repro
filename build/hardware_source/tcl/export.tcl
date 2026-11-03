set ::bundle_root [file normalize [file join [file dirname [info script]] ..]]
if {![info exists ::env(Z100_HARDWARE_OUTPUT)]} { error "Z100_HARDWARE_OUTPUT is required" }
if {![info exists ::env(Z100_HARDWARE_EXPORT_DCP)]} { error "Z100_HARDWARE_EXPORT_DCP is required" }
if {![info exists ::env(Z100_HARDWARE_EXPORT_SHA256)]} { error "Z100_HARDWARE_EXPORT_SHA256 is required" }
set ::output_root [file normalize $::env(Z100_HARDWARE_OUTPUT)]
set ::input_dcp [file normalize $::env(Z100_HARDWARE_EXPORT_DCP)]
set ::input_dcp_label [file tail $::input_dcp]
if {[info exists ::env(Z100_HARDWARE_EXPORT_LABEL)]} { set ::input_dcp_label $::env(Z100_HARDWARE_EXPORT_LABEL) }
set ::out [file join $::output_root export]
file mkdir $::out
set ::expected_dcp_sha256 $::env(Z100_HARDWARE_EXPORT_SHA256)
set ::expected_part xc7z100ffg900-2
set ::expected_clock clk_fpga_0
set ::expected_dsp 1252
set ::expected_period_ns 10.0

if {![string match *2026.1* [version -short]]} { error "Vivado 2026.1 is required" }
if {![regexp {^[0-9a-f]{64}$} $::expected_dcp_sha256]} { error "Invalid physopt checkpoint SHA-256" }

proc require {condition message} {
    if {!$condition} { error $message }
}

proc verify_identity {stage} {
    global expected_part expected_clock expected_dsp expected_period_ns
    set part [get_property PART [current_design]]
    set dsp_count [llength [get_cells -hier -filter {REF_NAME == DSP48E1}]]
    set clocks [get_clocks -quiet *]
    set clock_names [get_property NAME $clocks]
    require [expr {$part eq $expected_part}] "Unexpected part at $stage: $part"
    require [expr {$dsp_count == $expected_dsp}] "Unexpected DSP count at $stage: $dsp_count"
    require [expr {[llength $clocks] == 1 && [llength $clock_names] == 1 && [lindex $clock_names 0] eq $expected_clock}] "Expected exactly one $expected_clock at $stage"
    set period [get_property PERIOD $clocks]
    require [expr {abs(double($period)-$expected_period_ns) < 0.000001}] "Unexpected clock period at $stage: $period"
    puts "Z100_EXPORT_IDENTITY stage=$stage part=$part dsp=$dsp_count clock=$clock_names period_ns=$period"
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

proc json_escape {value} {
    return [string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $value]
}

proc write_acceptance {status detail metrics} {
    global expected_dcp_sha256 expected_part expected_clock expected_period_ns input_dcp_label out
    set result [format {{"schema_version":1,"status":"%s","detail":"%s","input_dcp":"%s","input_dcp_sha256":"%s","part":"%s","clock_name":"%s","period_ns":%.3f,"metrics":%s}} \
        $status [json_escape $detail] [json_escape $input_dcp_label] $expected_dcp_sha256 $expected_part $expected_clock $expected_period_ns $metrics]
    set fd [open [file join $out acceptance.json] w]
    puts $fd $result
    close $fd
}

proc write_text {path text} {
    set fd [open $path w]
    puts -nonewline $fd $text
    close $fd
}

proc run_export {} {
    global input_dcp input_dcp_label out expected_dcp_sha256
    set metrics_json "{}"
    set metrics [dict create]
    if {[catch {
        puts "Z100_EXPORT_BEGIN version=[version -short] input=$input_dcp_label sha256=$expected_dcp_sha256"
        open_checkpoint $input_dcp
        verify_identity loaded

        set timing_text [report_timing_summary -delay_type min_max -report_unconstrained -return_string]
        set route_text [report_route_status -return_string]
        set coverage_text [check_timing -verbose -return_string]
        set pulse_text [report_pulse_width -return_string]
        report_drc -file [file join $out drc_export.rpt]
        report_utilization -file [file join $out utilization_export.rpt]
        write_text [file join $out timing_export.rpt] $timing_text
        write_text [file join $out route_status_export.rpt] $route_text
        write_text [file join $out check_timing_export.rpt] $coverage_text
        write_text [file join $out pulse_width_export.rpt] $pulse_text

        set summary [parse_timing_summary $timing_text]
        set route [check_route_status $route_text]
        set coverage [check_timing_coverage $coverage_text]
        set drc_critical [llength [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]]
        set drc_warnings [llength [get_drc_violations -quiet -filter {SEVERITY == "Warning"}]]

        set wns [dict get $summary wns]
        set tns [dict get $summary tns]
        set setup_fail [dict get $summary setup_fail]
        set setup_total [dict get $summary setup_total]
        set whs [dict get $summary whs]
        set ths [dict get $summary ths]
        set hold_fail [dict get $summary hold_fail]
        set hold_total [dict get $summary hold_total]
        set wpws [dict get $summary wpws]
        set tpws [dict get $summary tpws]
        set pulse_fail [dict get $summary pulse_fail]
        set pulse_total [dict get $summary pulse_total]
        set timing_pass [expr {double($wns) >= 0.0 && double($tns) >= 0.0 && double($whs) >= 0.0 && double($ths) >= 0.0 && double($wpws) >= 0.0 && double($tpws) >= 0.0 && $setup_fail == 0 && $hold_fail == 0 && $pulse_fail == 0 && $setup_total > 0 && $hold_total > 0 && $pulse_total > 0}]
        set implementation_pass [expr {[dict get $route pass] && $drc_critical == 0 && [dict get $coverage complete] && [dict get $coverage pass]}]

        set coverage_json "\{"
        set separator ""
        dict for {name value} [dict get $coverage counts] {
            append coverage_json $separator "\"$name\":" $value
            set separator ","
        }
        append coverage_json "\}"
        set metrics_json [format {{"wns_ns":%.3f,"tns_ns":%.3f,"setup_fail_endpoints":%d,"setup_total_endpoints":%d,"whs_ns":%.3f,"ths_ns":%.3f,"hold_fail_endpoints":%d,"hold_total_endpoints":%d,"wpws_ns":%.3f,"tpws_ns":%.3f,"pulse_width_fail_endpoints":%d,"pulse_width_total_endpoints":%d,"timing_check_counts":%s,"routable_nets":%d,"fully_routed_nets":%d,"route_error_nets":%d,"route_counts_complete":%s,"critical_drc_count":%d,"warning_drc_groups":%d,"timing_coverage_complete":%s,"timing_checks_pass":%s,"timing_pass":%s,"implementation_pass":%s,"pass":%s}} \
            $wns $tns $setup_fail $setup_total $whs $ths $hold_fail $hold_total $wpws $tpws $pulse_fail $pulse_total $coverage_json \
            [dict get $route routable_nets] [dict get $route fully_routed_nets] [dict get $route route_error_nets] \
            [expr {[dict get $route counts_complete] ? "true" : "false"}] $drc_critical $drc_warnings \
            [expr {[dict get $coverage complete] ? "true" : "false"}] [expr {[dict get $coverage pass] ? "true" : "false"}] \
            [expr {$timing_pass ? "true" : "false"}] [expr {$implementation_pass ? "true" : "false"}] \
            [expr {$timing_pass && $implementation_pass ? "true" : "false"}]]
    } detail options]} {
        write_acceptance "TOOL_OR_GUARD_FAILURE_NO_RETRY" $detail $metrics_json
        puts stderr "Z100_EXPORT_FAILURE stage=analysis detail=$detail"
        return 1
    }

    if {!$timing_pass || !$implementation_pass} {
        write_acceptance "TIMING_FAIL" "Timing, routing, DRC, or coverage gates failed; no export performed" $metrics_json
        puts "Z100_EXPORT_COMPLETE pass=0"
        return 1
    }

    set stage [file join $out artifacts.stage]
    set deliverables [file join $out artifacts]
    if {[file exists $stage] || [file exists $deliverables]} {
        write_acceptance "EXPORT_FAILURE_NO_RETRY" "Output staging or artifact directory already exists; refusing overwrite" $metrics_json
        return 1
    }
    if {[catch {
        file mkdir $stage
        write_bitstream -force [file join $stage z100_platform.bit]
        write_hw_platform -fixed -force -file [file join $stage z100_platform.xsa]
        require [expr {[file exists [file join $stage z100_platform.bit]] && [file size [file join $stage z100_platform.bit]] > 0}] "Bitstream export is missing or empty"
        require [expr {[file exists [file join $stage z100_platform.xsa]] && [file size [file join $stage z100_platform.xsa]] > 0}] "XSA export is missing or empty"
        file rename $stage $deliverables
    } detail options]} {
        write_acceptance "EXPORT_FAILURE_NO_RETRY" $detail $metrics_json
        puts stderr "Z100_EXPORT_FAILURE stage=export detail=$detail"
        return 1
    }
    write_acceptance "EXPORT_PASS" "Timing, routing, DRC, and coverage gates passed; bitstream and XSA exported" $metrics_json
    puts "Z100_EXPORT_COMPLETE pass=1 tns=[dict get $summary tns] bit=export/artifacts/z100_platform.bit xsa=export/artifacts/z100_platform.xsa"
    return 0
}

set ::z100_export_exit_code [run_export]
if {$::z100_export_exit_code != 0} {
    error "Z100_EXPORT_FAILED; inspect acceptance.json and Vivado log"
}
