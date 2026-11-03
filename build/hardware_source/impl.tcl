proc z100_route_status_check {text} {
    set patterns [list \
        routable_nets {# of routable nets} \
        fully_routed_nets {# of fully routed nets} \
        route_error_nets {# of nets with routing errors}]
    set values [dict create routable_nets -1 fully_routed_nets -1 route_error_nets -1]
    foreach {key label} $patterns {
        set pattern [format {^[ \t]*%s[. ]*:[ \t]*([0-9]+)[ \t]*:} $label]
        if {[regexp -lineanchor -- $pattern $text -> value]} {
            dict set values $key $value
        }
    }
    set counts_complete [expr {[dict get $values routable_nets] >= 0 &&
                               [dict get $values fully_routed_nets] >= 0 &&
                               [dict get $values route_error_nets] >= 0}]
    set pass [expr {$counts_complete && [dict get $values routable_nets] > 0 &&
                    [dict get $values fully_routed_nets] == [dict get $values routable_nets] &&
                    [dict get $values route_error_nets] == 0}]
    dict set values counts_complete $counts_complete
    dict set values pass $pass
    return $values
}

proc z100_timing_checks {text} {
    set required {no_clock constant_clock pulse_width_clock unconstrained_internal_endpoints \
                  no_input_delay no_output_delay multiple_clock generated_clocks loops \
                  partial_input_delay partial_output_delay latch_loops}
    set counts [dict create]
    set occurrences [dict create]
    foreach name $required {
        dict set counts $name -1
        dict set occurrences $name 0
    }
    foreach line [split $text "\n"] {
        if {[regexp {^[ \t]*[0-9]+[.] checking ([a-z_]+)[ \t]*\(([0-9]+)\)} $line -> name value] &&
            [dict exists $counts $name]} {
            dict incr occurrences $name
            if {[dict get $counts $name] < $value} {
                dict set counts $name $value
            }
        }
    }
    set coverage_complete 1
    set all_zero 1
    foreach name $required {
        if {[dict get $occurrences $name] == 0 || [dict get $counts $name] < 0} {
            set coverage_complete 0
            set all_zero 0
        } elseif {[dict get $counts $name] != 0} {
            set all_zero 0
        }
    }
    set result [dict create coverage_complete $coverage_complete pass [expr {$coverage_complete && $all_zero}]]
    dict set result counts $counts
    dict set result occurrences $occurrences
    return $result
}

proc z100_pulse_metrics {text} {
    foreach line [split $text "\n"] {
        set fields [regexp -all -inline {[^ \t]+} [string trim $line]]
        if {[llength $fields] != 12} { continue }
        set numeric 1
        foreach index {8 9} {
            if {![string is double -strict [lindex $fields $index]]} { set numeric 0 }
        }
        foreach index {10 11} {
            if {![string is integer -strict [lindex $fields $index]]} { set numeric 0 }
        }
        if {$numeric} {
            return [dict create \
                wpws_ns [lindex $fields 8] \
                tpws_ns [lindex $fields 9] \
                pulse_width_fail_endpoints [lindex $fields 10] \
                pulse_width_total_endpoints [lindex $fields 11]]
        }
    }
    error "Could not parse pulse-width columns from the timing summary"
}

# Z100 full platform, built from the packaged RTL and block design without an
# incremental checkpoint. The post-place checkpoint separates synthesis and
# place from the longer route stage.
#
#   -Stage place : new project -> BD -> synth -> opt -> place -> post_place.dcp
#                  (+ congestion / utilization / timing reports, one-line verdict)
#   -Stage route : open this run's post_place.dcp -> phys_opt -> route -> reports
#                  -> acceptance.json; a separate gated stage exports bit + XSA
#
# Env: Z100_S_RTL  (RTL dir, default p4s12/rtl)
#      Z100_S_BD   (system_bd.tcl)
#      Z100_S_OUT  (run output dir)
#      Z100_S_SITES (expected SITES, default 12; DSP floor is derived from it)
#      Z100_S_PLACE_DCP (route stage only: this run's post_place.dcp)
#
# Directives are packaged as rtl/s12_directives.tcl and loaded by both stages.
if {![string match 2026.1* [version -short]]} {error "Requires Vivado 2026.1"}
puts "Z100_S12_BUILD version=[version -short] part=xc7z100ffg900-2 sites=12"
set stage {place}
if {[info exists ::env(Z100_S_STAGE)]} { set stage $::env(Z100_S_STAGE) }
set rtl   [file normalize $::env(Z100_S_RTL)]
# system_bd.tcl (shared with the S20 flow) resolves its MAP_FILE/TILE_FILE
# through ::z100_rtl, so this global must exist before the BD is sourced.
set ::z100_rtl $rtl
set bdtcl [file normalize $::env(Z100_S_BD)]
set out   [file normalize $::env(Z100_S_OUT)]
set sites 12
if {[info exists ::env(Z100_S_SITES)]} { set sites $::env(Z100_S_SITES) }

proc require {c m} { if {!$c} {error $m} }
proc stamp {name t0} { puts [format "Z100_S12_STAGE %s elapsed_s=%.1f" $name [expr {([clock milliseconds]-$t0)/1000.0}]]; flush stdout }
proc reports {tag} {
    global out
    report_utilization -file [file join $out ${tag}_utilization.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out ${tag}_timing.rpt]
    report_timing -delay_type max -max_paths 100 -nworst 1 -input_pins -path_type full_clock_expanded -file [file join $out ${tag}_setup_paths.rpt]
}
proc path_tsv {file limit} {
    set f [open $file w]
    puts $f "slack\tlevels\tstart\tend"
    foreach p [get_timing_paths -quiet -max_paths 30000 -nworst 1 -setup -slack_lesser_than $limit] {
        puts $f [format "%.3f\t%d\t%s\t%s" [get_property SLACK $p] [get_property LOGIC_LEVELS $p] \
            [get_property NAME [get_property STARTPOINT_PIN $p]] [get_property NAME [get_property ENDPOINT_PIN $p]]]
    }
    close $f
}
proc identity {stage} {
    set f0 [get_clocks -quiet clk_fpga_0]
    require [expr {[llength $f0]==1 && abs([get_property PERIOD $f0]-10.0)<1e-6}] "clk_fpga_0 must be 10.000 ns at $stage"
    require [expr {[llength [get_pblocks -quiet]]==0}] "Pblocks not allowed"
    require [expr {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX==1}]]==0}] "Black box at $stage"
    puts "Z100_S12_IDENTITY stage=$stage dsp=[llength [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]]"
}
# Worst congestion level over all directions, read back from the report we just
# wrote. The S20 run peaked at level 6 (East, 130%); level is the number that
# says whether the router has room, so it belongs in the one-line verdict.
proc congestion_level {rpt} {
    set lvl 0
    if {![catch {
        set f [open $rpt r]; set txt [read $f]; close $f
        foreach d [regexp -all -inline {Global\s*\|\s*(\d+)\s*\|} $txt] {
            if {[string is integer -strict $d] && $d > $lvl} { set lvl $d }
        }
    }]} {}
    return $lvl
}

# ---- DSP floor from SITES: mult = SITES*32*4/2, accum = SITES*32, +96 requant
# ---- S20 -> 1280+640+96 = 2016. S12 -> 768+384+96 = 1248; floor at 1240.
set dsp_floor [expr {$sites*64 + $sites*32 + 96 - 8}]

if {$stage eq "place"} {
    set_param general.maxThreads 4
    set t0 [clock milliseconds]
    create_project platform [file join $out project] -part xc7z100ffg900-2
    add_files -norecurse [lsort [glob -directory $rtl *.sv]]
    update_compile_order -fileset sources_1
    source $bdtcl
    require [expr {[get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells rst_fclk0]] == 0}] "Reset polarity must be active-low"
    validate_bd_design
    save_bd_design
    require [expr {[get_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ [get_bd_cells processing_system7_0]] == 100}] "FCLK not 100 MHz"
    require [expr {[get_property CONFIG.PCW_USE_S_AXI_ACP [get_bd_cells processing_system7_0]] == 1}] "ACP disabled"
    require [expr {[get_property CONFIG.PCW_USE_S_AXI_HP0 [get_bd_cells processing_system7_0]] == 0}] "Unexpected HP0"
    require [expr {[get_property CONFIG.PCW_USE_DEFAULT_ACP_USER_VAL [get_bd_cells processing_system7_0]] == 1}] "ACP USER override disabled"
    foreach key {PCW_S_AXI_ACP_ARUSER_VAL PCW_S_AXI_ACP_AWUSER_VAL} {
        require [expr {[get_property CONFIG.$key [get_bd_cells processing_system7_0]] == 31}] "Wrong ACP USER"
    }
    require [expr {[get_property CONFIG.DATA_WIDTH [get_bd_intf_pins processing_system7_0/S_AXI_ACP]] == 64}] "ACP not 64-bit"
    require [expr {[get_property CONFIG.ID_WIDTH [get_bd_intf_pins native_conv_backend_local_control_0/m_axi]] == 3}] "Wrong ACP wrapper ID width"
    generate_target all [get_files */system.bd]
    set wrappers [make_wrapper -files [get_files */system.bd] -top]
    add_files -norecurse $wrappers
    set_property top system_wrapper [get_filesets sources_1]
    update_compile_order -fileset sources_1
    stamp bd $t0

    # ---- directives: same file the route stage must use, recorded in the run
    set ::z_synth_dir Default; set ::z_opt_dir Default; set ::z_place_dir Default
    set ::z_phys_dir Default;  set ::z_route_dir Default
    set zdir [file join $rtl s12_directives.tcl]
    if {[file exists $zdir]} { source $zdir; file copy -force $zdir [file join $out directives.tcl] }
    puts "Z100_S12_DIRECTIVES synth=$::z_synth_dir opt=$::z_opt_dir place=$::z_place_dir phys=$::z_phys_dir route=$::z_route_dir"

    set t0 [clock milliseconds]
    set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY none [get_runs synth_1]
    if {$::z_synth_dir ne "Default"} { set_property STEPS.SYNTH_DESIGN.ARGS.DIRECTIVE $::z_synth_dir [get_runs synth_1] }
    launch_runs synth_1 -jobs 4
    wait_on_run synth_1
    require [expr {[get_property PROGRESS [get_runs synth_1]] eq {100%}}] "Platform synthesis failed"
    open_run synth_1
    stamp synth $t0
    set n_dsp [llength [get_cells -hier -quiet -filter {REF_NAME == DSP48E1}]]
    puts "Z100_S12_SANITY dsp=$n_dsp floor=$dsp_floor sites=$sites"
    require [expr {$n_dsp >= $dsp_floor}] "Synthesized design has only $n_dsp DSP48E1 (expected >= $dsp_floor for SITES=$sites): datapath was trimmed"
    # S12 must not silently fall back to the S20 datapath.
    require [expr {$n_dsp < 2016}] "Synthesized design still has $n_dsp DSP48E1 (S20 level): SITES override did not take effect"
    identity synth
    write_checkpoint -force [file join $out post_synth.dcp]
    reports synth
    report_utilization -hierarchical -hierarchical_depth 5 -file [file join $out synth_util_hier.rpt]
    report_drc -checks [get_drc_checks LUTLP-1] -file [file join $out synth_loops.rpt]
    set nloop [llength [get_drc_violations -quiet LUTLP-1*]]
    require [expr {$nloop==0}] "Combinational loop after synthesis"

    set_param general.maxThreads 8
    set t0 [clock milliseconds]; opt_design -directive $::z_opt_dir; stamp opt $t0; identity opt
    set t0 [clock milliseconds]; place_design -directive $::z_place_dir; stamp place $t0; identity place
    reports placed
    report_design_analysis -congestion -file [file join $out placed_congestion.rpt]
    path_tsv [file join $out placed_paths.tsv] 0.5
    write_checkpoint -force [file join $out post_place.dcp]

    # ---- checkpoint verdict: everything the go/no-go decision needs, one line
    set pwns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
    set pwhs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
    set pnfail [llength [get_timing_paths -quiet -max_paths 100000 -nworst 1 -setup -slack_lesser_than 0]]
    # Slice LUT usage straight from the report we just wrote (no extra query cost)
    set pluts 0
    catch {
        set uf [open [file join $out placed_utilization.rpt] r]
        set utxt [read $uf]; close $uf
        if {[regexp {Slice LUTs\s*\|\s*(\d+)} $utxt -> pluts]} {}
    }
    set cong [congestion_level [file join $out placed_congestion.rpt]]
    puts "Z100_S12_PLACE_VERDICT wns=$pwns whs=$pwhs setup_fail=$pnfail luts=$pluts congestion=$cong dsp=$n_dsp sites=$sites"
    set fd [open [file join $out place_verdict.json] w]
    puts $fd [format {{"stage":"place","sites":%d,"dsp":%d,"wns_ns":%.3f,"whs_ns":%.3f,"setup_fail_endpoints":%d,"luts":%d,"congestion_level":%d}} \
        $sites $n_dsp $pwns $pwhs $pnfail $pluts $cong]
    close $fd
    puts "Z100_S12_STAGE_COMPLETE place"
    exit
}

