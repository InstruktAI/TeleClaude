# Review Findings: unified-identity-resolution

**Round 2 review** — verifying all prior findings were resolved and checking for new issues.

---

## Lane: Scope

Requirements and implementation plan are stubs (from-main inline work). Scope lane verifies delivery against the stated intent: "Unified identity resolution: single resolver path for all origins."

The diff achieves this:

- Removes the duplicate `_EmailRoleCacheState` / `_load_email_role_map()` in `auth.py`.
- Routes all email-based identity resolution through the shared `IdentityResolver` singleton.
- Adds `origin="terminal"` handler to `IdentityResolver.resolve()` and `resolve_by_email()` public method.
- Injects `identity.email` into `channel_metadata` at the API boundary so session creation passes email to the resolver.
- Adds `InputOrigin.WEB` enum value and routes web origin sessions correctly.

No gold-plating. No gaps relative to stated goal. **PASS**.

---

## Lane: Code

No bugs or pattern violations found.

- `resolve_by_email()` correctly delegates to `_by_email.get(email.lower())` — consistent with `_load_config()` which stores lowercased keys.
- `registered_people_count` property correctly calls `_reload_if_stale()` before returning the count — no stale reads.
- `_build_terminal_identity` correctly computes `normalized_email` before calling `_resolve_terminal_role` — both operate on the same input, minor double-normalization (two `strip().lower()` calls) is harmless.
- `CallerIdentity.email: str | None = None` is placed after all required fields — valid dataclass ordering confirmed.
- `session_auth.py` now uses the public `resolve_by_email()` API instead of accessing `._by_email` and `._normalize_role()` directly — correct encapsulation.
- All instantiation sites for `CallerIdentity` use keyword arguments — safe against field ordering changes.

**PASS**.

---

## Lane: Paradigm

Follows the existing centralization pattern. The `IdentityResolver` was already the single source of truth for platform adapters (Telegram, Discord, WhatsApp). This change extends that pattern to terminal and web origins, completing the unified resolver path.

The `conftest.py` approach changes from patching `_GLOBAL_CONFIG_PATH` (an internal detail) to replacing `_resolver_instance` (the singleton) — this is architecturally correct, trading one form of internal coupling for another (see Suggestion S1).

No data-layer bypasses or copy-paste patterns. **PASS**.

---

## Lane: Principles

### Backward Compatibility (origin="api") — **RESOLVED**

Prior finding: removing the explicit `origin="api"` handler would cause `api`-origin sessions without `system_role` to receive `person_role=HUMAN_ROLE_CUSTOMER` instead of `None`, potentially jailing them to help-desk.

Fix applied (commit `d774fcb5d`): `origin="api"` passthrough is restored in `resolve()`, returning `IdentityContext()` with no role. Confirmed present in the delivered code (identity.py lines 167–170).

Callers verified:

- `command_service.run_session_for_command()` (line 379): always has `system_role` set from `COMMAND_ROLE_MAP`, so the jailing condition at `_session.py:163` is never triggered regardless.
- `api_server.py._metadata()` (line 206): used for internal metadata, no session creation path affected.
- `integration_bridge.py` (line 298), `command_mapper.py` (lines 328/333/357/365): all produce metadata consumed by `create_session()` which goes through the identity resolver; `origin="api"` returns `IdentityContext()` — correct pre-existing behavior preserved.

**RESOLVED**.

### Registered People Count Semantics — No Issue

Old code counted people with a valid email AND a role in `HUMAN_ROLES`. New code uses `len(global_config.people)`.

`PersonEntry.email` is a required `str` field (not `Optional`). `PersonEntry.role` is `Literal["admin", "member", "contributor", "newcomer"]` — all values are in `HUMAN_ROLES`. The semantic difference is zero for valid configs. **No issue**.

### SRP / DIP — PASS

`auth.py` imports from `teleclaude.core.identity` (adapter → core direction). No violations.

---

## Lane: Security

- No hardcoded credentials.
- No PII in logs (email not logged in any new code path).
- Email injection into `channel_metadata` comes from `CallerIdentity.email` (already authenticated and normalized via `_normalize_email()`) or `request.human_email` (from authenticated request body).
- `request.human_email` is stored without normalization into `channel_metadata["email"]`. The IdentityResolver normalizes to lowercase at lookup time (`.lower()`), so casing inconsistency in stored metadata is cosmetic — no functional issue.
- The ability for a web caller to supply an arbitrary `human_email` in `CreateSessionRequest` is pre-existing design behavior, not introduced by this diff. Role enforcement at the API boundary still applies.
- No auth bypass introduced.

**PASS**.

