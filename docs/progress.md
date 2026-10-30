# FRAME implementation progress

Updated 2026-10-27. FRAME_SPEC.md remains authoritative.

## M0

- [x] Read full specification; workspace originally contained only FRAME_SPEC.md.
- [x] Initialize Git without moving or overwriting the supplied specification.
- [x] Create private MattLD13/FilmScanner GitHub repository.
- [x] Verify local Codex CLI, model catalog and current documented custom-agent schema.
- [x] Configure Sol/high root default and at most three subagents; validate seven TOML files.
- [x] Create persistent contributor rules, shared API contract, build/test/startup commands and dependency evidence.
- [x] Record architecture decision and real-hardware capability limits.
- [x] Final production frontend build and complete startup verification at http://127.0.0.1:8765.

## M1

- [x] Roll metadata and persistent SQLite library.
- [x] Demonstration development session with acknowledged source/settings, elapsed timestamps, agitation schedule and physical transitions.
- [x] Monotonic clock discontinuity detection while service runs, persisted checkpoints and explicit interrupted-session review.
- [x] Connect/load/prescan/positions/acquire through synthetic ScannerBackend.
- [x] Full 36-frame API workflow and jam17 recovery retaining first16 originals.
- [x] Bounded authenticated event stream and reconnect snapshot.
- [x] Separate immutable originals, versioned edits, previews, JPEG/TIFF exports and ordered contact sheet.
- [x] Integrity-checked archive and SQLite metadata backup.
- [x] Restart recovery, cancellation and all injected fault modes in automated tests.
- [x] Connect and visually validate responsive React interface, home saved-image shuffle and complete browser workflow.
- [x] Save tested prototype checkpoint to the private GitHub repository.

M0 and the local simulated M1 vertical slice are implemented. Physical iPhone device access and scanner validation remain distinct, deferred work.

## M1.5: CyberView Reverse Engineering and Virtual Scanner Emulation

**Status: PARTIAL, EXTERNAL BLOCKER (2026-10-28).** Registered as **PENDING** in commit 877fb23 before any M1.5 research. The M0/M1 gate then passed again on 2026-10-27: 41 core tests in 21.33 seconds, TypeScript checks, production build and the full 36-frame browser workflow. M1.5 began automatically under the approved instruction. No existing work or agent was interrupted, cancelled or redirected.

- [x] M0/M1 gate: core tests, client checks/build and existing complete simulated browser workflow pass.
- [x] Preserve official PF1800 AFL Windows v1.3 installer, source provenance and SHA256; extract without executing legacy code.
- [x] Inventory binary versions, hashes, dependencies, TWAIN/driver/configuration files and firmware candidates.
- [x] Perform the initial static investigation of device detection, USB identity, transport, positioning, focus/calibration, image transfer, sensor controls and firmware paths; unresolved AFL-specific protocol details remain explicit.
- [x] Write an evidence-linked reverse engineering report and USB protocol notebook; separate static facts, actual observed interactions, hypotheses and unknowns.
- [x] Evaluate QEMU USB emulation and Python USB/IP; deliver tested passive parsers, management harness and offline exact replay. No PF1800 AFL profile is invented or advertised to a guest.
- [ ] Attempt original CyberView device detection inside an isolated licensed legacy Windows guest; retain actual communication logs and reproducible setup instructions. *(2026-10-28: no-device detection run and traced in the guest; detection against a virtual AFL is still blocked, see below.)*
- [x] Test the implemented harness and replay operations; scanner emulation and sample-image acquisition remain unimplemented without wire evidence.
- [x] Deliver firmware findings, real hardware experiment plan and virtual-versus-physical checklist.
- [x] Revalidate existing FRAME application and simulator tests.

Ownership: one primary reverse engineer (`gpt-6.1-sol`, `xhigh`) and one optional researcher (`gpt-6-luna`, `medium`). Configured roles alone are not claims of active execution. Research stays under `research/`; the production scanner backend and simulator remain unchanged. M2 may proceed independently when resources permit.

Do not install legacy kernel drivers on the main Windows system, modify physical hardware, flash firmware or issue speculative motor commands. Report missing vendor software, analysis tools, licensed guest media, protocol evidence or device traces precisely; never manufacture successful detection or hardware compatibility.

### M1.5 execution evidence so far

