# Capability evidence

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
