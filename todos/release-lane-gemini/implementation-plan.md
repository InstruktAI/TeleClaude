# Implementation Plan: release-lane-gemini

## Approach

Implement the Gemini lane by installing `@google/gemini-cli` via `npm` in the GitHub Actions runner. We will reuse the shared `release-inspector.md` prompt to maintain consistency across the triple-lane analysis.

## Proposed Changes

### 1. GitHub Action Configuration

- [x] Update `.github/workflows/release.yaml`.
- [x] Configure `gemini-lane` job:
  - Step 1: Checkout HEAD and last tag.
  - Step 2: Set up Node.js.
  - Step 3: `npm install -g @google/gemini-cli`.
  - Step 4: Run `gemini` CLI with the shared Inspector Prompt.
  - Step 5: Upload resulting report as artifact.

## Task Sequence

1. [x] Add `gemini-lane` job to `release.yaml`.
2. [ ] Ensure `GOOGLE_API_KEY` is available in CI secrets.
3. [ ] Test the lane and verify JSON parity with other lanes.

## Verification

- Confirm `gemini` CLI is correctly installed and authenticated in CI.
- Verify report output schema alignment.
