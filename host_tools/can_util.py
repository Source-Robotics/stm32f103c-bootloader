import datetime
import os
from pathlib import Path
import time
from sys import platform

import can

PG_SIZE = 1024

# CAN command IDs match CAN_Bootloader-main.
BL_WBUF = 1
BL_WPAGE = 2
BL_WCRC = 3
BL_PING = 4
BL_SET_ID = 5
BL_ERASE_APP = 6
BL_STREAM_BEGIN = 7
BL_STREAM_STATUS = 8
APP_IN_RESET = 14
APP_OUT_IN_PING = 10

CANID_BL_CMD = 0x700
CANID_BL_RPL_BASE = 0x701
CAN_STREAM_FRAME_COUNT = 128
CAN_BITRATE = 1_000_000
BL_BOARD_ID_MAX = 13
COMMAND_GAP_SEC = 0.005
CAN_INTERFACES = ("auto", "slcan", "gs_usb", "socketcan")


def is_bl_response_id(can_id):
    return 0 <= can_id - CANID_BL_RPL_BASE <= BL_BOARD_ID_MAX


def canmsg(can_id, data):
    if len(data) > 8:
        raise ValueError("invalid data")
    return can.Message(arbitration_id=can_id, is_extended_id=False, data=data)


def stream_data_can_id(board_id, seq):
    return ((board_id & 0x0F) << 7) | (seq & 0x7F)


def host_app_can_id(node_id, command_id, error_bit=0):
    return ((node_id & 0xF) << 7) | ((command_id & 0x3F) << 1) | (error_bit & 0x1)


def send_app_reset(bus, node_id):
    reset_id = host_app_can_id(node_id, APP_IN_RESET)
    reset_id_error = host_app_can_id(node_id, APP_IN_RESET, 1)
    print(f"    [APP RESET] node={node_id} cmd={APP_IN_RESET} id=0x{reset_id:03X}")
    print(f"    [APP RESET] node={node_id} cmd={APP_IN_RESET} id=0x{reset_id_error:03X} error_bit=1")
    for _ in range(3):
        bus.send(canmsg(reset_id, b""), 1.0)
        bus.send(canmsg(reset_id_error, b""), 1.0)
        bus.send(
            can.Message(
                arbitration_id=reset_id,
                is_extended_id=False,
                is_remote_frame=True,
                dlc=0,
            ),
            1.0,
        )
        bus.send(
            can.Message(
                arbitration_id=reset_id_error,
                is_extended_id=False,
                is_remote_frame=True,
                dlc=0,
            ),
            1.0,
        )
        time.sleep(0.02)


def send_app_reset_many(bus, node_ids):
    for node_id in node_ids:
        send_app_reset(bus, node_id)
        time.sleep(0.01)


def app_ping(bus, node_id, timeout=0.5):
    ping_id = host_app_can_id(node_id, APP_OUT_IN_PING)
    ping_id_error = host_app_can_id(node_id, APP_OUT_IN_PING, 1)
    print(f"    [APP PING] node={node_id} cmd={APP_OUT_IN_PING} id=0x{ping_id:03X}")
    bus.send(
        can.Message(
            arbitration_id=ping_id,
            is_extended_id=False,
            is_remote_frame=True,
            dlc=0,
        ),
        1.0,
    )
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=timeout)
    while datetime.datetime.now() < deadline:
        remaining = max(0.0, (deadline - datetime.datetime.now()).total_seconds())
        msg = bus.recv(min(remaining, 0.05))
        if msg is None:
            continue
        if (
            msg.arbitration_id in (ping_id, ping_id_error)
            and not msg.is_remote_frame
        ):
            print(f"    [APP PING RX] id=0x{msg.arbitration_id:03X} dlc={msg.dlc}")
            return True
    return False


def bl_cmd(bus, board_id, cmd, par1=0, par2=None):
    if par2 is None:
        par2 = [0] * 4
    if isinstance(par2, int):
        par2 = par2.to_bytes(4, "big")
    if len(par2) != 4:
        raise ValueError("par2 must be 4 bytes")

    data = bytearray(8)
    data[0] = board_id & 0xFF
    data[1] = cmd & 0xFF
    data[2:4] = int(par1).to_bytes(2, "little")
    data[4:8] = bytes(par2)[::-1]
    bus.send(canmsg(CANID_BL_CMD, data), 1.0)


def flush_rx(bus, timeout_sec=0.02):
    while bus.recv(timeout_sec) is not None:
        pass


def bl_waitresp(bus, board_id, cmd, timeout=0.1, verbose=False, expected_par1=None):
    """Wait for a bootloader response.

    Reply layout: [board_id][cmd][error_code][par1_lo][par1_hi]
    If expected_par1 is given, only accept responses whose par1 matches -
    this prevents late responses from being mis-matched to subsequent commands.
    """
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=timeout)
    while datetime.datetime.now() < deadline:
        remaining = max(0.0, (deadline - datetime.datetime.now()).total_seconds())
        msg = bus.recv(min(remaining, 0.05))
        if msg is None:
            continue
        if verbose:
            print(
                f"    [BUS RX] id=0x{msg.arbitration_id:03X} "
                f"data={msg.data.hex()} dlc={msg.dlc} err={msg.is_error_frame}"
            )
        if not (
            is_bl_response_id(msg.arbitration_id)
            and msg.dlc >= 3
            and msg.data[0] == board_id
            and msg.data[1] == cmd
        ):
            continue
        if expected_par1 is not None and msg.dlc >= 5:
            par1 = msg.data[3] | (msg.data[4] << 8)
            if par1 != expected_par1:
                continue
        return msg.data[2]
    return None


