---
description: Human input reflected to Discord carries source-supplied presentation
  or the person's stored Discord avatar without late lookup or fallback.
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

#### UC-RHP1: A person can recognize their message in the Discord admin lane

```gherkin
Scenario Outline: Reflect a person's message with the available presentation
  Given a person's input is being reflected
  And the source presentation is <source presentation>
  And the person's resolved identity has <stored avatar>
  When the input appears in the Discord admin lane
  Then the message uses the person's resolved display name and <expected avatar>

  Examples:
    | source presentation | stored avatar          | expected avatar       |
    | none                | a Discord avatar       | the stored avatar     |
    | an avatar           | a Discord avatar       | the source avatar     |
    | none                | no avatar              | no avatar             |
```

#### UC-RHP2: Source presentation takes precedence

#### UC-RHP3: Missing avatar preserves the no-avatar path

### Cross-context references

- **identity** owns the resolved human presentation and source-versus-stored precedence.
- **config** owns the per-person Discord credential record that stores the captured avatar URL.
- **integration** translates the selected presentation into Discord webhook delivery.

## Known caveats

- The stored avatar changes only when the Discord credential binding is written again or a person
  edits their own per-person overlay. Discord avatar changes are not refreshed automatically.
