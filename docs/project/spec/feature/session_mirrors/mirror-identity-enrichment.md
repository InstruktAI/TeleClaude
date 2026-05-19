---
id: 'project/spec/feature/session_mirrors/mirror-identity-enrichment'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Identity fields on the mirror (human_email, visibility, project, origin channel, platform user/channel ids) are sourced from the upstream session row at extraction time. Adapter metadata for telegram / discord / whatsapp is unpacked into the mirror''s metadata blob.'
---

# Mirror Identity Enrichment — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/identity.md

## What it is

A mirror's identity columns (`human_email`, `visibility`, `project`,
`computer`) and the contents of its `metadata` JSON blob (origin channel
plus platform-specific identifiers) come from the main TeleClaude database's
`sessions` row, not from the transcript file. At session-end fanout, the
default processor calls `get_session_context(session_id, transcript_path)`
against the read-only main DB engine, picks up the upstream identity
fields, and threads them into `generate_mirror`. Channel identifiers for
telegram, discord, and whatsapp adapters are pulled out of the session row's
`adapter_metadata` JSON column and merged into the mirror's metadata blob.

This means a mirror written in v1 carries a snapshot of identity at the
time of extraction. If the upstream session record is later pruned, the
mirror still has the identity values it captured.

## Canonical fields

### Behavioral contract

#### Session row lookup

```
Given a MirrorEvent with session_id S (and possibly transcript_path P)
When process_mirror_event calls get_session_context(session_id=S, transcript_path=P)
Then a single row is selected from the main DB's `sessions` table where
  session_id = :session_id OR native_log_file = :transcript_path
And ties prefer the row whose session_id matches :order_session_id (the explicit S)
And the returned SessionMirrorContext exposes
  session_id, computer, agent, project, transcript_path, human_email, visibility,
  last_input_origin, adapter_metadata_json
And missing columns or NULLs map to None / empty string
```

#### Identity threading into generate_mirror

```
Given a SessionMirrorContext is resolved
When process_mirror_event invokes generate_mirror
Then human_email = context.human_email
And visibility = context.visibility or "private"
And computer = context.computer or config.computer.name
And project = context.project or ""
And last_input_origin = context.last_input_origin
And these values are persisted onto the resulting mirror row
```

#### Channel identifier extraction for telegram

```
Given context.last_input_origin == "telegram"
And context.adapter_metadata_json is a valid SessionAdapterMetadata payload with a telegram block
When _extract_channel_identifiers runs
Then the returned dict contains {"user_id": str(telegram.user_id)} when user_id is present
And nothing else from the telegram block
And the dict is merged into the mirror's metadata blob (alongside transcript_path and agent)
```

#### Channel identifier extraction for discord

```
Given context.last_input_origin == "discord"
And the adapter payload exposes a discord block with user_id and channel_id
When _extract_channel_identifiers runs
Then the returned dict may contain "user_id" (the discord user_id string)
And "channel_id" (str(channel_id)) when present
```

#### Channel identifier extraction for whatsapp

```
Given context.last_input_origin == "whatsapp"
And the adapter payload exposes a whatsapp block with phone_number
When _extract_channel_identifiers runs
Then the returned dict contains {"phone_number": phone_number}
```

#### Unsupported origin or invalid payload

```
Given context.last_input_origin is None OR not in {"telegram", "discord", "whatsapp"}
OR adapter_metadata_json is empty
When _extract_channel_identifiers runs
Then it returns {}

Given adapter_metadata_json fails to parse via SessionAdapterMetadata.from_json
When _extract_channel_identifiers catches ValueError / KeyError / TypeError
Then it returns {}
```

#### Origin channel persistence in metadata

```
Given last_input_origin is non-empty when generate_mirror_sync builds metadata
When the mirror is upserted
Then metadata.origin_channel = last_input_origin
And metadata.transcript_path = transcript_path
And metadata.agent = agent_name.value
And metadata is merged with any channel_identifiers dict resolved above
And the final metadata is JSON-serialized with sort_keys for stable storage
```

### V1 implementation pointers

- `teleclaude/mirrors/processors.py:process_mirror_event` — orchestrates context resolution and generator dispatch.
- `teleclaude/mirrors/processors.py:_extract_channel_identifiers` — per-origin identifier extraction.
- `teleclaude/mirrors/processors.py:_ADAPTER_ORIGINS` — `{"telegram", "discord", "whatsapp"}`.
- `teleclaude/mirrors/store.py:get_session_context` — cross-DB lookup against the main `sessions` table.
- `teleclaude/mirrors/store.py:SessionMirrorContext` — dataclass returned by the lookup.
- `teleclaude/mirrors/generator.py:generate_mirror_sync` — metadata composition and `MirrorRecord` build.
- `teleclaude/core/models/_adapter.py:SessionAdapterMetadata` — parser used for adapter JSON.

## Known caveats

- The session context lookup is against the read-only engine on
  `MAIN_DB_PATH`. Updates to the session row made AFTER the mirror is
  written do not flow back into the mirror — extraction-time snapshot only.
- A session without a row in the main DB (cross-machine handoff, manual
  cleanup, etc.) means the processor returns without invoking the generator
  and no mirror is written.
- The `metadata` blob is JSON-serialized with `sort_keys=True`; the same
  set of fields always produces byte-identical metadata. Order changes are
  not a difference signal.
- The `discord.user_id` field is passed through as the raw string; the
  `discord.channel_id` is coerced via `str(...)`. The mixed treatment is a
  v1 quirk preserved as-is.
- `visibility` arrives as a free-form string from the session row but the
  mirror table defaults to `'private'` and the `_apply_role_filter`
  consumer only honors `'shared'` as a special value. Other strings are
  stored but have no effect on role filtering.
