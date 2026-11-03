# Working-copy review and commit record

Prepared November3,2026. This is a bounded review of dependencies and the recent
scanner guard paths, not a complete audit of every accumulated change. The review
initially left files unstaged; the subsequent user-authorized commit work is
recorded below. Earlier validation and hardware observations retain their scope.

## November 3 commit execution

The final sequence combines the capture, imaging and client groups because they
share recipe contracts and workflow state. It preserves usable intermediate
trees instead of splitting large shared files into incomplete features.

1. `c8e588e` — restrict desktop fullscreen to FRAME's local main frame.
2. `b097091` — gated independent USB research workbench; no production acquisition.
3. `2df43e1` — transactional simulator-archive roll deletion.
4. `5ed878e` — capture/imaging/client integration: optical plans, guarded transport, native
   modes, optional processing, preview/favorite workflows and responsive themes.
5. Documentation and simulator-generated screenshots — current engineering
   handoff, retained measurements, failures and remaining hardware limitations.

Validation used exported git-index trees under ignored `.local/staged-validation/`
to avoid accidentally relying on other unstaged source. No scanner commands were
issued. The backend-only staged tree passed the full `python -m pytest -q` suite:
**427 passed, 63 skipped, 2 xfailed in 507.60 s**. The skips include optional
compiled/local-vendor checks; they are not hardware passes. After building the
staged Windows helpers with `services/native_bridge/build.ps1 -Fixtures` and
`services/cyberview_bridge/build.ps1 -Tests`, the integration tree passed **83 tests**
in `tests/native/test_native_bridge.py`, `tests/scanner/test_usbwatch.py`,
`tests/imaging/test_vendor_autogamma.py`, `tests/imaging/test_vendor_negative.py`
and `tests/imaging/test_sensor_precision.py`. This targeted result overlaps the
full suite and must not be added to its pass count.

`npm run build`, `npm run test:native-ui`, `npm run test:e2e` (36 simulated frames)
and `npm run test:skin` passed. The native UI log also contains a Windows asyncio
connection-reset callback during teardown; the workflow returned success with no
browser exceptions. `npm run test:live-preview` initially missed its short-lived
half-transfer state under concurrent workflow load; an unchanged serial retry
passed. Its fake scanner transfer pause was extended from 0.35 s to 1.5 s, and the
final staged build/live-preview check passed. Production timing was unchanged.
The only source change after the broader checks was this fixture pause/comment.

The earlier groups passed 8 desktop tests, 71 offline driver tests, and 12 API
workflow tests. The latter two groups and desktop checks were also checked in an
export of the staged archive tree. `git diff --cached --check` passed. Local logs
are `.local/commit-*.log`; they are deliberately excluded from source commits.
Preview tone stays off by default. No push, library data, runtime state, generated
executables, installed vendor DLLs or acquired user photographs are included.

## Finding discovered and fixed during review

**P1 — native position-sensor failure force-terminated its helper at review start.**

`services/scanner_host/cyberview.py` returns early from `_exchange` on a
`position_sensor` error, then `scan()` calls the backend's `_stuck()` method.
At review start, `services/scanner_host/native.py::_stuck()` called `_kill()` and
only reset frame initialization/counter state. It did not quarantine the session
or latch transport uncertainty. This pre-existing path was outside the newer
timeout reservation behavior and contradicted a blanket claim that all blocked vendor
calls retain device ownership until return or deliberate hardware recovery.

A no-I/O reproduction instantiated the native host with the fake-helper path and
replaced `_kill` with an asynchronous mock. Calling `_stuck()` requested one kill,
left `quarantined=false` and `transport_position_uncertain=false`, and cleared
frame initialization. No scanner command or actual process termination was used.

The native path now latches uncertainty and quarantines a still-active session,
requests cancellation without killing the helper, and retains its process/mutex.
A terminal ready event permits the reservation to end but does not clear position
uncertainty. A ready event received before the error handler is also handled so
an already-returned call is not left falsely quarantined. The rapid-return fake
API case keeps the session open and uncertain until explicit recovery.

New regressions exercise the `position_sensor` dispatch through `scan`, retention
of a mocked live helper without `_kill`, release refusal while blocked, and the
terminal-ready race. These are software/no-I/O checks; physical sensor-loop
cancellation has not been newly qualified.

## Arithmetic/documentation correction