- Official manufacturer-linked PF1800AFL package preserved locally: 9,898,119 bytes, SHA256 `EBCBE798FE577B9461DF22DB3BDE6240185E0553E65EB9B93D139D367F9109CF`. Vendor binaries remain ignored; provenance and inventory reports are tracked.
- Reviewed source-built ISx and Unshield parsers extracted 290 payload files without executing vendor software. Embedded CyberView version 1.30/build 20110526 differs from individual PE resource versions; the report retains those distinctions.
- One primary reverse engineer (Sol/xhigh) is tracing actual AFL dispatch in Ghidra. One optional researcher (Luna/medium) handles acquisition, extraction and official guest-media research. No additional M1.5 agents were created. Both were interrupted by an account usage limit, then resumed in their same assignments after the user said to continue.
- The generic PF1800U driver declares VID 05E3/PID 0120, but distinct AFL/U class evidence means that ID is not yet attributed to the physical AFL unit.
- Sixteen portable passive USB/USB-IP parser/harness tests passed as part of a 64-test run. Harness traffic is test-generated metadata, not original CyberView traffic.
- A diskless, stopped QEMU/QMP smoke test has run; no vendor application or Windows guest is claimed from that test.
- The user has no local licensed Windows image and asked to find one online. The official Microsoft Server 2008 Enterprise x86 evaluation VHD and all three archive parts are downloaded and hashed. The included evaluation license permits VHD-capable virtualization; use is internal evaluation only, with no activation. The preserved base is 7,653,676,032 bytes; a disposable overlay is used for the bounded guest attempt. Host hypervisor/security settings are untouched. Actual guest/vendor results are recorded separately from acquisition.
- The official evaluation guest booted in isolated QEMU and reached first-run setup. The saved final screenshot shows the product-key/activation setup page with an empty key field, not CyberView. Computer Use reported a physical Escape-key stop; no further UI control occurred and QEMU was shut down. No key was entered or activation performed. This is a guest-preparation result, not a CyberView detection attempt.

### Current M1.5 result

**Partial implementation; M1.5 is not complete.** Original vendor detection and an attached virtual PF1800 AFL still need testing. The current research deliverables are:

| Deliverable | Actual result |
| --- | --- |
| Binary inventory | Complete 290-file relative-path hash/version/import manifest, with reproducible static extraction. |
| Reverse-engineering report | Ghidra function/address evidence and AFL-versus-U model distinctions. |
| USB protocol notebook | Host API/IOCTL mapping separated from missing wire captures; unknown requests rejected. |
| Virtual scanner | Offline replay engine and loopback USB/IP management harness tested; no evidenced AFL descriptors or successful-response profile yet. |
| Isolated environment | Official evaluation VHD preserved, read-only base/overlay and active resource bounds tested; guest reached setup. |
| Communication logs | Actual QEMU management and test-harness traffic. No original CyberView USB traffic exists. |
| Firmware report | Static candidates and generic updater symbols recorded; no image identified as AFL firmware and nothing flashed. |
| Hardware plan | Bounded original-software capture sequence and virtual-versus-physical checklist. |

The AFL constructor selects `SCAN08`; the examined BeneScan loader requests that model's external DLL. No standalone `SCAN08.dll` exists in the official archive. This is a likely packaging dependency gap, pending runtime confirmation or evidence that another installation path supplies it. PF1800U.dll and its VID/PID are not substituted.

### M1.5 completion pass, 2026-10-28 UTC

**Outcome: PARTIAL, EXTERNAL BLOCKER.** Completed static work on the directive's packages A, C and D, without executing vendor code:

