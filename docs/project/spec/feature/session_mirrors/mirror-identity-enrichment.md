---
id: 'project/spec/feature/session_mirrors/mirror-identity-enrichment'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Identity fields on the mirror (human_email, visibility, project, origin channel, platform user/channel ids) are sourced from the upstream session record at extraction time. Adapter metadata for telegram / discord / whatsapp is unpacked into the mirror''s metadata blob.'
---

# Mirror Identity Enrichment — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/identity.md

## What it is

A mirror's identity fields (`human_email`, `visibility`, `project`,
`computer`) and its `metadata` blob (origin channel plus platform-specific
identifiers) come from the upstream session record owned by the
agent_runtime bounded context, not from the transcript file. At session-end
fanout, the session_mirrors service looks up the upstream session by
session_id (or by transcript path), picks up the identity fields, and
threads them into mirror generation. Channel identifiers for telegram,
discord, and whatsapp adapters are pulled out of the upstream session's
adapter metadata and merged into the mirror's metadata blob.

This means a mirror carries a snapshot of identity at the time of
extraction. If the upstream session record is later pruned, the mirror
still has the identity values it captured.

## Canonical fields

### Use cases

#### Session record lookup

```
Given a mirror event for session_id S (and possibly a transcript_path P)
When the session_mirrors service resolves session context
Then a single session record is looked up where session_id = S OR transcript_path = P
And ties prefer the record whose session_id matches S
And the returned context exposes
  session_id, computer, agent, project, transcript_path, human_email, visibility,
  last_input_origin, adapter_metadata
And missing fields map to None or the empty string
```

#### Identity threading into mirror generation

```
Given a session context is resolved
When the session_mirrors service generates a mirror
Then human_email = context.human_email
And visibility = context.visibility OR "private"
And computer = context.computer OR the local computer name
And project = context.project OR ""
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
```

## Known caveats

- The session context lookup is read-only against the upstream session
  record. Updates to the upstream record made AFTER the mirror is written
  do not flow back into the mirror — extraction-time snapshot only.
- A session without a record in the upstream store (cross-machine handoff,
  manual cleanup, etc.) means the service returns without generating a
  mirror.
- The mirror's `metadata` blob is serialized with stable field ordering;
  the same set of fields always produces byte-identical metadata. Field
  ordering is not a difference signal.
- The discord adapter user_id is passed through as a raw string; the
  discord channel_id is coerced to string. The mixed treatment is a
  preserved quirk of the historical extractor.
- `visibility` arrives as a free-form string from the session record but
  the mirror store defaults to `private` and the role filter only honors
  `shared` as a special value. Other strings are stored but have no effect
  on role filtering.
