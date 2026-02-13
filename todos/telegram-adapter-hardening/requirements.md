# Requirements: telegram-adapter-hardening

## Goal

Enforce Law of Demeter boundaries across session metadata and hook/session identity flow, while replacing implicit fallbacks with explicit fail-fast behavior.

## In Scope

1. **Metadata access encapsulation** - remove broad direct access (`session.adapter_metadata.telegram` / `.redis`) from runtime codepaths and route through typed accessors.
2. **Adapter metadata layering** - represent metadata as UI/transport containers and keep serialized storage backward-compatible (`telegram` and `redis` keys unchanged on disk).
3. **Fail-fast Telegram send contracts** - when `topic_id` is missing, raise explicit errors for send/edit paths instead of silently returning sentinel values.
4. **Hook routing contract hardening** - enforce strict TMUX marker contract for non-headless hooks; keep headless resolution map/DB-driven and explicit.
5. **Orphan ownership heuristic removal** - remove brittle title-based topic ownership inference and related opportunistic delete path.
6. **Routing consistency** - route UI send paths through the same lane-recovery flow so channel recreation behavior is consistent.

## Out of Scope

1. Full auth/identity redesign beyond hook route contract validation.
2. New adapter types or non-Telegram transport redesign.
3. TUI visual redesign.
4. Broad functional feature additions outside hardening/refactor scope.

## Success Criteria

- [x] Runtime codepaths use accessor chains (`get_metadata().get_ui().get_telegram()` / `get_transport().get_redis()`) instead of direct adapter metadata attribute access.
- [x] Session metadata JSON format remains backward-compatible for existing rows.
- [x] Telegram send/file behavior fails explicitly when no topic is available.
- [x] Hook receiver exits non-zero on contract violations instead of silently dropping handled events.
- [x] Title-based ownership heuristic helpers are removed from Telegram adapter.
- [x] Targeted tests covering adapter client, hooks, metadata model, Telegram adapter, UI adapter, and multi-adapter broadcast pass.
- [x] `make lint` passes for the worktree.

## Constraints

1. Preserve existing persisted metadata shape for `telegram`/`redis`.
2. Keep refactor incremental with test coverage for behavior changes.
3. Prefer explicit contract failures over implicit fallbacks in critical routing paths.

## Risks

1. Stricter hook contract validation can surface latent environment misconfiguration.
2. Fail-fast topic contracts may reveal previously masked ordering/race issues in callers.
3. Removing heuristic ownership cleanup can leave orphan threads that previously relied on best-effort deletion.
