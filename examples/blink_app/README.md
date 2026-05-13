# blink_app — minimal test application

A tiny app linked at `0x08003000` that does nothing but blink the LED. Useful for confirming a fresh bootloader install works end-to-end, before you bring up your full application code.

## Files

- `blink_app.c` — main source (a few dozen lines).
- `blink_app.ld` — linker script placing FLASH at `0x08003000`.
- `startup.s` — minimal reset handler + vector table.
- `Makefile` — `make` builds `blink_app.bin`.
- `blink_app.bin`, `blink_app.elf` — pre-built artifacts (handy for a quick test without building).

## Build

```powershell
cd examples/blink_app
make
```

Requires `arm-none-eabi-gcc`.

## Flash via the bootloader

```powershell
cd ../../host_tools
python bl_flash.py --transport uart --port COM7 --baudrate 256000 \
                   flash ../examples/blink_app/blink_app.bin --board 0 --erase-first
```

Or via CAN — same as for any other app.

After the bootloader hands off, the LED on `PA7`/`PB13` will blink in whatever pattern `blink_app.c` defines. If the LED blinks, your bootloader install and host-tools setup are working.
