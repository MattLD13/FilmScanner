# FRAME scanner workspace

The scanner interface formerly called CyberScan X is now **FRAME**. It runs in
the FRAME desktop shell and uses the local service. Direct PF1800 AFL capture
uses the scanner's low-level driver; the hidden CyberView TWAIN path remains
available for research and tests. Hardware evidence and enabled settings are
documented in [native-scanner.md](native-scanner.md) and
[standalone-plan.md](standalone-plan.md).

## Open FRAME

From the repository root:

```powershell
npm run setup          # once
npm run build:native   # build the direct scanner bridge when required
npm run build          # build the web client
npm run frame          # open the scanner workspace in a FRAME window
```

To create per-user FRAME shortcuts in the Start menu and on the desktop, run
`powershell -ExecutionPolicy Bypass -File scripts\install-cyberscan-shortcut.ps1`.
The shortcuts use `--frame-scanner` and the FRAME icon. The installer replaces only
this checkout's recognised CyberScan X shortcut; customised links are preserved.
Older links remain usable through `--cyberscan`. The shell keeps its taskbar identity,
single-instance behavior and `%APPDATA%\cyberscan-x\logs` location.

While `npm start` serves the local application, the scanner workspace is at
`http://127.0.0.1:8765/?workspace=frame`; the older `workspace=cyberscan` URL
also works. `npm run preview:skin` opens a separate static demonstration with
clearly labeled sample photographs and disabled scanning. The static preview
makes no service, API, WebSocket or external requests.

## Navigation and editing

- **Home** shows a square, randomly selected saved scanner photograph, with a
  shuffle action that avoids immediately repeating a frame. It shows an empty
  state when there are no saved photographs. Demonstration photographs appear
  only in the explicitly labeled sample mode.
- **Scan** provides the current-frame viewer, scanner status, scan and transport
  actions, filmstrip, nondestructive adjustments, conversion profiles, alignment
  and original/adjusted exports. Scanner controls and detailed image settings are
  grouped in expandable panels. Available hardware actions remain governed by
  the existing validation gates.
- **Develop** opens the existing FRAME developing workflow, including its labeled
  demonstration recipe and persisted physical-time timer. Developing records and
  scanner-workspace rolls are currently separate; the interface says so. The
  navigation returns to the scanner workspace from that page.
- **Rolls** groups saved scanner captures by roll; **Settings** shows scanner
  status, diagnostics and release controls.

Home, Rolls and the filmstrip request rendered versions of saved edits. The
scanner viewer retains its interactive adjustment preview. Originals stay
unchanged, and exports retain their separate processing recipe. Direct negative
conversion and the locally derived reference profile have documented limitations;
see [negative-conversion.md](negative-conversion.md) and
[reference-tone.md](reference-tone.md).
Recovered model/film-stock conversion is described in
[vendor-colour-pipeline.md](vendor-colour-pipeline.md). It is selected explicitly;
existing edits are not changed.

## Design and checks

The workspace follows the original FRAME brief: dark chocolate surfaces, warm
cream text, editorial serif headings, restrained orange actions and a prominent
photograph. Desktop uses a persistent sidebar; narrow screens use labeled bottom
navigation and a larger fitted photograph. The existing local system fonts avoid
an external font request.

`npm run test:skin` checks the static demonstration in desktop and 390-pixel
Chromium views. `npm run test:native-ui` exercises the live UI with a synthetic
bridge, including saved-photo navigation, edit preview and export. `npm run
test:live-preview` uses synthetic streamed rows. These are software checks, not
evidence of physical scanner behavior. Current test screenshots are written under
`.local/frame-ui/` and remain outside version control.
