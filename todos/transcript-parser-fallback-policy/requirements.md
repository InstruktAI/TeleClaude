# Requirements: transcript-parser-fallback-policy

## Goal

Centralize and codify the transcript parser fallback behavior when `session.active_agent`
is unknown, missing, or refers to a legacy/unsupported agent identifier. Replace the current
silent coercion to Claude with an explicit, logged, and testable policy.

## Scope

### In scope

- The two fallback sites in the transcript rendering pipeline:
  - `teleclaude/api_server.py` `/messages` endpoint parser selection (line ~1096-1100)
  - `teleclaude/api/streaming.py` `_get_agent_name()` (line ~119-125)
- The related `_get_entries_for_agent()` in `teleclaude/utils/transcript.py` which returns
  `None` for unknown agents (defensive but undocumented behavior)
- `get_transcript_parser_info()` in `teleclaude/utils/transcript.py` which has no fallback
  at all (would `KeyError` on unknown agent)
- A centralized resolution function that all four sites can call
- Structured logging when fallback is triggered
- Unit tests covering unknown, missing (`None`/empty), and all canonical agent values

### Out of scope

- Changing the `AgentName` enum or adding new agent types
- Launch default-agent selection logic (already delivered as `default-agent-resolution`)
- Modifying how `session.active_agent` is set during session creation
- Historical data migration (transcripts already stored will continue to render correctly
  since the fallback behavior remains Claude-based — it just gets logged now)

## Success Criteria

- [ ] A single `resolve_parser_agent(active_agent: str | None) -> AgentName` function exists
      in `teleclaude/core/agents.py` that encapsulates the fallback policy
- [ ] All four callsites use the centralized function instead of inline try/except
- [ ] A `warning`-level log entry is emitted whenever the fallback is triggered, including
      the original `active_agent` value
- [ ] The fallback resolves to `AgentName.CLAUDE` (preserving backward compatibility for
      rendering historical transcripts)
- [ ] Unit tests in `tests/unit/test_agents.py` cover:
  - Known canonical values (`"claude"`, `"codex"`, `"gemini"`) resolve correctly
  - `None` input resolves to Claude with warning
  - Empty string resolves to Claude with warning
  - Unknown string (e.g. `"gpt4"`) resolves to Claude with warning
  - Case-insensitive resolution still works (e.g. `" CLAUDE "`)
- [ ] No existing tests break

## Constraints

- The fallback must remain `AgentName.CLAUDE` to preserve rendering compatibility for
  historical transcripts that predate multi-agent support.
- The warning log must not be noisy for the common case where `active_agent` is `None`
  on very new sessions that haven't started yet — use `debug` level for `None`, `warning`
  for genuinely unknown values.
- The centralized function must be a pure function (no side effects beyond logging) so it
  remains easy to test.

## Risks

- If `get_transcript_parser_info()` is called with an unknown `AgentName` in a code path
  that doesn't go through the centralized resolver, it will still `KeyError`. The resolver
  must be used at every callsite, not just the two already identified. The implementation
  plan identifies all four sites.
