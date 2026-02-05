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

### 4) Report Schemas

Define strict JSON schemas to make decisions machine-checkable:

- `.github/schemas/release-report.schema.json`
  - Required fields: `decision`, `confidence`, `evidence`, `notes_markdown`
  - `decision`: `patch | minor | skip`
  - `evidence`: last tag, diff range, contract checks, test status
- `.github/schemas/release-decision.schema.json`
  - Required fields: `release`, `bump`, `notes_markdown`, `selected_lane`
  - `release`: `true | false`
  - `bump`: `patch | minor`

### 5) Dual-Lane Workflows

Add two near-identical workflows:

- `.github/workflows/release-inspector-claude.yml`
- `.github/workflows/release-inspector-codex.yml`

Each produces:

- `report-claude.json` / `report-codex.json`
- `notes-claude.md` / `notes-codex.md`

Both must be uploaded as workflow artifacts.

### 6) Orchestration (Atomic)

Preferred: one orchestrator workflow with parallel jobs and a dependent arbiter:

- `release-orchestrator.yml`
  - `inspect-claude` job → uploads lane report
  - `inspect-codex` job → uploads lane report
  - `arbiter` job (needs both) → produces `decision.json` + `release-notes.md`
  - `release` job (needs arbiter) → performs tagging/release

Alternative (if separate workflows): use `workflow_run` to trigger the arbiter
and pull artifacts by run ID. This is more complex; prefer single workflow.

### 7) Consensus Arbiter

Add a small arbiter step (third AI pass):

- Consumes both reports and chooses the most convincing report.
- Emits `decision.json` (authoritative).
- Writes `release-notes.md` (from chosen report).

Only the arbiter decision can trigger tagging and releasing.

### 8) Release Execution

If `decision.json` says `release`:

- Bump version (patch or minor) with `uv version --bump` based on arbiter output.
- Tag `vX.Y.Z` and push tag.
- Create GitHub Release using `release-notes.md`.

If `decision.json` says `skip`, exit cleanly.

Idempotency guards:

- Skip if `git diff <last_tag>..HEAD` is empty.
- Skip if the computed tag already exists.

### 9) CI Prerequisite

Add `ci.yml` for PRs:

- Lint + tests on PRs.
- Required status checks before merge.

### 10) Codex Runner Auth Provisioning (automation)

Automate provisioning of Codex auth on the self-hosted runner:

- Install/ensure Codex CLI on the runner host.
- Run `codex login` once for the runner user.
- Persist `~/.codex/auth.json` under the runner’s home.
- Add a periodic validation step (e.g., cron or workflow check) to confirm the
  file exists and is readable before running release workflows.

Claude Code auth remains a runner/secret responsibility; the workflow consumes
what is provided but does not provision it.

## Implementation Checklist

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
