#!/usr/bin/env python3
"""Validate that an STM32F103CB app .bin looks bootloader-compatible."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys


DEFAULT_APP_START = 0x08003000
DEFAULT_FLASH_END = 0x08020000
DEFAULT_RAM_START = 0x20000000
DEFAULT_RAM_END = 0x20005000
PAGE_SIZE = 1024


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]
    size: int
    padded_size: int
    pages: int
    stack_pointer: int | None
    reset_vector: int | None


def validate_firmware(
    firmware: Path,
    app_start: int = DEFAULT_APP_START,
    flash_end: int = DEFAULT_FLASH_END,
    ram_start: int = DEFAULT_RAM_START,
    ram_end: int = DEFAULT_RAM_END,
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not firmware.exists():
        return ValidationResult(False, [f"File does not exist: {firmware}"], [], 0, 0, 0, None, None)
    if not firmware.is_file():
        return ValidationResult(False, [f"Path is not a file: {firmware}"], [], 0, 0, 0, None, None)

    data = firmware.read_bytes()
    size = len(data)
    max_size = flash_end - app_start
    padded_size = size
    if size % PAGE_SIZE:
        padded_size += PAGE_SIZE - (size % PAGE_SIZE)
    pages = padded_size // PAGE_SIZE if padded_size else 0

    if size == 0:
        errors.append("File is empty.")
        return ValidationResult(False, errors, warnings, size, padded_size, pages, None, None)
    if size < 8:
        errors.append("File is too short to contain a vector table.")
        return ValidationResult(False, errors, warnings, size, padded_size, pages, None, None)
    if size > max_size:
        errors.append(
            f"File is {size} bytes, but app flash space is only {max_size} bytes."
        )
    if padded_size > max_size:
        errors.append(
            f"File pads to {padded_size} bytes ({pages} pages), exceeding app flash space."
        )

    stack_pointer = int.from_bytes(data[0:4], "little")
    reset_vector = int.from_bytes(data[4:8], "little")
    reset_address = reset_vector & ~1

    if stack_pointer in (0x00000000, 0xFFFFFFFF):
        errors.append("Initial stack pointer is blank/invalid.")
    elif not (ram_start <= stack_pointer <= ram_end):
        errors.append(
            f"Initial stack pointer 0x{stack_pointer:08X} is outside RAM "
            f"0x{ram_start:08X}-0x{ram_end:08X}."
        )
    elif stack_pointer % 4 != 0:
        warnings.append(f"Initial stack pointer 0x{stack_pointer:08X} is not 4-byte aligned.")

    if reset_vector in (0x00000000, 0xFFFFFFFF):
        errors.append("Reset vector is blank/invalid.")
    else:
        if (reset_vector & 1) == 0:
            errors.append(
                f"Reset vector 0x{reset_vector:08X} does not have the Thumb bit set."
            )
        if not (app_start <= reset_address < flash_end):
            errors.append(
                f"Reset address 0x{reset_address:08X} is outside app flash "
                f"0x{app_start:08X}-0x{flash_end - 1:08X}."
            )
        elif reset_address < app_start + 0x100:
            warnings.append(
                f"Reset address 0x{reset_address:08X} is very close to app start; "
                "this can be valid, but double-check the linker script."
            )

    if reset_address < app_start and 0x08000000 <= reset_address < app_start:
        errors.append(
            "This looks like firmware linked for 0x08000000, not the bootloader "
            f"app start 0x{app_start:08X}."
        )

    return ValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        size=size,
        padded_size=padded_size,
        pages=pages,
        stack_pointer=stack_pointer,
        reset_vector=reset_vector,
    )


def parse_int(value: str) -> int:
    return int(value, 0)


def print_result(firmware: Path, result: ValidationResult):
    print(f"Firmware: {firmware}")
    print(f"Size:     {result.size} bytes")
    print(f"Padded:   {result.padded_size} bytes ({result.pages} page(s))")
    if result.stack_pointer is not None:
        print(f"SP:       0x{result.stack_pointer:08X}")
    if result.reset_vector is not None:
        print(f"Reset:    0x{result.reset_vector:08X}")

    for warning in result.warnings:
        print(f"WARNING:  {warning}")
    for error in result.errors:
        print(f"ERROR:    {error}")

    print("Result:   PASS" if result.ok else "Result:   FAIL")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate that an app .bin is safe to flash after the bootloader."
    )
    parser.add_argument("firmware", type=Path, help="Path to app .bin")
    parser.add_argument(
        "--app-start",
        type=parse_int,
        default=DEFAULT_APP_START,
        help="Application flash origin (default: 0x08003000)",
    )
    parser.add_argument(
        "--flash-end",
        type=parse_int,
        default=DEFAULT_FLASH_END,
        help="End address of MCU flash, exclusive (default: 0x08020000)",
    )
    parser.add_argument(
        "--ram-start",
        type=parse_int,
        default=DEFAULT_RAM_START,
        help="Start address of RAM (default: 0x20000000)",
    )
    parser.add_argument(
        "--ram-end",
        type=parse_int,
        default=DEFAULT_RAM_END,
        help="End/top address of RAM, inclusive for initial SP (default: 0x20005000)",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    result = validate_firmware(
        args.firmware,
        app_start=args.app_start,
        flash_end=args.flash_end,
        ram_start=args.ram_start,
        ram_end=args.ram_end,
    )
    print_result(args.firmware, result)
    if not result.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
