# Implementation Plan: release-lane-codex

## Approach

Implement the Codex lane by configuring `openai/codex-action@v1`. We will reuse the shared `release-inspector.md` prompt to ensure parity in analysis criteria across all AI lanes.

## Proposed Changes

### 1. GitHub Action Configuration

- [x] Update `.github/workflows/release.yaml`.
- [x] Configure `codex-lane` job:
  - Step 1: Checkout HEAD and last tag.
  - Step 2: Install dependencies (uv).
  - Step 3: Run `codex` CLI via Action with the shared Inspector Prompt.
  - Step 4: Upload resulting report as artifact.

## Task Sequence

1. [x] Add the `codex-lane` job to `release.yaml`.
2. [x] Ensure `OPENAI_API_KEY` is available in CI secrets.
3. [x] Test the lane and verify JSON parity with the Claude lane.

## Verification

- Cross-reference Codex and Claude reports on the same branch to ensure they both detect the same surface changes.
