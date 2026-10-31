# Handoff: CyberScan X and the PF1800 AFL (2026-10-31)

For the next agent. Read [AGENTS.md](../AGENTS.md) and FRAME_SPEC.md first. This page
says what exists, what is proven on the scanner, what is only proven in tests, and
what to do next.

## Current handoff

**Use [handoff-current.md](handoff-current.md) first.** The scanner session was
committed as `5fb63e2`; software colour work followed it. The earlier branch state,
uncommitted-work list and numbered scanner plan below are historical. Do not repeat
those completed actions. Current implementation, checks and remaining work are in
the current handoff and [negative-conversion.md](negative-conversion.md).

## Historical state of the branch

- Branch `cyberscan-x-cyberview-bridge`. Last commit `8fe705f` (Start menu shortcuts).
- **Everything below is uncommitted** (about 56 changed or new paths): the native AFL
  backend review, the SCAN08 catalog, auto-align and stitched scans, the protocol
  reverse engineering, the USB tracer, live preview, stuck detection and the CyberView
  step commands. Ask the user before committing. Never commit `data/` (scans and
  traces), `bin/` folders or anything machine-specific.
- Last full run (2026-10-31): `python -m pytest -q` → 178 passed, 2 xfailed;
  `npm run lint`, `build`, `test:skin`, `test:native-ui`, `test:live-preview`,
  `test:e2e`, `test:desktop` all passed.

## Build

```bash
powershell -ExecutionPolicy Bypass -File services/cyberview_bridge/build.ps1 -Tests
```

```bash
powershell -ExecutionPolicy Bypass -File services/native_bridge/build.ps1 -Fixtures
```

Both need Visual Studio 2022 Build Tools (x86). `-Tests`/`-Fixtures` build the
CPU-only harnesses the tests use; tests skip when they are missing.

## What exists

