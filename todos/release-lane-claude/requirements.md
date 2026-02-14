# Requirements: release-lane-claude

## Goal

Implement the Claude Code release inspector lane. This AI-driven workflow analyzes the diff between the current HEAD and the last release tag to determine if a release is warranted (Patch vs Minor).

## Success Criteria

- [x] Claude correctly identifies changes to public surfaces (CLI, MCP, Events, Config) by comparing the codebase to `docs/manifests/`.
- [x] Claude produces a structured report (JSON) containing:
  - `classification`: "patch" | "minor" | "none"
  - `rationale`: Descriptive text explaining the decision.
  - `contract_changes`: List of modified/added/removed surface items.
  - `release_notes`: Draft notes for the GitHub Release.
- [x] Integration with `anthropics/claude-code-action@v1` in `.github/workflows/release.yaml`.
- [x] The workflow successfully authenticates using `ANTHROPIC_API_KEY`.

## Constraints

- **Technical Continuity**: Must use the `claude` CLI directly (via the GitHub Action).
- **Semver Policy**: 0.x logic (Patch = no surface changes, Minor = any surface change).
- **Isolation**: Must run in a read-only environment (read-only checkout or sandbox).

## Risks

- Flaky diff analysis if the prompt is too vague.
- Context limits if the diff is massive.
