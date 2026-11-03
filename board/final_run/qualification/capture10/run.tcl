connect
after 1500
puts [targets]
foreach id {3 2} {targets -set $id;if {[catch {stop} e] && ![string match {*Already stopped*} $e]} {error $e}}
targets -set 2
proc regval {name} {
 set t [rrd $name]
 if {![regexp {:[[:space:]]*([0-9a-fA-F]+)} $t -> h]} {error "Cannot parse register"}
 scan $h %x v
 return [expr {$v & 0xffffffff}]
}
if {[lindex [mrd -value 0x2805c 1] 0]!=0xeafffffe} {error "OCM return changed"}
puts [mrd 0x5000c0 50]
set d [mrd -value 0x5000c0 18]
if {[lindex $d 0]!=1 || [lindex $d 1]!=8 || [lindex $d 6]!=49010 || [lindex [mrd -value 0x774280 1] 0]!=0 || [lindex [mrd -value 0x1debe4 1] 0]!=49000 || [lindex $d 16]!=10 || [lindex $d 17]!=0} {error "Expected firmware healthy idle identity"}
foreach r {r0 r1 r2 r3 r4 r5 r6 r7 r8 r9 r10 r11 r12 sp lr pc cpsr} {set saved($r) [regval $r]}
puts "SAVED_REGISTERS [array get saved]"
rwr cpsr [expr {($saved(cpsr)|0xc0)&~0x20}]
rwr r0 0x24000000
rwr r1 613248
rwr lr 0x2805c
rwr pc 0x139e7c
set bp [bpadd -addr 0x2805c -type hw]
con
after 300
if {[catch {stop} e] && ![string match {*Already stopped*} $e]} {error $e}
if {[regval pc]!=0x2805c} {error "ARM helper failed; leave halted"}
bpremove $bp
mrd -bin -file {hardware_workspace/gpt_softpack_launch02/qualification/capture10/heads.bin} 0x24000000 153300
rwr r0 0x1abb480
rwr r1 16384
rwr lr 0x2805c
rwr pc 0x139e7c
set bp [bpadd -addr 0x2805c -type hw]
con
after 300
if {[catch {stop} e] && ![string match {*Already stopped*} $e]} {error $e}
if {[regval pc]!=0x2805c} {error "ARM helper failed; leave halted"}
bpremove $bp
mrd -bin -file {hardware_workspace/gpt_softpack_launch02/qualification/capture10/irq_stack.bin} 0x1abb480 4096
foreach r {r0 r1 r2 r3 r4 r5 r6 r7 r8 r9 r10 r11 r12 sp lr pc cpsr} {rwr $r $saved($r)}
con
puts {CAPTURED_APP_RESUMED}
exit