if {$stage ne "route"} { error "Unknown -Stage $stage" }

# ---------------- route stage: resume from a saved post-place checkpoint ------
if {![info exists ::env(Z100_S_PLACE_DCP)]} { error "Z100_S_PLACE_DCP not set" }
set pdcp [file normalize $::env(Z100_S_PLACE_DCP)]
require [file exists $pdcp] "Missing post-place checkpoint $pdcp"
set ::z_synth_dir Default; set ::z_opt_dir Default; set ::z_place_dir Default
set ::z_phys_dir Default;  set ::z_route_dir Default
set zdir [file join $rtl s12_directives.tcl]
if {[file exists $zdir]} { source $zdir; file copy -force $zdir [file join $out directives.tcl] }
puts "Z100_S12_DIRECTIVES phys=$::z_phys_dir route=$::z_route_dir"

set_param general.maxThreads 8
open_checkpoint $pdcp
identity place_resumed
set t0 [clock milliseconds]; phys_opt_design -directive $::z_phys_dir; stamp physopt $t0
set t0 [clock milliseconds]; phys_opt_design -hold_fix; stamp hold_fix $t0
reports pre_route
write_checkpoint -force [file join $out pre_route.dcp]
set t0 [clock milliseconds]; route_design -directive $::z_route_dir; stamp route $t0; identity routed
write_checkpoint -force [file join $out post_route.dcp]
reports routed
path_tsv [file join $out routed_paths.tsv] 0.3
set timing_summary [report_timing_summary -delay_type min_max -report_unconstrained -return_string]
set pulse_metrics [z100_pulse_metrics $timing_summary]
set wpws [dict get $pulse_metrics wpws_ns]
set tpws [dict get $pulse_metrics tpws_ns]
set pulse_fail [dict get $pulse_metrics pulse_width_fail_endpoints]
set pulse_total [dict get $pulse_metrics pulse_width_total_endpoints]
set pulse_text [report_pulse_width -return_string]
set pf [open [file join $out pulse_width_routed.rpt] w]; puts $pf $pulse_text; close $pf
report_route_status -file [file join $out route_status.rpt]
report_timing -delay_type min -max_paths 50 -nworst 1 -input_pins -file [file join $out routed_hold_paths.rpt]
report_drc -file [file join $out drc_routed.rpt]
report_cdc -file [file join $out cdc_routed.rpt]
report_exceptions -file [file join $out exceptions_routed.rpt]
set f [open [file join $out check_timing_routed.rpt] w]; puts $f [check_timing -verbose -return_string]; close $f

