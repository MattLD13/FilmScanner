# FRAME desktop shell

A native Windows 11 window around the FRAME React client and local Python
service. The service selects the scanner backend; the shell does not issue
scanner commands itself. Direct PF1800 AFL capture has been tested on the user's
unit, with enabled actions and limitations recorded in
[native-scanner.md](../../docs/native-scanner.md) and
[standalone-plan.md](../../docs/standalone-plan.md). The main FRAME workflow
still includes a clearly labeled simulator.

```powershell
npm run setup          # once, from the repository root
npm run build          # build the React client the service serves
npm run frame          # open FRAME's scanner workspace
npm run desktop        # open the original FRAME journal and simulator
npm run test:desktop   # unit tests (no GUI)
npm run smoke:desktop  # launch Electron headlessly against a throwaway library
```

The scanner window has Home, Scan, Develop, Rolls and Settings navigation. The
Develop link opens the existing FRAME developing workflow; developing records
and scanner-workspace rolls are currently separate. The legacy `--cyberscan` flag
and `?workspace=cyberscan` URL remain supported as aliases for the renamed
scanner workspace. `--frame-scanner` and `?workspace=frame` are preferred.

Create per-user FRAME desktop and Start-menu shortcuts with
`powershell -ExecutionPolicy Bypass -File scripts\install-cyberscan-shortcut.ps1`.
This creates new FRAME shortcuts; it does not remove older CyberScan shortcuts.

## Behavior

* **Attach or own.** If a FRAME service already answers `/api/health` on
  `127.0.0.1:8765` (or `FRAME_PORT`), the shell shows it and leaves it running.
  Otherwise it starts `python -m uvicorn services.api.main:app` on a free loopback
  port and ends it on quit, so two services never share one library.
  `FRAME_PYTHON` selects the interpreter; `FRAME_DATA_DIR` the library.
* **Logs.** The original journal window uses
  `%APPDATA%\frame-desktop\logs\service.log`; the scanner workspace retains
  `%APPDATA%\cyberscan-x\logs\service.log` for compatibility with existing state.
* **Hardening.**
  * The page runs sandboxed and context-isolated, without Node.
  * Navigation is limited to the service origin, and webviews and popups are refused.
  * Every permission request is denied.
  * **Every network request except the loopback service, its event WebSocket
    and in-page `data:`/`blob:` URLs is cancelled**, so the shell itself never
    makes a TLS connection. Ordinary `https:` links open in the default browser.
* **Smoke mode** (`--smoke [--screenshot=file.png]`) starts its own service with
  a temporary library. It waits until the page has authenticated and
  `/api/state` returns 200, prints a JSON result, then stops the service, removes
  the library and exits 0 or 1.

## Electron version

Pinned to **44.7.1**: released 2026-10-13, the newest patch at least two weeks
old when chosen on 2026-10-28. `npm audit` reports
[GHSA-jr5w-w6x2-84p9](https://github.com/advisories/GHSA-jr5w-w6x2-84p9)
(compromised eMudhra intermediate certificates) for 44.0.0–44.9.0. The fix,
44.10.0, was published 2026-10-27, too new for the two-week rule. The advisory
concerns TLS certificate trust. The request lockdown above means this shell
makes no TLS connections, so it is not exposed in practice. **Upgrade to
≥ 44.10.0 on or after 2026-11-10.**

Packaging as an installer (electron-builder or similar) is not done yet. It
belongs with M6 distribution, together with bundling Python.
