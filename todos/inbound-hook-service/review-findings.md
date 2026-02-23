# Review Findings: inbound-hook-service

## Review Scope

Files changed: 13 (6 source, 2 new test files, 1 conftest fix, 4 todo artifacts)
Diff: +470 / -74 lines
Review baseline: `4c73236c`

---

## Critical

(none)

## Important

### 1. Config-driven contracts skipped when API server app is unavailable

**File:** `teleclaude/daemon.py:1575-1584`

When `app is None`, `load_hooks_config` is never called. This means config-driven subscription contracts are silently dropped — not just inbound endpoints. The `load_hooks_config` function accepts `inbound_registry=None` and would correctly load contracts without registering inbound routes.

**Current:**

```python
if app is None:
    logger.warning("API server app unavailable; inbound webhooks will not be registered")
    app = None
else:
    inbound_registry = InboundEndpointRegistry(app, normalizer_registry, dispatcher.dispatch)
    await load_hooks_config(
        project_config.hooks.model_dump(),
        contract_registry,
        inbound_registry=inbound_registry,
    )
```

**Expected:** Always call `load_hooks_config` for contracts; only skip inbound registration:

```python
inbound_registry = None
if app is not None:
    inbound_registry = InboundEndpointRegistry(app, normalizer_registry, dispatcher.dispatch)
else:
    logger.warning("API server app unavailable; inbound webhooks will not be registered")

await load_hooks_config(
    project_config.hooks.model_dump(),
    contract_registry,
    inbound_registry=inbound_registry,
)
```

**Why it matters:** Contracts and inbound endpoints are separate concerns. The contract-matching pipeline should work independently of the API server. If startup order ever changes or the API server fails to initialize, all config-driven subscriptions would silently vanish.

## Suggestions

### 2. Redundant `app = None` assignment

**File:** `teleclaude/daemon.py:1577`

Inside the `if app is None:` branch, `app = None` is assigned again — dead code.

### 3. Scattered mid-function imports

**File:** `teleclaude/daemon.py:1559-1563`

`load_project_config` and `RedisTransport` are imported between executable statements, while all other deferred imports are grouped at the function entry (lines 1543-1552). Moving these into the import block improves readability.

### 4. Missing integration test: missing HMAC signature header

The test suite covers invalid signatures (`test_inbound_webhook_invalid_signature_rejected` sends `sha256=bad`), but doesn't exercise the distinct code path where a secret is configured but no signature header is present at all (`inbound.py:95-96`). Adding a test with no `X-Hub-Signature-256` header would cover this branch.

---

## Paradigm-Fit Assessment

1. **Data flow**: Correct. Uses `load_project_config` for config, `ContractRegistry` for contracts, `HookDispatcher` for dispatch, `db.enqueue_webhook` for persistence. No inline hacks or bypasses.
2. **Component reuse**: Correct. Reuses existing `InboundEndpointRegistry`, `NormalizerRegistry`, `load_hooks_config`, background task lifecycle patterns, and done callbacks. No copy-paste duplication found.
3. **Pattern consistency**: Correct. Follows established codebase patterns — deferred imports, background task cancel/await lifecycle, structured logging, registry pattern, `_get_redis()` access pattern (consistent with `channels/api_routes.py`, `deploy_service.py`, `mcp/handlers.py`).

---

## Requirements Traceability

| Requirement                                             | Status | Evidence                                          |
| ------------------------------------------------------- | ------ | ------------------------------------------------- |
| Registries wired into daemon startup                    | Met    | `daemon.py:1569-1583`                             |
| POST `/hooks/inbound/github` with valid HMAC dispatches | Met    | `test_inbound_webhook_dispatches_to_contract`     |
| Invalid HMAC returns 401                                | Met    | `test_inbound_webhook_invalid_signature_rejected` |
| Unparseable payload returns 400                         | Met    | `test_inbound_webhook_invalid_json_rejected`      |
| Ping event normalized                                   | Met    | `test_normalize_github_ping_event`                |
| Push event produces correct HookEvent                   | Met    | `test_normalize_github_push_event`                |
| X-GitHub-Event header read correctly                    | Met    | Lowercased header dict + normalizer lookup        |
| Channel subscription worker starts                      | Met    | `daemon.py:1586-1609`                             |
| Path derivation `/hooks/inbound/{source_name}`          | Met    | `config.py:98-100`                                |
| Unit tests for normalizer                               | Met    | 5 unit tests                                      |
| Integration test E2E                                    | Met    | 5 integration tests                               |
| HookEvent dataclass unchanged                           | Met    | No changes to `webhook_models.py`                 |
| Backward-compatible normalizer signature                | Met    | `_invoke_normalizer` with `inspect.signature`     |
| Graceful degradation (no inbound config)                | Met    | Defensive guards throughout                       |

---

## Test Coverage Assessment

- **Unit tests (5):** push, ping, pull_request, missing header fallback, minimal payload safety. Good coverage of normalizer logic.
- **Integration tests (5):** E2E dispatch, invalid signature, invalid JSON, normalizer exception, dispatch failure. Good coverage of the HTTP layer.
- **Gap:** Missing signature header path (distinct from invalid signature). Minor.

---

## Verdict: REQUEST CHANGES

Finding #1 is an architectural correctness issue — contracts should load independently of API server availability. The fix is a small restructure of the conditional (see suggested code above). Suggestions #2-4 are non-blocking but recommended.

---

## Fixes Applied

### Finding #1 — Config-driven contracts skipped when API server unavailable

**Fix:** Restructured `_init_webhook_service` so `load_hooks_config` is always called. `InboundEndpointRegistry` is only instantiated when `app is not None`. Removed the redundant `app = None` assignment.
**Commit:** `ea75bb55`

### Suggestion #3 — Scattered mid-function imports

**Fix:** Moved `load_project_config` and `RedisTransport` imports into the grouped import block at function entry.
**Commit:** `ea75bb55`

### Suggestion #4 — Missing test: absent HMAC signature header

**Fix:** Added `test_inbound_webhook_missing_signature_rejected` covering the code path at `inbound.py:95-96` where no signature header is present.
**Commit:** `ea75bb55`

All 11 tests pass. Lint passes. Ready for re-review.