---

## Lane: Tests

### Prior findings resolved (commit `d774fcb5d`)

| Finding                           | Resolution                                                                                                                                                                                                            |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `resolve_by_email()` untested     | `TestResolveByEmail` class: known, unknown, case-insensitive                                                                                                                                                          |
| `origin="terminal"` untested      | `TestResolveTerminalOrigin`: match, unrecognized, no email                                                                                                                                                            |
| `origin="api"` behavior           | `TestResolveApiOrigin`: asserts `person_role is None`                                                                                                                                                                 |
| Email injection branches untested | `test_run_session_injects_caller_email_into_channel_metadata`, `test_prepare_create_session_selects_web_origin_when_human_email_provided`, `test_prepare_create_session_injects_identity_email_into_channel_metadata` |

All four prior Important findings confirmed resolved. Tests are properly structured with `@pytest.mark.unit` markers.

**PASS**.

---

## Lane: Silent Failures

- `_load_config()` broad `except Exception` catch (lines 96–98, 119–120): pre-existing, logs at error/warning level. Not silently swallowed.
- `_reload_if_stale()` catches `OSError` (lines 72–77): returns 0 (no config) — sensible fallback. Pre-existing.
- No new silent failure patterns introduced.

**PASS**.

---

## Lane: Types

- `CallerIdentity.email: str | None = None` — valid dataclass field with default after required fields. Confirmed via Python validation.
- `resolve_by_email(self, email: str) -> IdentityContext` — correctly typed.
- `registered_people_count` property returns `int` — correctly typed.
- `IdentityResolver.resolve()` docstring updated to reflect `'terminal'` instead of `'api'` as example.
- All construction sites use keyword arguments — type-safe.

**PASS**.

---

## Lane: Comments

- Updated docstring in `resolve()` correctly replaces `'api'` with `'terminal'` in the origin example.
- `# API-origin sessions are already authenticated...` comment (identity.py:168–170) accurately describes the `origin="api"` passthrough behavior — preserved from original.
- `# Inject identity into channel_metadata for IdentityResolver` (sessions_actions_routes.py:261, sessions_routes.py:393–394) — accurate.
- `# Retained for API compatibility — no longer TTY-scoped.` on `TerminalSessionContext` in session_auth.py — pre-existing, still accurate.

**PASS**.

---

## Lane: Logging

All logging on changed paths uses `%s` lazy format strings. No f-string logging. No debug probes. No PII logged. New code paths (`resolve_by_email()`, `registered_people_count`, terminal origin handler) appropriately add no logging — these are hot-path identity lookups.

**PASS**.

---

## Lane: Demo

`demo.md` carries the `<!-- no-demo: from-main inline work -->` marker. Demo lane skipped per procedure.

**SKIP (no-demo marker present)**.

---

## Lane: Simplify

Implementation is minimal for its purpose. No redundant branches, no over-engineering. The double normalization in `_build_terminal_identity` (`_normalize_email(email_header)` called once directly and once inside `_resolve_terminal_role`) is an O(1) string operation — not worth refactoring for readability cost.

The `conftest.py` mock still uses `IdentityResolver.__new__` + direct attribute injection (Suggestion S1 from round 1, still present). This is a maintainability concern but not a simplification opportunity for the reviewer to mandate.

**PASS**.

---

## Suggestions (non-blocking)

**S1 — conftest mock couples to private internals**
`tests/functional/conftest.py` constructs a mock `IdentityResolver` via `__new__` and directly sets `_by_email`, `_by_username`, `_registered_people_count`, `_config_mtime_ns`, `_people_mtime_ns`. This is fragile: if `_reload_if_stale()` triggers (because `~/.teleclaude/teleclaude.yml` exists with a nonzero mtime on developer machines), it will overwrite the mock's `_by_email` with real config data, causing test flakiness. Better: patch `_GLOBAL_CONFIG_PATH` and `_PEOPLE_DIR` to point at `tmp_path` stubs, or set `_config_mtime_ns` to the actual current mtime of the real config file.

**S2 — tautological enum test in test_origins.py**
`test_web_value` asserts `InputOrigin.WEB.value == "web"` — a string literal asserted against itself. `test_all_origins_have_string_values` already covers all values. Not harmful, consistent with file pattern.

---

## Summary

| Severity   | Count | Issues                                                    |
| ---------- | ----- | --------------------------------------------------------- |
| Critical   | 0     | —                                                         |
| Important  | 0     | All 4 from round 1 resolved (commit d774fcb5d)            |
| Suggestion | 2     | conftest mock fragility; tautological test (not blocking) |

**Verdict: APPROVE**
