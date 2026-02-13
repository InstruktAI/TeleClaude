# Requirements: release-lane-gemini

## Goal

Implement the Gemini release inspector lane. This AI-driven workflow analyzes the diff between current HEAD and the last release tag using the `gemini` CLI to ensure technical continuity across our triple CI lanes.

## Success Criteria

- [ ] Gemini correctly identifies changes to public surfaces (CLI, MCP, Events, Config) by comparing the codebase to `docs/manifests/`.
- [ ] Gemini produces a structured report (JSON) using the same schema as Claude and Codex.
- [ ] Integration with our custom CI environment where `gemini-cli` is installed via `npm`.
- [ ] The workflow successfully authenticates using `GOOGLE_API_KEY`.

## Constraints

- **Technical Continuity**: Must use the `gemini` CLI directly.
- **Semver Policy**: 0.x logic.
- **Isolation**: Must run in a restricted environment.

## Risks

- Unique output formatting of the Gemini CLI vs Claude/Codex.
