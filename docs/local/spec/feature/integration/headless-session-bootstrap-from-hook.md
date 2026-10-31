---
description: 'When an agent_session_start hook arrives for a session the integration service has never seen, the dispatcher creates a headless session record inline from the hook payload before continuing normal event dispatch.'
visibility: 'public'
---

# Headless Session Bootstrap from Hook — Spec

## What it is

The hook outbox dispatcher's explicitly authorized, just-in-time session
creation path. The receiver authorizes bootstrap only after proving that the
hook has neither a TeleClaude session identity marker nor tmux attachment. When
the dispatcher claims such an agent-session-start entry and the sessions store
does not contain its TeleClaude id, it synthesizes a create-session command from
the hook payload and creates the session record before continuing dispatch.
An unknown session-start without receiver-owned headless authorization is
dropped rather than interpreted as permission to create a row.
An event other than an authorized agent-session-start never creates an unknown
session; it is ignored without dispatch.
Session identity follows the terminal-resolved caller: a registered person keeps
their current identity and role; when no person resolves, the new session runs
under the computer's operator, `system:operator`, with no person role
(`local/projects/teleclaude/spec/identity-and-auth` §3). What that session may
run is decided by `local/projects/teleclaude/spec/feature/identity/command-clearance`.

The bootstrap is "headless" because the resulting session has no live
supervised process — only a record. The agent CLI was already running
when the hook fired; the integration service catches up by recording
the session's existence after the fact. This makes agent CLIs invoked
outside the platform's launch flow (manual `claude`, `codex`, `gemini`
invocations from a terminal) observable as TeleClaude sessions.

## Canonical fields

### Use cases

#### UC-HB1: A person brings a manually started agent into TeleClaude

```gherkin
Scenario: Recognize a manually started agent from an adopted project
  Given a person manually starts a supported agent from an authenticated terminal in an adopted project
  When TeleClaude recognizes the running agent
  Then a session for that project appears in TeleClaude
  And the running agent continues its work outside TeleClaude's launch flow

Scenario: Recognize a manually started agent from a project worktree
  Given a person manually starts a supported agent from a registered project's linked worktree
  When TeleClaude recognizes the running agent
  Then the session appears under its registered project and shows the branch from which the agent is working
```

#### UC-HB2: Non-session-start event for unknown session is dropped

#### UC-HB3: A person uses a manually started agent outside registered projects

```gherkin
Given a person manually starts a supported agent from a directory outside every registered project or home
When TeleClaude recognizes the running agent
Then the session appears without a project association
And project-scoped behavior does not apply to it
```

#### UC-HB4: Caller email role assignment

#### UC-HB5: Worktree subdir captured from cwd

#### UC-HB6: SESSION_STARTED event fires after creation

#### UC-HB7: Creation failure raises and triggers retry

#### UC-HB8: Unknown managed-descendant start cannot bootstrap

#### UC-HB9: An agent another application started works under the computer's operator

```gherkin
Scenario: Recognize an agent another application started
  Given another application on the computer starts a supported agent with no terminal login
  When TeleClaude recognizes the running agent
  Then a session for that agent appears in TeleClaude under the computer's operator
```

### Cross-context references

- Belongs (in v2) to `agent_runtime` along with the session aggregate.
  Bootstrap remains a property of session creation, not of integration.
- Reads identity context (caller email) via the auth subsystem;
  resolution rules live in `identity`.
- Reads the project registry's entries from `config` (`local/projects/teleclaude/spec/feature/config/project-registry`).
- Publishes a session-started event with cluster visibility; downstream
  consumers include the API server, frontends, and any notification
  dispatcher.

## Known caveats

- The native session id is captured at bootstrap time but the session
  record is not yet linked to a supervised process — `agent_runtime`
  cannot reattach to a manually started agent CLI after the fact.
- Codex sub-agent transcripts are filtered earlier (the receiver drops
  subagent events pre-resolution); they never reach this bootstrap.

- Caller email resolves from the live per-TTY login of the process's own
  terminal, else of its nearest terminal-bearing ancestor, else — while
  exactly one person is registered — from that person. When none of these
  answers, the bootstrap builds the command under the operator principal with
  no human role.

- The headless project-context resolver returns (none, none) for any
  cwd not under a project registry entry; the session is still
  created, just without a project association.
- The bootstrap path is taken once per session; subsequent hooks for
  the same session id find the record and skip directly to normal
  dispatch.

- Headless-bootstrap authorization is internal enrichment stamped after raw
  payload normalization. The receiver removes or overwrites any provider field
  with the same name, so external hook input cannot grant creation authority.

- A bootstrap that session creation refuses — the entry's identity or
  placement is not admitted — is dropped without retry
  (`local/projects/teleclaude/spec/feature/integration/hook-outbox-dispatcher`,
  UC-D8b). Any other bootstrap failure retries with the dispatcher's
  exponential backoff, with no attempt limit.
