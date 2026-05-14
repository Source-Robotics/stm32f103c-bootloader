import crcmod
import time

from can_util import (
    BL_STREAM_BEGIN,
    BL_STREAM_STATUS,
    BL_PING,
    BL_SET_ID,
    BL_ERASE_APP,
    BL_WBUF,
    BL_WCRC,
    BL_WPAGE,
    BL_BOARD_ID_MAX,
    CAN_STREAM_FRAME_COUNT,
    PG_SIZE,
    app_ping,
    bl_cmd,
    bl_cmd_response,
    bl_list_connected_boards,
    bl_wait_for_connection,
    bl_waitresp,
    flush_rx,
    get_can_bus,
    is_bl_response_id,
    send_app_reset,
    stream_data_can_id,
    canmsg,
)

PAGE_RETRIES = 10
DEFAULT_WBUF_SEND_GAP_SEC = 0.0
DEFAULT_PAGE_DRAIN_GAP_SEC = 0.0
DEFAULT_PAGE_GAP_SEC = 0.0
GS_USB_WBUF_SEND_GAP_SEC = DEFAULT_WBUF_SEND_GAP_SEC
GS_USB_PAGE_DRAIN_GAP_SEC = DEFAULT_PAGE_DRAIN_GAP_SEC
GS_USB_PAGE_GAP_SEC = DEFAULT_PAGE_GAP_SEC
DEFAULT_WBUF_ACK_STRIDE = 1
GS_USB_WBUF_ACK_STRIDE = 2
WBUF_BLOCK_RETRIES = 1
WBUF_ACK_TIMEOUT_SEC = 0.25
WBUF_RETRY_GAP_STEP_SEC = 0.0005
WBUF_RETRY_MAX_GAP_SEC = 0.004
DEFAULT_STREAM_ENABLED = True
DEFAULT_STREAM_CHUNK_FRAMES = 16
STREAM_CHUNK_RETRIES = 5


