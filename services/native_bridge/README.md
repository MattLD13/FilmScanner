# Experimental direct AFL module bridge

`aflbridge.exe` is an x86 host for the installed Pacific Image `SCAN08.dll`
1.0.3.6. It bypasses TWAIN and CyberView's application window, while retaining
the vendor's calibration, optics and USB routines. It is **not an independent
USB driver**. Current-frame acquisition is validated on the physical unit; the
other operations the service enables are listed in
[cyberview-parity.md](../../docs/cyberview-parity.md), and every selector of the
module is catalogued in [scan08-feature-catalog.md](../../docs/scan08-feature-catalog.md).
See also [physical results and app integration](../../docs/native-scanner.md).

The helper never changes CyberView's INI, installs a driver, resets USB, flashes
firmware, or exposes arbitrary selectors. Film movement (`film next|previous|
goto N|eject_forward|eject_backward`), focus (`focus auto|N`) and film-base
measurement (`calibrate`) are compiled in but refused unless the service passes
`--allow-experimental-controls --controls <list>`; it passes only the actions
recorded in `native_validation.json`. Acquisition settings other than the
default 1800 dpi 16-bit RGB need `--allow-experimental-settings`, which the
service passes only when that file records extra configurations.
Identity lookup tables retain the module's calibrated transmission output;
do not label it sensor raw or assume CyberView's negative inversion is applied.
The static analysis indicates a 12-bit lookup domain in a 16-bit container;
actual acquired precision must be measured separately.

## Build and CPU-only verification

From the repository root, with MSVC 2022 Build Tools installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File services/native_bridge/build.ps1 -Fixtures
python -m pytest -q tests/native
services/native_bridge/bin/aflbridge.exe --describe
services/native_bridge/bin/aflbridge.exe --self-test
```

The optional fixture helper is compiled with `FRAME_NATIVE_TEST`. Only that
separate executable accepts `--fixture-dll`, loads the synthetic test DLL and
labels its events `synthetic: true`. The production executable rejects this
option. Test artifacts are ignored, and no vendor binary is distributed.

## Explicit experimental device access

Before a physical experiment, obtain the user's authorization under
`FRAME_SPEC.md` section 11.4. Both native detection and open operations can write
registers, light the lamp and home the motors. They are not passive diagnostics.
An example invocation, **not a command to run during routine verification**, is:

```powershell
services/native_bridge/bin/aflbridge.exe serve --allow-experimental-device-io --timeout 300
```

The production helper loads only
`%WINDIR%\twain_32\CyberViewX_MF\SCAN08.dll`, with SHA-256
`da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f`.
The file cannot be replaced while its hash is checked and it is loaded.
Dependencies are searched only in that module's directory and the Windows
system directory. A shared `Local\FRAME_PF1800AFL` mutex blocks concurrent
native and TWAIN bridges; CyberView's loader must also be closed. The fixture
uses a separate process-specific mutex and cannot contend with a real scanner
session or another CPU-only fixture.

Startup uses model selectors 1 (CPU allocation), 3 (device detection and
initialization), 5 (open/homing), then 0x16 (capability block). The capability
block must report model 37, 1800 dpi and the reviewed 2586 by 1708 maximum.
Before every acquisition, selector 0x15 receives two DWORDs `{0x1f, 0}`. This
status query establishes the module's internal film type as well as checking
that supported strip film is present. A failed query or a response without
bit 2 is rejected before creating an output file or calling the scan selector.
Actual CyberView traces returned 0x0e with strip film and 0x08 without film.
Shutdown calls selector 2 (CPU cleanup). No explicit focus operation is issued
in this implementation, matching the observed vendor startup. A required masked
status query before each scan latches strip state and rejects missing film.

## USB trace

`--trace-usb PATH` logs every kernel32 call the vendor modules make to usbscan.sys
(see `usbtrace.h` and [scanner-protocol.md](../../docs/scanner-protocol.md)). It is
passive and still requires `--allow-experimental-device-io` to reach the scanner.

## Pipe protocol

Input is UTF-8, one command per line. Output is JSON, one record per line.
After `opened` and `ready`, send:

```text
scan 1 C:\absolute\path\new-acquisition.tif
cancel
quit
```

`scan 1` performs exactly one current-frame acquisition. Events are
`enabled`, `image_start`, `progress`, `image`, `scan_done`, then `ready`.
Only `image` means a complete TIFF has been atomically finalized. The helper
rejects existing destinations and preserves earlier partial files. Invalid,
missing or truncated callback strips are errors, never successful images.
Every scan has 16-bit RGB samples; rows are written exactly as delivered.

`cancel` and input EOF request the module's callback abort flag. This is
cooperative: the helper cannot promise to interrupt a vendor function that
hangs without invoking another callback. `--timeout` bounds elapsed time at
callback boundaries, not an arbitrary blocking vendor call. The command queue
holds at most four entries and never blocks receipt of cancel or EOF.

Every other command, including transport and alternate frame counts, is
rejected. There is no automatic reset, retry, firmware access or fallback to a
different scanner model. Research evidence is kept separately under
`research/cyberview` and the passive traces under ignored `.local/`.
