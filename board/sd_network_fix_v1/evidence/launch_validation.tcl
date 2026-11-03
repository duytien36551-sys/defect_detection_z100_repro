connect -url tcp:127.0.0.1:3121
targets -set -filter {name == "ARM Cortex-A9 MPCore #0"}
set p [rrd pc]
if {![regexp {:[[:space:]]*([0-9a-fA-F]+)} $p -> h]} {error "PC parse failed"}
scan $h %x pc
if {$pc != 0x122580} {error "Old application not at verified pre-inference failure hold: $p"}
puts "VERIFIED_OLD_FAILURE_HOLD $p"
stop
targets -set -filter {name == "ARM Cortex-A9 MPCore #1"}
catch {stop}
targets -set -filter {name == "ARM Cortex-A9 MPCore #0"}
rst -system -stop
after 1000
targets -set -filter {name == "ARM Cortex-A9 MPCore #0"}
set bp [bpadd -addr 0x100000 -type hw]
set rc [catch {
 con
 after 15000
 catch {stop}
 set p [rrd pc]
 if {![regexp {:[[:space:]]*([0-9a-fA-F]+)} $p -> h]} {error "Entry PC parse failed"}
 scan $h %x pc
 puts "SD_FSBL_APP_ENTRY $p"
 puts "ENTRY_SCTLR [rrd cp15 1 sctlr]"
 if {$pc != 0x100000} {error "SD did not reach application entry"}
} msg opts]
bpremove $bp
if {$rc} {return -options $opts $msg}
dow {C:/z100v13/sd_clock_fix_20261103/native_board_pool.elf}
puts "PATCH_ENTRY [rrd pc]"
con
after 8000
puts "PATCH_CPU [rrd pc]"
targets -set -filter {name == "APU"}
puts "PATCH_GEMCLK [mrd -value 0xf8000140 1]"
puts "PATCH_GEMCFG [mrd -value 0xe000b004 1]"
puts "PATCH_DEFAULT_CACHE_POLICY [mrd -value 0x7742c0 16]"
exit
