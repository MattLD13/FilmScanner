# Installed CyberView X MF: native AFL interface investigation

Research date: October 30, 2026 (America/New_York). This pass examines the
**genuine installed MF build**, which differs from the earlier SF web archive.
It does not replace earlier package-specific findings.

The missing-module blocker in the SF archive no longer applies to this install:
`C:\Windows\twain_32\CyberViewX_MF\SCAN08.dll` exists and the project's current
TWAIN bridge already uses it with the physical PF1800 AFL. Direct use of its
model API is feasible, but it still depends on the vendor scanner libraries.
It is not an independent USB driver or proof that every recovered operation is
safe or supported on the unit.

## Evidence and reproduction

The tracked [static evidence](analysis/evidence/installed-native-2026-10-30.json)
contains hashes, imports, exports, selector addresses, scan layout and hidden
setting references. Reproduce without executing vendor code:

```powershell
research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/installed_native_survey.py --output research/cyberview/analysis/evidence/installed-native-2026-10-30.json
```

Tools actually used: Ghidra 12.1.4, pefile 2024.8.26, capstone 5.0.7, Python
3.13, process-local Android Studio JBR. No new tool or driver was installed by
this research pass. Ghidra decompilation and instruction listings are preserved
under ignored `research/cyberview/.artifacts/installed-scan08-*.json`; vendor
binaries and full decompiler output are not distributed. Representative command:

```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
research/.tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless.bat research/cyberview/analysis/workspace.ghidra InstalledSCAN08 -import C:\Windows\twain_32\CyberViewX_MF\SCAN08.dll -max-cpu 2 -analysisTimeoutPerFile 180 -scriptPath research/cyberview/analysis -postScript EvidenceSurvey.java research/cyberview/.artifacts/installed-scan08-ghidra.json
```

All addresses below are preferred-image VAs, not process addresses.

| Module | Version | SHA-256 |
| --- | --- | --- |
| SCAN08.dll | 1.0.3.6 | `da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f` |
| CyberViewX.ds | 1.4.0.0 | `bfe1bac8744320a41d23ee7b51b21b4e0e31004eea4a7a49a68b32b522fd28bb` |
| BeneScan.dll | 1.5.0.0 | `9c824bf80a34ab23faf16fee8af1ca0eb72255c704fcb6169f1ddb475dc09e77` |

## Native boundary recovered

`SCAN08.dll` exports one function at `0x10015390`:

```c
int __cdecl ScannerDeviceIO(int selector, void *parameter);
```

This calling convention follows machine instructions: stack arguments at
`[EBP+8]` and `[EBP+C]`, caller stack cleanup, plain `RET` at `0x10015614`.
Ghidra's incidental `thiscall` inference is incorrect for the export. Do not
derive an ABI from the decompiler prototype alone.

The stack is `SCAN08.dll -> SQ_Scan.dll -> IO_PORT.dll -> FVC.dll -> USBSCAN`.
Its single export dispatches 37 implemented/no-op selector cases, including
seven diagnostic selectors 1001–1007. The complete address map and risk labels
are in the evidence JSON. Unknown selectors return zero. There is no legitimate
reason to execute unknown selectors to see what happens.

| Selector | Static meaning | Evidence / safety consequence |
| --- | --- | --- |
| 1 / 2 | Allocate / free CPU buffers | `0x100080c7` / `0x100081a8`. Freeing buffers is not a scanner disconnect. |
| 3 | Detect and initialize | `0x1000562f` calls USB enumeration and register/control writes. **Not a passive query.** |
| 5 | Open / initialize physical state | `0x1000573d` calls firmware query, lamp state and homing. **Can move the motor.** |
| 9 | Forward/reverse one or more frames | `0x10005aab`, two uint16 fields: direction bit, count. Reverse can hang according to earlier device tests. |
| 10 / 11 | Incremental movement / long travel-eject | `0x10005cfb` / `0x10005e11`. The latter sets count 99 internally. Keep disabled. |
| 14 | Autofocus measurement | `0x10005f91` performs acquisition and computes focus. Requires a separate bounded experiment. |
| 15 / 16 | Get / store focus step | CPU state at `0x10005f70` / `0x10005f82`; the next scan applies the stored step physically. |
| 17 / 23 / 27 | Minimum density / frame border alignment / both | `0x100066a3` / `0x1000687d` / `0x10006e64`. These scan and reposition film. |
| 18 | Last error | CPU state. |
| 19 / 32 | Scan core / flags plus scan request | `0x10006ea9` / `0x10007383`. Core can calibrate, focus and move before image delivery. |
| 21 | Masked device status | `0x1000655d`. Queries hardware; masked bits require real interpretation. |
| 22 | Length-prefixed capability block | `0x100057c0`, max size **0x85**, not the older inferred LC 0x84 layout. |
| 24 | Model code | `0x10006dec`, byte `0x25` (37). |
| 33 | Read saved RGB balance | `0x100076e8`. |
| 35 | Extended capability block | `0x100158c1`, honors caller length. Some unused stack bytes remain undefined. |
| 1001 | Low-level motor command | `0x100144c7`; arbitrary motion must remain disabled. |
| 1002 / 1005 / 1006 | Start / get / stop diagnostic line scan | `0x10014563`; not a safe public live-view feature yet. |
| 1004 | Apply focus | `0x10010da0`; physical focus commands. |
| 1007 | Read status register 3 | `0x100148bf`; static query only, unvalidated. |

