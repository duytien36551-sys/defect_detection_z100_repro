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
    require [expr {[llength $core_clk_nets] == 1 && [get_property NAME [lindex $buf_nets 0]] eq [get_property NAME [lindex $core_clk_nets 0]]}] "Resident core clock is not driven by fixture BUFG"

    set regs [all_registers -clock core_clk]
    require [expr {[llength $regs] >= 12000}] "Core arithmetic/state register census is below the observed minimum"
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
    puts "RESIDENT_V3_CHECK phase=$phase bufg=[llength $buf_cells] registers=[llength $regs] check_categories=12 status=PASS"
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
    set f [open [file join $directory resources_${phase}.txt] w]
    puts $f "RESOURCES phase=$phase lut=$lut ff=$ff dsp48e1=$dsp dsp_total=$dsp_all ramb36=$ram36 ramb18=$ram18 bram36_equivalent=$bram bufg=$bufg latches=$latches"
    close $f
    report_utilization -file [file join $directory utilization_${phase}.rpt]
    report_utilization -hierarchical -hierarchical_depth 4 -file [file join $directory utilization_hierarchical_${phase}.rpt]
}

proc write_dsp_census {directory phase} {
    set cells [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]
    array set counts {}
    set path [file join $directory dsp48e1_${phase}.tsv]
    set f [open $path w]
    puts $f "cell\tAREG\tBREG\tADREG\tALUMODEREG\tOPMODEREG\tMREG\tPREG\tUSE_MULT\tUSE_SIMD"
    foreach cell $cells {
        set name [get_property NAME $cell]
        set values {}
        foreach property {AREG BREG ADREG ALUMODEREG OPMODEREG MREG PREG USE_MULT USE_SIMD} {
            set value [get_property -quiet $property $cell]
            if {$value eq ""} { set value "UNAVAILABLE" }
            lappend values $value
        }
        set use_mult [lindex $values 7]
        if {![info exists counts($use_mult)]} { set counts($use_mult) 0 }
        incr counts($use_mult)
        puts $f "$name\t[join $values \t]"
    }
    close $f
    set summary [open [file join $directory dsp48e1_census_${phase}.txt] w]
    puts $summary "DSP48E1_COUNT [llength $cells]"
    foreach mode [lsort [array names counts]] { puts $summary "USE_MULT $mode $counts($mode)" }
    close $summary
    set multiply_count 0
    if {[info exists counts(MULTIPLY)]} { set multiply_count $counts(MULTIPLY) }
    return [list [llength $cells] $multiply_count]
}

