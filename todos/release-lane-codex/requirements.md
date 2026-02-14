# Requirements: release-lane-codex

## Goal

Implement the Codex CLI release inspector lane. This AI-driven workflow analyzes the diff between current HEAD and the last release tag using the `codex` CLI to ensure technical continuity.

## Success Criteria

- [x] Codex correctly identifies changes to public surfaces (CLI, MCP, Events, Config) by comparing the codebase to `docs/manifests/`.
- [x] Codex produces a structured report (JSON) using the same schema as the Claude lane.
- [x] Integration with `openai/codex-action@v1` in `.github/workflows/release.yaml`.
- [x] The workflow successfully authenticates using `OPENAI_API_KEY`.

## Constraints

- **Technical Continuity**: Must use the `codex` CLI directly (via the GitHub Action).
- **Semver Policy**: 0.x logic.
- **Isolation**: Must use `sandbox: read-only`.

## Risks

- Divergence in classification between Codex and Claude (to be handled by the Arbiter).
