proc require {condition message} { if {!$condition} { error $message } }

proc clean_messages {directory phase} {
    foreach {severity suffix} {ERROR errors {CRITICAL WARNING} critical} {
        set path [file join $directory ${phase}_${suffix}.rpt]
        write_messages -severity [list $severity] -force $path
        set f [open $path r]
        set content [read $f]
        close $f
        foreach line [split $content \n] {
            if {[string trim $line] ne "" && ![string match "#*" [string trim $line]]} {
                error "$phase has $severity messages: $line"
            }
        }
    }
}

proc check_fixture {directory phase period_ns} {
    set clocks [get_clocks -quiet]
    require [expr {[llength $clocks] == 1}] "Expected one clock"
    require [expr {[get_property NAME $clocks] eq "core_clk"}] "Wrong clock name"
    require [expr {abs([get_property PERIOD $clocks]-$period_ns) < 0.00001}] "Wrong clock period"

    set buf_cells [get_cells -quiet -hier -filter {REF_NAME == BUFG}]
    require [expr {[llength $buf_cells] == 1}] "Expected exactly one physical BUFG"
    set buf_out [get_pins -quiet -of_objects $buf_cells -filter {REF_PIN_NAME == O}]
    set buf_nets [get_nets -quiet -of_objects $buf_out]
    set core_clk_pin [get_pins -quiet core/clk]
    set core_clk_nets [get_nets -quiet -of_objects $core_clk_pin]
    require [expr {[llength $buf_out] == 1 && [llength $buf_nets] == 1}] "BUFG output is not uniquely connected"
    require [expr {[llength $core_clk_nets] == 1 && [get_property NAME [lindex $buf_nets 0]] eq [get_property NAME [lindex $core_clk_nets 0]]}] "Core clock is not driven by fixture BUFG"

    set regs [all_registers -clock core_clk]
    require [expr {[llength $regs] >= 1000}] "Core or fixture registers were optimized away"
    set f [open [file join $directory ${phase}_clock_topology.txt] w]
    puts $f "CLOCK core_clk PERIOD_NS $period_ns SOURCE [get_property SOURCE_PINS [lindex $clocks 0]]"
    puts $f "BUFG_COUNT [llength $buf_cells]"
    foreach c $buf_cells { puts $f "BUFG [get_property NAME $c] REF [get_property REF_NAME $c]" }
    puts $f "REGISTER_COUNT [llength $regs]"
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
    puts "SYNC_FIXTURE_CHECK phase=$phase bufg=[llength $buf_cells] registers=[llength $regs] check_categories=12 status=PASS"
}

proc screen_resources {directory phase} {
    set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
    set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]]
    set ram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
    set ram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
    set bufg [llength [get_cells -quiet -hier -filter {REF_NAME == BUFG}]]
    set bram [expr {$ram36 + $ram18/2.0}]
    set f [open [file join $directory resources_${phase}.txt] w]
    puts $f "RESOURCES phase=$phase lut=$lut dsp=$dsp bram36_equivalent=$bram bufg=$bufg"
    close $f
    report_utilization -file [file join $directory utilization_${phase}.rpt]
}

