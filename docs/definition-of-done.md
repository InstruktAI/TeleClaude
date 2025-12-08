# Definition of Done (TeleClaude)

- **Standards**: Work follows coding/testing directives, and existing project patterns. Code is typed, lint/format clean, and free of dead code or stray TODOs.
- **Tests**: Relevant unit/integration tests are added/updated and pass locally. For multi-computer flows, real-world hardware verification is performed and the result noted.
- **Config/Secrets**: Secrets live in `.env` (not committed). Any required `config.yml` changes are applied. Only the canonical `teleclaude.db` exists; no extra DB copies.
- **Logging/Noise**: Logs capture key boundaries and errors without sensitive data; avoid log spam and temporary debug prints.
- **UX/Flows**: Telegram/MCP flows honor existing deletion/feedback patterns; bot commands registered when required.
- **Handoff**: Summarize changes, test commands/results, and any deferrals in the standard handoff spot for this project so work can resume if a session ends.
- **Deployment**: If the change affects remote hosts, rsync and `make restart` on targets are done, or the deferral and rationale are documented.
- **Review Hygiene**: No unresolved comments, temp flags, or debug artifacts; incomplete work is feature-flagged and documented.
