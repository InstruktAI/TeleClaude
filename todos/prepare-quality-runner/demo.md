# Demo: Prepare Quality Runner

## Medium

CLI + daemon logs. The handler runs inside the daemon and reacts to events.
Observation is through the notification API, DOR report files, and state.yaml.

## Scenario 1: Artifact change triggers assessment

**Setup:** A todo with weak `requirements.md` exists.

**Steps:**

1. Modify `requirements.md` for the target todo (triggers `todo.artifact_changed`).
2. Observe daemon logs: handler claims the notification, starts assessment.
3. Check `todos/{slug}/dor-report.md` — shows score, gaps, improvements made.
4. Check `todos/{slug}/state.yaml` — dor section shows score, status, assessed commit.
5. Query notification API: notification is resolved with DOR verdict.

**Expected:** Score reflects artifact quality. If below threshold, artifacts are improved
and rescored. Report documents all actions.

## Scenario 2: Brain dump triggers preparation

**Steps:**

1. Run `telec todo dump "Build a webhook validator for external services"`.
2. Observe: `todo.dumped` event fires, handler picks it up.
3. Handler generates `requirements.md` and `implementation-plan.md` from the dump.
4. DOR report shows initial assessment with generated artifacts.
5. Notification resolved with score.

**Expected:** Fire-and-forget dump produces structured preparation artifacts automatically.

## Scenario 3: Idempotency — duplicate event skipped

**Steps:**

1. Trigger `todo.artifact_changed` for a todo that already has `dor.status == pass`
   and same commit hash.
2. Observe: handler logs "skipping — already assessed at commit {hash}".
3. Notification resolved as no-op.

**Expected:** No rework. No file changes. Fast resolution.

## Scenario 4: Needs decision — notification stays unresolved

**Steps:**

1. Trigger assessment for a todo with ambiguous requirements that cannot be safely improved.
2. Handler scores below 7, marks `needs_decision`.
3. DOR report lists specific blockers and decisions needed.
4. Notification remains unresolved — visible in TUI/API as awaiting human attention.

**Expected:** Human sees the unresolved notification, reads the blockers, provides direction.

## Validation commands

```bash
# Check handler registration
telec events list | grep todo

# Query notification state
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/api/notifications?domain=todo&limit=5"

# Check DOR report
cat todos/{slug}/dor-report.md

# Check state
cat todos/{slug}/state.yaml | grep -A 10 "dor:"
```
