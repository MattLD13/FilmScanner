# CyberScan X interface preview

This is the first modern scanner-workspace skin for FRAME. The user authorized
interface work on October 30, 2026 while explicitly keeping the software away from
the connected scanner. This preview follows that restriction.

## Run the preview

```powershell
npm run build
npm run preview:skin
```

Open [the local preview](http://127.0.0.1:8770/?workspace=cyberscan).
It is a static server bound to this computer only. It imports no FRAME API,
scanner host, USB/TWAIN backend or vendor software. It does not authenticate with
the service, discover devices, connect an event socket or register a service
worker. Its browser Content Security Policy blocks all connection requests.

The original app remains available through its normal startup path; its existing
implementation was not replaced. The static preview server redirects its root
entry to the CyberScan renderer and provides no API. The separate preview was
used for testing so the user's VueScan session and scanner were not touched.

## Working controls

- Three local demonstration photographs with clear demo labels. The displayed
  Gold 200 roll label is demonstration metadata, not a claim about the sample
  photographs' film stock or the user's scans.
- Filmstrip image selection and a session library.
- Import one or several local images into browser memory, without uploading them.
- Zoom/fit, rotation, mirroring and rule-of-thirds framing guides.
- Exposure, contrast and saturation display adjustments, reset and creative
  Neutral/Warm/Mono looks. They are not calibrated film-stock responses.
- Export a separate 8-bit JPEG preview with the image transforms and adjustments,
  or download its JSON preview recipe. Original imported files are not changed.
- Local preferences/information view and a layout suitable for desktop and 390px
  phone-size review.

Connect, Prescan and Scan remain visibly disabled. There is no simulated progress,
physical alignment control, automatic film motion, calibration or acquisition in
this mode. Framing guides are visual overlays; they do not move film or crop an
archival acquisition. No USB service/driver, Windows appearance setting or VueScan
setting is changed. The dark theme is confined to the preview page.

## Validation

```powershell
npm run lint
npm run build
npm run test:skin
```

The browser test starts only a temporary static server on 127.0.0.1:8771. It tests
frame selection, keyboard-accessible adjustments, creative look/reset, transforms,
guides, local import, session clearing on reload, JPEG/JSON downloads and a 390px
layout. It asserts that scanner actions are disabled and records **zero API
requests, zero WebSocket connections and zero external requests**.

Results: [cyberscan-validation.json](cyberscan-validation.json).
Screenshots: [desktop](screenshots/cyberscan-desktop.png) and
[phone](screenshots/cyberscan-phone.png). These are UI photographs/fixtures, not
hardware test evidence. Sources/licenses are in
[the demo asset record](../apps/web/public/demo/README.md).

## Scope still open

This is a renderer preview, not the finished hardware integration or archive
editor. Scanner access must remain disabled until the user authorizes that work.
Later work can connect the approved workspace to verified operations, migrate
the remaining FRAME screens, integrate the native desktop entry and add actual
histograms, crop/export recipes, keyboard shortcuts and per-frame edit history.
Imported preview images and adjustments currently last only for the page session.