- **SCAN08.dll: still unresolved, but sharper.** The AFL is BeneScan model 37 → `SCAN08.dll`, which is absent from the payload. The package contains two SCAN08-lineage builds ("SQ Scan08 ASIC"). `LC.dll` has a SCAN08.DLL 1.0.9.4 version resource, and WIA `PF1800LC.Dll` has the export name Scan08.dll 1.0.0.1. Instruction cross-references bind both to the **1800P / "Low Cost"** model 42, not the AFL. Gamma file numbers match model codes. Neither is renamed or substituted. Details: `research/cyberview/scan08-investigation.md`.
- **Candidate USB identities, not attributed to the AFL:** `2770:011C`, accepted by LC.dll and PF1800LC and bound by the LC/PF3600U INFs, and `0461:034A`, accepted only by the 2002 Scan08Dll build, with no INF. No INF in the package names an AFL.
- **SQ host stack mapped statically:** LC.dll → SQ_Scan → IO_PORT → FVC → `\\.\USBSCAN%d`, with 2-byte bulk register framing. This is the 1800P path. Whether the AFL uses it is INFERRED only.
- **Runtime baseline: captured (GUEST OBSERVED), in a second pass the same day.** The user completed OOBE in the QEMU window with no product key and their own password. A first attempt hung after a key was typed; it was reset to the restore point. The user authorized bounded guest input and accepted the CyberView EULA in chat. That EULA's section 4 forbids reverse engineering; the user's right-to-repair position is recorded. The install showed no driver prompts and installed no SCAN08.dll. With no scanner, `PfsLoader.exe` loaded CyberViewX.ds and BeneScan. BeneScan probed model records 18→1, loaded the 6 present modules (LC pulled in the SQ_SCAN/IO_PORT/FVC stack), and searched 5 paths for **SCAN08.dll without loading it**. CyberView then showed "Unable to communicate with the Film Scanner" and exited. The kernel trace lost 0 events. **SCAN08.dll is therefore genuinely missing after runtime verification for the official web package.** `research/cyberview/runtime-baseline.md`, `analysis/evidence/runtime-baseline-2026-10-28.json`.
- **Guest tooling:** results leave the network-less guest on a blank FAT12 floppy that the host reads offline. Guest input goes only through QMP and is logged. QMP media swaps are limited to hash-recorded media.
- **Virtual device: unable to build an evidence-backed AFL profile.** QEMU 11.1 `usb-redir` (socket chardev, `pcap=`) is the chosen architecture, with a Python usbredir server and `replay.py`. It is not built, and no guest-visible device was presented. With this package, no USB device can be recognized through the AFL class while `SCAN08.dll` is missing. `research/usb/virtual-device-feasibility.md`.
- **Simulated AFL, at the user's request (GUEST OBSERVED against a SIMULATOR).** The model-module contract was recovered from SCAN08-lineage LC.dll with Ghidra: identity, the 0x84-byte capability block with the model code at +0x74, status, and the strip-callback scan. A labeled FRAME `SCAN08.dll` (model `0x25`, synthetic image, every call logged, no device I/O) was built with MSVC x86 and placed only in the guest. Original CyberView **detected and opened it, showed its main window (1800 dpi, 1.386 × 0.948 in, Location 1), prescanned, and scanned `image001.tif` (416×284 RGB, 300 dpi)**. The captured scan request is decoded in `analysis/afl_contract.py`. Learned on the way:
  - a **second packaging gap**: model 37 reads film terms from `GAMMA\*.ft`, which is empty, and CyberView crashes at `+0xcf74` without them. The guest run used a test-only copy of `GAMMA\Original`;
  - status bit 0 means "film inserted" and starts an automatic Final Scan.

  This is not USB emulation and not device evidence. `research/cyberview/afl-simulator.md`.
- Hardware plan gains CD/VID checks and a stop condition: halt if CyberView names a model other than PF1800 AFL. It now also checks the CD for model-37 film terms.
- Validation: `python -m pytest -q tests/research` → 29 passed; `python -m pytest -q` → **78 passed in 22.77 s**; `npm run lint` and `npm run build` passed; `npm run test:e2e` passed (36 frames, 16-bit TIFF inspected, no JavaScript exceptions).

Exact blockers and the minimum input that unblocks each:

| Blocker | Minimum real-world input |
| --- | --- |
| ~~No CyberView no-device baseline~~ | Resolved 2026-10-28. |
| AFL model module `SCAN08.dll` and model-37 film terms absent (runtime-verified) | Original PF1800AFL CD (hash and inventory), or a genuine vendor package containing them. |
| Guest-visible virtual AFL device (spec "Done" item) | Requires the two rows below; without them no truthful profile exists. |
| AFL USB identity and descriptors | The physical unit's enumeration in an isolated guest (VID/PID, full descriptor set). |
| Initialization, status and image responses | Original-software traces, one action at a time, per `hardware-plan.md`. |

The Windows 11 compatibility-mode question is documented in `research/cyberview/windows11-compatibility.md`: an application-only test remains worthwhile and unattempted. Compatibility settings do not translate the extracted x86 kernel drivers for this 64-bit host. Successful application startup would not establish scanner operation.

## Windows desktop shell (started 2026-10-28)

**Status: first slice working.** The user asked for a Windows 11 app with an Electron UI built on the M1.5 findings. `apps/desktop-shell` opens the existing React client and Python service in a native Electron 44.7.1 window. It attaches to a running service on 8765, or owns one on a free loopback port. The page is sandboxed, navigation is locked to the service origin, and every non-loopback request is cancelled. CyberView features are being rebuilt in FRAME's own UI, not copied from Pacific Image's design or assets. The scanner backend is still the simulator; real AFL USB access stays disabled until traces from the physical unit exist.

