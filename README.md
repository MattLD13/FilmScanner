# FRAME

A local film workflow prototype: develop, scan, process and preserve your rolls. FRAME_SPEC.md is the authoritative specification.

FRAME includes a local simulator/developing workflow and a direct-capture workspace
for the PF1800 AFL. Current-frame acquisition, live preview, exposure and fine
transport were tested on this scanner; each command remains gated by its recorded
hardware evidence. See [current handoff](docs/handoff-current.md) for exact limits.

```powershell
npm run setup
npm run build
npm start
```

Open [FRAME](http://127.0.0.1:8765/?workspace=frame) for the scanner workspace, or
the [simulator and developing workflow](http://127.0.0.1:8765/).
For the desktop scanner app, run `npm run frame` after building. The previous
`npm run cyberscan` command and workspace URL remain compatible.

See [setup](docs/setup.md), [progress](docs/progress.md), [capabilities](docs/capability-matrix.md),
[agent configuration](docs/agents.md) and [next work](docs/backlog.md).

See the [current feature completion checklist](docs/feature-completion.md) and
[independent driver workbench](docs/custom-driver.md). `npm run driver:console`
opens the JSON command console in offline mode. The independent
`npm run driver:console -- --identify` and `--status` reads have now been tested
on the scanner without vendor DLLs; arbitrary commands and independent scanning
remain unfinished.
For finding and capturing the complete frame, use
[Auto find borders](docs/auto-find-borders.md).
The [film material interface](docs/film-lab-ui.md) adapts the workspace to color
negative, B&W or slide film while preserving existing photographs and edits.

Python owns the API, SQLite archive, simulator, developing timers and image pipeline. React/TypeScript provides a shared desktop and phone layout. The original file is saved unchanged with a SHA-256 record; edits and exports are separate. The water-only practice recipe is demonstration data, never chemistry guidance.

Isolated vendor/protocol research remains under `research/`. Only commands with
recorded hardware validation are offered by the scanner workspace. Imaging keeps
supported 16-bit acquisitions intact and distinguishes stored sample precision
from measured sensor precision. Reference-derived colour profiles are experimental;
the general negative conversion remains under comparison with CyberView.

Run `npm test` for core tests and `npm run build` for the checked production client. User library files and credentials are excluded from source control.
