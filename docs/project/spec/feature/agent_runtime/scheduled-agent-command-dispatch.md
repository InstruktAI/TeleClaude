---
description: Scheduled agent jobs enter the canonical command-session dispatch contract and receive authenticated job-runner identity.
delivered_by:
  - restore-canonical-agent-job-dispatch
---

# Scheduled Agent Command Dispatch — Spec

## What it is

A scheduled agent job starts through the same command-session dispatch contract as every other dispatched command. The scheduler supplies the configured job identity and authoritative job-spec identity to the daemon-owned run boundary; that boundary validates the job declaration, derives the job session, prepares the runtime-specific command input, and creates the session with the job-runner role. Session bootstrap then issues the job session's system-principal credential through the standard identity lifecycle.

Job configuration remains owned by the configuration context. A scheduler cannot redefine the configured agent, thinking mode, job specification, or role through an alternate creation contract.

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

```gherkin
Given a configured agent job is dispatched to any enabled agent runtime
When the new session receives its first instruction
Then the instruction is prepared through the shared command-loading mechanism
And it identifies both the job run and the authoritative job specification
And the runtime does not receive an unrecognized native command
```

#### UC-SACD3:

```gherkin
Given a scheduled job names no valid agent-job contract
Or the command-loading contract required to start it is unavailable
When dispatch is attempted
Then dispatch is refused before a session is created
And no alternate session-creation path or raw runtime command is used as fallback
```
