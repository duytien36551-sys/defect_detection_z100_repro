set_param general.maxThreads 2
set script_dir [file dirname [file normalize [info script]]]
set build [lindex $argv 0]
set evidence [lindex $argv 1]
file mkdir $build
file mkdir $evidence
create_project -force requant_threshold [file join $build project] -part xc7z100ffg900-2
read_verilog [file join $script_dir z100_requant_threshold.v]
synth_design -mode out_of_context -top z100_requant_threshold -part xc7z100ffg900-2
create_clock -name core_clk -period 5.000 [get_ports clk]
set_input_delay 1.000 -clock core_clk [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_output_delay 1.000 -clock core_clk [all_outputs]
report_utilization -file [file join $evidence utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $evidence timing_synth.rpt]
set lut [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]
set bram18 [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}]]
set bram36 [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}]]
set dsp [llength [get_cells -hier -filter {REF_NAME =~ DSP*}]]
set fd [open [file join $evidence resources.json] w]
puts $fd [format {{"lut":%d,"bram18":%d,"bram36":%d,"dsp":%d}} $lut $bram18 $bram36 $dsp]
close $fd
write_checkpoint -force [file join $build synthesized.dcp]
if {$bram18 != 1 || $bram36 != 0 || $dsp != 0} { error "Expected one RAMB18 and zero DSP" }
puts "REQUANT_SYNTH_PASS lut=$lut bram18=$bram18 dsp=$dsp"
close_project
exit 0
