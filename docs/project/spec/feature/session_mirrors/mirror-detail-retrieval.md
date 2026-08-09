---
description: "Fetch one session mirror by exact or prefix session identifier and render its conversation text. Used by `telec history show` and by the session_mirrors service's detail capability."
visibility: 'public'
---

# Mirror Detail Retrieval — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Operators inspect a specific past session by addressing its mirror with a
session identifier. The lookup accepts an exact match or a prefix of the
session id, with the exact match preferred when both could match. Optional
computer scoping narrows the lookup when callers supply a host name. The CLI
path renders a human-readable header (title, project, computer, start
timestamp) followed by the conversation body trimmed by an optional tail
character count. The detail capability of the session_mirrors service
returns a structured payload with session_id, identity, title, timestamps,
conversation_text, and message_count.

## Canonical fields

### Use cases

#### Exact-or-prefix matching

```
Given a session_id parameter and no source_identity
When the session_mirrors service executes the lookup
Then the lookup matches mirrors whose session_id equals <value> OR starts with <value>
And exact matches are preferred over prefix matches
And ties break by shortest session_id then by updated_at descending
And exactly one mirror is returned
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
And a blank line separates header from body
And the body is the mirror's conversation_text, optionally tail-trimmed by --tail
And the body is right-stripped before printing
```

#### Detail capability wire format

```
Given a caller invokes the detail capability for a session_id
When a mirror matches the lookup
Then the response carries
  session_id, computer, agent, project, title, conversation_text,
  message_count, timestamp_start, timestamp_end
And no role-based access filtering is applied at this capability

Given no mirror matches the lookup
Then the capability reports "Mirror not found"
```

#### Missing-store tolerance

```
Given the mirror store has never been initialized on this host
When the session_mirrors service executes the lookup
Then the missing-store condition is swallowed
And the function reports "no mirror" without raising
```

<!-- planned:telec-history-session-identity -->

#### UC-MDR-1: CLI accepts a TeleClaude session id

```
Given an operator runs `telec history show <session-id>` with a TeleClaude session id
And no mirror and no transcript match that id directly
And the session record for that id carries a native agent session id
When the CLI resolves the lookup
Then the CLI repeats the mirror lookup and the on-disk transcript discovery under the native agent session id
And the session's mirror is rendered, whether the session is still running or already closed
And `--raw` streams that session's transcript by the same resolution

Given the caller's role band excludes that session's mirror from the detail lookup
Then the resolved native id opens neither the mirror nor the transcript
And the CLI reports "No transcript found for session '<session-id>'" and exits non-zero

Given no session record carries the supplied id
Then the CLI reports "No transcript found for session '<session-id>'" and exits non-zero
```

<!-- /planned:telec-history-session-identity -->

## Known caveats

- The detail capability does not apply role filtering. Callers that need
  visibility scoping must reach mirrors through the CLI or apply policy at
  the service boundary themselves.
- Prefix matching is inclusive of the full session id, so a short prefix
  can match many sessions; only the first row by the ordering rules is
  returned.
- The CLI render drops `timestamp_end` and `message_count` from the
  header. The detail payload includes them; the terminal does not.
- When session_id is a substring (not a prefix) of a mirror's stored id,
  the detail lookup does NOT match — the match is by prefix, not by
  substring. The CLI's transcript fallback uses a separate substring scan
  over native transcripts but the mirror store itself is prefix-only.
