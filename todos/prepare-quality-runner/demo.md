# Demo: Prepare Quality Runner

## Medium

CLI + daemon logs. The cartridge runs inside the daemon's event pipeline.
Observation is through DOR report files, state.yaml, and notification DB queries.

## Scenario 1: Artifact change triggers assessment

**Setup:** A todo with weak `requirements.md` exists (missing dependency section).

**Steps:**

1. Emit a `planning.artifact_changed` event for the target slug (e.g., via `telec todo`
   operations that trigger the event, or directly via producer in tests).
2. Observe daemon logs: `prepare-quality` cartridge processes event, scores artifacts.
3. Check `todos/{slug}/dor-report.md` — shows score, per-dimension breakdown, improvements made.
4. Check `todos/{slug}/state.yaml` — dor section shows score, status, assessed commit.
5. Query notification DB: notification shows `agent_status=resolved` with DOR verdict.

**Expected:** Score reflects artifact quality. Missing dependency section is filled from
roadmap.yaml. Rescore lands above threshold. Report documents all actions.

## Scenario 2: New todo triggers initial assessment

**Steps:**

1. Create a todo with `telec todo create my-feature` (triggers `planning.todo_created`).
2. Observe: event flows through pipeline, cartridge picks it up.
3. If requirements.md exists: scores it. If missing: flags `needs_work` with specific gaps.
4. DOR report shows initial assessment.
5. Notification resolved with score.

**Expected:** Every new todo gets an immediate quality baseline.

## Scenario 3: Idempotency — duplicate event skipped

**Steps:**

1. Trigger `planning.artifact_changed` for a todo that already has `dor.status == pass`
   and same commit hash in `state.yaml`.
2. Observe: cartridge logs "skipping — already assessed at commit {hash}".
3. No file writes. Event passes through to downstream cartridges unchanged.

**Expected:** No rework. No file changes. Fast pass-through.

## Scenario 4: Needs decision — notification stays unresolved

**Steps:**

1. Trigger assessment for a todo with ambiguous requirements that cannot be structurally improved.
2. Cartridge scores below 7, marks `needs_decision`.
3. DOR report lists specific blockers and decisions needed.
4. Notification remains `agent_status=none` (not resolved) — visible for human attention.

**Expected:** Human sees the unresolved notification, reads the blockers, provides direction.

## Validation commands

```bash
# Check pipeline cartridges in daemon logs
instrukt-ai-logs teleclaude --since 5m --grep "prepare-quality"

# Query notification state for planning events
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/api/events/notifications?domain=software-development&limit=5"

# Check DOR report
cat todos/{slug}/dor-report.md

# Check state
cat todos/{slug}/state.yaml | grep -A 10 "dor:"
```
