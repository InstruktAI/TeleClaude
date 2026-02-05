# Release Automation

## Problem Statement

The project lacks automated release management. Currently, releases require manual intervention, version bumping, changelog generation, and tag creation. This is error-prone and inconsistent.

## Intended Outcome

A fully automated release pipeline where:

1. A dedicated AI inspector analyzes diffs on every main push
2. The AI decides whether to release (patch/minor) based on contract manifests
3. Releases are created automatically with generated notes
4. The system is trustworthy enough to operate without human approval for patches

## Requirements

### Core Release Strategy

1. **Single Dedicated AI Release Inspector**
   - One AI, one pass, meticulous and evidence-driven
   - Runs on every push to main
   - Compares HEAD to the last release tag (not "latest main")
   - Decides release classification deterministically

2. **Version Policy (0.x Semver)**
   - Patch: No public surface changes, tests green
   - Minor: Public surface changed (breaking under 0.x policy)
   - Major: Disabled until explicitly enabled

3. **Public Surface Contract Manifests**
   - CLI command surface
   - MCP tool names and signatures
   - Event types and payload fields
   - Config schema and environment variables
   - Public API structs (DTOs)
   - Contract tests that assert runtime matches manifests

4. **Decision Checklist (AI Must Verify)**
   - [ ] Compared against last release tag
   - [ ] Tests and lint passed
   - [ ] No public surface removals/renames unless allowed
   - [ ] No schema/config contract changes unless allowed
   - [ ] No migration required unless handled
   - [ ] Release notes generated

5. **Decision Outcomes**
   - If all pass → release (patch or minor based on surface changes)
   - If any fail/unknown → skip release (no action)

### Dual-Lane Pipeline (Claude Code + Codex CLI)

Two parallel workflows, nearly identical, dispatching to different AI agents:

1. **Claude Code Lane**
   - Uses `anthropics/claude-code-action@v1`
   - Authenticates via `ANTHROPIC_API_KEY`
   - Runs the release inspector prompt

2. **Codex CLI Lane**
   - Uses `openai/codex-action@v1`
   - Authenticates via `OPENAI_API_KEY`
   - Runs the same release inspector prompt
   - Uses `sandbox: read-only` for analysis

3. **Consensus Arbiter (Third AI pass)**
   - Consumes both lane reports (Claude + Codex)
   - Chooses the most convincing/complete report
   - Emits a JSON decision payload used by the release automation
   - Produces its own short audit note explaining the selection
   - Arbiter output is the only authority that can tag/release

### Workflow Triggers

- **Auto (push to main)**: AI decides patch/minor based on diff vs last release tag

### Required Outputs

- Release tag (vX.Y.Z)
- GitHub Release with generated notes
- Release notes include: rationale, contract changes, breaking changes
- Lane reports from Claude Code + Codex CLI
- Arbiter JSON decision output (authoritative)
- Lane/arbiter reports stored as workflow artifacts

### CI Pipeline Prerequisites

- Lint + test workflow must exist and run on PRs
- Release workflow runs after lint/test passes on main
- Tests must be deterministic (no flaky tests)
- Release must be idempotent (no re-tagging when no diff since last tag)

## Success Criteria

- [ ] AI correctly classifies patch vs minor 95%+ of the time
- [ ] No false releases (releasing when nothing changed)
- [ ] No missed releases (skipping when a release was warranted)
- [ ] Release notes are accurate and useful
- [ ] Both Claude Code and Codex lanes produce consistent results
- [ ] Arbiter consistently selects the strongest report when the lanes diverge
- [ ] No duplicate tags/releases from parallel lanes

## Non-Goals

- Alpha/beta tagging (just releases)
- Human approval step for patches
- Complex branching strategies

## Technical Dependencies

- GitHub Actions
- Claude Code GitHub Action (`anthropics/claude-code-action@v1`)
- Codex CLI GitHub Action (`openai/codex-action@v1`)
- API keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- JSON arbiter output schema (authoritative release decision)
- Shared report schema for lane outputs (Claude + Codex)

## Research Completed

Third-party documentation indexed:

- `third-party/claude-code/github-actions` - Claude Code GitHub Actions integration
- `third-party/codex-cli/github-actions` - Codex CLI GitHub Actions integration

## Implementation Phases

### Phase 1: Contract Manifests

- Define public surface manifests
- Create contract tests

### Phase 2: CI Workflow

- Add lint + test workflow for PRs
- Ensure tests are deterministic

### Phase 3: Release Workflow (Claude Code)

- Create release inspector workflow
- Test with Claude Code lane first

### Phase 4: Release Workflow (Codex CLI)

- Add parallel Codex lane
- Compare outputs for consistency

### Phase 5: Refinement

- Tune prompts based on results
- Add metrics/logging for decision auditing

### Phase 6: Arbiter + Consolidated Release

- Implement arbiter step to choose between lane reports
- Use arbiter JSON output as the only authority for tagging/releases
