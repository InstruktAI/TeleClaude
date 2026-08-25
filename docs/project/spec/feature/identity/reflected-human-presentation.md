---
description: Human input reflected to Discord carries source-supplied presentation or the person's stored Discord avatar without late lookup or fallback.
delivered_by:
  - discord-avatar-reflection
---

# Reflected Human Presentation — Spec

## What it is

The identity context supplies the presentation used when human input is reflected into the
Discord admin lane. Presentation already supplied by the input source takes precedence; when
none was supplied, the person's stored Discord avatar is used. A person without either
presentation remains on the existing no-avatar path, with no late Discord lookup and no
third-party fallback.

## Canonical fields

### Use cases

#### UC-RHP1: Stored Discord avatar presents non-Discord-origin human input

```gherkin
Given a configured human has a Discord avatar stored with their resolved identity
And a reflection request for that human supplies no source avatar
When the human's input is reflected into the Discord admin lane
Then the reflected message is presented under the human's resolved display name
And it uses the stored Discord avatar
```

#### UC-RHP2: Source presentation takes precedence

```gherkin
Given a reflection request already supplies the human's source avatar
And the resolved identity also carries a stored Discord avatar
When the human's input is reflected into the Discord admin lane
Then the reflected message uses the source-supplied avatar
```

#### UC-RHP3: Missing avatar preserves the no-avatar path

```gherkin
Given a configured human has no stored Discord avatar
And a reflection request supplies no source avatar
When the human's input is reflected into the Discord admin lane
Then the message is reflected without an avatar
And no Discord lookup or third-party avatar fallback is attempted
```

### Cross-context references

- **identity** owns the resolved human presentation and source-versus-stored precedence.
- **config** owns the per-person Discord credential record that stores the captured avatar URL.
- **integration** translates the selected presentation into Discord webhook delivery.

## Known caveats

- The stored avatar changes only when the Discord credential binding is written again or a person
  edits their own per-person overlay. Discord avatar changes are not refreshed automatically.
