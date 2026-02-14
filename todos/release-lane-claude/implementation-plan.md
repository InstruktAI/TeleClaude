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

- [ ] Update `.github/workflows/release.yaml`.
- [ ] Configure `claude-lane` job:
  - Step 1: Checkout HEAD and last tag.
  - Step 2: Install dependencies (uv).
  - Step 3: Run `claude` CLI via Action with the Inspector Prompt.
  - Step 4: Upload the resulting report as a workflow artifact.

## Task Sequence

1. [x] Draft the common `release-inspector.md` prompt.
2. [ ] Add the `claude-lane` job to the skeleton `release.yaml`.
3. [ ] Test the lane by triggering a push to a test branch.
4. [ ] Verify the JSON output matches the required schema for the arbiter.

## Verification

- Run the workflow on a branch with a "Patch" change (README edit).
- Run the workflow on a branch with a "Minor" change (New MCP tool).
- Assert the classification matches the Semver policy.
