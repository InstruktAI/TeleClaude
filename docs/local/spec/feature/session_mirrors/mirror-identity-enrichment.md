---
description: "A mirror is attributed at write time to the TeleClaude session whose transcript chain holds it, recording the session's principal, registered project, and launch facts. Identity fields come from the upstream session record, and no write replaces a recorded fact with an absent one."
visibility: 'public'
---

# Mirror Identity Enrichment — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md
- @docs/local/spec/domain/identity.md

## What it is

A mirror's identity comes from the upstream session record owned by the
agent_runtime bounded context, never from the transcript file. When the
session_mirrors service writes a mirror, it resolves the session record that
claims the transcript through the queries agent_runtime publishes for its session
records, and never reads those records' storage itself. It records what that
record establishes, in two places.

- **The session attribution.** Each TeleClaude session with a mirrored
  transcript holds one session attribution in the mirror store: its TeleClaude
  session id, the principal it ran under, the registered project it ran in, the
  subject the session recorded — the project, person, or company home it landed
  in, or none — with that subject's owner, its subfolder, the session that
  started it and that session's computer, whether an agent started it, the
  scheduled job it ran for, and when it started and closed. Every mirror of the
  session links to that attribution and records its position in the session's
  transcript chain. An attribution written before sessions recorded a subject
  receives the subject its session record carries, once.
- **The mirror itself.** `human_email`, `visibility`, `project_path` (the
  checkout the session ran in), `computer`, the launch command and the todo it
  worked, the worker classification, the title, and the origin channel with its
  platform identifiers are recorded on the mirror.

A session's transcripts rotate, and a handoff to another agent starts a new
transcript under the same session. The session record keeps the ordered chain of
earlier transcripts beside the current one, and every transcript in that chain is
attributed to the session, not only the current one.

The principal is the one the platform's session principal resolution yields for
the record (`local/projects/teleclaude/spec/identity-and-auth`); the mirror service never derives a
principal of its own. The registered project is the project the project catalog
registers at the session's project path; a path the catalog does not register
yields no project.

The mirror store is the durable history domain and the session record lives in an
operational store that may be pruned (`local/projects/teleclaude/policy/single-database`), so
attribution is recorded when the mirror is written and never looked up when it is
read. The reconciliation loop and the event fanout write every fact through the
same path. A write that finds no session record, or a record that lacks a value,
never replaces a value already recorded: the stored value stays. A value the
session record changes — the title while the session runs — is recorded by the
next write of the session's transcript. The session's close is recorded by the
reconciliation loop's next pass, whether or not the transcript changed after its
last write.

A transcript no session record claims carries no session attribution. It stays
mirrored and addressable by its agent-native id.

## Canonical fields

### Use cases

#### Session record lookup

```
Given a mirror event for session_id S (and possibly a transcript_path P)
When the session_mirrors service resolves session context
Then a single session record is looked up where session_id = S, or whose current transcript is P, or whose chain of earlier transcripts holds P
And ties prefer the record whose session_id matches S, then the most recently created record
And the returned context exposes
  session_id, computer, agent, project path, subfolder, transcript_path, the transcript's position in the chain,
  human_email, visibility, last_input_origin, adapter_metadata, system_role, the resolved principal,
  the initiating session and its computer, whether an agent initiated it, job, command, the todo it worked,
  title, the record's creation and close times, and the platform identifiers of its origin channel
And missing fields map to None or the empty string
```

#### Classification and title come from the session record

```
Given a session context is resolved
When the session_mirrors service generates a mirror
Then is_worker is true exactly when context.system_role is the worker role
And command and todo are the launch command and its argument recorded on the session record
And the mirror title is the session record's title
And no value among these is derived by reading the transcript's text

Given no session record exists for the transcript
When the session_mirrors service generates a mirror
Then is_worker, command, and todo keep the values already recorded on the mirror, and are false and null for a new mirror
And the title falls back to the first user message's stripped text, per `conversation-text-extraction`
```

#### Identity threading into mirror generation

```
Given a session context is resolved
When the session_mirrors service generates a mirror
Then human_email = context.human_email
And visibility = context.visibility OR "private"
And computer = context.computer OR the local computer name
And project_path = context's project path OR ""
And last_input_origin = context.last_input_origin
And these values are persisted on the resulting mirror
```

#### Channel identifier extraction for telegram

```
Given context.last_input_origin == "telegram"
And the adapter metadata exposes a telegram block
When channel identifiers are extracted
Then the result contains {"user_id": <str telegram user_id>} when user_id is present
And nothing else from the telegram block
And the result is merged into the mirror's metadata blob
```

#### Channel identifier extraction for discord

