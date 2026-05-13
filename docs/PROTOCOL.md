# Bootloader Protocol

The bootloader speaks the same logical protocol over both CAN and UART. The framing differs (CAN frames vs UART byte-stream with start-byte + CRC), but the command codes, payload semantics, and reply layout are identical.

## Command codes

| Code | Name | par1 | par2 | Description |
|---|---|---|---|---|
| `0x01` (UART) / `0x04` (CAN) | `PING` | — | — | Broadcast ping; all boards reply. |
| `0x02` (UART) / `0x01` (CAN) | `WRITE_BUF` | word offset (0-255) | 4 bytes of data | Write one word into the page buffer. *Legacy path; streaming is preferred.* |
| `0x03` (UART) / `0x02` (CAN) | `WRITE_PAGE` | page number (0-115) | page CRC32 | Verify CRC over the page buffer and commit it to flash. |
| `0x04` (UART) / `0x03` (CAN) | `WRITE_CRC` | page count | whole-app CRC32 | Verify CRC over the entire application and store metadata in the bootloader config page. Last command of a flash session. |
| `0x05` | `SET_ID` | new board ID (0-13) | — | Persist a new board ID to the bootloader config page. |
| `0x06` | `ERASE_APP` | — | — | Erase all 116 application pages. Used at the start of a flash for clean state. |
| `0x07` | `STREAM_BEGIN` | page number (0-115) | — | Begin streaming a page. Initialises the page buffer (`memset(0xFF)`) and clears the receive bitmask. |
| `0x08` | `STREAM_STATUS` | end_seq (last frame index, 0-127) | — | Verify that all stream frames `0..end_seq` have been received. Returns `BL_SUCCESS` if complete, `BL_ERR_INVALID_CRC` if any frame is missing. |
| `0x09` (UART only) | `STREAM_DATA` | seq | 8 bytes of data | Fire-and-forget. **No reply.** Stores 8 bytes at `pagebuf[seq * 2..seq * 2 + 1]`. |

CAN streaming uses different CAN IDs for data frames rather than a `STREAM_DATA` command — see "CAN framing" below.

## Reply layout (both transports)

```
[board_id][cmd][error_code][par1_lo][par1_hi]
```

5 bytes. Including `par1` in the reply prevents the host from confusing late responses for new ones — the host matches replies on `(cmd, par1)` rather than just `cmd`. This was a real bug class that the protocol fixes.

## Error codes

| Code | Name |
|---|---|
| `0` | `BL_SUCCESS` |
| `1` | `BL_ERR_INVALID_OFFSET` |
| `2` | `BL_ERR_INVALID_CRC` |
| `3` | `BL_ERR_FLASH_WRITE` |
| `4` | `BL_ERR_INVALID_PAGE_NUM` |

## CAN framing

- Bitrate: 1 Mbit/s, standard 11-bit IDs.
- Host → MCU command: ID `0x700`, DLC 8.
   - Byte layout: `[board_id][cmd][par1_lo][par1_hi][par2_b0][par2_b1][par2_b2][par2_b3]` (par2 is big-endian on wire — quirk preserved from a reference design).
- MCU → host reply: ID `0x701 + board_id`, DLC 5.

### CAN stream data frames

During a streaming session, the host sends raw 8-byte data frames at a CAN ID that encodes the board ID and frame sequence:

```
CAN ID = (board_id << 7) | (seq & 0x7F)
```

For `board_id = 0`, sequence frames use IDs `0x00 .. 0x7F`. These bypass the normal command parser; the bootloader stores them directly into the page buffer when `stream_active == 1`. No reply is sent for these frames.

Verification happens via `STREAM_STATUS` after each chunk and `WRITE_PAGE` at the end of the page.

### CAN bitrate and board ID constraints

Standard 11-bit IDs only. Board IDs 0-13 use reply IDs `0x701..0x70E`. Board IDs 14 and 15 are **reserved** — see the next section for why.

### Why board IDs 14 and 15 are reserved (interaction with the host application's CAN ID scheme)

This bootloader is designed to coexist with a host application that uses the **same 11-bit CAN bus** for its own traffic. The bootloader uses a few specific IDs (`0x700` for commands; `0x701..0x70E` for replies; `0x000..0x07F` shifted by `board_id << 7` for stream data) and reserves the rest for the application.

The Source Robotics motor controllers (StepFOC, Spectral BLDC) encode their 11-bit CAN IDs as:

```
11-bit ID = [node_id : 4 bits] [command_id : 6 bits] [error_bit : 1 bit]
          = (node_id << 7) | (command_id << 1) | error_bit
```

So *every* 11-bit standard CAN ID can technically be decoded by the app, including the bootloader's `0x700`:

```
0x700 = 0b111 0000 0000
       = node_id=14, command_id=0, error_bit=0   (in app-decode terms)
```

This is why **board IDs 14 and 15 are reserved** for the bootloader:

