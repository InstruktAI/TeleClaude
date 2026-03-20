# Plan Review Findings: refactor-agent-readiness

## Important

### I1: Task 3 verification does not prove the detector resolves markers from agent metadata

Task 3 says `wait_for_agent_ready()` must resolve marker knowledge from
`AgentName.from_str(agent_name).prompt_marker`, which is the core of SC-1 and the
detector-side constraint in `requirements.md`.

The verification it points to does not actually prove that contract. The current
spec file at `trees/refactor-agent-readiness/tests/unit/core/test_agent_readiness.py`
only exercises `agent_name="claude"` and only asserts Claude's marker in the tail.
A detector that hardcodes Claude's marker, or uses a second internal marker map
instead of `AgentName.prompt_marker`, would still make all four cited tests pass.

Because the plan's verification path would let the builder satisfy Task 3 while
still violating the metadata-owned-marker requirement, the plan does not yet pass
the test-review lane anticipation gate.

## Suggestion

- None.

## Resolved During Review

- Corrected Task 1's verification references to the actual spec class name,
  `TestAgentNameMetadataSpec`.
- Added demo validation to Task 6 so the plan explicitly anticipates the demo
  review lane.
- Synced `state.yaml.grounding.referenced_paths` with the plan's referenced files.