The selector-3 parameter must contain a valid pointer to a NUL-terminated string
at offset 0x1C. The function scans it until NUL or `%`, then follows the same
descriptor-probe path either way. It writes vendor[8], product[16], revision[4]
and three status bytes at 0x20–0x22. A null parameter or null string pointer is
unsafe. Selector 5 consumes that returned identity. Its call to `0x100090c9`
checks status register 0x40 and can home with `MotorMoveNormal` (4000-step
request, wait for sensor, then stop). This corrects the tempting but incorrect
classification of connection/detection as read-only.

Selector 20 (0x14) stores three function pointers for optional begin/end/progress
notifications; they are separate from the mandatory image-strip callback. In
`0x100116dd`, a fresh module's three pointers and phase flags are zero. Begin
sets a phase flag only after invoking a non-null begin callback. With all three
callbacks omitted, flags therefore stay zero and no notification is invoked.
Do not register only a begin callback: final phase cleanup calls the matching
end pointer without a null check if its phase flag was set. The startup trace
has no focus-set selector 16; leaving the native module's initial saved focus
zero matches that observed startup rather than imposing a different setting.

**Status initialization is mandatory before the normal native scan.** Selectors
3/5 leave internal film-type byte `0x10018b82` at its initial zero value. Status
routine `0x100135f5`, reached through selector 21 or 12, populates it from the
actual sensors. Scan calibration/transport subsequently branches on strip type
5 versus mounted-film state. Match the observed selector-21 request with two
uint32 values `{0x1F, 0}` and require success plus output bit `0x04` for loaded
strip. Root's successful scan trace contains 58 loaded responses `0x0E` and
mask-4 response `0x04`; later empty startup/reopen traces show `0x08`. Reject an
empty scanner before acquisition. Do not use the older simulator's “bit 0 means
film inserted” interpretation for this genuine build.

Review limitation in the first native experiment: the initial review established
that null notification callbacks were safe, then described the remaining setup
sequence as matching the essential ABI before checking this film-type latch.
The missing explicit status preflight was identified after root's authorized
first direct-DLL scan had begun delivering real rows. That earlier broader
assessment was incomplete. The first experiment must retain this limitation;
successful row delivery cannot retroactively verify the omitted preflight or
prove every calibration/transport assumption. Once the first image callback is
reached, the normal core's calibration and positioning setup has already run;
its callback loop reads/copies rows and completes the transfer, with no new
initialization branch. Further native acquisition requires the corrected status
preflight. Root owns and records the first experiment's actual completion and
image evidence separately.

### First physical native result: complete transfer, invalid RGB

Root's first authorized current-frame prototype run completed normally with 49
strips and a 2479 × 1703 uint16 TIFF, but its image validation **failed**:
channel maxima were `(31600, 0, 0)` and all samples' low four bits were zero.
The personal image stays in ignored `.local/native-device-current-frame.tif`.
This is actual direct-DLL transfer evidence, not usable RGB compatibility or a
completed native backend.

The missing status initialization gives a specific static explanation.
Exposure setup `0x10010ee9` checks film type 5 at `0x1001100a` and the negative
flag at `0x1001100f`. With an unset film type and requested negative media,
the fallback branch computes:

```text
red   = (red_balance // 100) * 0.65
green = (green_balance // 100) // 3
blue  = (blue_balance // 100) // 3
```

