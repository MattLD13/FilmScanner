# FRAME contributor rules
- Treat FRAME_SPEC.md as authoritative. Preserve original acquisitions and distinguish simulation from hardware evidence.
- Use Python for the local API, scanner simulator and imaging; React/TypeScript for the responsive client. Keep shared contracts in packages/contracts.
- Delegate independent work only, with explicit file ownership and acceptance tests. At most three subagents. Prefer Luna for bounded research, Sol for scanner/imaging/review, Terra for UI.
- Timers derive from persisted timestamps; never pause physical chemistry. Demo timings must be labeled and acknowledged.
- Bind locally by default, authenticate archive/API access, and keep real hardware commands disabled until verified.
- Run targeted tests and the workflow suite before reporting milestones complete. Report actual commands and failures.
- Never commit library data, credentials, runtime tokens, or machine-specific state.
- /graphify invokes the installed graphify skill before other work.
