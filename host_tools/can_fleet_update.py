#!/usr/bin/env python3
"""
Scan Spectral BLDC CAN app nodes, monitor live telemetry, then flash selected
nodes through the STM32F103C bootloader.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import can

from can_flash import flash
from can_util import BL_BOARD_ID_MAX, CAN_INTERFACES, get_can_bus
from validate_app_bin import print_result, validate_firmware


DEFAULT_SPECTRAL_API_PATH = Path.home() / "Desktop" / "Spectral-BLDC-Python-main"
APP_NODE_ID_MAX = 15


@dataclass
class NodeState:
    node_id: int
    last_seen: float = 0.0
    ping: bool = False
    position: int | None = None
    speed: int | None = None
    current: int | None = None
    voltage: int | None = None
    temperature: int | None = None
    error: int | None = None
    calibrated: int | None = None
    activated: int | None = None
    hardware_version: int | None = None
    software_version: int | None = None
    serial_number: int | None = None
    commands_seen: set[int] = field(default_factory=set)


class SpectralBusAdapter:
    """Tiny adapter matching the Spectral API's communication object shape."""

    def __init__(self, bus, can_utils):
        self.bus = bus
        self.can_utils = can_utils

    def send_can_message(self, message_id, data=b"", remote_frame=False):
        payload = bytes(data or b"")
        message = can.Message(
            arbitration_id=message_id,
            data=payload,
            is_remote_frame=remote_frame,
            is_extended_id=False,
            dlc=len(payload),
        )
        self.bus.send(message, 1.0)

    def receive_can_messages(self, timeout=None):
        message = self.bus.recv(timeout=timeout)
        if message is None:
            return None, None

        node_id, command_id, error_bit = self.can_utils.extract_from_can_id(
            message.arbitration_id
        )
        unpacked = SimpleNamespace(
            node_id=node_id,
            command_id=command_id,
            error_bit=error_bit,
        )
        return message, unpacked


def import_spectral_api(path: Path | None):
    if path is not None and path.exists():
        sys.path.insert(0, str(path))

    try:
        import Spectral_BLDC as Spectral  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Could not import Spectral_BLDC. Install it with "
            "`py -m pip install Spectral-BLDC` or pass "
            "`--spectral-api C:\\path\\to\\Spectral-BLDC-Python-main`."
        ) from exc

    return Spectral


def parse_node_spec(value: str) -> list[int]:
    nodes: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError(f"Bad node range: {part}")
            nodes.update(range(start, end + 1))
        else:
            nodes.add(int(part))

    bad = [node for node in nodes if node < 0 or node > APP_NODE_ID_MAX]
    if bad:
        raise ValueError(f"App node IDs must be 0-{APP_NODE_ID_MAX}: {bad}")
    return sorted(nodes)


def value_or_dash(value):
    return "-" if value is None else str(value)


def update_state_from_motor(state: NodeState, motor, command_id: int):
    state.last_seen = time.time()
    state.commands_seen.add(command_id)

    if motor.ping is not None:
        state.ping = True
    if motor.position is not None:
        state.position = motor.position
    if motor.speed is not None:
        state.speed = motor.speed
    if motor.current is not None:
        state.current = motor.current
    if motor.voltage is not None:
        state.voltage = motor.voltage
    if motor.temperature is not None:
        state.temperature = motor.temperature
    if motor.error is not None:
        state.error = motor.error
    if motor.calibrated is not None:
        state.calibrated = motor.calibrated
    if motor.activated is not None:
        state.activated = motor.activated
    if motor.HARDWARE_VERSION is not None:
        state.hardware_version = motor.HARDWARE_VERSION
    if motor.SOFTWARE_VERSION is not None:
        state.software_version = motor.SOFTWARE_VERSION
    if motor.SERIAL_NUMBER is not None:
        state.serial_number = motor.SERIAL_NUMBER


def receive_app_frames(adapter, motors, states, timeout_sec: float):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        message, unpacked = adapter.receive_can_messages(timeout=min(remaining, 0.05))
        if message is None or unpacked is None or message.is_remote_frame:
            continue
        if unpacked.node_id not in motors:
            continue

        motor = motors[unpacked.node_id]
        motor.UnpackData(message, unpacked)
        update_state_from_motor(
            states[unpacked.node_id],
            motor,
            unpacked.command_id,
        )