The green `IDIV` instructions are at `0x10011048` and `0x10011050`; blue at
`0x1001106c` and `0x10011074`. Normal balance 100 thus produces `(0.65,0,0)`,
matching the observed red-only failure. Correctly detected strip type 5 takes
the ordinary floating-point RGB branch instead. This is a strong causal
explanation, **not a physically verified fix**. The helper's identity LUT
construction and packed request layout match the recovered API; no additional
unverified calibration or exposure commands are justified by this failure.
The corrected status guard and a separately authorized supervised retest remain
necessary before promoting native acquisition.

## Actual scan block

Selector 32 receives a four-byte flags word followed by a 0x48-byte block.
Flags zero enters the normal scan core. Do not copy process pointers out of a
trace; allocate current-process LUTs and callbacks.

| Block offset | Type | Meaning |
| --- | --- | --- |
| 0x00 | uint16 | Requested DPI. |
| 0x04 | float32 × 4 | Left, top, **right, bottom** in inches. These are absolute edges. |
| 0x14 | uint32 | Pixel mode; 7 is RGB with 16-bit containers. |
| 0x18 | uint16 × 3 | Per-channel exposure/balance inputs. |
| 0x1E | uint16 × 3 | Per-channel highlight/exposure modifiers, normal 100. |
| 0x24 | pointer32 × 3 | Three LUTs, each **4096 uint16 entries**. |
| 0x30 | uint8 × 3 | Shadow/DC modifiers. Meaning follows code/logs, not a measured sensor-gain range. |
| 0x33 | uint8 | Maps 0/1/2/3 to 0x80/0/1/2, but the receiving setup function does not use that argument in this build. |
| 0x34 | uint8 | Shifted into an otherwise unused seventh setup argument. No demonstrated effect. |
| 0x35 | uint8 | Values >0x10 select the negative-film calibration/exposure branch. Observed request uses 0x20. |
| 0x38 / 0x3C | uint32 | No reads in normal core; do not invent semantics from their observed values 1 / 0x80. |
| 0x40 | pointer32 | `__cdecl` strip callback. |
| 0x44 | uint32 | Maximum callback strip lines. |

`0x100110af` clamps edges to **2586 × 1708** at 1800 DPI and reverses X
coordinates internally. The old LC-derived decoder names the last two fields
width/height; that name is incorrect for the installed AFL build. The observed
0.03, 0.003, 1.407, 0.95 box produces the existing 2479 × 1703 crop.

Callback block layout:

| Offset | Meaning |
| --- | --- |
| +0x00 / +0x04 | DPI / mode |
| +0x08 / +0x0C | Width / total height |
| +0x10 / +0x14 | Reserved / lines in this callback |
| +0x18 | Set to 1 to request cancellation at the callback boundary |
| +0x1C | Last-strip flag |
| +0x20 | Pixel pointer; copy synchronously before returning |
| +0x24 | Transfer routine result/local state; not buffer capacity |
| +0x28 | **Remaining lines**, not bytes per line |

The root agent's passive interception of the ordinary TWAIN scan on this pass
observed 49 callbacks: 48 × 35 + 23 = 1703 rows, width 2479, mode 7, remaining
lines reaching zero, final-strip flag set. Its local capture is
`.local/native-trace-current-frame.jsonl`; root owns that capture and any
derived physical evidence. This establishes that the vendor model API exposes
genuine progressive rows earlier than the buffered TWAIN transfer. It does not
yet validate the newly authored direct-call acquisition path.

### Precision and rawness

In `0x10011909`, modes 5/7 allocate per-channel expanded tables and repeat each
12-bit table value shifted left four bits across sixteen indices. An identity
LUT of 0…4095 therefore maps to 16-bit container values with 16-unit steps.
This is not evidence of sixteen independent ADC bits. Native output still
passes through vendor ADC, lamp/CCD calibration, exposure/balance and row
alignment routines. Removing CyberView's film inversion/LUT is useful, but the
result should be described as **linear/identity-LUT vendor acquisition** only
after a physical capture demonstrates it. Do not label it untouched sensor RAW.

## Hidden and lesser-known features

These are static findings, not verified device capabilities:

* **Diagnostic progressive line acquisition:** extended selectors 1002/1005/1006
  maintain their own line reader and stop/restart after 1708 lines. This could
  support tooling, but it also initializes hardware and is not a safe live-view
  toggle to expose today.
* **Two CCD paths:** the AFL model log reports CCD 533 or CCD 548. Detection
  `0x10012460` reads `%TEMP%\PF1800AFL.ini`, section `Check CCD`, key `CCDType`.
  Low byte 0x30 forces one branch, 0x21 the other; absent an override it scans a
  short line and decides by thresholds. Incorrect forcing can select wrong
  geometry/timing. Do not create or change this file.
