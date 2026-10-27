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

## Executed validation

- `python -m pytest -q`: **41 passed in21.04seconds**. Includes17scanner tests and7independent review regressions, a36-frame scan, jam17/recovery, cancellation, all simulator faults, authenticated HTTP/WebSocket access, originals/contact-sheet corruption rejection, and actual independent service-process restart. Restart preserves an active development timestamp, archived metadata and exact TIFF export bytes.
- `npm run lint`: passed TypeScript no-emit validation.
- `npm run build`: passed TypeScript and Vite6.4.5 production build.
- `npm run test:e2e`: passed against an isolated real local service and Chromium. Actual UI controls create/develop/transition/connect/scan/shuffle/search/edit/download/archive; a390×844 mobile context received a completed preview while scanning continued and reconnected to the current snapshot. Rehearsal timers ran at actual elapsed speed, including reload. No JavaScript exceptions were recorded.
- Initial client dependency audit: zero reported vulnerabilities.
- Screenshots: docs/screenshots/desktop-empty.png, desktop-home.png and iphone-home.png. Phone evidence is Chromium emulation, not a physical iPhone or Safari test.
- The interactive Chrome inspection also created a demonstration roll and started its water rehearsal. Browser-control tooling later stopped because it could not confidently verify the current URL. The isolated automated workflow completed successfully; the live demo may still show a practice confirmation dialog/session for the user to dismiss or continue.

The first remote checkpoint's CI failed because the client had not yet been committed. Final-source CI status is tracked separately; local results above are actual successful runs.

## Actual agent assignments

- Root: API, persistence, developing, imaging, integration, test harness and repository.
- Scanner agent, gpt-6.1-sol/high: scanner host and scanner tests; 17 targeted tests passed.
- Interface agent, gpt-6.1-terra/medium: responsive client and initial build/type checks, completed; root integrated and expanded workflow tests.
- Research agent, gpt-6-luna/medium: project agent configuration, model/runtime and dependency evidence; seven TOML files parsed.
- Independent reviewer, gpt-6.1-sol/high: substantial correctness/security review and seven passing regressions; fixes integrated by root.

No reverse-engineering or dedicated image subagent was activated. Configured agent roles are templates, not claims of execution. The root session's model was not retroactively changed. No per-agent token-cost telemetry was exposed; no cost total is invented.

## Remaining boundaries

No physical scanner/driver/USB verification; no public service or LAN companion access. UI phone viewport testing is distinct from physical iPhone testing. PWA background alarms cannot be guaranteed. Simulator fixtures are 8-bit synthetic charts; image pipeline is an initial density inversion with 8-bit sRGB exports. Full M2 color calibration, 16-bit output, custom chemistry/batches, portable restore, full offline developing synchronization and Windows packaging remain backlog work.
