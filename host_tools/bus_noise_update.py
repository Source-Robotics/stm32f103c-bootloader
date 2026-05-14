#!/usr/bin/env python3
"""Flash one node while injecting Spectral app telemetry traffic from others."""

from __future__ import annotations

import argparse
from itertools import cycle
from pathlib import Path
import sys
import time

import can

from can_flash import flash
from can_fleet_update import parse_node_spec
from can_util import BL_BOARD_ID_MAX, CAN_INTERFACES, host_app_can_id
from soak_fleet_update import wait_for_app_node
from validate_app_bin import print_result, validate_firmware


SPECTRAL_TELEMETRY_COMMANDS = {
    "temperature": 23,
    "voltage": 24,
    "errors": 26,
    "iq": 27,
    "encoder": 28,
}


class NoiseGenerator:
    def __init__(
        self,
        nodes: list[int],
        command_ids: list[int],
        frames_per_hook: int,
        min_gap_sec: float,
    ):
        self.items = cycle((node, command) for node in nodes for command in command_ids)
        self.frames_per_hook = frames_per_hook
        self.min_gap_sec = min_gap_sec
        self.last_send = 0.0
        self.sent = 0

    def __call__(self, bus):
        now = time.monotonic()
        if now - self.last_send < self.min_gap_sec:
            return

        for _ in range(self.frames_per_hook):
            node_id, command_id = next(self.items)
            bus.send(
                can.Message(
                    arbitration_id=host_app_can_id(node_id, command_id),
                    is_extended_id=False,
                    is_remote_frame=True,
                    dlc=0,
                ),
                1.0,
            )
            self.sent += 1
        self.last_send = now


def parse_noise_commands(value: str) -> list[int]:
    command_ids: list[int] = []
    for part in value.split(","):
        name = part.strip().lower()
        if not name:
            continue
        if name.isdigit():
            command_ids.append(int(name))
            continue
        if name not in SPECTRAL_TELEMETRY_COMMANDS:
            valid = ", ".join(sorted(SPECTRAL_TELEMETRY_COMMANDS))
            raise ValueError(f"Unknown noise command '{name}'. Use one of: {valid}")
        command_ids.append(SPECTRAL_TELEMETRY_COMMANDS[name])

    if not command_ids:
        raise ValueError("At least one noise command is required.")
    return command_ids


def run(args):
    result = validate_firmware(args.firmware)
    print_result(args.firmware, result)
    if not result.ok and not args.allow_invalid_bin:
        raise RuntimeError("Firmware validation failed; pass --allow-invalid-bin to override.")

    if args.target < 0 or args.target > BL_BOARD_ID_MAX:
        raise RuntimeError(f"Target bootloader board ID must be 0-{BL_BOARD_ID_MAX}.")

    noise_nodes = [node for node in parse_node_spec(args.noise_nodes) if node != args.target]
    if not noise_nodes:
        raise RuntimeError("No noise nodes left after removing the target node.")

    command_ids = parse_noise_commands(args.noise_commands)
    noise = NoiseGenerator(
        nodes=noise_nodes,
        command_ids=command_ids,
        frames_per_hook=args.noise_frames_per_hook,
        min_gap_sec=args.noise_min_gap,
    )

    print()
    print(
        f"Flashing target node {args.target} while requesting telemetry from "
        f"node(s) {','.join(str(node) for node in noise_nodes)}."
    )
    print(
        f"Noise commands: {','.join(str(command) for command in command_ids)}, "
        f"frames/hook={args.noise_frames_per_hook}, min_gap={args.noise_min_gap:.3f}s"
    )

    flash(
        board_id=args.target,
        app_node=args.target,
        filepath=str(args.firmware),
        channel=args.channel,
        can_interface=args.can_interface,
        erase_first=not args.no_erase_first,
        stream_enabled=not args.no_stream,
        stream_chunk_frames=args.stream_chunk_frames,
        noise_callback=noise,
    )

    print()
    print(f"Injected {noise.sent} telemetry request frame(s) during flashing.")
    if args.skip_app_ping:
        return

    print(f"Waiting for target app node {args.target} to respond after update...")
    if wait_for_app_node(
        args.target,
        args.channel,
        args.can_interface,
        args.app_ping_timeout,
    ):
        print("Target app ping: PASS")
    else:
        raise RuntimeError("Target app did not respond after noisy update.")


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Flash one CAN node while injecting harmless Spectral telemetry "
            "requests to other app nodes on the same bus."
        )
    )
    parser.add_argument("firmware", type=Path, help="Bootloader-compatible app .bin")
    parser.add_argument(
        "--target",
        type=int,
        required=True,
        help="Bootloader/app node ID to update",
    )
    parser.add_argument(
        "--noise-nodes",
        required=True,
        help="Other app node IDs to request telemetry from, e.g. 1,2,3",
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
        "--noise-commands",
        default="encoder,voltage,temperature,iq,errors",
        help=(
            "Comma-separated telemetry commands by name or numeric command ID "
            "(default: encoder,voltage,temperature,iq,errors)"
        ),
    )
    parser.add_argument(
        "--noise-frames-per-hook",
        type=int,
        default=1,
        help="Telemetry request frames to inject per transfer hook (default: 1)",
    )
    parser.add_argument(
        "--noise-min-gap",
        type=float,
        default=0.0,
        help="Minimum seconds between injected noise bursts (default: 0.0)",
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
        "--app-ping-timeout",
        type=float,
        default=8.0,
        help="Seconds to wait for target app ping after update (default: 8.0)",
    )
    parser.add_argument(
        "--skip-app-ping",
        action="store_true",
        help="Do not verify target app ping after flashing",
    )
    parser.add_argument(
        "--allow-invalid-bin",
        action="store_true",
        help="Continue even if validate_app_bin reports errors",
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
