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

Jobs are declarable at two tiers. A **global job** is declared once in the global
config's `jobs` registry and is available to every project. A **project** declares
its own **local jobs** under the project overlay's `jobs` mapping, and turns a
global job on or off through an **enable overlay** — an entry under the project's
`jobs` mapping keyed by the global job's name that carries only an `enabled` flag.
A global job is inactive in a project until that project enables it; a local job
(a name not present in the global registry) is active wherever it is declared.

The enable overlay may only toggle a global job on or off. An overlay entry whose
name collides with a global job but carries any identity-bearing field (a pointer,
a schedule, or an execution setting) is an attempt to redefine the global job and
fails the config load — a project can enable or disable a global job, never
reshape it.

The scheduling contract is the `when` block alone (see
`project/spec/feature/config/job-schedule-contract`); a declaration carries no
legacy schedule or preferred-timing fields, no execution-class discriminator, and
no agent-prompt override field. A declaration still in possession of a removed
field surfaces through the standard unknown-key warning rather than driving any
behavior.

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
And the project overlay carries a `jobs` entry of the same name with enabled = true and no other field
When the effective job set for the project is composed
Then the global job IS in the project's effective job set
And it runs with the global declaration's pointer and schedule
```

#### UC-JDM-7: Project disables a global job through the overlay

```
Given a global job that the project would otherwise run
And the project overlay carries a `jobs` entry of the same name with enabled = false
When the effective job set for the project is composed
Then the global job is NOT in the project's effective job set
```

#### UC-JDM-8: Identity-hijack overlay rejected at load

```
Given a job declared under the global config `jobs` registry
And the project overlay carries a `jobs` entry of the same name that also carries an identity-bearing field (a pointer, a schedule, or an execution setting)
When the config is loaded
Then the load fails with an error naming the job
And the global job's identity is never overridden by the project entry
```

#### UC-JDM-9: Local job declared by a project

```
Given a project overlay `jobs` entry whose name is NOT present in the global registry
And the entry carries exactly one pointer and a `when` schedule
When the config is loaded
Then the declaration is accepted as a local job
And it is in the project's effective job set without any global registration
```

#### UC-JDM-10: Removed field does not drive behavior

```
Given a job declaration still carrying a removed field (an execution-class discriminator, a legacy schedule or preferred-timing field, or an agent-prompt override)
When the config is loaded
Then the removed field is treated as an unknown key and surfaced as a warning
And the field drives no scheduling or execution decision
```

## Known caveats

- The enable overlay reuses the project overlay's `jobs` mapping rather than a
  separate surface, so cross-project consumers that ask "which projects carry job
  X" continue to find an enabled global job by its presence under the project's
  `jobs` mapping.
- A global job runs in a project only on explicit opt-in; there is no
  enabled-everywhere default.
