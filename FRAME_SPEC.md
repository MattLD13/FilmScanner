# FRAME
## Complete product and engineering specification

**Version:** 1.0  
**Date:** October 27, 2026  
**Status:** Implementation specification  
**Primary hardware:** Pacific Image PrimeFilm PF1800 AFL  
**Primary development environment:** Windows 11  
**Primary client platforms:** Windows desktop, iPhone web app, iPad web app  
**Working project directory:** `C:\FilmScanner`  
**Working title:** FRAME

---

## 1. Project summary

FRAME is an open source film photography application that follows an exposed roll through developing, scanning, editing, organizing, and archiving. Its initial hardware is a used, visually unused Pacific Image PrimeFilm PF1800 AFL acquired as an inexpensive entry level scanner. A successful first release must be useful before the physical scanner arrives, then progressively support actual scans without redesigning the application.

FRAME combines five products behind one consistent interface:

1. **SCAN:** A reliable scanner control application with automatic uncut 35mm roll processing, precut strip support, and mounted slide support where documented and verified.
2. **DEVELOP:** A trustworthy film developing assistant with configurable recipes, timers, agitation reminders, chemistry logs, and temperature information.
3. **PROCESS:** A nondestructive film image processing engine that preserves the original acquired data and produces editable TIFF and JPEG exports.
4. **ROLLS:** A searchable film archive that links camera information, development sessions, scanned frames, processing settings, contact sheets, and backups.
5. **COMPANION:** A responsive iPhone and iPad application with live scan status, acquired previews, developing sessions, notifications where supported, and the same library.

The appearance is inspired by the user's NICE Film Club reference screenshots, but the implementation, graphics, and name must be original. The home screen prominently features a **square containing a random photograph from the user's saved library**. This is a real saved photo, not a synthetic picture, whenever the library has images.

### 1.1 Principles

* Deliver working software incrementally. Do not spend weeks designing an independent driver before the simulator and film library work.
* Prefer verified hardware behavior over assumptions. Do not infer a capability simply because similar scanners have it.
* Never destroy originals or silently replace an archival scan with a processed export.
* Keep the entire workflow usable without a subscription or cloud account.
* Begin with one computer and one scanner, but support multiple scanner backends in the architecture.
* Keep developing timers trustworthy, even when the UI reloads or a desktop scan is running.
* Keep uncertain or dangerous firmware experiments isolated from production scanning.
* Use AI coding agents efficiently with measured, testable assignments instead of a permanent swarm.

### 1.2 Non goals for the initial release

* No guaranteed increase in optical resolution above the PF1800 AFL's rated 1800 DPI.
* No guaranteed continuous live camera video from the linear CCD.
* No firmware rewriting or flashing during initial development.
* No guaranteed background web timer alerts on iOS.
* No assumption that CyberView, VueScan, NAPS2, or Linux SANE already work on this particular unit.
* No automatically fabricated development chemistry recipes or timings.
* No public internet exposure of scanner motor controls.

---

## 2. Product experience and navigation

Primary navigation: **HOME | SCAN | DEVELOP | ROLLS | SETTINGS**.

Desktop and mobile must share visual components and data models. Desktop can show a denser multi panel workflow; mobile favors one clear task at a time.

### 2.1 Design system

**Visual reference:** NICE Film Club screenshots supplied by the user. Save them under `references/nice-film-club/` when available locally. If absent, use the textual design brief below and do not block development.

* Dark chocolate brown primary surfaces.
* Warm cream text and large editorial serif headlines.
* Small, deliberate orange accents for actions and current status.
* Readable modern sans serif body text, labels, and numeric displays.
* Gallery focused photographs with generous whitespace.
* Gentle rounded corners, restrained motion, and minimal clutter.
* High contrast for critical countdowns, error states, connection statuses, and safety messages.
* Consistent typography and spacing on Windows, iPhone, and iPad.
* Avoid copying NICE branding, distinctive icons, proprietary layouts, or licensed assets.
* Use accessible color contrast, keyboard navigation, semantic labels, and reduced motion preferences.

### 2.2 HOME

Home includes:

* Warm welcome and concise scanner status.
* A central square featured photograph, chosen randomly from the actual saved photo library.
* A shuffle action that picks another saved image; avoid immediate repeats when more than one image exists.
* The selected photo's film stock, roll identifier, and capture date if present.
* Empty state using a clear placeholder when no saved photos exist, not invented personal photographs.
* Quick actions for Scan, Develop, and Library.
* Active scan card with frame progress and estimated time when a session exists.
* Active development card with real elapsed time when a session exists.
* Recent rolls and recent scans.
* Small archive statistics such as rolls scanned and images saved.