The current statistics rule is `bottom <= .05*height` and
`side <= .05*width`, with each side8 pixels at1800 DPI. Thus height800/width160
is eligible, height799 or width159 is not. Both sides together can occupy10%
at the smallest eligible width. Width320 corresponds to a different rule:
both side margins together at most5%. The review response has been clarified
to describe the actual per-side implementation; no policy/code change was made.

## Proposed logical groups

These are candidate commit boundaries. Large shared files need hunk extraction
and dependency checks; this is not an instruction to stage each entire file in
every group. Do not claim an intermediate commit builds until it has been tested
from its own tree.

| Order | Suggested commit subject | Responsibility and boundaries |
| --- | --- | --- |
|1|`Allow fullscreen only for FRAME's local main frame`|Desktop shell `src/main.js`, `src/service.js`, and `test/service.test.js`. Independent of scanner changes.|
|2|`Add the gated independent USB research workbench`|New `custom_driver.py`, `custom_protocol.py`, `usbscan_transport.py`, `custom_validation.json`, their two scanner test modules, `driver:console` package script and research/setup documentation hunks. This remains separate from the normal vendor-assisted acquisition backend.|
|3|`Add transactional saved-roll deletion`|`services/api/store.py::delete_many`, roll-deletion route hunks in both API modules, related client deletion controls and API/workflow tests. Preserve the file staging/database rollback/active-operation checks together.|
|4|`Implement verified native capture planning and guarded roll transport`|Native bridge/host/settings/evidence gates; optical planner, border detection, film classification and repeats/precision support; required API orchestration, contracts, capture controls and associated tests. Include the sensor-failure fix and its regressions. Several of these features share the same state machine, so a coherent larger integration commit is preferable to incomplete file-based fragments.|
|5|`Add reversible negative conversion and optional preview tone`|Negative/model/film conversion, CPU tone worker, statistics guard, recipe/UI/API hunks and imaging/API tests. Keep preview tone off by default, and preserve explicitly selected favorite tone and legacy recipes. Depends on the capture/recipe contracts in group4.|
|6|`Apply film themes and responsive workspace refinements`|`film-theme.tsx`, `film-lab.css`, `film-develop.css`, remaining client/style hunks and UI/layout tests. Some theme imports must land with their assets or be included earlier as a dependency.|
|7|`Document measured validation and remaining hardware limits`|Current handoffs, feature/acceptance/vertical/processing reports, conversation summary, README/backlog/capability updates and captions for approved synthetic screenshots. Historical physical evidence remains historical; don't relabel it as hardware validation of the later guards.|

If groups4/5 cannot be separated without duplicating transitional API state or
breaking recipe behavior, combine them into one capture/imaging integration
commit. Split by independently reviewable behavior, not arbitrary file counts.

## Material that stays outside source commits

- `.local/`, `data/`, archive databases, authentication/runtime state and acquired
  user photos/TIFFs.
- Installed vendor DLLs/tables, generated helper executables and binary research
  artifacts. The versioned manifests/evidence gates remain source inputs.
- The three modified `docs/screenshots` images are generated by the simulator
  workflow (`run_workflow.py` connects to the simulator and labels output as a
  synthetic fixture). They belong with UI/documentation, not hardware evidence.

A basic changed/untracked-text pattern check examined83 files without printing
their contents and found no candidate private-key/provider-token literals. This
is not a comprehensive secret audit or permission to include ignored files.

## Checks performed in this review

- `npm run test:desktop`:8 passed.
- `python -m pytest -q tests/scanner/test_custom_driver.py tests/scanner/test_usbscan_transport.py`:
 71 passed in.87s, no hardware commands.
- No-I/O sensor-path mock reproduction and exact guard-cutoff arithmetic probes.
- After the sensor fix, native gate/API/engineering-guard checks passed27 tests
  in92.71s, and the native UI workflow passed without JavaScript exceptions. A
  separate native-gate rerun passed10 tests in1.01s, including the additional
  terminal-ready race test. No new full-suite or physical run is implied.
- Read the existing486-test full-suite and9-test later safety-subset checkpoints;
  they were not rerun or treated as a new full-tree pass today.

Each actual extracted commit should run its targeted checks, and the combined
tree should run the full Python suite, build, native UI and simulated workflow.
No new hardware reliability qualification is implied by organizing commits.
