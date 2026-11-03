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
    set accum_owner 0
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
            if {[string match "*accum_dsp*" $name] || [string match "*accum_plus_sum*" $name]} {
                incr accum_owner
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
    puts $sf "USE_MULT_NONE_ACCUM_OWNER $accum_owner"
    foreach mode [lsort [array names modes]] { puts $sf "USE_MULT_MODE $mode $modes($mode)" }
    close $sf
    require [expr {$total == 640 && $multiply == 512 && $none == 128 && $other == 0}] \
        "DSP census changed: total=$total MULTIPLY=$multiply NONE=$none other=$other"
    require [expr {$accum_owner == 128}] \
        "Expected all 128 NONE DSPs to implement accum_dsp feedback; found $accum_owner"
    return [list $total $multiply $none $other $accum_owner]
}

proc screen_resources {evidence_dir} {
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
    require [expr {$lut <= 35000}] "Slice LUT screen exceeded: $lut"
    require [expr {$ff <= 25000}] "FF screen exceeded: $ff"
    require [expr {$dsp == 640}] "Expected 640 DSP48E1 cells, found $dsp"
    require [expr {$bram <= 30.0}] "BRAM36-equivalent screen exceeded: $bram"
    require [expr {$latches == 0}] "Inferred latch cells: $latches"
    require [expr {[llength $blackboxes] == 0}] "Black-box cells found"
    return [list $lut $ff $dsp $bram $latches [llength $blackboxes]]
}

proc main {build_dir evidence_dir} {
    set script_dir [file dirname [file normalize [info script]]]
    set rtl_file [file join $script_dir z100_window_mac_accum_v2.sv]
    set project_dir [file join $build_dir project]
    set part xc7z100ffg900-2
    require [expr {[string first "2026.1" [version -short]] == 0}] "Requires Vivado 2026.1"
    require [file exists $rtl_file] "Missing v2 accumulator RTL"
    set_param general.maxThreads 2
    file mkdir $build_dir
    file mkdir $evidence_dir
    create_project -force window_mac_accum_v2_ooc $project_dir -part $part
    read_verilog -sv $rtl_file
    synth_design -top z100_window_mac_accum_v2 -part $part -flatten_hierarchy none
    puts "WINDOW_MAC_ACCUM_V2_OOC_VERSION [version -short] DEVICE $part THREADS 2"
    set resources [screen_resources $evidence_dir]
    set dsp [write_dsp_census [file join $evidence_dir dsp48e1_synth.tsv]]
    set f [open [file join $evidence_dir synth_summary.txt] w]
    puts $f "TOP z100_window_mac_accum_v2"
    puts $f "PART $part"
    puts $f "DSP_TOTAL [lindex $dsp 0] MULTIPLY [lindex $dsp 1] NONE [lindex $dsp 2] OTHER [lindex $dsp 3] NONE_ACCUM_OWNER [lindex $dsp 4]"
    puts $f "LUT [lindex $resources 0] FF [lindex $resources 1] BRAM36_EQ [lindex $resources 3] LATCH [lindex $resources 4] BLACKBOX [lindex $resources 5]"
    close $f
    puts "WINDOW_MAC_ACCUM_V2_OOC_PASS DSP=640 MULTIPLY=512 NONE=128 NONE_ACCUM_OWNER=128 LUT=[lindex $resources 0] FF=[lindex $resources 1] BRAM36_EQ=[lindex $resources 3]"
    close_project
}

if {$argc != 2} { error "usage: vivado -mode batch -source window_mac_accum_ooc_v2.tcl -tclargs BUILD_DIR EVIDENCE_DIR" }
main [lindex $argv 0] [lindex $argv 1]
exit 0
