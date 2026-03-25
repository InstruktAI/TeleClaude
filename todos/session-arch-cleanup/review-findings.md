# Review Findings: session-arch-cleanup

**Review type:** Ad-hoc review (via from-main)
**Branch:** session-arch-cleanup
**Commit range:** deb9bfb8e..752dacb83 (7 commits)
**Files changed:** 138
**Review round:** 2 (re-review after fix commits)

---

## Round 1 Findings — Resolution Status

All 6 findings from round 1 have been resolved by fix commits:

| Finding | Severity  | Resolution                                                                                                   | Commit      | Verified |
| ------- | --------- | ------------------------------------------------------------------------------------------------------------ | ----------- | -------- |
| C1      | Critical  | Rewrote `_run()` helper to mock `subprocess.run` + `_find_real_git`. Cleared TMUX env var. 53/53 tests pass. | `b036fa721` | Yes      |
| C2      | Critical  | Added 52 tests for from_dict/to_dict across all 4 adapter metadata classes + coercion helpers.               | `f0cf2b859` | Yes      |
| I1      | Important | Gated `_install_event_wait_tracer()` behind `TELECLAUDE_TRACE_EVENT_WAIT` env var.                           | `b2db01bf9` | Yes      |
| I2      | Important | Replaced read-modify-write with atomic `json_patch()` SQL UPDATE.                                            | `d7299be59` | Yes      |
| I3      | Important | Added 4 unit tests: new platform, cross-platform preservation, within-platform merge, initial write.         | `d7299be59` | Yes      |
| I4      | Important | Added 2 tests: active escalation clears state + emits event; non-escalated sessions unaffected.              | `d768ba1f3` | Yes      |

---

## Round 2 — Full Lane Re-review

### Verification Evidence

- **Unit tests:** 4315 passed, 0 failed (in 14.97s)
- **Functional tests:** 1 pre-existing timeout (`test_single_user_session_gets_admin_from_auth`) — also fails on main, not introduced by this branch
- **Lint (ruff):** Clean — no violations
- **Type check (pyright):** 0 errors, 0 warnings on key changed files

---

## Critical

No unresolved Critical findings.

---

## Important

No unresolved Important findings.

---

## Suggestions

### S1. `hasattr` Migration Shims in `_to_core_session` (Carried from R1)

**Location:** `teleclaude/core/db/_base.py:44,59,60,85,92,101`

Six `hasattr` checks guard against missing columns during migration:

```python
if hasattr(row, "origin_metadata") and row.origin_metadata:
system_role=row.system_role if hasattr(row, "system_role") else None,
job=row.job if hasattr(row, "job") else None,
turn_triggered_by_linked_output=... if hasattr(row, "turn_triggered_by_linked_output") else False,
principal=row.principal if hasattr(row, "principal") else None,
visibility=row.visibility if hasattr(row, "visibility") else "private",
```

Reasonable during migration rollout but should be cleaned up once migrations 033-035 are deployed to all environments.

### S2. Scope Creep — Unrelated Changes (Carried from R1)

Several changes are unrelated to session architecture cleanup:

- `teleclaude/chiptunes/player.py` — audio device hot-switch monitoring
- `teleclaude/adapters/telegram/lifecycle.py` — httpx pool limits
- `teleclaude/services/monitoring_service.py` — unnamed task diagnostics
- `teleclaude/events/sandbox/container.py` — asyncio.timeout pattern fix
- `teleclaude/events/signal/scheduler.py` — asyncio.timeout pattern fix

These are improvements but mix concerns in a single delivery. No functional issue but harder to bisect.

### S3. Git Wrapper TMUX Detection (Carried from R1)

**Location:** `teleclaude/install/wrappers/git:323-324`

Humans inside TMUX are now treated as workers. Behavior change should be documented.

### S4. WhatsApp Not in `channel_field` Mapping (Carried from R1)

**Location:** `teleclaude/core/adapter_client/_channels.py:263-266`

WhatsApp falls through to the default `("channel_id", str)`. Benign but the implicit fallback could cause confusion.

### S5. Unused `_human_role` Return Value

**Location:** `teleclaude/adapters/discord/input_handlers.py:480`

```python
effective_path, _human_role = self._resolve_session_creation_target(message, context)
```

`_human_role` is intentionally unused (prefixed `_`). The function still computes and returns the role but it's discarded. The role is now resolved centrally by the identity resolver in `_session.py`. Consider removing the return value from `_resolve_session_creation_target` to avoid confusion, or changing the return type to just the path.

---

## Review Lane Summary

| Lane       | Status   | Findings                                                              |
| ---------- | -------- | --------------------------------------------------------------------- |
| code       | Complete | No new findings — fix commits verified correct                        |
| paradigm   | Complete | No findings — adapter pattern consistent                              |
| principles | Complete | No new findings — race condition fixed (I2)                           |
| security   | Complete | No findings — identity resolver defaults correctly, parameterized SQL |
| tests      | Complete | No new findings — 4315 unit tests pass, fix tests adequate            |
| errors     | Complete | No new findings — tracer gated behind env var (I1)                    |
| types      | Complete | No findings — Session fields well-typed, from_dict/to_dict correct    |
| comments   | Complete | No findings — comments updated for new pattern                        |
| logging    | Complete | No findings — no debug probes, proper log levels                      |

### Why No Issues (Zero-Finding Justification)

1. **Paradigm-fit:** Verified all adapters follow consistent `_tg()`/`_dc()`/`_wa()` helper pattern with `from_dict(session.get_origin_section(key))`. DB writes use atomic `update_origin_metadata`. No copy-paste duplication found — shared behavior in `UiAdapter._origin_field` / `_set_origin_field`.

2. **Requirements met:** All 6 round-1 findings have been properly remediated:
   - Git wrapper tests fully rewritten and passing (53/53)
   - Adapter metadata from_dict/to_dict tested with round-trips, coercion, edge cases (52 tests)
   - Event wait tracer properly gated behind environment variable
   - Race condition eliminated with atomic `json_patch` SQL
   - New DB and cleanup tests cover the new behavior paths

3. **Copy-paste duplication checked:** The `_tg()`, `_dc()`, `_wa()` static methods are structurally similar across adapters but intentionally separate (each reads its own platform section). The `from_dict`/`to_dict` methods on each metadata class handle platform-specific fields.

4. **Security reviewed:** No hardcoded secrets. SQL uses parameterized queries. Identity resolver properly defaults unknown users to "customer" role (verified against `identity.py:231-235,250-255,257`). No injection vectors in the new code.

---

## Verdict

**Unresolved Critical:** 0
**Unresolved Important:** 0

**Verdict: APPROVE**
