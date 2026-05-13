# Integrating the STM32F103C Bootloader into your application

This guide explains the minimum changes required to make an existing STM32F103CB application bootloader-aware: linker placement, vector-table relocation, and the optional but recommended reset/sync hooks.

The files in [`../examples/integration/`](../examples/integration/) are a working template you can copy and adapt.

## 1. Move the application to `0x08003000`

The bootloader occupies `0x08000000 - 0x080022FF` and stores its config page at `0x08002C00`. The application gets everything from `0x08003000` up to the end of flash.

For a 128 KB STM32F103CB, that's **116 KB / 118784 bytes** of application space.

### Linker script (`ldscript_bootloader.ld`)

```ld
MEMORY
{
  RAM   (xrw) : ORIGIN = 0x20000000, LENGTH = 20K
  FLASH (rx)  : ORIGIN = 0x08003000, LENGTH = 118784
}
```

(Rest of the script unchanged — see the template file for a complete example.)

### Build-system hooks

#### Arduino / PlatformIO

```ini
[env:genericSTM32F103CB]
build_flags =
    -DVECT_TAB_OFFSET=0x3000
board_build.ldscript = ldscript_bootloader.ld
board_upload.offset_address = 0x08003000
board_upload.maximum_size = 118784
```

The `VECT_TAB_OFFSET` macro causes the Arduino STM32 core's `SystemInit()` to set `SCB->VTOR = 0x08003000` automatically.

#### CubeMX / bare Makefile

In your linker script, set `FLASH (rx) : ORIGIN = 0x08003000, LENGTH = 118784`. Then either:

- Define `VECT_TAB_OFFSET=0x3000` and let HAL's `SystemInit()` handle VTOR (CMSIS-style), or
- Manually set `SCB->VTOR = 0x08003000UL;` as the very first thing in `main()` before initialising any peripheral.

## 2. Add the reset and sync handlers

Copy [`../examples/integration/bootloader_config.cpp`](../examples/integration/bootloader_config.cpp) and [`../examples/integration/bootloader_config.h`](../examples/integration/bootloader_config.h) into your `src/`. They provide three functions:

### `Bootloader_SetVectorTable()`

Explicitly sets `SCB->VTOR = 0x08003000`. **Optional** — if you set `VECT_TAB_OFFSET=0x3000` as a build flag, `SystemInit()` already does this before `main()`. The function is provided as belt-and-suspenders.

Call it as the first thing in your `setup()` / `main()`:

```cpp
void setup() {
    Bootloader_SetVectorTable();
    // ... rest of your setup
}
```

### `Bootloader_ResetIntoBootloader()`

Cleanly drops your application back into the bootloader:

```cpp
void Bootloader_ResetIntoBootloader(void)
{
    volatile uint32_t *magic = (volatile uint32_t *)0x20001000;
    __disable_irq();
    *magic = 0;           // ensure bootloader doesn't fast-path past itself
    __DSB();
    __ISB();
    NVIC_SystemReset();
}
```

Wire this into whatever reset triggers you want:

- **CAN reset command**: pick a free command ID in your application protocol (the Spectral reference uses `IN_RESET = 14`). When you receive that command:
  ```cpp
  case IN_RESET:
      Bootloader_ResetIntoBootloader();
      break;
  ```
- **UART reset command**: pick a text command (Spectral uses `#Reset\n`). When you receive it:
  ```cpp
  else if (strcmp(command, "Reset") == 0) {
      Bootloader_ResetIntoBootloader();
  }
  ```

The host tool's `flash` command will automatically send these reset commands when it sees no bootloader reply.

### `Bootloader_SyncBoardId(uint8_t new_id)`

When the user permanently saves their CAN board ID via your app's "save config" flow, also push that ID into the bootloader's config page so the BL responds on the same ID on the next boot:

```cpp
void Write_config() {
    writeInt(CAN_ID_EEPROM, controller.CAN_ID);
    (void)Bootloader_SyncBoardId((uint8_t)controller.CAN_ID);
    // ... rest of your save-config logic
}
```

The function reads the existing BL config page, modifies only `board.id`, erases the page, and writes it back atomically. It disables IRQ for about 30 ms during the flash erase (the only place the BL touches its own config from app code).

Returns `false` if the ID is out of range (>13) or if flash write fails — silent failure is acceptable since the app keeps the new ID in EEPROM and the BL just stays on its previous ID until the next sync.

## 3. Match the bootloader's `bl_vars_t` layout

The bootloader and the application both read/write the same 20 (or 24, including padding) byte struct at `0x08002C00`:

```cpp
struct bl_app_vars_t {
    uint32_t page_count;     // number of pages in the current app
    uint32_t crc;            // CRC32 of the current app
};

struct bl_board_vars_t {
    uint64_t bl_build_version;  // bootloader build timestamp
    uint8_t  id;                // board CAN ID (0-13)
    uint8_t  padding[3];
};

struct bl_vars_t {
    bl_app_vars_t   app;
    bl_board_vars_t board;
};

static_assert(sizeof(bl_vars_t) == 24,
              "bl_vars_t layout must match the bootloader's struct exactly");
```

The `static_assert` catches accidental layout drift at compile time. Both the bootloader's `main.h` and your app's copy of `bootloader_config.h` should assert the same size.

## 4. Verify the binary is correctly linked

After building:

```powershell
arm-none-eabi-objdump -h .pio\build\genericSTM32F103CB\firmware.elf | findstr ".text"
```

You should see something like:

```
  1 .text         0001430c  08003110  08003110  00003110  2**3
```

The VMA and LMA both starting with `0800 3xxx` confirms the binary is for `0x08003000`, not `0x08000000`. If you accidentally upload a `0x08000000`-linked binary via `pio run -t upload`, the bootloader gets overwritten and the board needs a JTAG reflash to recover.

## 5. Flashing workflow once integrated

```powershell
# Build your app
pio run

# Flash via the bootloader (CAN or UART)
cd <stm32f103c-bootloader>/host_tools
python bl_flash.py --transport can --can-interface slcan --channel COM6 \
                   flash <path-to-your-firmware.bin> --board 0 --erase-first
```

If your app is currently running, the host tool will send the reset command you wired up in step 2, the board will drop into the bootloader, flash, then boot back into the new app.

## Notes / gotchas

- **`pio run -t upload` after the bootloader is installed**: PlatformIO writes the new app correctly to `0x08003000+`, but the bootloader's stored `app.crc` still reflects the *previous* app and won't match. Result: the bootloader refuses to boot the app (LED stays in idle pattern). **Recovery**: re-run the flash via `bl_flash.py` (the bootloader's `WRITE_CRC` step at the end updates the stored CRC).

  Practically: once the bootloader is installed, use `bl_flash.py` for every app update. Reserve `pio run -t upload` for the very first install on a chip that doesn't yet have a bootloader, or for reflashing the bootloader itself (via a separate build that links at `0x08000000`).

- **Board ID `14`/`15`** are accepted by the application (the Spectral reference allows the full 0-15 range) but the bootloader only supports 0-13. If the app saves CAN ID 14 or 15, `Bootloader_SyncBoardId` returns `false` and the BL keeps its previous ID. Document this constraint in your app if you allow IDs > 13.

- **Stack pointer and reset vector sanity**: the bootloader validates the app's vector table before jumping. The SP (word 0 of the app) must be in `0x20000000..0x20005000` and the reset vector (word 1) must be in `0x08003001..0x0801FFFF`. Standard linker output meets these constraints; if you ever see fast-path-boot failing, dump the first 8 bytes of your `.bin` with `xxd -l 8` and verify.