proc main {frequency_mhz build_dir evidence_dir {mode "all"} {checkpoint ""}} {
    set script_dir [file dirname [file normalize [info script]]]
    set project_dir [file join $build_dir project]
    set part xc7z100ffg900-2
    require [expr {[string first "2026.1" [version -short]] == 0}] "Requires Vivado2026.1"
    require [expr {$frequency_mhz in {100 200}}] "Frequency must be100 or200MHz"
    set period_ns [expr {1000.0 / double($frequency_mhz)}]
    set_param general.maxThreads 2
    file mkdir $build_dir
    file mkdir $evidence_dir

    require [expr {$checkpoint ne ""}] "Requires a source checkpoint"
    open_checkpoint $checkpoint
    create_clock -name core_clk -period $period_ns [get_ports clk]
    read_xdc [file join [file dirname $script_dir] reuse_sync_fixture sync_constraints.xdc]
    puts "SYNC_FIXTURE_VERSION [version -short] DEVICE $part FREQUENCY_MHZ $frequency_mhz"

    check_fixture $evidence_dir synth $period_ns
    screen_resources $evidence_dir synth
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence_dir timing_synth.rpt]
    set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]]
    set f [open [file join $evidence_dir dsp_registers.txt] w]
    foreach cell [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}] {
        puts $f "CELL [get_property NAME $cell] REF [get_property REF_NAME $cell] AREG [get_property AREG $cell] BREG [get_property BREG $cell] MREG [get_property MREG $cell] PREG [get_property PREG $cell]"
    }
    close $f
    puts "DSP_CORE_SYNTH_RESULT dsp=$dsp"
    write_checkpoint -force [file join $build_dir post_synth.dcp]
    require [expr {[llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]] <= 100000}] "LUT screen exceeded"

    opt_design
    place_design
    screen_resources $evidence_dir placed
    write_checkpoint -force [file join $build_dir post_place.dcp]
    phys_opt_design
    route_design
    report_route_status -file [file join $evidence_dir route_status.rpt]
    screen_resources $evidence_dir routed
    check_fixture $evidence_dir routed $period_ns
    report_clock_networks -clocks [get_clocks core_clk] -file [file join $evidence_dir clock_networks.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence_dir timing_routed.rpt]

    set regs [all_registers -clock core_clk]
    set setup [get_timing_paths -quiet -delay_type max -from $regs -to $regs -max_paths 1]
    set hold [get_timing_paths -quiet -delay_type min -from $regs -to $regs -max_paths 1]
    require [expr {[llength $setup] == 1 && [llength $hold] == 1}] "Missing internal register-to-register timing paths"
    report_timing -delay_type max -from $regs -to $regs -max_paths 30 -path_type full_clock_expanded -file [file join $evidence_dir internal_max_paths.rpt]
    report_timing -delay_type min -from $regs -to $regs -max_paths 30 -path_type full_clock_expanded -file [file join $evidence_dir internal_min_paths.rpt]
    report_timing -delay_type min -slack_lesser_than 0.0 -max_paths 30 -path_type full_clock_expanded -file [file join $evidence_dir all_failing_min_paths.rpt]
    report_timing -delay_type max -to [all_outputs] -max_paths 20 -path_type full_clock_expanded -file [file join $evidence_dir output_max_paths.rpt]
    report_drc -file [file join $evidence_dir drc_routed.rpt]
    write_checkpoint -force [file join $build_dir routed.dcp]

    set route_file [open [file join $evidence_dir route_status.rpt] r]
    set route_text [read $route_file]
    close $route_file
    require [regexp {# of routable nets\.+\s*:\s*(\d+)} $route_text ignored routable] "Missing routable count"
    require [regexp {# of fully routed nets\.+\s*:\s*(\d+)} $route_text ignored routed] "Missing routed count"
    require [regexp {# of nets with routing errors\.+\s*:\s*(\d+)} $route_text ignored route_errors] "Missing route error count"
    require [expr {$routable == $routed && $route_errors == 0}] "Route counts incomplete: $routable/$routed errors=$route_errors"

    set setup_slack [get_property SLACK [lindex $setup 0]]
    set hold_slack [get_property SLACK [lindex $hold 0]]
    set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
    set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]]
    set ram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
    set ram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
    set bufg [llength [get_cells -quiet -hier -filter {REF_NAME == BUFG}]]
    set bram [expr {$ram36 + $ram18/2.0}]
    puts "SYNC_FIXTURE_RESULT frequency_mhz=$frequency_mhz internal_wns_ns=$setup_slack internal_whs_ns=$hold_slack routable=$routable routed=$routed route_errors=$route_errors lut=$lut dsp=$dsp bram36_equivalent=$bram bufg=$bufg registers=[llength $regs]"
    close_project
}

if {[catch {main {*}$argv} message options]} {
    puts stderr "SYNC_FIXTURE_FAIL $message"
    if {[dict exists $options -errorinfo]} { puts stderr [dict get $options -errorinfo] }
    exit 1
}
exit 0
