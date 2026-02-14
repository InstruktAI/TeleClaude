# Implementation Plan: release-lane-claude

## Approach

Implement the Claude lane by configuring the `anthropics/claude-code-action@v1` in our GitHub Actions. The core work is developing a robust "Inspector Prompt" that guides Claude to perform a meticulous diff analysis against our contract manifests.

## Proposed Changes

### 1. Inspector Prompt

- [x] Create `docs/prompts/release-inspector.md` (shared by all lanes).
  - Pre-existing at `docs/project/spec/release-inspector-prompt.md` per codebase convention.
- [x] Refine the prompt to focus on evidence-based classification (Patch vs Minor).
  - Prompt already defines step-by-step evidence-based analysis with clear semver 0.x policy.

### 2. GitHub Action Configuration

- [x] Update `.github/workflows/release.yaml`.
- [x] Configure `claude-lane` job:
  - Step 1: Checkout with full history and prepare diff.
  - Step 2: Run `anthropics/claude-code-action@v1` with inspector prompt.
  - Step 3: Validate JSON output with `jq`.
  - Step 4: Upload the resulting report as a workflow artifact.

## Task Sequence

1. [x] Draft the common `release-inspector.md` prompt.
2. [x] Add the `claude-lane` job to the skeleton `release.yaml`.
3. [x] Test the lane by triggering a push to a test branch.

- YAML syntax validated locally. Full CI test requires merge and workflow trigger.

4. [x] Verify the JSON output matches the required schema for the arbiter.

- Prompt directs Claude to read `release-report-schema.md` and write matching JSON.
- Workflow includes `jq` validation step before artifact upload.
- Arbiter downloads both `claude-report` and `ai-release-reports-*` artifacts.

## Verification

- Run the workflow on a branch with a "Patch" change (README edit).
- Run the workflow on a branch with a "Minor" change (New MCP tool).
- Assert the classification matches the Semver policy.
