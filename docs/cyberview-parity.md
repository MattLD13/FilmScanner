# Native capture: device test record

**November 1 update:** additional acquisition configurations, vendor automatic
exposure, bounded go-to-frame, adjacent manual focus, and vendor realignment were
tested and recorded. The [feature-port report](cyberview-feature-port-2026-11-01.md)
and current `native_validation.json` supersede the October 30 control/configuration
tables below. Full CyberView processing parity, mounted-slide media, and calibrated
effective sensor bits remain distinct open items; no fixture test promotes them.

`services/scanner_host/native_validation.json` decides which native-capture
controls CyberScan X enables. This page is the readable record behind it.

**Source.** The ChatGPT session ran these supervised tests on 2026-10-30 and
recorded them only in that JSON file. The raw traces, scan files and logs of
those runs are not in the repository. This page restates exactly what the file
records and adds nothing to it. Claude did not repeat these runs. The broader
static evidence is in [scan08-feature-catalog.md](scan08-feature-catalog.md).

The record is tied to `SCAN08.dll` SHA-256
`da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f`. If the
installed module differs, `workspace.validation()` returns nothing and every
native control is disabled.

## Enabled controls

| Control | Selector | Recorded result | Conditions in the app |
| --- | --- | --- | --- |
| Next frame | 9 forward | Position 1 → 2 after a scan in the same session | Only after a scan or prescan in the current native session |
| Previous frame | 9 reverse | Position 2 → 1 after a scan in the same session | Same. The equivalent CyberView command hung the driver (see [cyberview-bridge.md](cyberview-bridge.md)) |
| Eject forward | 8 forward | "User confirmed strip came out normally and reloaded it" | Asks for confirmation |
| Eject backward | 8 reverse | User observed the strip exit backward on 2026-11-01; the module's post-eject sensor still reported loaded | Asks for confirmation; stale sensor state is advisory after selector completion |
| Autofocus | 14 | Focus step 2; a 600 dpi scan afterwards delivered 826 × 567, 16-bit RGB | Asks for confirmation |
| Film-base measurement | 17 | R/G/B 147 / 197 / 309 | Asks for confirmation |

Not recorded, so not enabled: go to frame, manual focus step.

## Enabled scan configurations

All three use RGB, negative film, the default crop (0.03, 0.003, 1.407, 0.95 in),
exposure 100/100/100 and no focus override.

| Resolution | Depth | Recorded |
| --- | --- | --- |
| 1800 dpi | 16-bit | Corrected current-frame capture: 2479 × 1703, all three channels populated ([native-scanner.md](native-scanner.md)) |
| 600 dpi | 16-bit | 826 × 567 after autofocus |
| 300 dpi | 8-bit | Prescan, 413 × 283. Source SHA-256 `67dd0180…8e8b` |

## Recorded limits

- A **fresh session could not advance film** before any scan: "fresh-session
  advance stalled and required a supervised power-off recovery". That is why
  film moves need a scan first.
- Native capture has **no automatic USB-reset recovery**. A timed-out native
  operation keeps the session reserved until the driver returns, and the
  scanner may need switching off and on.

## Promoting another control

Run it once under supervision, keep the raw output in ignored local storage,
add an `observations` entry and the action or configuration to
`native_validation.json`, then add a row here. Static analysis alone never
enables a control.
