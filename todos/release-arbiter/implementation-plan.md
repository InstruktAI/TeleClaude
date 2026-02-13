# Implementation Plan: release-arbiter

## Approach

Implement the arbiter as a final AI step using `run_once` (Restricted mode) logic. The arbiter will receive the text of all three lane reports and be prompted to produce a consolidated JSON decision.

## Proposed Changes

### 1. Arbiter Logic

- [ ] Create `docs/prompts/release-arbiter.md`.
- [ ] Implement a python script `scripts/release_consolidator.py` that downloads the artifacts and calls the arbiter agent.

### 2. GitHub Action Integration

- [ ] Update `release.yaml` to include the `consensus-arbiter` job.
- [ ] Implement the `authorized-tag` step:
  - If JSON `release_authorized` is true:
    - Compute next version number.
    - `git tag` and `git push`.
    - `gh release create`.

## Task Sequence

1. [ ] Develop the `release-arbiter.md` prompt.
2. [ ] Implement the `release_consolidator.py` script.
3. [ ] Wire the arbiter into the release workflow.
4. [ ] Test conflict resolution by feeding dummy conflicting reports.

## Verification

- Mock 3 reports: [Minor, Minor, Patch] -> Assert Arbiter chooses Minor.
- Mock 3 reports: [None, None, Patch] -> Assert Arbiter chooses None.
