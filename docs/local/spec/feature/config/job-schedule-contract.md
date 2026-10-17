---
description: Job scheduling contract requiring exactly one of an interval (`every`)
  or wall-clock times (`at`), with weekday filtering reserved for `at` schedules.
visibility: public
---

# Job Schedule Contract — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

A job declares WHEN it runs through the `when` schedule block carried inside
the job schedule entry (held under the project overlay's `jobs` mapping). v1 enforces
a strict XOR contract on `when`: exactly one of `every` (an interval expressed
as `<number><m|h|d>` with a minimum of one minute) OR `at` (a single `HH:MM`
string or a list of them, each validated against 00–23 hours and 00–59 minutes)
must be set. The `weekdays` filter is only meaningful for wall-clock schedules
and is rejected when `at` is absent. Beyond the modern `when` contract,
`JobScheduleConfig` also carries a legacy `schedule` field
(`hourly|daily|weekly|monthly`) that still parses for backward compatibility,
plus execution-shape fields (`type`, `script`, `job`, `agent`, `thinking_mode`,
`message`, `timeout`) and ordering hints (`category`, `preferred_hour`,
`preferred_weekday`, `preferred_day`). The contract is enforced at YAML load
time by schema validators; an ill-formed entry fails the project config load
outright rather than producing a silently misscheduled job.

## Canonical fields

### Use cases

#### UC-CFG-JOB-1: Interval schedule with valid duration accepted

#### UC-CFG-JOB-2: Interval schedule with malformed duration rejected

#### UC-CFG-JOB-3: Interval schedule with sub-minute duration rejected

#### UC-CFG-JOB-4: Wall-clock schedule with single time accepted

#### UC-CFG-JOB-5: Wall-clock schedule with list of times accepted

#### UC-CFG-JOB-6: Wall-clock schedule with malformed time rejected

#### UC-CFG-JOB-7: Wall-clock schedule with out-of-range hour rejected

#### UC-CFG-JOB-8: Wall-clock schedule with out-of-range minute rejected

#### UC-CFG-JOB-9: Both `every` and `at` set is rejected

#### UC-CFG-JOB-10: Neither `every` nor `at` set is rejected

#### UC-CFG-JOB-11: `weekdays` without `at` is rejected

#### UC-CFG-JOB-12: `weekdays` with `at` is accepted

#### UC-CFG-JOB-13: Legacy `schedule` field still parses

### Execution configuration ownership

`JobScheduleConfig` in `teleclaude/config/schema.py` owns execution-field
defaults. Scheduled agent launch resolves an omitted thinking mode in
`teleclaude/api/run_session_job.py`.

### Cross-context references

- Consumed by the scheduling bounded context that polls per-project jobs
  to dispatch them at the declared cadence. The scheduler reads
  `when.every` / `when.at` / `when.weekdays` directly; the legacy
  `schedule` field is interpreted at the same layer.
- Subscriptions reference jobs by slug (see `subscription-routing.md`)
  and may carry their own `when` override on the subscription side; the
  contract enforced here applies identically to the subscription-side
  override.

## Allowed values

- `when.every` — string matching `^(\d+)([mhd])$` where the leading integer is `>= 1`. Units: `m` (minutes), `h` (hours), `d` (days). Example: `"10m"`, `"2h"`, `"1d"`.
- `when.at` — `HH:MM` string (two-digit hour 00–23, two-digit minute 00–59) OR a list of such strings.
- `when.weekdays` — list of `"mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun"`. Only valid when `at` is set.
- `schedule` (legacy) — `"hourly" | "daily" | "weekly" | "monthly"`.
- `category` — `"subscription" | "system"`. Default: `"subscription"`.

## Known caveats

- **Validation runs on every load.** A `teleclaude.yml` edited out-of-band to violate the XOR rule fails the next project-config load; the runtime refuses to load a project whose `jobs` block is malformed.
- **`schedule` and `when` are not jointly validated.** A job may declare both a legacy `schedule` value and a modern `when` block; nothing in the schema rejects the combination. The scheduler decides which to honor.
- **Unit floor is one minute, but unit choice is unconstrained.** A literal `"525600m"` is accepted even though `"1y"` would be more readable; the regex permits only m/h/d so a "year" unit is unrepresentable.
- **Weekday rule is one-directional.** Empty `weekdays` is always accepted (treated as "no day filter"). The rule fires only when `weekdays` is non-empty AND `at` is missing.
- **The job schedule's `when` block is optional.** A job with neither `when` nor `schedule` set parses successfully; the scheduler treats it as ad-hoc / triggered, not periodic. The schema does not require any cadence to be declared.
- **Extra YAML keys are silently accepted.** Both the `when` block and the job schedule entry accept additional YAML keys without warning; typos in field names will silently land in the config rather than failing validation.
