---
description: Declarative job model — a job is declared by config pointing at exactly one execution target (a `script` entrypoint or a `job` procedure), the mother project publishes global jobs in a global registry, a side project subscribes to one with its own overrides, and the runner runs every subscribed job inside the subscribing project.
delivered_by:
  - generic-job-declarative-model
---

# Job Declaration Model — Spec

## What it is

A recurring job is declared entirely by config. Its execution class is read from
which pointer the declaration carries — `script` (an in-process entrypoint module)
or `job` (a procedure handed to an agent) — with no separate execution-class
discriminator field. A declaration carries exactly one of the two pointers; a
declaration carrying both, or neither, fails the config load.

The pointer is the job's identity, and a declaration carries no separate name:
`jobs` is a list of declarations at every tier, never a name-keyed mapping. A
`job` pointer is a procedure snippet ID — global-scope, current-project, or
slug-prefixed — and it is what dispatch, run state, the run directory, and the
structured report all use to name an agent job. A `script` pointer names a job
module relative to the project root, and that module's stem is the script job's
identity everywhere the job is named — run state, the run directory, and the
runner's job filter. A `job` pointer must resolve to a delivered procedure
snippet at config load; an unknown ID, a non-procedure snippet, or a procedure
pending for another delivery fails the load naming the job and the pointer.

Jobs are declarable at two tiers. A **global job** is published once in the
global config's `jobs` registry with its default schedule and execution settings
and is available to every project. A project gets nothing by default. It
**subscribes** to a global job by adding an entry to its own `jobs` list that
carries the global job's execution pointer; from then on the job runs in that
project on that project's terms. The subscribing entry overrides whatever it sets
— `when`, `agent`, `thinking_mode`, `timeout`, `category` — and falls back to the
published defaults for what it leaves unset. It unsubscribes by removing the entry
or setting `enabled: false`. The pointer is the subscription key and the only
thing a subscriber cannot change; nothing validates what a project may override,
because the job runs in that project alone. An entry whose pointer the registry
does not carry is a **local job**, active wherever it is declared. Which kind an
entry is comes from its pointer alone. A tier carries at most one entry per
pointer; a duplicate pointer fails the load naming it.

An agent job's `agent` field is an ordered preference list. The run boundary
launches the job in automatic dispatch mode with that list as the candidate
order, so the agent-runtime resolver applies its own eligibility rules: an
agent that is unconfigured, disabled, degraded, or operator-unavailable is
skipped and the next candidate is tried. Agent preference is execution
preference, not identity. When every candidate is ineligible the run closes as
failed, carrying the resolver's refusal reason, through the runner's normal
failed-run notification. Job configuration carries no availability data of its
own.

The scheduling contract is the `when` block alone (see
`project/spec/feature/config/job-schedule-contract`); a declaration carries no
legacy schedule or preferred-timing fields, no execution-class discriminator, and
no agent-prompt override field.
<!-- planned-change:config-schema-strictness -->
A declaration still in possession of a removed field surfaces through the
standard unknown-key warning rather than driving any behavior.
<!-- change:config-schema-strictness -->
A declaration still carrying a removed field fails at the project configuration
load boundary before it can drive behavior.
<!-- /planned-change:config-schema-strictness -->

A project's effective job set is its local jobs plus every global job it
subscribes to, each resolved as the published declaration overlaid by the
subscribing entry. The runner walks every registered project, composes that
project's effective set, runs what is due inside that project, and keeps run
state and run records per project and job.

## Canonical fields

### Use cases

#### UC-JDM-1: Script pointer declares a script job

```
Given a job declaration carrying a `script` pointer and no `job` pointer
When the config is loaded
Then the declaration is accepted
And the job is dispatched as a script (in-process) job
```

#### UC-JDM-2: Job pointer declares an agent job

```
Given a job declaration carrying a `job` pointer and no `script` pointer
When the config is loaded
Then the declaration is accepted
And the job is dispatched as an agent job
```

#### UC-JDM-3: Declaration with both pointers rejected

```
Given a job declaration carrying both a `script` pointer and a `job` pointer
When the config is loaded
Then the load fails with an error naming the job
And no execution class can be silently chosen for it
```

#### UC-JDM-4: Declaration with neither pointer rejected

```
Given a job declaration carrying neither a `script` pointer nor a `job` pointer
When the config is loaded
Then the load fails with an error naming the job
```

#### UC-JDM-5: Global job declared in the global registry

```
Given a job declared under the global config `jobs` registry
And a project whose overlay does not mention that job
When the effective job set for the project is composed
Then the global job is NOT in the project's effective job set
```

#### UC-JDM-6: Project subscribes to a global job

