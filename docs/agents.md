# Codex agents

The project default is GPT-6.1 Sol at high reasoning effort. This is a project-scoped default; it does not change the user's global Codex configuration or retroactively switch an already running session. Codex loads project configuration only when the repository is trusted, and a refreshed session may be needed after changes.

Six custom roles are available under `.codex/agents/`: `scanner`, `interface`, `research`, `reviewer`, `image`, and `reverse`. Use them only for independent tasks, with explicit ownership and acceptance criteria as required by `AGENTS.md` and `FRAME_SPEC.md`. Models and reasoning efforts are recorded in each role file and were present in the local model catalog at setup time; access can change.

The project cap is three concurrently open spawned-agent threads. Current Codex documentation defines `agents.max_concurrent_threads_per_session` as excluding the primary session, so this permits the primary plus up to three spawned threads. A configured role is a template, not an active agent.

Custom agent files inherit parent permissions and tools. Instructions inside a role file do not create additional sandbox or approval boundaries. Keep hardware controls disabled until verified and follow the project approval rules for consequential actions.

## Verification record

- Codex CLI reported `0.164.0-alpha.11.1`.
- The local models catalog listed `gpt-6.1-sol` and `gpt-6.1-terra` with low through ultra effort, and `gpt-6-luna` with low through max effort.
- Official agent configuration documentation was checked on 2026-10-27: [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) and [Configuration Reference](https://learn.chatgpt.com/docs/config-file/config-reference).
- TOML syntax is validated with Python's standard-library TOML parser as part of this change.
