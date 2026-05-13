"""
uart_flash.py — UART-specific flash logic for the host bootloader.
"""

import struct
import time
from uart_util import (
    get_serial, scan_boards, send_app_reset, wait_for_connection, send_cmd,
    send_frame_noreply,
    BL_PING, BL_WBUF, BL_WPAGE, BL_WCRC, BL_SET_ID, BL_ERASE_APP,
    BL_STREAM_BEGIN, BL_STREAM_STATUS, BL_STREAM_DATA,
    PG_SIZE, UART_STREAM_FRAME_COUNT,
)

PAGE_RETRIES = 8
BL_BOARD_ID_MAX = 13

DEFAULT_STREAM_ENABLED = True
DEFAULT_STREAM_CHUNK_FRAMES = 16
STREAM_CHUNK_RETRIES = 5

EC_NAMES = {0: "OK", 1: "INVALID_OFFSET", 2: "INVALID_CRC",
            3: "FLASH_WRITE_ERR", 4: "INVALID_PAGE_NUM"}

WORD_RETRIES = 3  # retries per word


def _format_elapsed(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = seconds - (minutes * 60)
    if minutes:
        return f"{minutes}m {secs:.1f}s"
    return f"{secs:.1f}s"


def _resync_bootloader(ser, board_id: int) -> bool:
    """Give the UART parser time to recover, then confirm bootloader replies."""
    ser.reset_input_buffer()
    return wait_for_connection(ser, board_id, retries=20)


def _stm32_crc32(words):
    """CRC-32 exactly matching STM32F1 hardware CRC unit.
    Poly=0x04C11DB7, init=0xFFFFFFFF, no reflection, no XorOut.
    Words are fed MSB-first (bit 31 first), one 32-bit word at a time.
    """
    crc = 0xFFFFFFFF
    for w in words:
        crc ^= w
        for _ in range(32):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def erase_app(ser, board_id: int) -> None:
    """Erase all application flash pages via the bootloader.

    Bootloader takes ~3.5 s to erase 116 pages, so temporarily extend the
    serial read timeout for this single command.
    """
    print("Erasing application flash area...", end=" ", flush=True)
    saved_timeout = ser.timeout
    try:
        ser.timeout = 15.0
        _, _, ec = send_cmd(ser, BL_ERASE_APP, board_id)
    finally:
        ser.timeout = saved_timeout
    if ec != 0:
        raise RuntimeError(f"ERASE_APP failed with error code {ec}")
    print("OK")


def _send_stream_chunk(ser, board_id: int, chunk_items, end_seq: int) -> None:
    """Send a chunk of stream-data frames then verify via STREAM_STATUS.

    chunk_items: list of (seq, 8-byte data) tuples.
    Retries the whole chunk if STREAM_STATUS reports missing frames.
    """
    for attempt in range(STREAM_CHUNK_RETRIES):
        for seq, payload in chunk_items:
            send_frame_noreply(ser, BL_STREAM_DATA, board_id,
                               bytes([seq]) + payload)
        ser.flush()

        # Verify: ask BL whether frames 0..end_seq have all been seen.
        status_payload = struct.pack("<H", end_seq)
        try:
            _, _, ec = send_cmd(ser, BL_STREAM_STATUS, board_id, status_payload)
            if ec == 0:
                return
        except RuntimeError:
            pass
        time.sleep(0.005)
        ser.reset_input_buffer()
    raise RuntimeError(f"Stream chunk ending at frame {end_seq} did not verify")


def _flash_page_stream(ser, board_id: int, page_num: int, page_bytes: bytes,
                        page_crc: int, stream_chunk_frames: int) -> None:
    """Flash one page using stream mode (fire-and-forget data + bitmask status)."""
    ser.reset_input_buffer()

    # Start streaming for this page
    _, _, ec = send_cmd(ser, BL_STREAM_BEGIN, board_id,
                        struct.pack("<H", page_num))
    if ec != 0:
        raise RuntimeError(f"STREAM_BEGIN page={page_num} ec={ec}")

    # Build the 128 data frames (8 bytes each)
    frame_items = []
    for seq in range(UART_STREAM_FRAME_COUNT):
        start = seq * 8
        frame_items.append((seq, page_bytes[start:start + 8]))

    # Send chunks; verify each chunk via STREAM_STATUS.
    for chunk_start in range(0, UART_STREAM_FRAME_COUNT, stream_chunk_frames):
        if chunk_start % 16 == 0:
            print(".", end="", flush=True)
        chunk_items = frame_items[chunk_start:chunk_start + stream_chunk_frames]
        end_seq = chunk_items[-1][0]
        _send_stream_chunk(ser, board_id, chunk_items, end_seq)

    # Commit the buffer to flash with end-of-page CRC check.
    crc_payload = struct.pack("<H", page_num) + struct.pack("<I", page_crc)
    _, _, ec = send_cmd(ser, BL_WPAGE, board_id, crc_payload)
    if ec != 0:
        raise RuntimeError(f"WRITE_PAGE page={page_num} ec={ec} ({EC_NAMES.get(ec, '?')})")

    # Small breather to let the USB-UART pipeline drain between pages.
    time.sleep(0.001)


def _flash_page(ser, board_id: int, page_num: int, page_data: bytes) -> bool:
    """Write one 1 KB page over UART. Returns True on success."""
    words = struct.unpack(f"<{PG_SIZE // 4}I", page_data)

    # Pre-compute page CRC once using manual STM32-identical implementation
    page_crc = _stm32_crc32(words)
    print(f" [CRC=0x{page_crc:08X}]", end=" ", flush=True)
    crc_payload = struct.pack("<H", page_num) + struct.pack("<I", page_crc)

    for page_attempt in range(PAGE_RETRIES):
        # Re-send all words into the MCU page buffer on every page attempt.
        # This is necessary if the MCU reset mid-page (pagebuf is zeroed on reset).
        buf_ok = True
        for offset, word in enumerate(words):
            if offset % 16 == 0:
                print(".", end="", flush=True)
            payload = struct.pack("<H", offset) + struct.pack("<I", word)
            for attempt in range(WORD_RETRIES):
                try:
                    _, _, ec = send_cmd(ser, BL_WBUF, board_id, payload)
                    if ec == 0:
                        break
                    print(f"\r  WRITE_BUF pg={page_num} off={offset} ec={ec} ({EC_NAMES.get(ec,'?')}), retry {attempt+1}/{WORD_RETRIES}  ", end="")
                except RuntimeError:
                    print(f"\r  WRITE_BUF pg={page_num} off={offset} timeout, retry {attempt+1}/{WORD_RETRIES}  ", end="")
            else:
                print(f"\n  FAILED: WRITE_BUF page={page_num} offset={offset} (all {WORD_RETRIES} retries exhausted)")
                print("  Resyncing UART bootloader...", end=" ", flush=True)
                if _resync_bootloader(ser, board_id):
                    print("OK")
                else:
                    print("FAILED")
                    return False
                buf_ok = False
                break
        if not buf_ok:
            continue  # retry the whole page

        # Commit the buffer to flash
        try:
            _, _, ec = send_cmd(ser, BL_WPAGE, board_id, crc_payload)
            if ec == 0:
                return True
            print(f"\n  FAILED: WRITE_PAGE page={page_num} ec={ec} ({EC_NAMES.get(ec,'?')}), attempt {page_attempt+1}/{PAGE_RETRIES}")
        except RuntimeError:
            print(f"\n  FAILED: WRITE_PAGE page={page_num} timeout, attempt {page_attempt+1}/{PAGE_RETRIES}")
            print("  Resyncing UART bootloader...", end=" ", flush=True)
            if _resync_bootloader(ser, board_id):
                print("OK")
            else:
                print("FAILED")
                return False

    return False


def flash(board_id: int, filepath: str, port: str, baudrate: int = 256000,
          interactive: bool = True, erase_first: bool = False,
          stream_enabled: bool = DEFAULT_STREAM_ENABLED,
          stream_chunk_frames: int = DEFAULT_STREAM_CHUNK_FRAMES):
    start_time = time.perf_counter()

    if board_id < 0 or board_id > BL_BOARD_ID_MAX:
        raise RuntimeError(f"Invalid board ID. Choose an ID from 0-{BL_BOARD_ID_MAX}. IDs 14 and 15 are reserved.")
    if stream_chunk_frames < 1 or stream_chunk_frames > UART_STREAM_FRAME_COUNT:
        raise RuntimeError(f"Invalid stream chunk size. Choose 1-{UART_STREAM_FRAME_COUNT}.")

    if interactive and not filepath.endswith(".bin"):
        ans = input("File does not end in '.bin'. Flash anyway? (Y/n): ")
        if "n" in ans.lower():
            print("Cancelled.")
            return

    with open(filepath, "rb") as f:
        data = bytearray(f.read())

    if len(data) % PG_SIZE:
        data.extend(bytes(PG_SIZE - (len(data) % PG_SIZE)))
    num_pages = len(data) // PG_SIZE

    ser = get_serial(port, baudrate)
    print(f"Connecting to board {board_id} on {port}...")
    if not wait_for_connection(ser, board_id, retries=12):
        print("No bootloader reply. Sending app UART reset command...")
        send_app_reset(ser)
        if not wait_for_connection(ser, board_id):
            board_ids = sorted(scan_boards(ser, retries=40))
            ser.close()
            if board_ids:
                detected = ", ".join(str(detected_id) for detected_id in board_ids)
                raise RuntimeError(f"Could not connect to board {board_id}. Detected UART board ID(s): {detected}.")
            raise RuntimeError(f"Could not connect to board {board_id}.")

    if erase_first:
        erase_app(ser, board_id)

    print(f"Connected. Flashing {filepath} ({num_pages} pages)...")
    if stream_enabled:
        print(f"UART stream mode: chunk_frames={stream_chunk_frames}")

    # Compute app-level CRC over all words (same STM32 HW CRC algorithm)
    all_words = struct.unpack(f"<{len(data) // 4}I", data)
    app_crc = _stm32_crc32(all_words)

    stream_failed = False
    for p in range(num_pages):
        page_bytes = bytes(data[p * PG_SIZE:(p + 1) * PG_SIZE])
        page_words = struct.unpack(f"<{PG_SIZE // 4}I", page_bytes)
        page_crc = _stm32_crc32(page_words)

        print(f"  Page {p + 1}/{num_pages}", end=" ", flush=True)

        ok = False
        if stream_enabled and not stream_failed:
            for attempt in range(PAGE_RETRIES):
                try:
                    _flash_page_stream(ser, board_id, p, page_bytes, page_crc,
                                       stream_chunk_frames)
                    ok = True
                    break
                except RuntimeError as exc:
                    print(f"\n    stream error: {exc}")
                    if attempt == PAGE_RETRIES - 1:
                        print("    Streaming failed; switching to WBUF fallback")
                        stream_failed = True
                        break
                    time.sleep(0.05)
                    ser.reset_input_buffer()
                    if not wait_for_connection(ser, board_id, retries=20):
                        print("    Could not re-sync with bootloader")
                        stream_failed = True
                        break
                    print(f"    Retrying page {p + 1} via stream", end="", flush=True)

        if not ok:
            ok = _flash_page(ser, board_id, p, page_bytes)

        print("OK" if ok else "FAILED")
        if not ok:
            ser.close()
            raise RuntimeError(f"Failed to write page {p}.")

    # Finalise
    payload = struct.pack("<H", num_pages) + struct.pack("<I", app_crc)  # 6 bytes
    print("Writing final CRC...", end=" ", flush=True)
    _, _, ec = send_cmd(ser, BL_WCRC, board_id, payload)
    print("OK" if ec == 0 else f"ERROR (code {ec})")
    ser.close()

    if ec != 0:
        raise RuntimeError("Board rejected final CRC.")
    elapsed = _format_elapsed(time.perf_counter() - start_time)
    print(f"Flash complete in {elapsed}! Board will reboot into the new firmware.")


def reset_app(port: str, baudrate: int = 256000):
    ser = get_serial(port, baudrate)
    try:
        print("Sending host app UART reset command...")
        send_app_reset(ser)
    finally:
        ser.close()


def reset_app_and_wait(board_id: int, port: str, baudrate: int = 256000):
    ser = get_serial(port, baudrate)
    try:
        print("Sending host app UART reset command...")
        send_app_reset(ser)
        print(f"Waiting for bootloader board {board_id}...")
        if wait_for_connection(ser, board_id):
            print(f"Detected bootloader board {board_id}.")
            return True
        board_ids = sorted(scan_boards(ser, retries=40))
        if board_id in board_ids:
            print(f"Detected bootloader board {board_id}.")
            return True
        if board_ids:
            print("Detected UART bootloader board(s), but not the requested ID:")
            for detected_id in board_ids:
                print(f"  Board ID {detected_id}")
        else:
            print("No UART bootloader boards detected after app reset.")
        print(f"Did not detect bootloader board {board_id}.")
        return False
    finally:
        ser.close()


def change_id(board_id: int, new_id: int, port: str, baudrate: int = 256000):
    if board_id < 0 or board_id > BL_BOARD_ID_MAX:
        raise RuntimeError(f"Invalid current board ID. Choose an ID from 0-{BL_BOARD_ID_MAX}. IDs 14 and 15 are reserved.")

    if new_id < 0 or new_id > BL_BOARD_ID_MAX:
        raise RuntimeError(f"Invalid ID. Choose an ID from 0-{BL_BOARD_ID_MAX}. IDs 14 and 15 are reserved.")

    ser = get_serial(port, baudrate)
    print(f"Connecting to board {board_id} on {port}...")
    if not wait_for_connection(ser, board_id):
        ser.close()
        raise RuntimeError(f"Could not connect to board {board_id}.")
    payload = bytes([new_id & 0xFF])
    _, _, ec = send_cmd(ser, BL_SET_ID, board_id, payload)
    ser.close()
    if ec == 0:
        print(f"Board {board_id} ID changed to {new_id}.")
    else:
        raise RuntimeError(f"SET_ID failed with error code {ec}.")


def list_connected_boards(port: str, baudrate: int = 256000):
    """Send a single broadcast PING and report the board ID from the reply."""
    print(f"Scanning for boards on {port} at {baudrate} bps...")
    ser = get_serial(port, baudrate)
    try:
        # PING is broadcast — board always replies with its own ID
        bid, _, ec = send_cmd(ser, BL_PING, 0)
        if ec == 0:
            print(f"  Found board ID {bid}")
            print("Board is in bootloader mode and ready.")
        else:
            print(f"  Board replied with error code {ec}")
    except RuntimeError:
        print("No boards found. Make sure the board is in bootloader mode (within 2 s of reset).")
    finally:
        ser.close()


def list_connected_boards(port: str, baudrate: int = 256000):
    """Scan for boards in bootloader mode."""
    print(f"Scanning for boards on {port} at {baudrate} bps...")
    print("(Reset or power-cycle the board now - scanning for about 7 seconds...)")
    ser = get_serial(port, baudrate)
    try:
        board_ids = sorted(scan_boards(ser, retries=100))
        if not board_ids:
            print("No boards found. Make sure the board is in bootloader mode.")
            return
        print("Detected board(s):")
        for board_id in board_ids:
            print(f"  Board ID {board_id}")
    finally:
        ser.close()