proc main {frequency_mhz build_dir evidence_dir} {
    set script_dir [file dirname [file normalize [info script]]]
    set top_file [file join $script_dir z100_tile_reuse_resident_v3_timing_top.sv]
    set rtl_file [file join $script_dir z100_tile_reuse_resident_v3.v]
    set xdc_file [file join $script_dir resident_v3_constraints.xdc]
    set project_dir [file join $build_dir project]
    set part xc7z100ffg900-2
    require [expr {[string first "2026.1" [version -short]] == 0}] "Requires Vivado 2026.1"
    require [expr {$frequency_mhz in {100 150}}] "Only 100 MHz, then conditionally 150 MHz, is allowed"
    require [file exists $top_file] "Missing synchronous resident-v3 fixture"
    require [file exists $rtl_file] "Missing resident-v3 RTL"
    require [file exists $xdc_file] "Missing fixture timing constraints"
    set period_ns [expr {1000.0 / double($frequency_mhz)}]
    set_param general.maxThreads 2
    file mkdir $build_dir
    file mkdir $evidence_dir

    create_project -force reuse_resident_v3_fixture $project_dir -part $part
    read_verilog -sv $rtl_file
    read_verilog -sv $top_file
    synth_design -top z100_tile_reuse_resident_v3_timing_top -part $part -flatten_hierarchy none
    read_xdc $xdc_file
    puts "RESIDENT_V3_FIXTURE_VERSION [version -short] DEVICE $part FREQUENCY_MHZ $frequency_mhz"

    check_fixture $evidence_dir synth $period_ns
    screen_resources $evidence_dir synth
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence_dir timing_synth.rpt]
    set dsp_result [write_dsp_census $evidence_dir synth]
    set synth_dsp [lindex $dsp_result 0]
    set synth_mult [lindex $dsp_result 1]
    set synth_lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
    set synth_ram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
    set synth_ram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
    set synth_bram [expr {$synth_ram36 + $synth_ram18 / 2.0}]
    set blackboxes [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]
    set f [open [file join $evidence_dir synth_observability.txt] w]
    puts $f "TOP z100_tile_reuse_resident_v3_timing_top"
    puts $f "CORE_INSTANCE core"
    puts $f "BLACKBOX_COUNT [llength $blackboxes]"
    foreach cell $blackboxes { puts $f "BLACKBOX [get_property NAME $cell]" }
    puts $f "OUTPUT_PORT_COUNT [llength [get_ports -quiet -filter {DIRECTION == OUT}]]"
    puts $f "SYNTH_DSP48E1_COUNT $synth_dsp"
    puts $f "SYNTH_MULTIPLY_DSP_COUNT $synth_mult"
    close $f
    require [expr {[llength $blackboxes] == 0}] "Synthesis contains black-box cells"
    require [expr {$synth_mult == 512}] "Expected all 512 resident 8x8 products in DSP48E1 MULTIPLY cells; found $synth_mult"
    require [expr {$synth_dsp <= 640}] "DSP screen exceeded: $synth_dsp"
    require [expr {$synth_lut <= 50000}] "LUT screen exceeded: $synth_lut"
    require [expr {$synth_bram >= 32.0 && $synth_bram <= 96.0}] "Resident RAM mapping outside 32..96 BRAM36 equivalents: $synth_bram"
    write_checkpoint -force [file join $build_dir post_synth.dcp]

    opt_design
    place_design
    screen_resources $evidence_dir placed
    write_dsp_census $evidence_dir placed
    check_fixture $evidence_dir placed $period_ns
    write_checkpoint -force [file join $build_dir post_place.dcp]
    phys_opt_design
    route_design

    report_route_status -file [file join $evidence_dir route_status.rpt]
    screen_resources $evidence_dir routed
    set routed_dsp [write_dsp_census $evidence_dir routed]
    check_fixture $evidence_dir routed $period_ns
    report_clock_networks -clocks [get_clocks core_clk] -file [file join $evidence_dir clock_networks.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence_dir timing_routed.rpt]
    report_pulse_width -file [file join $evidence_dir pulse_width_routed.rpt]

    set regs [all_registers -clock core_clk]
    set setup [get_timing_paths -quiet -delay_type max -from $regs -to $regs -max_paths 1]
    set hold [get_timing_paths -quiet -delay_type min -from $regs -to $regs -max_paths 1]
    require [expr {[llength $setup] == 1 && [llength $hold] == 1}] "Missing internal register-to-register timing paths"
    report_timing -delay_type max -from $regs -to $regs -max_paths 50 -path_type full_clock_expanded -file [file join $evidence_dir internal_setup_max.rpt]
    report_timing -delay_type min -from $regs -to $regs -max_paths 50 -path_type full_clock_expanded -file [file join $evidence_dir internal_hold_min.rpt]
    report_timing -delay_type max -max_paths 50 -path_type full_clock_expanded -file [file join $evidence_dir all_setup_max.rpt]
    report_timing -delay_type min -max_paths 50 -path_type full_clock_expanded -file [file join $evidence_dir all_hold_min.rpt]
    report_timing -delay_type min -slack_lesser_than 0.0 -max_paths 50 -path_type full_clock_expanded -file [file join $evidence_dir failing_hold_paths.rpt]
    report_drc -file [file join $evidence_dir drc_routed.rpt]
    write_checkpoint -force [file join $build_dir routed.dcp]

    set route_file [open [file join $evidence_dir route_status.rpt] r]
    set route_text [read $route_file]
    close $route_file
    require [regexp {# of routable nets\.+\s*:\s*(\d+)} $route_text ignored routable] "Missing routable-net count"
    require [regexp {# of fully routed nets\.+\s*:\s*(\d+)} $route_text ignored routed] "Missing fully-routed-net count"
    require [regexp {# of nets with routing errors\.+\s*:\s*(\d+)} $route_text ignored route_errors] "Missing route-error count"
    require [expr {$routable == $routed && $route_errors == 0}] "Route incomplete: $routable/$routed errors=$route_errors"

    set setup_slack [get_property SLACK [lindex $setup 0]]
    set hold_slack [get_property SLACK [lindex $hold 0]]
    set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
    set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
    set dsp [llength [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]]
    set ram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
    set ram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
    set bufg [llength [get_cells -quiet -hier -filter {REF_NAME == BUFG}]]
    set bram [expr {$ram36 + $ram18 / 2.0}]
    puts "RESIDENT_V3_RESULT frequency_mhz=$frequency_mhz internal_wns_ns=$setup_slack internal_whs_ns=$hold_slack routable=$routable routed=$routed route_errors=$route_errors lut=$lut ff=$ff dsp=$dsp bram36_equivalent=$bram bufg=$bufg registers=[llength $regs] multiply_dsp=[lindex $routed_dsp 1]"
    close_project
}

if {[catch {main {*}$argv} message options]} {
    puts stderr "RESIDENT_V3_FAIL $message"
    if {[dict exists $options -errorinfo]} { puts stderr [dict get $options -errorinfo] }
    exit 1
}
exit 0