```
Given context.last_input_origin == "discord"
And the adapter metadata exposes a discord block with user_id and channel_id
When channel identifiers are extracted
Then the result may contain "user_id" (the discord user_id string)
And "channel_id" (the discord channel_id as string) when present
```

#### Channel identifier extraction for whatsapp

```
Given context.last_input_origin == "whatsapp"
And the adapter metadata exposes a whatsapp block with phone_number
When channel identifiers are extracted
Then the result contains {"phone_number": <phone_number>}
```

#### Unsupported origin or invalid payload

```
Given context.last_input_origin is None OR not in {telegram, discord, whatsapp}
OR adapter metadata is empty
When channel identifiers are extracted
Then the extractor returns an empty result

Given adapter metadata fails to parse
When the extractor handles the parse failure
Then it returns an empty result
```

#### Origin channel persistence in metadata

```
Given last_input_origin is non-empty at mirror generation time
When the mirror metadata is built
Then metadata.origin_channel = last_input_origin
And metadata.transcript_path = the transcript path
And metadata.agent = the agent name
And metadata is merged with any channel identifiers extracted above
And the final metadata is serialized deterministically (stable field ordering)

Given a mirror whose metadata records an origin channel and platform identifiers
When a later write supplies no origin channel or no identifiers
Then the recorded origin channel and identifiers stay in the metadata
And the transcript path and agent are replaced by the write's values
```

#### UC-MIE-1: Every transcript in a session's chain belongs to that session

```
Given a TeleClaude session whose conversation spans several transcripts, because its transcript rotated or the session was handed off to another agent
When those transcripts are mirrored
Then each of their mirrors is attributed to that one session
And each mirror states its place in the session's order of transcripts
And an agent reading any of those mirrors from history learns the TeleClaude session it belongs to
```

#### UC-MIE-2: A mirror records the authority its session ran under

```
Given a session a person started, and the orchestrators and workers that ran in that person's chain
When their transcripts are mirrored
Then each mirror's session attribution records that person as the principal the session ran under
And a session rooted in the platform itself records the platform's principal
And a session whose record resolves no principal records none, rather than one inferred from the transcript
```

#### UC-MIE-3: A mirror records the registered project its session ran in

```
Given a session that ran in a checkout the project catalog registers
When its transcript is mirrored
Then the mirror's session attribution records that registered project
And the mirror records the checkout path it ran in
And a session that ran in a path the catalog does not register records the path and no project
```

#### UC-MIE-4: A later write never erases a recorded fact

```
Given a mirror that records identity facts
When a later write of that mirror finds no session record, or a record that lacks one of those facts
Then every fact the write cannot supply keeps its recorded value
And a fact the write does supply replaces the recorded value
And the reconciliation loop and the event fanout record the same facts for the same session record
```

#### UC-MIE-5: The session's launch facts are recorded

```
Given a session started by another session, by an agent, or for a scheduled job, in a subfolder of its project
When its transcript is mirrored
Then the session attribution records which session started it and on which computer, whether an agent started it, the job, and the subfolder
And it records when the session started
And once the session has closed, the reconciliation loop's next pass records when it closed, even when its transcript did not change after its last write
```

#### UC-MIE-6: The attribution survives the session record

```
Given a mirror attributed to a session
When that session's record is later pruned from the operational store
Then an agent reading the mirror from history still learns the TeleClaude session, principal, project, and launch facts it recorded
```

#### UC-MIE-7: A transcript no session claims stays unattributed

```
Given a transcript that no session record names as its current transcript or holds in its chain
When it is mirrored
Then the mirror carries no session attribution, principal, or registered project
And it remains mirrored and addressable by its agent-native id
```

## Known caveats

- The session context lookup is read-only against the upstream session
  record. A mirror-level value the record changes, such as the title, is
  recorded only by a later write of the session's transcript; once a closed
  session's transcript stops changing, the values its last write recorded stand.
- A session without a record in the upstream store (cross-machine handoff,
  manual cleanup, etc.) means the event fanout returns without generating a
  mirror; the reconciliation loop still mirrors the transcript, unattributed.
- A transcript that more than one session record claims — a revived session
  continues the same transcript under a new TeleClaude session — is attributed
  to the most recently created of them.
- The session record keeps its chain as an ordered list of transcript paths. A
  transcript's position is its place in that order, with the current transcript
  last.
- The mirror's `metadata` blob is serialized with stable field ordering;
  the same set of fields always produces byte-identical metadata. Field
  ordering is not a difference signal.
- The discord adapter user_id is passed through as a raw string; the
  discord channel_id is coerced to string. The mixed treatment is a
  preserved quirk of the historical extractor.
- `visibility` arrives as a free-form string from the session record and
  the mirror store defaults it to `private`. The value is stored but grants
  nothing: history scoping does not read it.
