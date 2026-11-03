# Next observable work

See [the current feature completion review](feature-completion.md) for the
implementation-based release checklist. The milestone notes below originated
before the physical scanner session; current real capture and crop/curves are
implemented, while broader acceptance work remains.

- M1.5: isolated CyberView static analysis, evidence-backed USB emulation and original-vendor guest testing; see FRAME_SPEC.md and docs/progress.md. Do not replace the production simulator.
- M2: broader photographic negative reference comparisons, measured color characterization, high-precision codecs and memory benchmarks. Crop/curves, preserving 16-bit TIFF input/output and manual film-base controls are implemented; the complete M2 acceptance gate is still open.
- Timer hardening: custom sourced recipe editor, chemistry batches/capacity, offline session reconciliation, accessible foreground sound and wake lock. Demo recipe is water rehearsal only.
- M3/M4: a physical image and device/driver inventory exist. Complete real-roll scanning, reliable positioning/recovery and repeatable safe transport acceptance remain open.
- Companion: deliberate LAN enablement, HTTPS and scoped pairing; real iPhone/iPad device validation. Background web alarms remain best effort.
- Archive: full portable backup/restore command, migration tests, crash injection between file/database commits and orphan reconciliation. Current SQLite backups accompany verified archive completion; they do not replace separate image backups.
- Scanner UI: manual boundary corrections, selected-frame rescan with revisions and audit trail, safe capability-based transport controls after real verification.
- Packaging: Windows installer, pinned distribution dependencies and full transitive notices.
