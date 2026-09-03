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

The bootstrap is "headless" because the resulting session has no live
supervised process — only a record. The agent CLI was already running
when the hook fired; the integration service catches up by recording
the session's existence after the fact. This makes agent CLIs invoked
outside the platform's launch flow (manual `claude`, `codex`, `gemini`
invocations from a terminal) observable as TeleClaude sessions.

## Canonical fields

### Use cases

#### UC-HB1: Manual agent invocation registers a headless session

```gherkin
Given a user runs `claude` manually in /Users/me/work/myproject
And the user is authenticated via the platform's session auth in this TTY
And Claude invokes the receiver with a SessionStart event from /Users/me/work/myproject
And the integration service has no session record for this native session
When the dispatcher claims the agent-session-start outbox entry
Then the dispatcher detects the session is unknown
And the event type is agent-session-start
And the receiver-owned headless-bootstrap authorization is present
And the headless-bootstrap path runs
And it reads the native log file, native session id, agent name, and cwd from the hook payload
And the headless project-context resolver maps cwd to (project_path, subdir) using the configured trusted directories
And the current caller's email is resolved from the per-TTY auth state if any
And a create-session command is built with headless=true, the native binding fields, project context, terminal origin, and caller-email metadata
And the command service creates the record
And a session-started event is published with cluster visibility
And the dispatcher continues normal dispatch for the now-existing session
```

<!-- planned:external-session-identity -->
#### UC-HB6: An attested session-start mints the session and its root binding

```gherkin
Given an agent CLI the daemon did not launch emits an agent-session-start hook
And the receiver reaches the daemon over the local socket while still a descendant of the agent process
And the daemon attests the receiver's process instance and finds no already-registered root in its ancestry
And exactly one ancestor's executable identity is in the configured agent binary registry
When the bootstrap runs
Then the daemon mints the TeleClaude session id
And it persists that ancestor as the session's immutable root process binding
And it enqueues the hook event under the session it just minted
And the native session id is recorded as provider metadata that selects nothing
```

#### UC-HB7: A descendant session-start stays owned by the registered session

```gherkin
Given an agent-session-start hook whose attested ancestry already contains a registered root
When the bootstrap evaluates it
Then no session is minted
And the event is enqueued under the session that root already owns
```

#### UC-HB8: An unattestable session-start still becomes observable, without a binding

```gherkin
Given an agent-session-start hook whose live attested delivery does not reach the daemon
When the receiver falls back to the durable outbox write and the dispatcher bootstraps from that entry
Then the session record is created exactly as it is today
And it carries no root process binding
And a later session-scoped call from that process tree is refused rather than resolved
And no machine-global login identity is presented as that session's identity
```

<!-- /planned:external-session-identity -->
#### UC-HB2: Non-session-start event for unknown session is dropped

```gherkin
Given a tool-use outbox entry arrives for a session id the sessions store does not contain
And the event type is NOT agent-session-start
When the dispatcher evaluates the event
Then a debug log records "ignoring hook event for unknown session (not session_start)"
And the dispatch returns early without bootstrap
And the outbox entry is removed as processed (no retry)
```

#### UC-HB3: Untrusted cwd produces null project context

```gherkin
Given the hook cwd is a directory not under any configured trusted directory
When the headless project-context resolver runs
Then it returns (none, none)
And the create-session command is built with an empty project path
And the session is created without a project association
And subsequent hooks still update the record but no project-scoped behaviors (memory, person header) fire
```

#### UC-HB4: Caller email role assignment

```gherkin
Given the current caller's email resolves to "mo@example.com"
When the headless-bootstrap path builds the create-session command
Then origin metadata is a terminal origin carrying email="mo@example.com"
And the human role is left unset (allowing config role resolution)
Otherwise (no email): the human role defaults to the customer role
```

#### UC-HB5: Worktree subdir captured from cwd

```gherkin
Given the cwd is /Users/me/work/myproject/trees/feature-x
And /Users/me/work/myproject is a trusted directory
When the headless project-context resolver runs
Then project_path = "/Users/me/work/myproject", subdir = "trees/feature-x"
And the create-session command carries both
And the session record reflects the worktree branch
```

#### UC-HB6: SESSION_STARTED event fires after creation

```gherkin
Given the headless-bootstrap path successfully created a session record
When the bootstrap completes
Then a session-started event is published with cluster visibility
And downstream cluster consumers see the new session
And UI watchers, live agent-runtime state, and notification subscribers all observe the bootstrap
```

#### UC-HB7: Creation failure raises and triggers retry

```gherkin
Given the create-session command service fails to produce a session id
When the bootstrap attempts to load the session record by the returned id
And the sessions store yields nothing
Then a value error "headless session creation returned missing session: ..." is raised
And the dispatcher's retryable-error classifier returns true (the message does NOT contain "not found")
And the entry is rescheduled with exponential backoff
```

#### UC-HB8: Unknown managed-descendant start cannot bootstrap

```gherkin
Given an agent-session-start entry addresses a session id absent from the sessions store
And the entry does not carry receiver-owned headless-bootstrap authorization
When the dispatcher evaluates the unknown session
Then it records that bootstrap authority is absent
And returns without creating a session row
And provider-supplied data cannot opt into headless bootstrap
```

### Cross-context references

- Belongs (in v2) to `agent_runtime` along with the session aggregate.
  Bootstrap remains a property of session creation, not of integration.
- Reads identity context (caller email) via the auth subsystem;
  resolution rules live in `identity`.
- Reads the trusted-directory set from `config`.
- Publishes a session-started event with cluster visibility; downstream
  consumers include the API server, frontends, and any notification
  dispatcher.

## Known caveats

- The native session id is captured at bootstrap time but the session
  record is not yet linked to a supervised process — `agent_runtime`
  cannot reattach to a manually started agent CLI after the fact.
- Codex sub-agent transcripts are filtered earlier (the receiver drops
  subagent events pre-resolution); they never reach this bootstrap.
- Caller-email resolution order is: (1) per-TTY auth state if a TTY is
  detectable, then (2) global identity state as a fallback. Running the
  agent CLI in a subshell that loses TTY context falls through to the
  global identity state; only when both are absent does email
  resolution return nothing, in which case the bootstrap builds the
  command with the customer human role.
- The headless project-context resolver returns (none, none) for any
  cwd not under a configured trusted directory; the session is still
  created, just without a project association.
- The bootstrap path is taken once per session; subsequent hooks for
  the same session id find the record and skip directly to normal
  dispatch.

- Headless-bootstrap authorization is internal enrichment stamped after raw
  payload normalization. The receiver removes or overwrites any provider field
  with the same name, so external hook input cannot grant creation authority.

- Bootstrap failures retry with the dispatcher's exponential backoff;
  a stuck agent-session-start entry will eventually accumulate attempt
  counts and reach the dead-letter region of the configured backoff cap.
