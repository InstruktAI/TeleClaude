---
description: Job scheduling contract requiring exactly one of an interval (`every`)
  or wall-clock times (`at`), with weekday filtering reserved for `at` schedules.
visibility: public
---

# Job Schedule Contract — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

A job declares WHEN it runs through the `when` schedule block carried inside
the job schedule entry (held under the project overlay's `jobs` mapping). The
contract enforces a strict XOR on `when`: exactly one of `every` (an interval
expressed as `<number><m|h|d>` with a minimum of one minute) OR `at` (a single
`HH:MM` string or a list of them, each validated against 00–23 hours and 00–59
minutes) must be set. The `weekdays` filter is only meaningful for wall-clock
schedules and is rejected when `at` is absent. `when` is the sole scheduling
contract: a job declaration carries no legacy schedule or preferred-timing
fields. The job's execution model — which pointer it carries, global-registry
declaration, and the per-project enable overlay — is specified in
`project/spec/feature/config/job-declaration-model`. The contract is enforced at
YAML load time by schema validators; an ill-formed entry fails the project
config load outright rather than producing a silently misscheduled job.

## Canonical fields

### Use cases

#### UC-CFG-JOB-1: Interval schedule with valid duration accepted

```
Given a project config under load with jobs.my-job.when.every = "10m"
When the `when` block's interval validator runs
Then the regex ^(\d+)([mhd])$ matches with value 10 and unit "m"
And the integer 10 is >= 1
And the value is returned unchanged
And validate_mode confirms exactly one of (every, at) is set
And the `when` schedule block is accepted
```

#### UC-CFG-JOB-2: Interval schedule with malformed duration rejected

```
Given a project config under load with jobs.my-job.when.every = "5s"
When the `when` block's interval validator runs
Then the regex ^(\d+)([mhd])$ does NOT match (only m|h|d units are allowed)
Then a validation error is raised with the message:
  "Invalid duration format: 5s. Expected format: <number><m|h|d> (e.g., '10m', '2h', '1d')"
And the project config load raises before the job is registered
```

#### UC-CFG-JOB-3: Interval schedule with sub-minute duration rejected

```
Given a project config under load with jobs.my-job.when.every = "0m"
When the `when` block's interval validator runs
Then the regex matches with value 0 and unit "m"
And the integer 0 is < 1
And a validation error is raised with the message:
  "Duration must be at least 1 minute, got: 0m"
```

#### UC-CFG-JOB-4: Wall-clock schedule with single time accepted

```
Given a project config under load with jobs.my-job.when.at = "09:00"
When the `when` block's time validator runs
Then the regex ^(\d{2}):(\d{2})$ matches with hour 9 and minute 0
And the hour is within 0..23 and the minute is within 0..59
And the value is returned unchanged
And validate_mode confirms exactly one of (every, at) is set
And the `when` schedule block is accepted
```

#### UC-CFG-JOB-5: Wall-clock schedule with list of times accepted

```
Given a project config under load with jobs.my-job.when.at = ["09:00", "14:30", "22:15"]
When the `when` block's time validator runs
Then each entry is validated independently against ^(\d{2}):(\d{2})$
And all entries pass hour 0..23 and minute 0..59 checks
And the list is returned unchanged
```

#### UC-CFG-JOB-6: Wall-clock schedule with malformed time rejected

```
Given a project config under load with jobs.my-job.when.at = "9:00"
When the `when` block's time validator runs
Then the regex requires two-digit hour and minute and does NOT match
Then a validation error is raised with the message:
  "Invalid time format: 9:00. Expected format: HH:MM (e.g., '09:00', '14:30')"
```

#### UC-CFG-JOB-7: Wall-clock schedule with out-of-range hour rejected

```
Given a project config under load with jobs.my-job.when.at = "24:00"
When the `when` block's time validator runs
Then the regex matches but the hour 24 is outside 0..23
Then a validation error is raised with the message:
  "Invalid hour in 24:00: must be 00-23"
```

#### UC-CFG-JOB-8: Wall-clock schedule with out-of-range minute rejected

```
Given a project config under load with jobs.my-job.when.at = "09:60"
When the `when` block's time validator runs
Then the regex matches but the minute 60 is outside 0..59
Then a validation error is raised with the message:
  "Invalid minute in 09:60: must be 00-59"
```

#### UC-CFG-JOB-9: Both `every` and `at` set is rejected

```
Given a project config under load with jobs.my-job.when.every = "10m"
And jobs.my-job.when.at = "09:00"
When the `when` block's mode validator runs
Then both `every` and `at` are set
Then a validation error is raised with the message:
  "Specify exactly one of 'every' or 'at'"
```

#### UC-CFG-JOB-10: Neither `every` nor `at` set is rejected

```
Given a project config under load with jobs.my-job.when present but with no every and no at
When the `when` block's mode validator runs
Then both `every` and `at` are absent
Then a validation error is raised with the message:
  "Specify exactly one of 'every' or 'at'"
```

#### UC-CFG-JOB-11: `weekdays` without `at` is rejected

```
Given a project config under load with jobs.my-job.when.every = "1h"
And jobs.my-job.when.weekdays = ["mon", "fri"]
When the `when` block's mode validator runs
Then `weekdays` is present but `at` is absent
Then a validation error is raised with the message:
  "'weekdays' requires 'at'"
```

#### UC-CFG-JOB-12: `weekdays` with `at` is accepted

```
Given a project config under load with jobs.my-job.when.at = "09:00"
And jobs.my-job.when.weekdays = ["mon", "tue", "wed", "thu", "fri"]
When the `when` block's mode validator runs
Then both `weekdays` and `at` are present
Then the `when` schedule block is accepted
```

#### UC-CFG-JOB-13: A declared job requires a `when` schedule

```
Given a project config under load with a local job declaration that omits `when`
When the job config validation runs
Then a validation error is raised naming the job
And the job is not registered with an absent schedule
```

#### UC-CFG-JOB-14: Surviving execution-config fields default appropriately

```
Given a project config under load with jobs.my-job carrying a `when` block and one execution pointer
When JobScheduleConfig is constructed
Then category defaults to "subscription"
And agent defaults to "claude"
And thinking_mode defaults to "fast"
And timeout defaults to None
And the unset execution pointer (script or job) defaults to None
```

### Cross-context references

- Consumed by the scheduling bounded context that polls per-project jobs
  to dispatch them at the declared cadence. The scheduler reads
  `when.every` / `when.at` / `when.weekdays` directly.
- Subscriptions reference jobs by slug (see `subscription-routing.md`)
  and may carry their own `when` override on the subscription side; the
  contract enforced here applies identically to the subscription-side
  override.

## Allowed values

- `when.every` — string matching `^(\d+)([mhd])$` where the leading integer is `>= 1`. Units: `m` (minutes), `h` (hours), `d` (days). Example: `"10m"`, `"2h"`, `"1d"`.
- `when.at` — `HH:MM` string (two-digit hour 00–23, two-digit minute 00–59) OR a list of such strings.
- `when.weekdays` — list of `"mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun"`. Only valid when `at` is set.
- `category` — `"subscription" | "system"`. Default: `"subscription"`.

## Known caveats

- **Validation runs on every load.** A `teleclaude.yml` edited out-of-band to violate the XOR rule fails the next project-config load; the runtime refuses to load a project whose `jobs` block is malformed.
- **Unit floor is one minute, but unit choice is unconstrained.** A literal `"525600m"` is accepted even though `"1y"` would be more readable; the regex permits only m/h/d so a "year" unit is unrepresentable.
- **Weekday rule is one-directional.** Empty `weekdays` is always accepted (treated as "no day filter"). The rule fires only when `weekdays` is non-empty AND `at` is missing.
- **`when` is required for a declaration, not for an enable overlay.** A local or global job declaration must carry a `when` block; a per-project enable overlay (a `jobs` entry that only toggles a global job) carries no schedule and inherits the global declaration's cadence.
- **Unknown job-entry keys surface as warnings.** A removed legacy field or a misspelled key in a job schedule entry is surfaced through the recursive unknown-key warning walk (`project/spec/feature/config/unknown-key-warning`) and drives no scheduling or execution decision, consistent with `project/spec/feature/config/job-declaration-model#uc-jdm-10`. The `when` block itself still accepts unrecognized sub-keys silently — that narrower gap is unchanged here.
