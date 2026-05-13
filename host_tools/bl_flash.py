#!/usr/bin/env python3
"""
bl_flash.py — Unified CLI for flashing host boards.

Usage:
  python bl_flash.py list   --transport can [--channel CHANNEL]
  python bl_flash.py flash  firmware.bin --transport can  --board ID [--channel CHANNEL]
  python bl_flash.py flash  firmware.bin --transport uart --board ID --port PORT
  python bl_flash.py set-id --transport can  --board ID --new-id NEW_ID [--channel CHANNEL]
  python bl_flash.py set-id --transport uart --board ID --new-id NEW_ID --port PORT
"""

import argparse
import sys


def cmd_list(args):
    if args.transport == "can":
        from can_flash import list_connected_boards
        list_connected_boards(channel=args.channel, can_interface=args.can_interface)
    elif args.transport == "uart":
        from uart_flash import list_connected_boards
        if not args.port:
            print("--port is required for UART transport.")
            sys.exit(1)
        list_connected_boards(port=args.port, baudrate=args.baudrate)
    else:
        print(f"Unknown transport: {args.transport}")
        sys.exit(1)


def cmd_flash(args):
    if args.transport == "can":
        from can_flash import flash
        flash(board_id=args.board, filepath=args.filepath, channel=args.channel,
              wbuf_gap_sec=args.wbuf_gap,
              page_drain_gap_sec=args.page_drain_gap,
              page_gap_sec=args.page_gap,
              wbuf_ack_stride=args.wbuf_ack_stride,
              erase_first=args.erase_first,
              stream_enabled=not args.no_stream,
              stream_chunk_frames=args.stream_chunk_frames,
              app_node=args.app_node,
              can_interface=args.can_interface)
    elif args.transport == "uart":
        from uart_flash import flash
        flash(board_id=args.board, filepath=args.filepath, port=args.port,
              baudrate=args.baudrate,
              erase_first=args.erase_first,
              stream_enabled=not args.no_stream,
              stream_chunk_frames=args.stream_chunk_frames)
    else:
        print(f"Unknown transport: {args.transport}")
        sys.exit(1)


def cmd_set_id(args):
    if args.transport == "can":
        from can_flash import change_id
        change_id(board_id=args.board, new_id=args.new_id, channel=args.channel,
                  can_interface=args.can_interface)
    elif args.transport == "uart":
        from uart_flash import change_id
        change_id(board_id=args.board, new_id=args.new_id, port=args.port,
                  baudrate=args.baudrate)
    else:
        print(f"Unknown transport: {args.transport}")
        sys.exit(1)


def cmd_app_reset(args):
    if args.transport == "can":
        if args.node is None:
            print("--node is required for CAN app-reset.")
            sys.exit(1)
        from can_flash import reset_app, reset_app_and_wait
        if args.wait:
            if not reset_app_and_wait(node_id=args.node, board_id=args.board,
                                      channel=args.channel,
                                      can_interface=args.can_interface):
                sys.exit(1)
        else:
            reset_app(node_id=args.node, channel=args.channel,
                      can_interface=args.can_interface)
    elif args.transport == "uart":
        if not args.port:
            print("--port is required for UART transport.")
            sys.exit(1)
        from uart_flash import reset_app, reset_app_and_wait
        if args.wait:
            board_id = args.board if args.board is not None else 0
            if not reset_app_and_wait(board_id=board_id, port=args.port, baudrate=args.baudrate):
                sys.exit(1)
        else:
            reset_app(port=args.port, baudrate=args.baudrate)
    else:
        print(f"Unknown transport: {args.transport}")
        sys.exit(1)


def cmd_app_ping(args):
    if args.transport != "can":
        print("app-ping is only available for CAN transport.")
        sys.exit(1)
    from can_flash import ping_app, scan_app_nodes
    if args.node is None:
        scan_app_nodes(channel=args.channel, can_interface=args.can_interface)
        return
    if not ping_app(node_id=args.node, channel=args.channel,
                    can_interface=args.can_interface):
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="host bootloader flash tool (CAN + UART)")
    parser.add_argument("--transport", choices=["can", "uart"], required=True,
                        help="Transport layer: 'can' or 'uart'")
    parser.add_argument("--channel", default=None,
                        help="CAN channel: COMx for slcan, can0 for socketcan, 0 for gs_usb")
    parser.add_argument("--can-interface", choices=["auto", "slcan", "gs_usb", "socketcan"],
                        default="auto",
                        help="python-can backend for CAN transport (default: auto)")
    parser.add_argument("--port", default=None,
                        help="Serial port for UART transport (e.g. COM3 or /dev/ttyUSB0)")
    parser.add_argument("--baudrate", type=int, default=256000,
                        help="UART baud rate (default: 256000)")

    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="List boards responding to ping on CAN")

    # flash
    p_flash = sub.add_parser("flash", help="Flash a .bin firmware to a board")
    p_flash.add_argument("filepath", help="Path to the .bin file")
    p_flash.add_argument("--board", "-b", type=int, required=True,
                         help="Board ID to flash")
    p_flash.add_argument("--app-node", type=int, default=None,
                         help="Running app CAN node to reset before flashing (default: --board)")
    p_flash.add_argument("--wbuf-gap", type=float, default=None,
                         help="CAN WBUF send gap in seconds")
    p_flash.add_argument("--page-drain-gap", type=float, default=None,
                         help="Pause after WBUF stream before WRITE_PAGE, seconds")
    p_flash.add_argument("--page-gap", type=float, default=None,
                         help="Pause after each WRITE_PAGE ACK, seconds")
    p_flash.add_argument("--wbuf-ack-stride", type=int, default=None,
                         help="Wait for sparse WBUF ACK every N words; 0 disables")
    p_flash.add_argument("--erase-first", action="store_true",
                         help="Erase application flash area before flashing (CAN only)")
    p_flash.add_argument("--no-stream", action="store_true",
                         help="Disable CAN page streaming and use WBUF fallback")
    p_flash.add_argument("--stream-chunk-frames", type=int, default=16,
                         help="8-byte stream frames per status check (default: 16)")

    # set-id
    p_setid = sub.add_parser("set-id", help="Change a board's ID")
    p_setid.add_argument("--board", "-b", type=int, required=True,
                         help="Current board ID")
    p_setid.add_argument("--new-id", "-i", type=int, required=True,
                         help="New board ID (0-13; 14 and 15 are reserved)")

    # app-reset
    p_app_reset = sub.add_parser("app-reset", help="Send host app reset command")
    p_app_reset.add_argument("--node", "-n", type=int, default=None,
                             help="host app node ID to reset (CAN only)")
    p_app_reset.add_argument("--board", "-b", type=int, default=None,
                             help="Bootloader board ID to wait for; CAN defaults to --node, UART defaults to 0")
    p_app_reset.add_argument("--wait", action="store_true",
                             help="Wait for bootloader reply after sending app reset")

    # app-ping
    p_app_ping = sub.add_parser("app-ping", help="Ping running host app over CAN")
    p_app_ping.add_argument("--node", "-n", type=int, default=None,
                            help="host app node ID to ping; omit to scan 0-15")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "flash":
        cmd_flash(args)
    elif args.command == "set-id":
        cmd_set_id(args)
    elif args.command == "app-reset":
        cmd_app_reset(args)
    elif args.command == "app-ping":
        cmd_app_ping(args)


if __name__ == "__main__":
    main()