```
Given a job published under the global config `jobs` registry
And the project's `jobs` list carries an entry with the same execution pointer and enabled = true
When the effective job set for the project is composed
Then the global job IS in the project's effective job set
And every setting the subscribing entry leaves unset is the published default
```

#### UC-JDM-7: Project unsubscribes from a global job

```
Given a global job the project subscribes to
And the project's `jobs` list carries an entry with the same execution pointer and enabled = false
When the effective job set for the project is composed
Then the global job is NOT in the project's effective job set
```

#### UC-JDM-8: Subscription overrides the published settings

```
Given a job published in the global registry with when.at = "03:00"
And the project's `jobs` list carries an entry with the same execution pointer and when.every = "30m"
When the effective job set for the project is composed
Then the load succeeds
And the job runs in that project every 30 minutes
And the published declaration is unchanged for every other project
```

#### UC-JDM-9: Local job declared by a project

```
Given a project overlay `jobs` entry whose execution pointer is NOT declared in the global registry
And the entry carries exactly one pointer and a `when` schedule
When the config is loaded
Then the declaration is accepted as a local job
And it is in the project's effective job set without any global registration
```

#### UC-JDM-11: Job pointer must resolve to a delivered procedure

```
Given a job declaration whose `job` pointer names an unknown snippet ID, a snippet that is not a procedure, or a procedure pending for another delivery
When the config is loaded
Then the load fails with an error naming the job and the pointer
And no agent session can be dispatched for it
```

#### UC-JDM-12: Agent preference list resolves through availability

```
Given an agent job declaring agent = [a, b, c]
And agent a is disabled in the machine configuration or marked unavailable
And agent b is enabled and available
When the job is dispatched
Then the session is created on agent b
And the dispatch decision records that a was skipped as ineligible
```

#### UC-JDM-13: A subscription may replace the agent preference

```
Given a global job declaring agent = [a, b]
And the project's `jobs` list carries an entry with the same pointer, enabled = true, and agent = [b]
When the config is loaded and the job is dispatched in that project
Then the load succeeds
And the session is created on agent b
```

#### UC-JDM-14: An exhausted preference list fails the run loud

```
Given an agent job whose every declared agent is unconfigured, disabled, degraded, or unavailable
When the job is due and dispatch is attempted
Then no session is created
And the run is closed as failed with the resolver's refusal reason
And the failed-run event notifies a human
```

#### UC-JDM-10: Removed field does not drive behavior

```
Given a job declaration still carrying a removed field (an execution-class discriminator, a legacy schedule or preferred-timing field, or an agent-prompt override)
When the config is loaded
<!-- planned-change:config-schema-strictness -->
Then the removed field is treated as an unknown key and surfaced as a warning
And the field drives no scheduling or execution decision
<!-- change:config-schema-strictness -->
Then configuration loading fails before the job enters the effective job set
And the failure identifies the removed field's path
<!-- /planned-change:config-schema-strictness -->
```

#### UC-JDM-15: Pre-declarative jobs document is migrated forward at load

```
Given a project or global configuration whose `jobs` block is a name-keyed mapping, or whose entries carry a scalar `agent` or a removed field
When the configuration is loaded
Then the document is rewritten on disk to the list shape with a list-valued `agent` and no removed field
And the effective job set composed from the rewritten document is the one the mapping declared
And a later load finds nothing left to rewrite
```

#### UC-JDM-16: A script job's identity is its module stem

```
Given a script job declared with `script` pointing at a job module
When the job is dispatched, its run is recorded, and its run directory is written
Then every one of those names the job by the module's stem
And no declaration key or separate name participates
```

#### UC-JDM-17: Duplicate pointer within a tier is rejected

```
Given two entries in one tier's `jobs` list carrying the same execution pointer
When the config is loaded
Then the load fails with an error naming the pointer
And neither entry enters the effective job set
```

#### UC-JDM-18: A subscribed job runs inside the subscribing project

```
Given two registered projects that both subscribe to the same global job
When the runner walks the registered projects
Then each project's due run is opened, executed, and closed under that project — an agent session rooted at that project, a script job told which project it runs in
And run state and run records are kept per project and job, so one project's run never closes or blocks the other's
```

## Known caveats

- A subscription is an ordinary entry in the project's `jobs` list rather than a
  separate surface, so anything that asks "which projects run job X" consults
  each project's composed effective job set by identity; raw entries are never
  read as membership.
- A pre-declarative `jobs` document — a name-keyed mapping, a scalar `agent`, or
  a removed field — is rewritten to the current shape at the config load
  boundary and persisted, so an overlay written before this contract loads to
  the current shape without an operator edit.
- A global job runs in a project only on that project's subscription; there is
  no subscribed-everywhere default.
