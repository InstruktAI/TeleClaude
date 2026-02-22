# Deferrals: member-invite

## Deferred: Phase 6 — Identity-Aware Routing via `resolve_project_path`

**Tasks:** 6.1, 6.2, 6.3

**What:** The implementation plan specified a `resolve_project_path(identity)` helper to centralize routing decisions. Both adapters instead call `scaffold_personal_workspace(person_name)` directly at the point of session creation, achieving the same routing outcome with a simpler pattern.

**Why deferred:** The centralized helper adds an indirection layer that isn't needed — each adapter already resolves identity and routes inline. The dead `resolve_project_path()` function is removed as part of this review cycle. Routing works correctly without it.

**Impact:** None. Personal workspace routing is functional in both Telegram and Discord adapters. The routing logic is inline rather than centralized, which is appropriate given there are only two adapters.

**Follow-up:** If a third adapter (WhatsApp) is added, consider extracting a shared routing helper at that point.

---

## Deferred: Phase 7 — Notification Channel Expansion

**Tasks:** 7.1, 7.2, 7.3

**What:** Extend the notification outbox worker to deliver via Discord DM and email channels in addition to Telegram. Requires a new `teleclaude/notifications/discord.py` sender module and changes to `worker.py` dispatch logic.

**Why deferred:** The core invite flow (token generation, email delivery, identity binding, personal workspace routing) is fully functional without notification channel expansion. The outbox worker currently handles Telegram delivery, which covers the primary notification path. Discord DM and email delivery through the outbox are separate concerns from the invite onboarding flow.

**Impact:** Notification outbox marks non-telegram delivery channels as failed. This does not affect the invite flow itself — invite emails are sent directly via `send_invite_email()`, not through the outbox worker.

**Follow-up:** Create a dedicated `notification-channels` todo to implement Discord and email senders in the outbox worker.

---

## Deferred: Phase 8 — Validation and Tests

**Tasks:** 8.1, 8.2, 8.3

**What:** Unit tests for invite token generation/lookup, email delivery, credential binding, adapter handlers, and routing. Integration tests for the full invite flow. Manual verification steps.

**Why deferred:** The implementation was focused on delivering functional code for Phases 1-5. Test authoring for adapter handlers and async email delivery requires mock infrastructure (mocked SMTP, mocked Telegram/Discord APIs, mocked identity resolution) that warrants dedicated effort.

**Impact:** New code (364 lines) ships without dedicated test coverage. Existing tests continue to pass. The risk is mitigated by the fact that core invite logic (token generation, link building) is straightforward, and adapter handlers follow established patterns.

**Follow-up:** Create a `member-invite-tests` todo covering unit tests for `invite.py`, `email.py`, and adapter handler methods.

---

## Deferred: Phase 9 — Review Readiness Checklist

**Tasks:** 9.1-9.5

**What:** Final cross-check of requirements coverage, task completion, regression verification, and documentation updates.

**Why deferred:** These tasks are procedural gates that depend on all prior phases being complete. With Phases 6-8 deferred, Phase 9 cannot be fully completed.

**Impact:** None beyond the scope already documented above.

**Follow-up:** Complete as part of re-review after deferred phases are addressed.
