# Requirements: adapter-output-delivery

## Goal

Guarantee continuous agent output delivery and consistent cross-adapter input reflection while preserving clear origin UX behavior.

## Scope

### In scope

1. **Continuous output delivery**

- Threaded adapters receive assistant output between tool calls, not only at tool boundaries.
- Output stream traffic follows dual-lane delivery (origin + admin destinations).

2. **Routing contract alignment**

- `feedback_notice_error_status` is `ORIGIN_ONLY`.
- `last_output_summary` is `ORIGIN_ONLY` and non-threaded/in-edit UX only.
- `output_stream_chunk_final_threaded` is `DUAL`.

3. **Reflection lane behavior**

- User input reflection is sent to all provisioned non-source UI adapters.
- Reflection applies consistently for text, voice, and MCP-origin input.
- Reflection attribution uses actor metadata (`reflection_actor_id`, `reflection_actor_name`, `reflection_actor_avatar_url`) with best-effort fallback naming.

4. **Adapter rendering behavior**

- Discord reflection uses webhook presentation when available, with safe fallback to bot send.

### Out of scope

- Discord infrastructure provisioning and category policy.
- Per-computer project category strategy.
- Changes to experiment config format or evaluation logic.

## Success Criteria

- [ ] Claude/Gemini threaded sessions deliver intermediate output between tool calls.
- [ ] Notices/errors/status messages remain origin-only.
- [ ] `last_output_summary` remains origin-only and non-threaded.
- [ ] Reflections fan out to all non-source provisioned adapters for text/voice/MCP origins.
- [ ] Reflections include actor attribution metadata with stable fallback behavior.
- [ ] Discord reflection presentation works via webhook path with fallback safety.

## Constraints

- Keep daemon lifecycle policy intact.
- Keep hook-triggered incremental rendering path intact.
- Do not couple cleanup trigger semantics to recipient selection.

## Risks

- Cross-adapter fanout volume increases with active destinations.
- Reflection presentation differs by adapter capabilities; behavior must remain contract-consistent.
