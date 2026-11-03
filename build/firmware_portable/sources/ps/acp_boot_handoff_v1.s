.syntax unified
.arm
.section .text.zn_acp_boot_handoff_v1,"ax",%progbits
.align 2
.global zn_acp_boot_handoff_v1
.type zn_acp_boot_handoff_v1,%function
.extern zn_acp_boot_receiver_v1

zn_acp_boot_handoff_v1:
    mov r0, #0
    mov r1, #0
    mov r2, #0
    mov r3, #0
.global zn_acp_boot_handoff_ready_v1
zn_acp_boot_handoff_ready_v1:
    nop
    b zn_acp_boot_receiver_v1
.size zn_acp_boot_handoff_v1, .-zn_acp_boot_handoff_v1

.section .note.GNU-stack,"",%progbits