* **Detailed internal log:** `%TEMP%\PF1800AFL.log`, writers `0x10007bd0` and
  `0x10007cdf`, records SDK/FW, CCD branch, film-hole/calibration border, lamp,
  focus, color balance, highlights, shadows, gain and DC. Read existing logs
  without toggling unknown options.
* **Alternate USB identities:** `0x1000831a` accepts 2770:0119, 1606:F000,
  05DA:00CD, 2770:011A and 2770:011B. Only 2770:0119 matches current project
  hardware evidence. The rest may be rebadges/revisions; no identification is
  established.
* **More native resolutions than the TWAIN list:** setup `0x10010999` chooses
  acquisition buckets 300/360/450/600/900/1800 from requested DPI. Static code
  suggests lower native modes exist despite TWAIN exposing an unusable fixed
  list. Physical geometry, sharpness and actual sample rate remain unverified.
* **Hidden settings exist:** CyberViewX.ds stores `Save Raw When Scan`, `Width of
  Raw`, `Height of Raw`, `Write Log`, `MultiSample Pass`, `Multi Scan`, `Is
  SmartTest`, `For QA Use`, manual focus and scan-area flags. Evidence JSON gives
  string VAs and immediate references. Several fields are written with constant
  zero in the settings writer; the presence of a setting name does not establish
  an implemented feature. `Enable ICE` belongs to a multi-model application and
  does not prove the AFL has an infrared channel.
* **The raw-save switch has real code behind it:** getter `0x10027210` reads
  `Others Setting / Save Raw When Scan`. Processing paths `0x100b8d40`,
  `0x100b9390` and `0x1003acb0` consume it; `0x10020320` conditionally writes
  image-memory buffers to four distinct CFile objects for stages 1–4.
  `0x1001ff60` preserves those diagnostic files when enabled, writes the acquired
  width/height settings and `%TEMP%\\5_raw.log`, and removes the temporary
  files when disabled. This establishes a diagnostic image-stage dump path,
  not an unprocessed CCD mode. It has not been enabled or physically tested.
  The four filenames are `1_Raw.raw`, `2_AfterFT.raw`, `3_AfterAG.raw` and
  `4_AfterUC.raw` (string VAs `0x101e9a98`–`0x101e9ac4`). Their names suggest
  film-term, auto-gamma and uniform-color stages, respectively; those expanded
  meanings remain inference until compared with actual buffers.
* **Raw image processing exports:** CyberViewX.ds exports `CIP_RawImg` load,
  write and histogram methods plus `iComputeAutoColor`. These are C++/processing
  APIs, not proof of RAW sensor transfer. Their ABI/lifetimes are unvalidated.
* **Raw film terms are present:** installed `Negative Raw.ft` and `Positive
  Raw.ft` have identity-like LUT entries and a “Raw Image” film name. They are
  vendor color profiles, not an independently established sensor-raw mode.

## Native implementation decision and remaining boundaries

### Root's physical correction result

After the first red-only prototype, the helper gained the required loaded-strip
status preflight. The corrected approved current-frame test returned 49 strips,
2479 × 1703 unsigned16-bit RGB, with channel maxima50160/36800/23792 and all
three channels populated. Both helper runs exited normally. All observed low four
sample bits were zero; effective precision and scanner color accuracy remain
unmeasured. This verifies the correction for one current-frame acquisition,
not native roll transport or complete USB compatibility. Personal originals and
full logs remain in ignored local storage. See [integration results](../../docs/native-scanner.md).

The useful first native step is an isolated x86 helper using the exact installed
`SCAN08.dll` hash and validated dependencies, one scanner owner, current-frame
acquisition only, explicit source/precision metadata, synchronous row copying,
bounded timeouts and atomic TIFF completion. It can remove CyberView's MFC/TWAIN
window and provide true row progress without rewriting USB from guesses.

Keep it opt-in until a reviewed, bounded actual-device run succeeds. Native
initialization itself may home, and new manual positioning/focus/exposure/eject
paths need separate physical evidence and the existing approval rules. A test
against a fake module verifies ABI handling and archival behavior; it does not
verify the scanner. Preserve the current working TWAIN fallback and original
images. Enforce the same exclusive ownership across both backends.

Full independent native USB support remains incomplete: endpoint descriptors,
all control/register and bulk-transfer formats, failure/recovery behavior,
calibration algorithm assumptions, motor bounds and firmware handling are not
fully recovered or validated. No firmware file was flashed, kernel driver
installed, physical command executed, or existing scanner setting changed by
this static-analysis agent.
