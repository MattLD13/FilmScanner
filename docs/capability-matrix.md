# Capability evidence

## Current native feature port — November 1, 2026

The [feature-port report](cyberview-feature-port-2026-11-01.md) supersedes older
checkpoint statements below. Actual captures now cover the recorded RGB/grayscale
8/16-bit modes at 300/360/450/600/900/1800 DPI, the tested custom area, and positive
mode on a strip. Configurations are individually gated; this is not every possible
combination. Vendor flag-1 exposure, bounded goto 1→2→1, focus 2→3→2, and vendor
realignment have new physical evidence. Software frame-origin labeling changes no
hardware counter. Optional filters and aligned repeat averaging are integrated.

Exact isolated vendor automatic-tone generation/application is CPU-verified, but
full CyberView caller-state/order parity and exact ROC/GEM ports remain unfinished.
Three actual originals establish 12-bit-aligned delivered codes, not sensor/ADC
effective bits. Mounted-slide handling and calibrated sensor precision still
require unavailable physical media/target evidence. See the report for scope,
failed trials corrected, and test commands.

## Historical checkpoints

The first table is the historical simulator checkpoint. Physical single-frame
capture, prescan, streamed preview and selected transport/exposure actions now
have recorded direct-bridge evidence; see the latest [progress](progress.md),
[native validation](../services/scanner_host/native_validation.json) and
[completion checklist](feature-completion.md). Full real-roll acceptance and
independent raw-driver acquisition remain unfinished. Neither the simulator nor
the new offline command workbench establishes those capabilities.

| Function | Simulator | Actual PF1800 AFL |
| --- | --- | --- |
| Discover/connect/initialize/calibrate | Implemented synthetic state machine | UNAVAILABLE in application; not tested |
| Load/prescan/frame positions/acquire | Deterministic synthetic fixtures | UNAVAILABLE in application; not tested |
| Uncut roll / precut strip | 1–72 synthetic frames | No on-device verification |
| Mounted slides | Unsupported | Unverified |
| 1800 DPI | Model label only; fixture is 192×128 | DOCUMENTED in supplied spec; not measured |
| Precision | Actual uint8 RGB, 8 effective bits | Exported precision and rawness unmeasured |
| Live view | Status/progress and completed previews | Actual transfer mode unknown |
| Jam/cancel/disconnect/recovery | Tested fault injection | No motor commands implemented |
| TWAIN / USB | Explicit unsupported backend stubs | UNAVAILABLE |
| Firmware | No writing implementation | UNAVAILABLE |

No simulator test promotes any real capability to VERIFIED ON DEVICE.

## Actual attached unit observed on October 30 2026

- **Verified enumeration on this unit:** Windows reports `AFL Film Scanner`, USB `2770:0119`, revision `0100`, with Image-class status Started and problem code 0.
- **Verified current host binding:** Hamrick's INF delegates to the Windows `usbscan` service. The actual AMD64 `usbscan.sys` kernel file has a valid Microsoft signature.
- **Observed real application communication:** VueScan 9 x32 9.8.37 identifies PrimeFilm 1800 AFL and displays scan progress and a photographic preview. No new operation was initiated by the inspection.
- **Still unverified:** completed archival acquisition, effective acquired precision, exact optical/output DPI, autofocus, full-roll transport/recovery, and physical behavior under FRAME control.
- **Static installed-file evidence:** `CyberViewX_MF/SCAN08.dll` version 1.0.3.6 checks `2770:0119`. CyberView was not launched by this inspection; production TWAIN/USB backends remain disabled.

Details and limits: [scanner inspection](reviews/2026-10-30-scanner-inspection.md). The historical table above describes the initial software state; enumeration and VueScan observations do not enable FRAME's real hardware backends.
