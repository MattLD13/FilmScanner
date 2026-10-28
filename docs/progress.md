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

**Status: IN PROGRESS.** Registered as **PENDING** in commit 877fb23 before any M1.5 research. The M0/M1 gate then passed again on 2026-10-27: 41 core tests in 21.33 seconds, TypeScript checks, production build and the full 36-frame browser workflow. M1.5 began automatically under the approved instruction. No existing work or agent was interrupted, cancelled or redirected.

- [x] M0/M1 gate: core tests, client checks/build and existing complete simulated browser workflow pass.
- [x] Preserve official PF1800 AFL Windows v1.3 installer, source provenance and SHA256; extract without executing legacy code.
- [x] Inventory binary versions, hashes, dependencies, TWAIN/driver/configuration files and firmware candidates.
- [x] Perform the initial static investigation of device detection, USB identity, transport, positioning, focus/calibration, image transfer, sensor controls and firmware paths; unresolved AFL-specific protocol details remain explicit.
- [x] Write an evidence-linked reverse engineering report and USB protocol notebook; separate static facts, actual observed interactions, hypotheses and unknowns.
- [x] Evaluate QEMU USB emulation and Python USB/IP; deliver tested passive parsers, management harness and offline exact replay. No PF1800 AFL profile is invented or advertised to a guest.
- [ ] Attempt original CyberView device detection inside an isolated licensed legacy Windows guest; retain actual communication logs and reproducible setup instructions.
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

The Windows 11 compatibility-mode question is documented in `research/cyberview/windows11-compatibility.md`: an application-only test remains worthwhile and unattempted. Compatibility settings do not translate the extracted x86 kernel drivers for this 64-bit host. Successful application startup would not establish scanner operation.

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
