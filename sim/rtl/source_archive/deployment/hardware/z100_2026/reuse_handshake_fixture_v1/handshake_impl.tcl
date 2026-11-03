proc require {condition message} { if {!$condition} { error $message } }

proc write_resource_snapshot {directory phase} {
    set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
    set dsp_cells [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]
    set ram36 [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]
    set ram18 [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]
    set buf_cells [get_cells -quiet -hier -filter {REF_NAME == BUFG}]
    set bram36_equivalent [expr {[llength $ram36] + [llength $ram18] / 2.0}]
    set f [open [file join $directory resources_${phase}.txt] w]
    puts $f "RESOURCES phase=$phase lut=$lut dsp=[llength $dsp_cells] ramb36=[llength $ram36] ramb18=[llength $ram18] bram36_equivalent=$bram36_equivalent bufg=[llength $buf_cells]"
    close $f
    report_utilization -hierarchical -file [file join $directory utilization_${phase}.rpt]
    return [list $lut [llength $dsp_cells] $bram36_equivalent [llength $buf_cells]]
}

proc first_path_slack {paths} {
    if {[llength $paths] == 0} { return "NO_PATH" }
    return [get_property SLACK [lindex $paths 0]]
}

proc write_path_class_report {directory phase class delay_type from_objects to_objects} {
    set paths [get_timing_paths -quiet -delay_type $delay_type -from $from_objects -to $to_objects -max_paths 1]
    set file [file join $directory ${phase}_${class}_${delay_type}.rpt]
    if {[llength $paths] == 0} {
        set f [open $file w]
        puts $f "NO_PATH class=$class delay_type=$delay_type"
        close $f
    } else {
        report_timing -delay_type $delay_type -from $from_objects -to $to_objects -max_paths 50 -path_type full_clock_expanded -file $file
    }
    return [list $paths [first_path_slack $paths]]
}

