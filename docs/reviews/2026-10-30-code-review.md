# Review of Claude changes, 2026-10-30

Reviewed `9b65274..eb842b6`: Electron shell, simulator scan workspace, selected-frame acquisition/recovery, CyberView film-term parsing/cache and imaging integration. This is a review, not an implementation change. Production code was not modified. No scanner, USB, driver or vendor GUI commands were issued by this reviewer.

## Findings

### [P2] Selected-frame scans break subsequent image import

Evidence: `services/api/main.py:82` introduces noncontiguous selected frame indexes, but the import handler at `services/api/main.py:577` still assigns `len(frames_for(roll_id)) + 1`. The unique frame-position index in `services/api/store.py:36` correctly rejects duplicates. `pipeline.save_frame` has already published the original and preview at `services/imaging/pipeline.py:148` before the database insertion at `services/api/main.py:580` fails.

Reproduced in an isolated library: scan `frame_count=3, frames=[2]`, wait for completion, then import an 8x8 PNG. Import returns HTTP 500. The only frame row remains index 2, while the acquisition directory contains two files. The imported file survives on disk but is absent from the library and contact sheet.

Minimal fix: allocate an unused index, normally `max(existing indexes, default=0) + 1`, before saving files. Keep the uniqueness constraint. Handle insertion failures without silently abandoning newly written files; preserve or explicitly reconcile an original already published.

Retained reproduction: `tests/review/test_claude_regressions.py::test_import_after_selected_frame_scan_uses_unused_index`, marked strict xfail for this known defect.

### [P2] Prescan task ownership permits conflicting development and overwrites roll state

Evidence: the new prescan handler assigns `runtime['task']` at `services/api/main.py:396` but leaves `runtime['scan_id']` associated with the previous acquisition. The development guard at `services/api/main.py:279` assumes every active task belongs to that scan. Prescan also retains the original roll dictionary across its awaits and writes it back wholesale at `services/api/main.py:401`.

Reproduced in an isolated library: finish a scan on roll A, start prescan on ready roll B, and start development on B while prescan is awaiting the backend. Development returns HTTP 200. Prescan also returns 200, then saves B's stale `ready_to_scan` status over `developing`. The development session remains `running`. The normal start-scan status gate therefore sees a scan-ready roll despite its active development session. On the first prescan before any acquisition, the same stale ownership assumption instead tries to look up scan ID `None` and can return an unrelated 404.

The test controls scheduling by holding only the synthetic backend's prescan await; it sends no hardware commands.

Minimal fix: record operation kind and roll ownership for prescan as well as acquisition, and use that ownership in development/import/cancel guards. Reload the roll after awaited work and update only the prescan field, or otherwise prevent conflicting state transitions for the operation's full lifetime.

Retained reproduction: `tests/review/test_claude_regressions.py::test_prescan_owns_roll_until_its_result_is_saved`, marked strict xfail for this known defect.

### [P2] Desktop and browser launchers can create competing owners of one library

Evidence: `apps/desktop-shell/src/main.js:31` probes only `FRAME_PORT` or port 8765, but `apps/desktop-shell/src/main.js:34` starts its owned API on an unrelated free port. For ordinary launches, `dataDir` is undefined and `serviceCommand` preserves the same default library (`main.js:35-36`, `service.js:72-78`). The root `package.json` browser launcher starts another API on port 8765. Starting the desktop first and then the documented `npm start` can consequently open the same archive twice. Electron's single-instance lock does not cover the Python launcher.

Consequence reproduced using two independent `create_app` instances and SQLite connections on one temporary library: while owner A's acquisition task was still running, owner B's startup changed A's session to `interrupted`. B then accepted recovery with HTTP 200, and both acquisition workers were running simultaneously. These were synthetic workers, not physical scanner operations. This violates the claimed single owner and can cause conflicting progress, duplicate-position failures and untracked acquisition files.

Minimal fix: use the configured service port for ordinary ownership, with an explicit error/attach path when occupied, and enforce ownership per library across processes. Do not treat the Electron application lock as an archive or scanner service lock. Verify that attaching to an existing service uses the intended library.

## Other observations

- Selected-frame completion still displays the physical frame count as the progress denominator: a one-frame selection from a three-frame roll completes with `completed_frames=1, frame_count=3`; `apps/web/src/main.tsx:44` renders this as 1/3 and a one-third progress bar. Use the selection size for acquisition progress while retaining the loaded roll's frame count separately.
- No new loss of original precision was found in the profile integration. Requested 16-bit scanning remains explicitly labeled while the simulator delivers 8-bit fixtures; original bytes remain separate from profile rendering. Existing workspace tests cover cached profiles after removing the source installation.
- Production `TwainScannerBackend` and `UsbScannerBackend` remain disabled (`services/scanner_host/backend.py:413-439`); the API and client still explicitly use the simulator. Guest CyberView simulator evidence is not evidence of the attached scanner working.

## Executed validation

- `python -m pytest tests/api/test_workspace.py tests/imaging tests/review tests/scanner -q`: **45 passed** before adding the two review reproductions.
- `npm run test:desktop`: **7 passed**.
- `python -m pytest tests/review/test_claude_regressions.py -q -rx`: **2 xfailed**, exit 0, both strict and explicitly identified above.
- `python -m pytest -q`: **106 passed, 2 xfailed in 24.26 seconds**, exit 0.

Additional temporary, uncommitted Python/Node diagnostic scripts reproduced the exact HTTP responses, orphan-file count and two-owner behavior described above. The Node diagnostic inspected shell startup decisions with mocked Electron/service dependencies; it did not launch a GUI. No hardware validation is implied by these tests.