def bl_cmd_response(
    bus,
    board_id,
    cmd,
    par1=0,
    par2=None,
    timeout_sec=0.1,
    retries=10,
    verbose=False,
):
    for _ in range(retries):
        time.sleep(COMMAND_GAP_SEC)
        bl_cmd(bus, board_id, cmd, par1, par2)
        result = bl_waitresp(bus, board_id, cmd, timeout_sec, verbose=verbose,
                             expected_par1=par1)
        if result is None:
            continue
        if result > 0:
            raise RuntimeError(f"Bootloader command {cmd} error #{result}")
        return result
    raise RuntimeError(f"Did not receive reply from board {board_id} for cmd {cmd}")


def bl_wait_for_connection(bus, board_id, timeout_sec=0.2, retries=40):
    for _ in range(retries):
        bl_cmd(bus, board_id, BL_PING, 0, [0] * 4)
        result = bl_waitresp(bus, board_id, BL_PING, timeout_sec)
        if result == 0:
            flush_rx(bus)
            return True
    return False


def bl_list_connected_boards(bus, timeout_sec=0.2, retries=75):
    board_ids = set()
    for _ in range(retries):
        bl_cmd(bus, 0, BL_PING, 0, [0] * 4)
        deadline = datetime.datetime.now() + datetime.timedelta(seconds=timeout_sec)
        while datetime.datetime.now() < deadline:
            remaining = max(0.0, (deadline - datetime.datetime.now()).total_seconds())
            msg = bus.recv(min(remaining, 0.05))
            if msg is None:
                continue
            if (
                is_bl_response_id(msg.arbitration_id)
                and msg.dlc >= 3
                and msg.data[1] == BL_PING
                and msg.data[2] == 0
            ):
                board_ids.add(msg.data[0])
    return board_ids


def _normalize_gs_usb_channel(channel):
    if channel is None:
        return 0
    if isinstance(channel, str) and channel.isdigit():
        return int(channel)
    return channel


def _prepare_gs_usb_backend():
    """Help PyUSB find libusb-1.0.dll when installed from pip packages."""
    if platform != "win32":
        return

    dll_paths = []

    try:
        import libusb_package
        lib_path = libusb_package.get_library_path()
        if lib_path:
            dll_paths.append(Path(lib_path).resolve())
    except ImportError:
        pass

    try:
        import libusb
    except ImportError:
        libusb = None

    if libusb is not None:
        libusb_root = Path(libusb.__file__).resolve().parent
        dll_paths.extend(libusb_root.rglob("libusb-1.0.dll"))

    for dll in dll_paths:
        dll_dir = str(dll.parent)
        os.add_dll_directory(dll_dir)
        os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
        return


def get_can_bus(channel=None, can_interface="auto"):
    if can_interface not in CAN_INTERFACES:
        raise ValueError(f"Unsupported CAN interface: {can_interface}")

    if can_interface == "auto":
        if channel is None:
            if platform == "win32":
                can_interface = "gs_usb"
                channel = 0
            elif platform in ("linux", "linux2", "darwin"):
                can_interface = "socketcan"
                channel = "can0"
            else:
                raise ValueError("Channel not specified and OS not recognized")
        elif isinstance(channel, str) and ("COM" in channel.upper() or "/dev" in channel):
            can_interface = "slcan"
        elif isinstance(channel, str) and channel.isdigit():
            can_interface = "gs_usb"
        else:
            can_interface = "socketcan"

    if can_interface == "slcan":
        if channel is None:
            raise RuntimeError("Specify --channel with your slcan COM port, e.g. COM20")
        return can.interface.Bus(
            bustype="slcan",
            channel=channel,
            bitrate=CAN_BITRATE,
            ttyBaudrate=921600,
        )

    if can_interface == "gs_usb":
        _prepare_gs_usb_backend()
        try:
            return can.interface.Bus(
                interface="gs_usb",
                channel=_normalize_gs_usb_channel(channel),
                bitrate=CAN_BITRATE,
            )
        except Exception as exc:
            if exc.__class__.__name__ == "NoBackendError":
                raise RuntimeError(
                    "PyUSB cannot find a libusb backend. Install it with:\n"
                    "  py -m pip install libusb-package\n"
                    "Then reopen PowerShell and retry. If the adapter is still "
                    "not found, use Zadig to assign WinUSB/libusbK to the "
                    "candleLight/CANable device."
                ) from exc
            raise

    if channel is None:
        channel = "can0"
    return can.interface.Bus(interface="socketcan", channel=channel, bitrate=CAN_BITRATE)