### 2.3 SCAN

Desktop scanner workspace:

* Connected scanner and backend type, shown as real, simulated, or disconnected.
* Film roll selection or new roll creation.
* Film type selector: color negative, black and white negative, positive slide.
* Physical media selector: uncut 35mm roll, supported precut strip, mounted slide.
* Startup checks for connection, film load, calibration, and available functions.
* Prescan strip with detected frames and manually correctable frame boundaries.
* Large current frame preview, and a grid or filmstrip of completed frames.
* Automatic scan entire roll and individual frame scan actions.
* Real acquisition settings such as optical DPI, available bit depth, available focus mode, and output destination.
* Actual statuses: initializing, calibrating, loading, prescanning, aligning, focusing, acquiring, transferring, processing, saving, complete, jam suspected, error.
* Elapsed time, progress if measurable, and ETA based on observed durations.
* Pause or cancel only where supported safely. A cancellation must leave the system in a defined state.
* Eject and transport controls only when hardware verified, with bounds and user confirmation when needed.
* Per frame rescan and failed frame retry with audit trail.
* Diagnostic view for hardware IDs, scanner capabilities, and event logs.

### 2.4 Live scanner view

Prefer the most truthful live view supported by each backend:

1. **Status only:** Scanner operation and progress based on confirmed events.
2. **Prescan plus completed frames:** Current thumbnail and instant display after each completed acquisition.
3. **Progressive transfer:** Partially acquired image updated as genuine image rows or chunks arrive.

Do not create a fake progressive image and describe it as actual CCD streaming. Where only buffered TWAIN transfers exist, display a prescan until the real image is available.

The phone receives thumbnail or preview events, never the entire archival TIFF on every progress update. Data transfer should be bounded and recover after disconnections.

### 2.5 DEVELOP

The DEVELOP area is a genuinely useful darkroom assistant, not an ornamental timer screen. It covers developing 35mm and 120 film, even though the PF1800 AFL only scans 35mm.

* Guided black and white negative processing.
* Guided C41 processing with manufacturer specific instructions.
* E6 processing can be a later supported extension.
* Select film stock, exposed ISO or push/pull notes, chemistry product, process version, and tank volume.
* Edit and save named chemistry profiles without pretending they have been manufacturer verified.
* Show exact ordered steps and transitions appropriate for the chosen chemistry.
* Timers for developer, stop bath if applicable, fixer, bleach or blix, washes, final rinse or stabilizer where applicable, and optional drying reminders.
* Initial and repeating agitation reminders, using the selected recipe's actual schedule.
* Temperature targets, manually recorded actual temperatures, and warnings for outside the documented target range.
* Concentrate and water dilution calculations, with rounding explained.
* Track mixed chemistry date, batches, prior roll count, and published capacity guidance.
* Record actual start and end timestamps and user confirmed transition times.
* Always keep the chemistry clock accurate. Pausing the interface must not incorrectly pause physical development.
* Resume after screen reload by deriving remaining time from saved timestamps. Distinguish device clock changes and interruptions.
* If browser notifications or audio are unavailable in the background, show an explicit limitation and recommend keeping the screen awake or using a separate reliable timer.
* Consider a native iOS implementation for dependable alerts and optional Live Activities after the PWA is validated.
* Preserve and show a complete development session history, linked to the roll and its final scans.
* Respect published chemical handling instructions and disposal guidance; do not guess or silently extrapolate reuse capacity.

### 2.6 ROLLS and FRAME DETAIL

* Cards with film stock, format, ISO, date, status, and an actual saved image as cover.
* Roll timeline: shot, awaiting development, developing, developed, ready to scan, scanning, scanned, archived.
* Filmstrip and gallery views.
* Contact sheets for preview and optional PDF or image export.
* Search by film stock, camera, date, status, tags, and notes.
* Favorite and rating actions.
* Frame editor with before and after comparison, neutral color controls, crop, rotation, exposure, curves, and film profile.
* Original file immutable, processing edits stored separately.
* Export JPEGs, processed TIFFs, and originals separately.
* Clear distinction between scans of a 35mm roll and imported images from 120 film or labs.

### 2.7 SETTINGS

* Scanner device selection, backend status, capability matrix, and diagnostic bundle.
* Storage and archive location.
* Color management preferences and optional ICC profiles.
* Device display preferences and accessible UI controls.
* Network access, authentication, allowed companion devices, and notification preferences.
* Data export and restore.
* Read only experimental hardware research panel until features are validated.

---

## 3. Hardware scope and capability confidence

### 3.1 Initial device

