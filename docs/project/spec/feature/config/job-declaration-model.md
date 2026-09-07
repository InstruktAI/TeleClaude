---
description: Declarative job model — a job is declared by config pointing at exactly one execution target (a `script` entrypoint or a `job` procedure), schedulable global jobs live in a global registry, and a project turns a global job on or off through a validated enable overlay that cannot redefine the global job's identity.
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

Jobs are declarable at two tiers. A **global job** is declared once in the global
config's `jobs` registry and is available to every project. A **project** declares
its own **local jobs** in the project overlay's `jobs` list, and turns a global
job on or off through an **enable overlay** — an entry in the project's `jobs`
list carrying the global job's execution pointer, an `enabled` flag, and
optionally its own `agent` preference list. A global job is inactive in a
project until that project enables it; a local job (a pointer not present in the
global registry) is active wherever it is declared. Which kind an entry is comes
from its pointer alone: an entry whose pointer matches a global registry
declaration is an overlay, any other entry is a local declaration. A tier
carries at most one entry per pointer; a duplicate pointer fails the load
naming it.

The enable overlay may toggle a global job on or off and may replace its agent
preference. An overlay entry whose pointer matches a global job but carries any
identity-bearing field (a schedule, or an execution setting other than `agent`)
is an attempt to redefine the global job and fails the config load — a project
can enable or disable a global job and choose who runs it, never reshape it.

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

The effective job set the runner executes for a workspace is the project's local
jobs plus every global job the project's overlay enables.

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

#### UC-JDM-6: Project enables a global job through the overlay

```
Given a job declared under the global config `jobs` registry
And the project overlay carries a `jobs` entry with the same execution pointer, enabled = true, and no other field
When the effective job set for the project is composed
Then the global job IS in the project's effective job set
And it runs with the global declaration's pointer and schedule
```

#### UC-JDM-7: Project disables a global job through the overlay

```
Given a global job that the project would otherwise run
And the project overlay carries a `jobs` entry with the same execution pointer and enabled = false
When the effective job set for the project is composed
Then the global job is NOT in the project's effective job set
```

#### UC-JDM-8: Identity-hijack overlay rejected at load

```
Given a job declared under the global config `jobs` registry
And the project overlay carries a `jobs` entry with the same execution pointer that also carries an identity-bearing field (a schedule, or an execution setting other than `agent`)
When the config is loaded
Then the load fails with an error naming the job
And the global job's identity is never overridden by the project entry
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

#### UC-JDM-13: An enable overlay may replace the agent preference

```
Given a global job declaring agent = [a, b]
And a project overlay carrying the same pointer, enabled = true, and agent = [b]
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

## Known caveats

- The enable overlay reuses the project overlay's `jobs` list rather than a
  separate surface, so a cross-project consumer that asks "which projects run
  job X" consults each project's composed effective job set by identity; a
  project's raw overlay entries are never read as membership.
- A pre-declarative `jobs` document — a name-keyed mapping, a scalar `agent`, or
  a removed field — is rewritten to the current shape at the config load
  boundary and persisted, so an overlay written before this contract loads to
  the current shape without an operator edit.
- A global job runs in a project only on explicit opt-in; there is no
  enabled-everywhere default.
