---
visibility: 'public'
description: 'Onboarding dispatches at most one live analysis or assessment session per project or company root, resolving the holder from the session record and failing closed when liveness cannot be established.'
delivered_by:
  - command-loader-and-title-cutover
---

# Onboarding Dispatch Dedup — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Project and company onboarding each dispatch worker sessions that analyse a
root and assess its configuration. Both are expensive and both are idempotent
in intent but not in cost, so onboarding admits at most one live session per
`(root, command)` subject before dispatching another.

The holder is resolved from the session record: an open session whose project
path is that root and whose recorded command is the one about to be dispatched.
Liveness that cannot be established is treated as held rather than free, so an
unreadable or ambiguous state suppresses the dispatch instead of duplicating it.

Project onboarding owns the shared resolution; company onboarding consumes it
through that published function rather than restating the rule.

## Canonical fields

### Use cases

#### UC-ODD1: A live holder suppresses a second dispatch

```gherkin
Given an open session whose project path is the target root
And whose recorded command is the analysis command about to be dispatched
When onboarding resolves whether to dispatch
Then it reports the subject held and dispatches no second session
```

#### UC-ODD2: A different command on the same root is not a holder

```gherkin
Given an open session whose project path is the target root
And whose recorded command is a different command that shares a leading token with the one about to be dispatched
When onboarding resolves whether to dispatch
Then that session does not hold the subject
And the dispatch proceeds
```

#### UC-ODD3: A same command on a different root is not a holder

```gherkin
Given an open session whose recorded command is the one about to be dispatched
And whose project path is a different root
When onboarding resolves whether to dispatch
Then that session does not hold the subject
And the dispatch proceeds
```

#### UC-ODD4: Indeterminate liveness fails closed

```gherkin
Given onboarding cannot establish whether a candidate holder is open
When it resolves whether to dispatch
Then it treats the subject as held
And dispatches no session
```

#### UC-ODD5: Company onboarding consumes the project-owned resolution

```gherkin
Given company onboarding is about to dispatch its analysis command for a company root
When it resolves whether to dispatch
Then it uses the same published resolution project onboarding uses
And it restates none of the subject, liveness, or fail-closed rules locally
```

## Known caveats

- The subject is `(root, command)`, not `(root, job)`. A single job value can
  cover several commands, so a job-keyed resolution would let one worker hold a
  subject that belongs to a different command.

## See Also

- docs/project/spec/feature/agent_runtime/run-session-with-command.md — the dispatch door that records the command this resolution reads.
