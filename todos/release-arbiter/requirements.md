# Requirements: release-arbiter

## Goal

Implement the Consensus Arbiter step in the release automation pipeline. This step consumes the three AI lane reports (Claude, Codex, Gemini), resolves any conflicts, and emits the authoritative release decision.

## Success Criteria

- [ ] Arbiter correctly selects the most complete and accurate report when classifications diverge.
- [ ] Arbiter produces a final JSON decision payload:
  - `release_authorized`: `true` | `false`
  - `target_version`: `patch` | `minor`
  - `authoritative_rationale`: Brief explanation of the consensus.
- [ ] Authorized tagging: The workflow automatically creates a git tag and GitHub Release ONLY if the arbiter authorizes it.
- [ ] Evidence-driven: Arbiter output includes links to the lane artifacts it considered.

## Constraints

- **Consensus Rule**: If 2 out of 3 AIs agree on a classification, the Arbiter typically follows that majority unless one report is significantly more detailed.
- **Fail-Safe**: If no consensus is reached or data is missing, `release_authorized` MUST be `false`.

## Risks

- Divergence where all 3 AIs provide different classifications (requires "Needs Human" exit code).
