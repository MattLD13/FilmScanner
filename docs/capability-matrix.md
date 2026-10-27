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
