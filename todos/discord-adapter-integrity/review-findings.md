# Review Findings: discord-adapter-integrity

**Review round:** 1
**Reviewer:** Claude (automated)
**Date:** 2026-02-23
**Branch:** `discord-adapter-integrity`

---

## Critical

### 1. Identity resolver "member" fallback is unreachable — unregistered Discord users get "customer" in project forums

**File:** `teleclaude/adapters/discord_adapter.py:1451`
**Traced to:** `teleclaude/core/identity.py:136-153`

The requirement states: _"resolve identity (role from people config, not hardcoded 'customer')"_. The implementation at line 1451:

```python
identity = get_identity_resolver().resolve("discord", {"user_id": user_id, "discord_user_id": user_id})
human_role = (identity.person_role if identity else None) or "member"
```

However, `IdentityResolver.resolve()` for `origin == "discord"` **never returns None**. For unregistered users, it returns `IdentityContext(person_role=CUSTOMER_ROLE, ...)` at `identity.py:149-153`. The guard `if identity else None` always evaluates to truthy, so `identity.person_role` is always `"customer"` for unknown users. The `"member"` default is dead code.

**Impact:** Unregistered users posting in project forums get `human_role="customer"` — exactly the bug the requirements say to fix.

**Fix:** Check `identity.person_name` (only populated for registered users):

```python
human_role = (identity.person_role if identity and identity.person_name else None) or "member"
```

### 2. Test `test_create_session_project_forum_defaults_member_when_unresolved` patches resolver incorrectly

**File:** `tests/unit/test_discord_adapter.py:1077-1108`

The test patches `get_identity_resolver` to return a resolver where `.resolve()` returns `None`. In production, `.resolve("discord", ...)` never returns `None` — it returns an `IdentityContext` with `person_role="customer"`. The test passes but does not reflect production behavior. It should use a resolver that returns `IdentityContext(person_role="customer", person_name=None, ...)` and verify the code correctly distinguishes registered from unregistered users.

### 3. Implementation plan checkboxes all unchecked

**File:** `todos/discord-adapter-integrity/implementation-plan.md`

All task checkboxes remain `[ ]` (unchecked). Per review procedure, this triggers REQUEST CHANGES: _"Ensure all implementation-plan tasks are checked; otherwise, add a finding and set verdict to REQUEST CHANGES."_

### 4. Build Gates section unchecked

**File:** `todos/discord-adapter-integrity/quality-checklist.md`

All Build Gates remain unchecked. Per review procedure: _"Validate Build section in quality-checklist.md is fully checked. If not, add a finding and set verdict to REQUEST CHANGES."_

---

## Important

### 5. `_ensure_project_forums` stale ID cleared in-memory but not persisted to disk

**File:** `teleclaude/adapters/discord_adapter.py:421-430`

When `_validate_channel_id` returns None, `td.discord_forum` is set to `None` in-memory. If `_find_or_create_forum` then also fails (returns None), the stale ID remains in `config.yml` (only successful new IDs are persisted via `project_changes`). This creates:

- Split-brain: in-memory `None`, on-disk stale ID
- Restart cycle: stale ID reloaded → validated → cleared → re-provision fails → repeat
- Project absent from `_project_forum_map` → messages misrouted to help_desk

**Fix:** Only clear `td.discord_forum` after successfully obtaining a replacement, or persist None explicitly.

### 6. `_resolve_forum_context` silent fallback to help_desk without logging

**File:** `teleclaude/adapters/discord_adapter.py:225`

When `parent_id` doesn't match any known forum, the function silently returns `("help_desk", help_desk_dir)`. No warning is logged. Combined with finding #1, this means a team member in an unrecognized project forum gets `human_role="customer"` with zero trace.

**Fix:** Add `logger.warning` when falling through with a non-None `parent_id` that matched nothing.

### 7. Missing test coverage for `_ensure_discord_infrastructure` stale channel clearing

**File:** `tests/unit/test_discord_adapter.py`

Tests cover `_validate_channel_id` in isolation and `_ensure_project_forums` stale clearing, but `_ensure_discord_infrastructure` itself (which validates 6 infrastructure channels) has no test for stale ID clearing + re-provisioning. A bug in any of the per-channel stanzas would go undetected.

---

## Suggestions

### 8. `_validate_channel_id` cannot distinguish transient failures from genuine staleness

**File:** `teleclaude/adapters/discord_adapter.py:267-275` → `_get_channel:1563-1566`

`_get_channel` catches all exceptions at DEBUG level. `_validate_channel_id` treats any failure as "stale". During a transient Discord API outage, all channel IDs are judged stale, triggering full re-provisioning. Consider differentiating `NotFound` from other failures.

### 9. Arbitrary first-trusted-dir for all_sessions forum

**File:** `teleclaude/adapters/discord_adapter.py:218`

`trusted[0].path` is used as project path for all_sessions messages. The order of `get_all_trusted_dirs()` is not defined as meaningful. Consider using `help_desk_dir` consistently or logging the selection.

### 10. Incomplete drop-path logging in `_handle_on_message`

**File:** `teleclaude/adapters/discord_adapter.py:1094, 1373`

The new entry-level DEBUG log at line 1045 is good. But messages dropped at line 1094 (no text/attachments) and line 1373 (no author ID) have no logging. These silent drops reduce debuggability.

---

## Paradigm-Fit Assessment

1. **Data flow:** The implementation correctly uses the existing data layer (`_get_channel`, `_find_or_create_forum`, `config.computer.get_all_trusted_dirs()`). No inline hacks or bypasses. The identity resolution follows the established pattern from the DM handler.

2. **Component reuse:** `_validate_channel_id` properly reuses `_get_channel`. The `_ensure_category` key parameter is a clean extension. `_resolve_forum_context` follows the adapter's `getattr` pattern for Discord objects.

3. **Pattern consistency:** The validation-before-trust pattern is applied consistently across all 6 infrastructure channels and project forums. The `_create_session_for_message` extension with keyword args preserves backward compatibility.

---

## Verdict: REQUEST CHANGES

**Blocking issues:**

- Finding #1 (identity resolution bug — the core requirement is not met)
- Finding #2 (test masks the bug by patching incorrectly)
- Finding #3 (implementation plan checkboxes unchecked)
- Finding #4 (build gates unchecked)