proc write_clock_and_timing_evidence {directory phase period_ns} {
    set clocks [get_clocks -quiet]
    require [expr {[llength $clocks] == 1}] "Expected one clock"
    require [expr {[get_property NAME $clocks] eq "core_clk"}] "Wrong clock name"
    require [expr {abs([get_property PERIOD $clocks] - $period_ns) < 0.00001}] "Wrong clock period"

    set buf_cells [get_cells -quiet -hier -filter {REF_NAME == BUFG}]
    require [expr {[llength $buf_cells] == 1}] "Expected exactly one physical BUFG"
    set buf_out [get_pins -quiet -of_objects $buf_cells -filter {REF_PIN_NAME == O}]
    set buf_nets [get_nets -quiet -of_objects $buf_out]
    set core_clk_pin [get_pins -quiet core/clk]
    set core_clk_nets [get_nets -quiet -of_objects $core_clk_pin]
    require [expr {[llength $buf_out] == 1 && [llength $buf_nets] == 1}] "BUFG output is not uniquely connected"
    require [expr {[llength $core_clk_nets] == 1 && [get_property NAME [lindex $buf_nets 0]] eq [get_property NAME [lindex $core_clk_nets 0]]}] "Core clock is not driven by fixture BUFG"

    set regs [all_registers -quiet -clock core_clk]
    set core_regs [get_cells -quiet -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *core*}]
    set dont_touch [get_cells -quiet -hier -filter {DONT_TOUCH == 1}]
    require [expr {[llength $regs] > 0}] "No clocked registers remain"
    require [expr {[llength $core_regs] > 0}] "No sequential cells remain under the core hierarchy"
    require [expr {[llength $dont_touch] == 0}] "Unexpected DONT_TOUCH cells: $dont_touch"

    set data_inputs [get_ports {rst_n load_seed[*] request_valid request_taps[*] request_lanes[*] request_sites[*] cancel observe_ready}]
    set clock_port [get_ports clk]
    set expected_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
    set output_ports [all_outputs]
    require [expr {[llength $data_inputs] > 0}] "No explicit data input ports matched in the timing constraints"
    require [expr {[lsort [get_property NAME $expected_inputs]] eq [lsort [get_property NAME $data_inputs]]}] "Explicit input budget does not match all top-level data inputs"
    require [expr {[llength $output_ports] == [llength [get_ports {request_ready scan_valid scan_word[*] scan_overflow scan_site[*] scan_lane[*] scan_lane_count[*] scan_last scan_job_done protocol_error}]]}] "At least one top-level output is missing from the 0/0.5 ns output budget"

    set f [open [file join $directory ${phase}_clock_topology.txt] w]
    puts $f "CLOCK core_clk PERIOD_NS $period_ns SOURCE [get_property SOURCE_PINS [lindex $clocks 0]]"
    puts $f "BUFG_COUNT [llength $buf_cells]"
    foreach c $buf_cells { puts $f "BUFG [get_property NAME $c] REF [get_property REF_NAME $c]" }
    puts $f "REGISTER_COUNT [llength $regs]"
    puts $f "CORE_SEQUENTIAL_CELL_COUNT [llength $core_regs]"
    puts $f "DONT_TOUCH_CELL_COUNT [llength $dont_touch]"
    puts $f "CORE_CLOCK_NET [get_property NAME [lindex $core_clk_nets 0]]"
    puts $f "INPUT_PORTS [lsort [get_property NAME $data_inputs]]"
    puts $f "INPUT_DELAY_NS min=0.000 max=1.000 source=explicit_measurement_assumption"
    puts $f "OUTPUT_PORTS [lsort [get_property NAME $output_ports]]"
    puts $f "OUTPUT_DELAY_NS min=0.000 max=0.500 load_pf=5.000"
    puts $f "CLOCK_UNCERTAINTY_NS 0.100"
    close $f

    set checked [check_timing -verbose -return_string]
    set f [open [file join $directory check_timing_${phase}.rpt] w]
    puts $f $checked
    close $f
    set categories {no_clock constant_clock pulse_width_clock unconstrained_internal_endpoints no_input_delay no_output_delay multiple_clock generated_clocks loops partial_input_delay partial_output_delay latch_loops}
    foreach category $categories {
        set pattern [format {checking\s+%s\s+\(([0-9]+)\)} $category]
        require [regexp $pattern $checked ignored count] "Missing check_timing category $category"
        require [expr {$count == 0}] "Nonzero check_timing $category: $count"
    }
    report_pulse_width -file [file join $directory pulse_width_${phase}.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $directory timing_${phase}.rpt]

    set all_setup [get_timing_paths -quiet -delay_type max -max_paths 1]
    set all_hold [get_timing_paths -quiet -delay_type min -max_paths 1]
    set core_setup [write_path_class_report $directory $phase core_internal_setup max $core_regs $core_regs]
    set core_hold [write_path_class_report $directory $phase core_internal_hold min $core_regs $core_regs]
    set input_setup [write_path_class_report $directory $phase input_to_register_setup max $data_inputs $regs]
    set input_hold [write_path_class_report $directory $phase input_to_register_hold min $data_inputs $regs]
    set output_setup [write_path_class_report $directory $phase register_to_output_setup max $regs $output_ports]
    set output_hold [write_path_class_report $directory $phase register_to_output_hold min $regs $output_ports]
    set internal_setup [write_path_class_report $directory $phase register_to_register_setup max $regs $regs]
    set internal_hold [write_path_class_report $directory $phase register_to_register_hold min $regs $regs]
    require [expr {[llength $all_setup] > 0 && [llength $all_hold] > 0}] "Missing all-design setup/hold path"
    require [expr {[llength [lindex $core_setup 0]] > 0 && [llength [lindex $core_hold 0]] > 0}] "Missing core-internal setup/hold path"
    require [expr {[llength [lindex $input_setup 0]] > 0 && [llength [lindex $input_hold 0]] > 0}] "Missing constrained input setup/hold path"
    require [expr {[llength [lindex $output_setup 0]] > 0 && [llength [lindex $output_hold 0]] > 0}] "Missing constrained output setup/hold path"
    require [expr {[llength [lindex $internal_setup 0]] > 0 && [llength [lindex $internal_hold 0]] > 0}] "Missing register-to-register setup/hold path"
    set timing_f [open [file join $directory ${phase}_timing_classes.txt] w]
    puts $timing_f "TIMING_CLASSES phase=$phase all_setup_ns=[first_path_slack $all_setup] all_hold_ns=[first_path_slack $all_hold] core_setup_ns=[lindex $core_setup 1] core_hold_ns=[lindex $core_hold 1] input_setup_ns=[lindex $input_setup 1] input_hold_ns=[lindex $input_hold 1] output_setup_ns=[lindex $output_setup 1] output_hold_ns=[lindex $output_hold 1] internal_setup_ns=[lindex $internal_setup 1] internal_hold_ns=[lindex $internal_hold 1]"
    close $timing_f
    puts "HANDSHAKE_TIMING_CHECK phase=$phase bufg=[llength $buf_cells] registers=[llength $regs] core_regs=[llength $core_regs] check_categories=[llength $categories] all_setup_ns=[first_path_slack $all_setup] all_hold_ns=[first_path_slack $all_hold] core_setup_ns=[lindex $core_setup 1] core_hold_ns=[lindex $core_hold 1] input_setup_ns=[lindex $input_setup 1] input_hold_ns=[lindex $input_hold 1] output_setup_ns=[lindex $output_setup 1] output_hold_ns=[lindex $output_hold 1] status=PASS"
}

