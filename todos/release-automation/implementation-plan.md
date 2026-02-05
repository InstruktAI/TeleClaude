# Release Automation — Implementation Plan

## Goals

- Automated release inspector on every push to `main`.
- Single decision authority: patch vs minor based on diff vs last release tag.
- Dual-lane AI reports (Claude Code + Codex CLI) with a consensus arbiter.
- Deterministic contract checks to remove guesswork.
- Idempotent releases (no re-tagging when no diff).

## Non-Goals

- Alpha/beta tags or pre-releases.
- Manual approval for patches.
- Major releases (disabled until explicitly enabled).

## Inputs

- `todos/release-automation/input.md`
- Third-party docs:
  - `third-party/claude-code/github-actions`
  - `third-party/codex-cli/github-actions`

## Plan

### 1) Contract Manifests (public surface)

Create a canonical contract folder and schema:

- `release/contracts/`
  - `cli-commands.json`
  - `mcp-tools.json`
  - `event-types.json`
  - `config-schema.json`
  - `dto-fields.json`

Define a small JSON schema for each to keep them consistent and machine-checkable.

### 2) Contract Tests

Add tests that assert runtime matches the manifests:

- CLI: parse `teleclaude/cli/telec.py` command registry.
- MCP: compare `teleclaude/mcp/tool_definitions.py`.
- Events: compare `teleclaude/core/events.py` + any public event registries.
- Config: compare `config.yml` schema + documented env vars.
- DTOs: compare `teleclaude/api_models.py`.

These tests should fail when public surface changes are not reflected in the contracts.

### 3) Release Inspector Prompts

Create prompts used by both lanes:

- `.github/prompts/release-inspector.prompt.yml`
  - Inputs: diff summary, contract test results, lint/test status, last tag.
  - Output: JSON report with classification (`patch|minor|skip`) + notes.

### 4) Dual-Lane Workflows

Add two near-identical workflows:

- `.github/workflows/release-inspector-claude.yml`
- `.github/workflows/release-inspector-codex.yml`

Each produces:

- `report-claude.json` / `report-codex.json`
- `notes-claude.md` / `notes-codex.md`

Both must be uploaded as workflow artifacts.

### 5) Consensus Arbiter

Add a small arbiter step (third AI pass):

- Consumes both reports and chooses the most convincing report.
- Emits `decision.json` (authoritative).
- Writes `release-notes.md` (from chosen report).

Only the arbiter decision can trigger tagging and releasing.

### 6) Release Execution

If `decision.json` says `release`:

- Bump version (patch or minor) with `uv version --bump`.
- Tag `vX.Y.Z` and push tag.
- Create GitHub Release using `release-notes.md`.

If `decision.json` says `skip`, exit cleanly.

### 7) CI Prerequisite

Add `ci.yml` for PRs:

- Lint + tests on PRs.
- Required status checks before merge.

## DoD (Definition of Done)

- Contract manifests exist and are enforced by tests.
- Dual-lane reports produced on every `main` push.
- Arbiter produces a single authoritative decision.
- Release workflow is idempotent and only runs on arbiter approval.
- Patch/minor decisions align with 0.x policy.
- Release notes generated and attached to GitHub Releases.

## Status

- [ ] Contract manifests defined
- [ ] Contract tests added
- [ ] Release inspector prompts written
- [ ] Dual-lane workflows added
- [ ] Arbiter step implemented
- [ ] Release execution wired
- [ ] CI workflow added
