# Bootloader firmware

The bootloader itself — flashed once via JTAG/SWD, never updates itself in the field.

## Build

Requires `arm-none-eabi-gcc` (Arm GCC toolchain) and `make`.

```powershell
cd firmware
make -j4
```

Output: `build/stm32f103c_bl.bin` (binary), `.elf` (debug), `.hex`, `.map`.

Expected size: about 9 KB `text+data` (out of the 12 KB bootloader region).

### Windows tip

On Windows, ARM GCC is conveniently shipped with PlatformIO. If you don't want to install a separate toolchain, point `PATH` at PlatformIO's bundled binaries and use `make` from MSYS2 or Git for Windows:

```powershell
$env:PATH = "$env:USERPROFILE\.platformio\packages\toolchain-gccarmnoneeabi\bin;C:\msys64\usr\bin;$env:PATH"
make -j4
```

## Flash via ST-Link / OpenOCD

```powershell
openocd -f interface/stlink.cfg -f target/stm32f1x.cfg `
        -c "program build/stm32f103c_bl.elf verify reset exit"
```

Or via ST-Link Utility / STM32CubeProgrammer: open `build/stm32f103c_bl.bin` and program at address `0x08000000`.

The bootloader binary is **128 KB chip-friendly**: it occupies `0x08000000` to about `0x080022FF`. The application region starts at `0x08003000`.

## Source layout

```
Core/Inc/          Headers
Core/Src/
  main.c           Main loop, timeout/auto-boot logic, CAN/UART/CRC/IWDG init
  bootloader.c     PreSystemInit (fast-path boot via SRAM magic value)
  can_bl.c         CAN protocol (streaming, classic WBUF, set-id, erase-app)
  uart_bl.c        UART protocol (mirror of CAN)
  flash_if.c       Flash erase + program (single-page write, app-region erase)
  stm32f1xx_it.c   ISR handlers
  stm32f1xx_hal_msp.c   HAL peripheral pin/clock setup

Drivers/           STM32F1xx HAL + CMSIS (vendor code, unchanged)
startup_stm32f103xb.s   Reset_Handler, vector table; calls PreSystemInit
STM32F103CBTx_FLASH.ld  Linker script (FLASH at 0x08000000, length 12 KB)
Makefile
openocd.cfg
```

## Key constants (`Core/Inc/main.h`)

| Constant | Value | Description |
|---|---|---|
| `APP_BASE` | `0x08003000` | Application start address |
| `PAGE_SIZE` | `0x100` (256 words = 1 KB) | Flash page size |
| `PAGE_COUNT` | `116` | Application region (116 × 1 KB) |
| `STARTUP_TO` | `2000` ms | Listen window before auto-booting app |
| `NOCANRX_TO` | `3000` ms | Inactivity timeout after first valid command |
| `FLASH_INPROGRESS_TO` | `60000` ms | Inactivity timeout once a flash sequence is in progress |
| `MAGIC_VAL` | `0x36051BF3` | SRAM magic value for fast-path boot |
| `MAGIC_ADDR` | `0x20001000` | SRAM address where magic is stored |
| `BL_BOARD_ID_MAX` | `13` | Maximum allowed board ID (14/15 reserved) |

## Changing the application region size

If you have a different chip variant (e.g. STM32F103CB**T7** is the same as **T6**, but check your part) or want a different application size, edit `Core/Inc/main.h`:

```c
#define PAGE_COUNT  116   // (TOTAL_FLASH_KB - 12) / 1
```

and `STM32F103CBTx_FLASH.ld` (the bootloader's own linker script — `FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 12K`). The 12 KB bootloader region is generous; you could shrink it to 8 KB if you need more app space.