def _format_elapsed(seconds):
    minutes = int(seconds // 60)
    secs = seconds - (minutes * 60)
    if minutes:
        return f"{minutes}m {secs:.1f}s"
    return f"{secs:.1f}s"


def list_connected_boards(channel=None, can_interface="auto"):
    print("Searching for host boards in bootloader mode...")
    print("(Power-cycle the board now - scanning for 15 seconds...)")
    bus = get_can_bus(channel, can_interface)
    try:
        board_ids = sorted(bl_list_connected_boards(bus))
    finally:
        bus.shutdown()

    if len(board_ids) == 0:
        print("No boards detected.")
        return

    print("Detected board(s):")
    for board_id in board_ids:
        print(f"  Board ID {board_id}")
    if 0 in board_ids:
        print("\nBoard ID 0 detected. Use set-id before flashing multiple boards.")


def reset_app(node_id, channel=None, can_interface="auto"):
    bus = get_can_bus(channel, can_interface)
    try:
        print(f"Sending host app reset command to node {node_id}...")
        send_app_reset(bus, node_id)
    finally:
        bus.shutdown()


def reset_app_and_wait(node_id, board_id=None, channel=None, can_interface="auto"):
    if board_id is None:
        board_id = node_id

    bus = get_can_bus(channel, can_interface)
    try:
        print(f"Sending host app reset command to node {node_id}...")
        send_app_reset(bus, node_id)
        print(f"Waiting for bootloader board {board_id}...")
        if bl_wait_for_connection(bus, board_id, timeout_sec=0.05, retries=80):
            print(f"Detected bootloader board {board_id}.")
            return True
        board_ids = sorted(bl_list_connected_boards(bus, timeout_sec=0.05, retries=20))
        if board_id in board_ids:
            print(f"Detected bootloader board {board_id}.")
            return True
        if board_ids:
            print("Detected bootloader board(s), but not the requested ID:")
            for detected_id in board_ids:
                print(f"  Board ID {detected_id}")
        else:
            print("No bootloader boards detected after app reset.")
        print(f"Did not detect bootloader board {board_id}.")
        return False
    finally:
        bus.shutdown()


def ping_app(node_id, channel=None, can_interface="auto"):
    bus = get_can_bus(channel, can_interface)
    try:
        print(f"Pinging host app node {node_id}...")
        if app_ping(bus, node_id):
            print(f"Detected host app node {node_id}.")
            return True
        print(f"No app ping response from node {node_id}.")
        return False
    finally:
        bus.shutdown()


def scan_app_nodes(channel=None, can_interface="auto"):
    found = []
    bus = get_can_bus(channel, can_interface)
    try:
        for node_id in range(16):
            if app_ping(bus, node_id, timeout=0.15):
                found.append(node_id)
        if found:
            print("Detected host app node(s):")
            for node_id in found:
                print(f"  Node ID {node_id}")
        else:
            print("No host app nodes detected.")
        return found
    finally:
        bus.shutdown()


def _crc32():
    return crcmod.Crc(0x104C11DB7, initCrc=0xFFFFFFFF, rev=False)


def erase_app(board_id, bus):
    print("Erasing application flash area and verifying blank...", end=" ", flush=True)
    bl_cmd_response(bus, board_id, BL_ERASE_APP, 0, [0] * 4,
                    timeout_sec=15.0, retries=1)
    flush_rx(bus)
    print("OK")


def _wait_wbuf_block_acks(bus, board_id, expected_offsets, timeout_sec):
    pending = set(expected_offsets)
    deadline = time.perf_counter() + timeout_sec
    while time.perf_counter() < deadline:
        if not pending:
            return 0
        remaining = max(0.0, deadline - time.perf_counter())
        msg = bus.recv(min(remaining, 0.02))
        if msg is None:
            continue
        if not (
            is_bl_response_id(msg.arbitration_id)
            and msg.dlc >= 5
            and msg.data[0] == board_id
            and msg.data[1] == BL_WBUF
        ):
            continue

        result = msg.data[2]
        par1 = msg.data[3] | (msg.data[4] << 8)
        if result > 0:
            return result
        pending.discard(par1)

    return pending


def _send_wbuf_block(bus, board_id, block_items, wbuf_gap_sec, wbuf_ack_stride):
    expected_offsets = [word_offset for word_offset, _ in block_items]
    for attempt in range(WBUF_BLOCK_RETRIES):
        flush_rx(bus, timeout_sec=0.001)
        for word_offset, word_bytes in block_items:
            bl_cmd(bus, board_id, BL_WBUF, word_offset, word_bytes)
            if wbuf_gap_sec > 0:
                time.sleep(wbuf_gap_sec)

        if not wbuf_ack_stride:
            return

        result = _wait_wbuf_block_acks(
            bus, board_id, expected_offsets, WBUF_ACK_TIMEOUT_SEC
        )
        if result == 0:
            return
        if isinstance(result, int):
            raise RuntimeError(
                f"WBUF block {expected_offsets[0]}-{expected_offsets[-1]}: error #{result}"
            )
        time.sleep(0.02)

    missing = ",".join(str(offset) for offset in sorted(result))
    raise RuntimeError(
        f"WBUF block {expected_offsets[0]}-{expected_offsets[-1]}: missing ACK(s) {missing}"
    )


def _send_stream_chunk(bus, board_id, chunk_items, end_seq, noise_callback=None):
    for attempt in range(STREAM_CHUNK_RETRIES):
        if noise_callback is not None:
            noise_callback(bus)
        for seq, payload in chunk_items:
            bus.send(canmsg(stream_data_can_id(board_id, seq), payload), 1.0)

        try:
            bl_cmd_response(
                bus, board_id, BL_STREAM_STATUS, end_seq, [0] * 4,
                timeout_sec=0.25, retries=1,
            )
            return
        except RuntimeError as exc:
            if attempt == STREAM_CHUNK_RETRIES - 1:
                raise RuntimeError(
                    f"Stream chunk ending at frame {end_seq} did not verify"
                ) from exc
            time.sleep(0.01)
            flush_rx(bus, timeout_sec=0.001)


def _flash_page_stream(
    bus,
    board_id,
    page,
    pcrc,
    page_bytes,
    stream_chunk_frames,
    noise_callback=None,
):
    flush_rx(bus, timeout_sec=0.001)
    bl_cmd_response(
        bus, board_id, BL_STREAM_BEGIN, page, [0] * 4,
        timeout_sec=0.5, retries=1,
    )

    frame_items = []
    for seq in range(CAN_STREAM_FRAME_COUNT):
        start = seq * 8
        frame_items.append((seq, page_bytes[start:start + 8]))

    for chunk_start in range(0, CAN_STREAM_FRAME_COUNT, stream_chunk_frames):
        if chunk_start % 16 == 0:
            print(".", end="", flush=True)
        chunk_items = frame_items[chunk_start:chunk_start + stream_chunk_frames]
        end_seq = chunk_items[-1][0]
        _send_stream_chunk(bus, board_id, chunk_items, end_seq, noise_callback)

    bl_cmd_response(bus, board_id, BL_WPAGE, page, pcrc.digest(), timeout_sec=1.0)


def _flash_page(bus, board_id, page, pcrc, page_data,
                wbuf_gap_sec, page_drain_gap_sec, page_gap_sec,
                wbuf_ack_stride, noise_callback=None):
    flush_rx(bus, timeout_sec=0.001)
    page_items = list(page_data.items())
    if wbuf_ack_stride:
        for block_start in range(0, len(page_items), wbuf_ack_stride):
            if block_start % 16 == 0:
                print(".", end="", flush=True)
            if noise_callback is not None:
                noise_callback(bus)
            block_items = page_items[block_start:block_start + wbuf_ack_stride]
            _send_wbuf_block(bus, board_id, block_items, wbuf_gap_sec, wbuf_ack_stride)
    else:
        for word_offset, word_bytes in page_items:
            if word_offset % 16 == 0:
                print(".", end="", flush=True)
            if noise_callback is not None:
                noise_callback(bus)
            bl_cmd(bus, board_id, BL_WBUF, word_offset, word_bytes)
            if wbuf_gap_sec > 0:
                time.sleep(wbuf_gap_sec)
    if page_drain_gap_sec > 0:
        time.sleep(page_drain_gap_sec)
    bl_cmd_response(bus, board_id, BL_WPAGE, page, pcrc.digest(), timeout_sec=1.0)
    if page_gap_sec > 0:
        time.sleep(page_gap_sec)


def flash(board_id, filepath, channel=None, interactive=True, app_node=None,
          wbuf_gap_sec=None,
          page_drain_gap_sec=None,
          page_gap_sec=None,
          wbuf_ack_stride=None,
          erase_first=False,
          stream_enabled=DEFAULT_STREAM_ENABLED,
          stream_chunk_frames=DEFAULT_STREAM_CHUNK_FRAMES,
          can_interface="auto",
          noise_callback=None):
    start_time = time.perf_counter()

    if wbuf_gap_sec is None:
        wbuf_gap_sec = GS_USB_WBUF_SEND_GAP_SEC if can_interface == "gs_usb" else DEFAULT_WBUF_SEND_GAP_SEC
    if page_drain_gap_sec is None:
        page_drain_gap_sec = GS_USB_PAGE_DRAIN_GAP_SEC if can_interface == "gs_usb" else DEFAULT_PAGE_DRAIN_GAP_SEC
    if page_gap_sec is None:
        page_gap_sec = GS_USB_PAGE_GAP_SEC if can_interface == "gs_usb" else DEFAULT_PAGE_GAP_SEC
    if wbuf_ack_stride is None:
        wbuf_ack_stride = GS_USB_WBUF_ACK_STRIDE if can_interface == "gs_usb" else DEFAULT_WBUF_ACK_STRIDE

    if board_id < 0 or board_id > BL_BOARD_ID_MAX:
        raise RuntimeError(f"Invalid board ID. Choose an ID from 0-{BL_BOARD_ID_MAX}. IDs 14 and 15 are reserved.")
    if stream_chunk_frames < 1 or stream_chunk_frames > CAN_STREAM_FRAME_COUNT:
        raise RuntimeError(f"Invalid stream chunk size. Choose 1-{CAN_STREAM_FRAME_COUNT}.")

    if interactive and not filepath.endswith(".bin"):
        response = input('File path does not end in ".bin". Flash anyway? (Y/n): ')
        if "n" in response.lower():
            print("Firmware flashing canceled")
            return

    with open(filepath, "rb") as firmware_file:
        image = bytearray(firmware_file.read())

    remainder = len(image) % PG_SIZE
    if remainder:
        image.extend(bytearray(PG_SIZE - remainder))
    num_pages = len(image) // PG_SIZE

    app_crc = _crc32()
    bus = get_can_bus(channel, can_interface)
    try:
        print(f"Connecting to board {board_id}...")
        if not bl_wait_for_connection(bus, board_id, retries=3):
            reset_node = board_id if app_node is None else app_node
            print(f"No bootloader reply. Sending app reset command to node {reset_node}...")
            send_app_reset(bus, reset_node)
            time.sleep(0.25)
            if not bl_wait_for_connection(bus, board_id):
                board_ids = sorted(bl_list_connected_boards(bus, timeout_sec=0.05, retries=20))
                if board_id in board_ids:
                    print(f"Detected bootloader board {board_id}.")
                elif board_ids:
                    print("Detected bootloader board(s), but not the requested ID:")
                    for detected_id in board_ids:
                        print(f"  Board ID {detected_id}")
                    raise RuntimeError(f"Could not connect to board {board_id}.")
                else:
                    print("No bootloader boards detected after app reset.")
                    raise RuntimeError(f"Could not connect to board {board_id}.")
        flush_rx(bus)

        if erase_first:
            erase_app(board_id, bus)

        print(f"Connected. Flashing {filepath} ({num_pages} pages)...")
        print(
            f"CAN pacing: wbuf_gap={wbuf_gap_sec * 1000:.1f} ms, "
            f"page_drain={page_drain_gap_sec * 1000:.1f} ms, "
            f"page_gap={page_gap_sec * 1000:.1f} ms, "
            f"wbuf_ack_stride={wbuf_ack_stride}"
        )
        if stream_enabled:
            print(f"CAN stream mode: chunk_frames={stream_chunk_frames}")
        learned_wbuf_ack_stride = wbuf_ack_stride
        stream_failed = False
        for page in range(num_pages):
            print(f"  Page {page + 1}/{num_pages} ", end="", flush=True)
            page_crc = _crc32()
            page_data = {}
            page_start = page * PG_SIZE
            page_bytes = bytes(image[page_start:page_start + PG_SIZE])

            for word_offset in range(PG_SIZE // 4):
                start = (page * PG_SIZE) + (word_offset * 4)
                word_bytes = image[start:start + 4][::-1]
                app_crc.update(word_bytes)
                page_crc.update(word_bytes)
                page_data[word_offset] = word_bytes

            retry_wbuf_gap_sec = wbuf_gap_sec
            retry_wbuf_ack_stride = learned_wbuf_ack_stride
            for attempt in range(PAGE_RETRIES):
                try:
                    if stream_enabled and not stream_failed:
                        _flash_page_stream(
                            bus, board_id, page, page_crc, page_bytes,
                            stream_chunk_frames, noise_callback,
                        )
                    else:
                        _flash_page(bus, board_id, page, page_crc, page_data,
                                    retry_wbuf_gap_sec, page_drain_gap_sec, page_gap_sec,
                                    retry_wbuf_ack_stride, noise_callback)
                        learned_wbuf_ack_stride = retry_wbuf_ack_stride
                    print(" CRC OK")
                    break
                except RuntimeError as exc:
                    print(f"\n    Error flashing page: {exc}")
                    if attempt == PAGE_RETRIES - 1:
                        raise RuntimeError(f"Failed to write page {page}.") from exc
                    time.sleep(max(page_drain_gap_sec, 0.2))
                    flush_rx(bus, timeout_sec=0.01)
                    if stream_enabled and not stream_failed:
                        stream_failed = True
                        print(
                            f"    Streaming failed; retrying page {page + 1}/{num_pages} "
                            f"with WBUF fallback (wbuf_ack_stride={retry_wbuf_ack_stride}) ",
                            end="",
                            flush=True,
                        )
                    elif wbuf_ack_stride == 0:
                        retry_wbuf_gap_sec = min(
                            retry_wbuf_gap_sec + WBUF_RETRY_GAP_STEP_SEC,
                            WBUF_RETRY_MAX_GAP_SEC,
                        )
                        print(
                            f"    Retrying page {page + 1}/{num_pages} "
                            f"(wbuf_gap={retry_wbuf_gap_sec * 1000:.1f} ms) ",
                            end="",
                            flush=True,
                        )
                    elif retry_wbuf_ack_stride > 1:
                        retry_wbuf_ack_stride = max(1, retry_wbuf_ack_stride // 2)
                        print(
                            f"    Retrying page {page + 1}/{num_pages} "
                            f"(wbuf_ack_stride={retry_wbuf_ack_stride}) ",
                            end="",
                            flush=True,
                        )
                    else:
                        print(f"    Retrying page {page + 1}/{num_pages} ", end="", flush=True)
                    bl_wait_for_connection(bus, board_id, retries=10)
                    flush_rx(bus)

        print("Verifying...", end=" ", flush=True)
        bl_cmd_response(bus, board_id, BL_WCRC, num_pages, app_crc.digest(), timeout_sec=1.0)
        print("OK")
        elapsed = _format_elapsed(time.perf_counter() - start_time)
        print(f"Flash complete in {elapsed}! Board will reboot into the new firmware.")
    finally:
        bus.shutdown()


def change_id(board_id, new_id, channel=None, can_interface="auto"):
    if board_id < 0 or board_id > BL_BOARD_ID_MAX:
        raise RuntimeError(f"Invalid current board ID. Choose an ID from 0-{BL_BOARD_ID_MAX}. IDs 14 and 15 are reserved.")

    if new_id < 0 or new_id > BL_BOARD_ID_MAX:
        raise RuntimeError(f"Invalid ID. Choose an ID from 0-{BL_BOARD_ID_MAX}. IDs 14 and 15 are reserved.")

    bus = get_can_bus(channel, can_interface)
    try:
        print(f"Connecting to board {board_id}...")
        if not bl_wait_for_connection(bus, board_id):
            raise RuntimeError(f"Could not connect to board {board_id}.")
        flush_rx(bus)

        print(f"Changing board ID {board_id} to {new_id}...")
        bl_cmd(bus, board_id, BL_SET_ID, new_id, [0] * 4)
        result = bl_waitresp(bus, new_id, BL_SET_ID, timeout=1.0)
        if result is None:
            raise RuntimeError("Did not receive reply from board")
        if result > 0:
            raise RuntimeError(f"Bootloader command SET_ID returned error #{result}")
        print("Successfully changed board ID")
    finally:
        bus.shutdown()
