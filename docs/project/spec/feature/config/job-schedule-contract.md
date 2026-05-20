---
id: 'project/spec/feature/config/job-schedule-contract'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Job scheduling contract requiring exactly one of an interval (`every`) or wall-clock times (`at`), with weekday filtering reserved for `at` schedules and a legacy fallback `schedule` field still accepted.'
---

# Job Schedule Contract — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

A job declares WHEN it runs through the `JobWhenConfig` block carried inside
`JobScheduleConfig` (the per-job entry under `ProjectConfig.jobs`). v1 enforces
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
time by Pydantic validators; an ill-formed entry fails the project config load
outright rather than producing a silently misscheduled job.

## Canonical fields

### Use cases

#### UC-CFG-JOB-1: Interval schedule with valid duration accepted

```
Given a project config under load with jobs.my-job.when.every = "10m"
When JobWhenConfig.validate_every_format runs
Then the regex ^(\d+)([mhd])$ matches with value 10 and unit "m"
And the integer 10 is >= 1
And the value is returned unchanged
And validate_mode confirms exactly one of (every, at) is set
And the JobWhenConfig is accepted
```

#### UC-CFG-JOB-2: Interval schedule with malformed duration rejected

```
Given a project config under load with jobs.my-job.when.every = "5s"
When JobWhenConfig.validate_every_format runs
Then the regex ^(\d+)([mhd])$ does NOT match (only m|h|d units are allowed)
Then a ValueError is raised with the message:
  "Invalid duration format: 5s. Expected format: <number><m|h|d> (e.g., '10m', '2h', '1d')"
And load_project_config raises before the job is registered
```

#### UC-CFG-JOB-3: Interval schedule with sub-minute duration rejected

```
Given a project config under load with jobs.my-job.when.every = "0m"
When JobWhenConfig.validate_every_format runs
Then the regex matches with value 0 and unit "m"
And the integer 0 is < 1
And a ValueError is raised with the message:
  "Duration must be at least 1 minute, got: 0m"
```

#### UC-CFG-JOB-4: Wall-clock schedule with single time accepted

```
Given a project config under load with jobs.my-job.when.at = "09:00"
When JobWhenConfig.validate_at_format runs
Then the regex ^(\d{2}):(\d{2})$ matches with hour 9 and minute 0
And the hour is within 0..23 and the minute is within 0..59
And the value is returned unchanged
And validate_mode confirms exactly one of (every, at) is set
And the JobWhenConfig is accepted
```

#### UC-CFG-JOB-5: Wall-clock schedule with list of times accepted

```
Given a project config under load with jobs.my-job.when.at = ["09:00", "14:30", "22:15"]
When JobWhenConfig.validate_at_format runs
Then each entry is validated independently against ^(\d{2}):(\d{2})$
And all entries pass hour 0..23 and minute 0..59 checks
And the list is returned unchanged
```

#### UC-CFG-JOB-6: Wall-clock schedule with malformed time rejected

```
Given a project config under load with jobs.my-job.when.at = "9:00"
When JobWhenConfig.validate_at_format runs
Then the regex requires two-digit hour and minute and does NOT match
Then a ValueError is raised with the message:
  "Invalid time format: 9:00. Expected format: HH:MM (e.g., '09:00', '14:30')"
```

#### UC-CFG-JOB-7: Wall-clock schedule with out-of-range hour rejected

```
Given a project config under load with jobs.my-job.when.at = "24:00"
When JobWhenConfig.validate_at_format runs
Then the regex matches but the hour 24 is outside 0..23
Then a ValueError is raised with the message:
  "Invalid hour in 24:00: must be 00-23"
```

#### UC-CFG-JOB-8: Wall-clock schedule with out-of-range minute rejected

```
Given a project config under load with jobs.my-job.when.at = "09:60"
When JobWhenConfig.validate_at_format runs
Then the regex matches but the minute 60 is outside 0..59
Then a ValueError is raised with the message:
  "Invalid minute in 09:60: must be 00-59"
```

#### UC-CFG-JOB-9: Both `every` and `at` set is rejected

```
Given a project config under load with jobs.my-job.when.every = "10m"
And jobs.my-job.when.at = "09:00"
When JobWhenConfig.validate_mode runs
Then bool(self.every) == bool(self.at) is True (both truthy)
Then a ValueError is raised with the message:
  "Specify exactly one of 'every' or 'at'"
```

#### UC-CFG-JOB-10: Neither `every` nor `at` set is rejected

```
Given a project config under load with jobs.my-job.when present but with no every and no at
When JobWhenConfig.validate_mode runs
Then bool(self.every) == bool(self.at) is True (both falsy)
Then a ValueError is raised with the message:
  "Specify exactly one of 'every' or 'at'"
```

