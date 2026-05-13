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
