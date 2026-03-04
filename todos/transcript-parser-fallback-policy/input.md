# Input: transcript-parser-fallback-policy

## Context

`default-agent-resolution` intentionally deferred parser/transcript fallback behavior for unknown or legacy agent values in:

- `teleclaude/api_server.py` (parser-selection fallback when `session.active_agent` is unknown)
- `teleclaude/api/streaming.py` (`_get_agent_name()` fallback behavior)

Those fallbacks affect transcript rendering compatibility and were not changed as part of launch default resolution.

## Requested Outcome

Define and implement transcript parser fallback policy and migration that:

1. Specifies canonical behavior for unknown/legacy agent identifiers.
2. Preserves rendering for historical transcripts where required.
3. Clarifies fail-fast vs fallback boundaries and rationale.
4. Adds tests for legacy, unknown, and canonical agent cases.

## Notes

- Keep this policy separate from launch default-agent selection logic.
- Include a clear migration path to reduce long-term fallback debt.
