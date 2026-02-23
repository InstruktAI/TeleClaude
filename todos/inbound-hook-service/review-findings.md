# Review Findings: inbound-hook-service

## Review Scope

Files changed: 13 (6 source, 2 new test files, 1 conftest fix, 4 todo artifacts)
Diff: +470 / -74 lines
Review baseline: `4c73236c`

---

## Round 1

### Important

#### 1. Config-driven contracts skipped when API server app is unavailable

**File:** `teleclaude/daemon.py:1575-1584`

When `app is None`, `load_hooks_config` was never called, silently dropping config-driven subscription contracts. The function accepts `inbound_registry=None` and would correctly load contracts without registering inbound routes.

**Resolution:** Fixed in `ea75bb55`. `load_hooks_config` is now called unconditionally. `InboundEndpointRegistry` is only created when `app is not None`. Redundant `app = None` assignment removed. Scattered mid-function imports grouped at function entry.

### Suggestions (addressed)

- **Redundant `app = None` assignment** — Removed in fix.
- **Scattered mid-function imports** — Moved to grouped import block.
- **Missing integration test: absent HMAC signature header** — Added `test_inbound_webhook_missing_signature_rejected`.

---

## Round 2 (Re-review)

All Round 1 findings verified as resolved. 11 tests pass. Import grouping correct. `load_hooks_config` called unconditionally.

### Critical

(none)

### Important

(none)

### Suggestions

#### 2. `_invoke_normalizer` per-request `inspect.signature()` overhead

**File:** `teleclaude/hooks/inbound.py:136-164`

The backward-compatibility shim calls `inspect.signature(normalizer)` on every webhook request. A normalizer's arity is fixed at registration time. Moving the introspection to `NormalizerRegistry.register()` and storing a pre-wrapped callable would eliminate per-request overhead. Not a correctness issue — the requirement explicitly mandates backward compatibility.

#### 3. Dead code in GitHub normalizer header lookup

**File:** `teleclaude/hooks/normalizers/github.py:39`

```python
event_type = (headers.get("x-github-event") or headers.get("X-GitHub-Event") or "").lower() or "unknown"
```

The `headers` dict is always lowercased (`inbound.py:89`), so `headers.get("X-GitHub-Event")` can never match. The mixed-case fallback is dead code.

#### 4. Dispatch test enqueue arguments not verified

**File:** `tests/integration/test_inbound_webhook.py:83`

`enqueue_webhook.assert_awaited_once()` confirms the mock was called but does not verify the arguments. Asserting at least `source == "github"` and `type == "push"` in the enqueued event would strengthen the end-to-end assertion.

---

## Paradigm-Fit Assessment

1. **Data flow:** Correct. Uses `load_project_config` for config, `ContractRegistry` for contracts, `HookDispatcher` for dispatch, `db.enqueue_webhook` for persistence. No inline hacks or bypasses.
2. **Component reuse:** Correct. Reuses existing `InboundEndpointRegistry`, `NormalizerRegistry`, `load_hooks_config`, background task lifecycle patterns, and done callbacks. No copy-paste duplication.
3. **Pattern consistency:** Correct. Follows established codebase patterns — deferred imports, background task cancel/await lifecycle, structured logging, registry pattern, `_get_redis()` access pattern (consistent with `channels/api_routes.py`, `deploy_service.py`, `mcp/handlers.py`).

No paradigm violations detected.

---

## Requirements Traceability

| Requirement                                             | Status | Evidence                                          |
| ------------------------------------------------------- | ------ | ------------------------------------------------- |
| Registries wired into daemon startup                    | Met    | `daemon.py:1568-1584`                             |
| POST `/hooks/inbound/github` with valid HMAC dispatches | Met    | `test_inbound_webhook_dispatches_to_contract`     |
| Invalid HMAC returns 401                                | Met    | `test_inbound_webhook_invalid_signature_rejected` |
| Missing signature returns 401                           | Met    | `test_inbound_webhook_missing_signature_rejected` |
| Unparseable payload returns 400                         | Met    | `test_inbound_webhook_invalid_json_rejected`      |
| Ping event normalized                                   | Met    | `test_normalize_github_ping_event`                |
| Push event produces correct HookEvent                   | Met    | `test_normalize_github_push_event`                |
| X-GitHub-Event header read correctly                    | Met    | Lowercased header dict + normalizer lookup        |
| Channel subscription worker starts                      | Met    | `daemon.py:1586-1609`                             |
| Path derivation `/hooks/inbound/{source_name}`          | Met    | `config.py:98-100`                                |
| Unit tests for normalizer                               | Met    | 5 unit tests                                      |
| Integration test E2E                                    | Met    | 6 integration tests                               |
| HookEvent dataclass unchanged                           | Met    | No changes to `webhook_models.py`                 |
| Backward-compatible normalizer signature                | Met    | `_invoke_normalizer` with `inspect.signature`     |
| Graceful degradation (no inbound config)                | Met    | Defensive guards throughout                       |

---

## Test Coverage Assessment

- **Unit tests (5):** push, ping, pull_request, missing header fallback, minimal payload safety. Good coverage of normalizer logic.
- **Integration tests (6):** E2E dispatch, missing signature, invalid signature, invalid JSON, normalizer exception, dispatch failure. Good coverage of the HTTP layer including both 401 branches.

---

## Verdict: APPROVE

All Round 1 findings resolved. No Critical or Important issues remain. 11 tests pass. The implementation is solid, well-structured, and follows established codebase patterns. Remaining suggestions are non-blocking optimization and hygiene items.