proc write_structure_evidence {directory phase} {
    set dsp_cells [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]
    set ram_cells [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}]
    set weight_groups [dict create]
    set activation_groups [dict create]
    set f [open [file join $directory structure_${phase}.txt] w]
    foreach cell $dsp_cells {
        puts $f "DSP [get_property NAME $cell] REF [get_property REF_NAME $cell] AREG [get_property AREG $cell] BREG [get_property BREG $cell] MREG [get_property MREG $cell] PREG [get_property PREG $cell]"
    }
    foreach cell $ram_cells {
        set name [get_property NAME $cell]
        puts $f "RAM [get_property REF_NAME $cell] $name"
        if {[regexp {gen_weight_bank\[(\d+)\]} $name ignored bank]} {
            dict set weight_groups $bank 1
        }
        if {[regexp {gen_activation_bank\[(\d+)\].*gen_activation_site\[(\d+)\]} $name ignored bank site]} {
            dict set activation_groups "$bank,$site" 1
        }
    }
    close $f
    set weight_count [dict size $weight_groups]
    set activation_count [dict size $activation_groups]
    set accumulator_cells [get_cells -quiet -hier -filter {NAME =~ *core*accumulator*}]
    set result_cells [get_cells -quiet -hier -filter {NAME =~ *core*result_mem*}]
    set sum_cells [get_cells -quiet -hier -filter {NAME =~ *core*group_sum_q*}]
    set f [open [file join $directory structure_${phase}.txt] a]
    puts $f "STRUCTURE accumulator_cells=[llength $accumulator_cells] group_sum_cells=[llength $sum_cells] result_memory_cells=[llength $result_cells]"
    close $f
    puts "HANDSHAKE_STRUCTURE phase=$phase dsp=[llength $dsp_cells] ram_cells=[llength $ram_cells] weight_banks=$weight_count activation_bank_sites=$activation_count"
    require [expr {$weight_count == 4}] "Expected four retained weight RAM banks, found $weight_count"
    require [expr {$activation_count == 16}] "Expected all 16 retained activation bank/site RAM groups, found $activation_count"
    require [expr {[llength $accumulator_cells] > 0 && [llength $sum_cells] > 0 && [llength $result_cells] > 0}] "Core accumulator, group sum, or result memory did not remain inspectable in the synthesized hierarchy"
    return [list [llength $dsp_cells] [llength $ram_cells] $weight_count $activation_count]
}

