# Requirements: telegram-adapter-hardening

## Goal

Harden Telegram message routing, delivery contracts, cleanup behavior, and ownership checks so that failures are explicit, cleanup is bounded, and cross-layer responsibility is clear.

## In Scope

1. **Sentinel coercion removal** — `CommandMapper` coerces missing `project_path` to `""` in three places. Missing required values must fail at ingress, not silently become empty strings.
2. **Help-desk fallback restriction** — `create_session` defaults missing `project_path` to `help-desk` even for unrestricted callers. Remove this non-role-based reroute; preserve the explicit non-admin jail.
3. **Session data contract clarity** — `get_session_data` returns ambiguous payloads where `messages` can be tmux output, pending notice, or parsed transcript. Callers cannot distinguish state without string inspection.
4. **Send-message return contract** — `MessageOperationsMixin.send_message` returns `""` when `topic_id` is not ready. This sentinel is indistinguishable from a failure to callers.
5. **Orphan topic cleanup suppression** — `_delete_orphan_topic` can be called repeatedly for the same invalid topic from `_handle_text_message`, `_handle_topic_closed`, and `_require_session_from_topic` with no backoff or cooldown.
6. **Ownership check hardening** — `_topic_owned_by_this_bot` relies solely on title string matching (`@computer` or `$computer`). This heuristic can produce false positives when topic titles are reused or stale.
7. **Parse-entities error handling** — `can't parse entities` errors in `edit_message` are logged but the fallback path is implicit. Make the retry/skip behavior explicit and observable.

## Out of Scope

1. Redesign of the adapter model or UiAdapter base class.
2. Non-Telegram adapter behavior.
3. TUI/visual changes.
4. Full identity/authorization redesign.

## Success Criteria

- [ ] `CommandMapper` raises or returns explicit error when `project_path` is missing and required.
- [ ] Session creation for unrestricted callers without `project_path` fails explicitly instead of silently routing to help-desk.
- [ ] Non-admin role jail to help-desk remains functional and unchanged.
- [ ] `get_session_data` response includes an explicit `source` field distinguishing transcript, tmux fallback, and pending states.
- [ ] `send_message` returns `None` (not `""`) when delivery is skipped, or raises on unrecoverable failure.
- [ ] Repeated orphan topic deletes for the same `topic_id` are suppressed within a cooldown window (e.g., 60s).
- [ ] `_topic_owned_by_this_bot` cross-references DB session records, not just title strings, before authorizing delete.
- [ ] Parse-entities failures emit a structured log with reason code and the fallback action taken is explicit.
- [ ] All changes pass `make lint` and `make test`.

## Constraints

1. Preserve existing user-facing functional behavior where safe.
2. Keep changes incremental with atomic commits per concern.
3. Do not introduce new fallback paths that hide failures.

## Risks

1. Tightening `project_path` contracts may surface latent callers that rely on the empty-string sentinel.
2. Suppression logic tuned too aggressively may hide legitimate one-off cleanup recovery.
3. Ownership check changes may leave some orphan topics uncleaned if the DB record is already deleted.
