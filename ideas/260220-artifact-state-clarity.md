# Artifact State Clarity Gap — Idea

## Summary

Memory ID 22: "Artifacts describe target state, never transition state" — this is a key principle, but it's being violated by agent artifacts that include transition markers.

## Current State

- **Documented**: Clear principle in memory
- **Not enforced**: No validation prevents agents from writing transition state
- **Confusion**: Artifacts like `state.json` in work items describe current state (a transition), not target state

## Pattern

This is a **design hygiene issue** with implications for:

- Agent communication (agents shouldn't track work-in-progress in durable artifacts)
- System debuggability (transition state should be in logs, not files)
- CI/CD safety (artifacts describe what was built, not what's being built)

## Actionable Insights

1. **Separate concerns**: Distinguish between:
   - **Target state** (what we want to build): `implementation-plan.md`, `requirements.md`
   - **Current state** (what's running now): Logs, memory, temporary files
   - **Transition state** (what's being worked on): Database records, not files

2. **Validation rule**: Agent artifact checkers should reject files that contain timestamps, UUIDs, or completion markers that indicate they're capturing current state.

3. **State machine clarity**: The `next-work` state machine should use database state, not file state, to track work phases.

## Next Steps

- Create `docs/project/spec/artifact-state-contract.md` — Clarify what artifacts can and cannot contain
- Add validation to agent linters
- Refactor `todos/*/state.json` to use database-backed state

## Related Memories

- ID 22: Artifacts describe target state, never transition state
- ID 21: Jobs architecture: agents as supervisors of scripts
