---
description: 'Fetch one session mirror by its full session identifier and render its semantic conversation. A TeleClaude id resolves through the session registry; a shortened identifier is refused. Used by `telec history show`, locally and on the peer that answers a remote show.'
visibility: 'public'
---

# Mirror Detail Retrieval — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md

## What it is

Operators inspect a specific past session by addressing its mirror with a
full session identifier. The lookup matches that identifier exactly; a
shortened value is refused rather than resolved. Optional
computer scoping narrows the lookup when callers supply a host name.

A local `telec history show` is answered in the CLI process by the
session_mirrors service's history detail capability, for the caller the
platform's shared caller resolution yields (`projects/teleclaude/spec/identity-and-auth` §6)
and after that caller clears the verb
(`projects/teleclaude/spec/feature/identity/command-clearance`, Local read clearance). That
capability resolves the identifier — a TeleClaude id through the session
registry, a native id directly — applies the caller's history scope, and returns
the same structured answer `telec history show --json` prints: both identifiers
and which of them was supplied, which source answered, title, project, computer,
timestamps, message count, coverage, whether the session is running, and the
conversation body. The CLI reads mirrors only through that capability; it renders
the answer as a human-readable header — title, project, computer, start
timestamp, both identifiers and which source answered — followed by the
conversation body in full.

## Canonical fields

### Use cases

#### UC-MDR-4: Exact identifier matching

```
Given a session_id parameter and no source_identity
When the session_mirrors service executes the lookup
Then the lookup matches mirrors whose session_id equals <value>
And a value that is not a full identifier is refused rather than matched
And at most one mirror is returned, since the identifier is unique
```

#### Source-identity lookup short-circuits

```
Given a source_identity parameter (the transcript-derived identity key)
When the session_mirrors service executes the lookup
Then the lookup matches source_identity exactly
And the session_id parameter is not consulted
```

#### Optional computer filter

```
Given session_id and an explicit computer name
When the session_mirrors service executes the lookup
Then the lookup additionally requires the mirror's computer to equal <value>
And no fuzzy matching is performed on the computer name
```

#### CLI display rendering

```
Given an operator runs `telec history show <session-id>` and a mirror is found
When the local mirror is rendered to the terminal
Then a header is printed combining: title (if any), "Project: <project>",
  "Computer: <computer>", "Started: <timestamp_start>"
And the header names the session's TeleClaude id and agent-native id, which of them the caller supplied, and whether the mirror or the on-disk transcript answered
And a blank line separates header from body
And the body is the mirror's conversation_text in full, bounded by the caller's own tooling rather than by a character-count flag
And the body is right-stripped before printing
```

#### Missing-store tolerance

```
Given the mirror store has never been initialized on this host
When the session_mirrors service executes the lookup
Then the missing-store condition is swallowed
And the function reports "no mirror" without raising
```

#### UC-MDR-1: CLI accepts a TeleClaude session id

```
Given an operator runs `telec history show <session-id>` with a TeleClaude session id
And no mirror matches that id directly
And the session record for that id carries a native agent session id
When the history detail capability resolves the lookup
Then it repeats only the mirror lookup under the native agent session id
And the on-disk transcript discovery is never repeated under a resolved id, because it applies no history scope
And the session's mirror is rendered, whether the session is still running or already closed
And `--raw` for a resolved id streams the transcript recorded on that mirror rather than a rediscovered file

Given the caller's history scope excludes that session's mirror from the detail lookup
Then the resolved native id opens neither the mirror nor the transcript
And the CLI reports "No transcript found for session '<session-id>'" and exits non-zero

Given no session record carries the supplied id
Then the CLI reports "No transcript found for session '<session-id>'" and exits non-zero
```

#### UC-MDR-2: An id lookup takes a full UUID

```
Given an operator supplies a value shorter than a full UUID
When the detail lookup resolves it
Then the value is refused, naming the full-identifier requirement
And no mirror is returned by prefix or recency
```

#### UC-MDR-3: The rendered view states what it is and what resolved it

```
Given a mirror is rendered to the terminal
Then the header names the session's TeleClaude id and agent-native id, and which of them the caller supplied
And the header names whether the mirror or the on-disk transcript answered
And the rendered body is the semantic conversation — tool calls and tool output are not present in it
```

#### UC-MDR-5: Retrieval states the conversation coverage it can establish

```gherkin
Given an agent retrieves a registered session whose durable conversation lags the available live conversation
When the agent uses the retrieved conversation to ground a review
Then the response states the latest conversation coverage it can establish
And content beyond that coverage is not represented as absent from the session
```

#### UC-MDR-6: The platform's verification, not the requesting process, decides a detail request

```
Given an agent process presents a session identity document naming a session the platform does not know
And the pane it runs on carries an admin's terminal login
When it runs `telec history show <session-id>` for a stored conversation
Then the request is refused
And no conversation, header, or transcript is printed
```

#### UC-MDR-7: A TeleClaude id reaches its session's conversation through the recorded attribution

```
Given an operator runs `telec history show <session-id>` with the TeleClaude id of a session that has attributed mirrors
When the history detail capability resolves the lookup within the caller's history scope
Then it renders the mirror of the session's latest transcript in its chain
And it does so whether or not the session record still exists
And the header names both the TeleClaude id and that transcript's agent-native id
```

## Known caveats

- The history detail capability applies the same history scope as every
  other mirror surface (see `feature/session_mirrors/role-scoped-history-access`).
- A shortened identifier is refused rather than resolved, so a lookup never
  returns a session the caller did not name.
- The CLI render drops `timestamp_end` and `message_count` from the
  header. The detail payload includes them; the terminal does not.
- The lookup matches a full identifier and nothing shorter, so neither a
  prefix nor a substring of a stored id resolves. The transcript fallback
  the CLI keeps for a mirror that does not yet exist is the one place a
  looser scan still runs, and it is not reachable through a resolved id.