| Area | Where | Proven on the scanner? |
| --- | --- | --- |
| Hidden CyberView scanning (TWAIN), one session for many frames, Forward One Frame | `services/cyberview_bridge/cvbridge.c`, `services/scanner_host/cyberview.py` | Yes (2026-10-30, 31) |
| USB restart task, settings restore | `cyberview.py`, `docs/cyberview-bridge.md` | Yes |
| Direct SCAN08 backend (ChatGPT's), gated | `services/native_bridge/aflbridge.c`, `services/scanner_host/native.py`, `native_validation.json` | Partly; see `docs/native-scanner.md` |
| SCAN08 feature catalog (37 selectors) | `docs/scan08-feature-catalog.md` | Static analysis |
| Full protocol: SCAN08 → SQ_Scan → IO_PORT → FVC → usbscan, register map, USB SETUP packets | `docs/scanner-protocol.md` | Confirmed by two traces |
| Passive USB tracer `--trace-usb` | `services/native_bridge/usbtrace.h` | Yes, two traced scans |
| Trace decoder (`--summary`, `--phases`, `--tables`) | `research/cyberview/analysis/usb_trace.py` | Yes |
| Live scan preview from the USB stream | `services/cyberview_bridge/usbwatch.h`, `cyberview_routes.py` (`relay_live`), `apps/web/src/cyberscan.tsx` (`LivePreview`) | **No**, fake bridge only |
| Stuck detection (`position_sensor`, 30 s status-only polling) | `usbwatch.h`, `cyberview.py` (`SENSOR`) | **No**; threshold from traces |
| Auto-align 35 mm (gap detection, exact 36 × 24 crop) | `services/imaging/frame_align.py`, `docs/auto-align.md` | On library scans only |
| Stitched scans via CyberView Forward/Backward One Step (`film step forward|back N`) | `cvbridge.c`, `cyberview.py` (`control`), `cyberview_validation.json` | **No**, disabled |
| Stitched scans via native nudge (selector 10) | `aflbridge.c`, `native.py` | **No**, disabled |

Evidence files: `research/cyberview/analysis/evidence/usb-trace-2026-10-31.json`
(the hung attempt) and `usb-trace-2026-10-31-scan.json` (the successful scan). Raw
traces and the image are in `data/traces/` on this PC (ignored by git).

## Rules that matter here

- **Ask the user before every scanner action** that moves film or runs a new kind of
  command. They approve per action. Listing sources (`cvbridge sources`) is read-only.
- A command becomes "enabled" only by adding it to a version-controlled validation
  file (`cyberview_validation.json`, `native_validation.json`) after a supervised test,
  with the evidence written down.
- CyberView must be closed (PfsLoader.exe) for any bridge session.
- If the driver hangs at "Preparing film scanner": a USB restart did **not** fix it on
  2026-10-31; turning the scanner off and on and reseating the film did. The stuck
  detector now says so.
- Backward One Frame (32866) hung the driver for 6 minutes. Treat every backward
  command as risky until tested.
- Shell gotcha in this environment: heredocs passed through the Bash tool collapse
  backslashes. For C or Python with `\n`, `\\` or Windows paths, use the Edit/Write
  tools or a script file, not inline heredocs.

## Next steps, in order

1. **Commit** the uncommitted work (with the user's go-ahead), in a few logical
   commits: native backend + catalog, auto-align, protocol + tracer, live preview +
   stuck detection + step commands.
2. **One supervised session on the scanner** (film loaded, CyberView closed). Restart
   the service first so it uses the rebuilt `cvbridge.exe`, and set
   `FRAME_USB_TRACE_DIR=data/traces` for steps a and b.
   a. Scan one frame from the app. Check the live preview appears about 105 s in, is
      the right way round and roughly the right colours. If it is flipped or mirrored,
      fix it in `LivePreview` (and note it in `docs/cyberview-bridge.md`).
   b. Scan two frames in one session. Run `usb_trace.py TRACE --phases` and compare
      frame 1 with frame 2. This shows whether CyberView repeats the 60 s calibration
      for every frame (see "Faster scans" below).
   c. Test the fine moves through the bridge: `film step forward 10`, scan, then
      `film step back 10`, scan, and compare the images (phase shift from
      `frame_align.phase_shift`). If both move and return without hanging, add
      `step_forward` and `step_back` to `cyberview_validation.json` with the evidence.
      That enables the Stitched scan button.
   d. Run one stitched scan from the app and check the 36 × 24 mm crop.
3. **Exposure tables.** From the step 2 trace, run `usb_trace.py TRACE --tables DIR`.
   The 4 KB tables at RAM `0x1f1000-0x1f3000` and 16 KB tables at `0x1f4000-0x1fc000`
   are now logged in full. Change CyberView's exposure (ini `[SETUPDLG DEFAULT PAGE]`
   or per-channel DMin) between two traced scans and diff the tables to find where
   per-channel exposure lives. Then CyberScan X can offer real per-channel exposure.
4. **Faster scans.** Of 180 s per frame, about 60 s is calibration before the first
   pass, 9 s focus and 20 s exposure passes (`docs/scanner-protocol.md`). Candidate
   ini settings for frames after the first: `Manual Set Focus=1` with
   `[SCAN INFORMATION] Focus Value Strip`, and `Is DMin On=1`/`Enable DMin=1` with
   `DMin Value R/G/B`. The bridge applies ini overrides with `--set` before the driver
   loads, but CyberView may only read them at session start, so test whether a second
   session with these set skips the passes (compare `--phases`). Remember the bridge
   restores calibration keys afterwards on purpose (a bad DMin once ruined colour).
5. **Stuck detector on a real stall.** It is tuned from one hung trace (51,000 polls
   in 6 minutes) and one good one (longest quiet gap 7.2 s). Confirm on the next real
   stall that it fires after 30 s with the power-cycle message.
6. Optional: a bounded live line view or CCD diagnostics built from the register
   sequence, never from the unsafe line-reader selectors 1002-1006 (see
   `docs/scanner-protocol.md`).

7. **Match CyberView's colours.** Hidden scans skip the prescan, so CyberView's Auto
   Exposure / Auto Gamma never run and scans look teal. CyberView's algorithm is the
   exported `iComputeAutoColor` in CyberViewX.ds; findings and the plan are in
   [auto-color-re.md](auto-color-re.md). Also: the app's saved preference was set to
   native capture on 2026-10-30, so the user's scans were not going through CyberView.

8. **Standalone (user decision 2026-10-31): no CyberView app or TWAIN, keep the
   scanner DLLs.** Ordered plan in [standalone-plan.md](standalone-plan.md). Done so far:
   exact Python port of CyberView's auto colour (`services/imaging/autocolor.py`).

9. **Standalone done in software (2026-10-31 evening).** Direct capture is the default,
   CyberView is gone from the UI, auto colour is applied to new scans, film-base exposure
   and the driver copy are in place. What still needs the scanner is listed at the top of
   [standalone-plan.md](standalone-plan.md) under "Needs one supervised session".

10. **Supervised session done (2026-10-31 afternoon).** Direct capture works from
    CyberScan's own driver copy; a vendor bug (random register write on every close) was
    found and fixed; film-base exposure, live preview, fine film moves and a stitched scan
    work on the real scanner. Results table in [standalone-plan.md](standalone-plan.md).
    Open: tune the negative-conversion tone against CyberView's output; selector 17.

## Where to look first

- `docs/scanner-protocol.md`: how every layer talks to the scanner, both traces.
- `docs/cyberview-bridge.md`: bridge commands, hidden mode, USB watch, settings file.
- `docs/auto-align.md`: alignment, stitched scans, the two fine-move paths.
- `docs/progress.md`: dated log of what was done and validated.
