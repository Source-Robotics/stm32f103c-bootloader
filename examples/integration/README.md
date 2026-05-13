# Integration template

These files are a working template for integrating the STM32F103C bootloader into an STM32 application built with PlatformIO + Arduino-STM32 framework. They came directly from a real product (the Spectral BLDC motor controller) and are kept as-is so you have a concrete reference rather than abstract pseudocode.

## Files

| File | Purpose |
|---|---|
| `bootloader_config.cpp` / `.h` | Implements `Bootloader_SetVectorTable`, `Bootloader_ResetIntoBootloader`, and `Bootloader_SyncBoardId`. Also declares the `bl_vars_t` struct that mirrors the bootloader's config-page layout. Copy these into your app's source tree. |
| `ldscript_bootloader.ld` | Linker script that places `FLASH` at `0x08003000` (length 116 KB) and otherwise mirrors a standard Arduino-STM32 / CMSIS layout. |

## How to use

See [`../../docs/INTEGRATION.md`](../../docs/INTEGRATION.md) for the full step-by-step guide.

In short:
1. Copy `bootloader_config.cpp/.h` into your `src/`.
2. Copy `ldscript_bootloader.ld` to your project root.
3. Add the relevant build flags / linker reference / upload offset to your `platformio.ini`.
4. Call `Bootloader_SetVectorTable()` as the first line of `setup()`.
5. Wire `Bootloader_ResetIntoBootloader()` into your CAN reset and UART reset commands.
6. Call `Bootloader_SyncBoardId()` whenever you persist a new CAN ID to your app's EEPROM.

## What's app-specific

These names appear in the template and are **examples** from the Spectral motor controller. Rename them to fit your application's conventions:

- `HOST_APP_CAN_ID_MAX = 15`: maximum CAN node ID your *app* uses (independent of `BOOTLOADER_BOARD_ID_MAX = 13`).
- `host_app_can_id_is_valid()` / `host_app_can_id_int_is_valid()`: validators for CAN IDs in your app's protocol.

The bootloader-specific names (`BOOTLOADER_BOARD_ID_MAX`, `BOOTLOADER_CONFIG_ADDRESS`, `BOOTLOADER_MAGIC_ADDRESS`, the `bl_vars_t` struct) are part of the binary contract with the bootloader and **must not be renamed**.
