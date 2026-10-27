# FRAME / FilmScanner

A local film workflow prototype: develop, scan, process and preserve your rolls. FRAME_SPEC.md is the authoritative specification.

The current application uses a **clearly labeled scanner simulator**. It does not control or validate a real Pacific Image PF1800 AFL.

```powershell
npm run setup
npm run build
npm start
```

Open http://127.0.0.1:8765. See [setup](docs/setup.md), [progress](docs/progress.md), [capabilities](docs/capability-matrix.md), [agent configuration](docs/agents.md) and [next work](docs/backlog.md).

Python owns the API, SQLite archive, simulator, developing timers and image pipeline. React/TypeScript provides a shared desktop and phone layout. The original file is saved unchanged with a SHA-256 record; edits and exports are separate. The water-only practice recipe is demonstration data, never chemistry guidance.

Run `npm test` for core tests and `npm run build` for the checked production client. User library files and credentials are excluded from source control.