Pacific Image PrimeFilm PF1800 AFL, a dedicated 35mm linear CCD film scanner with motorized film transport and a rated optical resolution of 1800 DPI. A 35mm frame scanned at that resolution produces approximately 4.3 megapixels, subject to scan area and cropping. Manual documentation indicates an original CyberView workflow with prescan, autofocusing and film movement. The software appears to provide an 8 bit and 12 bit per channel selection. **The actual available exported bit depth and rawness of acquired output must be measured on the user's unit.**

The device is approximately 25 years old, even if apparently unused, so motors, lamp, rollers, software compatibility, and USB behavior remain uncertain.

### 3.2 Capability evidence states

Every backend feature must be labeled using these states:

* **VERIFIED ON DEVICE:** Demonstrated on this actual scanner with captured evidence.
* **DOCUMENTED:** A model specific manual or source establishes support but it is not yet tested.
* **INFERRED:** Reasonable hypothesis based on software or component investigation.
* **EXPERIMENTAL:** Safe test is planned, but not yet proven.
* **UNAVAILABLE:** Not supported, not exposed, or not found.

The simulator must not mark a real hardware capability as verified.

### 3.3 Hardware control objectives

Priority order:

1. Device identification and connection detection.
2. Device initialization, calibration, and status.
3. Safe film load, advancement, reverse positioning, and ejection.
4. Frame prescan and mapping.
5. Autofocus and image acquisition.
6. Original bit depth capture and correct image transfer.
7. Automatic uncut roll scanning with fault recovery.
8. Verified manual positioning and focus controls.
9. Experimental exposure, sensor gain, averaging, or transfer optimization where hardware evidence exists.

Never command uncontrolled motor motion, assume position feedback exists, or send unverified update commands.

---

## 4. Scanner integration strategy

### 4.1 Backend interfaces

Implement a `ScannerBackend` contract that can be used by:

* `SimulatedScannerBackend`, deterministic, suitable for tests and demos.
* `TwainScannerBackend`, a wrapper around a compatible installed legacy data source if it actually works.
* `UsbScannerBackend`, future independently tested USB command implementation.

Shared operations should include discovery, capabilities, connect, initialize, calibrate, load, prescan, list frames, position frame, acquire, cancel safely, eject safely, disconnect, and subscribe to events. Operations not available must be explicitly unsupported, not silently simulated.

A bounded, serial hardware command queue owns the scanner. Only one operation that moves film or acquires an image may execute at a time. Companion clients cannot bypass the command queue.

### 4.2 Initial driver path

* Inspect the manufacturer's original CyberView CD and any legitimate archived installers.
* Preserve original optical media as an ISO when practical and compute hashes.
* Inventory executables, TWAIN files, DLLs, INF files, driver binaries, installers, firmware update tools, and version metadata.
* Test in a controlled compatibility environment when necessary, such as a properly licensed legacy Windows virtual machine with USB passthrough.
* Confirm device enumeration and a single scan before attempting automatic roll processing.
* Investigate NAPS2's TWAIN tooling for interoperability, while recognizing that standard document scanning tools may not expose proprietary film transport features.
* Document the dependence of any 32 bit TWAIN data source on a compatible 32 bit host process.

### 4.3 Reverse engineering

Use REA, Ghidra, static file inspection, USBPcap, Wireshark, and relevant device debugging tools.

Sequence:

1. Identify genuine installed software components and capture file hashes.
2. Static analysis of importer functions, strings, exported symbols, device IDs, and likely transport routines.
3. Trace high level actions to driver or USB calls.
4. Run vendor software in an appropriately isolated environment and capture a clean device connection.
5. Capture exactly one documented operation per trace: calibration, forward advance, reverse, prescan, acquire, eject.
6. Compare USB control transfers, endpoint traffic, command lengths, sequences, checksums, timings, responses, and frame payload sizes.
7. Write an evidence based protocol notebook, clearly separating confirmed fields from guesses.
8. Implement a passive USB parser and trace viewer before issuing custom commands.
9. Test read only queries, then carefully bounded commands using expendable film.
10. Only promote stable and repeatable functions into the production driver.

If a command could cause a jam, overtravel, lamp stress, or unexpected overwrite, require explicit user authorization before testing on real hardware.

### 4.4 Firmware investigation

Firmware analysis is optional and exploratory. An upgrade menu in related software does not prove this particular scanner accepts arbitrary firmware.

* Determine controller family and storage type from evidence, not family similarity.
* Search CD and driver for embedded firmware images, update protocol, and version data.
* Do not use firmware images from other PrimeFilm models.
* If physical board inspection is eventually required, defer it until after the return period and explain power and lamp inverter hazards.
* Prefer a verified readout and recoverability plan before any writing.
* No custom firmware flashing is permitted in the initial deliverables.