- [x] Shell, attach-or-own service lifecycle, single instance, hardening.
- [x] `npm run test:desktop`: 7 unit tests. `npm run smoke:desktop`: real Electron launch, page authenticated, `/api/state` 200, screenshot `docs/screenshots/desktop-shell.png`.
- [ ] Installer and bundled Python (M6). Electron upgrade to 44.10.0 or later on or after 2026-11-10 (GHSA-jr5w-w6x2-84p9, mitigated meanwhile).
- [x] CyberView-equivalent scan workspace (2026-10-28), in FRAME's own design, on the simulator. Details below.
- [ ] AFL-state-aware simulator behavior from `research/cyberview/afl-simulator.md`: film-inserted status, auto Final Scan, frame location.

### Scan workspace

The Scan page gains a workspace panel. Screenshot: `docs/screenshots/desktop-scan-workspace.png`.

- **Prescan roll** (`POST /api/rolls/{id}/prescan`): low-resolution synthetic preview of every frame, stored on the roll.
- **Frame strip**: view or select frames. `POST /api/scans` accepts `frames` and scans only those.
- **Scan window**: drag on the viewer or type percentages. The simulator crops the acquired frame to it.
- **Exposure**: per-channel gains of 50–200%, applied by the simulator at acquisition.
- **Resolution and color depth**: requested values are recorded per frame in `scan_settings` next to what was `delivered` (always an 8-bit synthetic fixture).
- **Film profiles**: `GET /api/film-profiles` reads CyberView `.ft` files from the user's install (`%WINDIR%\twain_32\CyberViewX_SF\GAMMA` or `FRAME_FILMTERM_DIRS`).
  - All 132 files in the official package parse, giving 82 unique profiles. Variants handled: CRLF, a trailing `;`, `B&&W` as the black-and-white class, and 4096-row tables with values up to 4095.
  - A chosen profile is applied after inversion as table then matrix (INFERRED ordering). It is cached in the library, so edits and exports survive uninstalling CyberView.
  - Many CyberView 3600u slide profiles share one identical table and matrix; that is vendor data.
  - FRAME distributes no vendor profile; tests use fictitious ones.
- Validation: `python -m pytest -q` → 106 passed (12 new workspace tests). `npm run lint` and `npm run build` passed. `npm run test:e2e` passed with prescan, profile, dragged 20–80% window and exposure R 105%, checking `scan_settings` on all 36 saved frames. `npm run test:desktop` 7 passed; `npm run smoke:desktop` passed.

## CyberScan X interface preview on October 30 2026

The user authorized work on a modern CyberView-style skin while explicitly
forbidding scanner connections by the software. A separate local-only renderer
now implements a dark CyberScan X scan studio with a large viewer, filmstrip,
image adjustments, local import, transforms, visual guides, session library and
JPEG/JSON preview exports. Demo photos are labeled and are not the user's Gold200
scans. The theme is confined to the page; no Windows appearance setting is changed.

`npm run preview:skin` serves only static files on127.0.0.1:8770. It imports no
FRAME API or scanner host. Connect/Prescan/Scan are disabled. A separate browser
test checks desktop and390px layouts and verifies zero API requests, zero event
sockets and zero external requests. This work did not start the scanner service,
run device discovery, open VueScan/CyberView, send a USB/TWAIN command or change a
driver. Existing production UI and backend workflows remain separately available.

`npm run lint`, `npm run build` and `npm run test:skin` passed. The skin test caught
and fixed missing accessible names on the adjustment sliders. Evidence and scope:
[skin notes](cyberscan-skin.md), [validation](cyberscan-validation.json),
[desktop screenshot](screenshots/cyberscan-desktop.png) and
[phone screenshot](screenshots/cyberscan-phone.png). Scanner integration and the
native desktop entry for this skin remain future work, subject to authorization.

## M2: Image processing and archival reliability

**Status: IN PROGRESS, independently of M1.5.**

- [x] Preserve unsigned 8/16-bit RGB/grayscale TIFF samples, including little/big endian and orientation handling.
- [x] Keep floating-point samples through processing and export true 16-bit RGB TIFF with original hash, edit/version, nominal sRGB profile and separate source/acquired/output precision metadata. JPEG/previews remain 8-bit.
- [x] Manual normalized film-base controls; older clients preserve an existing base when they omit that new setting.
- [x] Reject unsupported high-precision input rather than silently discarding sample precision.
- [x] Inject an export write failure and verify originals and prior exports remain byte-identical.
- [x] Nine imaging tests, independent-process export reproduction and full browser workflow pass; browser test inspects actual 16-bit TIFF tags and saves manual film-base settings.
- [ ] Photographic negative reference comparisons and calibrated color validation.
- [ ] Crop/curves, broader codecs, large-image memory benchmarks and portable restore acceptance.

