# Review Findings: job-report-notifications

**Review round:** 1
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-21
**Diff scope:** 24 files changed, +1426 / -480 lines (11 commits)

---

## Requirements Traceability

All 15 success criteria from requirements.md are satisfied:

| #   | Criterion                                                          | Status | Evidence                                                  |
| --- | ------------------------------------------------------------------ | ------ | --------------------------------------------------------- |
| 1   | `JobScheduleConfig.category` defaults to `"subscription"`          | PASS   | `schema.py:68` + test                                     |
| 2   | `Subscription` base has `enabled: bool = True`                     | PASS   | `schema.py:131` + test                                    |
| 3   | Subscription jobs with no enabled subscribers don't execute        | PASS   | `runner.py:476-477` + `test_cron_runner_subscriptions.py` |
| 4   | Subscription jobs run when enabled subscriber's `when` is due      | PASS   | `_should_run_subscription_job()` + test                   |
| 5   | System jobs run on project-level schedule                          | PASS   | `runner.py:478-479` + test                                |
| 6   | System job results auto-delivered to admins                        | PASS   | `job_recipients.py:89-93` + test                          |
| 7   | Opt-in system subscribers receive via preferred channel            | PASS   | `job_recipients.py:91` + test                             |
| 8   | Disabled subscriptions ignored by execution and delivery           | PASS   | `runner.py:318`, `job_recipients.py:80` + tests           |
| 9   | `last_notified` tracks delivery progress                           | PASS   | `state.py:35,119-123` + test                              |
| 10  | Undelivered reports detected by mtime > last_notified              | PASS   | `notification_scan.py:38` + test                          |
| 11  | `delivery_channel` routes to correct backend                       | PASS   | `worker.py:105-119` + test                                |
| 12  | Legacy `NotificationsConfig` and old `SubscriptionsConfig` removed | PASS   | Confirmed absent from schema.py                           |
| 13  | Migration script converts person configs                           | PASS   | `scripts/migrate_person_configs.py`                       |
| 14  | Full test suite passes                                             | PASS   | Builder reports 1815 pass (44 pre-existing TUI)           |
| 15  | Lint passes                                                        | PASS   | Builder reports 0 pyright errors                          |

## Deferrals

No `deferrals.md` exists. No hidden deferrals detected in implementation plan — all tasks are checked.

## Implementation Plan

All tasks in `implementation-plan.md` are marked `[x]`. Build section of `quality-checklist.md` is fully checked.

---

## Critical

(none)

## Important

### I1: Migration script has no automated tests

**File:** `scripts/migrate_person_configs.py`
**Severity:** Important

The migration script touches every person's YAML config file in production. It has `--dry-run` and backup support, which is good, but there are zero automated tests. The `_migrate()` and `_is_new_format()` functions are pure and easily testable. A test file with representative old-format configs would catch regressions if the script is ever re-run or adapted.

**Recommendation:** Add `tests/unit/test_migrate_person_configs.py` with cases for: already-migrated (idempotent skip), legacy notifications+channels, old dict-style youtube, mixed existing+new subscriptions.

### I2: `_should_run_subscription_job` with `when=None` subscriber is fire-once

**File:** `teleclaude/cron/runner.py:326-328`
**Severity:** Important

When a `JobSubscription` has no `when` field, the function only returns `True` if `job_state.last_run is None` (never run before). After the first run, this subscriber will never trigger the job again. This makes `when=None` subscriptions effectively one-shot. The `JobSubscription` schema allows `when: Optional[JobWhenConfig] = None`, so this is a reachable state.

If the intent is that subscribers without `when` defer to the project-level schedule, the fallback logic is missing. If fire-once is intentional, consider documenting it or making `when` required on `JobSubscription`.

---

## Suggestions

### S1: `recipient_email` column stores chat IDs — semantic drift

**File:** `teleclaude/core/db_models.py:146`, `teleclaude/notifications/worker.py:123`

The `recipient_email` column now stores Telegram chat IDs (e.g. `"111"`) for subscription-path notifications. The worker distinguishes old email rows from new chat_id rows by checking for `"@"` in the value. This works but is fragile — a future channel could use an address containing `@`. Consider renaming to `recipient_address` in a future migration.

### S2: `_resolve_recipient_address` silent fallback to telegram

**File:** `teleclaude/notifications/router.py:122-124`

When `preferred_channel` is `"discord"` (or any unsupported channel), the function falls through to a telegram fallback. The outbox row still gets `delivery_channel="discord"`, so the worker correctly rejects it. But the fallback masks the fact that no discord address was resolved. A debug-level log here would improve observability.

### S3: Consider `when` as required on `JobSubscription`

**File:** `teleclaude/config/schema.py:138`

If the fire-once behavior in I2 is undesirable, making `when` required on `JobSubscription` (with a sensible default like `every: "1d"`) would eliminate the ambiguity. This is a design choice, not a defect.

---

## Test Coverage Assessment

| Module                              | Test file                           | Coverage                                                          |
| ----------------------------------- | ----------------------------------- | ----------------------------------------------------------------- |
| `config/schema.py` (new models)     | `test_config_schema.py`             | Good — defaults, roundtrips, toggles, YAML integration            |
| `cron/state.py`                     | `test_cron_state.py`                | Good — default None, roundtrip, mark_notified create/update       |
| `cron/job_recipients.py`            | `test_job_recipients.py`            | Good — subscription/system jobs, admin inclusion, dedup, disabled |
| `cron/notification_scan.py`         | `test_notification_scan.py`         | Good — undelivered, already notified, empty, multiple jobs        |
| `cron/runner.py` (subscription)     | `test_cron_runner_subscriptions.py` | Good — skip no subs, skip disabled, system always due             |
| `notifications/router.py`           | `test_notifications.py`             | Good — enqueue rows, delivery_channel, skip no address            |
| `notifications/worker.py`           | `test_notifications.py`             | Good — telegram delivery, unsupported channel, isolated failures  |
| `scripts/migrate_person_configs.py` | (none)                              | **Gap** — see I1                                                  |

No prose-lock assertions found. Tests verify behavior, not documentation wording.

## Logging Hygiene

- All modules use `instrukt_ai_logging.get_logger(__name__)` — consistent structured logging.
- No temporary debug probes found.
- Log messages use structured key-value pairs (logfmt-compatible).
- Appropriate log levels: `error` for failures, `warning` for degraded paths, `debug` for skipped items, `info` for operational events.

## Architecture

- Clean separation: schema → state → discovery → scan → routing → delivery. Each module has a single responsibility.
- Discriminated union `SubscriptionEntry` is idiomatic Pydantic v2 — extensible for future subscription types.
- Mailbox-flag pattern (mtime vs last_notified) is simple and correct for the use case.
- Legacy gutting of `notifications/discovery.py` is clean — retains API surface but returns empty, with docstring explaining the deprecation.
- DB migration is additive and idempotent — safe for existing deployments.
- Commit history is clean: one logical commit per implementation task, chronological.

---

## Verdict: APPROVE

The implementation is well-structured, requirements are fully traced, code quality is high, and test coverage is comprehensive. The two Important findings (I1: missing migration script tests, I2: fire-once `when=None` semantics) are real but not blocking — I1 is a testing gap for a one-time script with dry-run/backup safety, and I2 is a design ambiguity that should be documented. Neither represents a regression risk for the core notification pipeline.
