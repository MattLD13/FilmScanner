# Run FRAME locally

Requirements: Python 3.13+, Node.js 22+ and npm. No cloud account or scanner is needed to run the simulator.

From the repository root:

```powershell
npm run setup
npm run build
npm start
```

Open http://127.0.0.1:8765. The server binds only to this computer. `powershell -File scripts/start.ps1` also builds a missing client and starts the server. After changing client source, rebuild; after Python changes, restart the service. Avoid multiple service processes sharing the same data directory.

```powershell
npm test
npm run lint
npm run build
```

`data/` stores SQLite, originals, previews, edit revisions, exports, event logs and versioned SQLite backups. It is ignored by Git. Set FRAME_DATA_DIR to an absolute folder before startup to use another library. Keep a separate backup of the entire directory; SQLite-only snapshots do not include image files.

For the optional automated browser workflow, install `requirements-dev.txt` and run `python -m playwright install chromium`, then `npm run test:e2e`. This starts an isolated service on 127.0.0.1:8766, uses a temporary library, runs real elapsed water rehearsal timers, and writes evidence under docs/screenshots. Port8766 must be free. The normal application uses port8765.

Create a roll in Rolls. Develop it using the acknowledged water-only rehearsal (8/5/6 seconds), confirming each transition. Alternatively mark an already-developed roll ready. Connect the simulator, select the roll and scan 36 frames. The fast mode accelerates software events; the review mode takes longer but is not measured hardware speed. Inject a jam at frame17 to test controlled recovery. Browse the saved roll, edit a frame, export images and archive it after integrity verification. Imported images are preserved byte-for-byte and shown as imported, separate from synthetic charts.

Timings continue while the page reloads. Keep a reliable physical timer for real chemistry; the bundled demo must never be used for processing film. iOS may suspend web alarms. A clock discontinuity interrupts the session for explicit review instead of silently adjusting chemistry time.

The responsive client can be reviewed with a 390px phone viewport. Actual iPhone LAN access is disabled until HTTPS and scoped device pairing are implemented. No router, firewall or security changes are made.
