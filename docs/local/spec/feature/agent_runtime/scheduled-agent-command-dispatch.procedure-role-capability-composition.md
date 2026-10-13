---
description: Scheduled agent jobs enter the procedure-entry contract with their configured job identity and receive the role their procedure declares.
---

# Scheduled Agent Command Dispatch — Spec

## What it is

A scheduled agent job starts through the procedure-entry contract
(`local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry`) like
every other dispatched assignment. The scheduler supplies the job's identity —
its declared name — to the daemon-owned run boundary; that boundary finds the
declaration carrying that name in the project's composed effective job set (a
local declaration, or a published global declaration overlaid by that project's
subscription), resolves the entry procedure its `job` pointer names, and
creates the session carrying the role that procedure declares, with the job
name as its instance identity and the open run correlated to the session. The
boundary hands the declaration's agent preference list and thinking mode to
dispatch as the candidate order and mode; it never fixes one agent and never
unions the declaration with the procedure's own dispatch defaults. The brief
the session reads is the procedure's complete closure together with the
outcome-reporting instructions a job entry implies. Session bootstrap then
issues the job session's system-principal credential through the standard
identity lifecycle, and the session is standing whatever its role.

Job configuration remains owned by the configuration context. A scheduler
cannot redefine the configured agent preference, thinking mode or job procedure
through an alternate creation contract, and no job supplies a role: the role is
the procedure's.

## Canonical fields

### Use cases

#### UC-SACD1:

```gherkin
Given a configured agent job is due
When the scheduler dispatches the job
Then the job starts through the procedure-entry contract
And the created session carries the configured job identity and the role its procedure declares
And session bootstrap issues the session's system-principal credential
```

#### UC-SACD2:

```gherkin
Given a configured agent job is dispatched to any enabled agent runtime
When the new session receives its first instruction
Then the instruction is the loader naming the materialized brief for the job's procedure
And the brief identifies the job by its declared name and carries the reporting instructions a job entry implies
And the runtime does not receive an unrecognized native command
```

#### UC-SACD3:

```gherkin
Given a scheduled job names no valid agent-job contract
Or its procedure is not a published entry procedure declaring a role
When dispatch is attempted
Then dispatch is refused before a session is created
And no alternate session-creation path or raw runtime command is used as fallback
```