---

## 5. Simulator and integration test fixture

The scanner simulator is the first hardware backend delivered.

It must:

* Behave through the same public contract as real hardware.
* Model idle, connected, ready, loading, positioning, focusing, prescanning, scanning, saving, complete, error, disconnected states.
* Support uncut rolls with variable frame counts and precut strips.
* Generate a frame index with deterministic positioning and repeatable event timing.
* Stream meaningful incremental acquisition events and optionally chunked image fixture data to exercise the UI.
* Inject jams, calibration failures, USB disconnections, timeouts, bad alignment, failed file writes, and cancellation.
* Support accelerated mode for automated tests and real time mode for human UI review.
* Use imported, freely usable image fixtures or clearly labeled synthetic images, never claim they are scans from the actual device.
* Provide replayable event logs for reproducing bugs.

Acceptance scenario: a complete 36 frame simulated roll progresses from loading to archive, and another scenario fails at frame 17 and resumes correctly after a controlled recovery.

---

## 6. Image acquisition, processing, and calibration

### 6.1 Originals and precision

* Save exact data received from the scanner before creative transformations where possible.
* Do not call data truly raw if the vendor driver has already applied unobservable processing.
* Never expand 8 bit samples to 16 bits and advertise a higher acquired precision.
* Use a 16 bit TIFF container when real data exceeds 8 bit precision and preserve metadata describing its effective bits.
* Document bit order, channel order, black point, white point, color space, ICC tags, and compression.
* Preserve a hash and immutable record for each original acquired file.

### 6.2 Processing pipeline

Processing should be nondestructive and versioned:

1. Load original acquisition and metadata.
2. Apply scanner calibration if available and justified.
3. Determine film base from a manually selected or automatically suggested unexposed region.
4. Invert negative using a scientifically defensible density or film response method.
5. Apply roll level film profile or manually adjusted neutral balance.
6. Apply frame specific exposure, highlight, shadow, contrast, and tone curve controls.
7. Apply rotation, edge cleanup, and crop.
8. Optionally detect dust and scratches, with an inspectable mask and repair review.
9. Optionally apply grain respectful sharpening and noise reduction.
10. Export through explicit color space conversion with documented ICC metadata.

Black and white, C41, and positive slides require separate processing branches. Film stock presets are starting points, not measured spectral identities.

### 6.3 Calibration

* Support optional IT8 transparency target profiling with matching reference measurement data.
* Provide scanner characterization using suitable ICC tooling such as ArgyllCMS.
* Distinguish scanner profiling from color negative conversion. An IT8 slide does not make all negative stocks perfect automatically.
* Support comparison of the same negative against an existing professional lab scan, with controlled white balance and exposure comparison.
* Evaluate accuracy using measurable neutral error and color difference when valid references exist, rather than subjective appeal alone.
* Do not require a calibration slide for the first usable release.

### 6.4 Quality improvement experiments

Investigate only after reliable archival scans:

* Repeat capture averaging and image registration to reduce random noise.
* Exposure or gain adjustments if the scanner demonstrably exposes those controls.
* Multiexposure merge only if the device can capture different exposures and alignment is sound.
* Optical blur compensation without aggressive grain artifacts.
* Software dust and scratch detection without assuming an infrared channel.
* Optional AI upscaling with explicit labeling that fine details can be inferred, not captured optically.
* Side by side quantitative and visual comparisons.

### 6.5 Exports

At minimum:

* Exact original as delivered by acquisition backend.
* 16 bit processed TIFF when actual processing precision warrants it.
* Standard JPEG for sharing and preview.
* Contact sheet as image and optionally PDF.
* `frame.json` or database processing record and edit history.

Store export settings and rendering engine version so exports can be reproduced later.

---

## 7. Film development engine

### 7.1 Recipes

Recipe data must identify manufacturer, chemistry name, product version, supported film or process, temperatures, dilutions, timings, agitation directions, maximum recommended reuse, and a source or user supplied record. Distinguish verified from custom recipes.

Recipes may have variable steps and agitation patterns. Never hardcode developer, stop, fixer, or stabilizer steps as universal across all processes.

### 7.2 Timer state machine

Possible session states:

`not_started`, `ready`, `running`, `awaiting_user_transition`, `completed`, `interrupted`, `aborted`.

For each step store planned duration, actual start timestamp, actual end timestamp, agitation events, user confirmations, and deviations. Use monotonic timing while in the foreground and persisted wall clock checkpoints for resuming. Detect large wall clock discontinuities and require user review.

