# Requirements: conversation-projection-unification

## Goal

Introduce one canonical core output projection route and move every current output producer/consumer onto it, so the system has one reusable projection layer instead of separate paths to the same truth.

## Scope

### In scope

- A canonical core output projection route in core.
- A canonical `conversation` projection for transcript chains.
- A canonical `terminal_live` projection for poller-driven output snapshots.
- Shared normalization into reusable projection models rather than consumer-specific logic.
- Shared visibility policy for:
  - `text`
  - `thinking`
  - explicitly user-visible tools/widgets
  - suppression of internal tool transcript blocks by default
- Wiring the existing poller-driven standard output producer through the shared projection route without changing adapter implementations.
- Wiring the existing transcript-driven threaded output producer through the shared projection route without changing adapter implementations.
- Web history cutover to the shared conversation projector.
- Web live SSE cutover to the shared conversation projector.
- Mirror/search consumers prepared to use the same conversation projection route.
- Preserving existing adapter-facing `send_output_update()` / `send_threaded_output()` contracts while making them consumers of shared projected output.
- Tests proving web history and web live now share the same semantics.
- Regression tests proving current threaded-mode behavior remains unchanged.
- API/documentation updates needed to describe the new web projection contract.

### Out of scope

- Changes to Telegram adapter behavior or code paths.
- Changes to Discord adapter behavior or code paths.
- Changes to TUI adapter behavior or code paths.
- Changes to threaded-output presentation semantics.
- Reflection routing / adapter boundary ownership changes.
- Telegram tmux-live output unification.
- Adapter routing/presentation cleanup work.

## Success Criteria

- [ ] Poller-driven standard output, threaded transcript output, web history, and web live stream all flow through one core projection route instead of each producer inventing its own semantics.
- [ ] Web history and web live stream are backed by the same core conversation projector.
- [ ] Internal transcript `tool_use` / `tool_result` blocks no longer surface in web chat unless the tool is explicitly allowlisted as user-visible.
- [ ] Web history and live output preserve parity for visible text/thinking content from the same transcript chain.
- [ ] No adapter implementation files under `teleclaude/adapters/` need behavioral changes for this todo.
- [ ] Existing threaded-mode behavior remains unchanged and is covered by regression tests.
- [ ] The current raw `convert_entry()` web-only semantic path is removed or reduced to a serializer over the shared projector output, not an independent classifier.
- [ ] Existing adapter-facing delivery methods continue receiving stable payloads; the refactor happens in core producers/projection code.
- [ ] Future mirror/search consumers have a shared projection contract to adopt instead of creating a new transcript classifier.
- [ ] The web bug bucket references this todo as the architectural owner of the visible symptom.

## Constraints

- Adapter-facing delivery methods and session metadata contracts must remain stable.
- This todo may refactor core projection code, core producers, and web API endpoints, but it must not require Telegram/Discord/TUI adapter rewrites.
- Existing working adapter paths are protected by non-regression tests during phased cutover.
- The shared conversation projector must operate on transcript chains, not a web-only copy of transcript logic.
- The shared terminal-live projector must sit beneath the existing poller-driven adapter push path, not inside adapter implementations.

## Current Visibility Divergence (Codebase Evidence)

The following table captures the confirmed divergence across the four output paths as of the current codebase. The canonical projector must collapse these into a single policy.

| Block type     | Web history (`extract_messages_from_chain`) | Web live SSE (`convert_entry`) | Threaded clean (`render_clean_agent_output`) | Threaded full (`render_agent_output`) |
|----------------|---------------------------------------------|-------------------------------|----------------------------------------------|---------------------------------------|
| text           | visible                                     | visible                       | visible                                      | visible                               |
| thinking       | hidden (default)                            | **visible**                   | visible (italicized)                         | visible (italicized)                  |
| tool_use       | hidden (default)                            | **visible**                   | hidden                                       | hidden (default)                      |
| tool_result    | hidden (default)                            | **visible**                   | **hidden (hardcoded)**                       | visible (default)                     |

The web SSE path (`convert_entry()` at `transcript_converter.py:159`) has **no visibility filtering** — it emits all assistant blocks unconditionally. This is the root cause of internal tool blocks leaking into web chat.

The web history path (`extract_messages_from_chain()` at `transcript.py:2224`) filters tools and thinking via boolean flags, defaulting to hidden.

The threaded clean path (`render_clean_agent_output()` at `transcript.py:491`) hardcodes tool result suppression with no configurability.

## Risks

- The existing threaded transcript renderers may embed assumptions that are not yet encoded in a reusable projector. Specifically, `render_clean_agent_output()` hardcodes tool result suppression while `render_agent_output()` makes it configurable — the projector must reconcile this. Mitigation: add parity fixtures before cutover.
- AI SDK SSE serialization may tempt reintroducing web-only rules. Mitigation: serializer must accept canonical projected blocks, not raw transcript entries.
- Tool/widget classification may drift if the allowlist is implicit. Mitigation: make user-visible tool allowance explicit and test it.
- The existing normalization entry point (`normalize_transcript_entry_message()` at `transcript.py:170`) handles Claude, Codex, and Gemini formats. The projector must reuse this rather than inventing new normalization.
