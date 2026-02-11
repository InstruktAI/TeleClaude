# Implementation Plan: Release Automation

## Phase 1: Contract Manifests

Define what constitutes the "Public Surface" that the AI must protect.

- [ ] **Create `docs/project/spec/public-surface.md`**: List CLI commands (`telec`), MCP tools (`teleclaude__*`), and Config schema (`config.yml`).
- [ ] **Create `tests/contract/`**: Add basic snapshot tests for CLI help output and MCP tool lists (to help AI see changes).

## Phase 2: Inspector Prompts

Author the prompts that drive the AI lanes.

- [ ] **Create `agents/prompts/release-inspector.md`**: The system prompt for analyzing diffs.
  - _Instructions:_ "You are the Release Inspector. Compare HEAD to {last_tag}. Check against @public-surface.md. Output JSON."
- [ ] **Create `agents/prompts/release-arbiter.md`**: The prompt for synthesizing lane reports.

## Phase 3: GitHub Actions Workflow

Build the `.github/workflows/release.yml` pipeline.

- [ ] **Job 1: Prereqs**: Checkout, fetch tags, run `make test`.
- [ ] **Job 2: Lane A (Claude)**: Run `claude-code` action. Input: `git diff`. Output: artifact `claude-report`.
- [ ] **Job 3: Lane B (Codex)**: Run `codex-cli` action. Input: `git diff`. Output: artifact `codex-report`.
- [ ] **Job 4: Arbiter**: Download artifacts. Run Arbiter AI. Output: `decision.json`.
- [ ] **Job 5: Tag & Publish**: Read `decision.json`. If `release=true`, push tag and create GitHub Release.

## Phase 4: Verification

- [ ] **Dry Run**: Run workflow on a branch with `dry-run: true`.
- [ ] **Patch Test**: Merge a dummy fix to `main`. Verify patch bump.
- [ ] **Minor Test**: Merge a non-breaking feature. Verify minor bump.