proc main {frequency_mhz build_dir evidence_dir mode {checkpoint ""}} {
    set script_dir [file dirname [file normalize [info script]]]
    set project_dir [file join $build_dir project]
    set part xc7z100ffg900-2
    require [expr {[string first "2026.1" [version -short]] == 0}] "Requires Vivado 2026.1"
    require [expr {$frequency_mhz == 200}] "This fixture packet allows only one 200 MHz implementation"
    require [expr {$mode in {synth route}}] "Mode must be synth or route"
    set period_ns 5.000
    set_param general.maxThreads 2
    file mkdir $build_dir
    file mkdir $evidence_dir

    if {$mode eq "synth"} {
        create_project -force reuse_handshake_fixture $project_dir -part $part
        read_verilog [file join [file dirname $script_dir] tile_reuse_core_v2 z100_tile_reuse_core.v]
        read_verilog -sv [file join $script_dir z100_tile_reuse_handshake_fixture_top.sv]
        synth_design -top z100_tile_reuse_handshake_fixture_top -part $part -flatten_hierarchy none
        create_clock -name core_clk -period $period_ns [get_ports clk]
        read_xdc [file join $script_dir handshake_constraints.xdc]
    } else {
        require [file exists $checkpoint] "Synthesis checkpoint not found: $checkpoint"
        open_checkpoint $checkpoint
    }
    if {$mode eq "synth"} { write_checkpoint -force [file join $build_dir unreviewed_synth.dcp] }
    puts "HANDSHAKE_FIXTURE_VERSION [version -short] DEVICE $part FREQUENCY_MHZ $frequency_mhz MODE $mode"
    write_clock_and_timing_evidence $evidence_dir $mode $period_ns
    set resources [write_resource_snapshot $evidence_dir $mode]
    set structure [write_structure_evidence $evidence_dir $mode]
    set lut [lindex $resources 0]
    set dsp [lindex $resources 1]
    set bram [lindex $resources 2]
    set bufg [lindex $resources 3]
    set core_dsp [lindex $structure 0]
    require [expr {$dsp == 512 && $core_dsp == 512}] "Expected all 512 live core multipliers to map to DSP cells; observed total=$dsp core=$core_dsp"
    require [expr {abs($bram - 38.0) < 0.01}] "Expected 38 BRAM36 equivalents as in unchanged v2, observed $bram"
    require [expr {$bufg == 1}] "Expected exactly one BUFG"
    require [expr {$lut < 100000}] "LUT count exceeds broad sanity cap: $lut"
    if {$mode eq "synth"} {
        write_checkpoint -force [file join $build_dir post_synth.dcp]
        puts "HANDSHAKE_SYNTHESIS_REVIEW_READY dsp=$dsp bram36_equivalent=$bram lut=$lut"
        close_design
        return
    }

    opt_design
    place_design
    write_resource_snapshot $evidence_dir placed
    write_checkpoint -force [file join $build_dir post_place.dcp]
    phys_opt_design
    route_design
    report_route_status -file [file join $evidence_dir route_status.rpt]
    write_clock_and_timing_evidence $evidence_dir routed $period_ns
    set resources [write_resource_snapshot $evidence_dir routed]
    write_structure_evidence $evidence_dir routed
    report_clock_networks -clocks [get_clocks core_clk] -file [file join $evidence_dir clock_networks.rpt]
    report_drc -file [file join $evidence_dir drc_routed.rpt]

    set all_regs [all_registers -quiet -clock core_clk]
    set core_regs [get_cells -quiet -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *core*}]
    set data_inputs [get_ports {rst_n load_seed[*] request_valid request_taps[*] request_lanes[*] request_sites[*] cancel observe_ready}]
    set output_ports [all_outputs]
    set setup_all [get_timing_paths -quiet -delay_type max -max_paths 1]
    set hold_all [get_timing_paths -quiet -delay_type min -max_paths 1]
    set setup_core [get_timing_paths -quiet -delay_type max -from $core_regs -to $core_regs -max_paths 1]
    set hold_core [get_timing_paths -quiet -delay_type min -from $core_regs -to $core_regs -max_paths 1]
    set setup_input [get_timing_paths -quiet -delay_type max -from $data_inputs -to $all_regs -max_paths 1]
    set hold_input [get_timing_paths -quiet -delay_type min -from $data_inputs -to $all_regs -max_paths 1]
    set setup_output [get_timing_paths -quiet -delay_type max -from $all_regs -to $output_ports -max_paths 1]
    set hold_output [get_timing_paths -quiet -delay_type min -from $all_regs -to $output_ports -max_paths 1]
    set setup_internal [get_timing_paths -quiet -delay_type max -from $all_regs -to $all_regs -max_paths 1]
    set hold_internal [get_timing_paths -quiet -delay_type min -from $all_regs -to $all_regs -max_paths 1]
    write_checkpoint -force [file join $build_dir routed.dcp]

    set route_file [open [file join $evidence_dir route_status.rpt] r]
    set route_text [read $route_file]
    close $route_file
    require [regexp {# of routable nets\.+\s*:\s*(\d+)} $route_text ignored routable] "Missing routable count"
    require [regexp {# of fully routed nets\.+\s*:\s*(\d+)} $route_text ignored routed] "Missing fully routed count"
    require [regexp {# of nets with routing errors\.+\s*:\s*(\d+)} $route_text ignored route_errors] "Missing route error count"
    require [expr {$routable == $routed && $route_errors == 0}] "Route counts incomplete: $routable/$routed, errors=$route_errors"
    require [expr {[llength $setup_all] == 1 && [llength $hold_all] == 1}] "Missing overall internal setup/hold paths"
    require [expr {[llength $setup_core] == 1 && [llength $hold_core] == 1}] "Missing core internal setup/hold paths"
    require [expr {[llength $setup_input] == 1 && [llength $hold_input] == 1}] "Missing constrained input setup/hold path"
    require [expr {[llength $setup_output] == 1 && [llength $hold_output] == 1}] "Missing constrained external output setup/hold path"
    require [expr {[llength $setup_internal] == 1 && [llength $hold_internal] == 1}] "Missing register-to-register setup/hold path"
    puts "HANDSHAKE_ROUTE_RESULT all_setup_ns=[get_property SLACK [lindex $setup_all 0]] all_hold_ns=[get_property SLACK [lindex $hold_all 0]] internal_setup_ns=[get_property SLACK [lindex $setup_internal 0]] internal_hold_ns=[get_property SLACK [lindex $hold_internal 0]] core_setup_ns=[get_property SLACK [lindex $setup_core 0]] core_hold_ns=[get_property SLACK [lindex $hold_core 0]] input_setup_ns=[get_property SLACK [lindex $setup_input 0]] input_hold_ns=[get_property SLACK [lindex $hold_input 0]] output_setup_ns=[get_property SLACK [lindex $setup_output 0]] output_hold_ns=[get_property SLACK [lindex $hold_output 0]] routable=$routable routed=$routed route_errors=$route_errors lut=[lindex $resources 0] dsp=[lindex $resources 1] bram36_equivalent=[lindex $resources 2] bufg=[lindex $resources 3] registers=[llength $all_regs] core_registers=[llength $core_regs]"
    close_project
}

if {[info exists ::handshake_library_only] && $::handshake_library_only} { return }

if {[catch {main {*}$argv} message options]} {
    puts stderr "HANDSHAKE_FIXTURE_FAIL $message"
    if {[dict exists $options -errorinfo]} { puts stderr [dict get $options -errorinfo] }
    exit 1
}
exit 0
