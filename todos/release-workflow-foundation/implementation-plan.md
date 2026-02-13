# Implementation Plan: release-workflow-foundation

## Approach

Migrate the local `make lint` and `make test` logic into a GitHub Actions workflow. Create a separate `release` workflow that depends on the test workflow and sets up the environment for future AI lanes.

## Proposed Changes

- [ ] Create `.github/workflows/lint-test.yaml`.
- [ ] Create `.github/workflows/release.yaml` (skeleton).

## Task Sequence

1. [ ] Implement `lint-test.yaml` using `astral-sh/setup-uv`.
2. [ ] Verify CI pass on a dummy PR.
3. [ ] Implement `release.yaml` with placeholder steps for Claude and Codex.
4. [ ] Configure `main` push trigger for `release.yaml`.
