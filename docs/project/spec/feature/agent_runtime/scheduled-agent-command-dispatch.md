---
description: Scheduled agent jobs enter the canonical command-session dispatch contract
  and receive authenticated job-runner identity.
---

# Scheduled Agent Command Dispatch — Spec

## What it is

<!-- planned-change:job-name-identity -->
A scheduled agent job starts through the same command-session dispatch contract as every other dispatched command. The scheduler supplies the job's identity — the procedure snippet ID its declaration points at — to the daemon-owned run boundary; that boundary finds the declaration carrying that pointer in the project's composed effective job set (a local declaration, or a published global declaration overlaid by that project's subscription), derives the job session, prepares the runtime-specific command input, and creates the session with the job-runner role. The boundary hands the declaration's agent preference list to automatic dispatch as the candidate order; it never fixes one agent. Session bootstrap then issues the job session's system-principal credential through the standard identity lifecycle.
<!-- change:job-name-identity -->
A scheduled agent job starts through the same command-session dispatch contract as every other dispatched command. The scheduler supplies the job's identity — its declared name — to the daemon-owned run boundary; that boundary finds the declaration carrying that name in the project's composed effective job set (a local declaration, or a published global declaration overlaid by that project's subscription), derives the job session from the procedure snippet ID its `job` pointer carries, prepares the runtime-specific command input, and creates the session with the job-runner role. The boundary hands the declaration's agent preference list to automatic dispatch as the candidate order; it never fixes one agent. Session bootstrap then issues the job session's system-principal credential through the standard identity lifecycle.
<!-- /planned-change:job-name-identity -->

Job configuration remains owned by the configuration context. A scheduler cannot redefine the configured agent preference, thinking mode, job procedure, or role through an alternate creation contract.

## Canonical fields

### Use cases

#### UC-SACD1:

```gherkin
Given a configured agent job is due
When the scheduler dispatches the job
Then the job starts through the canonical command-session dispatch contract
And the created session carries the configured job identity and job-runner role
And session bootstrap issues the session's system-principal credential
```

#### UC-SACD2:

<!-- planned-change:job-name-identity -->
```gherkin
Given a configured agent job is dispatched to any enabled agent runtime
When the new session receives its first instruction
Then the instruction is prepared through the shared command-loading mechanism
And it identifies the job by its procedure snippet ID, the value its declaration carries
And the runtime does not receive an unrecognized native command
```
<!-- change:job-name-identity -->
```gherkin
Given a configured agent job is dispatched to any enabled agent runtime
When the new session receives its first instruction
Then the instruction is prepared through the shared command-loading mechanism
And it identifies the job by its declared name
And it names the procedure snippet ID the declaration's `job` pointer carries
And the runtime does not receive an unrecognized native command
```
<!-- /planned-change:job-name-identity -->

#### UC-SACD3:

```gherkin
Given a scheduled job names no valid agent-job contract
Or the command-loading contract required to start it is unavailable
When dispatch is attempted
Then dispatch is refused before a session is created
And no alternate session-creation path or raw runtime command is used as fallback
```
