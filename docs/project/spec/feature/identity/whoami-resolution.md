---
description: "Report the caller's identity via `telec auth whoami`."
visibility: 'public'
---

# Whoami Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

`telec auth whoami` is the operator-facing question "who does the system think I am?". The CLI answers it in its own process from the identity context's shared caller resolution (`project/spec/identity-and-auth` §6) — the same resolution every caller-dependent command applies — and sends no request to the daemon. Inside a session — one whose TMPDIR holds a session identity document — it prints the Principal and Role the session's record resolves to, and never reads the terminal login; a document that is present but identifies no open session on this computer is reported as carrying no usable identity. Outside any session it prints the Email and Role of the person the terminal's login names, followed by the TTY and the login document's path. The Role is the one that authorizes the caller: a person's role from the people registry, or a system caller's system role as derived from its session record. The CLI accepts a conversational alias — `telec auth who am i` — that rewrites to `telec auth whoami`.

The identity context's whoami capability answers the same question for clients of the daemon's API. It answers from the identity the request carries, so its answer for a caller agrees with the CLI's.

Inside a session it also prints the session's company context, which is how a tool running in the session — in any language — reads it. The CLI resolves that context in its own process from the session record the identity document's session id names, together with the person's company memberships (`project/spec/feature/agent_runtime/company-scoped-session-context`); the document itself carries no company fact. The Principal line already tells human-directed work (`human:`) from system-principal work (`system:`), so the company context adds one line: the resolved company, `none` when the session has no company, or `ambiguous` with the eligible companies and how to select one. Outside a session there is no session company, and no Company line is printed.

## Canonical fields

### Use cases

#### UC-WHO1: A system session reports its principal and system role

```
Given an agent session whose record resolves to the principal `system:daemon` and whose derived system role is `worker`
When the operator runs `telec auth whoami`
Then it prints `Principal: system:daemon` and `Role: worker`, followed by the session's Company line (UC-WHO-SESSION-COMPANY)
```

#### UC-WHO2: A terminal reports the person its login names

```
Given a terminal outside any session — no session identity document — whose login document names `ada@example.com`
And the `people` registry holds `ada@example.com` with the `admin` Role
When the operator runs `telec auth whoami`
Then it prints `Email: ada@example.com` and `Role: admin`, then `TTY: <pts/N>` and `Session auth file: <path>`
```

#### UC-WHO3: An unidentified terminal is told how to log in

```
Given a terminal outside any session that the platform cannot identify — no login document on a host with more than one registered person, or a login naming no registered person
When the operator runs `telec auth whoami`
Then the CLI prints that no identity is established for the current TTY, with the instruction to log in, and exits with success
```

#### UC-WHO4: No terminal and no session is an error

```
Given an environment outside any session with no detectable TTY
When the operator runs `telec auth whoami`
Then the CLI prints `Error: no terminal session detected (TTY unavailable).` and exits with a failure status
```

#### UC-WHO-SESSION-CARRIED: Inside a session, whoami reports the identity the session carries

```
Given a process inside a session whose lineage roots at a person
And the pane it runs on carries a live login document for someone else
When the operator runs `telec auth whoami`
Then it prints the Principal and Role the session's record resolves to
And the terminal's login is not printed
```

#### UC-WHO-SESSION-UNUSABLE: A session identity document that identifies nothing is reported, not replaced

```
Given a process whose session identity document is present but malformed, carries no session id, or names a session with no open record on this computer
When the operator runs `telec auth whoami`
Then the CLI reports that the session carries no usable identity and exits with a failure status
And no terminal login is consulted or printed
```

#### UC-WHO6: Whoami answers while the daemon is not running

```
Given the daemon's local service is not reachable
And a process inside a session whose lineage roots at the registered person `ada@example.com`
When the operator runs `telec auth whoami`
Then it prints `Principal: human:ada@example.com` and the Role the `people` registry holds for her
And no request is sent to the daemon's local service
```

#### UC-WHO-CAPABILITY-SESSION: The capability answers a session caller with its principal and session

```
Given an agent in a session whose carried principal is `system:daemon` and whose system role is `orchestrator`
When a client of the daemon's API asks who that caller is
Then the answer carries the principal `system:daemon`, the role `orchestrator`, no email, and the id of the caller's session
And the role is the one `telec auth whoami` prints for that caller, also when the session inherited its principal
```

#### UC-WHO-CAPABILITY-PERSON: The capability answers a person with a principal named for them

```
Given a caller the platform resolves as the registered person `ada@example.com`, whose registered role is `member` — at a terminal, or through a session whose lineage roots at them
When a client of the daemon's API asks who that caller is
Then the answer carries the principal `human:ada@example.com`, the role `member`, and the email `ada@example.com`
And it carries a session id only when the caller is a session
```

#### UC-WHO-CAPABILITY-NOBODY: The capability attributes nothing it cannot attribute

```
Given a session caller that resolves to no person and carries no principal
When a client of the daemon's API asks who that caller is
Then the answer carries no principal, no role, and no email
```

#### UC-WHO-SESSION-COMPANY: Inside a session, whoami reports the session's company context

```gherkin
Scenario Outline: The Company line follows the session record and the person's memberships
  Given a process inside a session that <session>
  When the operator runs `telec auth whoami`
  Then after the Principal and Role lines it prints <company line>
  And the session identity document still carries no company field

  Examples:
    | session                                                                         | company line                                                         |
    | was created with the company `acme`                                             | `Company: acme`                                                      |
    | was started from a session operating under `acme`                               | `Company: acme`                                                      |
    | carries the lineage of a person whose only company is `acme`, with no selection | `Company: acme`                                                      |
    | carries the lineage of a person in `acme` and `beta`, with no selection         | `Company: ambiguous (acme, beta) — select one with --company <slug>` |
    | has no company and no person with a company membership                          | `Company: none`                                                      |
```

#### UC-WHO5: The conversational alias answers as whoami

```
Given an operator in any context where `telec auth whoami` answers
When the operator runs `telec auth who am i`
Then the output and exit status are those `telec auth whoami` produces in that context
```

<!-- planned:authorize-person-roles-at-scope -->
#### UC-WHO-SCOPED-ROLE: A person's Role is the one that authorizes them where the command runs

```
Given a terminal whose login names a person holding no platform role and the admin role in one company
When the operator runs `telec auth whoami` in a checkout of a project that company owns
Then it prints `Role: admin`
And run in a checkout of a project owned by another company, or outside any registered project, it prints `Role: customer`
```
<!-- /planned:authorize-person-roles-at-scope -->

### Cross-context references

- Inside a session the CLI reads the session record in `agent_runtime.sessions` that the identity document's session id names; the record, never the document's copied fields, supplies the principal (`feature/identity/session-identity-file`).
- The person and role printed at a terminal come from the `people` registry for the login the terminal presents, through the same resolution the identity context applies.
- In v2 this is the same capability spelled as a method on the identity service (`identity.who_am_i(principal)`) returning a typed `Principal` (or Anonymous).

## Known caveats

- The conversational alias is strict: it matches exactly the three tokens `who`, `am`, `i` (the third with optional trailing `?`). Punctuation or different ordering misses and falls through to the unknown-subcommand branch.
- A session whose record is closed or absent is reported as carrying no usable identity, not as a friendly "logged out" message. An open record the identity document names is admitted on that naming alone; resolving it never reads the machine configuration.

- The session path prints `Principal`, `Role`, and `Company`. The terminal path prints `Email`, `Role`, `TTY`, and `Session auth file`. The two outputs are intentionally different shapes because they answer different questions about Resolution.
