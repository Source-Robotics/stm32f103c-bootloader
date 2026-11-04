# STM32F103C CAN/UART bootloader

**CAN and UART field-update bootloader for the STEPFOC and Spectral Micro motor drivers (STM32F103CBT6), with
host tools.** It lives in the first 12 KB of flash, starts the application at `0x08003000` in about 10 ms on a
normal boot, and loads a new one over CAN (slcan or candleLight/gs_usb adapters) or UART, without a programming
adapter.

[STEPFOC manual](https://docs.source-robotics.com/STEPFOC-docs/latest/07-firmware/the-bootloader/) ·
[Spectral Micro manual](https://docs.source-robotics.com/Spectral-BLDC-docs/latest/07-firmware/the-bootloader/) ·
[Binaries](https://github.com/Source-Robotics/stm32f103c-bootloader/tree/main/bin) ·
[Host tools](https://github.com/Source-Robotics/stm32f103c-bootloader/tree/main/host_tools) ·
[Discord](https://discord.com/invite/prjUvjmGpZ)

[![Release](https://img.shields.io/github/v/release/Source-Robotics/stm32f103c-bootloader?style=flat-square&color=143952&label=release)](https://github.com/Source-Robotics/stm32f103c-bootloader/releases/latest)
[![MCU](https://img.shields.io/badge/mcu-STM32F103CBT6-143952?style=flat-square)](#works-with)
[![License](https://img.shields.io/badge/license-MIT-143952?style=flat-square)](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/LICENSE)
[![Discord](https://img.shields.io/discord/1072498136284667955?style=flat-square&logo=discord&logoColor=white&label=discord&color=292B37)](https://discord.com/invite/prjUvjmGpZ)

## Install

A STEPFOC shipped with firmware 105 or newer and a Spectral Micro that runs firmware 104 or newer already carry
the bootloader, and so do some older drivers (the
[STEPFOC](https://docs.source-robotics.com/STEPFOC-docs/latest/07-firmware/releases/#drivers-that-report-103) and
[Spectral Micro](https://docs.source-robotics.com/Spectral-BLDC-docs/latest/07-firmware/releases/#drivers-that-report-101)
manuals say how to tell). For those, install only the host tools.

### The host tools

```
git clone https://github.com/Source-Robotics/stm32f103c-bootloader.git
cd stm32f103c-bootloader/host_tools
pip install -r requirements.txt
```

Tested with Python 3.11; `python-can` and `pyserial` are the main dependencies. You need a CAN adapter that speaks
slcan, such as the [CANvas USB-to-CAN adapter](https://source-robotics.com/products/canvas-usb-to-can-adapter), or
gs_usb (candleLight firmware), or a USB-UART adapter for the UART transport.

### The bootloader itself (no compilation needed)

The latest pre-built bootloader binaries, those of release V0.1, are committed in
[`bin/`](https://github.com/Source-Robotics/stm32f103c-bootloader/tree/main/bin). Flash one of them once, at
address `0x08000000`, with ST-Link, J-Link, OpenOCD or STM32CubeProgrammer:

```
STM32_Programmer_CLI -c port=SWD -w bin/stm32f103c_bl.hex -v -rst
```

The other recipes and how to check the install are in
[`bin/README.md`](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/bin/README.md). On a STEPFOC
or Spectral Micro, with the [programming adapter](https://source-robotics.com/products/jtag-programming-adapter-1-27-pitch)
on its JTAG pads and the motor supply disconnected:
[Installing the bootloader on an older board](https://docs.source-robotics.com/STEPFOC-docs/latest/07-firmware/bootloader/)
([Spectral Micro](https://docs.source-robotics.com/Spectral-BLDC-docs/latest/07-firmware/bootloader/)).

## Quick start

Flash an application over CAN or UART, from `host_tools`:

```powershell
# Over CAN (slcan adapter on COM6):
python bl_flash.py --transport can --can-interface slcan --channel COM6 flash <firmware.bin> --board 0 --erase-first

# Over CAN (candleLight / gs_usb):
python bl_flash.py --transport can --can-interface gs_usb --channel 0 flash <firmware.bin> --board 0 --erase-first

# Over UART:
python bl_flash.py --transport uart --port COM7 --baudrate 256000 flash <firmware.bin> --board 0 --erase-first
```

`--erase-first` erases all application pages before streaming new data; recommended for reliability. If a host
application is already running, the host tool sends it a reset command (`#Reset\n` over UART, or a configurable
CAN command via `--app-node`) to drop the board into the bootloader window automatically. The board replies with
its board ID (default 0; `set-id` changes it once you have several boards on the same bus):

```powershell
python bl_flash.py --transport can --can-interface slcan --channel COM6 list
```

The driver releases are `stepfoc-firmware-V<number>.bin` and `spectral-bldc-firmware-V<number>.bin`; the same
commands on Linux and macOS, with the release names:
[Updating through the bootloader](https://docs.source-robotics.com/STEPFOC-docs/latest/07-firmware/update/)
([Spectral Micro](https://docs.source-robotics.com/Spectral-BLDC-docs/latest/07-firmware/update/)).

## Works with

| Product | Firmware on the bootloader | Repository |
|---|---|---|
| [STEPFOC stepper controller](https://source-robotics.com/products/stepfoc-stepper-controller) | 105 or newer (latest 108) | [STEPFOC-stepper-controller](https://github.com/Source-Robotics/STEPFOC-stepper-controller) |
| [Spectral Micro BLDC controller](https://source-robotics.com/products/spectral-micro-bldc-controller) | 104 or newer (latest 107) | [Spectral-Micro-BLDC-controller](https://github.com/Source-Robotics/Spectral-Micro-BLDC-controller) |
| MSG compliant AI stepper gripper | STEPFOC firmware, as for STEPFOC | [MSG-compliant-AI-stepper-gripper](https://github.com/Source-Robotics/MSG-compliant-AI-stepper-gripper) |
| SSG-48 adaptive electric gripper | Spectral Micro firmware, as for Spectral Micro | [SSG-48-adaptive-electric-gripper](https://github.com/Source-Robotics/SSG-48-adaptive-electric-gripper) |

Older firmware (STEPFOC 103 and older, Spectral Micro 101 and older) is linked for `0x08000000`, runs without the
bootloader and must never be flashed through it. Which release needs what: the compatibility pages of the
[STEPFOC](https://docs.source-robotics.com/STEPFOC-docs/latest/appendix/compatibility/) and
[Spectral Micro](https://docs.source-robotics.com/Spectral-BLDC-docs/latest/appendix/compatibility/) manuals.
[Motor GUI](https://motorgui.com/) and the PAR6 control box flash through the same bootloader.

If you're shipping a product with this bootloader, open a PR adding it here.

## Host tools

In [host_tools](https://github.com/Source-Robotics/stm32f103c-bootloader/tree/main/host_tools):

| Tool | What it does |
|---|---|
| `bl_flash.py` | lists the boards in bootloader mode (`list`), flashes an image (`flash`), changes a board ID (`set-id`), sends a running application back into the bootloader (`app-reset`), over CAN or UART |
| `can_fleet_update.py` | scans the Spectral application nodes on a CAN bus, shows live motor data, then flashes the nodes you choose (`all`, or a list like `0,2,3`) one at a time; it imports the [Spectral-BLDC](https://github.com/Source-Robotics/Spectral-BLDC-Python) library (`--spectral-api`) |
| `validate_app_bin.py` | checks that an image is linked for the `0x08003000` application region: its size, stack pointer and reset vector |
| `soak_fleet_update.py` | flashes one or more nodes repeatedly and checks that the application answers a ping after every update |
| `bus_noise_update.py` | flashes one node while sending telemetry requests to the other application nodes on the bus |

Every option, the Spectral fleet helper's settings and the troubleshooting:
[host_tools/README.md](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/host_tools/README.md).

## Examples

| Example | What it does |
|---|---|
| [`examples/blink_app`](https://github.com/Source-Robotics/stm32f103c-bootloader/tree/main/examples/blink_app) | a minimal 1-page test app linked at `0x08003000` that blinks the LED, pre-built as `blink_app.bin`: confirms a fresh install end to end |
| [`examples/integration`](https://github.com/Source-Robotics/stm32f103c-bootloader/tree/main/examples/integration) | template files from the Spectral BLDC motor controller showing how to wire an STM32 application to the bootloader: vector-table relocation, the reset command, board-ID sync, a linker script at `0x08003000` |
| [`scripts`](https://github.com/Source-Robotics/stm32f103c-bootloader/tree/main/scripts) | batch scripts for stress and soak testing: 20 consecutive flash cycles over CAN (gs_usb), CAN (slcan) or UART |

## Integrating it into your application

The application's linker script must place FLASH at `0x08003000` (length 116 KB / 118784 bytes), and the
application must set `SCB->VTOR = 0x08003000` before initialising peripherals. Optional but recommended: a handler
for the reset command (`#Reset\n` over UART, a CAN command), so the host tools can drop it into the bootloader,
and `Bootloader_SyncBoardId()`, which keeps the bootloader's board ID in step with the application's CAN ID. Step
by step:
[docs/INTEGRATION.md](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/docs/INTEGRATION.md); the
wire protocol: [docs/PROTOCOL.md](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/docs/PROTOCOL.md);
the validation runs: [docs/TEST_RESULTS.md](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/docs/TEST_RESULTS.md).

## Building from source

Two build systems are provided, both producing equivalent output.

<details>
<summary>Option A: PlatformIO (one command, recommended for newcomers)</summary>

```powershell
pio run -t upload
```

That's it. Builds via `framework = cmsis` and flashes via ST-Link. Config is in
[`platformio.ini`](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/platformio.ini). Works from
VSCode + PlatformIO IDE too.

</details>

<details>
<summary>Option B: Make (recommended for developers without PlatformIO)</summary>

```powershell
cd firmware
make -j4
# Output: build/stm32f103c_bl.bin
```

Requires `arm-none-eabi-gcc`. See
[`firmware/README.md`](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/firmware/README.md) for
flash-via-OpenOCD recipes.

</details>

## How it works

<details>
<summary>Features</summary>

- Streaming flash protocol over CAN and UART — robust against transport hiccups, with end-of-page CRC verification.
- `BL_ERASE_APP` command for atomic app-region erase before re-flash.
- Per-WBUF response correlation via `par1` echo (eliminates late-response drift bugs common in single-byte ACK protocols).
- Fast-path boot — after a successful flash, the BL hands off to the app in ~10 ms via an SRAM-magic-value handshake.
- Independent watchdog (IWDG) protects against firmware hangs.
- Host tools auto-detect either slcan or gs_usb CAN adapters.
- Verified by soak testing: 60/60 consecutive flash cycles pass across CAN slcan, CAN gs_usb, and UART transports.

</details>

<details>
<summary>Memory layout</summary>

```
0x08000000 - 0x080022FF   Bootloader code (~9 KB)
0x08002C00 - 0x08002FFF   Bootloader config page (board ID, app CRC, build version)
0x08003000 - 0x0801FFFF   Application (up to 116 KB)
```

SRAM:
```
0x20001000                Magic value (set by BL, read by PreSystemInit on next boot)
```

</details>

<details>
<summary>Boot flow</summary>

1. `PreSystemInit()` runs from the startup assembly *before* HAL/clocks are initialised.
2. If the SRAM magic value at `0x20001000` is present AND the last reset was a software reset, the bootloader validates the application's stack pointer and reset vector and **jumps directly to the application** (fast path, ~10 ms).
3. Otherwise the bootloader initialises HAL, clocks, GPIO, CAN, UART, CRC, and IWDG.
4. It listens for bootloader commands for `STARTUP_TO` ms (2 s by default).
5. If no command is received and a valid application is present, it sets the SRAM magic value and triggers `NVIC_SystemReset()`. On the next boot, step 2 takes the fast path.
6. If a flash is in progress, the listen window extends to `FLASH_INPROGRESS_TO` (60 s) to tolerate slow hosts.
7. If the application CRC is invalid (partial flash, never flashed, etc.), the bootloader stays in bootloader mode indefinitely.

</details>

<details>
<summary>Timing: how long the board stays in the bootloader</summary>

| Timer | Value | When it applies |
|---|---|---|
| `STARTUP_TO` | **2 s** | Cold boot, before any valid command has been received |
| `NOCANRX_TO` | **3 s** | After the first valid command, if traffic stops |
| `FLASH_INPROGRESS_TO` | **60 s** | Once a flash sequence is in progress (WBUF or stream data seen, before `WRITE_CRC`) |

Any valid `PING` command resets the timer, so the host can extend the window indefinitely by sending pings during long operations. This is the same pattern as the "tester present" message in industrial bootloaders.

**How this compares to industry norms**

Cold-boot listen windows in industry typically range from **1–5 seconds** for hobbyist and motor-drive bootloaders, up to **5–30 seconds** for automotive/industrial ECU bootloaders (AUTOSAR, UDS, CANopen LSS). Some bootloaders use no timeout at all and instead enter bootloader mode via a hardware pin or user gesture (the STM32 ROM bootloader, Adafruit UF2, ESP-IDF). The pattern of "any valid command resets the timer" — used by this bootloader — is also how industrial UDS-style bootloaders stay alive during long flash sessions.

Our 2 s cold-boot window sits on the short side of that range, which favours **fast application boot** when no host is connected — usually what you want for an embedded motor controller. The 60 s mid-flash window is generous and tolerates slow USB-CAN adapters or busy hosts without giving up partway through.

If your use case needs different timing, the values are `#define`s in [`firmware/Core/Inc/main.h`](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/firmware/Core/Inc/main.h) and a recompile is a one-liner change.

</details>

<details>
<summary>CAN interface</summary>

- Peripheral: `CAN1`, PB8 (RX) / PB9 (TX), 1 Mbit/s, standard 11-bit IDs.
- Command frame: `0x700` (host → MCU, 8 bytes).
- Reply frame: `0x701 + board_id` (MCU → host, 5 bytes — `[board_id][cmd][error_code][par1_lo][par1_hi]`).
- Board IDs 0-13 (14 and 15 reserved for the host application's own use).
- Bulk-data frames during streaming use IDs `0x000 + (board_id << 7) + seq` (16 frames × 8 bytes per chunk).

Full protocol detail in [docs/PROTOCOL.md](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/docs/PROTOCOL.md).

</details>

<details>
<summary>UART interface</summary>

- Peripheral: `USART1`, PB6 (TX) / PB7 (RX), 256000 baud, 8N1.
- Frame: `[0xBB][CMD][LEN_L][LEN_H][BOARD_ID][DATA...][CRC16_L][CRC16_H]`, CRC16/CCITT over `[CMD..DATA]`.
- Reply: `[board_id][cmd][error_code][par1_lo][par1_hi]` (5 bytes).
- Parser auto-resyncs on a 20 ms inter-byte gap, ORE/framing errors, or any malformed frame.

Full protocol detail in [docs/PROTOCOL.md](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/docs/PROTOCOL.md).

</details>

<details>
<summary>Status LED</summary>

Pins `PA7` and `PB13` are both driven (active-low) so the board's LED works regardless of which footprint is populated.

- Early register-level boot: 3 quick blinks.
- BL idle (no host activity): slow double-flash @ 1 Hz.
- BL active (host command received): fast 100 ms on / 100 ms off.

</details>

<details>
<summary>Repository layout</summary>

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

</details>

## Community

Ask in [Discussions](https://github.com/orgs/Source-Robotics/discussions), chat on
[Discord](https://discord.com/invite/prjUvjmGpZ), report a bug in
[Issues](https://github.com/Source-Robotics/stm32f103c-bootloader/issues). Follow Source Robotics:

[![Discord](https://img.shields.io/discord/1072498136284667955?style=flat-square&logo=discord&logoColor=white&label=discord&color=143952)](https://discord.com/invite/prjUvjmGpZ)
[![Discussions](https://img.shields.io/badge/discussions-ask_a_question-143952?style=flat-square&logo=github&logoColor=white)](https://github.com/orgs/Source-Robotics/discussions)
[![YouTube](https://img.shields.io/badge/youtube-%40source--robotics-143952?style=flat-square&logo=youtube&logoColor=white)](https://www.youtube.com/@source-robotics)
[![Instagram](https://img.shields.io/badge/instagram-%40source__robotics-143952?style=flat-square&logo=instagram&logoColor=white)](https://www.instagram.com/source_robotics/)
[![X](https://img.shields.io/badge/x-%40SourceRobotics-143952?style=flat-square&logo=x&logoColor=white)](https://x.com/SourceRobotics)
[![LinkedIn](https://img.shields.io/badge/linkedin-Source_Robotics-143952?style=flat-square&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI%2BPHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0yMC40NDcgMjAuNDUyaC0zLjU1NHYtNS41NjljMC0xLjMyOC0uMDI3LTMuMDM3LTEuODUyLTMuMDM3LTEuODUzIDAtMi4xMzYgMS40NDUtMi4xMzYgMi45Mzl2NS42NjdIOS4zNTFWOWgzLjQxNHYxLjU2MWguMDQ2Yy40NzctLjkgMS42MzctMS44NSAzLjM3LTEuODUgMy42MDEgMCA0LjI2NyAyLjM3IDQuMjY3IDUuNDU1djYuMjg2ek01LjMzNyA3LjQzM2MtMS4xNDQgMC0yLjA2My0uOTI2LTIuMDYzLTIuMDY1IDAtMS4xMzguOTItMi4wNjMgMi4wNjMtMi4wNjMgMS4xNCAwIDIuMDY0LjkyNSAyLjA2NCAyLjA2MyAwIDEuMTM5LS45MjUgMi4wNjUtMi4wNjQgMi4wNjV6bTEuNzgyIDEzLjAxOUgzLjU1NVY5aDMuNTY0djExLjQ1MnpNMjIuMjI1IDBIMS43NzFDLjc5MiAwIDAgLjc3NCAwIDEuNzI5djIwLjU0MkMwIDIzLjIyNy43OTIgMjQgMS43NzEgMjRoMjAuNDUxQzIzLjIgMjQgMjQgMjMuMjI3IDI0IDIyLjI3MVYxLjcyOUMyNCAuNzc0IDIzLjIgMCAyMi4yMjIgMGguMDAzeiIvPjwvc3ZnPg%3D%3D)](https://www.linkedin.com/company/source-robotics/)
[![Blog](https://img.shields.io/badge/blog-source--robotics.com-143952?style=flat-square&logo=rss&logoColor=white)](https://source-robotics.com/blogs/blog)

## Licensing

MIT — see [LICENSE](https://github.com/Source-Robotics/stm32f103c-bootloader/blob/main/LICENSE).
