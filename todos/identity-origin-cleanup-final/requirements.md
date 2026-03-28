# Requirements: identity-origin-cleanup-final

## Goal

Eliminate the untyped `channel_metadata: dict[str, object]` bag from the per-message data path, replace it with typed actor fields, route headless session creation through the command pipeline, and remove the legacy `resolve_from_terminal()` identity path. This is the final pass that completes the identity-origin-cleanup effort — no backward compatibility is required.

## Scope

### In scope

- **R1 — Typed actor fields on message model**: Replace the untyped `channel_metadata` dict on `MessageMetadata` with typed fields: `actor_id`, `actor_name`, `actor_avatar_url`, `platform_message_id`. Remove the `channel_metadata` field and its associated type definitions.
- **R2 — Adapter-edge normalization**: Each adapter (Telegram, Discord, WhatsApp, fanout) must set typed actor fields directly on `MessageMetadata` instead of populating a dict. Platform-specific ID prefixing (e.g., `telegram:{id}`, `discord:{id}`) must happen at the adapter edge. [inferred: prefix convention derived from existing `_extract_actor()` behavior in `CommandMapper`]
- **R3 — Eliminate centralized actor extraction**: The centralized normalization that reads untyped dict keys and produces actor fields must be removed. After R2, it has no callers. All command-mapping methods must read typed fields from `MessageMetadata` directly.
- **R4 — Redis wire format migration**: The Redis transport must serialize and deserialize typed actor fields individually instead of JSON-encoding a `channel_metadata` blob. The `RedisInboundMessage` model must carry typed fields instead of the dict. The `RedisTransportMetadata` adapter model must drop its `channel_metadata` field.
- **R5 — Dead code removal in Redis transport**: The `target_computer` injection that mutates `channel_metadata` after message parsing is dead code — the value already flows through `RedisTransportMetadata` via a separate path. It must be removed. [inferred: verified by tracing `target_computer` flow from `RedisInboundMessage.initiator` through `RedisTransportMetadata.target_computer` to `_forward_stop_to_initiator`]
- **R6 — Headless session creation via command pipeline**: Daemon and API callers that create headless sessions by calling the database directly must route through `CreateSessionCommand` and the command service instead. Identity must propagate via `origin_metadata` using the established `TerminalOriginMetadata` pattern (read terminal auth email, pass via `origin_metadata`), not via `resolve_from_terminal()`. After migration, the direct database method for headless session creation has no production callers and must be removed. Tests that directly called `create_headless_session()` must be migrated to test session creation through the command pipeline instead. [inferred: input explicitly called out test__sessions.py tests as requiring migration]
- **R7 — Remove `resolve_from_terminal()`**: The legacy terminal identity resolution method must be removed from the identity resolver. CLI callers that depend on it must use the standard identity resolution path (the same `resolve()` method used by all other origins). [inferred: CLI callers need the terminal auth email from `TELEC_AUTH_EMAIL` / `TELEC_SESSION_TOKEN` / `telec auth whoami` to feed the standard resolver]
- **R8 — Documentation updates**: All documentation referencing `channel_metadata`, `resolve_from_terminal()`, or direct headless session creation must be updated to reflect the new patterns.
- **R9 — Dead data removal in fanout**: The fanout path populates `actor_role`, `actor_agent`, and `actor_computer` keys in `channel_metadata` that are never consumed by the actor extraction path. These must not be carried forward to the typed fields — they are dead data. [inferred: verified by tracing consumers of `_extract_actor()` output; none read these keys]

### Out of scope

- Backward compatibility shims for `channel_metadata` — the input explicitly states greenfield.
- Changes to session origin metadata (`OriginMetadata`, `TransportMetadata`) — those were already migrated in the prior identity-origin-cleanup delivery.
- New adapter implementations or new transport backends.
- Changes to the `resolve()` method or identity resolution logic beyond removing `resolve_from_terminal()`.

## Success Criteria

- [ ] `grep -r "channel_metadata" teleclaude/ tests/ docs/ demos/` returns zero hits.
- [ ] `grep -r "resolve_from_terminal" teleclaude/ tests/` returns zero hits.
- [ ] `grep -r "create_headless_session" teleclaude/ tests/` returns zero hits (excluding migration/schema artifacts if any).
- [ ] All adapters set typed actor fields (`actor_id`, `actor_name`, `actor_avatar_url`, `platform_message_id`) directly on `MessageMetadata`.
- [ ] Redis wire format serializes/deserializes typed fields individually (no JSON blob for actor data).
- [ ] Existing xfail test specs in `test_daemon_headless_pipeline.py` pass with markers removed.
- [ ] All pre-commit hooks pass (`make lint`, `make test`).
- [ ] Actor identity resolves correctly end-to-end: adapter → command mapper → session (verifiable via existing test infrastructure).
- [ ] CLI identity resolution works without `resolve_from_terminal()` (verifiable via updated CLI tests).

## Constraints

- No backward compatibility — this is greenfield per the input.
- The `_extract_actor()` normalization logic (platform prefix conventions) must be preserved in behavior when moved to adapter edges. The prefixing is the contract, not the location.
- `CreateSessionCommand` and the command service already exist and are the established pattern for session creation. The headless path must conform to this pattern.
- The existing xfail test spec (`test_daemon_headless_pipeline.py`) defines the behavioral contract for R6-R7 and must not be weakened — only the xfail markers may be removed.

## Risks

- **Wire format compatibility**: Redis messages in flight during deployment will use the old format. [inferred: this is a rolling-restart concern, not a code concern — the system does not support mixed-version wire formats today, so this is accepted as a deployment constraint, not a code requirement]
- **CLI callers of `resolve_from_terminal()`**: Three CLI handlers depend on this. The alternative path must be verified to produce equivalent identity resolution results for terminal callers. Failure would break CLI admin guards.

## Splitting Assessment

**No split recommended.** The input provides exact before/after code for every change site. Per the DOR splitting heuristics:

- **Ground first**: Changes are 1-5 lines per site across ~25 production files. Total lines of change is modest despite file count.
- **Coherence test**: Eliminating `channel_metadata` is one behavior flowing through adapters → mapper → transport → model. Parts 5-7 (headless pipeline, resolve_from_terminal) are from the same original scope and share the identity cleanup theme. Not independently shippable — removing `channel_metadata` without updating all consumers would break the system.
- **Detail inverts complexity**: The input has exact file paths, line numbers, and before/after code. Discovery is fully done. What remains is mechanical execution.
- **Coordination cost**: Splitting into sequential parts (model → adapters → mapper → transport) creates inter-todo dependencies with no independent value. The coordination overhead exceeds any session-size benefit.
