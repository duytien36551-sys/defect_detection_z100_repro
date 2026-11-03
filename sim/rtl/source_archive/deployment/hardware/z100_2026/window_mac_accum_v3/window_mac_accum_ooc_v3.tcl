proc require {condition message} {
    if {!$condition} { error $message }
}

proc write_dsp_census {path} {
    set cells [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]
    array set modes {}
    set total [llength $cells]
    set multiply 0
    set none 0
    set other 0
    set feedback_owner 0
    set f [open $path w]
    puts $f "cell\tUSE_MULT\tUSE_SIMD\tPREG"
    foreach cell $cells {
        set name [get_property NAME $cell]
        set mode [get_property -quiet USE_MULT $cell]
        set simd [get_property -quiet USE_SIMD $cell]
        set preg [get_property -quiet PREG $cell]
        if {$mode eq ""} { set mode UNAVAILABLE }
        if {$simd eq ""} { set simd UNAVAILABLE }
        if {$preg eq ""} { set preg UNAVAILABLE }
        puts $f "$name\t$mode\t$simd\t$preg"
        if {![info exists modes($mode)]} { set modes($mode) 0 }
        incr modes($mode)
        if {$mode eq "MULTIPLY"} {
            incr multiply
        } elseif {$mode eq "NONE"} {
            incr none
            if {[string match -nocase "*feedback_accum*" $name] || [string match -nocase "*feedback_next*" $name]} {
                incr feedback_owner
            }
        } else {
            incr other
        }
    }
    close $f
    set summary [file rootname $path]
    set sf [open ${summary}_summary.txt w]
    puts $sf "DSP48E1_TOTAL $total"
    puts $sf "USE_MULT_MULTIPLY $multiply"
    puts $sf "USE_MULT_NONE $none"
    puts $sf "USE_MULT_OTHER $other"
    puts $sf "USE_MULT_NONE_FEEDBACK_OWNER $feedback_owner"
    foreach mode [lsort [array names modes]] { puts $sf "USE_MULT_MODE $mode $modes($mode)" }
    close $sf
    return [list $total $multiply $none $other $feedback_owner]
}

proc capture_resources {evidence_dir} {
    set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
    set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
    set dsp [llength [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]]
    set ram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
    set ram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
    set bram [expr {$ram36 + $ram18 / 2.0}]
    set latches [llength [get_cells -quiet -hier -filter {REF_NAME =~ LD*}]]
    set blackboxes [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]
    set f [open [file join $evidence_dir resources_synth.txt] w]
    puts $f "RESOURCES lut=$lut ff=$ff dsp48e1=$dsp ramb36=$ram36 ramb18=$ram18 bram36_equivalent=$bram latches=$latches blackboxes=[llength $blackboxes]"
    close $f
    report_utilization -file [file join $evidence_dir utilization_synth.rpt]
    report_utilization -hierarchical -hierarchical_depth 4 \
        -file [file join $evidence_dir utilization_hierarchical_synth.rpt]
    return [list $lut $ff $dsp $bram $latches [llength $blackboxes]]
}

proc main {build_dir evidence_dir} {
    set script_dir [file dirname [file normalize [info script]]]
    set rtl_file [file join $script_dir z100_window_mac_accum_v3.sv]
    set project_dir [file join $build_dir project]
    set part xc7z100ffg900-2
    require [expr {[string first "2026.1" [version -short]] == 0}] "Requires Vivado 2026.1"
    require [file exists $rtl_file] "Missing v3 accumulator RTL"
    set_param general.maxThreads 2
    file mkdir $build_dir
    file mkdir $evidence_dir
    create_project -force window_mac_accum_v3_ooc $project_dir -part $part
    read_verilog -sv $rtl_file
    synth_design -top z100_window_mac_accum_v3 -part $part -flatten_hierarchy none
    puts "WINDOW_MAC_ACCUM_V3_OOC_SYNTH_DONE VERSION [version -short] DEVICE $part THREADS 2"

    # Persist diagnosis before checking the fixed gate: a failed DSP mapping
    # must still leave a checkpoint, complete cell census, and utilization.
    write_checkpoint -force [file join $evidence_dir post_synth.dcp]
    set dsp [write_dsp_census [file join $evidence_dir dsp48e1_synth.tsv]]
    set resources [capture_resources $evidence_dir]
    set summary [open [file join $evidence_dir synth_summary.txt] w]
    puts $summary "TOP z100_window_mac_accum_v3"
    puts $summary "PART $part"
    puts $summary "DSP_TOTAL [lindex $dsp 0] MULTIPLY [lindex $dsp 1] NONE [lindex $dsp 2] OTHER [lindex $dsp 3] NONE_FEEDBACK_OWNER [lindex $dsp 4]"
    puts $summary "LUT [lindex $resources 0] FF [lindex $resources 1] BRAM36_EQ [lindex $resources 3] LATCH [lindex $resources 4] BLACKBOX [lindex $resources 5]"
    close $summary

    require [expr {[lindex $dsp 0] == 640 && [lindex $dsp 1] == 512 && [lindex $dsp 2] == 128 && [lindex $dsp 3] == 0}] \
        "DSP census changed: total=[lindex $dsp 0] MULTIPLY=[lindex $dsp 1] NONE=[lindex $dsp 2] other=[lindex $dsp 3]"
    require [expr {[lindex $dsp 4] == 128}] \
        "Expected 128 NONE DSPs owned by scalar feedback_accum; found [lindex $dsp 4]"
    require [expr {[lindex $resources 0] <= 35000}] "Slice LUT screen exceeded: [lindex $resources 0]"
    require [expr {[lindex $resources 1] <= 25000}] "FF screen exceeded: [lindex $resources 1]"
    require [expr {[lindex $resources 2] == 640}] "Expected 640 DSP48E1 cells, found [lindex $resources 2]"
    require [expr {[lindex $resources 3] <= 30.0}] "BRAM36-equivalent screen exceeded: [lindex $resources 3]"
    require [expr {[lindex $resources 4] == 0}] "Inferred latch cells: [lindex $resources 4]"
    require [expr {[lindex $resources 5] == 0}] "Black-box cells found: [lindex $resources 5]"
    puts "WINDOW_MAC_ACCUM_V3_OOC_PASS DSP=640 MULTIPLY=512 NONE=128 NONE_FEEDBACK_OWNER=128 LUT=[lindex $resources 0] FF=[lindex $resources 1] BRAM36_EQ=[lindex $resources 3]"
    close_project
}

if {$argc != 2} { error "usage: vivado -mode batch -source window_mac_accum_ooc_v3.tcl -tclargs BUILD_DIR EVIDENCE_DIR" }
main [lindex $argv 0] [lindex $argv 1]
exit 0