set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
set tns 0.0; set nfail 0
foreach p [get_timing_paths -quiet -max_paths 100000 -nworst 1 -setup -slack_lesser_than 0] { set tns [expr {$tns+[get_property SLACK $p]}]; incr nfail }
set nhold [llength [get_timing_paths -quiet -max_paths 100000 -nworst 1 -hold -slack_lesser_than 0]]
set rs [report_route_status -return_string]
set route_check [z100_route_status_check $rs]
set route_counts_complete [dict get $route_check counts_complete]
set routable_nets [dict get $route_check routable_nets]
set fully_routed_nets [dict get $route_check fully_routed_nets]
set unrouted [dict get $route_check route_error_nets]
set route_complete [dict get $route_check pass]
set drc [report_drc -return_string]
set crit [expr {[llength [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]] > 0}]
set check_text [check_timing -verbose -return_string]
set tf [open [file join $out check_timing_routed.rpt] w]
puts $tf $check_text
close $tf
set timing_check [z100_timing_checks $check_text]
set timing_coverage [dict get $timing_check coverage_complete]
set timing_checks_pass [dict get $timing_check pass]
set timing_counts [dict get $timing_check counts]
set unconstr [dict get $timing_counts unconstrained_internal_endpoints]
set all_timing_zero [format {"no_clock":%d,"constant_clock":%d,"pulse_width_clock":%d,"unconstrained_internal_endpoints":%d,"no_input_delay":%d,"no_output_delay":%d,"multiple_clock":%d,"generated_clocks":%d,"loops":%d,"partial_input_delay":%d,"partial_output_delay":%d,"latch_loops":%d} \
    [dict get $timing_counts no_clock] [dict get $timing_counts constant_clock] \
    [dict get $timing_counts pulse_width_clock] [dict get $timing_counts unconstrained_internal_endpoints] \
    [dict get $timing_counts no_input_delay] [dict get $timing_counts no_output_delay] \
    [dict get $timing_counts multiple_clock] [dict get $timing_counts generated_clocks] \
    [dict get $timing_counts loops] [dict get $timing_counts partial_input_delay] \
    [dict get $timing_counts partial_output_delay] [dict get $timing_counts latch_loops]]
