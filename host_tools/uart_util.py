"""
uart_util.py — Low-level UART helpers for the host bootloader.

Frame format (host → MCU):
  [0xBB][CMD][LEN_L][LEN_H][BOARD_ID][DATA...][CRC16_L][CRC16_H]
  CRC16/CCITT-FALSE over bytes [CMD..DATA end]

Response (MCU → host, 3 bytes):
  [board_id][cmd][error_code]
"""

import serial
import struct
import time

UART_START = 0xBB
UART_COMMAND_GAP_SEC = 0.005
# Serial read timeout: generous enough to receive a 3-byte reply,
# but short enough that a lost reply doesn't stall the transfer.
# At 256 kbps a 3-byte frame takes ~0.1 ms; 200 ms gives ample margin
# while letting page-level retry recover before the bootloader timeout.
CMD_TIMEOUT = 0.2   # seconds

# Command codes (must match firmware)
BL_PING          = 0x01
BL_WBUF          = 0x02
BL_WPAGE         = 0x03
BL_WCRC          = 0x04
BL_SET_ID        = 0x05
BL_ERASE_APP     = 0x06
BL_STREAM_BEGIN  = 0x07
BL_STREAM_STATUS = 0x08
BL_STREAM_DATA   = 0x09  # fire-and-forget; bootloader does not reply

# Page size in bytes and stream parameters
PG_SIZE = 1024
UART_STREAM_FRAME_COUNT = 128   # 128 x 8 bytes = 1 KB page
APP_RESET_PACKET = b"#Reset\n"


def _crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly=0x1021, init=0xFFFF, no reflect."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
        crc &= 0xFFFF
    return crc


def build_frame(cmd: int, board_id: int, payload: bytes = b"") -> bytes:
    """Build a complete bootloader UART frame."""
    length = len(payload)
    header = bytes([cmd, length & 0xFF, (length >> 8) & 0xFF, board_id])
    body = header + payload
    crc = _crc16(body)
    return bytes([UART_START]) + body + struct.pack("<H", crc)


def get_serial(port: str, baudrate: int = 256000) -> serial.Serial:
    return serial.Serial(port, baudrate=baudrate, bytesize=8, parity="N",
                         stopbits=1, timeout=CMD_TIMEOUT)


def _drain_rx(ser: serial.Serial, max_bytes: int = 256) -> None:
    """Discard any pending RX bytes without blocking. More thorough than
    reset_input_buffer alone — also reads any bytes the driver hasn't
    surfaced to the OS buffer yet."""
    saved = ser.timeout
    try:
        ser.timeout = 0  # non-blocking
        for _ in range(4):  # repeat to catch slow-arriving bytes
            ser.reset_input_buffer()
            data = ser.read(max_bytes)
            if not data:
                break
    finally:
        ser.timeout = saved


def send_cmd(ser: serial.Serial, cmd: int, board_id: int,
             payload: bytes = b"") -> tuple:
    """Send a command and return (board_id, cmd, error_code) reply tuple.

    Reply layout (5 bytes): [board_id][cmd][error_code][par1_lo][par1_hi]
    Raises RuntimeError on timeout or framing error.
    """
    frame = build_frame(cmd, board_id, payload)
    time.sleep(UART_COMMAND_GAP_SEC)
    _drain_rx(ser)
    ser.write(frame)
    ser.flush()
    resp = ser.read(5)
    if len(resp) < 5:
        raise RuntimeError(f"Timeout: no reply to cmd=0x{cmd:02X} (got {len(resp)} bytes)")
    if resp[0] != board_id or resp[1] != cmd:
        # Show full 5 bytes for diagnosis when reply is misaligned.
        raise RuntimeError(
            f"Unexpected reply: board={resp[0]} cmd=0x{resp[1]:02X} ec={resp[2]} "
            f"par1=0x{resp[3]:02X}{resp[4]:02X} (raw={resp.hex()})"
        )
    return resp[0], resp[1], resp[2]


def wait_for_connection(ser: serial.Serial, board_id: int,
                        retries: int = 100) -> bool:
    """Ping the board until it responds."""
    ser.reset_input_buffer()
    for _ in range(retries):
        try:
            reply_board_id, _, ec = send_cmd(ser, BL_PING, board_id)
            if ec == 0 and reply_board_id == board_id:
                return True
        except RuntimeError:
            pass
        time.sleep(0.05)
    return False


def scan_boards(ser: serial.Serial, retries: int = 100) -> set:
    """Ping broadcast and collect board IDs that reply."""
    board_ids = set()
    ser.reset_input_buffer()
    for _ in range(retries):
        try:
            ser.reset_input_buffer()
            frame = build_frame(BL_PING, 0)
            time.sleep(UART_COMMAND_GAP_SEC)
            ser.write(frame)
            ser.flush()
            resp = ser.read(5)
            if len(resp) >= 3 and resp[1] == BL_PING and resp[2] == 0:
                reply_board_id = resp[0]
                board_ids.add(reply_board_id)
        except RuntimeError:
            pass
        time.sleep(0.05)
    return board_ids


def send_app_reset(ser: serial.Serial) -> None:
    """Send the host app text reset command over UART."""
    ser.reset_input_buffer()
    ser.write(APP_RESET_PACKET)
    ser.flush()
    time.sleep(0.5)
    ser.reset_input_buffer()


def send_frame_noreply(ser: serial.Serial, cmd: int, board_id: int,
                       payload: bytes = b"") -> None:
    """Send a bootloader frame without expecting a reply (fire-and-forget).

    Used for STREAM_DATA — the bootloader does not ACK these frames; the host
    correlates via STREAM_STATUS at the end of a chunk.
    """
    frame = build_frame(cmd, board_id, payload)
    ser.write(frame)
    # Intentionally no flush here — let pyserial batch writes for throughput.