Do not offer a deceptive pause button for chemistry that continues reacting. A pause action can stop notifications or record an interruption but must not claim the chemistry clock stopped.

### 7.3 UX and notifications

* The timer screen must keep the current step and remaining time very large.
* A separate next agitation timer is visible where applicable.
* Step completion gives audible and visual notification when available.
* Require user confirmation for physical transitions that the app cannot perform.
* Display the recipe source and active temperature prominently.
* Allow attaching development photos or notes after the session.
* Support offline operation on the phone for a loaded recipe and saved local session state.
* A PWA cannot guarantee alarm execution after iOS suspends it. Expose this limitation clearly, with a native app or independent physical timer as a later solution.

### 7.4 Chemistry calculations

Dilution expressions should be explicit and tested, including ratios such as `1+9` and kit volume requirements. Provide both concentrate and water volume, note minimum working solution volume per tank, and warn when the calculation conflicts with the chemistry instructions.

Capacity should be recorded against specific product guidance rather than inferred from rolls alone.

---

## 8. Data model and storage

### 8.1 Core entities

* `Roll`: ID, stock, format, ISO, camera, lens, dates, notes, tags, status.
* `DevelopmentSession`: roll ID, chemistry profile version, step events, measured temperatures, deviations, completion.
* `ScannerDevice`: model, hardware IDs, backend, firmware version if verified, capability evidence.
* `ScanSession`: roll ID, scanner ID, profile, scan settings, start and completion events, failure recovery.
* `Frame`: frame index, source path, thumbnails, scan status, favorite, notes, photo metadata.
* `EditRecipe`: frame ID, parameters, software version, optional ICC reference, timestamps.
* `Export`: frame ID, format, destination, color space, validation result, file hash.
* `ChemicalBatch`: product, mix date, known capacity, usage, discard status.
* `DeviceSession`: authorized desktop or mobile client and access scope.

### 8.2 File organization

Suggested organization:

```text
FilmLibrary/
  Roll_0001/
    roll.json
    development/
      session.json
    acquisition/
      frame_001.tif
      frame_002.tif
    edits/
      frame_001.json
    previews/
      frame_001.jpg
    exports/
      frame_001_processed.tif
      frame_001_share.jpg
    contact_sheet.jpg
    logs/
      scanner_events.jsonl
```

Database storage should be SQLite with migrations and versioned backups. All image paths use stable, portable identifiers. Write images atomically using a temporary file followed by a verified rename. Protect against accidental overwrite and corruption.

### 8.3 Backup

* Encourage at least one separate archive backup device.
* Add optional offsite sync but not as a startup prerequisite.
* Keep logs of backup verification and hashes.
* Optional future connection to the user's existing film gallery backup workflow and Google Photos, only with user granted credentials and a separate synchronization module.
* An image is not archived merely because a database row says it is archived; the files must exist and pass integrity checks.

---

## 9. iPhone and remote architecture

### 9.1 First release

Use a responsive React PWA sharing frontend code with the desktop browser. A Windows service remains the scanner controller and archive authority.

Mobile features:

* Live scanner connection state.
* Roll status, current frame, elapsed time, ETA.
* Actual prescan or completed frame previews.
* Progressive image preview where the backend supports real chunks.
* Browse rolls and photo details.
* Contact sheets and exported images.
* Development recipes, timers, logs, and history.
* Error and completion notifications where supported.

### 9.2 Transport and security

* Use HTTPS for nonlocal connections and authenticated WebSocket or SignalR events.
* Default server binding should be local only until the user deliberately enables LAN access.
* Do not expose the API to the public internet or enable router port forwarding automatically.
* If remote access is needed, use a private networking solution after explicit setup.
* Authenticate the companion and use scoped tokens.
* Restrict remote operations that can physically move film unless specifically implemented with permission checks, hardware state validation, and safe cancellation.
* Do not transmit full archival originals as routine live updates.

### 9.3 Native mobile roadmap

A future iOS app could provide reliable local alarms, better foreground and background behavior, notification permissions, and ActivityKit Live Activities for scan progress and developing. Native iOS development requires an appropriate Apple build and signing workflow; it is not a dependency of the first Windows implementation.

---

## 10. Suggested implementation stack

Prefer a modular monorepo:

```text
FRAME/
  FRAME_SPEC.md
  AGENTS.md
  .codex/
    config.toml
    agents/
  apps/
    web/
    desktop-shell/              # optional later
  services/
    api/
    scanner-host/
    imaging/
  packages/
    contracts/
    ui/
  research/
    cyberview/
    usb/
    firmware/
  fixtures/
    scanner/
    imaging/
  references/
    nice-film-club/
  docs/
    decisions/
    capability-matrix.md
    hardware-testing.md
    setup.md
  tests/
    api/
    scanner/
    imaging/
    developing/
    e2e/
```

