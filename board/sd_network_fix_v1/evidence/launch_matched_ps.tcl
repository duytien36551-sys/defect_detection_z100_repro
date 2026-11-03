connect -url tcp:127.0.0.1:3121
targets -set -filter {name == "ARM Cortex-A9 MPCore #0"}
catch {stop}
rst -system -stop
after 1000
targets -set -filter {name == "ARM Cortex-A9 MPCore #1"}
catch {stop}
targets -set -filter {name == "ARM Cortex-A9 MPCore #0"}
catch {stop}
source {C:/Users/Administrator/Desktop/end_work/defect_detection_z100/build/firmware_portable/boot/ps7_init.tcl}
# Bound vendor polling so failed initialization cannot silently fall through.
proc mask_poll {addr mask} {
 set end [expr {[clock milliseconds]+10000}]
 while {([lindex [mrd -value $addr 1] 0]&$mask)==0} {
  if {[clock milliseconds]>$end} {error "PS init poll timeout $addr"}
 }
}
ps7_init
puts "MATCHED_PS_INITIALIZED"
targets -set -filter {name == "xc7z100"}
fpga -file {C:/z100v13/sd_clock_fix_20261103/z100_platform.bit}
targets -set -filter {name == "ARM Cortex-A9 MPCore #0"}
ps7_post_config
puts "PRE_APP_SCTLR [rrd cp15 1 sctlr]"
dow {C:/z100v13/sd_clock_fix_20261103/native_board_pool.elf}
rwr r0 0
rwr r1 0
rwr r2 0
rwr r3 0
con
after 8000
puts "PATCH_CPU [rrd pc]"
targets -set -filter {name == "APU"}
puts "PATCH_GEMCLK [mrd -value 0xf8000140 1]"
puts "PATCH_GEMCFG [mrd -value 0xe000b004 1]"
puts "PATCH_DEFAULT_CACHE_POLICY [mrd -value 0x7742c0 16]"
exit
