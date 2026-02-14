# Requirements: release-pipeline-simulation

## Goal

Establish a deterministic, fast, and cost-free CI pipeline (`test-release-pipeline.yaml`) that verifies the `release.yaml` logic by mocking the AI agent steps. This ensures the "wiring" (artifact passing, JSON parsing, Arbiter logic, git tagging) is robust without relying on live, non-deterministic LLMs.

## Problem Statement

The current `release.yaml` depends on live AI agents (Claude, Codex, Gemini). Testing changes to the workflow is risky and expensive because:

1.  **Non-Determinism:** Agents might return different results, making it hard to test edge cases (like split votes).
2.  **Cost/Latency:** Running 3 full analysis lanes for every workflow PR is wasteful.
3.  **Safety:** We need to prove the Arbiter correctly handles "Contract Violation" overrides and "Fatal Error" masking _before_ we trust it with production releases.

## Success Criteria

- [ ] **Mock Actions:** Create a local composite action or script that mimics the interface of the real AI agents (Inputs: `diff`; Outputs: `report.json` artifact).
- [ ] **Test Pipeline:** Create `.github/workflows/test-release-pipeline.yaml` that triggers on PRs to `.github/workflows/`.
- [ ] **Scenarios:** The pipeline must run the Arbiter against 3 pre-canned scenarios:
  1.  **Unanimous Patch:** All 3 agents say "patch". -> Result: `vX.Y.Z+1` authorized.
  2.  **Split Vote:** 2 Patch, 1 Minor. -> Result: `patch` wins (Majority).
  3.  **Conservative Override:** Majority "None", Minority "Patch" with `contract_changes: true`. -> Result: `minor` wins (Safety).
- [ ] **Artifact Verification:** The test pipeline must assert that the generated `release-notes.md` contains the expected Rationale and Lane Summary.
- [ ] **Dry-Run Validation:** Verify the tagging step runs with `--dry-run` and does not crash on the generated version number.

## Constraints

- **Zero Token Usage:** Must not make external API calls.
- **Fast:** Should complete in < 2 minutes.
- **Isomorphic:** The `release_consolidator.py` used in the test must be the exact same script used in production.