def request_node_snapshot(motor, include_identity=False):
    motor.Send_Respond_Encoder_data()
    time.sleep(0.004)
    motor.Send_Respond_Voltage()
    time.sleep(0.004)
    motor.Send_Respond_Temperature()
    time.sleep(0.004)
    motor.Send_Respond_Iq_data()
    time.sleep(0.004)
    motor.Send_Respond_State_of_Errors()
    time.sleep(0.004)
    if include_identity:
        motor.Send_Respond_Device_Info()
        time.sleep(0.004)


def scan_nodes(Spectral, adapter, nodes, scan_timeout):
    motors = {
        node_id: Spectral.SpectralCAN(node_id=node_id, communication=adapter)
        for node_id in nodes
    }
    states = {node_id: NodeState(node_id=node_id) for node_id in nodes}

    node_text = ",".join(str(node_id) for node_id in nodes)
    print(f"Scanning app nodes: {node_text}")
    per_node_timeout = min(0.08, max(0.01, scan_timeout))
    for motor in motors.values():
        motor.Send_Respond_Ping()
        time.sleep(0.006)
        request_node_snapshot(motor, include_identity=True)
        receive_app_frames(adapter, motors, states, per_node_timeout)

    receive_app_frames(adapter, motors, states, scan_timeout)
    found = {
        node_id: state
        for node_id, state in states.items()
        if state.last_seen > 0
    }
    return motors, found


def print_table(states: dict[int, NodeState]):
    if not states:
        print("No app nodes detected.")
        return

    print(
        "Node  Age   Pos        Speed      Current  Voltage  Temp  Err  "
        "Act  Cal  SW  Serial"
    )
    print("-" * 84)
    now = time.time()
    for node_id in sorted(states):
        state = states[node_id]
        age = now - state.last_seen if state.last_seen else 0.0
        print(
            f"{node_id:>4}  "
            f"{age:>4.1f}s  "
            f"{value_or_dash(state.position):>9}  "
            f"{value_or_dash(state.speed):>9}  "
            f"{value_or_dash(state.current):>7}  "
            f"{value_or_dash(state.voltage):>7}  "
            f"{value_or_dash(state.temperature):>4}  "
            f"{value_or_dash(state.error):>3}  "
            f"{value_or_dash(state.activated):>3}  "
            f"{value_or_dash(state.calibrated):>3}  "
            f"{value_or_dash(state.software_version):>2}  "
            f"{value_or_dash(state.serial_number):>6}"
        )


def monitor_nodes(motors, states, interval_sec, duration_sec):
    if not states:
        return

    print()
    print(
        f"Monitoring {len(states)} detected node(s) for {duration_sec:.1f}s "
        "before firmware selection..."
    )
    end_time = time.monotonic() + duration_sec
    while time.monotonic() < end_time:
        loop_start = time.monotonic()
        for node_id in sorted(states):
            request_node_snapshot(motors[node_id])

        receive_app_frames(
            next(iter(motors.values())).communication,
            motors,
            states,
            timeout_sec=max(0.05, interval_sec * 0.5),
        )
        print()
        print_table(states)

        elapsed = time.monotonic() - loop_start
        if elapsed < interval_sec:
            time.sleep(interval_sec - elapsed)


def prompt_firmware_path(initial: str | None) -> Path | None:
    value = initial
    while not value:
        value = input("Firmware .bin path to flash (or q to quit): ").strip()
        if value.lower() in ("q", "quit", "exit"):
            return None

    firmware = Path(value.strip('"')).expanduser()
    if not firmware.exists():
        raise RuntimeError(f"Firmware file does not exist: {firmware}")
    if not firmware.is_file():
        raise RuntimeError(f"Firmware path is not a file: {firmware}")
    return firmware


def prompt_selection(states: dict[int, NodeState]) -> list[int]:
    detected = sorted(states)
    if not detected:
        return []

    print()
    print(f"Detected app nodes: {', '.join(str(node) for node in detected)}")
    while True:
        raw = input("Update which node(s)? Enter all, a list like 0,2,3, or q: ")
        raw = raw.strip().lower()
        if raw in ("q", "quit", "exit"):
            return []
        if raw in ("all", "a", "*"):
            return detected

        try:
            selected = parse_node_spec(raw)
        except ValueError as exc:
            print(exc)
            continue

        missing = [node for node in selected if node not in states]
        if missing:
            print(f"Not detected in this scan: {missing}")
            continue
        return selected


