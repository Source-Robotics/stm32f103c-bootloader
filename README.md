# STM32F103C CAN/UART Bootloader

A small, reliable field-update bootloader for the **STM32F103CBT6** (128 KB flash, 20 KB SRAM), with matching host tools for flashing firmware over **CAN** (slcan or candleLight/gs_usb adapters) and **UART**.

Designed to live in the first 12 KB of flash and load a regular application from `0x08003000` upward. The application keeps the rest of the chip (116 KB) and can update itself over CAN or UART without a JTAG probe.

## Boards using this bootloader

- [**StepFOC stepper controller**](https://source-robotics.com/products/stepfoc-stepper-controller) — Source Robotics
- [**Spectral Micro BLDC controller**](https://source-robotics.com/products/spectral-micro-bldc-controller) — Source Robotics

If you're shipping a product with this bootloader, open a PR adding it here.

## Installing the bootloader (no compilation needed)

The latest pre-built bootloader binaries are committed in [`bin/`](bin/). Flash one of these via ST-Link, J-Link, OpenOCD, or STM32CubeProgrammer at address `0x08000000` and you're done — see [`bin/README.md`](bin/README.md) for one-command recipes.

## Building from source

Two build systems are provided, both producing equivalent output:

### Option A — PlatformIO (one command, recommended for newcomers)

```powershell
pio run -t upload
```

That's it. Builds via `framework = cmsis` and flashes via ST-Link. Config is in [`platformio.ini`](platformio.ini). Works from VSCode + PlatformIO IDE too.

### Option B — Make (recommended for developers without PlatformIO)

```powershell
cd firmware
make -j4
# Output: build/stm32f103c_bl.bin
```

Requires `arm-none-eabi-gcc`. See [`firmware/README.md`](firmware/README.md) for flash-via-OpenOCD recipes.

## Features

- Streaming flash protocol over CAN and UART — robust against transport hiccups, with end-of-page CRC verification.
- `BL_ERASE_APP` command for atomic app-region erase before re-flash.
- Per-WBUF response correlation via `par1` echo (eliminates late-response drift bugs common in single-byte ACK protocols).
- Fast-path boot — after a successful flash, the BL hands off to the app in ~10 ms via an SRAM-magic-value handshake.
- Independent watchdog (IWDG) protects against firmware hangs.
- Host tools auto-detect either slcan or gs_usb CAN adapters.
- Verified by soak testing: 60/60 consecutive flash cycles pass across CAN slcan, CAN gs_usb, and UART transports.

## Memory layout

```
0x08000000 - 0x080022FF   Bootloader code (~9 KB)
0x08002C00 - 0x08002FFF   Bootloader config page (board ID, app CRC, build version)
0x08003000 - 0x0801FFFF   Application (up to 116 KB)
```

SRAM:
```
0x20001000                Magic value (set by BL, read by PreSystemInit on next boot)
```

## Repository layout

```
firmware/             The bootloader itself (STM32 HAL + Makefile build).
host_tools/           Python CLI for flashing apps over CAN or UART.
examples/
  blink_app/          Minimal 1-page test app (handy for confirming a fresh install).
  integration/        Template files showing how to wire an STM32 application
                      to the bootloader (vector-table relocation, reset command,
                      board-ID sync).
docs/
  PROTOCOL.md         CAN + UART wire protocol.
  INTEGRATION.md      Step-by-step guide for integrating the BL into a new app.
scripts/              Batch scripts for stress / soak testing.
```

## Quick start

### 1. Install the bootloader

Either flash a pre-built binary from [`bin/`](bin/) (no compilation needed), or build from source — see "Installing the bootloader" and "Building from source" sections above.

### 2. Build your application linked at `0x08003000`

See [docs/INTEGRATION.md](docs/INTEGRATION.md) and the template files in [`examples/integration/`](examples/integration/). The application's linker script must place FLASH at `0x08003000` (length 116 KB / 118784 bytes) and the application must set `SCB->VTOR = 0x08003000` before initialising peripherals.

### 3. Flash the application over CAN or UART

```powershell
cd host_tools
pip install -r requirements.txt

# Over CAN (slcan adapter on COM6):
python bl_flash.py --transport can --can-interface slcan --channel COM6 flash <firmware.bin> --board 0 --erase-first

# Over CAN (candleLight / gs_usb):
python bl_flash.py --transport can --can-interface gs_usb --channel 0 flash <firmware.bin> --board 0 --erase-first

# Over UART:
python bl_flash.py --transport uart --port COM7 --baudrate 256000 flash <firmware.bin> --board 0 --erase-first
```

`--erase-first` erases all application pages before streaming new data; recommended for reliability.

If a host application is already running, the host tool will send a reset command (`#Reset\n` over UART, or a configurable CAN command via `--app-node`) to drop the board into the bootloader window automatically. See [docs/INTEGRATION.md](docs/INTEGRATION.md) for the required app-side handler.

### 4. Verify board reachability

```powershell
python bl_flash.py --transport can --can-interface slcan --channel COM6 list
```

The board replies with its current board ID (default 0; configurable via `set-id` once you have multiple boards on the same bus).

## Boot flow

1. `PreSystemInit()` runs from the startup assembly *before* HAL/clocks are initialised.
2. If the SRAM magic value at `0x20001000` is present AND the last reset was a software reset, the bootloader validates the application's stack pointer and reset vector and **jumps directly to the application** (fast path, ~10 ms).
3. Otherwise the bootloader initialises HAL, clocks, GPIO, CAN, UART, CRC, and IWDG.
4. It listens for bootloader commands for `STARTUP_TO` ms (2 s by default).
5. If no command is received and a valid application is present, it sets the SRAM magic value and triggers `NVIC_SystemReset()`. On the next boot, step 2 takes the fast path.
6. If a flash is in progress, the listen window extends to `FLASH_INPROGRESS_TO` (60 s) to tolerate slow hosts.
7. If the application CRC is invalid (partial flash, never flashed, etc.), the bootloader stays in bootloader mode indefinitely.

## CAN interface

- Peripheral: `CAN1`, PB8 (RX) / PB9 (TX), 1 Mbit/s, standard 11-bit IDs.
- Command frame: `0x700` (host → MCU, 8 bytes).
- Reply frame: `0x701 + board_id` (MCU → host, 5 bytes — `[board_id][cmd][error_code][par1_lo][par1_hi]`).
- Board IDs 0-13 (14 and 15 reserved for the host application's own use).
- Bulk-data frames during streaming use IDs `0x000 + (board_id << 7) + seq` (16 frames × 8 bytes per chunk).

Full protocol detail in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## UART interface

- Peripheral: `USART1`, PB6 (TX) / PB7 (RX), 256000 baud, 8N1.
- Frame: `[0xBB][CMD][LEN_L][LEN_H][BOARD_ID][DATA...][CRC16_L][CRC16_H]`, CRC16/CCITT over `[CMD..DATA]`.
- Reply: `[board_id][cmd][error_code][par1_lo][par1_hi]` (5 bytes).
- Parser auto-resyncs on a 20 ms inter-byte gap, ORE/framing errors, or any malformed frame.

Full protocol detail in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Status LED

Pins `PA7` and `PB13` are both driven (active-low) so the board's LED works regardless of which footprint is populated.

- Early register-level boot: 3 quick blinks.
- BL idle (no host activity): slow double-flash @ 1 Hz.
- BL active (host command received): fast 100 ms on / 100 ms off.

## License

MIT — see [LICENSE](LICENSE).
