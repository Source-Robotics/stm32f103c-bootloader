#!/usr/bin/env python3
"""Repeated CAN firmware update soak test for one or more app nodes."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import can

from can_flash import flash
from can_fleet_update import parse_node_spec
from can_util import (
    APP_OUT_IN_PING,
    BL_BOARD_ID_MAX,
    CAN_INTERFACES,
    get_can_bus,
    host_app_can_id,
)
from validate_app_bin import print_result, validate_firmware


def log(message: str):
    print(message, flush=True)


def app_ping_once(bus, node_id: int, timeout: float) -> bool:
    ping_id = host_app_can_id(node_id, APP_OUT_IN_PING)
    ping_id_error = host_app_can_id(node_id, APP_OUT_IN_PING, 1)
    bus.send(
        can.Message(
            arbitration_id=ping_id,
            is_extended_id=False,
            is_remote_frame=True,
            dlc=0,
        ),
        1.0,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        msg = bus.recv(min(remaining, 0.05))
        if msg is None:
            continue
        if msg.arbitration_id in (ping_id, ping_id_error) and not msg.is_remote_frame:
            return True
    return False


def wait_for_app_node(node_id: int, channel, can_interface: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        bus = get_can_bus(channel, can_interface)
        try:
            if app_ping_once(bus, node_id, timeout=min(0.4, max(0.05, timeout))):
                return True
        finally:
            bus.shutdown()
        time.sleep(0.25)
    return False


def validate_nodes(nodes: list[int]):
    bad = [node for node in nodes if node < 0 or node > BL_BOARD_ID_MAX]
    if bad:
        raise RuntimeError(
            f"Bootloader board IDs must be 0-{BL_BOARD_ID_MAX}; got {bad}."
        )


def run(args):
    firmware = args.firmware
    result = validate_firmware(firmware)
    print_result(firmware, result)
    if not result.ok and not args.allow_invalid_bin:
        raise RuntimeError("Firmware validation failed; pass --allow-invalid-bin to override.")

    nodes = parse_node_spec(args.nodes)
    validate_nodes(nodes)

    pass_count = 0
    fail_count = 0
    start_time = time.monotonic()

    log("")
    log(
        f"Starting soak: {args.iterations} iteration(s), "
        f"node(s) {','.join(str(node) for node in nodes)}"
    )

    for iteration in range(1, args.iterations + 1):
        log("")
        log(f"=== Iteration {iteration}/{args.iterations} ===")
        for node_id in nodes:
            label = f"iteration {iteration}, node {node_id}"
            try:
                log(f"[{label}] Flashing...")
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

                if args.boot_delay > 0:
                    time.sleep(args.boot_delay)

                log(f"[{label}] Waiting for app ping...")
                if wait_for_app_node(
                    node_id,
                    args.channel,
                    args.can_interface,
                    args.app_ping_timeout,
                ):
                    log(f"[{label}] PASS")
                    pass_count += 1
                else:
                    log(f"[{label}] FAIL: app did not respond after flashing")
                    fail_count += 1
                    if args.stop_on_fail:
                        raise RuntimeError("Stopping after first failure.")
            except Exception as exc:
                log(f"[{label}] FAIL: {exc}")
                fail_count += 1
                if args.stop_on_fail:
                    raise

    elapsed = time.monotonic() - start_time
    log("")
    log(
        f"Soak complete in {elapsed:.1f}s: "
        f"{pass_count} PASS, {fail_count} FAIL, "
        f"{pass_count + fail_count} total flash attempt(s)."
    )
    if fail_count:
        sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Repeatedly flash selected CAN nodes and verify app ping after each update."
    )
    parser.add_argument("firmware", type=Path, help="Bootloader-compatible app .bin")
    parser.add_argument(
        "--nodes",
        default="0",
        help="Node IDs to soak, e.g. 0 or 0,2,3 (default: 0)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=20,
        help="Number of update cycles (default: 20)",
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
        "--boot-delay",
        type=float,
        default=2.0,
        help="Seconds to wait after flash before app ping (default: 2.0)",
    )
    parser.add_argument(
        "--app-ping-timeout",
        type=float,
        default=8.0,
        help="Seconds to wait for app ping after each flash (default: 8.0)",
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
        help="Continue even if validate_app_bin reports errors",
    )
    parser.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="Stop immediately after the first failed flash or app ping",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        print("\nCanceled.")
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