def filter_bootloader_supported_nodes(nodes: list[int]) -> list[int]:
    unsupported = [node for node in nodes if node > BL_BOARD_ID_MAX]
    if unsupported:
        print(
            "Skipping node(s) "
            f"{unsupported}: this bootloader supports board IDs 0-{BL_BOARD_ID_MAX}."
        )
    return [node for node in nodes if 0 <= node <= BL_BOARD_ID_MAX]


def confirm_flash(nodes: list[int], firmware: Path) -> bool:
    print()
    print(f"Firmware: {firmware}")
    print(f"Nodes to update: {', '.join(str(node) for node in nodes)}")
    response = input("Reset and flash these node(s)? Type yes to continue: ")
    return response.strip().lower() == "yes"


def run(args):
    Spectral = import_spectral_api(args.spectral_api)
    nodes = parse_node_spec(args.nodes)

    bus = get_can_bus(args.channel, args.can_interface)
    adapter = SpectralBusAdapter(bus, Spectral.CAN_utils)
    try:
        motors, states = scan_nodes(Spectral, adapter, nodes, args.scan_timeout)
        print()
        print_table(states)
        monitor_nodes(motors, states, args.monitor_interval, args.monitor_seconds)
    finally:
        bus.shutdown()

    selected = prompt_selection(states)
    if not selected:
        print("No nodes selected.")
        return

    selected = filter_bootloader_supported_nodes(selected)
    if not selected:
        print("No selected nodes can be flashed by this bootloader.")
        return

    firmware = prompt_firmware_path(args.firmware)
    if firmware is None:
        print("No firmware selected.")
        return

    result = validate_firmware(firmware)
    print()
    print_result(firmware, result)
    if not result.ok and not args.allow_invalid_bin:
        print("Firmware validation failed. Use --allow-invalid-bin to override.")
        return

    if not confirm_flash(selected, firmware):
        print("Firmware update canceled.")
        return

    for index, node_id in enumerate(selected, start=1):
        print()
        print(f"[{index}/{len(selected)}] Updating node {node_id}...")
        flash(
            board_id=node_id,
            app_node=node_id,
            filepath=str(firmware),
            channel=args.channel,
            can_interface=args.can_interface,
            erase_first=not args.no_erase_first,
            stream_enabled=not args.no_stream,
            stream_chunk_frames=args.stream_chunk_frames,
        )

    print()
    print("Selected firmware updates complete.")


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Scan Spectral BLDC app nodes, monitor telemetry, then update "
            "selected nodes through the STM32F103C bootloader."
        )
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="CAN channel: COMx for slcan, can0 for socketcan, 0 for gs_usb",
    )
    parser.add_argument(
        "--can-interface",
        choices=CAN_INTERFACES,
        default="auto",
        help="python-can backend for CAN transport (default: auto)",
    )
    parser.add_argument(
        "--firmware",
        default=None,
        help="Path to the bootloader-compatible app .bin file",
    )
    parser.add_argument(
        "--nodes",
        default="0-15",
        help="App node IDs to scan, e.g. 0-15 or 0,2,3 (default: 0-15)",
    )
    parser.add_argument(
        "--spectral-api",
        type=Path,
        default=DEFAULT_SPECTRAL_API_PATH,
        help=(
            "Path to Spectral-BLDC-Python-main if Spectral_BLDC is not "
            f"installed (default: {DEFAULT_SPECTRAL_API_PATH})"
        ),
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=1.0,
        help="Seconds to collect replies during the scan (default: 1.0)",
    )
    parser.add_argument(
        "--monitor-seconds",
        type=float,
        default=10.0,
        help="Seconds to monitor telemetry before prompting (default: 10)",
    )
    parser.add_argument(
        "--monitor-interval",
        type=float,
        default=1.0,
        help="Telemetry table refresh interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--no-erase-first",
        action="store_true",
        help="Do not erase the app flash area before writing",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable CAN page streaming and use WBUF fallback",
    )
    parser.add_argument(
        "--stream-chunk-frames",
        type=int,
        default=16,
        help="8-byte stream frames per status check (default: 16)",
    )
    parser.add_argument(
        "--allow-invalid-bin",
        action="store_true",
        help="Allow flashing even if validate_app_bin reports errors",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        print("\nCanceled.")
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