Candidate technology choices:

* **Scanner host:** C# and .NET on Windows, with a separate 32 bit process if a legacy TWAIN data source requires it.
* **Existing scanner integration:** NAPS2 SDK or another appropriate TWAIN wrapper, after a compatibility proof.
* **USB research:** REA, Ghidra, USBPcap, Wireshark, and a later minimal libusb implementation if needed.
* **Backend:** ASP.NET Core with SignalR for server events.
* **Frontend:** React with TypeScript and a shared responsive component system.
* **Image processing:** Initially Python, NumPy, OpenCV, ICC tooling, and native image libraries when justified by benchmarks.
* **Persistence:** SQLite for metadata, file system for originals and exports.
* **Tests:** xUnit for .NET, pytest for Python, Playwright for interface and workflow.
* **Packaging:** documented local development commands first, an installable Windows package later.

This is a candidate stack, not a reason to introduce every framework on day one. Select one language per subsystem and avoid duplicating the same backend function in multiple services.

### 10.1 Open source reference projects

Research before reuse, and confirm current license terms:

* NAPS2: `https://github.com/cyanfish/naps2`
* REA: `https://github.com/morluto/rea`
* negaflow: `https://github.com/habinsong/negaflow`
* Negative Vibes: `https://github.com/cschalle/negative-vibes`
* DarkSlide: `https://github.com/kilianvivien/DarkSlide`
* darktable negadoctor documentation: `https://docs.darktable.org/`
* ArgyllCMS: `https://www.argyllcms.com/`
* SANE: `http://www.sane-project.org/`

Do not assume a repository supports PF1800 AFL or that its architecture is suitable without inspecting actual code. Open source licenses must be checked before code is copied or linked. Do not incorporate an incompatible copyleft dependency into the project without making an explicit licensing decision.

---

## 11. Codex agents and compute efficiency

### 11.1 Orchestration philosophy

Use the lessons from Anthropic's agent judgment research: recommendations can strongly sway human decisions, so major choices need transparent evidence and alternatives. Use the lessons from multiagent research and official Codex documentation: delegate truly independent tasks, bound their context, and verify outputs. Do not spend compute maintaining idle agents or running the same analysis repeatedly.

Reference research:

* `https://www.anthropic.com/research/agents-judgment-calls`
* `https://www.anthropic.com/research/multi-agent-research-system`
* `https://developers.openai.com/codex/subagents`
* `https://learn.chatgpt.com/docs/models`

### 11.2 Agent roles and preferred models

These are preferred assignments, **not guarantees of access**. Before writing configuration, read current Codex documentation and inspect the models actually available in the user's desktop account. Do not invent unsupported configuration keys or pretend a requested model ran.

| Role | Preferred model ID | Reasoning effort | When used |
| --- | --- | --- | --- |
| Root orchestrator | `gpt-6.1-sol` | `high` | Architecture, integration, decisions |
| Research and code mapper | `gpt-6-luna` | `medium` | Targeted docs and code exploration |
| Scanner and USB engineer | `gpt-6.1-sol` | `high` | Simulator, TWAIN and verified USB |
| Reverse engineer | `gpt-6.1-sol` | `xhigh` | REA, Ghidra, difficult protocol traces |
| Image engineer | `gpt-6.1-sol` | `high` | Color, TIFFs and correctness |
| Interface engineer | `gpt-6.1-terra` | `medium` | UI, responsive PWA and visual checks |
| Independent reviewer | `gpt-6.1-sol` | `high` | Significant safety and correctness review |

Use an available supported substitute when a preferred model cannot be selected. Use Astra selectively for exceptional, independently justified hard reviews only if the environment offers it, not as the default.

Set at most **three concurrent subagent threads** unless a measured task justifies a temporary increase. Most routine work requires zero or one subagent. Define roles in `.codex/agents/*.toml` using documented custom agent properties. Keep `.codex/config.toml` minimal and valid for the installed version. A Codex restart or refreshed session may be needed to load new agents.

### 11.3 Delegation contract

Each subagent receives:

* A narrowly defined task and intended outcome.
* Dependencies and evidence available.
* Specific files or folders it owns.
* Acceptance criteria and tests.
* Stop conditions and situations requiring escalation.
* A token efficient reporting format: change, evidence, tests, uncertainty, next action.

Do not send the entire repository to every subagent. Do not ask two agents to edit the same files concurrently. Use isolated worktrees or coordination when helpful.

