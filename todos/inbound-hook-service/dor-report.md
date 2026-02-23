# DOR Report: inbound-hook-service

## Gate Assessment

**Date:** 2026-02-23
**Phase:** Gate (formal DOR validation)
**Verdict:** PASS (score 9/10)

## Summary

The input document is thorough (14KB brain dump with codebase inventory, design direction, research findings, and open questions). Requirements and implementation plan have been derived from it. The scope has been narrowed from the full vision (which spans handler resolution, config layering, telec sync registration, WhatsApp, and more) to the foundational wiring that unblocks everything else.

Gate validation identified one significant gap in the implementation plan (config access bridge between daemon Config and ProjectConfig) which has been resolved by tightening the plan and requirements with explicit instructions. All other gates pass cleanly.

## Gate Status by Criterion

### 1. Intent & Success -- PASS

Problem statement is explicit: inbound infrastructure exists but is dead code. Success criteria are concrete and testable (HMAC verification, normalizer output shape, daemon startup behavior). 11 testable success criteria defined.

### 2. Scope & Size -- PASS

The original input describes work that would exhaust multiple AI sessions. The requirements scope it to: wire registries, update normalizer signature, create one normalizer (GitHub), path derivation, wire subscription worker. This fits one session.

**Recommended follow-up todos (not in this scope):**

- `inbound-handler-resolution`: Python module import + executable subprocess handler modes
- `inbound-config-layering`: System defaults for built-in platforms, override policy
- `inbound-telec-sync-registration`: Platform API calls to create/update/delete webhooks + state tracking
- WhatsApp normalizer + bridge handler belongs in `help-desk-whatsapp`

### 3. Verification -- PASS

Unit tests for GitHub normalizer (5 test cases). Integration test for end-to-end flow (4 test cases). Demo artifacts with validation commands. Observable daemon logs for wiring confirmation.

### 4. Approach Known -- PASS

All code paths exist -- this is wiring, not invention. `InboundEndpointRegistry`, `NormalizerRegistry`, `load_hooks_config()`, and `run_subscription_worker()` are implemented. The normalizer signature change is straightforward (type alias + one call site). GitHub normalizer follows an obvious pattern.

### 5. Research Complete -- PASS

GitHub webhook format is well-understood (documented in input.md with `gh api` examples). No new third-party dependencies introduced. The existing `InboundEndpointRegistry` already handles HMAC verification.

### 6. Dependencies & Preconditions -- PASS

No prerequisite todos. Redis must be available for subscription worker (already a daemon requirement). No new config keys or environment variables beyond what's already in the schema.

### 7. Integration Safety -- PASS

All changes are additive. Existing outbound path is untouched. Daemon startup gracefully handles missing inbound config (the `if inbound_registry:` guard in `load_hooks_config()` already exists). The normalizer signature change is internal to `teleclaude/hooks/inbound.py`.

### 8. Tooling Impact -- N/A

No tooling or scaffolding changes.

## Gate Actions Taken

### Config access gap (resolved)

**Finding:** The implementation plan Task 2.1 assumed the daemon's `Config` dataclass has a `hooks` field. It does not. The existing code at `daemon.py:1554` (`getattr(config, "hooks", None)`) is dead -- it always returns `None`. The `HooksConfig` and `channel_subscriptions` live on `ProjectConfig` (in `teleclaude/config/schema.py`), which the daemon never loads.

**Resolution:** Tightened the implementation plan (Task 2.1 and Task 2.4) to explicitly require loading `ProjectConfig` from `teleclaude.yml` using `load_project_config()`. Updated requirements items 1 and 5 to reference the correct config access path. Added a risk entry for the config access bridge.

### Plan-to-requirement fidelity check

Every implementation plan task traces to a requirement:

- Task 1.1 (normalizer signature) -> Requirement 2
- Task 1.2 (GitHub normalizer) -> Requirement 3
- Task 1.3 (registration helper) -> Requirement 3 (supporting infrastructure)
- Task 2.1 (wire registries) -> Requirement 1
- Task 2.2 (path derivation) -> Requirement 4
- Task 2.3 (optional config fields) -> Requirement 4, 6
- Task 2.4 (subscription worker) -> Requirement 5
- Task 3.1 (unit tests) -> Requirement 7
- Task 3.2 (integration tests) -> Requirement 7
- Task 3.3 (quality checks) -> Requirement 7

No task contradicts a requirement. The plan prescribes reuse of existing infrastructure as required.

### Path derivation verified

`load_hooks_config()` at `config.py:97` defaults to `f"/hooks/{source_name}"` which differs from the requirement's `/hooks/inbound/{source_name}`. Task 2.2 explicitly addresses this update. Confirmed.

### Normalizer type alias scope verified

`Normalizer` type alias is only referenced in `teleclaude/hooks/inbound.py`. No external consumers. Signature change is safe.

## Open Design Questions (resolved)

1. **Normalizer signature approach.** Decision: 2-arg callable `(payload, headers)`. Simpler, sufficient for now. Migrate to `NormalizerInput` dataclass if a third parameter is ever needed.

2. **Path derivation with project dimension.** Decision: Use `/hooks/inbound/{source}` now (no project dimension). The project dimension is tied to config layering (out of scope). Path scheme allows adding project dimension later without breaking existing URLs.

## Assumptions (verified)

- The daemon's FastAPI app accepts dynamically added routes during `_init_webhook_service()` (before uvicorn starts serving). **Verified:** `_init_webhook_service()` is called during `start()` before the event loop serves requests.
- `InboundSourceConfig.path` can be made optional without breaking existing config files. **Verified:** No existing configs set inbound sources -- the feature is unused.
- The `Normalizer` type alias is only referenced in `teleclaude/hooks/inbound.py`. **Verified:** grep confirms no external consumers.
- `ProjectConfig` can be loaded in the daemon via `load_project_config()` from `teleclaude.yml`. **Verified:** `teleclaude/cron/runner.py` uses the same pattern.

## Blockers

None remaining. The config access gap was the only finding and has been resolved in the artifacts.
