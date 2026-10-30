# Scanner and software inspection on October 30 2026

The connected scanner is recognized by Windows and VueScan is communicating with it. FRAME's application still uses its simulator. These are separate results.

This inspection reviewed Claude's changes from `9b65274` through `eb842b6`, queried Windows device/driver metadata, inspected installed files statically, and observed the already running VueScan application. No scan, calibration, film movement, cancellation, ejection, firmware operation or driver installation was initiated by this inspection. The only application input was selecting VueScan's Input tab to read the current settings.

## Connected hardware

| Check | Observed result |
| --- | --- |
| Windows device | PIE Scanner; Image class; Status OK / Started; problem code 0 |
| Bus-reported device description | AFL Film Scanner |
| Hardware identity | VID `2770`, PID `0119`, revision `0100` |
| Device class compatibility metadata | Vendor-specific USB class/subclass/protocol `FF/FF/FF` |
| Installed binding | Hamrick Software `oem273.inf`, original name `scadrv60.inf` |
| Binding version | `1.0.0.163`, dated August 21, 2006 |
| Active service and stack | `usbscan`; stack reported `ksthunk`, `usbscan`, `USBHUB3` |
| Actual kernel driver | Microsoft `usbscan.sys` in the AMD64 Windows DriverStore, version `10.0.26100.9818` |
| Kernel signature | Valid Microsoft Windows Authenticode signature |
| Kernel SHA256 | `7F7C830056008AFF93FB2B9C01B003F5C02D05C5D339DA8D0F664FC8AFBDC5D1` |

The Hamrick INF explicitly matches `USB\VID_2770&PID_0119` and delegates to `sti.inf` / `STI.USBSection.Services`. The INF's old version/date is not the version of the loaded Microsoft kernel binary. One Windows WMI query reported the package as unsigned; PnPUtil reported Hamrick as its signer, while direct examination of the actual loaded Microsoft kernel file reported a valid signature. This report does not conflate those different signing observations or recommend reinstalling a working driver.

This actual unit's identity supersedes the earlier uncertainty about the AFL ID. The historical `05E3:0120` finding belongs to the separate PF1800U path. The `2770:011C` and `0461:034A` values in the earlier package investigation are not the identity of this attached unit.

## VueScan observation

The already running application was VueScan 9 x32, version 9.8.37, on the Windows 11 host. It identified the source as **PrimeFilm 1800 AFL** / **PIE PrimeFilm 1800 AFL**, 35 mm film. During observation it displayed frame 2, scan progress, lamp-warmup status and a photographic preview. This is real application behavior with the attached device, not FRAME's synthetic chart.

The user clarified that the loaded film is **color negative**. An earlier observation showed B/W negative. At the final Input-tab inspection, Media read **Color negative**, matching that correction. The inspector did not change the media selection. VueScan remained in an active scan, so acquisition settings and transport were left alone.

The final visible Input settings included Batch scan Auto, frame 2, frame offset 0, automatic preview/scan resolution, rotation Left, Mirror enabled, and JPEG output. The preceding Color-tab observation showed Generic / Color / Negative with Portrait balance. These were current user/application settings, not defaults selected or validated by this inspection. Rotation, mirroring, film stock response and final color accuracy were not calibrated here.

No completed archival original was verified. A search for recently modified image files directly in the configured Pictures folder found no candidate to inspect at that moment; it was not a recursive search and does not establish that no saved scan exists elsewhere. Effective acquired bit depth, actual DPI, TIFF metadata, full-roll reliability, focus accuracy and transport safety remain unverified. A changing or populated preview alone does not establish any of those properties.

## Installed CyberView module

The installed **CyberViewX_MF** directory contains a standalone `SCAN08.dll` that was absent from the earlier official **CyberViewX_SF** download.

| Property | Static result |
| --- | --- |
| File | `%WINDIR%\TWAIN_32\CyberViewX_MF\SCAN08.dll` |
| Size | 118,784 bytes |
| Resource version | `1.0.3.6` |
| Architecture | x86 PE32 |
| Export | `ScannerDeviceIO` |
| SHA256 | `DA413438C0136338799CC7D49A14ABAE700E29FEB7DA1E993D4DA1B8B5554B7F` |
| Important imported library | `SQ_Scan.dll` |

Static disassembly after the device-descriptor query at preferred address `0x100083c2` compares the vendor to `0x2770` at `0x100083e9` and product to `0x0119` at `0x100083f9`, then accepts that pair. A separate branch also checks `1606:F000`. The first pair matches the actual connected device. This is strong evidence that this installed module is relevant to the unit; it is not proof that CyberView has successfully loaded it or scanned with it on this host.

The MF folder also contains `PF3610AFL.dll`, `BeneScan.dll` version 1.5.0.0, and film terms directly under GAMMA. The inspector did not load any of these vendor libraries or launch CyberView, because VueScan already owned an active scan. Installed-file provenance beyond the current Windows installation was not established; the original package or CD should be preserved and hashed before further investigation.

## What Claude added

- A research-only replacement model-37 module that original CyberView could detect, prescan and scan against inside the guest. Its image is synthetic and it performs no device I/O. This demonstrates a host module contract, not physical USB emulation or scanner compatibility.
- An Electron desktop shell around FRAME's local service and React UI.
- A simulator scan workspace with prescan thumbnails, frame selection, crop window, channel gains, requested DPI/depth metadata and parsed/cached CyberView film profiles.

The production TWAIN and USB backends remain disabled. FRAME cannot yet use the attached hardware merely because Windows or VueScan can.

## Code review findings

The [detailed independent review](2026-10-30-code-review.md) reproduces three P2 defects:

1. **Import collision after selected scans.** A scan containing only index 2 leaves one frame row; the next import also chooses index 2, returns HTTP 500 and leaves an untracked file.
2. **Prescan ownership race.** Development can start while a prescan owns the same roll; completion can overwrite its developing status with stale scan-ready state.
3. **Two service owners.** Desktop startup can choose a random port while the browser launcher starts another service on 8765 against the same default library. Independent acquisition/recovery workers can then conflict.

Selected-frame progress also uses the full roll's frame count as its denominator. These issues were documented rather than silently fixed as part of a review request. Two strict expected-failure regressions keep the first two known bugs visible in the test suite.

## Validation executed

- Python suite: **106 passed**, plus **2 strict known-bug expected failures** after the review reproductions were added.
- Desktop helper tests: **7 passed**.
- TypeScript checks and production build: passed.
- Browser workflow: passed with 36 synthetic frames, prescan, film profile, dragged crop window, exposure settings, phone-size event delivery and inspected 16-bit TIFF output.
- Hardware checks: Windows PnP and PnPUtil, driver signature/version/hash, VueScan window/status observation, static installed-module inspection.

The tests did not operate the physical scanner. No firmware or motion command was issued by the inspection. Personal scan images and workstation-specific identifiers are excluded from the tracked review evidence.

## Next useful work

1. Correct the three reproduced application ownership/indexing defects before attaching a real acquisition backend to the same orchestration.
2. Let the current VueScan operation finish and preserve one original scan in a separate, non-overwriting archival output, then inspect its dimensions, sample depth and metadata.
3. Inventory and preserve the genuine MF installer or original CD that supplied `SCAN08.dll`, including its dependencies and model-37 film terms.
4. When no other application owns the scanner, establish a controlled original-software baseline for this exact `2770:0119` unit. Do not start competing scan applications.
5. Capture actual descriptors and one documented operation at a time before enabling production hardware controls. The [hardware plan](../../research/cyberview/hardware-plan.md) still governs movement, fault recovery and firmware work.
