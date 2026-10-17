---
description: Declarative job model — a job is declared by config under a required
  name and points at exactly one execution target (a `script` entrypoint or a `job`
  procedure), the mother project publishes global jobs in a global registry, a side
  project subscribes to one by name with its own overrides, and the runner runs every
  subscribed job inside the subscribing project.
---

# Job Declaration Model — Spec

## What it is

A recurring job is declared entirely by config. Every declaration carries a
`name`, and the name is the job's one identity: dispatch, run state, the run
directory, the structured report, the runner's job filter, the jobs API, and the
runner's log records all name the job by it, and nothing computes a second
identity from anything else. A name is lowercase kebab-case
(`[a-z0-9]+(-[a-z0-9]+)*`); a declaration without a name, or with a malformed
one, fails the config load naming the offending entry. A name is never derived
from the execution pointer, the job module, or any other field. `jobs` is a list
of declarations at every tier, never a name-keyed mapping.

The execution class is read from which pointer the declaration carries —
`script` (an in-process entrypoint module) or `job` (a procedure handed to an
agent) — with no separate execution-class discriminator field. A published or
local declaration carries exactly one of the two pointers; one carrying both, or
neither, fails the config load naming the job. The pointer says only what runs:
one pointer may back several differently named jobs. A `script` pointer names a
job module relative to the project root. A `job` pointer is a procedure's
qualified snippet ID — the same identity from every location — and must resolve to a
delivered procedure snippet at config load; an unknown ID, a non-procedure
snippet, or a brand-new procedure with no delivered body fails the load naming
the job and the pointer. A delivered procedure remains executable when a
replacement or addition is pending; execution uses its current body, not the
pending material. The lookup has no exception for the declaration's delivering
slug.

Jobs are declarable at two tiers. A **global job** is published once in the
global config's `jobs` registry with its default schedule and execution settings
and is available to every project. A project gets nothing by default. It
**subscribes** to a global job by adding an entry to its own `jobs` list that
carries the global job's name; from then on the job runs in that project on that
project's terms. The subscribing entry need not repeat the execution pointer; an
entry carrying a published job's name with a different pointer fails the load
naming the job. The subscribing entry overrides whatever else it sets — `when`,
`agent`, `thinking_mode`, `timeout`, `category` — and falls back to the published
defaults for what it leaves unset. It unsubscribes by removing the entry or
setting `enabled: false`. The name is the subscription key; nothing validates
what a project may override. An entry whose name the registry does not carry is
a **local job**, active wherever it is declared. Which kind an entry is comes
from its name alone. A tier carries at most one entry per name; a duplicate name
fails the load naming it. The same name in different projects remains
independent.

An effective agent job's `agent` field is a non-empty ordered preference list.
A subscription may inherit that list from its published declaration. A missing
or empty effective list fails configuration validation; it never selects a
code-owned job order. A single declared agent is a one-entry list. The run boundary
launches the job in automatic dispatch mode with that list as the candidate
order, with no candidates appended from a command matrix. The agent-runtime
resolver applies its own eligibility rules: an
agent that is unconfigured, disabled, degraded, or operator-unavailable is
skipped and the next candidate is tried. Agent preference is execution
preference, not identity. When every candidate is ineligible the run closes as
failed, carrying the resolver's refusal reason, through the runner's normal
failed-run notification. Job configuration carries no availability data of its
own.

The scheduling contract is the `when` block alone (see
`local/projects/teleclaude/spec/feature/config/job-schedule-contract`); a declaration carries no
legacy schedule or preferred-timing fields, no execution-class discriminator, and
no agent-prompt override field. Job declarations are validated as stored: a
mapping-valued `jobs` block, a scalar `agent`, or an unknown field is refused.
No job-entry rewrite runs at load.

A project's effective job set is its local jobs plus every global job it
subscribes to, each resolved as the published declaration overlaid by the
subscribing entry. The runner walks every registered project, composes that
project's effective set, runs what is due inside that project, and keeps run
state and run records per project and job name.

## Canonical fields

### Use cases

#### UC-JDM-1: Script pointer declares a script job

```
Given an operator wants a scheduled task to run as a script job
When they declare that job for a project
Then the job is available to run on its declared schedule
```

#### UC-JDM-2: Job pointer declares an agent job

```
Given an operator wants a scheduled task to run as an agent job
When they declare a delivered procedure for that job
Then the job is available for agent dispatch on its declared schedule
```

#### UC-JDM-3: Declaration with both pointers rejected

#### UC-JDM-4: Declaration with neither pointer rejected

#### UC-JDM-5: Global job declared in the global registry

#### UC-JDM-6: Project subscribes to a global job

```
Given an operator wants a project to run a job published globally
When they subscribe that project to the job
Then the job is available to run in that project using its published defaults
```

#### UC-JDM-7: Project unsubscribes from a global job

```
Given an operator wants a project to stop running a subscribed global job
When they disable that project's subscription
Then the job is no longer available to run in that project
```

#### UC-JDM-8: Subscription overrides the published settings

```
Scenario: Change a subscribed job's schedule
  Given an operator wants a project to use a different schedule for a published job
  When they override the schedule in that project's subscription
  Then the job uses the project's schedule without changing other projects

Scenario: Change a subscribed job's agent preference
  Given an operator wants a project to prefer a different eligible agent for a published agent job
  When they override the agent preference in that project's subscription
  Then the job uses that preference without changing other projects
```

#### UC-JDM-9: Local job declared by a project

```
Given an operator wants a scheduled job that is local to a project
When they declare the job in that project's configuration
Then it is available to run in that project without a global subscription
```

#### UC-JDM-11: Job pointer must resolve to a delivered procedure

#### UC-JDM-25: A job's pointer must name a usable entry procedure

#### UC-JDM-12:

#### UC-JDM-13: A subscription may replace the agent preference

#### UC-JDM-14:

#### UC-JDM-16: A job's identity is its declared name

#### UC-JDM-17: Duplicate name within a tier is rejected

#### UC-JDM-18: A subscribed job runs inside the subscribing project

#### UC-JDM-20:

#### UC-JDM-21: The commit gate validates a project's jobs declaration

#### UC-JDM-22: A declaration without a valid name is rejected

#### UC-JDM-23: One execution pointer backs several named jobs

#### UC-JDM-24: A subscription cannot change the published pointer

## Known caveats

- A subscription is an ordinary entry in the project's `jobs` list rather than a
  separate surface, so anything that asks "which projects run job X" consults
  each project's composed effective job set by name; raw entries are never read
  as membership.
- A global job runs in a project only on that project's subscription; there is
  no subscribed-everywhere default.
- Run history is keyed by name, so renaming a job starts it fresh under the new
  name; nothing carries history across a rename.
- The sealed commit gate validates effective job declarations when a project's
  `teleclaude.yml` is in the commit path; other pathsets do not invoke this check.
- Legacy aggregate run state is migrated to a project-qualified identity only
  when its former runner project is known. Aggregate dispatch history remains
  separate, and history without a known project remains recoverable rather than
  being assigned to another project's run.
