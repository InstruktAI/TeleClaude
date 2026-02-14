# Implementation Plan: release-pipeline-simulation

## Phase 1: Mock Infrastructure

- [ ] Create `tests/fixtures/release-simulation/` directory.
- [ ] Create JSON fixtures for the 3 scenarios (Unanimous, Split, Override).
  - `scenarios/unanimous/claude.json`, `codex.json`, `gemini.json`
  - `scenarios/split/...`
  - `scenarios/override/...`
- [ ] Create a `mock-agent-action` (composite action or simple script) that takes a `scenario` input and outputs the corresponding JSON artifact.

## Phase 2: Simulation Workflow

- [ ] Create `.github/workflows/test-release-pipeline.yaml`.
- [ ] Define a matrix strategy to run all 3 scenarios in parallel.
- [ ] **Job 1: Mock Lanes:**
  - Checkout code.
  - Copy fixture JSONs to `artifacts/` based on matrix scenario.
  - Upload artifacts (mimicking the real agent jobs).
- [ ] **Job 2: Arbiter:**
  - Download artifacts.
  - Run `scripts/release_consolidator.py`.
  - Upload `arbiter-decision.json`.
- [ ] **Job 3: Assertions:**
  - Download decision.
  - Run a simple bash/python script to assert the decision matches the scenario expectation.
    - Unanimous -> Authorized: True, Version: Patch
    - Split -> Authorized: True, Version: Patch (Majority)
    - Override -> Authorized: False (or Needs Human), Rationale contains "Safety"

## Phase 3: Documentation

- [ ] Update `docs/project/design/architecture/jobs-runner.md` (or equivalent CI doc) to document the simulation strategy.
- [ ] Add instructions on how to add new test scenarios.

## Phase 4: Verification

- [ ] Open a PR with these changes.
- [ ] Verify the `test-release-pipeline` turns Green.
