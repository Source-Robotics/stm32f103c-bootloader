# Bootloader Test Results

This file records known-good validation runs for the STM32F103C bootloader and
host tools.

## 2026-05-14 - CAN SLCAN Update Validation

### Setup

| Item | Value |
|---|---|
| Host OS | Windows |
| CAN adapter | CANvas adapter running SLCAN |
| CAN channel | `COM6` |
| CAN bitrate | 1 Mbit/s |
| Bootloader transport | CAN |
| Bootloader app start | `0x08003000` |
| Test firmware | `C:\Users\Petar\Desktop\BLDC.bin` |
| Firmware size | `90936` bytes |
| Firmware padded size | `91136` bytes / `89` flash pages |
| Initial stack pointer | `0x20005000` |
| Reset vector | `0x08004241` |

Firmware validation command:

```powershell
cd C:\Users\Petar\Desktop\stm32f103c-bootloader\host_tools
py .\validate_app_bin.py C:\Users\Petar\Desktop\BLDC.bin
```

Observed result:

```text
Firmware: C:\Users\Petar\Desktop\BLDC.bin
Size:     90936 bytes
Padded:   91136 bytes (89 page(s))
SP:       0x20005000
Reset:    0x08004241
Result:   PASS
```

### Repeated CAN Update Soak

Command:

```powershell
py .\soak_fleet_update.py C:\Users\Petar\Desktop\BLDC.bin `
  --can-interface slcan --channel COM6 `
  --nodes 0 --iterations 20
```

Observed result:

```text
Verifying... OK
Flash complete in 26.2s! Board will reboot into the new firmware.
[iteration 20, node 0] Waiting for app ping...
[iteration 20, node 0] PASS

Soak complete in 609.8s: 20 PASS, 0 FAIL, 20 total flash attempt(s).
```

What this validates:

- App reset to bootloader over CAN works repeatedly.
- CAN erase, stream flash, page CRC, and final app CRC paths are stable.
- The bootloader reboots into the application after flashing.
- The application responds to CAN ping after each update.

### Bus Noise During Update

Command pattern:

```powershell
py .\bus_noise_update.py C:\Users\Petar\Desktop\BLDC.bin `
  --can-interface slcan --channel COM6 `
  --target 0 --noise-nodes <other-running-app-nodes>
```

Observed result, normal noise:

```text
Verifying... OK
Flash complete in 27.6s! Board will reboot into the new firmware.

Injected 713 telemetry request frame(s) during flashing.
Waiting for target app node 0 to respond after update...
Target app ping: PASS
```

Observed result, heavier noise:

```text
Verifying... OK
Flash complete in 27.8s! Board will reboot into the new firmware.

Injected 1426 telemetry request frame(s) during flashing.
Waiting for target app node 0 to respond after update...
Target app ping: PASS
```

What this validates:

- The CAN flasher ignores unrelated Spectral app telemetry traffic while waiting
  for bootloader ACKs.
- Other running application nodes can remain active on the bus while one target
  node is updated.
- The target node still verifies, reboots, and responds to app ping after a noisy
  update.

### Summary

| Test | Result |
|---|---|
| Firmware binary validation | PASS |
| 20-cycle CAN update soak | PASS, `20/20` |
| Bus-noise update, 713 injected frames | PASS |
| Bus-noise update, 1426 injected frames | PASS |

Overall result: CAN bootloader update path is stable on the tested CANvas SLCAN
adapter setup.

### Remaining Useful Abuse Test

The main untested field-abuse case is power loss during flashing:

1. Start a normal CAN flash.
2. Remove power partway through the update.
3. Power the board again.
4. Confirm the bootloader remains reachable.
5. Reflash the same app successfully.
6. Confirm the app boots and responds to CAN ping.

Passing this would validate recovery from interrupted or partial application
updates.