set pass [expr {$wns>=0 && $whs>=0 && $wpws>=0 && $tpws>=0 && $nfail==0 && $nhold==0 && $pulse_fail==0 && $pulse_total>0 && $route_complete && !$crit && $timing_checks_pass && $unconstr==0}]
set fd [open [file join $out acceptance.json] w]
puts $fd [format {{"wns_ns":%.3f,"whs_ns":%.3f,"wpws_ns":%.3f,"tpws_ns":%.3f,"tns_ns":%.3f,"setup_fail_endpoints":%d,"hold_fail_endpoints":%d,"pulse_width_fail_endpoints":%d,"pulse_width_total_endpoints":%d,"route_status_counts_complete":%s,"routable_nets":%d,"fully_routed_nets":%d,"route_error_nets":%d,"route_completeness_pass":%s,"drc_error_or_critical":%d,"timing_checks_coverage_complete":%s,"timing_checks_pass":%s,"timing_check_counts":{%s},"unconstrained_internal":%d,"pass":%s,"sites":%s,"note":"FULL PLATFORM from zero, SITES descoped"}} \
    $wns $whs $wpws $tpws $tns $nfail $nhold $pulse_fail $pulse_total \
    [expr {$route_counts_complete ? "true" : "false"}] $routable_nets $fully_routed_nets $unrouted \
    [expr {$route_complete ? "true" : "false"}] $crit \
    [expr {$timing_coverage ? "true" : "false"}] [expr {$timing_checks_pass ? "true" : "false"}] \
    $all_timing_zero $unconstr [expr {$pass?"true":"false"}] $sites]
close $fd
puts "Z100_S12_ACCEPT wns=$wns whs=$whs wpws=$wpws tpws=$tpws tns=$tns setup_fail=$nfail hold_fail=$nhold pulse_fail=$pulse_fail routeable=$routable_nets fully_routed=$fully_routed_nets route_err=$unrouted timing_checks=$timing_checks_pass pass=$pass"

# Final export performs its own full timing, route, DRC, and coverage gates.
puts "Z100_S12_COMPLETE pass=$pass export_required=1"
exit