Latest combined run at this checkpoint: `python -m pytest -q` →64passed in 21.63 seconds (including 16 research tests); client checks/build and complete 36-frame browser workflow passed. The already running M1 service was not restarted. New service processes use `frame-density-2`; the client shows new film-base controls only when that engine is reported, preserving compatibility until the next normal service restart.

The repeatable nominal 4.34-megapixel synthetic TIFF benchmark is `python scripts/benchmark_imaging.py`; the recorded run rendered in 0.671 seconds with 416,628,522 bytes of tracked Python/NumPy allocations during rendering. The measurement excludes preallocated input and full process RSS and is not scanner performance. Larger input benchmarks and a lower-memory pipeline remain open.

## Executed validation

- `python -m pytest -q`: **41 passed in 21.04 seconds**. Includes 17 scanner tests and 7 independent review regressions, a 36-frame scan, jam at frame 17/recovery, cancellation, all simulator faults, authenticated HTTP/WebSocket access, originals/contact-sheet corruption rejection, and actual independent service-process restart. Restart preserves an active development timestamp, archived metadata and exact TIFF export bytes.
- `npm run lint`: passed TypeScript no-emit validation.
- `npm run build`: passed TypeScript and Vite 6.4.5 production build.
- `npm run test:e2e`: passed against an isolated real local service and Chromium. Actual UI controls create/develop/transition/connect/scan/shuffle/search/edit/download/archive; a 390×844 mobile context received a completed preview while scanning continued and reconnected to the current snapshot. Rehearsal timers ran at actual elapsed speed, including reload. No JavaScript exceptions were recorded.
- Initial client dependency audit: zero reported vulnerabilities.
- Screenshots: docs/screenshots/desktop-empty.png, desktop-home.png and iphone-home.png. Phone evidence is Chromium emulation, not a physical iPhone or Safari test.
- The interactive Chrome inspection also created a demonstration roll and started its water rehearsal. Browser-control tooling later stopped because it could not confidently verify the current URL. The isolated automated workflow completed successfully; the live demo may still show a practice confirmation dialog/session for the user to dismiss or continue.

The first remote checkpoint's CI failed because the client had not yet been committed. The initial finished M1 checkpoint then passed Windows CI. Subsequent Windows CI runs exposed concurrent access to the shared SQLite connection in a recovery test (`sqlite3.InterfaceError`); root serialized store operations, transactions and cursor consumption with a lock and added a six-thread read/write regression. The fix passed [Windows CI](https://github.com/MattLD13/FilmScanner/actions/runs/40609045952) at commit 67e746f. Latest local validation: **71 tests passed in 21.86 seconds**, client checks/build passed, and the full browser workflow passed with 16-bit TIFF tag inspection.

## Actual agent assignments

- Root: API, persistence, developing, imaging, integration, test harness and repository.
- Scanner agent, gpt-6.1-sol/high: scanner host and scanner tests; 17 targeted tests passed.
- Interface agent, gpt-6.1-terra/medium: responsive client and initial build/type checks, completed; root integrated and expanded workflow tests.
- Research agent, gpt-6-luna/medium: project agent configuration, model/runtime and dependency evidence; seven TOML files parsed.
- Independent reviewer, gpt-6.1-sol/high: substantial correctness/security review and seven passing regressions; fixes integrated by root.

The initial M0/M1 pass used no reverse-engineering or dedicated image subagent. M1.5 later activated the reverse/research assignments recorded above; root handled the independent M2 precision work. Configured roles are templates, not claims of execution. The root session's model was not retroactively changed. No per-agent token-cost telemetry was exposed; no cost total is invented.

## Remaining boundaries

No physical scanner/driver/USB verification; no public service or LAN companion access. UI phone viewport testing is distinct from physical iPhone testing. PWA background alarms cannot be guaranteed. Simulator fixtures remain 8-bit synthetic charts. The independent M2 engine now preserves supported 16-bit TIFF input and renders 16-bit processed TIFF; this never upgrades a claim about acquired precision. Full color calibration, custom chemistry/batches, portable restore, full offline developing synchronization and Windows packaging remain backlog work. M1.5 guest/vendor detection remains incomplete until genuinely executed and documented.
