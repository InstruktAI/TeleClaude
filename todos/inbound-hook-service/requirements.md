# Requirements: inbound-hook-service

## Goal

Wire the existing inbound webhook infrastructure into the daemon so external platforms can POST webhooks into TeleClaude and have them routed through the contract-matching pipeline. Deliver at least one working normalizer (GitHub) as proof that the end-to-end path works.

## Problem Statement

The `InboundEndpointRegistry` and `NormalizerRegistry` exist as code but are never instantiated by the daemon. Zero normalizers exist. The subscription worker (`run_subscription_worker`) is never started. The result: the outbound path (internal events → contract match → external delivery) works, but the inbound path (external platform → TeleClaude) is dead code.

## In Scope

1. **Wire registries into daemon startup.** Create `NormalizerRegistry` and `InboundEndpointRegistry` in `_init_webhook_service()`, pass `inbound_registry` to `load_hooks_config()` so inbound endpoints from config are mounted. This requires loading `ProjectConfig` from `teleclaude.yml` in the daemon, since the daemon's `Config` dataclass does not include hooks config (use `load_project_config()` from `teleclaude/config/loader.py`).

2. **Update normalizer signature to include request headers.** The current `Normalizer = Callable[[dict], HookEvent]` cannot access HTTP headers. GitHub sends event type in `X-GitHub-Event`, WhatsApp sends signature in a header. Change to `Callable[[dict, dict], HookEvent]` where second arg is headers dict. Update `InboundEndpointRegistry.handle_post()` to pass headers to normalizer.

3. **GitHub normalizer.** A normalizer registered under key `"github"` that:
   - Reads `X-GitHub-Event` header to determine event type.
   - Produces `HookEvent(source="github", type="{github_event}", properties={repo, sender, action, ref}, payload=raw_body)`.
   - Handles `ping` event type (GitHub sends this on webhook creation) by returning a HookEvent with type `"ping"`.

4. **Deterministic path derivation.** Inbound endpoint paths are derived from source name, not hardcoded. Scheme: `/hooks/inbound/{source_name}`. The `InboundSourceConfig.path` field becomes optional — when omitted, the path is derived. When provided, it overrides.

5. **Wire channel subscription worker.** Start `run_subscription_worker()` in daemon startup when `project_cfg.channel_subscriptions` is non-empty (from `ProjectConfig` loaded via `load_project_config()`). Pass Redis client, subscriptions, and shutdown event.

6. **Config-driven inbound endpoints.** The existing `load_hooks_config()` already handles inbound registration when passed an `InboundEndpointRegistry`. This requirement is satisfied by wiring (item 1) plus ensuring the config schema supports the documented shape.

7. **Tests.** Unit tests for the GitHub normalizer. Integration test for the end-to-end flow: POST to inbound endpoint → normalize → dispatch through contract pipeline.

## Out of Scope

- **WhatsApp normalizer.** Depends on this todo but belongs in `help-desk-whatsapp`. The inbound infrastructure this todo delivers makes it possible.
- **Handler resolution (Python module import / subprocess command).** The input describes two handler modes (Python and executable). This is significant new functionality — user code invocation with import caching, subprocess management, timeouts, env vars. Separate todo.
- **`telec sync` webhook registration.** Calling platform APIs (GitHub, WhatsApp) to create/update/delete webhooks, plus webhook state tracking in DB. Separate todo.
- **Command dispatch in subscription worker.** Currently stubbed (logs only). Wiring actual command execution is separate scope.
- **Config layering (system defaults vs user config).** Built-in platform handlers as global subscriptions with system defaults in `config.py`. This requires design decisions about override policy. Separate todo.
- **Multiple repo / org-wide GitHub hooks.** One webhook config entry = one source. Multi-repo is future scope.

## Success Criteria

- [ ] Daemon starts with `InboundEndpointRegistry` and `NormalizerRegistry` wired.
- [ ] A POST to `/hooks/inbound/github` with valid HMAC signature and GitHub payload produces a `HookEvent` dispatched through the contract pipeline.
- [ ] A POST with invalid HMAC returns 401.
- [ ] A POST with valid HMAC but unparseable payload returns 400.
- [ ] GitHub `ping` event is normalized and dispatched (does not error).
- [ ] GitHub `push` event produces `HookEvent(source="github", type="push", properties={repo, sender, ...})`.
- [ ] `X-GitHub-Event` header is correctly read by the normalizer.
- [ ] Channel subscription worker starts when subscriptions are configured.
- [ ] Inbound path derivation produces `/hooks/inbound/{source_name}` when path is not explicitly set in config.
- [ ] Unit tests for GitHub normalizer cover: push, ping, pull_request, missing header.
- [ ] Integration test verifies end-to-end inbound flow.

## Constraints

- Must not break existing outbound webhook functionality.
- Must not change the `HookEvent` dataclass shape — it is a shared contract.
- Normalizer signature change must remain backward-compatible during transition (accept both 1-arg and 2-arg callables, or use a richer input object).
- Daemon startup must not fail if no inbound sources are configured (graceful degradation).

## Risks

- **Normalizer signature change ripple.** Changing from `Callable[[dict], HookEvent]` to `Callable[[dict, dict], HookEvent]` may break any code that currently references the `Normalizer` type alias. Mitigate: check all references (verified: only `inbound.py` references it).
- **FastAPI route mounting order.** Dynamic routes added after app startup may not be reachable if the app has already started. Verify that `_init_webhook_service()` runs before `uvicorn.run()`.
- **Config access bridge.** The daemon's `Config` dataclass does not include hooks. `_init_webhook_service()` must load `ProjectConfig` from `teleclaude.yml` to access `HooksConfig` and `channel_subscriptions`. The existing `getattr(config, "hooks", None)` at daemon.py:1554 is dead code that must be replaced.

## Open Design Questions (for gate phase)

1. **Normalizer signature approach.** Two options: (a) change type alias to 2-arg callable, or (b) introduce a `NormalizerInput` dataclass wrapping payload + headers. Option (b) is more extensible but heavier. Recommendation: start with (a), migrate to (b) if a third parameter is needed.
2. **Path derivation with project scope.** The input mentions `/hooks/inbound/{project}/{source}` for project-scoped hooks. This todo uses `/hooks/inbound/{source}` (no project dimension) since project scoping requires the config layering work (out of scope). The path scheme must be designed to allow adding the project dimension later without breaking URLs.
