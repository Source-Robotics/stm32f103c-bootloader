MEMORY
{
  FLASH (rx) : ORIGIN = 0x08003000, LENGTH = 116K
  RAM  (xrw) : ORIGIN = 0x20000000, LENGTH = 20K
}

_stack_top = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{
  .isr_vector :
  {
    KEEP(*(.isr_vector))
  } > FLASH

  .text :
  {
    *(.text*)
    *(.rodata*)
    _etext = .;
  } > FLASH

  .bss :
  {
    _sbss = .;
    *(.bss*)
    *(COMMON)
    _ebss = .;
  } > RAM
}
