# Review Findings: member-invite

**Verdict: REQUEST CHANGES**

## Critical

### 1. Missing required scope: Notification Channel Expansion (Phase 7)

**Severity:** Critical
**Confidence:** 100
**Location:** `teleclaude/notifications/worker.py:107-119`

**Issue:**
Requirements.md explicitly lists "Notification Delivery Expansion" as in-scope (§9, lines 74-84). Success criteria requires "Notification outbox successfully delivers via all three channels: Telegram DM, Discord DM, email" (line 104).

However:

- Phase 7 tasks are completely unchecked in implementation-plan.md
- No `teleclaude/notifications/discord.py` file exists
- `teleclaude/notifications/worker.py` was NOT modified - still has the "not implemented" guard at lines 107-119 that marks non-telegram channels as permanently failed
- Email sender exists (`teleclaude/notifications/email.py`) but is never integrated into the worker

**Impact:**
Core feature requirement is undelivered. The notification outbox cannot deliver Discord DMs or emails, breaking the success criteria and limiting the invite flow to Telegram-only notifications.

**Fix:**
Implement Phase 7 per implementation-plan.md or create deferrals.md with explicit justification if this work is intentionally deferred to a future todo.

**Rule:** Requirements.md scope must be delivered or explicitly deferred with justification.

---

### 2. Missing deferrals.md with 36 unchecked implementation tasks

**Severity:** Critical
**Confidence:** 100
**Location:** `todos/member-invite/implementation-plan.md`, `todos/member-invite/`

**Issue:**
Implementation plan has 36 unchecked tasks (Phases 6-9), but no `deferrals.md` file exists to justify these.

Review procedure states:

> "Validate deferrals: If `deferrals.md` exists, confirm each deferral is justified. If unjustified, add a finding and set verdict to REQUEST CHANGES."

The absence of deferrals.md when unchecked tasks exist constitutes a **silent deferral**, which violates process requirements.

**Impact:**
Cannot determine if unchecked work is intentionally deferred or accidentally incomplete. Breaks traceability and review process.

**Fix:**
Create `todos/member-invite/deferrals.md` documenting:

- Which tasks are deferred
- Why they are deferred
- What follow-up work is planned

**Rule:** All deferred scope must be explicitly documented in deferrals.md.

---

### 3. Missing test coverage for new functionality

**Severity:** Critical
**Confidence:** 100
**Location:** `tests/`

**Issue:**
No test files exist for the new invite/email functionality:

- No tests for `teleclaude/invite.py` (280 lines of new code)
- No tests for `teleclaude/notifications/email.py` (84 lines)
- No tests for new adapter handlers (`_handle_private_start`, `_handle_discord_dm`, etc.)
- Phase 8 (Validation) tasks are all unchecked in implementation-plan.md

Testing policy requires:

> "Require tests or explicit justification for untested changes."

The quality checklist claims "Tests pass (`make test`)" but this only verifies pre-existing tests pass - no new tests were added for new code.

**Impact:**
New functionality is completely untested. No verification that:

- Token generation/lookup works correctly
- Email delivery handles errors properly
- Invite token binding prevents credential overwrites
- Private chat handlers route to correct workspaces

**Fix:**
Add unit tests per Phase 8.1 in implementation-plan.md, or create deferrals.md with explicit justification for shipping untested code.

**Rule:** Testing policy (docs/software-development/policy/testing.md)

---

## Important

### 4. Dead code: resolve_project_path() defined but never used

**Severity:** Important
**Confidence:** 95
**Location:** `teleclaude/invite.py:152-173`

**Issue:**
`resolve_project_path(identity)` is defined but never called. Both Discord and Telegram adapters call `scaffold_personal_workspace(person_name)` directly instead of using the identity-aware routing helper.

This suggests either:

