# Host tools

Python CLI for flashing the STM32F103C bootloader's applications over CAN or UART.

## Install

```powershell
cd host_tools
pip install -r requirements.txt
```

Tested with Python 3.11. `python-can` and `pyserial` are the main dependencies.

## Quick reference

```powershell
# List boards in bootloader mode
python bl_flash.py --transport can --can-interface slcan --channel COM6 list
python bl_flash.py --transport uart --port COM7 --baudrate 256000 list

# Flash a firmware binary
python bl_flash.py --transport can --can-interface slcan --channel COM6 \
                   flash <firmware.bin> --board 0 --erase-first

python bl_flash.py --transport can --can-interface gs_usb --channel 0 \
                   flash <firmware.bin> --board 0 --app-node 3 --erase-first

python bl_flash.py --transport uart --port COM7 --baudrate 256000 \
                   flash <firmware.bin> --board 0 --erase-first

# Scan Spectral app nodes, monitor motor data, then choose nodes to update
python can_fleet_update.py --can-interface slcan --channel COM6 \
                           --firmware <firmware.bin>

# Check that an app .bin is linked for the bootloader app region
python validate_app_bin.py <firmware.bin>

# Repeated update soak test
python soak_fleet_update.py <firmware.bin> --can-interface slcan --channel COM6 \
                            --nodes 0,1 --iterations 20

# Flash node 0 while injecting telemetry requests to other app nodes
python bus_noise_update.py <firmware.bin> --can-interface slcan --channel COM6 \
                           --target 0 --noise-nodes 1,2,3

# Change board ID (one-time setup if you have multiple boards on the same bus)
python bl_flash.py --transport can --can-interface slcan --channel COM6 \
                   set-id --board 0 --new-id 5

# Trigger a running host application back into bootloader mode (CAN)
python bl_flash.py --transport can --can-interface slcan --channel COM6 \
                   app-reset --node 0 --wait
```

## Options

| Flag | What it does |
|---|---|
| `--transport can\|uart` | Which transport. |
| `--can-interface slcan\|gs_usb\|auto` | CAN backend. `slcan` for USB-CDC adapters (CANable original firmware, Lawicel-compatible); `gs_usb` for candleLight-firmware adapters (native USB CAN). |
| `--channel <port-or-index>` | COM port for slcan/UART (`COM6`), or device index for gs_usb (`0`). |
| `--port COMx --baudrate N` | UART transport. Default baud `256000`. |
| `--board N` | Bootloader board ID (0-13, default 0). |
| `--app-node N` | Host application's CAN node ID (used for the app-reset command if needed). Defaults to `--board`. |
| `--erase-first` | Erase the application region before streaming new data. Recommended. |
| `--no-stream` | Fall back to per-word `WBUF` mode instead of streaming (rarely needed). |
| `--stream-chunk-frames N` | Stream chunk size (default 16). Lower = more verifications, more overhead. |

## Spectral fleet update helper

`can_fleet_update.py` is an interactive test/update tool for Spectral BLDC
applications. It scans app node IDs, polls live motor telemetry, then lets you
enter `all` or a comma-separated list like `0,2,3`. Selected nodes are flashed
one at a time through the existing CAN bootloader path.

Example:

```powershell
cd host_tools
python can_fleet_update.py --can-interface slcan --channel COM6 `
                           --firmware path\to\BLDC.bin
```

By default it imports the Spectral Python API from:

```text
C:\Users\<you>\Desktop\Spectral-BLDC-Python-main
```

If your copy is somewhere else:

```powershell
python can_fleet_update.py --can-interface slcan --channel COM6 `
  --spectral-api "C:\path\to\Spectral-BLDC-Python-main" `
  --firmware path\to\BLDC.bin
```

The selected app node ID is also used as the bootloader board ID. This matches
the integration flow where the app keeps the bootloader ID synced with
`Bootloader_SyncBoardId()`. Bootloader IDs `14` and `15` are skipped because the
bootloader reserves those IDs.

## Firmware validation

`validate_app_bin.py` catches the most common dangerous mistake: trying to flash
a normal `0x08000000` image through the bootloader. It checks:

- file size fits in the `0x08003000` app region
- initial stack pointer points into STM32F103CB RAM
- reset vector points into app flash and has the Thumb bit set

Example:

```powershell
python validate_app_bin.py path\to\BLDC.bin
```

`can_fleet_update.py`, `soak_fleet_update.py`, and `bus_noise_update.py` run this
same check before flashing.

## Soak and noise tests

`soak_fleet_update.py` repeatedly flashes one or more nodes, then checks that the
app responds to CAN ping after every update:

```powershell
python soak_fleet_update.py path\to\BLDC.bin `
  --can-interface slcan --channel COM6 `
  --nodes 0,1 --iterations 20
```

`bus_noise_update.py` updates one target node while injecting harmless Spectral
telemetry requests to other running app nodes on the same CAN bus. This verifies
that the bootloader flasher ignores unrelated app traffic while waiting for
bootloader ACKs:

```powershell
python bus_noise_update.py path\to\BLDC.bin `
  --can-interface slcan --channel COM6 `
  --target 0 --noise-nodes 1,2,3
```

You can make the noise heavier with `--noise-frames-per-hook 2` or force WBUF
fallback with `--no-stream` if you want to stress the slower path too.

## How it picks a path

1. The host tool sends a `BL_PING` to the configured board.
2. If a reply arrives within a short timeout, the board is already in bootloader mode → continue.
3. If not, the host sends a reset command:
   - CAN: `IN_RESET` command (cmd 14) to the host application's node.
   - UART: literal text `#Reset\n`.
4. The host then waits for the board to boot the bootloader and start replying. Up to ~25 s.
5. Optional `--erase-first` triggers `BL_ERASE_APP`.
6. Streaming starts: `STREAM_BEGIN` → chunked data frames → `STREAM_STATUS` per chunk → `WRITE_PAGE` (CRC check) per page → `WRITE_CRC` (whole-app CRC) at the end.

## Streaming protocol summary

Per page (1024 bytes):
1. `STREAM_BEGIN(page_num)` — bootloader initialises the page buffer.
2. 128 fire-and-forget data frames of 8 bytes each, sent in groups of `--stream-chunk-frames`.
3. `STREAM_STATUS(end_seq)` after each chunk — bootloader confirms all frames received via a bitmask.
4. `WRITE_PAGE(page_num, page_crc32)` — bootloader verifies the page CRC and commits the buffer to flash.

At the end of all pages: `WRITE_CRC(total_pages, app_crc32)` writes the whole-app CRC to the bootloader config page, which gates whether the bootloader will boot the app on the next reset.

## Troubleshooting

- **"Could not connect to board"** — make sure the host application implements the reset command (see `docs/INTEGRATION.md`). For first-time installs without an app present, power-cycle the board and run the host tool within the 2 s startup window. For development boards, you can keep the bootloader in "stay alive" mode by power-cycling and immediately running the host tool.
- **CAN slcan adapter drops out after sustained traffic** — try the gs_usb backend instead (CANable v2 with candleLight firmware supports it). Both worked equally well in our 20-iteration soak tests, but slcan is more sensitive to USB stack quality.
- **`Unexpected reply: board=X cmd=0x..` on UART** — usually OS-level USB-serial drift. The host already tries to drain RX before each command; if you still see this, try a different USB-UART adapter (FT232-based adapters tend to be most reliable).
