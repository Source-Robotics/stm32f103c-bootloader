/* Minimal startup for blink_app — vectors at 0x08003000 */
    .syntax unified
    .cpu cortex-m3
    .thumb

    .section .isr_vector,"a",%progbits
    .word  _stack_top
    .word  Reset_Handler
    .rept 46
    .word  Default_Handler
    .endr

    .section .text.Reset_Handler
    .global Reset_Handler
    .type   Reset_Handler, %function
Reset_Handler:
    ldr  r0, =_sbss
    ldr  r1, =_ebss
    movs r2, #0
1:  cmp  r0, r1
    bge  2f
    str  r2, [r0], #4
    b    1b
2:
    bl   main
    b    .

    .section .text
    .global Default_Handler
    .type   Default_Handler, %function
Default_Handler:
    b .