#### UC-CFG-JOB-11: `weekdays` without `at` is rejected

```
Given a project config under load with jobs.my-job.when.every = "1h"
And jobs.my-job.when.weekdays = ["mon", "fri"]
When JobWhenConfig.validate_mode runs
Then self.weekdays is truthy AND self.at is None
Then a ValueError is raised with the message:
  "'weekdays' requires 'at'"
```

#### UC-CFG-JOB-12: `weekdays` with `at` is accepted

```
Given a project config under load with jobs.my-job.when.at = "09:00"
And jobs.my-job.when.weekdays = ["mon", "tue", "wed", "thu", "fri"]
When JobWhenConfig.validate_mode runs
Then self.weekdays is truthy AND self.at is set
Then the JobWhenConfig is accepted
```

#### UC-CFG-JOB-13: Legacy `schedule` field still parses

```
Given a project config under load with jobs.my-job.schedule = "daily"
And jobs.my-job.when is omitted
When JobScheduleConfig is constructed
Then the Literal["hourly", "daily", "weekly", "monthly"] type accepts "daily"
And `when` is None
And no validator on JobScheduleConfig rejects a missing `when` block
And the job is accepted with its legacy schedule string
```

#### UC-CFG-JOB-14: Execution config fields default appropriately

```
Given a project config under load with jobs.my-job set to an empty dict
When JobScheduleConfig is constructed
Then category defaults to "subscription"
And preferred_hour defaults to 6 (validated within 0..23)
And preferred_weekday defaults to 0 (validated within 0..6)
And preferred_day defaults to 1 (validated within 1..31)
And agent defaults to "claude"
And thinking_mode defaults to "fast"
And when, schedule, type, script, job, message, timeout all default to None
```

### Implementation pointers (v1)

- `teleclaude/config/schema.py:22-79` — `JobWhenConfig` with `validate_every_format`, `validate_at_format`, and `validate_mode` model validator enforcing XOR + weekday rule.
- `teleclaude/config/schema.py:82-102` — `JobScheduleConfig` wrapping `JobWhenConfig`, retaining the legacy `schedule` field plus execution and preference defaults.
- `teleclaude/config/schema.py:320` — `ProjectConfig.jobs: dict[str, JobScheduleConfig]` (the project-level container that ties named jobs to their schedules).

### Cross-context references

- Consumed by the `daemon` scheduler that polls `ProjectConfig.jobs` to dispatch jobs at the declared cadence. The scheduler reads `when.every` / `when.at` / `when.weekdays` directly; the legacy `schedule` field is interpreted at the same layer.
- Subscriptions reference jobs by slug via `JobSubscription.job` (see `subscription-routing.md`) and may carry their own `when` override on the subscription side; the contract enforced by `JobWhenConfig` applies identically to the subscription-side override.

## Allowed values

- `when.every` — string matching `^(\d+)([mhd])$` where the leading integer is `>= 1`. Units: `m` (minutes), `h` (hours), `d` (days). Example: `"10m"`, `"2h"`, `"1d"`.
- `when.at` — `HH:MM` string (two-digit hour 00–23, two-digit minute 00–59) OR a list of such strings.
- `when.weekdays` — list of `"mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun"`. Only valid when `at` is set.
- `schedule` (legacy) — `"hourly" | "daily" | "weekly" | "monthly"`.
- `category` — `"subscription" | "system"`. Default: `"subscription"`.

## Known caveats

- **Validation runs on every load.** A `teleclaude.yml` edited out-of-band to violate the XOR rule fails the next `load_project_config` call; the daemon refuses to load a project whose `jobs` block is malformed.
- **`schedule` and `when` are not jointly validated.** A job may declare both a legacy `schedule` value and a modern `when` block; nothing in the schema rejects the combination. The scheduler decides which to honor.
- **Unit floor is one minute, but unit choice is unconstrained.** A literal `"525600m"` is accepted even though `"1y"` would be more readable; the regex permits only m/h/d so a "year" unit is unrepresentable.
- **Weekday rule is one-directional.** Empty `weekdays` is always accepted (treated as "no day filter"). The rule fires only when `weekdays` is non-empty AND `at` is missing.
- **`JobScheduleConfig.when` is optional.** A job with neither `when` nor `schedule` set parses successfully; the scheduler treats it as ad-hoc / triggered, not periodic. The schema does not require any cadence to be declared.
- **`extra="allow"` admits unknown keys.** Both `JobWhenConfig` and `JobScheduleConfig` accept additional YAML keys without warning; typos in field names will silently land in the model rather than failing validation.
