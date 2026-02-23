# Review Findings: discord-adapter-integrity

**Review round:** 2
**Reviewer:** Claude (automated)
**Date:** 2026-02-24
**Branch:** `discord-adapter-integrity`

---

## Round 1 Resolution Status

All 7 actionable findings from round 1 have been addressed:

| #   | Finding                                         | Status                                                     | Commit     |
| --- | ----------------------------------------------- | ---------------------------------------------------------- | ---------- |
| 1   | Identity resolver "member" fallback unreachable | **Fixed** — `person_name` guard added                      | `ccd29fd8` |
| 2   | Test patches resolver to return None            | **Fixed** — uses `IdentityContext` with `person_name=None` | `ccd29fd8` |
| 3   | Implementation plan checkboxes unchecked        | **Fixed** — all 29/29 checked in committed state           | `ccd29fd8` |
| 4   | Build gates unchecked                           | **Fixed** — all 9/9 checked in committed state             | `ccd29fd8` |
| 5   | Stale forum ID not persisted to disk            | **Fixed** — `stale_cleared` flag + persist None            | `24b342b3` |
| 6   | Silent fallback to help_desk                    | **Fixed** — `logger.warning` on unrecognized `parent_id`   | `8f469635` |
| 7   | Missing infrastructure stale-clearing test      | **Fixed** — test added                                     | `c3fd2a38` |

Round 1 suggestions #8-#10 remain as pre-existing improvement opportunities (not blocking).

---

## Verification of Fixes

### Fix #1 — Identity resolution (traced with concrete values)

**File:** `discord_adapter.py:1474`, cross-ref `identity.py:136-153`

Production path for unregistered Discord user in project forum:

1. `IdentityResolver.resolve("discord", ...)` → `IdentityContext(person_role="customer", person_name=None)`
2. `identity and identity.person_name` → `True and None` → `None` (falsy)
3. `(None) or "member"` → `"member"` ✓

Production path for registered admin:

1. `IdentityResolver.resolve("discord", ...)` → `IdentityContext(person_role="admin", person_name="Alice")`
2. `identity and identity.person_name` → `True and "Alice"` → `"Alice"` (truthy)
3. `identity.person_role` → `"admin"` ✓

Help desk path: `forum_type == "help_desk"` → `human_role = "customer"` directly, no identity resolution ✓

### Fix #2 — Test fidelity

**File:** `test_discord_adapter.py:1113-1143`

Test uses `IdentityContext(person_role="customer", person_name=None, platform="discord", platform_user_id="999001")` — matches `identity.py:149-153` production output for unregistered users. Asserts `human_role == "member"`. ✓

### Fix #5 — Stale persistence chain

**File:** `discord_adapter.py:430-445` → `560-585`

When `stale_cleared=True` and `_find_or_create_forum` returns None → `project_changes.append((td.name, None))` → `_persist_project_forum_ids` calls `td.pop("discord_forum", None)` removing the stale key from config.yml. Restart cycle broken. ✓

---

## Critical

_None._

---

## Important

### 1. Missing test for stale-cleared + failed re-provisioning → persists None

**File:** `tests/unit/test_discord_adapter.py`

The critical path from commit `24b342b3` — when a stale forum ID is detected, cleared, and re-provisioning fails (returns None) — persists None to break the restart cycle. This specific code path (`elif stale_cleared:` at line 442) has no dedicated test. A regression removing this branch would silently reintroduce the restart cycle bug.

### 2. `_ensure_project_forums` test doesn't assert persistence was called

**File:** `tests/unit/test_discord_adapter.py:830`

`test_ensure_project_forums_clears_stale_id_and_reprovisions` verifies in-memory state (`td.discord_forum == 777`) and that `_find_or_create_forum` was called, but does not assert `_persist_project_forum_ids` was invoked. Since the stated purpose of this code path is to persist changes to config.yml, the persistence call should be verified.

---

## Suggestions

### 3. `_resolve_forum_context` — no warning when all parent_id lookups return None

**File:** `discord_adapter.py:225-234`

The warning log fires only when `parent_id is not None`. When all three attribute lookups fail (`parent_id`, `parent.id`, `channel.id` all None), the message routes to help_desk with zero logging. Consider logging a warning for this edge case to catch structurally unexpected message objects.

### 4. Transient Discord API failures vs genuine staleness (reiteration of round 1 S#8)

**File:** `discord_adapter.py:1574-1590` → `276-284`

`_get_channel` catches all exceptions at DEBUG level. `_validate_channel_id` treats any failure as "stale." During a transient Discord outage, this could trigger unnecessary re-provisioning and — combined with the persist-None path — permanently remove valid forum IDs from config. Consider differentiating `discord.NotFound` from transient errors in a future hardening pass.

### 5. Test `_resolve_forum_context` via direct `parent_id` attribute (path 1)

**File:** `tests/unit/test_discord_adapter.py`

`FakeThread` sets `self.parent = SimpleNamespace(id=parent_id)` but has no `parent_id` attribute. All forum routing tests exercise path 2 (`parent.id`) but not path 1 (`channel.parent_id`), which is the primary path for real discord.py Thread objects. Consider adding a test with a channel object that has a direct `parent_id` attribute.

---

## Paradigm-Fit Assessment

1. **Data flow:** Uses the existing data layer (`_get_channel`, `_find_or_create_forum`, `config.computer.get_all_trusted_dirs()`). Identity resolution follows the established DM handler pattern. No inline hacks or bypasses.

2. **Component reuse:** `_validate_channel_id` properly reuses `_get_channel`. The `_ensure_category` `key` parameter is a clean extension. `_resolve_forum_context` follows the adapter's `getattr` pattern for Discord objects. No copy-paste duplication.

3. **Pattern consistency:** Validation-before-trust applied consistently across all 6 infrastructure channels and project forums. `_create_session_for_message` extended with keyword args preserving backward compatibility. Per-computer category slug generation is clean (`projects_{computer_name_slug}`).

---

## Requirements Traceability

| Requirement                                           | Implementation                                                                                           | Verified |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | -------- |
| Stale IDs cleared and re-provisioned                  | `_validate_channel_id` + validation calls in `_ensure_discord_infrastructure` + `_ensure_project_forums` | ✓        |
| Per-computer project categories                       | `f"Projects - {config.computer.name}"` with clean slug `key` param                                       | ✓        |
| Identity from people config, not hardcoded "customer" | `person_name` guard in `_create_session_for_message`                                                     | ✓        |
| Project path from forum mapping                       | `_resolve_forum_context` reverse lookup in `_project_forum_map`                                          | ✓        |
| Help desk retains customer role                       | `forum_type == "help_desk"` branch → `human_role = "customer"`                                           | ✓        |
| Entry-level DEBUG logging                             | `[DISCORD MSG]` log at top of `_handle_on_message`                                                       | ✓        |

---

## Verdict: APPROVE

All round 1 critical and important findings are resolved. The implementation meets all stated requirements. The two Important findings are test coverage improvements — real gaps worth addressing, but not blocking for the behavioral correctness of the delivered code. The code is well-structured, follows existing patterns, and introduces no regressions.
