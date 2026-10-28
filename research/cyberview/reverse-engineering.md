# CyberView static reverse engineering

Research pass: 2026-10-27–28 UTC. **M1.5 is incomplete.** The official installer
was preserved and statically extracted; a useful model/host-I/O map and tested
passive laboratory exist. Original CyberView has not yet been installed or
launched inside the evaluation guest. No PF1800AFL USB device has been enumerated
by a guest, and no physical scanner behavior is verified.

## Artifact identity and evidence rules

The manufacturer-linked installer is 9,898,119 bytes, SHA256
`EBCBE798FE577B9461DF22DB3BDE6240185E0553E65EB9B93D139D367F9109CF`.
The source, redirects, source-built extraction tools, licenses, all 290 extracted
files and their hashes/versions/imports are recorded in
[the acquisition inventory](acquisition/inventory.md) and
[machine-readable inventory](acquisition/payload-inventory.json).
No legacy installer, DLL or driver was executed on the host.

The filename's `1.3`, embedded `CyberView X - SF v1.30 (build 20110526)`,
InstallShield `14.0.162`, and TWAIN `CyberViewX.ds` resource version `1.4.0.0`
are distinct version records. This package contains several scanner families.
An official PF1800AFL download link does not make every included driver an AFL
driver.

All addresses below are **preferred image virtual addresses** in the exact named
32-bit PE, not file offsets or runtime relocated addresses. A static instruction,
string, import or RTTI relationship is labeled STATIC. A semantic interpretation
without an actual operation trace is INFERRED. None is VERIFIED ON DEVICE.
Ghidra warnings about unsettled type propagation mean inferred parameter types
and return types must be checked against disassembly. Windows `GetFocus` and
`SetFocus` imports refer to UI keyboard focus; they are not optical focus evidence.

## Analysis tools actually used

* Ghidra **12.1.4**, official NSA release
  `ghidra_12.1.4_PUBLIC_20260921.zip`, using 64-bit JDK **21.0.10** from the existing
  Android Studio JBR. No global Java change was made. The PATH Java8 was unsuitable.
* Python **3.13**, isolated `pefile==2024.8.26`, `capstone==5.0.9`. Dependencies and
  downloaded tools remain ignored under `research/.tools/`.