### 11.4 Human judgment and high risk changes

Record substantial architecture decisions in `docs/decisions/` with:

* Decision and context.
* Supporting evidence and whether it was verified.
* One or more credible alternatives.
* Tradeoffs and failure modes.
* Reversibility and verification plan.
* User approval where required.

User approval required before firmware flashing, novel motor commands on real hardware, changing computer wide security settings, risky driver installation, irreversible archival deletion, paid cloud services, or public access configuration.

### 11.5 Review and testing efficiency

* Use targeted tests during small changes.
* Run an end to end suite at each milestone.
* Activate the independent reviewer after significant scanner, archive, chemistry timing, and security changes.
* Do not spawn a new reviewer for every CSS tweak.
* Track tests, compute usage if available, rework, and duplicate agent work.
* Distinguish actual execution from planned or simulated tests.
* Prefer a simple implementation with strong tests to a larger architecture with no running software.

---

## 12. Milestones and definition of done

### M0: Repository and architecture

* Inspect local project and existing contents.
* Create or validate Git repository.
* Place this specification at repository root.
* Write concise `AGENTS.md` with only persistent coding rules.
* Verify supported models and create agent TOML definitions only if supported.
* Define shared API and data contracts.
* Create basic build, test, lint, and startup commands.
* Research critical dependencies and licenses.

**Done:** Project opens and local development startup path is documented, initial packages build, and no existing user files were overwritten.

### M1: Useful simulated vertical slice

* Create a roll with film stock and metadata.
* Start and complete a development session using a test recipe clearly labeled as demonstration data.
* Move the roll to ready to scan.
* Connect a simulated PF1800 AFL.
* Load a simulated roll, prescan, show frame positions, and scan all frames.
* Stream real simulator events to desktop and iPhone PWA.
* Store images and metadata, generate contact sheet, and browse the roll.
* Random home square shows a saved frame and shuffles correctly.
* Restart application and verify session persistence.
* Include a clear simulator badge and never claim actual scanner connection.

**Done:** A user can complete this full workflow in a running app without the actual scanner.

### M2: Image processing and archival reliability

* Import known negative sample images.
* Produce a usable inversion and editable processing workflow.
* Save originals unchanged with hashes.
* Produce TIFF and JPEG exports with correct metadata.
* Build deterministic image tests and reference comparisons.
* Verify interrupted exports do not destroy valid originals.

**Done:** Independent image processing tests pass and exports survive restart and restore.

### M3: Real PF1800 AFL first scan

* Preserve and inventory CyberView CDs.
* Identify actual hardware IDs and correct connection state.
* Establish working original driver or documented alternative, where possible.
* Test sacrificial precut 35mm strip using documented loading guidance.
* Acquire and save one valid image, verify the acquired bit depth, test safe ejection.
* Preserve exact diagnostic logs and observed timings.

**Done:** An actual image exists with a reproducible acquisition procedure, or a precise technical blocker is documented without claiming success.

### M4: Automatic real roll scanning

* Validate frame detection and positioning with real film.
* Scan a complete uncut roll, with user supervised first experiments.
* Verify no transport damage and correct frame order.
* Support controlled retries and per frame rescans.
* Show phone progress and acquired previews.

**Done:** A complete tested uncut roll is imported, processed, and archived with no lost frames, or limitations are clearly enumerated.

### M5: Advanced reverse engineering

* Analyze binary evidence and clean USB traces.
* Produce verified command descriptions.
* Build minimal independent USB prototype in read only mode first.
* Expand only to bounded and confirmed hardware operations.
* Compare output quality and performance with original software.

**Done:** Measured improvements or validated compatibility, not speculative API surfaces.

### M6: Hardening and distribution

* Installer or documented one command local setup.
* Reliable shutdown and recovery.
* Backup and migration tests.
* Network authentication and transport protections.
* Smartphone installation documentation.
* Accessibility and screen size validation.
* User guide and troubleshooting.

**Done:** Another user can follow the instructions to run simulator mode and safely try a verified supported scanner path.

---

## 13. Detailed acceptance tests

### Functional tests

* A 36 frame simulated roll scans without missing or duplicate frame IDs.
* Simulated jam at frame 17 produces an error rather than false completion and does not corrupt the first 16 files.
* Cancel during acquisition leaves a recoverable session record.
* Completed frame previews reach an authorized phone client while scanning proceeds.
* A disconnected phone can reconnect and obtain current status without replaying gigabytes of files.
* The featured HOME square selects a genuine saved photo and can shuffle.
* Search returns a roll by film stock and by date.
* Contact sheet frame order matches the roll.
* Image editor changes are reversible and original file checksums remain identical.
* Processing from a saved edit record generates reproducible output with the same software version.
* Development timer continues to show physically elapsed time when the page is reloaded; no fictional paused chemistry time.
* Agitation alerts are scheduled according to the selected recipe.
* User cannot start a chemistry session without verifying source and process settings.
* A locked or backgrounded iPhone does not silently promise a guaranteed alert from a PWA.
* The backend rejects unauthenticated access to personal archive data.
* Any attempted hardware command outside the verified capability set is blocked.

