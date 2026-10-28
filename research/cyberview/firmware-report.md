# Firmware investigation

Status: STATIC INVESTIGATION ONLY. No firmware readout, updater execution,
physical inspection, scanner write or flashing has occurred.

The official package's290-file inventory has no standalone `.bin`, `.hex`, `.rom`
or `.fw` firmware image. `PScanner.CFG` is a configuration candidate beginning
`PIE Macross 1.103`, not a validated firmware image. InstallShield `layout.bin` is
installer metadata; its extension is not evidence of device firmware. Unknown
embedded blobs have not been identified by controller architecture or validated
against a known image. Full file hashes are in the acquisition inventory.

| Static location | Finding | Limit |
| --- | --- | --- |
| CyberViewX.ds `0x101cc0e6`, `0x101d1328` | Update Firmware menu/resource strings | Generic multi-model UI; not proof AFL can update. |
| CyberViewX.ds `0x101d1c4e` | Error message expects firmware-upgrade filename `*.bin` | No corresponding image found in this package. |
| CyberViewX.ds `0x101d1d8e` /`0x101d1ef6` | Version-comparison and upgrade-duration messages | Resource text, not observed acceptance or measured duration. |
| daspi32u.dll `0x1000139f` | Export `_UsbWriteScannerFw@8`, prefix bytes1,1,0,0 plus size; calls generic write helper`0x100015c4` | Family implementation; AFL applicability and update framing unknown. Not executed or allowlisted. |
| PF1800U.dll `0x100050a0`, log string`0x1001b17c` | SDK log emits `F/W Version = NO F/W` | Distinct U module's label, not evidence that AFL has no firmware. |
| CyberViewX.ds `0x100a8520` →BeneScan model table | AFL path names `SCAN08`/`SCAN08.dll` | No standalone module in extracted file inventory; cannot fully inspect AFL controller implementation yet. |

Neither controller family nor nonvolatile storage type is established. The VID
manufacturer name, a related-model DLL or generic motor/firmware export is
insufficient. No claim of a Cypress/Genesys CPU, EEPROM layout, bootloader,
recoverability, update checksum, signed image, version response or writable flash
is made. Generic UI focus imports are unrelated to sensor firmware.

Next useful work is read-only: compare the user's original CD with these hashes;
resolve the AFL-specific driver module; capture normal enumeration/initialization
using vendor software; inspect any genuine model-specific firmware version query
in those traces. Board inspection is deferred until after the return period and
requires a separate power/lamp-inverter safety plan. A verified readout and recovery
strategy would precede any discussion of writing. **No custom firmware flashing
is part of M1.5 or the initial deliverables.**
