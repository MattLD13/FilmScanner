# Native feature port and physical validation plan

This describes implemented interfaces and CPU-only evidence. It does not promote
any new hardware action/configuration in `native_validation.json`. The primary
agent is the sole hardware operator for this task.

## Acquisition and protocol

`ScanOptions.auto_exposure` defaults to `false`. The usual eleven acquisition
settings remain valid. A twelfth optional `0`/`1` field selects vendor exposure:

```
settings DPI BITS CHANNEL FILM LEFT TOP RIGHT BOTTOM RED GREEN BLUE [AUTO_EXPOSURE]
```

Omitting the field resets it to false even after a prior true request. Trailing
garbage and other flag values are rejected without changing current settings.
True requires both experimental settings and the separate `auto_exposure`
control allowlist. The Python configuration gate requires that validated action
plus a previously validated underlying acquisition configuration. Older evidence
JSON is normalized through `ScanOptions`, so omitted optional fields cannot make
old validated settings appear unvalidated. Border-search options explicitly set
the flag false; a planned archival capture may use true once its gate is promoted.

The exact vendor selector-32 request receives `flags=1`; the helper does not
substitute a new exposure formula. RGB identity LUTs remain unchanged for all
supported depths, including 8-bit output. Grayscale/positive/alternate DPI and
custom windows were already parsed by the native helper; their availability
still depends on real configuration evidence, not the fixture.

After the vendor call, an event records requested exposure and the original
caller-block exposure values. `effective_exposure` deliberately remains null.
The caller block is not proof of what the vendor used internally.

### Static auto-exposure evidence and caveat

These preferred-base addresses refer only to pinned SCAN08.dll SHA-256
`da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f`.

- Selector 32 / `0x10007383`: bit 0 takes the vendor auto-exposure branch.
- `0x100073cf`: copies the 0x48-byte acquisition block to a local block, sets
  300 DPI and RGB8, and invokes `0x10007739` to acquire its preview.
- `0x10007459`: invokes exposure calculation `0x10004a7f` with preview data and
  dimensions. Computed R/G/B are stored at globals `0x100187c8/c6/c4`.
- If preview output already matches requested DPI/mode and the exposure result
  requires no rescan, the wrapper delivers the preview through caller callbacks.
  Otherwise `0x100075af` copies the original request again, places computed
  exposure into its local block, then invokes the regular scan core at
  `0x100075ef`.
- Selector 33 / `0x100076e8` reads *different* globals `0x1001821a/1c/1e`.
  Its default `100/100/100` report is not evidence of computed auto exposure.
- The preview branch tests stack local `[ebp-0x58]` after the preview helper;
  the bounded disassembly does not establish a clear result assignment in that
  branch. Runtime behavior must be tested, not inferred from the fake model.

Reproduction uses static file reads only:

```
research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/colour_survey.py --module C:/Windows/twain_32/CyberViewX_MF/SCAN08.dll --function 0x10007383 --limit 0x400
research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/colour_survey.py --module C:/Windows/twain_32/CyberViewX_MF/SCAN08.dll --function 0x100076e8 --limit 0x51
```

## Position/focus interfaces

- `film goto N` was already implemented as bounded selector-12 counter reads
  plus single-step selector-9 moves, checking each resulting counter. Targets
  are 1–40 relative to the vendor session counter, not physical encoder locations.
  Cancellation is now checked after each move before declaring it complete.
- `focus N` stores a bounded 0–200 value through selector 16 and verifies it
  through selector 15. A scan applies the stored focus. The interface's 200-step
  ceiling is not physical evidence that every step in that range is useful/safe.
  Begin validation by reading and restoring adjacent values around a known focus.
  After physical testing, an optional `focus_range: [low, high]` in validation
  evidence restricts manual dispatch to the tested interval. The Python gate
  validates two ordered integer bounds inside 0–200 and rejects out-of-range or
  noninteger requests before any process or command starts. Malformed evidence
  disables focus instead of silently restoring the broad model range. Capabilities
  expose the interval to the UI. Omitted range retains legacy 0–200 parameter
  bounds but does not itself enable the focus action.
- `film realign` invokes selector 23 only after an initialized same-session
  acquisition. It must retain the same vendor frame counter and requires a fresh
  optical verification afterward. Counter agreement alone does not prove borders.
- No undocumented hardware counter setter was added. A UI reset should record a
  software frame-origin label without motor motion or a fabricated hardware write.
- A successful scan emits `frame_position` with a one-based vendor counter.
  `NativeAflBridge.last_frame_position` mirrors confirmed scan/move events and
  is cleared on startup/release/eject or before an operation that could change it.
  Focus/calibration command events no longer invent a frame-1 position.

## Suggested bounded physical sequence

1. Confirm exclusive ownership; preserve current loaded film and all existing
   validation evidence. Make an ordinary known configuration scan to initialize
   transport, retain its frame position, identity-LUT TIFF, log, and SHA-256.
2. Vendor auto exposure: in the same session, try a bounded 300 DPI RGB8 flag-1
   acquisition first, then 1800 DPI RGB16 if that succeeds. Record requested and
   actual delivered modes, timings, original caller-block metadata, and the
   vendor's own exposure log/trace. A fixture pass does not promote this action.
3. Modes: one configuration at a time, low DPI first. Verify actual TIFF samples,
   channels, dimensions, bits, declared DPI, and meaningful nonflat scene content.
   Retain a negative-film baseline before positive-mode testing. A positive-mode
   capture of loaded negative film is not validation of actual slide handling.
4. Manual focus: record current focus; set an adjacent bounded value, capture a
   sharpness comparison, and restore it. Goto: one known neighboring frame and
   return, with raw vendor counters and fresh optical images. Do not seek beyond
   a known loaded strip just because the numerical target is within 1–40.
5. Realign: one selector-23 operation on an initialized frame, followed by the
   low-resolution optical border check. Invalidate any old preview coordinates.
6. Mounted-slide handling requires an actual appropriate mount, physical loading,
   and independent media/status evidence. It remains unverified with a film strip.

Stop after uncertain motion, cancellation, or timeout. Do not use additional
status commands to probe a busy/hung vendor call. No new mode or control is
automatically promoted by this document.

## Verification performed here

```
powershell -NoProfile -ExecutionPolicy Bypass -File services/native_bridge/build.ps1 -Fixtures
python -m pytest -q tests/native/test_native_bridge.py tests/scanner/test_native_gate.py
```

Build passed. Native production helper SHA-256 after the port:
`11761A16BF899735F82A399FCAEE06A5E6E59D9453C9272994EA78D4C58E2135`.
The latest tests passed **46 in 4.35 seconds**, using the synthetic model DLL and
scanner gate fixtures. They verify exact flag dispatch, optional-protocol
backward compatibility, source-mode preservation, bounded goto/focus, realignment
counter failure, truthful position metadata, and old-evidence normalization.
No physical device I/O was issued by the scanner-port agent.

Subsequent Python-only focus-interval checks passed **10 tests in 0.34 seconds**:
`python -m pytest -q tests/native/test_native_bridge.py -k 'recorded_focus_range or focus_range_without'`.
No native rebuild or scanner/fixture process was performed for that follow-up,
so it did not interrupt the primary agent's physical validation sweep.