* [REA installation requirements](https://github.com/morluto/rea/blob/main/docs/installation.md)
  were investigated. REA was not installed or run: the available Node24.19.0 is
  below the retrieved REA6.8.0 Node24.22.1 requirement. Direct Ghidra headless and
  Capstone supplied the static analysis. No REA analysis is claimed.
* Headless results: PF1800U.dll **721 functions /64 selected**, daspi32u.dll
  **437/56**, CyberViewX.ds **6531/270**, BeneScan.dll **1489/25**. Explicit AFL
  virtual-method and loader follow-ups were also decompiled with disassembly.
  Raw exports and analyzer logs remain in ignored `.artifacts`; reproducible
  survey scripts are in [analysis/](analysis/).

Initial headless project creation failed because Ghidra forbids a path component
starting with `.`. Projects were then created in ignored
`analysis/workspace.ghidra/`; analysis succeeded. This path requirement does not
affect importing binaries from `.artifacts`.

## AFL-specific class and driver binding

`Resource_ENG/CyberViewX.ds` SHA256
`50C9B359417CA61E555A743B8E7351DF43A22585822AA79C334140DD0EB6D64E`
contains distinct `CPfs1800AFL`, `CPfs1800Lab`, `CPfs1800P`, and `CPfs1800U` RTTI.
The reproducible [RTTI candidate map](analysis/rtti-evidence.json) records their
type descriptors, virtual tables and method slots.

| Binary/address | STATIC finding | Implication / confidence |
| --- | --- | --- |
| CyberViewX.ds `0x101510e4` /`0x10129264` | `CPfs1800AFL` type descriptor and 111-entry virtual table | High confidence class identity; slots alone do not name operations. |
| CyberViewX.ds `0x100a8520` | Constructor assigns that AFL table and driver-name string `SCAN08`; it also sets a field to `0x28` | High confidence binding string. `0x28` is not promoted as a validated maximum roll length. |
| CyberViewX.ds `0x100a9fe0` /`0x101297dc` | Separate U constructor uses `PF1800U` and a distinct table | The PF1800U USB identity cannot simply be assigned to AFL. |
| CyberViewX.ds `0x100a8490` →`0x100bb2a0` | AFL table slot61 enters common binding. It loads `BeneScan.dll`, resolves `ScannerDeviceIO`, calls host API selectors1,5,0x16,0x14 | Host library boundary identified; selectors are not USB opcodes. |
| BeneScan.dll `0x10011840` /`0x10010a30` | Export `ScannerDeviceIO` creates a scanner object and dispatches API selectors through a handler table | Recovered host API dispatcher. |
| BeneScan.dll `0x1000c0f0` /`0x1000bf50` | Discovery/open walk 0x44-byte model-table records at `0x100450d0` | Selection uses model records and dynamically loaded modules. |
| BeneScan.dll `0x1004519c` /`0x100451a0` | Model `0x25` record contains `SCAN08.dll` | Concrete model module name in the driver loader's table. |
| BeneScan.dll `0x100106d0` /`0x10010040` | Builds module-directory + table filename, calls `LoadLibraryA`; fallback loads the filename; then resolves `ScannerDeviceIO` | Strong evidence of an external DLL load path in this examined code. |
| CyberViewX.ds `0x100a9d58` /`0x100a9d65` | `CPfs1800P` constructor pushes `LC` and `42.GG` | 1800P binds BeneScan model 42 `LC.dll` (record `0x100452f0`). Added 2026-10-28. |
| BeneScan.dll `0x1000c0f0` | Discovery walks records 18→0; calls detect selector 3 only after the module loads | A missing module is most likely skipped silently (INFERRED). |
| LC.dll `0x10011677` et al. | Version resource SCAN08.DLL 1.0.9.4; `Model Code = 42`; accepts USBSCAN descriptor `2770:011C` only | SCAN08-lineage build bound to 1800P, not AFL. |
| PF1800LC.Dll `0x10005d40` | Export name `Scan08.dll` 1.0.0.1; accepts `0461:034A` or `2770:011C` | WIA 1800P module; PWiaScnr binds `CPfs1800P → PF1800LC`. |

`BeneRaw.dll` and `BeneScan.dll` are byte-identical, SHA256
`ACD215AA92EC45B79837A6DC0ECF4A008AAE772A6A6946C98A93B9570635C27C`.
The 290-file listing contains **no standalone `SCAN08.dll`**. Strings naming it
also occur in LC/WIA components. A string is not an embedded executable, and the
examined BeneScan path loads an external file; however, a successful runtime trace
or exhaustive installer/resource recovery has not established whether another
installation path generates/supplies it. Therefore this is a **specific likely
dependency gap**, not a proven guest loader failure. Do not rename PF1800U.dll or
substitute a DLL from another scanner model. The original CD remains an important
comparison source.

**2026-10-28 refinement.** The earlier note that strings in `LC.dll`/`PF1800LC.Dll`
"may resolve to code" is now answered. Both are SCAN08-*lineage* builds: LC.dll's
version resource says `SCAN08.DLL`, and PF1800LC.Dll's export name is `Scan08.dll`.
The vendor's own tables bind both to the 1800P ("Low Cost", model 42), and the
AFL is model 37. Neither supplies the AFL module, and renaming either would be a
cross-model substitution. Gamma file numbers match model codes throughout. The
`setup.inx` script is still encoded, so an install-time rename is not ruled out
statically. Full evidence: [scan08-investigation.md](scan08-investigation.md).
Status: **still unresolved**.

## Detection, transport and acquisition map

`PF1800U.dll` SHA256
`6A694BF6344C90E11F961B29239F99BE82567D0DC3FCF790F213602D44414F03`
is included and statically analyzable, but is the distinct U path.

| Binary/address | STATIC evidence | Scope / remaining unknown |
| --- | --- | --- |
| PF1800U `0x10001cb0` | Opens `\\.\Geneusb%d` then `\\.\usbscan%d`, indexes0–126; checks VID`05e3`, PID`0120` | Matches PF1800U.INF. Actual AFL identity remains unknown. |
| PF1800U `0x10007b90` | Exported `ScannerDeviceIO` dispatches host selectors; selector1→`0x100050a0`,3→`0x10005460`,0x13→`0x100057f0`,0x20→`0x10006e00` | Named host boundary; no USB opcode equivalence. |
| PF1800U `0x10003480` | Builds 16-byte block; `DeviceIoControl(...,0x80002010,...)` | x86 USBSCAN-compatible `IO_BLOCK` write path. |
| PF1800U `0x100021d0` | Writes register offset0x83, then reads offset0x84 using IOCTL`0x8000200c` | Register address and length are static; register meanings need traces. |
| PF1800U `0x100034f0` | Writes offset0x82 with an 8-byte block before `ReadFile`; splits at0xf000 bytes | Buffered transfer/chunk strategy. `0x82` here is a register value, **not a proven endpoint address**. |
| PF1800U `0x10002260` | Another read path writes offsets0x83/0x82, then `ReadFile`, chunks≤0xffff | Host path exists; successful frame lengths/channel order not measured. |
| PF1800U `0x100050a0` /`0x10007230` | Allocates acquisition buffers, prepares `PF1800U.log`; calibration/start-scan log labels include RGB gain, DC and exposure | Sensor-control evidence in the U implementation; units/ranges and AFL applicability unverified. |
| CyberViewX.ds `0x100a8660` | AFL-specific table slot50 manages Number Scanned and invokes host selector9 or shared helper`0x100b9d50` | Roll/advance orchestration inferred. Wire format/position units/safe motion bounds remain unknown. |
| CyberViewX.ds `0x100b8fd0` /`0x100b9000` | Shared AFL table methods invoke selector10 with a two-word block whose first word is1 or2 | Direction-like host API variants; forward/reverse semantics need original UI traces. |
| CyberViewX.ds `0x100bb1a0` /`0x100bb240` | Status/IsDocumentInFeeder strings, selector0x15, masks on returned status | Shared status bit handling; no actual sensor observations. |
| CyberViewX.ds `0x100a8860` | AFL acquisition override builds settings/LUT buffers and thread/event callbacks; calls selector0x20; helper`0x100b9ac0` delivers rows/chunks | Genuine application acquisition architecture, not proof of CCD live streaming or effective precision. |
| daspi32u `0x100017c8` /`0x100016a3` /`0x10001738` | Generic Geneusb/Usbscan enumeration and identity queries | Family transport reference; another routine`0x10001e4b` requests05e3:0129, so cannot be assigned wholesale to AFL. |
| daspi32u `0x1000140b` /`0x10001464` | Read/write IO_BLOCK wrappers | Independent confirmation of host control structure. |
| daspi32u `0x10001c15` | Export `_UsbMotorControl@16` builds six bytes and writes register0x89 | Real static motor-related symbol; purpose, bounds and target model unverified. Never issued. |
| daspi32u `0x1000139f` | `_UsbWriteScannerFw@8` builds a transfer prefix and calls bulk-write helper | Generic firmware-named path, not an AFL updater proof. |

Optical autofocus is documented by the specification/manual context and generic
CyberView UI/classes (`CAutoFocusDlg`, `CAutoFocusPS`). This pass did **not** recover
an AFL-specific focus wire command or safe focus bounds. Calibration, exposure and
gain are likewise investigated above without claiming a reconstructed AFL
protocol. Firmware details are in [firmware-report.md](firmware-report.md).

## Executed isolated laboratory results

[USB protocol notebook](protocol-notebook.md) identifies exactly what the parsers
understand. They reject unsupported or ambiguous commands, malformed descriptors,
oversized transfers and out-of-order replay. There is no default PF1800 descriptor
or fabricated response profile. The optional FRAME simulator adapter was omitted:
there is no evidenced wire operation to map to it, and inventing a mapping would
make a misleading emulator. The production simulator and hardware enablement
remain untouched.

Portable QEMU11.1 was extracted without executing its installer; its published
SHA512 matched. An actual stopped/diskless/no-NIC QMP smoke test passed. A real
Python loopback TCP USB/IP management exchange passed: DEVLIST returned zero
devices, IMPORT failed explicitly, unknown management traffic was rejected.
Those [logs](../usb/evidence/) are **harness-only**, not CyberView communication.
The exact replay engine also passed deterministic synthetic-fixture tests; it
has no captured PF1800 profile.

The officially downloaded Server2008 x86 evaluation VHD was booted in a writable
qcow2 overlay over an explicitly read-only hash-verified base, with no NIC, shared
host folder or physical USB passthrough. It advanced through regional OOBE to the
product-key page (blank key; default autoactivation checkbox checked; no
activation submitted and no NIC). The first attempt's relative pointer input
initially appeared delayed; a second bounded start added
QEMU's standard USB tablet. Computer Use then reported that the **user stopped it
with the physical Escape key**. UI automation ceased immediately, and our QEMU
was stopped through its own management socket. No CyberView execution or device
detection occurred. This is a stopped guest-preparation attempt, not a vendor
detection test. Details and remaining prerequisites are in
[guest-environment.md](guest-environment.md).

Validation during this pass: `python -m pytest -q tests/research` → **22 passed in
0.07s** (19 USB/replay tests plus3 inventory tests). This is not a substitute for
the root's full application/workflow validation. Physical testing remains governed
by [hardware-plan.md](hardware-plan.md).