### Nonfunctional targets

* Responsive layouts suitable for desktop, iPhone, and iPad.
* Local first operation without needing a cloud account.
* Clear visual status for every error and long operation.
* Log files suitable for diagnostics without exposing secrets.
* Atomic file output and integrity checks.
* Bounded memory use when processing multiple full resolution TIFF files.
* Event streaming that does not block the acquisition pipeline.
* A short, repeatable command sequence for running all core services locally.

Measure scan speed and image quality rather than imposing unfounded performance targets on 25 year old hardware.

---

## 14. Work package order and ownership

**First pass, orchestrator:** Establish repo, shared contracts, API skeleton, and acceptance harness.

**Parallel tasks, no more than three subagents:** Researcher validates dependency options; scanner engineer implements simulator; interface engineer builds HOME, SCAN, and DEVELOP screens against typed mock events. Keep file ownership distinct.

**Integration pass:** Main agent connects simulator to backend, implements roll persistence, resolves shared schema issues, and runs M1 workflow.

**Second pass:** Image engineer handles TIFF pipeline independently; main agent implements persistent developing sessions; interface engineer connects real event streams and mobile views.

**Review pass:** Reviewer tests risky behavior, data durability, timer logic, network access, and errors. Fix evidence based bugs.

**When hardware arrives:** Activate reverse engineer for CD and USB traces; scanner engineer tests the vendor integration and updates verified capabilities. Do not delay user facing software on firmware research.

Use the shortest next task that produces an observable, testable improvement.

---

## 15. Required Codex behavior on first launch

1. Inspect the folder and detect existing work before creating files.
2. Read `FRAME_SPEC.md` as authoritative requirements.
3. Verify Codex model availability, subagent configuration syntax, installed runtimes, and permissions. Select supported models and report deviations.
4. Create a concise `AGENTS.md`, minimal valid `.codex/config.toml`, and only needed custom agent files.
5. Create a milestone checklist in `docs/progress.md` and a concise issue backlog.
6. Implement M0 and then start M1 immediately; do not stop at a planning document.
7. Run the app and automated tests using available local tools.
8. Provide screenshots or browser evidence of the running UI if tooling supports it.
9. Report which functionality is implemented, simulated, or blocked.
10. Never claim a real scan, active subagent, successful test, working push notification, or supported driver without evidence.

### First message to Codex after this file is placed in the project

> Read FRAME_SPEC.md in full. Treat it as the authoritative specification. Inspect the existing folder, verify supported models and agent settings, establish only the minimal necessary architecture and subagents, then implement milestones M0 and M1. Build a real running simulated develop, scan, process, and archive workflow with the NICE inspired interface and iPhone responsive views. Run tests, fix failures, and report actual working features. Do not block on the physical scanner or stop after planning. Never claim that simulated hardware has been validated on the real PF1800 AFL.

---

## 16. Source and research links

These references are starting points for Codex to recheck, not proof of compatibility with the actual scanner:

* Anthropic research on judgment calls: https://www.anthropic.com/research/agents-judgment-calls
* Anthropic research on multiagent systems: https://www.anthropic.com/research/multi-agent-research-system
* Official Codex subagents documentation: https://developers.openai.com/codex/subagents
* Current model selection documentation: https://learn.chatgpt.com/docs/models
* REA reverse engineering toolkit: https://github.com/morluto/rea
* NAPS2 project: https://github.com/cyanfish/naps2
* negaflow project: https://github.com/habinsong/negaflow
* Negative Vibes project: https://github.com/cschalle/negative-vibes
* DarkSlide project: https://github.com/kilianvivien/DarkSlide
* Pacific Image support: https://www.scanace.com/product/all-models-driver-download-user-guide
* VueScan PF1800 AFL support: https://www.hamrick.com/vuescan/pie_primefilm_1800afl.html
* ArgyllCMS: https://www.argyllcms.com/

**Final acceptance principle:** FRAME is successful when a person can safely move from a development session to a verified archival scan and browse their processed images, with an understandable interface and no silent data loss. The simulator demonstrates software behavior. The physical scanner validates hardware behavior. Those are separate milestones.
