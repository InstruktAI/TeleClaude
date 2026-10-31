---
description: "Report the caller's identity via `telec auth whoami`."
visibility: 'public'
---

# Whoami Resolution — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

`telec auth whoami` is the operator-facing question "who does the system think I am?". The CLI answers it in its own process from the identity context's shared caller resolution (`local/projects/teleclaude/spec/identity-and-auth` §6) — the same resolution every caller-dependent command applies — and sends no request to the daemon. Inside a session — one whose TMPDIR holds a session identity document — it prints the Principal and Role the session's record resolves to, and never reads the terminal login; a document that is present but identifies no open session on this computer is reported as carrying no usable identity. Outside any session it prints the Email and Role of the person the terminal's login names, followed by the TTY and the login document's path. A caller outside any session for which no login names anyone is the computer's operator (`local/projects/teleclaude/spec/identity-and-auth` §2): whoami prints its Principal, `system:operator`, with no Role, TTY or login document, and succeeds with or without a terminal. The Role is the one that authorizes the caller: a person's effective role at the scope of the project the command runs in (`local/projects/teleclaude/design/architecture/scoped-roles`), or a system caller's system role as derived from its session record. The CLI accepts a conversational alias — `telec auth who am i` — that rewrites to `telec auth whoami`.

The identity context's whoami capability answers the same question for clients of the daemon's API. It answers from the identity the request carries. The daemon has no invocation directory, so it reads a person's Role for the project of the caller's session, and at platform scope for a caller with no session (`local/projects/teleclaude/design/architecture/scoped-roles`). Its answer therefore agrees with the CLI's for a session invoking inside its own project and for a terminal outside any registered project. The API response includes email for a resolved person and `session_id` only for a session caller; it also carries the resolved `person_slug` used by the TUI to scope person configuration and the recorded `config_subject` when available. An unidentifiable caller has no principal, role, or email.

Inside a session it also prints the session's company context, which is how a tool running in the session — in any language — reads it. The CLI resolves that context in its own process from the session record the identity document's session id names, together with the person's company memberships (`local/projects/teleclaude/spec/feature/agent_runtime/company-scoped-session-context`); the document itself carries no company fact. The Principal line already tells human-directed work (`human:`) from system-principal work (`system:`), so the company context adds one line: the resolved company, `none` when the session has no company, or `ambiguous` with the eligible companies and how to select one. Outside a session there is no session company, and no Company line is printed.

## Canonical fields

### Use cases

#### UC-WHO1: A system session reports its principal and system role

#### UC-WHO2: An operator inspects the identity used by the current context

```gherkin
Scenario: Inspect the identity used by the current context
  Given the operator is using a registered terminal login or an open session
  When they run `telec auth whoami`
  Then the result identifies the person or principal and the role that applies to this interaction

Scenario: An unrecognized terminal is told how to establish identity
  Given the terminal login cannot be resolved to a registered person
  When the operator runs `telec auth whoami`
  Then the command reports that no identity is established for the current TTY and tells the operator to log in
  And the command exits successfully

Scenario: A caller nothing identifies is reported as the computer's operator
  Given the caller has no session and no terminal login names anyone, with or without a terminal
  When they run `telec auth whoami`
  Then the command reports the operator's principal and names no person
  And the command exits successfully
```

#### UC-WHO3: An unidentified terminal is told how to log in

#### UC-WHO4: No session and no login is the computer's operator

#### UC-WHO-SESSION-CARRIED: Inside a session, whoami reports the identity the session carries

#### UC-WHO-SESSION-UNUSABLE: A session identity document that identifies nothing is reported, not replaced

#### UC-WHO6: Whoami answers while the daemon is not running

#### UC-WHO-CAPABILITY-SESSION: The capability answers a session caller with its principal and session

#### UC-WHO-CAPABILITY-PERSON: The capability answers a person with a principal named for them

#### UC-WHO-CAPABILITY-NOBODY: The capability attributes nothing it cannot attribute

#### UC-WHO-SESSION-COMPANY: Inside a session, whoami reports the session's company context

#### UC-WHO5: The conversational alias answers as whoami

#### UC-WHO-SCOPED-ROLE: A person's Role is the one that authorizes them where the command runs

### Cross-context references

- Inside a session the CLI reads the session record in `agent_runtime.sessions` that the identity document's session id names; the record, never the document's copied fields, supplies the principal (`feature/identity/session-identity-file`).
- The person and role printed at a terminal come from the `people` registry for the login the terminal presents, through the same resolution the identity context applies.
- In v2 this is the same capability spelled as a method on the identity service (`identity.who_am_i(principal)`) returning a typed `Principal` (or Anonymous).

## Known caveats

- The conversational alias is strict: it matches exactly the three tokens `who`, `am`, `i` (the third with optional trailing `?`). Punctuation or different ordering misses and falls through to the unknown-subcommand branch.
- A session whose record is closed or absent is reported as carrying no usable identity, not as a friendly "logged out" message. An open record the identity document names is admitted on that naming alone; resolving it never reads the machine configuration.

- The session path prints `Principal`, `Role`, and `Company`. The terminal path prints `Email`, `Role`, `TTY`, and `Session auth file`. The operator path prints `Principal` only. The outputs are intentionally different shapes because they answer different questions about Resolution.
- A terminal login naming an email no registered person holds is not the operator: whoami reports that no identity is established for the TTY. A session identity document that identifies no open session is reported as carrying no usable identity, never as the operator.