- Bootloader command frame `0x700` decodes as app-node `14`, command `0`. If the app were configured with node ID 14, it would treat every bootloader command as a (probably invalid) message addressed to itself.
- Bootloader reply frames `0x701..0x70E` (board IDs 0-13) all decode as app-node `14` too, command `0..6`, error `0` or `1`. Again, an app on node 14 would see all bootloader replies as its own traffic.

By **not** allowing the app to use node 14 (and 15, for symmetry), the bootloader's ID space is fully isolated from any app traffic — both directions.

In normal operation, only one of {bootloader, app} is running at any moment (a successful flash hands off to the app via `NVIC_SystemReset`; an app-reset command does the reverse), so the IDs *would* be free to overlap. But the conservative choice of reserving node 14/15 means the host can send bootloader frames safely even if it has stale assumptions about what's running on the bus, and the app can never accidentally receive bootloader frames.

The `bl_flash.py` `app-reset` command in the host tools uses this encoding to build the reset command's CAN ID:

```
reset_id = (node_id << 7) | (14 << 1) | 0    # e.g. 0x09C for node 1
```

where `14` is the host application's chosen `IN_RESET` command code in its own protocol. This is unrelated to the bootloader's node-14 reservation — the bootloader doesn't process this ID at all; the app sees and acts on it.

## UART framing

- Peripheral: `USART1`, PB6 (TX) / PB7 (RX), 256 000 baud, 8N1.
- Frame from host:
   ```
   [0xBB][CMD][LEN_L][LEN_H][BOARD_ID][DATA × LEN][CRC16_L][CRC16_H]
   ```
   `CRC16/CCITT` (polynomial `0x1021`, init `0xFFFF`) over bytes `[CMD..DATA-end]`.
- Reply: same 5-byte layout as CAN.

### Parser resync

The UART parser resets to IDLE state on:
- a 20 ms inter-byte gap mid-frame,
- USART_SR ORE/FE/NE/PE error flags,
- successful frame completion (CRC match → process command),
- length-field overflow (LEN > `UART_MAX_PAYLOAD`).

This makes the parser self-healing: any single dropped or corrupted byte loses one frame at most, and the host's normal retry pattern recovers.

## A complete flash session (streaming, recommended path)

```
host                                                 BL
 │  bl_ping(brd=0)                                    │
 │ ────────────────────────────────────────────────► │
 │ ◄────────────────────────────────────────────────  │  reply OK
 │  (optional, for clean re-flash) ERASE_APP         │
 │ ────────────────────────────────────────────────► │
 │ ◄────────────────────────────────────────────────  │  reply OK after ~3.5 s
 │                                                    │
 │  per page p in 0..N-1:                            │
 │    STREAM_BEGIN(p)                                 │
 │ ────────────────────────────────────────────────► │
 │ ◄────────────────────────────────────────────────  │  reply OK
 │    per chunk c in 0..7:                           │
 │      send 16 × STREAM_DATA (fire-and-forget)      │
 │ ────────────────────────────────────────────────► │
 │      STREAM_STATUS(end_seq = c*16 + 15)           │
 │ ────────────────────────────────────────────────► │
 │ ◄────────────────────────────────────────────────  │  reply OK (bitmask complete)
 │    WRITE_PAGE(p, page_crc32)                       │
 │ ────────────────────────────────────────────────► │
 │ ◄────────────────────────────────────────────────  │  reply OK (CRC matched, page flashed)
 │                                                    │
 │  WRITE_CRC(N, app_crc32)                           │
 │ ────────────────────────────────────────────────► │
 │ ◄────────────────────────────────────────────────  │  reply OK (config page written)
 │                                                    │
 │  (host disconnects; after NOCANRX_TO of silence    │
 │   the BL sets the SRAM magic and resets into app)  │
```

If `STREAM_STATUS` fails (bitmask incomplete), the host re-sends the same chunk. If `WRITE_PAGE` fails, the host re-sends the entire page (`STREAM_BEGIN` again). Up to 8 page retries.

## CRC32 algorithm

The bootloader uses STM32F1 hardware CRC: polynomial `0x04C11DB7`, init `0xFFFFFFFF`, no reflection on input or output, no final XOR, words fed MSB-first. The host computes a matching CRC in Python — see `_stm32_crc32` in `host_tools/uart_flash.py` for the reference implementation.

## CRC16 algorithm (UART framing only)

CRC-16/CCITT-FALSE: polynomial `0x1021`, init `0xFFFF`, no reflection, no XorOut.

## Activity timer

The bootloader's main loop tracks how recently it received a valid command. If silence exceeds:
- `STARTUP_TO` (2 s) — at startup before any command is received,
- `NOCANRX_TO` (3 s) — after at least one valid command,
- `FLASH_INPROGRESS_TO` (60 s) — once a flash sequence has started (WBUF/WPAGE/STREAM seen),

the bootloader checks whether the stored application CRC is valid. If yes, it sets the SRAM magic and resets to the app via the fast path. If no, it stays in bootloader mode (LED blinks idle pattern).

This means: a host that takes a long pause mid-flash (e.g. slow USB stack) is tolerated for 60 s, but a host that simply walks away after a valid command lets the board boot the existing app within 3 s. Cold boots boot the app within 2 s.