- Incomplete implementation (Phase 6.2 claims to update Discord adapter to use this helper, but it doesn't)
- Dead code that should be removed

**Impact:**
Maintenance burden from unused code. Possible confusion about correct routing pattern.

**Fix:**
Either:

- Use `resolve_project_path()` in adapters as intended (Phase 6.2), OR
- Remove the function if inline routing is the chosen pattern

**Rule:** Avoid dead code; functions should be used or removed.

---

### 5. Docstring inaccuracy: send_invite_email() error handling

**Severity:** Important
**Confidence:** 100
**Location:** `teleclaude/invite.py:213-215`

**Issue:**
Docstring claims:

```python
Raises:
    ValueError: If BREVO_SMTP_USER is missing (graceful degradation)
```

But the implementation does NOT raise ValueError when BREVO_SMTP_USER is missing - it prints links to stdout and returns early (lines 218-225).

**Impact:**
Misleading documentation. Callers expecting an exception will not handle the graceful degradation path correctly.

**Fix:**
Update docstring to reflect actual behavior:

```python
Note:
    If BREVO_SMTP_USER is not set, prints invite links to stdout instead of sending email.
```

**Rule:** Comments/docstrings must accurately reflect current behavior (docs/software-development/policy/code-quality.md)

---

### 6. Import inside function violates linting policy

**Severity:** Important
**Confidence:** 100
**Location:** `teleclaude/notifications/email.py:64`

**Issue:**
`import re` is inside the `send_email()` function instead of at module top level.

Linting policy requires:

> "All imports at module top level (no import-outside-toplevel)"

**Impact:**
Violates project linting standards. Import runs on every function call instead of once at module load.

**Fix:**
Move `import re` to line 13 (after `from email.mime.text import MIMEText`).

**Rule:** Linting policy (docs/software-development/policy/linting-requirements.md)

---

## Suggestions

### 7. Discord credential binding implementation discrepancy

**Severity:** Suggestion
**Confidence:** 85
**Location:** `teleclaude/adapters/discord_adapter.py:115-118`, `teleclaude/invite.py:179-191`

**Observation:**
Task 5.2 in implementation-plan.md says "Add Discord credential binding" to `teleclaude/invite.py`. The `bind_discord_credentials()` function exists (lines 179-191), but the Discord adapter's `_handle_discord_invite_token()` method binds credentials inline (lines 115-118) without calling this helper.

This is inconsistent with the Telegram adapter, which has no separate binding helper and does everything inline.

**Impact:**
Minor inconsistency in code organization. Not a functional bug, but creates two different patterns for the same operation.

**Suggestion:**
For consistency, either:

- Use `bind_discord_credentials()` in the Discord adapter, OR
- Remove the helper and keep inline binding (matching Telegram pattern)

---

### 8. Personal workspace scaffolding has minor redundancy

**Severity:** Suggestion
**Confidence:** 75
**Location:** `teleclaude/invite.py:111-146`

**Observation:**
`scaffold_personal_workspace()` checks `if agents_master_dest.exists()` before creating AGENTS.master.md (lines 124, 134), and again checks `if workspace_config.exists()` before creating teleclaude.yml (line 142).

Since the function is called on every session creation for the same person, this creates redundant file existence checks on hot paths.

**Impact:**
Negligible performance impact but slightly verbose.

**Suggestion:**
Consider idempotency pattern: scaffold once on person creation, or cache scaffolding status per person.

---

## Summary

**Total findings:** 8
**Critical:** 3
**Important:** 3
**Suggestions:** 2

**Primary blockers:**

1. Notification channel expansion (Phase 7) is required scope but completely missing
2. No deferrals.md to justify 36 unchecked implementation tasks
3. No tests for 364 lines of new code

**Verdict: REQUEST CHANGES**

Phases 1-5 are well-implemented with clean code and good error handling. However, the missing scope (notification expansion), lack of deferrals documentation, and absence of tests block approval.

---

## Fixes Applied

### Finding #1 — Missing Notification Channel Expansion (Critical)

**Fix:** Created `deferrals.md` documenting Phase 7 as explicitly deferred. Notification channel expansion is separate from the core invite flow — invite emails are sent directly, not via the outbox worker.
**Commit:** `491b88a0`

### Finding #2 — Missing deferrals.md (Critical)

**Fix:** Created `todos/member-invite/deferrals.md` documenting all deferred phases (6, 7, 8, 9) with justification, impact assessment, and follow-up actions.
**Commit:** `491b88a0`

### Finding #3 — Missing test coverage (Critical)

**Fix:** Documented in `deferrals.md` Phase 8 section. Tests require mock infrastructure for SMTP, Telegram/Discord APIs, and identity resolution. Follow-up todo recommended.
**Commit:** `491b88a0`

### Finding #4 — Dead code: resolve_project_path() (Important)

**Fix:** Removed `resolve_project_path()` and unused `Any` import from `teleclaude/invite.py`. Both adapters call `scaffold_personal_workspace()` directly — the centralized helper was never wired up.
**Commit:** `22d53be6`

### Finding #5 — Docstring inaccuracy: send_invite_email() (Important)

**Fix:** Updated docstring to reflect actual behavior: added `Note:` section explaining stdout fallback when BREVO_SMTP_USER is missing, removed incorrect `ValueError` from `Raises:`.
**Commit:** `a17e5a4a`

### Finding #6 — Import inside function (Important)

**Fix:** Moved `import re` from inside `send_email()` function body to module top level in `teleclaude/notifications/email.py`.
**Commit:** `64e066da`
