# Implementation Plan: release-pipeline-simulation

## Phase 1: Mock Infrastructure

- [x] Create `tests/fixtures/release-simulation/` directory.
- [x] Create JSON fixtures for the 3 scenarios (Unanimous, Split, Override).
  - `scenarios/unanimous/claude.json`, `codex.json`, `gemini.json`
  - `scenarios/split/...`
  - `scenarios/override/...`
- [x] Create `expected.json` with expected outcomes per scenario (replaces composite action — simpler approach).

## Phase 2: Simulation Workflow

- [x] Create `.github/workflows/test-release-pipeline.yaml`.
- [x] Trigger: `pull_request` paths `.github/workflows/**`, `scripts/release_consolidator.py`, `tests/fixtures/release-simulation/**`.
- [x] Define a matrix strategy to run all 3 scenarios in parallel.
- [x] Each matrix entry runs these steps in sequence:
  1. **Checkout** code.
  2. **Stage fixtures:** Copy the scenario's `claude.json`, `codex.json`, `gemini.json` to working directory.
  3. **Run Arbiter:** `python scripts/release_consolidator.py --claude-report claude.json --codex-report codex.json --gemini-report gemini.json -o arbiter-decision.json`.
  4. **Assert decision:** Run assertion script/step that validates `arbiter-decision.json` against expected outcome:
     - Unanimous -> `release_authorized=true`, `target_version="patch"`.
     - Split -> `release_authorized=true`, `target_version="patch"`.
     - Override -> `release_authorized=true`, `target_version="patch"`, rationale contains `"contract changes"` and `"overriding"`.
  5. **Release notes (Unanimous only):** Replicate the `jq` generation from `release.yaml` authorized-tag job, assert output contains rationale and lane summary.
  6. **Version bump (Unanimous only):** Run the version-bump shell logic from `release.yaml` against a known baseline tag (e.g., `v0.1.5`), assert next version equals `v0.1.6`.

## Phase 3: Documentation

- [ ] Deferred: CI documentation update (not needed for functional delivery; existing workflow is self-documenting).

## Phase 4: Verification

- [ ] Open a PR with these changes.
- [ ] Verify the `test-release-pipeline` turns Green.
