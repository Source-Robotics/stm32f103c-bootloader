# Pre-built bootloader binaries

This folder holds the latest pre-built bootloader artifacts. **You don't need to build from source** if you just want to install the bootloader on a chip — flash one of these files via ST-Link / J-Link / OpenOCD / STM32CubeProgrammer at address `0x08000000`.

## Files

| File | Use |
|---|---|
| `stm32f103c_bl.bin` | Raw binary. Flash at `0x08000000`. |
| `stm32f103c_bl.hex` | Intel HEX format (address embedded). Use with STM32CubeProgrammer GUI or `stm32flash`. |
| `stm32f103c_bl.elf` | ELF with debug symbols. Use for OpenOCD/GDB debugging, or `program <file> verify reset exit`. |

## Quick flash recipes

### STM32CubeProgrammer (GUI)

1. Connect ST-Link.
2. Open `stm32f103c_bl.hex` — the address is embedded; no need to enter `0x08000000` manually.
3. Click "Download".

### ST-Link Utility

1. Open `stm32f103c_bl.bin`.
2. Set start address to **`0x08000000`** (this is critical — the default is sometimes wrong).
3. Click "Program & Verify".

### OpenOCD CLI

```powershell
openocd -f interface/stlink.cfg -f target/stm32f1x.cfg `
        -c "program bin/stm32f103c_bl.elf verify reset exit"
```

### STM32CubeProgrammer CLI

```powershell
STM32_Programmer_CLI -c port=SWD -w bin/stm32f103c_bl.hex -v -rst
```

## Verify it's installed

After flashing, power-cycle the board. You should see:
- 3 quick LED flashes (register-level boot probe)
- Then the BL idle pattern (slow double-flash @ 1 Hz)

Then connect via the host tool:
```powershell
cd ../host_tools
python bl_flash.py --transport can --can-interface slcan --channel COM6 list
```

Should print `Detected board(s): Board ID 0`.

## How to update these binaries

If you modify the bootloader source and want to refresh the pre-built artifacts:

```powershell
cd firmware
make -j4
copy build\stm32f103c_bl.bin ..\bin\
copy build\stm32f103c_bl.elf ..\bin\
copy build\stm32f103c_bl.hex ..\bin\
```

Then commit the updated `bin/` files alongside your source changes.
